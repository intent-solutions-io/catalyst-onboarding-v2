"""Settings for Catalyst v2 (005 S1; ADR-02, ADR-17, ADR-18).

Every value that differs between machines comes from a CATALYST_* environment variable. There is no
database URL and no engine variable: the engine is PostgreSQL, and config.guards refuses anything else.
"""

import os
import re
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise ImproperlyConfigured(f"environment variable {name} is required")
    return value


CATALYST_ENV = env("CATALYST_ENV")
SECRET_KEY = env("CATALYST_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = [h.strip() for h in env("CATALYST_ALLOWED_HOSTS", "localhost").split(",") if h.strip()]

INSTALLED_APPS = [
    "config.apps.CatalystConfig",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    # The read-only staff view (S1-T7, D-23): Django Admin with database sessions and its messages.
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
    "accounts",
    "workflow",
    "applications",
    "correspondence",
    "assessments",  # P3 (018; D-34)
    "agreements",  # P4 (021; D-37)
    "provisioning",  # P5 (023; D-47)
]
MIDDLEWARE = [
    "config.redaction.PrivateConfirmationResponses",  # outermost: covers responses built outside the view
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
SECURE_REFERRER_POLICY = "no-referrer"  # no page needs to tell another site where a visitor came from
ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": [
            "django.template.context_processors.request",
            "django.contrib.auth.context_processors.auth",
            "django.contrib.messages.context_processors.messages",
        ]},
    }
]
# Request limits for the public form (005 S1.5): a larger body or more fields is a 400, not a form error.
# The form has 25 fields plus the CSRF token (the three S1 fields and the optional P3 claim fields, 018 section 2);
# 128 KiB covers their longest percent-encoded values.
DATA_UPLOAD_MAX_MEMORY_SIZE = 128 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 32
DATA_UPLOAD_MAX_NUMBER_FILES = 0  # the memory limit excludes file parts; no form here accepts a file
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("CATALYST_DB_NAME"),
        "USER": env("CATALYST_DB_USER"),
        "PASSWORD": env("CATALYST_DB_PASSWORD"),
        "HOST": env("CATALYST_DB_HOST"),
        "PORT": env("CATALYST_DB_PORT", "5432"),
        "ATOMIC_REQUESTS": False,  # services own their transactions (005 S1.4)
        "CONN_MAX_AGE": 0,
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ADR-14 (D-17): three database roles, provisioned outside the application (scripts/provision_db_roles.py).
# Migrations run as the owner and grant the application and retention roles exactly what they need.
# Web and worker processes connect as the application role, never as the owner or a superuser.
CATALYST_DB_ROLES = {
    "owner": env("CATALYST_DB_OWNER_ROLE", "catalyst_owner"),
    "app": env("CATALYST_DB_APP_ROLE", "catalyst_app"),
    "retention": env("CATALYST_DB_RETENTION_ROLE", "catalyst_retention"),
}
# Role names reach SQL as identifiers in migrations: accept only plain lowercase identifiers.
for _key, _role in CATALYST_DB_ROLES.items():
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", _role):
        raise ImproperlyConfigured(f"CATALYST_DB_ROLES[{_key!r}] is not a plain lowercase identifier")
if len(set(CATALYST_DB_ROLES.values())) != 3:
    raise ImproperlyConfigured("the owner, application and retention roles must be three different roles")
# The kind of process for the catalyst.E002 diagnostic. Runtime enforcement does not read it: entry points
# declare their kind in code (config.runtime), so a stale value cannot exempt the web process.
# CATALYST_DB_USER / CATALYST_DB_PASSWORD are the login of whichever role this process uses.
CATALYST_PROCESS = os.environ.get("CATALYST_PROCESS", "management")

def number(name: str, default: str | None = None, cast=int, minimum=1):
    try:
        value = cast(env(name, default))
    except ValueError:
        raise ImproperlyConfigured(f"{name} must be a number") from None
    if value < minimum:
        raise ImproperlyConfigured(f"{name} must be at least {minimum}")
    return value


# Verification challenge lifetime (POL-02 open: no production value is proposed). Required, so no number
# is invented here; compose and CI pass a synthetic value.
CATALYST_CHALLENGE_LIFETIME_SECONDS = number("CATALYST_CHALLENGE_LIFETIME_SECONDS")

