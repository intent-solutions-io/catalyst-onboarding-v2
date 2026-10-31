"""The receipt at the first submission (bead bgl.5; 034 rows 7 and 9, section 1.2 steps 1 and 2).

The first generation answers every new request at once with a receipt: subject `<static words> [CAT-XXXX-XXXX]`, the
reference, the date, the interest answer and how to reach us, and never a second one for a repeat from the same
address. v2 keeps its own address verification (005 S1.2), so the receipt comes in one of two shapes
(`applications.notices.receipt_mode`, from CATALYST_INTAKE_RECEIPT and CATALYST_RECEIPT_IS_VERIFICATION):

- "separate": the `send_receipt` action intake queues for a new application (applications.services), handled here: one
  `intake_receipt` mail, before and independent of the confirm-your-address mail;
- "verification": no extra action; the verification mail is rendered from `intake_receipt_confirm`, the receipt with
  the one-time link (correspondence.verification), so the applicant's first and only intake mail looks like the first
  generation's receipt and still confirms the address.

The wording is a message template the owner approves (D-29); a live environment sends nothing unapproved or synthetic
and withholds intake meanwhile (applications.notices.receipt_withheld). Where a draft may be shown and the test reset
removed the row, the seeded draft itself is used, marked, as for the verification mail.

Values (the templates' exact allow-list, `notices.RECEIPT_VARIABLES`): `greeting` ("Hello" and the first word of the
name when it is plainly a name, else "Hello", the first generation's rule: the name is free text and the mail is signed
by our domain), `reference` (the application's), `submitted_on` (the version's receipt date) and `interest` (the
interest answer's label, when the form has the field, else empty). The subject is the template's static subject with
the reference appended by this sender (`subject_reference`, 016 A1 amended for the reference alone).

Sending is S1's shape (correspondence.verification): an eligibility check under the application lock, the mail through
Django's backend with no lock held, the result in one lease-fenced transaction. A receipt is redeliverable like the
verification mail (D-20): an attempt interrupted after the backend accepted it may be followed by the identical receipt.
"""

import logging
import unicodedata
from dataclasses import dataclass
from datetime import timedelta
from email.utils import make_msgid
from importlib import import_module
from string import Template
from urllib.parse import urlsplit
from uuid import UUID

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import connection, transaction
from django.db.models.functions import Now

from applications import notices
from applications.models import OPEN_STAGES, Application, ApplicationEvent, SubmissionVersion
from applications.services import SEND_RECEIPT, send_receipt_key
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

from .models import OutboundMessage

logger = logging.getLogger(__name__)
Status = PendingAction.Status
SEED = import_module("correspondence.migrations.0022_intake_receipt_templates")
WORDING_RECHECK_SECONDS = 3600
GREETING_MAX = 40
_GREETING_PUNCTUATION = frozenset("-'’")


def greeting(name: str | None) -> str:
    """"Hello" and the first word of the name when it is plainly a name (letters with their combining marks, hyphens
    and apostrophes, at most GREETING_MAX characters, at least one letter), else "Hello"."""
    words = (name or "").split()
    first = words[0] if words else ""
    plain = (first and len(first) <= GREETING_MAX and any(unicodedata.category(ch).startswith("L") for ch in first)
             and all(unicodedata.category(ch)[0] in "LM" or ch in _GREETING_PUNCTUATION for ch in first))
    return f"Hello {first}" if plain else "Hello"


def _interest_label(code: str) -> str:
    """The interest answer as words. The form's labels are the form's (bgl.3); without them the stored code is shown."""
    from applications import forms

    return getattr(forms, "INTEREST_LABELS", {}).get(code, code) if code else ""


def values(application, version) -> dict:
    fields = version.submitted_fields or {}
    return {"greeting": greeting(fields.get("name") or application.display_name), "reference": application.reference,
            "submitted_on": version.received_at.strftime("%d %B %Y"),
            "interest": _interest_label(str(fields.get("interest_track") or ""))}


def values_for(application_id: int) -> dict:
    """The receipt values for the application's newest version (the verification mail in "verification" mode)."""
    application = Application.objects.get(pk=application_id)
    return values(application, application.versions.order_by("-version_number").first())


def wording(key: str, given: dict) -> notices.Wording:
    """The receipt mail for these values, or `notices.Unavailable` with a reason code."""
    try:
        return notices.wording(key, given)
    except notices.Unavailable as refused:
        if str(refused) != f"{key}_missing":  # raised only where a draft may be shown
            raise
    subject, body, *_ = SEED.SEEDS[key]
    return notices.Wording(key, 1, SEED.digest(subject, body), subject, Template(body).substitute(given), approved=False,
                           subject_reference=True)


@dataclass(frozen=True)
class Proceed:
    application_id: int
    recipient: str
    reference: str
    values: dict


@dataclass(frozen=True)
class Stop:
    status: str
    reason: str  # a reason code: no address or wording
    due_seconds: float | None = None


def _after_send(claim) -> None:
    """Test seam: called after the backend accepted the receipt, before the result is recorded."""


