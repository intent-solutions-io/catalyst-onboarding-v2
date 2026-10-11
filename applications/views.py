"""Public intake views (005 S1.2; J-01, J-02).

The applicant sees the same redirect and the same received page whether the address is new, known,
verified or not, so the form never reveals whether an email is on file. A database failure shows a
"please try again" page with status 503. The service runs in one transaction, so a failure before the
commit records nothing; a connection lost at the commit leaves the outcome unknown, and the applicant's
resubmission follows the duplicate rules (services module docstring).
Oversized bodies and too many fields are refused by Django with 400 before the form is read; CSRF is
enforced by CsrfViewMiddleware (403).

The confirmation view (005 S1.2 Confirm; J-03) carries the signed token in its path. Every response under
that path, including the ones Django builds outside the view, is sent with `Referrer-Policy: no-referrer`
and `Cache-Control: no-store` (config.redaction middleware), and refusals are logged as a reason code
only. Django's own request and CSRF loggers name the path of a 4xx response, so config.redaction
replaces the token in those records.
"""

import logging
import uuid

from django.db import DatabaseError, InterfaceError
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods, require_safe

from . import confirmation, services
from .forms import AccessRequestForm

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "HEAD", "POST"])
def request_access(request):
    if request.method == "POST":
        form = AccessRequestForm(request.POST)
        if form.is_valid():
            try:
                services.accept_submission(form.cleaned_data)
            except DatabaseError as exc:
                # Class name only: no applicant data and no database error text. "Did not complete" rather than
                # "not saved": if the commit acknowledgment was lost, the submission may have committed.
                logger.warning("intake submission did not complete: %s", type(exc).__name__)
                return render(request, "applications/try_again.html", status=503)
            return redirect("applications:request_access_received")
    else:
        form = AccessRequestForm()
    return render(request, "applications/request_access.html", {"form": form})


@require_safe
def request_access_received(request):
    return render(request, "applications/request_access_received.html")


REFUSAL_STATUS = {
    confirmation.Refused.INVALID: 404,
    confirmation.Refused.NO_LONGER_VALID: 410,
    confirmation.Refused.BAD_VERSION: 400,
}


@require_http_methods(["GET", "HEAD", "POST"])
@never_cache
@ensure_csrf_cookie
def confirm(request, token):
    try:
        challenge = confirmation.challenge_id(token)
        if request.method == "POST":
            try:
                version = uuid.UUID(request.POST.get("version", ""))
            except ValueError:
                raise confirmation.Refused(confirmation.Refused.BAD_VERSION, "version is not a reference") from None
            confirmation.confirm(challenge, version)
            response = render(request, "applications/confirmed.html", {"already": False})
        else:
            response = render(request, "applications/confirm.html", {"preview": confirmation.preview(challenge)})
    except confirmation.Refused as refusal:
        if refusal.kind == confirmation.Refused.ALREADY:
            logger.info("confirmation: %s; nothing changed", refusal.reason)
            response = render(request, "applications/confirmed.html", {"already": True})
        else:
            logger.info("confirmation refused: %s; nothing changed", refusal.reason)
            response = render(request, "applications/link_invalid.html", status=REFUSAL_STATUS[refusal.kind])
    except (DatabaseError, InterfaceError) as exc:
        logger.warning("confirmation did not complete: %s", type(exc).__name__)  # class name only
        response = render(request, "applications/confirm_try_again.html", status=503)
    return response
