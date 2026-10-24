"""oc4.9 (018 section 21): the live-call protections, built and tested before any live model call; and the oc4.10
real-use defects 4 to 7 (items 1 to 3 are fixed and tested in tests/test_human_only.py, oc4.12).

No test here makes a live request or reads a key: the model is a scripted PydanticAI `FunctionModel`, requests to
non-test models are disabled for the process, and the HTTP library a provider client would use raises on every
request (tests/conftest.py, the raising transport). The live branch itself does not exist, so a test that records an
approval shows the approval check passing and the call still refusing.
"""

import asyncio
import os
import sys
import time

import httpx2
import pytest
from django.conf import settings as django_settings
from django.db import connection
from psycopg import errors
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from assessments import agent, approval, interpret, pack, runs
from assessments.models import AssessmentInvocation, ModelUseApproval
from assessments.schema import AssessmentOutput
from config import guards
from tests import support
from tests.conftest import ModelNetworkRefused
from tests.test_assessment import a, claim_run, queued, scripted, valid  # noqa: F401  (fixtures and helpers)
from tests.test_evidence import ev  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from tests.test_outbound import p2  # noqa: F401
from workflow import keeper as keepers, ledger
from workflow.models import PendingAction

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
    broken = valid(quote="A quote that is nowhere in the evidence at all")  # fails the check: one repair follows
    app, run, seen = queued(a, monkeypatch, settings, broken, valid())
    runs.RunAssessment().run(claim_run())
    run.refresh_from_db()
    assert (run.status, seen["calls"], len(fences)) == ("succeeded", 2, 2)  # one fence per request, the repair included


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
    assert guards.ASSESSMENT_REQUESTS_PER_ATTEMPT == approval.REQUESTS_PER_ATTEMPT == runs.REQUESTS_PER_ATTEMPT == 2


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
