"""The bounded derivation pipeline (016 3.5; owner decision D-28, A-9). Pure functions, versioned.

Original MIME bytes are read into memory, digested and discarded; what is stored is a sanitized
**derivative** with its provenance (versions, truncation, omitted parts, redaction counts). Content-transfer
encodings and charsets are decoded before redaction, so an encoded confirmation link cannot slip past it.
HTML is reduced to text and never rendered; forwarded `message/rfc822` parts are reduced within the depth
cap; attachments are never opened (metadata only). No universal secret detection is promised.
"""

import hashlib
import html
import re
import unicodedata
from dataclasses import dataclass, field
from email import message_from_bytes
from email.policy import default as DEFAULT_POLICY
from email.utils import getaddresses
from html.parser import HTMLParser
from urllib.parse import unquote

from applications.links import CONFIRM_PATH

DERIVATION_VERSION = 1
REDACTION_VERSION = 1
MAX_DEPTH = 5
MAX_PARTS = 50
MAX_HEADERS = 200
MAX_DECODED_BYTES = 2_000_000
REDACTED = "[confirmation link removed]"
FILED_COPY_HEADER = "X-Catalyst-Filed-Copy"
# The confirmation path is CONFIRM_PATH, shared with config/redaction.py. A token may be wrapped across lines,
# including quoted continuations ("\n> "), so line breaks inside the token are part of the match.
_CONFIRM = re.compile(r"(?i)" + re.escape(CONFIRM_PATH)
                      + r"(?:[^\s\"'<>)\]]|\r?\n[> \t]*(?=[A-Za-z0-9_\-:.=%/]+[ \t]*(?:\r?\n|$)))+")
_MSGID = re.compile(r"<[^<>\s]+>")


@dataclass
class Derived:
    message_id: str = ""
    in_reply_to: list = field(default_factory=list)
    references: list = field(default_factory=list)
    from_addresses: list = field(default_factory=list)
    date_header: str = ""
    auto_markers: dict = field(default_factory=dict)
    is_bounce: bool = False
    embedded_message_ids: list = field(default_factory=list)
    filed_copy: str = ""
    authentication_results: list = field(default_factory=list)
    text: str = ""
    truncated: bool = False
    truncated_at_chars: int | None = None
    omitted_parts: list = field(default_factory=list)
    redactions: dict = field(default_factory=dict)
    attachments: list = field(default_factory=list)
    defects: int = 0
    dsn_status: str = ""  # the first per-recipient Status of a delivery-status report, for example 5.1.1
    dsn_final_recipient: str = ""


