"""The live browser canary (9kg.87): one real applicant journey against the deployed site, recorded for review.

    sops exec-env <canary secrets> 'python3 scripts/live_canary.py --public-url https://<v2 host> \
        --invite "ssh <host alias> sudo /usr/local/sbin/catalyst-v2-manage" \
        --retention "ssh <host alias> sudo /usr/local/sbin/catalyst-v2-erase" --out <private dir>'

Steps, each timed and screenshotted: invite the canary address (CANARY_ADDRESS, by default the owner's own test inbox
CANARY_MAIL_USER; a sub-address such as `inbox+canary-2@` of that inbox is a distinct applicant identity delivered to
the same inbox) through the real `catalyst_invite`; open the public request form in headless Chromium and submit it
from that address; read this run's verification mail from the inbox by IMAP (addressed to the canary address, dated
after the run began, with a link on the exact public origin); open the link twice and check that a GET alone does not
confirm; confirm with the form's POST; assert the confirmed page; open the link once more and check that it cannot
confirm again. Then the canary person is erased with `catalyst_erase` through the `--retention` command (one that
runs manage.py as the retention login with the erasure key; the invitation's reference names the person and covers
every record of that address) and the erasure record is checked with `catalyst_erasure_record --expect-head`. Without
`--retention` the erasure is reported NOT RUN and the run fails: a canary person left in production is a failed run.
`--mail-window-minutes` accepts an earlier run's mail (a reused link) for diagnosis; such a run is reported as
DIAGNOSTIC and never as a fresh full-journey PASS (exit 2).

The run directory (outside any repository, mode 0700) holds the Playwright trace (`trace.zip`: actions and network
timeline, no DOM snapshots and no screencast; replay with `playwright show-trace`), the step screenshots with the
address masked, the browser console messages, page errors and failed requests, and `run.json` with every step's
outcome and timing plus the erasure head the owner keeps out of band. The verification mail is deleted from the inbox
afterwards: it holds a one-time link. No text record carries the canary's address, the link or its token: both are
redacted before anything is written (the trace's text entries are rewritten in place), and the screenshots mask the
address. Every external call is bounded, and the reports are written even when cleanup fails.

Exit 0 when every step passed, including the erasure; 1 otherwise.
"""

import argparse
import email
import imaplib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

TOKEN = re.compile(r"(/(?:confirm|setup|withdraw)/)[^/\s\"'\\]+")
COMMAND_TIMEOUT = 120  # seconds for one invitation, erasure or record command
MAIL_TIMEOUT = 300  # seconds to wait for the verification mail
PRIVATE: list[str] = []  # the canary's login and address, set once in main(); redact() replaces them everywhere


def redact(text: str) -> str:
    """The text with every link token and every occurrence of the canary's login or address replaced."""
    text = TOKEN.sub(r"\1REDACTED", text or "")
    for value in PRIVATE:
        if value:
            text = text.replace(value, "<canary address>")
    return text


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
        self.steps.append({"step": name, "ok": False, "not_run": True, "detail": why})


def describe(exc: Exception) -> str:
    """An exception as text that never carries the failed command (which can hold the address): class, exit code and
    the last line of stderr for a command failure; class and message otherwise."""
    if isinstance(exc, subprocess.CalledProcessError):
        tail = (exc.stderr or "").strip().splitlines()[-1:] or [""]
        return f"command failed (exit {exc.returncode}): {tail[0]}"
    if isinstance(exc, subprocess.TimeoutExpired):
        return f"command did not finish within {exc.timeout}s"
    return f"{type(exc).__name__}: {exc}"


