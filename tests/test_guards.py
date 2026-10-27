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


def test_only_the_four_named_environments_are_allowed():
    for allowed in ("test", "development", "staging", "production"):  # staging: D-49; production: 9kg.31.11
        assert guards.environment_problems(allowed) == []
    for refused in ("prod", "", "Staging", "staging ", "Production", "production ", "live"):
        assert guards.environment_problems(refused) != []
    assert {e for e in ("test", "staging", "development", "production") if guards.synthetic(e)} == {"test", "staging"}
    assert guards.LIVE_ENVIRONMENTS == {"production"} and guards.DEPLOYED_ENVIRONMENTS == {"staging", "production"}
    assert not guards.draft_wording_allowed("production")  # an unapproved wording is never shown in production


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
    # Production is admitted (9kg.31.11), so every deployment and live rule speaks instead of one environment refusal.
    problems = guards.all_problems(settings, {"SMTP_PASSWORD": "x"})
    for expected in ("sqlite3", "not a local sink backend", "SMTP_PASSWORD", "CATALYST_INTAKE_MODE must be",
                     "CATALYST_CLIENT_IDENTITY must be", "must name the production mail host",
                     "must list the first-generation mailbox", "must pin the v2 mailbox login",
                     "must be the Sent-folder reader", "CATALYST_STAFF_HOST is required",
                     "CATALYST_WORKER_HEARTBEAT_FILE must be", "CATALYST_SECRETS_DIR must be",
                     "CATALYST_EFFECT_JOURNAL_DIR must be", "must be 'invitation' in a live environment",
                     "must be https on the dedicated v2 host name"):
        assert any(expected in p for p in problems), expected
    assert not any("is not allowed; use one of" in p for p in problems)


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


def test_9kg_33_the_effect_journal_directory_is_required_outside_the_local_environments():
    for local in ("test", "development"):
        assert guards.journal_problems(SimpleNamespace(CATALYST_ENV=local, CATALYST_EFFECT_JOURNAL_DIR="")) == []
    assert guards.journal_problems(staging(CATALYST_EFFECT_JOURNAL_DIR="")) == ["CATALYST_EFFECT_JOURNAL_DIR must be an absolute path outside test and development"]
    assert guards.journal_problems(staging(CATALYST_EFFECT_JOURNAL_DIR="/var/lib/catalyst/effects")) == []
    for bad in ("effects", "relative/effects", str(__import__("pathlib").Path(guards.__file__).resolve().parent.parent / "x")):
        assert guards.journal_problems(staging(CATALYST_EFFECT_JOURNAL_DIR=bad)), bad
    assert guards.journal_problems(SimpleNamespace(CATALYST_ENV="production", CATALYST_EFFECT_JOURNAL_DIR="")) == [
        "CATALYST_EFFECT_JOURNAL_DIR must be an absolute path outside test and development"]  # 9kg.31.11: admitted


def test_9kg_33_the_fetcher_starts_without_a_journal_and_a_journaling_process_does_not(tmp_path, monkeypatch, settings):
    """9kg.63 (found by the deploy drill): the staging fetcher is a worker with the fetcher role whose journal setting
    names a directory it never mounts; it must start, while a web or worker process with a missing directory is
    refused."""
    missing = str(tmp_path / "effects-none")
    settings.CATALYST_EFFECT_JOURNAL_DIR = missing
    # At start-up the worker command has not declared its kind yet (the check runs in ready()), so it is "management".
    for kind in ("management", "worker"):
        monkeypatch.setattr(guards, "_process_kind", lambda kind=kind: kind)
        assert guards.journal_problems(staging(CATALYST_EFFECT_JOURNAL_DIR=missing, CATALYST_PROCESS_ROLE="fetcher")) == []
    for kind in ("management", "web", "worker"):
        monkeypatch.setattr(guards, "_process_kind", lambda kind=kind: kind)
        assert guards.journal_problems(staging(CATALYST_EFFECT_JOURNAL_DIR=missing, CATALYST_PROCESS_ROLE="")) == [
            "CATALYST_EFFECT_JOURNAL_DIR is missing: a private (0700) directory this process can write"]
    # A web process may not carry the fetcher role at all, so the exemption cannot reach the web path.
    assert guards.process_role_problems(staging(CATALYST_PROCESS_ROLE="fetcher"), "web")
    # And through the whole start-up check (PR #95 release-ops review): a web process claiming the fetcher role with
    # no journal directory is still refused, whatever the journal rule exempts.
    settings.CATALYST_ENV = "staging"
    settings.CATALYST_PROCESS_ROLE = "fetcher"
    monkeypatch.setattr(guards, "_process_kind", lambda: "web")
    assert "the web process may not run as CATALYST_PROCESS_ROLE=fetcher" in guards.all_problems(settings, {})


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



