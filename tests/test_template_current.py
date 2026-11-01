"""Current template replacement preserves approval evidence and legacy envelope continuation."""

import threading
import time

import pytest
from django.db import IntegrityError, ProgrammingError, connection, transaction
from django.test import Client
from django.urls import reverse

from agreements import handlers, services
from agreements.models import (
    AgreementInstance,
    AgreementTemplateVersion,
    EnvelopeAttempt,
)
from correspondence.models import OutboundMessage
from firstgen import review, signing_cadence
from tests.support import manage_as_owner
from tests.test_legacy_envelopes import (  # noqa: F401 (fixture chain and helpers)
    adopt,
    app,
    envelopes,
    legacy,
    provider_envelope,
    read_once,
    source_record,
    tls,
    v1,
)
from workflow.models import AutomationPause, PendingAction


def draft(env, number):
    old = env.versions["nda"]
    return AgreementTemplateVersion.objects.create(
        agreement_type=old.agreement_type,
        version=number,
        provider_template_ref=f"template_nda_{number}",
        provider_template_number=100 + number,
        recipient_slots=old.recipient_slots,
        pdf_sha256=old.pdf_sha256,
    )


def approve(env, version):
    return services.approve_template_version(
        version.pk, env.user, services.template_digest(version)
    )


def test_template_replacement_is_current_and_preserves_retired_approval(envelopes):
    old = envelopes.versions["nda"]
    evidence = (old.approved_by, old.approved_at, services.template_digest(old))
    second = draft(envelopes, 3)
    with pytest.raises(services.Refused, match="template_changed_since_shown"):
        services.approve_template_version(second.pk, envelopes.user, "stale")
    assert handlers.approved_version("nda").pk == old.pk
    current, changed = approve(envelopes, second)
    assert changed and handlers.approved_version("nda").pk == current.pk
    old.refresh_from_db()
    assert old.status == "retired"
    assert (old.approved_by, old.approved_at, services.template_digest(old)) == evidence
    assert not approve(envelopes, current)[1]
    with pytest.raises(services.Refused, match="template_version_retired"):
        approve(envelopes, old)
    with pytest.raises(services.Refused, match="template_version_not_newer"):
        approve(envelopes, draft(envelopes, 2))
    client = Client()
    client.force_login(envelopes.user)
    page = client.get(reverse("agreements_staff:templates"))
    assert page.status_code == 200
    rows = [
        r for r in page.content.decode().split("<tr>") if r.startswith("<td>nda</td>")
    ]
    assert ["yes: new agreements" in r for r in rows] == [True, False, False]
    assert "retired" in rows[-1] and "<form" not in rows[-1]


def test_template_database_rejects_two_current_versions_and_retired_mutation(envelopes):
    old = envelopes.versions["nda"]
    new = draft(envelopes, 2)
    with (
        pytest.raises(IntegrityError, match="agreement_template_one_current"),
        transaction.atomic(),
    ):
        AgreementTemplateVersion.objects.filter(pk=new.pk).update(
            status="approved",
            approved_by="synthetic duplicate",
            approved_at=old.approved_at,
        )
    approve(envelopes, new)
    owner = envelopes.committed.connect("owner", autocommit=True)
    from psycopg.errors import InsufficientPrivilege

    for version, fields in (
        (old, "status = 'approved'"),
        (old, "pdf_sha256 = 'forged'"),
        (new, "status = 'retired', approved_by = 'changed actor'"),
    ):
        with pytest.raises(InsufficientPrivilege):
            owner.execute(
                f"UPDATE agreements_agreementtemplateversion SET {fields} WHERE id = %s",
                [version.pk],
            )
    # An owner-written legacy identity is required for any new row using a retired template. Ordinary new issuance
    # and a foreign application's imported external key are both refused even through direct application-role SQL.
    application = app("CAT-ND00-0007")
    for external_key in (
        "ag_new_retired",
        source_record(app("CAT-SP00-0008")).data["external_ref"],
    ):
        with (
            pytest.raises(ProgrammingError, match="template version"),
            transaction.atomic(),
        ):
            AgreementInstance.objects.create(
                application=application,
                agreement_type=old.agreement_type,
                template_version=old,
                external_key=external_key,
            )
    assert not AgreementInstance.objects.exists()


def test_template_concurrent_approvals_leave_only_the_newest_current(envelopes):
    versions = [draft(envelopes, n) for n in (2, 3)]
    barrier, outcomes = threading.Barrier(2), []

    def attempt(version):
        barrier.wait(10)
        try:
            approve(envelopes, version)
            outcomes.append("approved")
        except services.Refused as exc:
            outcomes.append(str(exc))

    threads = [envelopes.committed.thread(attempt, v) for v in versions]
    for thread in threads:
        thread.join(30)
        assert not thread.is_alive()
    assert sorted(outcomes) in (
        ["approved", "approved"],
        ["approved", "template_version_not_newer"],
    )
    assert list(
        AgreementTemplateVersion.objects.filter(
            agreement_type=versions[0].agreement_type, status="approved"
        ).values_list("version", flat=True)
    ) == [3]


