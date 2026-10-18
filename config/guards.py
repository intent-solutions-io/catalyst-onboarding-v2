"""Start-up guards for Catalyst v2 (005 S1.5; REQ-021, REQ-022).

Pure functions so they can be unit tested. ``config.apps.CatalystConfig.ready()`` raises when any of
them reports a problem, so every process (web server, management command, future worker) refuses to
start; the same functions back a system check for ``manage.py check`` output.
"""

import re
import ipaddress
from urllib.parse import urlsplit
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
    sent, collected = getattr(settings, "CATALYST_MAIL_SENT_FOLDER", ""), getattr(settings, "CATALYST_MAIL_COLLECT_FOLDER", "INBOX")
    if sent and sent == collected:
        problems.append("CATALYST_MAIL_SENT_FOLDER must differ from CATALYST_MAIL_COLLECT_FOLDER (016 3.6)")
    tls = getattr(settings, "CATALYST_MAIL_TLS", "starttls")
    if tls not in ("starttls", "none"):
        problems.append("CATALYST_MAIL_TLS must be 'starttls' or 'none'")
    elif tls == "none" and host and not is_loopback_literal(host):
        problems.append("CATALYST_MAIL_TLS=none is allowed only for a loopback mail host")
    return problems


DISPATCH_SETTINGS = ("CATALYST_ATTENTION_OPENER", "CATALYST_ACTION_HANDLERS", "CATALYST_REPLY_INTERPRETER",
                     "CATALYST_ANSWERS_CONFIRMED_HOOK", "CATALYST_REPLY_INTERPRETATION_ACTIVATION")


def dispatch_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """The two dotted-path settings that load code (2B.3) are fixed in code: never from the environment, and
    only into the Catalyst apps that own them, so a typo or override fails at start-up, not mid-submission."""
    problems = [f"{name} may not be set from the environment" for name in DISPATCH_SETTINGS if name in environ]
    opener = getattr(settings, "CATALYST_ATTENTION_OPENER", None)
    if opener is not None and not str(opener).startswith("correspondence."):
        problems.append("CATALYST_ATTENTION_OPENER must name a correspondence function")
    for name in ("CATALYST_REPLY_INTERPRETER", "CATALYST_ANSWERS_CONFIRMED_HOOK"):  # P3 3B.3
        path = getattr(settings, name, None)
        if path is not None and not str(path).startswith("assessments."):
            problems.append(f"{name} must name an assessments object")
    for kind, path in (getattr(settings, "CATALYST_ACTION_HANDLERS", None) or {}).items():
        if not str(path).startswith(("correspondence.", "workflow.", "assessments.", "agreements.")):
            problems.append(f"CATALYST_ACTION_HANDLERS[{kind!r}] must name a correspondence, workflow, assessments or agreements handler")
    return problems


EVIDENCE_TEST_ONLY = ("CATALYST_EVIDENCE_ALLOWED_HOSTS", "CATALYST_EVIDENCE_FIXTURE_ADDRESS", "CATALYST_EVIDENCE_CA_FILE")


def evidence_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """018 3.3 step 7 (P3 3B.1): evidence fetching is synthetic only. Outside `test`, no host may be fetchable, no
    fixture address may be pinned and no custom trust store may be set; none of them may come from the
    environment."""
    problems = [f"{name} may not be set from the environment" for name in EVIDENCE_TEST_ONLY if name in environ]
    if getattr(settings, "CATALYST_ENV", "") != "test":
        for name in EVIDENCE_TEST_ONLY:
            if getattr(settings, name, None):
                problems.append(f"{name} is allowed only in the test environment (synthetic evidence only)")
    return problems


def assessment_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """018 5.5 (P3 3B.2): no live model anywhere. "test" (a PydanticAI test model) only in the test environment;
    every other environment must say "none"; never from the environment."""
    problems = ["CATALYST_ASSESSMENT_MODEL may not be set from the environment"] if "CATALYST_ASSESSMENT_MODEL" in environ else []
    mode = getattr(settings, "CATALYST_ASSESSMENT_MODEL", "none")
    if mode not in ("none", "test"):
        problems.append("CATALYST_ASSESSMENT_MODEL must be 'none' or 'test'; live model use is not authorized")
    elif mode == "test" and getattr(settings, "CATALYST_ENV", "") != "test":
        problems.append("CATALYST_ASSESSMENT_MODEL 'test' is allowed only in the test environment")
    return problems


