"""Start-up guards for Catalyst v2 (005 S1.5; REQ-021, REQ-022).

Pure functions so they can be unit tested. ``config.apps.CatalystConfig.ready()`` raises when any of
them reports a problem, so every process (web server, management command, future worker) refuses to
start; the same functions back a system check for ``manage.py check`` output.
"""

import hashlib
import ipaddress
import re
from urllib.parse import urlsplit
from collections.abc import Mapping

from config import parity

POSTGRESQL_ENGINE = "django.db.backends.postgresql"

# The secrets Catalyst reads (6B.5, 026 section 5): one list, used by settings to read them and by the guards to refuse
# them in the environment outside test and development.
SECRET_ENV_NAMES = (
    "CATALYST_SECRET_KEY",
    "CATALYST_VERIFICATION_KEY",
    "CATALYST_VERIFICATION_FALLBACK_KEYS",
    "CATALYST_DB_PASSWORD",
    "CATALYST_MAIL_PASSWORD",
    "CATALYST_ERASURE_KEY",
    "CATALYST_ERASURE_PREVIOUS_KEYS",
    "CATALYST_CUSTODY_WRAPPING_KEY",
    "CATALYST_CUSTODY_NEXT_WRAPPING_KEY",
    "CATALYST_ASSESSMENT_API_KEY",  # bgl.12: the live model key, a file outside test and development
    "CATALYST_TWENTY_TOKEN",
    "CATALYST_AGREEMENT_PROVIDER_TOKEN",
)  # bgl.14: the Twenty token, a file outside test and development

# Environments Catalyst may run in. `staging` (026 P6-D-2, D-49) is synthetic like `test`: the same fakes under the
# same strict rules, never a real provider. `production` (9kg.31.11, 026 section 18) is admitted in code with every
# live refusal in force: it may start, but it reaches no provider the guards below do not name, holds no model, no
# fetchable evidence host (the fetcher runs and refuses every host), no agreement provider and no provisioning adapter,
# and backs up, stores custody or serves a wording only once the owner's decisions are recorded. Starting it on a host
# is a separate, owner-approved act.
ALLOWED_ENVIRONMENTS = frozenset({"development", "test", "staging", "production"})
# Environments that are deployments: secrets from files, https behind the proxy, a journal, a staff host.
DEPLOYED_ENVIRONMENTS = frozenset({"staging", "production"})
SYNTHETIC_ENVIRONMENTS = frozenset({"test", "staging"})


def synthetic(environment: str) -> bool:
    """True where the synthetic fakes may be configured: `test` and `staging`, under identical rules (026 section 3:
    the staging fakes share the worker's network namespace, so every loopback-only rule holds unchanged)."""
    return environment in SYNTHETIC_ENVIRONMENTS


# Environments where an unapproved placeholder wording may be shown to a person, marked as a draft (9kg.52, 030 Q8):
# the local and synthetic ones, listed by name. A live environment is never listed here, so it refuses to serve a
# notice or an invitation whose wording the owner has not approved (applications.notices).
DRAFT_WORDING_ENVIRONMENTS = frozenset({"development", "test", "staging"})


def draft_wording_allowed(environment: str) -> bool:
    return environment in DRAFT_WORDING_ENVIRONMENTS


# Production's Django mailer (config.mail): the transport backend (9kg.77), which sends through correspondence.transport
# only, or the refusing one, an explicit hold. Never a file or console sink with live links, never Django's SMTP backend.
REFUSING_EMAIL_BACKEND = "config.mail.RefusingEmailBackend"
TRANSPORT_EMAIL_BACKEND = "config.mail.TransportEmailBackend"
LIVE_EMAIL_BACKENDS = (TRANSPORT_EMAIL_BACKEND, REFUSING_EMAIL_BACKEND)
# Mail backends that never leave the process or the local disk.
SINK_EMAIL_BACKENDS = frozenset(
    {
        "django.core.mail.backends.locmem.EmailBackend",
        "django.core.mail.backends.console.EmailBackend",
        "django.core.mail.backends.filebased.EmailBackend",
        REFUSING_EMAIL_BACKEND,
    }
)

# Catalyst's own providers (D-04 to D-08): any variable with these prefixes is refused. The first generation's Twenty
# variables (TWENTY_*) stay refused after bgl.14: v2's projection reads only its own CATALYST_TWENTY_* settings, fixed in
# code, and a token file (twenty_problems).
PROVIDER_ENV_PREFIXES = (
    "MINIMAX_",
    "DOCUMENSO_",
    "TWENTY_",
    "MXROUTE_",
    "SMTP_",
    "EMAIL_HOST",
)

# Other model-provider and telemetry credential or export settings, refused by exact name (owner
# decision 2026-10-10). Exact names, not prefixes, so harmless vendor-named variables still pass. The
# guard only stops a Catalyst process from starting; it never changes the developer's environment or
# any other tool's credentials, and Catalyst processes receive an explicit synthetic environment.
PROVIDER_ENV_NAMES = frozenset(
    {
        "OPENAI_API_KEY",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "OPENAI_BASE_URL",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_BASE_URL",
        "LOGFIRE_TOKEN",
        "LOGFIRE_SEND_TO_LOGFIRE",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_HEADERS",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
        "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
        "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT",
        "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
    }
)


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
        return [
            f"CATALYST_ENV={environment!r} is not allowed; use one of {sorted(ALLOWED_ENVIRONMENTS)}"
        ]
    return []


