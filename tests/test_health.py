"""6B.3 (026 sections 4 and 8; P6-D-12; TEST-P6-07, 32): liveness, readiness and the public-host guard."""

import logging

from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from config import health

PUBLIC = "catalyst.example.test"  # the test environment's public base URL host


def test_6b3_liveness_answers_ok_without_touching_the_database(db):
    with CaptureQueriesContext(connection) as queries:
        response = Client().get("/healthz")
    assert (response.status_code, response.content) == (200, b"ok") and len(queries) == 0
    assert "no-store" in response["Cache-Control"] or "max-age=0" in response["Cache-Control"]


def test_6b3_readiness_is_a_fixed_token_with_no_version_or_detail(db):
    response = Client().get("/readyz")
    assert (response.status_code, response.content) == (200, b"ready")
    for header in ("Server", "X-Version", "X-Commit"):
        assert header not in response


def test_6b3_readiness_refuses_pending_migrations_a_wrong_role_and_a_dead_database(db, monkeypatch, caplog):
    from django.db.migrations import executor as executor_module

    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(executor_module.MigrationExecutor, "migration_plan", lambda self, targets: [("pending", False)])
    assert (Client().get("/readyz").status_code, health.readiness_problem()) == (503, "migrations_pending")
    monkeypatch.undo()
    monkeypatch.setattr(health.runtime, "role_problems", lambda cursor, kind, roles: ["connects as the owner"])
    response = Client().get("/readyz")
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
    Client().get("/readyz")
    assert seen == {"kind": "web"}  # this test process connects as the application role, so the check passes


def test_6b3_the_public_host_never_serves_staff_admin_or_health(db, settings):
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, PUBLIC]  # as in a deployment, the public host is allowed
    client = Client()
    for path in ("/healthz", "/readyz", "/staff/", "/staff/p5/", "/STAFF/", "/admin/", "/Healthz"):
        response = client.get(path, HTTP_HOST=PUBLIC)
        assert response.status_code == 404, path
    assert client.get("/healthz", HTTP_HOST=f"{PUBLIC}.").status_code == 404  # a trailing dot is the same host
    assert client.get("/request-access/", HTTP_HOST=PUBLIC).status_code == 200  # applicant pages still answer
    assert client.get("/healthz").status_code == 200  # the local socket's own host name is unaffected
