"""Contact confirmation (S1-T6; 005 S1.2 Confirm; J-03; ADR-16, D-24): TEST-S1-08 to TEST-S1-10,
TEST-S1-22, the confirmation part of TEST-S1-05 and the confirmation part of TEST-S1-16.

Every request and service call runs as the application role (tests/conftest.py). Work is created by an
actual intake POST, and links are built by the same helper the worker uses (or read from the sink in the
end-to-end test). Tests that need committed data (expiry set by the owner, concurrency, failure injection)
use `privileged_reset`; the others roll back. "Nothing changed" is checked against a full snapshot of the
rows confirmation could touch.
"""

import logging
import re
from io import StringIO
from urllib.parse import urlencode

import pytest
from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.signing import Signer
from django.db import DatabaseError, connection
from django.test import Client
from django.urls import reverse

from applications import confirmation
from applications.identity import email_key
from applications.links import CONFIRM_PATH, SALT, verification_link
from applications.models import Application, ApplicationEvent, ContactChallenge, SubmissionVersion, VersionAdoption
from config import redaction, runtime
from tests.test_intake import SLICE, app_role_rows, wait_for_waiters
from workflow.models import PendingAction

FORM = reverse("applications:request_access")
VALID = {"name": "Ada Example", "email": "ada@example.test", "reason": "Synthetic reason for access."}
APP_ROLE = settings.CATALYST_DB_ROLES["app"]


def intake(client=None, **fields):
    data = {**VALID, **fields}
    response = (client or Client()).post(FORM, urlencode(data), content_type="application/x-www-form-urlencoded")
    assert response.status_code == 302
    return Application.objects.get(email_key=email_key(data["email"]))


def active_challenge(app):
    return ContactChallenge.objects.get(application=app, used_at__isnull=True, superseded_at__isnull=True)


def link_for(app):
    return verification_link(active_challenge(app).public_id)


def path_of(link):
    return link.removeprefix(settings.CATALYST_PUBLIC_BASE_URL)


def token_of(link):
    return path_of(link).removeprefix(CONFIRM_PATH).rstrip("/")


def version(app, number):
    return SubmissionVersion.objects.get(application=app, version_number=number)


def post_confirm(client, link, version_public_id, **extra):
    return client.post(path_of(link), urlencode({"version": str(version_public_id), **extra}),
                       content_type="application/x-www-form-urlencoded")


def snapshot():
    """Every row confirmation could write or change, in a comparable form."""
    return {
        "applications": sorted(Application.objects.values_list("id", "stage", "contact_verified_at", "updated_at")),
        "challenges": sorted(ContactChallenge.objects.values_list("id", "used_at", "superseded_at")),
        "adoptions": sorted(VersionAdoption.objects.values_list("id", "submission_version_id")),
        "events": sorted(ApplicationEvent.objects.values_list("id", "kind")),
        "actions": sorted(PendingAction.objects.values_list("id", "kind", "status", "input_ref")),
        "versions": sorted(SubmissionVersion.objects.values_list("id", "version_number")),
    }


def assert_private_headers(response):
    assert response["Referrer-Policy"] == "no-referrer"
    assert "no-store" in response["Cache-Control"]


def assert_confirmed_once(app, adopted_number):
    app.refresh_from_db()
    assert app.stage == "contact_verified" and app.contact_verified_at is not None
    adopted = version(app, adopted_number)
    adoption = VersionAdoption.objects.get()
    assert (adoption.application_id, adoption.submission_version_id) == (app.id, adopted.id)
    assert ContactChallenge.objects.get(pk=adoption.via_challenge_id).used_at is not None
    assert list(app.events.filter(kind="contact_verified").values_list("actor_type", "data")) == [
        ("applicant", {"version_number": adopted_number})]
    action = PendingAction.objects.get(kind="start_evidence_collection")
    assert (action.status, action.subject_type, action.subject_id) == ("held", "application", app.public_ref)
    assert action.input_ref == str(adopted.public_id)  # the adopted version, never "the latest"
    assert action.idempotency_key == f"start_evidence_collection:{app.public_ref}"


