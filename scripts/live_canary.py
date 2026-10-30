"""The live browser canary (9kg.87): one real applicant journey against the deployed site, recorded for review.

    sops exec-env <canary secrets> 'python3 scripts/live_canary.py --public-url https://<v2 host> \
        --invite "ssh <host alias> sudo /usr/local/sbin/catalyst-v2-manage catalyst_invite" --out <private dir>'

Steps, each timed and screenshotted: invite the canary mailbox (the owner's own test inbox, CANARY_MAIL_USER) through
the real `catalyst_invite`; open the public request form in headless Chromium and submit it from that address; read
the real verification mail from the inbox by IMAP; open the link, check the answers shown, confirm; assert the
confirmed page. The run directory (outside any repository) holds the Playwright trace (`trace.zip`, replay with
`playwright show-trace`), the screenshots, the browser console messages, page errors and failed requests, and
`run.json` with every step's outcome and timing. The verification mail is deleted from the inbox afterwards: it holds
a one-time link. Nothing printed or written carries the canary's address, the link or its token (the link's token
segment is redacted before anything is recorded). The canary person is erased afterwards with `catalyst_erase` by the
retention login, as the first production erasure.

Exit 0 when every step passed, 1 otherwise.
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
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

LINK = re.compile(r"https://\S+/confirm/[^\s/]+/")
TOKEN = re.compile(r"(/(?:confirm|setup|withdraw)/)[^/\s\"']+")


def redact(text: str) -> str:
    return TOKEN.sub(r"\1REDACTED", text or "")


class Run:
    def __init__(self, out: Path):
        self.out, self.steps, self.started = out, [], time.monotonic()

    def step(self, name, fn):
        began = time.monotonic()
        try:
            detail = fn()
            self.steps.append({"step": name, "ok": True, "seconds": round(time.monotonic() - began, 2),
                               "detail": redact(str(detail or ""))})
            return detail
        except Exception as exc:  # recorded, then the run stops
            self.steps.append({"step": name, "ok": False, "seconds": round(time.monotonic() - began, 2),
                               "error": redact(f"{type(exc).__name__}: {exc}")[:500]})
            raise


def wait_for_mail(user, password, host, since, timeout=300):
    """The newest verification mail received after `since`: (link, IMAP id), polled every 10 seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        box = imaplib.IMAP4_SSL(host, 993)
        try:
            box.login(user, password)
            box.select("INBOX")
            _, found = box.search(None, '(SUBJECT "Confirm your email address")')
            for num in reversed(found[0].split()):
                _, data = box.fetch(num, "(RFC822)")
                message = email.message_from_bytes(data[0][1])
                sent = parsedate_to_datetime(message["Date"])
                if sent.tzinfo is None:
                    sent = sent.replace(tzinfo=timezone.utc)
                if sent < since:
                    continue
                body = message.get_payload(decode=True) if not message.is_multipart() else \
                    next(p for p in message.walk() if p.get_content_type() == "text/plain").get_payload(decode=True)
                match = LINK.search(body.decode(errors="replace"))
                if match:
                    return match.group(0), num.decode()
        finally:
            box.logout()
        time.sleep(10)
    raise TimeoutError("no verification mail within the timeout")


def delete_mail(user, password, host, num):
    box = imaplib.IMAP4_SSL(host, 993)
    try:
        box.login(user, password)
        box.select("INBOX")
        box.store(num, "+FLAGS", "\\Deleted")
        box.expunge()
    finally:
        box.logout()


def main() -> int:
    from playwright.sync_api import expect, sync_playwright

    parser = argparse.ArgumentParser()
    parser.add_argument("--public-url", required=True)
    parser.add_argument("--invite", required=True, help="the command that runs catalyst_invite on the host")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--imap-host", default="sunfire.mxrouting.net")
    parser.add_argument("--mail-window-minutes", type=int, default=0,
                        help="also accept a verification mail this many minutes older than the run (a reused link)")
    args = parser.parse_args()
    user, password = os.environ["CANARY_MAIL_USER"], os.environ["CANARY_MAIL_PASSWORD"]
    out = args.out / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, mode=0o700)
    run = Run(out)
    console, failures = [], []
    since = datetime.now(timezone.utc).replace(microsecond=0)
    ok = False
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CANARY_CHROMIUM") or None)
        context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        context.tracing.start(screenshots=True, snapshots=True, sources=False)
        page = context.new_page()
        page.on("console", lambda m: console.append({"type": m.type, "text": redact(m.text)}))
        page.on("pageerror", lambda e: console.append({"type": "pageerror", "text": redact(str(e))}))
        page.on("requestfailed", lambda r: failures.append({"url": redact(r.url), "failure": r.failure}))
        page.on("response", lambda r: failures.append({"url": redact(r.url), "status": r.status})
                if r.status >= 400 else None)
        shot = lambda name: page.screenshot(path=str(out / f"{len(run.steps):02d}-{name}.png"), full_page=True)  # noqa: E731
        mail_id = None
        try:
            invited = run.step("invite", lambda: json.loads(subprocess.run(
                [*shlex.split(args.invite), user, "--issued-by", "live canary", "--days", "1", "--note", "live canary"],
                capture_output=True, text=True, check=True).stdout)["invitation"])
            run.step("open the request form", lambda: (page.goto(f"{args.public_url}/request-access/"),
                                                       expect(page.locator("h1")).to_have_text("Request access"),
                                                       shot("form")))
            run.step("data notice shown", lambda: expect(page.locator("#data-notice")).to_contain_text(
                "pseudonymous record"))

            def submit():
                page.locator("#id_name").fill("Live Canary")
                page.locator("#id_email").fill(user)
                page.locator("#id_reason").fill("Live canary check of the deployed service.")
                shot("filled")
                page.get_by_role("button", name="Send request").click()
                expect(page.locator("h1")).to_have_text("Request received")
                shot("received")
            run.step("submit the form", submit)
            link, mail_id = run.step("verification mail arrives", lambda: wait_for_mail(user, password, args.imap_host,
                                                                                         since - timedelta(minutes=args.mail_window_minutes)))

            def confirm():
                page.goto(link)
                expect(page.locator("h1")).to_have_text("Confirm your email address")
                expect(page.locator("dl")).to_contain_text("Live Canary")
                shot("confirm")
                page.get_by_role("button", name="Confirm").click()
                expect(page.locator("h1")).to_have_text("Email address confirmed")
                shot("confirmed")
            run.step("open the link and confirm", confirm)
            ok = True
            run.steps.append({"step": "invitation reference", "ok": True, "detail": invited})
        except Exception:
            try:
                shot("failure")
            except Exception:
                pass
        finally:
            context.tracing.stop(path=str(out / "trace.zip"))
            browser.close()
            if mail_id is not None:
                delete_mail(user, password, args.imap_host, mail_id)
    (out / "console.json").write_text(json.dumps(console, indent=1))
    (out / "requests.json").write_text(json.dumps(failures, indent=1))
    (out / "run.json").write_text(json.dumps({"ok": ok, "public_url": args.public_url, "started_at": since.isoformat(),
                                              "seconds": round(time.monotonic() - run.started, 1),
                                              "steps": run.steps, "console_errors": sum(
                                                  1 for c in console if c["type"] in ("error", "pageerror")),
                                              "http_errors": len(failures)}, indent=1))
    for s in run.steps:
        print(f"{'PASS' if s['ok'] else 'FAIL'}  {s['step']}  ({s.get('seconds', 0)}s)")
    print(f"{'PASS' if ok else 'FAIL'}: run directory {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
