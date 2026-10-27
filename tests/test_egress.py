"""6B.11 (026 section 5, H5; TEST-P6-30): the evidence fetcher's egress proxy, and 9kg.39 (TEST-P6-28): its deny list
of the estate's own production hosts, by name and by resolved address. The live stack's checks (no other route, every
denied range and the deny list refused through the proxy) are in scripts/staging_check.sh.

DNS is never consulted here: `resolve` (the target) and `resolve_names` (the denied names) are replaced by the table
`DNS`, with synthetic names and documentation addresses standing in for the real ones."""

import json
import socket
import threading
from pathlib import Path

import pytest

from assessments import egress, fetch
from assessments.models import EvidenceSource
from tests.test_evidence import HOST, MIRROR, collect, ev, items, source, url  # noqa: F401  (fixture chain and helpers)
from tests.test_inbound import tls  # noqa: F401
from tests.test_outbound import p2  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent
DENY_FILE = str(ROOT / "tests" / "egress-deny.example")  # prod-a.example.test and prod-b.example.test, synthetic
TEST_ENV = {"CATALYST_ENV": "test", "CATALYST_EGRESS_DENY_FILE": DENY_FILE}
PROD_V4, PROD_V6 = "198.51.100.7", "2001:db8::7"  # a production host's addresses, as documentation addresses
REAL_RESOLVE_NAMES, REAL_CLASSIFY = egress.resolve_names, fetch.classify


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """The resolver for every test here: name -> addresses ([] does not exist, None a failed lookup)."""
    table = {"prod-a.example.test": [PROD_V4, PROD_V6], "prod-b.example.test": []}
    monkeypatch.setattr(egress, "resolve_names", lambda names: {name: table.get(name, []) for name in names})
    return table


