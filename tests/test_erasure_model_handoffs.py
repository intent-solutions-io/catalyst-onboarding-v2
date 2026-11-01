"""9kg.73: provider cleanup follows possible disclosure, not merely queued model work."""

import pytest
from django.db.models.functions import Now

from applications.models import SubmissionVersion
from assessments.models import AssessmentInvocation, AssessmentRun
from correspondence.models import InboundMessage, ReplyInterpretation
from erasure import catalog
from provisioning import closure
from tests.support import manage_as_owner
from tests.test_agreements import grant
from tests.test_assessment import a, assessed, ev, p2, queued, tls, valid  # noqa: F401
from tests.test_erasure import AUTHORITY, REASON, decided, erase, subject  # noqa: F401
from tests.test_erasure_replay import place_hold, registry_classes
from tests.test_outbound import run_worker, staff


def handoffs(committed, app, replay):
    if not replay:
        return erase(committed, app.public_ref).handoffs
    place_hold(committed)
    conn = committed.connect("retention")
    result = conn.execute(
        "SELECT public.catalyst_erase_replay(%s, %s, %s, %s)",
        [app.public_ref, AUTHORITY, REASON, list(registry_classes())],
    ).fetchone()[0]
    conn.commit()
    return result["handoffs"]


@pytest.mark.parametrize("replay", [False, True], ids=["erase", "replay"])
@pytest.mark.parametrize("called", [False, True], ids=["refused", "provider-called"])
def test_9kg_73_a_suspended_assessment_owes_no_provider_handoff_but_a_real_call_does(
    a, monkeypatch, settings, decided, replay, called
):
    if called:
        app, run, seen = assessed(a, monkeypatch, valid())
        assert run.status == "succeeded" and seen["calls"] == 1
        assert AssessmentInvocation.objects.filter(run=run).exists()
    else:
        app, run, seen = queued(a, monkeypatch, settings, valid())
        settings.CATALYST_ASSESSMENT_MODEL = "none"
        run_worker()
        run.refresh_from_db()
        assert run.status == "refused" and seen["calls"] == 0
        assert not AssessmentInvocation.objects.filter(run=run).exists()
    closer = grant(a, staff(a, "model-erasure-closer"), "close_application")
    closure.close_application(app.pk, closer, "closed", "Synthetic erasure regression")
    assert ("model_provider" in handoffs(a.committed, app, replay)) is called


@pytest.mark.parametrize("replay", [False, True], ids=["erase", "replay"])
@pytest.mark.parametrize(
    "reserved", [0, 2], ids=["precall-refusal", "possible-disclosure"]
)
def test_9kg_73_reply_only_model_reservations_keep_the_provider_handoff(
    privileged_reset, decided, replay, reserved
):
    app = subject()
    ReplyInterpretation.objects.create(
        application=app,
        message=InboundMessage.objects.get(application=app),
        attempt=1,
        text_sha256="a" * 64,
        status="unavailable",
        reserved_requests=reserved,
        finished_at=Now(),
    )
    assert ("model_provider" in handoffs(privileged_reset, app, replay)) is bool(
        reserved
    )


def reserved_run(app, status="abandoned"):
    run = AssessmentRun.objects.create(
        application=app,
        adopted_version=SubmissionVersion.objects.get(application=app),
        trigger="synthetic",
        snapshot={},
        snapshot_sha256="a" * 64,
        prompt_pack="synthetic",
        prompt_pack_sha256="b" * 64,
        rubric_version=1,
        schema_version="3",
        status="abandoned",
        finished_at=Now(),
    )
    AssessmentInvocation.objects.create(
        run=run,
        application=app,
        snapshot_sha256=run.snapshot_sha256,
        attempt=1,
        reserved_requests=2,
        reserved_tokens=0,
        status=status,
    )
    return run


@pytest.mark.parametrize("status", ["started", "abandoned"])
def test_9kg_73_an_uncertain_reserved_call_still_owes_provider_cleanup(
    privileged_reset, decided, status
):
    app = subject()
    reserved_run(app, status)
    assert "model_provider" in handoffs(privileged_reset, app, False)


def test_9kg_73_both_functions_reverse_and_reapply_without_changing_rows_or_grants(
    privileged_reset, decided
):
    app = subject()
    run = reserved_run(app)
    owner = privileged_reset.connect("owner", autocommit=True)
    query = (
        "SELECT p.proname, pg_get_functiondef(p.oid), p.proowner, p.proacl::text"
        " FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace"
        " WHERE n.nspname='public' AND p.proname IN ('catalyst_erase', 'catalyst_erase_replay')"
        " ORDER BY p.proname"
    )
    installed = owner.execute(query).fetchall()
    assert len(installed) == 2
    assert all(catalog.MODEL_PROVIDER_HANDOFF in row[1] for row in installed)

    def rows():
        return (
            owner.execute(
                "SELECT to_jsonb(r) FROM assessments_assessmentrun r WHERE id=%s",
                [run.pk],
            ).fetchall(),
            owner.execute(
                "SELECT to_jsonb(i) FROM assessments_assessmentinvocation i WHERE run_id=%s",
                [run.pk],
            ).fetchall(),
        )

    before = rows()
    try:
        manage_as_owner("migrate", "erasure", "0007", "--verbosity", "0")
        reversed_functions = owner.execute(query).fetchall()
        assert all(
            catalog.MODEL_PROVIDER_HANDOFF not in row[1] for row in reversed_functions
        )
        assert [row[2:] for row in reversed_functions] == [row[2:] for row in installed]
        assert rows() == before
    finally:
        manage_as_owner("migrate", "erasure", "0008", "--verbosity", "0")
    assert owner.execute(query).fetchall() == installed
    assert rows() == before