# --- 9kg.49: the production mail-host allow-list and the denied first-generation mailbox ----------------------------

HOST = "mail.synthetic.example.test"
LEGACY_DIGEST = guards.user_digest("legacy-synthetic@example.test")
V2_DIGEST = guards.user_digest("synthetic-user")


def live(**values):
    base = dict(CATALYST_ENV="production", CATALYST_MAIL_HOST=HOST, CATALYST_MAIL_ALLOWED_HOSTS=[HOST],
                CATALYST_PROCESS_ROLE="web", CATALYST_MAIL_TLS="starttls", CATALYST_MAIL_SENT_FOLDER="Sent",
                CATALYST_MAIL_COLLECT_FOLDER="INBOX", CATALYST_MAIL_USER="synthetic-user", CATALYST_MAIL_PASSWORD="x",
                CATALYST_MAIL_USER_SHA256=V2_DIGEST, CATALYST_MAIL_DENIED_USER_SHA256=[LEGACY_DIGEST],
                CATALYST_SEND_EVIDENCE_SOURCE=guards.SENT_FOLDER_SOURCE)
    return SimpleNamespace(**{**base, **values})


def test_9kg_49_the_allow_list_admits_exactly_the_named_host_for_live_web_and_worker_processes():
    for role, ok in (("web", True), ("worker", True), ("fetcher", False), ("", False), ("management", False), ("reconcile", False)):
        assert guards.mail_host_allowed("production", HOST, "", [HOST], role) is ok, role
    for role, ok in (("web", True), ("worker", True), ("reconcile", True), ("fetcher", False), ("management", False)):
        assert guards.mail_host_allowed("production", HOST, "", [HOST], role, purpose="imap") is ok, role  # RD-1: the Sent read
    assert guards.mail_host_allowed("production", HOST.upper(), "", [HOST], "web")  # names compare case-insensitively
    for other in ("other.synthetic.example.test", "127.0.0.1", "", "mail.synthetic.example.test.evil.test"):
        assert not guards.mail_host_allowed("production", other, "", [HOST], "web"), other
    assert not guards.mail_host_allowed("production", HOST, "", [], "web")  # an empty list admits nothing
    assert guards.mail_problems(live()) == []  # the start-up check is configuration only: the kind is checked at use
    assert any("must name the production mail host" in p for p in guards.mail_problems(live(CATALYST_MAIL_ALLOWED_HOSTS=[])))
    assert any("not allowed in a live environment" in p for p in guards.mail_problems(live(CATALYST_MAIL_CA_FILE="/x/ca.pem")))
    assert any("Sent-folder reader in a live" in p for p in guards.mail_problems(live(CATALYST_SEND_EVIDENCE_SOURCE="")))
    for bad in (["127.0.0.1"], ["Mail.Example.Test"], ["mail.example.test;x"], ["mail"], ["mail.example.test\u3002evil"],
                ["mail.example.123"], ["10.0.0.5"]):
        assert any("plain lower-case host names" in p for p in guards.mail_problems(live(CATALYST_MAIL_ALLOWED_HOSTS=bad))), bad
    assert guards.HOST_NAME.fullmatch("mail.synthetic.example.test") and guards.HOST_NAME.fullmatch("mx1.example.t3st")
    # Outside a live environment the list is refused: test, staging and development never leave loopback.
    for environment in ("test", "staging", "development"):
        problems = guards.mail_problems(SimpleNamespace(CATALYST_ENV=environment, CATALYST_MAIL_HOST="127.0.0.1",
                                                        CATALYST_MAIL_ALLOWED_HOSTS=[HOST], CATALYST_MAIL_TLS="none"))
        assert any("allowed only in a live environment" in p for p in problems), environment
        assert not guards.mail_host_allowed(environment, HOST, "", [HOST], "web")
    assert "production" in guards.ALLOWED_ENVIRONMENTS and "production" in guards.LIVE_ENVIRONMENTS  # 9kg.31.11


