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
from django.core.management.base import BaseCommand, CommandError
from django.db import InterfaceError, OperationalError, connections

from config import runtime
from workflow import heartbeat, ledger

logger = logging.getLogger("workflow.worker")


def select(registry: dict, only: str, exclude: str) -> dict:
    """The handlers this process may run. An unknown kind is an error, so a typo cannot silently run nothing."""
    wanted = {k.strip() for k in only.split(",") if k.strip()}
    unwanted = {k.strip() for k in exclude.split(",") if k.strip()}
    unknown = (wanted | unwanted) - set(registry)
    if unknown:
        raise CommandError(f"unknown action kinds: {', '.join(sorted(unknown))}")
    selected = {kind: h for kind, h in registry.items() if (not wanted or kind in wanted) and kind not in unwanted}
    if not selected:  # a process with nothing to run is a misconfiguration, never a quiet idle loop (PR #65 review)
        raise CommandError("no action kinds left to run")
    if settings.CATALYST_PROCESS_ROLE == "fetcher" and set(selected) != {"fetch_evidence"}:
        raise CommandError("the fetcher runs only fetch_evidence (--only fetch_evidence)")  # its role grants nothing else
    return selected


class Command(BaseCommand):
    help = "Run the pending-action worker: claim and run queued actions until stopped (or idle, with --exit-when-idle)."

    def add_arguments(self, parser):
        parser.add_argument("--exit-when-idle", action="store_true", help="stop when no action is claimable")
        # 6B.5 (026 section 5, P6-D-14): the fetcher runs only the evidence fetch; the worker runs everything else.
        parser.add_argument("--only", default="", help="comma-separated action kinds this process may run")
        parser.add_argument("--exclude", default="", help="comma-separated action kinds this process never runs")

    def handle(self, *args, exit_when_idle=False, only="", exclude="", **options):
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
            registry = select(ledger.handlers(), only, exclude)
            self.stdout.write("worker started")
            self.stdout.flush()
            while not stop.is_set():
                heartbeat.beat(settings.CATALYST_WORKER_HEARTBEAT_FILE)  # 6B.4: alive, even while the database is down
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
