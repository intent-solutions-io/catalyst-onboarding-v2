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


# Settings a spawned worker receives, and nothing else: no owner, retention or administrator login.
WORKER_SETTINGS = ("CATALYST_SECRET_KEY", "CATALYST_DB_HOST", "CATALYST_DB_PORT", "CATALYST_CHALLENGE_LIFETIME_SECONDS",
                   "CATALYST_PUBLIC_BASE_URL", "CATALYST_VERIFICATION_KEY")


def worker_env(sink_dir, **overrides):
    """An explicit, minimal environment for a worker subprocess: the application role's login, synthetic
    settings, a run-owned file sink and short synthetic timings. Built from scratch, not inherited."""
    from django.conf import settings
    from django.db import connection

    env = {name: os.environ[name] for name in ("PATH", "LANG") if name in os.environ}
    env.update({name: os.environ[name] for name in WORKER_SETTINGS})
    env.update(
        HOME="/tmp", PYTHONDONTWRITEBYTECODE="1", DJANGO_SETTINGS_MODULE="config.settings", CATALYST_ENV="test",
        CATALYST_DB_NAME=connection.settings_dict["NAME"],
        CATALYST_DB_USER=settings.CATALYST_DB_ROLES["app"], CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_APP_PASSWORD"],
        CATALYST_EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend", CATALYST_EMAIL_FILE_PATH=str(sink_dir),
        CATALYST_WORKER_LEASE_SECONDS="2", CATALYST_WORKER_POLL_SECONDS="0.1", CATALYST_WORKER_RETRY_SECONDS="0",
        CATALYST_EMAIL_TIMEOUT_SECONDS="1",
    )
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


def worker_process(sink_dir, *args, module=None, **overrides):
    """Start a worker subprocess: the real `manage.py run_worker`, or `module` (a test child that installs
    a fault seam and then runs the same command)."""
    cmd = [sys.executable, "-m", module] if module else [sys.executable, "manage.py", "run_worker"]
    return subprocess.Popen([*cmd, *args], cwd=ROOT, env=worker_env(sink_dir, **overrides),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
