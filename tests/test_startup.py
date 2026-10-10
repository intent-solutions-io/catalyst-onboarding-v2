"""Start-up behaviour of real processes (TEST-S1-13, TEST-S1-14): the guards run in AppConfig.ready(),
so each case starts a fresh Python process and asserts its exit status and message."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECK = [sys.executable, "manage.py", "check"]
WSGI = [sys.executable, "-c", "import config.wsgi"]


def run(cmd, **overrides):
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings", **overrides}
    env = {k: v for k, v in env.items() if v is not None}
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)


def test_check_passes_with_the_test_configuration():
    result = run(CHECK)
    assert result.returncode == 0, result.stderr
    assert "System check identified no issues" in result.stdout


@pytest.mark.parametrize("cmd", [CHECK, WSGI], ids=["manage-check", "wsgi-import"])
def test_non_postgresql_engine_refuses_to_start(cmd):
    result = run(cmd, DJANGO_SETTINGS_MODULE="tests.settings_sqlite")
    assert result.returncode != 0
    assert "Catalyst refuses to start" in result.stderr
    assert "sqlite3" in result.stderr


@pytest.mark.parametrize("cmd", [CHECK, WSGI], ids=["manage-check", "wsgi-import"])
def test_provider_credential_variable_refuses_to_start(cmd):
    result = run(cmd, MINIMAX_API_KEY="synthetic-not-a-key")
    assert result.returncode != 0
    assert "MINIMAX_API_KEY" in result.stderr
    assert "synthetic-not-a-key" not in result.stderr + result.stdout


def test_smtp_backend_refuses_to_start():
    result = run(CHECK, CATALYST_EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
    assert result.returncode != 0
    assert "not a local sink backend" in result.stderr


def test_production_environment_refuses_to_start():
    result = run(CHECK, CATALYST_ENV="production")
    assert result.returncode != 0
    assert "CATALYST_ENV='production' is not allowed" in result.stderr


@pytest.mark.parametrize("missing", ["CATALYST_SECRET_KEY", "CATALYST_DB_NAME", "CATALYST_ENV"])
def test_required_setting_missing_refuses_to_start(missing):
    result = run(CHECK, **{missing: None})
    assert result.returncode != 0
    assert f"environment variable {missing} is required" in result.stderr


def test_unreachable_database_fails_loudly_when_a_command_needs_it():
    # `manage.py check --database default` opened no connection here and exited 0 with the database
    # unreachable, so it is not a readiness probe. A command that must read the database fails clearly.
    result = run([sys.executable, "manage.py", "showmigrations"], CATALYST_DB_PORT="1")
    assert result.returncode != 0
    assert "OperationalError" in result.stderr