def test_9kg_49_the_first_generation_mailbox_can_never_be_a_source():
    legacy = "legacy-synthetic@example.test"
    for environment, host in (("test", "127.0.0.1"), ("staging", "127.0.0.1"), ("production", HOST)):
        kwargs = dict(live(CATALYST_ENV=environment, CATALYST_MAIL_HOST=host,
                           CATALYST_MAIL_ALLOWED_HOSTS=[HOST] if environment == "production" else [],
                           CATALYST_SEND_EVIDENCE_SOURCE=guards.SENT_FOLDER_SOURCE if environment == "production" else "",
                           CATALYST_MAIL_TLS="starttls").__dict__)
        for user in (legacy, legacy.upper(), f" {legacy} "):
            problems = guards.mail_problems(SimpleNamespace(**{**kwargs, "CATALYST_MAIL_USER": user}))
            assert any("denied mailbox" in p for p in problems), (environment, user)
            assert legacy not in " ".join(problems)  # the message names no mailbox
        assert not any("denied" in p for p in guards.mail_problems(SimpleNamespace(**{**kwargs, "CATALYST_MAIL_USER": "synthetic-user"})))
    # In a live environment the rule is never opt-in (security review of PR #89): the denied list and the pin are
    # required, digests only, and the login must hash to the pin.
    assert any("must list the first-generation mailbox" in p for p in guards.mail_problems(live(CATALYST_MAIL_DENIED_USER_SHA256=[])))
    assert any("must pin the v2 mailbox" in p for p in guards.mail_problems(live(CATALYST_MAIL_USER_SHA256="")))
    assert any("does not hash to" in p for p in guards.mail_problems(live(CATALYST_MAIL_USER="other-synthetic")))
    assert any("names a denied mailbox" in p for p in guards.mail_problems(live(CATALYST_MAIL_USER_SHA256=LEGACY_DIGEST,
                                                                                 CATALYST_MAIL_USER="legacy-synthetic@example.test")))
    for bad in (["not-a-digest"], ["abcdef" * 10 + "012"]):  # not hex, not 64 characters
        assert any("hex digests only" in p for p in guards.mail_problems(live(CATALYST_MAIL_DENIED_USER_SHA256=bad))), bad
    assert guards.user_pinned(" Synthetic-User ", V2_DIGEST) and not guards.user_pinned("synthetic-user", "")


def test_9kg_49_only_the_sent_folder_reader_is_an_evidence_source_outside_test():
    mail = dict(CATALYST_MAIL_SENT_FOLDER="Sent", CATALYST_MAIL_COLLECT_FOLDER="INBOX", CATALYST_MAIL_TLS="starttls")
    assert guards.mail_problems(staging(CATALYST_SEND_EVIDENCE_SOURCE=guards.SENT_FOLDER_SOURCE, **mail)) == []
    assert any("Sent-folder reader" in p for p in guards.mail_problems(
        staging(CATALYST_SEND_EVIDENCE_SOURCE="tests.smtp_server.ServerEvidence", **mail)))
    assert guards.mail_problems(SimpleNamespace(CATALYST_ENV="test", CATALYST_SEND_EVIDENCE_SOURCE="tests.smtp_server.ServerEvidence",
                                                CATALYST_MAIL_TLS="none")) == []
    assert guards.mail_problems(live(CATALYST_SEND_EVIDENCE_SOURCE="tests.smtp_server.ServerEvidence"))