def provider_problems(
    email_backend: str, environ: Mapping[str, str], environment: str = ""
) -> list[str]:
    """No provider credential is in the environment, anywhere (REQ-022, D-10). Django's mailer is a local sink in every
    environment but a live one, where it may also be the transport backend (9kg.77): applicant mail in production
    leaves only through `correspondence.transport` to an allow-listed host (mail_problems)."""
    problems = []
    if email_backend not in SINK_EMAIL_BACKENDS and not (
        environment in LIVE_ENVIRONMENTS and email_backend == TRANSPORT_EMAIL_BACKEND
    ):
        problems.append(f"EMAIL_BACKEND {email_backend!r} is not a local sink backend")
    leaked = sorted(
        name
        for name in environ
        if name.startswith(PROVIDER_ENV_PREFIXES) or name in PROVIDER_ENV_NAMES
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


# 9kg.49: the environments in which the production mail-host allow-list and the other live rules apply. `production` is
# admitted in code (9kg.31.11); starting it on the host stays the owner's go (029 section 13).
LIVE_ENVIRONMENTS = frozenset({"production"})
# The process kinds (config.runtime, declared in code) that may reach the production mail host, per purpose: web and
# worker send and read; the owner-run `reconcile` kind (the post-restore step, RD-1) reads the Sent folder only.
MAIL_KINDS = {
    "smtp": frozenset({"web", "worker"}),
    "imap": frozenset({"web", "worker", "reconcile"}),
}
ANY_KIND = "*"  # the start-up configuration check: the host is listed; the kind is checked at use time
SENT_FOLDER_SOURCE = "correspondence.sent_reader.SentFolderSource"
# A host name: lower-case labels, and a final label with a letter (never an all-digit or address-like name).
HOST_NAME = re.compile(
    r"([a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?\.)+[a-z0-9-]*[a-z][a-z0-9-]*"
)
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
# bgl.6: the one value of CATALYST_MAIL_TAKEOVER, the swap act that clears the first-generation guard (config/settings.py).
MAIL_TAKEOVER_VALUE = "first-generation-poll-stopped"
# bgl.6: a plain mailbox address for the sender settings: one local part and one domain, no display name, comment,
# white space or list separator, so a header built from it names exactly one mailbox.
PLAIN_ADDRESS = re.compile(r"[^@\s<>()\[\]\\,;:\"]+@[^@\s<>()\[\]\\,;:\"]+")
DISPLAY_NAME_MAX = 64


def mail_host_allowed(
    environment: str,
    host: str,
    test_host: str,
    allowed_hosts=(),
    role: str = "",
    purpose: str = "smtp",
) -> bool:
    """016 section 6, A-4 (D-28, amends REQ-022): a literal loopback address in `development`, `test` and `staging`,
    or, in `test` only, the one named test-service host. Names other than that one are refused, so a
    real provider can never be configured in a synthetic environment. 9kg.49: in a live environment, exactly a host named
    in the configured allow-list, for the web and worker kinds (and, for the IMAP Sent read only, the reconcile
    kind); never a fetcher, never a management process."""
    if environment in LIVE_ENVIRONMENTS:
        # The configuration check at start-up (`role` ANY_KIND) asks only whether the host is listed; which process
        # may use it, and for what, is decided at use time from the kind declared in code (transport._host_allowed).
        return (
            bool(host)
            and host.lower() in {h.lower() for h in allowed_hosts}
            and (role == ANY_KIND or role in MAIL_KINDS.get(purpose, frozenset()))
        )
    if environment not in ALLOWED_ENVIRONMENTS:
        return False
    if is_loopback_literal(host):
        return True
    return environment == "test" and bool(test_host) and host == test_host


def user_digest(user: str) -> str:
    return hashlib.sha256((user or "").strip().lower().encode()).hexdigest()


def user_pinned(user: str, pin: str) -> bool:
    return bool(user) and bool(pin) and user_digest(user) == pin.strip().lower()


def mail_allow_list_problems(settings) -> list[str]:
    """9kg.49: the allow-list is exact, non-empty in a live environment, empty everywhere else. A live environment
    also requires the positive pin of the one v2 mailbox login (`CATALYST_MAIL_USER_SHA256`, a 64-hex digest the
    login must hash to) and a non-empty denied list of 64-hex digests (the first-generation mailbox), so the rule is
    never opt-in there (security review of PR #89); a denied login is refused in every environment until the swap
    value lifts the denial (bgl.6, takeover_problems). The digest values are private: never pasted into a pull request
    or a document."""
    environment = getattr(settings, "CATALYST_ENV", "")
    allowed = list(getattr(settings, "CATALYST_MAIL_ALLOWED_HOSTS", []) or [])
    problems = []
    for host in allowed:
        if (
            not isinstance(host, str)
            or not host.isascii()
            or not HOST_NAME.fullmatch(host)
            or is_loopback_literal(host)
        ):
            problems.append(
                "CATALYST_MAIL_ALLOWED_HOSTS entries must be plain lower-case host names, never addresses"
            )
            break
    user = getattr(settings, "CATALYST_MAIL_USER", "") or ""
    pin = str(getattr(settings, "CATALYST_MAIL_USER_SHA256", "") or "").strip().lower()
    denied = [
        str(d).strip().lower()
        for d in (getattr(settings, "CATALYST_MAIL_DENIED_USER_SHA256", []) or [])
    ]
    if any(not SHA256_HEX.fullmatch(d) for d in denied) or (
        pin and not SHA256_HEX.fullmatch(pin)
    ):
        problems.append(
            "CATALYST_MAIL_DENIED_USER_SHA256 and CATALYST_MAIL_USER_SHA256 hold SHA-256 hex digests only"
        )
    if environment in LIVE_ENVIRONMENTS:
        if not allowed:
            problems.append(
                "CATALYST_MAIL_ALLOWED_HOSTS must name the production mail host outside the synthetic environments"
            )
        if not denied:
            problems.append(
                "CATALYST_MAIL_DENIED_USER_SHA256 must list the first-generation mailbox in a live environment"
            )
        if not pin:
            problems.append(
                "CATALYST_MAIL_USER_SHA256 must pin the v2 mailbox login in a live environment"
            )
        elif user and not user_pinned(user, pin):
            problems.append(
                "CATALYST_MAIL_USER does not hash to CATALYST_MAIL_USER_SHA256 (not the pinned v2 mailbox)"
            )
        if (
            pin and pin in denied and not takeover(settings)
        ):  # bgl.6: the swap lifts the denial (takeover_problems)
            problems.append("CATALYST_MAIL_USER_SHA256 names a denied mailbox")
        if getattr(settings, "CATALYST_SEND_EVIDENCE_SOURCE", "") != SENT_FOLDER_SOURCE:
            problems.append(
                "CATALYST_SEND_EVIDENCE_SOURCE must be the Sent-folder reader in a live environment (9kg.49)"
            )
    elif allowed:
        problems.append(
            "CATALYST_MAIL_ALLOWED_HOSTS is allowed only in a live environment (synthetic and development use loopback)"
        )
    if denied and user and user_digest(user) in denied and not takeover(settings):
        problems.append(
            "CATALYST_MAIL_USER is a denied mailbox (the first-generation mailbox is never a v2 source)"
        )
    return problems


def takeover(settings) -> bool:
    """bgl.6: whether this configuration has taken over the first generation's mailbox (the swap act)."""
    return getattr(settings, "CATALYST_MAIL_TAKEOVER", "") == MAIL_TAKEOVER_VALUE


def sender_address(settings) -> str:
    return str(getattr(settings, "DEFAULT_FROM_EMAIL", "") or "").strip().lower()


def takeover_problems(settings) -> list[str]:
    """bgl.6 (034 section 3.2; the owner's answer of 2026-10-31): the swap lifts the first-generation guard, and only
    explicitly: CATALYST_MAIL_TAKEOVER is empty (the denied digests refuse the first generation's login, the default)
    or exactly MAIL_TAKEOVER_VALUE (the denial is lifted; the digests stay configured, so unsetting the value restores
    the refusal). With it, v2 must read the mailbox it sends from: the login, where this process holds one, equals
    CATALYST_FROM_EMAIL, and in a live environment the pin every process holds is that address's digest. Messages
    name settings, never a mailbox."""
    value = getattr(settings, "CATALYST_MAIL_TAKEOVER", "") or ""
    if not value:
        return []
    if value != MAIL_TAKEOVER_VALUE:
        return [
            f"CATALYST_MAIL_TAKEOVER must be empty or exactly {MAIL_TAKEOVER_VALUE!r} (the swap act)"
        ]
    problems = []
    sender = sender_address(settings)
    user = str(getattr(settings, "CATALYST_MAIL_USER", "") or "").strip().lower()
    if user and user != sender:
        problems.append(
            "CATALYST_MAIL_USER must be the CATALYST_FROM_EMAIL mailbox under CATALYST_MAIL_TAKEOVER "
            "(v2 reads the mailbox it sends from)"
        )
    pin = str(getattr(settings, "CATALYST_MAIL_USER_SHA256", "") or "").strip().lower()
    if (
        getattr(settings, "CATALYST_ENV", "") in LIVE_ENVIRONMENTS
        and pin
        and pin != user_digest(sender)
    ):
        problems.append(
            "CATALYST_MAIL_USER_SHA256 must pin the CATALYST_FROM_EMAIL mailbox under CATALYST_MAIL_TAKEOVER"
        )
    return problems


def sender_problems(settings) -> list[str]:
    """bgl.6 (034 rows 10 and 22): the sender headers of every applicant mail. CATALYST_FROM_EMAIL is one plain address;
    the display name, when set, is one short line of printable text that holds no address (no look-alike sender);
    Reply-To, when set, is one plain address, and in a live environment the From address itself, so a reply reaches
    the mailbox v2 reads (the first generation's own rule: Reply-To the same)."""
    problems = []
    sender = str(getattr(settings, "DEFAULT_FROM_EMAIL", "") or "")
    if not PLAIN_ADDRESS.fullmatch(sender):
        problems.append(
            "CATALYST_FROM_EMAIL must be one plain address (the display name is CATALYST_FROM_DISPLAY_NAME)"
        )
    name = str(getattr(settings, "CATALYST_FROM_DISPLAY_NAME", "") or "")
    if name and (
        len(name) > DISPLAY_NAME_MAX
        or not name.isprintable()
        or any(c in name for c in '@<>"\\')
        or name != name.strip()
    ):
        problems.append(
            f"CATALYST_FROM_DISPLAY_NAME must be one line of at most {DISPLAY_NAME_MAX} printable characters "
            "with no address, quote, angle bracket or backslash"
        )
    reply_to = str(getattr(settings, "CATALYST_REPLY_TO", "") or "")
    if reply_to:
        if not PLAIN_ADDRESS.fullmatch(reply_to):
            problems.append("CATALYST_REPLY_TO must be one plain address")
        elif (
            getattr(settings, "CATALYST_ENV", "") in LIVE_ENVIRONMENTS
            and reply_to.lower() != sender.strip().lower()
        ):
            problems.append(
                "CATALYST_REPLY_TO must be the CATALYST_FROM_EMAIL address in a live environment (replies "
                "reach the mailbox v2 reads)"
            )
    return problems


def mail_problems(settings) -> list[str]:
    host = getattr(settings, "CATALYST_MAIL_HOST", "")
    test_host = getattr(settings, "CATALYST_MAIL_TEST_HOST", "")
    allowed = getattr(settings, "CATALYST_MAIL_ALLOWED_HOSTS", []) or []
    role = ANY_KIND
    problems = mail_allow_list_problems(settings) + takeover_problems(settings)
    if test_host and settings.CATALYST_ENV != "test":
        problems.append(
            "CATALYST_MAIL_TEST_HOST is allowed only in the test environment"
        )
    if host and not mail_host_allowed(
        settings.CATALYST_ENV, host, test_host, allowed, role
    ):
        problems.append(
            "CATALYST_MAIL_HOST must be a literal loopback address (or the named test host in test"
            ", or an allow-listed host for a live web or worker process)"
        )
    if (
        getattr(settings, "CATALYST_MAIL_USER", "")
        or getattr(settings, "CATALYST_MAIL_PASSWORD", "")
    ) and (
        not host
        or not mail_host_allowed(settings.CATALYST_ENV, host, test_host, allowed, role)
    ):
        problems.append("mail credentials are set without an allowed local mail host")
    source = getattr(settings, "CATALYST_SEND_EVIDENCE_SOURCE", "")
    if source and source != SENT_FOLDER_SOURCE and settings.CATALYST_ENV != "test":
        # 016 A5 and 8.3; 9kg.49: the read-only Sent reader is the one production source; anything else is test-only.
        problems.append(
            "CATALYST_SEND_EVIDENCE_SOURCE may name only the Sent-folder reader outside the test environment"
        )
    sent, collected = (
        getattr(settings, "CATALYST_MAIL_SENT_FOLDER", ""),
        getattr(settings, "CATALYST_MAIL_COLLECT_FOLDER", "INBOX"),
    )
    if sent and sent == collected:
        problems.append(
            "CATALYST_MAIL_SENT_FOLDER must differ from CATALYST_MAIL_COLLECT_FOLDER (016 3.6)"
        )
    if settings.CATALYST_ENV in DEPLOYED_ENVIRONMENTS:
        # 6B.1 review: messages carry bearer links, so a deployment never prints them (the console backend writes to
        # stdout, which is the container log); the file sink needs a private absolute directory.
        backend = getattr(settings, "EMAIL_BACKEND", "")
        if backend == "django.core.mail.backends.console.EmailBackend":
            problems.append(
                f"the console mail backend is not allowed in {settings.CATALYST_ENV} (it writes links to the logs)"
            )
        path = getattr(settings, "EMAIL_FILE_PATH", None) or ""
        if backend == "django.core.mail.backends.filebased.EmailBackend" and not str(
            path
        ).startswith("/"):
            problems.append(
                f"{settings.CATALYST_ENV}'s file mail sink needs an absolute EMAIL_FILE_PATH"
            )
    tls = getattr(settings, "CATALYST_MAIL_TLS", "starttls")
    if tls not in ("starttls", "none"):
        problems.append("CATALYST_MAIL_TLS must be 'starttls' or 'none'")
    elif tls == "none" and host and not is_loopback_literal(host):
        problems.append(
            "CATALYST_MAIL_TLS=none is allowed only for a loopback mail host"
        )
    if settings.CATALYST_ENV in LIVE_ENVIRONMENTS and getattr(
        settings, "CATALYST_MAIL_CA_FILE", ""
    ):
        problems.append(
            "CATALYST_MAIL_CA_FILE (a replaced trust store) is not allowed in a live environment"
        )
    return problems


DISPATCH_SETTINGS = (
    "CATALYST_ATTENTION_OPENER",
    "CATALYST_ACTION_HANDLERS",
    "CATALYST_REPLY_INTERPRETER",
    "CATALYST_ANSWERS_CONFIRMED_HOOK",
    "CATALYST_REPLY_INTERPRETATION_ACTIVATION",
    "CATALYST_FOREIGN_THREAD_RESOLVER",
)
# bgl.6: the one module that may resolve replies to first-generation threads (config/settings.py), and only with its app
# installed; tests name their own fake under `tests.`.
FOREIGN_THREAD_RESOLVER = "firstgen.threads"


def dispatch_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """The two dotted-path settings that load code (2B.3) are fixed in code: never from the environment, and
    only into the Catalyst apps that own them, so a typo or override fails at start-up, not mid-submission."""
    problems = [
        f"{name} may not be set from the environment"
        for name in DISPATCH_SETTINGS
        if name in environ
    ]
    opener = getattr(settings, "CATALYST_ATTENTION_OPENER", None)
    if opener is not None and not str(opener).startswith("correspondence."):
        problems.append("CATALYST_ATTENTION_OPENER must name a correspondence function")
    for name in (
        "CATALYST_REPLY_INTERPRETER",
        "CATALYST_ANSWERS_CONFIRMED_HOOK",
    ):  # P3 3B.3
        path = getattr(settings, name, None)
        if path is not None and not str(path).startswith("assessments."):
            problems.append(f"{name} must name an assessments object")
    for kind, path in (
        getattr(settings, "CATALYST_ACTION_HANDLERS", None) or {}
    ).items():
        if not str(path).startswith(
            (
                "correspondence.",
                "workflow.",
                "assessments.",
                "agreements.",
                "provisioning.",
                "accounts.",
                "crm.",
            )
        ):  # accounts: the session clean-up (6B.9); crm: bgl.14
            problems.append(
                f"CATALYST_ACTION_HANDLERS[{kind!r}] must name a correspondence, workflow, assessments, "
                "agreements, provisioning, accounts or crm handler"
            )
    resolver = str(getattr(settings, "CATALYST_FOREIGN_THREAD_RESOLVER", "") or "")
    installed = list(getattr(settings, "INSTALLED_APPS", []) or [])
    if resolver and not (
        (resolver == FOREIGN_THREAD_RESOLVER and "firstgen" in installed)
        or (
            resolver.startswith("tests.")
            and getattr(settings, "CATALYST_ENV", "") == "test"
        )
    ):
        problems.append(
            f"CATALYST_FOREIGN_THREAD_RESOLVER must be empty or {FOREIGN_THREAD_RESOLVER!r} with its app installed"
        )
    return problems


EVIDENCE_TEST_ONLY = (
    "CATALYST_EVIDENCE_ALLOWED_HOSTS",
    "CATALYST_EVIDENCE_FIXTURE_ADDRESS",
    "CATALYST_EVIDENCE_CA_FILE",
)


def evidence_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """018 3.3 step 7 (P3 3B.1): evidence fetching is synthetic only. Outside `test` and `staging`, no host may be
    fetchable, no fixture address may be pinned and no custom trust store may be set; in `staging` only `.test` hosts,
    a loopback fixture address and an absolute trust-store path; none of them may come from the environment."""
    problems = [
        f"{name} may not be set from the environment"
        for name in EVIDENCE_TEST_ONLY
        if name in environ
    ]
    environment = getattr(settings, "CATALYST_ENV", "")
    if not synthetic(environment):
        for name in EVIDENCE_TEST_ONLY:
            if getattr(settings, name, None):
                problems.append(
                    f"{name} is allowed only in the test and staging environments (synthetic evidence only)"
                )
    elif (
        environment == "staging"
    ):  # staging gets no wider than test's fixtures: reserved names, loopback, an absolute path
        if any(
            not str(host).lower().endswith(".test")
            for host in getattr(settings, "CATALYST_EVIDENCE_ALLOWED_HOSTS", ()) or ()
        ):
            problems.append(
                "CATALYST_EVIDENCE_ALLOWED_HOSTS may name only .test hosts in staging"
            )
        address = getattr(settings, "CATALYST_EVIDENCE_FIXTURE_ADDRESS", "")
        if address and not is_loopback_literal(address):
            problems.append(
                "CATALYST_EVIDENCE_FIXTURE_ADDRESS must be a literal loopback address in staging"
            )
        ca = getattr(settings, "CATALYST_EVIDENCE_CA_FILE", "")
        if ca and not str(ca).startswith("/"):
            problems.append("CATALYST_EVIDENCE_CA_FILE must be an absolute path")
    return problems


# bgl.12: the settings that reach a live model, allowed only in the synthetic environments and only under the activation.
LIVE_MODEL_TEST_ONLY = (
    "CATALYST_ASSESSMENT_LIVE_BASE_URL",
    "CATALYST_ASSESSMENT_API_KEY",
)
CODE_FIXED_ASSESSMENT = (
    "CATALYST_ASSESSMENT_MODEL",
    "CATALYST_ASSESSMENT_LIVE_ACTIVATION",
    "CATALYST_ROUTINE_ADVANCE_ACTIVATION",
)


def assessment_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """018 5.5 (P3 3B.2) and bgl.12: "test" (a PydanticAI test model) only in the test and staging environments; a live
    value "<provider>:<model id>" only there too, and only with CATALYST_ASSESSMENT_LIVE_ACTIVATION on; every other
    environment must say "none". The live base URL and key are allowed only in those environments, and none of the
    model, the activations or the routine policy's activation may come from the environment."""
    problems = [
        f"{name} may not be set from the environment"
        for name in CODE_FIXED_ASSESSMENT
        if name in environ
    ]
    mode = getattr(settings, "CATALYST_ASSESSMENT_MODEL", "none")
    environment = getattr(settings, "CATALYST_ENV", "")
    live_activation = int(
        getattr(settings, "CATALYST_ASSESSMENT_LIVE_ACTIVATION", 0) or 0
    )
    if mode == "test":
        if not synthetic(environment):
            problems.append(
                "CATALYST_ASSESSMENT_MODEL 'test' is allowed only in the test and staging environments"
            )
    elif mode != "none":
        from assessments.approval import parse_model

        if (
            parse_model(mode) is None
            or not (synthetic(environment) or parity.enabled(settings))
            or live_activation < 1
        ):
            problems.append(
                "CATALYST_ASSESSMENT_MODEL must be 'none' or 'test', or name '<provider>:<model id>' in a synthetic "
                "environment with CATALYST_ASSESSMENT_LIVE_ACTIVATION on; live model use is not authorized here"
            )
    if not synthetic(environment) and not parity.enabled(settings):
        for name in LIVE_MODEL_TEST_ONLY:
            if getattr(settings, name, ""):
                problems.append(
                    f"{name} is allowed only in the test and staging environments (no live model elsewhere)"
                )
        if live_activation >= 1:
            problems.append(
                "CATALYST_ASSESSMENT_LIVE_ACTIVATION is allowed only in the test and staging environments"
            )
    url = getattr(settings, "CATALYST_ASSESSMENT_LIVE_BASE_URL", "")
    if url:
        from assessments.live import base_url_problem

        if base_url_problem(url):
            problems.append(
                "CATALYST_ASSESSMENT_LIVE_BASE_URL must be an https URL, or http to a loopback literal"
            )
    routine = int(getattr(settings, "CATALYST_ROUTINE_ADVANCE_ACTIVATION", 0) or 0)
    if routine not in (0, 1, 2):
        problems.append(
            "CATALYST_ROUTINE_ADVANCE_ACTIVATION must be 0 (off), 1 (shadow) or 2 (act)"
        )
    if routine >= 1:
        from assessments.policy import Thresholds

        try:
            problems += Thresholds.from_settings(settings).problems()
        except AttributeError:
            problems.append(
                "the routine-advance thresholds must be set when CATALYST_ROUTINE_ADVANCE_ACTIVATION is on"
            )
    if environment == "production" and live_activation >= 1:
        # The largest job drafts and checks one clarification (two bounded attempts).
        if getattr(settings, "CATALYST_MINIMAX_REQUESTS_PER_MINUTE", 0) < 4:
            problems.append(
                "CATALYST_MINIMAX_REQUESTS_PER_MINUTE must cover one bounded clarification job"
            )
    if parity.enabled(settings):
        problems += parity.endpoint_problems(
            settings, "CATALYST_ASSESSMENT_LIVE_BASE_URL"
        )
        if live_activation not in (0, 1):
            problems.append("CATALYST_ASSESSMENT_LIVE_ACTIVATION must be 0 or 1")
        if mode not in ("none", "test") and not mode.startswith("minimax:"):
            problems.append("the production model provider must be minimax")
    return problems + attempt_lease_problems(settings)


ASSESSMENT_REQUESTS_PER_ATTEMPT = (
    2  # the call and the one repair: 1 + assessments.approval.REPAIR_LIMIT
)


def attempt_lease_problems(settings) -> list[str]:
    """oc4.9, oc4.10 item 7: one model attempt (at most two requests, each bounded by the request timeout) must fit in
    half the worker lease, like the mail, fetch and agreement deadlines, so a running attempt is never reclaimed."""
    timeout = getattr(settings, "CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS", 60)
    lease = getattr(settings, "CATALYST_WORKER_LEASE_SECONDS", 300)
    if not timeout or timeout <= 0:
        return [
            "CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS must be a positive number of seconds"
        ]
    if ASSESSMENT_REQUESTS_PER_ATTEMPT * timeout * 2 > lease:
        return [
            "one assessment attempt (2 x CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS) must fit in half of "
            "CATALYST_WORKER_LEASE_SECONDS"
        ]
    return []


def decision_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """018 section 7 (P3 3B.4): the selection policy is fixed in code, never taken from the environment; the decision
    authority is configuration (9kg.30) but takes only "explicit_permission", the one rule the code implements, or
    stays unset (POL-05 undecided: everyone refused)."""
    problems = (
        ["CATALYST_SELECTION_POLICY may not be set from the environment"]
        if "CATALYST_SELECTION_POLICY" in environ
        else []
    )
    if getattr(settings, "CATALYST_QUALIFICATION_AUTHORITY", None) not in (
        None,
        "explicit_permission",
    ):
        problems.append(
            "CATALYST_QUALIFICATION_AUTHORITY must be None or 'explicit_permission'"
        )
    policy = getattr(settings, "CATALYST_SELECTION_POLICY", "")
    if policy and not re.fullmatch(r"SP-[A-Z0-9]{1,8}-[0-9]{1,4}", policy):
        problems.append(
            "CATALYST_SELECTION_POLICY must be empty or an SP-<role>-<n> identifier (019 section 6)"
        )
    elif policy:
        # oc4.12 (oc4.10 item 1): a policy labels decisions only when it is bound to the pack it was approved with,
        # and never while that pack's rubric is the synthetic one.
        pack_name = (
            getattr(settings, "CATALYST_SELECTION_POLICY_PACKS", None) or {}
        ).get(policy)
        if not pack_name:
            problems.append(
                "CATALYST_SELECTION_POLICY is set but CATALYST_SELECTION_POLICY_PACKS does not bind it to a prompt pack"
            )
        else:
            from assessments import pack as packs

            try:
                synthetic = packs.load(pack_name).rubric.get("synthetic", True)
            except packs.PackRefused as exc:
                problems.append(
                    f"CATALYST_SELECTION_POLICY is bound to an unusable prompt pack ({exc})"
                )
            else:
                if synthetic:
                    problems.append(
                        "CATALYST_SELECTION_POLICY is bound to a prompt pack whose rubric is synthetic (POL-04)"
                    )
    return problems


AGREEMENT_TEST_ONLY = (
    "CATALYST_AGREEMENT_PROVIDER_URL",
    "CATALYST_AGREEMENT_PROVIDER_ADDRESS",
    "CATALYST_AGREEMENT_PROVIDER_CA_FILE",
    "CATALYST_AGREEMENT_PROVIDER_TOKEN",
    "CATALYST_AGREEMENT_WEBHOOK_SECRETS",
    "CATALYST_AGREEMENT_STORAGE_DIR",
    "CATALYST_AGREEMENT_REQUIRED_DETAILS",
    "CATALYST_CUSTODY_KEY_DIR",
    "CATALYST_CUSTODY_KEY_MIRROR_DIR",
    # bgl.8: the signing host and the read-back layouts are synthetic until POL-18 and the canary
    "CATALYST_AGREEMENT_SIGNING_BASE_URL",
    "CATALYST_AGREEMENT_FIELD_LAYOUTS",
)
AGREEMENT_DISTRIBUTIONS = (
    "provider",
    "service",
)  # bgl.8: who mails the signing request (config.settings)


def _distribution_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """bgl.8: the distribution mode is one of two known values, fixed in code; "service" needs the public signing host,
    https with nothing but a host, from which the service-sent link is built (agreements.signing_mail)."""
    problems = []
    if "CATALYST_AGREEMENT_DISTRIBUTION" in environ:
        problems.append(
            "CATALYST_AGREEMENT_DISTRIBUTION may not be set from the environment"
        )
    mode = getattr(settings, "CATALYST_AGREEMENT_DISTRIBUTION", "provider")
    if mode not in AGREEMENT_DISTRIBUTIONS:
        problems.append(
            "CATALYST_AGREEMENT_DISTRIBUTION must be 'provider' or 'service'"
        )
    base = getattr(settings, "CATALYST_AGREEMENT_SIGNING_BASE_URL", "")
    if mode == "service" and not base:
        problems.append(
            "CATALYST_AGREEMENT_SIGNING_BASE_URL is required when CATALYST_AGREEMENT_DISTRIBUTION is 'service'"
        )
    if base:
        parts = urlsplit(base)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
        ):
            problems.append(
                "CATALYST_AGREEMENT_SIGNING_BASE_URL must be https with a host and nothing else"
            )
    layouts = getattr(settings, "CATALYST_AGREEMENT_FIELD_LAYOUTS", {}) or {}
    if layouts:
        from agreements.details import layout_problems

        problems += layout_problems(layouts)
    return problems


