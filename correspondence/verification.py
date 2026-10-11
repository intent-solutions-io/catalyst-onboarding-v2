"""The "send verification" handler (005 S1.2 Send, S1.4; D-20, D-24): queued intake work becomes one
verification invitation in the local mail sink and one recorded outcome.

Order of work for one claim:
1. Eligibility check, one short transaction, locking the application then the challenge (intake's order):
   the claim still holds the lease; the subject is an application that exists; the input names a challenge
   of that application whose idempotency key matches the action; automation is not paused; the challenge
   is unused, not superseded and unexpired by the database clock; and the application is open with contact
   not yet verified. The recipient is the challenge's address at issue. The transaction then commits, so
   no row lock is held while sending.
2. Send through Django's mail backend (a local sink outside production; config.guards). A backend error or
   a send count other than one is a failed attempt, never a success.
3. Result through `ledger.finish`: completion, the OutboundMessage for this attempt and the history event
   in one transaction fenced by the lease token.

Outcomes that send nothing: a superseded, used or expired challenge, or contact already verified, ends
`cancelled` (terminal, not retried) with an event. A missing or mismatched subject, input or key ends
`failed` (terminal, not retried), logged with a reason code and kept for staff. A pause found at the check
puts the action back in the queue without counting the attempt; the claim query skips it while paused.

Boundary, stated rather than hidden: the check is the last word before sending. A repeat submission,
pause or confirmation that commits after the check, or a lease lost while the message is in flight, cannot
recall it; a stale worker's result is then discarded by the fence, and the confirmation step (S1-T6)
independently rejects any challenge that is no longer valid. Delivery to the sink is at least once (D-20):
an interrupted attempt may be followed by the identical invitation. Sink acceptance is not inbox delivery,
and nothing here claims exactly-once external effects.
"""

import logging
from dataclasses import dataclass
from email.utils import make_msgid
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import connection, transaction
from django.db.models import Q
from django.db.models.functions import Now

from applications.links import verification_link
from applications.models import OPEN_STAGES, Application, ApplicationEvent, ContactChallenge
from applications.services import SEND_VERIFICATION, send_verification_key
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

from .models import OutboundMessage

logger = logging.getLogger(__name__)
Status = PendingAction.Status

TEMPLATE_KEY = "verification_invitation"
TEMPLATE_VERSION = "s1-synthetic-1"  # placeholder wording (POL-17)
SUBJECT = "Confirm your email address"
BODY = (
    "Hello,\n\n"
    "Someone asked to start an application with this email address. If it was you, open this link to confirm"
    " the address:\n\n{link}\n\n"
    "If it was not you, you can ignore this message.\n"
)


class SendCountMismatch(Exception):
    pass


@dataclass(frozen=True)
class Proceed:
    application_id: int
    recipient: str
    challenge_public_id: UUID


@dataclass(frozen=True)
class Stop:
    status: str
    reason: str  # a reason code: no address, token or database text


def _after_send(claim) -> None:
    """Test seam (TEST-S1-07): called after the sink accepted the message, before the result is recorded."""


