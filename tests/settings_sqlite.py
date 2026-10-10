# Deliberately wrong settings used only to prove that start-up refuses a non-PostgreSQL engine.
from config.settings import *  # noqa: F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
