"""The hardened Documenso client (021 sections 5, 6 and 10; 4B.1). Synthetic only: the provider is the local fake.

Every exchange:

- goes to `CATALYST_AGREEMENT_PROVIDER_URL`'s host, connected at the pinned address and nowhere else; the connected
  peer is checked before TLS (a resolver can never redirect it);
- verifies TLS against the configured trust store (verification is never switched off);
- follows no redirect, caps the response size and bounds the whole exchange with one deadline;
- authenticates with the API key in `Authorization` (the installed version's documented scheme, 021 section 15),
  which never appears in an error, a log line or `repr`.

Errors carry whether the request may have reached the provider (`sent`). For a write that matters: before sending,
or on a 429 or a definite 4xx, the provider did not act; anything else after sending (a timeout, a reset, a 5xx, a
redirect, an unreadable 2xx) is an **unknown** outcome, reconciled and never retried blindly (021 section 5).

Responses are parsed into an allowlist (`Envelope`, `Recipient`). Signing tokens and signing links, which the
installed version returns from `envelope/use`, `envelope/distribute` and envelope reads, are dropped here and never
reach a record, a log or a screen (021 section 6, TEST-P4-24).
"""

import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import threading
import time
import uuid
from dataclasses import dataclass
from types import MappingProxyType
from urllib.parse import quote, urlencode, urlsplit

from django.conf import settings

USER_AGENT = "catalyst-onboarding/agreements"
ENVELOPE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
STATUSES = ("DRAFT", "PENDING", "COMPLETED", "REJECTED", "CANCELLED")  # anything else reads as UNKNOWN
SIGNING = ("NOT_SIGNED", "SIGNED", "REJECTED")
ROLES = ("CC", "SIGNER", "VIEWER", "APPROVER", "ASSISTANT")
# D-41: the provider's own email, per envelope (`emailSettings`, installed v2.20.0). Every setting keeps the
# provider's default except `documentDeleted`, which is suppressed, so a protective cancel never mails the applicant.
# The signing request and the completed copy (P4-D-14) stay on. Sent whole on create and distribute, so a later call can never fall back to the
# all-true default. Whether the installation honours it is NOT VERIFIED until an authorized canary (D-41).
EMAIL_SETTINGS = MappingProxyType({"recipientSigningRequest": True, "recipientRemoved": True, "recipientSigned": True,
                  "documentPending": True, "documentCompleted": True, "documentDeleted": False,
                  "ownerDocumentCompleted": True, "ownerRecipientExpired": True, "ownerDocumentCreated": True})
CANCEL_REASON = "This agreement request was withdrawn."  # fixed and generic: never staff notes (D-41)
UNKNOWN_STATUSES = (408,)  # a timeout reply: the provider may still act


class ProviderError(Exception):
    """`code` is a reason code; `sent` says whether the request may have reached the provider."""

    def __init__(self, code: str, *, sent: bool, status: int | None = None, retry_after: float | None = None):
        super().__init__(code)
        self.code, self.sent, self.status, self.retry_after = code, sent, status, retry_after

    @property
    def unknown(self) -> bool:
        """For a write: the provider may have acted, so the outcome is unknown."""
        if not self.sent:
            return False
        if self.status is None or self.status in UNKNOWN_STATUSES:
            return True
        return not (400 <= self.status < 500)  # 3xx, 5xx: unknown; 4xx (429 included): the provider did not act

    def __repr__(self):
        return f"ProviderError({self.code!r}, sent={self.sent}, status={self.status})"


@dataclass(frozen=True)
class Recipient:
    email: str
    role: str
    signing_order: int | None
    signing_status: str
    expired: bool = False


@dataclass(frozen=True)
class Envelope:
    id: str
    external_id: str
    status: str
    template_number: int | None
    type: str
    recipients: tuple
    created_at: str = ""
    items: tuple = ()  # the envelope's item ids (validated), for custody


@dataclass(frozen=True)
class Response:
    status: int
    content_type: str
    body: bytes


def configured() -> bool:
    return bool(settings.CATALYST_AGREEMENT_PROVIDER_URL)


