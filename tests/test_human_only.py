"""oc4.12 (019 decision 4; 018 section 20): the recorded human-only assessment path, complete for an internal launch
that runs with model advice disabled, and the oc4.10 real-use defects 1 to 3.

- A run refused under the launch-wide suspension is labelled "refused by suspension", not an assessment failure,
  and the case leaves `assessing` through the authority-gated decision form, never a free close action.
- A capped snapshot leaves `assessing` the same way (the oc4.8 recommended default).
- The decision digest carries the policy reference, the pack digest, the snapshot digest with an evidence manifest
  and every run; the decision records them, and the pack and rubric even when a policy is set (oc4.10 items 2, 3).
- A policy labels decisions only when bound to its pack, never a synthetic one (oc4.10 item 1).
- Every human-only decision carries a structured reason; the suspension is cited by reference; the database refuses a
  human-only row without a code.
- Human-only decisions are counted on the selection-quality scorecard; model output is shown as nonbinding.
"""

import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from psycopg import errors

from applications.models import Application
from assessments import decisions, pack
from assessments.models import QualificationDecision
from assessments.services import Refused
from config import guards
from correspondence.models import StaffItem
from tests.test_assessment import a, scripted, valid  # noqa: F401  (fixtures and helpers)
from tests.test_clarification import c  # noqa: F401
from tests.test_decision import d, decide, rationale, ready_app  # noqa: F401
from tests.test_evidence import collect, ev, url  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from tests.test_outbound import p2, run_worker, staff  # noqa: F401


def form_for(app, outcome="hold", **extra):
    form = {"digest": decisions.decision_state(app)["digest"], "outcome": outcome, "reason_code": "synthetic_reason", **extra}
    for criterion in rationale():
        form.update({f"cap-{criterion}": "unknown", f"str-{criterion}": "none", f"note-{criterion}": "Read it myself."})
    return form


def failed_case(env, monkeypatch, email="failed@example.test"):
    """A second applicant whose two runs fail (invalid output): human-only applies from `assessing`."""
    bad = valid(quote="A quote that appears nowhere in the evidence")
    scripted(monkeypatch, bad, bad)
    app = collect(env, email=email, work_url_1=url(env, "/w"), contribution="I wrote the parser.")
    run_worker()
    app.refresh_from_db()
    assert app.stage == "assessing"
    return app


def open_items(app, code):
    return StaffItem.objects.filter(application=app, reason_code=code, status="open").count()


def test_a_run_refused_under_the_suspension_is_labelled_so_and_leaves_assessing_through_the_decision_form(d, settings):
    settings.CATALYST_ASSESSMENT_MODEL = "none"  # the launch: model advice disabled (029 section 7)
    app = collect(d, work_url_1=url(d, "/w"), contribution="I wrote the parser.")
    run_worker()
    app.refresh_from_db()
    assert app.stage == "assessing" and open_items(app, "assessment_suspended") == 1 and open_items(app, "assessment_failed") == 0
    from applications.staff import describe_attention

    assert "refused by suspension" in describe_attention(StaffItem.objects.get(application=app, status="open"))
    client = Client()
    client.force_login(d.decider)
    page = client.get(reverse("assessments_staff:decision", args=[app.public_ref])).content.decode()
    assert "Refused by suspension" in page and "not an assessment failure" in page
    assert "advice_suspended" in page and settings.CATALYST_MODEL_ADVICE_SUSPENSION_REF in page
    assert 'name="human_only_reason"' in page and "none-approved:assessment_v3" in page and "work:1: present" in page
    response = client.post(reverse("assessments_staff:decide", args=[app.public_ref]),
                           form_for(app, human_only_reason="Model advice is off for the launch; I read every item."))
    assert response.status_code == 302 and Application.objects.get(pk=app.pk).stage == "on_hold"
    decision = QualificationDecision.objects.get(application=app)
    loaded = pack.load()
    assert (decision.basis, decision.human_only_code, decision.run) == ("human_only", "advice_suspended", None)
    assert (decision.prompt_pack, decision.prompt_pack_sha256, decision.rubric_version) == (loaded.name, loaded.sha256, loaded.rubric_version)
    assert decision.policy_ref == f"none-approved:{loaded.name}:rubric-{loaded.rubric_version}"
    inputs = decision.decision_inputs
    assert inputs["suspension_ref"] == settings.CATALYST_MODEL_ADVICE_SUSPENSION_REF and inputs["policy"] == decision.policy_ref
    assert inputs["evidence"] == [{"claim": "work:1", "state": "present"}] and inputs["snapshot"] == decision.snapshot_sha256
    assert [(r["status"], r["error_code"], r["requests_used"]) for r in inputs["runs"]] == [("refused", "model_not_authorized", 0)]
    assert app.events.get(kind="qualification_hold").data["human_only_code"] == "advice_suspended"


