"""Public intake (S1-T4; 005 S1.2, S1.3; J-01, J-02): TEST-S1-01 to TEST-S1-05 as far as they apply
before the worker (S1-T5) and the confirmation handler (S1-T6) exist.

Every request and service call here runs as the restricted application role (tests/conftest.py). Tests
marked django_db roll back; tests that need real commits (expiry set by the owner, concurrency, failure
injection with connection loss) use `privileged_reset`. Stand-ins for later tasks are named where used.
"""

import threading
import uuid
from urllib.parse import urlencode

import psycopg
import pytest
from django.conf import settings
from django.db import DatabaseError, connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from applications import services
from applications.identity import email_key
from applications.models import Application, ApplicationEvent, ContactChallenge, SubmissionVersion, VersionAdoption
from workflow.models import PendingAction

FORM = reverse("applications:request_access")
RECEIVED = reverse("applications:request_access_received")
VALID = {"name": "Ada Example", "email": "ada@example.test", "reason": "Synthetic reason for access."}


def post(client, data=None, **fields):
    """A browser-style urlencoded POST."""
    body = urlencode(data if data is not None else {**VALID, **fields})
    return client.post(FORM, body, content_type="application/x-www-form-urlencoded")


def counts():
    return {
        "applications": Application.objects.count(),
        "versions": SubmissionVersion.objects.count(),
        "events": ApplicationEvent.objects.count(),
        "challenges": ContactChallenge.objects.count(),
        "actions": PendingAction.objects.count(),
    }


EMPTY = {"applications": 0, "versions": 0, "events": 0, "challenges": 0, "actions": 0}


def active_challenges(app):
    return ContactChallenge.objects.filter(application=app, used_at__isnull=True, superseded_at__isnull=True)


def app_role_rows(table):
    """Count rows through a fresh application-role connection: what is committed, not what this test sees."""
    with psycopg.connect(
        host=connection.settings_dict["HOST"], port=connection.settings_dict["PORT"], dbname=connection.settings_dict["NAME"],
        user=settings.CATALYST_DB_ROLES["app"], password=connection.settings_dict["PASSWORD"],
    ) as conn:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


SLICE = ["applications_application", "applications_submissionversion", "applications_applicationevent",
         "applications_contactchallenge", "applications_versionadoption", "workflow_pendingaction",
         "correspondence_outboundmessage"]


# --- the identity key (005 S1.3, POL-01 PROPOSED default) -------------------------------------------------

@pytest.mark.parametrize(("typed", "key"), [
    ("ada@example.test", "ada@example.test"),
    ("  Ada@Example.TEST  ", "ada@example.test"),
    ("ada@ＥＸＡＭＰＬＥ.test", "ada@example.test"),  # full-width letters, NFKC
    ("ada@exämple.test", "ada@xn--exmple-cua.test"),  # IDN to its ASCII form
    ("ada@exämple.test", "ada@xn--exmple-cua.test"),  # decomposed form of the same domain
    ("STRASSE@example.test", "strasse@example.test"),
    ("ada+x@example.test", "ada+x@example.test"),  # plus-addressing not folded
])
def test_email_key(typed, key):
    assert email_key(typed) == key


@pytest.mark.parametrize("typed", ["", "no-at-sign", "@example.test", "ada@"])
def test_email_key_refuses_non_addresses(typed):
    with pytest.raises(ValueError):
        email_key(typed)


# --- TEST-S1-01: a valid submission -------------------------------------------------------------------------

@pytest.mark.django_db
def test_s1_01_valid_submission_records_everything_once(client):
    response = post(client)
    assert response.status_code == 302 and response["Location"] == RECEIVED
    app = Application.objects.get()
    assert (app.email, app.email_key, app.display_name, app.stage) == ("ada@example.test", "ada@example.test", "Ada Example", "submitted")
    assert app.next_version_number == 2
    version = SubmissionVersion.objects.get()
    assert (version.application_id, version.version_number, version.origin) == (app.id, 1, "form")
    assert version.submitted_fields == {"name": "Ada Example", "email": "ada@example.test", "reason": "Synthetic reason for access."}
    event = ApplicationEvent.objects.get()
    assert (event.kind, event.actor_type, event.data) == ("submission_received", "applicant", {"version_number": 1})
    challenge = active_challenges(app).get()
    assert challenge.email_at_issue == "ada@example.test"
    assert challenge.expires_at > challenge.created_at
    action = PendingAction.objects.get()
    assert (action.kind, action.status, action.subject_type, action.subject_id) == ("send_verification", "queued", "application", app.public_ref)
    assert action.input_ref == str(challenge.public_id)
    assert action.idempotency_key == f"send_verification:{challenge.public_id}"
    assert VersionAdoption.objects.count() == 0  # adoption is S1-T6's, never intake's


