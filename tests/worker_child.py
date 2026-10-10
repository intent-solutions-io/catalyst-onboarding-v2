"""A worker subprocess with one fault seam, for TEST-S1-07(c): `python -m tests.worker_child <marker>`.

It runs the real run_worker command; after the sink accepts a message it creates <marker> and hangs, so
the test can SIGKILL it at exactly that point (the message is in the sink, the result is not recorded)."""

import sys
import time
from pathlib import Path

import django

django.setup()

from django.core.management import call_command  # noqa: E402

from correspondence import verification  # noqa: E402


def hang(claim):
    Path(sys.argv[1]).touch()
    time.sleep(120)


verification._after_send = hang
call_command("run_worker")
