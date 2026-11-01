"""bgl.2 (034 rows 1, 2, 4 and 5): the public entry on the first generation's URLs.

The intake mode from the environment (open: anyone may apply; invitation: unchanged and silent), the exact paths
without a trailing slash beside the slash forms, the form's bot checks (a honeypot and a signed render time) and the
global hourly and daily caps that defer the verification mail instead of refusing. The suite turns the bot checks off
and lifts the caps per test (tests/conftest.py SUITE_PUBLIC_ENTRY); each test here sets the values it proves.
"""

import logging
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from django.test import Client
from django.utils import timezone

from applications import abuse, services
from applications.models import Application, ApplicationEvent, ContactChallenge
from config import guards
from tests.support import run
from tests.test_intake import EMPTY, FORM, RECEIVED, VALID, counts, post
from tests.test_guards import production
from tests.test_invitation import CHECK, PROBE, closed
from tests.test_startup import STAGING as STAGING_ENV
from tests.test_web_security import STAGING as STAGING_WEB
from workflow.models import PendingAction

EXACT, EXACT_RECEIVED = "/request-access", "/request-access/received"


def checked(settings):
    settings.CATALYST_INTAKE_FORM_CHECKS = True


def _hour(when):
    return when.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def aged(seconds=10):
    """A render time `seconds` ago: what a person's browser sends back."""
    return abuse.issue_token(now=time.time() - seconds)


# --- the mode: from the environment, invitation-only unless it says open -------------------------------------------

def test_bgl_2_the_mode_is_read_from_the_environment_and_a_bad_value_refuses_start_up():
    assert run(PROBE).stdout.split()[0] == "invitation"  # unset: invitation-only
    opened = run(PROBE, CATALYST_INTAKE_MODE="open")
    assert opened.returncode == 0 and opened.stdout.split()[0] == "open", opened.stderr
    for bad in ("", "closed", "Open", "invite"):
        refused = run(CHECK, CATALYST_INTAKE_MODE=bad)
        assert refused.returncode != 0, bad
        assert "CATALYST_INTAKE_MODE must be 'invitation' (the default) or 'open'" in refused.stderr, bad
    # Production takes either mode; the bot checks may be off only in the test suite.
    live = SimpleNamespace(CATALYST_ENV="production", CATALYST_CLIENT_IDENTITY="proxy", CATALYST_INTAKE_FORM_CHECKS=True,
                           CATALYST_INTAKE_FORM_MIN_AGE_SECONDS=3, CATALYST_INTAKE_FORM_MAX_AGE_SECONDS=7200)
    for mode in ("invitation", "open"):
        assert guards.intake_problems(SimpleNamespace(**{**vars(live), "CATALYST_INTAKE_MODE": mode}), {}) == []
    off = SimpleNamespace(**{**vars(live), "CATALYST_INTAKE_MODE": "open", "CATALYST_INTAKE_FORM_CHECKS": False})
    assert guards.intake_problems(off, {}) == ["CATALYST_INTAKE_FORM_CHECKS must be on outside the test suite"]
    inverted = SimpleNamespace(**{**vars(live), "CATALYST_INTAKE_MODE": "open", "CATALYST_INTAKE_FORM_MIN_AGE_SECONDS": 7200})
    assert guards.intake_problems(inverted, {}) == [
        "CATALYST_INTAKE_FORM_MIN_AGE_SECONDS must be below CATALYST_INTAKE_FORM_MAX_AGE_SECONDS"]


@pytest.mark.django_db
def test_bgl_2_open_mode_accepts_an_uninvited_submission(settings):
    settings.CATALYST_INTAKE_MODE = "open"
    response = post(Client(), email="stranger@example.test")
    assert (response.status_code, response["Location"]) == (302, RECEIVED)
    assert Application.objects.get().email == "stranger@example.test"
    assert counts() == {"applications": 1, "versions": 1, "events": 1, "challenges": 1, "actions": 1}


