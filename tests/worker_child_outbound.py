"""A worker subprocess with one fault seam, for the 2B.1 real-process recovery test (TEST-P2-27, owner
closeout of PR #21): `python -m tests.worker_child_outbound <marker>`.

It runs the real run_worker command. After the SMTP exchange of a `send_message` action has finished (the
synthetic server has accepted the complete message) and before the result is recorded, it creates
<marker> and hangs, so the test can SIGKILL it at exactly that point."""

import sys
import time
from pathlib import Path

import django

django.setup()

from django.core.management import call_command  # noqa: E402

from correspondence import outbound  # noqa: E402


def hang(claim, result):
    Path(sys.argv[1]).write_text(result.outcome)
    time.sleep(120)


outbound._after_send = hang
call_command("run_worker")
