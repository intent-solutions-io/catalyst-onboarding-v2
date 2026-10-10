"""System check wrapper around config.guards (catalyst.E001).

At start-up CatalystConfig.ready() refuses to run before any check could report, so this check is the
reporting path for settings that change after start-up (for example override_settings in tests) and
for `manage.py check` in any process where ready() already passed.
"""

import os

from django.conf import settings
from django.core import checks

from . import guards


@checks.register()  # no "database" tag: runs on every `manage.py check`
def guard_check(app_configs, **kwargs):
    return [checks.Error(p, id="catalyst.E001") for p in guards.all_problems(settings, os.environ)]


@checks.register(checks.Tags.database)
def database_role_check(app_configs, databases=None, **kwargs):
    """catalyst.E002 (ADR-14, D-17): no process connects as a superuser; web and worker processes connect
    as exactly the application role, which is not a member of the owner or retention role. Tagged
    `database`: it runs with `manage.py check --database default`, which deployment must call (P6)."""
    from django.db import connections

    roles = settings.CATALYST_DB_ROLES
    errors = []
    for alias in databases or []:
        with connections[alias].cursor() as cursor:
            cursor.execute(
                "SELECT current_user, rolsuper, pg_has_role(current_user, %s, 'MEMBER'), pg_has_role(current_user, %s, 'MEMBER')"
                " FROM pg_catalog.pg_roles WHERE rolname = current_user",
                [roles["owner"], roles["retention"]],
            )
            user, is_superuser, owner_member, retention_member = cursor.fetchone()
        if is_superuser:
            errors.append(checks.Error(f"database {alias!r} connects as superuser {user!r}", id="catalyst.E002"))
        if settings.CATALYST_PROCESS in {"web", "worker"}:
            if user != roles["app"]:
                errors.append(checks.Error(
                    f"{settings.CATALYST_PROCESS} process connects to {alias!r} as {user!r}, not the application role {roles['app']!r}",
                    id="catalyst.E002",
                ))
            elif owner_member or retention_member:
                errors.append(checks.Error(
                    f"the application role {user!r} is a member of the owner or retention role", id="catalyst.E002"
                ))
    return errors
