"""The worker's heartbeat (026 section 7; 6B.4): a file the worker rewrites on every loop, so a host timer can tell
a live worker from a dead or wedged one without a database (and so a database outage is not mistaken for a dead
worker). Configured by CATALYST_WORKER_HEARTBEAT_FILE; empty means no heartbeat (test and development)."""

import os
import time


def beat(path: str) -> None:
    """Write the current time atomically. Never raises: a full disk must not stop the worker; a stale heartbeat
    then raises the alert instead."""
    if not path:
        return
    try:
        temporary = f"{path}.tmp"
        with open(temporary, "w", encoding="ascii") as handle:
            handle.write(f"{time.time():.0f}\n")
        os.replace(temporary, path)
    except OSError:
        pass


def age_seconds(path: str) -> float | None:
    """Seconds since the last beat, or None when there is no heartbeat file."""
    try:
        with open(path, encoding="ascii") as handle:
            return max(0.0, time.time() - float(handle.read().strip()))
    except (OSError, ValueError):
        return None
