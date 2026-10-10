"""Settings for Catalyst v2 (005 S1; ADR-02, ADR-17, ADR-18).

Every value that differs between machines comes from a CATALYST_* environment variable. There is no
database URL and no engine variable: the engine is PostgreSQL, and config.guards refuses anything else.
"""

import os
import re

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
    "accounts",
    "workflow",
    "applications",
    "correspondence",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
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
# The kind of process: "web" and "worker" must connect as the application role (config.checks, E002).
# CATALYST_DB_USER / CATALYST_DB_PASSWORD are the login of whichever role this process uses.
CATALYST_PROCESS = os.environ.get("CATALYST_PROCESS", "management")

# ADR-18 (D-19): the custom user model exists before the first migration.
AUTH_USER_MODEL = "accounts.User"
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