def agreement_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """021 section 10 (P4 4B.1; TEST-P4-20): no real Documenso. The provider URL, its pinned address, the trust store
    and the token are fixed in code, never from the environment, and empty outside `test` and `staging`. In those two
    the URL must be https on a `.test` host and the pinned address a literal loopback address, so only the local fake
    can answer."""
    problems = [
        f"{name} may not be set from the environment"
        for name in AGREEMENT_TEST_ONLY
        if name in environ
    ]
    problems += _distribution_problems(settings, environ)
    if not synthetic(getattr(settings, "CATALYST_ENV", "")) and not parity.enabled(
        settings
    ):
        for name in AGREEMENT_TEST_ONLY:
            if getattr(settings, name, ""):
                problems.append(
                    f"{name} is allowed only in the test and staging environments (synthetic agreements only)"
                )
        return problems
    url = getattr(settings, "CATALYST_AGREEMENT_PROVIDER_URL", "")
    if parity.enabled(settings):
        problems += parity.endpoint_problems(
            settings,
            "CATALYST_AGREEMENT_PROVIDER_URL",
            pinned="CATALYST_AGREEMENT_PROVIDER_ADDRESS",
            trust="CATALYST_AGREEMENT_PROVIDER_CA_FILE",
        )
        problems += parity.endpoint_problems(
            settings, "CATALYST_AGREEMENT_SIGNING_BASE_URL", origin=True
        )
    elif url:
        if not url.startswith("https://"):
            problems.append("CATALYST_AGREEMENT_PROVIDER_URL must be https")
        host = (urlsplit(url).hostname or "") if url.startswith("https://") else ""
        if not host.endswith(
            ".test"
        ):  # a reserved test name, so a loopback forward to a real host cannot pass
            problems.append("CATALYST_AGREEMENT_PROVIDER_URL must name a .test host")
        if not is_loopback_literal(
            getattr(settings, "CATALYST_AGREEMENT_PROVIDER_ADDRESS", "")
        ):
            problems.append(
                "CATALYST_AGREEMENT_PROVIDER_ADDRESS must be a literal loopback address"
            )
    storage = getattr(settings, "CATALYST_AGREEMENT_STORAGE_DIR", "")
    if storage:
        from pathlib import Path

        repository = Path(__file__).resolve().parent.parent
        target = Path(storage).resolve()
        if (
            not Path(storage).is_absolute()
            or target == repository
            or repository in target.parents
        ):
            problems.append(
                "CATALYST_AGREEMENT_STORAGE_DIR must be an absolute path outside the repository"
            )
    if len(getattr(settings, "CATALYST_AGREEMENT_WEBHOOK_SECRETS", []) or []) > 2:
        problems.append(
            "CATALYST_AGREEMENT_WEBHOOK_SECRETS holds at most two secrets (one rotation, P4-D-17)"
        )
    return problems


