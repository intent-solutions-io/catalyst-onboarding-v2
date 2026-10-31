"""Assessment runs (018 section 4 step 4, 5.1, 6; task 3B.2). Test models only.

- `enqueue_assessment`: inside the caller's transaction with the application locked, freeze the snapshot and
  create one queued `AssessmentRun` and its `run_assessment` action, unless this snapshot already succeeded or a
  run is in flight. Called when evidence collection completes, by "proceed without", by the activation command
  for applications already waiting in `assessing`, and by a staff rerun.
- `RunAssessment` (automated, redeliverable within the per-snapshot budget, P3-D-12):
  1. pre-call transaction (application locked, lease fenced): the run is still queued or reserved, the
     application still `assessing`, the snapshot recomputed equal (else `refused: input_changed`), the pack
     digest unchanged, the budgets allow it; then an `AssessmentInvocation` is recorded **before** any request;
  2. the model call, outside any transaction;
  3. a fenced record transaction: the result once; on success the stage moves `assessing → awaiting_decision`
     whatever the output says (staff own the next step); otherwise a staff item and no stage change.
  A recorded invocation is never refunded. A result whose lease was lost is discarded with its transaction.

oc4.9: the call runs inside a `workflow.keeper.LeaseKeeper` (a heartbeat while the call outlives a third of the lease,
and a fence before each request and before the repair: a lost lease makes no further request), and the pre-call
check passes the run's own frozen versions to `agent.build_model`, so a live value needs the owner's recorded
approval of exactly this use. oc4.10 items 4 to 6: only a run whose action still holds a live lease takes a
concurrency slot; a handler defect returns the run to queued for its retry; a run that ends leaves no invocation
`started`.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import CharField, Exists, OuterRef, Sum
from django.db.models.functions import Cast, Coalesce, Now

from applications.models import Application, ApplicationEvent, Stage
from applications.stages import StageConflict, transition
from correspondence.models import StaffItem
from correspondence.staff_items import open_item, resolve_item
from workflow import ledger
from workflow.keeper import LeaseKeeper
from workflow.models import AutomationPause, PendingAction

from .quotas import exceeds
from . import rate_limits
from . import agent, approval, clarification, pack as packs, routine, snapshot
from .models import AssessmentInvocation, AssessmentRun
from .schema import SCHEMA_VERSION, flags

logger = logging.getLogger(__name__)
Status = PendingAction.Status
Run = AssessmentRun.Status
KIND = "run_assessment"
REQUESTS_PER_ATTEMPT = approval.REQUESTS_PER_ATTEMPT  # the call and the one repair
_GLOBAL_LOCK = 0x43415441  # pg advisory lock for the global counters (concurrency, daily budget)


def event(application, kind, data, actor_ref=""):
    ApplicationEvent.objects.create(application=application, kind=kind, actor_type=ApplicationEvent.ActorType.SYSTEM,
                                    actor_ref=actor_ref, data=data)


def enqueue_assessment(application, trigger: str, why: list | None = None, round: int | None = None):
    """Returns the queued run, or None when nothing is needed or allowed; `why` receives the reason code."""
    why = why if why is not None else []
    try:
        pack = packs.load()
    except packs.PackRefused as exc:
        open_item("assessment_pack_refused", f"pack:{application.public_ref}", application=application)
        logger.warning("assessment not queued: %s", exc)
        why.append("prompt_pack_refused")
        return None
    value = snapshot.manifest(application, pack)
    if value is None:
        why.append("no_adopted_version")
        return None
    digest = snapshot.snapshot_sha256(value)
    runs = AssessmentRun.objects.filter(application=application)
    if runs.filter(snapshot_sha256=digest, status=Run.SUCCEEDED).exists():
        why.append("snapshot_already_assessed")
        return None
    if runs.filter(status__in=(Run.QUEUED, Run.RESERVED)).exists():
        why.append("run_in_flight")
        return None
    if exceeds(runs.count() + 1, settings.CATALYST_ASSESSMENT_RUNS_PER_APPLICATION):
        open_item("assessment_capped", f"runs:{application.public_ref}", application=application)
        why.append("application_run_budget")
        return None
    if round is None:  # a first run or a rerun stays in the round of the latest run, whatever its outcome (018 step 8)
        latest = runs.order_by("-round", "-id").first()
        round = latest.round if latest is not None else 1
    run = AssessmentRun.objects.create(
        application=application, adopted_version=application.versions.get(public_id=value["version"]),
        trigger=trigger, round=round, snapshot=value, snapshot_sha256=digest, prompt_pack=pack.name, prompt_pack_sha256=pack.sha256,
        rubric_version=pack.rubric_version, schema_version=SCHEMA_VERSION)
    PendingAction.objects.create(kind=KIND, subject_type="application", subject_id=application.public_ref,
                                 input_ref=str(run.public_id), idempotency_key=f"{KIND}:{run.public_id}",
                                 max_attempts=settings.CATALYST_ASSESSMENT_ATTEMPTS)
    event(application, "assessment_queued", {"run": str(run.public_id), "snapshot": digest[:16], "trigger": trigger})
    return run


def _finish_run(run, status, **fields):
    AssessmentRun.objects.filter(pk=run.pk, status__in=(Run.QUEUED, Run.RESERVED)).update(
        status=status, finished_at=Now(), **fields)
    # oc4.10 item 6: an invocation still `started` when its run ends (an early exit after a crashed attempt, or this
    # attempt's own on a refusal) is abandoned: still counted at its reservation, never left looking in flight.
    AssessmentInvocation.objects.filter(run=run, status="started").update(status="abandoned", finished_at=Now())


# `assessment_suspended` (oc4.12): the run was refused because model advice is disabled (the launch-wide suspension,
# 019 decision 4), which is not an assessment failure; the recorded human-only decision is the way on.
ITEM_CODES = ("assessment_failed", "assessment_capped", "assessment_input_changed", "assessment_pack_refused",
              "assessment_suspended")


def _staff(application, reason, run):
    open_item(reason, f"run:{run.public_id}", application=application)


def settle_items(application, code: str, actor_ref: str, actor_type=None) -> int:
    """Resolve the application's open assessment items once they are overtaken (a success or a staff rerun)."""
    kwargs = {"actor_type": actor_type} if actor_type is not None else {"actor_type": ApplicationEvent.ActorType.SYSTEM}
    return sum(resolve_item(item, code=code, actor_ref=actor_ref, effects={}, **kwargs) for item in
               StaffItem.objects.filter(application=application, status=StaffItem.Status.OPEN, reason_code__in=ITEM_CODES))


