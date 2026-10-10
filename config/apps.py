import os

from django.apps import AppConfig
from django.core import checks
from django.core.exceptions import ImproperlyConfigured


class CatalystConfig(AppConfig):
    """Hosts the start-up guards; holds no models."""

    name = "config"
    label = "catalyst_config"
    verbose_name = "Catalyst configuration"

    def ready(self):
        from django.conf import settings

        from . import guards

        checks.register(guard_check)  # no "database" tag: runs on every `manage.py check`
        problems = guards.all_problems(settings, os.environ)
        if problems:
            raise ImproperlyConfigured("Catalyst refuses to start: " + "; ".join(problems))


def guard_check(app_configs, **kwargs):
    from django.conf import settings

    from . import guards

    return [checks.Error(p, id="catalyst.E001") for p in guards.all_problems(settings, os.environ)]