# bgl.9 (034 rows 30 and 36): the automated countersignature and release. The modes are fixed in code; the company
# recipient's identity is provider identity, so like the provider URL it is empty outside `test` and `staging`.
COUNTERSIGN_MODES = ("manual", "automatic")
RELEASE_MODES = ("owner", "automatic")
COMPANY_TEST_ONLY = (
    "CATALYST_AGREEMENT_COMPANY_EMAIL",
    "CATALYST_AGREEMENT_COMPANY_NAME",
    "CATALYST_AGREEMENT_COUNTERSIGN_SIGNATURE",
)
AUTOMATION_FIXED = (
    "CATALYST_AGREEMENT_COUNTERSIGN",
    "CATALYST_AGREEMENT_COMPANY_ROLE",
    "CATALYST_RELEASE_MODE",
)


def automation_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """bgl.9: each mode one of its known values and never from the environment; the company recipient's address, name
    and typed signature refused outside `test` and `staging`, and in those a `.test` address only; "automatic"
    countersigning needs the recipient and the signature text."""
    problems = [
        f"{name} may not be set from the environment"
        for name in (*AUTOMATION_FIXED, *COMPANY_TEST_ONLY)
        if name in environ
    ]
    mode = getattr(settings, "CATALYST_AGREEMENT_COUNTERSIGN", "manual")
    if mode not in COUNTERSIGN_MODES:
        problems.append(
            "CATALYST_AGREEMENT_COUNTERSIGN must be 'manual' or 'automatic'"
        )
    if getattr(settings, "CATALYST_RELEASE_MODE", "owner") not in RELEASE_MODES:
        problems.append("CATALYST_RELEASE_MODE must be 'owner' or 'automatic'")
    if getattr(settings, "CATALYST_AGREEMENT_COMPANY_ROLE", "APPROVER") not in (
        "APPROVER",
        "SIGNER",
    ):
        problems.append(
            "CATALYST_AGREEMENT_COMPANY_ROLE must be 'APPROVER' or 'SIGNER'"
        )
    if not synthetic(getattr(settings, "CATALYST_ENV", "")) and not parity.enabled(
        settings
    ):
        for name in COMPANY_TEST_ONLY:
            if getattr(settings, name, ""):
                problems.append(
                    f"{name} is allowed only in the test and staging environments (synthetic agreements only)"
                )
    elif not parity.enabled(settings):
        email = getattr(settings, "CATALYST_AGREEMENT_COMPANY_EMAIL", "") or ""
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.test", email.lower()):
            problems.append(
                "CATALYST_AGREEMENT_COMPANY_EMAIL must be an address at a .test domain"
            )
    if parity.enabled(settings):
        email = getattr(settings, "CATALYST_AGREEMENT_COMPANY_EMAIL", "")
        if email and not re.fullmatch(r"[^@\s]+@intentsolutions\.io", email):
            problems.append(
                "the company recipient must be at the approved company domain"
            )
    if mode == "automatic" and not (
        getattr(settings, "CATALYST_AGREEMENT_COMPANY_EMAIL", "")
        and getattr(settings, "CATALYST_AGREEMENT_COUNTERSIGN_SIGNATURE", "")
    ):
        problems.append(
            "CATALYST_AGREEMENT_COUNTERSIGN 'automatic' needs CATALYST_AGREEMENT_COMPANY_EMAIL and "
            "CATALYST_AGREEMENT_COUNTERSIGN_SIGNATURE"
        )
    return problems


