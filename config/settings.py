"""Settings for Catalyst v2 (005 S1; ADR-02, ADR-17, ADR-18).

Every value that differs between machines comes from a CATALYST_* environment variable. There is no
database URL and no engine variable: the engine is PostgreSQL, and config.guards refuses anything else.
"""

import os

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
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
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

# ADR-18 (D-19): the custom user model exists before the first migration.
AUTH_USER_MODEL = "accounts.User"

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