# --- TEST-S1-08: open the link, then confirm ------------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "head"])
def test_s1_08_opening_the_link_shows_the_answers_and_changes_nothing(method):
    app = intake()
    link = link_for(app)
    before = snapshot()
    client = Client()
    response = getattr(client, method)(path_of(link))
    assert response.status_code == 200
    assert_private_headers(response)
    assert "csrftoken" in response.cookies
    assert snapshot() == before
    if method == "get":
        body = response.content.decode()
        assert all(value in body for value in VALID.values())
        assert f'name="version" value="{version(app, 1).public_id}"' in body
        assert token_of(link) not in body  # the form posts to its own URL; the token is not repeated


@pytest.mark.django_db
def test_s1_08_confirming_records_contact_control_once():
    app = intake()
    link = link_for(app)
    client = Client(enforce_csrf_checks=True)
    page = client.get(path_of(link))
    v1 = version(app, 1)
    assert post_confirm(client, link, v1.public_id).status_code == 403  # CSRF enforced
    response = post_confirm(client, link, v1.public_id, csrfmiddlewaretoken=page.cookies["csrftoken"].value)
    assert response.status_code == 200 and "Email address confirmed" in response.content.decode()
    assert_private_headers(response)
    assert_confirmed_once(app, 1)
    assert not app.events.filter(kind="needs_staff_attention").exists()
    # The same link again: "already confirmed", and nothing changes.
    before = snapshot()
    for again in (client.get(path_of(link)),
                  post_confirm(client, link, v1.public_id, csrfmiddlewaretoken=page.cookies["csrftoken"].value)):
        assert again.status_code == 200 and "already confirmed" in again.content.decode()
        assert_private_headers(again)
    assert snapshot() == before


def test_s1_08_end_to_end_from_intake_through_the_worker_to_confirmation(privileged_reset, monkeypatch, settings):
    """The synthetic flow: intake POST, the real worker command sends to the sink, the link from the sink
    is opened and confirmed. Afterwards the send is done and nothing more is queued for the worker."""
    monkeypatch.setitem(runtime._declared, "kind", runtime.process_kind())  # the command declares a worker
    settings.CATALYST_WORKER_POLL_SECONDS = 0.05
    app = intake()
    call_command("run_worker", exit_when_idle=True, stdout=StringIO())
    [message] = mail.outbox
    link = re.search(re.escape(settings.CATALYST_PUBLIC_BASE_URL + CONFIRM_PATH) + r"\S+/", message.body).group(0)
    assert link == link_for(app)
    client = Client()
    page = client.get(path_of(link))
    v1 = re.search(r'name="version" value="([^"]+)"', page.content.decode()).group(1)
    assert post_confirm(client, link, v1).status_code == 200
    assert_confirmed_once(app, 1)
    assert sorted(PendingAction.objects.values_list("kind", "status")) == [
        ("send_verification", "done"), ("start_evidence_collection", "held")]
    call_command("run_worker", exit_when_idle=True, stdout=StringIO())  # the held action is never claimed
    assert PendingAction.objects.get(kind="start_evidence_collection").status == "held"
    assert len(mail.outbox) == 1


def test_s1_08_a_send_still_queued_when_the_link_is_used_is_cancelled_by_the_worker(privileged_reset, monkeypatch, settings):
    """A redelivered or late send must not go out for a used challenge: the worker's check refuses it."""
    monkeypatch.setitem(runtime._declared, "kind", runtime.process_kind())
    settings.CATALYST_WORKER_POLL_SECONDS = 0.05
    app = intake()
    assert post_confirm(Client(), link_for(app), version(app, 1).public_id).status_code == 200
    call_command("run_worker", exit_when_idle=True, stdout=StringIO())
    assert mail.outbox == []
    send = PendingAction.objects.get(kind="send_verification")
    assert (send.status, send.last_error) == ("cancelled", "challenge already used")


# --- TEST-S1-09: refusals ----------------------------------------------------------------------------------------

def refused(client, link, version_public_id, status):
    """POST and GET of a refused link: the status, the invalid page, private headers, no state change."""
    before = snapshot()
    for response in (client.get(path_of(link)), post_confirm(client, link, version_public_id)):
        assert response.status_code == status
        assert_private_headers(response)
        assert "This link is not valid" in response.content.decode()
    assert snapshot() == before