def public(monkeypatch, *addresses):
    """Let the address checks admit `addresses` as if they were public: a production host's address is public, so only
    the deny list stands between it and the fetcher. Every other address still meets the real `classify`."""
    stand_ins = {egress.canonical(a) for a in addresses}

    def classify(ip, extra_allowed=frozenset()):
        return egress.canonical(ip) in stand_ins or REAL_CLASSIFY(ip, extra_allowed)
    monkeypatch.setattr(egress, "classify", classify)
    monkeypatch.setattr(fetch, "classify", classify)


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
    synthetic = egress.Policy({**TEST_ENV, "CATALYST_ENV": "staging", "CATALYST_EVIDENCE_FIXTURE_ADDRESS": "127.0.0.1",
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
    port = proxy(egress.Policy({**TEST_ENV, "CATALYST_EVIDENCE_FIXTURE_ADDRESS": "127.0.0.1",
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



# --- 9kg.39 (TEST-P6-28): the estate's own production hosts, by name and by resolved address ---------------------

def fixture_policy(port):
    """A synthetic policy whose allowed ports include a loopback listener's, so a live tunnel can be shown."""
    return egress.Policy({**TEST_ENV, "CATALYST_EVIDENCE_FIXTURE_ADDRESS": "127.0.0.1",
                          "CATALYST_EGRESS_FIXTURE_PORT": str(port)})


def refusal(answer) -> tuple:
    head = answer.split("\r\n")
    codes = [line.split(": ", 1)[1] for line in head if line.startswith("X-Catalyst-Refusal: ")]
    return head[0].split(" ")[1], codes[0] if codes else "-"


@pytest.mark.parametrize("content", [None, "missing", b"", b"# only a comment\n\n", b"prod-a.example.test\n10.0.0.1\n",
                                     b"prod\n", b"pr\xc3\xb6d.example.test\n", b"a.example.test\n" * 5000])
def test_9kg39_a_missing_unreadable_empty_or_malformed_deny_file_refuses_everything(tmp_path, proxy, content):
    environ = {"CATALYST_ENV": "test"}
    if content == "missing":
        environ["CATALYST_EGRESS_DENY_FILE"] = str(tmp_path / "absent")
    elif content is not None:
        (tmp_path / "deny").write_bytes(content)
        environ["CATALYST_EGRESS_DENY_FILE"] = str(tmp_path / "deny")
    policy = egress.Policy(environ)
    assert policy.deny == ()
    with pytest.raises(egress.Refusal) as refused:  # even an ordinary public name: no deny list, no egress
        policy.target(b"CONNECT evidence.example.test:443 HTTP/1.1\r\n\r\n")
    assert (refused.value.status, refused.value.code) == (503, "deny_list_unavailable")
    if content is None:  # and the live proxy says the same, with a code and nothing else
        assert refusal(connect(proxy(policy), "evidence.example.test:443")) == ("503", "deny_list_unavailable")


def test_9kg39_the_deny_file_takes_names_comments_and_blank_lines(tmp_path):
    (tmp_path / "deny").write_text("# hosts\n\nProd-A.Example.Test.  # trailing dot and case\nprod-b.example.test\n")
    assert egress.load_deny(str(tmp_path / "deny")) == ("prod-a.example.test", "prod-b.example.test")


@pytest.mark.parametrize("host", ["prod-a.example.test", "PROD-A.example.test", "api.prod-a.example.test",
                                  "deep.api.prod-b.example.test"])
def test_9kg39_a_production_host_name_is_refused_before_any_lookup(monkeypatch, host):
    def no_lookup(*args):
        raise AssertionError("a denied name was looked up")
    monkeypatch.setattr(egress, "resolve", no_lookup)
    with pytest.raises(egress.Refusal) as refused:
        egress.Policy(TEST_ENV).target(f"CONNECT {host}:443 HTTP/1.1\r\n\r\n".encode())
    assert (refused.value.status, refused.value.code) == (403, "host_denied")


def test_9kg39_a_name_that_only_ends_like_a_production_host_is_not_denied_by_name(monkeypatch):
    monkeypatch.setattr(egress, "resolve", lambda host, port: ["93.184.215.14"])
    assert egress.Policy(TEST_ENV).target(b"CONNECT notprod-a.example.test:443 HTTP/1.1\r\n\r\n")[2] == ["93.184.215.14"]


@pytest.mark.parametrize("answers", [[PROD_V4], [PROD_V6], ["::ffff:198.51.100.7"], ["::ffff:c633:6407"],
                                     ["93.184.215.14", PROD_V4]])
def test_9kg39_a_name_resolving_to_a_production_address_is_refused(proxy, monkeypatch, answers):
    public(monkeypatch, PROD_V4, PROD_V6, "93.184.215.14")  # public addresses all: only the deny list refuses
    monkeypatch.setattr(egress, "resolve", lambda host, port: answers)
    assert refusal(connect(proxy(egress.Policy(TEST_ENV)), "innocent.example.test:443")) == ("403", "address_denied")


def test_9kg39_a_dns_change_toward_a_production_address_is_refused_between_requests_and_at_the_peer(proxy, monkeypatch, dns):
    listener = socket.create_server(("127.0.0.1", 0))
    listener.settimeout(5)
    accepted = []

    def accept_one():
        worker = threading.Thread(target=lambda: accepted.append(listener.accept()), daemon=True)
        worker.start()
        return worker
    first = accept_one()
    public(monkeypatch, "127.0.0.1")  # the loopback listener stands in for a public host
    target = {"innocent.example.test": ["127.0.0.1"]}
    monkeypatch.setattr(egress, "resolve", lambda host, port: target[host])
    policy = fixture_policy(listener.getsockname()[1])
    port = proxy(policy)
    authority = f"innocent.example.test:{listener.getsockname()[1]}"
    assert connect(port, authority).startswith("HTTP/1.1 200")  # the control: tunnelled to the checked address
    first.join(5)
    assert accepted and accepted[0][1][0] == "127.0.0.1"
    target["innocent.example.test"] = [PROD_V4]  # the target's DNS now points at production: no answer is cached
    public(monkeypatch, "127.0.0.1", PROD_V4)
    assert refusal(connect(port, authority)) == ("403", "address_denied")
    # A production name moves onto the address the target resolves to between the check and the connection: the
    # check passes, the connected peer is refused.
    target["innocent.example.test"] = ["127.0.0.1"]
    calls = []

    def moving(names):
        calls.append(names)
        return {name: (["127.0.0.1"] if name == "prod-a.example.test" and len(calls) > 1 else dns.get(name, []))
                for name in names}
    monkeypatch.setattr(egress, "resolve_names", moving)
    second = accept_one()
    assert refusal(connect(port, authority)) == ("403", "peer_denied")
    second.join(5)
    assert len(accepted) == 2  # it did connect, to the checked address; only the peer check refused
    assert len(calls) == 2  # resolved afresh at the address check and again at the peer
    for sock, _ in accepted:
        sock.close()
    listener.close()


def test_9kg39_an_address_a_production_name_once_resolved_to_stays_denied(dns):
    policy = egress.Policy(TEST_ENV)
    assert PROD_V4 in policy.denied_addresses()
    dns["prod-a.example.test"] = ["198.51.100.8"]  # production moved; a DNS change away does not reopen the old address
    assert {PROD_V4, "198.51.100.8"} <= policy.denied_addresses()


def test_9kg39_a_deny_name_that_has_never_resolved_refuses_as_transient(proxy, monkeypatch, dns):
    public(monkeypatch, "93.184.215.14")
    monkeypatch.setattr(egress, "resolve", lambda host, port: ["93.184.215.14"])
    dns["prod-a.example.test"] = None  # a lookup failure or timeout with no earlier answer: unknown, so nothing passes
    assert refusal(connect(proxy(egress.Policy(TEST_ENV)), "innocent.example.test:443")) == ("502", "deny_list_unresolved")


def test_9kg39_a_failed_lookup_keeps_the_last_good_answer(proxy, monkeypatch, dns, caplog):
    public(monkeypatch, PROD_V4, "93.184.215.14")
    target = {"innocent.example.test": ["93.184.215.14"], "moved.example.test": [PROD_V4]}
    monkeypatch.setattr(egress, "resolve", lambda host, port: target[host])
    policy = egress.Policy(TEST_ENV)
    assert PROD_V4 in policy.denied_addresses()  # one good answer
    dns["prod-a.example.test"] = None  # then SERVFAIL, EAI_AGAIN or a timeout
    port = proxy(policy)
    with caplog.at_level("INFO", logger="assessments.egress"):
        assert refusal(connect(port, "moved.example.test:443")) == ("403", "address_denied")  # still denied
    assert "egress deny_lookup_stale" in caplog.text and "prod-a" not in caplog.text  # a code, never the name


def test_9kg39_one_lookup_pass_uses_one_thread_and_a_slow_name_is_a_failure(monkeypatch):
    seen, started = [], threading.Event()

    def getaddrinfo(name, port, *args):
        seen.append((name, threading.get_ident()))
        if name == "slow.example.test":
            started.set()
            threading.Event().wait(3)  # past the deadline below
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PROD_V4, port))]
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    monkeypatch.setattr(egress, "CONNECT_SECONDS", 1)
    answers = REAL_RESOLVE_NAMES(("prod-a.example.test", "prod-b.example.test", "slow.example.test", "late.example.test"))
    assert answers == {"prod-a.example.test": [PROD_V4], "prod-b.example.test": [PROD_V4], "slow.example.test": None,
                       "late.example.test": None}
    assert started.is_set() and len({ident for _, ident in seen}) == 1  # one thread for the whole pass


def test_9kg39_denied_names_resolve_together_and_a_missing_name_denies_nothing(monkeypatch):
    def getaddrinfo(name, port, *args):
        if name == "gone.example.test":
            raise socket.gaierror(socket.EAI_NONAME, "no such name")
        if name == "broken.example.test":
            raise socket.gaierror(socket.EAI_AGAIN, "temporary failure")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PROD_V4, port))]
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    assert REAL_RESOLVE_NAMES(("prod-a.example.test", "gone.example.test", "broken.example.test")) == {
        "prod-a.example.test": [PROD_V4], "gone.example.test": [], "broken.example.test": None}