PROVISIONING_TEST_ONLY = (
    "CATALYST_PROVISIONING_ADAPTER",
    "CATALYST_PROVISIONING_DOMAIN",
    # the live mail host's values (034 row 37): fixed in code, empty outside test and staging
    "CATALYST_PROVISIONING_API_URL",
    "CATALYST_PROVISIONING_API_SERVER",
    "CATALYST_PROVISIONING_API_ACCOUNT",
    "CATALYST_PROVISIONING_API_KEY_FILE",
    "CATALYST_PROVISIONING_IMAP_HOST",
)
NAMING_POLICIES = ("first_last", "first_name")
CREDENTIAL_MODES = ("set_your_own", "one_time_password")


def provisioning_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """023 sections 3 and 11.1 (P5 5B.1; TEST-P5-23): no real mail host. The adapter and the domain are fixed in code,
    never from the environment, and empty outside `test` and `staging`. In those two the adapter must be a test fake
    and the domain a `.test` domain. No live adapter exists; building one is a pre-live gate (D-47)."""
    problems = [
        f"{name} may not be set from the environment"
        for name in PROVISIONING_TEST_ONLY
        if name in environ
    ]
    # No mail-host credential may sit in a web or worker environment (023 11.1): the live key, if ever authorized,
    # belongs to the separate credential service only (security review of PR #53).
    problems += [
        f"{name} looks like a mail-host credential and may not be in this process's environment"
        for name in environ
        if re.search(
            r"MXROUTE|DIRECTADMIN|X_API_KEY|MAILHOST_(API_)?(KEY|TOKEN)", name.upper()
        )
    ]
    environment = getattr(settings, "CATALYST_ENV", "")
    base = getattr(settings, "CATALYST_PUBLIC_BASE_URL", "")
    if (
        environment not in ("test", "development")
        and base
        and not base.startswith("https://")
    ):
        # Setup and confirmation tokens travel in links: outside test and development only https (5B.2 review).
        problems.append(
            "CATALYST_PUBLIC_BASE_URL must be https outside test and development"
        )
    if environment == "staging":
        # PR #59 and #61 reviews: staging must never answer for, or link to, a production host (its links would reach
        # real applicants). Hosts are compared in ASCII form, so look-alike characters cannot slip past.
        if base and _production_host(urlsplit(base).hostname or ""):
            problems.append(
                "CATALYST_PUBLIC_BASE_URL in staging may not name a production host"
            )
        for host in getattr(settings, "ALLOWED_HOSTS", []) or []:
            if host.strip() in ("*", ".") or _production_host(host.strip().lstrip(".")):
                problems.append(f"ALLOWED_HOSTS in staging may not include {host!r}")
    if (
        getattr(settings, "CATALYST_PROVISIONING_NAMING_POLICY", "first_last")
        not in NAMING_POLICIES
    ):
        problems.append(
            "CATALYST_PROVISIONING_NAMING_POLICY must be first_last or first_name"
        )
    if (
        getattr(settings, "CATALYST_PROVISIONING_CREDENTIAL_MODE", "set_your_own")
        not in CREDENTIAL_MODES
    ):
        problems.append(
            "CATALYST_PROVISIONING_CREDENTIAL_MODE must be set_your_own or one_time_password"
        )
    if not synthetic(environment) and not parity.enabled(settings):
        for name in PROVISIONING_TEST_ONLY:
            if getattr(settings, name, ""):
                problems.append(
                    f"{name} is allowed only in the test and staging environments (synthetic provisioning only)"
                )
        return problems
    adapter = getattr(settings, "CATALYST_PROVISIONING_ADAPTER", "")
    if adapter and not adapter.startswith("tests.") and not parity.enabled(settings):
        problems.append("CATALYST_PROVISIONING_ADAPTER must name a test fake")
    problems += (
        parity.provisioning_problems(settings)
        if parity.enabled(settings)
        else _live_host_problems(settings)
    )
    domain = getattr(settings, "CATALYST_PROVISIONING_DOMAIN", "")
    if domain and not domain.lower().endswith(".test") and not parity.enabled(settings):
        problems.append("CATALYST_PROVISIONING_DOMAIN must be a .test domain")
    if getattr(settings, "CATALYST_PROVISIONING_METHOD", "api") not in (
        "api",
        "checklist",
    ):
        problems.append("CATALYST_PROVISIONING_METHOD must be api or checklist")
    quota, limit = (
        getattr(settings, "CATALYST_PROVISIONING_QUOTA_MB", 1),
        getattr(settings, "CATALYST_PROVISIONING_SEND_LIMIT", 1),
    )
    if not (isinstance(quota, int) and quota >= 1):
        problems.append(
            "CATALYST_PROVISIONING_QUOTA_MB must be at least 1 (never unlimited, P5-D-2)"
        )
    if not (isinstance(limit, int) and 1 <= limit <= 9600):
        problems.append("CATALYST_PROVISIONING_SEND_LIMIT must be between 1 and 9600")
    return problems


