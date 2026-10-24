"""The evidence fetcher's egress proxy (026 section 5, H5; TEST-P6-30; 6B.11). Run as its own process from the same
image: `python -m assessments.egress`.

The fetcher sits on a network that reaches nothing but the database and this proxy, and has no DNS. Every fetch
goes through here as an HTTP CONNECT tunnel, so the deny is absolute and lives in one place:

1. CONNECT only, to an allowed port (443, and in a synthetic environment the fixture's port), within a deadline
   for the request head; anything else is refused.
2. A DNS name, never an IP literal, except the one pinned fixture address of a synthetic environment.
3. Every address the name resolves to must pass `assessments.fetch.classify`, the same pure function the fetcher
   uses: global unicast only, never loopback, a private or shared range, link-local or metadata, or this host.
4. The connected peer is checked again, then reported in the reply (`X-Catalyst-Peer`) so the fetcher checks it a
   third time before its TLS handshake. TLS is end to end: the proxy never sees the content or the path.
5. Tunnels are bounded in number and in time. Nothing is logged but outcome codes: never a host, a path or a byte.
6. The estate's own production hosts are denied (9kg.39; TEST-P6-28). An operator-supplied, secret-free file
   (`CATALYST_EGRESS_DENY_FILE`) lists logical host names; each denies itself and every name under it. A name is
   refused before any lookup; every address the target resolves to, and then the connected peer, is refused when it
   is an address a denied name resolves to. The denied names are resolved afresh at both checks, and every address
   they resolved to before stays denied (up to 64 per name, the oldest evicted first, the fresh answer always kept),
   so a DNS change toward or away from a production address between the check and the connection cannot open a
   way through. A missing, unreadable, empty or malformed file, or a list in which no name resolves to anything,
   refuses every request; at start the proxy logs how many names resolve to nothing (`deny_names_unresolved=N`). Only this policy reads the file: the fetcher, the Documenso and mail
   adapters never do. Each fetch and each redirect hop is its own CONNECT, so every hop passes every check here.

Deny file format (one entry per line; `#` starts a comment; blank lines ignored; ASCII; at most 64 KiB and 256 names):

    # production hosts of this estate (synthetic names here; the real list is supplied at deploy time)
    prod-a.example.test
    prod-b.example.test

An entry is a dotted DNS name, never an address or a single label; an entry that is not one makes the whole file
malformed (refuse everything), never quietly skipped.
"""

import ipaddress
import logging
import os
import re
import select
import socket
import sys
import threading
import time

from assessments.fetch import classify

logger = logging.getLogger("assessments.egress")
# A dotted DNS name whose last label has a letter, so no numeric form (`0x7f.0.0.01`) is ever a name.
NAME = re.compile(r"(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]*[a-z][a-z0-9-]*")
HEAD_LIMIT, HEAD_SECONDS, CONNECT_SECONDS, IDLE_SECONDS, TUNNEL_SECONDS = 4096, 10, 10, 30, 120
SYNTHETIC = ("test", "staging")
DENY_FILE_LIMIT, DENY_NAMES_LIMIT, DENY_ADDRESSES_PER_NAME = 65536, 256, 64
NO_SUCH_NAME = {socket.EAI_NONAME, getattr(socket, "EAI_NODATA", -5)}