@pytest.mark.parametrize(("address", "expected"), [
    (PROD_V4, PROD_V4), ("::ffff:198.51.100.7", PROD_V4), ("::ffff:c633:6407", PROD_V4), ("2001:DB8::7", PROD_V6),
    ("fe80::1%eth0", "fe80::1"), ("not-an-address", ""),
])
def test_9kg39_addresses_compare_in_one_canonical_form(address, expected):
    assert egress.canonical(address) == expected


def test_9kg39_a_redirect_to_a_production_host_or_its_address_is_refused_and_a_test_fixture_still_fetches(
        ev, settings, proxy, monkeypatch, dns):
    """Every redirect hop is its own CONNECT, so the proxy checks each one. A non-fixture source sends the name."""
    public(monkeypatch, "127.0.0.1", PROD_V4)
    target = {HOST: ["127.0.0.1"], MIRROR: ["127.0.0.1"]}
    monkeypatch.setattr(egress, "resolve", lambda host, port: target[host])
    settings.CATALYST_EVIDENCE_PROXY = f"127.0.0.1:{proxy(fixture_policy(ev.site.port))}"
    # An operator who listed a production host by mistake: the settings and the source admit it, the proxy does not.
    settings.CATALYST_EVIDENCE_ALLOWED_HOSTS = [HOST, MIRROR, "prod-a.example.test"]
    src = EvidenceSource(host=HOST, port=ev.site.port, path_prefix="/", content_types=["text/html"], max_bytes=65536,
                         deadline_seconds=5, fixture_only=False, redirect_hosts=[MIRROR, "prod-a.example.test"])
    ev.site.page("/m", "<p>Mirrored synthetic evidence.</p>")
    ev.site.page("/to-mirror", "", status=302, Location=url(ev, "/m", host=MIRROR))
    assert fetch.fetch(url(ev, "/to-mirror"), src).status == 200  # the positive control, through the proxy
    ev.site.page("/to-prod", "", status=302, Location=url(ev, "/m", host="prod-a.example.test"))
    with pytest.raises(fetch.Refused, match="^host_denied$"):
        fetch.fetch(url(ev, "/to-prod"), src)
    target[MIRROR] = [PROD_V4]  # the mirror's name now resolves to a production address
    with pytest.raises(fetch.Refused, match="^address_denied$"):
        fetch.fetch(url(ev, "/to-mirror"), src)
    assert [r["path"] for r in ev.site.requests] == ["/to-mirror", "/m", "/to-prod", "/to-mirror"]


