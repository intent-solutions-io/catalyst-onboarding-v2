"""Parity track bgl.12 (034 section 2.2 rows 15 to 19): the live MiniMax branch and the routine-advance policy, both
behind activations that are off in code. No test here makes a live request or reads a key: the model is a scripted
PydanticAI `FunctionModel`, the request flag is restored after every test, and the HTTP library the provider client
uses raises on every request (tests/conftest.py).

Covered: the live branch is selected only when the settings say so and `ALLOW_MODEL_REQUESTS` is on (and refused
with its reason code otherwise, the default configuration included); the guards refuse every live setting outside the
synthetic environments; the policy across its decision table; shadow mode records and never acts; an advance admits
on the existing path with no person; an ask drafts, checks and sends only on a pass; the daily caps stop hard with a
staff item; a hold and a self-caused failure retry a bounded number of times; needs-human lands on the screen; and
nothing sends when the activation forbids automatic action.
"""

from types import SimpleNamespace

import pytest
from pydantic_ai import models as ai_models

from applications.models import Application, ApplicationEvent
from assessments import agent, live, policy
from assessments.models import AssessmentInvocation, AssessmentRun, QualificationDecision
from assessments.schema import AssessmentOutput
from config import guards
from correspondence.models import ApprovedMessage, Question, StaffItem
from tests.test_assessment import QUOTE, a, assessed, scripted, valid  # noqa: F401  (fixtures and helpers)
from tests.test_clarification import c  # noqa: F401
from tests.test_evidence import ev, url  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from tests.test_live_safety import stub_keeper  # noqa: F401
from tests.test_outbound import p2, run_worker  # noqa: F401
from workflow.models import AutomationPause, PendingAction

LIVE = "minimax:MiniMax-M3"
BASE_URL = "https://api.minimax.example/v1"
PROPOSAL = {"text": "Which part of the synthetic parser did you write yourself?", "criterion_id": "contribution",
            "why_needed": "No sample shows which part the applicant wrote.", "alternative_route": "", "requires_evidence": False}
DRAFT = {"schema_version": "1", "body": "1. Which part of the synthetic parser did you write yourself?", "covers": ["contribution"]}
PASS = {"schema_version": "1", "verdict": "pass", "issues": []}
REVISE = {"schema_version": "1", "verdict": "revise", "issues": ["The draft asks about a criterion the gaps do not name."]}


def routine_admit():
    """Every criterion supported on evidence, admit at high confidence: the policy's routine case."""
    out = valid(recommendation="admit", confidence="high")
    for finding in out["criteria"]:
        finding.update(rating="supported", summary="Shown in the sample.", citations=[{"evidence_alias": "E1", "quote": QUOTE}])
    return out


def ask():
    return valid(recommendation="hold", proposed_questions=[PROPOSAL])


@pytest.fixture
def flag(monkeypatch):
    """The request flag is process-wide: monkeypatch restores it (False) after every test."""
    monkeypatch.setattr(agent._models, "ALLOW_MODEL_REQUESTS", False)


@pytest.fixture
def live_settings(settings, flag):
    settings.CATALYST_ASSESSMENT_MODEL = LIVE
    settings.CATALYST_ASSESSMENT_LIVE_ACTIVATION = 1
    settings.CATALYST_ASSESSMENT_LIVE_BASE_URL = BASE_URL
    settings.CATALYST_ASSESSMENT_API_KEY = "synthetic-key-never-sent"
    return settings


@pytest.fixture
def r(c, settings):
    """The assessment fixture with an approved question template and the routine policy acting."""
    settings.CATALYST_ROUTINE_ADVANCE_ACTIVATION = 2
    settings.CATALYST_ROUTINE_DAILY_SENDS = 5
    settings.CATALYST_ROUTINE_RETRY_AFTER_SECONDS = 0
    settings.CATALYST_ROUTINE_RETRY_LIMIT = 1
    return c


def events(app, kind):
    return list(ApplicationEvent.objects.filter(application=app, kind=kind).order_by("id").values_list("data", flat=True))


def action(run):
    return PendingAction.objects.filter(kind="routine_advance", input_ref=str(run.public_id)).first()


# --- the live branch ------------------------------------------------------------------------------------------

