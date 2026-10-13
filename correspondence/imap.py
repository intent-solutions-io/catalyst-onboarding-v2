"""The TLS-only IMAP client (016 B2 and A4; owner decisions D-28, M6). Synthetic only.

Implicit TLS (`imaplib.IMAP4_SSL`) with a verifying context (certificate chain and hostname; the trust store
may be replaced by CATALYST_MAIL_CA_FILE for synthetic servers, never disabled). There is no plaintext path.
The host must pass `config.guards`, and the connected peer is checked before LOGIN, so no credential can
reach a server other than the allowed one. Collection uses EXAMINE (read-only) and BODY.PEEK, so the
mailbox is never modified; APPEND is used only to file copies of accepted sends into a different folder.
Nothing here logs addresses, content or credentials, and imaplib's debug output is never enabled.
"""

import imaplib
import re
import ssl

from django.conf import settings

from config import guards

from .transport import peer_allowed, tls_context


def classify(exc: BaseException) -> "MailboxError":
    """One mapping for every network-level failure the collector meets (TLS, socket, protocol)."""
    if isinstance(exc, MailboxError):
        return exc
    if isinstance(exc, ssl.SSLError):
        return MailboxError("tls_refused")
    if isinstance(exc, imaplib.IMAP4.abort) or isinstance(exc, OSError):
        return MailboxError("unreachable")
    return MailboxError("protocol_error")


NETWORK_ERRORS = (OSError, ssl.SSLError, imaplib.IMAP4.error)


class MailboxError(Exception):
    """A failure with a reason code: `auth_failed`, `tls_refused`, `unreachable`, `peer_refused`,
    `protocol_error`, `not_configured` or `folder_missing`."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_UIDVALIDITY = re.compile(rb"UIDVALIDITY (\d+)")
_UIDNEXT = re.compile(rb"UIDNEXT (\d+)")
_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")
_DATE = re.compile(rb'INTERNALDATE ("[^"]*")')


class MailboxClient:
    def __init__(self, timeout: float):
        host = settings.CATALYST_MAIL_HOST
        if not host or not guards.mail_host_allowed(settings.CATALYST_ENV, host, settings.CATALYST_MAIL_TEST_HOST):
            raise MailboxError("not_configured")
        if not settings.CATALYST_MAIL_USER:
            raise MailboxError("not_configured")  # IMAP selection needs an authenticated session
        try:
            self.imap = imaplib.IMAP4_SSL(host, settings.CATALYST_MAIL_IMAP_PORT, ssl_context=tls_context(), timeout=timeout)
        except ssl.SSLError:
            raise MailboxError("tls_refused") from None
        except (OSError, imaplib.IMAP4.error):
            raise MailboxError("unreachable") from None
        try:
            if not peer_allowed(self.imap.sock.getpeername()[0]):
                raise MailboxError("peer_refused")
            try:
                self.imap.login(settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_PASSWORD)
            except imaplib.IMAP4.abort:
                raise MailboxError("unreachable") from None  # a dropped connection is not a refused login
            except imaplib.IMAP4.error:
                raise MailboxError("auth_failed") from None
        except MailboxError:
            self.close()
            raise
        except (OSError, imaplib.IMAP4.abort):
            self.close()
            raise MailboxError("unreachable") from None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try:
            self.imap.logout()
        except (OSError, imaplib.IMAP4.error, AttributeError):
            try:
                self.imap.shutdown()
            except (OSError, AttributeError):
                pass

    def _ok(self, result):
        typ, data = result
        if typ != "OK":
            raise MailboxError("protocol_error")
        return data

    def examine(self, folder: str) -> tuple[int, int]:
        """Read-only selection. Returns (UIDVALIDITY, UIDNEXT)."""
        typ, _ = self.imap.select(f'"{folder}"', readonly=True)
        if typ != "OK":
            raise MailboxError("folder_missing")
        validity = self.imap.untagged_responses.get("UIDVALIDITY", [None])[-1]
        uidnext = self.imap.untagged_responses.get("UIDNEXT", [None])[-1]
        if validity is None or uidnext is None:
            raise MailboxError("protocol_error")
        return int(validity), int(uidnext)

    def uids_after(self, last_uid: int) -> list[int]:
        """UIDs strictly greater than `last_uid`, ascending. The server's answer to `n:*` is re-filtered here,
        because a range ending in `*` can return the highest UID even when it is below n."""
        data = self._ok(self.imap.uid("SEARCH", "UID", f"{last_uid + 1}:*"))
        return sorted(u for u in (int(x) for x in (data[0] or b"").split()) if u > last_uid)

    def meta(self, uid: int) -> tuple[int, str]:
        data = self._ok(self.imap.uid("FETCH", str(uid), "(RFC822.SIZE INTERNALDATE)"))
        line = b" ".join(d if isinstance(d, bytes) else d[0] for d in data if d)
        size, date = _SIZE.search(line), _DATE.search(line)
        if size is None:
            raise MailboxError("protocol_error")
        return int(size.group(1)), (date.group(1).decode(errors="replace") if date else "")

    def _literal(self, uid: int, item: str) -> bytes:
        data = self._ok(self.imap.uid("FETCH", str(uid), f"({item})"))
        for part in data:
            if isinstance(part, tuple) and len(part) == 2:
                return part[1]
        raise MailboxError("protocol_error")

    def fetch(self, uid: int) -> bytes:
        return self._literal(uid, "BODY.PEEK[]")

    def fetch_headers(self, uid: int) -> bytes:
        return self._literal(uid, "BODY.PEEK[HEADER]")

    def search_message_id(self, folder: str, message_id: str) -> list[int]:
        self.examine(folder)
        data = self._ok(self.imap.uid("SEARCH", "HEADER", "Message-ID", f'"{message_id}"'))
        return [int(x) for x in (data[0] or b"").split()]

    def append(self, folder: str, data: bytes) -> None:
        self._ok(self.imap.append(f'"{folder}"', None, None, data))
