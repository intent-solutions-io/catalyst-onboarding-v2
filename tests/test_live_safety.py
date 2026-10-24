"""oc4.9 (018 section 21): the live-call protections, built and tested before any live model call; and the oc4.10
real-use defects 4 to 7 (items 1 to 3 are fixed and tested in tests/test_human_only.py, oc4.12).

No test here makes a live request or reads a key: the model is a scripted PydanticAI `FunctionModel`, requests to
non-test models are disabled for the process, and the HTTP library a provider client would use raises on every
request (tests/conftest.py, the raising transport). The live branch itself does not exist, so a test that records an
approval shows the approval check passing and the call still refusing.
"""

import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import httpx2
import pytest
from django.conf import settings as django_settings
from django.db import connection, transaction
from psycopg import errors
from pydantic import BaseModel
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.models.wrapper import WrapperModel

from applications.models import Stage
from applications.stages import transition
from assessments import agent, approval, interpret, pack, runs, snapshot
from assessments.models import AssessmentInvocation, AssessmentRun, ModelUseApproval
from assessments.schema import AssessmentOutput
from config import guards
from tests import support
from tests.conftest import ModelNetworkRefused
from tests.test_assessment import a, claim_run, queued, scripted, valid  # noqa: F401  (fixtures and helpers)
from tests.test_evidence import ev, url  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from tests.test_outbound import p2  # noqa: F401
from workflow import keeper as keepers, ledger
from workflow.models import AutomationPause, PendingAction

LIVE = "minimax:MiniMax-M3"  # a live value: refused at start-up by the guard; set here only to reach the check