def _live_host_problems(settings) -> list[str]:
    """The live mail host's values in test and staging (034 row 37): the API origin is https on a `.test` host or http
    on loopback, with no path, query or fragment; the key file is an absolute path; the IMAP host is loopback or a
    `.test` name, its port in range. Nothing here may name a real host."""
    problems = []
    api = getattr(settings, "CATALYST_PROVISIONING_API_URL", "") or ""
    if api:
        parts = urlsplit(api)
        host = parts.hostname or ""
        origin = (
            parts.scheme == "https"
            and host.isascii()
            and host.lower().endswith(".test")
        ) or (parts.scheme == "http" and is_loopback_literal(host))
        if (
            not origin
            or parts.path not in ("", "/")
            or parts.query
            or parts.fragment
            or "@" in parts.netloc
        ):
            problems.append(
                "CATALYST_PROVISIONING_API_URL must be an https origin on a .test host, or http on loopback"
            )
    key_file = getattr(settings, "CATALYST_PROVISIONING_API_KEY_FILE", "") or ""
    if key_file and not key_file.startswith("/"):
        problems.append("CATALYST_PROVISIONING_API_KEY_FILE must be an absolute path")
    imap = getattr(settings, "CATALYST_PROVISIONING_IMAP_HOST", "") or ""
    if imap and not (
        is_loopback_literal(imap) or (imap.isascii() and imap.lower().endswith(".test"))
    ):
        problems.append(
            "CATALYST_PROVISIONING_IMAP_HOST must be loopback or a .test host"
        )
    port = getattr(settings, "CATALYST_PROVISIONING_IMAP_PORT", 993)
    if not (isinstance(port, int) and 1 <= port <= 65535):
        problems.append("CATALYST_PROVISIONING_IMAP_PORT must be a port number")
    return problems


TWENTY_TEST_ONLY = (
    "CATALYST_TWENTY_PROJECTION",
    "CATALYST_TWENTY_URL",
    "CATALYST_TWENTY_ADDRESS",
    "CATALYST_TWENTY_CA_FILE",
)
# The process roles that never call Twenty (the fetcher reaches applicant-supplied addresses; the post-restore step reads
# only the restored tables and the Sent folder).
TWENTY_TOKEN_DENIED_ROLES = ("fetcher", "reconcile")


def twenty_problems(settings, environ: Mapping[str, str], kind: str = "") -> list[str]:
    """bgl.14 (034 rows 42 and 43; owner answer of 2026-10-31 reversing D-08 on activation): the Twenty projection.
    The switch, the URL, the pinned address and the trust store are fixed in code, never from the environment, and,
    with the token file, empty or off outside `test` and `staging` until the swap's own reviewed code change admits
    production. In those two the URL must be https on a `.test` host and the address a literal loopback address, so only
    the local stub can answer. The token is a secret file (`twenty_token`), held by the worker and the owner-run commands
    only: the web process and the fetcher and post-restore roles refuse to start with it."""
    problems = [
        f"{name} may not be set from the environment"
        for name in TWENTY_TEST_ONLY
        if name in environ
    ]
    token = getattr(settings, "CATALYST_TWENTY_TOKEN", "")
    if token and (
        kind == "web"
        or getattr(settings, "CATALYST_PROCESS_ROLE", "") in TWENTY_TOKEN_DENIED_ROLES
    ):
        problems.append(
            "CATALYST_TWENTY_TOKEN may be given only to the worker and the owner-run commands"
        )
    if not synthetic(getattr(settings, "CATALYST_ENV", "")) and not parity.enabled(
        settings
    ):
        for name in (*TWENTY_TEST_ONLY, "CATALYST_TWENTY_TOKEN"):
            if getattr(settings, name, ""):
                problems.append(
                    f"{name} is allowed only in the test and staging environments until the Twenty swap"
                )
        return problems
    url = getattr(settings, "CATALYST_TWENTY_URL", "")
    if parity.enabled(settings):
        problems += parity.endpoint_problems(
            settings,
            "CATALYST_TWENTY_URL",
            pinned="CATALYST_TWENTY_ADDRESS",
            trust="CATALYST_TWENTY_CA_FILE",
        )
    elif url:
        parts = urlsplit(url) if url.startswith("https://") else None
        if parts is None:
            problems.append("CATALYST_TWENTY_URL must be https")
        elif (
            not (parts.hostname or "").endswith(".test")
            or parts.query
            or parts.fragment
            or parts.username
        ):
            problems.append(
                "CATALYST_TWENTY_URL must name a .test host, with no user, query or fragment"
            )
        if not is_loopback_literal(getattr(settings, "CATALYST_TWENTY_ADDRESS", "")):
            problems.append(
                "CATALYST_TWENTY_ADDRESS must be a literal loopback address"
            )
        if not getattr(settings, "CATALYST_TWENTY_CA_FILE", ""):
            problems.append(
                "CATALYST_TWENTY_CA_FILE is required with CATALYST_TWENTY_URL (never the system store)"
            )
    return problems


PRODUCTION_DOMAINS = ("intentsolutions.io",)
# The learning site's host (029 section 7): the internal launch runs on a dedicated v2 host, and moving Learn's routes
# is GATE-CUTOVER, a separate decision; production may not answer for or link to it.
LEARN_HOSTS = ("learn.intentsolutions.io",)


def _production_host(host: str) -> bool:
    """True for a production domain or any name under it. A name that is not plain ASCII counts as production:
    look-alike characters (a full-width dot, an ideographic full stop) would map onto the real name."""
    if not host.isascii():
        return True
    host = host.lower().rstrip(".")
    return any(
        host == domain or host.endswith("." + domain) for domain in PRODUCTION_DOMAINS
    )


def _live_host(host: str) -> bool:
    """A plain lower-case DNS name with a letter in its last label: no port, no wildcard, no address, no look-alike."""
    return (
        host.isascii()
        and bool(HOST_NAME.fullmatch(host))
        and not is_loopback_literal(host)
    )


def live_problems(settings) -> list[str]:
    """9kg.31.11 (029 sections 4.1, 7 and 13; the owner directive of 2026-10-26): the rails a live environment adds,
    failing closed (security review of PR #118: a deny-list of bad hosts let `\\@`, percent-encoding and ports past).

    - The intake mode is not a live rail: "invitation" or "open" is checked for every environment (intake_problems);
      open intake on the first-generation URLs is the owner's switch (034 row 2, bgl.2).
    - The public base URL is exactly `https://<host>`: no user part, port, path, query or fragment, and nothing a
      browser could read differently from Python (a backslash, a percent sign, white space).
    - The public host and the staff host are distinct plain DNS names, never the learning site's host, the apex of
      a production domain or its `www` name (the pilot runs on a dedicated v2 host; moving Learn is GATE-CUTOVER).
    - ALLOWED_HOSTS is exactly those two plus CATALYST_LOCAL_HOSTS, so nothing else is answered for.
    - Django's own mailer is the transport backend or the refusing hold (LIVE_EMAIL_BACKENDS), and the sender
      address is a real one, never the synthetic default."""
    if getattr(settings, "CATALYST_ENV", "") not in LIVE_ENVIRONMENTS:
        return []
    problems = []
    base = str(getattr(settings, "CATALYST_PUBLIC_BASE_URL", "") or "")
    match = re.fullmatch(r"https://([^/?#@\\%\s:]+)", base)
    public = match.group(1) if match else ""
    if not match or not _live_host(public):
        problems.append(
            "CATALYST_PUBLIC_BASE_URL must be exactly https://<the dedicated v2 host name> in a live environment"
        )
    staff = str(getattr(settings, "CATALYST_STAFF_HOST", "") or "")
    if staff and not _live_host(staff):
        problems.append(
            "CATALYST_STAFF_HOST must be a plain lower-case host name in a live environment"
        )
    if public and staff and public == staff:
        problems.append("CATALYST_STAFF_HOST must differ from the public host")
    for name, host in (
        ("CATALYST_PUBLIC_BASE_URL", public),
        ("CATALYST_STAFF_HOST", staff),
    ):
        if any(host == learn or host.endswith("." + learn) for learn in LEARN_HOSTS):
            problems.append(
                f"{name} may not be the learning site's host: the pilot runs on the dedicated v2 host "
                "(moving Learn is GATE-CUTOVER)"
            )
        elif host in PRODUCTION_DOMAINS or any(
            host == f"www.{domain}" for domain in PRODUCTION_DOMAINS
        ):
            problems.append(
                f"{name} may not be a production domain's apex or www name (a dedicated v2 host only)"
            )
    local = [str(h) for h in (getattr(settings, "CATALYST_LOCAL_HOSTS", []) or [])]
    aliases = [
        str(h) for h in (getattr(settings, "CATALYST_PUBLIC_HOST_ALIASES", []) or [])
    ]  # bgl.2, alias_problems
    expected = {h for h in (public, staff, *local, *aliases) if h}
    extra = sorted(
        h for h in (getattr(settings, "ALLOWED_HOSTS", []) or []) if h not in expected
    )
    if extra:
        problems.append(
            f"ALLOWED_HOSTS may hold only the public, staff, local and alias hosts in a live environment, not {extra}"
        )
    if getattr(settings, "EMAIL_BACKEND", "") not in LIVE_EMAIL_BACKENDS:
        problems.append(
            f"EMAIL_BACKEND must be {TRANSPORT_EMAIL_BACKEND} (or the {REFUSING_EMAIL_BACKEND} hold) "
            "in a live environment"
        )
    sender = str(getattr(settings, "DEFAULT_FROM_EMAIL", "") or "").lower()
    domain = sender.rpartition("@")[2]
    if (
        not domain
        or not _live_host(domain)
        or domain.endswith((".invalid", ".example"))
        or domain.startswith("example.")
    ):
        problems.append(
            "CATALYST_FROM_EMAIL must be the v2 sender address in a live environment, not a synthetic one"
        )
    return problems


