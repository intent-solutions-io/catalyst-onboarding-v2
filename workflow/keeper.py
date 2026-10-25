"""Lease keeping for a handler's long outside call (oc4.9; 018 section 6; ledger rule 3).

The ledger does not renew a lease while a handler runs, so a call longer than the lease could be reclaimed and run a
second time while the first is still in flight. A model call is the one such call today. `LeaseKeeper` closes that gap
for the duration of a `with` block, within a hard bound:

- **Heartbeat.** A daemon thread renews the lease (`ledger.fence(beat=False)`, in its own short transaction on its own
  database connection) every third of the lease. A renewal that finds the lease gone, or that fails at all, marks the
  keeper `lost`: the keeper never assumes it still holds a lease it could not confirm.
- **A hard bound.** After `max_seconds` (by default one model attempt: two requests at the request timeout, plus a
  margin) the thread stops renewing and marks the keeper `lost`. A call that hangs past every timeout, for example
  in code that cannot be cancelled, therefore lets its lease run out and the action becomes reclaimable; it is never
  kept alive forever.
- **Not a liveness signal.** The renewals never write the worker-alive file (6B.4): that file must say the worker's
  own thread is making progress. `beat()` writes it, and the model layer calls it from the calling side after each
  request completes, so a long call that is progressing keeps the dead-man timer honest and a stuck one does not.
- **Fence before each request.** `fence()` renews the lease now (without a beat) and raises `LeaseLost` when the lease
  is gone, the bound is reached or the heartbeat has lost it. The model layer calls it before every request, the
  repair included.

`current()` returns the keeper active in this context, so the model layer finds it without a new argument on every
interface between the handler and the call (the reply interpreter's P2 protocol is unchanged). Subject-generic, like
the ledger: no domain import.
"""

import contextvars
import logging
import threading
import time

from django.conf import settings
from django.db import connections, transaction

from . import heartbeat, ledger

logger = logging.getLogger(__name__)
_current = contextvars.ContextVar("catalyst_lease_keeper", default=None)
REQUESTS_PER_ATTEMPT = 2  # the call and the one repair (assessments.approval.REQUESTS_PER_ATTEMPT)


def current():
    """The keeper of the `with` block this code runs in, or None."""
    return _current.get()


def attempt_bound() -> float:
    """The default hard bound: one model attempt at the request timeout, plus a third of the lease as the margin."""
    return (REQUESTS_PER_ATTEMPT * float(settings.CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS)
            + settings.CATALYST_WORKER_LEASE_SECONDS / 3)


class LeaseKeeper:
    def __init__(self, claim, interval: float | None = None, max_seconds: float | None = None):
        self.claim = claim
        self.interval = interval if interval is not None else max(0.05, settings.CATALYST_WORKER_LEASE_SECONDS / 3)
        self.max_seconds = max_seconds if max_seconds is not None else attempt_bound()
        self.lost = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._token = None
        self._owner = None
        self._deadline = None
        self.renewals = 0  # heartbeat renewals that succeeded (evidence for tests and logs)

    def _expired(self) -> bool:
        return self._deadline is not None and time.monotonic() >= self._deadline

    def _renew(self) -> None:
        with transaction.atomic():
            ledger.fence(self.claim, beat=False)

    def fence(self) -> None:
        """Renew the lease now or raise `ledger.LeaseLost`. Safe from any thread, before or inside the block: a thread
        other than the one that entered the block closes the database connection it opened."""
        owner = self._owner is not None and threading.current_thread() is self._owner
        try:
            if self._expired():
                self.lost.set()
            if self.lost.is_set():
                raise ledger.LeaseLost
            try:
                self._renew()
            except ledger.LeaseLost:
                self.lost.set()
                raise
        finally:
            if not owner:
                connections.close_all()

    def beat(self) -> None:
        """The worker-alive beat, from the calling side after a request completes (6B.4)."""
        heartbeat.beat(settings.CATALYST_WORKER_HEARTBEAT_FILE)

    def _beat(self) -> None:
        try:
            while not self._stop.wait(self.interval):
                if self._expired():
                    self.lost.set()
                    logger.warning("action %s (%s): the lease keeper reached its bound (%.0f s); renewals stop",
                                   self.claim.id, self.claim.kind, self.max_seconds)
                    return
                try:
                    self._renew()
                    self.renewals += 1
                except Exception as exc:  # LeaseLost, or a database failure: either way the lease is not confirmed
                    self.lost.set()
                    logger.warning("action %s (%s): lease not renewed (%s); no further request will be made",
                                   self.claim.id, self.claim.kind, type(exc).__name__)
                    return
        finally:
            connections.close_all()

    def __enter__(self):
        self._owner = threading.current_thread()
        self._deadline = time.monotonic() + self.max_seconds
        self._token = _current.set(self)
        self._thread = threading.Thread(target=self._beat, name=f"lease-keeper-{self.claim.id}", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        # A renewal in progress finishes within the database's own timeouts; never wait on it without a bound.
        self._thread.join(timeout=self.interval + 10)
        if self._thread.is_alive():
            logger.warning("action %s (%s): the lease keeper thread did not stop in time", self.claim.id, self.claim.kind)
        _current.reset(self._token)
        return False