def _target():
    url = settings.CATALYST_AGREEMENT_PROVIDER_URL
    if not url:
        raise ProviderError("provider_not_configured", sent=False)
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
        raise ProviderError("provider_url_invalid", sent=False)
    address = settings.CATALYST_AGREEMENT_PROVIDER_ADDRESS
    try:
        loopback = ipaddress.ip_address(address).is_loopback
    except ValueError:
        loopback = False
    if not loopback:  # re-checked here, not only at start-up: synthetic P4 talks to a local fake only
        raise ProviderError("provider_address_not_pinned", sent=False)
    if not settings.CATALYST_AGREEMENT_PROVIDER_CA_FILE:
        raise ProviderError("provider_trust_store_missing", sent=False)  # never the system store, never SSL_CERT_* vars
    return parts.hostname, parts.port or 443, parts.path.rstrip("/"), address


def _tls_context():
    context = ssl.create_default_context(cafile=settings.CATALYST_AGREEMENT_PROVIDER_CA_FILE)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def exchange(method: str, path: str, *, query: dict | None = None, body: bytes | None = None,
             content_type: str = "", recipient_route: bool = False) -> Response:
    """One bounded HTTPS exchange. Raises ProviderError for anything but a 2xx or a 4xx response with a body.

    `recipient_route` (bgl.9, the countersignature): `path` is from the host's root, not under the API base, and the
    request carries no API key; it sends the instance's own `Origin` instead, the check the installed version applies
    to a token-authenticated mutation. The credential is the recipient token in the body."""
    host, port, base, address = _target()
    if recipient_route:
        base = ""
    deadline = time.monotonic() + settings.CATALYST_AGREEMENT_DEADLINE_SECONDS
    sent = False
    raw, watchdog, expired, live = None, None, threading.Event(), {}

    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise ProviderError("deadline_exceeded", sent=sent)
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
            raise ProviderError("peer_not_allowed", sent=False)
        tls = _tls_context().wrap_socket(raw, server_hostname=host, do_handshake_on_connect=False)
        raw = live["sock"] = tls
        tls.settimeout(remaining())
        tls.do_handshake()
        connection = http.client.HTTPSConnection(host, port, timeout=remaining())
        connection.sock = tls  # never reconnects or re-resolves
        target = f"{base}{path}" + (f"?{urlencode(query)}" if query else "")
        connection.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", host if port == 443 else f"{host}:{port}")
        connection.putheader("User-Agent", USER_AGENT)
        connection.putheader("Accept-Encoding", "identity")
        connection.putheader("Connection", "close")
        if recipient_route:
            connection.putheader("Origin", f"https://{host}" + ("" if port == 443 else f":{port}"))
        else:
            connection.putheader("Authorization", settings.CATALYST_AGREEMENT_PROVIDER_TOKEN)
        if body is not None:
            connection.putheader("Content-Type", content_type)
            connection.putheader("Content-Length", str(len(body)))
        sent = True  # from here on, the provider may receive the request
        connection.endheaders(body)
        tls.settimeout(remaining())
        response = connection.getresponse()
        if expired.is_set():
            raise ProviderError("deadline_exceeded", sent=True)
        status = response.status
        if 300 <= status < 400:
            raise ProviderError("redirect_refused", sent=True, status=status)  # never followed, on or off host
        if status == 429:
            raise ProviderError("rate_limited", sent=True, status=429, retry_after=_retry_after(response))
        if (response.getheader("Content-Encoding") or "identity").strip().lower() != "identity":
            raise ProviderError("content_encoding_refused", sent=True, status=status)
        cap, chunks, size = settings.CATALYST_AGREEMENT_MAX_BYTES, [], 0
        while True:
            tls.settimeout(remaining())
            chunk = response.read1(min(65536, cap + 1 - size))
            if expired.is_set():
                raise ProviderError("deadline_exceeded", sent=True, status=status)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > cap:
                raise ProviderError("response_too_large", sent=True, status=status)
        declared = response.getheader("Content-Length")
        if declared is not None and declared.isdigit() and int(declared) != size:
            raise ProviderError("response_truncated", sent=True, status=status)
        if not 200 <= status < 300:
            raise ProviderError(f"http_{status}", sent=True, status=status)
        content = (response.getheader("Content-Type") or "").split(";")[0].strip().lower()
        return Response(status, content, b"".join(chunks))
    except ProviderError:
        raise
    except ssl.SSLCertVerificationError:
        raise ProviderError("tls_certificate_refused", sent=sent) from None
    except (TimeoutError, socket.timeout):
        raise ProviderError("deadline_exceeded" if expired.is_set() else "timeout", sent=sent) from None
    except (ssl.SSLError, ConnectionError, OSError, http.client.HTTPException, ValueError):
        raise ProviderError("deadline_exceeded" if expired.is_set() else "connection_failed", sent=sent) from None
    finally:
        if watchdog is not None:
            watchdog.cancel()
        if raw is not None:
            try:
                raw.close()
            except OSError:
                pass


