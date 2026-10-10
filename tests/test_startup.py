"""Start-up behaviour of real processes (TEST-S1-13, TEST-S1-14): the guards run in AppConfig.ready(),
so each case starts a fresh Python process and asserts its exit status and message."""

import sys

import pytest

from tests.support import ROOT, run

CHECK = [sys.executable, "manage.py", "check"]
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


@pytest.mark.parametrize(
    ("environment", "backend"),
    [("test", "locmem"), ("development", "console")],
)
def test_configured_default_mail_backend_is_a_local_sink(environment, backend):
    probe = "from django.conf import settings; print(settings.EMAIL_BACKEND)"
    result = run(
        [sys.executable, "-c", f"import django; django.setup(); {probe}"],
        CATALYST_ENV=environment, CATALYST_EMAIL_BACKEND=None,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"django.core.mail.backends.{backend}.EmailBackend"


def test_image_digests_match_between_compose_and_ci():
    import re

    pins = lambda text: sorted(set(re.findall(r"(?:python|postgres):[\w.-]+@sha256:[0-9a-f]{64}", text)))
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