def test_bgl_2_invitation_mode_still_refuses_an_uninvited_address_silently(privileged_reset, settings, caplog):
    caplog.set_level(logging.INFO, logger="applications.views")
    closed(settings)
    checked(settings)
    response = post(Client(), {**VALID, "email": "stranger@example.test", "form_token": aged()})
    assert (response.status_code, response["Location"], response.content) == (302, RECEIVED, b"")
    assert counts() == EMPTY
    assert "intake refused: not_invited; nothing recorded" in caplog.text


# --- the first generation's exact paths --------------------------------------------------------------------------

@pytest.mark.django_db
def test_bgl_2_the_exact_paths_without_a_slash_answer_and_the_slash_forms_still_do(settings):
    settings.CATALYST_INTAKE_MODE = "open"
    client = Client()
    for path in (EXACT, FORM):
        page = client.get(path, follow=True)
        assert page.status_code == 200 and page.redirect_chain == [], path  # no redirect, so no loop
        assert b"Request access" in page.content and b'name="form_token"' in page.content
    for path in (EXACT_RECEIVED, RECEIVED):
        page = client.get(path, follow=True)
        assert page.status_code == 200 and page.redirect_chain == [] and b"Request received" in page.content, path
    exact = client.post(EXACT, {**VALID, "email": "exact@example.test"})
    assert (exact.status_code, exact["Location"]) == (302, EXACT_RECEIVED)  # the first generation's received path
    slash = client.post(FORM, {**VALID, "email": "slash@example.test"})
    assert (slash.status_code, slash["Location"]) == (302, RECEIVED)
    assert sorted(Application.objects.values_list("email", flat=True)) == ["exact@example.test", "slash@example.test"]


# --- the bot checks: honeypot and signed render time ----------------------------------------------------------------

@pytest.mark.django_db
def test_bgl_2_the_page_carries_a_fresh_render_time_and_the_hidden_honeypot(settings):
    checked(settings)
    page = Client().get(FORM).content.decode()
    assert 'name="form_token"' in page and 'name="website"' in page
    assert 'aria-hidden="true"' in page and 'tabindex="-1"' in page and 'autocomplete="off"' in page
    token = page.split('name="form_token" value="', 1)[1].split('"', 1)[0]
    assert abuse.check_token(token) == abuse.TOO_FAST  # rendered just now
    assert abuse.check_token(token, now=time.time() + 10) == abuse.OK


@pytest.mark.django_db
def test_bgl_2_a_filled_honeypot_looks_exactly_like_success_and_records_nothing(settings, caplog):
    caplog.set_level(logging.INFO, logger="applications.views")
    settings.CATALYST_INTAKE_MODE = "open"
    checked(settings)
    client = Client()
    for path, received in ((FORM, RECEIVED), (EXACT, EXACT_RECEIVED)):
        bot = client.post(path, {**VALID, "email": "bot@example.test", "form_token": aged(), "website": "https://spam.example"})
        assert (bot.status_code, bot["Location"], bot.content) == (302, received, b""), path
    assert counts() == EMPTY
    assert caplog.text.count("intake refused: honeypot; nothing recorded") == 2
    person = client.post(FORM, {**VALID, "email": "person@example.test", "form_token": aged(), "website": ""})
    assert (person.status_code, person["Location"], person.content) == (302, RECEIVED, b"")
    assert Application.objects.get().email == "person@example.test"


@pytest.mark.parametrize(("token", "reason"), [
    (None, "missing"),
    ("", "missing"),
    ("not-a-signed-value", "invalid"),
    ("forged", "invalid"),
    ("expired", "expired"),
    ("too_fast", "too_fast"),
])
@pytest.mark.django_db
def test_bgl_2_a_bad_render_time_gets_the_form_back_with_its_values_and_records_nothing(settings, caplog, token, reason):
    caplog.set_level(logging.INFO, logger="applications.views")
    settings.CATALYST_INTAKE_MODE = "open"
    checked(settings)
    value = {"forged": aged()[:-2] + "xx", "expired": aged(settings.CATALYST_INTAKE_FORM_MAX_AGE_SECONDS + 5),
             "too_fast": aged(0)}.get(token, token)
    data = {**VALID, "email": "hurried@example.test", **({"form_token": value} if value is not None else {})}
    response = Client().post(FORM, data)
    assert response.status_code == 400
    body = response.content.decode()
    assert "Please check your details and send the form again." in body
    assert 'value="hurried@example.test"' in body and 'value="Ada Example"' in body  # what was typed is kept
    assert abuse.check_token(body.split('name="form_token" value="', 1)[1].split('"', 1)[0], now=time.time() + 10) == abuse.OK
    assert counts() == EMPTY
    assert f"intake refused: form_{reason}; nothing recorded" in caplog.text
    assert "hurried@example.test" not in caplog.text  # a reason code only