class _Text(HTMLParser):
    """HTML to text: tags dropped, link targets kept as text so redaction sees them; nothing is rendered."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        for name, value in attrs:
            if name in ("href", "src") and value:
                self.out.append(f" <{value}> ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in ("p", "br", "div", "li", "tr"):
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    parser.close()
    return "".join(parser.out)


def redact(text: str) -> tuple[str, int]:
    """Replace every confirmation-path URL (D-24) with a fixed marker: after decoding percent-encoding (also
    partial, such as %63onfirm) and HTML character references, and joining quoted-printable soft breaks, so
    encoded or wrapped forms are caught. The stored text is a derivative, so the normalized form is what is
    kept. Returns the text and the number of replacements. Not a universal secret detector."""
    text = re.sub(r"=\r?\n", "", text)  # a stray quoted-printable soft break left in decoded text
    text = html.unescape(unquote(text))
    text, count = _CONFIRM.subn(REDACTED, text)
    return clean(text), count


def clean(value: str) -> str:
    """PostgreSQL text and jsonb refuse NUL: escape it last, after every decoding step (a %00 decodes to NUL)."""
    return value.replace("\x00", "\\x00")


def redact_short(value: str) -> str:
    return redact(value)[0]


def sanitize_name(name: str) -> str:
    name = unicodedata.normalize("NFKC", name or "")
    return re.sub(r"[^\w.\- ]", "_", name)[:120]


def _decoded_text(part) -> str:
    try:
        content = part.get_content()
    except (LookupError, UnicodeError, AssertionError, KeyError):
        payload = part.get_payload(decode=True) or b""
        content = payload[:MAX_DECODED_BYTES].decode("utf-8", errors="replace")
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")
    return content[:MAX_DECODED_BYTES]


def _walk(part, derived: Derived, chunks: list, depth: int, counter: list) -> None:
    counter[0] += 1
    if counter[0] > MAX_PARTS:
        if {"part": "remaining", "reason": "part_cap"} not in derived.omitted_parts:
            derived.omitted_parts.append({"part": "remaining", "reason": "part_cap"})
        return
    if depth > MAX_DEPTH:
        derived.omitted_parts.append({"part": "nested", "reason": "depth_cap"})
        return
    ctype = part.get_content_type()
    if ctype == "message/delivery-status":
        derived.is_bounce = True
        payload = part.get_payload()
        for block in payload if isinstance(payload, list) else []:
            status = str(block.get("Status", "")).strip()
            if status and not derived.dsn_status:
                derived.dsn_status = redact_short(status)[:16]
                recipient = str(block.get("Final-Recipient", "")).split(";", 1)[-1].strip()
                derived.dsn_final_recipient = redact_short(recipient)[:320]
        return
    if ctype == "message/rfc822":  # a forwarded or bounced original: its Message-ID, then its text, reduced
        payload = part.get_payload()
        inner = payload[0] if isinstance(payload, list) and payload else None
        if inner is not None:
            derived.embedded_message_ids += _MSGID.findall(str(inner.get("Message-ID", "")))
            _walk(inner, derived, chunks, depth + 1, counter)
        return
    if part.is_multipart():
        for sub in part.get_payload():
            _walk(sub, derived, chunks, depth + 1, counter)
        return
    if ctype == "text/rfc822-headers":
        headers = message_from_bytes(_decoded_text(part).encode(), policy=DEFAULT_POLICY)
        derived.embedded_message_ids += _MSGID.findall(str(headers.get("Message-ID", "")))
        return
    disposition = (part.get_content_disposition() or "").lower()
    if disposition == "attachment" or not ctype.startswith("text/"):
        payload = part.get_payload(decode=True) or b""
        derived.attachments.append({"name": sanitize_name(part.get_filename() or ""), "type": ctype,
                                    "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
        return
    text = _decoded_text(part)
    chunks.append(html_to_text(text) if ctype == "text/html" else text)


def derive(raw: bytes | None, *, max_text_chars: int, headers_only: bool = False) -> Derived:
    derived = Derived()
    if raw is None:
        return derived
    message = message_from_bytes(raw, policy=DEFAULT_POLICY)
    derived.defects = len(message.defects)
    if len(message.keys()) > MAX_HEADERS:
        derived.omitted_parts.append({"part": "headers", "reason": "header_cap"})
    derived.message_id = clean((_MSGID.findall(str(message.get("Message-ID", ""))) or [""])[0])
    derived.in_reply_to = [clean(v) for v in _MSGID.findall(str(message.get("In-Reply-To", "")))]
    derived.references = [clean(v) for v in _MSGID.findall(str(message.get("References", "")))]
    derived.from_addresses = [clean(addr) for _, addr in getaddresses([str(v) for v in message.get_all("From", [])])]
    derived.date_header = redact_short(str(message.get("Date", "")))[:200]
    for name in ("Auto-Submitted", "Precedence", "X-Autoreply", "X-Autorespond", "List-Id", "List-Unsubscribe"):
        if message.get(name) is not None:
            derived.auto_markers[name.lower()] = redact_short(str(message.get(name)))[:200]
    if derived.defects:
        derived.omitted_parts.append({"part": "message", "reason": "mime_defects", "count": derived.defects})
    if message.get_content_type() == "multipart/report" and "delivery-status" in str(message.get("Content-Type", "")).lower():
        derived.is_bounce = True
    derived.filed_copy = clean(str(message.get(FILED_COPY_HEADER, "")))[:200]
    derived.authentication_results = [clean(str(v)) for v in message.get_all("Authentication-Results", [])][:50]
    if headers_only:
        derived.omitted_parts.append({"part": "body", "reason": "oversize"})
        return derived
    chunks: list = []
    try:
        _walk(message, derived, chunks, 0, [0])
    except (IndexError, TypeError, ValueError, LookupError):
        derived.omitted_parts.append({"part": "body", "reason": "unparseable"})
    text, count = redact("\n".join(chunks))
    if count:
        derived.redactions["confirmation_link"] = count
    if len(text) > max_text_chars:
        text, derived.truncated, derived.truncated_at_chars = text[:max_text_chars], True, max_text_chars
    derived.text = text
    return derived


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
