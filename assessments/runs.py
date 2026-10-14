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
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Sum
from django.db.models.functions import Now, TruncDate

from applications.models import Application, ApplicationEvent, Stage
from applications.stages import StageConflict, transition
from correspondence.staff_items import open_item
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

from . import agent, pack as packs, snapshot
from .models import AssessmentInvocation, AssessmentRun
from .schema import SCHEMA_VERSION, flags

logger = logging.getLogger(__name__)
Status = PendingAction.Status
Run = AssessmentRun.Status
KIND = "run_assessment"
REQUESTS_PER_ATTEMPT = 2
_GLOBAL_LOCK = 0x43415441  # pg advisory lock for the global counters (concurrency, daily budget)


def event(application, kind, data, actor_ref=""):
    ApplicationEvent.objects.create(application=application, kind=kind, actor_type=ApplicationEvent.ActorType.SYSTEM,
                                    actor_ref=actor_ref, data=data)


def enqueue_assessment(application, trigger: str):
    """Returns the queued run, or None when nothing is needed or allowed (the reason goes to staff)."""
    try:
        pack = packs.load()
    except packs.PackRefused as exc:
        open_item("assessment_pack_refused", f"pack:{application.public_ref}", application=application)
        logger.warning("assessment not queued: %s", exc)
        return None
    value = snapshot.manifest(application, pack)
    if value is None:
        return None
    digest = snapshot.snapshot_sha256(value)
    runs = AssessmentRun.objects.filter(application=application)
    if runs.filter(snapshot_sha256=digest, status=Run.SUCCEEDED).exists() or runs.filter(
            status__in=(Run.QUEUED, Run.RESERVED)).exists():
        return None
    if runs.count() >= settings.CATALYST_ASSESSMENT_RUNS_PER_APPLICATION:
        open_item("assessment_capped", f"runs:{application.public_ref}", application=application)
        return None
    run = AssessmentRun.objects.create(
        application=application, adopted_version=application.versions.get(public_id=value["version"]),
        trigger=trigger, snapshot=value, snapshot_sha256=digest, prompt_pack=pack.name, prompt_pack_sha256=pack.sha256,
        rubric_version=pack.rubric_version, schema_version=SCHEMA_VERSION)
    PendingAction.objects.create(kind=KIND, subject_type="application", subject_id=application.public_ref,
                                 input_ref=str(run.public_id), idempotency_key=f"{KIND}:{run.public_id}",
                                 max_attempts=settings.CATALYST_ASSESSMENT_ATTEMPTS)
    event(application, "assessment_queued", {"run": str(run.public_id), "snapshot": digest[:16], "trigger": trigger})
    return run


def _finish_run(run, status, **fields):
    AssessmentRun.objects.filter(pk=run.pk, status__in=(Run.QUEUED, Run.RESERVED)).update(
        status=status, finished_at=Now(), **fields)


def _staff(application, reason, run):
    open_item(reason, f"run:{run.public_id}", application=application)


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
                AssessmentInvocation.objects.filter(run=run, status="started").update(status="abandoned", finished_at=Now())
                _finish_run(run, Run.ABANDONED, error_code="handler_error")
                _staff(application, "assessment_failed", run)

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
            outcome = agent.assess(request)  # outside any transaction
        except agent.ModelUnavailable as exc:
            self._end(claim, run, Run.REFUSED, str(exc), staff="assessment_failed")
        except agent.InvalidOutput as exc:
            self._end(claim, run, Run.INVALID_OUTPUT, str(exc), staff="assessment_failed", requests=REQUESTS_PER_ATTEMPT)
        except agent.BudgetStop as exc:
            self._end(claim, run, Run.CAPPED, str(exc), staff="assessment_capped")
        except agent.ProviderError as exc:
            if claim.final:
                self._end(claim, run, Run.FAILED, f"provider_{exc}", staff="assessment_failed", ledger_status=Status.FAILED)
            else:
                ledger.finish(claim, self, status=Status.QUEUED, error=f"provider_{exc}",
                              write=lambda: AssessmentInvocation.objects.filter(run=run, attempt=claim.attempt).update(
                                  status="completed", finished_at=Now()))
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
        request = snapshot.build_request(application, current, pack)
        AssessmentInvocation.objects.create(
            run=run, application=application, snapshot_sha256=run.snapshot_sha256, attempt=claim.attempt,
            reserved_requests=REQUESTS_PER_ATTEMPT, reserved_tokens=settings.CATALYST_ASSESSMENT_TOTAL_TOKENS_PER_SNAPSHOT)
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
        if spent + REQUESTS_PER_ATTEMPT > settings.CATALYST_ASSESSMENT_REQUESTS_PER_SNAPSHOT:
            return "snapshot_request_budget"
        used = AssessmentRun.objects.filter(application=application).aggregate(t=Sum("input_tokens"), o=Sum("output_tokens"))
        if (used["t"] or 0) + (used["o"] or 0) + settings.CATALYST_ASSESSMENT_TOTAL_TOKENS_PER_SNAPSHOT > \
                settings.CATALYST_ASSESSMENT_TOKENS_PER_APPLICATION:
            return "application_token_budget"
        today = invocations.annotate(day=TruncDate("started_at")).filter(day=TruncDate(Now())).aggregate(
            n=Sum("reserved_requests"))["n"] or 0
        if today + REQUESTS_PER_ATTEMPT > settings.CATALYST_ASSESSMENT_DAILY_REQUESTS:
            return "daily_request_budget"  # defaults to 0: nothing runs until the owner sets a value
        if AssessmentRun.objects.filter(status=Run.RESERVED).exclude(pk=run.pk).count() >= settings.CATALYST_ASSESSMENT_CONCURRENT_RUNS:
            return "concurrency"
        return ""

    def _end(self, claim, run, status, code, staff=None, requests=0, ledger_status=Status.DONE):
        def write():
            AssessmentInvocation.objects.filter(run=run, attempt=claim.attempt).update(status="completed", finished_at=Now())
            _finish_run(run, status, error_code=code, requests_used=requests)
            if staff:
                _staff(Application.objects.get(pk=run.application_id), staff, run)
        ledger.finish(claim, self, status=ledger_status, error=code, write=write)

    def _succeed(self, claim, run, request, outcome):
        import pydantic_ai

        def write():
            application = Application.objects.get(pk=run.application_id)
            data = outcome.output.model_dump(mode="json")
            AssessmentInvocation.objects.filter(run=run, attempt=claim.attempt).update(status="completed", finished_at=Now())
            _finish_run(run, Run.SUCCEEDED, output=data, output_sha256=snapshot.snapshot_sha256(data),
                        flags=flags(outcome.output, request), requests_used=outcome.requests,
                        input_tokens=outcome.input_tokens, output_tokens=outcome.output_tokens, provider="test",
                        model_id=outcome.model_id[:100], output_mode="tool", library_version=pydantic_ai.__version__)
            event(application, "assessment_completed", {"run": str(run.public_id), "snapshot": run.snapshot_sha256[:16]})
            try:  # unconditional on the content: no output field chooses a transition (018 4 step 4)
                transition(application.pk, (Stage.ASSESSING,), Stage.AWAITING_DECISION, event_kind="assessment_ready_for_decision",
                           data={"run": str(run.public_id)}, actor_ref=f"pending_action:{claim.id}")
            except StageConflict:
                pass  # the application left `assessing` meanwhile: the run is history only
        ledger.finish(claim, self, status=Status.DONE, write=write)