class Refusal(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status, self.code = status, code


class Policy:
    def __init__(self, environ=os.environ):
        self.synthetic = environ.get("CATALYST_ENV", "") in SYNTHETIC
        fixture, fixture_port = environ.get("CATALYST_EVIDENCE_FIXTURE_ADDRESS", ""), environ.get("CATALYST_EGRESS_FIXTURE_PORT", "")
        if (fixture or fixture_port) and not self.synthetic:
            # Fail closed at start, never quietly ignore: a fixture outside test and staging is a misconfiguration.
            raise SystemExit("egress: a fixture address or port may be set only in a synthetic environment")
        self.fixture = str(ipaddress.ip_address(fixture)) if fixture else ""
        ports = {443}
        if self.fixture and fixture_port:
            if not fixture_port.isdigit() or not 1024 <= int(fixture_port) <= 65535:
                raise SystemExit("egress: the fixture port must be an unprivileged port number")
            ports.add(int(fixture_port))
        self.ports = frozenset(ports)
        self.deny = load_deny(environ.get("CATALYST_EGRESS_DENY_FILE", ""))
        self.remembered: dict = {}  # name -> its addresses, oldest first, at most DENY_ADDRESSES_PER_NAME
        self.lock = threading.Lock()

    def name_denied(self, host: str) -> bool:
        return any(host == name or host.endswith("." + name) for name in self.deny or ())

    def denied_addresses(self) -> frozenset:
        """Every address a denied name resolves to now, together with the ones it resolved to before (at most
        DENY_ADDRESSES_PER_NAME per name). A name that does not exist denies nothing. A lookup that fails or runs out
        of time (SERVFAIL, EAI_AGAIN, the deadline) keeps that name's last good answer; only a name that has never
        resolved refuses (502, so retried). Each fallback is logged as one outcome code, never a name."""
        answers = resolve_names(self.deny)
        with self.lock:
            failed = [name for name, addresses in answers.items() if addresses is None]
            if any(name not in self.remembered for name in failed):
                raise Refusal(502, "deny_list_unresolved")
            for name, addresses in answers.items():
                if addresses is not None:
                    self.remember(name, addresses)
            if failed:
                logger.info("egress deny_lookup_stale")
            denied = frozenset(ip for kept in self.remembered.values() for ip in kept)
        if not denied:  # a list in which no name resolves denies nothing at all: refuse rather than pretend
            raise Refusal(503, "deny_list_resolves_nothing")
        return denied

    def startup(self) -> list:
        """The outcome codes logged once at start: how many deny names resolve to nothing (never which ones). The
        pass also seeds each name's last good answer."""
        if not self.deny:
            return []
        answers = resolve_names(self.deny)
        with self.lock:
            for name, addresses in answers.items():
                if addresses is not None:
                    self.remember(name, addresses)
        return [f"deny_names_unresolved={sum(1 for addresses in answers.values() if not addresses)}"]

    def remember(self, name: str, addresses) -> None:
        """Keep a name's fresh answer in full and as many earlier addresses as fit, evicting the oldest address that
        is not in the fresh answer; never a global limit that could latch the proxy shut."""
        fresh = list(dict.fromkeys(a for a in (canonical(ip) for ip in addresses) if a))
        kept = [a for a in self.remembered.get(name, []) if a not in fresh] + fresh
        older = len(kept) - len(fresh)
        if len(kept) > DENY_ADDRESSES_PER_NAME:
            kept = kept[min(older, len(kept) - DENY_ADDRESSES_PER_NAME):]
        self.remembered[name] = kept

    def target(self, head: bytes):
        """(host, port, addresses, extra) for a CONNECT request head, or a Refusal."""
        try:
            line = head.split(b"\r\n", 1)[0].decode("ascii")
            method, authority, version = line.split(" ")
        except (UnicodeDecodeError, ValueError):
            raise Refusal(400, "bad_request") from None
        if method != "CONNECT" or not version.startswith("HTTP/1."):
            raise Refusal(405, "connect_only")
        if not self.deny:  # no deny list, no egress at all
            raise Refusal(403, "deny_list_unavailable")
        host, _, port_text = authority.rpartition(":")
        if not port_text.isdigit() or int(port_text) not in self.ports:
            raise Refusal(403, "port_not_allowed")
        host, port = host.strip("[]").lower(), int(port_text)
        try:
            literal = str(ipaddress.ip_address(host))
        except ValueError:
            literal = ""
        if literal:
            if not self.fixture or literal != self.fixture:
                raise Refusal(403, "ip_literal_refused")
            return host, port, [literal], frozenset({literal})
        if not NAME.fullmatch(host):
            raise Refusal(400, "bad_host")
        if self.name_denied(host.rstrip(".")):  # before any lookup
            raise Refusal(403, "host_denied")
        return host, port, resolve(host, port), frozenset()


def load_deny(path: str) -> tuple:
    """The denied names, or () (refuse everything) for a missing, unreadable, oversized, empty or malformed file. The
    content is never logged."""
    if not path:
        return ()
    try:
        with open(path, "rb") as handle:
            raw = handle.read(DENY_FILE_LIMIT + 1)
        text = raw.decode("ascii")
    except (OSError, UnicodeDecodeError):
        return ()
    if len(raw) > DENY_FILE_LIMIT:
        return ()
    names = []
    for line in text.splitlines():
        entry = line.split("#", 1)[0].strip().lower().rstrip(".")
        if not entry:
            continue
        if not NAME.fullmatch(entry):
            return ()
        names.append(entry)
    names = tuple(dict.fromkeys(names))
    return names if len(names) <= DENY_NAMES_LIMIT else ()  # more names than that is malformed


def canonical(ip: str) -> str:
    """One spelling per address: the zone dropped and an IPv4-mapped IPv6 address unwrapped, so `::ffff:a.b.c.d`, its
    hex form and `a.b.c.d` compare equal. Anything that is not an address is ""."""
    try:
        addr = ipaddress.ip_address(str(ip).split("%", 1)[0])
    except ValueError:
        return ""
    if addr.version == 6 and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return str(addr)


def resolve_names(names) -> dict:
    """name -> its addresses ([] for a name that does not exist), or None for a lookup that failed or ran out of time.
    One lookup pass: a single daemon thread resolves the names in turn under one deadline (`getaddrinfo` has no
    timeout), so a request costs one thread whatever the list's length; a name not reached in time is a failure."""
    box = {}

    def lookup_all():
        for name in names:
            try:
                box[name] = [info[4][0] for info in socket.getaddrinfo(name, 443, 0, socket.SOCK_STREAM)]
            except socket.gaierror as exc:
                box[name] = [] if exc.errno in NO_SUCH_NAME else None
            except (OSError, UnicodeError):
                box[name] = None

    worker = threading.Thread(target=lookup_all, daemon=True)
    worker.start()
    worker.join(CONNECT_SECONDS)
    return {name: box.get(name) for name in names}


def resolve(host: str, port: int) -> list:
    box = {}

    def lookup():
        try:
            box["infos"] = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        except socket.gaierror:
            box["error"] = True

    worker = threading.Thread(target=lookup, daemon=True)
    worker.start()
    worker.join(CONNECT_SECONDS)
    if worker.is_alive() or "error" in box:
        raise Refusal(502, "dns_failed")
    return list(dict.fromkeys(info[4][0] for info in box["infos"]))


def read_head(client) -> bytes:
    client.settimeout(HEAD_SECONDS)
    head = b""
    deadline = time.monotonic() + HEAD_SECONDS
    while b"\r\n\r\n" not in head:
        if len(head) > HEAD_LIMIT or time.monotonic() > deadline:
            raise Refusal(400, "bad_request")
        chunk = client.recv(1024)
        if not chunk:
            raise Refusal(400, "bad_request")
        head += chunk
    return head


def reply(client, status: int, code: str, peer: str = "") -> None:
    reason = {200: "Connection established", 400: "Bad Request", 403: "Forbidden", 405: "Method Not Allowed",
              502: "Bad Gateway", 503: "Service Unavailable"}[status]
    extra = f"X-Catalyst-Peer: {peer}\r\n" if peer else f"X-Catalyst-Refusal: {code}\r\n"
    client.sendall(f"HTTP/1.1 {status} {reason}\r\n{extra}Content-Length: 0\r\n\r\n".encode("ascii"))


def splice(client, upstream) -> None:
    """Copy both ways until either side closes, IDLE_SECONDS pass with nothing to read, or TUNNEL_SECONDS pass in
    all. Each send is bounded too (the sockets keep a timeout), so a peer that stops reading cannot pin the tunnel."""
    started, poller = time.monotonic(), select.poll()
    by_fd = {client.fileno(): (client, upstream), upstream.fileno(): (upstream, client)}
    for fd in by_fd:
        poller.register(fd, select.POLLIN)
    try:
        while time.monotonic() - started < TUNNEL_SECONDS:
            events = poller.poll(IDLE_SECONDS * 1000)
            if not events:
                return
            for fd, _ in events:
                source, sink = by_fd[fd]
                data = source.recv(65536)
                if not data:
                    return
                sink.sendall(data)
                if time.monotonic() - started >= TUNNEL_SECONDS:
                    return
    except (TimeoutError, OSError):
        return


def handle(client, policy: Policy) -> str:
    upstream = None
    try:
        host, port, addresses, extra = policy.target(read_head(client))
        if not addresses or not all(classify(ip, extra) for ip in addresses):
            raise Refusal(403, "address_not_allowed")
        denied = policy.denied_addresses()
        if any(canonical(ip) in denied for ip in addresses):
            raise Refusal(403, "address_denied")
        for address in addresses:  # every answer already passed classify; try each until one connects
            try:
                upstream = socket.create_connection((address, port), timeout=CONNECT_SECONDS)
                break
            except OSError:
                continue
        if upstream is None:
            raise Refusal(502, "connect_failed")
        peer = upstream.getpeername()[0]
        if not classify(peer, extra):
            raise Refusal(403, "peer_not_allowed")
        if canonical(peer) in policy.denied_addresses():  # resolved afresh: a DNS change since the check is caught here
            raise Refusal(403, "peer_denied")
        reply(client, 200, "ok", peer)
        upstream.settimeout(IDLE_SECONDS)
        client.settimeout(IDLE_SECONDS)
        splice(client, upstream)
        return "tunnelled"
    except Refusal as refusal:
        try:
            reply(client, refusal.status, refusal.code)
        except OSError:
            pass
        return refusal.code
    except OSError:
        return "client_error"
    finally:
        for sock in (upstream, client):
            if sock is not None:
                sock.close()


def serve(listen: str, policy: Policy, limit: int = 16, ready: threading.Event | None = None, stop=None):
    host, _, port = listen.rpartition(":")
    server = socket.create_server((host or "0.0.0.0", int(port)), reuse_port=False)
    server.settimeout(1)
    slots = threading.BoundedSemaphore(limit)
    for code in policy.startup():
        logger.info("egress %s", code)  # a count or a code, never a name
    if ready is not None:
        ready.listen_port = server.getsockname()[1]
        ready.set()

    def run(client):
        try:
            logger.info("egress %s", handle(client, policy))  # an outcome code only
        finally:
            slots.release()

    try:
        while stop is None or not stop.is_set():
            try:
                client, _ = server.accept()
            except TimeoutError:
                continue
            if not slots.acquire(blocking=False):
                try:
                    reply(client, 503, "busy")
                finally:
                    client.close()
                continue
            threading.Thread(target=run, args=(client,), daemon=True).start()
    finally:
        server.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    serve(os.environ.get("CATALYST_EGRESS_LISTEN", "0.0.0.0:3128"), Policy())
