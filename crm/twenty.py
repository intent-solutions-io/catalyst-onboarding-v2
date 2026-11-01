"""The Twenty REST client (bgl.14; 034 rows 42 and 43): the only code in Catalyst v2 that sends a request to Twenty.

The first generation's API is kept: `/rest/people`, `/rest/notes` and `/rest/noteTargets`, with the same filters and the
same response shapes (`data.people`, `data.createPerson`, `data.updatePerson`, `data.person`, and the note
equivalents), authenticated with a bearer token. What the projection writes, and when, lives in `crm.projection`; this
module only moves JSON and classifies failures.

Every exchange, like the Documenso client's (agreements.provider):

- goes to `CATALYST_TWENTY_URL`'s host, connected at the pinned `CATALYST_TWENTY_ADDRESS` and nowhere else; the
  connected peer is checked before TLS, so a resolver can never redirect it. In `test` and `staging` the address must
  be a literal loopback address (re-checked here, not only at start-up);
- verifies TLS against `CATALYST_TWENTY_CA_FILE` (never switched off, never the process's default store);
- follows no redirect, caps the response at `CATALYST_TWENTY_MAX_BYTES` and bounds the whole exchange with one deadline
  (`CATALYST_TWENTY_DEADLINE_SECONDS`), and retries nothing itself: the ledger's bounded attempts are the only retry;
- sends the token only in `Authorization`, never in an error, a log line or `repr`. Errors carry a code and an HTTP
  status, never a body (Twenty echoes submitted values back in its error payloads).

`TwentyError.sent` says whether the request may have reached Twenty. For a write, `unknown` is true when it did and the
outcome cannot be known (a timeout, a reset, a 5xx); the projection never relies on that distinction to avoid a
duplicate, because it reads before every write (a lost create is found again by the case id it carries).
"""

import http.client
import ipaddress
import json
import re
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlsplit

from django.conf import settings

USER_AGENT = "catalyst-onboarding/crm"
SEARCH_LIMIT = 10
RECORD_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
RETRYABLE = frozenset({408, 425, 429, 500, 502, 503, 504})


class TwentyError(Exception):
    """`code` is a reason code; `sent` says whether the request may have reached Twenty; `status` is the HTTP status."""

    def __init__(self, code: str, *, sent: bool, status: int | None = None):
        super().__init__(code)
        self.code, self.sent, self.status = code, sent, status

    @property
    def rejected(self) -> bool:
        """Twenty refused the request (a 4xx other than the retryable ones): another attempt cannot help."""
        return self.status is not None and 400 <= self.status < 500 and self.status not in RETRYABLE

    @property
    def unknown(self) -> bool:
        """For a write: Twenty may have acted."""
        return self.sent and not self.rejected and self.status not in (425, 429)

    def __repr__(self):
        return f"TwentyError({self.code!r}, sent={self.sent}, status={self.status})"


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes


def configured() -> bool:
    return bool(settings.CATALYST_TWENTY_URL and settings.CATALYST_TWENTY_TOKEN)


def normalize_email(address: str) -> str:
    """The first generation's matching key, exactly: trimmed and case-folded (matching only, never delivery)."""
    return str(address or "").strip().casefold()


def _target():
    url = settings.CATALYST_TWENTY_URL
    if not url or not settings.CATALYST_TWENTY_TOKEN:
        raise TwentyError("twenty_not_configured", sent=False)
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment or parts.username:
        raise TwentyError("twenty_url_invalid", sent=False)
    from config import parity

    if parity.enabled(settings) and parity.endpoint_problems(
            settings, "CATALYST_TWENTY_URL", pinned="CATALYST_TWENTY_ADDRESS", trust="CATALYST_TWENTY_CA_FILE"):
        raise TwentyError("twenty_target_not_approved", sent=False)
    address = settings.CATALYST_TWENTY_ADDRESS
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        raise TwentyError("twenty_address_not_pinned", sent=False) from None
    if settings.CATALYST_ENV in ("test", "staging") and not parsed.is_loopback:
        raise TwentyError("twenty_address_not_pinned", sent=False)  # the synthetic environments reach the stub only
    if not settings.CATALYST_TWENTY_CA_FILE:
        raise TwentyError("twenty_trust_store_missing", sent=False)
    return parts.hostname, parts.port or 443, parts.path.rstrip("/"), address