def test_bgl_2_the_render_time_bounds_are_the_first_generations(settings):
    assert (settings.CATALYST_INTAKE_FORM_MIN_AGE_SECONDS, settings.CATALYST_INTAKE_FORM_MAX_AGE_SECONDS) == (3, 7200)
    assert (settings.CATALYST_INTAKE_GLOBAL_PER_HOUR, settings.CATALYST_INTAKE_GLOBAL_PER_DAY) == (100_000, 100_000)  # suite
    shipped = run([*PROBE[:2], "import django; django.setup(); from django.conf import settings as s; print("
                   "s.CATALYST_INTAKE_FORM_CHECKS, s.CATALYST_INTAKE_GLOBAL_PER_HOUR, s.CATALYST_INTAKE_GLOBAL_PER_DAY)"])
    assert shipped.returncode == 0 and shipped.stdout.split() == ["True", "30", "100"], shipped.stderr
    now = int(time.time())  # the token carries whole seconds
    assert abuse.check_token(abuse.issue_token(now - 3), now) == abuse.OK
    assert abuse.check_token(abuse.issue_token(now - 2), now) == abuse.TOO_FAST
    assert abuse.check_token(abuse.issue_token(now - 7200), now) == abuse.OK
    assert abuse.check_token(abuse.issue_token(now - 7201), now) == abuse.EXPIRED


# --- the global caps: deferred, never refused ------------------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize("receipt_enabled", [False, True])
def test_bgl_2_over_the_hourly_cap_the_applicant_is_accepted_and_the_verification_waits(settings, receipt_enabled):
    settings.CATALYST_INTAKE_RECEIPT = receipt_enabled
    settings.CATALYST_RECEIPT_IS_VERIFICATION = False
    settings.CATALYST_INTAKE_MODE = "open"
    settings.CATALYST_INTAKE_GLOBAL_PER_HOUR = 2
    client = Client()
    for n in range(3):
        response = post(client, email=f"applicant{n}@example.test")
        assert (response.status_code, response["Location"], response.content) == (302, RECEIVED, b"")  # the same page
    assert Application.objects.count() == 3  # stored, not refused
    third = Application.objects.get(email="applicant2@example.test")
    received = ApplicationEvent.objects.get(application=third, kind="submission_received")
    send = PendingAction.objects.get(subject_id=third.public_ref, kind="send_verification")
    challenge = ContactChallenge.objects.get(application=third)
    first = ApplicationEvent.objects.get(application__email="applicant0@example.test", kind="submission_received")
    if _hour(first.occurred_at) != _hour(received.occurred_at):  # the clock hour turned mid-test: the third had room
        assert send.due_at == send.created_at and received.data == {"version_number": 1}
        return
    next_hour = received.occurred_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    assert send.status == "queued" and send.due_at == next_hour
    if receipt_enabled:
        receipt = PendingAction.objects.get(subject_id=third.public_ref, kind="send_receipt")
        assert receipt.due_at == send.due_at
    assert received.data == {"version_number": 1, "deferred_until": next_hour.isoformat()}
    assert challenge.expires_at == next_hour + timedelta(seconds=settings.CATALYST_CHALLENGE_LIFETIME_SECONDS)
    assert not PendingAction.objects.filter(pk=send.pk, due_at__lte=timezone.now()).exists()  # not claimable yet
    for first in ("applicant0@example.test", "applicant1@example.test"):
        app = Application.objects.get(email=first)
        assert ApplicationEvent.objects.get(application=app, kind="submission_received").data == {"version_number": 1}
    # A repeat from the deferred applicant reuses the queued challenge: no new send, nothing more deferred.
    post(client, email="applicant2@example.test")
    assert PendingAction.objects.filter(subject_id=third.public_ref, kind="send_verification").count() == 1


