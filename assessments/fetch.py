"""Deterministic, SSRF-safe evidence fetching (018 section 3.3; REQ-029; task 3B.1). Synthetic only.

One GET of one claimed URL, checked against one approved `EvidenceSource` version:

1. URL: https only, the source's port, no userinfo, at most 2,048 characters, fragment dropped, a DNS name (no IP
   literal in any form), IDNA, exact host match, path normalized before the prefix check.
2. Resolution under a deadline (`getaddrinfo` has none, so it runs in a worker thread); every address must pass
   `classify`, one pure function with no environment branch.
3. Connection to the validated IP literal, TLS with SNI and certificate verification for the hostname, so nothing
   re-resolves between the check and the connection.
4. The connected peer is checked with `classify` again before any request byte.
5. Redirects: at most 3, each re-validated in full and allowed only to the source host or its listed redirect
   hosts; never to http.
6. Limits: the socket timeout is set to the remaining deadline before every read; a streamed byte cap; GET only;
   `Accept-Encoding: identity` and any other `Content-Encoding` refused; content types from the source; no
   cookies, credentials, proxies or connection reuse.

A synthetic fixture source (`fixture_only`, refused outside `test`) replaces DNS with one pinned address, which
`classify` admits only because the source names it; every other step is identical.

Nothing here logs a URL path, query, header or body. Results are reason codes: `Refused` (never retried) or
`Transient` (retried a bounded number of times by the handler).
"""

import concurrent.futures
import hashlib
import http.client
import ipaddress
import posixpath
import re
import socket
import ssl
import time
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urljoin, urlsplit

from django.conf import settings

DERIVATION_VERSION = 1
MAX_URL = 2048
MAX_REDIRECTS = 3
USER_AGENT = "CatalystEvidence/1 (synthetic)"
REDIRECT_STATUSES = (301, 302, 303, 307, 308)
TRANSIENT_STATUSES = (408, 425, 429, 500, 502, 503, 504)

# Explicit denials on top of "global unicast only" (018 3.3 step 2).
_DENY = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24",
    "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4", "255.255.255.255/32",
    "::/128", "::1/128", "::/96", "64:ff9b::/96", "64:ff9b:1::/48", "2001::/32", "2002::/16", "fc00::/7",
    "fe80::/10", "ff00::/8", "fd00:ec2::254/128",
)]


class Refused(Exception):
    """A non-retryable refusal; the message is a reason code."""


class Transient(Exception):
    """A retryable failure (timeout, connection error, 429 or 5xx); the message is a reason code."""


@dataclass
class FetchResult:
    final_url: str
    status: int
    content_type: str
    revision_marker: str
    body: bytes
    truncated: bool
    peer_ip: str
    location: str = ""


@dataclass
class Derived:
    text: str = ""
    truncated: bool = False
    markers: list = field(default_factory=list)


