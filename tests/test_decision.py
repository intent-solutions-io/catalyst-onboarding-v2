"""P3 task 3B.4: the authorized qualification decision (018 section 4 step 9, section 7; owner decisions D-34
P3-D-9 to P3-D-11 and P3-D-16, D-35; the 3B.4 release). TEST-P3-04, 43 to 49, 51 to 53, plus the D-35 human-only
assessment and the per-criterion rationale.

POL-05 is undecided, so the code-fixed authority is None and every decision is refused; tests set the authority the
code would carry once the owner records POL-05, and grant the decision permission explicitly to one person.
"""

import threading
from urllib.parse import urlencode

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.test import Client
from django.urls import reverse
from psycopg import errors

from applications.models import Application
from assessments import decisions, pack
from assessments.models import EvidenceItem, QualificationDecision
from assessments.services import Refused
from config import guards
from correspondence.models import StaffItem
from tests.test_assessment import a, valid  # noqa: F401  (fixtures and helpers)
from tests.test_clarification import ASK, assessed_with, c, proposal, reply_to  # noqa: F401
from tests.test_evidence import BASE, FORM, collect, ev, url  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from tests.test_outbound import p2, run_worker, staff  # noqa: F401
from workflow.models import AutomationPause, PendingAction


@pytest.fixture
def d(c, settings):
    settings.CATALYST_QUALIFICATION_AUTHORITY = "explicit_permission"
    c.decider = staff(c, "decider-p3", "Assessment operator")
    owner = c.committed.connect("owner", autocommit=True)  # an explicit grant, as POL-05 would name a person
    owner.execute("INSERT INTO accounts_user_user_permissions (user_id, permission_id) SELECT %s, id FROM auth_permission "
                  "WHERE codename = 'record_qualification_decision'", [c.decider.pk])
    return c


def rationale(capability="shown", strength="moderate"):
    return {cr["id"]: {"capability": capability, "evidence_strength": strength, "note": "Read the work sample."}
            for cr in pack.load().criteria}


def decide(env, app, outcome="hold", user=None, **kw):
    state = decisions.decision_state(Application.objects.get(pk=app.pk))
    args = {"outcome": outcome, "reason_code": "synthetic_reason", "expected_digest": state["digest"],
            "rationale": rationale(), **kw}
    return decisions.record_decision(app.pk, user or env.decider, **args)


def ready_app(d, monkeypatch, **claims):
    app, _ = assessed_with(d, monkeypatch, valid())
    assert app.stage == "awaiting_decision"
    return app


# --- TEST-P3-04, 53: authority -------------------------------------------------------------------------------------

def test_p3_04_no_decision_authority_refuses_everyone_including_superusers(c, monkeypatch, settings):
    app = ready_app(c, monkeypatch)
    assert settings.CATALYST_QUALIFICATION_AUTHORITY is None  # POL-05 undecided: the code default
    root = staff(c, "root-p3", superuser=True)
    for user in (root, staff(c, "operator-p3", "Assessment operator")):
        with pytest.raises(Refused, match="no_decision_authority_configured"):
            decide(c, app, user=user)
    assert not QualificationDecision.objects.exists() and Application.objects.get(pk=app.pk).stage == "awaiting_decision"