@pytest.mark.parametrize("bad", ["http://evidence.example.test/w", "ftp://evidence.example.test/w",
                                 "ws://evidence.example.test/w", "file:///etc/passwd", "gopher://evidence.example.test/",
                                 "HTTP://evidence.example.test/w"])
def test_9kg39_any_scheme_but_https_is_refused(bad):
    src = EvidenceSource(host=HOST, port=443, path_prefix="/")
    with pytest.raises(fetch.Refused, match="^scheme_not_https$"):
        fetch.validate_url(bad, src, {HOST})


@pytest.mark.parametrize("authority", ["evidence.example.test:80", "evidence.example.test:8443",
                                       "evidence.example.test:22", "evidence.example.test:0", "evidence.example.test:"])
def test_9kg39_any_port_but_443_is_refused(authority):
    with pytest.raises(egress.Refusal) as refused:
        egress.Policy(TEST_ENV).target(f"CONNECT {authority} HTTP/1.1\r\n\r\n".encode())
    assert refused.value.code == "port_not_allowed"
    src = EvidenceSource(host=HOST, port=443, path_prefix="/")
    with pytest.raises(fetch.Refused, match="^port_not_allowed$"):
        fetch.validate_url(f"https://{HOST}:{authority.rpartition(':')[2] or 8443}/w", src, {HOST})


@pytest.mark.parametrize("host", ["2130706433", "0177.0.0.1", "0x7f000001", "0x7f.1", "127.1", "0x7f.0.0.01",
                                  "3325256711", "0306.063.0144.07", "0x7f.0x0.0x0.0x1", "0xc6.0x33.0x64.0x7",
                                  "0X7F.0X0.0X0.0X1"])