def in_flight(exclude=None):
    """oc4.10 item 4: the runs that hold a global concurrency slot: reserved, with their action still running under a
    lease that has not expired (the heartbeat keeps a long call's lease alive, oc4.9). A dead reserved run (its worker
    died; for example on a paused application, which the claim skips) holds no slot: its call is not in flight, and a
    later claim abandons its invocation (counted) before any further call. No staff item is opened for it: nothing is
    stuck but the paused application itself, which staff paused and resume."""
    live = PendingAction.objects.filter(kind=KIND, status=Status.RUNNING, lease_expires_at__gt=Now(),
                                        input_ref=Cast(OuterRef("public_id"), CharField()))
    runs = AssessmentRun.objects.filter(status=Run.RESERVED).filter(Exists(live))
    return runs.exclude(pk=exclude.pk) if exclude is not None else runs


class RunAssessment:
    kind = KIND
    automated = True
    redeliverable = True

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
        AssessmentRun.objects.select_for_update(of=("self",)).filter(public_id=claim.input_ref).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        if application is None:
            return
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final")):
            run = AssessmentRun.objects.filter(public_id=claim.input_ref).first()
            if run is not None:
                _finish_run(run, Run.ABANDONED, error_code="handler_error")  # abandons its started invocations too
                _staff(application, "assessment_failed", run)
        elif kind == "action_failed":
            # oc4.10 item 5: a handler defect with attempts left. Like a provider error, the run waits out the backoff
            # as queued, holding no concurrency slot; the attempt's invocation is abandoned (counted, never refunded).
            run = AssessmentRun.objects.filter(public_id=claim.input_ref).first()
            if run is not None:
                AssessmentInvocation.objects.filter(run=run, status="started").update(status="abandoned", finished_at=Now())
                AssessmentRun.objects.filter(pk=run.pk, status=Run.RESERVED).update(status=Run.QUEUED)

    # --- the three phases ---------------------------------------------------------------------------------

    def run(self, claim) -> None:
        try:
            with transaction.atomic():
                self.lock_subject(claim)
                ledger.fence(claim)
                early, run, request = self.precall(claim)
                if early is not None:
                    status, reason, refund, write, due = early
                    ledger.finish(claim, self, status=status, error=reason, refund_attempt=refund, write=write, due_in=due)
                    return
        except ledger.LeaseLost:
            logger.warning("action %s (%s): lease lost before the call; nothing called", claim.id, claim.kind)
            return
        try:
            with LeaseKeeper(claim):  # oc4.9: a heartbeat, and a fence before each request and before the repair
                outcome = agent.assess(request, approval.Use.for_run(run))  # outside any transaction
        except ledger.LeaseLost:
            # Another claim owns the action now: nothing more is requested or recorded here. The invocation stays
            # counted; the next claim abandons it before any further call.
            logger.warning("action %s (%s): lease lost during the attempt; no further request", claim.id, claim.kind)
            return
        except agent.ModelUnavailable as exc:
            self._end(claim, run, Run.REFUSED, str(exc), staff="assessment_failed")
        except agent.InvalidOutput as exc:
            self._end(claim, run, Run.INVALID_OUTPUT, exc.code, staff="assessment_failed", requests=REQUESTS_PER_ATTEMPT,
                      validation_codes=exc.problems)
        except agent.BudgetStop as exc:
            self._end(claim, run, Run.CAPPED, str(exc), staff="assessment_capped")
        except agent.ProviderError as exc:
            if claim.final:
                self._end(claim, run, Run.FAILED, f"provider_{exc}", staff="assessment_failed", ledger_status=Status.FAILED)
            else:
                def write():  # counted; the run waits out the backoff as queued, holding no concurrency slot
                    AssessmentInvocation.objects.filter(run=run, attempt=claim.attempt).update(status="completed", finished_at=Now())
                    AssessmentRun.objects.filter(pk=run.pk, status=Run.RESERVED).update(status=Run.QUEUED)
                ledger.finish(claim, self, status=Status.QUEUED, error=f"provider_{exc}", write=write,
                              due_in=max(ledger.retry_delay(claim.attempt), timedelta(seconds=exc.retry_after)))
        else:
            self._succeed(claim, run, request, outcome)

    def precall(self, claim):
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        run = AssessmentRun.objects.filter(public_id=claim.input_ref).first()
        if application is None or run is None or run.application_id != application.pk:
            return (Status.FAILED, "run_not_found", False, None, None), None, None
        if run.status not in (Run.QUEUED, Run.RESERVED):
            return (Status.DONE, "run_already_finished", False, None, None), None, None
        if application.stage != Stage.ASSESSING:
            return (Status.CANCELLED, "stage_changed", False,
                    lambda: _finish_run(run, Run.REFUSED, error_code="stage_changed"), None), None, None
        try:  # before the pause check (oc4.12): a paused application under the suspension ends refused at once, so the
            # human-only path is open to staff instead of a requeued run that blocks it; nothing is reserved either way
            agent.build_model(approval.Use.for_run(run))  # oc4.9: a live value needs the approval of this run's versions
        except agent.ModelUnavailable as exc:
            reason = str(exc)
            item = "assessment_suspended" if settings.CATALYST_ASSESSMENT_MODEL == "none" else "assessment_failed"
            return (Status.DONE, reason, False, lambda: (
                _finish_run(run, Run.REFUSED, error_code=reason), _staff(application, item, run)), None), None, None
        if AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
            # No invocation is recorded yet for this attempt, so the attempt may be returned.
            return (Status.QUEUED, "automation_paused", True, None,
                    timedelta(seconds=settings.CATALYST_WORKER_POLL_SECONDS)), None, None
        try:
            pack = packs.load(run.prompt_pack)
        except packs.PackRefused:
            return (Status.FAILED, "prompt_pack_digest_mismatch", False, lambda: (
                _finish_run(run, Run.REFUSED, error_code="prompt_pack_digest_mismatch"),
                _staff(application, "assessment_failed", run)), None), None, None
        current = snapshot.manifest(application, pack)
        if current is None or snapshot.snapshot_sha256(current) != run.snapshot_sha256:
            return (Status.DONE, "input_changed", False, lambda: (
                _finish_run(run, Run.REFUSED, error_code="input_changed"),
                _staff(application, "assessment_input_changed", run)), None), None, None
        # Earlier invocations of this run whose attempt never finished were possibly billed: counted, abandoned.
        AssessmentInvocation.objects.filter(run=run, status="started").update(status="abandoned", finished_at=Now())
        stop = self._budget(application, run)
        if stop == "concurrency":
            return (Status.QUEUED, "global_concurrency", True, None,
                    timedelta(seconds=settings.CATALYST_WORKER_POLL_SECONDS)), None, None
        if stop:
            return (Status.DONE, stop, False, lambda: (
                _finish_run(run, Run.CAPPED, error_code=stop), _staff(application, "assessment_capped", run)), None), None, None
        try:
            request = snapshot.build_request(application, current, pack)
        except ValueError:  # a confirmed answer no longer matches the snapshot: refuse cleanly, nothing reserved
            return (Status.DONE, "answer_changed", False, lambda: (
                _finish_run(run, Run.REFUSED, error_code="answer_changed"),
                _staff(application, "assessment_input_changed", run)), None), None, None
        if not request.fields <= set(approval.FIELDS["assessment"]):  # oc4.9: refused before anything is reserved
            return (Status.DONE, "fields_not_approved", False, lambda: (
                _finish_run(run, Run.REFUSED, error_code="fields_not_approved"),
                _staff(application, "assessment_failed", run)), None), None, None
        delay = rate_limits.reserve(REQUESTS_PER_ATTEMPT,
                                    REQUESTS_PER_ATTEMPT * settings.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS, commit=False)
        if delay:
            return (Status.QUEUED, "provider_rate_limited", True, None, timedelta(seconds=delay)), None, None
        AssessmentInvocation.objects.create(
            run=run, application=application, snapshot_sha256=run.snapshot_sha256, attempt=claim.attempt,
            reserved_requests=REQUESTS_PER_ATTEMPT, reserved_tokens=agent.attempt_tokens())
        from .interpret import record_usage

        record_usage()  # 9kg.33: the day's total into the effect journal once this reservation commits
        AssessmentRun.objects.filter(pk=run.pk).update(status=Run.RESERVED, request_sha256=request.sha256)
        return None, run, request

    def _budget(self, application, run) -> str:
        """Per snapshot, per application, global concurrency and the daily global budget (018 6). Lock order:
        application (held), then the global advisory lock, then the action (the ledger)."""
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_GLOBAL_LOCK])
        invocations = AssessmentInvocation.objects
        spent = invocations.filter(application=application, snapshot_sha256=run.snapshot_sha256).aggregate(
            n=Sum("reserved_requests"))["n"] or 0
        if exceeds(spent + REQUESTS_PER_ATTEMPT, settings.CATALYST_ASSESSMENT_REQUESTS_PER_SNAPSHOT):
            return "snapshot_request_budget"
        # A call whose usage is unknown (failed, invalid, abandoned) counts at its full reservation.
        used = invocations.filter(application=application).aggregate(
            t=Sum(Coalesce("used_tokens", "reserved_tokens")))["t"] or 0
        if agent.token_limits_enabled() and exceeds(used + agent.attempt_tokens(), settings.CATALYST_ASSESSMENT_TOKENS_PER_APPLICATION):
            return "application_token_budget"
        from .interpret import daily_requests_used

        today = daily_requests_used()  # assessments and reply interpretations share the daily budget (3B.3)
        if exceeds(today + REQUESTS_PER_ATTEMPT, settings.CATALYST_ASSESSMENT_DAILY_REQUESTS):
            return "daily_request_budget"  # defaults to 0: nothing runs until the owner sets a value
        if in_flight(exclude=run).count() >= settings.CATALYST_ASSESSMENT_CONCURRENT_RUNS:
            return "concurrency"
        return ""

    def _end(self, claim, run, status, code, staff=None, requests=0, ledger_status=Status.DONE, validation_codes=()):
        def write():
            AssessmentInvocation.objects.filter(run=run, attempt=claim.attempt).update(status="completed", finished_at=Now())
            _finish_run(run, status, error_code=code, requests_used=requests, validation_codes=list(validation_codes))
            if staff:
                _staff(Application.objects.get(pk=run.application_id), staff, run)
        ledger.finish(claim, self, status=ledger_status, error=code, write=write)

    def _succeed(self, claim, run, request, outcome):
        import pydantic_ai

        def write():
            application = Application.objects.get(pk=run.application_id)
            data = outcome.output.model_dump(mode="json")
            AssessmentInvocation.objects.filter(run=run, attempt=claim.attempt).update(
                status="completed", finished_at=Now(), used_tokens=outcome.input_tokens + outcome.output_tokens)
            _finish_run(run, Run.SUCCEEDED, output=data, output_sha256=snapshot.snapshot_sha256(data),
                        flags=flags(outcome.output, request), requests_used=outcome.requests,
                        input_tokens=outcome.input_tokens, output_tokens=outcome.output_tokens, provider=outcome.provider,
                        model_id=outcome.model_id[:100], output_mode=outcome.output_mode, library_version=pydantic_ai.__version__)
            event(application, "assessment_completed", {"run": str(run.public_id), "snapshot": run.snapshot_sha256[:16]})
            settle_items(application, "assessment_succeeded", f"pending_action:{claim.id}")
            try:  # unconditional on the content: no output field chooses a transition (018 4 step 4)
                transition(application.pk, (Stage.ASSESSING,), Stage.AWAITING_DECISION, event_kind="assessment_ready_for_decision",
                           data={"run": str(run.public_id)}, actor_ref=f"pending_action:{claim.id}")
            except StageConflict:
                return  # the application left `assessing` meanwhile: the run is history only, and proposes nothing
            clarification.propose_from_run(run, outcome.output)  # stored proposed; nothing is sent (P3-D-5)
            routine.enqueue(run)  # bgl.12: nothing below CATALYST_ROUTINE_ADVANCE_ACTIVATION 1; the policy reads the output there
        ledger.finish(claim, self, status=Status.DONE, write=write)