class SendVerification:
    kind = SEND_VERIFICATION
    redeliverable = True  # D-20, this kind only
    automated = True

    # --- ledger interface -------------------------------------------------------------------------------

    def lock_subject(self, claim) -> None:
        if claim.subject_type == "application":
            Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        """A history event on the subject application, if there is one. Never a token, link or address."""
        if claim.subject_type != "application":
            return
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        if application is not None:
            ApplicationEvent.objects.create(
                application=application, kind=kind, actor_type=ApplicationEvent.ActorType.SYSTEM,
                actor_ref=f"pending_action:{claim.id}", data=data,
            )

    def run(self, claim) -> None:
        decision = self.check(claim)
        if decision is None:  # the lease is already gone: another worker owns the action
            logger.warning("action %s attempt %s: lease lost before sending; nothing sent", claim.id, claim.attempt)
            return
        if isinstance(decision, Stop):
            self._stop(claim, decision)
            return
        if connection.in_atomic_block:
            raise RuntimeError("refusing to send inside a transaction")
        message_id = make_msgid(idstring=f"a{claim.attempt}", domain=urlsplit(settings.CATALYST_PUBLIC_BASE_URL).hostname)
        message = EmailMessage(
            subject=SUBJECT,
            body=BODY.format(link=verification_link(decision.challenge_public_id)),
            to=[decision.recipient],
            headers={"Message-ID": message_id},
        )
        outbound = dict(
            application_id=decision.application_id, pending_action_id=claim.id, attempt_number=claim.attempt,
            template_key=TEMPLATE_KEY, template_version=TEMPLATE_VERSION, recipient=decision.recipient,
            message_id=message_id,
        )
        try:
            sent = message.send(fail_silently=False)
            if sent != 1:
                raise SendCountMismatch(f"sent {sent}")
        except Exception as exc:
            error = type(exc).__name__
            logger.warning("action %s attempt %s: send failed (%s)", claim.id, claim.attempt, error)

            def write_failure():
                OutboundMessage.objects.create(status=OutboundMessage.Status.FAILED, **outbound)
                self.record(claim, "verification_send_failed", {"attempt": claim.attempt, "error": error, "final": claim.final})

            ledger.fail_or_retry(claim, self, f"send failed: {error}", write=write_failure)
            return
        _after_send(claim)

        def write_success():
            OutboundMessage.objects.create(status=OutboundMessage.Status.ACCEPTED, sent_at=Now(), **outbound)
            self.record(claim, "verification_sent", {"attempt": claim.attempt, "template_version": TEMPLATE_VERSION})

        try:
            recorded = ledger.finish(claim, self, status=Status.DONE, write=write_success)
        except Exception as exc:
            # The sink has the message; recording failed. Never report that as a failed send: leave the
            # action running for lease recovery, which may redeliver the identical invitation (D-20).
            raise ledger.LeftForRecovery from exc
        if not recorded:
            logger.warning("action %s attempt %s: sent, but a newer claim owns the action", claim.id, claim.attempt)

    # --- the eligibility check ----------------------------------------------------------------------------

    def check(self, claim) -> Proceed | Stop | None:
        refuse = lambda reason: Stop(Status.FAILED, reason)  # noqa: E731
        skip = lambda reason: Stop(Status.CANCELLED, reason)  # noqa: E731
        with transaction.atomic():
            if claim.subject_type != "application":
                return refuse("subject is not an application")
            try:
                challenge_id = UUID(claim.input_ref)
            except ValueError:
                return refuse("input is not a challenge reference")
            application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
            if application is None:
                return refuse("subject application not found")
            challenge = (
                ContactChallenge.objects.select_for_update(of=("self",))
                .filter(public_id=challenge_id)
                .annotate(unexpired=Q(expires_at__gt=Now()))
                .first()
            )
            if challenge is None or challenge.application_id != application.pk:
                return refuse("challenge does not belong to the subject application")
            action = PendingAction.objects.filter(
                pk=claim.id, status=Status.RUNNING, lease_token=claim.lease_token
            ).values_list("idempotency_key", flat=True).first()
            if action is None:
                return None
            if action != send_verification_key(challenge.public_id):
                return refuse("idempotency key does not match the challenge")
            if AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
                return Stop(Status.QUEUED, "automation paused")
            if challenge.used_at is not None:
                return skip("challenge already used")
            if challenge.superseded_at is not None:
                return skip("challenge superseded")
            if not challenge.unexpired:
                return skip("challenge expired")
            if application.contact_verified_at is not None or application.stage not in OPEN_STAGES:
                return skip("contact already verified or application closed")
            return Proceed(application.pk, challenge.email_at_issue, challenge.public_id)

    def _stop(self, claim, decision: Stop) -> None:
        if decision.status == Status.QUEUED:
            logger.info("action %s: %s; returned to the queue", claim.id, decision.reason)
            ledger.finish(claim, self, status=Status.QUEUED, error=decision.reason, refund_attempt=True)
            return
        event = "verification_send_refused" if decision.status == Status.FAILED else "verification_send_skipped"
        if ledger.finish(claim, self, status=decision.status, error=decision.reason,
                         write=lambda: self.record(claim, event, {"attempt": claim.attempt, "reason": decision.reason})):
            if decision.status == Status.FAILED:
                logger.warning("action %s refused: %s; nothing sent", claim.id, decision.reason)
            else:
                logger.info("action %s: %s; nothing sent", claim.id, decision.reason)
