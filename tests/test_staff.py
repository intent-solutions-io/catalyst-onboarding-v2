"""The read-only staff view (S1-T7; 005 S1.2 Staff; D-23, D-24, POL-13 PROPOSED): TEST-S1-11, TEST-S1-12
and the staff parts of the role and logging tests.

Staff accounts are created as the owner (the authorized path: the application role cannot insert users or
memberships), so these tests commit (`privileged_reset`, which also clears accounts and sessions). Every
request then runs through the real middleware, admin and database sessions as the application role.
"""

import logging
import os
import re
import sys
from io import StringIO
from urllib.parse import urlencode

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.urls import reverse

from accounts.management.commands.add_readonly_staff import READ_ONLY_STAFF
from applications.links import verification_link
from applications.models import Application, ApplicationEvent, ContactChallenge, SubmissionVersion
from config import runtime
from tests import support
from tests.test_intake import app_role_rows
from workflow.models import AutomationPause, PendingAction

FORM = reverse("applications:request_access")
VALID = {"name": "Ada Example", "email": "ada@example.test", "reason": "Synthetic reason for access."}
PASSWORD = "synthetic-staff-passphrase-31"  # gitleaks:allow (synthetic test-only password)
LOGIN = reverse("admin:login")
CHANGELIST = reverse("admin:applications_application_changelist")
_hash = {}

VIEWABLE = {
    ("applications", "view_application"), ("applications", "view_submissionversion"),
    ("applications", "view_versionadoption"), ("applications", "view_applicationevent"),
    ("applications", "view_contactchallenge"), ("workflow", "view_pendingaction"),
    ("workflow", "view_automationpause"), ("correspondence", "view_outboundmessage"),
}
REGISTERED = ["applications_application", "workflow_pendingaction", "workflow_automationpause",
              "correspondence_outboundmessage"]


def intake(**fields):
    response = Client().post(FORM, urlencode({**VALID, **fields}), content_type="application/x-www-form-urlencoded")
    assert response.status_code == 302
    return Application.objects.get(email_key=fields.get("email", VALID["email"]))


def make_user(privileged_reset, username, *, staff=True, group=True, superuser=False):
    """As the owner (test setup on the authorized path), never through the application."""
    if "hash" not in _hash:
        _hash["hash"] = make_password(PASSWORD)
    owner = privileged_reset.connect("owner", autocommit=True)
    uid = owner.execute(
        "INSERT INTO accounts_user (password, is_superuser, username, first_name, last_name, email, is_staff, is_active,"
        " date_joined) VALUES (%s, %s, %s, '', '', '', %s, true, now()) RETURNING id",
        [_hash["hash"], superuser, username, staff]).fetchone()[0]
    if group:
        owner.execute("INSERT INTO accounts_user_groups (user_id, group_id) SELECT %s, id FROM auth_group WHERE name = %s",
                      [uid, READ_ONLY_STAFF])
    return get_user_model().objects.get(pk=uid)


def logged_in(user):
    client = Client()
    client.force_login(user)
    return client


def change_url(app):
    return reverse("admin:applications_application_change", args=[app.pk])


def no_applicant_data(response):
    body = response.content.decode()
    return all(value not in body for value in VALID.values())


# --- the group and the grants (POL-13 PROPOSED default; D-23) --------------------------------------------------

@pytest.mark.django_db
def test_s1_12_the_group_holds_exactly_the_view_permissions_on_slice_models():
    group = Group.objects.get(name=READ_ONLY_STAFF)  # created by migration accounts.0003, as the owner
    assert set(group.permissions.values_list("content_type__app_label", "codename")) == VIEWABLE


