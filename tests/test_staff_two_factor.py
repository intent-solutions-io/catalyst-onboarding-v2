"""6B.9 (026 section 8, P6-D-3; TEST-P6-14 to 16): staff two-factor, login throttling, the absolute session
lifetime and the scheduled session clean-up."""

import hashlib
import re
import time
import uuid
from datetime import timedelta

import psycopg
import pytest
from django.contrib.auth import authenticate
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.test import Client
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import staff_access
from config import system_health
from tests.support import manage_as_owner
from tests.test_outbound import p2, staff  # noqa: F401  (fixture chain and helpers)
from workflow import ledger
from workflow.models import PendingAction

PASSWORD = "synthetic-password-only"  # gitleaks:allow
# The admin and one focused screen of each staff app: the gate covers everything under /staff/.
STAFF_PAGES = ("/staff/", "/staff/p2/", "/staff/p3/sources/",
               f"/staff/p4/applications/{uuid.uuid4()}/agreements/",
               f"/staff/p5/applications/{uuid.uuid4()}/provisioning/")


@pytest.fixture
def required(p2, settings):
    settings.CATALYST_STAFF_TWO_FACTOR = True
    return p2


def enrol(username):
    out = manage_as_owner("enroll_staff_two_factor", username).stdout
    secret = re.search(r"secret=([A-Z2-7]+)", out).group(1)
    codes = re.findall(r"^  (\S+)$", out, flags=re.M)
    return secret, codes


def current_token(username) -> str:
    device = TOTPDevice.objects.get(user__username=username)
    return f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):0{device.digits}d}"


def sign_in(client, username, device_model, token, password=PASSWORD):
    device = device_model.objects.get(user__username=username)
    return client.post("/staff/login/?next=/staff/", {"username": username, "password": password,
                                                       "otp_device": device.persistent_id, "otp_token": token})


def test_6b9_an_unverified_staff_session_reaches_no_staff_page(required):
    staff(required, "no-second-factor")
    for page in STAFF_PAGES:
        client = Client()
        assert client.login(username="no-second-factor", password=PASSWORD)  # password alone, as a test may
        response = client.get(page)
        assert response.status_code == 302 and response["Location"].startswith("/staff/login/"), page
        assert "_auth_user_id" not in client.session  # signed out, not merely redirected


def test_6b9_an_anonymous_request_reaches_only_the_login_page(p2):
    for page in (*STAFF_PAGES, "/staff/some-view-added-later/"):
        response = Client().get(page)
        assert response.status_code == 302 and response["Location"].startswith("/staff/login/?next="), page
    assert Client().get("/staff/login/").status_code == 200


def test_6b9_a_session_without_a_recorded_login_time_is_ended(p2):
    staff(p2, "no-login-time", superuser=True)
    client = Client()
    assert client.login(username="no-login-time", password=PASSWORD)
    session = client.session
    del session[staff_access.LOGIN_AT]
    session.save()
    assert client.get("/staff/").status_code == 302 and "_auth_user_id" not in client.session


def test_6b9_the_login_needs_the_token_and_a_verified_session_reaches_every_staff_page(required):
    staff(required, "two-factor-staff")
    enrol("two-factor-staff")
    client = Client()
    refused = client.post("/staff/login/?next=/staff/", {"username": "two-factor-staff", "password": PASSWORD})
    assert refused.status_code == 200 and "_auth_user_id" not in client.session  # the password alone is not enough
    wrong = sign_in(client, "two-factor-staff", TOTPDevice, "000000")
    assert wrong.status_code == 200 and "_auth_user_id" not in client.session
    TOTPDevice.objects.filter(user__username="two-factor-staff").update(throttling_failure_timestamp=None,
                                                                         throttling_failure_count=0)
    token = current_token("two-factor-staff")
    assert sign_in(Client(), "two-factor-staff", TOTPDevice, token).status_code == 302
    # The same code again: refused by django-otp's last_t. Replaying the code itself, not a fresh current_token(),
    # keeps this true when the 30-second step rolls over between the two sign-ins.
    replay = Client()
    assert sign_in(replay, "two-factor-staff", TOTPDevice, token).status_code == 200
    assert "_auth_user_id" not in replay.session
    TOTPDevice.objects.filter(user__username="two-factor-staff").update(last_t=-1, throttling_failure_timestamp=None,
                                                                         throttling_failure_count=0)
    client = Client()
    assert sign_in(client, "two-factor-staff", TOTPDevice, current_token("two-factor-staff")).status_code == 302
    for page in STAFF_PAGES:
        response = client.get(page)
        assert not (response.status_code == 302 and response["Location"].startswith("/staff/login/")), page