# Verification links (ADR-16, D-24). Built from this base URL, never from a request's Host header (the
# worker has no request). The signing key is dedicated: independent of SECRET_KEY, with fallback keys for
# rotation. The link names the confirmation view (applications/views.py, S1-T6).
_base = urlsplit(env("CATALYST_PUBLIC_BASE_URL"))
if _base.scheme not in ("http", "https") or not _base.hostname or _base.path not in ("", "/") or _base.query or _base.fragment:
    raise ImproperlyConfigured("CATALYST_PUBLIC_BASE_URL must be an http(s) origin such as https://example.test")
CATALYST_PUBLIC_BASE_URL = f"{_base.scheme}://{_base.netloc}"
CATALYST_VERIFICATION_KEY = env("CATALYST_VERIFICATION_KEY")
CATALYST_VERIFICATION_FALLBACK_KEYS = [
    k.strip() for k in os.environ.get("CATALYST_VERIFICATION_FALLBACK_KEYS", "").split(",") if k.strip()
]
if SECRET_KEY in [CATALYST_VERIFICATION_KEY, *CATALYST_VERIFICATION_FALLBACK_KEYS]:
    raise ImproperlyConfigured("the verification signing key must differ from SECRET_KEY (ADR-16)")

# Worker (ADR-03, D-16; 005 S1.4). Times are compared with the database clock; these are only lengths.
# The mail timeout must stay well below the lease, so a slow send cannot outlive its claim.
CATALYST_WORKER_LEASE_SECONDS = number("CATALYST_WORKER_LEASE_SECONDS", "300")
CATALYST_WORKER_POLL_SECONDS = number("CATALYST_WORKER_POLL_SECONDS", "5", cast=float, minimum=0.05)
CATALYST_WORKER_RETRY_SECONDS = number("CATALYST_WORKER_RETRY_SECONDS", "60", minimum=0)  # doubles per attempt
EMAIL_TIMEOUT = number("CATALYST_EMAIL_TIMEOUT_SECONDS", "10")
if EMAIL_TIMEOUT * 2 > CATALYST_WORKER_LEASE_SECONDS:
    raise ImproperlyConfigured("CATALYST_EMAIL_TIMEOUT_SECONDS must be at most half of CATALYST_WORKER_LEASE_SECONDS")