def test_a_capped_snapshot_leaves_assessing_through_the_decision_form_and_no_close_action_exists(d, settings):
    from assessments import staff_urls

    settings.CATALYST_ASSESSMENT_DAILY_REQUESTS = 0  # the daily budget is spent before any call: capped (TEST-P3-26)
    app = collect(d, work_url_1=url(d, "/w"), contribution="I wrote the parser.")
    run_worker()
    app.refresh_from_db()
    assert app.stage == "assessing" and open_items(app, "assessment_capped") == 1
    state = decisions.decision_state(app)
    assert state["human_only_allowed"] and state["human_only_code"] == "run_capped" and state["suspension_ref"] == ""
    assert not any("close" in str(p.pattern) or "close" in (p.name or "") for p in staff_urls.urlpatterns)
    client = Client()
    client.force_login(d.decider)
    response = client.post(reverse("assessments_staff:decide", args=[app.public_ref]),
                           form_for(app, "decline", human_only_reason="The budget is spent; assessed by hand."))
    assert response.status_code == 302 and Application.objects.get(pk=app.pk).stage == "declined"
    decision = QualificationDecision.objects.get(application=app)
    assert decision.human_only_code == "run_capped" and decision.decision_inputs["runs"][0]["status"] == "capped"


def test_the_digest_carries_the_policy_and_a_bound_policy_still_records_the_pack_and_rubric(d, monkeypatch, settings):
    app = ready_app(d, monkeypatch)
    shown = decisions.decision_state(app)["digest"]
    settings.CATALYST_SELECTION_POLICY = "SP-L2-1"  # a policy change between the screen and the submit (oc4.10 item 2)
    assert decisions.decision_state(app)["digest"] != shown
    with pytest.raises(Refused, match="^changed_since_shown$"):
        decisions.record_decision(app.pk, d.decider, outcome="hold", reason_code="synthetic_reason", expected_digest=shown,
                                  rationale=rationale())
    with pytest.raises(Refused, match="^policy_not_bound_to_pack$"):  # oc4.10 item 1: unbound, so no decision carries it
        decide(d, app, "hold")
    settings.CATALYST_SELECTION_POLICY_PACKS = {"SP-L2-1": pack.CURRENT}  # bound, as an activation would record
    assisted = decide(d, app, "hold")
    loaded = pack.load()
    assert assisted.policy_ref == "SP-L2-1" and assisted.basis == "model_assisted"
    assert (assisted.prompt_pack, assisted.prompt_pack_sha256, assisted.rubric_version) == (loaded.name, loaded.sha256, loaded.rubric_version)
    assert assisted.decision_inputs["pack_sha256"] == loaded.sha256 and assisted.decision_inputs["policy"] == "SP-L2-1"
    # oc4.10 item 3: a human-only decision under a policy records the pack and rubric it relied on too.
    failed = failed_case(d, monkeypatch)
    human = decide(d, failed, "hold", human_only_reason="Two failed runs; read every item myself.")
    assert (human.basis, human.human_only_code, human.policy_ref) == ("human_only", "run_failed", "SP-L2-1")
    assert (human.prompt_pack, human.prompt_pack_sha256, human.rubric_version) == (loaded.name, loaded.sha256, loaded.rubric_version)
    assert [r["status"] for r in human.decision_inputs["runs"]] == ["invalid_output"]


