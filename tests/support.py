"""Shared test helpers: child-process environments and owner-run management commands (D-21)."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADMIN_PREFIX = "CATALYST_DB_ADMIN_"


def child_env(**overrides):
    """The environment for a child process: this process's synthetic environment without the bootstrap
    administrator's login (CATALYST_DB_ADMIN_*), plus `overrides` (a value of None removes a name). Only the
    probe that proves superuser refusal passes administrator credentials back in, explicitly."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(ADMIN_PREFIX)}
    env["DJANGO_SETTINGS_MODULE"] = "config.settings"
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


def run(cmd, timeout=60, **overrides):
    return subprocess.run(cmd, cwd=ROOT, env=child_env(**overrides), capture_output=True, text=True, timeout=timeout)


def manage_as_owner(*args):
    """Run a management command as the migration owner against this run's test database: the separate,
    authorized administration path. The test process itself runs as the application role."""
    from django.conf import settings
    from django.db import connection

    result = run(
        [sys.executable, "manage.py", *args],
        CATALYST_DB_NAME=connection.settings_dict["NAME"],
        CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
        CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"],
    )
    assert result.returncode == 0, result.stderr
    return result