def decision_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """018 section 7 (P3 3B.4): the decision authority and the selection policy are fixed in code, never taken from
    the environment; the authority is None (POL-05 undecided) or the one rule the code implements."""
    problems = [f"{name} may not be set from the environment" for name in
                ("CATALYST_QUALIFICATION_AUTHORITY", "CATALYST_SELECTION_POLICY") if name in environ]
    if getattr(settings, "CATALYST_QUALIFICATION_AUTHORITY", None) not in (None, "explicit_permission"):
        problems.append("CATALYST_QUALIFICATION_AUTHORITY must be None or 'explicit_permission'")
    policy = getattr(settings, "CATALYST_SELECTION_POLICY", "")
    if policy and not re.fullmatch(r"SP-[A-Z0-9]{1,8}-[0-9]{1,4}", policy):
        problems.append("CATALYST_SELECTION_POLICY must be empty or an SP-<role>-<n> identifier (019 section 6)")
    return problems


AGREEMENT_TEST_ONLY = ("CATALYST_AGREEMENT_PROVIDER_URL", "CATALYST_AGREEMENT_PROVIDER_ADDRESS",
                       "CATALYST_AGREEMENT_PROVIDER_CA_FILE", "CATALYST_AGREEMENT_PROVIDER_TOKEN",
                       "CATALYST_AGREEMENT_WEBHOOK_SECRETS", "CATALYST_AGREEMENT_STORAGE_DIR",
                       "CATALYST_AGREEMENT_REQUIRED_DETAILS")


def agreement_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """021 section 10 (P4 4B.1; TEST-P4-20): no real Documenso. The provider URL, its pinned address, the trust store
    and the token are fixed in code, never from the environment, and empty outside `test`. In `test` the URL must be
    https and the pinned address a literal loopback address, so only the local fake can answer."""
    problems = [f"{name} may not be set from the environment" for name in AGREEMENT_TEST_ONLY if name in environ]
    if getattr(settings, "CATALYST_ENV", "") != "test":
        for name in AGREEMENT_TEST_ONLY:
            if getattr(settings, name, ""):
                problems.append(f"{name} is allowed only in the test environment (synthetic agreements only)")
        return problems
    url = getattr(settings, "CATALYST_AGREEMENT_PROVIDER_URL", "")
    if url:
        if not url.startswith("https://"):
            problems.append("CATALYST_AGREEMENT_PROVIDER_URL must be https")
        host = (urlsplit(url).hostname or "") if url.startswith("https://") else ""
        if not host.endswith(".test"):  # a reserved test name, so a loopback forward to a real host cannot pass
            problems.append("CATALYST_AGREEMENT_PROVIDER_URL must name a .test host")
        if not is_loopback_literal(getattr(settings, "CATALYST_AGREEMENT_PROVIDER_ADDRESS", "")):
            problems.append("CATALYST_AGREEMENT_PROVIDER_ADDRESS must be a literal loopback address")
    storage = getattr(settings, "CATALYST_AGREEMENT_STORAGE_DIR", "")
    if storage:
        from pathlib import Path

        repository = Path(__file__).resolve().parent.parent
        target = Path(storage).resolve()
        if not Path(storage).is_absolute() or target == repository or repository in target.parents:
            problems.append("CATALYST_AGREEMENT_STORAGE_DIR must be an absolute path outside the repository")
    if len(getattr(settings, "CATALYST_AGREEMENT_WEBHOOK_SECRETS", []) or []) > 2:
        problems.append("CATALYST_AGREEMENT_WEBHOOK_SECRETS holds at most two secrets (one rotation, P4-D-17)")
    return problems


def all_problems(settings, environ: Mapping[str, str]) -> list[str]:
    return (
        database_problems(settings.DATABASES)
        + environment_problems(settings.CATALYST_ENV)
        + provider_problems(settings.EMAIL_BACKEND, environ)
        + mail_problems(settings)
        + dispatch_problems(settings, environ)
        + evidence_problems(settings, environ)
        + assessment_problems(settings, environ)
        + decision_problems(settings, environ)
        + agreement_problems(settings, environ)
    )
