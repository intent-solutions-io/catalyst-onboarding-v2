"""The "send verification" handler (005 S1.2 Send, S1.4; D-20, D-24): queued intake work becomes one
verification invitation sent through the configured mail backend and one recorded outcome.

Order of work for one claim:
1. Eligibility check, one short transaction, locking the application then the challenge (intake's order):
   the claim still holds the lease; the subject is an application that exists; the input names a challenge
   of that application whose idempotency key matches the action; automation is not paused; the challenge
   is unused, not superseded and unexpired by the database clock; and the application is open with contact
   not yet verified. The recipient is the challenge's address at issue. The transaction then commits, so
   no row lock is held while sending.
2. Send through Django's mail backend (a local sink in every allowed environment; production is not one yet;
   config.guards). A backend error or a send count other than one is a failed attempt, never a success.
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

The expiry of the only link (9kg.66, 029 appendix B GAP 1): `verification_expiry_sweep`, a recurring action like the
session clean-up, opens one `verification_expired` staff item for each open, unverified application whose active
challenge has expired by the database clock, once per challenge; the staff resend resolves it. It changes nothing on
the S1 path: no extra action is queued by intake or by a send.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from email.utils import make_msgid
from importlib import import_module
from string import Template
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.db.models.functions import Now

from applications import notices
from applications.links import verification_link
from applications.models import OPEN_STAGES, Application, ApplicationEvent, ContactChallenge
from applications.services import SEND_VERIFICATION, send_verification_key
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

from .models import OutboundMessage

logger = logging.getLogger(__name__)
Status = PendingAction.Status

# 9kg.66: the recurring sweep and the staff item it opens.
EXPIRY_SWEEP = "verification_expiry_sweep"
EXPIRY_SWEEP_SUBJECT = ("system", uuid.UUID("00000000-0000-0000-0000-00000000cccc"))
EXPIRED_ITEM = "verification_expired"
EXPIRY_SWEEP_BATCH = 200  # per pass, oldest expiry first; the rest wait for the next pass

# 9kg.80: the wording is the `verification_invitation` message template (migration 0020), approved by the owner on
# the template screen and rendered through applications.notices with the link as its one variable. A live environment
# sends only an approved, non-synthetic version; with none it returns the action to the queue under the reason code and
# looks again after WORDING_RECHECK_SECONDS (intake is withheld meanwhile, applications.views). The outbound row records
# the version and a digest prefix (`<version>:<24 hex>`, the column holds 32), the `verification_sent` event the full
# digest. Where a draft may be shown and the test reset removed the row, the seeded draft itself is used, marked.
TEMPLATE_KEY = notices.VERIFICATION
SEED = import_module("correspondence.migrations.0020_verification_template")
SUBJECT = SEED.SUBJECT
WORDING_RECHECK_SECONDS = 3600


def wording(link: str) -> notices.Wording:
    """The verification mail for this link, or `notices.Unavailable` with a reason code."""
    try:
        return notices.wording(TEMPLATE_KEY, {"link": link})
    except notices.Unavailable as refused:
        if str(refused) != f"{TEMPLATE_KEY}_missing":  # raised only where a draft may be shown
            raise
    return notices.Wording(TEMPLATE_KEY, 1, SEED.digest(SEED.SUBJECT, SEED.BODY), SEED.SUBJECT,
                           Template(SEED.BODY).substitute(link=link), approved=False)


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
    due_seconds: float | None = None  # for a deferral (QUEUED): when to look again


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
        try:
            mail = wording(verification_link(decision.challenge_public_id))
        except notices.Unavailable as refused:  # 9kg.80: no approvable wording here; wait for the owner's approval
            self._stop(claim, Stop(Status.QUEUED, str(refused), WORDING_RECHECK_SECONDS))
            return
        message_id = make_msgid(idstring=f"a{claim.attempt}", domain=urlsplit(settings.CATALYST_PUBLIC_BASE_URL).hostname)
        # bgl.11: multipart/alternative (text, then HTML) when the approved version has an HTML part; text otherwise.
        message = (EmailMultiAlternatives if mail.html else EmailMessage)(
            subject=mail.subject,
            body=mail.display,
            to=[decision.recipient],
            headers={"Message-ID": message_id},
        )
        if mail.html:
            message.attach_alternative(mail.html, "text/html")
        outbound = dict(
            application_id=decision.application_id, pending_action_id=claim.id, attempt_number=claim.attempt,
            template_key=TEMPLATE_KEY, template_version=f"{mail.version}:{mail.sha256[:24]}", recipient=decision.recipient,
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
            self.record(claim, "verification_sent", {"attempt": claim.attempt, "template_version": mail.version,
                                                     "template_sha256": mail.sha256, "draft": mail.draft})

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
            from .staff_items import hard_bounce_open

            if hard_bounce_open(application):  # every send path, S1 verification included (9kg.3)
                return Stop(Status.QUEUED, "hard bounce open", settings.CATALYST_HARD_BOUNCE_RECHECK_SECONDS)
            return Proceed(application.pk, challenge.email_at_issue, challenge.public_id)

    def _stop(self, claim, decision: Stop) -> None:
        if decision.status == Status.QUEUED:
            logger.info("action %s: %s; returned to the queue", claim.id, decision.reason)
            due = None if decision.due_seconds is None else timedelta(seconds=decision.due_seconds)
            ledger.finish(claim, self, status=Status.QUEUED, error=decision.reason, refund_attempt=True, due_in=due)
            return
        event = "verification_send_refused" if decision.status == Status.FAILED else "verification_send_skipped"
        if ledger.finish(claim, self, status=decision.status, error=decision.reason,
                         write=lambda: self.record(claim, event, {"attempt": claim.attempt, "reason": decision.reason})):
            if decision.status == Status.FAILED:
                logger.warning("action %s refused: %s; nothing sent", claim.id, decision.reason)
            else:
                logger.info("action %s: %s; nothing sent", claim.id, decision.reason)


# --- 9kg.66: the expiry of the only link -------------------------------------------------------------------------

def expired_item_key(challenge_public_id) -> str:
    return f"challenge:{challenge_public_id}"


def _expired_active():
    """Active challenges (unused, not superseded) that have expired by the database clock, of open applications whose
    contact is unverified: the applicant holds no working link. There is at most one active challenge per application
    (issuance supersedes the previous one), so this is the application's last link."""
    return ContactChallenge.objects.filter(used_at__isnull=True, superseded_at__isnull=True, expires_at__lte=Now(),
                                           application__contact_verified_at__isnull=True,
                                           application__stage__in=OPEN_STAGES)


