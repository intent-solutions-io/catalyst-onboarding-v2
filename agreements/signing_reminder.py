"""The signing reminder (bead bgl.7; parity inventory 034 row 34 and section 1.2 step 14). Behind the agreements
activation like every agreement action: nothing here exists until an envelope has been issued.

One more copy of the signing link mail, `CATALYST_SIGNING_REMINDER_BUSINESS_DAYS` business days (workflow.business_days)
after the envelope was issued and still unsigned, at most `CATALYST_SIGNING_REMINDER_MAX` times (the first-generation
values: five days, once). `schedule` is called in the transaction that records the envelope as issued
(agreements.handlers.DistributeAgreement); the key `remind_signing:<instance>:<n>` makes it idempotent.

`RemindSigning` (`remind_signing`, automated, redeliverable: one fenced database transaction, no provider call) locks
the application, then the instance, and reminds only if the envelope is still issued and unsigned, the application
still waits in `agreements`, agreements are not stopped and automation is not paused, the applicant recipient is still
the verified address, no hard bounce is open and it is not quiet hours. The mail itself goes through
agreements.signing_mail, the seam bead bgl.8 fills: while that reports `NOT_AVAILABLE` the reminder records that the
applicant was not reminded (`signing_reminder_withheld`, one `signing_reminder_unavailable` staff item) and schedules
nothing further; once a reminder is handed to the outbound path, the next one or, after the last, the `lapse` action
(`lapse:agreement:<instance>`, correspondence.lapse) is scheduled in the same transaction.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction

from applications.models import TERMINAL_STAGES, Application, Stage
from correspondence import reminders, scheduling
from correspondence.messages import verified_address
from correspondence.staff_items import event, hard_bounce_open, open_item
from workflow import business_days, ledger
from workflow.models import AutomationPause, PendingAction

from . import signing_mail
from .models import AgreementInstance

Status = PendingAction.Status
Decision = reminders.Decision
REMIND_SIGNING = "remind_signing"
UNAVAILABLE_ITEM = "signing_reminder_unavailable"
REFUSED_ITEM = "signing_reminder_refused"
FAILED_ITEM = "signing_reminder_failed"
UNSIGNED = ("issued", "not_started")  # (issue_status, signing_status) of an envelope the applicant has not acted on


def remind_key(instance, n: int) -> str:
    return f"{REMIND_SIGNING}:{instance.public_id}:{n}"


def lapse_key(instance) -> str:
    return f"{scheduling.LAPSE}:agreement:{instance.public_id}"


def schedule(instance, n: int = 1) -> bool:
    """Inside the caller's transaction: reminder `n`, due `CATALYST_SIGNING_REMINDER_BUSINESS_DAYS` business days on.
    False (nothing scheduled) when reminders are off or `n` is past the maximum."""
    days = settings.CATALYST_SIGNING_REMINDER_BUSINESS_DAYS
    if days <= 0 or n > settings.CATALYST_SIGNING_REMINDER_MAX:
        return False
    scheduling.create_action(REMIND_SIGNING, remind_key(instance, n), instance.application.public_ref,
                             f"{instance.public_id}:{n}", business_days.after(business_days.db_now(), days))
    return True


def schedule_lapse(instance) -> bool:
    due = scheduling.lapse_due()
    if due is None:
        return False
    scheduling.create_action(scheduling.LAPSE, lapse_key(instance), instance.application.public_ref,
                             f"agreement:{instance.public_id}", due)
    return True


def stopped(application) -> bool:
    from .completion import stopped as agreements_stopped  # completion builds on handlers; imported here only

    return agreements_stopped(application)


class RemindSigning:
    kind = REMIND_SIGNING
    automated = True
    redeliverable = True  # one fenced transaction: the seam writes rows, never a provider

    def _instance_ref(self, claim) -> str:
        return claim.input_ref.split(":", 1)[0]

    def lock_subject(self, claim) -> None:
        """Application, then the instance (021 section 4)."""
        application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
        if application is not None:
            AgreementInstance.objects.select_for_update(of=("self",)).filter(public_id=self._instance_ref(claim),
                                                                             application=application).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final")):
            open_item(FAILED_ITEM, claim.input_ref, application=application, pending_action_id=claim.id)

    def run(self, claim) -> None:
        with transaction.atomic():
            self.lock_subject(claim)
            decision = self.decide(claim)
            ledger.finish(claim, self, status=decision.status, error=decision.reason, write=decision.write,
                          due_in=decision.due_in, refund_attempt=decision.refund)

    def decide(self, claim) -> Decision:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        ref, _, n = claim.input_ref.partition(":")
        instance = (AgreementInstance.objects.select_related("application").filter(public_id=ref, application=application).first()
                    if application else None)
        if application is None or instance is None:
            return Decision(Status.FAILED, "agreement_not_found")
        if not n.isdigit() or int(n) > settings.CATALYST_SIGNING_REMINDER_MAX:
            return Decision(Status.CANCELLED, "beyond_maximum")
        if application.stage in TERMINAL_STAGES:
            return Decision(Status.CANCELLED, "application_closed")
        if (instance.issue_status, instance.signing_status) != UNSIGNED or instance.replaced_at:
            return Decision(Status.CANCELLED, "agreement_moved")  # signed, declined, cancelled or replaced: no reminder
        if application.stage != Stage.AGREEMENTS:
            return Decision(Status.CANCELLED, "stage_moved")  # a lapsed application is the lapse's to reopen
        if stopped(application) or AutomationPause.objects.filter(subject_type="application",
                                                                    subject_id=application.public_ref).exists():
            return Decision(Status.QUEUED, "automation_paused", refund=True,
                            due_in=timedelta(seconds=settings.CATALYST_WORKER_POLL_SECONDS))
        now = reminders.db_now()
        quiet = reminders.quiet_until(now)
        if quiet is not None:
            return Decision(Status.QUEUED, "quiet_hours", due_in=quiet - now, refund=True)
        applicant = instance.recipients.filter(who="applicant").first()
        if applicant is None or applicant.email != verified_address(application):
            return Decision(Status.QUEUED, "recipient_not_verified_address", refund=True,
                            due_in=timedelta(seconds=settings.CATALYST_REMINDER_STALE_RETRY_SECONDS),
                            write=lambda: open_item(REFUSED_ITEM, claim.input_ref, application=application,
                                                    pending_action_id=claim.id))
        if hard_bounce_open(application):
            return Decision(Status.QUEUED, "hard_bounce_open", refund=True,
                            due_in=timedelta(seconds=settings.CATALYST_HARD_BOUNCE_RECHECK_SECONDS))
        actor = f"pending_action:{claim.id}"
        number = int(n)

        def write():
            outcome = signing_mail.resend_link(instance, actor_ref=actor)
            data = {"instance": str(instance.public_id), "n": number}
            if outcome == signing_mail.NOT_AVAILABLE:
                open_item(UNAVAILABLE_ITEM, claim.input_ref, application=application, pending_action_id=claim.id)
                event(application, "signing_reminder_withheld", {**data, "reason": outcome}, actor_ref=actor)
                return
            event(application, "signing_reminder_queued", {**data, "send_ref": outcome}, actor_ref=actor)
            if not schedule(instance, number + 1):
                schedule_lapse(instance)  # bgl.7: the quiet period before the closing note starts at the last reminder
        return Decision(Status.DONE, write=write)