def run_json(command: list[str]) -> dict:
    """Run a command that prints one JSON object (possibly after other lines) and return it, bounded in time."""
    done = subprocess.run(command, capture_output=True, text=True, check=True, timeout=COMMAND_TIMEOUT)
    for line in reversed(done.stdout.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise ValueError("the command printed no JSON object")


def wait_for_mail(user, password, host, since, origin, address=None, timeout=MAIL_TIMEOUT):
    """The newest verification mail addressed to `address` (the login `user` by default), received after `since`,
    whose link is on the exact `origin`: (link, IMAP UID). A matching subject alone never qualifies a message.

    Polled every 10 seconds with read-only fetches (BODY.PEEK); every connection and command is bounded by the time
    left."""
    address = address or user
    link = re.compile(re.escape(origin) + r"/confirm/[^\s/]+/")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(5, deadline - time.monotonic())
        box = imaplib.IMAP4_SSL(host, 993, timeout=remaining)
        try:
            box.login(user, password)
            box.select("INBOX")
            _, found = box.uid("search", None, '(SUBJECT "Confirm your email address")')
            for uid in reversed(found[0].split()):
                _, data = box.uid("fetch", uid, "(BODY.PEEK[])")
                message = email.message_from_bytes(data[0][1])
                if address.casefold() not in (message.get("To") or "").casefold():
                    continue
                sent = parsedate_to_datetime(message["Date"])
                if sent.tzinfo is None:
                    sent = sent.replace(tzinfo=timezone.utc)
                if sent < since:
                    continue
                body = message.get_payload(decode=True) if not message.is_multipart() else \
                    next(p for p in message.walk() if p.get_content_type() == "text/plain").get_payload(decode=True)
                match = link.search(body.decode(errors="replace"))
                if match:
                    return match.group(0), uid.decode()
        finally:
            box.logout()
        time.sleep(10)
    raise TimeoutError("no verification mail within the timeout")


def delete_mail(user, password, host, uid):
    """Delete the one message `uid` (UID EXPUNGE where the server has it, so nothing else marked deleted goes)."""
    box = imaplib.IMAP4_SSL(host, 993, timeout=60)
    try:
        box.login(user, password)
        box.select("INBOX")
        box.uid("store", uid, "+FLAGS", "\\Deleted")
        try:
            box.uid("expunge", uid)
        except imaplib.IMAP4.error:
            box.expunge()
    finally:
        box.logout()


def scrub_trace(path: Path):
    """Rewrite the trace's text entries (actions, network, console) through redact(); binary entries are kept."""
    if not path.exists():
        return
    scrubbed = path.with_suffix(".scrubbed")
    with zipfile.ZipFile(path) as src, zipfile.ZipFile(scrubbed, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            data = src.read(item)
            if item.filename.endswith((".trace", ".network", ".json", ".txt", ".stacks")):
                data = redact(data.decode("utf-8", errors="replace")).encode()
            dst.writestr(item, data)
    scrubbed.replace(path)


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
    address = os.environ.get("CANARY_ADDRESS", "").strip() or user
    PRIVATE[:] = sorted({user, address}, key=len, reverse=True)
    origin = args.public_url.rstrip("/")
    fresh = args.mail_window_minutes == 0
    out = args.out / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, mode=0o700)
    run = Run(out)
    console, failures = [], []
    since = datetime.now(timezone.utc).replace(microsecond=0)
    journey_ok = erased = False
    head = None
    invited = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("CANARY_CHROMIUM") or None)
            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
            context.tracing.start(screenshots=False, snapshots=False, sources=False)
            page = context.new_page()
            page.on("console", lambda m: console.append({"type": m.type, "text": redact(m.text)}))
            page.on("pageerror", lambda e: console.append({"type": "pageerror", "text": redact(str(e))}))
            page.on("requestfailed", lambda r: failures.append({"url": redact(r.url), "failure": r.failure}))
            page.on("response", lambda r: failures.append({"url": redact(r.url), "status": r.status})
                    if r.status >= 400 else None)

            def shot(name):
                """A full-page screenshot with every element that shows the address masked."""
                masks = [page.locator("#id_email"), page.get_by_text(address, exact=True)]
                page.screenshot(path=str(out / f"{len(run.steps):02d}-{name}.png"), full_page=True, mask=masks)

            mail_uid = None
            try:
                invited = run.step("invite", lambda: run_json(
                    # no spaces in any argument: the command may run through ssh, where the remote shell re-splits
                    [*shlex.split(args.invite), "catalyst_invite", address, "--issued-by", "live-canary", "--days",
                     "1", "--note", "live-canary"])["invitation"])
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
                    shot("confirm")
                run.step("open the link: a GET alone does not confirm", open_link)

                def confirm():
                    page.get_by_role("button", name="Confirm").click()
                    expect(page.locator("h1")).to_have_text("Email address confirmed")
                    shot("confirmed")
                run.step("confirm", confirm)

                def once_only():
                    page.goto(link)
                    expect(page.locator("h1")).not_to_have_text("Confirm your email address")
                    shot("link-after-confirmation")
                    return page.locator("h1").inner_text()
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
                        pass
        scrub_trace(out / "trace.zip")
        if invited is None:
            run.not_run("erase the canary person", "nothing was invited")
        elif not args.retention:
            run.not_run("erase the canary person", "no --retention command (the retention login and the erasure key)")
        else:
            try:
                outcome = run.step("erase the canary person", lambda: run_json(
                    [*shlex.split(args.retention), "catalyst_erase", "--subject", invited,
                     "--authority", args.erase_authority, "--reason", args.erase_reason]))
                head = outcome.get("journal_head")
                run.steps[-1]["detail"] = json.dumps({k: outcome.get(k) for k in
                                                      ("status", "changed", "handoffs", "retained", "journal_head")})
                run.step("verify the erasure record", lambda: json.dumps(run_json(
                    [*shlex.split(args.retention), "catalyst_erasure_record", "--expect-head", str(head)])))
                erased = True
            except Exception:
                pass
    finally:
        ok = journey_ok and erased
        mode = "fresh journey" if fresh else f"link-reuse diagnostic (mail window {args.mail_window_minutes} min)"
        (out / "console.json").write_text(json.dumps(console, indent=1))
        (out / "requests.json").write_text(json.dumps(failures, indent=1))
        (out / "run.json").write_text(json.dumps({
            "ok": ok and fresh, "mode": mode, "journey_ok": journey_ok, "erased": erased, "invitation": invited,
            "erasure_head": head, "public_url": origin, "started_at": since.isoformat(),
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