def test_9kg39_numeric_address_encodings_are_never_names(host):
    with pytest.raises(egress.Refusal) as refused:
        egress.Policy(TEST_ENV).target(f"CONNECT {host}:443 HTTP/1.1\r\n\r\n".encode())
    assert refused.value.code in ("bad_host", "ip_literal_refused")
    with pytest.raises(fetch.Refused, match="^host_not_a_name$"):
        fetch.validate_url(f"https://{host}/w", EvidenceSource(host=HOST, port=443, path_prefix="/"), {HOST})


@pytest.mark.parametrize("literal", [PROD_V4, f"[{PROD_V6}]", "[::ffff:198.51.100.7]", "[::ffff:c633:6407]",
                                     "[::ffff:127.0.0.1]", "[fe80::1]", "169.254.169.254", "[fd00:ec2::254]"])
def test_9kg39_ip_literals_in_any_form_are_refused(literal):
    with pytest.raises(egress.Refusal) as refused:
        egress.Policy(TEST_ENV).target(f"CONNECT {literal}:443 HTTP/1.1\r\n\r\n".encode())
    assert refused.value.code == "ip_literal_refused"


@pytest.mark.parametrize("answers", [["fe80::1"], ["fe80::1%eth0"], ["fd00:ec2::254"], ["::ffff:169.254.169.254"],
                                     ["169.254.170.2"], ["::ffff:10.0.0.1"], ["192.168.0.1"], ["fc00::1"],
                                     ["100.100.100.100"], ["100.127.255.254"], ["::ffff:100.64.0.1"], ["0.0.0.0"]])
def test_9kg39_link_local_metadata_private_and_tailnet_answers_are_refused_in_every_form(proxy, monkeypatch, answers):
    monkeypatch.setattr(egress, "resolve", lambda host, port: answers)
    assert refusal(connect(proxy(egress.Policy(TEST_ENV)), "innocent.example.test:443")) == ("403", "address_not_allowed")


APP_PACKAGES = ("accounts", "agreements", "applications", "assessments", "config", "correspondence", "erasure",
                "provisioning", "workflow")


def test_9kg39_only_the_egress_policy_reads_the_deny_list():
    readers = sorted(str(path.relative_to(ROOT)) for package in APP_PACKAGES for path in (ROOT / package).rglob("*.py")
                     if "CATALYST_EGRESS_DENY_FILE" in path.read_text())
    assert readers == ["assessments/egress.py"]
    compose = json.loads((ROOT / "deploy" / "staging" / "compose.yaml").read_text().split("\n", 2)[2])
    holders = [name for name, svc in compose["services"].items() if "CATALYST_EGRESS_DENY_FILE" in svc.get("environment", {})]
    assert holders == ["egress"]
    assert "./egress-deny:/etc/catalyst/egress-deny:ro" in compose["services"]["egress"]["volumes"]


# --- security review of PR #101 ------------------------------------------------------------------------------------

def test_9kg39_the_remembered_addresses_are_bounded_per_name_and_never_latch_the_proxy_shut(tmp_path, dns):
    names = [f"prod-{n}.example.test" for n in range(256)]
    (tmp_path / "deny").write_text("\n".join(names) + "\n")
    assert len(egress.load_deny(str(tmp_path / "deny"))) == 256  # at the limit: loaded
    (tmp_path / "more").write_text("\n".join([*names, "one-too-many.example.test"]) + "\n")
    assert egress.load_deny(str(tmp_path / "more")) == ()  # past it: malformed, so everything is refused
    policy = egress.Policy(TEST_ENV)
    for n in range(200):  # production keeps moving: far more addresses than are remembered
        dns["prod-a.example.test"] = [f"198.51.100.{n % 250}", f"2001:db8::{n:x}"]
        denied = policy.denied_addresses()  # never a refusal, however many addresses went before
        assert {f"198.51.100.{n % 250}", egress.canonical(f"2001:db8::{n:x}")} <= denied  # the fresh answer is always in
    assert len(policy.remembered["prod-a.example.test"]) == egress.DENY_ADDRESSES_PER_NAME
    dns["prod-a.example.test"] = [f"203.0.113.{n}" for n in range(80)]  # an answer larger than the cap is kept whole
    assert {f"203.0.113.{n}" for n in range(80)} <= policy.denied_addresses()
    assert len(policy.remembered["prod-a.example.test"]) == 80
    dns["prod-a.example.test"] = ["192.0.2.1"]  # the oldest addresses go first, the newest stay
    remembered = (policy.denied_addresses(), policy.remembered["prod-a.example.test"])[1]
    assert remembered[-1] == "192.0.2.1" and "203.0.113.79" in remembered and "203.0.113.0" not in remembered