def approve(purpose="assessment", *flags, expect=0, provider="minimax", model_id="MiniMax-M3",
            ref="synthetic oc4.9 approval"):
    """The owner-run command, as the owner runs it: a separate process connected as the migration owner, with this
    process's budgets and timeout, so the terms it records are the ones this process computes."""
    env = {name: str(getattr(django_settings, name)) for name in approval.BUDGETS}
    env["CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS"] = str(django_settings.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS)
    args = ["--purpose", purpose]
    if "--revoke" not in flags:
        args += ["--provider", provider, "--model-id", model_id]
    if ref is not None and "--show" not in flags:
        args += ["--approval-ref", ref]
    result = support.run(
        [sys.executable, "manage.py", "approve_model_use", *args, *flags],
        CATALYST_DB_NAME=connection.settings_dict["NAME"], CATALYST_DB_USER=django_settings.CATALYST_DB_ROLES["owner"],
        CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"], **env)
    assert result.returncode == expect, (result.stdout, result.stderr)
    return result.stdout + result.stderr


def refused_with(use):
    with pytest.raises(agent.ModelUnavailable) as caught:
        agent.build_model(use)
    return str(caught.value)


# --- the lease fence before each request and before the repair ------------------------------------------------

def test_oc4_9_the_lease_is_fenced_before_each_request_and_before_the_repair(a, monkeypatch, settings):
    fences = []
    real = keepers.LeaseKeeper.fence

    def counted(self):
        fences.append(time.monotonic())
        return real(self)
    monkeypatch.setattr(keepers.LeaseKeeper, "fence", counted)
    beats = []
    monkeypatch.setattr(keepers.LeaseKeeper, "beat", lambda self: beats.append(1))
    broken = valid(quote="A quote that is nowhere in the evidence at all")  # fails the check: one repair follows
    app, run, seen = queued(a, monkeypatch, settings, broken, valid())
    runs.RunAssessment().run(claim_run())
    run.refresh_from_db()
    assert (run.status, seen["calls"], len(fences)) == ("succeeded", 2, 2)  # one fence per request, the repair included
    assert len(beats) == 2  # a worker-alive beat from the calling side after each completed request


def test_oc4_9_a_lease_lost_before_the_repair_makes_no_further_request(a, monkeypatch, settings):
    owner = a.committed.connect("owner", autocommit=True)
    broken = valid(quote="A quote that is nowhere in the evidence at all")
    app, run, _ = queued(a, monkeypatch, settings, broken, valid())
    claim = claim_run()
    seen = scripted(monkeypatch, broken, valid(), during=lambda seen: owner.execute(
        "UPDATE workflow_pendingaction SET lease_token = gen_random_uuid() WHERE id = %s", [claim.id]))
    runs.RunAssessment().run(claim)
    run.refresh_from_db()
    assert seen["calls"] == 1  # the repair was never requested: the fence before it found the lease gone
    assert run.status == "reserved" and run.output is None  # nothing recorded by the stale worker
    assert AssessmentInvocation.objects.get(run=run).status == "started"  # counted; the next claim abandons it
    action = PendingAction.objects.get(pk=claim.id)
    assert action.status == "running" and action.lease_token != claim.lease_token  # the new owner's, untouched


# --- one attempt fits in half the lease (oc4.10 item 7 is the same guard) -------------------------------------

def test_oc4_9_oc4_10_7_one_attempt_must_fit_in_half_the_lease():
    class Fake:
        CATALYST_ENV = "test"
        CATALYST_ASSESSMENT_MODEL = "none"
        CATALYST_WORKER_LEASE_SECONDS = 300
        CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS = 60
    assert guards.attempt_lease_problems(Fake) == [] and guards.assessment_problems(Fake, {}) == []
    Fake.CATALYST_WORKER_LEASE_SECONDS = 239  # two 60 s requests need 240 s of lease at half
    assert guards.assessment_problems(Fake, {}) == [
        "one assessment attempt (2 x CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS) must fit in half of CATALYST_WORKER_LEASE_SECONDS"]
    Fake.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS = 0
    assert "positive" in guards.attempt_lease_problems(Fake)[0]
    # The running settings pass, and every place that counts requests per attempt agrees.
    assert guards.attempt_lease_problems(django_settings) == []
    assert (guards.ASSESSMENT_REQUESTS_PER_ATTEMPT == approval.REQUESTS_PER_ATTEMPT == runs.REQUESTS_PER_ATTEMPT
            == keepers.REQUESTS_PER_ATTEMPT == 1 + approval.REPAIR_LIMIT == 2)


def test_oc4_9_the_default_timeout_follows_a_short_lease():
    result = support.run([sys.executable, "-c", (
        "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); django.setup();"
        "from django.conf import settings as s; from config import guards;"
        "print(s.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS, guards.attempt_lease_problems(s))")],
        CATALYST_WORKER_LEASE_SECONDS="2", CATALYST_EMAIL_TIMEOUT_SECONDS="1")  # the worker tests' timings
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[:2] == ["0.5", "[]"]  # a quarter of a 2 s lease: the worker tests' lease still starts


# --- the heartbeat for a call longer than the lease -------------------------------------------------------------

def test_oc4_9_a_call_longer_than_the_lease_keeps_its_lease_by_heartbeat(a, monkeypatch, settings):
    settings.CATALYST_WORKER_LEASE_SECONDS = 1
    owner = a.committed.connect("owner", autocommit=True)
    app, run, _ = queued(a, monkeypatch, settings, valid())
    claim = claim_run()
    observed = []

    def slow(seen):
        for _ in range(5):  # 2.5 s: more than twice the lease
            time.sleep(0.5)
            observed.append(owner.execute("SELECT lease_expires_at > now(), lease_token = %s FROM workflow_pendingaction"
                                          " WHERE id = %s", [claim.lease_token, claim.id]).fetchone())
    seen = scripted(monkeypatch, valid(), during=slow)
    runs.RunAssessment().run(claim)
    run.refresh_from_db()
    assert observed == [(True, True)] * 5  # never reclaimable while the call ran
    assert run.status == "succeeded" and seen["calls"] == 1


def test_oc4_9_the_keeper_marks_the_lease_lost_when_a_renewal_fails(a, monkeypatch, settings):
    owner = a.committed.connect("owner", autocommit=True)
    queued(a, monkeypatch, settings, valid())
    claim = claim_run()
    owner.execute("UPDATE workflow_pendingaction SET lease_token = gen_random_uuid() WHERE id = %s", [claim.id])
    with keepers.LeaseKeeper(claim, interval=0.05) as keeper:
        assert keepers.current() is keeper
        deadline = time.monotonic() + 5
        while not keeper.lost.is_set() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert keeper.lost.is_set()
        with pytest.raises(ledger.LeaseLost):
            keeper.fence()
    assert keepers.current() is None


# --- the provider-side timeout ------------------------------------------------------------------------------

def test_oc4_9_the_request_timeout_is_enforced_around_the_call(monkeypatch, settings):
    settings.CATALYST_ASSESSMENT_MODEL = "test"
    settings.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS = 0.5
    told = {}

    async def hangs(messages, info: AgentInfo):
        told["timeout"] = (info.model_settings or {}).get("timeout")
        await asyncio.sleep(30)  # a provider that never answers
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {})])
    monkeypatch.setattr(agent, "TEST_MODEL", FunctionModel(hangs))
    started = time.monotonic()
    with pytest.raises(agent.ProviderError, match="^TimeoutError$"):  # a provider error, never an adverse result
        agent.run_checked("system", "prompt", AssessmentOutput, lambda output: [])
    assert time.monotonic() - started < 5
    assert told["timeout"] == 0.5  # the same bound goes to the provider client as its own timeout


