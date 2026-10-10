"""The worker (ADR-03, D-16; 005 S1.4): one management command running the claim loop.

It declares itself a worker process before touching the database, whatever CATALYST_PROCESS says, so the
connection-time role check (config/runtime.py, ADR-14) refuses any login but the application role. A
refused connection stops the worker with an error; it is not retried. After a database error the loop
closes its connections and polls again (rule 7); between idle polls it holds no connection. SIGTERM or
SIGINT stops it after the current action.
"""

import logging
import signal
import threading

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import InterfaceError, OperationalError, connections

from config import runtime
from workflow import ledger

logger = logging.getLogger("workflow.worker")


class Command(BaseCommand):
    help = "Run the pending-action worker (local mail sink only in this slice)."

    def add_arguments(self, parser):
        parser.add_argument("--exit-when-idle", action="store_true", help="stop when no action is claimable")

    def handle(self, *args, exit_when_idle=False, **options):
        runtime.declare_process("worker")
        connections.close_all()  # nothing opened before the declaration is reused unchecked
        stop = threading.Event()
        restore = {}
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                restore[sig] = signal.signal(sig, lambda *_: stop.set())
        processed = 0
        poll = settings.CATALYST_WORKER_POLL_SECONDS
        try:
            registry = ledger.handlers()
            self.stdout.write("worker started")
            self.stdout.flush()
            while not stop.is_set():
                try:
                    worked = ledger.run_one(registry)
                except (OperationalError, InterfaceError) as exc:
                    logger.warning("worker: database unavailable (%s); reconnecting", type(exc).__name__)
                    connections.close_all()
                    stop.wait(poll)
                    continue
                if worked:
                    processed += 1
                    continue
                if exit_when_idle:
                    break
                connections.close_all()
                stop.wait(poll)
        finally:
            connections.close_all()
            for sig, handler in restore.items():
                signal.signal(sig, handler)
        self.stdout.write(f"worker stopped after {processed} actions")