def _retry_after(response) -> float | None:
    value = (response.getheader("Retry-After") or "").strip()
    try:
        seconds = float(value) if value else None
    except ValueError:
        return None  # an HTTP-date is not honoured: the ledger's backoff applies instead
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return None
    return min(seconds, float(settings.CATALYST_AGREEMENT_RETRY_AFTER_MAX_SECONDS))


def _json(response: Response):
    if response.content_type != "application/json":
        raise ProviderError("response_not_json", sent=True, status=response.status)
    try:
        return json.loads(response.body)
    except ValueError:
        raise ProviderError("response_unreadable", sent=True, status=response.status) from None


def _text(value, limit=320) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _enum(value, allowed) -> str:
    """A provider-controlled code reaches records only as one of the known values (4B.1 review)."""
    return value if value in allowed else "UNKNOWN"


def _envelope_id(value) -> str:
    if not isinstance(value, str) or not ENVELOPE_ID.fullmatch(value):
        raise ProviderError("response_unreadable", sent=True, status=200)
    return value


def _recipient(raw) -> Recipient:
    if not isinstance(raw, dict):
        raise ProviderError("response_unreadable", sent=True, status=200)
    order = raw.get("signingOrder")
    return Recipient(email=_text(raw.get("email")), role=_enum(raw.get("role"), ROLES),
                     signing_order=order if isinstance(order, int) and not isinstance(order, bool) else None,
                     signing_status=_enum(raw.get("signingStatus"), SIGNING), expired=bool(raw.get("expired")))


def envelope(raw) -> Envelope:
    """The allowlist: everything else in a provider response (tokens, signing links, names, fields) is dropped."""
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not isinstance(raw.get("recipients", []), list):
        raise ProviderError("response_unreadable", sent=True, status=200)
    number = raw.get("templateId")
    return Envelope(id=_envelope_id(raw["id"]), external_id=_text(raw.get("externalId"), 64),
                    status=_enum(raw.get("status"), STATUSES),
                    template_number=number if isinstance(number, int) and not isinstance(number, bool) else None,
                    type=_enum(raw.get("type"), ("DOCUMENT", "TEMPLATE")), recipients=tuple(_recipient(r) for r in raw.get("recipients", [])),
                    created_at=_text(raw.get("createdAt"), 40),
                    items=tuple(_envelope_id(i.get("id")) for i in raw.get("envelopeItems", [])
                                if isinstance(i, dict))[:20] if isinstance(raw.get("envelopeItems", []), list) else ())


def _multipart(payload: dict) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"payload\"\r\n"
            f"Content-Type: application/json\r\n\r\n{json.dumps(payload)}\r\n--{boundary}--\r\n").encode()
    return body, f"multipart/form-data; boundary={boundary}"


# --- operations (the installed v2.20.0 envelope API; 021 section 15) -------------------------------------------

def create_from_template(template_ref: str, external_key: str, recipients: list[dict]) -> str:
    """`POST /envelope/use` as a draft (`distributeDocument: false`, P4-D-4). Returns the new envelope id only."""
    body, content_type = _multipart({"envelopeId": template_ref, "externalId": external_key,
                                     "recipients": recipients, "distributeDocument": False,
                                     "override": {"emailSettings": dict(EMAIL_SETTINGS)}})
    data = _json(exchange("POST", "/envelope/use", body=body, content_type=content_type))
    if not isinstance(data, dict):
        raise ProviderError("response_unreadable", sent=True, status=200)
    return _envelope_id(data.get("id"))


def distribute(envelope_id: str) -> None:
    """`POST /envelope/distribute`: Documenso emails the recipients. No subject or message is sent (021 section 10)."""
    body = json.dumps({"envelopeId": envelope_id,
                       "meta": {"distributionMethod": "EMAIL", "emailSettings": dict(EMAIL_SETTINGS)}}).encode()
    _json(exchange("POST", "/envelope/distribute", body=body, content_type="application/json"))


def read(envelope_id: str) -> Envelope:
    return envelope(_json(exchange("GET", f"/envelope/{quote(envelope_id, safe='')}")))


