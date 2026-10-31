"""Message identity and the wire form (a leaf module shared by outbound, inbound and processing; 016 3.2, A3, A4).

- `message_id`: <c{send_ref hex}@{CATALYST_MAIL_DOMAIN}>, recomputable after any crash.
- `verified_address`: the address the applicant proved control of (the challenge named by the adoption).
- `build_email`: static headers from the frozen record only. The standard-library header policy refuses a CR
  or LF in any header value, so no input can add a header (TEST-P2-38). No CC or BCC exists.
- `enqueue_file_copy`: queues the filing of a mailbox copy of an accepted send (016 A4); never for a
  secret-bearing message.
"""

from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from email.utils import formatdate

from django.conf import settings
from django.db import IntegrityError, transaction

from workflow.models import PendingAction

FILE_COPY = "file_copy"


def message_id(send_ref) -> str:
    return f"<c{send_ref.hex}@{settings.CATALYST_MAIL_DOMAIN}>"


def verified_address(application) -> str | None:
    if application.contact_verified_at is None:
        return None
    adoption = application.adoptions.select_related("via_challenge").first()
    return adoption.via_challenge.email_at_issue if adoption else None


def build_email(message, subject: str, body: str, extra_headers: dict | None = None, html: str = "") -> bytes:
    """The wire form: text/plain alone, or multipart/alternative (the text, then the HTML) when `html` is given, the
    structure the first generation sends (bgl.11)."""
    email = EmailMessage(policy=SMTP_POLICY)
    email["From"] = settings.DEFAULT_FROM_EMAIL
    email["To"] = message.recipient
    email["Subject"] = subject
    email["Message-ID"] = message_id(message.send_ref)
    email["Date"] = formatdate(usegmt=True)
    if message.kind != "staff_message":
        email["Auto-Submitted"] = "auto-generated"  # RFC 3834: automated mail is marked
    for name, value in (extra_headers or {}).items():
        email[name] = value
    email.set_content(body)
    if html:
        email.add_alternative(html, subtype="html")
    return email.as_bytes()


def only_duplicate_key(exc: IntegrityError) -> None:
    """Tolerate only the idempotency-key unique violation; any other integrity error propagates."""
    diag = getattr(exc.__cause__, "diag", None)
    if "idempotency_key" not in (getattr(diag, "constraint_name", None) or ""):
        raise exc


def enqueue_file_copy(message, attempt_id: int) -> None:
    from .models import OutboundMessage

    secret = message.template_version is not None and message.template_version.secret_bearing
    if not settings.CATALYST_MAIL_SENT_FOLDER or secret:
        return  # no copy of a secret-bearing message is ever filed (016 A4)
    OutboundMessage.objects.filter(pk=attempt_id).update(filed_copy_state="pending")
    try:
        with transaction.atomic():
            PendingAction.objects.create(
                kind=FILE_COPY, subject_type="application", subject_id=message.application.public_ref,
                input_ref=str(message.send_ref), idempotency_key=f"{FILE_COPY}:{message.send_ref}",
                max_attempts=settings.CATALYST_MAIL_SEND_ATTEMPTS)
    except IntegrityError as exc:
        only_duplicate_key(exc)