def exchange(method: str, path: str, *, query: dict | None = None, body: dict | None = None,
             allow_404: bool = False) -> Response | None:
    """One bounded HTTPS exchange. Returns the 2xx response (None for a 404 when `allow_404`); raises TwentyError for
    anything else."""
    host, port, base, address = _target()
    deadline = time.monotonic() + settings.CATALYST_TWENTY_DEADLINE_SECONDS
    sent = False
    raw, watchdog, expired, live = None, None, threading.Event(), {}
    payload = None if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()

    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise TwentyError("deadline_exceeded", sent=sent)
        return left

    def expire():
        expired.set()
        try:
            live["sock"].shutdown(socket.SHUT_RDWR)
        except (OSError, KeyError):
            pass

    try:
        raw = socket.create_connection((address, port), timeout=min(10.0, remaining()))
        live["sock"] = raw
        watchdog = threading.Timer(remaining(), expire)
        watchdog.daemon = True
        watchdog.start()
        if raw.getpeername()[0] != address:
            raise TwentyError("peer_not_allowed", sent=False)
        context = ssl.create_default_context(cafile=settings.CATALYST_TWENTY_CA_FILE)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        tls = context.wrap_socket(raw, server_hostname=host, do_handshake_on_connect=False)
        raw = live["sock"] = tls
        tls.settimeout(remaining())
        tls.do_handshake()
        connection = http.client.HTTPSConnection(host, port, timeout=remaining())
        connection.sock = tls  # never reconnects or re-resolves
        target = f"{base}{path}" + (f"?{urlencode(query)}" if query else "")
        connection.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", host if port == 443 else f"{host}:{port}")
        connection.putheader("User-Agent", USER_AGENT)
        connection.putheader("Accept", "application/json")
        connection.putheader("Accept-Encoding", "identity")
        connection.putheader("Connection", "close")
        connection.putheader("Authorization", f"Bearer {settings.CATALYST_TWENTY_TOKEN}")
        if payload is not None:
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(len(payload)))
        sent = True  # from here on, Twenty may receive the request
        connection.endheaders(payload)
        tls.settimeout(remaining())
        response = connection.getresponse()
        if expired.is_set():
            raise TwentyError("deadline_exceeded", sent=True)
        status = response.status
        if 300 <= status < 400:
            raise TwentyError("redirect_refused", sent=True, status=status)
        if status == 404 and allow_404:
            return None
        if not 200 <= status < 300:
            raise TwentyError(f"http_{status}", sent=True, status=status)
        if (response.getheader("Content-Encoding") or "identity").strip().lower() != "identity":
            raise TwentyError("content_encoding_refused", sent=True, status=status)
        cap, chunks, size = settings.CATALYST_TWENTY_MAX_BYTES, [], 0
        while True:
            tls.settimeout(remaining())
            chunk = response.read1(min(65536, cap + 1 - size))
            if expired.is_set():
                raise TwentyError("deadline_exceeded", sent=True, status=status)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > cap:
                raise TwentyError("response_too_large", sent=True, status=status)
        return Response(status, b"".join(chunks))
    except TwentyError:
        raise
    except ssl.SSLCertVerificationError:
        raise TwentyError("tls_certificate_refused", sent=sent) from None
    except (TimeoutError, socket.timeout):
        raise TwentyError("deadline_exceeded" if expired.is_set() else "timeout", sent=sent) from None
    except (ssl.SSLError, ConnectionError, OSError, http.client.HTTPException, ValueError):
        raise TwentyError("deadline_exceeded" if expired.is_set() else "connection_failed", sent=sent) from None
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if raw is not None:
            try:
                raw.close()
            except OSError:
                pass


def _data(response: Response | None, key: str):
    if response is None:
        return None
    try:
        payload = json.loads(response.body)
    except ValueError:
        raise TwentyError("response_unreadable", sent=True, status=response.status) from None
    if not isinstance(payload, dict):
        raise TwentyError("response_unreadable", sent=True, status=response.status)
    return (payload.get("data") or {}).get(key)


def _id(value: str) -> str:
    if not isinstance(value, str) or not RECORD_ID.fullmatch(value):
        raise TwentyError("record_id_invalid", sent=False)
    return quote(value, safe="")


def _literal(value: str) -> str:
    """A value placed inside a Twenty filter's double quotes: refused when it could end the quotes."""
    if '"' in value or "\\" in value:
        raise TwentyError("filter_value_refused", sent=False)
    return value


def _live(rows) -> list:
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("id") and not r.get("deletedAt")]


# --- People -------------------------------------------------------------------------------------------------------

def find_people(filter_expression: str) -> list:
    """People matching a REST filter expression (soft-deleted people are never returned)."""
    return _live(_data(exchange("GET", "/rest/people", query={"filter": filter_expression, "limit": SEARCH_LIMIT}),
                       "people"))


