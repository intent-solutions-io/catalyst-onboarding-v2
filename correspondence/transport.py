"""The protocol-aware SMTP transport (016 A3 and section 6; owner decisions D-27, D-28). Synthetic only.

A thin `smtplib` wrapper that records the protocol phase each outcome was observed in, because Django's
mail backend cannot tell a rejection from an unknown outcome. Outcomes (016 A3; RFC 5321 sections 2.1,
4.1.1.4, 4.2.1 and 6.1):

- Channel phases (connect, greeting, EHLO, STARTTLS, AUTH, MAIL FROM) concern the sending channel, not the
  message. A failure, or a 4yz reply, is `transport_blocked`; a 5yz reply is `transport_blocked` with
  `hard=True` (a configuration fault, held at once).
- Message phases (RCPT TO, DATA): a 4yz reply, or a failure known to happen before the body write starts,
  is `rejected_temporary`; a 5yz reply is `rejected_permanent`.
- The body and the end-of-data marker go to the socket in one `sendall` (through `SMTP.send`). Python's
  documentation says that after a `sendall` error "there is no way to determine how much data, if any,
  was successfully sent", so the marker may have reached the server. **Once that write starts**, a failure
  of the write, a timeout, a disconnect or an unparseable reply is `unknown`, never a retryable rejection
  (016 A3, owner closeout of PR #21). A 250 reply after the end of data is `accepted_by_server` (never
  "delivered"); a 4yz or 5yz reply after it is a temporary or permanent rejection.
- After the body write has started, nothing more is sent on the connection (no QUIT): the socket is only
  closed, so cleanup can never complete or alter a partial DATA transaction.

Guards (A-4, amends REQ-022): the configured host must already pass `config.guards`; after connecting,
the transport also checks the connected peer address and refuses before any command that could carry a
credential, so a name that resolves elsewhere at connect time cannot reach a real server. STARTTLS uses
a verifying context; `none` is allowed only for a loopback host (config.guards). The whole exchange has a
total deadline below half the worker lease. Nothing here logs addresses, content, reply text or
credentials, and the SMTP debug level is never set.
"""

import ipaddress
import re
import smtplib
import ssl
import time
from dataclasses import dataclass

from django.conf import settings

from config import guards

ACCEPTED = "accepted_by_server"
REJECTED_TEMPORARY = "rejected_temporary"
REJECTED_PERMANENT = "rejected_permanent"
TRANSPORT_BLOCKED = "transport_blocked"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class SendResult:
    outcome: str
    phase: str
    code: int | None = None
    hard: bool = False  # transport_blocked only: hold now instead of retrying the channel


class _Deadline(Exception):
    pass


def _code(value) -> int | None:
    """A reply code is recorded only when it is a real SMTP code; smtplib reports an unparseable reply as -1."""
    return value if isinstance(value, int) and 100 <= value <= 599 else None


def tls_context() -> ssl.SSLContext:
    """A verifying context (certificate chain and hostname). CATALYST_MAIL_CA_FILE only replaces the trust
    store for synthetic servers; verification is never switched off."""
    return ssl.create_default_context(cafile=settings.CATALYST_MAIL_CA_FILE or None)


def peer_allowed(peer_ip: str) -> bool:
    """The connected peer must be loopback, or (in `test` only) the named test service on a private
    address. Checked after connect and before any further command."""
    try:
        address = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    host, test_host = settings.CATALYST_MAIL_HOST, settings.CATALYST_MAIL_TEST_HOST
    return (settings.CATALYST_ENV == "test" and bool(test_host) and host == test_host and address.is_private
            and not address.is_link_local)


def _channel(phase: str, code: int | None) -> SendResult:
    code = _code(code)
    hard = code is not None and not 400 <= code < 500
    return SendResult(TRANSPORT_BLOCKED, phase, code, hard=hard)


def _message(phase: str, code: int | None) -> SendResult:
    code = _code(code)
    if code is not None and 500 <= code < 600:
        return SendResult(REJECTED_PERMANENT, phase, code)
    return SendResult(REJECTED_TEMPORARY, phase, code)


def _payload(message_bytes: bytes) -> bytes:
    """Dot-stuffing and the end-of-data marker (RFC 5321 section 4.5.2)."""
    data = re.sub(rb"(?m)^\.", b"..", message_bytes)
    if not data.endswith(b"\r\n"):
        data += b"\r\n"
    return data + b".\r\n"