# The only action kinds the worker may execute: a fixed mapping in code, never read from the database.
CATALYST_ACTION_HANDLERS = {
    "send_verification": "correspondence.verification.SendVerification",
    "send_message": "correspondence.outbound.SendMessage",  # 016 A3 (P2 2B.1)
    "reconcile_send": "correspondence.outbound.ReconcileSend",  # 016 A5
    "collect": "correspondence.inbound.Collect",  # 016 B (P2 2B.2)
    "file_copy": "correspondence.inbound.FileCopy",  # 016 A4
    "process_reply": "correspondence.processing.ProcessReply",  # 016 D (P2 2B.3)
    "send_staff_message": "correspondence.outbound.SendStaffMessage",  # 016 3.4, not automated (P2 2B.4)
    "remind": "correspondence.reminders.SendReminder",  # 016 E2 (P2 2B.4)
    "escalate_unanswered": "correspondence.reminders.EscalateUnanswered",  # 016 E1, J-08 (P2 2B.4)
    # P3 3B.1 (018 4.1): the S1 action stays held until the owner-run activation command releases it.
    "start_evidence_collection": "assessments.collection.StartEvidenceCollection",
    "fetch_evidence": "assessments.collection.FetchEvidence",
    "run_assessment": "assessments.runs.RunAssessment",  # 018 4 step 4 (P3 3B.2); test models only
    "interpret_message": "correspondence.processing.InterpretMessage",  # 018 5.4 (P3 3B.3); test models only
    # P4 4B.1 (021 section 4): the held `issue_nda` from 3B.4 stays held until `activate_agreements` releases it.
    "issue_nda": "agreements.handlers.IssueAgreement",
    "create_agreement": "agreements.handlers.CreateAgreement",
    "distribute_agreement": "agreements.handlers.DistributeAgreement",
    "reconcile_agreement": "agreements.handlers.ReconcileAgreement",
    "cancel_envelope": "agreements.handlers.CancelEnvelope",
    # P4 4B.2 (021 sections 4 to 6)
    "read_agreement": "agreements.completion.ReadAgreement",
    "advance_agreements": "agreements.completion.AdvanceAgreements",
    "cancel_agreement": "agreements.completion.CancelAgreement",
    "store_agreement": "agreements.custody.StoreAgreement",  # 4B.3 (021 section 7)
    # P5 5B.1 (023 sections 5 and 11): the held `provision` hand-off stays held until `activate_provisioning`.
    "provision_create": "provisioning.handlers.CreateMailbox",
    "provision_reconcile": "provisioning.handlers.ReconcileMailbox",
    "provision_verify": "provisioning.handlers.VerifyMailbox",
}
# P5 provisioning (023; D-47). Synthetic only: the adapter is a local fake set by tests, the domain a `.test` domain
# (P5-D-1), and the limits labelled synthetic defaults (P5-D-2), never unlimited. A live adapter, a provider key and
# the production domain are pre-live gates; the guards refuse them outside the test environment.
CATALYST_PROVISIONING_ADAPTER = ""
CATALYST_PROVISIONING_DOMAIN = ""
CATALYST_PROVISIONING_METHOD = "api"  # P5-D-4: API-first against the fake; "checklist" is the recorded fallback
CATALYST_PROVISIONING_QUOTA_MB = 1024  # synthetic default (P5-D-2)
CATALYST_PROVISIONING_SEND_LIMIT = 100  # synthetic default (P5-D-2)
CATALYST_PROVISIONING_RESERVED_LOCAL_PARTS = []
CATALYST_PROVISIONING_ATTEMPTS = 3
CATALYST_PROVISIONING_RECONCILE_CHECKS = 3
CATALYST_PROVISIONING_RECONCILE_GRACE_SECONDS = 30
CATALYST_PROVISIONING_WATCH_CHECKS = 3
# The one seam through which the applications app opens a staff item for a `needs_staff_attention` event
# (016 3.8; 2B.3). Like the handler mapping, a fixed dotted path in code, so `applications` never imports
# `correspondence` (003 ADR-01) and the creation logic exists once.
CATALYST_ATTENTION_OPENER = "correspondence.staff_items.open_attention"
# P3 3B.3 (018 5.4, step 8): the same seam pattern in the other direction. `correspondence` resolves the reply
# interpreter and the answers-confirmed hook through these fixed paths and never imports `assessments`.
CATALYST_REPLY_INTERPRETER = "assessments.interpret.Interpreter"
CATALYST_ANSWERS_CONFIRMED_HOOK = "assessments.clarification.answers_settled"
# The activation version of message-level reply interpretation (018 5.4). 0: off; process_reply creates no
# `interpret_message` row. The owner turns it on by changing this value in code, then releases earlier replies
# with `activate_reply_interpretation`. Even when on, no model runs outside tests (CATALYST_ASSESSMENT_MODEL).
CATALYST_REPLY_INTERPRETATION_ACTIVATION = 0

