"""The live browser canary (9kg.87): one real applicant journey against the deployed site, recorded for review.

    sops exec-env <canary secrets> 'CANARY_ADDRESS=inbox+canary-N@example python3 scripts/live_canary.py \
        --public-url https://<v2 host> --invite "ssh <host alias> sudo <manage wrapper>" \
        --retention "ssh <host alias> sudo <retention wrapper>" --out <private dir>'

The canary identity is CANARY_ADDRESS, a sub-address (`inbox+canary-N@`) of the owner's test inbox CANARY_MAIL_USER:
mail to it lands in that inbox, and it is a distinct applicant identity that the erasure at the end can cover without
touching the inbox's own address (which may be a real identity). The login address itself is refused as the canary.
An invitation that supersedes a live one for the address is refused too: the identity was already in use.

Steps, each timed and screenshotted: invite the canary address through the real `catalyst_invite`; open the public
request form in headless Chromium and submit it from that address; read this run's verification mail from the inbox
by IMAP (addressed to exactly the canary address, dated after the run began, with a link on the exact public origin);
open the link twice and check that a GET alone does not confirm; confirm with the form's POST; assert the confirmed
page; open the link once more and check it shows the confirmed page with nothing left to submit. Then the canary
person is erased with `catalyst_erase` through the `--retention` command (one that runs manage.py as the retention
login with the erasure key; the invitation's reference names the person and covers every record of that address)
and the erasure record is checked with `catalyst_erasure_record --expect-head` on the printed head, which is the
receipt. The run passes only when the erasure reports `erased` with changed rows and the record verifies. Without
`--retention` the erasure is NOT RUN and the run fails: a canary person left in production is a failed run.
`--mail-window-minutes` accepts an earlier run's mail (a reused link) for diagnosis; such a run is reported as
DIAGNOSTIC and never as a fresh full-journey PASS.

The run directory (outside any repository, mode 0700) holds the Playwright trace (`trace.zip`: actions and network
timeline, no DOM snapshots and no screencast; replay with `playwright show-trace`), the step screenshots with the
address masked, the browser console messages, page errors and failed requests, and `run.json` with every step's
outcome and timing plus the erasure head the owner keeps out of band. The verification mail is deleted from the inbox
afterwards: it holds a one-time link. No text record carries the canary's login, address, password or a link token:
all are redacted before anything is written, the trace's entries are rewritten in place and the trace is discarded
if any entry still holds one, and a screenshot is discarded if the page showed the address outside the masked
elements. Every external call is bounded, IMAP reads are read-only, cleanup deletes one message by UID (never a plain
EXPUNGE), and the reports are written even when cleanup fails.

Exit 0 when every step passed, the cleanup and the erasure included; 2 for a DIAGNOSTIC run that passed; 1 otherwise.
"""

import argparse
import email
import imaplib
import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import time
import urllib.parse
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

TOKEN = re.compile(r"(/(?:confirm|setup|withdraw)/)[^/\s\"'\\]+")
ADDRESS_SHAPE = re.compile(r"^[A-Za-z0-9._+-]{1,64}@[A-Za-z0-9.-]{1,255}$")  # conservative: it travels through ssh
COMMAND_TIMEOUT = 120  # seconds for one invitation, erasure or record command
MAIL_TIMEOUT = 300  # seconds to wait for the verification mail
ERASE = "erase the canary person"
PRIVATE: list[str] = []  # the canary's login, address and password; set once in main(); redact() replaces them all
TEXT_ENTRIES = (".trace", ".network", ".json", ".txt", ".stacks")


def private_forms(value: str) -> list[str]:
    """The spellings of a private value that can appear in a record: as is, case-folded, and percent-encoded."""
    forms = {value, value.casefold(), urllib.parse.quote(value, safe=""), urllib.parse.quote_plus(value)}
    return sorted((f for f in forms if f), key=len, reverse=True)