@pytest.mark.django_db
def test_bgl_2_the_deferral_counts_releases_per_hour_and_per_day(settings):
    settings.CATALYST_INTAKE_MODE = "open"
    post(Client(), email="anchor@example.test")
    app = Application.objects.get()
    now = datetime(2030, 1, 1, 10, 30, tzinfo=UTC)

    def released(at, deferred_until=None):
        data = {"version_number": 1, **({"deferred_until": deferred_until.isoformat()} if deferred_until else {})}
        ApplicationEvent.objects.create(application=app, kind="submission_received", actor_type="applicant",
                                        occurred_at=at, data=data)

    settings.CATALYST_INTAKE_GLOBAL_PER_HOUR, settings.CATALYST_INTAKE_GLOBAL_PER_DAY = 2, 5
    assert services.cap_deferral(now) is None
    released(datetime(2030, 1, 1, 10, 5, tzinfo=UTC))
    assert services.cap_deferral(now) is None
    released(datetime(2030, 1, 1, 10, 6, tzinfo=UTC))
    assert services.cap_deferral(now) == datetime(2030, 1, 1, 11, tzinfo=UTC)  # this hour is full
    released(datetime(2030, 1, 1, 10, 7, tzinfo=UTC), deferred_until=datetime(2030, 1, 1, 11, tzinfo=UTC))
    released(datetime(2030, 1, 1, 10, 8, tzinfo=UTC), deferred_until=datetime(2030, 1, 1, 11, tzinfo=UTC))
    assert services.cap_deferral(now) == datetime(2030, 1, 1, 12, tzinfo=UTC)  # the backlog fills the next hour too
    released(datetime(2030, 1, 1, 10, 9, tzinfo=UTC), deferred_until=datetime(2030, 1, 1, 12, tzinfo=UTC))
    assert services.cap_deferral(now) == datetime(2030, 1, 2, tzinfo=UTC)  # five released today: the day is full
    released(datetime(2029, 12, 31, 23, 59, tzinfo=UTC))  # yesterday's arrivals count for yesterday only
    assert services.cap_deferral(now) == datetime(2030, 1, 2, tzinfo=UTC)
    settings.CATALYST_INTAKE_GLOBAL_PER_DAY = 100
    assert services.cap_deferral(now) == datetime(2030, 1, 1, 12, tzinfo=UTC)  # 12:00 holds one of two: room
    released(datetime(2030, 1, 1, 10, 10, tzinfo=UTC), deferred_until=datetime(2030, 1, 1, 12, tzinfo=UTC))
    assert services.cap_deferral(now) == datetime(2030, 1, 1, 13, tzinfo=UTC)


# --- public host aliases: the learning host's names for the public request pages -------------------------------------

ALIAS = "learn.example.test"


def aliased(settings):
    for name, value in STAGING_WEB.items():
        setattr(settings, name, value)
    settings.CATALYST_PUBLIC_HOST_ALIASES = [ALIAS]
    settings.ALLOWED_HOSTS = [*STAGING_WEB["ALLOWED_HOSTS"], ALIAS]
    settings.CSRF_TRUSTED_ORIGINS = [settings.CATALYST_PUBLIC_BASE_URL, f"https://{ALIAS}"]
    settings.CATALYST_INTAKE_MODE = "open"


