"""The read-only Sent-folder evidence source (016 A5 and 8.3; 029 section 5.2; bead 9kg.49). Synthetic against the
fake; the live proof is the mail canary.

`SentFolderSource` is the production value of `CATALYST_SEND_EVIDENCE_SOURCE`: it reads the mailbox's Sent folder
(`CATALYST_MAIL_SENT_FOLDER`) through `ReadOnlyMailbox`, a view of the TLS-only IMAP client that has no `append`:
EXAMINE (read-only selection), UID SEARCH, UID FETCH with sizes, dates and BODY.PEEK, LOGOUT. A reader that could
write would be a second filer. Each copy becomes an `Evidence` record of origin `provider`: its Message-ID, its `To`
address, the canonical digest of its subject and text, its internal date and whether it carries Catalyst's own
filed-copy header (`filed_by_catalyst`, which the 016 A5 rule makes inadmissible). Admissibility is decided by the
caller (`outbound.admissible`), never here.

- `find(message_id)`: the copies with that Message-ID (the ordinary reconciliation of one uncertain send).
- `within(since)`: every copy whose internal date is on or after `since` (IMAP `SINCE` is a calendar day, so the
  read starts a day early and errs toward more copies; the caller drops copies before `since` by their date), or
  the whole folder for None. More than `CATALYST_MAIL_SENT_SCAN_LIMIT` copies is `scan_limit_exceeded`: an
  unbounded read is never silently truncated (PR #89 review).

Hardening (security review of PR #89): each copy's size is read first (`meta`) and a copy above
`CATALYST_MAIL_MAX_MESSAGE_BYTES` is not fetched; a copy that cannot be fetched or parsed is counted; any such copy
makes the read `incomplete`, an error the caller treats as unreadable evidence, never as "no copy".

Absence of a copy is not proof of non-send: the caller treats "none" as "unknown", never as "not sent". A read
failure raises `MailboxError` with a reason code (`not_configured`, `tls_refused`, `unreachable`, `peer_refused`,
`auth_failed`, `folder_missing`, `protocol_error`, `scan_limit_exceeded`, `incomplete`), never an address, a body
or a credential.
"""

import email
import logging
from datetime import UTC, datetime, timedelta
from email.policy import default as DEFAULT_POLICY
from email.utils import parseaddr

from django.conf import settings

from .imap import NETWORK_ERRORS, MailboxError, ReadOnlyMailbox, classify
from .mime import FILED_COPY_HEADER
from .outbound import Evidence
from .rendering import canonical_digest

logger = logging.getLogger(__name__)
ORIGIN = "provider"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def imap_date(moment: datetime) -> str:
    """RFC 9051 date-day-fixed: `23-Oct-2026`, locale-independent."""
    return f"{moment.day:02d}-{MONTHS[moment.month - 1]}-{moment.year}"


def parse_internal_date(text: str) -> datetime | None:
    """An IMAP INTERNALDATE (`"13-Oct-2026 10:00:00 +0000"`) as an aware datetime, or None when unreadable."""
    try:
        return datetime.strptime(text.strip().strip('"'), "%d-%b-%Y %H:%M:%S %z").astimezone(UTC)
    except (ValueError, AttributeError):
        return None


def recipient_address(header: str) -> str:
    """The address of a `To` header in any of its forms (`Name <a@b>`, `<a@b>`, `a@b`), lower-cased."""
    return parseaddr(header or "")[1].strip().lower()


def record_from_bytes(data: bytes, origin: str = ORIGIN, observed_at: datetime | None = None) -> Evidence:
    parsed = email.message_from_bytes(data, policy=DEFAULT_POLICY)
    try:
        body = parsed.get_content() if not parsed.is_multipart() else (parsed.get_body(("plain",)) or parsed).get_content()
    except (KeyError, LookupError, UnicodeDecodeError, TypeError):
        body = ""
    return Evidence(origin=origin, message_id=str(parsed["Message-ID"] or "").strip(),
                    recipient=recipient_address(str(parsed["To"] or "")),
                    content_sha256=canonical_digest(str(parsed["Subject"] or ""), body),
                    filed_by_catalyst=parsed[FILED_COPY_HEADER] is not None, observed_at=observed_at)


class SentFolderSource:
    def _folder(self) -> str:
        folder = settings.CATALYST_MAIL_SENT_FOLDER
        if not folder:
            raise MailboxError("not_configured")
        return folder

    def _read(self, uids, client) -> list:
        if len(uids) > settings.CATALYST_MAIL_SENT_SCAN_LIMIT:
            raise MailboxError("scan_limit_exceeded")
        records, failed = [], 0
        for uid in sorted(uids):
            try:
                size, date = client.meta(uid)
                if size > settings.CATALYST_MAIL_MAX_MESSAGE_BYTES:
                    failed += 1
                    continue
                records.append(record_from_bytes(client.fetch(uid), observed_at=parse_internal_date(date)))
            except MailboxError:
                failed += 1
            except Exception as exc:  # a copy that will not parse: counted, never a crash and never "no copy"
                logger.warning("sent folder copy unreadable (%s)", type(exc).__name__)
                failed += 1
        if failed:
            raise MailboxError("incomplete")
        return records

    def find(self, message_id: str):
        folder = self._folder()
        try:
            with ReadOnlyMailbox(timeout=settings.CATALYST_MAIL_SEND_DEADLINE_SECONDS) as client:
                uids = client.search_message_id(folder, message_id)
                return [r for r in self._read(uids, client) if r.message_id == message_id]
        except NETWORK_ERRORS as exc:
            raise classify(exc) from None

    def within(self, since):
        folder = self._folder()
        try:
            with ReadOnlyMailbox(timeout=settings.CATALYST_MAIL_SEND_DEADLINE_SECONDS) as client:
                client.examine(folder)
                if since is None:
                    uids = client.uids_after(0)
                else:
                    uids = client.uids_since(imap_date(since - timedelta(days=1)))
                return self._read(uids, client)
        except NETWORK_ERRORS as exc:
            raise classify(exc) from None