# P2 outbound mail (016 A3 to A6, section 6; owner decisions D-27, D-28). Synthetic only: real MXroute is
# prohibited (D-28, A-4). The host must be a literal loopback address, or in `test` the one named
# test-service host; config.guards refuses anything else at start-up and the transport re-checks the
# connected peer before any credential is sent. Unset means no outbound transport: sends are held.
# Names are CATALYST_MAIL_*, never SMTP_* or EMAIL_HOST*, which config.guards refuses as provider names.
CATALYST_MAIL_HOST = os.environ.get("CATALYST_MAIL_HOST", "")
CATALYST_MAIL_PORT = number("CATALYST_MAIL_PORT", "25")
CATALYST_MAIL_TEST_HOST = os.environ.get("CATALYST_MAIL_TEST_HOST", "")  # `test` only: a named test service
CATALYST_MAIL_TLS = os.environ.get("CATALYST_MAIL_TLS", "starttls")  # "starttls", or "none" for loopback only
CATALYST_MAIL_USER = os.environ.get("CATALYST_MAIL_USER", "")
CATALYST_MAIL_PASSWORD = os.environ.get("CATALYST_MAIL_PASSWORD", "")
CATALYST_MAIL_DOMAIN = os.environ.get("CATALYST_MAIL_DOMAIN", "") or _base.hostname  # Message-ID right-hand side
# A certificate authority file the transports trust instead of the system store (synthetic test servers);
# unset means the system store. Verification itself is never switched off.
CATALYST_MAIL_CA_FILE = os.environ.get("CATALYST_MAIL_CA_FILE", "")
# P2 inbound (016 section 4 B and C; 2B.2). IMAP is implicit TLS only (IMAP4_SSL) on the same allowed host.
CATALYST_MAIL_IMAP_PORT = number("CATALYST_MAIL_IMAP_PORT", "993")
CATALYST_MAIL_MAILBOX_REF = os.environ.get("CATALYST_MAIL_MAILBOX_REF", "applicants")  # a configuration key, never an address
CATALYST_MAIL_COLLECT_FOLDER = os.environ.get("CATALYST_MAIL_COLLECT_FOLDER", "INBOX")
# Filed copies of accepted sends (016 A4). Empty means no copies are filed; when set it must differ from the
# collected folder (checked at start-up).
CATALYST_MAIL_SENT_FOLDER = os.environ.get("CATALYST_MAIL_SENT_FOLDER", "")
# The receiving MTA's authserv-id whose Authentication-Results header is trusted (016 C3). Empty: none is,
# so every reply is `unverified` until staff associate it. The production value is unknown (8.3).
CATALYST_MAIL_TRUSTED_AUTHSERV_ID = os.environ.get("CATALYST_MAIL_TRUSTED_AUTHSERV_ID", "")
# Synthetic collection limits (POL-06 and POL-10 values are not decided).
CATALYST_MAIL_POLL_SECONDS = number("CATALYST_MAIL_POLL_SECONDS", "60", cast=float, minimum=0)
CATALYST_MAIL_BATCH_SIZE = number("CATALYST_MAIL_BATCH_SIZE", "50")
CATALYST_MAIL_MAX_MESSAGE_BYTES = number("CATALYST_MAIL_MAX_MESSAGE_BYTES", "1048576")
CATALYST_MAIL_MAX_TEXT_CHARS = number("CATALYST_MAIL_MAX_TEXT_CHARS", "20000")
CATALYST_MAIL_COLLECT_FAILURE_LIMIT = number("CATALYST_MAIL_COLLECT_FAILURE_LIMIT", "5")
CATALYST_MAIL_COLLECTOR_STALE_FACTOR = number("CATALYST_MAIL_COLLECTOR_STALE_FACTOR", "3")
# Loop detection (016 D1, J-08): this many automatic messages for one application within the window pause
# automation and open a staff item. Synthetic values; POL-06 production values are not decided.
CATALYST_MAIL_LOOP_THRESHOLD = number("CATALYST_MAIL_LOOP_THRESHOLD", "3", minimum=2)  # 1 would break the single-autoresponder rule
CATALYST_MAIL_LOOP_WINDOW_SECONDS = number("CATALYST_MAIL_LOOP_WINDOW_SECONDS", "86400")
# Reminders (016 E; POL-06 cadence). Synthetic values; production numbers are decided later (8.2).
CATALYST_REMINDER_MAX = number("CATALYST_REMINDER_MAX", "2", minimum=0)  # then escalate_unanswered
CATALYST_REMINDER_INTERVAL_SECONDS = number("CATALYST_REMINDER_INTERVAL_SECONDS", "259200", minimum=0)
CATALYST_REMINDER_MIN_GAP_SECONDS = number("CATALYST_REMINDER_MIN_GAP_SECONDS", "86400", minimum=0)
CATALYST_REMINDER_QUIET_START_HOUR = number("CATALYST_REMINDER_QUIET_START_HOUR", "21", minimum=0)  # UTC; equal = none
CATALYST_REMINDER_QUIET_END_HOUR = number("CATALYST_REMINDER_QUIET_END_HOUR", "7", minimum=0)
CATALYST_REMINDER_RESUME_GRACE_SECONDS = number("CATALYST_REMINDER_RESUME_GRACE_SECONDS", "3600", minimum=0)
CATALYST_REMINDER_STALE_DEFERRALS = number("CATALYST_REMINDER_STALE_DEFERRALS", "6", minimum=1)  # then collector_stale
# 9kg.3: how often a send held by an unresolved hard bounce looks again (the resolution also releases it at once).
CATALYST_HARD_BOUNCE_RECHECK_SECONDS = number("CATALYST_HARD_BOUNCE_RECHECK_SECONDS", "3600", cast=float, minimum=1)
CATALYST_REMINDER_STALE_RETRY_SECONDS = number("CATALYST_REMINDER_STALE_RETRY_SECONDS", "600", cast=float, minimum=0)
# Evidence fetching (018 3.3; P3 3B.1). Synthetic only: every fetchable host must also be listed here, and the
# guards refuse a non-empty list, a fixture address or a custom CA outside `test` (config.guards.evidence_problems).
# Fixed in code, never read from the environment.
CATALYST_EVIDENCE_ALLOWED_HOSTS: list = []
CATALYST_EVIDENCE_FIXTURE_ADDRESS = ""
CATALYST_EVIDENCE_CA_FILE = ""
CATALYST_EVIDENCE_FETCH_ATTEMPTS = number("CATALYST_EVIDENCE_FETCH_ATTEMPTS", "3")
# Unset, the per-fetch deadline is half the worker lease, at most 10 s (as for the SMTP exchange).
CATALYST_EVIDENCE_DEADLINE_SECONDS = number("CATALYST_EVIDENCE_DEADLINE_SECONDS",
                                            str(max(1, min(10, CATALYST_WORKER_LEASE_SECONDS // 2))))
CATALYST_EVIDENCE_MAX_BYTES = number("CATALYST_EVIDENCE_MAX_BYTES", "262144")
CATALYST_EVIDENCE_MAX_TEXT_CHARS = number("CATALYST_EVIDENCE_MAX_TEXT_CHARS", "20000")
if CATALYST_EVIDENCE_DEADLINE_SECONDS * 2 > CATALYST_WORKER_LEASE_SECONDS:
    raise ImproperlyConfigured("CATALYST_EVIDENCE_DEADLINE_SECONDS must be at most half of CATALYST_WORKER_LEASE_SECONDS")
# The assessment run (018 5.5, 6; P3 3B.2). "none" everywhere except `test`, where "test" selects a PydanticAI
# test model; there is no live value (config.guards.assessment_problems). Fixed in code, never from the environment.
CATALYST_ASSESSMENT_MODEL = "none"
CATALYST_ASSESSMENT_ATTEMPTS = number("CATALYST_ASSESSMENT_ATTEMPTS", "2")
CATALYST_ASSESSMENT_REQUESTS_PER_SNAPSHOT = number("CATALYST_ASSESSMENT_REQUESTS_PER_SNAPSHOT", "4")
CATALYST_ASSESSMENT_RUNS_PER_APPLICATION = number("CATALYST_ASSESSMENT_RUNS_PER_APPLICATION", "6")
CATALYST_ASSESSMENT_TOKENS_PER_APPLICATION = number("CATALYST_ASSESSMENT_TOKENS_PER_APPLICATION", "150000")
CATALYST_ASSESSMENT_INPUT_TOKENS_PER_REQUEST = number("CATALYST_ASSESSMENT_INPUT_TOKENS_PER_REQUEST", "16000")
CATALYST_ASSESSMENT_OUTPUT_TOKENS_PER_ATTEMPT = number("CATALYST_ASSESSMENT_OUTPUT_TOKENS_PER_ATTEMPT", "8000")
CATALYST_ASSESSMENT_CONCURRENT_RUNS = number("CATALYST_ASSESSMENT_CONCURRENT_RUNS", "2")
# Fail-closed: no run proceeds until the owner sets a daily budget (018 6).
CATALYST_ASSESSMENT_DAILY_REQUESTS = number("CATALYST_ASSESSMENT_DAILY_REQUESTS", "0", minimum=0)
# Clarification (018 section 6 and step 5): at most 3 assessment rounds per application, 3 proposals per round.
CATALYST_ASSESSMENT_ROUNDS = number("CATALYST_ASSESSMENT_ROUNDS", "3")
# The qualification decision (018 section 7; P3 3B.4). Who may decide is POL-05: until the owner records it this
# stays None and every decision is refused, superusers included. Once decided it is set here in code to
# "explicit_permission" (assessments.record_qualification_decision, granted to named people only). Never from the
# environment (config.guards.decision_problems).
CATALYST_QUALIFICATION_AUTHORITY = None
# The active selection policy (019 section 6), set in code by a recorded owner activation. Empty: none is approved,
# and decisions record the synthetic rubric they relied on instead.
CATALYST_SELECTION_POLICY = ""
CATALYST_QUESTIONS_PER_ROUND = number("CATALYST_QUESTIONS_PER_ROUND", "3")
# Reply interpretation may use at most this many of the shared daily requests per application (3B.3 review).
CATALYST_INTERPRETATION_DAILY_REQUESTS_PER_APPLICATION = number("CATALYST_INTERPRETATION_DAILY_REQUESTS_PER_APPLICATION", "10")
CATALYST_STAFF_DRAFT_TTL_SECONDS = number("CATALYST_STAFF_DRAFT_TTL_SECONDS", "1800")  # 016 3.4: a preview expires
CATALYST_REMINDER_OVERDUE_MARGIN_SECONDS = number("CATALYST_REMINDER_OVERDUE_MARGIN_SECONDS", "3600", minimum=0)
if CATALYST_REMINDER_QUIET_START_HOUR > 23 or CATALYST_REMINDER_QUIET_END_HOUR > 23:
    raise ImproperlyConfigured("reminder quiet hours are UTC hours 0 to 23")
# Synthetic values; POL-06 production values are not decided (D-29).
CATALYST_MAIL_SEND_ATTEMPTS = number("CATALYST_MAIL_SEND_ATTEMPTS", "3")
# The whole SMTP exchange must end well inside the worker lease; unset, it is half the lease, at most 20 s.
CATALYST_MAIL_SEND_DEADLINE_SECONDS = number(
    "CATALYST_MAIL_SEND_DEADLINE_SECONDS", str(min(20.0, CATALYST_WORKER_LEASE_SECONDS / 2)), cast=float, minimum=0.1)
CATALYST_MAIL_TRANSPORT_BLOCK_LIMIT = number("CATALYST_MAIL_TRANSPORT_BLOCK_LIMIT", "3")
CATALYST_MAIL_TRANSPORT_BACKOFF_SECONDS = number("CATALYST_MAIL_TRANSPORT_BACKOFF_SECONDS", "60", minimum=0)
CATALYST_MAIL_RECONCILE_CHECKS = number("CATALYST_MAIL_RECONCILE_CHECKS", "3")
CATALYST_MAIL_RECONCILE_GRACE_SECONDS = number("CATALYST_MAIL_RECONCILE_GRACE_SECONDS", "300", minimum=0)
if CATALYST_MAIL_SEND_DEADLINE_SECONDS * 2 > CATALYST_WORKER_LEASE_SECONDS:
    raise ImproperlyConfigured("CATALYST_MAIL_SEND_DEADLINE_SECONDS must be at most half of CATALYST_WORKER_LEASE_SECONDS")
# Admissible reconciliation evidence (016 A5): none until a provider check verifies a source (8.3). A
# dotted path to a class with `find(message_id)`; tests point it at a declared synthetic source.
CATALYST_SEND_EVIDENCE_SOURCE = os.environ.get("CATALYST_SEND_EVIDENCE_SOURCE", "")

# P4 agreements (021; 4B.1). Synthetic only: the provider is a local fake Documenso in `test`. The URL, the pinned
# address, the trust store and the API token are fixed in code and empty everywhere else, so nothing can reach a
# real Documenso (config.guards.agreement_problems, TEST-P4-20). A production token arrives through SOPS at P6, never
# as a setting here.
CATALYST_AGREEMENT_PROVIDER_URL = ""  # e.g. https://documenso.test:<port>/api/v2 in tests
CATALYST_AGREEMENT_PROVIDER_ADDRESS = ""  # the literal loopback address the provider host is pinned to
CATALYST_AGREEMENT_PROVIDER_CA_FILE = ""
CATALYST_AGREEMENT_PROVIDER_TOKEN = ""
# Documenso webhook secrets (021 section 6; P4-D-17): the installed version sends a plain shared secret in
# `X-Documenso-Secret`. Two may be valid during a rotation. Fixed in code and empty outside `test`; the webhook route
# is mounted only in `test` and `development` until the P6 exposure decision.
CATALYST_AGREEMENT_WEBHOOK_SECRETS: list = []
# Custody (021 section 7; 4B.3; POL-09 open): an absolute directory outside the repository and any web root, test only
# in synthetic P4. Fixed in code, empty everywhere else.
CATALYST_AGREEMENT_STORAGE_DIR = ""
# Required details per agreement type (POL-18 open: no production field list). Synthetic field names only, set by
# tests; fixed in code and empty everywhere else.
CATALYST_AGREEMENT_REQUIRED_DETAILS: dict = {}
CATALYST_AGREEMENT_DEADLINE_SECONDS = number("CATALYST_AGREEMENT_DEADLINE_SECONDS",
                                             str(max(1, min(10, CATALYST_WORKER_LEASE_SECONDS // 2))))
CATALYST_AGREEMENT_MAX_BYTES = number("CATALYST_AGREEMENT_MAX_BYTES", "1048576")
CATALYST_AGREEMENT_ATTEMPTS = number("CATALYST_AGREEMENT_ATTEMPTS", "3")
CATALYST_AGREEMENT_RECONCILE_CHECKS = number("CATALYST_AGREEMENT_RECONCILE_CHECKS", "3")
CATALYST_AGREEMENT_RECONCILE_GRACE_SECONDS = number("CATALYST_AGREEMENT_RECONCILE_GRACE_SECONDS", "300", minimum=0)
CATALYST_AGREEMENT_DISTRIBUTE_SETTLE_SECONDS = number("CATALYST_AGREEMENT_DISTRIBUTE_SETTLE_SECONDS", "600", minimum=0)
CATALYST_AGREEMENT_LIST_PAGES = number("CATALYST_AGREEMENT_LIST_PAGES", "3")  # the bounded reconciliation listing
CATALYST_AGREEMENT_LIST_PAGE_SIZE = number("CATALYST_AGREEMENT_LIST_PAGE_SIZE", "50")
CATALYST_AGREEMENT_ORPHAN_CHECKS = number("CATALYST_AGREEMENT_ORPHAN_CHECKS", "6")  # P4-D-19: watching an old key
CATALYST_AGREEMENT_RETRY_AFTER_MAX_SECONDS = number("CATALYST_AGREEMENT_RETRY_AFTER_MAX_SECONDS", "3600", minimum=0)
CATALYST_AGREEMENT_READ_INTERVAL_SECONDS = number("CATALYST_AGREEMENT_READ_INTERVAL_SECONDS", "3600", minimum=0)  # the sweep
CATALYST_AGREEMENT_READ_MIN_INTERVAL_SECONDS = number("CATALYST_AGREEMENT_READ_MIN_INTERVAL_SECONDS", "60", minimum=0)
CATALYST_AGREEMENT_WEBHOOK_MAX_BYTES = number("CATALYST_AGREEMENT_WEBHOOK_MAX_BYTES", "65536")
CATALYST_AGREEMENT_MAX_ITEMS = number("CATALYST_AGREEMENT_MAX_ITEMS", "5")  # envelope items stored per agreement
if CATALYST_AGREEMENT_DEADLINE_SECONDS * 2 > CATALYST_WORKER_LEASE_SECONDS:
    raise ImproperlyConfigured("CATALYST_AGREEMENT_DEADLINE_SECONDS must be at most half of CATALYST_WORKER_LEASE_SECONDS")
if CATALYST_AGREEMENT_LIST_PAGE_SIZE > 100:
    raise ImproperlyConfigured("CATALYST_AGREEMENT_LIST_PAGE_SIZE is at most 100 (the installed API's limit)")
if CATALYST_AGREEMENT_MAX_BYTES > 16 * 1024 * 1024 or CATALYST_AGREEMENT_LIST_PAGES > 20:
    raise ImproperlyConfigured("CATALYST_AGREEMENT_MAX_BYTES is at most 16 MiB and CATALYST_AGREEMENT_LIST_PAGES at most 20")

# ADR-18 (D-19): the custom user model exists before the first migration.
AUTH_USER_MODEL = "accounts.User"
# Staff sessions (S1-T7) live in PostgreSQL. Production cookie flags (secure, lifetime) and MFA belong to
# the staging gate (POL-13, catalyst-v2-9kg); ADMINS stays unset so no error mail carries request data.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
LOGIN_URL = "admin:login"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

USE_TZ = True
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
USE_I18N = False

# Local sink only outside production (config.guards). Tests use locmem.
EMAIL_BACKEND = env(
    "CATALYST_EMAIL_BACKEND",
    "django.core.mail.backends.locmem.EmailBackend"
    if CATALYST_ENV == "test"
    else "django.core.mail.backends.console.EmailBackend",
)
EMAIL_FILE_PATH = os.environ.get("CATALYST_EMAIL_FILE_PATH") or None  # the filebased sink's private directory
DEFAULT_FROM_EMAIL = env("CATALYST_FROM_EMAIL", "onboarding@example.invalid")  # synthetic (POL-17)