def find_people_by_field(field: str, value: str) -> list:
    """People whose TEXT `field` equals `value` exactly (the case id the projection writes)."""
    return [p for p in find_people(f'{field}[eq]:"{_literal(value)}"') if str(p.get(field) or "") == value]


def find_people_by_email(address: str) -> list:
    """Every person whose primary or additional email equals `address` after `normalize_email`, as the first
    generation matches: Twenty's `ilike` covers the primary email; additional emails are raw JSON, searched with a
    case-sensitive `like` in the lower-cased and the as-entered spelling; every candidate is then re-checked exactly
    here (`_` and `%` stay wildcards in Twenty's filter, so the filter alone is never trusted). Never fuzzy."""
    wanted = normalize_email(address)
    if not wanted:
        raise TwentyError("filter_value_refused", sent=False)
    spellings = sorted({wanted, str(address).strip()} - {""})
    clauses = [f'emails.primaryEmail[ilike]:"{_literal(wanted)}"']
    clauses += [f'emails.additionalEmails[like]:"%{_literal(s)}%"' for s in spellings]
    exact = {}
    for person in find_people(f"or({','.join(clauses)})"):
        emails = person.get("emails") or {}
        addresses = [emails.get("primaryEmail") or ""] + list(emails.get("additionalEmails") or [])
        if any(normalize_email(str(a)) == wanted for a in addresses):
            exact[str(person["id"])] = person
    return list(exact.values())


def get_person(person_id: str) -> dict | None:
    """The person, or None when it does not exist or is soft-deleted."""
    person = _data(exchange("GET", f"/rest/people/{_id(person_id)}", allow_404=True), "person")
    return person if isinstance(person, dict) and person.get("id") and not person.get("deletedAt") else None


def create_person(body: dict) -> dict:
    person = _data(exchange("POST", "/rest/people", body=body), "createPerson")
    if not isinstance(person, dict) or not person.get("id"):
        raise TwentyError("response_unreadable", sent=True, status=200)
    return person


def update_person(person_id: str, body: dict) -> dict:
    person = _data(exchange("PATCH", f"/rest/people/{_id(person_id)}", body=body), "updatePerson")
    return person if isinstance(person, dict) else {}


# --- Notes (the applicant file) -----------------------------------------------------------------------------------
# A note has `title` and the rich-text composite `bodyV2` (`markdown`, `blocknote`); writing `markdown` alone makes
# Twenty derive `blocknote`. A note is attached to a person by a `noteTargets` row (`noteId`, `targetPersonId`).

def _note_body(title: str, markdown: str) -> dict:
    return {"title": title, "bodyV2": {"markdown": markdown, "blocknote": None}}


def get_note(note_id: str) -> dict | None:
    note = _data(exchange("GET", f"/rest/notes/{_id(note_id)}", allow_404=True), "note")
    return note if isinstance(note, dict) and note.get("id") and not note.get("deletedAt") else None


def find_notes(title: str) -> list:
    """Notes whose title equals `title` exactly (soft-deleted notes are never returned)."""
    notes = _data(exchange("GET", "/rest/notes", query={"filter": f'title[eq]:"{_literal(title)}"',
                                                         "limit": SEARCH_LIMIT}), "notes")
    return [n for n in _live(notes) if n.get("title") == title]


def note_targets(note_id: str) -> list:
    """The people a note is attached to."""
    targets = _data(exchange("GET", "/rest/noteTargets", query={"filter": f'noteId[eq]:"{_literal(note_id)}"',
                                                                 "limit": SEARCH_LIMIT}), "noteTargets")
    return [str(t["targetPersonId"]) for t in _live(targets) if t.get("targetPersonId")]


def create_note(title: str, markdown: str) -> str:
    note = _data(exchange("POST", "/rest/notes", body=_note_body(title, markdown)), "createNote")
    if not isinstance(note, dict) or not note.get("id"):
        raise TwentyError("response_unreadable", sent=True, status=200)
    return str(note["id"])


def update_note(note_id: str, title: str, markdown: str) -> bool:
    """Replace a note's title and body. False when the note no longer exists (deleted in Twenty)."""
    return exchange("PATCH", f"/rest/notes/{_id(note_id)}", body=_note_body(title, markdown), allow_404=True) is not None


def attach_note(note_id: str, person_id: str) -> None:
    target = _data(exchange("POST", "/rest/noteTargets", body={"noteId": note_id, "targetPersonId": person_id}),
                   "createNoteTarget")
    if not isinstance(target, dict) or not target.get("id"):
        raise TwentyError("response_unreadable", sent=True, status=200)