def test_the_guard_refuses_a_policy_that_is_unbound_or_bound_to_a_synthetic_pack(monkeypatch):
    class Fake:
        CATALYST_QUALIFICATION_AUTHORITY = None
        CATALYST_SELECTION_POLICY = "SP-L2-1"
        CATALYST_SELECTION_POLICY_PACKS = {}
    assert "does not bind" in guards.decision_problems(Fake, {})[0]
    Fake.CATALYST_SELECTION_POLICY_PACKS = {"SP-L2-1": "assessment_v9"}
    assert "unusable prompt pack" in guards.decision_problems(Fake, {})[0]
    Fake.CATALYST_SELECTION_POLICY_PACKS = {"SP-L2-1": pack.CURRENT}
    assert "rubric is synthetic" in guards.decision_problems(Fake, {})[0]  # the current pack is synthetic (POL-04)
    real = pack.load()
    monkeypatch.setattr(pack, "load", lambda name=pack.CURRENT: pack.Pack(real.name, real.sha256, real.system,
                                                                            {**real.rubric, "synthetic": False}))
    assert guards.decision_problems(Fake, {}) == []
    Fake.CATALYST_SELECTION_POLICY = ""
    assert guards.decision_problems(Fake, {}) == []


def test_a_human_only_decision_never_rests_on_free_text_alone(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    version = app.versions.first()
    conn = d.committed.connect("app", autocommit=True)
    insert = ("INSERT INTO assessments_qualificationdecision (public_id, application_id, adopted_version_id, outcome, basis,"
              " human_only_reason, human_only_code, reason_code, reason_text, rationale, snapshot_sha256, decision_digest,"
              " policy_ref, actor_ref, second_actor_ref) VALUES (gen_random_uuid(), %s, %s, 'hold', 'human_only', %s, %s,"
              " 'synthetic', '', '{}', 'x', 'x', 'x', 'test', '')")
    with pytest.raises(errors.CheckViolation):
        conn.execute(insert, [app.pk, version.pk, "a free-text reason alone", ""])
    conn.execute(insert, [app.pk, version.pk, "a reason", "run_failed"])  # with a structured reason the row is accepted
    assert QualificationDecision.objects.filter(application=app, human_only_code="run_failed").count() == 1
    assert decisions.HUMAN_ONLY_CODES[0] == "advice_suspended"


def test_human_only_decisions_are_counted_on_the_scorecard_without_identifiers(d, monkeypatch, settings):
    app = ready_app(d, monkeypatch)
    decide(d, app, "hold")
    failed = failed_case(d, monkeypatch)
    decide(d, failed, "decline", human_only_reason="Two failed runs; read every item myself.")
    out = StringIO()
    call_command("selection_scorecard", stdout=out)
    card = json.loads(out.getvalue())
    assert card["decisions"] == 2 and card["human_only_by_code"] == [{"human_only_code": "run_failed", "count": 1}]
    assert {"basis": "human_only", "outcome": "decline", "count": 1} in card["by_basis_and_outcome"]
    assert card["by_policy"][0]["policy_ref"].startswith("none-approved:")
    for value in (app.display_name, app.email, str(app.public_ref), str(failed.public_ref), "read every item"):
        assert value not in out.getvalue()


def test_model_output_is_shown_as_nonbinding(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    client = Client()
    client.force_login(d.decider)
    page = client.get(reverse("assessments_staff:decision", args=[app.public_ref])).content.decode()
    assert "nonbinding advice, not a decision" in page and "Assessment (advisory)" in page