@pytest.mark.django_db
@pytest.mark.parametrize("statement", [
    "UPDATE accounts_user SET is_superuser = true",
    "UPDATE accounts_user SET is_staff = true",
    "UPDATE accounts_user SET is_active = true",
    "INSERT INTO accounts_user (password, is_superuser, username, first_name, last_name, email, is_staff, is_active,"
    " date_joined) VALUES ('x', true, 'self', '', '', '', true, true, now())",
    "INSERT INTO accounts_user_groups (user_id, group_id) VALUES (1, 1)",
    "INSERT INTO accounts_user_user_permissions (user_id, permission_id) VALUES (1, 1)",
    "INSERT INTO auth_group_permissions (group_id, permission_id) VALUES (1, 1)",
    "INSERT INTO auth_group (name) VALUES ('escalated')",
    "UPDATE auth_permission SET codename = 'change_application'",
    "INSERT INTO django_admin_log (action_time, object_repr, action_flag, change_message, user_id)"
    " VALUES (now(), 'x', 2, '', 1)",
    "DELETE FROM django_admin_log",
])
def test_the_application_role_cannot_elevate_staff_or_write_the_admin_log(statement):
    from django.db import ProgrammingError, transaction

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        assert cursor.fetchone()[0] == settings.CATALYST_DB_ROLES["app"]
        with pytest.raises(ProgrammingError, match="permission denied"), transaction.atomic():
            cursor.execute(statement)


@pytest.mark.django_db
def test_the_application_role_has_only_the_session_and_admin_log_grants_it_needs():
    role = settings.CATALYST_DB_ROLES["app"]
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name, string_agg(privilege_type, ',' ORDER BY privilege_type) FROM information_schema.role_table_grants"
            " WHERE grantee = %s AND table_name IN ('django_session', 'django_admin_log') GROUP BY table_name", [role])
        assert dict(cursor.fetchall()) == {"django_admin_log": "SELECT", "django_session": "DELETE,INSERT,SELECT,UPDATE"}


