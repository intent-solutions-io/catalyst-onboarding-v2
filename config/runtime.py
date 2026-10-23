"""Runtime database-role enforcement (ADR-14, D-17): the one contract behind catalyst.E002 and the
connection-time guard.

Each entry point declares what kind of process it is: config/wsgi.py declares "web" unconditionally,
before Django loads, so no environment value can exempt the web path; the worker (S1-T5) will declare
"worker"; anything undeclared (management commands, tests) is "management". For "web" and "worker",
CatalystConfig.ready() connects a receiver to connection_created, so every new database connection is
checked before any application query runs on it. ready() itself runs no query (Django advises against
it). A refused connection, or one whose check itself fails, is closed before the error propagates;
ImproperlyConfigured names roles only, never passwords. Every new entry point (an ASGI module, the
worker command) must call declare_process: an undeclared process is "management" and is not enforced.
"""

ENFORCED_KINDS = frozenset({"web", "worker"})
# `reconcile` (9kg.49, RD-1): the owner-run post-restore step, declared in code by its command; it may read the
# mailbox's Sent folder and nothing else of the mail host, and is never role-enforced (it connects as the owner).
KINDS = ENFORCED_KINDS | {"management", "reconcile"}

_declared = {"kind": "management"}


def declare_process(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown process kind {kind!r}")
    _declared["kind"] = kind


def process_kind() -> str:
    return _declared["kind"]


def role_problems(cursor, kind: str, roles) -> list[str]:
    """No process may connect as a superuser; a web or worker process must connect as exactly the
    application role, and the fetcher (a worker with CATALYST_PROCESS_ROLE=fetcher, 9kg.24) as exactly the fetcher
    role; neither may be a member of the owner or retention role, nor the fetcher of the application role. `cursor`
    is any DB-API cursor with %s parameters (Django's or psycopg's)."""
    from django.conf import settings

    fetcher = kind == "worker" and getattr(settings, "CATALYST_PROCESS_ROLE", "") == "fetcher"
    expected_key = "fetcher" if fetcher else "app"
    cursor.execute(
        "SELECT current_user, rolsuper, pg_has_role(current_user, %s, 'MEMBER'), pg_has_role(current_user, %s, 'MEMBER'),"
        " pg_has_role(current_user, %s, 'MEMBER') FROM pg_catalog.pg_roles WHERE rolname = current_user",
        [roles["owner"], roles["retention"], roles["app"]],
    )
    user, is_superuser, owner_member, retention_member, app_member = cursor.fetchone()
    problems = []
    if is_superuser:
        problems.append(f"connects as superuser {user!r}")
    if kind in ENFORCED_KINDS:
        name = "the fetcher role" if fetcher else "the application role"
        if user != roles[expected_key]:
            problems.append(f"{kind} process connects as {user!r}, not {name} {roles[expected_key]!r}")
        elif owner_member or retention_member or (fetcher and app_member):
            problems.append(f"{name} {user!r} is a member of a broader role")
    return problems


def enforce_on_connect(sender, connection, **kwargs):
    """connection_created receiver: refuse the connection before the process uses it."""
    kind = process_kind()
    if kind not in ENFORCED_KINDS:
        return
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    try:
        with connection.cursor() as cursor:
            problems = role_problems(cursor, kind, settings.CATALYST_DB_ROLES)
    except BaseException:
        connection.close()  # fail closed: an unchecked connection is never left open for a retry to reuse
        raise
    if problems:
        connection.close()
        raise ImproperlyConfigured(f"Catalyst refuses the database connection {connection.alias!r}: " + "; ".join(problems))
