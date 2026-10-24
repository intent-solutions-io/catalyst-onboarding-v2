import os

from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class CatalystConfig(AppConfig):
    """Hosts the start-up guards; holds no models. First in INSTALLED_APPS, so it runs before any other app."""

    name = "config"
    label = "catalyst_config"
    verbose_name = "Catalyst configuration"

    def ready(self):
        from django.conf import settings
        from django.db.backends.signals import connection_created

        from . import checks, guards, redaction, runtime  # noqa: F401  (importing checks registers catalyst.E001, E002)

        problems = guards.all_problems(settings, os.environ)
        if problems:
            raise ImproperlyConfigured("Catalyst refuses to start: " + "; ".join(problems))
        # No query here: the receiver checks each new connection, and only in web and worker processes.
        connection_created.connect(runtime.enforce_on_connect, dispatch_uid="catalyst.db_role_enforcement")
        redaction.install()  # confirmation tokens never reach Django's request, CSRF or server log records
        if runtime.process_kind() == "web":  # declared before Django loads (config/wsgi.py); the worker sweeps in run_worker
            sweep_custody_keys()


def sweep_custody_keys() -> None:
    """9kg.34 (review of PR #102, F4): finish every journaled custody-key destruction before the web or worker
    process serves anything, so a restored or copied key file never revives an erased document. Refuses to start when
    the key store or the journal cannot be read (fail closed)."""
    from agreements import keystore

    try:
        keystore.sweep()
    except keystore.KeyStoreError as exc:
        raise ImproperlyConfigured(f"Catalyst refuses to start: the custody key sweep failed ({exc.code})") from None
