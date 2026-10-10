"""Public intake views (005 S1.2; J-01, J-02).

The applicant sees the same redirect and the same received page whether the address is new, known,
verified or not, so the form never reveals whether an email is on file. A database failure shows a
"please try again" page with status 503 and commits nothing (the service runs in one transaction).
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
                logger.warning("intake submission not accepted: %s", type(exc).__name__)  # no applicant data
                return render(request, "applications/try_again.html", status=503)
            return redirect("applications:request_access_received")
    else:
        form = AccessRequestForm()
    return render(request, "applications/request_access.html", {"form": form})


@require_safe
def request_access_received(request):
    return render(request, "applications/request_access_received.html")