def test_9kg_49_a_live_peer_must_be_the_allow_listed_host_on_a_global_address(settings, monkeypatch):
    from config import runtime
    from correspondence import transport

    settings.CATALYST_ENV, settings.CATALYST_MAIL_HOST, settings.CATALYST_MAIL_TEST_HOST = "production", HOST, ""
    settings.CATALYST_MAIL_ALLOWED_HOSTS = [HOST]
    settings.CATALYST_MAIL_USER, settings.CATALYST_MAIL_USER_SHA256 = "synthetic-user", V2_DIGEST
    monkeypatch.setitem(runtime._declared, "kind", "web")  # the kind comes from code, never only from the environment
    assert transport.peer_allowed("11.22.33.44") and transport.peer_allowed("2600:1f18:1:2::3")
    for private in ("127.0.0.1", "10.0.0.5", "169.254.1.1", "::1", "224.0.0.1", "not-an-address"):
        assert not transport.peer_allowed(private), private
    monkeypatch.setitem(runtime._declared, "kind", "management")
    assert not transport.peer_allowed("11.22.33.44")  # the kind, not only the host, is part of the rule
    monkeypatch.setitem(runtime._declared, "kind", "reconcile")
    assert transport.peer_allowed("11.22.33.44", "imap") and not transport.peer_allowed("11.22.33.44", "smtp")  # RD-1
    assert transport.send(b"Subject: x\r\n\r\nbody\r\n", "from@example.test", "to@example.test").outcome == "transport_blocked"
    monkeypatch.setitem(runtime._declared, "kind", "web")
    settings.CATALYST_MAIL_HOST = "other.synthetic.example.test"
    assert not transport.peer_allowed("11.22.33.44")
    settings.CATALYST_MAIL_HOST, settings.CATALYST_MAIL_USER_SHA256 = HOST, LEGACY_DIGEST
    assert not transport.mailbox_pinned()  # re-checked before any login, whatever the start-up check saw
    assert transport.send(b"Subject: x\r\n\r\nbody\r\n", "from@example.test", "to@example.test").outcome == "transport_blocked"
    settings.CATALYST_ENV = "test"


# --- 9kg.31.11: production is admitted in code with every live refusal in force ------------------------------------