@pytest.mark.django_db
def test_s1_01_challenge_lifetime_comes_from_the_setting(client, settings):
    settings.CATALYST_CHALLENGE_LIFETIME_SECONDS = 120
    post(client)
    challenge = ContactChallenge.objects.get()
    assert abs((challenge.expires_at - challenge.created_at).total_seconds() - 120) < 1


@pytest.mark.django_db
def test_s1_01_the_received_page_carries_no_reference(client):
    post(client)
    app = Application.objects.get()
    page = client.get(RECEIVED)
    body = page.content.decode()
    assert page.status_code == 200 and "Request received" in body
    assert str(app.public_ref) not in body and "ada@example.test" not in body


@pytest.mark.django_db
def test_s1_01_the_service_runs_as_the_application_role(client, monkeypatch):
    seen = []
    original = services._next_version_number

    def spy(application):
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_user")
            seen.append(cursor.fetchone()[0])
        return original(application)

    monkeypatch.setattr(services, "_next_version_number", spy)
    post(client)
    assert seen == [settings.CATALYST_DB_ROLES["app"]]


# --- TEST-S1-02: invalid submissions -------------------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize("fields", [
    {"name": ""}, {"email": ""}, {"reason": ""},
    {"email": "not-an-email"}, {"email": "ada@"},
    {"name": "n" * 201}, {"reason": "r" * 2001}, {"email": "a" * 310 + "@example.test"},
], ids=["no-name", "no-email", "no-reason", "malformed-email", "no-domain", "long-name", "long-reason", "long-email"])
def test_s1_02_invalid_fields_show_form_errors_and_record_nothing(client, fields):
    response = post(client, **fields)
    assert response.status_code == 200
    assert response.context["form"].errors
    assert counts() == EMPTY


@pytest.mark.django_db
def test_s1_02_too_many_fields_is_a_400_and_records_nothing(client):
    response = post(client, {**VALID, **{f"extra{i}": "x" for i in range(settings.DATA_UPLOAD_MAX_NUMBER_FIELDS)}})
    assert response.status_code == 400
    assert counts() == EMPTY


@pytest.mark.django_db
def test_s1_02_an_oversized_body_is_a_400_and_records_nothing(client):
    response = post(client, reason="r" * (settings.DATA_UPLOAD_MAX_MEMORY_SIZE + 1))
    assert response.status_code == 400
    assert counts() == EMPTY


@pytest.mark.django_db
def test_s1_02_an_address_that_normalizes_past_the_column_is_a_form_error(client):
    typed = "a@" + ".".join(["ä"] * 100) + ".test"  # 300 characters typed; punycode makes it far longer
    assert len(typed) <= 320 and len(email_key(typed)) > 320
    response = post(client, email=typed)
    assert response.status_code == 200 and "email" in response.context["form"].errors
    assert counts() == EMPTY