def test_oc4_9_a_timed_out_attempt_is_retried_then_ends_failed_with_no_stage_change(a, monkeypatch, settings):
    settings.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS = 0.3

    async def hangs(messages, info):
        await asyncio.sleep(30)
    app, run, _ = queued(a, monkeypatch, settings, valid())
    monkeypatch.setattr(agent, "TEST_MODEL", FunctionModel(hangs))
    runs.RunAssessment().run(claim_run())
    run.refresh_from_db()
    assert run.status == "queued"  # the first timeout waits out the backoff (0 s here), holding no slot
    runs.RunAssessment().run(claim_run())
    run.refresh_from_db()
    app.refresh_from_db()
    assert (run.status, run.error_code, app.stage) == ("failed", "provider_TimeoutError", "assessing")


# --- the raising HTTP transport ---------------------------------------------------------------------------------

def test_oc4_9_the_raising_transport_refuses_every_model_http_request():
    with pytest.raises(ModelNetworkRefused):
        httpx2.Client().get("https://api.minimax.io/v1/models")
    with pytest.raises(ModelNetworkRefused):
        httpx2.Client().get("http://127.0.0.1:9/")  # loopback too: no fake provider endpoint either

    async def provider_client():
        from pydantic_ai.models import create_async_httpx2_client

        async with create_async_httpx2_client() as client:
            await client.post("https://api.minimax.io/v1/chat/completions", json={})
    with pytest.raises(ModelNetworkRefused):
        asyncio.run(provider_client())  # the client PydanticAI's provider classes use


# --- the pre-call approval check ---------------------------------------------------------------------------------

