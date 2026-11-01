"""The decline notice (oc4.11; 029 section 17.3; 016 section 10.19).

A recorded decline (`decisions.record_decision`) queues one `send_decline:<application>` action unless the
decision-maker chose, on the decision form and with a reason, to withhold the notice; the choice is part of the
decision record (`decision_inputs["decline_notice"]`). `SendDecline` runs it: one fenced transaction, automated (a
pause holds it) and redeliverable, because it sends nothing itself. It freezes the decline notice as an
`ApprovedMessage` of kind `decline` and queues its `send_message`, so the P2 sender delivers it under every P2 rule:
the three-phase exchange, the uncertain-send reconciliation, the hard-bounce block and the staff items for unknown,
exhausted, blocked, rejected and refused sends, which the decision-maker settles with the usual resend or abandon.
`correspondence.outbound.declined_notice` lets exactly this kind through to the terminal `declined` stage.

The wording is the `decline_notice` template (correspondence migration 0019), read through the same function as the
data notice (`applications.notices.wording`): only an approved, non-synthetic version in a live environment; in the
draft environments the newest draft with its visible marker. Its one variable is the display name, so no reason,
rationale or model output can ever reach the applicant. Wording that may not be used here is not an error: the action
looks again later and one staff item (`decline_notice_refused`) says why; it resolves itself once the notice is queued.

Refused without a send, and cancelled: a decision recorded before this handler existed (it made no choice about the
notice; such held actions were cancelled by migration 0019 and are never released), a withheld notice, an application
no longer declined, and a member with a first-generation agreement on file (030 Q8: never declined in v2; the
decision service already refuses that). A copy of the notice that left after a backup and is under review after a
restore defers the freeze, so a restore never sends a second notice by itself.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction

from applications import members, notices
from applications.models import Application, ApplicationEvent, Stage
from correspondence.models import ApprovedMessage, MessageTemplateVersion, StaffItem
from correspondence.outbound import enqueue_send, verified_address
from correspondence.rendering import canonical_digest, html_inputs
from correspondence.staff_items import event, open_item, resolve_item
from workflow import ledger
from workflow.models import PendingAction

from .models import QualificationDecision

KIND = "send_decline"
TEMPLATE = "decline_notice"
REFUSED_ITEM = "decline_notice_refused"
MEMBER_ITEM = "decline_notice_member_on_file"  # its own reason: cancelled for good, unlike a refusal that retries
SEND, WITHHOLD = "send", "withhold"
CHOICES = (SEND, WITHHOLD)
WITHHOLD_REASON_MIN, WITHHOLD_REASON_MAX = 10, 300
RESTORE_ITEM = "restore_effect_unknown_send"  # correspondence.restore: a copy left after the backup, under review
Status = PendingAction.Status


def key(application) -> str:
    return f"{KIND}:{application.public_ref}"


def enqueue(application, decision) -> PendingAction:
    """Inside the decision's transaction (decisions.record_decision)."""
    return PendingAction.objects.create(kind=KIND, subject_type="application", subject_id=application.public_ref,
                                        input_ref=str(decision.public_id), idempotency_key=key(application))


class SendDecline:
    kind = KIND
    redeliverable = True  # one fenced transaction that freezes and queues: nothing leaves the process here
    automated = True  # a paused application's notice waits for the resume, like every other automated mail

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if application is not None and (kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final"))):
            open_item(REFUSED_ITEM, f"decline:{application.public_ref}", application=application, pending_action_id=claim.id)

    def run(self, claim) -> None:
        with transaction.atomic():
            self.lock_subject(claim)
            status, error, write, due_in = self.decide(claim)
            ledger.finish(claim, self, status=status, error=error, write=write, due_in=due_in,
                          refund_attempt=status == Status.QUEUED)

    def decide(self, claim):
        actor = f"pending_action:{claim.id}"
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        if application is None:
            return Status.FAILED, "subject_application_not_found", None, None
        decision = QualificationDecision.objects.filter(public_id=claim.input_ref, application=application,
                                                        outcome="decline").first()
        if decision is None:
            return Status.FAILED, "decline_decision_not_found", None, None
        choice = (decision.decision_inputs or {}).get("decline_notice")
        if not isinstance(choice, dict) or choice.get("choice") not in CHOICES:
            return Status.CANCELLED, "decided_before_the_decline_notice", None, None
        if choice["choice"] == WITHHOLD:
            return Status.CANCELLED, "withheld_by_decision_maker", None, None
        if application.stage != Stage.DECLINED:
            return Status.CANCELLED, "application_not_declined", None, None

        def item():
            open_item(REFUSED_ITEM, f"decline:{application.public_ref}", application=application, pending_action_id=claim.id)

        if members.on_file(application) is not None:
            def member_item():
                open_item(MEMBER_ITEM, f"decline:{application.public_ref}", application=application, pending_action_id=claim.id)
            return Status.CANCELLED, "member_on_file", member_item, None  # 030 Q8: never declined in v2; staff are told
        if ApprovedMessage.objects.filter(application=application, kind=ApprovedMessage.Kind.DECLINE).exists():
            return Status.DONE, "already_queued", None, None  # one notice per declined application
        recheck = timedelta(seconds=settings.CATALYST_DECLINE_NOTICE_RECHECK_SECONDS)
        if StaffItem.objects.filter(application=application, reason_code=RESTORE_ITEM, status=StaffItem.Status.OPEN).exists():
            return Status.QUEUED, "sent_after_backup_pending_review", None, recheck
        recipient = verified_address(application)
        if recipient is None:
            return Status.QUEUED, "contact_not_verified", item, recheck
        try:
            wording = notices.wording(TEMPLATE, {"display_name": application.display_name})
        except notices.Unavailable as refused:
            return Status.QUEUED, str(refused)[:64], item, recheck
        version = MessageTemplateVersion.objects.get(template__key=TEMPLATE, version=wording.version)
        subject, body = wording.subject, wording.display  # a draft always carries its marker
        # bgl.11: an approved version with an HTML part is sent multipart; a draft goes as marked text only.
        inputs = html_inputs(version, {"display_name": application.display_name}) if wording.approved else {}

        def write():
            message = ApprovedMessage.objects.create(
                kind=ApprovedMessage.Kind.DECLINE, application=application, recipient=recipient, template_version=version,
                frozen_subject=subject, frozen_body=body, content_sha256=canonical_digest(subject, body),
                authorized_by=actor, authority=ApprovedMessage.Authority.SYSTEM_POLICY, reproducible_inputs=inputs)
            enqueue_send(message, 0)  # the P2 sender sends it later, outside this transaction, with its own checks
            event(application, "decline_notice_queued",
                  {"decision": str(decision.public_id), "send_ref": str(message.send_ref), "template_version": version.version,
                   "template_sha256": version.content_sha256, "draft": wording.draft}, actor_ref=actor)
            for open_one in StaffItem.objects.filter(application=application, reason_code=REFUSED_ITEM,
                                                     status=StaffItem.Status.OPEN):
                resolve_item(open_one, code="decline_notice_queued", actor_ref=actor, effects={"send_ref": str(message.send_ref)},
                             actor_type=ApplicationEvent.ActorType.SYSTEM)
        return Status.DONE, "", write, None
