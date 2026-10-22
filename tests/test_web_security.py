"""6B.2 (026 section 8): the web security settings as behaviour on real responses, not only as values.

Staging's settings are applied with override_settings to this test process, so each assertion reads a real
response from the middleware stack: redirects, the exempt health paths, HSTS, cookie attributes, the CSP and
the framing headers, an anonymous page that creates no session, and an idle session that is refused.
"""

from datetime import timedelta

import pytest
from django.contrib.sessions.models import Session
from django.test import Client
from django.utils import timezone

from config.security_headers import POLICY
from tests.test_outbound import p2  # noqa: F401  (fixture)

HOST = "catalyst.example.test"
STAGING = dict(
    SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True, SESSION_COOKIE_NAME="__Host-catalyst-session",
    CSRF_COOKIE_NAME="__Host-catalyst-csrf", SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SECURE_SSL_REDIRECT=True, SECURE_REDIRECT_EXEMPT=[r"^healthz$", r"^readyz$"], SECURE_HSTS_SECONDS=300,
    SECURE_HSTS_INCLUDE_SUBDOMAINS=False, SECURE_HSTS_PRELOAD=False, ALLOWED_HOSTS=[HOST, "testserver", "localhost"],
)
HTTPS = {"HTTP_X_FORWARDED_PROTO": "https", "HTTP_HOST": HOST}


@pytest.fixture
def staging_web(settings):
    for name, value in STAGING.items():
        setattr(settings, name, value)
    return Client()


def test_6b2_plain_http_is_redirected_to_https_except_the_health_paths(staging_web, db):
    response = staging_web.get("/request-access/", HTTP_HOST=HOST)
    assert response.status_code == 301 and response["Location"] == f"https://{HOST}/request-access/"
    for path in ("/healthz", "/readyz"):  # exempt, on the proxy's local socket host (6B.3)
        assert staging_web.get(path, HTTP_HOST="localhost").status_code != 301
        assert staging_web.get(path, HTTP_HOST=HOST).status_code == 404  # never on the public host (6B.3)
    assert staging_web.get("/healthz/", HTTP_HOST="localhost").status_code == 301  # the exemption is exact


def test_6b2_hsts_is_sent_only_over_https_and_covers_no_subdomains(staging_web, db):
    secure = staging_web.get("/request-access/", **HTTPS)
    assert secure.status_code == 200 and secure["Strict-Transport-Security"] == "max-age=300"
    assert "Strict-Transport-Security" not in staging_web.get("/healthz", HTTP_HOST="localhost")


def test_6b2_the_csrf_cookie_is_host_only_secure_and_hidden_from_scripts(staging_web, db):
    response = staging_web.get("/request-access/", **HTTPS)
    cookie = response.cookies["__Host-catalyst-csrf"]
    assert cookie["secure"] and cookie["httponly"] and cookie["path"] == "/" and not cookie["domain"]
    assert cookie["samesite"] == "Lax"


def test_6b2_every_page_carries_the_csp_and_framing_headers(staging_web, db):
    response = staging_web.get("/request-access/", **HTTPS)
    assert response["Content-Security-Policy"] == POLICY and "frame-ancestors 'none'" in POLICY
    assert response["X-Frame-Options"] == "DENY" and response["X-Content-Type-Options"] == "nosniff"
    assert response["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "script-src 'self'" in POLICY and "unsafe-inline" not in POLICY.split("script-src")[1].split(";")[0]


def test_6b2_an_anonymous_page_creates_no_session(staging_web, db):
    before = Session.objects.count()
    staging_web.get("/request-access/", **HTTPS)
    assert Session.objects.count() == before


def test_6b2_an_idle_staff_session_is_refused_after_30_minutes(p2):
    from tests.test_outbound import staff

    user = staff(p2, "idle-staff")
    client = Client()
    client.force_login(user)
    key = client.session.session_key
    session = Session.objects.get(session_key=key)
    assert timedelta(minutes=29) < session.expire_date - timezone.now() <= timedelta(minutes=30)  # 30 minutes idle
    Session.objects.filter(session_key=key).update(expire_date=timezone.now() - timedelta(seconds=1))
    response = client.get("/staff/")
    assert response.status_code == 302 and "login" in response["Location"]  # idle: back to the login page
