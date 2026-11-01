"""Django mail backends for production (9kg.31.11, 9kg.77).

Three applicant mails are sent through Django's mailer: the contact confirmation (correspondence.verification), the
password setup (provisioning.credentials) and the withdrawal link (provisioning.closure). Production never uses a file
or console sink for them: it would keep their live bearer links and addresses on disk and let each sender record a
delivery that never happened.

- `TransportEmailBackend` (production's default, 9kg.77) sends each message through `correspondence.transport`, the
  one SMTP path: the allow-listed host, the pinned v2 login, verified TLS, the peer check, and the web and worker
  kinds only (the post-restore step, the fetcher and a management process cannot send). One message per call, one
  recipient per message, no cc or bcc; the envelope recipient is the message's one `To` address, sanitized as
  Django's SMTP backend does. Anything but `accepted_by_server` raises, so each sender takes its failure path: the
  confirmation is retried and then fails; the password setup becomes uncertain and a new series opens with a new
  token; the withdrawal opens a staff item. An outcome that may have reached the server (`unknown`) raises
  `MailUncertain`, a subclass the senders log by name; they treat it as a failure like any other (a retried
  confirmation repeats the same link, D-20).
- `RefusingEmailBackend` refuses every message: the explicit hold, when the owner wants none of the three to leave.
- `from_header` and `reply_to` (bgl.6, 034 rows 10 and 22): the sender headers every applicant mail carries, the P2
  sender's (correspondence.messages) and the three above alike. Unset, they are the bare CATALYST_FROM_EMAIL and no
  Reply-To, as before; the SMTP envelope sender is always the bare address.
"""

from email.utils import formataddr, parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.core.mail.message import sanitize_address


def from_header() -> str:
    """The From header: `Display Name <address>` when CATALYST_FROM_DISPLAY_NAME is set, else the bare address."""
    name = settings.CATALYST_FROM_DISPLAY_NAME
    return formataddr((name, settings.DEFAULT_FROM_EMAIL)) if name else settings.DEFAULT_FROM_EMAIL


def reply_to() -> list[str]:
    """The Reply-To addresses: CATALYST_REPLY_TO when set (one address, checked at start-up), else none."""
    return [settings.CATALYST_REPLY_TO] if settings.CATALYST_REPLY_TO else []


class MailRefused(Exception):
    """The message did not leave (refused here, or rejected or blocked by the transport)."""


class MailUncertain(MailRefused):
    """The transport cannot tell whether the server accepted the message (016 A3)."""


class RefusingEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        raise MailRefused("django_mail_held")


class TransportEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        from correspondence import transport

        if not email_messages:
            return 0
        if len(email_messages) != 1:  # a batch could fail after an acceptance and lose its count
            raise MailRefused("one_message_per_call")
        sent = 0
        for message in email_messages:
            recipients = message.recipients()
            if len(recipients) != 1 or message.cc or message.bcc or "cc" in {k.lower() for k in message.extra_headers}:
                raise MailRefused("one_recipient_only")
            # CRLF line ends, as SMTP requires; Django adds the Date and Message-ID headers when absent, and refuses a
            # header value with a line break (BadHeaderError) before anything is sent.
            data = message.message().as_bytes(linesep="\r\n")
            recipient = sanitize_address(recipients[0], message.encoding)
            # The envelope sender is the bare address even when the From header carries a display name (bgl.6).
            sender = parseaddr(message.from_email)[1] or message.from_email
            result = transport.send(data, sanitize_address(sender, message.encoding), recipient)
            if result.outcome == transport.UNKNOWN:
                raise MailUncertain(f"{result.outcome}:{result.phase}")
            if result.outcome != transport.ACCEPTED:
                raise MailRefused(f"{result.outcome}:{result.phase}")
            sent += 1
        return sent
