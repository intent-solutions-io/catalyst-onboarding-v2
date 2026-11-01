"""The routine-advance action (parity track bgl.12; 034 section 2.2 rows 15 to 19, section 4 item 2): what the first
generation's acting review did, rebuilt beside v2's human decision and behind an activation that is off in code.

`enqueue(run)` is called inside a successful run's record transaction (`runs.RunAssessment._succeed`) when
`CATALYST_ROUTINE_ADVANCE_ACTIVATION` is at least 1, and queues one `routine_advance` action per run. The handler:

1. pre-call transaction (application locked, lease fenced): the run is still the valid succeeded run for the current
   snapshot and the application still awaits a decision (else done, `superseded`); the application's facts are
   gathered and `policy.decide` names the verdict, which is recorded as an event (`routine_policy_evaluated`) whatever
   the activation level. At level 1 (shadow) nothing else happens: the owner can read verdicts before any act.
   At level 2:
   - `needs_human`: done; the case stays on the decision screen exactly as today;
   - `hold`: the action is requeued after `CATALYST_ROUTINE_RETRY_AFTER_SECONDS`, at most
     `CATALYST_ROUTINE_RETRY_LIMIT` times, then a staff item (`routine_advance_failed`) and the screen;
   - `advance_to_nda`: `decisions.record_routine_admit` on the existing admit path, in this transaction;
   - `ask_a_question`: the daily caps are checked (a hard stop records why and opens a staff item), two invocations
     are reserved against the shared daily request budget, and the pre-call ends;
2. the two model calls (`clarify.draft`, then `clarify.check`), outside any transaction, under a `LeaseKeeper`, through
   `agent.run_checked`: the approval, the lease fence, the timeout and the limits apply to each. A failure of the
   model or the budget here is a self-caused hold: the action retries like a hold, bounded;
3. the record transaction: the invocations complete; a `pass`, with the case still unpaused and the daily send cap
   re-checked under the global lock (another worker may have spent the last send meanwhile), approves the proposals
   the policy chose as one frozen message with the checked body (`correspondence.outbound.approve_questions_by_policy`, authority `system_policy`) and
   opens the round; anything else records the verdict and leaves the proposals on the screen, unsent.

Nothing a model wrote leaves without the check and the activation (P3-D-5 holds everywhere else); a decline is never
automatic; every verdict, send and stop is an application event. The decision screen is unchanged.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count
from django.db.models.functions import Now, TruncDate

from applications.models import Application, ApplicationEvent, Stage
from correspondence import outbound
from correspondence.common import Refused as OutboundRefused
from correspondence.messages import verified_address
from correspondence.models import ApprovedMessage, Question, StaffItem
from correspondence.staff_items import open_item
from workflow import ledger
from workflow.keeper import LeaseKeeper
from workflow.models import AutomationPause, PendingAction

from .quotas import exceeds
from . import rate_limits
from . import agent, clarify, decisions, pack as packs, policy
from .models import AssessmentInvocation, AssessmentRun, EvidenceItem
from .schema import AssessmentOutput
from .services import Refused

logger = logging.getLogger(__name__)
Status = PendingAction.Status
KIND = "routine_advance"
ACTOR = f"policy:routine_advance:v{policy.VERSION}"
ITEM_CODES = ("routine_advance_failed", "routine_send_cap_reached", "routine_request_cap_reached")
DRAFT_ATTEMPT, CHECK_ATTEMPT = 1001, 1002  # invocation attempt numbers beyond any run attempt
REQUESTS = 2 * agent.approval.REQUESTS_PER_ATTEMPT  # the draft and the check, each with one repair


def activation() -> int:
    return int(getattr(settings, "CATALYST_ROUTINE_ADVANCE_ACTIVATION", 0) or 0)


def event(application, kind, data, actor_ref=ACTOR):
    ApplicationEvent.objects.create(application=application, kind=kind, actor_type=ApplicationEvent.ActorType.SYSTEM,
                                    actor_ref=actor_ref, data=data)


def enqueue(run) -> PendingAction | None:
    """Inside the run's record transaction: one action per succeeded run, none below activation level 1."""
    if activation() < 1:
        return None
    action, _ = PendingAction.objects.get_or_create(
        idempotency_key=f"{KIND}:{run.public_id}",
        defaults={"kind": KIND, "subject_type": "application", "subject_id": run.application.public_ref,
                  "input_ref": str(run.public_id), "max_attempts": 1 + settings.CATALYST_ROUTINE_RETRY_LIMIT})
    return action


