"""Unit tests for config.guards: the rules, independent of process start-up."""

from types import SimpleNamespace

from config import guards

PG = {"default": {"ENGINE": "django.db.backends.postgresql"}}
LOCMEM = "django.core.mail.backends.locmem.EmailBackend"


def test_postgresql_is_accepted():
    assert guards.database_problems(PG) == []


def test_missing_default_database_is_reported():
    assert guards.database_problems({}) == ["no 'default' database is configured"]


def test_every_non_postgresql_alias_is_reported():
    problems = guards.database_problems(
        {**PG, "other": {"ENGINE": "django.db.backends.sqlite3"}, "third": {"ENGINE": "django.db.backends.mysql"}}
    )
    assert len(problems) == 2
    assert any("'other'" in p and "sqlite3" in p for p in problems)
    assert any("'third'" in p and "mysql" in p for p in problems)


def test_only_development_and_test_environments_are_allowed():
    assert guards.environment_problems("test") == []
    assert guards.environment_problems("development") == []
    assert guards.environment_problems("production") != []
    assert guards.environment_problems("staging") != []


def test_sink_backends_pass_and_smtp_is_refused():
    for backend in (
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.filebased.EmailBackend",
    ):
        assert guards.provider_problems(backend, {}) == []
    problems = guards.provider_problems("django.core.mail.backends.smtp.EmailBackend", {})
    assert problems == ["EMAIL_BACKEND 'django.core.mail.backends.smtp.EmailBackend' is not a local sink backend"]


def test_provider_variables_are_reported_by_name_not_value():
    environ = {"MINIMAX_API_KEY": "synthetic-value-1", "DOCUMENSO_TOKEN": "synthetic-value-2", "PATH": "/usr/bin"}
    (problem,) = guards.provider_problems(LOCMEM, environ)
    assert "DOCUMENSO_TOKEN" in problem and "MINIMAX_API_KEY" in problem
    assert "synthetic-value" not in problem
    assert "PATH" not in problem


def test_all_problems_combines_every_rule():
    settings = SimpleNamespace(
        DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3"}},
        CATALYST_ENV="production",
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
    )
    assert len(guards.all_problems(settings, {"SMTP_PASSWORD": "x"})) == 4


def test_system_check_reports_a_problem_introduced_after_startup(settings):
    from django.core import checks

    settings.EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    errors = [e for e in checks.run_checks() if e.id == "catalyst.E001"]
    assert [e.msg for e in errors] == [
        "EMAIL_BACKEND 'django.core.mail.backends.smtp.EmailBackend' is not a local sink backend"
    ]


def test_system_check_is_silent_for_the_valid_configuration():
    from django.core import checks

    assert [e for e in checks.run_checks() if e.id == "catalyst.E001"] == []


def test_model_provider_and_telemetry_credentials_are_refused_by_exact_name():
    environ = {
        "OPENAI_API_KEY": "synthetic-1",
        "ANTHROPIC_API_KEY": "synthetic-2",
        "LOGFIRE_TOKEN": "synthetic-3",
        "OTEL_EXPORTER_OTLP_HEADERS": "synthetic-4",
    }
    (problem,) = guards.provider_problems(LOCMEM, environ)
    for name in environ:
        assert name in problem
    assert "synthetic-" not in problem


def test_harmless_vendor_named_variables_are_not_refused():
    environ = {"OPENAI_DOCS_URL": "https://example.test", "ANTHROPIC_COURSE_NOTES": "x", "LOGFIRE_DOCS": "x"}
    assert guards.provider_problems(LOCMEM, environ) == []