def find(template_number: int, page: int) -> tuple[list[Envelope], int]:
    """One page of documents created from a template, newest first (the bounded reconciliation listing: the installed
    version has no lookup by `externalId`, 021 section 15). Returns the page and the total page count."""
    query = {"type": "DOCUMENT", "templateId": template_number, "orderByColumn": "createdAt",
             "orderByDirection": "desc", "page": page, "perPage": settings.CATALYST_AGREEMENT_LIST_PAGE_SIZE}
    data = _json(exchange("GET", "/envelope", query=query))
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ProviderError("response_unreadable", sent=True, status=200)
    pages = data.get("totalPages")
    return [envelope(e) for e in data["data"]], pages if isinstance(pages, int) and not isinstance(pages, bool) else 1


def find_recent(page: int) -> list[Envelope]:
    """One page of the team's documents, newest first, from every template (9kg.76: the post-restore listing). The page
    count is not returned: a caller that must be complete stops only on a short page or on a date it can check."""
    query = {"type": "DOCUMENT", "orderByColumn": "createdAt", "orderByDirection": "desc", "page": page,
             "perPage": settings.CATALYST_AGREEMENT_LIST_PAGE_SIZE}
    data = _json(exchange("GET", "/envelope", query=query))
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ProviderError("response_unreadable", sent=True, status=200)
    return [envelope(e) for e in data["data"]]


def cancel(envelope_id: str) -> None:
    body = json.dumps({"envelopeId": envelope_id, "reason": CANCEL_REASON}).encode()
    exchange("POST", "/envelope/cancel", body=body, content_type="application/json")


def download(item_id: str) -> bytes:
    """The signed PDF of an envelope item (4B.3 stores it). Anything that is not a PDF is refused."""
    response = exchange("GET", f"/envelope/item/{quote(item_id, safe='')}/download", query={"version": "signed"})
    if not response.body.startswith(b"%PDF-"):
        raise ProviderError("download_not_pdf", sent=True, status=response.status)
    return response.body


# --- the company countersignature (bgl.9; 034 row 30; first-generation decision 12) ----------------------------------
# The installed version has no API-key route that signs as a recipient. The first generation signs through the routes
# the provider's own signing page uses, authenticated by the recipient's token: `envelope.field.sign` for each of the
# company recipient's signature fields, then `recipient.completeDocumentWithToken`. The provider then runs its own
# checks (pending envelope, signing order, required fields, expiry), writes its own audit log and seals the document.
# The request and response shapes below are the ones the first generation uses against its installed version; for v2
# they are NOT VERIFIED until an authorized canary, like every other provider shape here (021 section 15).
RECIPIENT_TOKEN = re.compile(r"^[A-Za-z0-9_-]{8,128}$")
DOCUMENT_NUMBER = re.compile(r"^document_([0-9]{1,12})$")
SIGN_FIELD = "/api/trpc/envelope.field.sign"
COMPLETE = "/api/trpc/recipient.completeDocumentWithToken"
UNSIGNED_COMPANY_FIELDS = ("SIGNATURE", "DATE")  # a DATE field is filled by the provider at completion