def sends_today() -> int:
    """Clarifications the policy sent today (the database's UTC date), against CATALYST_ROUTINE_DAILY_SENDS."""
    return (ApprovedMessage.objects.filter(kind=ApprovedMessage.Kind.QUESTION, authority=ApprovedMessage.Authority.SYSTEM_POLICY)
            .annotate(day=TruncDate("authorized_at")).filter(day=TruncDate(Now())).aggregate(n=Count("id"))["n"] or 0)


def facts(application, run, pack) -> policy.Facts:
    version = application.versions.get(public_id=run.snapshot["version"])
    approved = Question.objects.filter(application=application, approval_state=Question.Approval.APPROVED)
    return policy.Facts(
        required=frozenset(c["id"] for c in pack.criteria if c.get("required")), flags=tuple(run.flags or ()),
        round=run.round, rounds=settings.CATALYST_ASSESSMENT_ROUNDS,
        room=max(0, settings.CATALYST_QUESTIONS_PER_ROUND - approved.filter(round=run.round).count()),
        cohort_boundary=decisions.cohort_boundary(),
        identity_item_open=StaffItem.objects.filter(application=application, status=StaffItem.Status.OPEN,
                                                    reason_code__in=decisions.IDENTITY_ITEMS).exists(),
        paused=AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists(),
        contact_verified=verified_address(application) is not None,
        open_question=approved.filter(status__in=(Question.Status.OPEN, Question.Status.REPLY_PENDING)).exists(),
        evidence_pending=EvidenceItem.objects.filter(application=application, adopted_version=version, status="pending").exists())


