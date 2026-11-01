"""The live MXroute mail host behind `provisioning.adapter.MailHost`, and the IMAP login check of a one-time password
(034 rows 37 and 39; 023 sections 3, 11.1 and 11.8). Built; nothing activates it: the settings it reads are empty by
default, `config.guards` refuses them outside the test and staging environments, and the adapter setting itself must
still name a test fake there, so the live class is reached only through a stub transport until the owner's separate
canary authorizes the live path (D-47, D-48).

The API contract, from the first-generation service's recorded behaviour and the published schema (023 section 3):

| Operation          | Call                                                | Answer                                   |
|--------------------|-----------------------------------------------------|------------------------------------------|
| `read`             | `GET /domains/{domain}/email-accounts/{local}`      | 200 `{success, data}`; 404 means absent  |
| `create`           | `POST /domains/{domain}/email-accounts`             | 201; `username`, `password`, `quota`, `limit` |
| `set_password`     | `PATCH /domains/{domain}/email-accounts/{local}`    | 200; `password` only                     |
| `list_forwarders`  | `GET /domains/{domain}/forwarders`                  | 200 `{success, data: [{alias, ...}]}`     |
| `delete_forwarder` | `DELETE /domains/{domain}/forwarders/{alias}`       | 200 or 204; 404 means already gone       |
| `read_catch_all`   | `GET /domains/{domain}/catch-all`                   | 200 `{success, data}`; 404 means none    |

Authentication is three headers (`X-Server`, `X-Username`, `X-API-Key`), the key read from the configured file at call
time and held only for the call (023 11.1: one hosting user's key, never a reseller's; never in settings or the
environment). The forwarder and catch-all field names and the delete route are documented operations whose exact
shapes are NOT VERIFIED against the live service; a body that does not fit raises, never guesses.

Errors follow the P4 taxonomy through `AdapterError`: a transport failure before anything was sent is definite and
not sent; a timeout or dropped connection after sending, a 5xx (MXroute's 500 for a failed or ambiguous lookup
included) and a 429 are unknown outcomes; only another 4xx is a definite rejection. The exception carries a reason code
and the status: never a body, an address or the key. Logging is allowlisted to the operation, the status and the
elapsed time (the route carries the local part, which is personal data, so it is never logged).

The HTTP client is `httpx2`, already in the dependency set (the model clients use it); the transport is injectable, and
the test suite's raising transport covers the default one, so no test can reach a network through it.
"""

import imaplib
import logging
import ssl
import time
from dataclasses import dataclass

from django.conf import settings

from .adapter import CODE, AdapterError, MailHost, Mailbox
from .naming import SAFE as SAFE_LOCAL_PART

logger = logging.getLogger(__name__)

NOT_SENT = ("ConnectError", "ConnectTimeout", "UnsupportedProtocol", "InvalidURL", "ProxyError", "LocalProtocolError")


@dataclass(frozen=True)
class Timeout:
    connect: float
    read: float


@dataclass(frozen=True)
class Response:
    status: int
    body: object  # the decoded JSON body, or None
    retry_after: float | None = None


class TransportFailure(Exception):
    """No HTTP answer. `sent` says whether the request may have reached the host (a read timeout) or provably did not
    (a refused connection, a bad URL). The code is the failure's class name, never its message."""

    def __init__(self, code: str, *, sent: bool):
        super().__init__(code)
        self.code, self.sent = code, sent


class HttpxTransport:
    """The default transport: one short-lived client per call, certificate verification on, no proxy from the
    environment. Exceptions are reduced to their class name with `from None`, so no traceback keeps a request body."""

    def __call__(self, method: str, url: str, headers: dict, body: dict | None, timeout: Timeout) -> Response:
        import httpx2

        try:
            with httpx2.Client(timeout=httpx2.Timeout(timeout.read, connect=timeout.connect), trust_env=False) as client:
                answer = client.request(method, url, headers=headers, json=body)
        except httpx2.HTTPError as exc:
            name = type(exc).__name__
            raise TransportFailure(name, sent=name not in NOT_SENT) from None
        except httpx2.InvalidURL:
            raise TransportFailure("InvalidURL", sent=False) from None
        try:
            decoded = answer.json() if answer.content else None
        except ValueError:
            decoded = None
        return Response(answer.status_code, decoded, _retry_after(answer.headers.get("Retry-After")))


