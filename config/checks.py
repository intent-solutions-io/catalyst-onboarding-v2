"""System check wrapper around config.guards (catalyst.E001).

At start-up CatalystConfig.ready() refuses to run before any check could report, so this check is the
reporting path for settings that change after start-up (for example override_settings in tests) and
for `manage.py check` in any process where ready() already passed.
"""

import os

from django.conf import settings
from django.core import checks

from . import guards, runtime


@checks.register()  # no "database" tag: runs on every `manage.py check`
def guard_check(app_configs, **kwargs):
    return [checks.Error(p, id="catalyst.E001") for p in guards.all_problems(settings, os.environ)]


@checks.register(checks.Tags.database)
def database_role_check(app_configs, databases=None, **kwargs):
    """catalyst.E002 (ADR-14, D-17): the diagnostic form of config.runtime.role_problems, the same contract
    the web and worker processes enforce on every new connection. Tagged `database`: it runs with
    `manage.py check --database default`, for the kind named by CATALYST_PROCESS (default "management")."""
    from django.db import connections

    errors = []
    for alias in databases or []:
        with connections[alias].cursor() as cursor:
            problems = runtime.role_problems(cursor, settings.CATALYST_PROCESS, settings.CATALYST_DB_ROLES)
        errors += [checks.Error(f"database {alias!r}: {p}", id="catalyst.E002") for p in problems]
    return errors