def test_oc4_9_no_live_request_without_a_recorded_approval_and_any_changed_term_refuses(privileged_reset, settings):
    settings.CATALYST_ASSESSMENT_MODEL = LIVE
    use = approval.Use.current("assessment")
    assert refused_with(use) == "model_use_not_approved"
    assert refused_with(None) == "model_use_not_approved"  # a live value with nothing to check is refused too
    out = approve()
    record = ModelUseApproval.objects.get()
    assert f"terms digest {record.terms_sha256}" in out and record.terms == approval.terms(use, "minimax", "MiniMax-M3")
    assert set(record.terms) >= {"provider", "model_id", "fields", "pack", "pack_sha256", "rubric_version",
                                 "schema_version", "budgets", "repair_limit", "request_timeout_seconds"}
    assert record.terms["fields"] == list(approval.FIELDS["assessment"]) and record.terms["repair_limit"] == 1
    # Approved: the check passes, and the call still refuses, because no live branch exists.
    assert refused_with(use) == "model_not_authorized"
    # Every changed term makes the approval stale.
    settings.CATALYST_ASSESSMENT_DAILY_REQUESTS = 999  # a budget
    assert refused_with(use) == "model_use_approval_stale"
    settings.CATALYST_ASSESSMENT_DAILY_REQUESTS = record.terms["budgets"]["CATALYST_ASSESSMENT_DAILY_REQUESTS"]
    settings.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS = 1.0  # the timeout
    assert refused_with(use) == "model_use_approval_stale"
    settings.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS = record.terms["request_timeout_seconds"]
    settings.CATALYST_ASSESSMENT_MODEL = "minimax:MiniMax-M2.7"  # the model id
    assert refused_with(use) == "model_use_approval_stale"
    settings.CATALYST_ASSESSMENT_MODEL = LIVE
    for changed in ({"rubric_version": use.rubric_version + 1}, {"schema_version": "99"},
                    {"pack": "assessment_v2", "pack_sha256": pack.PINNED["assessment_v2"]}):  # a stale snapshot's versions
        assert refused_with(approval.Use(**{**use.__dict__, **changed})) == "model_use_approval_stale"
    original = approval.FIELDS["assessment"]
    try:
        approval.FIELDS["assessment"] = (*original, "claims.something_new")  # the field list
        assert refused_with(use) == "model_use_approval_stale"
    finally:
        approval.FIELDS["assessment"] = original
    assert refused_with(use) == "model_not_authorized"
    approve("assessment", "--revoke", ref="synthetic oc4.9 revocation")
    assert refused_with(use) == "model_use_not_approved"


def test_oc4_9_a_run_with_a_live_value_and_no_approval_is_refused_before_any_reservation(a, monkeypatch, settings):
    app, run, seen = queued(a, monkeypatch, settings, valid())
    settings.CATALYST_ASSESSMENT_MODEL = LIVE
    runs.RunAssessment().run(claim_run())
    run.refresh_from_db()
    assert (run.status, run.error_code, seen["calls"]) == ("refused", "model_use_not_approved", 0)
    assert AssessmentInvocation.objects.count() == 0


def test_oc4_9_the_reply_interpreter_needs_its_own_approval(privileged_reset, settings):
    settings.CATALYST_ASSESSMENT_MODEL = LIVE
    assert interpret.Interpreter().admit(None) == "model_use_not_approved"
    approve("assessment")  # the assessment's approval does not cover the interpreter
    assert interpret.Interpreter().admit(None) == "model_use_not_approved"
    approve("interpretation")
    record = ModelUseApproval.objects.get(purpose="interpretation")
    assert record.terms["pack"] == pack.INTERPRET and record.terms["fields"] == list(approval.FIELDS["interpretation"])
    assert record.terms["schema_version"] == interpret.InterpretOutput.model_fields["schema_version"].annotation.__args__[0]
    assert interpret.Interpreter().admit(None) == "model_not_authorized"  # approved; still no live branch
    settings.CATALYST_INTERPRETATION_DAILY_REQUESTS_PER_APPLICATION = 1  # the shared budgets are part of the terms
    assert interpret.Interpreter().admit(None) == "model_use_approval_stale"


