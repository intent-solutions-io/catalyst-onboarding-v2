"""Settings for Catalyst v2 (005 S1; ADR-02, ADR-17, ADR-18).

Every value that differs between machines comes from a CATALYST_* environment variable. There is no
database URL and no engine variable: the engine is PostgreSQL, and config.guards refuses anything else.
"""

import os
import re
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

from config.guards import SECRET_ENV_NAMES as SECRET_NAMES  # one list for settings and the guards (6B.5)


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value == "":
        raise ImproperlyConfigured(f"environment variable {name} is required")
    return value


# 6B.5 (026 section 5, P6-D-6): outside test and development every secret is read from its own file in
# CATALYST_SECRETS_DIR (tmpfs, mounted read-only for one process kind), never from the environment, where
# /proc/<pid>/environ, `docker exec env`, child processes and crash dumps would expose it. config.guards refuses a
# secret in the environment there. The file name is the setting's name, lower-case, without the CATALYST_ prefix.
CATALYST_SECRETS_DIR = os.environ.get("CATALYST_SECRETS_DIR", "").strip()


def secret(name: str, default: str | None = None) -> str:
    if not CATALYST_SECRETS_DIR:
        return env(name) if default is None else os.environ.get(name, default)  # an optional secret may be empty
    if name not in SECRET_NAMES:
        raise ImproperlyConfigured(f"{name} is not a listed secret")
    path = os.path.join(CATALYST_SECRETS_DIR, name.removeprefix("CATALYST_").lower())  # symlinks are followed: the
    try:                                                                               # operator mounts these files
        with open(path, encoding="utf-8") as handle:
            value = handle.read().rstrip("\r\n")  # only the line ending; a secret's own spaces are kept
    except FileNotFoundError:
        value = ""
    except (OSError, UnicodeDecodeError) as exc:  # never the bytes, only which secret and why
        raise ImproperlyConfigured(f"secret {name} cannot be read from CATALYST_SECRETS_DIR ({type(exc).__name__})") from None
    if value:
        return value
    if default is not None:
        return default
    raise ImproperlyConfigured(f"secret {name} is missing from CATALYST_SECRETS_DIR")