def redact(text: str) -> str:
    """The text with every link token and every form of the canary's login, address and password replaced."""
    text = TOKEN.sub(r"\1REDACTED", text or "")
    for value in PRIVATE:
        pattern = re.compile(re.escape(value), re.IGNORECASE)
        text = pattern.sub("<canary private>", text)
    return text


def holds_private(data: bytes) -> bool:
    """Whether a byte string (text or binary) still carries a private value or a link token."""
    text = data.decode("utf-8", errors="replace")
    if TOKEN.search(text) and any(m.group(0).split("/")[-1] != "REDACTED" for m in TOKEN.finditer(text)):
        return True
    return any(re.search(re.escape(value), text, re.IGNORECASE) for value in PRIVATE)


class Run:
    """The ordered steps of one run, each with its outcome, timing and a redacted detail or error."""

    def __init__(self, out: Path):
        self.out, self.steps, self.started = out, [], time.monotonic()

    def step(self, name, fn):
        """Run `fn` as the step `name`; record PASS with its string result or FAIL with the error, then re-raise."""
        began = time.monotonic()
        try:
            detail = fn()
            self.steps.append({"step": name, "ok": True, "seconds": round(time.monotonic() - began, 2),
                               "detail": redact(detail) if isinstance(detail, str) else ""})
            return detail
        except Exception as exc:  # recorded, then the run stops
            self.steps.append({"step": name, "ok": False, "seconds": round(time.monotonic() - began, 2),
                               "error": redact(describe(exc))[:500]})
            raise

    def not_run(self, name, why):
        """Record a step that was not attempted, with the reason."""
        self.steps.append({"step": name, "ok": False, "not_run": True, "detail": redact(why)})


def describe(exc: Exception) -> str:
    """An exception as text that never carries the failed command (which can hold the address): class, exit code and
    the last line of stderr for a command failure; class and message otherwise."""
    if isinstance(exc, subprocess.CalledProcessError):
        tail = (exc.stderr or "").strip().splitlines()[-1:] or [""]
        return f"command failed (exit {exc.returncode}): {tail[0]}"
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"command did not finish within {exc.timeout}s"
    return f"{type(exc).__name__}: {exc}"


def child_env() -> dict:
    """The environment for child processes (the browser, ssh): the canary's secrets never travel with it."""
    return {k: v for k, v in os.environ.items() if not k.startswith("CANARY_")}