def test_oc4_9_the_approval_is_written_only_by_the_owner_command_and_is_append_only(privileged_reset):
    out = approve("assessment", "--show")
    assert "terms digest" in out and not ModelUseApproval.objects.exists()  # --show writes nothing
    assert "--approval-ref is required" in approve("assessment", expect=1, ref=None)
    assert "--provider" in approve("assessment", provider="Not A Provider", expect=1)
    approve("assessment")
    record = ModelUseApproval.objects.get()
    assert record.approval_ref == "synthetic oc4.9 approval" and record.actor_ref.startswith("owner_command")
    for role in ("app", "owner"):
        conn = privileged_reset.connect(role, autocommit=True)
        for statement in ("UPDATE assessments_modeluseapproval SET model_id = 'x' WHERE id = %s",
                          "DELETE FROM assessments_modeluseapproval WHERE id = %s"):
            with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
                conn.execute(statement, [record.pk])
        with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
            conn.execute("TRUNCATE assessments_modeluseapproval")
    app = privileged_reset.connect("app", autocommit=True)
    with pytest.raises(errors.InsufficientPrivilege):  # the running application never approves its own model use
        app.execute("INSERT INTO assessments_modeluseapproval (purpose, action, provider, model_id, terms, terms_sha256,"
                    " approval_ref, actor_ref) VALUES ('assessment', 'approve', 'x', 'y', '{}', '', 'x', 'x')")
    # No web path: no URL module, view or admin names the record.
    from pathlib import Path

    root = Path(support.ROOT)
    for path in [*root.glob("*/urls.py"), *root.glob("*/*views*.py"), *root.glob("*/staff_urls.py"), *root.glob("*/admin.py")]:
        assert "ModelUseApproval" not in path.read_text() and "approve_model_use" not in path.read_text(), path


# --- oc4.10 items 4 to 6 -------------------------------------------------------------------------------------

def test_oc4_10_4_a_dead_reserved_run_on_a_paused_application_holds_no_concurrency_slot(a, monkeypatch, settings):
    settings.CATALYST_ASSESSMENT_CONCURRENT_RUNS = 1
    owner = a.committed.connect("owner", autocommit=True)
    app, run, _ = queued(a, monkeypatch, settings, valid())
    rival, rival_run, seen = queued(a, monkeypatch, settings, valid(), email="rival@example.test")  # the live script
    # The rival's worker died mid-attempt (reserved, its lease expired), and staff paused the rival: the claim skips
    # it, so nothing would ever finish it.
    owner.execute("UPDATE assessments_assessmentrun SET status = 'reserved' WHERE id = %s", [rival_run.pk])
    owner.execute("UPDATE workflow_pendingaction SET status = 'running', lease_token = gen_random_uuid(),"
                  " lease_expires_at = now() - interval '1 second' WHERE input_ref = %s", [str(rival_run.public_id)])
    AutomationPause.objects.create(subject_type="application", subject_id=rival.public_ref, reason="synthetic", actor_ref="t")
    assert runs.in_flight().count() == 0
    runs.RunAssessment().run(claim_run())
    run.refresh_from_db()
    assert (run.status, seen["calls"]) == ("succeeded", 1)  # not held behind the dead run's slot


def test_oc4_10_4_a_live_reserved_run_still_holds_its_slot(a, monkeypatch, settings):
    settings.CATALYST_ASSESSMENT_CONCURRENT_RUNS = 1
    owner = a.committed.connect("owner", autocommit=True)
    app, run, _ = queued(a, monkeypatch, settings, valid())
    rival, rival_run, seen = queued(a, monkeypatch, settings, valid(), email="rival@example.test")
    owner.execute("UPDATE assessments_assessmentrun SET status = 'reserved' WHERE id = %s", [rival_run.pk])
    owner.execute("UPDATE workflow_pendingaction SET status = 'running', lease_token = gen_random_uuid(),"
                  " lease_expires_at = now() + interval '5 minutes' WHERE input_ref = %s", [str(rival_run.public_id)])
    claim = claim_run()
    runs.RunAssessment().run(claim)
    action = PendingAction.objects.get(pk=claim.id)
    assert (action.status, action.last_error, seen["calls"]) == ("queued", "global_concurrency", 0)


