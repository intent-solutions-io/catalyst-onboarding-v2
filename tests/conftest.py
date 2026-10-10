"""Test-wide network guard (TEST-S1-14): Python-level sockets may reach only loopback, Unix sockets and
the configured database host. This covers every Python client (smtplib, HTTP libraries). It does not
see libpq, which psycopg's binary wheel uses for database connections; the database host comes from
the CATALYST_DB_* settings, which config.guards keeps PostgreSQL-only."""

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


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