def _send_body(smtp: smtplib.SMTP, payload: bytes) -> None:
    """Test seam (TEST-P2-48): hand the body and the end-of-data marker to the socket."""
    smtp.send(payload)


def send(message_bytes: bytes, mail_from: str, recipient: str) -> SendResult:
    host = settings.CATALYST_MAIL_HOST
    if not host or not guards.mail_host_allowed(settings.CATALYST_ENV, host, settings.CATALYST_MAIL_TEST_HOST):
        return SendResult(TRANSPORT_BLOCKED, "connect", None, hard=True)
    deadline = time.monotonic() + settings.CATALYST_MAIL_SEND_DEADLINE_SECONDS

    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise _Deadline
        return left

    smtp = smtplib.SMTP(timeout=remaining())
    phase = "connect"
    peer_checked = False
    body_started = False
    try:
        try:
            code, _ = smtp.connect(host, settings.CATALYST_MAIL_PORT)
            if not peer_allowed(smtp.sock.getpeername()[0]):
                return SendResult(TRANSPORT_BLOCKED, "connect", None, hard=True)  # nothing more is sent to it
            peer_checked = True
            phase = "greeting"
            if code != 220:
                return _channel(phase, code)
            phase = "ehlo"
            smtp.sock.settimeout(remaining())
            code, _ = smtp.ehlo()
            if code != 250:
                return _channel(phase, code)
            if settings.CATALYST_MAIL_TLS == "starttls":
                phase = "starttls"
                if not smtp.has_extn("starttls"):
                    return SendResult(TRANSPORT_BLOCKED, phase, None, hard=True)
                smtp.sock.settimeout(remaining())
                code, _ = smtp.starttls(context=tls_context())
                if code != 220:
                    return _channel(phase, code)
                smtp.sock.settimeout(remaining())
                code, _ = smtp.ehlo()
                if code != 250:
                    return _channel("ehlo", code)
            if settings.CATALYST_MAIL_USER:
                phase = "auth"
                smtp.sock.settimeout(remaining())
                smtp.login(settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD)
            phase = "mail"
            smtp.sock.settimeout(remaining())
            code, _ = smtp.mail(mail_from)
            if code != 250:
                return _channel(phase, code)
        except (smtplib.SMTPNotSupportedError, ssl.SSLError):
            return SendResult(TRANSPORT_BLOCKED, phase, None, hard=True)  # no TLS or a certificate refused: hold
        except smtplib.SMTPResponseException as exc:
            return _channel(phase, exc.smtp_code)
        except (smtplib.SMTPException, OSError, _Deadline):
            return _channel(phase, None)
        try:
            phase = "rcpt"
            smtp.sock.settimeout(remaining())
            code, _ = smtp.rcpt(recipient)
            if code not in (250, 251):
                return _message(phase, code)
            phase = "data"
            smtp.sock.settimeout(remaining())
            code, _ = smtp.docmd("DATA")
            if code != 354:
                return _message(phase, code)
            phase = "body"
            payload = _payload(message_bytes)
            smtp.sock.settimeout(remaining())
        except smtplib.SMTPResponseException as exc:
            return _message(phase, exc.smtp_code)
        except (smtplib.SMTPException, OSError, _Deadline):
            return _message(phase, None)  # known before the body write started: nothing was accepted
        body_started = True
        try:
            _send_body(smtp, payload)
        except (smtplib.SMTPException, OSError):
            # sendall's progress is unknowable after an error: the marker may have reached the server.
            return SendResult(UNKNOWN, phase, None)
        phase = "end"
        try:
            smtp.sock.settimeout(remaining())
            code, _ = smtp.getreply()
        except (smtplib.SMTPException, OSError, _Deadline):
            return SendResult(UNKNOWN, phase, None)
        code = _code(code)
        if code == 250:
            return SendResult(ACCEPTED, phase, code)
        if code is not None and 400 <= code < 600:
            return _message(phase, code)
        return SendResult(UNKNOWN, phase, code)  # an unparseable or unexpected reply after the marker
    finally:
        try:
            if smtp.sock is not None and peer_checked and not body_started:
                smtp.sock.settimeout(1)
                smtp.quit()
        except (smtplib.SMTPException, OSError):
            pass  # the outcome is already decided; a failed QUIT never changes it
        try:
            smtp.close()
        except OSError:
            pass
