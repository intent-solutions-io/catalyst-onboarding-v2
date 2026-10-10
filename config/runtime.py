"""Runtime database-role enforcement (ADR-14, D-17): the one contract behind catalyst.E002 and the
connection-time guard.

Each entry point declares what kind of process it is: config/wsgi.py declares "web" unconditionally,
before Django loads, so no environment value can exempt the web path; the worker (S1-T5) will declare
"worker"; anything undeclared (management commands, tests) is "management". For "web" and "worker",
CatalystConfig.ready() connects a receiver to connection_created, so every new database connection is
checked before any application query runs on it. ready() itself runs no query (Django advises against
it). A refused connection is closed and ImproperlyConfigured is raised, naming roles only, never
passwords.
"""

ENFORCED_KINDS = frozenset({"web", "worker"})
KINDS = ENFORCED_KINDS | {"management"}

_declared = {"kind": "management"}


def declare_process(kind: str) -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown process kind {kind!r}")
    _declared["kind"] = kind


def process_kind() -> str:
    return _declared["kind"]


def role_problems(cursor, kind: str, roles) -> list[str]:
    """No process may connect as a superuser; a web or worker process must connect as exactly the
    application role, which must not be a member of the owner or retention role. `cursor` is any DB-API
    cursor with %s parameters (Django's or psycopg's)."""
    cursor.execute(
        "SELECT current_user, rolsuper, pg_has_role(current_user, %s, 'MEMBER'), pg_has_role(current_user, %s, 'MEMBER')"
        " FROM pg_catalog.pg_roles WHERE rolname = current_user",
        [roles["owner"], roles["retention"]],
    )
    user, is_superuser, owner_member, retention_member = cursor.fetchone()
    problems = []
    if is_superuser:
        problems.append(f"connects as superuser {user!r}")
    if kind in ENFORCED_KINDS:
        if user != roles["app"]:
            problems.append(f"{kind} process connects as {user!r}, not the application role {roles['app']!r}")
        elif owner_member or retention_member:
            problems.append(f"the application role {user!r} is a member of the owner or retention role")
    return problems


def enforce_on_connect(sender, connection, **kwargs):
    """connection_created receiver: refuse the connection before the process uses it."""
    kind = process_kind()
    if kind not in ENFORCED_KINDS:
        return
    from django.conf import settings
    from django.core.exceptions import ImproperlyConfigured

    with connection.cursor() as cursor:
        problems = role_problems(cursor, kind, settings.CATALYST_DB_ROLES)
    if problems:
        connection.close()
        raise ImproperlyConfigured(f"Catalyst refuses the database connection {connection.alias!r}: " + "; ".join(problems))