def alias_problems(settings) -> list[str]:
    """bgl.2: every public host alias is a plain lower-case DNS name (no wildcard, port, address or look-alike), never
    the staff host and never a local host, so an alias can only ever reach the public applicant pages."""
    staff = (getattr(settings, "CATALYST_STAFF_HOST", "") or "").lower().rstrip(".")
    local = {
        str(h).lower().rstrip(".")
        for h in getattr(settings, "CATALYST_LOCAL_HOSTS", []) or []
    }
    problems = []
    for alias in getattr(settings, "CATALYST_PUBLIC_HOST_ALIASES", []) or []:
        alias = str(alias)
        if "*" in alias or not _live_host(alias):
            problems.append(
                f"CATALYST_PUBLIC_HOST_ALIASES entries must be plain lower-case host names, not {alias!r}"
            )
        elif staff and alias.rstrip(".") == staff:
            problems.append(
                "CATALYST_PUBLIC_HOST_ALIASES may not include the staff host"
            )
        elif alias.rstrip(".") in local:
            problems.append("CATALYST_PUBLIC_HOST_ALIASES may not include a local host")
    return problems


def host_problems(settings) -> list[str]:
    """PR #62 review: outside the local environments the staff screens need their own host, and neither it nor the
    local health hosts (the proxy's socket) may be the public host, a wildcard or a domain pattern."""
    environment = getattr(settings, "CATALYST_ENV", "")
    if environment not in ALLOWED_ENVIRONMENTS or environment in (
        "test",
        "development",
    ):
        return []
    base = getattr(settings, "CATALYST_PUBLIC_BASE_URL", "")
    public = (urlsplit(base).hostname or "").lower().rstrip(".") if base else ""
    staff = (getattr(settings, "CATALYST_STAFF_HOST", "") or "").lower().rstrip(".")
    problems = (
        []
        if staff
        else ["CATALYST_STAFF_HOST is required outside test and development"]
    )
    beat = getattr(settings, "CATALYST_WORKER_HEARTBEAT_FILE", "") or ""
    if not beat.startswith(
        "/"
    ):  # PR #64 review: no deployment without a worker liveness signal
        problems.append(
            "CATALYST_WORKER_HEARTBEAT_FILE must be an absolute path outside test and development"
        )
    for name, hosts in (
        ("CATALYST_STAFF_HOST", [staff] if staff else []),
        ("CATALYST_LOCAL_HOSTS", getattr(settings, "CATALYST_LOCAL_HOSTS", []) or []),
    ):
        for host in hosts:
            host = host.lower().rstrip(".")
            if host in ("*", "") or host.startswith(".") or (public and host == public):
                problems.append(
                    f"{name} may not be a wildcard, a domain pattern or the public host"
                )
    local = {
        h.lower().rstrip(".")
        for h in getattr(settings, "CATALYST_LOCAL_HOSTS", []) or []
    }
    if (
        staff and staff in local
    ):  # health would then answer on the staff host (PR #63 review)
        problems.append(
            "CATALYST_STAFF_HOST may not also be one of CATALYST_LOCAL_HOSTS"
        )
    return problems


def secret_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """6B.5 (026 section 5, P6-D-6): outside test and development, secrets come only from per-secret files."""
    environment = getattr(settings, "CATALYST_ENV", "")
    if environment == "development" and getattr(settings, "CATALYST_SECRETS_DIR", ""):
        # A process with mounted secrets is a deployment; "development" would switch the guards and the safe mail sink
        # off (PR #65 review).
        return [
            "CATALYST_ENV=development may not be used with CATALYST_SECRETS_DIR (a deployment must say staging or production)"
        ]
    if environment not in ALLOWED_ENVIRONMENTS or environment in (
        "test",
        "development",
    ):
        return []
    problems = [
        f"{name} may not be in the environment outside test and development; use CATALYST_SECRETS_DIR"
        for name in SECRET_ENV_NAMES
        if name in environ
    ]
    if not str(getattr(settings, "CATALYST_SECRETS_DIR", "") or "").startswith("/"):
        problems.append(
            "CATALYST_SECRETS_DIR must be an absolute path outside test and development"
        )
    return problems


def journal_problems(settings) -> list[str]:
    """9kg.33 (029 section 6.2): outside test and development every process writes the effect journal, so the
    directory must be an absolute path outside the repository. The local environments may leave it empty (no
    durable effects; the post-restore lift then refuses for want of evidence)."""
    environment = getattr(settings, "CATALYST_ENV", "")
    path = str(getattr(settings, "CATALYST_EFFECT_JOURNAL_DIR", "") or "")
    if not path:
        if environment in ALLOWED_ENVIRONMENTS and environment not in (
            "test",
            "development",
        ):
            return [
                "CATALYST_EFFECT_JOURNAL_DIR must be an absolute path outside test and development"
            ]
        return []
    from pathlib import Path

    repository = Path(__file__).resolve().parent.parent
    target = Path(path).resolve()
    if (
        not Path(path).is_absolute()
        or target == repository
        or repository in target.parents
    ):
        return [
            "CATALYST_EFFECT_JOURNAL_DIR must be an absolute path outside the repository"
        ]
    if environment in ("test", "development"):
        return []
    from workflow import journal

    if getattr(settings, "CATALYST_PROCESS_ROLE", "") == "fetcher":
        # 9kg.63: the fetcher makes no effect and mounts no journal (scripts/render_staging_compose.py names a directory
        # it never has, so a stray write fails loudly); requiring that directory to exist kept it from starting. The
        # role is read, not the process kind: this check runs at start-up, before the worker command declares its kind,
        # and a web process with the fetcher role is refused by process_role_problems.
        return []
    kind = _process_kind()
    problem = journal.directory_problem(write=kind in ("web", "worker", "reconcile"))
    if problem and not (problem == "not_configured"):
        return [
            f"CATALYST_EFFECT_JOURNAL_DIR is {problem}: a private (0700) directory this process can write"
        ]
    if getattr(settings, "CATALYST_ENV", "") in LIVE_ENVIRONMENTS and not getattr(
        settings, "CATALYST_JOURNAL_SHIP_LAG_SECONDS", 0
    ):
        return [
            "CATALYST_JOURNAL_SHIP_LAG_SECONDS must be set in a live environment: the journal is shipped off the host "
            "and its lag pages (9kg.60)"
        ]
    return []


PROCESS_ROLES = ("", "web", "worker", "fetcher", "reconcile")


def process_role_problems(settings, kind: str) -> list[str]:
    """PR #65 re-check: the fetcher alone may run without the link-signing key, so the role must be one Catalyst knows,
    may never be claimed by the web process (whose kind is declared in code before Django loads), and any other process
    must hold a key: links signed with an empty key could be forged by anyone."""
    role = getattr(settings, "CATALYST_PROCESS_ROLE", "") or ""
    if role not in PROCESS_ROLES:
        return [
            f"CATALYST_PROCESS_ROLE must be one of {', '.join(r for r in PROCESS_ROLES if r)}"
        ]
    problems = []
    if role in ("fetcher", "reconcile") and kind == "web":
        problems.append(f"the web process may not run as CATALYST_PROCESS_ROLE={role}")
    if role in ("web", "worker") and kind == "reconcile":
        problems.append(
            "the post-restore step may not run as a web or worker process role (9kg.49, RD-1)"
        )
    proxy = str(getattr(settings, "CATALYST_EVIDENCE_PROXY", "") or "")
    if proxy and not re.fullmatch(r"[a-z0-9.-]+:\d{1,5}", proxy):
        problems.append("CATALYST_EVIDENCE_PROXY must be host:port")
    if (
        role == "fetcher"
        and getattr(settings, "CATALYST_ENV", "") not in ("test", "development")
        and not proxy
    ):
        # Every environment past the local ones (PR #76 review): the fetcher reaches nothing but the egress proxy.
        problems.append(
            "a fetcher outside test and development needs CATALYST_EVIDENCE_PROXY (the egress proxy)"
        )
    key = getattr(settings, "CATALYST_VERIFICATION_KEY", None)
    if role != "fetcher" and key is not None and not key:
        problems.append("CATALYST_VERIFICATION_KEY may be empty only for the fetcher")
    return problems


def erasure_key_problems(settings, kind: str) -> list[str]:
    """9kg.32 (PR #99 security review): the erasure key is for the owner-run erasure command and the restore's replay
    only; a web or worker process (the kinds declared in code) that holds it refuses to start."""
    from config.runtime import ENFORCED_KINDS

    if kind in ENFORCED_KINDS and (
        getattr(settings, "CATALYST_ERASURE_KEY", "")
        or getattr(settings, "CATALYST_ERASURE_PREVIOUS_KEYS", [])
    ):
        return [
            f"CATALYST_ERASURE_KEY and CATALYST_ERASURE_PREVIOUS_KEYS may not be given to a {kind} process (the erasure command and replay only)"
        ]
    return []


# 9kg.34: the process roles that may never hold the custody wrapping key (the fetcher reaches applicant-supplied
# addresses; the post-restore step reads the restored tables and the Sent folder only). The backup and erasure commands
# refuse it themselves (config.backup, erasure's command).
CUSTODY_KEY_DENIED_ROLES = ("fetcher", "reconcile")


def _inside(path, other) -> bool:
    return path == other or other in path.parents


