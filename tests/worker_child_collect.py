"""A worker subprocess with one fault seam, for TEST-P2-19: `python -m tests.worker_child_collect <marker>`.

It runs the real run_worker command. Inside the per-message transaction for the second UID, after the message,
its location and the cursor advance were written and before the lease fence and the commit, it creates <marker>
and hangs, so the test can SIGKILL it with the transaction open (the first message is already committed)."""

import sys
import time
from pathlib import Path

import django

django.setup()

from django.core.management import call_command  # noqa: E402

from correspondence import inbound  # noqa: E402

real_ingest = inbound.ingest


def ingest(cursor_id, validity, uid, *args, **kwargs):
    result = real_ingest(cursor_id, validity, uid, *args, **kwargs)
    if uid >= 2:
        Path(sys.argv[1]).touch()
        time.sleep(120)
    return result


inbound.ingest = ingest
call_command("run_worker")