def test_9kg39_a_list_in_which_no_name_resolves_refuses_everything_and_start_up_counts_them(proxy, monkeypatch, dns,
                                                                                           caplog):
    public(monkeypatch, "93.184.215.14")
    monkeypatch.setattr(egress, "resolve", lambda host, port: ["93.184.215.14"])
    dns["prod-a.example.test"] = []  # every name now resolves to nothing (prod-b already does)
    with caplog.at_level("INFO", logger="assessments.egress"):
        port = proxy(egress.Policy(TEST_ENV))
        assert refusal(connect(port, "innocent.example.test:443")) == ("503", "deny_list_resolves_nothing")
    assert "egress deny_names_unresolved=2" in caplog.text and "example.test" not in caplog.text
    dns["prod-a.example.test"] = [PROD_V4]  # one name resolving again is enough
    assert egress.Policy(TEST_ENV).startup() == ["deny_names_unresolved=1"]


def test_9kg39_a_broken_deny_list_is_transient_for_the_fetcher_logged_at_start_and_unhealthy(ev, settings, proxy, caplog,
                                                                                            tmp_path):
    environ = {"CATALYST_ENV": "test", "CATALYST_EVIDENCE_FIXTURE_ADDRESS": "127.0.0.1",
               "CATALYST_EGRESS_FIXTURE_PORT": str(ev.site.port)}  # no deny file
    with caplog.at_level("INFO", logger="assessments.egress"):
        settings.CATALYST_EVIDENCE_PROXY = f"127.0.0.1:{proxy(egress.Policy(environ))}"
    assert "egress deny_list_unavailable" in caplog.text  # once, at start
    ev.site.page("/w", "<p>never reached</p>")
    with pytest.raises(fetch.Transient, match="^egress_unavailable$"):  # retried, never a final refusal
        fetch.fetch(url(ev, "/w"), source(ev))
    assert not ev.site.requests
    import subprocess
    import sys
    check = [sys.executable, "-m", "assessments.egress", "--check"]
    broken = subprocess.run(check, cwd=ROOT, env={"CATALYST_ENV": "test", "PATH": "/usr/bin:/bin"}, capture_output=True)
    healthy = subprocess.run(check, cwd=ROOT, env={"CATALYST_ENV": "test", "CATALYST_EGRESS_DENY_FILE": DENY_FILE,
                                                   "PATH": "/usr/bin:/bin"}, capture_output=True)
    assert (broken.returncode, healthy.returncode) == (1, 0) and not broken.stdout + healthy.stdout


def test_9kg39_a_name_of_hex_labels_is_never_a_name_and_never_a_deny_entry(tmp_path):
    assert not egress.is_name("0x7f.0x0.0x0.0x1") and not egress.is_name("prod.0xff")
    assert egress.is_name("0xdeadbeefcafe-x.example.test") and egress.is_name("x0.example.test")
    (tmp_path / "deny").write_text("prod-a.example.test\n0x7f.0x0.0x0.0x1\n")
    assert egress.load_deny(str(tmp_path / "deny")) == ()  # malformed: refuse everything


EGRESS_CODES = ("host_denied", "address_denied", "peer_denied", "deny_list_unavailable", "deny_list_unresolved",
                "deny_list_resolves_nothing", "address_not_allowed", "peer_not_allowed", "ip_literal_refused",
                "port_not_allowed", "bad_host")