class RoutineAdvance:
    kind = KIND
    automated = True
    redeliverable = True

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        if application is None:
            return
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final")):
            AssessmentInvocation.objects.filter(run__public_id=claim.input_ref, status="started").update(status="abandoned", finished_at=Now())
            open_item("routine_advance_failed", f"routine:{claim.input_ref}", application=application)

    # --- the three phases ---------------------------------------------------------------------------------

    def run(self, claim) -> None:
        try:
            with transaction.atomic():
                self.lock_subject(claim)
                ledger.fence(claim)
                early, work = self.precall(claim)
                if early is not None:
                    status, reason, write, due = early
                    ledger.finish(claim, self, status=status, error=reason, write=write, due_in=due,
                                  refund_attempt=reason == "provider_rate_limited")
                    return
        except ledger.LeaseLost:
            logger.warning("action %s (%s): lease lost before the call; nothing called", claim.id, claim.kind)
            return
        application, run, pack, proposals, uses = work
        try:
            with LeaseKeeper(claim):  # oc4.9: a heartbeat, and a fence before each request and before each repair
                draft = clarify.draft(application, pack, uses["clarify"], proposals, uses["draft_use"])
                check = clarify.check(application, pack, uses["check"], proposals, draft.output.body, uses["check_use"])
        except ledger.LeaseLost:
            logger.warning("action %s (%s): lease lost during the attempt; no further request", claim.id, claim.kind)
            return
        except (agent.ModelUnavailable, agent.InvalidOutput, agent.BudgetStop, agent.ProviderError) as exc:
            code = exc.code if isinstance(exc, agent.InvalidOutput) else str(exc)
            if isinstance(exc, agent.ProviderError) and exc.retry_after and not claim.final:
                ledger.finish(claim, self, status=Status.QUEUED, error="provider_rate_limited",
                              due_in=max(ledger.retry_delay(claim.attempt), timedelta(seconds=exc.retry_after)))
                return
            self._hold(claim, application, run, f"self_caused:{type(exc).__name__}:{code}"[:120])
            return
        usage = {"draft": [draft.requests, draft.input_tokens + draft.output_tokens],
                 "check": [check.requests, check.input_tokens + check.output_tokens]}
        # provenance on every post-call event, sent or not: the model, its provider and the two pinned prompt packs
        provenance = {"usage": usage, "provider": draft.provider, "model_id": draft.model_id[:100],
                      "packs": [uses["clarify"].name, uses["check"].name],
                      "pack_sha256": [uses["clarify"].sha256, uses["check"].sha256]}

        def write():
            for attempt, (requests, tokens) in zip(uses["attempts"], (usage["draft"], usage["check"])):
                AssessmentInvocation.objects.filter(run=run, attempt=attempt).update(status="completed", finished_at=Now(), used_tokens=tokens)
            verdict = check.output.verdict
            if verdict != "pass":
                event(application, "routine_clarification_refused", {"run": str(run.public_id), "verdict": verdict,
                                                                     "issues": list(check.output.issues), **provenance})
                return
            # Re-checked at the send itself, under the same lock order as the pre-call (application, then the global
            # advisory lock): another worker may have spent the day's last send, or a person paused the case, while the
            # model was drafting. Either way nothing is sent and the proposals stay on the screen.
            from .interpret import GLOBAL_LOCK  # imported where used, as in the pre-call

            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [GLOBAL_LOCK])
            if AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
                event(application, "routine_clarification_refused", {"run": str(run.public_id), "verdict": "automation_paused",
                                                                     **provenance})
                return
            if exceeds(sends_today() + 1, settings.CATALYST_ROUTINE_DAILY_SENDS):
                self._stop(application, run, "routine_send_cap_reached", "daily_send_cap")[2]()
                return
            try:
                message = outbound.approve_questions_by_policy(application.pk, [q.pk for q in proposals], body=draft.output.body, actor=ACTOR)
            except OutboundRefused as exc:
                event(application, "routine_clarification_refused", {"run": str(run.public_id), "verdict": "send_refused",
                                                                     "reason": str(exc), **provenance})
                return
            event(application, "routine_clarification_sent", {"run": str(run.public_id), "send_ref": str(message.send_ref),
                                                              "questions": [str(q.public_id) for q in proposals], **provenance})
        ledger.finish(claim, self, status=Status.DONE, write=write)

    def precall(self, claim):
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        run = AssessmentRun.objects.filter(public_id=claim.input_ref).first()
        if application is None or run is None or run.application_id != application.pk:
            return (Status.FAILED, "run_not_found", None, None), None
        if run.status != AssessmentRun.Status.SUCCEEDED or application.stage != Stage.AWAITING_DECISION:
            return (Status.DONE, "superseded", None, None), None
        state = decisions.decision_state(application)
        if state["run"] is None or state["run"].pk != run.pk or state["pack"] is None:
            return (Status.DONE, "superseded", None, None), None
        pack = state["pack"]
        output = AssessmentOutput.model_validate(run.output)
        verdict = policy.decide(output, facts(application, run, pack), policy.Thresholds.from_settings(settings))
        level = activation()
        event(application, "routine_policy_evaluated", {"run": str(run.public_id), "activation": level, **verdict.record()})
        if level < 2:
            return (Status.DONE, "shadow", None, None), None
        if verdict.outcome == policy.NEEDS_HUMAN:
            return (Status.DONE, verdict.reason, None, None), None
        if verdict.outcome == policy.HOLD:
            return self._hold_early(claim, application, run, verdict.reason), None
        if verdict.outcome == policy.ADVANCE:
            try:
                with transaction.atomic():  # a refusal inside leaves no decision row behind
                    decision = decisions.record_routine_admit(application, run, rationale=policy.rationale(output),
                                                              verdict=verdict.record(), actor=ACTOR)
            except Refused as exc:
                reason = str(exc)
                return (Status.DONE, reason, lambda: event(application, "routine_advance_refused",
                                                           {"run": str(run.public_id), "reason": reason}), None), None
            return (Status.DONE, "", lambda: event(application, "routine_advanced", {"run": str(run.public_id),
                                                                                     "decision": str(decision.public_id)}), None), None
        # ask_a_question: the caps, then the reservations (lock order: application, then the global advisory lock)
        from .interpret import GLOBAL_LOCK, daily_requests_used, record_usage

        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [GLOBAL_LOCK])
        if exceeds(sends_today() + 1, settings.CATALYST_ROUTINE_DAILY_SENDS):
            return self._stop(application, run, "routine_send_cap_reached", "daily_send_cap"), None
        if exceeds(daily_requests_used() + REQUESTS, settings.CATALYST_ASSESSMENT_DAILY_REQUESTS):
            return self._stop(application, run, "routine_request_cap_reached", "daily_request_cap"), None
        try:
            clarify_pack, check_pack = clarify.packs_for()
        except packs.PackRefused as exc:
            return (Status.DONE, str(exc), lambda: open_item("routine_advance_failed", f"routine:{run.public_id}", application=application), None), None
        draft_use, check_use = clarify.uses(clarify_pack, check_pack)
        proposals = list(Question.objects.filter(application=application, origin=Question.Origin.MODEL, round=run.round,
                                                 approval_state=Question.Approval.PROPOSED, raised_by=f"run:{run.public_id}")
                         .exclude(status=Question.Status.WITHDRAWN).order_by("id")[:len(verdict.questions)])
        if not proposals:
            return (Status.DONE, "no_proposal_to_send", None, None), None
        delay = rate_limits.reserve(REQUESTS,
                                    REQUESTS * settings.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS, commit=False)
        if delay:
            return (Status.QUEUED, "provider_rate_limited", None, timedelta(seconds=delay)), None
        # Earlier draft or check invocations whose attempt never finished were possibly billed: counted, abandoned.
        AssessmentInvocation.objects.filter(run=run, attempt__gte=DRAFT_ATTEMPT, status="started").update(
            status="abandoned", finished_at=Now())
        attempts = (DRAFT_ATTEMPT + 10 * claim.attempt, CHECK_ATTEMPT + 10 * claim.attempt)
        for attempt in attempts:
            AssessmentInvocation.objects.create(run=run, application=application, snapshot_sha256=run.snapshot_sha256,
                                                attempt=attempt, reserved_requests=agent.approval.REQUESTS_PER_ATTEMPT,
                                                reserved_tokens=agent.attempt_tokens())
        record_usage()  # 9kg.33: the day's total into the effect journal once this reservation commits
        return None, (application, run, pack, proposals, {"clarify": clarify_pack, "check": check_pack,
                                                           "draft_use": draft_use, "check_use": check_use, "attempts": attempts})

    def _stop(self, application, run, item: str, reason: str):
        """A daily cap: a hard stop that records why and opens one staff item per day; the case stays on the screen."""
        def write():
            event(application, "routine_cap_stop", {"run": str(run.public_id), "reason": reason})
            open_item(item, f"{item}:{_today()}", application=application)  # one item per cap per day
        return (Status.DONE, reason, write, None)

    def _hold_early(self, claim, application, run, reason: str):
        if claim.final:
            return (Status.DONE, reason, lambda: (
                event(application, "routine_hold_exhausted", {"run": str(run.public_id), "reason": reason}),
                open_item("routine_advance_failed", f"routine:{run.public_id}", application=application)), None)
        return (Status.QUEUED, reason, lambda: event(application, "routine_held", {"run": str(run.public_id), "reason": reason,
                                                                                "attempt": claim.attempt}),
                timedelta(seconds=settings.CATALYST_ROUTINE_RETRY_AFTER_SECONDS))

    def _hold(self, claim, application, run, reason: str) -> None:
        """A self-caused hold after the pre-call (the draft or the check failed): counted, then retried like a hold."""
        def write():
            AssessmentInvocation.objects.filter(run=run, status="started").update(status="completed", finished_at=Now())
        status, error, early_write, due = self._hold_early(claim, application, run, reason)

        def both():
            write()
            if early_write is not None:
                early_write()
        ledger.finish(claim, self, status=status, error=error, write=both, due_in=due)


def _today() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT CURRENT_DATE::text")
        return cursor.fetchone()[0]