def test_bgl12_the_default_configuration_reaches_no_live_branch(settings, flag):
    assert (settings.CATALYST_ASSESSMENT_LIVE_ACTIVATION, settings.CATALYST_ROUTINE_ADVANCE_ACTIVATION) == (0, 0)
    assert (settings.CATALYST_ROUTINE_DAILY_SENDS, settings.CATALYST_ASSESSMENT_DAILY_REQUESTS) == (0, 0)
    assert not live.activated() and live.allow_requests() is False and ai_models.ALLOW_MODEL_REQUESTS is False
    settings.CATALYST_ASSESSMENT_MODEL = LIVE  # a live value with no activation: approval checked, then refused as today
    with pytest.raises(agent.ModelUnavailable, match="^model_use_not_approved$"):
        agent.build_model(SimpleNamespace(purpose="assessment"))


def test_bgl12_the_live_branch_is_selected_only_when_settings_say_so_and_requests_are_allowed(live_settings, monkeypatch):
    monkeypatch.setattr(agent.approval, "require", lambda use: None)  # the approval machinery has its own tests (oc4.9)
    use = SimpleNamespace(purpose="assessment")
    with pytest.raises(agent.ModelUnavailable, match="^model_requests_disabled$"):
        agent.build_model(use)  # configured and approved, but the worker has not switched the flag on
    assert live.allow_requests() is True and ai_models.ALLOW_MODEL_REQUESTS is True
    model = agent.build_model(use)
    assert type(model).__name__ == "OpenAIChatModel" and model.model_name == "MiniMax-M3" and model.system == "openai"
    client = model.client
    assert str(client.base_url).rstrip("/") == BASE_URL and client.max_retries == 0
    assert client.timeout == pytest.approx(float(live_settings.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS))
    # each missing piece has its own refusal, and none of them builds a client
    for name, value, code in (("CATALYST_ASSESSMENT_API_KEY", "", "live_api_key_missing"),
                              ("CATALYST_ASSESSMENT_LIVE_BASE_URL", "http://api.minimax.example/v1", "live_base_url_not_https"),
                              ("CATALYST_ASSESSMENT_MODEL", "openai:gpt-x", "provider_not_supported")):
        before = getattr(live_settings, name)
        setattr(live_settings, name, value)
        with pytest.raises(agent.ModelUnavailable, match=f"^{code}$"):
            agent.build_model(use)
        setattr(live_settings, name, before)
    live_settings.CATALYST_ASSESSMENT_LIVE_ACTIVATION = 0  # the activation off: the flag being on is itself refused
    with pytest.raises(agent.ModelUnavailable, match="^model_requests_enabled$"):
        agent.build_model(use)
    live_settings.CATALYST_ENV = "production"  # never in a live environment, whatever the settings say
    live_settings.CATALYST_ASSESSMENT_LIVE_ACTIVATION = 1
    assert not live.activated()
    with pytest.raises(agent.ModelUnavailable, match="^model_requests_enabled$"):
        agent.build_model(use)


def test_bgl12_a_live_call_runs_fenced_and_a_provider_failure_is_never_adverse(live_settings, monkeypatch, stub_keeper):
    monkeypatch.setattr(agent.approval, "require", lambda use: None)
    live.allow_requests()
    use = SimpleNamespace(purpose="assessment")
    with pytest.raises(agent.ProviderError, match="^APIConnectionError$"):  # the raising transport: nothing left the box
        agent.run_checked("system", "prompt", AssessmentOutput, lambda output: [], use, fields=frozenset())
    assert stub_keeper.fences >= 1  # the lease fence ran before the request


