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
# The form has three fields plus the CSRF token; 64 KiB covers its longest percent-encoded values.
DATA_UPLOAD_MAX_MEMORY_SIZE = 64 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10
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
CATALYST_ACTION_HANDLERS = {"send_verification": "correspondence.verification.SendVerification"}

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
