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
    """catalyst.E002 (ADR-14, D-17): no process connects as a superuser, and web and worker processes
    never connect as the migration owner. Tagged `database`: it runs with `manage.py check --database`."""
    from django.db import connections

    errors = []
    for alias in databases or []:
        with connections[alias].cursor() as cursor:
            cursor.execute("SELECT current_user, rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user")
            user, is_superuser = cursor.fetchone()
        if is_superuser:
            errors.append(checks.Error(f"database {alias!r} connects as superuser {user!r}", id="catalyst.E002"))
        if settings.CATALYST_PROCESS in {"web", "worker"} and user == settings.CATALYST_DB_ROLES["owner"]:
            errors.append(
                checks.Error(
                    f"{settings.CATALYST_PROCESS} process connects to {alias!r} as the migration owner {user!r}",
                    id="catalyst.E002",
                )
            )
    return errors