CATALYST_ENV = env("CATALYST_ENV")
SECRET_KEY = secret("CATALYST_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = [h.strip() for h in env("CATALYST_ALLOWED_HOSTS", "localhost").split(",") if h.strip()]
# 6B.3 (026 section 8): the host names that may read the health paths (the proxy's local socket) and the one staff
# host that may serve the staff screens and the admin. Staging and later must name a staff host (config.guards).
CATALYST_LOCAL_HOSTS = [h.strip() for h in os.environ.get("CATALYST_LOCAL_HOSTS", "localhost").split(",") if h.strip()]
CATALYST_STAFF_HOST = os.environ.get("CATALYST_STAFF_HOST", "").strip()
# bgl.2 (034 section 3.1): other host names the public applicant pages answer on, for the learning host's proxy, which
# forwards the first generation's exact paths with the browser's Host and Origin unchanged. Comma-separated, empty by
# default (with several, write ", " between them: the stack proxy reads the same value as its site address list); each
# is added to ALLOWED_HOSTS and (outside the local environments) to CSRF_TRUSTED_ORIGINS as https://<alias>.
# config.guards refuses a non-plain name, a wildcard, the staff host and a local host; HostGuard never serves the staff
# screens or the health paths on one; the stack proxy forwards only the public request paths for them.
CATALYST_PUBLIC_HOST_ALIASES = [h.strip() for h in os.environ.get("CATALYST_PUBLIC_HOST_ALIASES", "").split(",") if h.strip()]
ALLOWED_HOSTS += [h for h in CATALYST_PUBLIC_HOST_ALIASES if h not in ALLOWED_HOSTS]

INSTALLED_APPS = [
    "config.apps.CatalystConfig",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    # The read-only staff view (S1-T7, D-23): Django Admin with database sessions and its messages.
    "django.contrib.admin",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",  # 6B.5: the admin's stylesheets, collected into the image, served by the proxy
    # 6B.9 (026 section 8, P6-D-3): staff two-factor, TOTP devices and single-use recovery codes (accounts.staff_access).
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "accounts",
    "workflow",
    "applications",
    "correspondence",
    "assessments",  # P3 (018; D-34)
    "agreements",  # P4 (021; D-37)
    "provisioning",  # P5 (023; D-47)
    "erasure",  # 9kg.32 (029 section 6.2): the authorized erasure path
]
MIDDLEWARE = [
    "config.redaction.PrivateConfirmationResponses",  # outermost: covers responses built outside the view
    "config.health.HostGuard",  # 6B.3: no staff, admin or health path on the public host
    "django.middleware.security.SecurityMiddleware",
    "config.security_headers.ContentSecurityPolicy",  # 6B.2: Django has no CSP of its own
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",  # 6B.9: request.user.is_verified()
    "accounts.staff_access.StaffAccess",  # 6B.9: two-factor and the absolute lifetime for everything under /staff/
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
SECURE_REFERRER_POLICY = "same-origin"  # never tells another site where a visitor came from. Not "no-referrer": with it,
# a real browser sends `Origin: null` on its own form posts and the CSRF check refuses every one (live canary, 2026-10-29)
# Pinned rather than left to Django's defaults, so an upgrade cannot loosen them (PR #61 review).
X_FRAME_OPTIONS = "DENY"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SAMESITE = CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True
ROOT_URLCONF = "config.urls"
STATIC_URL = "/static/"
STATIC_ROOT = os.environ.get("CATALYST_STATIC_ROOT", "") or None  # the image collects into /app/static
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
        "PASSWORD": secret("CATALYST_DB_PASSWORD"),
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
    "backup": env("CATALYST_DB_BACKUP_ROLE", "catalyst_backup"),  # 6B.6: reads for the backup job, never writes
    "fetcher": env("CATALYST_DB_FETCHER_ROLE", "catalyst_fetcher"),  # 9kg.24: only what the evidence fetch touches
}
# Role names reach SQL as identifiers in migrations: accept only plain lowercase identifiers.
for _key, _role in CATALYST_DB_ROLES.items():
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", _role):
        raise ImproperlyConfigured(f"CATALYST_DB_ROLES[{_key!r}] is not a plain lowercase identifier")
if len(set(CATALYST_DB_ROLES.values())) != len(CATALYST_DB_ROLES):
    raise ImproperlyConfigured("the owner, application, retention, backup and fetcher roles must be different roles")
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
# 9kg.50: how many times staff may resend the verification message for one application (a new challenge each time,
# the old one superseded; the applicant-facing message is the same). A synthetic default until 211.7.7 (POL-02).
CATALYST_VERIFICATION_RESEND_LIMIT = number("CATALYST_VERIFICATION_RESEND_LIMIT", "3", minimum=0)
if CATALYST_VERIFICATION_RESEND_LIMIT > 10:  # security review of PR #87: a resend is a send to an unverified address
    raise ImproperlyConfigured("CATALYST_VERIFICATION_RESEND_LIMIT must be at most 10")

# Verification links (ADR-16, D-24). Built from this base URL, never from a request's Host header (the
# worker has no request). The signing key is dedicated: independent of SECRET_KEY, with fallback keys for
# rotation. The link names the confirmation view (applications/views.py, S1-T6).
_base = urlsplit(env("CATALYST_PUBLIC_BASE_URL"))
if _base.scheme not in ("http", "https") or not _base.hostname or _base.path not in ("", "/") or _base.query or _base.fragment:
    raise ImproperlyConfigured("CATALYST_PUBLIC_BASE_URL must be an http(s) origin such as https://example.test")
CATALYST_PUBLIC_BASE_URL = f"{_base.scheme}://{_base.netloc}"
# The fetcher builds no links, so it does not get the link-signing key (026 section 5; PR #65 review).
CATALYST_PROCESS_ROLE = os.environ.get("CATALYST_PROCESS_ROLE", "").strip()
CATALYST_VERIFICATION_KEY = secret("CATALYST_VERIFICATION_KEY", "" if CATALYST_PROCESS_ROLE == "fetcher" else None)
CATALYST_VERIFICATION_FALLBACK_KEYS = [
    k.strip() for k in secret("CATALYST_VERIFICATION_FALLBACK_KEYS", "").split(",") if k.strip()
]
if SECRET_KEY in [k for k in (CATALYST_VERIFICATION_KEY, *CATALYST_VERIFICATION_FALLBACK_KEYS) if k]:
    raise ImproperlyConfigured("the verification signing key must differ from SECRET_KEY (ADR-16)")

# Worker (ADR-03, D-16; 005 S1.4). Times are compared with the database clock; these are only lengths.
# The mail timeout must stay well below the lease, so a slow send cannot outlive its claim.
CATALYST_WORKER_LEASE_SECONDS = number("CATALYST_WORKER_LEASE_SECONDS", "300")
# 6B.4 (026 section 7): the worker's heartbeat file (empty: none) and the health command's thresholds, placeholders
# until POL-16 (P6-D-9). A stale heartbeat is twice the lease: one action may legitimately run that long.
CATALYST_WORKER_HEARTBEAT_FILE = os.environ.get("CATALYST_WORKER_HEARTBEAT_FILE", "").strip()
CATALYST_HEALTH_HEARTBEAT_STALE_SECONDS = number("CATALYST_HEALTH_HEARTBEAT_STALE_SECONDS", str(2 * CATALYST_WORKER_LEASE_SECONDS))
CATALYST_HEALTH_PENDING_AGE_SECONDS = number("CATALYST_HEALTH_PENDING_AGE_SECONDS", "3600")
CATALYST_HEALTH_HARD_BOUNCE_AGE_SECONDS = number("CATALYST_HEALTH_HARD_BOUNCE_AGE_SECONDS", "86400")
# 9kg.51 (029 section 5.2): the waits that had no bound. Each class has its own age threshold (default: the pending-age
# target above) and the page list says which classes raise a health anomaly (default: all); a class not listed is
# still counted and its oldest age printed. The values are the owner's (211.7.2, 211.7.7); these are placeholders.
CATALYST_HEALTH_AGED_WAIT_CLASSES = ("assessing", "awaiting_decision", "on_hold", "open_staff_items", "pauses",
                                     "replies_awaiting_processing", "issued_agreements", "provisioning_activation",
                                     "held_followons")  # 9kg.57
CATALYST_HEALTH_AGED_WAIT_SECONDS = {
    name: number(f"CATALYST_HEALTH_AGED_WAIT_{name.upper()}_SECONDS", str(CATALYST_HEALTH_PENDING_AGE_SECONDS), cast=float,
                 minimum=0) for name in CATALYST_HEALTH_AGED_WAIT_CLASSES}
# Default page list: the three classes that are bad in themselves (a reply nobody is processing, a sent agreement
# nobody signs, an activation the provider keeps refusing); the stage, item and pause classes are counted and
# printed but page only once the owner lists them (211.7.2). So are the held follow-ons (9kg.57): at the internal
# launch a held decline notice (oc4.11) and a held provisioning hand-off (provisioning disabled) are the plan, not a fault.
CATALYST_HEALTH_AGED_WAITS_PAGE = [n.strip() for n in os.environ.get(
    "CATALYST_HEALTH_AGED_WAITS_PAGE", "replies_awaiting_processing,issued_agreements,provisioning_activation").split(",") if n.strip()]
if set(CATALYST_HEALTH_AGED_WAITS_PAGE) - set(CATALYST_HEALTH_AGED_WAIT_CLASSES):
    raise ImproperlyConfigured("CATALYST_HEALTH_AGED_WAITS_PAGE names an unknown wait class")
CATALYST_WORKER_POLL_SECONDS = number("CATALYST_WORKER_POLL_SECONDS", "5", cast=float, minimum=0.05)
CATALYST_WORKER_RETRY_SECONDS = number("CATALYST_WORKER_RETRY_SECONDS", "60", minimum=0)  # doubles per attempt
EMAIL_TIMEOUT = number("CATALYST_EMAIL_TIMEOUT_SECONDS", "10")
if EMAIL_TIMEOUT * 2 > CATALYST_WORKER_LEASE_SECONDS:
    raise ImproperlyConfigured("CATALYST_EMAIL_TIMEOUT_SECONDS must be at most half of CATALYST_WORKER_LEASE_SECONDS")
# 9kg.33 (029 section 6.2): the effect journal, the one durable record outside the backup's rollback domain
# (workflow.journal). An absolute directory outside the repository, shared by every process on the host; required
# outside test and development (config.guards). Empty in the local environments means no durable effects.
CATALYST_EFFECT_JOURNAL_DIR = os.environ.get("CATALYST_EFFECT_JOURNAL_DIR", "").strip()
# 9kg.60: the journal's off-host copy (workflow.shipping). When above 0, the health part pages once the oldest entry
# not yet shipped is older than this many seconds, or nothing was ever shipped. 0 turns the signal off, allowed only
# outside a live environment (config.guards). The value is the journal's RPO, the owner's (211.7.2).
CATALYST_JOURNAL_SHIP_LAG_SECONDS = number("CATALYST_JOURNAL_SHIP_LAG_SECONDS", "0", minimum=0)
# 9kg.32 (029 section 6.2): the key of the durable erasure record's keyed hashes (erasure.record states its custody).
# Optional here: only the owner-run erasure command (and the post-restore replay, 9kg.25) needs it, and refuses
# without it. A file in CATALYST_SECRETS_DIR outside test and development, never in the database or a backup set.
CATALYST_ERASURE_KEY = secret("CATALYST_ERASURE_KEY", "")
# The only action kinds the worker may execute: a fixed mapping in code, never read from the database.
CATALYST_ACTION_HANDLERS = {
    "send_verification": "correspondence.verification.SendVerification",
    "verification_expiry_sweep": "correspondence.verification.SweepExpiredVerification",  # 9kg.66: expired only links
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
    "complete_evidence_collection": "assessments.collection.CompleteEvidenceCollection",  # 9kg.24: run by the worker
    "run_assessment": "assessments.runs.RunAssessment",  # 018 4 step 4 (P3 3B.2); test models only
    "interpret_message": "correspondence.processing.InterpretMessage",  # 018 5.4 (P3 3B.3); test models only
    # oc4.11: a recorded decline queues `send_decline`, which freezes the decline notice and hands it to send_message.
    "send_decline": "assessments.decline.SendDecline",
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
    # P5 5B.2 (023 sections 5 steps 6 and 7, 11.2 and 11.5)
    "provision_invite": "provisioning.credentials.SendSetupInvitation",
    "provision_setup_sweep": "provisioning.credentials.SweepSetup",
    "provision_activate": "provisioning.credentials.Activate",
    # P5 5B.3 (023 sections 6 and 11.6)
    "provision_revoke": "provisioning.closure.RevokeAccess",
    "provision_withdraw_send": "provisioning.closure.SendWithdrawalLink",
    "clear_sessions": "accounts.staff_access.ClearSessions",  # 6B.9: expired staff sessions, hourly
}
# P5 provisioning (023; D-47). Synthetic only: the adapter is a local fake set by tests, the domain a `.test` domain
# (P5-D-1), and the limits labelled synthetic defaults (P5-D-2), never unlimited. A live adapter, a provider key and
# the production domain are pre-live gates; the guards refuse them outside the test and staging environments.
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
# 5B.2: the set-your-own-password link (synthetic values; production policy is the owner's).
CATALYST_SETUP_LINK_SECONDS = 86400
CATALYST_SETUP_INVITE_MAX_SERIES = 3  # 023 11.2: then staff decide (OWNER: the production bound)
CATALYST_SETUP_SET_ATTEMPTS = 3  # 023 11.11: definite password rejections before a new series
CATALYST_SETUP_SET_TIMEOUT_SECONDS = 60  # a set_pending older than this is set_uncertain (023 11.5)
# The one seam through which the applications app opens a staff item for a `needs_staff_attention` event
# (016 3.8; 2B.3). Like the handler mapping, a fixed dotted path in code, so `applications` never imports
# `correspondence` (003 ADR-01) and the creation logic exists once.
CATALYST_ATTENTION_OPENER = "correspondence.staff_items.open_attention"
# 9kg.52: the same seam for the data notice and the invitation mail (applications.notices): the templates are read
# and rendered by this module (its `approved`, `draft` and `status`), resolved by the fixed path, never by an import.
CATALYST_NOTICE_SOURCE = "correspondence.notices"
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
CATALYST_MAIL_PASSWORD = secret("CATALYST_MAIL_PASSWORD", "")
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
# 9kg.85 (033 Q9): 02:00 to 13:00 UTC, the night across the cohort's US time zones.
CATALYST_REMINDER_QUIET_START_HOUR = number("CATALYST_REMINDER_QUIET_START_HOUR", "2", minimum=0)  # UTC; equal = none
CATALYST_REMINDER_QUIET_END_HOUR = number("CATALYST_REMINDER_QUIET_END_HOUR", "13", minimum=0)
CATALYST_REMINDER_RESUME_GRACE_SECONDS = number("CATALYST_REMINDER_RESUME_GRACE_SECONDS", "3600", minimum=0)
CATALYST_REMINDER_STALE_DEFERRALS = number("CATALYST_REMINDER_STALE_DEFERRALS", "6", minimum=1)  # then collector_stale
# 9kg.3: how often a send held by an unresolved hard bounce looks again (the resolution also releases it at once).
CATALYST_HARD_BOUNCE_RECHECK_SECONDS = number("CATALYST_HARD_BOUNCE_RECHECK_SECONDS", "3600", cast=float, minimum=1)
CATALYST_REMINDER_STALE_RETRY_SECONDS = number("CATALYST_REMINDER_STALE_RETRY_SECONDS", "600", cast=float, minimum=0)
# oc4.11: how often a decline notice that cannot be prepared yet (wording not approved here, no verified address)
# looks again; one staff item says why meanwhile. Fixed in code.
CATALYST_DECLINE_NOTICE_RECHECK_SECONDS = 900
# Evidence fetching (018 3.3; P3 3B.1). Synthetic only: every fetchable host must also be listed here, and the
# guards refuse a non-empty list, a fixture address or a custom CA outside `test` (config.guards.evidence_problems).
# Fixed in code, never read from the environment.
CATALYST_EVIDENCE_ALLOWED_HOSTS: list = []
CATALYST_EVIDENCE_FIXTURE_ADDRESS = ""
CATALYST_EVIDENCE_CA_FILE = ""
# 6B.11 (026 section 5, H5): "host:port" of the egress proxy (assessments.egress). When set, every fetch is a CONNECT
# tunnel through it: the fetcher's own network reaches nothing else. Required for a staging fetcher (config.guards).
CATALYST_EVIDENCE_PROXY = os.environ.get("CATALYST_EVIDENCE_PROXY", "").strip()
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
# oc4.9 / oc4.10 item 7: the wall time of one model request, enforced by Catalyst around the call (agent.run_checked)
# and passed to the provider client. One attempt (the call and the repair) must fit in half the worker lease
# (config.guards.assessment_problems), so a lease is never reclaimed while an attempt is in flight.
# Unset: a quarter of the lease, at most 60 s (018 section 6).
CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS = number(
    "CATALYST_ASSESSMENT_REQUEST_TIMEOUT_SECONDS", str(min(60.0, CATALYST_WORKER_LEASE_SECONDS / 4)), cast=float, minimum=0.1)
# Fail-closed: no run proceeds until the owner sets a daily budget (018 6).
CATALYST_ASSESSMENT_DAILY_REQUESTS = number("CATALYST_ASSESSMENT_DAILY_REQUESTS", "0", minimum=0)
# Clarification (018 section 6 and step 5): at most 3 assessment rounds per application, 3 proposals per round.
CATALYST_ASSESSMENT_ROUNDS = number("CATALYST_ASSESSMENT_ROUNDS", "3")
# The qualification decision (018 section 7; P3 3B.4). Who may decide is POL-05: until the owner records it this
# stays unset (None) and every decision is refused, superusers included. The one value the code implements is
# "explicit_permission" (assessments.record_qualification_decision, granted to named people only, by
# `grant_staff_role`); the guard refuses any other (config.guards.decision_problems). Configuration-driven since
# 9kg.30 (029 section 5.2): the launch host sets it when `211.7.8` names the holders, with no code change.
CATALYST_QUALIFICATION_AUTHORITY = os.environ.get("CATALYST_QUALIFICATION_AUTHORITY", "").strip() or None
# The active selection policy (019 section 6), set in code by a recorded owner activation. Empty: none is approved,
# and decisions record the synthetic rubric they relied on instead. A policy names the prompt pack it was approved
# with (oc4.12, oc4.10 item 1): the guard refuses a policy that is unbound or bound to a synthetic rubric, and a
# decision refuses a pack other than the bound one.
CATALYST_SELECTION_POLICY = ""
CATALYST_SELECTION_POLICY_PACKS = {}  # {"SP-L2-1": "assessment_v<n>"}, written by the activation that approves both
# oc4.12 (019 decision 4, section 10): the launch-wide suspension of model advice, recorded in 011 section 4.1. Every
# human-only decision taken under it cites this reference in its structured reason; fixed in code, like the policy.
CATALYST_MODEL_ADVICE_SUSPENSION_REF = "011:4.1:2026-10-23:model-advice-suspended"
# The policy identifier every cohort decision records while no policy is active and model advice is off (council
# record 030 Q8; D-M): the literal below, never the synthetic rubric's reference. Once advice is on, the rubric
# reference applies again. Fixed in code.
CATALYST_NO_POLICY_LABEL = "none: internal cohort, D-M"
# oc4.8 (recommended default, oc4.12): what clears a capped assessment snapshot. "human_only": the authority-gated
# human-only decision form; "none": nothing (a capped case waits for the owner's budget decision). Fixed in code.
CATALYST_CAPPED_EXIT = "human_only"
if CATALYST_CAPPED_EXIT not in ("human_only", "none"):
    raise ImproperlyConfigured("CATALYST_CAPPED_EXIT must be 'human_only' or 'none'")
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
# Admissible reconciliation evidence (016 A5): a dotted path to a class with `find(message_id)` and `within(since)`.
# 9kg.49: the production value is the read-only Sent-folder reader (correspondence.sent_reader.SentFolderSource),
# allowed in every environment; any other source only in `test` (config.guards). Whether the provider's Sent
# copies are made only on acceptance is the mail canary's finding (016 8.3), not this setting's.
CATALYST_SEND_EVIDENCE_SOURCE = os.environ.get("CATALYST_SEND_EVIDENCE_SOURCE", "")
CATALYST_MAIL_SENT_SCAN_LIMIT = number("CATALYST_MAIL_SENT_SCAN_LIMIT", "500")  # newest copies one read may fetch
# 9kg.49: the exact production mail-host allow-list (lower-case host names; the one the production environment
# may connect to, for the web and worker roles only). Required and non-empty in a live environment, refused in
# the synthetic ones and in development, where only loopback (or the named test host) is ever allowed.
CATALYST_MAIL_ALLOWED_HOSTS = [h.strip().lower() for h in os.environ.get("CATALYST_MAIL_ALLOWED_HOSTS", "").split(",") if h.strip()]
# 9kg.49: SHA-256 digests (lower-case hex) of mailbox logins that may never be configured as this service's
# mailbox: the first-generation service's own mailbox, so v2 can never become a second poller or reader of it.
# Digests, not names: the repository is public and names nothing.
CATALYST_MAIL_DENIED_USER_SHA256 = [d.strip().lower() for d in os.environ.get("CATALYST_MAIL_DENIED_USER_SHA256", "").split(",") if d.strip()]
# 9kg.49 (security review): the positive pin of the one v2 mailbox login, a SHA-256 hex digest CATALYST_MAIL_USER must
# hash to; required in a live environment, re-checked before any login. Private: never pasted into a PR or a doc.
CATALYST_MAIL_USER_SHA256 = os.environ.get("CATALYST_MAIL_USER_SHA256", "").strip().lower()

# P4 agreements (021; 4B.1). Synthetic only: the provider is a local fake Documenso in `test` and `staging`. The URL, the pinned
# address, the trust store and the API token are fixed in code and empty everywhere else, so nothing can reach a
# real Documenso (config.guards.agreement_problems, TEST-P4-20). A production token arrives through SOPS at P6, never
# as a setting here.
CATALYST_AGREEMENT_PROVIDER_URL = ""  # e.g. https://documenso.test:<port>/api/v2 in tests
CATALYST_AGREEMENT_PROVIDER_ADDRESS = ""  # the literal loopback address the provider host is pinned to
CATALYST_AGREEMENT_PROVIDER_CA_FILE = ""
CATALYST_AGREEMENT_PROVIDER_TOKEN = ""
# Documenso webhook secrets (021 section 6; P4-D-17): the installed version sends a plain shared secret in
# `X-Documenso-Secret`. Two may be valid during a rotation. Fixed in code and empty outside `test` and `staging`; the webhook route
# is mounted only in `test` and `development` until the P6 exposure decision.
CATALYST_AGREEMENT_WEBHOOK_SECRETS: list = []
# Custody (021 section 7; 4B.3; POL-09 open): an absolute directory outside the repository and any web root, test and
# staging only (synthetic P4). Fixed in code, empty everywhere else.
CATALYST_AGREEMENT_STORAGE_DIR = ""
# 9kg.34 (026 section 6 option c; 030 Q4, D-51): custody encryption at rest (agreements.keystore). The wrapped data keys
# live in a key directory and its live mirror, both outside the custody directory and the backup set; like the storage
# directory they are fixed in code and empty outside `test` and `staging` until the owner's custody decision (211.7.9,
# agreements.custody_policy). The wrapping key is a secret file (`custody_wrapping_key` in CATALYST_SECRETS_DIR outside
# test and development): 64 lower-case hex characters (32 random bytes), its recovery copy escrowed in the operator's
# encrypted secret store, never in the database, a backup set, the journal, a receipt or a log. Optional: only the web
# process (decision-maker retrieval), the worker (custody writes) and the owner-run custody commands hold it.
CATALYST_CUSTODY_WRAPPING_KEY = secret("CATALYST_CUSTODY_WRAPPING_KEY", "")
# 9kg.69: the next wrapping key (`custody_next_wrapping_key`), mounted only into the owner-run rotation
# (`catalyst_custody_keys --rotate`) for that run; every other process refuses to start holding it (config.guards).
CATALYST_CUSTODY_NEXT_WRAPPING_KEY = secret("CATALYST_CUSTODY_NEXT_WRAPPING_KEY", "")
CATALYST_CUSTODY_KEY_DIR = ""
CATALYST_CUSTODY_KEY_MIRROR_DIR = ""
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
# Staff sessions (S1-T7) live in PostgreSQL. ADMINS stays unset so no error mail carries request data.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
LOGIN_URL = "admin:login"
# Idle timeout for every environment (026 section 8, 6B.2): a session lasts 30 minutes from its last request and
# ends when the browser closes. Django has no idle timeout of its own; saving on every request makes the expiry slide.
SESSION_COOKIE_AGE = 30 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
# 6B.9 (026 section 8, P6-D-3; accounts.staff_access). Fixed in code, not read from the environment: two-factor is
# required everywhere but the local environments, where tests sign staff in directly.
CATALYST_STAFF_TWO_FACTOR = CATALYST_ENV not in ("test", "development")
CATALYST_STAFF_SESSION_MAX_SECONDS = 8 * 3600  # absolute lifetime from login, however active (PR #61 review)
CATALYST_STAFF_LOGIN_FAILURE_LIMIT = 5
CATALYST_STAFF_LOGIN_LOCK_SECONDS = 15 * 60
CATALYST_SESSION_CLEANUP_SECONDS = 3600  # the clear_sessions action's interval
# 9kg.66: the verification expiry sweep's interval (correspondence.verification); how late an expired-link item opens.
CATALYST_VERIFICATION_SWEEP_SECONDS = 900
AUTHENTICATION_BACKENDS = ["accounts.staff_access.ThrottledModelBackend"]
OTP_TOTP_ISSUER = "Catalyst " + CATALYST_ENV
CSRF_COOKIE_HTTPONLY = True  # every form carries its token in the page; no script reads the cookie

# Web security outside the local environments (026 section 8, 6B.2). Staging and anything later run only behind the
# proxy, over https: secure host-only cookies, the proxy's https header trusted (the web process listens only on the
# proxy's local socket, so the proxy is the one hop that sets it), redirects to https except the local health paths,
# and a short HSTS without subdomains or preload, because the parent domain is shared with other estate sites.
LOCAL_ENVIRONMENTS = ("test", "development")
if CATALYST_ENV not in LOCAL_ENVIRONMENTS:
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_NAME = "__Host-catalyst-session"  # __Host-: secure, path /, no Domain, so no sibling host gets it
    CSRF_COOKIE_NAME = "__Host-catalyst-csrf"
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [r"^healthz$", r"^readyz$"]  # reached only through the local socket (6B.3)
    SECURE_HSTS_SECONDS = 300
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
    CSRF_TRUSTED_ORIGINS = [CATALYST_PUBLIC_BASE_URL, *(f"https://{alias}" for alias in CATALYST_PUBLIC_HOST_ALIASES)]
    # Deliberate (026 P6-D-3, section 8): HSTS stays short and covers no subdomains and no preload list.
    SILENCED_SYSTEM_CHECKS = ["security.W005", "security.W021"]

# 9kg.29 (029 section 4.1; REQ-027): the public endpoints' limits, counted in PostgreSQL per fixed window
# (config.throttle). Owner settings (POL-16): these are synthetic placeholders, one window length for every bucket.
CATALYST_THROTTLE_WINDOW_SECONDS = number("CATALYST_THROTTLE_WINDOW_SECONDS", "600")
CATALYST_THROTTLE_INTAKE_PER_CLIENT = number("CATALYST_THROTTLE_INTAKE_PER_CLIENT", "10")  # form posts per client
CATALYST_THROTTLE_INTAKE_PER_ADDRESS = number("CATALYST_THROTTLE_INTAKE_PER_ADDRESS", "3")  # verification issuance per address key
CATALYST_THROTTLE_LINK_PER_CLIENT = number("CATALYST_THROTTLE_LINK_PER_CLIENT", "30")  # confirm, setup and withdraw requests per client
CATALYST_THROTTLE_LINK_PER_TOKEN = number("CATALYST_THROTTLE_LINK_PER_TOKEN", "10")  # requests per link token
CATALYST_THROTTLE_WEBHOOK_PER_CLIENT = number("CATALYST_THROTTLE_WEBHOOK_PER_CLIENT", "120")
# The client identity the limits key on (config.client_identity). Fixed in code: "proxy" wherever the web process
# listens on the proxy's socket (the proxy overwrites X-Forwarded-For with the peer address and trusts no proxy, 026
# section 8), "direct" in the local environments, where the test client or the development server is the peer.
# config.guards refuses any other value, an environment-sourced value, and "direct" outside the local environments.
CATALYST_CLIENT_IDENTITY = "direct" if CATALYST_ENV in LOCAL_ENVIRONMENTS else "proxy"
# 9kg.43 (029 sections 4.1 and 7): who may apply. "invitation": only an address holding a live invitation issued by the
# owner-run `catalyst_invite` (applications.invitations); "open": anyone (034 row 2, bgl.2: the public entry on the
# first-generation URLs). Read from the environment so the host opens or closes intake without a release; unset is
# invitation-only, and any value but the two is refused at start-up (config.guards), never an open form. The release
# receipt and the health report record the mode in force. The test suite opens it per test (tests/conftest.py) and
# proves the default from a fresh process.
CATALYST_INTAKE_MODE = os.environ.get("CATALYST_INTAKE_MODE", "invitation")
# bgl.2 (034 row 4): the request form's bot checks (applications.abuse). A hidden honeypot field and a signed render
# time: a filled honeypot gets the received page and nothing is recorded; a missing, forged or expired render time, or
# a submission faster than a person could fill the form, gets the form back (status 400) and nothing is recorded.
# The first generation's values: at least 3 seconds and at most 2 hours after the page was rendered.
CATALYST_INTAKE_FORM_CHECKS = True  # fixed in code; the test suite turns it off per test (tests/conftest.py)
CATALYST_INTAKE_FORM_MIN_AGE_SECONDS = number("CATALYST_INTAKE_FORM_MIN_AGE_SECONDS", "3", minimum=0)
CATALYST_INTAKE_FORM_MAX_AGE_SECONDS = number("CATALYST_INTAKE_FORM_MAX_AGE_SECONDS", str(2 * 3600))
# bgl.2 (034 row 5): global caps on new applications per UTC clock hour and per UTC day (the first generation's 30 and
# 100). A new application over a cap is still accepted and stored; its verification mail, and so its confirmation and
# everything after it, waits for the first window with room (applications.services).
CATALYST_INTAKE_GLOBAL_PER_HOUR = number("CATALYST_INTAKE_GLOBAL_PER_HOUR", "30")
CATALYST_INTAKE_GLOBAL_PER_DAY = number("CATALYST_INTAKE_GLOBAL_PER_DAY", "100")
CATALYST_INVITATION_LIFETIME_SECONDS = number("CATALYST_INVITATION_LIFETIME_SECONDS", str(14 * 86400))
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

# A local sink in every environment but production (config.guards). In production Django's own mails go through
# correspondence.transport, the one SMTP path (config.mail, 9kg.77); `config.mail.RefusingEmailBackend` is the explicit
# hold. No live link is ever written to disk. Tests use locmem.
EMAIL_BACKEND = env(
    "CATALYST_EMAIL_BACKEND",
    {"test": "django.core.mail.backends.locmem.EmailBackend",
     # a deployment: a private file sink, never the console, whose output lands in container logs with bearer links
     "staging": "django.core.mail.backends.filebased.EmailBackend",
     "production": "config.mail.TransportEmailBackend"}.get(
        CATALYST_ENV, "django.core.mail.backends.console.EmailBackend"),
)
EMAIL_FILE_PATH = os.environ.get("CATALYST_EMAIL_FILE_PATH") or None  # the filebased sink's private directory
DEFAULT_FROM_EMAIL = env("CATALYST_FROM_EMAIL", "onboarding@example.invalid")  # synthetic (POL-17)
