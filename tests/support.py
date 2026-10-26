"""Shared test helpers: child-process environments and owner-run management commands (D-21)."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADMIN_PREFIX = "CATALYST_DB_ADMIN_"
# 6hl.10: the test process never holds CATALYST_DB_ADMIN_* (compose.yaml and ci.yml give it to the provisioning
# step alone). The superuser-refusal probes, and the tests that must act as the administrator, take the login from
# this probe-only pair, read here and nowhere else; no application, provisioning or deployment code knows the name.
PROBE_PREFIX = "CATALYST_TEST_SUPERUSER_PROBE_"
STRIPPED_PREFIXES = (ADMIN_PREFIX, PROBE_PREFIX)


def superuser_login():
    """The probe-only superuser login as (user, password), for a test that states it acts as the administrator."""
    return os.environ[PROBE_PREFIX + "USER"], os.environ[PROBE_PREFIX + "PASSWORD"]


def superuser_probe():
    """The administrator variables a child needs when a test passes the login back in, explicitly."""
    user, password = superuser_login()
    return {"CATALYST_DB_ADMIN_USER": user, "CATALYST_DB_ADMIN_PASSWORD": password}


def child_env(**overrides):
    """The environment for a child process: this process's synthetic environment without the administrator's
    login (CATALYST_DB_ADMIN_*, never present anyway) and without the probe pair, plus `overrides` (a value of
    None removes a name). Only a test that states it acts as the administrator passes the login in, explicitly."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(STRIPPED_PREFIXES)}
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
                   "CATALYST_PUBLIC_BASE_URL", "CATALYST_VERIFICATION_KEY", "CATALYST_EFFECT_JOURNAL_DIR")


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


def resume_pauses(*applications, note="synthetic resume (test setup)") -> int:
    """Clear automation pauses in the shape the pause guard requires (workflow 0005; 9kg.6): the `automation_resumed`
    history event, recorded by staff with an actor reference and a note, in the transaction that deletes the row.
    For tests that step past a pause as setup, without the staff service's policy (permissions, open causes): the
    service itself and its policy are tested in tests/test_processing.py and test_reminders.py. With no application
    given, every application's pause is cleared; the restore hold is never touched. Returns the rows cleared."""
    from django.db import transaction

    from applications.models import Application, ApplicationEvent
    from workflow.models import AutomationPause

    with transaction.atomic():
        rows = AutomationPause.objects.filter(subject_type="application")
        if applications:
            rows = rows.filter(subject_id__in=[a.public_ref for a in applications])
        for row in rows:
            application = Application.objects.get(public_ref=row.subject_id)
            ApplicationEvent.objects.create(
                application=application, kind="automation_resumed", actor_type=ApplicationEvent.ActorType.STAFF,
                actor_ref="user:test-setup", data={"note": note, "paused_by": row.actor_ref, "pause_reason": row.reason,
                                                   "system_pause": row.actor_ref == "system" or row.actor_ref.startswith("system:")})
        return rows.delete()[0]


# 9kg.25: the erasure key tests use (synthetic; never a real key), and the replay marker the post-restore review and lift
# require, for tests about something else: the replay with nothing to replay, written straight to the journal.
ERASURE_KEY = "synthetic-erasure-key-for-tests-only-0123456789abcdef"  # gitleaks:allow (synthetic; never a real key)


def mark_erasures_replayed() -> None:
    from erasure import replay
    from workflow import journal

    if journal.configured():
        replay.mark(journal.read(), ERASURE_KEY.encode())