def test_bgl_2_aliases_come_from_the_environment_into_the_allowed_hosts_and_trusted_origins():
    probe = [*PROBE[:2], "import django; django.setup(); from django.conf import settings as s; "
                         "print(s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS, s.CATALYST_PUBLIC_HOST_ALIASES)"]
    shown = run(probe, **STAGING_ENV, CATALYST_PUBLIC_HOST_ALIASES="learn.example.test, other.example.test")
    assert shown.returncode == 0, shown.stderr
    assert shown.stdout.strip() == ("['catalyst.staging.test', 'learn.example.test', 'other.example.test'] "
                                    "['https://catalyst.staging.test', 'https://learn.example.test', "
                                    "'https://other.example.test'] ['learn.example.test', 'other.example.test']")
    assert run(probe, **STAGING_ENV).stdout.strip().endswith("['https://catalyst.staging.test'] []")  # none by default
    assert run(CHECK, **STAGING_ENV, CATALYST_PUBLIC_HOST_ALIASES=ALIAS).returncode == 0
    for bad in ("*.example.test", "Learn.example.test", "learn.example.test:443", "127.0.0.1", "learn", "staff.staging.test",
                "https://learn.example.test"):
        refused = run(CHECK, **STAGING_ENV, CATALYST_PUBLIC_HOST_ALIASES=bad)
        assert refused.returncode != 0 and "CATALYST_PUBLIC_HOST_ALIASES" in refused.stderr, bad
    # Production answers for its aliases and nothing else.
    hosts = ["catalyst-v2.example.test", "staff-v2.example.test", "localhost"]
    assert guards.live_problems(production(CATALYST_PUBLIC_HOST_ALIASES=["learn.intentsolutions.io"],
                                           ALLOWED_HOSTS=[*hosts, "learn.intentsolutions.io"])) == []
    assert any("ALLOWED_HOSTS may hold only" in p for p in guards.live_problems(
        production(ALLOWED_HOSTS=[*hosts, "learn.intentsolutions.io"])))
    assert guards.alias_problems(production(CATALYST_PUBLIC_HOST_ALIASES=["staff-v2.example.test"])) == [
        "CATALYST_PUBLIC_HOST_ALIASES may not include the staff host"]


@pytest.mark.django_db
def test_bgl_2_an_alias_host_gets_the_form_and_submits_with_csrf_on_its_own_origin(settings):
    aliased(settings)
    checked(settings)
    browser = Client(enforce_csrf_checks=True)
    https = {"HTTP_HOST": ALIAS, "HTTP_X_FORWARDED_PROTO": "https"}
    page = browser.get(EXACT, **https)
    assert page.status_code == 200 and b"Request access" in page.content
    body = page.content.decode()
    csrf = body.split('name="csrfmiddlewaretoken" value="', 1)[1].split('"', 1)[0]
    data = {**VALID, "email": "alias@example.test", "csrfmiddlewaretoken": csrf, "form_token": aged()}
    sent = browser.post(EXACT, data, HTTP_ORIGIN=f"https://{ALIAS}", HTTP_REFERER=f"https://{ALIAS}{EXACT}", **https)
    assert (sent.status_code, sent["Location"]) == (302, EXACT_RECEIVED)
    assert Application.objects.get().email == "alias@example.test"
    assert browser.get(EXACT_RECEIVED, **https).status_code == 200
    # Another site's origin is refused by CSRF: the alias is trusted, not every origin.
    forged = browser.post(EXACT, {**data, "email": "forged@example.test"}, HTTP_ORIGIN="https://evil.example.test", **https)
    assert forged.status_code == 403 and Application.objects.count() == 1


@pytest.mark.django_db
def test_bgl_2_a_host_that_is_not_listed_gets_400_and_an_alias_never_serves_the_staff_or_health_paths(settings):
    aliased(settings)
    client = Client()
    assert client.get(EXACT, HTTP_HOST="unlisted.example.test", HTTP_X_FORWARDED_PROTO="https").status_code == 400
    https = {"HTTP_HOST": ALIAS, "HTTP_X_FORWARDED_PROTO": "https"}
    for path in ("/staff/", "/staff/login/", "/staff/p2/", "/healthz", "/readyz"):
        assert client.get(path, **https).status_code == 404, path
    settings.CATALYST_STAFF_HOST = ""  # the local fallback (no staff host) still refuses the alias, as the public host
    settings.CATALYST_ENV = "test"
    for path in ("/staff/", "/staff/p2/"):
        assert client.get(path, **https).status_code == 404, path
