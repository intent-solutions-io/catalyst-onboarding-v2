"""The applicant's set-your-own-password page (023 sections 11.5 and 11.8; 5B.2).

GET shows the form and never consumes the token. POST commits. Every refusal is the same page (an unknown, used,
expired, cancelled or superseded link cannot be told apart). The password field is never re-rendered, nothing typed is
kept, and the POST parameters are marked sensitive so no error report can show them. Responses under the setup path
are private and no-referrer (`config.redaction`).
"""

from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from . import credentials


def _closed(request, status=404):
    return render(request, "provisioning/setup_closed.html", status=status)


@never_cache
@sensitive_variables("password", "confirm")
@sensitive_post_parameters("password", "confirm")
@require_http_methods(["GET", "POST"])
def setup(request, token):
    if request.method == "GET":
        found = credentials.live_setup(token)
        if found is None:
            return _closed(request)
        credentials.mark_presented(found)
        return render(request, "provisioning/setup.html", {"error": ""})
    password, confirm = request.POST.get("password", ""), request.POST.get("confirm", "")
    if password != confirm:
        return render(request, "provisioning/setup.html", {"error": "The two entries do not match."}, status=400)
    try:
        outcome = credentials.set_password(token, password)
    except credentials.SetupRefused:
        return _closed(request)
    finally:
        password = confirm = ""
    if outcome == "retry":
        return render(request, "provisioning/setup.html", {
            "error": "That password was not accepted. Choose another one (8 to 72 characters)."}, status=400)
    response = render(request, "provisioning/setup_done.html")
    return response if isinstance(response, HttpResponse) else HttpResponse(status=200)


@never_cache
@require_http_methods(["GET", "POST"])
def withdraw(request, token):
    """P5-D-8: GET shows what withdrawing means; POST commits. One uniform page for any link that cannot be used."""
    from . import closure

    if request.method == "GET":
        if closure.live_withdrawal(token) is None:
            return render(request, "provisioning/link_closed.html", status=404)
        return render(request, "provisioning/withdraw.html")
    if not closure.confirm_withdrawal(token):
        return render(request, "provisioning/link_closed.html", status=404)
    return render(request, "provisioning/withdrawn.html")

