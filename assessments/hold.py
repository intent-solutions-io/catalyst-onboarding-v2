"""The still-in-review note of a hold (bgl.24; D-55).

An applicant put on hold hears nothing until there is a decision, so after ten business days on hold they get one short
note saying the request is still in review and nothing is needed from them. Off by default: while
`CATALYST_HOLD_NOTICE_ENABLED` is off nothing is queued and nothing is sent.

`schedule` runs inside the hold's own transaction (`decisions.record_decision`, outcome `hold`, the application
locked): with the switch on it queues one `send_hold_notice:<application>` action, due when ten business days have
passed since the hold was recorded (workflow.business_days: Monday to Friday by the UTC date, the lapse's count). The key
is per application, so a case gets at most one note: a second scheduling attempt adds nothing, and the handler freezes
at most one note per application however often it runs.

`SendHoldNotice` runs it the way `assessments.decline.SendDecline` runs the decline notice: one fenced transaction,
automated (a pause holds it) and redeliverable, because it sends nothing itself. It freezes the note as an
`ApprovedMessage` of kind `hold_notice` and queues its `send_message`, so the P2 sender delivers it under every P2 rule
(the three-phase exchange, uncertain-send reconciliation, the hard-bounce block and their staff items).

Cancelled without a send: the switch was turned off before it ran, or the application is no longer on hold (the way
off a hold is a final decision or a closure, never a second hold). Done without a second freeze: a note was already
frozen for the application. Deferred: before the tenth business day (a redelivery or a moved clock), in quiet hours (as the
lapse note), while a copy that left after a backup is under review after a restore (as the decline notice), and while
the wording may not be used here or the address is not verified, with one `hold_notice_refused` staff item that
resolves itself once the note is queued.

The wording is the `hold_notice` template (correspondence migration 0027; the real wording in correspondence.wording),
read through applications.notices: only an approved, non-synthetic version in a live environment. Its one variable is
the first name, so no reason, rationale or model output can reach the applicant.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction

from applications import notices
from applications.models import Application, ApplicationEvent, Stage
from correspondence.models import ApprovedMessage, MessageTemplateVersion, StaffItem
from correspondence.outbound import enqueue_send, verified_address
from correspondence.reminders import quiet_until
from correspondence.rendering import canonical_digest, html_inputs
from correspondence.staff_items import event, open_item, resolve_item
from workflow import business_days, ledger
from workflow.models import PendingAction

from .models import QualificationDecision

KIND = "send_hold_notice"
TEMPLATE = "hold_notice"
REFUSED_ITEM = "hold_notice_refused"
BUSINESS_DAYS = 10  # D-55: the note goes after ten business days on hold
RECHECK_SECONDS = 900  # how often a note that cannot be prepared yet looks again (as the decline notice)
RESTORE_ITEM = "restore_effect_unknown_send"  # correspondence.restore: a copy left after the backup, under review
Status = PendingAction.Status


def enabled() -> bool:
    return bool(settings.CATALYST_HOLD_NOTICE_ENABLED)


def key(application) -> str:
    return f"{KIND}:{application.public_ref}"


def due(held_at):
    """The first instant at which BUSINESS_DAYS business days have passed since the hold was recorded."""
    return business_days.after(held_at, BUSINESS_DAYS)


def schedule(application, decision) -> PendingAction | None:
    """Inside the hold's transaction (decisions.record_decision), the application locked. Nothing while the switch is
    off; nothing when the application already has its one note action (the key is unique: never an IntegrityError
    inside the decision)."""
    if (
        not enabled()
        or PendingAction.objects.filter(idempotency_key=key(application)).exists()
    ):
        return None
    return PendingAction.objects.create(
        kind=KIND,
        subject_type="application",
        subject_id=application.public_ref,
        input_ref=str(decision.public_id),
        idempotency_key=key(application),
        due_at=due(business_days.db_now()),
    )


class SendHoldNotice:
    kind = KIND
    redeliverable = True  # one fenced transaction that freezes and queues: nothing leaves the process here
    automated = True  # a paused application's note waits for the resume, like every other automated mail

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(
            public_ref=claim.subject_id
        ).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if application is not None and (
            kind == "action_attempts_exhausted"
            or (kind == "action_failed" and data.get("final"))
        ):
            open_item(
                REFUSED_ITEM,
                f"hold:{application.public_ref}",
                application=application,
                pending_action_id=claim.id,
            )

    def run(self, claim) -> None:
        with transaction.atomic():
            self.lock_subject(claim)
            status, error, write, due_in = self.decide(claim)
            ledger.finish(
                claim,
                self,
                status=status,
                error=error,
                write=write,
                due_in=due_in,
                refund_attempt=status == Status.QUEUED,
            )

    def decide(self, claim):
        actor = f"pending_action:{claim.id}"
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        if application is None:
            return Status.FAILED, "subject_application_not_found", None, None
        if not enabled():
            return (
                Status.CANCELLED,
                "hold_notice_disabled",
                None,
                None,
            )  # the owner turned it off: nothing is sent
        decision = QualificationDecision.objects.filter(
            public_id=claim.input_ref, application=application, outcome="hold"
        ).first()
        if decision is None:
            return Status.FAILED, "hold_decision_not_found", None, None
        if application.stage != Stage.ON_HOLD:
            # Decided, withdrawn or closed meanwhile. The only way off a hold is a final decision or a closure (9kg.50),
            # so an application on hold is still in the hold this action was queued for.
            return Status.CANCELLED, "application_not_on_hold", None, None
        if ApprovedMessage.objects.filter(
            application=application, kind=ApprovedMessage.Kind.HOLD_NOTICE
        ).exists():
            return Status.DONE, "already_queued", None, None  # one note per application
        now = business_days.db_now()
        due_at = due(decision.created_at)
        if now < due_at:
            return Status.QUEUED, "not_yet_due", None, due_at - now
        quiet = quiet_until(now)
        if quiet is not None:
            return Status.QUEUED, "quiet_hours", None, quiet - now
        recheck = timedelta(seconds=RECHECK_SECONDS)
        if StaffItem.objects.filter(
            application=application,
            reason_code=RESTORE_ITEM,
            status=StaffItem.Status.OPEN,
        ).exists():
            return Status.QUEUED, "sent_after_backup_pending_review", None, recheck

        def item():
            open_item(
                REFUSED_ITEM,
                f"hold:{application.public_ref}",
                application=application,
                pending_action_id=claim.id,
            )

        recipient = verified_address(application)
        if recipient is None:
            return Status.QUEUED, "contact_not_verified", item, recheck
        values = {
            "display_name": application.display_name
        }  # the version declares `first_name`: the first word of it
        try:
            wording = notices.wording(TEMPLATE, values)
        except notices.Unavailable as refused:
            return Status.QUEUED, str(refused)[:64], item, recheck
        version = MessageTemplateVersion.objects.get(
            template__key=TEMPLATE, version=wording.version
        )
        subject, body = (
            wording.subject_for(application.reference),
            wording.display,
        )  # a draft carries its marker
        inputs = html_inputs(version, values) if wording.approved else {}

        def write():
            message = ApprovedMessage.objects.create(
                kind=ApprovedMessage.Kind.HOLD_NOTICE,
                application=application,
                recipient=recipient,
                template_version=version,
                frozen_subject=subject,
                frozen_body=body,
                content_sha256=canonical_digest(subject, body),
                authorized_by=actor,
                authority=ApprovedMessage.Authority.SYSTEM_POLICY,
                reproducible_inputs=inputs,
            )
            enqueue_send(
                message, 0
            )  # the P2 sender sends it later, outside this transaction, with its own checks
            event(
                application,
                "hold_notice_queued",
                {
                    "decision": str(decision.public_id),
                    "send_ref": str(message.send_ref),
                    "template_version": version.version,
                    "template_sha256": version.content_sha256,
                    "draft": wording.draft,
                },
                actor_ref=actor,
            )
            for open_one in StaffItem.objects.filter(
                application=application,
                reason_code=REFUSED_ITEM,
                status=StaffItem.Status.OPEN,
            ):
                resolve_item(
                    open_one,
                    code="hold_notice_queued",
                    actor_ref=actor,
                    effects={"send_ref": str(message.send_ref)},
                    actor_type=ApplicationEvent.ActorType.SYSTEM,
                )

        return Status.DONE, "", write, None