def test_bgl12_the_guards_refuse_every_live_setting_outside_the_synthetic_environments():
    def fake(**over):
        values = {"CATALYST_ENV": "production", "CATALYST_ASSESSMENT_MODEL": "none", "CATALYST_ASSESSMENT_LIVE_ACTIVATION": 0,
                  "CATALYST_ASSESSMENT_LIVE_BASE_URL": "", "CATALYST_ASSESSMENT_API_KEY": "", "CATALYST_ROUTINE_ADVANCE_ACTIVATION": 0,
                  "CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS": 60, "CATALYST_WORKER_LEASE_SECONDS": 300}
        return SimpleNamespace(**{**values, **over})
    assert guards.assessment_problems(fake(), {}) == []
    for over in ({"CATALYST_ASSESSMENT_MODEL": LIVE, "CATALYST_ASSESSMENT_LIVE_ACTIVATION": 1}, {"CATALYST_ASSESSMENT_LIVE_BASE_URL": BASE_URL},
                 {"CATALYST_ASSESSMENT_API_KEY": "x"}, {"CATALYST_ASSESSMENT_LIVE_ACTIVATION": 1}):
        assert guards.assessment_problems(fake(**over), {}), over
        assert guards.assessment_problems(fake(CATALYST_ENV="development", **over), {}), over
    # a synthetic environment accepts a live value only with the activation on, and a usable base URL
    assert any("not authorized" in p for p in guards.assessment_problems(fake(CATALYST_ENV="staging", CATALYST_ASSESSMENT_MODEL=LIVE), {}))
    assert guards.assessment_problems(fake(CATALYST_ENV="staging", CATALYST_ASSESSMENT_MODEL=LIVE, CATALYST_ASSESSMENT_LIVE_ACTIVATION=1,
                                           CATALYST_ASSESSMENT_LIVE_BASE_URL=BASE_URL, CATALYST_ASSESSMENT_API_KEY="x"), {}) == []
    assert any("https" in p for p in guards.assessment_problems(fake(CATALYST_ENV="test", CATALYST_ASSESSMENT_LIVE_BASE_URL="http://api.x/v1"), {}))
    assert guards.assessment_problems(fake(CATALYST_ENV="test", CATALYST_ASSESSMENT_LIVE_BASE_URL="http://127.0.0.1:9/v1"), {}) == []
    # none of the switches may come from the environment, and the key is a per-secret file in a deployment
    environ = {name: "1" for name in guards.CODE_FIXED_ASSESSMENT}
    assert sum("may not be set from the environment" in p for p in guards.assessment_problems(fake(), environ)) == len(environ)
    assert "CATALYST_ASSESSMENT_API_KEY" in guards.SECRET_ENV_NAMES
    assert any("ROUTINE_ADVANCE_CONFIDENCE" in p for p in guards.assessment_problems(
        fake(CATALYST_ENV="test", CATALYST_ROUTINE_ADVANCE_ACTIVATION=1, CATALYST_ROUTINE_ADVANCE_CONFIDENCE="sure",
             CATALYST_ROUTINE_ADVANCE_REQUIRED_RATING="supported", CATALYST_ROUTINE_ADVANCE_OTHER_RATING="supported"), {}))


# --- the policy -----------------------------------------------------------------------------------------------

def output(**over) -> AssessmentOutput:
    return AssessmentOutput.model_validate(valid(**over))


OPEN = dict(cohort_boundary=False, identity_item_open=False, paused=False, contact_verified=True, open_question=False, evidence_pending=False)
ADMIT = AssessmentOutput.model_validate(routine_admit())