def test_9kg39_egress_refusal_codes_stay_staff_only(ev, settings, proxy, dns):
    """A proxy refusal ends the item with its code on the staff dossier, never in what the model sees (so never in
    a clarification question it proposes), in a mail or on an applicant-facing page."""
    from django.core import mail

    from assessments import pack, snapshot

    dns["prod-a.example.test"] = ["127.0.0.1"]  # the fixture's own address is a production address here
    settings.CATALYST_EVIDENCE_PROXY = f"127.0.0.1:{proxy(fixture_policy(ev.site.port))}"
    source(ev)
    ev.site.page("/w", "<p>never reached</p>")
    app = collect(ev, work_url_1=url(ev, "/w"))
    [item] = items(app)
    assert (item.status, item.reason_code) == ("refused", "address_denied") and not ev.site.requests
    loaded = pack.load()
    value = snapshot.manifest(app, loaded)
    sent = snapshot.build_request(app, value, loaded)  # the clarification path starts from this request
    outward = [sent.system, sent.prompt, repr(sent.items), *sent.missing]
    outward += [f"{m.subject}\n{m.body}" for m in mail.outbox]
    assert not [code for code in EGRESS_CODES for text in outward if code in text]
    templates = [path for path in ROOT.glob("*/templates/**/*.html") if "/staff/" not in str(path)]
    assert templates and not [str(p) for p in templates if "reason_code" in p.read_text()]  # only staff pages show it


def test_9kg39_the_staging_by_address_checks_are_not_run_without_public_dns_never_failed(tmp_path):
    """scripts/staging_check.sh: the address_denied cases need public DNS from the proxy. The guard is run here with
    a stand-in `docker` that cannot resolve, and must print NOT RUN for each case and record no FAIL."""
    script = (ROOT / "scripts" / "staging_check.sh").read_text()
    start = script.index("public_dns() {")
    loop = script.index("for authority in 1.1.1.1.nip.io", start)
    block = script[start:script.index("\ndone\n", loop) + 6]
    assert block.count('"403 address_denied"') == 1 and "NOT RUN" in block
    (tmp_path / "docker").write_text("#!/bin/sh\nexit 1\n")
    (tmp_path / "docker").chmod(0o755)
    harness = ("set -u; fail=0; compose=(true); sleep() { :; }; check() { echo \"CHECKED $1\"; }; via_proxy_settled() { echo x; }\n"
               + block + "\necho fail=$fail\n")
    import subprocess
    out = subprocess.run(["bash", "-c", harness], env={"PATH": f"{tmp_path}:/usr/bin:/bin"}, capture_output=True,
                         text=True).stdout
    assert out.count("NOT RUN TEST-P6-28") == 2 and "CHECKED" not in out and "fail=0" in out


def test_9kg_78_2_an_intentionally_empty_list_is_healthy_only_where_fetching_is_disabled(tmp_path):
    empty, comments, broken, good = (tmp_path / name for name in ("empty", "comments", "broken", "good"))
    empty.write_text("")
    comments.write_text("# fetching is disabled in production\n\n   \n")
    broken.write_text("prod-a.example.test\n0x7f.0x0.0x0.0x1\n")
    good.write_text("prod-a.example.test\n")
    states = {path.name: egress.deny_file_state(str(path)) for path in (empty, comments, broken, good)}
    assert states == {"empty": "empty", "comments": "empty", "broken": "broken", "good": "loaded"}
    assert egress.deny_file_state(str(tmp_path / "missing")) == egress.deny_file_state("") == "broken"
    (tmp_path / "big").write_bytes(b"#" * (egress.DENY_FILE_LIMIT + 1))
    assert egress.deny_file_state(str(tmp_path / "big")) == "broken"
    disabled = {"CATALYST_EGRESS_FETCHING": "disabled"}
    for path, enabled_rc, disabled_rc in ((good, 0, 0), (empty, 1, 0), (comments, 1, 0), (broken, 1, 1),
                                          (tmp_path / "missing", 1, 1)):
        assert egress.check({"CATALYST_EGRESS_DENY_FILE": str(path)}) == enabled_rc, path.name
        assert egress.check({"CATALYST_EGRESS_DENY_FILE": str(path), **disabled}) == disabled_rc, path.name
    assert egress.check({"CATALYST_EGRESS_DENY_FILE": str(empty), "CATALYST_EGRESS_FETCHING": "Disabled"}) == 1
    # An empty list still refuses every fetch: the health check changes, the policy does not.
    assert egress.load_deny(str(empty)) == () and egress.load_deny(str(comments)) == ()
