"""Unit tests for config.guards: the rules, independent of process start-up."""

from types import SimpleNamespace

import pytest

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


def test_only_development_test_and_staging_environments_are_allowed():
    for allowed in ("test", "development", "staging"):  # staging: 026 P6-D-2 (D-49)
        assert guards.environment_problems(allowed) == []
    for refused in ("production", "prod", "", "Staging", "staging "):
        assert guards.environment_problems(refused) != []
    assert {e for e in ("test", "staging", "development", "production") if guards.synthetic(e)} == {"test", "staging"}


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
    # database, environment, provider variable, sink backend, plus the 9kg.29 and 9kg.43 fixed intake settings (unset here)
    assert len(guards.all_problems(settings, {"SMTP_PASSWORD": "x"})) == 6


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


EXPECTED_REFUSED_NAMES = (
    "OPENAI_API_KEY", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "LOGFIRE_TOKEN", "LOGFIRE_SEND_TO_LOGFIRE",
    "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
)


@pytest.mark.parametrize("name", EXPECTED_REFUSED_NAMES)
def test_each_listed_credential_name_is_refused_without_its_value(name):
    (problem,) = guards.provider_problems(LOCMEM, {name: "synthetic-value"})
    assert name in problem
    assert "synthetic-value" not in problem


def test_the_refused_name_list_is_exactly_the_documented_one():
    assert guards.PROVIDER_ENV_NAMES == frozenset(EXPECTED_REFUSED_NAMES)


def test_harmless_vendor_named_variables_are_not_refused():
    environ = {"OPENAI_DOCS_URL": "https://example.test", "ANTHROPIC_COURSE_NOTES": "x", "LOGFIRE_DOCS": "x"}
    assert guards.provider_problems(LOCMEM, environ) == []



def test_code_loading_settings_are_pinned_to_catalyst_apps_and_never_from_the_environment():
    ok = SimpleNamespace(CATALYST_ATTENTION_OPENER="correspondence.staff_items.open_attention",
                         CATALYST_ACTION_HANDLERS={"send": "correspondence.outbound.SendMessage"})
    assert guards.dispatch_problems(ok, {}) == []
    bad = SimpleNamespace(CATALYST_ATTENTION_OPENER="os.system", CATALYST_ACTION_HANDLERS={"x": "subprocess.run"})
    assert len(guards.dispatch_problems(bad, {"CATALYST_ATTENTION_OPENER": "y"})) == 3


# --- 6B.1: the staging environment is synthetic under test's strict rules (026 P6-D-2, D-49) -------------------

def staging(**values):
    base = dict(CATALYST_ENV="staging", CATALYST_PUBLIC_BASE_URL="https://catalyst.staging.test")
    return SimpleNamespace(**{**base, **values})


def test_6b1_staging_allows_the_fake_agreement_provider_only_under_the_test_rules(tmp_path):
    good = staging(CATALYST_AGREEMENT_PROVIDER_URL="https://documenso.staging.test:8443/api/v2",
                   CATALYST_AGREEMENT_PROVIDER_ADDRESS="127.0.0.1", CATALYST_AGREEMENT_STORAGE_DIR=str(tmp_path),
                   CATALYST_AGREEMENT_WEBHOOK_SECRETS=["synthetic-one"])
    assert guards.agreement_problems(good, {}) == []
    for change, expected in (({"CATALYST_AGREEMENT_PROVIDER_URL": "https://documenso.example.com/api/v2"}, ".test host"),
                             ({"CATALYST_AGREEMENT_PROVIDER_URL": "http://documenso.staging.test/api/v2"}, "https"),
                             ({"CATALYST_AGREEMENT_PROVIDER_ADDRESS": "10.0.0.5"}, "loopback"),
                             ({"CATALYST_AGREEMENT_STORAGE_DIR": "relative/dir"}, "absolute"),
                             ({"CATALYST_AGREEMENT_WEBHOOK_SECRETS": ["a", "b", "c"]}, "at most two")):
        problems = guards.agreement_problems(SimpleNamespace(**{**vars(good), **change}), {})
        assert any(expected in p for p in problems), (change, problems)
    assert guards.agreement_problems(good, {"CATALYST_AGREEMENT_PROVIDER_TOKEN": "x"})  # never from the environment


def test_6b1_staging_allows_only_the_fake_mail_host_and_a_test_domain():
    good = staging(CATALYST_PROVISIONING_ADAPTER="tests.mxroute_fake.FakeMailHost",
                   CATALYST_PROVISIONING_DOMAIN="team.staging.test")
    assert guards.provisioning_problems(good, {}) == []
    assert any("test fake" in p for p in guards.provisioning_problems(
        staging(CATALYST_PROVISIONING_ADAPTER="provisioning.live.MXroute"), {}))
    assert any(".test domain" in p for p in guards.provisioning_problems(
        staging(CATALYST_PROVISIONING_DOMAIN="intentsolutions.io"), {}))
    assert any("mail-host credential" in p for p in guards.provisioning_problems(good, {"MXROUTE_API_KEY": "x"}))