@pytest.mark.parametrize("out,facts,expected", [
    (ADMIT, policy.Facts(required=frozenset({"work_quality"}), **OPEN), (policy.ADVANCE, "routine_admit")),
    (ADMIT, policy.Facts(), (policy.NEEDS_HUMAN, "cohort_boundary")),  # the safe defaults: nothing automatic
    (ADMIT, policy.Facts(**{**OPEN, "identity_item_open": True}), (policy.NEEDS_HUMAN, "identity_item_open")),
    (ADMIT, policy.Facts(flags=("inconsistent_recommendation",), **OPEN), (policy.NEEDS_HUMAN, "flagged_for_a_person")),
    (ADMIT, policy.Facts(**{**OPEN, "paused": True}), (policy.HOLD, "automation_paused")),
    (ADMIT, policy.Facts(**{**OPEN, "contact_verified": False}), (policy.HOLD, "contact_not_verified")),
    (ADMIT, policy.Facts(**{**OPEN, "open_question": True}), (policy.HOLD, "question_open")),
    (ADMIT, policy.Facts(**{**OPEN, "evidence_pending": True}), (policy.HOLD, "evidence_pending")),
    (output(recommendation="decline", confidence="high"), policy.Facts(**OPEN), (policy.NEEDS_HUMAN, "decline_is_never_automatic")),
    (output(recommendation="admit", confidence="high"), policy.Facts(**OPEN), (policy.NEEDS_HUMAN, "rating_below_threshold")),
    (output(recommendation="admit", confidence="medium"), policy.Facts(**OPEN), (policy.NEEDS_HUMAN, "confidence_below_threshold")),
    (AssessmentOutput.model_validate(routine_admit()).model_copy(update={"injection_suspected": True}), policy.Facts(**OPEN),
     (policy.NEEDS_HUMAN, "flagged_for_a_person")),
    (output(recommendation="hold"), policy.Facts(**OPEN), (policy.NEEDS_HUMAN, "hold_recommended")),
    (output(recommendation="hold", proposed_questions=[PROPOSAL]), policy.Facts(room=3, **OPEN), (policy.ASK, "evidence_gap")),
    (output(recommendation="hold", proposed_questions=[PROPOSAL]), policy.Facts(room=3, **{**OPEN, "paused": True}), (policy.HOLD, "automation_paused")),
    (output(recommendation="hold", proposed_questions=[PROPOSAL]), policy.Facts(room=0, **OPEN), (policy.NEEDS_HUMAN, "round_full")),
    (output(recommendation="hold", proposed_questions=[PROPOSAL]), policy.Facts(round=3, rounds=3, room=3, **OPEN), (policy.NEEDS_HUMAN, "rounds_exhausted")),
])
def test_bgl12_the_policy_decision_table(out, facts, expected):
    verdict = policy.decide(out, facts, policy.Thresholds())
    assert (verdict.outcome, verdict.reason) == expected
    assert len(verdict.questions) == (1 if verdict.outcome == policy.ASK else 0)


def test_bgl12_the_policy_never_advances_on_claims_alone_and_thresholds_are_settings():
    claims = routine_admit()
    for finding in claims["criteria"]:
        finding["citations"] = [{"evidence_alias": "C1", "quote": QUOTE}]
    assert policy.decide(AssessmentOutput.model_validate(claims), policy.Facts(**OPEN)).reason == "rating_rests_on_claims_only"
    partly = routine_admit()
    partly["criteria"][2]["rating"] = "partly_supported"  # an optional criterion
    out = AssessmentOutput.model_validate(partly)
    assert policy.decide(out, policy.Facts(required=frozenset({"work_quality", "contribution"}), **OPEN)).outcome == policy.ADVANCE
    assert policy.decide(out, policy.Facts(required=frozenset({"work_quality", "contribution"}), **OPEN),
                         policy.Thresholds(other_rating="supported")).reason == "rating_below_threshold"
    assert policy.Thresholds("sure", "supported", "not_supported").problems() == [
        "CATALYST_ROUTINE_ADVANCE_CONFIDENCE must be low, medium or high",
        "CATALYST_ROUTINE_ADVANCE_OTHER_RATING must be insufficient_evidence, partly_supported or supported"]
    record = policy.rationale(out)
    assert record["credential_support"] == {"capability": "partly_shown", "evidence_strength": "weak",
                                            "note": "Routine policy v1: the assessment rated this partly_supported on 1 evidence citation(s)."}
    assert all(e["capability"] == "unknown" for e in record.values() if e["evidence_strength"] == "none")


# --- the action -------------------------------------------------------------------------------------------------

def test_bgl12_below_the_activation_nothing_is_queued_and_shadow_records_without_acting(c, monkeypatch, settings):
    app, run, _ = assessed(c, monkeypatch, routine_admit())
    assert action(run) is None and events(app, "routine_policy_evaluated") == []
    settings.CATALYST_ROUTINE_ADVANCE_ACTIVATION = 1
    app2, run2, _ = assessed(c, monkeypatch, routine_admit(), contribution="I wrote the second parser.")
    assert action(run2).status == "done" and action(run2).last_error == "shadow"
    (recorded,) = events(app2, "routine_policy_evaluated")
    assert (recorded["outcome"], recorded["reason"], recorded["activation"], recorded["policy_version"]) == ("advance_to_nda", "routine_admit", 1, "1")
    assert app2.stage == "awaiting_decision" and not QualificationDecision.objects.filter(application=app2).exists()