SUPERSEDED = "verification_superseded"


def close_moot_items() -> int:
    """Review of PR #97: an open `verification_expired` item whose application has since been verified or has left the
    open stages has nothing left to do; it is resolved by the system (code `verification_superseded`), with the
    application locked. Returns the number resolved."""
    from .models import StaffItem
    from .staff_items import resolve_item

    moot = (StaffItem.objects.filter(reason_code=EXPIRED_ITEM, status=StaffItem.Status.OPEN)
            .filter(Q(application__contact_verified_at__isnull=False) | ~Q(application__stage__in=OPEN_STAGES))
            .values_list("pk", "application_id"))
    closed = 0
    for item_id, application_id in list(moot):
        with transaction.atomic():
            application = Application.objects.select_for_update(of=("self",)).get(pk=application_id)
            item = StaffItem.objects.select_for_update(of=("self",)).get(pk=item_id)
            if item.status != StaffItem.Status.OPEN or (
                    application.contact_verified_at is None and application.stage in OPEN_STAGES):
                continue
            reason = "contact_verified" if application.contact_verified_at is not None else "application_closed"
            if resolve_item(item, code=SUPERSEDED, actor_ref=f"system:{EXPIRY_SWEEP}",
                            effects={"reason": EXPIRED_ITEM, "because": reason},
                            actor_type=ApplicationEvent.ActorType.SYSTEM):
                closed += 1
    return closed


