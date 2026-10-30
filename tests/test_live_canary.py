"""The live browser canary's helpers (9kg.87): what it records never carries the canary's address or a link token,
the verification mail it follows is bound to this run's address, origin and start, its mail cleanup names one message
by UID, and a failed command is described without its command line."""

import importlib.util
import json
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://canary.example.test"
ADDRESS = "inbox+canary-1@example.test"
LOGIN = "inbox@example.test"


@pytest.fixture
def canary():
    spec = importlib.util.spec_from_file_location("live_canary", ROOT / "scripts" / "live_canary.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PRIVATE[:] = [ADDRESS, LOGIN]
    return module


def test_9kg_87_redaction_removes_every_token_and_the_canary_login_and_address(canary):
    text = (f"fill {ADDRESS} then {LOGIN} and GET {ORIGIN}/confirm/abc.DEF-123/ and /setup/tok/ and "
            f"\"url\":\"{ORIGIN}/withdraw/t0k3n\" and https://h/other/left")
    out = canary.redact(text)
    for private in (ADDRESS, LOGIN, "abc.DEF-123", "/setup/tok", "t0k3n"):
        assert private not in out
    assert out.count("/REDACTED") == 3 and "<canary address>" in out and "/other/left" in out
    assert canary.redact("") == "" and canary.redact(None) == ""


def test_9kg_87_a_failed_command_is_described_without_its_command_line(canary):
    exc = subprocess.CalledProcessError(2, ["ssh", "host", "catalyst_invite", ADDRESS], stderr="usage\nrefused: x\n")
    text = canary.redact(canary.describe(exc))
    assert text == "command failed (exit 2): refused: x" and ADDRESS not in text
    assert canary.describe(subprocess.TimeoutExpired(["ssh"], 120)) == "command did not finish within 120s"
    assert canary.describe(ValueError("plain")) == "ValueError: plain"


def test_9kg_87_the_trace_text_entries_are_scrubbed_and_binary_entries_kept(canary, tmp_path):
    trace = tmp_path / "trace.zip"
    with zipfile.ZipFile(trace, "w") as z:
        z.writestr("trace.trace", json.dumps({"url": f"{ORIGIN}/confirm/tok123/", "value": ADDRESS}))
        z.writestr("trace.network", json.dumps({"referer": f"{ORIGIN}/confirm/tok123/"}))
        z.writestr("resources/page.png", b"\x89PNG\r\n")
    canary.scrub_trace(trace)
    with zipfile.ZipFile(trace) as z:
        for name in ("trace.trace", "trace.network"):
            text = z.read(name).decode()
            assert "tok123" not in text and ADDRESS not in text and "REDACTED" in text
        assert z.read("resources/page.png") == b"\x89PNG\r\n"
    canary.scrub_trace(tmp_path / "absent.zip")  # a run that never saved a trace is not an error


class FakeImap:
    """An IMAP mailbox of (uid, To, Date, body) messages recording every command, for wait_for_mail/delete_mail."""

    instances: list = []

    def __init__(self, host, port, timeout=None):
        self.messages = dict(FakeImap.mailbox)
        self.commands = []
        self.timeout = timeout
        FakeImap.instances.append(self)

    def login(self, user, password):
        self.commands.append(("login", user))

    def select(self, box):
        self.commands.append(("select", box))

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
            return "OK", [b""]
        raise AssertionError(command)


def _date(moment):
    return moment.strftime("%a, %d %b %Y %H:%M:%S +0000")


def test_9kg_87_only_a_mail_for_this_address_origin_and_run_qualifies_and_is_read_without_mutation(canary, monkeypatch):
    since = datetime(2026, 10, 30, 2, 0, tzinfo=timezone.utc)
    fresh, stale = _date(since + timedelta(seconds=30)), _date(since - timedelta(minutes=10))
    FakeImap.mailbox = {
        1: (ADDRESS, fresh, f"Older link {ORIGIN}/confirm/EARLIER/ \n"),                     # uid order: not the newest
        2: (LOGIN, fresh, f"For the inbox itself {ORIGIN}/confirm/OTHER-PERSON/ \n"),          # another applicant
        3: (ADDRESS, stale, f"Before the run {ORIGIN}/confirm/STALE/ \n"),                      # earlier run's link
        4: (ADDRESS, fresh, "Elsewhere https://evil.example.test/confirm/PHISH/ \n"),         # wrong origin
        5: (ADDRESS, fresh, f"Prefix https://{ORIGIN[8:]}.evil.test/confirm/LOOKALIKE/ \n"),  # origin as a prefix
        6: (ADDRESS, fresh, f"This run {ORIGIN}/confirm/THIS-RUN/ \n"),
    }
    FakeImap.instances = []
    monkeypatch.setattr(canary.imaplib, "IMAP4_SSL", FakeImap)
    link, uid = canary.wait_for_mail(LOGIN, "pw", "imap.example.test", since, ORIGIN, ADDRESS, timeout=30)
    assert (link, uid) == (f"{ORIGIN}/confirm/THIS-RUN/", "6")
    box = FakeImap.instances[0]
    assert box.timeout and box.timeout <= 30
    fetches = [c for c in box.commands if c[:2] == ("uid", "fetch")]
    assert fetches and all(c[3] == "(BODY.PEEK[])" for c in fetches)  # read-only: no \\Seen flag is set
    assert ("uid", "store") not in {c[:2] for c in box.commands} and ("expunge",) not in box.commands
    assert box.commands[-1] == ("logout",)


def test_9kg_87_without_a_qualifying_mail_the_wait_times_out_rather_than_following_a_look_alike(canary, monkeypatch):
    since = datetime(2026, 10, 30, 2, 0, tzinfo=timezone.utc)
    FakeImap.mailbox = {1: (LOGIN, _date(since + timedelta(seconds=5)), f"{ORIGIN}/confirm/OTHER-PERSON/ \n")}
    FakeImap.instances = []
    monkeypatch.setattr(canary.imaplib, "IMAP4_SSL", FakeImap)
    monkeypatch.setattr(canary.time, "sleep", lambda s: None)
    clock = iter([0, 0, 100, 100, 100])  # past the deadline after one round
    monkeypatch.setattr(canary.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError):
        canary.wait_for_mail(LOGIN, "pw", "imap.example.test", since, ORIGIN, ADDRESS, timeout=30)


def test_9kg_87_cleanup_deletes_the_one_message_by_uid_and_never_expunges_the_whole_mailbox(canary, monkeypatch):
    FakeImap.mailbox = {7: (ADDRESS, "x", "y"), 9: (LOGIN, "x", "unrelated, already flagged elsewhere")}
    FakeImap.instances = []
    monkeypatch.setattr(canary.imaplib, "IMAP4_SSL", FakeImap)
    canary.delete_mail(LOGIN, "pw", "imap.example.test", "7")
    box = FakeImap.instances[0]
    assert ("uid", "store", "7", "+FLAGS", "\\Deleted") in box.commands
    assert ("uid", "expunge", "7") in box.commands and ("expunge",) not in box.commands
    assert 9 in box.messages and 7 not in box.messages and box.commands[-1] == ("logout",)


def test_9kg_87_a_step_records_its_outcome_redacted_and_a_not_run_step_its_reason(canary, tmp_path):
    run = canary.Run(tmp_path)
    assert run.step("ok", lambda: f"ref for {ADDRESS} at {ORIGIN}/confirm/t/") == f"ref for {ADDRESS} at {ORIGIN}/confirm/t/"
    assert run.steps[-1]["ok"] and run.steps[-1]["detail"] == f"ref for <canary address> at {ORIGIN}/confirm/REDACTED/"
    assert run.step("tuple result", lambda: (1, b"png-bytes")) == (1, b"png-bytes")
    assert run.steps[-1]["detail"] == ""  # only text results are recorded, never a screenshot's bytes
    with pytest.raises(RuntimeError):
        run.step("fails", lambda: (_ for _ in ()).throw(RuntimeError(f"saw {ADDRESS}")))
    assert run.steps[-1] == {**run.steps[-1], "ok": False, "error": "RuntimeError: saw <canary address>"}
    run.not_run("erase the canary person", "no --retention command")
    assert run.steps[-1]["not_run"] and not run.steps[-1]["ok"]