def test_bgl12_a_routine_applicant_is_admitted_on_the_existing_path_without_a_person(r, monkeypatch, settings):
    app, run, seen = assessed(r, monkeypatch, routine_admit())
    assert seen["calls"] == 1 and app.stage == "admitted" and action(run).status == "done"
    decision = QualificationDecision.objects.get(application=app)
    assert (decision.outcome, decision.basis, decision.run_id, decision.reason_code, decision.actor_ref) == (
        "admit", "model_assisted", run.pk, "routine_advance", "policy:routine_advance:v1")
    assert decision.decision_inputs["routine_policy"]["outcome"] == "advance_to_nda" and decision.decision_digest
    assert set(decision.rationale) == {"work_quality", "contribution", "credential_support", "purpose_fit", "consistency"}
    assert PendingAction.objects.get(kind="issue_nda", subject_id=app.public_ref).status == "held"  # P4 releases it, as today
    assert events(app, "routine_advanced") == [{"run": str(run.public_id), "decision": str(decision.public_id)}]
    assert not ApprovedMessage.objects.exists()  # nothing was sent to the applicant


def test_bgl12_an_ask_drafts_checks_and_sends_only_on_a_pass(r, monkeypatch):
    app, run, seen = assessed(r, monkeypatch, ask(), DRAFT, PASS)
    assert seen["calls"] == 3 and app.stage == "awaiting_answers" and action(run).status == "done"
    message = ApprovedMessage.objects.get(kind="question")
    assert message.authority == "system_policy" and message.authorized_by == "policy:routine_advance:v1"
    assert DRAFT["body"] in message.frozen_body
    question = Question.objects.get(application=app)
    assert (question.approval_state, question.approved_by, question.origin) == ("approved", "policy:routine_advance:v1", "model")
    assert PendingAction.objects.get(kind="send_message").status == "done"  # sent through P2 to the local sink
    (sent,) = events(app, "routine_clarification_sent")
    assert sent["provider"] == "test" and sent["packs"] == ["clarify_v1", "check_v1"] and sent["usage"]["draft"][0] == 1
    assert "<<DATA alias=D" in seen["prompts"][2] and DRAFT["body"] in seen["prompts"][2]  # the check read the draft, fenced
    reserved = AssessmentInvocation.objects.filter(run=run, attempt__gte=1000)
    assert reserved.count() == 2 and set(reserved.values_list("status", flat=True)) == {"completed"}
    assert not QualificationDecision.objects.exists()


def test_bgl12_a_check_that_does_not_pass_sends_nothing_and_leaves_the_proposal_on_the_screen(r, monkeypatch):
    app, run, seen = assessed(r, monkeypatch, ask(), DRAFT, REVISE)
    assert seen["calls"] == 3 and app.stage == "awaiting_decision" and action(run).status == "done"
    assert not ApprovedMessage.objects.exists() and not PendingAction.objects.filter(kind="send_message").exists()
    assert Question.objects.get(application=app).approval_state == "proposed"
    (refused,) = events(app, "routine_clarification_refused")
    assert refused["verdict"] == "revise" and refused["issues"] == REVISE["issues"]


def test_bgl12_a_draft_that_fails_the_screen_is_repaired_once_then_held(r, monkeypatch):
    bad = {**DRAFT, "body": "Send your password to ada@example.test so we can check."}
    app, run, seen = assessed(r, monkeypatch, ask(), bad, bad)  # the call and one repair, then invalid output
    assert seen["calls"] == 3 and app.stage == "awaiting_decision"
    held = action(run)
    assert held.status == "queued" and held.last_error.startswith("self_caused:InvalidOutput:invalid_output_after_repair")
    assert not ApprovedMessage.objects.exists()


def test_bgl12_the_daily_send_cap_is_a_hard_stop_with_a_staff_item(r, monkeypatch, settings):
    settings.CATALYST_ROUTINE_DAILY_SENDS = 0
    app, run, seen = assessed(r, monkeypatch, ask(), DRAFT, PASS)
    assert seen["calls"] == 1 and app.stage == "awaiting_decision" and action(run).last_error == "daily_send_cap"
    assert StaffItem.objects.filter(application=app, reason_code="routine_send_cap_reached", status="open").count() == 1
    assert events(app, "routine_cap_stop") == [{"run": str(run.public_id), "reason": "daily_send_cap"}]
    assert not AssessmentInvocation.objects.filter(run=run, attempt__gte=1000).exists()  # nothing reserved