def open_expired_link_items(limit: int = EXPIRY_SWEEP_BATCH) -> int:
    """First close the items that became moot (`close_moot_items`); then open one `verification_expired` item per
    expired active challenge, re-checked with the application locked (the lock order of intake and confirmation). Once
    per challenge: an item for it, open or resolved, is never opened again, so a re-run, a redelivered sweep or an
    acknowledged item adds nothing. Returns the number opened."""
    from .models import StaffItem
    from .staff_items import open_item

    close_moot_items()

    seen = set(StaffItem.objects.filter(reason_code=EXPIRED_ITEM).values_list("dedupe_key", flat=True))
    candidates = [(c.application_id, c.public_id) for c in _expired_active().order_by("expires_at", "id")
                  if expired_item_key(c.public_id) not in seen][:limit]
    opened = 0
    for application_id, challenge_id in candidates:
        with transaction.atomic():
            application = Application.objects.select_for_update(of=("self",)).filter(pk=application_id).first()
            key = expired_item_key(challenge_id)
            if (application is None or not _expired_active().filter(public_id=challenge_id, application=application).exists()
                    or StaffItem.objects.filter(reason_code=EXPIRED_ITEM, dedupe_key=key).exists()):
                continue  # confirmed, reissued or closed meanwhile, or another sweep opened it
            open_item(EXPIRED_ITEM, key, application=application)
            opened += 1
    return opened


def schedule_expiry_sweep(n: int | None = None, delay: float = 0.0) -> bool:
    """Queue the next sweep unless one is already queued or running; True when it queued one. Idempotent: the
    deployment runs it after migrate (`manage.py schedule_verification_sweep`), and each pass queues its successor."""
    active = PendingAction.objects.filter(kind=EXPIRY_SWEEP, status__in=(Status.QUEUED, Status.RUNNING))
    if n is None and active.exists():
        return False
    n = n if n is not None else PendingAction.objects.filter(kind=EXPIRY_SWEEP).count() + 1
    try:
        with transaction.atomic():
            PendingAction.objects.create(kind=EXPIRY_SWEEP, subject_type=EXPIRY_SWEEP_SUBJECT[0],
                                         subject_id=EXPIRY_SWEEP_SUBJECT[1], input_ref="",
                                         idempotency_key=f"{EXPIRY_SWEEP}:{n}", due_at=Now() + timedelta(seconds=delay))
    except IntegrityError:
        return False
    return True


def _sweep_number(claim) -> int:
    key = PendingAction.objects.filter(pk=claim.id).values_list("idempotency_key", flat=True).first() or ""
    try:
        return int(key.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return 0


class SweepExpiredVerification:
    """9kg.66 (`verification_expiry_sweep`): every CATALYST_VERIFICATION_SWEEP_SECONDS, open the expired-link items and
    queue the next pass. It sends nothing; it opens staff items only, so it is not automation and an application's
    pause does not hold it (the item tells staff about a paused case too); the restore hold stops it like everything."""

    kind = EXPIRY_SWEEP
    redeliverable = True  # internal and idempotent: a repeat finds the items it already opened
    automated = False

    def lock_subject(self, claim) -> None:
        pass

    def record(self, claim, kind, data) -> None:
        """The chain survives a final failure: the next sweep is queued anyway."""
        if kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final")):
            schedule_expiry_sweep(_sweep_number(claim) + 1, settings.CATALYST_VERIFICATION_SWEEP_SECONDS)

    def run(self, claim) -> None:
        opened = open_expired_link_items()
        if opened:
            logger.info("verification expiry sweep: %s staff item(s) opened", opened)
        n = _sweep_number(claim)
        ledger.finish(claim, self, status=Status.DONE,
                      write=lambda: schedule_expiry_sweep(n + 1, settings.CATALYST_VERIFICATION_SWEEP_SECONDS))