@pytest.mark.django_db
def test_s1_02_a_file_part_is_a_400_and_records_nothing(client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    response = client.post(FORM, {**VALID, "attachment": SimpleUploadedFile("x.txt", b"synthetic")})  # multipart
    assert response.status_code == 400
    assert counts() == EMPTY


@pytest.mark.django_db
def test_s1_02_a_missing_csrf_token_is_a_403_and_records_nothing():
    strict = Client(enforce_csrf_checks=True)
    assert post(strict).status_code == 403
    assert counts() == EMPTY
    # With the token from the form page the same submission is accepted, so CSRF is what refused it.
    strict.get(FORM)
    token = strict.cookies[settings.CSRF_COOKIE_NAME].value
    assert post(strict, {**VALID, "csrfmiddlewaretoken": token}).status_code == 302
    assert counts()["applications"] == 1


# --- TEST-S1-03: repeat submissions ------------------------------------------------------------------------

@pytest.mark.django_db
def test_s1_03_variants_of_one_key_attach_to_one_application_and_reuse_the_challenge(client):
    responses = [post(client, email=e) for e in ("ada@example.test", "  ADA@Example.TEST ", "ada@ＥＸＡＭＰＬＥ.test")]
    assert {(r.status_code, r["Location"], r.content) for r in responses} == {(302, RECEIVED, b"")}
    app = Application.objects.get()
    assert list(app.versions.order_by("version_number").values_list("version_number", "origin")) == [
        (1, "form"), (2, "form"), (3, "form")]
    assert app.email == "ada@example.test"  # the address first typed is kept for sending
    assert list(app.events.order_by("id").values_list("kind", flat=True)) == [
        "submission_received", "repeat_submission", "repeat_submission"]
    assert ContactChallenge.objects.count() == 1 and PendingAction.objects.count() == 1  # reused, no new work


@pytest.mark.django_db
def test_s1_03_a_plus_addressed_variant_is_a_different_applicant(client):
    post(client)
    response = post(client, email="ada+x@example.test")
    assert (response.status_code, response["Location"]) == (302, RECEIVED)
    assert sorted(Application.objects.values_list("email_key", flat=True)) == ["ada+x@example.test", "ada@example.test"]
    assert PendingAction.objects.count() == 2


@pytest.mark.django_db
def test_s1_03_a_repeat_after_a_failed_send_supersedes_the_challenge(client):
    post(client)
    first = ContactChallenge.objects.get()
    PendingAction.objects.update(status="failed")  # stand-in for S1-T5 recording a failed send
    response = post(client)
    assert (response.status_code, response["Location"], response.content) == (302, RECEIVED, b"")
    first.refresh_from_db()
    assert first.superseded_at is not None
    current = active_challenges(first.application).get()
    assert current.pk != first.pk
    queued = PendingAction.objects.get(status="queued")
    assert queued.input_ref == str(current.public_id)
    assert PendingAction.objects.count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize(("status", "reused"), [
    ("queued", True), ("running", True), ("done", True),
    ("failed", False), ("uncertain", False), ("held", False), ("cancelled", False),
])
def test_s1_03_the_challenge_is_reused_only_while_its_send_is_queued_running_or_done(client, status, reused):
    post(client)
    lease = {"lease_token": uuid.uuid4(), "lease_expires_at": timezone.now()} if status == "running" else {}
    PendingAction.objects.update(status=status, **lease)  # stand-in for the worker's state (S1-T5)
    post(client)
    assert ContactChallenge.objects.count() == (1 if reused else 2)
    assert PendingAction.objects.count() == (1 if reused else 2)


@pytest.mark.django_db
def test_s1_03_a_challenge_without_any_send_is_reissued(client):
    from datetime import timedelta

    app = Application.objects.create(email="ada@example.test", email_key="ada@example.test", display_name="Ada Example")
    challenge = ContactChallenge.objects.create(application=app, email_at_issue=app.email,
                                                expires_at=timezone.now() + timedelta(hours=1))  # never queued
    post(client)
    challenge.refresh_from_db()
    assert challenge.superseded_at is not None and active_challenges(challenge.application).count() == 1


@pytest.mark.django_db
def test_s1_03_expiry_is_judged_by_the_database_clock(client, monkeypatch):
    from datetime import timedelta

    post(client)
    real_now = timezone.now
    monkeypatch.setattr(timezone, "now", lambda: real_now() + timedelta(days=365))  # an application clock far ahead
    post(client)
    assert ContactChallenge.objects.count() == 1  # still unexpired by the database clock, so reused


def test_s1_03_a_repeat_after_the_challenge_expired_supersedes_it(privileged_reset):
    client = Client()
    post(client)
    owner = privileged_reset.connect("owner", autocommit=True)
    # Test setup only, as the owner: age the challenge (the application role cannot change expiry).
    owner.execute("UPDATE applications_contactchallenge SET created_at = now() - interval '2 hours',"
                  " expires_at = now() - interval '1 hour'")
    response = post(client)
    assert (response.status_code, response["Location"], response.content) == (302, RECEIVED, b"")
    challenges = list(ContactChallenge.objects.order_by("id"))
    assert len(challenges) == 2 and challenges[0].superseded_at is not None and challenges[1].superseded_at is None
    assert list(PendingAction.objects.order_by("id").values_list("input_ref", flat=True)) == [
        str(c.public_id) for c in challenges]


@pytest.mark.django_db
def test_s1_03_a_repeat_after_verification_is_unverified_and_goes_to_staff(client):
    post(client)
    app = Application.objects.get()
    challenge = ContactChallenge.objects.get()
    first = SubmissionVersion.objects.get()
    # Stand-in for S1-T6: contact verified through the challenge and version 1 adopted.
    ContactChallenge.objects.filter(pk=challenge.pk).update(used_at=challenge.created_at)
    Application.objects.filter(pk=app.pk).update(stage="contact_verified", contact_verified_at=challenge.created_at)
    adoption = VersionAdoption.objects.create(application=app, submission_version=first, via_challenge=challenge)

    response = post(client, name="Someone Else", reason="Different answers.")
    assert (response.status_code, response["Location"], response.content) == (302, RECEIVED, b"")
    repeat = SubmissionVersion.objects.get(version_number=2)
    assert repeat.origin == "repeat_after_verification"
    assert repeat.submitted_fields["name"] == "Someone Else"
    staff = ApplicationEvent.objects.get(kind="needs_staff_attention")
    assert staff.data == {"version_number": 2, "reason": "repeat_after_verification"}
    # Verified data, the earlier version and the adoption are untouched; no new verification work.
    app.refresh_from_db()
    assert (app.display_name, app.stage) == ("Ada Example", "contact_verified")
    first.refresh_from_db()
    assert first.submitted_fields["name"] == "Ada Example"
    assert VersionAdoption.objects.get().pk == adoption.pk and VersionAdoption.objects.get().submission_version_id == first.pk
    assert ContactChallenge.objects.count() == 1 and PendingAction.objects.count() == 1


@pytest.mark.django_db
def test_s1_03_every_outcome_looks_identical_to_the_applicant(client):
    new = post(client)
    repeat = post(client)
    plus = post(client, email="ada+x@example.test")
    assert len({(r.status_code, r["Location"], r.content) for r in (new, repeat, plus)}) == 1


# --- TEST-S1-04: concurrent first submissions ---------------------------------------------------------------

def submit_in_thread(results, email):
    def body():
        try:
            response = post(Client(), email=email)
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user")
                role = cursor.fetchone()[0]
            results.append((response.status_code, response.get("Location"), role))
        except BaseException as exc:  # recorded so the test fails with the cause, not a silent thread
            results.append(exc)
    return body


def test_s1_04_two_concurrent_first_submissions_make_one_application(privileged_reset, monkeypatch):
    # Deterministic seam: both requests have read "no open application" before either inserts.
    barrier = threading.Barrier(2, timeout=20)
    monkeypatch.setattr(services, "_before_insert", lambda key: barrier.wait())
    caught = []
    original = services._constraint_name
    monkeypatch.setattr(services, "_constraint_name", lambda exc: caught.append(original(exc)) or caught[-1])
    results = []
    threads = [privileged_reset.thread(submit_in_thread(results, "race@example.test")) for _ in range(2)]
    for t in threads:
        t.join(timeout=30)
    assert results == [(302, RECEIVED, settings.CATALYST_DB_ROLES["app"])] * 2
    assert caught == [services.OPEN_KEY_CONSTRAINT]  # the loser hit exactly the named constraint
    app = Application.objects.get()
    assert sorted(app.versions.values_list("version_number", flat=True)) == [1, 2]
    assert sorted(app.events.values_list("kind", flat=True)) == ["repeat_submission", "submission_received"]
    assert ContactChallenge.objects.count() == 1 and PendingAction.objects.count() == 1


def test_s1_04_any_other_integrity_error_is_not_swallowed(privileged_reset, monkeypatch):
    # If the losing insert failed on some other constraint, the service must not treat it as the race.
    barrier = threading.Barrier(2, timeout=20)
    monkeypatch.setattr(services, "_before_insert", lambda key: barrier.wait())
    monkeypatch.setattr(services, "_constraint_name", lambda exc: "some_other_constraint")
    results = []
    threads = [privileged_reset.thread(submit_in_thread(results, "race@example.test")) for _ in range(2)]
    for t in threads:
        t.join(timeout=30)
    assert sorted(r[0] for r in results) == [302, 503]
    assert Application.objects.count() == 1 and SubmissionVersion.objects.count() == 1


def test_s1_04_smoke_loop_of_concurrent_pairs(privileged_reset):
    # Supporting evidence only (no seam): each pair starts with a fresh key, so this is not a controlled
    # existing-application test (those are above); real interleavings vary run to run.
    for i in range(15):
        results = []
        email = f"pair{i}@example.test"
        threads = [privileged_reset.thread(submit_in_thread(results, email)) for _ in range(2)]
        for t in threads:
            t.join(timeout=30)
        assert [r[:2] for r in results] == [(302, RECEIVED)] * 2, results
        app = Application.objects.get(email_key=email)
        assert sorted(app.versions.values_list("version_number", flat=True)) == [1, 2]
        assert PendingAction.objects.filter(subject_id=app.public_ref).count() == 1


def wait_for_waiters(monitor, expected, timeout=20):
    """Bounded wait until `expected` sessions in the test database are waiting on a lock (no sleep-only
    timing). Counted by wait state, not by pg_blocking_pids(holder): the second waiter queues behind the
    first on the row's tuple lock, so PostgreSQL names the first waiter, not the holder, as its blocker."""
    import time

    deadline = time.monotonic() + timeout
    while monitor.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                          " AND wait_event_type = 'Lock'").fetchone()[0] < expected:
        if time.monotonic() > deadline:
            raise AssertionError(f"{expected} submissions did not queue behind the application lock in {timeout}s")
        time.sleep(0.02)


