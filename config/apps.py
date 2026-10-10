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

        from . import checks, guards, runtime  # noqa: F401  (importing checks registers catalyst.E001, E002)

        problems = guards.all_problems(settings, os.environ)
        if problems:
            raise ImproperlyConfigured("Catalyst refuses to start: " + "; ".join(problems))
        # No query here: the receiver checks each new connection, and only in web and worker processes.
        connection_created.connect(runtime.enforce_on_connect, dispatch_uid="catalyst.db_role_enforcement")