def test_6b9_a_recovery_code_signs_in_once(required):
    staff(required, "recovery-staff")
    _, codes = enrol("recovery-staff")
    assert len(codes) == 10
    assert sign_in(Client(), "recovery-staff", StaticDevice, codes[0]).status_code == 302
    assert not StaticToken.objects.filter(token=codes[0]).exists()  # spent by the application role's DELETE
    StaticDevice.objects.filter(user__username="recovery-staff").update(throttling_failure_timestamp=None,
                                                                        throttling_failure_count=0)
    client = Client()
    assert sign_in(client, "recovery-staff", StaticDevice, codes[0]).status_code == 200
    assert "_auth_user_id" not in client.session


def test_6b9_the_application_role_may_count_failures_but_never_change_or_add_a_device(required):
    from django.db import connection

    staff(required, "device-guard")
    enrol("device-guard")
    device = TOTPDevice.objects.get(user__username="device-guard")
    TOTPDevice.objects.filter(pk=device.pk).update(throttling_failure_count=3)  # counters: allowed
    for statement in ("UPDATE otp_totp_totpdevice SET key = repeat('0', 40) WHERE id = %s",
                      "UPDATE otp_totp_totpdevice SET confirmed = false WHERE id = %s",
                      "UPDATE otp_static_staticdevice SET user_id = user_id + 1 WHERE user_id = (SELECT user_id FROM"
                      " otp_totp_totpdevice WHERE id = %s)",
                      "DELETE FROM otp_totp_totpdevice WHERE id = %s",
                      "INSERT INTO otp_static_statictoken (device_id, token) SELECT id, 'forged01' FROM"
                      " otp_static_staticdevice WHERE id <> %s LIMIT 1"):
        with pytest.raises(Exception) as caught, connection.cursor() as cursor:
            from django.db import transaction

            with transaction.atomic():
                cursor.execute(statement, [device.pk])
        assert isinstance(caught.value.__cause__, psycopg.errors.InsufficientPrivilege), statement