def race_two_repeats_on_an_existing_application(privileged_reset, email):
    """A controlled lock-holder sequence: an application-role session holds the existing application's row
    lock; both repeats start and block on that same lock (the first statement of the service's transaction);
    the test waits until both are queued behind it, then releases. Coordination is before the contested
    lock, so the two requests then run through it one after the other, in whichever order PostgreSQL wakes
    them. Returns the request results."""
    holder = privileged_reset.connect("app")  # a transaction is open until commit
    holder.execute("SELECT id FROM applications_application WHERE email_key = %s FOR UPDATE", [email_key(email)])
    monitor = privileged_reset.connect("app", autocommit=True)
    results = []
    threads = [privileged_reset.thread(submit_in_thread(results, email)) for _ in range(2)]
    wait_for_waiters(monitor, expected=2)
    assert results == []  # neither request got past the lock
    holder.commit()  # release
    for t in threads:
        t.join(timeout=30)
    return results


def test_s1_04_two_concurrent_repeats_on_an_existing_application_reuse_its_challenge(privileged_reset):
    email = "known@example.test"
    assert post(Client(), email=email).status_code == 302  # committed: application, version 1, queued send
    results = race_two_repeats_on_an_existing_application(privileged_reset, email)
    assert results == [(302, RECEIVED, settings.CATALYST_DB_ROLES["app"])] * 2
    app = Application.objects.get()
    assert list(app.versions.order_by("version_number").values_list("version_number", flat=True)) == [1, 2, 3]
    assert app.next_version_number == 4
    events = list(app.events.order_by("id").values_list("kind", "data"))
    assert events[0] == ("submission_received", {"version_number": 1})
    assert sorted(events[1:], key=lambda e: e[1]["version_number"]) == [
        ("repeat_submission", {"version_number": 2}), ("repeat_submission", {"version_number": 3})]
    challenge = active_challenges(app).get()
    assert ContactChallenge.objects.count() == 1  # reused by both repeats
    action = PendingAction.objects.get()
    assert (action.status, action.input_ref) == ("queued", str(challenge.public_id))


