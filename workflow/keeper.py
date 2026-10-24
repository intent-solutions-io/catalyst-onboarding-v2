"""Lease keeping for a handler's long outside call (oc4.9; 018 section 6; ledger rule 3).

The ledger does not renew a lease while a handler runs, so a call longer than the lease could be reclaimed and run a
second time while the first is still in flight. A model call is the one such call today. `LeaseKeeper` closes that gap
for the duration of a `with` block:

- **Heartbeat.** A daemon thread renews the lease (`ledger.fence`, in its own short transaction on its own database
  connection) every third of the lease. A renewal that finds the lease gone, or that fails at all, marks the keeper
  `lost`: the keeper never assumes it still holds a lease it could not confirm.
- **Fence before each request.** `fence()` renews the lease now, in the calling thread, and raises `LeaseLost` when the
  lease is gone or the heartbeat has lost it. The model layer calls it before every request, the repair included, so
  a worker that lost its claim stops before it spends another request.

`current()` returns the keeper active in this context, so the model layer finds it without a new argument on every
interface between the handler and the call (the reply interpreter's P2 protocol is unchanged). Subject-generic, like
the ledger: no domain import.
"""

import contextvars
import logging
import threading

from django.conf import settings
from django.db import connections, transaction

from . import ledger

logger = logging.getLogger(__name__)
_current = contextvars.ContextVar("catalyst_lease_keeper", default=None)


def current():
    """The keeper of the `with` block this code runs in, or None."""
    return _current.get()


class LeaseKeeper:
    def __init__(self, claim, interval: float | None = None):
        self.claim = claim
        self.interval = interval if interval is not None else max(0.05, settings.CATALYST_WORKER_LEASE_SECONDS / 3)
        self.lost = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._token = None
        self.renewals = 0  # heartbeat renewals that succeeded (evidence for tests and logs)

    def _renew(self) -> None:
        with transaction.atomic():
            ledger.fence(self.claim)

    def fence(self) -> None:
        """Renew the lease now or raise `ledger.LeaseLost`. Safe from any thread: a thread other than the one that
        entered the block closes the database connection it opened."""
        owner = threading.current_thread() is self._owner
        try:
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

    def _beat(self) -> None:
        try:
            while not self._stop.wait(self.interval):
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
        self._token = _current.set(self)
        self._thread = threading.Thread(target=self._beat, name=f"lease-keeper-{self.claim.id}", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()
        _current.reset(self._token)
        return False