class SendReceipt:
    kind = SEND_RECEIPT
    redeliverable = True  # D-20, as the verification mail: an identical receipt may follow an interrupted attempt
    automated = True

    def lock_subject(self, claim) -> None:
        if claim.subject_type == "application":
            Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        """A history event on the subject application, if there is one. Never an address or wording."""
        if claim.subject_type != "application":
            return
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        if application is not None:
            ApplicationEvent.objects.create(application=application, kind=kind, actor_type=ApplicationEvent.ActorType.SYSTEM,
                                            actor_ref=f"pending_action:{claim.id}", data=data)

    def run(self, claim) -> None:
        decision = self.check(claim)
        if decision is None:
            logger.warning("action %s attempt %s: lease lost before sending; nothing sent", claim.id, claim.attempt)
            return
        if isinstance(decision, Stop):
            self._stop(claim, decision)
            return
        if connection.in_atomic_block:
            raise RuntimeError("refusing to send inside a transaction")
        try:
            mail = wording(notices.RECEIPT, decision.values)
        except notices.Unavailable as refused:  # no approvable wording here; wait for the owner's approval
            self._stop(claim, Stop(Status.QUEUED, str(refused), WORDING_RECHECK_SECONDS))
            return
        message_id = make_msgid(idstring=f"r{claim.attempt}", domain=urlsplit(settings.CATALYST_PUBLIC_BASE_URL).hostname)
        message = EmailMessage(subject=mail.subject_for(decision.reference), body=mail.display, to=[decision.recipient],
                               headers={"Message-ID": message_id})
        outbound = dict(application_id=decision.application_id, pending_action_id=claim.id, attempt_number=claim.attempt,
                        template_key=mail.key, template_version=f"{mail.version}:{mail.sha256[:24]}",
                        recipient=decision.recipient, message_id=message_id)
        try:
            sent = message.send(fail_silently=False)
            if sent != 1:
                raise RuntimeError(f"sent {sent}")
        except Exception as exc:
            error = type(exc).__name__
            logger.warning("action %s attempt %s: receipt send failed (%s)", claim.id, claim.attempt, error)

            def write_failure():
                OutboundMessage.objects.create(status=OutboundMessage.Status.FAILED, **outbound)
                self.record(claim, "receipt_send_failed", {"attempt": claim.attempt, "error": error, "final": claim.final})

            ledger.fail_or_retry(claim, self, f"send failed: {error}", write=write_failure)
            return
        _after_send(claim)

        def write_success():
            OutboundMessage.objects.create(status=OutboundMessage.Status.ACCEPTED, sent_at=Now(), **outbound)
            self.record(claim, "receipt_sent", {"attempt": claim.attempt, "template_version": mail.version,
                                                "template_sha256": mail.sha256, "draft": mail.draft})

        try:
            recorded = ledger.finish(claim, self, status=Status.DONE, write=write_success)
        except Exception as exc:  # sent, not recorded: lease recovery may redeliver the identical receipt (D-20)
            raise ledger.LeftForRecovery from exc
        if not recorded:
            logger.warning("action %s attempt %s: sent, but a newer claim owns the action", claim.id, claim.attempt)

    def check(self, claim) -> Proceed | Stop | None:
        refuse = lambda reason: Stop(Status.FAILED, reason)  # noqa: E731
        skip = lambda reason: Stop(Status.CANCELLED, reason)  # noqa: E731
        with transaction.atomic():
            if claim.subject_type != "application":
                return refuse("subject is not an application")
            try:
                version_id = UUID(claim.input_ref)
            except ValueError:
                return refuse("input is not a submission version")
            application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
            if application is None:
                return refuse("subject application not found")
            version = SubmissionVersion.objects.filter(public_id=version_id, application=application).first()
            if version is None:
                return refuse("version does not belong to the subject application")
            action = PendingAction.objects.filter(
                pk=claim.id, status=Status.RUNNING, lease_token=claim.lease_token
            ).values_list("idempotency_key", flat=True).first()
            if action is None:
                return None
            if action != send_receipt_key(application.public_ref):
                return refuse("idempotency key does not match the application")
            if AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
                return Stop(Status.QUEUED, "automation paused")
            if application.stage not in OPEN_STAGES or application.email_key.startswith("erased:"):
                return skip("application closed")
            from .staff_items import hard_bounce_open

            if hard_bounce_open(application):  # every send path (9kg.3)
                return Stop(Status.QUEUED, "hard bounce open", settings.CATALYST_HARD_BOUNCE_RECHECK_SECONDS)
            return Proceed(application.pk, application.email, application.reference, values(application, version))

    def _stop(self, claim, decision: Stop) -> None:
        if decision.status == Status.QUEUED:
            logger.info("action %s: %s; returned to the queue", claim.id, decision.reason)
            due = None if decision.due_seconds is None else timedelta(seconds=decision.due_seconds)
            ledger.finish(claim, self, status=Status.QUEUED, error=decision.reason, refund_attempt=True, due_in=due)
            return
        event = "receipt_send_refused" if decision.status == Status.FAILED else "receipt_send_skipped"
        if ledger.finish(claim, self, status=decision.status, error=decision.reason,
                         write=lambda: self.record(claim, event, {"attempt": claim.attempt, "reason": decision.reason})):
            logger.info("action %s: %s; no receipt sent", claim.id, decision.reason)
