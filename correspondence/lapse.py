"""The lapse and its reopening (bead bgl.7; parity inventory 034 row 21 and section 1.2 step 9). Synthetic wording only.

An applicant who stays quiet after the last follow-up is not kept waiting out loud. Ten quiet business days
(`CATALYST_LAPSE_AFTER_BUSINESS_DAYS`, Monday to Friday, workflow.business_days) after the last automated message of a
chain, the application moves to the `lapsed` stage with one closing note, and comes back the moment the applicant
returns. A lapse is not a decision: `lapsed` is an open stage (applications.models.OPEN_STAGES), nothing is withdrawn,
declined or cancelled at the provider, the email key stays held, and erasure and retention treat the application as
open. Only a reply or a signature reopens it; a repeat submission from the address is a revision of the open
application as before and reopens nothing.

Two triggers schedule the `lapse` action, each under its own unique key so one chain leads to at most one note:

- `lapse:question:<question>`: correspondence.scheduling creates it in the transaction that records the acceptance of
  the last clarification reminder (or of the question itself when no reminder is configured), beside the staff
  escalation that already exists. The E3 projection holds it while a reply is pending and cancels it with the question.
- `lapse:agreement:<instance>`: agreements.signing_reminder creates it once the signing reminder has been handed to the
  outbound path.

`Lapse` (`lapse`, automated, redeliverable: its whole effect is one fenced database transaction) locks the application,
then the question when there is one, and lapses only if every condition still holds: the stage is the one the trigger
waits in (`awaiting_answers` for a question, `agreements` for a signing wait); the question is still asked with no
reply pending, or the envelope is still issued and unsigned; automation is not paused; nothing trusted came from the
applicant since the action was scheduled; it is not quiet hours; and the completed-collection watermark is past the
due time (016 4.1), so an uncollected reply cannot be mistaken for silence. Then, in that transaction, the stage moves
to `lapsed` (applications.stages.transition records the stage it came from), the closing note is frozen from the
approved `lapse_note` template and its send queued (016 A2, A3). No approved version, or no verified address, defers the
lapse and opens one `lapse_note_refused` staff item: nothing applicant-facing goes out until the owner approves wording.
The note goes in the thread of the latest accepted automated message (correspondence.messages.thread_headers).

`reopen` runs inside the caller's transaction with the application locked: on a trusted reply (correspondence.inbound,
when the reply is associated) or on a signature the provider shows (agreements.completion.apply_read), the stage
returns to the one recorded by the lapse, with an `application_reopened` event saying what brought it back. The normal
automation then continues: the reply is processed, the completed envelope advances the agreements.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction

from applications.models import TERMINAL_STAGES, Application, ApplicationEvent, Stage
from applications.stages import StageConflict, transition
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

from . import association, reminders
from .models import ApprovedMessage, InboundMessage, Question
from .outbound import _freeze, current_template_version, enqueue_send, verified_address
from .reminders import Decision, collection_stale, quiet_until
from .rendering import TemplateRefused, render
from .scheduling import LAPSE
from .staff_items import event, open_item

Status = PendingAction.Status
LAPSE_TEMPLATE = "lapse_note"
LAPSED_EVENT = "application_lapsed"
REOPENED_EVENT = "application_reopened"
NOTE_REFUSED = "lapse_note_refused"
LAPSE_FAILED = "lapse_failed"
# The stage each trigger waits in; a lapse from any other stage is a stale action and cancels itself.
FROM_STAGE = {"question": Stage.AWAITING_ANSWERS, "agreement": Stage.AGREEMENTS}
REOPEN_FALLBACK = (
    Stage.AWAITING_DECISION
)  # a lapsed application whose lapse record is missing goes to a person


def trigger_of(input_ref: str) -> tuple[str, str]:
    kind, _, ref = input_ref.partition(":")
    return kind, ref


def heard_from_since(application, since) -> bool:
    """Whether a trusted human message from the applicant arrived after `since` (a reply is any sign of life)."""
    return InboundMessage.objects.filter(
        application=application,
        classification="human",
        trust_decision=association.TRUSTED,
        received_at__gt=since,
    ).exists()


def reopen(
    application,
    *,
    trigger: str,
    actor_ref: str,
    actor_type: str = ApplicationEvent.ActorType.SYSTEM,
) -> bool:
    """Inside the caller's transaction with the application locked: back to the stage it lapsed from. False when the
    application is not lapsed."""
    if application.stage != Stage.LAPSED:
        return False
    lapsed = application.events.filter(kind=LAPSED_EVENT).order_by("-id").first()
    prior = (lapsed.data or {}).get("from") if lapsed is not None else None
    data = {"trigger": trigger}
    if prior not in FROM_STAGE.values():
        prior, data["prior_unknown"] = REOPEN_FALLBACK, True
    try:
        transition(
            application.pk,
            (Stage.LAPSED,),
            prior,
            event_kind=REOPENED_EVENT,
            data=data,
            actor_type=actor_type,
            actor_ref=actor_ref,
        )
    except StageConflict:
        return False
    application.stage = prior
    return True


class Lapse:
    kind = LAPSE
    automated = True
    redeliverable = (
        True  # one fenced transaction: nothing external happens in this handler
    )

    def lock_subject(self, claim) -> None:
        """Application, then the question (016 section 5); an agreement instance is read, never locked here."""
        application = (
            Application.objects.select_for_update(of=("self",))
            .filter(public_ref=claim.subject_id)
            .first()
        )
        kind, ref = trigger_of(claim.input_ref)
        if application is not None and kind == "question":
            Question.objects.select_for_update(of=("self",)).filter(
                public_id=ref, application=application
            ).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if kind == "action_attempts_exhausted" or (
            kind == "action_failed" and data.get("final")
        ):
            open_item(
                LAPSE_FAILED,
                claim.input_ref,
                application=application,
                pending_action_id=claim.id,
            )

    def run(self, claim) -> None:
        with transaction.atomic():
            self.lock_subject(claim)
            decision = self.decide(claim)
            ledger.finish(
                claim,
                self,
                status=decision.status,
                error=decision.reason,
                write=decision.write,
                due_in=decision.due_in,
                refund_attempt=decision.refund,
            )

    def _subject_still_waits(
        self, application, trigger: str, ref: str
    ) -> Decision | None:
        if trigger == "question":
            question = Question.objects.filter(
                public_id=ref, application=application
            ).first()
            if question is None:
                return Decision(Status.FAILED, "question_not_found")
            if question.status in (
                Question.Status.SATISFIED,
                Question.Status.WITHDRAWN,
            ):
                return Decision(Status.CANCELLED, f"question_{question.status}")
            if (
                question.status == Question.Status.REPLY_PENDING
                or question.reply_links.filter(state="pending").exists()
            ):
                return Decision(Status.HELD, "reply_pending", refund=True)
            return None
        from agreements.models import (
            AgreementInstance,
        )  # agreements builds on correspondence; imported here only

        instance = AgreementInstance.objects.filter(
            public_id=ref, application=application
        ).first()
        if instance is None:
            return Decision(Status.FAILED, "agreement_not_found")
        if (
            instance.issue_status != "issued"
            or instance.signing_status != "not_started"
            or instance.replaced_at
        ):
            return Decision(
                Status.CANCELLED, "agreement_moved"
            )  # signed, declined, cancelled or replaced meanwhile
        return None

    def decide(self, claim) -> Decision:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        trigger, ref = trigger_of(claim.input_ref)
        if application is None or trigger not in FROM_STAGE:
            return Decision(Status.FAILED, "lapse_trigger_not_found")
        if application.stage in TERMINAL_STAGES:
            return Decision(Status.CANCELLED, "application_closed")
        if application.stage == Stage.LAPSED:
            return Decision(Status.CANCELLED, "already_lapsed")
        if application.stage != FROM_STAGE[trigger]:
            return Decision(Status.CANCELLED, "stage_moved")
        waiting = self._subject_still_waits(application, trigger, ref)
        if waiting is not None:
            return waiting
        if AutomationPause.objects.filter(
            subject_type="application", subject_id=application.public_ref
        ).exists():
            return Decision(
                Status.QUEUED,
                "automation_paused",
                refund=True,
                due_in=timedelta(seconds=settings.CATALYST_WORKER_POLL_SECONDS),
            )
        row = (
            PendingAction.objects.filter(pk=claim.id)
            .values("due_at", "created_at", "idempotency_key")
            .first()
        )
        from firstgen.signing_cadence import quiet_since

        if heard_from_since(
            application, quiet_since(application, claim.id, row["created_at"])
        ):
            return Decision(Status.CANCELLED, "applicant_replied")
        now = reminders.db_now()
        quiet = quiet_until(now)
        if (
            quiet is not None
        ):  # the closing note is mail to the applicant: quiet hours hold it
            return Decision(
                Status.QUEUED, "quiet_hours", due_in=quiet - now, refund=True
            )
        if collection_stale(row["due_at"]):
            retry = timedelta(seconds=settings.CATALYST_REMINDER_STALE_RETRY_SECONDS)
            if not claim.final:
                return Decision(
                    Status.QUEUED, "watermark_stale", due_in=retry
                )  # counts toward the bound
            return Decision(
                Status.QUEUED,
                "watermark_stale",
                due_in=retry,
                refund=True,
                write=lambda: open_item(
                    "collector_stale",
                    row["idempotency_key"],
                    application=application,
                    pending_action_id=claim.id,
                ),
            )
        refused = lambda reason: Decision(  # noqa: E731  (as for a reminder: a configuration problem waits for staff)
            Status.QUEUED,
            reason,
            refund=True,
            due_in=timedelta(seconds=settings.CATALYST_REMINDER_STALE_RETRY_SECONDS),
            write=lambda: open_item(
                NOTE_REFUSED,
                claim.input_ref,
                application=application,
                pending_action_id=claim.id,
            ),
        )
        recipient = verified_address(application)
        version = current_template_version(LAPSE_TEMPLATE)
        if recipient is None:
            return refused("contact_not_verified")
        if version is None:
            return refused("no_approved_lapse_note_template")
        values = {"display_name": application.display_name}
        try:
            render(version, values)
        except TemplateRefused:
            return refused("lapse_note_content_refused")
        if version.secret_bearing:
            return refused("secret_bearing_lapse_note_template")
        actor = f"pending_action:{claim.id}"

        def write():
            transition(
                application.pk,
                (FROM_STAGE[trigger],),
                Stage.LAPSED,
                event_kind=LAPSED_EVENT,
                data={"trigger": f"{trigger}:{ref}"},
                actor_ref=actor,
            )
            message = _freeze(
                application,
                ApprovedMessage.Kind.LAPSE_NOTE,
                recipient,
                version,
                values,
                actor,
                ApprovedMessage.Authority.SYSTEM_POLICY,
            )
            enqueue_send(message, 0)
            event(
                application,
                "lapse_note_queued",
                {"trigger": f"{trigger}:{ref}", "send_ref": str(message.send_ref)},
                actor_ref=actor,
            )

        return Decision(Status.DONE, write=write)
