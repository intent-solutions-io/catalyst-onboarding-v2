"""The live browser canary (9kg.87): what it records never carries the canary's login, address, password or a link
token; the verification mail it follows is bound to this run's exact address, exact origin and start; its mail cleanup
names one message by UID and never expunges the mailbox; a failed command is described without its command line; and
the run's verdict needs the erasure receipt, survives cleanup failures, and never reports a reused link as a PASS."""

import importlib.util
import json
import subprocess
import sys
import types
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://canary.example.test"
LOGIN = "inbox@example.test"
ADDRESS = "inbox+canary-1@example.test"
PASSWORD = "s3cret-mailbox-password"
INVITATION = "db267ebb-fdb0-4869-9798-ca2200bfaef3"


@pytest.fixture
def canary():
    spec = importlib.util.spec_from_file_location("live_canary", ROOT / "scripts" / "live_canary.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PRIVATE[:] = [f for v in (LOGIN, ADDRESS, PASSWORD) for f in module.private_forms(v)]
    return module


def test_9kg_87_redaction_removes_every_token_and_every_form_of_the_login_address_and_password(canary):
    text = (f"fill {ADDRESS} then {LOGIN} and {LOGIN.upper()} and inbox%2Bcanary-1%40example.test and "
            f"pw={PASSWORD} and GET {ORIGIN}/confirm/abc.DEF-123/ and /setup/tok/ and "
            f"\"url\":\"{ORIGIN}/withdraw/t0k3n\" and https://h/other/left")
    out = canary.redact(text)
    for private in (ADDRESS, LOGIN, LOGIN.upper(), "canary-1%40", PASSWORD, "abc.DEF-123", "/setup/tok", "t0k3n"):
        assert private not in out
    assert out.count("/REDACTED") == 3 and out.count("<canary private>") == 5 and "/other/left" in out
    assert canary.redact("") == "" and canary.redact(None) == ""
    assert canary.holds_private(f"x {ADDRESS.upper()} y".encode()) and canary.holds_private(b"/confirm/tok/")
    assert not canary.holds_private(f"x {ORIGIN}/confirm/REDACTED/ <canary private> y".encode())


def test_9kg_87_a_failed_command_is_described_without_its_command_line(canary):
    exc = subprocess.CalledProcessError(2, ["ssh", "host", "catalyst_invite", ADDRESS], stderr="usage\nrefused: x\n")
    text = canary.redact(canary.describe(exc))
    assert text == "command failed (exit 2): refused: x" and ADDRESS not in text
    assert canary.describe(subprocess.TimeoutExpired(["ssh"], 120)) == "command did not finish within 120s"
    assert canary.describe(ValueError("plain")) == "ValueError: plain"


def test_9kg_87_the_trace_text_entries_are_scrubbed_and_a_trace_that_still_leaks_is_discarded(canary, tmp_path):
    trace = tmp_path / "trace.zip"
    with zipfile.ZipFile(trace, "w") as z:
        z.writestr("trace.trace", json.dumps({"url": f"{ORIGIN}/confirm/tok123/", "value": ADDRESS}))
        z.writestr("trace.network", json.dumps({"postData": "email=inbox%2Bcanary-1%40example.test&name=x"}))
        z.writestr("resources/page.png", b"\x89PNG\r\n")
    assert canary.scrub_trace(trace) == "trace kept, text entries redacted"
    with zipfile.ZipFile(trace) as z:
        for name in ("trace.trace", "trace.network"):
            text = z.read(name).decode()
            assert "tok123" not in text and "canary-1" not in text and ("REDACTED" in text or "<canary private>" in text)
        assert z.read("resources/page.png") == b"\x89PNG\r\n"
    with zipfile.ZipFile(trace, "w") as z:  # a binary entry carrying the address cannot be redacted: the trace goes
        z.writestr("trace.trace", "{}")
        z.writestr("resources/blob.bin", b"\x00\x01" + ADDRESS.encode() + b"\x02")
    assert canary.scrub_trace(trace).startswith("trace discarded")
    assert not trace.exists() and not trace.with_suffix(".scrubbed").exists()
    assert canary.scrub_trace(tmp_path / "absent.zip") == "no trace"


class FakeImap:
    """An IMAP mailbox of uid -> (To, Date, body) recording every command, for wait_for_mail and delete_mail."""

    mailbox: dict = {}
    instances: list = []
    uid_expunge_supported = True

    def __init__(self, host, port, timeout=None, ssl_context=None):
        self.messages = dict(FakeImap.mailbox)
        self.commands = []
        self.timeout, self.ssl_context = timeout, ssl_context
        FakeImap.instances.append(self)

    def login(self, user, password):
        self.commands.append(("login", user))

    def select(self, box, readonly=False):
        self.commands.append(("select", box, readonly))

    def logout(self):
        self.commands.append(("logout",))

    def expunge(self):
        self.commands.append(("expunge",))

    def uid(self, command, *args):
        self.commands.append(("uid", command, *args))
        if command == "search":
            return "OK", [b" ".join(str(u).encode() for u in sorted(self.messages))]
        if command == "fetch":
            to, date, body = self.messages[int(args[0])]
            raw = f"To: {to}\r\nDate: {date}\r\nSubject: Confirm your email address\r\n\r\n{body}\r\n".encode()
            return "OK", [(b"", raw)]
        if command == "store":
            self.messages.pop(int(args[0]))
            return "OK", [b""]
        if command == "expunge":
            if not FakeImap.uid_expunge_supported:
                raise __import__("imaplib").IMAP4.error("BAD unknown command")
            return "OK", [b""]
        raise AssertionError(command)


def _date(moment):
    return moment.strftime("%a, %d %b %Y %H:%M:%S +0000")


SINCE = datetime(2026, 10, 30, 2, 0, tzinfo=timezone.utc)
FRESH, STALE = _date(SINCE + timedelta(seconds=30)), _date(SINCE - timedelta(minutes=10))
DISTRACTORS = {
    "another applicant of the same inbox": (LOGIN, FRESH, f"{ORIGIN}/confirm/OTHER-PERSON/ \n"),
    "the address as a substring": (f"not{ADDRESS}", FRESH, f"{ORIGIN}/confirm/SUBSTRING/ \n"),
    "an earlier run's mail": (ADDRESS, STALE, f"{ORIGIN}/confirm/STALE/ \n"),
    "a wrong origin": (ADDRESS, FRESH, "https://evil.example.test/confirm/PHISH/ \n"),
    "the origin as a prefix": (ADDRESS, FRESH, f"https://{ORIGIN[8:]}.evil.test/confirm/LOOKALIKE/ \n"),
    "a malformed message": (ADDRESS, "not a date", f"{ORIGIN}/confirm/MALFORMED/ \n"),
}


def test_9kg_87_only_a_mail_for_this_address_origin_and_run_qualifies_and_is_read_without_mutation(canary, monkeypatch):
    # The genuine mail has the LOWEST uid: every distractor above it is examined and rejected first.
    FakeImap.mailbox = {1: (ADDRESS, FRESH, f"This run {ORIGIN}/confirm/THIS-RUN/ \n"),
                        **{i + 2: m for i, m in enumerate(DISTRACTORS.values())}}
    FakeImap.instances = []
    monkeypatch.setattr(canary.imaplib, "IMAP4_SSL", FakeImap)
    link, uid = canary.wait_for_mail(LOGIN, "pw", "imap.example.test", SINCE, ORIGIN, ADDRESS, timeout=30)
    assert (link, uid) == (f"{ORIGIN}/confirm/THIS-RUN/", "1")
    box = FakeImap.instances[0]
    assert box.timeout and box.timeout <= 30 and box.ssl_context is not None  # bounded, verified TLS
    assert ("select", "INBOX", True) in box.commands  # a read-only session
    fetches = [c for c in box.commands if c[:2] == ("uid", "fetch")]
    assert len(fetches) == len(DISTRACTORS) + 1 and all(c[3] == "(BODY.PEEK[])" for c in fetches)
    search = next(c for c in box.commands if c[:2] == ("uid", "search"))[3]
    assert f'TO "{ADDRESS}"' in search and "SINCE 30-Oct-2026" in search
    assert ("uid", "store") not in {c[:2] for c in box.commands} and ("expunge",) not in box.commands
    assert box.commands[-1] == ("logout",)


@pytest.mark.parametrize("distractor", sorted(DISTRACTORS))
def test_9kg_87_without_a_qualifying_mail_the_wait_times_out_rather_than_following_a_look_alike(canary, monkeypatch,
                                                                                                distractor):
    FakeImap.mailbox = {1: DISTRACTORS[distractor]}
    FakeImap.instances = []
    monkeypatch.setattr(canary.imaplib, "IMAP4_SSL", FakeImap)
    monkeypatch.setattr(canary.time, "sleep", lambda s: None)
    clock = iter([0, 0, 0, 0, 100, 100, 100, 100])  # one poll round, then past the deadline
    monkeypatch.setattr(canary.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError):
        canary.wait_for_mail(LOGIN, "pw", "imap.example.test", SINCE, ORIGIN, ADDRESS, timeout=30)


def test_9kg_87_cleanup_deletes_the_one_message_by_uid_and_never_expunges_the_whole_mailbox(canary, monkeypatch):
    FakeImap.mailbox = {7: (ADDRESS, "x", "y"), 9: (LOGIN, "x", "unrelated, flagged deleted by someone else")}
    FakeImap.instances = []
    monkeypatch.setattr(canary.imaplib, "IMAP4_SSL", FakeImap)
    FakeImap.uid_expunge_supported = True
    assert canary.delete_mail(LOGIN, "pw", "imap.example.test", "7") == "deleted by UID"
    box = FakeImap.instances[0]
    assert ("uid", "store", "7", "+FLAGS", "\\Deleted") in box.commands and ("uid", "expunge", "7") in box.commands
    assert ("expunge",) not in box.commands and box.commands[-1] == ("logout",)
    FakeImap.uid_expunge_supported = False  # no UIDPLUS: the message stays flagged, the obligation is recorded
    FakeImap.instances = []
    outcome = canary.delete_mail(LOGIN, "pw", "imap.example.test", "7")
    assert outcome.startswith("UID EXPUNGE unsupported") and "by hand" in outcome
    assert ("expunge",) not in FakeImap.instances[0].commands
    FakeImap.uid_expunge_supported = True


def test_9kg_87_a_step_records_its_outcome_redacted_and_a_not_run_step_its_reason(canary, tmp_path):
    run = canary.Run(tmp_path)
    result = f"ref for {ADDRESS} at {ORIGIN}/confirm/t/"
    assert run.step("ok", lambda: result) == result
    assert run.steps[-1]["ok"] and run.steps[-1]["detail"] == f"ref for <canary private> at {ORIGIN}/confirm/REDACTED/"
    assert run.step("tuple result", lambda: (1, b"png-bytes")) == (1, b"png-bytes")
    assert run.steps[-1]["detail"] == ""  # only text results are recorded, never a screenshot's bytes
    with pytest.raises(RuntimeError):
        run.step("fails", lambda: (_ for _ in ()).throw(RuntimeError(f"saw {ADDRESS}")))
    assert run.steps[-1]["ok"] is False and run.steps[-1]["error"] == "RuntimeError: saw <canary private>"
    run.not_run(canary.ERASE, f"no --retention command for {ADDRESS}")
    assert run.steps[-1] == {"step": canary.ERASE, "ok": False, "not_run": True,
                             "detail": "no --retention command for <canary private>"}


class FakePlaywright:
    """The browser surface the canary touches, as a module injected under `playwright.sync_api`: pages render
    nothing, screenshots are empty files, and the trace stop writes a zip that carries the address and a token."""

    def __init__(self):
        self.cleanup_raises = False

    def install(self, monkeypatch):
        fake = self

        class Locator:
            def fill(self, value): pass
            def select_option(self, value): pass  # bgl.3: the country and interest selects
            def check(self): pass  # bgl.3: the "none" ticks, the consent and the 18+ attestation
            def click(self): pass
            def inner_text(self): return "Email address confirmed"
            def count(self): return 0

        class Expectation:
            def to_have_text(self, *a, **k): pass
            def to_contain_text(self, *a, **k): fake.contained = [*getattr(fake, "contained", []), a]
            def to_have_count(self, *a, **k): fake.counted = [*getattr(fake, "counted", []), a]
            def not_to_have_text(self, *a, **k): pass

        class Response:
            status = 200

        class Page:
            def on(self, event, handler): pass
            def goto(self, url): return Response()
            def locator(self, selector): return Locator()
            def get_by_role(self, role, name=None): return Locator()
            def get_by_text(self, text, exact=False): return Locator()
            def screenshot(self, path, full_page=False, mask=()): Path(path).write_bytes(b"\x89PNG")
            def wait_for_timeout(self, ms): fake.waited = getattr(fake, "waited", 0) + ms

        class Tracing:
            def start(self, **kwargs): fake.tracing_options = kwargs
            def stop(self, path):
                if fake.cleanup_raises:
                    raise RuntimeError("trace save failed")
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr("trace.trace", json.dumps({"fill": ADDRESS, "goto": f"{ORIGIN}/confirm/tok/"}))

        class Context:
            tracing = Tracing()
            def new_page(self): return Page()

        class Browser:
            def new_context(self, **kwargs): return Context()
            def close(self):
                if fake.cleanup_raises:
                    raise RuntimeError("browser close failed")

        class Chromium:
            def launch(self, executable_path=None, env=None):
                fake.launch_env = env
                return Browser()

        class Playwright:
            chromium = Chromium()
            def __enter__(self): return self
            def __exit__(self, *exc): return False

        module = types.ModuleType("playwright.sync_api")
        module.sync_playwright = lambda: Playwright()
        module.expect = lambda locator: Expectation()
        package = types.ModuleType("playwright")
        package.sync_api = module
        monkeypatch.setitem(sys.modules, "playwright", package)
        monkeypatch.setitem(sys.modules, "playwright.sync_api", module)


@pytest.fixture
def journey(canary, monkeypatch, tmp_path):
    """main() with every external call faked; returns (run_main, calls, fake) where run_main(*args) -> exit code."""
    fake = FakePlaywright()
    fake.install(monkeypatch)
    calls = []

    def run_json(command):
        calls.append(command)
        if "catalyst_invite" in command:
            return {"invitation": INVITATION, "superseded": False, "issued": True}
        if "catalyst_erase" in command:
            return {"status": "erased", "changed": 4, "handoffs": [], "retained": [], "journal_head": "id:1:abc"}
        if "catalyst_erasure_record" in command:
            return {"open": [], "head": "id:1:abc"}
        raise AssertionError(command)
    monkeypatch.setattr(canary, "run_json", run_json)
    monkeypatch.setattr(canary, "wait_for_mail", lambda *a, **k: (f"{ORIGIN}/confirm/THIS-RUN/", "5"))
    deletions = []

    def delete_mail(user, password, host, uid):
        if fake.cleanup_raises:
            raise RuntimeError("imap down")
        deletions.append(uid)
        return "deleted by UID"
    monkeypatch.setattr(canary, "delete_mail", delete_mail)
    monkeypatch.setenv("CANARY_MAIL_USER", LOGIN)
    monkeypatch.setenv("CANARY_MAIL_PASSWORD", PASSWORD)
    monkeypatch.setenv("CANARY_ADDRESS", ADDRESS)
    monkeypatch.setattr(canary, "inside_repository", lambda path: False)

    def run_main(*extra):
        monkeypatch.setattr(sys, "argv", ["live_canary.py", "--public-url", ORIGIN, "--invite", "ssh host manage",
                                          "--out", str(tmp_path / "runs"), *extra])
        return canary.main()
    return run_main, calls, deletions, fake, tmp_path / "runs"


def _report(out):
    [run_dir] = sorted(p for p in out.iterdir() if p.is_dir())
    return run_dir, json.loads((run_dir / "run.json").read_text())


def test_9kg_87_a_fresh_journey_passes_only_with_the_erasure_receipt_and_records_nothing_private(journey, capsys):
    run_main, calls, deletions, fake, out = journey
    assert run_main("--retention", "ssh host erase") == 0
    run_dir, report = _report(out)
    assert report["ok"] and report["journey_ok"] and report["erased"] and report["cleanup_ok"]
    assert report["mode"] == "fresh journey" and report["invitation"] == INVITATION and report["erasure_head"] == "id:1:abc"
    names = [s["step"] for s in report["steps"]]
    assert names[:2] == ["invite", "open the request form"] and names[-2:] == [
        "erase the canary person", "verify the erasure record"]
    assert all(s["ok"] for s in report["steps"]) and deletions == ["5"]
    erase = next(c for c in calls if "catalyst_erase" in c)
    assert erase[:3] == ["ssh", "host", "erase"] and erase[erase.index("--subject") + 1] == INVITATION
    assert "CANARY_MAIL_PASSWORD" not in fake.launch_env and "CANARY_ADDRESS" not in fake.launch_env
    assert fake.tracing_options == {"screenshots": False, "snapshots": False, "sources": False}
    everything = "".join(p.read_text() for p in run_dir.glob("*.json")) + capsys.readouterr().out
    for private in (ADDRESS, LOGIN, PASSWORD, "/confirm/tok/", "THIS-RUN"):
        assert private not in everything
    with zipfile.ZipFile(run_dir / "trace.zip") as z:
        assert ADDRESS not in z.read("trace.trace").decode() and "tok" not in z.read("trace.trace").decode()
    assert (run_dir.stat().st_mode & 0o777) == 0o700


def test_9kg_87_without_the_retention_command_the_erasure_is_not_run_and_the_run_fails(journey, capsys):
    run_main, calls, deletions, fake, out = journey
    assert run_main() == 1
    _, report = _report(out)
    erase = next(s for s in report["steps"] if s["step"] == "erase the canary person")
    assert report["journey_ok"] and not report["erased"] and not report["ok"]
    assert erase["not_run"] and "--retention" in erase["detail"]
    assert not any("catalyst_erase" in c for c in calls)
    assert "NOT RUN  erase the canary person" in capsys.readouterr().out


def test_9kg_87_an_erasure_that_erased_nothing_or_printed_no_head_is_not_a_receipt(journey, canary, monkeypatch):
    run_main, calls, deletions, fake, out = journey
    original = canary.run_json

    def run_json(command):
        result = original(command)
        if "catalyst_erase" in command:
            result = {**result, "status": "nothing_to_erase", "changed": 0}
        return result
    monkeypatch.setattr(canary, "run_json", run_json)
    assert run_main("--retention", "ssh host erase") == 1
    _, report = _report(out)
    erase = next(s for s in report["steps"] if s["step"] == "erase the canary person")
    assert not erase["ok"] and "nothing_to_erase" in erase["error"] and not report["erased"]
    assert not any("catalyst_erasure_record" in c for c in calls)


def test_9kg_87_a_reused_link_run_is_a_diagnostic_never_a_fresh_pass(journey):
    run_main, calls, deletions, fake, out = journey
    assert run_main("--retention", "ssh host erase", "--mail-window-minutes", "30") == 2
    _, report = _report(out)
    assert report["journey_ok"] and report["erased"] and not report["ok"]
    assert report["mode"].startswith("link-reuse diagnostic")


def test_9kg_87_the_reports_survive_cleanup_failures_and_a_failed_cleanup_fails_the_run(journey):
    run_main, calls, deletions, fake, out = journey
    fake.cleanup_raises = True
    assert run_main("--retention", "ssh host erase") == 1
    run_dir, report = _report(out)
    assert (run_dir / "console.json").exists() and (run_dir / "requests.json").exists()
    failed = {s["step"] for s in report["steps"] if not s["ok"] and not s.get("not_run")}
    assert failed == {"save the trace", "close the browser", "delete the verification mail"}
    assert report["journey_ok"] and report["erased"] and not report["cleanup_ok"] and not report["ok"]


def test_9kg_87_the_login_address_and_a_superseding_invitation_are_refused_as_the_canary(journey, canary, monkeypatch,
                                                                                         capsys):
    run_main, calls, deletions, fake, out = journey
    monkeypatch.setenv("CANARY_ADDRESS", LOGIN)
    assert run_main("--retention", "ssh host erase") == 1 and not calls and not out.exists()
    assert "distinct from its login" in capsys.readouterr().err
    monkeypatch.setenv("CANARY_ADDRESS", ADDRESS)
    original = canary.run_json
    monkeypatch.setattr(canary, "run_json", lambda c: {**original(c), "superseded": True} if "catalyst_invite" in c
                        else original(c))
    assert run_main("--retention", "ssh host erase") == 1
    _, report = _report(out)
    assert report["steps"][0]["step"] == "invite" and not report["steps"][0]["ok"]
    assert "already existed" in report["steps"][0]["error"] and not report["journey_ok"]
    erase = next(s for s in report["steps"] if s["step"] == "erase the canary person")
    assert erase["not_run"] and "outcome is unknown" in erase["detail"]


def test_bgl_2_open_intake_checks_that_no_data_notice_is_shown_and_still_invites_the_erasure_subject(journey):
    run_main, calls, deletions, fake, out = journey
    assert run_main("--retention", "ssh host erase", "--intake-mode", "open") == 0
    _, report = _report(out)
    names = [s["step"] for s in report["steps"]]
    assert report["ok"] and "no data notice (open intake)" in names and "data notice shown" not in names
    assert ("pseudonymous record",) not in fake.contained and (0,) in fake.counted
    assert any("catalyst_invite" in c for c in calls) and report["invitation"] == INVITATION
    assert fake.waited >= 4000  # past the form's minimum age before submitting


def test_bgl_2_invitation_mode_is_the_default_and_checks_the_data_notice(journey):
    run_main, calls, deletions, fake, out = journey
    assert run_main("--retention", "ssh host erase") == 0
    _, report = _report(out)
    names = [s["step"] for s in report["steps"]]
    assert "data notice shown" in names and "no data notice (open intake)" not in names
    assert ("pseudonymous record",) in fake.contained