def production(**overrides):
    values = dict(CATALYST_ENV="production", CATALYST_INTAKE_MODE="invitation",
                  CATALYST_PUBLIC_BASE_URL="https://catalyst-v2.example.test", CATALYST_STAFF_HOST="staff-v2.example.test",
                  ALLOWED_HOSTS=["catalyst-v2.example.test", "staff-v2.example.test", "localhost"],
                  EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend", EMAIL_FILE_PATH="/var/lib/catalyst/mail")
    return SimpleNamespace(**{**values, **overrides})


def test_9kg_31_11_production_keeps_model_advice_fetching_agreements_and_provisioning_off():
    # The QA note on the bead: admission must not open any of the four paths the synthetic environments allow.
    for name, value in (("CATALYST_EVIDENCE_ALLOWED_HOSTS", ["site.example.test"]),
                        ("CATALYST_EVIDENCE_FIXTURE_ADDRESS", "127.0.0.1"), ("CATALYST_EVIDENCE_CA_FILE", "/ca.pem")):
        assert any("synthetic evidence only" in p for p in guards.evidence_problems(production(**{name: value}), {})), name
    assert any("allowed only in the test and staging" in p
               for p in guards.assessment_problems(production(CATALYST_ASSESSMENT_MODEL="test"), {}))
    for mode in ("minimax", "live", "openai:gpt"):
        assert any("live model use is not authorized" in p
                   for p in guards.assessment_problems(production(CATALYST_ASSESSMENT_MODEL=mode), {})), mode
    for name in guards.AGREEMENT_TEST_ONLY:
        assert any("synthetic agreements only" in p for p in guards.agreement_problems(production(**{name: "x"}), {})), name
    for name, value in (("CATALYST_PROVISIONING_ADAPTER", "provisioning.live.Adapter"),
                        ("CATALYST_PROVISIONING_DOMAIN", "intentsolutions.io")):
        assert any("synthetic provisioning only" in p
                   for p in guards.provisioning_problems(production(**{name: value}), {})), name
    # None of them may arrive through the environment either, and no provider credential may be present.
    environ = {name: "x" for name in (*guards.EVIDENCE_TEST_ONLY, *guards.AGREEMENT_TEST_ONLY,
                                       *guards.PROVISIONING_TEST_ONLY, "CATALYST_ASSESSMENT_MODEL")}
    found = (guards.evidence_problems(production(), environ) + guards.agreement_problems(production(), environ)
             + guards.provisioning_problems(production(), environ) + guards.assessment_problems(production(), environ))
    assert sum("may not be set from the environment" in p for p in found) == len(environ)
    assert guards.provider_problems("django.core.mail.backends.filebased.EmailBackend",
                                    {"MINIMAX_API_KEY": "x", "DOCUMENSO_TOKEN": "y"})
    assert guards.provider_problems("django.core.mail.backends.smtp.EmailBackend", {})  # Django's mailer stays a sink
    # With none of them set, the four checks are quiet: admission alone opens nothing and refuses nothing.
    quiet = production()
    assert guards.evidence_problems(quiet, {}) == guards.agreement_problems(quiet, {}) == []
    assert guards.provisioning_problems(quiet, {}) == []
    assert guards.assessment_problems(SimpleNamespace(**{**vars(quiet), "CATALYST_ASSESSMENT_MODEL": "none"}), {}) == []


def test_9kg_31_11_production_runs_invitation_only_on_its_own_host():
    assert guards.live_problems(production()) == []
    assert any("must be 'invitation'" in p for p in guards.live_problems(production(CATALYST_INTAKE_MODE="open")))
    for base in ("", "http://catalyst-v2.example.test", "https://"):
        assert any("must be https on the dedicated v2 host" in p
                   for p in guards.live_problems(production(CATALYST_PUBLIC_BASE_URL=base))), base
    for learn in ("learn.intentsolutions.io", "LEARN.intentsolutions.io.", "x.learn.intentsolutions.io"):
        for field in ("CATALYST_PUBLIC_BASE_URL", "CATALYST_STAFF_HOST", "ALLOWED_HOSTS"):
            value = {"CATALYST_PUBLIC_BASE_URL": f"https://{learn}", "CATALYST_STAFF_HOST": learn,
                     "ALLOWED_HOSTS": ["catalyst-v2.example.test", learn]}[field]
            assert any("GATE-CUTOVER" in p for p in guards.live_problems(production(**{field: value}))), (learn, field)
    for wild in ("*", ".", ".example.test", "cat\u2024alyst.example.test"):
        assert any("wildcard" in p for p in guards.live_problems(production(ALLOWED_HOSTS=[wild]))), wild
    # Staging is not a live environment: these rails are production's own (staging has its own host rules).
    assert guards.live_problems(SimpleNamespace(CATALYST_ENV="staging", CATALYST_INTAKE_MODE="open")) == []


def test_9kg_31_11_production_never_prints_mail_and_keeps_its_sink_private():
    console = production(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
    console.CATALYST_MAIL_TLS, console.CATALYST_MAIL_HOST = "starttls", ""
    assert any("console mail backend is not allowed in production" in p for p in guards.mail_problems(console))
    relative = production(EMAIL_FILE_PATH="mail")
    relative.CATALYST_MAIL_TLS, relative.CATALYST_MAIL_HOST = "starttls", ""
    assert any("production's file mail sink needs an absolute EMAIL_FILE_PATH" in p for p in guards.mail_problems(relative))


def test_9kg_31_11_production_is_a_deployment_for_every_deployment_rule():
    bare = production(CATALYST_STAFF_HOST="")
    assert "CATALYST_STAFF_HOST is required outside test and development" in guards.host_problems(bare)
    assert any("CATALYST_SECRETS_DIR must be an absolute path" in p for p in guards.secret_problems(production(), {}))
    assert any("CATALYST_SECRET_KEY may not be in the environment" in p
               for p in guards.secret_problems(production(CATALYST_SECRETS_DIR="/run/secrets"), {"CATALYST_SECRET_KEY": "x"}))
    assert guards.intake_problems(production(CATALYST_CLIENT_IDENTITY="direct"), {})  # behind the proxy only
