"""Liveness and readiness (026 sections 4 and 7; 6B.3; P6-D-12).

- `/healthz` answers that the process is up. It makes no database call.
- `/readyz` answers that the process may take traffic: its database login is the application role (ADR-14, the
  same check every web connection gets) and every migration is applied.

Each answers with a fixed token and nothing else: never a version, commit, configuration or reason (`003`: health
"never returns version, configuration or dependency detail"). The reason for a refusal goes to the log as a
short code. Both are reached only through the proxy's local socket: `HostGuard` serves them only on the local host
names, and the staff screens and the admin only on the staff host.
"""

import logging
import posixpath
import re
import threading
import time
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
    if settings.CATALYST_ENV not in ("test", "development"):
        from workflow import journal

        problem = journal.directory_problem(write=True)  # 9kg.33: a web process that cannot journal takes no traffic
        if problem:
            return f"effect_journal_{problem}"
    return ""


_CACHE = {"at": None, "problem": ""}
_CACHE_LOCK = threading.Lock()
CACHE_SECONDS = 5


def cached_readiness_problem() -> str:
    """The readiness answer, reused for a few seconds, so repeated probes cannot turn into a database load
    (PR #62 review)."""
    with _CACHE_LOCK:
        now = time.monotonic()
        if _CACHE["at"] is None or now - _CACHE["at"] >= CACHE_SECONDS:
            _CACHE["problem"], _CACHE["at"] = readiness_problem(), now
        return _CACHE["problem"]


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE["at"] = None


@never_cache
@require_GET
def readyz(request):
    problem = cached_readiness_problem()
    if problem:
        logger.warning("not ready: %s", problem)
        return _text(NOT_READY, status=503)
    return _text(READY)


STAFF_PREFIXES = ("/staff", "/admin")
HEALTH_PATHS = ("/healthz", "/readyz")


def _normal_path(path: str) -> str:
    """Collapse repeated slashes and dot segments, and lower-case, so `//staff`, `/./staff` and `/STAFF` are one path."""
    path = posixpath.normpath("/" + re.sub(r"/+", "/", path).lstrip("/")).lower()
    return "/" if path in ("", ".") else path


class HostGuard:
    """An allow-list by host name, independent of the proxy (026 section 8, TEST-P6-32; PR #62 review):

    - the health paths answer only on the local host names (the proxy's socket);
    - the staff screens and the admin answer only on the staff host; in the local environments (test, development)
      with no staff host configured, on any host but the public one;
    - every other host, the public one and its aliases included, gets 404 for those paths.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = _normal_path(request.path)
        host = _host(request.get_host().split(":", 1)[0])
        if path in HEALTH_PATHS and host not in {_host(h) for h in settings.CATALYST_LOCAL_HOSTS}:
            return _not_found()
        if path.startswith(STAFF_PREFIXES) and not _staff_allowed(host):
            return _not_found()
        return self.get_response(request)


def _staff_allowed(host: str) -> bool:
    staff_host = _host(settings.CATALYST_STAFF_HOST)
    if staff_host:
        return host == staff_host
    public_hosts = {_host(urlsplit(settings.CATALYST_PUBLIC_BASE_URL).hostname or ""),
                    *(_host(alias) for alias in settings.CATALYST_PUBLIC_HOST_ALIASES)}  # bgl.2: never on an alias
    return settings.CATALYST_ENV in ("test", "development") and host not in public_hosts


def _host(name: str) -> str:
    return (name or "").strip().lower().rstrip(".")


def _not_found():
    return HttpResponseNotFound("Not found", content_type="text/plain; charset=utf-8")
