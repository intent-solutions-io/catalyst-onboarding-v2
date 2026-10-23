"""Start-up guards for Catalyst v2 (005 S1.5; REQ-021, REQ-022).

Pure functions so they can be unit tested. ``config.apps.CatalystConfig.ready()`` raises when any of
them reports a problem, so every process (web server, management command, future worker) refuses to
start; the same functions back a system check for ``manage.py check`` output.
"""

import ipaddress
import re
from urllib.parse import urlsplit
from collections.abc import Mapping

POSTGRESQL_ENGINE = "django.db.backends.postgresql"

# The secrets Catalyst reads (6B.5, 026 section 5): one list, used by settings to read them and by the guards to refuse
# them in the environment outside test and development.
SECRET_ENV_NAMES = ("CATALYST_SECRET_KEY", "CATALYST_VERIFICATION_KEY", "CATALYST_VERIFICATION_FALLBACK_KEYS",
                    "CATALYST_DB_PASSWORD", "CATALYST_MAIL_PASSWORD")

# Environments Catalyst may run in. `staging` (026 P6-D-2, D-49) is synthetic like `test`: the same fakes under the
# same strict rules, never a real provider. Production settings are not authorized (a later P6 decision).
ALLOWED_ENVIRONMENTS = frozenset({"development", "test", "staging"})
SYNTHETIC_ENVIRONMENTS = frozenset({"test", "staging"})