def test_p3_53_after_pol05_a_superuser_or_ungranted_staff_is_refused_and_the_setting_is_code_only(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    for user in (staff(d, "root-p3", superuser=True), staff(d, "operator-p3", "Assessment operator")):
        with pytest.raises(PermissionDenied):
            decide(d, app, user=user)

    class Fake:
        CATALYST_QUALIFICATION_AUTHORITY = "anyone"
    assert guards.decision_problems(Fake, {})
    assert guards.decision_problems(type("S", (), {})(), {"CATALYST_QUALIFICATION_AUTHORITY": "explicit_permission"})


# --- TEST-P3-44, 45, 46, 52: the decision, its follow-on, races, history, the backstop -----------------------------

@pytest.mark.parametrize("outcome,stage,follow_on", [("admit", "admitted", "issue_nda"), ("decline", "declined", "send_decline"),
                                                    ("hold", "on_hold", None)])
def test_p3_44_a_decision_is_one_transaction_with_its_held_follow_on(d, monkeypatch, outcome, stage, follow_on):
    app = ready_app(d, monkeypatch)
    decision = decide(d, app, outcome)
    app.refresh_from_db()
    assert app.stage == stage and decision.basis == "model_assisted" and decision.run is not None
    assert decision.policy_ref.startswith("none-approved:assessment_v3:rubric-")  # no selection policy is approved yet
    assert decision.rationale["work_quality"] == {"capability": "shown", "evidence_strength": "moderate",
                                                  "note": "Read the work sample."}
    held = list(PendingAction.objects.filter(kind__in=("issue_nda", "send_decline")).values_list("kind", "status"))
    assert held == ([(follow_on, "held")] if follow_on else [])
    assert app.events.filter(kind=f"qualification_{outcome}").exists()


def test_p3_45_two_concurrent_decisions_one_wins(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    digest = decisions.decision_state(app)["digest"]
    results = []

    def attempt(outcome):
        try:
            decisions.record_decision(app.pk, d.decider, outcome=outcome, reason_code="synthetic_reason",
                                      expected_digest=digest, rationale=rationale())
            results.append("ok")
        except Refused as exc:
            results.append(str(exc))
        finally:
            connection.close()
    threads = [threading.Thread(target=attempt, args=(o,)) for o in ("admit", "decline")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert sorted(results) in (["already_decided", "ok"], ["ok", "stage_not_decidable"])  # exactly one wins
    assert QualificationDecision.objects.count() == 1


def test_p3_46_decisions_are_append_only_for_every_role(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    decision = decide(d, app, "hold")
    for role in ("app", "owner"):
        conn = d.committed.connect(role, autocommit=True)
        for statement in ("UPDATE assessments_qualificationdecision SET outcome = 'admit' WHERE id = %s",
                          "DELETE FROM assessments_qualificationdecision WHERE id = %s"):
            with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
                conn.execute(statement, [decision.pk])


def test_p3_52_no_role_can_move_into_a_decided_stage_without_a_decision_row(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    for role in ("app", "owner"):
        conn = d.committed.connect(role, autocommit=True)
        for stage in ("admitted", "declined", "on_hold"):
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute("UPDATE applications_application SET stage = %s WHERE id = %s", [stage, app.pk])
    assert Application.objects.get(pk=app.pk).stage == "awaiting_decision"


# --- TEST-P3-43, 51: the inputs must still be what the decision-maker saw ------------------------------------------

def test_p3_43_51_a_newly_confirmed_answer_makes_the_run_stale(d, monkeypatch):
    from correspondence import outbound, processing
    from correspondence.models import Question

    app, _ = assessed_with(d, monkeypatch, valid(proposed_questions=[proposal()]))
    shown = decisions.decision_state(app)["digest"]
    q = Question.objects.get(application=app)
    outbound.approve_question(q.pk, d.author)
    inbound = reply_to(q, "I wrote the tokenizer of the synthetic parser myself.")
    # Hold the reassessment so the stale state is observable: no run is queued while we look.
    monkeypatch.setattr("assessments.clarification.answers_settled", lambda application: None)
    monkeypatch.setattr("correspondence.processing.answers_settled", lambda application: None)
    processing.confirm_question_outcome(inbound.pk, {q.pk: "satisfied"}, d.author)
    with pytest.raises(Refused, match="changed_since_shown"):
        decisions.record_decision(app.pk, d.decider, outcome="hold", reason_code="synthetic_reason",
                                  expected_digest=shown, rationale=rationale())


def test_p3_51_a_changed_question_set_or_a_re_fetch_is_refused(d, monkeypatch):
    from assessments import services

    app = ready_app(d, monkeypatch)
    shown = decisions.decision_state(app)["digest"]
    services.author_clarification(app.pk, d.author, text=ASK, criterion_id="contribution", evidence_gap="gap")
    with pytest.raises(Refused, match="changed_since_shown"):
        decisions.record_decision(app.pk, d.decider, outcome="hold", reason_code="synthetic_reason",
                                  expected_digest=shown, rationale=rationale())
    item = EvidenceItem.objects.get(application=app)
    EvidenceItem.objects.create(application=app, adopted_version=item.adopted_version, source=item.source,
                                claim_ref=item.claim_ref, request_url=item.request_url,
                                request_url_sha256=item.request_url_sha256, round=item.round + 1)  # a re-fetch
    with pytest.raises(Refused, match="evidence_pending|no_valid_assessment"):
        decide(d, app, "hold")  # even with the fresh digest: the run no longer describes the evidence


# --- TEST-P3-47: identity items and pauses --------------------------------------------------------------------------

def test_p3_47_an_identity_item_blocks_and_admit_is_refused_while_paused(d, monkeypatch):
    from correspondence.staff_items import open_item

    app = ready_app(d, monkeypatch)
    with transaction.atomic():
        item = open_item("newer_unverified_version", "synthetic", application=app)
    with pytest.raises(Refused, match="identity_item_open"):
        decide(d, app, "hold")
    StaffItem.objects.filter(pk=item.pk).update(status="resolved")
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="t")
    with pytest.raises(Refused, match="admit_refused_while_paused"):
        decide(d, app, "admit")
    assert decide(d, app, "decline").outcome == "decline"  # decline and hold stay possible


# --- D-35: the human-only assessment and the rationale ---------------------------------------------------------------

def test_d35_a_human_only_assessment_is_allowed_only_when_model_advice_is_unavailable(d, monkeypatch, settings):
    bad = valid(quote="A quote that appears nowhere in the evidence")
    app, _ = assessed_with(d, monkeypatch, bad, bad)  # the run fails: the stage stays `assessing`
    assert app.stage == "assessing"
    with pytest.raises(Refused, match="no_valid_assessment"):
        decide(d, app, "hold")  # P3-D-10 still holds without the recorded human-only path
    decision = decide(d, app, "hold", human_only_reason="The assessment failed twice; I read every item myself.")
    assert (decision.basis, decision.run, Application.objects.get(pk=decision.application_id).stage) == ("human_only", None, "on_hold")


def test_d35_human_only_is_never_a_shortcut_past_a_working_assessment(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    with pytest.raises(Refused, match="human_only_assessment_not_allowed"):
        decide(d, app, "admit", human_only_reason="Faster this way.")


@pytest.mark.parametrize("broken", [{"capability": "great"}, {"evidence_strength": ""}, {"note": "  "}, None])
def test_d35_every_criterion_needs_capability_strength_and_a_note(d, monkeypatch, broken):
    app = ready_app(d, monkeypatch)
    r = rationale()
    if broken is None:
        r.pop("consistency")
    else:
        r["work_quality"] = {**r["work_quality"], **broken}
    with pytest.raises(Refused, match="rationale"):
        decide(d, app, "hold", rationale=r)


# --- TEST-P3-48: the screen ----------------------------------------------------------------------------------------

def test_p3_48_the_screen_shows_everything_escaped_and_only_permitted_outcomes(d, monkeypatch, settings):
    app, _ = assessed_with(d, monkeypatch, valid(limitations=["Only one synthetic sample was available."]))
    client = Client()
    client.force_login(d.decider)
    page = client.get(reverse("assessments_staff:decision", args=[app.public_ref])).content.decode()
    for text in ("Claims and observations", "A work page", "Assessment (advisory)", "Only one synthetic sample",
                 "Strength of evidence", 'value="admit"', "none-approved:assessment_v3"):
        assert text in page, text
    assert "<script>" not in page
    viewer = staff(d, "viewer-p3", "Assessment operator")
    client.force_login(viewer)
    page = client.get(reverse("assessments_staff:decision", args=[app.public_ref])).content.decode()
    assert "You may not record a decision" in page and 'value="admit"' not in page
    settings.CATALYST_QUALIFICATION_AUTHORITY = None
    client.force_login(d.decider)
    page = client.get(reverse("assessments_staff:decision", args=[app.public_ref])).content.decode()
    assert "No decision authority is configured (POL-05)" in page


def test_p3_48_the_screen_records_a_decision_through_one_post(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    client = Client()
    client.force_login(d.decider)
    form = {"digest": decisions.decision_state(app)["digest"], "outcome": "hold", "reason_code": "synthetic_reason"}
    for criterion in rationale():
        form.update({f"cap-{criterion}": "partly_shown", f"str-{criterion}": "weak", f"note-{criterion}": "Thin evidence."})
    assert client.post(reverse("assessments_staff:decide", args=[app.public_ref]), form).status_code == 302
    assert Application.objects.get(pk=app.pk).stage == "on_hold"


# --- TEST-P3-49: reapplying after a decline ---------------------------------------------------------------------------

def test_p3_49_a_repeat_after_decline_creates_nothing_new_and_asks_staff(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    decide(d, app, "decline")
    Client().post(FORM, urlencode({**BASE, "reason": "Trying again."}), content_type="application/x-www-form-urlencoded")
    assert Application.objects.filter(email_key=app.email_key).count() == 1
    app.refresh_from_db()
    assert app.stage == "declined" and app.versions.count() == 2
    assert StaffItem.objects.filter(application=app, reason_code="repeat_after_decline", status="open").count() == 1