def test_staff_accounts_are_created_by_the_owner_command_and_refused_to_the_application_role(privileged_reset):
    result = support.run(
        [sys.executable, "manage.py", "add_readonly_staff", "grace", "--password-env", "STAFF_PASSWORD_FOR_TEST"],
        STAFF_PASSWORD_FOR_TEST=PASSWORD, CATALYST_DB_NAME=connection.settings_dict["NAME"],
        CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"], CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"])
    assert result.returncode == 0, result.stderr
    assert PASSWORD not in result.stdout + result.stderr
    user = get_user_model().objects.get(username="grace")
    assert (user.is_staff, user.is_superuser, user.is_active) == (True, False, True)
    assert list(user.groups.values_list("name", flat=True)) == [READ_ONLY_STAFF]
    # The same command as the application role: refused by the database grants.
    refused = support.run(
        [sys.executable, "manage.py", "add_readonly_staff", "mallory", "--password-env", "STAFF_PASSWORD_FOR_TEST"],
        STAFF_PASSWORD_FOR_TEST=PASSWORD, CATALYST_DB_NAME=connection.settings_dict["NAME"],
        CATALYST_DB_USER=settings.CATALYST_DB_ROLES["app"], CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_APP_PASSWORD"])
    assert refused.returncode != 0 and "permission denied" in refused.stderr
    assert not get_user_model().objects.filter(username="mallory").exists()


# --- TEST-S1-11: who gets in ----------------------------------------------------------------------------------

def test_s1_11_anonymous_visitors_are_sent_to_login_and_see_no_data(privileged_reset):
    app = intake()
    for url in (reverse("admin:index"), CHANGELIST, change_url(app), reverse("admin:workflow_pendingaction_changelist")):
        response = Client().get(url)
        assert response.status_code == 302 and response["Location"].startswith(f"{LOGIN}?next=")
        assert no_applicant_data(response)


def test_s1_11_real_login_and_logout_work_with_the_application_role_grants(privileged_reset):
    reader = make_user(privileged_reset, "reader")
    client = Client(enforce_csrf_checks=True)
    page = client.get(LOGIN)
    token = page.cookies["csrftoken"].value
    response = client.post(LOGIN, {"username": "reader", "password": PASSWORD, "csrfmiddlewaretoken": token,
                                   "next": CHANGELIST})
    assert response.status_code == 302 and response["Location"] == CHANGELIST
    assert app_role_rows("django_session") == 1  # a database session, written by the application role
    reader.refresh_from_db()
    assert reader.last_login is not None
    assert client.get(CHANGELIST).status_code == 200
    token = client.cookies["csrftoken"].value  # rotated at login
    assert client.post(reverse("admin:logout"), {"csrfmiddlewaretoken": token}).status_code == 200
    assert app_role_rows("django_session") == 0  # logout deletes it
    assert client.get(CHANGELIST).status_code == 302


def test_s1_11_a_wrong_password_and_a_non_staff_account_cannot_log_in(privileged_reset):
    make_user(privileged_reset, "reader")
    make_user(privileged_reset, "outsider", staff=False)
    for username, password in (("reader", "wrong-password"), ("outsider", PASSWORD)):
        client = Client()
        response = client.post(LOGIN, {"username": username, "password": password, "next": CHANGELIST})
        assert response.status_code == 200 and "correct username and password for a staff account" in response.content.decode()
        assert client.get(CHANGELIST).status_code == 302
    assert app_role_rows("django_session") == 0


def test_s1_11_staff_outside_the_group_are_refused_every_record(privileged_reset, caplog):
    app = intake()
    client = logged_in(make_user(privileged_reset, "nogroup", group=False))
    index = client.get(reverse("admin:index"))
    assert index.status_code == 200 and "have permission to view or edit anything" in index.content.decode()
    for url in (CHANGELIST, change_url(app), reverse("admin:workflow_pendingaction_changelist"),
                reverse("admin:correspondence_outboundmessage_changelist")):
        response = client.get(url)
        assert response.status_code == 403 and no_applicant_data(response)
    assert all(v not in caplog.text for v in VALID.values())


@pytest.mark.parametrize("superuser", [False, True], ids=["read-only-staff", "django-superuser"])
def test_s1_11_every_write_path_is_refused_and_changes_nothing(privileged_reset, monkeypatch, settings, superuser):
    """Read-only staff, and even a Django superuser (never the intended path), cannot add, change, delete or
    run a bulk action on any registered Catalyst record."""
    monkeypatch.setitem(runtime._declared, "kind", runtime.process_kind())
    settings.CATALYST_WORKER_POLL_SECONDS = 0.05
    app = intake()
    call_command("run_worker", exit_when_idle=True, stdout=StringIO())  # an outbound message to target
    owner = privileged_reset.connect("owner", autocommit=True)
    owner.execute("INSERT INTO workflow_automationpause (subject_type, subject_id, reason, actor_ref, created_at)"
                  " VALUES ('application', %s, 'synthetic pause', 'staff:test', now())", [app.public_ref])
    client = logged_in(make_user(privileged_reset, "writer", group=not superuser, superuser=superuser))
    tables = REGISTERED + ["applications_applicationevent", "applications_submissionversion", "applications_contactchallenge"]
    before = {t: app_role_rows(t) for t in tables}
    state = (app.stage, app.contact_verified_at, list(PendingAction.objects.values_list("status", flat=True)))
    targets = [("applications", "application", app), ("workflow", "pendingaction", PendingAction.objects.get()),
               ("workflow", "automationpause", AutomationPause.objects.get()),
               ("correspondence", "outboundmessage", app.outbound_messages.get())]
    for label, model, obj in targets:
        base = f"admin:{label}_{model}"
        assert client.get(reverse(f"{base}_add")).status_code == 403
        assert client.post(reverse(f"{base}_add"), {"stage": "admitted", "status": "done"}).status_code == 403
        assert client.get(reverse(f"{base}_change", args=[obj.pk])).status_code == 200  # viewable, read-only
        change = client.post(reverse(f"{base}_change", args=[obj.pk]), {"stage": "admitted", "status": "done", "_save": "Save"})
        assert change.status_code == 403
        assert client.get(reverse(f"{base}_delete", args=[obj.pk])).status_code == 403
        assert client.post(reverse(f"{base}_delete", args=[obj.pk]), {"post": "yes"}).status_code == 403
        bulk = client.post(reverse(f"{base}_changelist"), {"action": "delete_selected", "_selected_action": [obj.pk], "post": "yes"})
        assert bulk.status_code in (200, 403) and "Are you sure" not in bulk.content.decode()  # no action exists
    # Group, user and password administration is not available through the application.
    assert client.get("/staff/auth/group/").status_code == 404
    assert client.get("/staff/accounts/user/").status_code == 404
    password = get_user_model().objects.get(username="writer").password
    assert client.get(reverse("admin:password_change")).status_code == 403
    assert client.post(reverse("admin:password_change"), {"old_password": PASSWORD, "new_password1": "another-synthetic-pass-77",
                                                          "new_password2": "another-synthetic-pass-77"}).status_code == 403
    assert get_user_model().objects.get(username="writer").password == password
    app.refresh_from_db()
    assert (app.stage, app.contact_verified_at, list(PendingAction.objects.values_list("status", flat=True))) == state
    assert {t: app_role_rows(t) for t in tables} == before
    assert app_role_rows("django_admin_log") == 0


def test_every_registered_admin_is_read_only_and_the_registry_is_exactly_the_slice_views():
    from django.contrib import admin

    from config.staff_admin import ReadOnlyAdminMixin

    registry = admin.site._registry
    assert {m._meta.label for m in registry} == {
        "applications.Application", "workflow.PendingAction", "workflow.AutomationPause", "correspondence.OutboundMessage"}
    for model_admin in registry.values():
        assert isinstance(model_admin, ReadOnlyAdminMixin) and model_admin.actions is None
        assert not model_admin.list_editable and not model_admin.save_as and not model_admin.autocomplete_fields
        for inline in model_admin.inlines:
            assert issubclass(inline, ReadOnlyAdminMixin) and inline.max_num == 0 and inline.can_delete is False


def test_changelist_query_strings_accept_only_the_declared_filters(privileged_reset):
    """Django accepts a lookup on any local field unless told otherwise: a prefix search on a hidden column
    (an idempotency key, an input reference, a lease token) would reveal challenge ids one character at a time."""
    intake()
    client = logged_in(make_user(privileged_reset, "reader"))
    actions = reverse("admin:workflow_pendingaction_changelist")
    for probe in ("idempotency_key__startswith=send", "input_ref__startswith=0", "lease_token__isnull=True",
                  "subject_id__exact=00000000-0000-4000-8000-000000000000"):
        assert client.get(f"{actions}?{probe}").status_code == 400, probe
    for probe in ("email_key__startswith=a", "challenges__public_id__startswith=0", "contact_verified_at__isnull=True"):
        assert client.get(f"{CHANGELIST}?{probe}").status_code == 400, probe
    assert client.get(f"{actions}?status__exact=queued").status_code == 200
    assert client.get(f"{CHANGELIST}?stage__exact=submitted&attention=no").status_code == 200


# --- TEST-S1-12: the dossier --------------------------------------------------------------------------------------

def dossier(client, app):
    response = client.get(change_url(app))
    assert response.status_code == 200
    return response.content.decode()


def test_s1_12_staff_follow_one_applicant_from_intake_to_confirmed_contact(privileged_reset, monkeypatch, settings):
    monkeypatch.setitem(runtime._declared, "kind", runtime.process_kind())  # the worker command declares itself
    settings.CATALYST_WORKER_POLL_SECONDS = 0.05
    client = logged_in(make_user(privileged_reset, "reader"))
    app = intake()  # TEST-S1-01's application

    listing = client.get(CHANGELIST).content.decode()
    assert "Ada Example" in listing and "ada@example.test" in listing
    page = dossier(client, app)
    assert "Not verified; a verification link is active until" in page
    assert "<strong>System</strong>: The verification message is waiting to be sent" in page
    assert "send_verification: <strong>queued</strong>" in page
    assert "none: no version is adopted until the applicant confirms" in page

    call_command("run_worker", exit_when_idle=True, stdout=StringIO())
    page = dossier(client, app)
    assert "<strong>Applicant</strong>: Confirm the email address" in page
    assert "send_verification: <strong>done</strong>" in page
    assert "verification_invitation" in page and "accepted" in page  # the outbound message row

    [message] = mail.outbox
    link = re.search(r"http://\S+/confirm/\S+/", message.body).group(0)
    path = link.removeprefix(settings.CATALYST_PUBLIC_BASE_URL)
    version = re.search(r'name="version" value="([^"]+)"', Client().get(path).content.decode()).group(1)
    assert Client().post(path, {"version": version}).status_code == 200

    page = dossier(client, app)
    assert "contact_verified" in page  # stage and history
    assert "Verified at" in page and "by the applicant&#x27;s confirmation" in page
    assert "version 1; 0 other version(s) unverified" in page
    assert "adopted (confirmed by the applicant)" in page
    assert "used (contact confirmed)" in page
    assert "start_evidence_collection: <strong>held</strong>" in page
    assert "<strong>Blocked</strong>: Start evidence collection is held" in page
    for kind in ("submission_received", "verification_sent", "contact_verified"):
        assert kind in page
    assert "Needs staff attention" not in page  # nothing open on a clean confirmation
    assert "name=\"_save\"" not in page  # read-only: no save button
    assert_no_secret_in(page, app)


def test_s1_12_a_staff_attention_item_is_listed_and_set_apart_from_completed_steps(privileged_reset):
    client = logged_in(make_user(privileged_reset, "reader"))
    app = intake()
    calm = intake(email="calm@example.test", name="Calm Example")
    Application.objects.filter(pk=app.pk).update(stage="contact_verified", contact_verified_at=app.created_at)  # stand-in
    intake(reason="A repeat after verification.")  # raises needs_staff_attention (005 S1.2)

    flagged = client.get(CHANGELIST + "?attention=yes").content.decode()
    assert "Ada Example" in flagged and "Calm Example" not in flagged
    unflagged = client.get(CHANGELIST + "?attention=no").content.decode()
    assert "Calm Example" in unflagged and "Ada Example" not in unflagged
    listing = client.get(CHANGELIST).content.decode()
    assert listing.count('class="errornote">Needs staff attention') == 1

    page = dossier(client, app)
    assert ('<strong class="errornote">Needs staff attention</strong> a submission arrived after the address was verified;'
            " it was not adopted (version 2)") in page
    assert "Needs staff attention. <strong>Staff</strong>: Review: a submission arrived after the address was verified" in page
    assert page.count("recorded step") == 2  # submission_received and repeat_submission, not the attention item
    assert "repeat_after_verification" in page  # the version's origin
    calm_page = dossier(client, calm)
    assert 'class="errornote">Needs staff attention' not in calm_page and "Needs staff attention. " not in calm_page


def flagged(client):
    page = client.get(CHANGELIST + "?attention=yes").content.decode()
    return {a.email for a in Application.objects.all() if f">{a.display_name}<" in page}


def test_s1_12_the_list_flag_and_the_dossier_follow_one_attention_rule(privileged_reset):
    """Each state, with who acts next: the list filter flags exactly the applications whose dossier names
    staff with an attention mark."""
    client = logged_in(make_user(privileged_reset, "reader"))
    owner = privileged_reset.connect("owner", autocommit=True)
    queued = intake(email="queued@example.test", name="Queued Example")
    failed = intake(email="failed@example.test", name="Failed Example")
    PendingAction.objects.filter(subject_id=failed.public_ref).update(status="failed")  # stand-in for the attempt limit
    cancelled = intake(email="cancelled@example.test", name="Cancelled Example")
    PendingAction.objects.filter(subject_id=cancelled.public_ref).update(status="cancelled")
    expired = intake(email="expired@example.test", name="Expired Example")
    owner.execute("UPDATE applications_contactchallenge SET created_at = now() - interval '2 hours',"
                  " expires_at = now() - interval '1 hour' WHERE application_id = %s", [expired.pk])
    paused = intake(email="paused@example.test", name="Paused Example")
    owner.execute("INSERT INTO workflow_automationpause (subject_type, subject_id, reason, actor_ref, created_at)"
                  " VALUES ('application', %s, 'synthetic pause', 'staff:test', now())", [paused.public_ref])
    verified = intake(email="verified@example.test", name="Verified Example")
    challenge = ContactChallenge.objects.get(application=verified)
    from applications import confirmation
    confirmation.confirm(challenge.public_id, SubmissionVersion.objects.get(application=verified).public_id)
    lost = intake(email="lost@example.test", name="Lost Example")
    confirmation.confirm(ContactChallenge.objects.get(application=lost).public_id,
                         SubmissionVersion.objects.get(application=lost).public_id)
    owner.execute("DELETE FROM workflow_pendingaction WHERE kind = 'start_evidence_collection' AND subject_id = %s",
                  [lost.public_ref])  # test setup only: a broken state the dossier must flag

    expected = {
        queued: ("System", False, "The verification message is waiting to be sent"),
        failed: ("Staff", True, "The verification send ended failed and is not retried"),
        cancelled: ("Staff", True, "The verification send ended cancelled and is not retried"),
        expired: ("Applicant", False, "The verification link expired"),
        paused: ("Blocked", True, "The verification message waits: automation is paused"),
        verified: ("Blocked", False, "Start evidence collection is held"),
        lost: ("Staff", True, "Contact is verified but no start-evidence-collection action exists"),
    }
    from applications import staff
    for app, (party, attention, text) in expected.items():
        steps = staff.next_steps(Application.objects.get(pk=app.pk))
        assert steps[-1].party == party and text in steps[-1].text, (app.email, steps)
        assert any(s.attention for s in steps) is attention, app.email
    assert flagged(client) == {a.email for a, (_, attention, _) in expected.items() if attention}
    assert "Automation is paused for this application" in dossier(client, paused)
    assert "Not verified; the verification link expired at" in dossier(client, expired)


def test_s1_12_an_expired_challenge_is_shown_as_expired_in_its_row(privileged_reset):
    client = logged_in(make_user(privileged_reset, "reader"))
    app = intake()
    owner = privileged_reset.connect("owner", autocommit=True)
    owner.execute("UPDATE applications_contactchallenge SET created_at = now() - interval '2 hours',"
                  " expires_at = now() - interval '1 hour'")
    page = dossier(client, app)
    state = re.search(r'<td class="field-state">\s*(?:<p>)?([^<]+)', page).group(1).strip()
    assert state == "expired"


# --- no secret or usable token in any staff page (D-24) --------------------------------------------------------------

def assert_no_secret_in(page, app):
    for challenge in ContactChallenge.objects.filter(application=app):
        link = verification_link(challenge.public_id)
        assert str(challenge.public_id) not in page
        assert link.rsplit("/", 2)[1] not in page and "/confirm/" not in page
    for action in PendingAction.objects.filter(subject_id=app.public_ref):
        assert action.idempotency_key not in page and (action.lease_token is None or str(action.lease_token) not in page)
        if action.input_ref:
            assert action.input_ref not in page
    for secret in (settings.SECRET_KEY, settings.CATALYST_VERIFICATION_KEY, *settings.CATALYST_VERIFICATION_FALLBACK_KEYS):
        assert secret not in page


def test_no_staff_page_shows_a_token_link_key_or_secret(privileged_reset, monkeypatch, settings, caplog):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setitem(runtime._declared, "kind", runtime.process_kind())
    settings.CATALYST_WORKER_POLL_SECONDS = 0.05
    client = logged_in(make_user(privileged_reset, "reader"))
    app = intake()
    call_command("run_worker", exit_when_idle=True, stdout=StringIO())
    action = PendingAction.objects.get()
    message = app.outbound_messages.get()
    # A claimed-looking row, so the lease token and the error text are real values the pages must not show.
    owner = privileged_reset.connect("owner", autocommit=True)
    owner.execute("UPDATE workflow_pendingaction SET status = 'running', lease_token = gen_random_uuid(),"
                  " lease_expires_at = now() + interval '1 hour'")
    action.refresh_from_db()
    assert action.lease_token is not None
    pages = [client.get(url) for url in (
        CHANGELIST, change_url(app), reverse("admin:applications_application_history", args=[app.pk]),
        reverse("admin:workflow_pendingaction_changelist"), reverse("admin:workflow_pendingaction_change", args=[action.pk]),
        reverse("admin:correspondence_outboundmessage_changelist"),
        reverse("admin:correspondence_outboundmessage_change", args=[message.pk]),
    )]
    assert [p.status_code for p in pages] == [200] * len(pages)
    for page in pages:
        assert_no_secret_in(page.content.decode(), app)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert all(v not in text for v in VALID.values())
    assert SubmissionVersion.objects.count() == 1 and ApplicationEvent.objects.count() == 2