@pytest.mark.parametrize("adopt_before_retirement", [False, True])
def test_retired_template_keeps_legacy_adoption_timers_and_native_verification(
    envelopes, settings, adopt_before_retirement
):
    settings.CATALYST_SIGNING_REMINDER_MAX = 1
    settings.CATALYST_SIGNING_REMINDER_BUSINESS_DAYS = 5
    settings.CATALYST_LAPSE_AFTER_BUSINESS_DAYS = 10
    application = app("CAT-ND00-0007")
    original = envelopes.versions["nda"]
    envelope = provider_envelope(envelopes, application)
    existing = adopt(envelopes, application) if adopt_before_retirement else None
    approve(envelopes, draft(envelopes, 2))
    instance = adopt(envelopes, application)
    assert (
        instance.template_version_id == original.pk
        and instance.envelope_id == envelope["id"]
    )
    if existing:
        assert instance.pk == existing.pk
    receipt = signing_cadence.prepare(
        application.pk,
        instance.pk,
        envelopes.user,
        expected_digest=review.review_state(application)["digest"],
        source_stopped=True,
        timers_reviewed=True,
        note="Reviewed original envelope and timers after template replacement",
    )
    assert PendingAction.objects.get(pk=receipt.data["action"]).kind == "remind_signing"
    assert AutomationPause.objects.filter(subject_id=application.public_ref).exists()
    envelopes.fake.sign(envelope["id"], 0)
    envelopes.fake.sign(envelope["id"], 1)
    read_once()
    instance.refresh_from_db()
    assert (
        instance.signing_status == "signing_complete_verified"
        and instance.custody_status == "pending"
    )
    assert not EnvelopeAttempt.objects.exists() and not OutboundMessage.objects.exists()
    assert not any(r["method"] == "POST" for r in envelopes.fake.requests)


def test_template_migration_preserves_multiple_approvals_and_reverses_exactly(
    envelopes,
):
    owner = envelopes.committed.connect("owner", autocommit=True)
    query = "SELECT pg_get_functiondef(%s::regprocedure)"
    names = [
        "public.catalyst_agreement_template_frozen()",
        "public.catalyst_agreement_instance_insert()",
    ]
    current_definitions = [owner.execute(query, [name]).fetchone()[0] for name in names]
    manage_as_owner("migrate", "agreements", "0013", "--verbosity", "0")
    try:
        old_definitions = [owner.execute(query, [name]).fetchone()[0] for name in names]
        second = draft(envelopes, 2)
        first = envelopes.versions["nda"]
        AgreementTemplateVersion.objects.filter(pk=second.pk).update(
            status="approved",
            approved_by="synthetic historical approval",
            approved_at=first.approved_at,
        )
        evidence = list(
            AgreementTemplateVersion.objects.order_by("pk").values_list(
                "pk", "approved_by", "approved_at", "pdf_sha256"
            )
        )
        manage_as_owner("migrate", "--verbosity", "0")
        assert handlers.approved_version("nda").pk == second.pk
        first.refresh_from_db()
        assert first.status == "retired"
        assert (
            list(
                AgreementTemplateVersion.objects.order_by("pk").values_list(
                    "pk", "approved_by", "approved_at", "pdf_sha256"
                )
            )
            == evidence
        )
        assert [
            owner.execute(query, [name]).fetchone()[0] for name in names
        ] == current_definitions
        manage_as_owner("migrate", "agreements", "0013", "--verbosity", "0")
        assert [
            owner.execute(query, [name]).fetchone()[0] for name in names
        ] == old_definitions
        assert (
            AgreementTemplateVersion.objects.filter(
                agreement_type=first.agreement_type, status="approved"
            ).count()
            == 2
        )
    finally:
        manage_as_owner("migrate", "--verbosity", "0")
    assert handlers.approved_version("nda").pk == second.pk


def test_template_replacement_waits_for_native_issuance_to_commit(envelopes):
    application = app("CAT-ND00-0007")
    new = draft(envelopes, 2)
    started, finished = threading.Event(), threading.Event()
    result = []
    backend = []

    def replace():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            backend.append(cursor.fetchone()[0])
        started.set()
        try:
            result.append(approve(envelopes, new)[0].pk)
        finally:
            finished.set()

    owner = envelopes.committed.connect("owner", autocommit=True)
    with transaction.atomic():
        selected = handlers.approved_version("nda", for_update=True)
        thread = envelopes.committed.thread(replace)
        assert started.wait(10)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            waiting = owner.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = %s AND locktype = 'advisory' AND NOT granted)",
                [backend[0]],
            ).fetchone()[0]
            if waiting:
                break
            assert not finished.is_set(), (
                "replacement bypassed the issuance transaction"
            )
            time.sleep(0.01)
        assert waiting, "approval never reached the shared template lock"
        instance = handlers.start_agreement(
            application, selected, "synthetic template race"
        )
    thread.join(30)
    assert not thread.is_alive() and result == [new.pk]
    instance.refresh_from_db()
    assert instance.template_version_id == selected.pk
    assert handlers.approved_version("nda").pk == new.pk
    selected.refresh_from_db()
    assert selected.status == "retired"
    assert (
        PendingAction.objects.filter(
            kind="create_agreement", input_ref=str(instance.public_id)
        ).count()
        == 1
    )
    assert not envelopes.fake.requests
