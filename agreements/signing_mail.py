"""The service-sent signing link (bgl.8; 034 section 2.3 rows 27 and 28; 021 step 3 under distribution "service").

Under CATALYST_AGREEMENT_DISTRIBUTION "service" the envelope is created and distributed with `distributionMethod: NONE`,
so the provider mails nobody, and this handler (`send_signing_link`, queued by `handlers._start_sweep` when an envelope
becomes issued) sends the applicant the link from Catalyst's own sender: for the NDA the `agreement_link_nda` template,
for the User Agreement the branded cover `agreement_link_user_agreement`, both approved by the owner on the template
screen (correspondence migration 0021; D-29). The first generation sent exactly these two mails.

The link is `<CATALYST_AGREEMENT_SIGNING_BASE_URL>/sign/<token>`, the applicant's own signing token read from the
provider at send time (`provider.signing_token`): it is the applicant's credential, so the template is secret-bearing,
the mail is built and sent in memory, and no record, event or log ever carries the token or the link (021 section 6).
What is recorded: the outbound attempt (template, version, digest prefix, recipient, message id, outcome) and a history
event with identifiers.

Checks before a send, with the application and instance locked: the claim holds its lease and its key names this
instance and series; automation is not paused (the mail waits); the agreements are not stopped and no cancel is
requested; the instance is issued and the applicant has not signed; the recipient is still the verified address; no hard
bounce is open (9kg.3). The provider read at send time is the last word: a recipient already SIGNED gets no link.

At least once, like the verification mail (D-20): an interrupted attempt may be followed by the identical link; the
token is the same one, so a repeat discloses nothing new. The series number is the seam for the signing reminder
(bgl.7): series 0 is the first delivery, a reminder is `enqueue_signing_link(instance, series=n)`; this handler already
skips once the applicant has signed. Under distribution "provider" the action is never queued, and a queued one skips.

The signing reminder (agreements.signing_reminder, bgl.7) asks `available()` and calls `resend_link` inside its fenced
transaction: under distribution "service" that queues this same send as series n (database rows only, no provider or
SMTP call, so the reminder stays redeliverable) and returns its key as the send reference; under "provider" there is no
service path that sends the link again (a second distribute of a PENDING envelope is NOT VERIFIED), so it returns
`NOT_AVAILABLE` and the reminder records that the applicant was not reminded.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from email.utils import make_msgid
from importlib import import_module
from string import Template
from urllib.parse import urlsplit

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, connection, transaction
from django.db.models.functions import Now
from django.views.decorators.debug import sensitive_variables

from applications import notices
from applications.models import Application
from config.mail import from_header, reply_to
from correspondence.messages import only_duplicate_key, verified_address
from correspondence.models import OutboundMessage
from correspondence.staff_items import event, hard_bounce_open, open_item
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

from . import provider
from .models import AgreementInstance

logger = logging.getLogger(__name__)
Status = PendingAction.Status

KIND = "send_signing_link"
TEMPLATE_PREFIX = "agreement_link_"
LINK_SEND_FAILED = "agreement_link_send_failed"  # the staff item when the mail could not be sent or the signer was not found
WORDING_RECHECK_SECONDS = 3600
SEED = import_module("correspondence.migrations.0021_agreement_link_templates")


def template_key(type_key: str) -> str:
    return f"{TEMPLATE_PREFIX}{type_key}"


def action_key(instance, series: int) -> str:
    return f"{KIND}:{instance.public_id}:{series}"


def enqueue_signing_link(instance, series: int = 0) -> PendingAction | None:
    """Queue one link send for `instance`; `series` 0 is the first delivery, n >= 1 a reminder (bgl.7's seam). A
    repeat of the same series is a no-op (the key is unique)."""
    try:
        with transaction.atomic():
            return PendingAction.objects.create(
                kind=KIND, subject_type="application", subject_id=instance.application.public_ref,
                input_ref=str(instance.public_id), idempotency_key=action_key(instance, series),
                max_attempts=settings.CATALYST_MAIL_SEND_ATTEMPTS)
    except IntegrityError as exc:
        only_duplicate_key(exc)
        return None


NOT_AVAILABLE = "no_service_signing_mail"  # the reminder's outcome when the service does not send the link itself


def available() -> bool:
    """Whether the service sends the signing link itself (bgl.8): only under distribution "service"."""
    return settings.CATALYST_AGREEMENT_DISTRIBUTION == "service"


def resend_link(instance, *, actor_ref: str, series: int = 1) -> str:
    """The signing reminder's seam (bgl.7): inside the caller's transaction, queue the link mail once more for
    `instance` as `series` (n >= 1; the reminder's number) and return its key as the send reference. A repeat of the
    same series queues nothing and returns the same key. `NOT_AVAILABLE` when the service does not send the link
    (distribution "provider"). `actor_ref` is the reminder's; the send records its own history when it runs."""
    if not available():
        return NOT_AVAILABLE
    if series < 1:
        raise ValueError("a reminder is series 1 or later; series 0 is the first delivery")
    enqueue_signing_link(instance, series=series)
    return action_key(instance, series)


def signing_link(token: str) -> str:
    return f"{settings.CATALYST_AGREEMENT_SIGNING_BASE_URL.rstrip('/')}/sign/{token}"


def wording(type_key: str, display_name: str, link: str) -> notices.Wording:
    """The mail for this type, or `notices.Unavailable` with a reason code. Where a draft may be shown and the test
    reset removed the row, the seeded draft itself is used, marked (as correspondence.verification does)."""
    key = template_key(type_key)
    try:
        return notices.wording(key, {"display_name": display_name, "link": link})
    except notices.Unavailable as refused:
        if str(refused) != f"{key}_missing" or key not in SEED.TEMPLATES:
            raise
    subject, body, _ = SEED.TEMPLATES[key]
    return notices.Wording(key, 1, SEED.digest(subject, body), subject,
                           Template(body).substitute(display_name=display_name, link=link), approved=False)


@dataclass(frozen=True)
class Proceed:
    application_id: int
    instance_id: int
    envelope_id: str
    recipient: str
    display_name: str
    type_key: str
    series: int


@dataclass(frozen=True)
class Stop:
    status: str
    reason: str  # a reason code only
    due_seconds: float | None = None


class SendCountMismatch(Exception):
    pass


def _series(claim) -> int | None:
    key = PendingAction.objects.filter(pk=claim.id, status=Status.RUNNING, lease_token=claim.lease_token).values_list(
        "idempotency_key", flat=True).first()
    if key is None:
        return None  # the lease is gone
    parts = key.split(":")
    if len(parts) != 3 or parts[0] != KIND or parts[1] != str(claim.input_ref) or not parts[2].isdigit():
        return -1
    return int(parts[2])


class SendSigningLink:
    kind = KIND
    redeliverable = True  # at least once, the identical link (module docstring)
    automated = True

    def lock_subject(self, claim) -> None:
        application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
        if application is not None:
            AgreementInstance.objects.select_for_update(of=("self",)).filter(public_id=claim.input_ref,
                                                                             application=application).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if application is not None and (kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final"))):
            open_item(LINK_SEND_FAILED, f"link:{claim.input_ref}", application=application, pending_action_id=claim.id)

    @sensitive_variables("token", "link", "mail", "message")
    def run(self, claim) -> None:
        decision = self.check(claim)
        if decision is None:
            logger.warning("action %s attempt %s: lease lost before sending; nothing sent", claim.id, claim.attempt)
            return
        if isinstance(decision, Stop):
            self._stop(claim, decision)
            return
        if connection.in_atomic_block:
            raise RuntimeError("refusing to read the provider or send inside a transaction")
        try:
            token = provider.signing_token(decision.envelope_id, decision.recipient)
        except provider.ProviderError as exc:  # a read: nothing was sent; retry within the attempt bound, then staff
            if claim.final:
                self._stop(claim, Stop(Status.FAILED, exc.code))
            else:
                self._stop(claim, Stop(Status.QUEUED, exc.code, exc.retry_after), refund=False)
            return
        if token is None:
            self._stop(claim, Stop(Status.FAILED, "signer_not_on_envelope"))
            return
        try:
            mail = wording(decision.type_key, decision.display_name, signing_link(token))
        except notices.Unavailable as refused:  # no approvable wording here; wait for the owner's approval (D-29)
            self._stop(claim, Stop(Status.QUEUED, str(refused)[:64], WORDING_RECHECK_SECONDS))
            return
        message_id = make_msgid(idstring=f"l{claim.attempt}", domain=urlsplit(settings.CATALYST_PUBLIC_BASE_URL).hostname)
        # bgl.11 (parity integration): multipart/alternative (text, then HTML) when the approved version has an HTML
        # part, rendered by correspondence.rendering.render_html through applications.notices; text only otherwise.
        message = EmailMultiAlternatives(subject=mail.subject, body=mail.display, to=[decision.recipient],
                                         from_email=from_header(), reply_to=reply_to(),  # bgl.6: config.mail
                                         headers={"Message-ID": message_id, "Auto-Submitted": "auto-generated"})
        if mail.html:
            message.attach_alternative(mail.html, "text/html")
        outbound = dict(application_id=decision.application_id, pending_action_id=claim.id, attempt_number=claim.attempt,
                        template_key=mail.key, template_version=f"{mail.version}:{mail.sha256[:24]}",
                        recipient=decision.recipient, message_id=message_id)
        data = {"instance": str(claim.input_ref), "type": decision.type_key, "series": decision.series, "attempt": claim.attempt}
        try:
            sent = message.send(fail_silently=False)
            if sent != 1:
                raise SendCountMismatch(f"sent {sent}")
        except Exception as exc:
            error = type(exc).__name__
            logger.warning("action %s attempt %s: signing link send failed (%s)", claim.id, claim.attempt, error)

            def write_failure():
                OutboundMessage.objects.create(status=OutboundMessage.Status.FAILED, **outbound)
                self.record(claim, "agreement_link_send_failed", {**data, "error": error, "final": claim.final})

            ledger.fail_or_retry(claim, self, f"send failed: {error}", write=write_failure)
            return

        def write_success():
            OutboundMessage.objects.create(status=OutboundMessage.Status.ACCEPTED, sent_at=Now(), **outbound)
            self.record(claim, "agreement_link_sent", {**data, "template_version": mail.version, "template_sha256": mail.sha256,
                                                       "draft": mail.draft})

        try:
            recorded = ledger.finish(claim, self, status=Status.DONE, write=write_success)
        except Exception as exc:
            raise ledger.LeftForRecovery from exc  # the sink has the message; recording failed (D-20)
        if not recorded:
            logger.warning("action %s attempt %s: sent, but a newer claim owns the action", claim.id, claim.attempt)

    def check(self, claim) -> Proceed | Stop | None:
        from .completion import stopped

        refuse = lambda reason: Stop(Status.FAILED, reason)  # noqa: E731
        skip = lambda reason: Stop(Status.CANCELLED, reason)  # noqa: E731
        with transaction.atomic():
            application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
            if application is None:
                return refuse("subject_application_not_found")
            instance = (AgreementInstance.objects.select_for_update(of=("self",)).select_related("agreement_type")
                        .filter(public_id=claim.input_ref, application=application).first())
            if instance is None:
                return refuse("instance_not_found")
            series = _series(claim)
            if series is None:
                return None
            if series < 0:
                return refuse("idempotency_key_does_not_match_the_instance")
            if settings.CATALYST_AGREEMENT_DISTRIBUTION != "service":
                return skip("provider_distributes")
            if AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists():
                return Stop(Status.QUEUED, "automation_paused")
            if stopped(application) or instance.cancel_requested_at:
                return skip("agreements_stopped")
            if instance.issue_status != "issued" or not instance.envelope_id:
                return skip("not_issued")
            if instance.signing_status not in ("not_started", "partially_signed"):
                return skip("already_signed_or_closed")
            applicant = instance.recipients.filter(who="applicant").first()
            if applicant is None or applicant.email != verified_address(application):
                return refuse("recipient_changed")
            if hard_bounce_open(application):
                return Stop(Status.QUEUED, "hard_bounce_open", settings.CATALYST_HARD_BOUNCE_RECHECK_SECONDS)
            return Proceed(application.pk, instance.pk, instance.envelope_id, applicant.email, application.display_name,
                           instance.agreement_type.key, series)

    def _stop(self, claim, decision: Stop, *, refund: bool = True) -> None:
        """A deferral (QUEUED) refunds the attempt when nothing was tried (a pause, a bounce, unapproved wording), and
        counts it when the provider read failed, so an outage ends with staff told, never a silent loop."""
        if decision.status == Status.QUEUED:
            due = None if decision.due_seconds is None else timedelta(seconds=decision.due_seconds)
            ledger.finish(claim, self, status=Status.QUEUED, error=decision.reason, refund_attempt=refund, due_in=due)
            return
        name = "agreement_link_send_refused" if decision.status == Status.FAILED else "agreement_link_send_skipped"

        def write():
            self.record(claim, name, {"instance": str(claim.input_ref), "attempt": claim.attempt, "reason": decision.reason})
            if decision.status == Status.FAILED:
                application = Application.objects.filter(public_ref=claim.subject_id).first()
                open_item(LINK_SEND_FAILED, f"link:{claim.input_ref}", application=application, pending_action_id=claim.id)
        ledger.finish(claim, self, status=decision.status, error=decision.reason, write=write)
