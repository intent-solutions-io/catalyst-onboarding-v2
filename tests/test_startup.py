"""Start-up behaviour of real processes (TEST-S1-13, TEST-S1-14): the guards run in AppConfig.ready(),
so each case starts a fresh Python process and asserts its exit status and message."""

import sys

import pytest

from tests.support import ROOT, run

CHECK = [sys.executable, "manage.py", "check"]
def _staging_secrets() -> str:
    """6B.5: staging reads its secrets from per-secret files, never the environment."""
    import os
    import tempfile

    directory = tempfile.mkdtemp(prefix="catalyst-staging-secrets-")
    for name, value in (("secret_key", "synthetic-staging-key-" + "x7Qp2LmZ9vR4tYw8NcB3hK6sJd1FgUe5aTo0" * 2),  # gitleaks:allow
                        ("verification_key", "synthetic-staging-verification-" + "Lq8Zr3Wm6Tn1Vb4Hc7Xs" * 3),  # gitleaks:allow
                        ("db_password", os.environ.get("CATALYST_DB_PASSWORD", "unused"))):
        with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
            handle.write(value)
    return directory


STAGING_SECRETS = _staging_secrets()
# A staging process: synthetic, https links on a staging name, secrets from files, the private file mail sink
# (6B.1, 6B.2, 6B.5).
STAGING = {
    "CATALYST_ENV": "staging", "CATALYST_PUBLIC_BASE_URL": "https://catalyst.staging.test",
    "CATALYST_ALLOWED_HOSTS": "catalyst.staging.test",
    "CATALYST_SECRETS_DIR": STAGING_SECRETS, "CATALYST_SECRET_KEY": None, "CATALYST_VERIFICATION_KEY": None,
    "CATALYST_VERIFICATION_FALLBACK_KEYS": None, "CATALYST_DB_PASSWORD": None, "CATALYST_MAIL_PASSWORD": None,
    "CATALYST_EMAIL_BACKEND": None, "CATALYST_EMAIL_FILE_PATH": "/tmp/catalyst-staging-mail",
    "CATALYST_MAIL_TEST_HOST": None, "CATALYST_STAFF_HOST": "staff.staging.test", "CATALYST_LOCAL_HOSTS": "localhost",
    "CATALYST_WORKER_HEARTBEAT_FILE": "/tmp/catalyst-staging-worker.beat",
    "CATALYST_EFFECT_JOURNAL_DIR": __import__("tempfile").mkdtemp(prefix="catalyst-staging-effects-"),  # 9kg.33: 0700
}
WSGI = [sys.executable, "-c", "import config.wsgi"]


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
@pytest.mark.parametrize("variable", ["MINIMAX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LOGFIRE_TOKEN"])
def test_provider_credential_variable_refuses_to_start(cmd, variable):
    result = run(cmd, **{variable: "synthetic-not-a-key"})
    assert result.returncode != 0
    assert variable in result.stderr
    assert "synthetic-not-a-key" not in result.stderr + result.stdout


