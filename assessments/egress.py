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

    def target(self, head: bytes):
        """(host, port, addresses, extra) for a CONNECT request head, or a Refusal."""
        try:
            line = head.split(b"\r\n", 1)[0].decode("ascii")
            method, authority, version = line.split(" ")
        except (UnicodeDecodeError, ValueError):
            raise Refusal(400, "bad_request") from None
        if method != "CONNECT" or not version.startswith("HTTP/1."):
            raise Refusal(405, "connect_only")
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
        return host, port, resolve(host, port), frozenset()


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
