"""Liveness and readiness (026 sections 4 and 7; 6B.3; P6-D-12).

- `/healthz` answers that the process is up. It makes no database call.
- `/readyz` answers that the process may take traffic: its database login is the application role (ADR-14, the
  same check every web connection gets) and every migration is applied.

Each answers with a fixed token and nothing else: never a version, commit, configuration or reason (`003`: health
"never returns version, configuration or dependency detail"). The reason for a refusal goes to the log as a
short code. Both are reached only through the proxy's local socket: `HostGuard` refuses them, the staff screens
and the admin on the public host name.
"""

import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.db import connection
from django.http import HttpResponse, HttpResponseNotFound
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from config import runtime

logger = logging.getLogger(__name__)
READY, NOT_READY = "ready", "not-ready"


def _text(body: str, status: int = 200) -> HttpResponse:
    return HttpResponse(body, status=status, content_type="text/plain; charset=utf-8")


@never_cache
@require_GET
def healthz(request):
    return _text("ok")


def readiness_problem() -> str:
    """A short code for the first thing that makes this process unready, or "" when it is ready."""
    from django.db.migrations.executor import MigrationExecutor

    try:
        with connection.cursor() as cursor:
            if runtime.role_problems(cursor, "web", settings.CATALYST_DB_ROLES):
                return "wrong_database_role"
        executor = MigrationExecutor(connection)
        if executor.migration_plan(executor.loader.graph.leaf_nodes()):
            return "migrations_pending"
    except Exception as exc:  # any database failure is "not ready"; the code is logged, never returned
        logger.warning("readiness check failed: %s", type(exc).__name__)
        return "database_unavailable"
    return ""


@never_cache
@require_GET
def readyz(request):
    problem = readiness_problem()
    if problem:
        logger.warning("not ready: %s", problem)
        return _text(NOT_READY, status=503)
    return _text(READY)


PUBLIC_DENIED_PREFIXES = ("/staff/", "/staff", "/admin", "/healthz", "/readyz")


class HostGuard:
    """Refuses staff, admin and health paths on the public host name, independently of the proxy (026 section 8,
    TEST-P6-32). Staff use their own host; health is read through the local socket."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.public_host = (urlsplit(settings.CATALYST_PUBLIC_BASE_URL).hostname or "").lower()

    def __call__(self, request):
        host = request.get_host().split(":", 1)[0].lower().rstrip(".")
        if host == self.public_host and request.path.lower().startswith(PUBLIC_DENIED_PREFIXES):
            return HttpResponseNotFound("Not found", content_type="text/plain; charset=utf-8")
        return self.get_response(request)
