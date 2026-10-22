"""6B.11 (026 section 5, H5; TEST-P6-30): the evidence fetcher's egress proxy. The live stack's checks (no other route,
every denied range refused through the proxy) are in scripts/staging_check.sh."""

import socket
import threading

import pytest

from assessments import egress
from tests.test_evidence import collect, ev, items, source, url  # noqa: F401  (fixture chain and helpers)
from tests.test_inbound import tls  # noqa: F401
from tests.test_outbound import p2  # noqa: F401

TEST_ENV = {"CATALYST_ENV": "test"}


@pytest.mark.parametrize(("head", "status", "code"), [
    (b"GET http://example.test/ HTTP/1.1\r\n\r\n", 405, "connect_only"),
    (b"CONNECT example.test:80 HTTP/1.1\r\n\r\n", 403, "port_not_allowed"),
    (b"CONNECT 10.0.0.1:443 HTTP/1.1\r\n\r\n", 403, "ip_literal_refused"),
    (b"CONNECT [::1]:443 HTTP/1.1\r\n\r\n", 403, "ip_literal_refused"),
    (b"CONNECT 169.254.169.254:443 HTTP/1.1\r\n\r\n", 403, "ip_literal_refused"),
    (b"CONNECT bad_host!:443 HTTP/1.1\r\n\r\n", 400, "bad_host"),
    (b"\xff\xfe\r\n\r\n", 400, "bad_request"),
])
def test_6b11_the_policy_refuses_anything_but_a_connect_to_a_name_on_an_allowed_port(head, status, code):
    with pytest.raises(egress.Refusal) as refused:
        egress.Policy(TEST_ENV).target(head)
    assert (refused.value.status, refused.value.code) == (status, code)


def test_6b11_the_fixture_address_is_admitted_only_in_a_synthetic_environment():
    synthetic = egress.Policy({"CATALYST_ENV": "staging", "CATALYST_EVIDENCE_FIXTURE_ADDRESS": "127.0.0.1",
                               "CATALYST_EGRESS_FIXTURE_PORT": "8443"})
    assert synthetic.target(b"CONNECT 127.0.0.1:8443 HTTP/1.1\r\n\r\n")[2:] == (["127.0.0.1"], frozenset({"127.0.0.1"}))
    with pytest.raises(SystemExit):  # outside test and staging the proxy refuses to start with a fixture at all
        egress.Policy({"CATALYST_ENV": "production", "CATALYST_EVIDENCE_FIXTURE_ADDRESS": "127.0.0.1",
                       "CATALYST_EGRESS_FIXTURE_PORT": "8443"})


@pytest.fixture
def proxy():
    """A live proxy on loopback, for the fixture site only (whose pinned address it admits)."""
    stop, ready = threading.Event(), threading.Event()
    policies = {}

    def start(policy):
        policies["p"] = policy
        threading.Thread(target=egress.serve, args=("127.0.0.1:0", policy), kwargs={"ready": ready, "stop": stop},
                         daemon=True).start()
        assert ready.wait(5)
        return ready.listen_port
    yield start
    stop.set()


def connect(port, authority) -> str:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        sock.sendall(f"CONNECT {authority} HTTP/1.1\r\n\r\n".encode())
        return sock.recv(1024).decode()


@pytest.mark.parametrize("answers", [["127.0.0.1"], ["10.1.2.3"], ["169.254.169.254"], ["100.64.0.1"],
                                     ["172.17.0.1"], ["93.184.215.14", "192.168.1.5"], ["::1"]])
def test_6b11_a_name_resolving_to_any_denied_address_is_refused_by_the_live_proxy(proxy, monkeypatch, answers):
    monkeypatch.setattr(egress, "resolve", lambda host, port: answers)  # what a hostile name's DNS could return
    port = proxy(egress.Policy(TEST_ENV))
    answer = connect(port, "evidence.example.test:443")
    assert answer.startswith("HTTP/1.1 403") and "X-Catalyst-Refusal: address_not_allowed" in answer


def test_6b11_a_single_label_name_is_refused_before_any_lookup(proxy):
    port = proxy(egress.Policy(TEST_ENV))
    assert "X-Catalyst-Refusal: bad_host" in connect(port, "localhost:443")


def test_6b11_evidence_is_fetched_through_the_egress_proxy(ev, settings, proxy):
    port = proxy(egress.Policy({"CATALYST_ENV": "test", "CATALYST_EVIDENCE_FIXTURE_ADDRESS": "127.0.0.1",
                                "CATALYST_EGRESS_FIXTURE_PORT": str(ev.site.port)}))
    settings.CATALYST_EVIDENCE_PROXY = f"127.0.0.1:{port}"
    source(ev)
    ev.site.page("/w", "<p>Work sample fetched through the egress proxy.</p>")
    app = collect(ev, work_url_1=url(ev, "/w"))
    [item] = items(app)
    assert item.status == "fetched" and item.captures.get().peer_ip == "127.0.0.1"  # the proxy's reported peer
    assert len([r for r in ev.site.requests if r["path"] == "/w"]) == 1


def test_6b11_a_proxy_refusal_is_a_refusal_and_never_retried(ev, settings, proxy):
    port = proxy(egress.Policy(TEST_ENV))  # no fixture address: the pinned fixture is refused
    settings.CATALYST_EVIDENCE_PROXY = f"127.0.0.1:{port}"
    source(ev)
    ev.site.page("/w", "<p>never reached</p>")
    app = collect(ev, work_url_1=url(ev, "/w"))
    [item] = items(app)
    assert item.status == "refused" and item.reason_code == "port_not_allowed"  # the fixture's port is not admitted
    assert not ev.site.requests


def test_6b11_the_proxy_refuses_to_start_with_a_fixture_outside_a_synthetic_environment():
    for environ in ({"CATALYST_ENV": "production", "CATALYST_EVIDENCE_FIXTURE_ADDRESS": "10.0.0.5"},
                    {"CATALYST_ENV": "", "CATALYST_EGRESS_FIXTURE_PORT": "8443"}):
        with pytest.raises(SystemExit):
            egress.Policy(environ)
    with pytest.raises(SystemExit):  # a privileged or malformed fixture port
        egress.Policy({"CATALYST_ENV": "test", "CATALYST_EVIDENCE_FIXTURE_ADDRESS": "127.0.0.1",
                       "CATALYST_EGRESS_FIXTURE_PORT": "22"})


@pytest.mark.parametrize("authority", ["0x7f.0.0.01:443", "127.0.0.1.:443", "1.2.3.4.5:443"])
def test_6b11_numeric_names_are_never_names(authority):
    with pytest.raises(egress.Refusal):
        egress.Policy(TEST_ENV).target(f"CONNECT {authority} HTTP/1.1\r\n\r\n".encode())


def test_6b11_a_tunnel_whose_peer_stops_reading_is_bounded(monkeypatch):
    monkeypatch.setattr(egress, "IDLE_SECONDS", 1)
    left, right = socket.socketpair()
    far, near = socket.socketpair()
    for sock in (left, near):
        sock.settimeout(1)
    started = __import__("time").monotonic()
    worker = threading.Thread(target=egress.splice, args=(left, near), daemon=True)
    worker.start()
    right.settimeout(5)
    try:  # nobody ever reads `far`, so the copy towards it blocks; this side stops being read once the splice ends
        right.sendall(b"x" * 65536 * 8)
    except TimeoutError:
        pass
    worker.join(10)
    assert not worker.is_alive() and __import__("time").monotonic() - started < 10