def classify(ip: str, extra_allowed: frozenset = frozenset()) -> bool:
    """True only for a global unicast address. `extra_allowed` holds the one pinned address of a fixture source,
    never anything derived from the environment."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if str(addr) in extra_allowed:
        return True
    if addr.version == 6:
        if getattr(addr, "scope_id", None):
            return False
        if addr.ipv4_mapped is not None:
            addr = addr.ipv4_mapped
        elif addr.sixtofour is not None or addr.teredo is not None:
            return False
    if any(addr in net for net in _DENY if net.version == addr.version):
        return False
    return addr.is_global and not addr.is_multicast


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        pass
    try:
        socket.inet_aton(host)  # accepts decimal, octal and hex forms such as 2130706433 or 0x7f.1
        return True
    except OSError:
        return False


@dataclass(frozen=True)
class Target:
    url: str
    host: str
    port: int
    request_path: str


def validate_url(url: str, source, allowed_hosts) -> Target:
    if not url or len(url) > MAX_URL:
        raise Refused("url_too_long")
    if any(ch in url for ch in "\\\r\n\t ") or any(unicodedata.category(ch) in ("Cc", "Cf") for ch in url):
        raise Refused("url_characters_refused")
    parts = urlsplit(url)
    if parts.scheme.lower() != "https":
        raise Refused("scheme_not_https")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise Refused("userinfo_refused")
    host = (parts.hostname or "").rstrip(".")
    if not host or _is_ip_literal(host):
        raise Refused("host_not_a_name")
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise Refused("host_not_a_name") from None
    if host not in allowed_hosts:
        raise Refused("host_not_allowed")
    try:
        port = parts.port or 443
    except ValueError:
        raise Refused("port_invalid") from None
    if port != source.port:
        raise Refused("port_not_allowed")
    raw_path = parts.path or "/"
    decoded = unquote(raw_path)
    if "\\" in decoded or "\x00" in decoded:
        raise Refused("path_refused")
    normalized = posixpath.normpath(decoded) if decoded != "/" else "/"
    if decoded.endswith("/") and normalized != "/":
        normalized += "/"
    if not normalized.startswith(source.path_prefix):
        raise Refused("path_not_allowed")
    request_path = quote(normalized, safe="/-._~!$&'()*+,;=:@")  # exactly the path that was checked
    if parts.query:
        request_path += "?" + parts.query
    return Target(url=f"https://{host}{'' if port == 443 else f':{port}'}{request_path}", host=host, port=port,
                  request_path=request_path)


def resolve(host: str, port: int, timeout: float) -> list:
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = pool.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
    try:
        infos = future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        raise Transient("dns_timeout") from None
    except socket.gaierror as exc:
        if exc.errno in (socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5)):
            raise Refused("dns_not_found") from None
        raise Transient("dns_failed") from None
    finally:
        pool.shutdown(wait=False)
    return list(dict.fromkeys(info[4][0] for info in infos))


def _addresses(source, host, port, remaining):
    if source.fixture_only:
        pinned = settings.CATALYST_EVIDENCE_FIXTURE_ADDRESS
        if not pinned:
            raise Refused("fixture_not_configured")
        return [pinned], frozenset({pinned})
    return resolve(host, port, remaining), frozenset()


def tls_context():
    context = ssl.create_default_context(cafile=settings.CATALYST_EVIDENCE_CA_FILE or None)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def fetch(url: str, source) -> FetchResult:
    started = time.monotonic()
    deadline = started + min(source.deadline_seconds, settings.CATALYST_EVIDENCE_DEADLINE_SECONDS)

    def remaining() -> float:
        left = deadline - time.monotonic()
        if left <= 0:
            raise Transient("deadline_exceeded")
        return left

    allowed = {source.host, *[h.lower() for h in source.redirect_hosts]}
    current, hops = url, 0
    while True:
        target = validate_url(current, source, {source.host} if hops == 0 else allowed)
        ips, extra = _addresses(source, target.host, target.port, remaining())
        if not ips or not all(classify(ip, extra) for ip in ips):
            raise Refused("address_not_allowed")
        result = _one_request(target, ips[0], extra, source, remaining)
        if result.status in REDIRECT_STATUSES:
            hops += 1
            if hops > MAX_REDIRECTS:
                raise Refused("too_many_redirects")
            if not result.location:
                raise Refused("redirect_without_location")
            current = urljoin(target.url, result.location)
            if urlsplit(current).scheme.lower() != "https":
                raise Refused("redirect_not_https")
            continue
        return result


def _one_request(target: Target, ip: str, extra, source, remaining) -> FetchResult:
    raw = None
    try:
        raw = socket.create_connection((ip, target.port), timeout=min(10.0, remaining()))
        peer = raw.getpeername()[0]
        if not classify(peer, extra):
            raise Refused("peer_not_allowed")
        tls = tls_context().wrap_socket(raw, server_hostname=target.host)
        raw = tls
        connection = http.client.HTTPSConnection(target.host, target.port, timeout=remaining())
        connection.sock = tls  # never reconnects or re-resolves
        connection.putrequest("GET", target.request_path, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", target.host if target.port == 443 else f"{target.host}:{target.port}")
        connection.putheader("User-Agent", USER_AGENT)
        connection.putheader("Accept-Encoding", "identity")
        connection.putheader("Connection", "close")
        connection.endheaders()
        tls.settimeout(remaining())
        response = connection.getresponse()
        status = response.status
        if status in REDIRECT_STATUSES:
            return FetchResult(target.url, status, "", "", b"", False, peer, location=response.getheader("Location") or "")
        if status in TRANSIENT_STATUSES:
            raise Transient(f"http_{status}")
        encoding = (response.getheader("Content-Encoding") or "identity").strip().lower()
        if encoding != "identity":
            raise Refused("content_encoding_refused")
        content_type = (response.getheader("Content-Type") or "").split(";")[0].strip().lower()
        if status == 200 and content_type not in source.content_types:
            raise Refused("content_type_refused")
        if status not in (200, 404, 410):
            raise Refused(f"http_{status}")
        revision = (response.getheader("ETag") or response.getheader("Last-Modified") or "")[:200]
        cap = min(source.max_bytes, settings.CATALYST_EVIDENCE_MAX_BYTES)
        chunks, size, truncated = [], 0, False
        while True:
            tls.settimeout(remaining())
            chunk = response.read(min(65536, cap + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > cap:
                truncated = True
                break
        body = b"".join(chunks)[:cap]
        charset = (response.getheader("Content-Type") or "").partition("charset=")[2].split(";")[0].strip()
        return FetchResult(target.url, status, content_type + (f";charset={charset}" if charset else ""), revision, body,
                           truncated, peer)
    except (Refused, Transient):
        raise
    except ssl.SSLCertVerificationError:
        raise Refused("tls_certificate_refused") from None
    except (TimeoutError, socket.timeout):
        raise Transient("timeout") from None
    except (ssl.SSLError, ConnectionError, OSError, http.client.HTTPException):
        raise Transient("connection_failed") from None
    finally:
        if raw is not None:
            try:
                raw.close()
            except OSError:
                pass


# --- derivation ---------------------------------------------------------------------------------------------

_SKIP_TAGS = {"script", "style", "noscript", "template", "head", "iframe", "object", "svg"}
_VOID = {"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)
_MARKERS = [
    ("instruction_override", re.compile(r"\b(ignore|disregard|forget)\b.{0,40}\b(previous|prior|above|all)\b.{0,20}\b(instructions?|rules?)\b", re.I)),
    ("role_claim", re.compile(r"\b(system|assistant|developer)\s*(prompt|message|:)", re.I)),
    ("model_directive", re.compile(r"\b(you are now|act as|respond only with|output (only|exactly))\b", re.I)),
    ("delimiter_lookalike", re.compile(r"<<\s*/?\s*DATA|\[\[|\]\]|<\s*/?\s*(system|instructions?)\s*>", re.I)),
    ("decision_directive", re.compile(r"\b(admit|approve|accept)\s+(this|the)\s+(applicant|candidate|application)\b", re.I)),
]


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], []

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            return
        a = dict(attrs)
        hidden = (tag in _SKIP_TAGS or "hidden" in a or (a.get("aria-hidden") or "").lower() == "true"
                  or bool(_HIDDEN_STYLE.search(a.get("style") or "")))
        self.skip.append(hidden or (bool(self.skip) and self.skip[-1]))
        if tag in ("p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if self.skip:
            self.skip.pop()

    def handle_data(self, data):
        if not (self.skip and self.skip[-1]):
            self.parts.append(data)


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf", "Cs", "Co"))
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def derive(result: FetchResult) -> Derived:
    """The visible text of a page, as untrusted data: scripts, styles, comments and hidden elements removed;
    control, format (zero-width, bidi) and private-use characters stripped; capped. Markers are computed on this
    same text, so a later quote and its marker refer to identical characters."""
    content_type, _, charset = result.content_type.partition(";charset=")
    try:
        raw = result.body.decode(charset or "utf-8", errors="replace")
    except LookupError:
        raw = result.body.decode("utf-8", errors="replace")
    if content_type == "text/html":
        parser = _Text()
        parser.feed(raw)
        parser.close()
        raw = "".join(parser.parts)
    text = _clean(raw)
    derived = Derived()
    limit = settings.CATALYST_EVIDENCE_MAX_TEXT_CHARS
    if len(text) > limit:
        text, derived.truncated = text[:limit], True
    derived.text = text
    derived.markers = sorted({name for name, pattern in _MARKERS if pattern.search(text)})
    return derived


def sha256(data) -> str:
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()