def synthetic(environment: str) -> bool:
    """True where the synthetic fakes may be configured: `test` and `staging`, under identical rules (026 section 3:
    the staging fakes share the worker's network namespace, so every loopback-only rule holds unchanged)."""
    return environment in SYNTHETIC_ENVIRONMENTS

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
    """016 section 6, A-4 (D-28, amends REQ-022): a literal loopback address in `development`, `test` and `staging`,
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
    if settings.CATALYST_ENV == "staging":
        # 6B.1 review: messages carry bearer links, so staging never prints them (the console backend writes to
        # stdout, which is the container log); the file sink needs a private absolute directory.
        backend = getattr(settings, "EMAIL_BACKEND", "")
        if backend == "django.core.mail.backends.console.EmailBackend":
            problems.append("the console mail backend is not allowed in staging (it writes links to the logs)")
        path = getattr(settings, "EMAIL_FILE_PATH", None) or ""
        if backend == "django.core.mail.backends.filebased.EmailBackend" and not str(path).startswith("/"):
            problems.append("staging's file mail sink needs an absolute EMAIL_FILE_PATH")
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
        if not str(path).startswith(("correspondence.", "workflow.", "assessments.", "agreements.", "provisioning.",
                                     "accounts.")):  # accounts: the session clean-up (6B.9)
            problems.append(f"CATALYST_ACTION_HANDLERS[{kind!r}] must name a correspondence, workflow, assessments, "
                            "agreements, provisioning or accounts handler")
    return problems


EVIDENCE_TEST_ONLY = ("CATALYST_EVIDENCE_ALLOWED_HOSTS", "CATALYST_EVIDENCE_FIXTURE_ADDRESS", "CATALYST_EVIDENCE_CA_FILE")


def evidence_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """018 3.3 step 7 (P3 3B.1): evidence fetching is synthetic only. Outside `test`, no host may be fetchable, no
    fixture address may be pinned and no custom trust store may be set; none of them may come from the
    environment."""
    problems = [f"{name} may not be set from the environment" for name in EVIDENCE_TEST_ONLY if name in environ]
    environment = getattr(settings, "CATALYST_ENV", "")
    if not synthetic(environment):
        for name in EVIDENCE_TEST_ONLY:
            if getattr(settings, name, None):
                problems.append(f"{name} is allowed only in the test and staging environments (synthetic evidence only)")
    elif environment == "staging":  # staging gets no wider than test's fixtures: reserved names, loopback, an absolute path
        if any(not str(host).lower().endswith(".test") for host in getattr(settings, "CATALYST_EVIDENCE_ALLOWED_HOSTS", ()) or ()):
            problems.append("CATALYST_EVIDENCE_ALLOWED_HOSTS may name only .test hosts in staging")
        address = getattr(settings, "CATALYST_EVIDENCE_FIXTURE_ADDRESS", "")
        if address and not is_loopback_literal(address):
            problems.append("CATALYST_EVIDENCE_FIXTURE_ADDRESS must be a literal loopback address in staging")
        ca = getattr(settings, "CATALYST_EVIDENCE_CA_FILE", "")
        if ca and not str(ca).startswith("/"):
            problems.append("CATALYST_EVIDENCE_CA_FILE must be an absolute path")
    return problems


def assessment_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """018 5.5 (P3 3B.2): no live model anywhere. "test" (a PydanticAI test model) only in the test environment;
    every other environment must say "none"; never from the environment."""
    problems = ["CATALYST_ASSESSMENT_MODEL may not be set from the environment"] if "CATALYST_ASSESSMENT_MODEL" in environ else []
    mode = getattr(settings, "CATALYST_ASSESSMENT_MODEL", "none")
    if mode not in ("none", "test"):
        problems.append("CATALYST_ASSESSMENT_MODEL must be 'none' or 'test'; live model use is not authorized")
    elif mode == "test" and not synthetic(getattr(settings, "CATALYST_ENV", "")):
        problems.append("CATALYST_ASSESSMENT_MODEL 'test' is allowed only in the test and staging environments")
    return problems


def decision_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """018 section 7 (P3 3B.4): the selection policy is fixed in code, never taken from the environment; the decision
    authority is configuration (9kg.30) but takes only "explicit_permission", the one rule the code implements, or
    stays unset (POL-05 undecided: everyone refused)."""
    problems = ["CATALYST_SELECTION_POLICY may not be set from the environment"] if "CATALYST_SELECTION_POLICY" in environ else []
    if getattr(settings, "CATALYST_QUALIFICATION_AUTHORITY", None) not in (None, "explicit_permission"):
        problems.append("CATALYST_QUALIFICATION_AUTHORITY must be None or 'explicit_permission'")
    policy = getattr(settings, "CATALYST_SELECTION_POLICY", "")
    if policy and not re.fullmatch(r"SP-[A-Z0-9]{1,8}-[0-9]{1,4}", policy):
        problems.append("CATALYST_SELECTION_POLICY must be empty or an SP-<role>-<n> identifier (019 section 6)")
    elif policy:
        # oc4.12 (oc4.10 item 1): a policy labels decisions only when it is bound to the pack it was approved with,
        # and never while that pack's rubric is the synthetic one.
        pack_name = (getattr(settings, "CATALYST_SELECTION_POLICY_PACKS", None) or {}).get(policy)
        if not pack_name:
            problems.append("CATALYST_SELECTION_POLICY is set but CATALYST_SELECTION_POLICY_PACKS does not bind it to a prompt pack")
        else:
            from assessments import pack as packs

            try:
                synthetic = packs.load(pack_name).rubric.get("synthetic", True)
            except packs.PackRefused as exc:
                problems.append(f"CATALYST_SELECTION_POLICY is bound to an unusable prompt pack ({exc})")
            else:
                if synthetic:
                    problems.append("CATALYST_SELECTION_POLICY is bound to a prompt pack whose rubric is synthetic (POL-04)")
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
    if not synthetic(getattr(settings, "CATALYST_ENV", "")):
        for name in AGREEMENT_TEST_ONLY:
            if getattr(settings, name, ""):
                problems.append(f"{name} is allowed only in the test and staging environments (synthetic agreements only)")
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


PROVISIONING_TEST_ONLY = ("CATALYST_PROVISIONING_ADAPTER", "CATALYST_PROVISIONING_DOMAIN")


def provisioning_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """023 sections 3 and 11.1 (P5 5B.1; TEST-P5-23): no real mail host. The adapter and the domain are fixed in code,
    never from the environment, and empty outside `test`. In `test` the adapter must be a test fake and the domain a
    `.test` domain. No live adapter exists; building one is a pre-live gate (D-47)."""
    problems = [f"{name} may not be set from the environment" for name in PROVISIONING_TEST_ONLY if name in environ]
    # No mail-host credential may sit in a web or worker environment (023 11.1): the live key, if ever authorized,
    # belongs to the separate credential service only (security review of PR #53).
    problems += [f"{name} looks like a mail-host credential and may not be in this process's environment"
                 for name in environ if re.search(r"MXROUTE|DIRECTADMIN|X_API_KEY|MAILHOST_(API_)?(KEY|TOKEN)", name.upper())]
    environment = getattr(settings, "CATALYST_ENV", "")
    base = getattr(settings, "CATALYST_PUBLIC_BASE_URL", "")
    if environment not in ("test", "development") and base and not base.startswith("https://"):
        # Setup and confirmation tokens travel in links: outside test and development only https (5B.2 review).
        problems.append("CATALYST_PUBLIC_BASE_URL must be https outside test and development")
    if environment == "staging":
        # PR #59 and #61 reviews: staging must never answer for, or link to, a production host (its links would reach
        # real applicants). Hosts are compared in ASCII form, so look-alike characters cannot slip past.
        if base and _production_host(urlsplit(base).hostname or ""):
            problems.append("CATALYST_PUBLIC_BASE_URL in staging may not name a production host")
        for host in getattr(settings, "ALLOWED_HOSTS", []) or []:
            if host.strip() in ("*", ".") or _production_host(host.strip().lstrip(".")):
                problems.append(f"ALLOWED_HOSTS in staging may not include {host!r}")
    if not synthetic(environment):
        for name in PROVISIONING_TEST_ONLY:
            if getattr(settings, name, ""):
                problems.append(f"{name} is allowed only in the test and staging environments (synthetic provisioning only)")
        return problems
    adapter = getattr(settings, "CATALYST_PROVISIONING_ADAPTER", "")
    if adapter and not adapter.startswith("tests."):
        problems.append("CATALYST_PROVISIONING_ADAPTER must name a test fake")
    domain = getattr(settings, "CATALYST_PROVISIONING_DOMAIN", "")
    if domain and not domain.lower().endswith(".test"):
        problems.append("CATALYST_PROVISIONING_DOMAIN must be a .test domain")
    if getattr(settings, "CATALYST_PROVISIONING_METHOD", "api") not in ("api", "checklist"):
        problems.append("CATALYST_PROVISIONING_METHOD must be api or checklist")
    quota, limit = getattr(settings, "CATALYST_PROVISIONING_QUOTA_MB", 1), getattr(settings, "CATALYST_PROVISIONING_SEND_LIMIT", 1)
    if not (isinstance(quota, int) and quota >= 1):
        problems.append("CATALYST_PROVISIONING_QUOTA_MB must be at least 1 (never unlimited, P5-D-2)")
    if not (isinstance(limit, int) and 1 <= limit <= 9600):
        problems.append("CATALYST_PROVISIONING_SEND_LIMIT must be between 1 and 9600")
    return problems


PRODUCTION_DOMAINS = ("intentsolutions.io",)


def _production_host(host: str) -> bool:
    """True for a production domain or any name under it. A name that is not plain ASCII counts as production:
    look-alike characters (a full-width dot, an ideographic full stop) would map onto the real name."""
    if not host.isascii():
        return True
    host = host.lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in PRODUCTION_DOMAINS)


def host_problems(settings) -> list[str]:
    """PR #62 review: outside the local environments the staff screens need their own host, and neither it nor the
    local health hosts (the proxy's socket) may be the public host, a wildcard or a domain pattern."""
    environment = getattr(settings, "CATALYST_ENV", "")
    if environment not in ALLOWED_ENVIRONMENTS or environment in ("test", "development"):
        return []
    base = getattr(settings, "CATALYST_PUBLIC_BASE_URL", "")
    public = (urlsplit(base).hostname or "").lower().rstrip(".") if base else ""
    staff = (getattr(settings, "CATALYST_STAFF_HOST", "") or "").lower().rstrip(".")
    problems = [] if staff else ["CATALYST_STAFF_HOST is required outside test and development"]
    beat = getattr(settings, "CATALYST_WORKER_HEARTBEAT_FILE", "") or ""
    if not beat.startswith("/"):  # PR #64 review: no deployment without a worker liveness signal
        problems.append("CATALYST_WORKER_HEARTBEAT_FILE must be an absolute path outside test and development")
    for name, hosts in (("CATALYST_STAFF_HOST", [staff] if staff else []),
                        ("CATALYST_LOCAL_HOSTS", getattr(settings, "CATALYST_LOCAL_HOSTS", []) or [])):
        for host in hosts:
            host = host.lower().rstrip(".")
            if host in ("*", "") or host.startswith(".") or (public and host == public):
                problems.append(f"{name} may not be a wildcard, a domain pattern or the public host")
    local = {h.lower().rstrip(".") for h in getattr(settings, "CATALYST_LOCAL_HOSTS", []) or []}
    if staff and staff in local:  # health would then answer on the staff host (PR #63 review)
        problems.append("CATALYST_STAFF_HOST may not also be one of CATALYST_LOCAL_HOSTS")
    return problems


def secret_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """6B.5 (026 section 5, P6-D-6): outside test and development, secrets come only from per-secret files."""
    environment = getattr(settings, "CATALYST_ENV", "")
    if environment == "development" and getattr(settings, "CATALYST_SECRETS_DIR", ""):
        # A process with mounted secrets is a deployment; "development" would switch the guards and the safe mail sink
        # off (PR #65 review).
        return ["CATALYST_ENV=development may not be used with CATALYST_SECRETS_DIR (a deployment must say staging)"]
    if environment not in ALLOWED_ENVIRONMENTS or environment in ("test", "development"):
        return []
    problems = [f"{name} may not be in the environment outside test and development; use CATALYST_SECRETS_DIR"
                for name in SECRET_ENV_NAMES if name in environ]
    if not str(getattr(settings, "CATALYST_SECRETS_DIR", "") or "").startswith("/"):
        problems.append("CATALYST_SECRETS_DIR must be an absolute path outside test and development")
    return problems


PROCESS_ROLES = ("", "web", "worker", "fetcher")


def process_role_problems(settings, kind: str) -> list[str]:
    """PR #65 re-check: the fetcher alone may run without the link-signing key, so the role must be one Catalyst knows,
    may never be claimed by the web process (whose kind is declared in code before Django loads), and any other process
    must hold a key: links signed with an empty key could be forged by anyone."""
    role = getattr(settings, "CATALYST_PROCESS_ROLE", "") or ""
    if role not in PROCESS_ROLES:
        return [f"CATALYST_PROCESS_ROLE must be one of {', '.join(r for r in PROCESS_ROLES if r)}"]
    problems = []
    if role == "fetcher" and kind == "web":
        problems.append("the web process may not run as CATALYST_PROCESS_ROLE=fetcher")
    proxy = str(getattr(settings, "CATALYST_EVIDENCE_PROXY", "") or "")
    if proxy and not re.fullmatch(r"[a-z0-9.-]+:\d{1,5}", proxy):
        problems.append("CATALYST_EVIDENCE_PROXY must be host:port")
    if role == "fetcher" and getattr(settings, "CATALYST_ENV", "") not in ("test", "development") and not proxy:
        # Every environment past the local ones (PR #76 review): the fetcher reaches nothing but the egress proxy.
        problems.append("a fetcher outside test and development needs CATALYST_EVIDENCE_PROXY (the egress proxy)")
    key = getattr(settings, "CATALYST_VERIFICATION_KEY", None)
    if role != "fetcher" and key is not None and not key:
        problems.append("CATALYST_VERIFICATION_KEY may be empty only for the fetcher")
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
        + provisioning_problems(settings, environ)
        + host_problems(settings)
        + secret_problems(settings, environ)
        + process_role_problems(settings, _process_kind())
    )


def _process_kind() -> str:
    from config import runtime

    return runtime.process_kind()