def test_oc4_10_5_a_handler_defect_returns_the_run_to_queued_for_its_retry(a, monkeypatch, settings):
    calls = {"n": 0}
    real = runs.RunAssessment._succeed

    def crash_once(self, claim, run, request, outcome):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("synthetic handler defect after the call")
        return real(self, claim, run, request, outcome)
    monkeypatch.setattr(runs.RunAssessment, "_succeed", crash_once)
    app, run, seen = queued(a, monkeypatch, settings, valid())
    assert ledger.run_one({"run_assessment": runs.RunAssessment()})
    run.refresh_from_db()
    assert run.status == "queued"  # waiting out the backoff, holding no concurrency slot
    assert list(AssessmentInvocation.objects.filter(run=run).values_list("status", flat=True)) == ["abandoned"]
    assert runs.in_flight().count() == 0
    assert ledger.run_one({"run_assessment": runs.RunAssessment()})
    run.refresh_from_db()
    assert run.status == "succeeded" and seen["calls"] == 2


def test_oc4_10_6_a_run_that_ends_early_leaves_no_invocation_started(a, monkeypatch, settings):
    owner = a.committed.connect("owner", autocommit=True)
    app, run, _ = queued(a, monkeypatch, settings, valid())
    claim = claim_run()
    scripted(monkeypatch, valid(), during=lambda seen: owner.execute(
        "UPDATE workflow_pendingaction SET lease_token = gen_random_uuid() WHERE id = %s", [claim.id]))
    runs.RunAssessment().run(claim)  # the lease was lost during the call: the invocation stays started (counted)
    assert AssessmentInvocation.objects.get(run=run).status == "started"
    owner.execute("UPDATE workflow_pendingaction SET lease_expires_at = now() - interval '1 second' WHERE id = %s",
                  [claim.id])
    with transaction.atomic():
        transition(app.pk, (Stage.ASSESSING,), Stage.AWAITING_DECISION, event_kind="synthetic_stage_move")
    runs.RunAssessment().run(claim_run())  # the reclaim exits early: the stage changed
    run.refresh_from_db()
    assert (run.status, run.error_code) == ("refused", "stage_changed")
    assert AssessmentInvocation.objects.get(run=run).status == "abandoned"  # still counted, no longer "in flight"
    assert AssessmentRun.objects.filter(pk=run.pk, finished_at__isnull=False).exists()


# --- review fix-ups (PR #100): fields bound to what is sent ------------------------------------------------------

EXTRA = ("hobby", "a hobby", "Synthetic hobby text", 400, ("claims.hobby",))


def test_oc4_9_a_field_the_builder_adds_is_refused_before_any_reservation(a, monkeypatch, settings):
    app, run, seen = queued(a, monkeypatch, settings, valid())
    real = snapshot._claim_texts
    monkeypatch.setattr(snapshot, "_claim_texts", lambda claims: [*real(claims), EXTRA])  # the builder sends a new field
    runs.RunAssessment().run(claim_run())
    run.refresh_from_db()
    assert (run.status, run.error_code, seen["calls"]) == ("refused", "fields_not_approved", 0)
    assert AssessmentInvocation.objects.count() == 0
    # The checked run refuses on its own too, whatever its caller checked, and an unknown field set refuses.
    use = approval.Use.current("assessment")
    for fields in (frozenset({"claims.hobby"}), None):
        with pytest.raises(agent.ModelUnavailable, match="^fields_not_approved$"):
            agent.run_checked("system", "prompt", AssessmentOutput, lambda output: [], use, fields=fields)
    assert seen["calls"] == 0


