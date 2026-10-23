"""The read-only Sent-folder evidence source (016 A5 and 8.3; 029 section 5.2; bead 9kg.49). Synthetic against the
fake; the live proof is the mail canary.

`SentFolderSource` is the production value of `CATALYST_SEND_EVIDENCE_SOURCE`: it reads the mailbox's Sent folder
(`CATALYST_MAIL_SENT_FOLDER`) over the TLS-only IMAP client, with EXAMINE (read-only selection) and BODY.PEEK, and
never APPENDs, STOREs, EXPUNGEs or SELECTs for writing: a reader that could write would be a second filer. Each copy
becomes an `Evidence` record of origin `provider`: its Message-ID, its `To` address, the canonical digest of its
subject and text, and whether it carries Catalyst's own filed-copy header (`filed_by_catalyst`, which the 016 A5
rule makes inadmissible). Admissibility is decided by the caller (`outbound.admissible`), never here.

- `find(message_id)`: the copies with that Message-ID (the ordinary reconciliation of one uncertain send).
- `within(since)`: every copy whose internal date is on or after `since` (IMAP `SINCE` is a calendar day, so the
  read starts a day early and errs toward more copies), or the whole folder for None; bounded by
  `CATALYST_MAIL_SENT_SCAN_LIMIT` newest copies, so a large folder never makes the read unbounded.

Absence of a copy is not proof of non-send: the caller treats "none" as "unknown", never as "not sent". A read
failure raises `MailboxError` with a reason code (`not_configured`, `tls_refused`, `unreachable`, `peer_refused`,
`auth_failed`, `folder_missing`, `protocol_error`), never an address, a body or a credential.
"""

import email
from datetime import datetime, timedelta
from email.policy import default as DEFAULT_POLICY

from django.conf import settings

from .imap import NETWORK_ERRORS, MailboxClient, MailboxError, classify
from .mime import FILED_COPY_HEADER
from .outbound import Evidence
from .rendering import canonical_digest

ORIGIN = "provider"
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def imap_date(moment: datetime) -> str:
    """RFC 9051 date-day-fixed: `23-Oct-2026`, locale-independent."""
    return f"{moment.day:02d}-{MONTHS[moment.month - 1]}-{moment.year}"


def record_from_bytes(data: bytes, origin: str = ORIGIN) -> Evidence:
    parsed = email.message_from_bytes(data, policy=DEFAULT_POLICY)
    try:
        body = parsed.get_content() if not parsed.is_multipart() else (parsed.get_body(("plain",)) or parsed).get_content()
    except (KeyError, LookupError, UnicodeDecodeError, TypeError):
        body = ""
    return Evidence(origin=origin, message_id=str(parsed["Message-ID"] or "").strip(),
                    recipient=str(parsed["To"] or "").strip(), content_sha256=canonical_digest(str(parsed["Subject"] or ""), body),
                    filed_by_catalyst=parsed[FILED_COPY_HEADER] is not None)


class SentFolderSource:
    def _folder(self) -> str:
        folder = settings.CATALYST_MAIL_SENT_FOLDER
        if not folder:
            raise MailboxError("not_configured")
        return folder

    def _read(self, uids, client) -> list:
        limit = settings.CATALYST_MAIL_SENT_SCAN_LIMIT
        records = []
        for uid in sorted(uids)[-limit:]:  # the newest copies, bounded
            records.append(record_from_bytes(client.fetch(uid)))
        return records

    def find(self, message_id: str):
        folder = self._folder()
        try:
            with MailboxClient(timeout=settings.CATALYST_MAIL_SEND_DEADLINE_SECONDS) as client:
                uids = client.search_message_id(folder, message_id)
                return [r for r in self._read(uids, client) if r.message_id == message_id]
        except NETWORK_ERRORS as exc:
            raise classify(exc) from None

    def within(self, since):
        folder = self._folder()
        try:
            with MailboxClient(timeout=settings.CATALYST_MAIL_SEND_DEADLINE_SECONDS) as client:
                client.examine(folder)
                if since is None:
                    uids = client.uids_after(0)
                else:
                    uids = client.uids_since(imap_date(since - timedelta(days=1)))
                return self._read(uids, client)
        except NETWORK_ERRORS as exc:
            raise classify(exc) from None
