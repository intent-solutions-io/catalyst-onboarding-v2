"""Public intake views (005 S1.2; J-01, J-02).

The applicant sees the same redirect and the same received page whether the address is new, known,
verified or not, so the form never reveals whether an email is on file. A database failure shows a
"please try again" page with status 503. The service runs in one transaction, so a failure before the
commit records nothing; a connection lost at the commit leaves the outcome unknown, and the applicant's
resubmission follows the duplicate rules (services module docstring).
Oversized bodies and too many fields are refused by Django with 400 before the form is read; CSRF is
enforced by CsrfViewMiddleware (403).
"""

import logging

from django.db import DatabaseError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_safe

from . import services
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