class CountersignRefused(Exception):
    """A condition for signing does not hold. Nothing was sent: `code` names the failed check."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def countersign(envelope_id: str, external_key: str, email: str, role: str, signature: str) -> str:
    """Sign as the company recipient (`email`, `role`, order 2) and complete its part; returns the provider's status
    for the completion (`SIGNED`, or `ALREADY_SIGNED` when the recipient had completed meanwhile).

    A fresh `GET envelope/{id}` first, and nothing is sent unless it shows our envelope (`externalId` equal to
    `external_key`, which must be a v2 `ag_` key: an envelope v2 did not create is never touched), PENDING, exactly two
    recipients in order with the applicant SIGNER signed, the company recipient not signed and not expired, nobody
    rejected, the company's own unsigned fields only signatures (and dates the provider fills), at least one signature
    field, and a plain token. Raises CountersignRefused for a failed condition (nothing sent) and ProviderError for an
    exchange that failed (its `sent` says whether a write may have reached the provider). The recipient token is used
    in memory for these two calls and never returned, recorded or logged."""
    if not external_key.startswith("ag_"):
        raise CountersignRefused("not_a_v2_envelope")
    raw = _json(exchange("GET", f"/envelope/{quote(envelope_id, safe='')}"))
    if not isinstance(raw, dict) or raw.get("id") != envelope_id:
        raise CountersignRefused("identity_mismatch")
    if raw.get("externalId") != external_key:
        raise CountersignRefused("not_a_v2_envelope")
    if raw.get("status") != "PENDING":
        raise CountersignRefused("envelope_not_pending")
    recipients = raw.get("recipients")
    if not isinstance(recipients, list) or len(recipients) != 2 or not all(isinstance(r, dict) for r in recipients):
        raise CountersignRefused("recipients_unexpected")
    applicant, company = sorted(recipients, key=lambda r: r.get("signingOrder") if isinstance(r.get("signingOrder"), int) else 99)
    if (applicant.get("signingOrder"), company.get("signingOrder")) != (1, 2) or applicant.get("role") != "SIGNER":
        raise CountersignRefused("recipients_unexpected")
    if (not isinstance(company.get("email"), str) or company["email"].casefold() != email.casefold()
            or company.get("role") != role):
        raise CountersignRefused("company_recipient_unexpected")
    if any(r.get("signingStatus") == "REJECTED" for r in recipients):
        raise CountersignRefused("rejected")
    if applicant.get("signingStatus") != "SIGNED":
        raise CountersignRefused("applicant_not_signed")
    if company.get("signingStatus") == "SIGNED":
        return "ALREADY_SIGNED"
    if company.get("signingStatus") != "NOT_SIGNED" or company.get("expired"):
        raise CountersignRefused("company_recipient_not_signable")
    token = company.get("token")
    if not isinstance(token, str) or not RECIPIENT_TOKEN.fullmatch(token):
        raise CountersignRefused("recipient_token_missing")
    number = DOCUMENT_NUMBER.fullmatch(str(raw.get("secondaryId") or ""))
    if number is None:
        raise CountersignRefused("document_number_missing")
    fields = raw.get("fields", [])
    own = [f for f in fields if isinstance(f, dict) and f.get("recipientId") == company.get("id")] \
        if isinstance(fields, list) and company.get("id") is not None else []
    if not any(f.get("type") == "SIGNATURE" for f in own):
        raise CountersignRefused("company_signature_field_missing")
    if any(f.get("inserted") is not True and f.get("type") not in UNSIGNED_COMPANY_FIELDS for f in own):
        raise CountersignRefused("company_fields_unexpected")
    for field in own:
        if field.get("type") != "SIGNATURE" or field.get("inserted") is True:
            continue
        if not isinstance(field.get("id"), int) or isinstance(field.get("id"), bool):
            raise CountersignRefused("company_fields_unexpected")
        body = json.dumps({"json": {"token": token, "fieldId": field["id"],
                                    "fieldValue": {"type": "SIGNATURE", "value": signature}}}).encode()
        _json(exchange("POST", SIGN_FIELD, body=body, content_type="application/json", recipient_route=True))
    body = json.dumps({"json": {"token": token, "documentId": int(number.group(1))}}).encode()
    data = _json(exchange("POST", COMPLETE, body=body, content_type="application/json", recipient_route=True))
    result = ((data.get("result") or {}).get("data") or {}).get("json") if isinstance(data, dict) else None
    status = result.get("status") if isinstance(result, dict) else None
    if status not in ("SIGNED", "ALREADY_SIGNED"):
        raise ProviderError("countersign_unexpected_response", sent=True)  # unknown: the next attempt reads first
    return status


EVENTS = ("DOCUMENT_CREATED", "DOCUMENT_SENT", "DOCUMENT_OPENED", "DOCUMENT_SIGNED", "DOCUMENT_RECIPIENT_COMPLETED",
          "DOCUMENT_COMPLETED", "DOCUMENT_REJECTED", "DOCUMENT_CANCELLED", "DOCUMENT_REMINDER_SENT",
          "DOCUMENT_RECIPIENT_REJECTED")


@dataclass(frozen=True)
class Hint:
    """A webhook body, allowlisted (021 section 6). The installed version posts `{event, payload, createdAt,
    webhookEndpoint}`; `payload` is the document with its legacy numeric id, `externalId`, `status`, `templateId` and
    recipients, tokens included (021 section 15). Only these facts survive; a hint never verifies anything."""

    event: str
    external_id: str
    status: str
    template_number: int | None
    recipients: tuple


def hint(raw) -> Hint | None:
    if not isinstance(raw, dict) or not isinstance(raw.get("payload"), dict):
        return None
    doc = raw["payload"]
    recipients = doc.get("recipients", [])
    if not isinstance(recipients, list) or len(recipients) > 20 or not all(isinstance(r, dict) for r in recipients):
        return None
    number = doc.get("templateId")
    return Hint(event=_enum(raw.get("event"), EVENTS), external_id=_text(doc.get("externalId"), 64),
                status=_enum(doc.get("status"), STATUSES),
                template_number=number if isinstance(number, int) and not isinstance(number, bool) else None,
                recipients=tuple(_recipient(r) for r in recipients))

