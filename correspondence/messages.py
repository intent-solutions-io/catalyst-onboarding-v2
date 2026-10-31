"""Message identity and the wire form (a leaf module shared by outbound, inbound and processing; 016 3.2, A3, A4).

- `message_id`: <c{send_ref hex}@{CATALYST_MAIL_DOMAIN}>, recomputable after any crash.
- `verified_address`: the address the applicant proved control of (the challenge named by the adoption).
- `build_email`: static headers from the frozen record only. The standard-library header policy refuses a CR
  or LF in any header value, so no input can add a header (TEST-P2-38). No CC or BCC exists.
- `enqueue_file_copy`: queues the filing of a mailbox copy of an accepted send (016 A4); never for a
  secret-bearing message.
- `thread_parent` and `thread_headers` (bgl.7; 034 rows 20 and 21): a reminder is a reply in the thread of its
  question's first message, and a lapse note a reply in the thread of the latest accepted automated message, so
  `In-Reply-To` and `References` name that message's Message-ID. Derived from the frozen records alone, so a worker
  rebuilds the same headers after any crash; nothing is stored for it.
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


def build_email(message, subject: str, body: str, extra_headers: dict | None = None) -> bytes:
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
    return email.as_bytes()


THREADED_KINDS = ("reminder", "lapse_note")
ACCEPTED_DISPOSITIONS = ("accepted_by_server", "accepted_by_evidence")


def thread_parent(message):
    """The frozen message this one replies to, or None: for a reminder its question's initial message; for a lapse note
    the application's latest accepted question or reminder authorized before it (the note goes in the thread of the
    last thing the service said, as the first generation did)."""
    from .models import ApprovedMessage, ApprovedMessageQuestion

    if message.kind == "reminder":
        link = (ApprovedMessageQuestion.objects.filter(question__message_links__approved_message=message, purpose="initial")
                .select_related("approved_message").order_by("approved_message_id").first())
        return link.approved_message if link is not None else None
    if message.kind == "lapse_note":
        return (ApprovedMessage.objects.filter(application_id=message.application_id, kind__in=("question", "reminder"),
                                               disposition__in=ACCEPTED_DISPOSITIONS, authorized_at__lt=message.authorized_at)
                .order_by("-authorized_at", "-id").first())
    return None


def thread_headers(message) -> dict:
    parent = thread_parent(message) if message.kind in THREADED_KINDS else None
    if parent is None:
        return {}
    parent_id = message_id(parent.send_ref)
    return {"In-Reply-To": parent_id, "References": parent_id}


def reply_subject(parent_subject: str) -> str:
    """`Re: ` once, in front of the parent's subject (never doubled on a parent that already replies)."""
    return parent_subject if parent_subject.lower().startswith("re: ") else f"Re: {parent_subject}"


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