def tampered(link):
    token = token_of(link)
    flipped = token[:-1] + ("A" if token[-1] != "A" else "B")
    return link.replace(token, flipped)


@pytest.mark.django_db
def test_s1_09_a_tampered_or_forged_token_is_refused(caplog):
    caplog.set_level(logging.INFO)
    app = intake()
    link = link_for(app)
    v1 = version(app, 1).public_id
    client = Client()
    refused(client, tampered(link), v1, 404)
    refused(client, link.replace(token_of(link), str(active_challenge(app).public_id)), v1, 404)  # the raw id is not authorization
    forged_value = Signer(key=settings.CATALYST_VERIFICATION_KEY, salt=SALT).sign("not-a-uuid")
    refused(client, link.replace(token_of(link), forged_value), v1, 404)
    other_salt = Signer(key=settings.CATALYST_VERIFICATION_KEY, salt="other").sign(str(active_challenge(app).public_id))
    refused(client, link.replace(token_of(link), other_salt), v1, 404)
    unknown = verification_link("00000000-0000-4000-8000-000000000000")
    refused(client, unknown, v1, 404)
    assert "confirmation refused: bad signature; nothing changed" in caplog.text
    assert "confirmation refused: unknown challenge; nothing changed" in caplog.text
    assert_no_secrets(caplog, link, tampered(link), unknown)
    assert active_challenge(app).used_at is None


@pytest.mark.django_db
def test_s1_09_a_token_signed_with_a_retired_key_past_its_fallback_is_refused(settings):
    app = intake()
    old_link = link_for(app)  # signed with the current key
    v1 = version(app, 1).public_id
    settings.CATALYST_VERIFICATION_KEY = "synthetic-rotated-verification-key"
    settings.CATALYST_VERIFICATION_FALLBACK_KEYS = []
    refused(Client(), old_link, v1, 404)
    # Positive control: while the old key is still a fallback, the same link confirms.
    settings.CATALYST_VERIFICATION_FALLBACK_KEYS = [settings_value("CATALYST_VERIFICATION_KEY")]
    assert post_confirm(Client(), old_link, v1).status_code == 200
    assert_confirmed_once(app, 1)


def settings_value(name):
    """The value from the environment-built settings module, untouched by the `settings` fixture."""
    import config.settings as built
    return getattr(built, name)


def test_s1_09_an_expired_challenge_is_refused_by_the_database_clock(privileged_reset):
    app = intake()
    link = link_for(app)
    owner = privileged_reset.connect("owner", autocommit=True)
    # Test setup only, as the owner: age the challenge (the application role cannot change expiry).
    owner.execute("UPDATE applications_contactchallenge SET created_at = now() - interval '2 hours',"
                  " expires_at = now() - interval '1 hour'")
    refused(Client(), link, version(app, 1).public_id, 410)
    assert active_challenge(app).used_at is None


@pytest.mark.django_db
def test_s1_09_a_superseded_challenge_is_refused_and_the_new_one_works():
    app = intake()
    old_link = link_for(app)
    PendingAction.objects.update(status="failed")  # its send failed, so a repeat reissues the challenge
    intake()
    new_link = link_for(app)
    assert new_link != old_link
    refused(Client(), old_link, version(app, 2).public_id, 410)
    assert post_confirm(Client(), new_link, version(app, 2).public_id).status_code == 200
    assert_confirmed_once(app, 2)


@pytest.mark.django_db
def test_s1_09_a_closed_application_cannot_be_confirmed():
    app = intake()
    link = link_for(app)
    Application.objects.filter(pk=app.pk).update(stage="withdrawn")  # stand-in for a later terminal stage
    refused(Client(), link, version(app, 1).public_id, 410)


@pytest.mark.django_db
def test_s1_09_a_post_naming_another_application_s_version_or_no_version_is_refused(caplog):
    caplog.set_level(logging.INFO)
    app = intake()
    other = intake(email="other@example.test", name="Other Example")
    link = link_for(app)
    client = Client()
    before = snapshot()
    for bad in (version(other, 1).public_id, "00000000-0000-4000-8000-000000000000", "not-a-version", ""):
        response = post_confirm(client, link, bad)
        assert response.status_code == 400 and "This link is not valid" in response.content.decode()
        assert_private_headers(response)
    assert snapshot() == before
    assert "confirmation refused: version does not belong to the application; nothing changed" in caplog.text
    assert "confirmation refused: version is not a reference; nothing changed" in caplog.text
    assert_no_secrets(caplog, link)
    # The link itself is still good.
    assert post_confirm(client, link, version(app, 1).public_id).status_code == 200