def test_smtp_backend_refuses_to_start():
    result = run(CHECK, CATALYST_EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
    assert result.returncode != 0
    assert "not a local sink backend" in result.stderr


def test_production_environment_refuses_to_start():
    result = run(CHECK, CATALYST_ENV="production")
    assert result.returncode != 0
    assert "CATALYST_ENV='production' is not allowed" in result.stderr


@pytest.mark.parametrize("missing", ["CATALYST_SECRET_KEY", "CATALYST_DB_NAME", "CATALYST_ENV", "CATALYST_CHALLENGE_LIFETIME_SECONDS",
                                     "CATALYST_PUBLIC_BASE_URL", "CATALYST_VERIFICATION_KEY"])
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


@pytest.mark.parametrize(
    ("environment", "backend"),
    [("test", "locmem"), ("development", "console"), ("staging", "filebased")],
)
def test_configured_default_mail_backend_is_a_local_sink(environment, backend):
    probe = "from django.conf import settings; print(settings.EMAIL_BACKEND)"
    extra = STAGING if environment == "staging" else {}
    result = run(
        [sys.executable, "-c", f"import django; django.setup(); {probe}"],
        **{**extra, "CATALYST_ENV": environment, "CATALYST_EMAIL_BACKEND": None},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"django.core.mail.backends.{backend}.EmailBackend"


def test_image_digests_match_between_compose_and_ci():
    import re

    def pins(text):
        return sorted(set(re.findall(r"(?:python|postgres):[\w.-]+@sha256:[0-9a-f]{64}", text)))

    compose = pins((ROOT / "compose.yaml").read_text())
    ci = pins((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    assert len(compose) == 2
    assert compose == ci


PROBES = {
    "skip": ("import pytest\n\ndef test_probe():\n    pytest.skip('probe')\n", "1 skipped"),
    "xfail": ("import pytest\n\n@pytest.mark.xfail\ndef test_probe():\n    assert False\n", "1 xfailed"),
    "xpass": ("import pytest\n\n@pytest.mark.xfail\ndef test_probe():\n    assert True\n", "1 xpassed"),
}


@pytest.mark.parametrize("kind", PROBES)
def test_a_skip_or_expected_failure_fails_the_run(tmp_path, kind):
    # Standing proof of the gate in conftest.py, so a pytest upgrade cannot silently disable it.
    source, summary = PROBES[kind]
    probe = tmp_path / "test_probe.py"
    probe.write_text(source)
    result = run([sys.executable, "-m", "pytest", "-p", "tests.conftest", "-q", "-p", "no:cacheprovider", str(probe)])
    assert summary in result.stdout
    assert result.returncode == 1


def test_a_collection_time_skip_fails_the_run(tmp_path):
    # A module skipped at collection (module-level skip, importorskip) must also fail the run. A lone
    # skipped module exits 5 (nothing collected), so a passing module runs beside it.
    (tmp_path / "test_skipped_module.py").write_text("import pytest\n\npytest.skip('probe', allow_module_level=True)\n")
    (tmp_path / "test_passing.py").write_text("def test_ok():\n    assert True\n")
    result = run([sys.executable, "-m", "pytest", "-p", "tests.conftest", "-q", "-p", "no:cacheprovider", str(tmp_path)])
    assert "1 passed, 1 skipped" in result.stdout
    assert "FAILED GATE" in result.stdout
    assert result.returncode == 1


def test_a_plain_pass_still_passes(tmp_path):
    probe = tmp_path / "test_probe.py"
    probe.write_text("def test_probe():\n    assert True\n")
    result = run([sys.executable, "-m", "pytest", "-p", "tests.conftest", "-q", "-p", "no:cacheprovider", str(probe)])
    assert "1 passed" in result.stdout
    assert result.returncode == 0


# --- 6B.2: web security outside the local environments (026 section 8) ----------------------------------------

def test_6b2_staging_passes_django_deploy_checks():
    result = run([sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"], **STAGING)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "System check identified no issues" in result.stdout


def test_6b2_staging_cookies_are_secure_host_only_and_sessions_idle_out():
    probe = ("from django.conf import settings as s; print(s.SESSION_COOKIE_NAME, s.CSRF_COOKIE_NAME, s.SESSION_COOKIE_SECURE,"
             " s.CSRF_COOKIE_SECURE, s.CSRF_COOKIE_HTTPONLY, s.SESSION_COOKIE_AGE, s.SESSION_SAVE_EVERY_REQUEST,"
             " s.SECURE_PROXY_SSL_HEADER, s.SECURE_SSL_REDIRECT, s.SECURE_HSTS_SECONDS, s.SECURE_HSTS_INCLUDE_SUBDOMAINS,"
             " s.SECURE_HSTS_PRELOAD, s.CSRF_TRUSTED_ORIGINS, s.SECURE_REDIRECT_EXEMPT)")
    result = run([sys.executable, "-c", f"import django; django.setup(); {probe}"], **STAGING)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == [
        "__Host-catalyst-session", "__Host-catalyst-csrf", "True", "True", "True", "1800", "True",
        "('HTTP_X_FORWARDED_PROTO',", "'https')", "True", "300", "False", "False",
        "['https://catalyst.staging.test']", "['^healthz$',", "'^readyz$']"]


def test_6b2_staging_refuses_a_production_link_host():
    result = run(CHECK, **{**STAGING, "CATALYST_PUBLIC_BASE_URL": "https://learn.intentsolutions.io"})
    assert result.returncode != 0
    assert "may not name a production host" in result.stderr


def test_6b2_local_environments_keep_plain_cookies_but_still_idle_out():
    probe = "from django.conf import settings as s; print(s.SESSION_COOKIE_NAME, s.SESSION_COOKIE_SECURE, s.SESSION_COOKIE_AGE)"
    result = run([sys.executable, "-c", f"import django; django.setup(); {probe}"])
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["sessionid", "False", "1800"]


def test_6b2_review_staging_refuses_wildcard_production_and_look_alike_hosts():
    for hosts in ("*", ".intentsolutions.io", "catalyst.staging.test,learn.intentsolutions.io"):
        result = run(CHECK, **{**STAGING, "CATALYST_ALLOWED_HOSTS": hosts})
        assert result.returncode != 0 and "ALLOWED_HOSTS in staging may not include" in result.stderr, hosts
    look_alike = "https://learn.intentsolutions。io"  # an ideographic full stop for the last dot
    result = run(CHECK, **{**STAGING, "CATALYST_PUBLIC_BASE_URL": look_alike})
    assert result.returncode != 0


def test_6b3_review_staging_needs_a_proper_staff_host_and_local_hosts():
    no_staff = run(CHECK, **{**STAGING, "CATALYST_STAFF_HOST": None})
    assert no_staff.returncode != 0 and "CATALYST_STAFF_HOST is required" in no_staff.stderr
    for name, value in (("CATALYST_STAFF_HOST", "catalyst.staging.test"), ("CATALYST_STAFF_HOST", "*"),
                        ("CATALYST_LOCAL_HOSTS", "localhost,catalyst.staging.test"), ("CATALYST_LOCAL_HOSTS", ".staging.test")):
        result = run(CHECK, **{**STAGING, name: value})
        assert result.returncode != 0 and "may not be a wildcard" in result.stderr, (name, value)


def test_6b4_review_staging_requires_a_worker_heartbeat_file():
    result = run(CHECK, **{**STAGING, "CATALYST_WORKER_HEARTBEAT_FILE": None})
    assert result.returncode != 0 and "CATALYST_WORKER_HEARTBEAT_FILE must be an absolute path" in result.stderr


def test_9kg_33_a_deployment_needs_an_effect_journal_directory_outside_the_repository():
    """029 section 6.2: outside the local environments every process journals effects, so the directory is required
    and must lie outside the repository (the image root is read-only and the repository is public)."""
    result = run(CHECK, **{**STAGING, "CATALYST_EFFECT_JOURNAL_DIR": None})
    assert result.returncode != 0 and "CATALYST_EFFECT_JOURNAL_DIR must be an absolute path" in result.stderr
    result = run(CHECK, **{**STAGING, "CATALYST_EFFECT_JOURNAL_DIR": str(ROOT / "effects")})
    assert result.returncode != 0 and "outside the repository" in result.stderr
    assert run(CHECK, **STAGING).returncode == 0
    import os
    import tempfile

    missing = os.path.join(tempfile.gettempdir(), "catalyst-staging-effects-absent")
    result = run(CHECK, **{**STAGING, "CATALYST_EFFECT_JOURNAL_DIR": missing})
    assert result.returncode != 0 and "is missing" in result.stderr  # the directory must exist (PR #89 review)
    loose = tempfile.mkdtemp(prefix="catalyst-staging-effects-loose-")
    os.chmod(loose, 0o750)
    result = run(CHECK, **{**STAGING, "CATALYST_EFFECT_JOURNAL_DIR": loose})
    assert result.returncode != 0 and "is not_private" in result.stderr


# --- 6B.5: secrets from per-secret files outside the local environments (026 section 5, P6-D-6) ---------------

def test_6b5_staging_reads_each_secret_from_its_own_file():
    probe = ("from django.conf import settings as s; print(len(s.SECRET_KEY) > 50, s.CATALYST_VERIFICATION_KEY[:31],"
             " s.CATALYST_VERIFICATION_FALLBACK_KEYS)")
    result = run([sys.executable, "-c", f"import django; django.setup(); {probe}"], **STAGING)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["True", "synthetic-staging-verification-", "[]"]


@pytest.mark.parametrize("value", ["synthetic-value-in-the-environment", ""])  # an empty variable counts too
@pytest.mark.parametrize("name", ["CATALYST_SECRET_KEY", "CATALYST_VERIFICATION_KEY", "CATALYST_VERIFICATION_FALLBACK_KEYS",
                                  "CATALYST_DB_PASSWORD", "CATALYST_MAIL_PASSWORD"])
def test_6b5_staging_refuses_a_secret_in_the_environment(name, value):
    result = run(CHECK, **{**STAGING, name: value})
    assert result.returncode != 0 and f"{name} may not be in the environment" in result.stderr
    assert "synthetic-value-in-the-environment" not in result.stderr + result.stdout


def test_6b5_every_secret_name_is_both_read_and_guarded():
    from config import guards, settings

    assert settings.SECRET_NAMES is guards.SECRET_ENV_NAMES


def secrets_dir(tmp_path, **files):
    import shutil

    directory = tmp_path / "secrets"
    shutil.copytree(STAGING_SECRETS, directory)
    for name, content in files.items():
        target = directory / name
        if content is None:
            target.unlink(missing_ok=True)
            target.mkdir()
        else:
            target.write_bytes(content)
    return str(directory)


def test_6b5_secret_files_keep_their_own_spaces_and_lose_only_the_line_ending(tmp_path):
    directory = secrets_dir(tmp_path, verification_key=b"  synthetic-verification-with-spaces-0123456789  \n")
    probe = "from django.conf import settings as s; print(repr(s.CATALYST_VERIFICATION_KEY))"
    result = run([sys.executable, "-c", f"import django; django.setup(); {probe}"],
                 **{**STAGING, "CATALYST_SECRETS_DIR": directory})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "'  synthetic-verification-with-spaces-0123456789  '"


@pytest.mark.parametrize(("files", "message"), [
    ({"secret_key": b""}, "secret CATALYST_SECRET_KEY is missing"),  # an empty file is a missing secret
    ({"secret_key": None}, "secret CATALYST_SECRET_KEY cannot be read"),  # a directory where the file should be
    ({"secret_key": b"\xff\xfe-not-utf8"}, "secret CATALYST_SECRET_KEY cannot be read"),
])
def test_6b5_an_unreadable_secret_stops_start_up_without_showing_its_bytes(tmp_path, files, message):
    result = run(CHECK, **{**STAGING, "CATALYST_SECRETS_DIR": secrets_dir(tmp_path, **files)})
    assert result.returncode != 0 and message in result.stderr
    assert "not-utf8" not in result.stderr


def test_6b5_the_fetcher_starts_without_the_link_signing_key(tmp_path):
    directory = secrets_dir(tmp_path)
    (tmp_path / "secrets" / "verification_key").unlink()
    result = run(CHECK, **{**STAGING, "CATALYST_SECRETS_DIR": directory, "CATALYST_PROCESS_ROLE": "fetcher",
                            "CATALYST_EVIDENCE_PROXY": "egress:3128"})
    assert result.returncode == 0, result.stderr
    web = run(CHECK, **{**STAGING, "CATALYST_SECRETS_DIR": directory})
    assert web.returncode != 0 and "CATALYST_VERIFICATION_KEY is missing" in web.stderr


def test_6b5_a_deployment_cannot_call_itself_development():
    result = run(CHECK, **{**STAGING, "CATALYST_ENV": "development"})
    assert result.returncode != 0 and "CATALYST_ENV=development may not be used with CATALYST_SECRETS_DIR" in result.stderr


def test_6b5_staging_refuses_a_missing_secrets_directory_or_file(tmp_path):
    no_dir = run(CHECK, **{**STAGING, "CATALYST_SECRETS_DIR": None})
    assert no_dir.returncode != 0
    missing = run(CHECK, **{**STAGING, "CATALYST_SECRETS_DIR": str(tmp_path)})  # an empty directory
    assert missing.returncode != 0 and "secret CATALYST_SECRET_KEY is missing from CATALYST_SECRETS_DIR" in missing.stderr


def test_6b5_review_the_web_process_never_runs_as_the_fetcher_or_without_a_signing_key(tmp_path):
    directory = secrets_dir(tmp_path)
    (tmp_path / "secrets" / "verification_key").unlink()
    fetcher = {**STAGING, "CATALYST_SECRETS_DIR": directory, "CATALYST_PROCESS_ROLE": "fetcher",
               "CATALYST_EVIDENCE_PROXY": "egress:3128"}
    web = run(WSGI, **fetcher)  # config.wsgi declares the web kind before Django loads
    assert web.returncode != 0 and "the web process may not run as CATALYST_PROCESS_ROLE=fetcher" in web.stderr
    assert run(CHECK, **fetcher).returncode == 0  # a management or worker process may be the fetcher
    unknown = run(CHECK, **{**STAGING, "CATALYST_PROCESS_ROLE": "superuser"})
    assert unknown.returncode != 0 and "CATALYST_PROCESS_ROLE must be one of" in unknown.stderr


def test_6b8_the_staff_host_is_never_also_a_local_health_host():
    result = run(CHECK, **{**STAGING, "CATALYST_LOCAL_HOSTS": "localhost,staff.staging.test"})
    assert result.returncode != 0 and "may not also be one of CATALYST_LOCAL_HOSTS" in result.stderr


def test_6b11_a_staging_fetcher_refuses_to_start_without_the_egress_proxy(tmp_path):
    directory = secrets_dir(tmp_path)
    fetcher = {**STAGING, "CATALYST_SECRETS_DIR": directory, "CATALYST_PROCESS_ROLE": "fetcher"}
    missing = run(CHECK, **fetcher)
    assert missing.returncode != 0 and "a fetcher outside test and development needs CATALYST_EVIDENCE_PROXY" in missing.stderr
    malformed = run(CHECK, **{**fetcher, "CATALYST_EVIDENCE_PROXY": "http://egress:3128"})
    assert malformed.returncode != 0 and "CATALYST_EVIDENCE_PROXY must be host:port" in malformed.stderr