def run_json(command: list[str]) -> dict:
    """Run a command that prints one JSON object (possibly after other lines) and return it, bounded in time."""
    done = subprocess.run(command, capture_output=True, text=True, check=True, timeout=COMMAND_TIMEOUT,
                          env=child_env())
    for line in reversed(done.stdout.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise ValueError("the command printed no JSON object")


def connect(host, user, password, timeout, readonly):
    """A verified-TLS IMAP session on INBOX, read-only unless the caller is deleting."""
    box = imaplib.IMAP4_SSL(host, 993, timeout=timeout, ssl_context=ssl.create_default_context())
    box.login(user, password)
    box.select("INBOX", readonly=readonly)
    return box


def wait_for_mail(user, password, host, since, origin, address, timeout=MAIL_TIMEOUT):
    """The newest verification mail addressed to exactly `address`, received after `since`, whose link is on the
    exact `origin`: (link, IMAP UID). A matching subject alone never qualifies a message; a malformed one is skipped.

    Polled every 10 seconds in a read-only session with BODY.PEEK fetches; the search is narrowed to the address and
    the run's day, and the deadline is checked before every fetch."""
    link = re.compile(re.escape(origin) + r"/confirm/[^\s/]+/")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        box = connect(host, user, password, max(5, deadline - time.monotonic()), readonly=True)
        try:
            query = f'(SUBJECT "Confirm your email address" TO "{address}" SINCE {since.strftime("%d-%b-%Y")})'
            _, found = box.uid("search", None, query)
            for uid in reversed(found[0].split()):
                if time.monotonic() >= deadline:
                    break
                try:
                    _, data = box.uid("fetch", uid, "(BODY.PEEK[])")
                    message = email.message_from_bytes(data[0][1])
                    recipients = [addr.casefold() for _, addr in getaddresses(message.get_all("To") or [])]
                    if address.casefold() not in recipients:  # the parsed address, equal: never a substring match
                        continue
                    sent = parsedate_to_datetime(message["Date"])
                    if sent.tzinfo is None:
                        sent = sent.replace(tzinfo=timezone.utc)
                    if sent < since:
                        continue
                    part = message if not message.is_multipart() else next(
                        p for p in message.walk() if p.get_content_type() == "text/plain")
                    match = link.search(part.get_payload(decode=True).decode(errors="replace"))
                except (StopIteration, TypeError, ValueError, AttributeError, IndexError):
                    continue  # a malformed message never fails the wait; the real mail is well formed
                if match:
                    return match.group(0), uid.decode()
        finally:
            box.logout()
        time.sleep(10)
    raise TimeoutError("no verification mail within the timeout")


def delete_mail(user, password, host, uid):
    """Delete the one message `uid` with UID EXPUNGE, which removes that message alone. Never a plain EXPUNGE: the
    inbox may hold unrelated messages someone else flagged. Where the server lacks UID EXPUNGE the message stays
    flagged \\Deleted and the returned text records the manual cleanup still owed."""
    box = connect(host, user, password, 60, readonly=False)
    try:
        box.uid("store", uid, "+FLAGS", "\\Deleted")
        try:
            box.uid("expunge", uid)
        except imaplib.IMAP4.error:
            return "UID EXPUNGE unsupported: the verification mail is flagged deleted; expunge it by hand"
        return "deleted by UID"
    finally:
        box.logout()


def scrub_trace(path: Path) -> str:
    """Rewrite the trace's text entries through redact(); then, if any entry (binary ones included) still holds a
    private value or a token, discard the trace. Returns what was kept."""
    if not path.exists():
        return "no trace"
    scrubbed = path.with_suffix(".scrubbed")
    leaking = []
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(scrubbed, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item)
            if item.filename.endswith(TEXT_ENTRIES):
                data = redact(data.decode("utf-8", errors="replace")).encode()
            if holds_private(data):
                leaking.append(item.filename)
            dst.writestr(item, data)
    if leaking:
        scrubbed.unlink()
        path.unlink()
        return f"trace discarded: {len(leaking)} entries still held a private value"
    scrubbed.replace(path)
    return "trace kept, text entries redacted"


def inside_repository(path: Path) -> bool:
    """Whether `path` (or a parent) is a git work tree: the evidence never lives in one."""
    return any((p / ".git").exists() for p in (path.resolve(), *path.resolve().parents))


def main() -> int:
    """Run the canary; see the module docstring."""
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser()
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--invite", required=True,
                        help="the command that runs manage.py as the owner login on the host (catalyst_invite)")
    parser.add_argument("--retention", default="",
                        help="the command that runs manage.py as the retention login with the erasure key "
                             "(catalyst_erase, catalyst_erasure_record); without it the erasure is NOT RUN")
    parser.add_argument("--erase-authority", default="owner:9kg.87", help="the erasure's authority code")
    parser.add_argument("--erase-reason", default="canary_test_subject", help="the erasure's reason code")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--imap-host", default="sunfire.mxrouting.net")
    parser.add_argument("--mail-window-minutes", type=int, default=0,
                        help="also accept a verification mail this many minutes older than the run (a reused link)")
    args = parser.parse_args()
    user, password = os.environ["CANARY_MAIL_USER"], os.environ["CANARY_MAIL_PASSWORD"]
    address = os.environ.get("CANARY_ADDRESS", "").strip()
    PRIVATE[:] = [f for v in (user, address, password) for f in private_forms(v)]
    if not address or address.casefold() == user.casefold() or not ADDRESS_SHAPE.match(address):
        print("FAIL: CANARY_ADDRESS must be a sub-address of the canary inbox, distinct from its login", file=sys.stderr)
        return 1
    if inside_repository(args.out):
        print("FAIL: --out must be outside any repository", file=sys.stderr)
        return 1
    origin = args.public_url.rstrip("/")
    fresh = args.mail_window_minutes == 0
    out = args.out / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, mode=0o700)
    out.chmod(0o700)
    run = Run(out)
    console, failures = [], []
    since = datetime.now(timezone.utc).replace(microsecond=0)
    journey_ok = erased = False
    cleanup_ok = True
    head = None
    invited = None
    invite_attempted = False
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("CANARY_CHROMIUM") or None, env=child_env())
            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
            context.tracing.start(screenshots=False, snapshots=False, sources=False)
            page = context.new_page()
            page.on("console", lambda m: console.append({"type": m.type, "text": redact(m.text)}))
            page.on("pageerror", lambda e: console.append({"type": "pageerror", "text": redact(str(e))}))
            page.on("requestfailed", lambda r: failures.append({"url": redact(r.url), "failure": r.failure}))
            page.on("response", lambda r: failures.append({"url": redact(r.url), "status": r.status})
                    if r.status >= 400 else None)

            def shot(name):
                """A full-page screenshot with the elements that show the address masked. If the page shows the
                address anywhere else (inside a sentence), the screenshot is discarded and the step fails."""
                target = out / f"{len(run.steps):02d}-{name}.png"
                masks = [page.locator("#id_email"), page.get_by_text(address, exact=True)]
                page.screenshot(path=str(target), full_page=True, mask=masks)
                if page.get_by_text(address, exact=False).count() > page.get_by_text(address, exact=True).count():
                    target.unlink()
                    raise AssertionError(f"the page shows the address outside the masked elements ({name})")

            mail_uid = None
            try:
                def invite():
                    nonlocal invite_attempted
                    invite_attempted = True
                    # no spaces in any argument: the command may run through ssh, where the remote shell re-splits
                    issued = run_json([*shlex.split(args.invite), "catalyst_invite", address, "--issued-by",
                                       "live-canary", "--days", "1", "--note", "live-canary"])
                    if issued.get("superseded"):
                        raise AssertionError("a live invitation for this address already existed: use a fresh "
                                             "sub-address, this identity was in use")
                    return str(uuid.UUID(str(issued["invitation"])))  # the reference, validated before it is reused
                invited = run.step("invite", invite)
                run.step("open the request form", lambda: (page.goto(f"{origin}/request-access/"),
                                                           expect(page.locator("h1")).to_have_text("Request access"),
                                                           shot("form")))
                run.step("data notice shown", lambda: expect(page.locator("#data-notice")).to_contain_text(
                    "pseudonymous record"))

                def submit():
                    page.locator("#id_name").fill("Live Canary")
                    page.locator("#id_email").fill(address)
                    page.locator("#id_reason").fill("Live canary check of the deployed service.")
                    shot("filled")
                    page.wait_for_timeout(4000)  # bgl.2: the form refuses a submission under 3 s after rendering
                    page.get_by_role("button", name="Send request").click()
                    expect(page.locator("h1")).to_have_text("Request received")
                    shot("received")
                run.step("submit the form", submit)
                link, mail_uid = run.step("verification mail arrives", lambda: wait_for_mail(
                    user, password, args.imap_host, since - timedelta(minutes=args.mail_window_minutes), origin,
                    address))

                def open_link():
                    """GET the link twice: the page asks for confirmation both times, so a GET alone confirms nothing."""
                    for _ in range(2):
                        page.goto(link)
                        expect(page.locator("h1")).to_have_text("Confirm your email address")
                        expect(page.locator("dl")).to_contain_text("Live Canary")
                        expect(page.get_by_role("button", name="Confirm")).to_have_count(1)
                    shot("confirm")
                run.step("open the link: a GET alone does not confirm", open_link)

                def confirm():
                    page.get_by_role("button", name="Confirm").click()
                    expect(page.locator("h1")).to_have_text("Email address confirmed")
                    shot("confirmed")
                run.step("confirm", confirm)

                def once_only():
                    """The used link shows the confirmed page (status 200) with no Confirm button: nothing to submit
                    twice. The server side is checked by the owner in the dossier: one contact_verified event."""
                    response = page.goto(link)
                    expect(page.locator("h1")).to_have_text("Email address confirmed")
                    expect(page.get_by_role("button", name="Confirm")).to_have_count(0)
                    shot("link-after-confirmation")
                    return f"status {response.status}: {page.locator('h1').inner_text()}, no Confirm button"
                run.step("the link cannot confirm again", once_only)
                journey_ok = True
            except Exception:
                try:
                    shot("failure")
                except Exception:
                    pass
            finally:
                for name, fn in (("save the trace", lambda: context.tracing.stop(path=str(out / "trace.zip"))),
                                 ("close the browser", browser.close),
                                 ("delete the verification mail", lambda: delete_mail(
                                     user, password, args.imap_host, mail_uid) if mail_uid else "no mail to delete")):
                    try:
                        run.step(name, fn)
                    except Exception:
                        cleanup_ok = False
        try:
            run.step("redact the trace", lambda: scrub_trace(out / "trace.zip"))
        except Exception:
            cleanup_ok = False
            (out / "trace.zip").unlink(missing_ok=True)  # never keep a trace the redaction could not finish
        if invited is None and not invite_attempted:
            run.not_run(ERASE, "nothing was invited")
        elif invited is None:
            run.not_run(ERASE, "the invitation's outcome is unknown (the command failed or printed no reference): "
                               "an invitation may exist; check the host")
        elif not args.retention:
            run.not_run(ERASE, "no --retention command (the retention login and the erasure key)")
        else:
            try:
                def erase():
                    outcome = run_json([*shlex.split(args.retention), "catalyst_erase", "--subject", invited,
                                        "--authority", args.erase_authority, "--reason", args.erase_reason])
                    if outcome.get("status") != "erased" or not outcome.get("changed"):
                        raise AssertionError(f"the erasure reported {outcome.get('status')!r} with "
                                             f"{outcome.get('changed')} changes: not an erasure of the canary person")
                    if not outcome.get("journal_head"):
                        raise AssertionError("the erasure printed no journal head: no receipt")
                    return json.dumps({k: outcome.get(k) for k in
                                       ("status", "changed", "handoffs", "retained", "journal_head")})
                head = json.loads(run.step(ERASE, erase))["journal_head"]
                run.step("verify the erasure record", lambda: json.dumps(run_json(
                    [*shlex.split(args.retention), "catalyst_erasure_record", "--expect-head", str(head)])))
                erased = True
            except Exception:
                pass
    finally:
        if invite_attempted and not any(s["step"] == ERASE for s in run.steps):
            run.not_run(ERASE, "interrupted before the erasure: the canary person may still be in production")
        ok = journey_ok and erased and cleanup_ok
        mode = "fresh journey" if fresh else f"link-reuse diagnostic (mail window {args.mail_window_minutes} min)"
        (out / "console.json").write_text(json.dumps(console, indent=1))
        (out / "requests.json").write_text(json.dumps(failures, indent=1))
        (out / "run.json").write_text(json.dumps({
            "ok": ok and fresh, "mode": mode, "journey_ok": journey_ok, "cleanup_ok": cleanup_ok, "erased": erased,
            "invitation": invited, "erasure_head": head, "public_url": origin, "started_at": since.isoformat(),
            "seconds": round(time.monotonic() - run.started, 1), "steps": run.steps,
            "console_errors": sum(1 for c in console if c["type"] in ("error", "pageerror")),
            "http_errors": len(failures)}, indent=1))
        for s in run.steps:
            state = "NOT RUN" if s.get("not_run") else "PASS" if s["ok"] else "FAIL"
            print(f"{state}  {s['step']}  ({s.get('seconds', 0)}s)" + (f"  {s['detail']}" if s.get("not_run") else ""))
        if head:
            print(f"erasure head (keep it out of band): {head}")
        verdict = "PASS" if ok and fresh else "DIAGNOSTIC" if ok else "FAIL"
        print(f"{verdict} ({mode}): run directory {out}")
    return 0 if ok and fresh else 2 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
