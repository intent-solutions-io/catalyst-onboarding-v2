"""The live canary's first finding (9kg.87, 2026-10-29): with `Referrer-Policy: no-referrer`, a real browser sends
`Origin: null` on the page's own form post, and Django's CSRF check refuses it (403). The in-process browser check and
the test client never send that header, so nothing caught it before the deployed site did. Every page that posts a
form is now `same-origin`: the referrer, a one-time link's token included, goes back only to this site.
"""

import pytest
from django.conf import settings
from django.test import Client
from django.urls import reverse

FORM = reverse("applications:request_access")
pytestmark = pytest.mark.django_db


def test_9kg_87_no_page_that_posts_a_form_tells_the_browser_no_referrer():
    assert settings.SECURE_REFERRER_POLICY == "same-origin"
    assert Client().get(FORM)["Referrer-Policy"] == "same-origin"


def test_9kg_87_a_form_post_with_origin_null_is_what_the_csrf_check_refuses():
    """The failure itself, reproduced: the browser's `Origin: null` is refused, its real origin is not."""
    client = Client(enforce_csrf_checks=True)
    page = client.get(FORM)
    token = page.cookies[settings.CSRF_COOKIE_NAME].value
    base = {"name": "Origin Probe", "email": "origin.probe@example.test", "reason": "Synthetic reason for access.",
            "csrfmiddlewaretoken": token}
    refused = client.post(FORM, base, HTTP_ORIGIN="null", secure=True)
    assert refused.status_code == 403
    accepted = client.post(FORM, base, HTTP_ORIGIN="https://testserver", secure=True)
    assert accepted.status_code != 403
