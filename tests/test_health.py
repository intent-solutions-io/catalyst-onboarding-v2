"""6B.3 (026 sections 4 and 8; P6-D-12; TEST-P6-07, 32): liveness, readiness and the public-host guard."""

import logging

import pytest

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from config import health

PUBLIC = "catalyst.example.test"  # the test environment's public base URL host
LOCAL = {"HTTP_HOST": "localhost"}  # the proxy's local socket


@pytest.fixture(autouse=True)
def fresh_readiness():
    health.clear_cache()
    yield
    health.clear_cache()


def test_6b3_liveness_answers_ok_without_touching_the_database(db):
    with CaptureQueriesContext(connection) as queries:
        response = Client().get("/healthz", **LOCAL)
    assert (response.status_code, response.content) == (200, b"ok") and len(queries) == 0
    assert "no-store" in response["Cache-Control"] or "max-age=0" in response["Cache-Control"]


def test_6b3_readiness_is_a_fixed_token_with_no_version_or_detail(db):
    response = Client().get("/readyz", **LOCAL)
    assert (response.status_code, response.content) == (200, b"ready")
    # Only these headers: none names a version or a server. (The WSGI server's own Server header is added outside
    # Django; it is checked on the staging stack, TEST-P6-07, and is NOT RUN here.)
    assert {h.lower() for h in response.headers} <= {
        "content-type", "content-length", "cache-control", "expires", "x-frame-options", "x-content-type-options",
        "referrer-policy", "cross-origin-opener-policy", "content-security-policy", "vary"}


def test_6b3_readiness_refuses_pending_migrations_a_wrong_role_and_a_dead_database(db, monkeypatch, caplog):
    from django.db.migrations import executor as executor_module

    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(executor_module.MigrationExecutor, "migration_plan", lambda self, targets: [("pending", False)])
    assert (Client().get("/readyz", **LOCAL).status_code, health.readiness_problem()) == (503, "migrations_pending")
    health.clear_cache()
    monkeypatch.undo()
    monkeypatch.setattr(health.runtime, "role_problems", lambda cursor, kind, roles: ["connects as the owner"])
    health.clear_cache()
    response = Client().get("/readyz", **LOCAL)
    assert (response.status_code, response.content) == (503, b"not-ready")  # never the reason
    assert "wrong_database_role" in caplog.text
    monkeypatch.undo()

    class Down:
        def cursor(self):
            raise RuntimeError("database is down")
    monkeypatch.setattr(health, "connection", Down())
    assert health.readiness_problem() == "database_unavailable"
    assert "database is down" not in caplog.text  # the exception's message is never logged either


def test_6b3_readiness_runs_the_strict_web_role_check(db, monkeypatch):
    seen = {}
    real = health.runtime.role_problems

    def spy(cursor, kind, roles):
        seen["kind"] = kind
        return real(cursor, kind, roles)
    monkeypatch.setattr(health.runtime, "role_problems", spy)
    Client().get("/readyz", **LOCAL)
    assert seen == {"kind": "web"}  # this test process connects as the application role, so the check passes


def test_6b3_health_answers_only_on_the_local_hosts(db, settings):
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, PUBLIC, "staff.example.test", "other.example.test"]
    client = Client()
    for host in (PUBLIC, "staff.example.test", "other.example.test", "testserver"):
        for path in ("/healthz", "/readyz", "//healthz", "/./readyz", "/HEALTHZ"):
            assert client.get(path, HTTP_HOST=host).status_code == 404, (host, path)
    assert client.get("/healthz", HTTP_HOST="localhost.").status_code == 200  # a trailing dot is the same host
    assert client.get("/request-access/", HTTP_HOST=PUBLIC).status_code == 200  # applicant pages still answer


def test_6b3_staff_answer_only_on_the_staff_host_once_one_is_named(db, settings):
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, PUBLIC, "staff.example.test", "other.example.test"]
    settings.CATALYST_STAFF_HOST = "staff.example.test"
    client = Client()
    for host in (PUBLIC, "localhost", "other.example.test", "testserver"):
        for path in ("/staff/", "//staff/", "/./staff/", "/%73taff/", "/STAFF/p5/", "/admin/"):
            assert client.get(path, HTTP_HOST=host).status_code == 404, (host, path)
    assert client.get("/staff/", HTTP_HOST="staff.example.test").status_code in (200, 302)  # the login page
    settings.CATALYST_STAFF_HOST = ""  # the local environments without a staff host: any host but the public one
    assert client.get("/staff/", HTTP_HOST=PUBLIC).status_code == 404
    assert client.get("/staff/").status_code in (200, 302)


def test_6b3_a_bad_host_header_is_a_400_not_a_server_error(db):
    assert Client().get("/staff/", HTTP_HOST="evil.example.com").status_code == 400


def test_6b3_readiness_is_cached_briefly_so_probes_cannot_load_the_database(db, monkeypatch):
    calls = {"n": 0}
    real = health.readiness_problem

    def counted():
        calls["n"] += 1
        return real()
    monkeypatch.setattr(health, "readiness_problem", counted)
    for _ in range(5):
        assert Client().get("/readyz", **LOCAL).status_code == 200
    assert calls["n"] == 1