def test_oc4_9_a_fully_populated_record_emits_exactly_the_approved_fields(a, monkeypatch, settings):
    app, run, _ = queued(a, monkeypatch, settings, valid(), work_note_1="A synthetic parser page",
                         work_url_2=url(a, "/missing"), experience="Synthetic experience.", confidential="on",
                         confidential_description="Synthetic private tooling work.", cred_name_1="Synthetic cert",
                         cred_issuer_1="Synthetic issuer", cred_identifier_1="SYN-1")
    # A confirmed answer needs the P2 loop; its texts are supplied directly, and the real builder does the rest.
    monkeypatch.setattr(snapshot, "_answer_texts", lambda answers: [(["Which part did you write?"], ["satisfied"],
                                                                     "I wrote the synthetic tokenizer.")])
    current = pack.load(run.prompt_pack)
    request = snapshot.build_request(app, snapshot.manifest(app, current), current)
    assert request.fields == set(approval.FIELDS["assessment"])  # every approved field is reachable, nothing else
    prompt, fields = interpret.build_prompt({"Q1": SimpleNamespace(text="Which part did you write?")},
                                            "I wrote the synthetic tokenizer.", snapshot._names(app), "n0nce")
    assert fields == set(approval.FIELDS["interpretation"]) and "tokenizer" in prompt


# --- review fix-ups: the fence is mandatory for a live model; the approval is checked on every request -----------

class Out(BaseModel):
    x: int


def tool_model(calls, during=None):
    def respond(messages, info: AgentInfo):
        calls.append(1)
        if during is not None:
            during()
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"x": len(calls)})])
    return FunctionModel(respond)


class StubKeeper:
    def __init__(self, delay=0.0):
        self.delay, self.fences, self.beats = delay, 0, 0

    def fence(self):
        self.fences += 1
        time.sleep(self.delay)

    def beat(self):
        self.beats += 1


@pytest.fixture
def stub_keeper():
    keeper = StubKeeper()
    token = keepers._current.set(keeper)
    yield keeper
    keepers._current.reset(token)


def test_oc4_9_a_model_other_than_a_test_model_is_refused_without_a_lease_fence(monkeypatch, settings):
    calls = []
    monkeypatch.setattr(agent, "build_model", lambda use=None: WrapperModel(tool_model(calls)))  # stands in for live
    assert keepers.current() is None
    with pytest.raises(agent.ModelUnavailable, match="^no_lease_fence$"):
        agent.run_checked("system", "prompt", Out, lambda output: [])
    assert calls == []


def test_oc4_9_the_approval_is_rechecked_before_the_repair(privileged_reset, monkeypatch, settings, stub_keeper):
    settings.CATALYST_ASSESSMENT_MODEL = LIVE
    use = approval.Use.current("assessment")
    terms = approval.terms(use, "minimax", "MiniMax-M3")
    owner = privileged_reset.connect("owner", autocommit=True)
    insert = ("INSERT INTO assessments_modeluseapproval (purpose, action, provider, model_id, terms, terms_sha256,"
              " approval_ref, actor_ref) VALUES ('assessment', %s, %s, %s, %s, %s, 'synthetic oc4.9', 'owner_command')")
    owner.execute(insert, ["approve", "minimax", "MiniMax-M3", json.dumps(terms), approval.digest(terms)])
    calls = []
    revoke = lambda: owner.execute(insert, ["revoke", "", "", "{}", ""])  # noqa: E731  (the owner revokes mid-attempt)
    monkeypatch.setattr(agent, "build_model", lambda use=None: WrapperModel(tool_model(calls, during=revoke)))
    with pytest.raises(agent.ModelUnavailable, match="^model_use_not_approved$"):
        agent.run_checked("system", "prompt", Out, lambda output: ["again"], use, fields=frozenset())
    assert calls == [1] and stub_keeper.fences == 1  # the first request was approved; the repair was never sent