# --- TEST-S1-10: concurrency ---------------------------------------------------------------------------------

def in_thread(results, call):
    def body():
        try:
            response = call()
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user")
                role = cursor.fetchone()[0]
            results.append((response.status_code, response.content.decode(), role))
        except BaseException as exc:  # recorded so the test fails with the cause
            results.append(exc)
    return body


def hold_application(privileged_reset, app):
    holder = privileged_reset.connect("app")  # a transaction is open until commit
    holder.execute("SELECT id FROM applications_application WHERE id = %s FOR UPDATE", [app.pk])
    return holder, privileged_reset.connect("app", autocommit=True)


def test_s1_10_two_concurrent_confirmations_of_one_link_record_it_once(privileged_reset):
    app = intake()
    link, v1 = link_for(app), version(app, 1).public_id
    holder, monitor = hold_application(privileged_reset, app)
    results = []
    threads = [privileged_reset.thread(in_thread(results, lambda: post_confirm(Client(), link, v1))) for _ in range(2)]
    wait_for_waiters(monitor, expected=2)
    assert results == []  # both are queued behind the application lock
    holder.commit()
    for t in threads:
        t.join(timeout=30)
    assert [(status, role) for status, _, role in results] == [(200, APP_ROLE)] * 2
    assert sorted("already confirmed" in body for _, body, _ in results) == [False, True]
    assert_confirmed_once(app, 1)
    assert ContactChallenge.objects.count() == 1


@pytest.mark.parametrize("first", ["confirmation", "repeat"])
def test_s1_10_a_confirmation_racing_a_repeat_submission(privileged_reset, first):
    """Both queue behind a held application lock in a fixed order (PostgreSQL grants a row lock to its
    waiters in arrival order), so each order is exercised deliberately. Lock order is application, then
    challenge on both paths: no deadlock, and each outcome follows the policy for that order."""
    app = intake()
    link, v1 = link_for(app), version(app, 1).public_id
    holder, monitor = hold_application(privileged_reset, app)
    results = {"confirmation": [], "repeat": []}
    calls = {
        "confirmation": lambda: post_confirm(Client(), link, v1),
        "repeat": lambda: Client().post(FORM, urlencode({**VALID, "reason": "A second synthetic reason."}),
                                        content_type="application/x-www-form-urlencoded"),
    }
    second = "repeat" if first == "confirmation" else "confirmation"
    threads = [privileged_reset.thread(in_thread(results[first], calls[first]))]
    wait_for_waiters(monitor, expected=1)
    threads.append(privileged_reset.thread(in_thread(results[second], calls[second])))
    wait_for_waiters(monitor, expected=2)
    holder.commit()
    for t in threads:
        t.join(timeout=30)
    assert [r[0] for r in results["confirmation"]] == [200]
    assert [r[0] for r in results["repeat"]] == [302]
    assert_confirmed_once(app, 1)  # version 1 was shown and named, whatever came in meanwhile
    v2 = version(app, 2)
    staff = list(app.events.filter(kind="needs_staff_attention").values_list("data", flat=True))
    if first == "confirmation":  # the repeat arrived after verification
        assert v2.origin == "repeat_after_verification"
        assert staff == [{"version_number": 2, "reason": "repeat_after_verification"}]
    else:  # the repeat reused the challenge; the confirmation found a newer unverified version
        assert v2.origin == "form"
        assert staff == [{"reason": "newer_unverified_version", "adopted_version_number": 1, "unverified_version_numbers": [2]}]
    assert ContactChallenge.objects.count() == 1
    assert PendingAction.objects.filter(kind="start_evidence_collection").count() == 1


# --- TEST-S1-22: intervening unverified submissions ----------------------------------------------------------------

