"""Keeps confirmation tokens out of Django's own log records and caches (D-24; TEST-S1-16).

Django's request logger names the path of every 4xx and 5xx response, its CSRF logger names the path of a
refused POST, and the development server logs every request line. A confirmation link carries its signed
token in the path, so this filter rewrites any such record with the token replaced. It is attached to
those loggers themselves (CatalystConfig.ready), so it applies whatever handlers are configured. A
rewritten record also loses its `request` attribute, which a handler or error report could print with the
path (the default admin-mail handler builds one only when ADMINS is set; it is not set).
Stated limit: it covers this process's log records only, never a proxy's or server's access log.

`PrivateConfirmationResponses` is the outermost middleware: every response under the confirmation path,
including those Django builds outside the view (CSRF 403, 405, 404 from the resolver, the trailing-slash
redirect, a 500), is sent with `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
"""

import logging
import re

from django.utils.cache import patch_cache_control

from applications.links import CONFIRM_PATH

TOKEN_IN_PATH = re.compile(re.escape(CONFIRM_PATH) + r"[^/\s?#\"']+")
REDACTED = CONFIRM_PATH + "[redacted]"
LOGGERS = ("django.request", "django.security.csrf", "django.server")


class RedactConfirmationTokens(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        redacted = TOKEN_IN_PATH.sub(REDACTED, message)
        if redacted != message:
            record.msg, record.args = redacted, ()
            if hasattr(record, "request"):
                record.request = None
        return True


class PrivateConfirmationResponses:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith(CONFIRM_PATH):
            patch_cache_control(response, no_store=True, private=True)
            response["Referrer-Policy"] = "no-referrer"
        return response


def install():
    for name in LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactConfirmationTokens) for f in logger.filters):
            logger.addFilter(RedactConfirmationTokens())