def test_s1_04_two_concurrent_repeats_needing_a_new_challenge_create_only_one(privileged_reset):
    email = "known@example.test"
    assert post(Client(), email=email).status_code == 302
    old = ContactChallenge.objects.get()
    PendingAction.objects.update(status="failed")  # stand-in for S1-T5 recording a failed send
    results = race_two_repeats_on_an_existing_application(privileged_reset, email)
    assert results == [(302, RECEIVED, settings.CATALYST_DB_ROLES["app"])] * 2
    app = Application.objects.get()
    assert list(app.versions.order_by("version_number").values_list("version_number", flat=True)) == [1, 2, 3]
    assert app.next_version_number == 4
    events = list(app.events.order_by("id").values_list("kind", "data"))
    assert events[0] == ("submission_received", {"version_number": 1})
    assert sorted(events[1:], key=lambda e: e[1]["version_number"]) == [
        ("repeat_submission", {"version_number": 2}), ("repeat_submission", {"version_number": 3})]
    # The first repeat superseded the old challenge and queued one replacement; the second reused it.
    old.refresh_from_db()
    assert old.superseded_at is not None
    current = active_challenges(app).get()
    assert ContactChallenge.objects.count() == 2
    assert sorted(PendingAction.objects.values_list("status", "input_ref")) == sorted(
        [("failed", str(old.public_id)), ("queued", str(current.public_id))])


