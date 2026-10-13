"""A worker subprocess with one fault seam, for TEST-P2-19: `python -m tests.worker_child_collect <marker>`.

It runs the real run_worker command. When the collector fetches the body of the second UID (the first
message is already committed), it creates <marker> and hangs, so the test can SIGKILL it mid-message."""

import sys
import time
from pathlib import Path

import django

django.setup()

from django.core.management import call_command  # noqa: E402

from correspondence import imap  # noqa: E402

real_fetch = imap.MailboxClient.fetch


def fetch(self, uid):
    if uid >= 2:
        Path(sys.argv[1]).touch()
        time.sleep(120)
    return real_fetch(self, uid)


imap.MailboxClient.fetch = fetch
call_command("run_worker")
