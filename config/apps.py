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

        from . import checks, guards  # noqa: F401  (importing checks registers catalyst.E001)

        problems = guards.all_problems(settings, os.environ)
        if problems:
            raise ImproperlyConfigured("Catalyst refuses to start: " + "; ".join(problems))