def custody_key_problems(settings, kind: str) -> list[str]:
    """9kg.34 (026 section 6 option c; 030 Q4, D-51): the custody wrapping key and the key directories.

    - The wrapping key, when set: 64 lower-case hex characters (32 random bytes), distinct from the Django secret key,
      the link-signing keys and the erasure key, and never given to the fetcher or the post-restore step. Outside test
      and development it comes only from its secret file (secret_problems refuses it in the environment).
    - The key directory and its mirror: absolute, distinct, neither inside the other, outside the repository, and
      neither inside nor around the custody directory or the effect journal, so no backup of either carries a key.
    - Custody storage needs both directories (nothing new is stored in the clear).
    - A live environment refuses any custody configuration while the owner's custody decision has an undecided row
      (agreements.custody_policy, 211.7.9), as the erasure registry does for POL-10."""
    from pathlib import Path

    problems = []
    secret = str(getattr(settings, "CATALYST_CUSTODY_WRAPPING_KEY", "") or "")
    databases = getattr(settings, "DATABASES", {}) or {}
    others = [
        getattr(settings, "SECRET_KEY", ""),
        getattr(settings, "CATALYST_VERIFICATION_KEY", "") or "",
        *(getattr(settings, "CATALYST_VERIFICATION_FALLBACK_KEYS", []) or []),
        getattr(settings, "CATALYST_ERASURE_KEY", "") or "",
        *(getattr(settings, "CATALYST_ERASURE_PREVIOUS_KEYS", []) or []),
        # review of PR #102: the passwords and webhook secrets this process holds, where it holds them
        *(str((db or {}).get("PASSWORD", "") or "") for db in databases.values()),
        getattr(settings, "CATALYST_MAIL_PASSWORD", "") or "",
        *(getattr(settings, "CATALYST_AGREEMENT_WEBHOOK_SECRETS", []) or []),
    ]
    if secret:
        if not re.fullmatch(r"[0-9a-f]{64}", secret):
            problems.append(
                "CATALYST_CUSTODY_WRAPPING_KEY must be 64 lower-case hex characters (32 random bytes)"
            )
        elif len(set(secret)) == 1:
            problems.append(
                "CATALYST_CUSTODY_WRAPPING_KEY is one character repeated, not a random key"
            )
        if secret in [o for o in others if o]:
            problems.append(
                "CATALYST_CUSTODY_WRAPPING_KEY must differ from every other key"
            )
        role = getattr(settings, "CATALYST_PROCESS_ROLE", "") or ""
        if role in CUSTODY_KEY_DENIED_ROLES or kind == "reconcile":
            problems.append(
                f"CATALYST_CUSTODY_WRAPPING_KEY may not be given to the {role or kind} process (9kg.34)"
            )
    upcoming = str(getattr(settings, "CATALYST_CUSTODY_NEXT_WRAPPING_KEY", "") or "")
    if upcoming:  # 9kg.69: the next wrapping key, held only by the owner-run rotation
        if not re.fullmatch(r"[0-9a-f]{64}", upcoming) or len(set(upcoming)) == 1:
            problems.append(
                "CATALYST_CUSTODY_NEXT_WRAPPING_KEY must be 64 lower-case hex characters (32 random bytes)"
            )
        if upcoming == secret or upcoming in [o for o in others if o]:
            problems.append(
                "CATALYST_CUSTODY_NEXT_WRAPPING_KEY must differ from the current wrapping key and every other key"
            )
        role = getattr(settings, "CATALYST_PROCESS_ROLE", "") or ""
        if kind != "management" or role in (*CUSTODY_KEY_DENIED_ROLES, "web", "worker"):
            problems.append(
                "CATALYST_CUSTODY_NEXT_WRAPPING_KEY is held only by the owner-run rotation (9kg.69)"
            )
    primary = str(getattr(settings, "CATALYST_CUSTODY_KEY_DIR", "") or "")
    mirror = str(getattr(settings, "CATALYST_CUSTODY_KEY_MIRROR_DIR", "") or "")
    storage = str(getattr(settings, "CATALYST_AGREEMENT_STORAGE_DIR", "") or "")
    journal_dir = str(getattr(settings, "CATALYST_EFFECT_JOURNAL_DIR", "") or "")
    if storage and not (primary and mirror):
        problems.append(
            "CATALYST_AGREEMENT_STORAGE_DIR needs CATALYST_CUSTODY_KEY_DIR and CATALYST_CUSTODY_KEY_MIRROR_DIR"
            " (custody is encrypted at rest, 9kg.34)"
        )
    dirs = [d for d in (primary, mirror) if d]
    if dirs:
        repository = Path(__file__).resolve().parent.parent
        if any(not Path(d).is_absolute() for d in dirs):
            problems.append("the custody key directories must be absolute paths")
        else:
            resolved = [Path(d).resolve() for d in dirs]
            if any(_inside(r, repository) for r in resolved):
                problems.append(
                    "the custody key directories must be outside the repository"
                )
            if len(resolved) == 2 and (
                _inside(resolved[0], resolved[1]) or _inside(resolved[1], resolved[0])
            ):
                problems.append(
                    "CATALYST_CUSTODY_KEY_DIR and CATALYST_CUSTODY_KEY_MIRROR_DIR must be separate directories"
                )
            for name, other in (
                ("CATALYST_AGREEMENT_STORAGE_DIR", storage),
                ("CATALYST_EFFECT_JOURNAL_DIR", journal_dir),
            ):
                if other and Path(other).is_absolute():
                    target = Path(other).resolve()
                    if any(_inside(r, target) or _inside(target, r) for r in resolved):
                        problems.append(
                            f"the custody key directories may not be inside or around {name} (it is backed up or carried)"
                        )
    if getattr(settings, "CATALYST_ENV", "") in LIVE_ENVIRONMENTS and (
        storage or dirs or secret
    ):
        from agreements import custody_policy

        if custody_policy.problems():
            problems.append(
                "custody is configured in a live environment while the owner's custody decision is open"
                " (agreements.custody_policy, 211.7.9)"
            )
    return problems


INTAKE_FIXED = ("CATALYST_CLIENT_IDENTITY",)
INTAKE_MODES = ("invitation", "open")
CLIENT_IDENTITY_SOURCES = ("proxy", "direct")


def intake_problems(settings, environ: Mapping[str, str]) -> list[str]:
    """9kg.29, 9kg.43 and bgl.2: the intake mode comes from the environment and is "invitation" (the default when
    unset) or "open", nothing else, so an empty or mistyped value refuses start-up instead of opening the form; the
    form checks are fixed in code and on outside the test suite; the client-identity source is fixed in code, never
    from the environment, "proxy" everywhere the web process listens on the proxy's socket (026 section 8) and
    "direct" only in test and development."""
    problems = [
        f"{name} may not be set from the environment"
        for name in INTAKE_FIXED
        if name in environ
    ]
    if getattr(settings, "CATALYST_INTAKE_MODE", None) not in INTAKE_MODES:
        problems.append(
            "CATALYST_INTAKE_MODE must be 'invitation' (the default) or 'open'"
        )
    if (
        getattr(settings, "CATALYST_INTAKE_FORM_CHECKS", True) is not True
        and getattr(settings, "CATALYST_ENV", "") != "test"
    ):
        problems.append("CATALYST_INTAKE_FORM_CHECKS must be on outside the test suite")
    low, high = (
        getattr(settings, name, None)
        for name in (
            "CATALYST_INTAKE_FORM_MIN_AGE_SECONDS",
            "CATALYST_INTAKE_FORM_MAX_AGE_SECONDS",
        )
    )
    if isinstance(low, int) and isinstance(high, int) and low >= high:
        problems.append(
            "CATALYST_INTAKE_FORM_MIN_AGE_SECONDS must be below CATALYST_INTAKE_FORM_MAX_AGE_SECONDS"
        )
    source = getattr(settings, "CATALYST_CLIENT_IDENTITY", None)
    if source not in CLIENT_IDENTITY_SOURCES:
        problems.append("CATALYST_CLIENT_IDENTITY must be 'proxy' or 'direct'")
    elif source == "direct" and getattr(settings, "CATALYST_ENV", "") not in (
        "test",
        "development",
    ):
        problems.append(
            "CATALYST_CLIENT_IDENTITY must be 'proxy' outside test and development (the web process listens on the proxy's socket)"
        )
    return problems


def all_problems(settings, environ: Mapping[str, str]) -> list[str]:
    return (
        database_problems(settings.DATABASES)
        + environment_problems(settings.CATALYST_ENV)
        + provider_problems(settings.EMAIL_BACKEND, environ, settings.CATALYST_ENV)
        + mail_problems(settings)
        + sender_problems(settings)
        + dispatch_problems(settings, environ)
        + evidence_problems(settings, environ)
        + assessment_problems(settings, environ)
        + decision_problems(settings, environ)
        + agreement_problems(settings, environ)
        + provisioning_problems(settings, environ)
        + twenty_problems(settings, environ, _process_kind())
        + host_problems(settings)
        + alias_problems(settings)
        + live_problems(settings)
        + secret_problems(settings, environ)
        + journal_problems(settings)
        + process_role_problems(settings, _process_kind())
        + erasure_key_problems(settings, _process_kind())
        + custody_key_problems(settings, _process_kind())
        + intake_problems(settings, environ)
        + automation_problems(settings, environ)
        + parity.process_problems(settings, _process_kind())
    )


def _process_kind() -> str:
    from config import runtime

    return runtime.process_kind()