def _retry_after(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _code(value, default: str) -> str:
    code = str(value or "").lower()
    return code if CODE.fullmatch(code) else default


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class MXrouteHost(MailHost):
    """The documented mailbox operations only. No delete of a mailbox, no suspend, no domain or reseller operation
    exists here, and every route is built from the configured domain and a validated local part (023 11.8)."""

    def __init__(self, transport=None):
        self._transport = transport if transport is not None else HttpxTransport()

    # --- configuration and the key --------------------------------------------------------------------------------

    def _base(self) -> str:
        from config import parity

        if parity.enabled(settings) and parity.provisioning_problems(settings):
            raise AdapterError("mail_host_target_not_approved", sent=False)
        base = (settings.CATALYST_PROVISIONING_API_URL or "").rstrip("/")
        if not (base and settings.CATALYST_PROVISIONING_API_SERVER and settings.CATALYST_PROVISIONING_API_ACCOUNT
                and settings.CATALYST_PROVISIONING_API_KEY_FILE):
            raise AdapterError("mail_host_not_configured", sent=False)
        if not (base.startswith("https://") or base.startswith("http://127.0.0.1") or base.startswith("http://localhost")):
            raise AdapterError("mail_host_url_not_https", sent=False)
        return base

    def _headers(self) -> dict:
        try:
            with open(settings.CATALYST_PROVISIONING_API_KEY_FILE, encoding="utf-8") as handle:
                key = handle.read().strip()
        except (OSError, UnicodeDecodeError):
            raise AdapterError("mail_host_credential_unreadable", sent=False) from None
        if not key:
            raise AdapterError("mail_host_credential_empty", sent=False)
        return {"X-Server": settings.CATALYST_PROVISIONING_API_SERVER, "X-Username": settings.CATALYST_PROVISIONING_API_ACCOUNT,
                "X-API-Key": key, "Accept": "application/json"}

    def _route(self, domain: str, kind: str, item: str | None = None) -> str:
        from urllib.parse import quote

        configured = (settings.CATALYST_PROVISIONING_DOMAIN or "").lower()
        if not configured or (domain or "").lower() != configured:
            raise AdapterError("domain_not_allowed", sent=False)  # one domain's mailbox, forwarder and catch-all routes only
        path = f"/domains/{quote(configured, safe='')}/{kind}"
        if item is not None:
            item = (item or "").lower()
            if not SAFE_LOCAL_PART.fullmatch(item) or ".." in item:
                raise AdapterError("local_part_invalid", sent=False)
            path += f"/{quote(item, safe='')}"
        return path

    def _call(self, operation: str, method: str, path: str, body: dict | None = None) -> Response:
        base = self._base()
        timeout = Timeout(settings.CATALYST_PROVISIONING_API_CONNECT_SECONDS, settings.CATALYST_PROVISIONING_API_READ_SECONDS)
        headers = self._headers()
        started = time.monotonic()
        try:
            answer = self._transport(method, base + path, headers, body, timeout)
        except TransportFailure as exc:
            logger.info("mxroute %s: no answer (%s, sent=%s)", operation, exc.code, exc.sent)
            raise AdapterError(_code(exc.code, "transport_error"), sent=exc.sent) from None
        finally:
            del headers  # the key is held for the call only
        logger.info("mxroute %s -> %s in %d ms", operation, answer.status, int((time.monotonic() - started) * 1000))
        return answer

    @staticmethod
    def _refuse(answer: Response) -> None:
        """Raise for anything but a 2xx, with the P4 taxonomy: 429 and 5xx unknown, 409 a conflict, other 4xx definite."""
        status = answer.status
        if 200 <= status < 300:
            return
        error = answer.body.get("error") if isinstance(answer.body, dict) else None
        reported = error.get("code") if isinstance(error, dict) else None
        if status == 429:
            raise AdapterError("rate_limited", sent=True, status=429, retry_after=answer.retry_after)
        if status >= 500:
            raise AdapterError(_code(reported, "server_error"), sent=True, status=status)
        if status == 409:
            raise AdapterError("conflict", sent=True, status=409)
        raise AdapterError(_code(reported, "rejected"), sent=True, status=status)

    @staticmethod
    def _data(answer: Response, operation: str):
        body = answer.body
        if not isinstance(body, dict) or body.get("success") is not True or "data" not in body:
            raise AdapterError(f"{operation}_schema_error", sent=True, status=answer.status)
        return body["data"]

    @staticmethod
    def _confirmed(answer: Response, operation: str) -> None:
        if not isinstance(answer.body, dict) or answer.body.get("success") is not True:
            raise AdapterError(f"{operation}_not_confirmed", sent=True, status=answer.status)  # 2xx without the confirmation: unknown

    # --- the interface --------------------------------------------------------------------------------------------

    def read(self, domain: str, local_part: str) -> Mailbox | None:
        answer = self._call("read", "GET", self._route(domain, "email-accounts", local_part))
        if answer.status == 404:
            return None  # the one authoritative "absent"; a 500 (failed or ambiguous lookup) raises below
        self._refuse(answer)
        data = self._data(answer, "read")
        quota, limit = (_int(data.get("quota")), _int(data.get("limit"))) if isinstance(data, dict) else (None, None)
        if quota is None or limit is None:
            raise AdapterError("read_schema_error", sent=True, status=answer.status)
        username = data.get("username")
        local = username.split("@", 1)[0].lower() if isinstance(username, str) and username else local_part.lower()
        return Mailbox(local, domain.lower(), quota, limit, data.get("suspended") is True)

    def create(self, domain: str, local_part: str, password: str, quota_mb: int, send_limit: int) -> None:
        path = self._route(domain, "email-accounts")
        body = {"username": local_part.lower(), "password": password, "quota": int(quota_mb), "limit": int(send_limit)}
        try:
            answer = self._call("create", "POST", path, body)
        finally:
            del body, password
        self._refuse(answer)
        self._confirmed(answer, "create")

    def set_password(self, domain: str, local_part: str, password: str) -> None:
        path = self._route(domain, "email-accounts", local_part)
        body = {"password": password}
        try:
            answer = self._call("set_password", "PATCH", path, body)
        finally:
            del body, password
        self._refuse(answer)
        self._confirmed(answer, "set_password")

    def list_forwarders(self, domain: str) -> list[tuple[str, tuple[str, ...]]]:
        answer = self._call("list_forwarders", "GET", self._route(domain, "forwarders"))
        self._refuse(answer)
        data = self._data(answer, "list_forwarders")
        if not isinstance(data, list):
            raise AdapterError("list_forwarders_schema_error", sent=True, status=answer.status)
        found = []
        for item in data:
            alias = item.get("alias") if isinstance(item, dict) else None
            if not isinstance(alias, str) or not alias:
                raise AdapterError("list_forwarders_schema_error", sent=True, status=answer.status)
            targets = item.get("destinations", item.get("destination", ()))
            targets = [targets] if isinstance(targets, str) else targets
            if not isinstance(targets, (list, tuple)) or not all(isinstance(t, str) for t in targets):
                raise AdapterError("list_forwarders_schema_error", sent=True, status=answer.status)
            found.append((alias.split("@", 1)[0].lower(), tuple(targets)))
        return sorted(found)

    def delete_forwarder(self, domain: str, alias: str) -> None:
        answer = self._call("delete_forwarder", "DELETE", self._route(domain, "forwarders", alias))
        if answer.status == 404:
            return  # already gone: the obligation is met; closure verifies by listing (5B.3)
        self._refuse(answer)

    def read_catch_all(self, domain: str) -> str:
        answer = self._call("read_catch_all", "GET", self._route(domain, "catch-all"))
        if answer.status == 404:
            return ""
        self._refuse(answer)
        data = self._data(answer, "read_catch_all")
        if data in (None, "", {}, []):
            return ""
        address = data if isinstance(data, str) else (data.get("address") or data.get("destination") or data.get("email")
                                                        if isinstance(data, dict) else None)
        if not isinstance(address, str):
            raise AdapterError("read_catch_all_schema_error", sent=True, status=answer.status)
        return address.lower()


# --- the IMAP login check -----------------------------------------------------------------------------------------

def login_check(address: str, password: str) -> bool:
    """Log in to the configured IMAP host as the new mailbox and out again; fetch nothing. True when the server accepts
    the credential, False when it refuses it. Anything else (no host configured, TLS refused, unreachable) raises an
    `AdapterError` that was never sent, so the caller can tell "the password does not work" from "could not check".
    Implicit TLS with a verifying context; the trust store may be replaced by CATALYST_MAIL_CA_FILE for synthetic
    servers, never disabled. The password is held for the call only."""
    from correspondence.transport import tls_context

    host = settings.CATALYST_PROVISIONING_IMAP_HOST
    if not host:
        raise AdapterError("imap_not_configured", sent=False)
    try:
        imap = imaplib.IMAP4_SSL(host, settings.CATALYST_PROVISIONING_IMAP_PORT, ssl_context=tls_context(),
                                 timeout=settings.CATALYST_PROVISIONING_IMAP_TIMEOUT_SECONDS)
    except ssl.SSLError:
        raise AdapterError("imap_tls_refused", sent=False) from None
    except (OSError, imaplib.IMAP4.error):
        raise AdapterError("imap_unreachable", sent=False) from None
    try:
        try:
            imap.login(address, password)
        except imaplib.IMAP4.abort:
            raise AdapterError("imap_unreachable", sent=False) from None  # a dropped connection is not a refused login
        except imaplib.IMAP4.error:
            return False
        return True
    except (OSError, ssl.SSLError):
        raise AdapterError("imap_unreachable", sent=False) from None
    finally:
        del password
        try:
            imap.logout()
        except Exception:  # noqa: BLE001  (the answer is already known; a failed logout changes nothing)
            pass
