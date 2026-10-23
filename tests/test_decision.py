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


def test_p3_53_after_pol05_a_superuser_or_ungranted_staff_is_refused_and_the_setting_takes_one_rule(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    for user in (staff(d, "root-p3", superuser=True), staff(d, "operator-p3", "Assessment operator")):
        with pytest.raises(PermissionDenied):
            decide(d, app, user=user)

    class Fake:
        CATALYST_QUALIFICATION_AUTHORITY = "anyone"
    assert guards.decision_problems(Fake, {})
    # 9kg.30: the authority is configuration (the launch host sets it once 211.7.8 names the holders), but it takes
    # only the one rule the code implements; the selection policy stays code-only.
    environ = {"CATALYST_QUALIFICATION_AUTHORITY": "explicit_permission"}
    assert not guards.decision_problems(type("S", (), {"CATALYST_QUALIFICATION_AUTHORITY": "explicit_permission"})(), environ)
    assert guards.decision_problems(type("S", (), {"CATALYST_QUALIFICATION_AUTHORITY": "anyone"})(), {"CATALYST_QUALIFICATION_AUTHORITY": "anyone"})
    assert guards.decision_problems(type("S", (), {})(), {"CATALYST_SELECTION_POLICY": "SP-L2-1"})


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


def test_p3_51_a_completed_re_fetch_after_the_screen_was_shown_is_refused(d, monkeypatch):
    from django.db.models.functions import Now

    app = ready_app(d, monkeypatch)
    shown = decisions.decision_state(app)["digest"]
    item = EvidenceItem.objects.get(application=app)
    EvidenceItem.objects.create(application=app, adopted_version=item.adopted_version, source=item.source,
                                claim_ref=item.claim_ref, request_url=item.request_url, round=item.round + 1,
                                request_url_sha256=item.request_url_sha256, status="unavailable", reason_code="synthetic",
                                finished_at=Now())  # a re-fetch that has finished
    with pytest.raises(Refused, match="^changed_since_shown$"):
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
    with pytest.raises(Refused, match="^evidence_pending$"):
        decide(d, app, "hold")  # even with the fresh digest: the new round is still pending


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
    assert app.versions.order_by("-version_number").first().origin == "repeat_after_verification"  # unverified
    assert not app.adoptions.filter(submission_version__version_number=2).exists()  # never adopted
    assert not PendingAction.objects.filter(kind="send_verification", subject_id=app.public_ref, status="queued").exists()


# === review of c4fa72f =============================================================================================

def _decision_sql(conn, app_id, outcome="hold"):
    version = conn.execute("SELECT id FROM applications_submissionversion WHERE application_id = %s ORDER BY id LIMIT 1",
                           [app_id]).fetchone()[0]
    conn.execute("INSERT INTO assessments_qualificationdecision (public_id, application_id, adopted_version_id, outcome, basis,"
                 " human_only_reason, human_only_code, reason_code, reason_text, rationale, snapshot_sha256, decision_digest,"
                 " policy_ref, actor_ref, second_actor_ref) VALUES (gen_random_uuid(), %s, %s, %s, 'human_only', 'synthetic',"
                 " 'run_failed', 'synthetic', '', '{}', 'x', 'x', 'x', 'test', '')", [app_id, version, outcome])  # oc4.12: a code


def test_review_the_backstop_needs_a_matching_decision_from_this_very_transaction(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    owner = d.committed.connect("owner", autocommit=True)
    _decision_sql(owner, app.pk)  # committed in an earlier transaction
    with pytest.raises(errors.InsufficientPrivilege):
        owner.execute("UPDATE applications_application SET stage = 'on_hold' WHERE id = %s", [app.pk])
    tx = d.committed.connect("owner", autocommit=False)
    _decision_sql(tx, app.pk, "hold")  # the wrong outcome for the stage
    tx.execute("UPDATE applications_application SET stage = 'admitted' WHERE id = %s", [app.pk])
    with pytest.raises(errors.InsufficientPrivilege):
        tx.commit()  # deferred: checked at commit
    tx.rollback()
    tx.execute("SAVEPOINT s")
    _decision_sql(tx, app.pk, "hold")
    tx.execute("ROLLBACK TO SAVEPOINT s")  # the decision is gone with its savepoint
    tx.execute("UPDATE applications_application SET stage = 'on_hold' WHERE id = %s", [app.pk])
    with pytest.raises(errors.InsufficientPrivilege):
        tx.commit()
    tx.rollback()
    tx.execute("SAVEPOINT s")
    _decision_sql(tx, app.pk, "hold")
    tx.execute("RELEASE SAVEPOINT s")  # a decision inside a savepoint of this transaction counts
    tx.execute("UPDATE applications_application SET stage = 'on_hold' WHERE id = %s", [app.pk])
    tx.commit()
    assert Application.objects.get(pk=app.pk).stage == "on_hold"


def test_review_the_backstop_refuses_another_applications_decision_and_a_decided_insert(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    tx = d.committed.connect("owner", autocommit=False)
    columns = [r[0] for r in tx.execute("SELECT column_name FROM information_schema.columns WHERE table_name ="
                                        " 'applications_application' AND column_name NOT IN ('id', 'public_ref', 'email_key',"
                                        " 'stage')").fetchall()]
    new_id = tx.execute(f"INSERT INTO applications_application (public_ref, email_key, stage, {', '.join(columns)}) SELECT"
                        f" gen_random_uuid(), 'other@example.test', 'admitted', {', '.join(columns)} FROM"
                        " applications_application WHERE id = %s RETURNING id", [app.pk]).fetchone()[0]
    _decision_sql(tx, app.pk, "admit")  # a decision, but for a different application
    with pytest.raises(errors.InsufficientPrivilege):
        tx.commit()
    tx.rollback()
    assert not Application.objects.filter(pk=new_id).exists()


def test_review_a_supplied_transaction_marker_is_overwritten_and_truncate_is_refused(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    conn = d.committed.connect("app", autocommit=True)
    conn.execute("INSERT INTO assessments_qualificationdecision (public_id, application_id, adopted_version_id, outcome,"
                 " basis, human_only_reason, human_only_code, reason_code, reason_text, rationale, snapshot_sha256,"
                 " decision_digest, policy_ref, actor_ref, second_actor_ref, created_txid) SELECT gen_random_uuid(), %s, id,"
                 " 'hold', 'human_only', 'x', 'run_failed', 'x', '', '{}', 'x', 'x', 'x', 'x', '', 1"
                 " FROM applications_submissionversion WHERE application_id = %s LIMIT 1", [app.pk, app.pk])
    assert conn.execute("SELECT created_txid FROM assessments_qualificationdecision WHERE application_id = %s",
                        [app.pk]).fetchone()[0] != 1
    with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
        conn.execute("TRUNCATE assessments_qualificationdecision")


def test_review_human_only_is_reachable_when_staff_get_the_case_back_without_a_reassessment(d, monkeypatch, settings):
    from correspondence import outbound, processing

    from assessments import services

    settings.CATALYST_ASSESSMENT_ROUNDS = 1
    app = ready_app(d, monkeypatch)
    q = services.author_clarification(app.pk, d.author, text=ASK, criterion_id="contribution", evidence_gap="gap")
    outbound.approve_question(q.pk, d.author)
    inbound = reply_to(q, "I wrote the tokenizer of the synthetic parser myself.")
    processing.confirm_question_outcome(inbound.pk, {q.pk: "satisfied"}, d.author)
    app.refresh_from_db()
    assert app.stage == "awaiting_decision"  # the round cap handed it back; the run no longer fits the snapshot
    with pytest.raises(Refused, match="no_valid_assessment"):
        decide(d, app, "hold")
    client = Client()
    client.force_login(d.decider)
    page = client.get(reverse("assessments_staff:decision", args=[app.public_ref])).content.decode()
    assert "not for the current snapshot" in page and "human-only assessment" in page
    decision = decide(d, app, "hold", human_only_reason="The case came back after the last round; I read everything.")
    assert decision.basis == "human_only"


def test_review_a_decision_withdraws_unsent_questions_and_none_can_be_sent_afterwards(d, monkeypatch):
    from correspondence import outbound
    from correspondence.common import Refused as CorrespondenceRefused
    from correspondence.models import Question

    app, _ = assessed_with(d, monkeypatch, valid(proposed_questions=[proposal()]))
    decide(d, app, "admit")
    q = Question.objects.get(application=app)
    assert (q.status, q.withdrawn_reason) == ("withdrawn", "decided")
    staff_q = Question.objects.create(application=app, text="Which synthetic suite did you write?")
    with pytest.raises(CorrespondenceRefused, match="application_decided"):
        outbound.approve_question(staff_q.pk, d.author)


def test_review_no_evidence_means_capability_unknown(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    for capability in ("shown", "partly_shown", "not_shown"):
        with pytest.raises(Refused, match="rationale_no_evidence_means_capability_unknown"):
            decide(d, app, "hold", rationale=rationale(capability, "none"))
    assert decide(d, app, "hold", rationale=rationale("unknown", "none")).outcome == "hold"


def test_review_exact_refusals_for_pending_evidence_a_run_in_flight_and_a_decided_stage(d, monkeypatch):
    from assessments import runs

    app = ready_app(d, monkeypatch)
    item = EvidenceItem.objects.get(application=app)
    EvidenceItem.objects.create(application=app, adopted_version=item.adopted_version, source=item.source,
                                claim_ref=item.claim_ref, request_url=item.request_url,
                                request_url_sha256=item.request_url_sha256, round=item.round + 1)  # pending
    with pytest.raises(Refused, match="^evidence_pending$"):
        decide(d, app, "hold")
    from django.db.models.functions import Now

    EvidenceItem.objects.filter(application=app, round=item.round + 1).update(status="unavailable", reason_code="synthetic",
                                                                              finished_at=Now())
    with transaction.atomic():  # a new snapshot now exists: a reassessment is queued
        assert runs.enqueue_assessment(Application.objects.select_for_update().get(pk=app.pk), "staff_rerun") is not None
    with pytest.raises(Refused, match="^assessment_in_flight$"):
        decide(d, app, "hold")


def test_review_a_failure_creating_the_follow_on_rolls_everything_back(d, monkeypatch):
    app = ready_app(d, monkeypatch)

    class Broken:
        Status = PendingAction.Status

        class objects:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("synthetic failure creating the held follow-on")
    monkeypatch.setattr(decisions, "PendingAction", Broken)
    with pytest.raises(RuntimeError):
        decide(d, app, "admit")
    assert not QualificationDecision.objects.exists() and Application.objects.get(pk=app.pk).stage == "awaiting_decision"


def test_review_a_group_grant_never_confers_the_decision(d, monkeypatch):
    app = ready_app(d, monkeypatch)
    owner = d.committed.connect("owner", autocommit=True)
    owner.execute("INSERT INTO auth_group_permissions (group_id, permission_id) SELECT g.id, p.id FROM auth_group g,"
                  " auth_permission p WHERE g.name = 'Assessment operator' AND p.codename = 'record_qualification_decision'")
    try:
        member = staff(d, "group-member-p3", "Assessment operator")
        assert member.has_perm("assessments.record_qualification_decision")  # Django would say yes
        with pytest.raises(PermissionDenied):
            decide(d, app, user=member)
    finally:  # group permissions are not reset between tests: leave the matrix as the migrations made it (9kg.30)
        owner.execute("DELETE FROM auth_group_permissions WHERE group_id = (SELECT id FROM auth_group WHERE name = 'Assessment operator')"
                      " AND permission_id = (SELECT id FROM auth_permission WHERE codename = 'record_qualification_decision')")


def test_review_hostile_claim_text_is_escaped_and_nothing_is_preselected(d, monkeypatch):
    from tests.test_assessment import scripted

    scripted(monkeypatch, valid())
    seen_app = collect(d, work_url_1=url(d, "/w"), contribution="<script>alert(1)</script> I wrote it.")
    run_worker()
    client = Client()
    client.force_login(d.decider)
    page = client.get(reverse("assessments_staff:decision", args=[seen_app.public_ref])).content.decode()
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    form = page.split("<h2>Decision</h2>")[1]
    assert 'name="outcome"' in form and " selected" not in form and "checked" not in form


def test_review_the_selection_policy_setting_is_validated():
    class Fake:
        CATALYST_QUALIFICATION_AUTHORITY = None
        CATALYST_SELECTION_POLICY = "anything goes"
    assert guards.decision_problems(Fake, {})
    Fake.CATALYST_SELECTION_POLICY = "SP-L2-1"
    # oc4.12 (oc4.10 item 1): a well-formed policy is refused until it is bound to the pack it was approved with, and
    # while that pack's rubric is synthetic; tests/test_human_only.py has the bound cases.
    [problem] = guards.decision_problems(Fake, {})
    assert "does not bind it to a prompt pack" in problem


def test_recheck_human_only_after_the_run_cap_in_assessing(d, monkeypatch, settings):
    from django.db.models.functions import Now

    from tests.test_assessment import scripted

    scripted(monkeypatch, valid())
    handlers = dict(settings.CATALYST_ACTION_HANDLERS)
    settings.CATALYST_ACTION_HANDLERS = {k: v for k, v in handlers.items() if k != "run_assessment"}
    app = collect(d, work_url_1=url(d, "/w"))
    settings.CATALYST_ACTION_HANDLERS = handlers
    item = EvidenceItem.objects.get(application=app)
    EvidenceItem.objects.create(application=app, adopted_version=item.adopted_version, source=item.source,
                                claim_ref=item.claim_ref, request_url=item.request_url, round=item.round + 1,
                                request_url_sha256=item.request_url_sha256, status="unavailable", reason_code="synthetic",
                                finished_at=Now())
    run_worker()  # the run ends refused: input_changed; the stage stays `assessing`
    settings.CATALYST_ASSESSMENT_RUNS_PER_APPLICATION = 1  # no further run can be queued
    app.refresh_from_db()
    assert app.stage == "assessing" and decisions.decision_state(app)["human_only_allowed"]
    decision = decide(d, app, "hold", human_only_reason="No run can be queued any more; I read every item.")
    assert decision.basis == "human_only"


def test_recheck_an_open_sent_question_blocks_the_decision(d, monkeypatch):
    from correspondence.models import Question

    app = ready_app(d, monkeypatch)
    q = Question.objects.create(application=app, text=ASK, round=1, criterion_id="contribution", evidence_gap="gap")
    d.committed.connect("owner", autocommit=True).execute(  # test setup: a question sent earlier and still open
        "UPDATE correspondence_question SET approval_state = 'approved', approved_by = 'user:1', approved_at = now()"
        " WHERE id = %s", [q.pk])
    with pytest.raises(Refused, match="^open_question_pending$"):
        decide(d, app, "hold")
