"""Start-up guards for Catalyst v2 (005 S1.5; REQ-021, REQ-022).

Pure functions so they can be unit tested. ``config.apps.CatalystConfig.ready()`` raises when any of
them reports a problem, so every process (web server, management command, future worker) refuses to
start; the same functions back a system check for ``manage.py check`` output.
"""

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


def all_problems(settings, environ: Mapping[str, str]) -> list[str]:
    return (
        database_problems(settings.DATABASES)
        + environment_problems(settings.CATALYST_ENV)
        + provider_problems(settings.EMAIL_BACKEND, environ)
    )