@pytest.mark.django_db
def test_s1_22_only_the_version_shown_and_named_is_adopted():
    app = intake()  # version 1, its link queued
    intake(name="Ada Changed", reason="Different synthetic answers.")  # version 2 before confirmation
    link = link_for(app)
    client = Client()
    page = client.get(path_of(link)).content.decode()
    assert "Ada Changed" in page and "Different synthetic answers." in page  # the current version
    assert "Ada Example" not in page
    v2 = version(app, 2)
    assert post_confirm(client, link, v2.public_id).status_code == 200
    assert_confirmed_once(app, 2)
    assert not VersionAdoption.objects.filter(submission_version=version(app, 1)).exists()
    assert SubmissionVersion.objects.filter(application=app).count() == 2  # version 1 is kept, unverified
    assert not app.events.filter(kind="needs_staff_attention").exists()  # nothing newer than the adopted one


@pytest.mark.django_db
def test_s1_22_a_version_arriving_between_get_and_post_stays_unverified_and_goes_to_staff():
    app = intake()
    intake(name="Ada Two", reason="Second synthetic answers.")
    link = link_for(app)
    client = Client()
    page = client.get(path_of(link)).content.decode()
    shown = re.search(r'name="version" value="([^"]+)"', page).group(1)
    assert shown == str(version(app, 2).public_id)
    intake(name="Ada Three", reason="Third synthetic answers.")  # version 3 arrives after the page was shown
    assert post_confirm(client, link, shown).status_code == 200
    assert_confirmed_once(app, 2)
    assert VersionAdoption.objects.filter(submission_version__version_number__in=[1, 3]).count() == 0
    staff = app.events.get(kind="needs_staff_attention")
    assert staff.data == {"reason": "newer_unverified_version", "adopted_version_number": 2, "unverified_version_numbers": [3]}


# --- TEST-S1-05 (confirmation part): a failure after the verification write leaves nothing --------------------------

def failing_insert(table, lose_connection=False):
    def wrapper(execute, sql, params, many, context):
        if sql.startswith(f'INSERT INTO "{table}"'):
            if lose_connection:
                context["connection"].connection.close()
            else:
                raise DatabaseError("injected failure")
        return execute(sql, params, many, context)
    return wrapper


@pytest.mark.parametrize("fault", ["after-verification-write", "at-event", "at-action", "connection-lost"])
def test_s1_05_a_failure_during_confirmation_records_nothing(privileged_reset, caplog, monkeypatch, fault):
    app = intake()
    link, v1 = link_for(app), version(app, 1).public_id
    committed = {t: app_role_rows(t) for t in SLICE}
    client = Client()
    with monkeypatch.context() as patch:  # the autouse network guard stays in place
        if fault == "after-verification-write":
            patch.setattr(confirmation, "_after_verification_write", lambda: (_ for _ in ()).throw(DatabaseError("injected failure")))
            response = post_confirm(client, link, v1)
        else:
            table = {"at-event": "applications_applicationevent", "at-action": "workflow_pendingaction",
                     "connection-lost": "applications_versionadoption"}[fault]
            with connection.execute_wrapper(failing_insert(table, lose_connection=fault == "connection-lost")):
                response = post_confirm(client, link, v1)
    assert response.status_code == 503 and "Please try again" in response.content.decode()
    assert_private_headers(response)
    assert "confirmation did not complete:" in caplog.text and "injected failure" not in caplog.text
    assert_no_secrets(caplog, link)
    assert {t: app_role_rows(t) for t in SLICE} == committed  # no verification, adoption, event or action
    app.refresh_from_db()
    assert (app.stage, app.contact_verified_at) == ("submitted", None)
    assert active_challenge(app).used_at is None  # still active
    # The same link works once the database does.
    assert post_confirm(client, link, v1).status_code == 200
    assert_confirmed_once(app, 1)


# --- TEST-S1-16 (confirmation part): no token, address or name in any log record --------------------------------------

def assert_no_secrets(caplog, *links):
    text = "\n".join(record.getMessage() + str(record.exc_text or "") + str(getattr(record, "request", "") or "")
                     for record in caplog.records)
    for link in links:
        assert token_of(link) not in text
    for value in (VALID["email"], VALID["name"], VALID["reason"], "other@example.test"):
        assert value not in text


