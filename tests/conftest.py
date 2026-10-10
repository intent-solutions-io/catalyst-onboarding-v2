"""Test-only network protection (TEST-S1-14), at Python level and nothing more.

An autouse fixture patches ``socket.socket.connect`` and ``connect_ex`` for the duration of each test
function, allowing only loopback, Unix sockets and the configured database host. It is a test aid, not
a firewall or sandbox. It does not cover:

- native libraries that open sockets themselves (libpq, used by psycopg's binary wheel);
- code that runs outside a test function (collection, imports, session-scoped fixtures);
- child processes (each subprocess is a fresh interpreter without the patch);
- other socket operations (UDP sendto, DNS resolution).

The container-level boundary is the explicit, synthetic environment the test service receives
(compose.yaml) and config.guards, which refuses provider credentials at start-up."""

import ipaddress
import os
import socket

import pytest

_real_connect = socket.socket.connect


def _allowed_hosts() -> set[str]:
    db_host = os.environ.get("CATALYST_DB_HOST", "")
    allowed = {"localhost", db_host}
    try:
        allowed.update(info[4][0] for info in socket.getaddrinfo(db_host, None))
    except OSError:
        pass
    return allowed


def _guarded_connect(self, address):
    if self.family == socket.AF_UNIX:
        return _real_connect(self, address)
    host = address[0]
    try:
        if ipaddress.ip_address(host).is_loopback:
            return _real_connect(self, address)
    except ValueError:
        pass
    if host in _allowed_hosts():
        return _real_connect(self, address)
    raise RuntimeError(f"network access blocked in tests: {host}")


def _guarded_connect_ex(self, address):
    _guarded_connect(self, address)  # raises for a blocked host; otherwise connected
    return 0


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)


# PASS means executed and passed. A skipped test, an expected failure (xfail) or an unexpected pass of
# an xfail-marked test (xpass) cannot satisfy a required case, so any of them fails the run (CI gate).
# Counted from the reports themselves, so it does not depend on the terminal reporter plugin.
_skipped = []


def pytest_runtest_logreport(report):
    if report.skipped or hasattr(report, "wasxfail"):
        _skipped.append(report.nodeid)


def pytest_collectreport(report):
    if report.skipped:
        _skipped.append(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    if _skipped and session.exitstatus == 0:
        session.exitstatus = 1