def test_6b9_repeated_password_failures_lock_the_username_even_for_the_right_password(p2, settings):
    staff(p2, "throttled-staff")
    for _ in range(settings.CATALYST_STAFF_LOGIN_FAILURE_LIMIT):
        assert authenticate(username="throttled-staff", password="not-the-password") is None
    assert authenticate(username="throttled-staff", password=PASSWORD) is None  # locked
    from accounts.models import LoginThrottle

    row = LoginThrottle.objects.get(key=staff_access.throttle_key("throttled-staff"))
    assert row.locked_until > timezone.now() and row.key == hashlib.sha256(b"throttled-staff").hexdigest()
    LoginThrottle.objects.filter(pk=row.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
    assert authenticate(username="throttled-staff", password=PASSWORD) is not None  # the lock ran out
    assert LoginThrottle.objects.get(pk=row.pk).failures == 0


def test_6b9_the_login_page_locks_a_username_that_does_not_exist_like_one_that_does(p2, settings):
    from accounts.models import LoginThrottle

    for _ in range(settings.CATALYST_STAFF_LOGIN_FAILURE_LIMIT):
        response = Client().post("/staff/login/", {"username": "nobody-here", "password": "guess"})
        assert response.status_code == 200
    assert LoginThrottle.objects.get(key=staff_access.throttle_key("nobody-here")).locked_until > timezone.now()


def test_6b9_a_session_older_than_its_absolute_lifetime_is_ended(p2, settings):
    staff(p2, "long-session", superuser=True)
    client = Client()
    assert client.login(username="long-session", password=PASSWORD)
    assert client.get("/staff/").status_code == 200  # before
    session = client.session
    session[staff_access.LOGIN_AT] = int(time.time()) - settings.CATALYST_STAFF_SESSION_MAX_SECONDS - 1
    session.save()
    response = client.get("/staff/")
    assert response.status_code == 302 and response["Location"].startswith("/staff/login/")
    assert "_auth_user_id" not in client.session


def test_6b9_expired_sessions_are_removed_by_a_self_renewing_action(p2, settings):
    expired = SessionStore()
    expired["probe"] = 1
    expired.create()
    Session.objects.filter(session_key=expired.session_key).update(expire_date=timezone.now() - timedelta(minutes=1))
    live = SessionStore()
    live.create()
    assert staff_access.schedule_session_cleanup() and not staff_access.schedule_session_cleanup()  # idempotent
    assert ledger.run_one({staff_access.CLEAR_SESSIONS: staff_access.ClearSessions()})
    assert not Session.objects.filter(session_key=expired.session_key).exists()
    assert Session.objects.filter(session_key=live.session_key).exists()
    successor = PendingAction.objects.get(kind=staff_access.CLEAR_SESSIONS, status="queued")
    assert successor.idempotency_key == "clear_sessions:2"
    assert successor.due_at > timezone.now() + timedelta(seconds=settings.CATALYST_SESSION_CLEANUP_SECONDS - 60)


def test_6b9_health_reports_an_unscheduled_clean_up_where_two_factor_is_required(p2, settings):
    assert system_health.session_health()["anomalies"] == []  # local: not required
    settings.CATALYST_STAFF_TWO_FACTOR = True
    assert system_health.session_health()["anomalies"] == ["session_cleanup_unscheduled"]
    manage_as_owner("schedule_session_cleanup")
    assert system_health.session_health() == {"cleanup_scheduled": True, "anomalies": []}


def test_6b9_the_break_glass_reset_leaves_nothing_from_before_it_working(required):
    from accounts.models import User

    staff(required, "lost-device")
    _, codes = enrol("lost-device")
    client = Client()
    assert sign_in(client, "lost-device", StaticDevice, codes[0]).status_code == 302
    assert client.get("/staff/").status_code == 200  # before: signed in and verified
    from accounts.models import LoginThrottle

    LoginThrottle.objects.create(key=staff_access.throttle_key("lost-device"),
                                 locked_until=timezone.now() + timedelta(minutes=10))
    result = manage_as_owner("reset_staff_two_factor", "lost-device")
    assert "ended 1 sessions" in result.stdout
    user_pk = User.objects.get(username="lost-device").pk
    assert f"break-glass reset for staff account {user_pk}" in result.stderr and "lost-device" not in result.stderr
    assert not LoginThrottle.objects.filter(key=staff_access.throttle_key("lost-device")).exists()
    assert not StaticDevice.objects.filter(user__username="lost-device").exists()
    assert not TOTPDevice.objects.filter(user__username="lost-device").exists()
    assert not StaticToken.objects.filter(token=codes[1]).exists()
    assert not User.objects.get(username="lost-device").has_usable_password()
    assert client.get("/staff/").status_code == 302


def test_6b9_two_factor_is_required_outside_the_local_environments():
    from tests.support import run
    import sys

    result = run([sys.executable, "-c", "import django; django.setup(); from django.conf import settings;"
                  " print(settings.CATALYST_STAFF_TWO_FACTOR)"], DJANGO_SETTINGS_MODULE="config.settings")
    assert result.stdout.strip() == "False"  # the test environment
    from tests.test_startup import STAGING

    staged = run([sys.executable, "-c", "import django; django.setup(); from django.conf import settings;"
                  " print(settings.CATALYST_STAFF_TWO_FACTOR)"], **{**STAGING, "DJANGO_SETTINGS_MODULE": "config.settings"})
    assert staged.stdout.strip().splitlines()[-1] == "True", staged.stderr  # staging, and anything not local
    from django.conf import settings

    assert "accounts.staff_access.StaffAccess" in settings.MIDDLEWARE
    assert settings.MIDDLEWARE.index("django_otp.middleware.OTPMiddleware") < settings.MIDDLEWARE.index(
        "accounts.staff_access.StaffAccess")
    from tests.support import ROOT

    source = (ROOT / "config" / "settings.py").read_text()
    assert 'CATALYST_STAFF_TWO_FACTOR = CATALYST_ENV not in ("test", "development")' in source  # fixed in code


def test_6b9_a_superuser_account_gets_no_staff_session_where_two_factor_is_required(required):
    staff(required, "super-staff", superuser=True)
    enrol("super-staff")
    client = Client()
    response = client.post("/staff/login/?next=/staff/", {"username": "super-staff", "password": PASSWORD})
    assert response.status_code == 200 and b"cannot sign in to the staff site" in response.content  # refused at the form
    assert "_auth_user_id" not in client.session
    # The backstop: a superuser session that is somehow verified is still ended on its next staff request.
    from accounts.models import User

    client.force_login(User.objects.get(username="super-staff"))
    session = client.session
    session["otp_device_id"] = TOTPDevice.objects.get(user__username="super-staff").persistent_id
    session.save()
    response = client.get("/staff/")
    assert response.status_code == 302 and response["Location"].startswith("/staff/login/")
    assert "_auth_user_id" not in client.session


def test_6b9_superusers_keep_their_local_sessions_in_test_and_development(p2):
    staff(p2, "local-super", superuser=True)
    client = Client()
    assert client.login(username="local-super", password=PASSWORD)
    assert client.get("/staff/").status_code == 200