def test_6b1_staging_links_must_be_https_and_production_still_may_not_use_any_fake():
    assert any("https" in p for p in guards.provisioning_problems(
        staging(CATALYST_PUBLIC_BASE_URL="http://catalyst.staging.test"), {}))
    production = SimpleNamespace(CATALYST_ENV="production", CATALYST_PROVISIONING_ADAPTER="tests.mxroute_fake.FakeMailHost",
                                 CATALYST_AGREEMENT_PROVIDER_URL="https://documenso.staging.test/api/v2",
                                 CATALYST_EVIDENCE_ALLOWED_HOSTS=["site.staging.test"], CATALYST_ASSESSMENT_MODEL="test",
                                 CATALYST_PUBLIC_BASE_URL="https://x.test")
    assert guards.provisioning_problems(production, {}) and guards.agreement_problems(production, {})
    assert guards.evidence_problems(production, {}) and guards.assessment_problems(production, {})


def test_6b1_staging_evidence_fixtures_are_no_wider_than_test():
    good = staging(CATALYST_EVIDENCE_ALLOWED_HOSTS=["portfolio.staging.test"], CATALYST_EVIDENCE_FIXTURE_ADDRESS="127.0.0.1",
                   CATALYST_EVIDENCE_CA_FILE="/run/fixtures/ca.pem")
    assert guards.evidence_problems(good, {}) == []
    assert guards.evidence_problems(staging(CATALYST_EVIDENCE_ALLOWED_HOSTS=["github.com"]), {})
    assert guards.evidence_problems(staging(CATALYST_EVIDENCE_FIXTURE_ADDRESS="192.0.2.10"), {})
    assert guards.evidence_problems(staging(CATALYST_EVIDENCE_CA_FILE="ca.pem"), {})


def test_6b1_staging_keeps_the_test_model_only_and_no_live_mail_or_send_evidence():
    assert guards.assessment_problems(staging(CATALYST_ASSESSMENT_MODEL="test"), {}) == []
    assert guards.assessment_problems(staging(CATALYST_ASSESSMENT_MODEL="minimax"), {})
    mail = dict(CATALYST_MAIL_SENT_FOLDER="", CATALYST_MAIL_COLLECT_FOLDER="INBOX", CATALYST_MAIL_TLS="starttls")
    assert guards.mail_problems(staging(CATALYST_MAIL_HOST="127.0.0.1", **mail)) == []  # the loopback sink
    assert guards.mail_problems(staging(CATALYST_MAIL_HOST="smtp.example.com", **mail))
    assert guards.mail_problems(staging(CATALYST_MAIL_HOST="mailsink", CATALYST_MAIL_TEST_HOST="mailsink", **mail))
    assert guards.mail_problems(staging(CATALYST_SEND_EVIDENCE_SOURCE="sent-folder", **mail))  # still test only
    assert guards.provider_problems(LOCMEM, {"DOCUMENSO_API_TOKEN": "x"})  # provider variables refused everywhere


def test_6b1_review_staging_never_prints_mail_and_its_file_sink_is_private():
    mail = dict(CATALYST_MAIL_SENT_FOLDER="", CATALYST_MAIL_COLLECT_FOLDER="INBOX", CATALYST_MAIL_TLS="starttls")
    console = staging(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend", **mail)
    assert any("console" in p for p in guards.mail_problems(console))
    filebased = "django.core.mail.backends.filebased.EmailBackend"
    assert any("absolute EMAIL_FILE_PATH" in p for p in guards.mail_problems(staging(EMAIL_BACKEND=filebased, **mail)))
    assert guards.mail_problems(staging(EMAIL_BACKEND=filebased, EMAIL_FILE_PATH="/run/mailsink", **mail)) == []


def test_6b1_review_staging_refuses_a_private_mail_peer_like_development(settings):
    from correspondence import transport

    settings.CATALYST_MAIL_HOST = settings.CATALYST_MAIL_TEST_HOST = "mailsink"
    for environment, private_ok in (("test", True), ("staging", False), ("development", False)):
        settings.CATALYST_ENV = environment
        assert transport.peer_allowed("10.0.0.5") is private_ok, environment
        assert transport.peer_allowed("127.0.0.1") is True
    settings.CATALYST_ENV = "test"


def test_6b1_review_staging_builds_only_the_test_model(settings):
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.models.test import TestModel

    from assessments import agent

    settings.CATALYST_ASSESSMENT_MODEL = "test"
    for environment, allowed in (("staging", True), ("test", True), ("development", False)):
        settings.CATALYST_ENV = environment
        if allowed:
            assert isinstance(agent.build_model(), (TestModel, FunctionModel))
        else:
            with pytest.raises(agent.ModelUnavailable):
                agent.build_model()
    settings.CATALYST_ENV = "test"