# --- TEST-S1-05: failures before the commit leave nothing behind; a lost commit acknowledgment is safe to retry --

def failing_on(table, lose_connection=False):
    def wrapper(execute, sql, params, many, context):
        if sql.startswith(f'INSERT INTO "{table}"'):
            if lose_connection:
                context["connection"].connection.close()  # the server connection goes away mid-transaction
            else:
                raise DatabaseError("injected failure")
        return execute(sql, params, many, context)
    return wrapper


@pytest.mark.parametrize(("table", "lose_connection"), [
    ("applications_submissionversion", False),  # right after the application insert
    ("applications_contactchallenge", False),  # inside the challenge step
    ("workflow_pendingaction", False),  # at the action insert
    ("applications_applicationevent", False),  # right after the pending action insert (the last write)
    ("applications_applicationevent", True),  # connection lost after the action insert
], ids=["after-application", "at-challenge", "at-action", "after-action", "connection-lost"])
def test_s1_05_a_database_failure_commits_nothing_and_shows_try_again(privileged_reset, caplog, table, lose_connection):
    client = Client()
    with connection.execute_wrapper(failing_on(table, lose_connection)):
        response = post(client)
    assert response.status_code == 503
    assert "intake submission did not complete" in caplog.text
    assert "ada@example.test" not in caplog.text and "Ada Example" not in caplog.text  # no applicant data logged
    assert VALID["reason"] not in caplog.text and "injected failure" not in caplog.text  # nor the error text
    assert "Please try again" in response.content.decode()
    assert "Location" not in response
    assert {t: app_role_rows(t) for t in SLICE} == {t: 0 for t in SLICE}
    # The form works again once the database does.
    assert post(client).status_code == 302
    assert app_role_rows("applications_application") == 1


def test_s1_05_simulated_lost_commit_acknowledgment_leaves_the_outcome_unknown_and_a_resubmission_is_safe(
        privileged_reset, caplog, monkeypatch):
    """SIMULATION, not a network fault: the COMMIT really succeeds on the server, then the commit call
    reports an OperationalError, standing in for an acknowledgment lost in transit. (A real lost connection
    would also fail Django's rollback and close the connection; the test closes connections itself before
    the retry.) The caller sees a failure although everything committed; the applicant's resubmission on a
    fresh connection follows the duplicate policy."""
    from django.db import OperationalError, connections

    conn = connections["default"]
    commit, lost = conn._commit, []

    def commit_then_lose_the_acknowledgment():
        commit()
        if not lost:
            lost.append(True)
            raise OperationalError("simulated lost commit acknowledgment")

    client = Client()
    with monkeypatch.context() as patch:  # undo only this patch; the autouse network guard stays in place
        patch.setattr(conn, "_commit", commit_then_lose_the_acknowledgment)
        response = post(client)
    assert lost == [True]
    assert response.status_code == 503 and "Location" not in response
    assert "intake submission did not complete: OperationalError" in caplog.text
    assert "ada@example.test" not in caplog.text and "Ada Example" not in caplog.text
    assert "simulated lost" not in caplog.text  # the database error text is never logged
    committed = {t: app_role_rows(t) for t in SLICE}
    assert committed == {**{t: 0 for t in SLICE}, "applications_application": 1, "applications_submissionversion": 1,
                         "applications_applicationevent": 1, "applications_contactchallenge": 1, "workflow_pendingaction": 1}

    connections.close_all()  # the applicant retries on a fresh connection
    assert post(client).status_code == 302
    after = {t: app_role_rows(t) for t in SLICE}
    assert after == {**committed, "applications_submissionversion": 2, "applications_applicationevent": 2}
    app = Application.objects.get()
    assert list(app.versions.order_by("version_number").values_list("version_number", "origin")) == [(1, "form"), (2, "form")]
    assert list(app.events.order_by("id").values_list("kind", flat=True)) == ["submission_received", "repeat_submission"]
    assert PendingAction.objects.get().input_ref == str(active_challenges(app).get().public_id)  # no extra work
