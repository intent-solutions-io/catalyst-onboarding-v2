"""System check wrapper around config.guards (catalyst.E001).

At start-up CatalystConfig.ready() refuses to run before any check could report, so this check is the
reporting path for settings that change after start-up (for example override_settings in tests) and
for `manage.py check` in any process where ready() already passed.
"""

import os

from django.conf import settings
from django.core import checks

from . import guards


@checks.register()  # no "database" tag: runs on every `manage.py check`
def guard_check(app_configs, **kwargs):
    return [checks.Error(p, id="catalyst.E001") for p in guards.all_problems(settings, os.environ)]