def test_bgl12_the_daily_request_cap_stops_the_draft_before_any_reservation(r, monkeypatch, settings):
    settings.CATALYST_ASSESSMENT_DAILY_REQUESTS = 3  # room for the run's two, not for the draft and the check
    app, run, seen = assessed(r, monkeypatch, ask(), DRAFT, PASS)
    assert seen["calls"] == 1 and action(run).last_error == "daily_request_cap"
    assert StaffItem.objects.filter(application=app, reason_code="routine_request_cap_reached", status="open").count() == 1
    assert not AssessmentInvocation.objects.filter(run=run, attempt__gte=1000).exists()


def test_bgl12_a_self_caused_failure_retries_bounded_then_opens_a_staff_item(r, monkeypatch, settings):
    app, run, seen = assessed(r, monkeypatch, ask(), OSError("synthetic 503"))
    held = action(run)
    assert held.last_error == "self_caused:ProviderError:OSError" and seen["calls"] >= 2
    assert held.status in ("queued", "done")  # the first failure was requeued (due at once: retry after 0 s) and run again
    run_worker()
    held.refresh_from_db()
    assert held.status == "done" and held.attempts == 2  # 1 + CATALYST_ROUTINE_RETRY_LIMIT
    assert events(app, "routine_held") and events(app, "routine_hold_exhausted")
    assert StaffItem.objects.filter(application=app, reason_code="routine_advance_failed", status="open").count() == 1
    assert Application.objects.get(pk=app.pk).stage == "awaiting_decision" and not ApprovedMessage.objects.exists()
    # the reservations of both attempts are counted, never refunded
    assert AssessmentInvocation.objects.filter(run=run, attempt__gte=1000).count() == 4


def test_bgl12_a_hold_waits_and_needs_human_lands_on_the_screen(r, monkeypatch, settings):
    settings.CATALYST_ROUTINE_RETRY_AFTER_SECONDS = 3600
    out = routine_admit()
    scripted(monkeypatch, out)
    from tests.test_evidence import collect
    app = collect(r, work_url_1=url(r, "/w"), contribution="I wrote the parser.")
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="synthetic", actor_ref="test")
    run_worker()
    run = AssessmentRun.objects.get(application=app)
    held = action(run)
    assert held.status == "queued" and held.last_error == "automation_paused" and held.attempts == 1
    assert events(app, "routine_held")[0]["reason"] == "automation_paused"
    assert Application.objects.get(pk=app.pk).stage == "awaiting_decision" and not QualificationDecision.objects.exists()
    # needs-human: a decline recommendation is never acted on
    app2, run2, _ = assessed(r, monkeypatch, valid(recommendation="decline", confidence="high"), contribution="Another parser.")
    assert action(run2).status == "done" and action(run2).last_error == "decline_is_never_automatic"
    assert app2.stage == "awaiting_decision" and not QualificationDecision.objects.filter(application=app2).exists()


def test_bgl12_only_the_policy_module_reads_the_advisory_fields_and_only_live_imports_the_client():
    from pathlib import Path

    from tests import support

    code = {p.name: p.read_text() for p in Path(support.ROOT, "assessments").rglob("*.py") if "migrations" not in p.parts}
    for field in ("recommendation", "confidence", "proposed_questions", "injection_suspected", ".rating", '"rating"', "'rating'"):
        assert field not in code["routine.py"], field  # the action consults the policy; it reads nothing itself
    assert "policy.decide(" in code["routine.py"] and "policy.rationale(" in code["routine.py"]
    for name, text in code.items():
        assert ("from openai" in text or "import openai" in text) == (name == "live.py"), name
    assert "ALLOW_MODEL_REQUESTS = True" in code["live.py"] and code["live.py"].count("ALLOW_MODEL_REQUESTS = True") == 1
    assert not any("ALLOW_MODEL_REQUESTS = True" in t for n, t in code.items() if n != "live.py")
