"""Start-up guards for Catalyst v2 (005 S1.5; REQ-021, REQ-022).

Pure functions so they can be unit tested. ``config.apps.CatalystConfig.ready()`` raises when any of
them reports a problem, so every process (web server, management command, future worker) refuses to
start; the same functions back a system check for ``manage.py check`` output.
"""

import ipaddress
from collections.abc import Mapping

POSTGRESQL_ENGINE = "django.db.backends.postgresql"

# Environments this skeleton may run in. Production settings are not authorized before phase P6.
ALLOWED_ENVIRONMENTS = frozenset({"development", "test"})

# Mail backends that never leave the process or the local disk.
SINK_EMAIL_BACKENDS = frozenset({
    "django.core.mail.backends.locmem.EmailBackend",
    "django.core.mail.backends.console.EmailBackend",
    "django.core.mail.backends.filebased.EmailBackend",
})

# Catalyst's own providers (D-04 to D-08): any variable with these prefixes is refused.
PROVIDER_ENV_PREFIXES = ("MINIMAX_", "DOCUMENSO_", "TWENTY_", "MXROUTE_", "SMTP_", "EMAIL_HOST")

# Other model-provider and telemetry credential or export settings, refused by exact name (owner
# decision 2026-10-10). Exact names, not prefixes, so harmless vendor-named variables still pass. The
# guard only stops a Catalyst process from starting; it never changes the developer's environment or
# any other tool's credentials, and Catalyst processes receive an explicit synthetic environment.
PROVIDER_ENV_NAMES = frozenset({
    "OPENAI_API_KEY", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID", "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "LOGFIRE_TOKEN", "LOGFIRE_SEND_TO_LOGFIRE",
    "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
    "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
})


def database_problems(databases: Mapping) -> list[str]:
    """A default database must exist and every database must be PostgreSQL (ADR-02, D-02); no silent
    SQLite fallback and no Django dummy backend."""
    problems = [] if "default" in databases else ["no 'default' database is configured"]
    return problems + [
        f"database {alias!r} uses {config.get('ENGINE')!r}; only {POSTGRESQL_ENGINE!r} is allowed"
        for alias, config in databases.items()
        if config.get("ENGINE") != POSTGRESQL_ENGINE
    ]


def environment_problems(environment: str) -> list[str]:
    if environment not in ALLOWED_ENVIRONMENTS:
        return [f"CATALYST_ENV={environment!r} is not allowed; use one of {sorted(ALLOWED_ENVIRONMENTS)}"]
    return []


def provider_problems(email_backend: str, environ: Mapping[str, str]) -> list[str]:
    """Outside production nothing may reach a real provider (REQ-022, D-10)."""
    problems = []
    if email_backend not in SINK_EMAIL_BACKENDS:
        problems.append(f"EMAIL_BACKEND {email_backend!r} is not a local sink backend")
    leaked = sorted(
        name for name in environ if name.startswith(PROVIDER_ENV_PREFIXES) or name in PROVIDER_ENV_NAMES
    )
    if leaked:
        # Report names only, never values.
        problems.append(f"provider credential variables are set: {', '.join(leaked)}")
    return problems


def is_loopback_literal(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def mail_host_allowed(environment: str, host: str, test_host: str) -> bool:
    """016 section 6, A-4 (D-28, amends REQ-022): a literal loopback address in `development` and `test`,
    or, in `test` only, the one named test-service host. Names other than that one are refused, so a
    real provider can never be configured outside production."""
    if environment not in ALLOWED_ENVIRONMENTS:
        return False
    if is_loopback_literal(host):
        return True
    return environment == "test" and bool(test_host) and host == test_host


def mail_problems(settings) -> list[str]:
    host = getattr(settings, "CATALYST_MAIL_HOST", "")
    test_host = getattr(settings, "CATALYST_MAIL_TEST_HOST", "")
    problems = []
    if test_host and settings.CATALYST_ENV != "test":
        problems.append("CATALYST_MAIL_TEST_HOST is allowed only in the test environment")
    if host and not mail_host_allowed(settings.CATALYST_ENV, host, test_host):
        problems.append("CATALYST_MAIL_HOST must be a literal loopback address (or the named test host in test)")
    if (getattr(settings, "CATALYST_MAIL_USER", "") or getattr(settings, "CATALYST_MAIL_PASSWORD", "")) and (
            not host or not mail_host_allowed(settings.CATALYST_ENV, host, test_host)):
        problems.append("mail credentials are set without an allowed local mail host")
    if getattr(settings, "CATALYST_SEND_EVIDENCE_SOURCE", "") and settings.CATALYST_ENV != "test":
        # 016 A5 and 8.3: no evidence source is admissible until a separately authorized provider check.
        problems.append("CATALYST_SEND_EVIDENCE_SOURCE is allowed only in the test environment")
    tls = getattr(settings, "CATALYST_MAIL_TLS", "starttls")
    if tls not in ("starttls", "none"):
        problems.append("CATALYST_MAIL_TLS must be 'starttls' or 'none'")
    elif tls == "none" and host and not is_loopback_literal(host):
        problems.append("CATALYST_MAIL_TLS=none is allowed only for a loopback mail host")
    return problems


def all_problems(settings, environ: Mapping[str, str]) -> list[str]:
    return (
        database_problems(settings.DATABASES)
        + environment_problems(settings.CATALYST_ENV)
        + provider_problems(settings.EMAIL_BACKEND, environ)
        + mail_problems(settings)
    )