def test_oc4_9_a_fence_that_cannot_confirm_in_time_is_a_lost_lease(monkeypatch, settings, stub_keeper):
    settings.CATALYST_ASSESSMENT_MODEL = "test"
    settings.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS = 0.3
    stub_keeper.delay = 2.0  # the database does not answer the renewal in time
    calls = []
    monkeypatch.setattr(agent, "TEST_MODEL", tool_model(calls))
    started = time.monotonic()
    with pytest.raises(ledger.LeaseLost):
        agent.run_checked("system", "prompt", Out, lambda output: [])
    assert calls == [] and time.monotonic() - started < 1.5


def test_oc4_9_streaming_is_refused():
    guarded = agent._Guarded(TestModel(), fence=None, check=None, after=None, timeout=1.0)
    with pytest.raises(agent.ModelUnavailable, match="^streaming_not_allowed$"):
        guarded.request_stream([], None, None)


# --- review fix-ups: the keeper is bounded and is not a liveness signal ------------------------------------------

def test_oc4_9_an_uncancellable_call_lets_the_lease_run_out_and_never_refreshes_liveness(a, monkeypatch, settings,
                                                                                          tmp_path):
    settings.CATALYST_WORKER_LEASE_SECONDS = 1
    owner = a.committed.connect("owner", autocommit=True)
    app, run, _ = queued(a, monkeypatch, settings, valid())
    claim = claim_run()
    alive = tmp_path / "worker-alive"
    settings.CATALYST_WORKER_HEARTBEAT_FILE = str(alive)  # set after the set-up's own worker loop, which beats
    with keepers.LeaseKeeper(claim, max_seconds=1.0) as keeper:
        time.sleep(3.0)  # a call that blocks past every timeout and cannot be cancelled
        assert keeper.lost.is_set() and keeper.renewals >= 1  # it renewed, then stopped at its bound
        assert not alive.exists()  # the renewals never wrote the worker-alive file
        assert owner.execute("SELECT lease_expires_at < now() FROM workflow_pendingaction WHERE id = %s",
                             [claim.id]).fetchone() == (True,)
        with pytest.raises(ledger.LeaseLost):
            keeper.fence()
    again = claim_run()  # the action is reclaimable
    assert again.id == claim.id and again.lease_token != claim.lease_token


def test_oc4_9_a_keeper_fence_before_its_block_renews_and_does_not_fail(a, monkeypatch, settings):
    queued(a, monkeypatch, settings, valid())
    keepers.LeaseKeeper(claim_run()).fence()  # no AttributeError before __enter__


# --- review fix-ups: the raising transport's coverage ------------------------------------------------------------

def test_oc4_9_a_client_with_its_own_transport_class_is_refused_too():
    def handler(request):
        raise AssertionError("the transport must never be reached")
    with pytest.raises(ModelNetworkRefused):
        httpx2.Client(transport=httpx2.MockTransport(handler)).get("https://api.example.test/v1/models")


def test_oc4_9_no_unpatched_http_or_provider_library_enters_the_dependencies():
    names = {re.match(r"^([A-Za-z0-9_.-]+)==", line).group(1).lower()
             for line in Path(support.ROOT, "requirements", "base.txt").read_text().splitlines()
             if re.match(r"^[A-Za-z0-9_.-]+==", line)}
    assert names, "requirements/base.txt was not parsed"
    found = names & {"openai", "anthropic", "requests", "aiohttp", "httpx"}
    assert not found, f"{sorted(found)}: extend the raising transport in tests/conftest.py first, then this list"


def test_oc4_9_only_the_agent_module_builds_a_pydantic_ai_agent():
    pattern = re.compile(r"from pydantic_ai import [^\n]*\bAgent\b|pydantic_ai\.Agent\b|from pydantic_ai\.agent import")
    root = Path(support.ROOT)
    found = sorted(str(p.relative_to(root)) for p in root.rglob("*.py")
                   if not {".venv", "venv", "node_modules", ".git"} & set(p.parts) and p.resolve() != Path(__file__).resolve()
                   and pattern.search(p.read_text()))  # tests included: none builds an Agent of its own
    assert found == ["assessments/agent.py"]