@pytest.mark.django_db
def test_s1_16_confirmation_logs_carry_no_token_address_or_name(caplog):
    caplog.set_level(logging.DEBUG)
    app = intake()
    link = link_for(app)
    v1 = version(app, 1).public_id
    client = Client(enforce_csrf_checks=True)
    assert client.get(path_of(tampered(link))).status_code == 404  # django.request: "Not Found: <path>"
    assert Client().put(path_of(link)).status_code == 405  # django.request: "Method Not Allowed (PUT): <path>"
    assert post_confirm(client, link, v1).status_code == 403  # django.security.csrf: "Forbidden (...): <path>"
    csrf = client.get(path_of(link)).cookies["csrftoken"].value
    assert post_confirm(client, link, "not-a-version", csrfmiddlewaretoken=csrf).status_code == 400
    assert post_confirm(client, link, v1, csrfmiddlewaretoken=csrf).status_code == 200
    assert post_confirm(client, link, v1, csrfmiddlewaretoken=csrf).status_code == 200  # already confirmed
    redacted = [r.getMessage() for r in caplog.records if r.name in ("django.request", "django.security.csrf")]
    assert any(m.startswith("Not Found: /confirm/[redacted]") for m in redacted), redacted
    assert any(m.startswith("Method Not Allowed (PUT): /confirm/[redacted]") for m in redacted), redacted
    assert any(re.fullmatch(r"Forbidden \(CSRF [^)]*\): /confirm/\[redacted\]/", m) for m in redacted), redacted
    assert_no_secrets(caplog, link, tampered(link))


def test_redaction_rewrites_only_the_token():
    record = logging.LogRecord("django.request", logging.WARNING, __file__, 1, "%s: %s",
                               ("Not Found", "/confirm/abc:def-_/"), None)
    assert redaction.RedactConfirmationTokens().filter(record) is True
    assert record.getMessage() == "Not Found: /confirm/[redacted]/"
    plain = logging.LogRecord("django.request", logging.WARNING, __file__, 1, "%s: %s", ("Not Found", "/request-access/x"), None)
    redaction.RedactConfirmationTokens().filter(plain)
    assert (plain.msg, plain.args) == ("%s: %s", ("Not Found", "/request-access/x"))  # untouched
    assert all(any(isinstance(f, redaction.RedactConfirmationTokens) for f in logging.getLogger(name).filters)
               for name in redaction.LOGGERS)
    # The development server's request line, and the request object a handler could print.
    server = logging.LogRecord("django.server", logging.INFO, __file__, 1, '"%s" %s %s',
                               ("GET /confirm/abc:def/ HTTP/1.1", "200", "12"), None)
    server.request = object()
    redaction.RedactConfirmationTokens().filter(server)
    assert server.getMessage() == '"GET /confirm/[redacted]/ HTTP/1.1" 200 12' and server.request is None


@pytest.mark.django_db
def test_s1_08_responses_built_outside_the_view_are_private_too(monkeypatch):
    """CSRF 403, 405, the resolver's 404, the trailing-slash redirect (whose Location carries the token)
    and a 500 are produced outside the view: the middleware still marks them no-store and no-referrer."""
    app = intake()
    link = link_for(app)
    path = path_of(link)
    responses = {
        403: post_confirm(Client(enforce_csrf_checks=True), link, version(app, 1).public_id),
        405: Client().put(path),
        301: Client().get(path.rstrip("/")),
        404: Client().get(path + "extra/"),
    }
    monkeypatch.setattr(confirmation, "preview", lambda challenge: 1 / 0)
    responses[500] = Client(raise_request_exception=False).get(path)
    for status, response in responses.items():
        assert response.status_code == status
        assert_private_headers(response)
    assert "no-store" not in Client().get(FORM).get("Cache-Control", "")  # only the confirmation path


@pytest.mark.django_db
def test_s1_09_expiry_follows_the_database_clock_not_the_application_clock(monkeypatch):
    from django.utils import timezone

    app = intake()
    link = link_for(app)
    real_now = timezone.now
    monkeypatch.setattr(timezone, "now", lambda: real_now() + timezone.timedelta(days=365))  # app clock a year ahead
    assert post_confirm(Client(), link, version(app, 1).public_id).status_code == 200
    assert_confirmed_once(app, 1)


def test_the_confirm_route_is_the_path_the_link_names():
    assert reverse("applications:confirm", args=["x:y"]) == f"{CONFIRM_PATH}x:y/"
