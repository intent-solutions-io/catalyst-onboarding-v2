"""9kg.30 (029 sections 5.2, 7 and 14; D-D4 recommended default): the owner-run `grant_staff_role` command, the
role matrix in accounts.roles, and the append-only grant record. Synthetic accounts only.

- every permission a staff screen checks has a supported grant path (a role in the matrix);
- each role, granted by the command, confers exactly its permitted actions and nothing else;
- the qualification decision is granted only while the authority is configured, and only directly, never by group;
- superusers, unknown roles, drifted groups and a missing approval are refused;
- every grant and revocation is recorded, and the record is append-only for every role;
- no runbook step grants with raw SQL or a shell.
"""

import inspect
import os
import re
import sys
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import Client
from django.urls import reverse
from psycopg import errors

from accounts import roles
from accounts.models import StaffRoleGrant
from applications.models import Application
from assessments import decisions
from tests import support
from tests.test_outbound import p2, staff  # noqa: F401  (fixtures and helpers)

ROOT = Path(__file__).resolve().parent.parent
CATALYST_APPS = ("applications", "workflow", "correspondence", "assessments", "agreements", "provisioning")
STAFF_VIEW_MODULES = ("correspondence.staff_views", "assessments.staff_views", "assessments.decisions",
                      "agreements.staff_views", "provisioning.staff_views", "applications.admin")


def owner_command(*args, expect=0, **env):
    """The command as the owner runs it: a separate process connected as the migration owner (support.manage_as_owner,
    with an explicit environment for the authority setting)."""
    result = support.run(
        [sys.executable, "manage.py", "grant_staff_role", *args],
        CATALYST_DB_NAME=connection.settings_dict["NAME"], CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
        CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"], **env)
    assert result.returncode == expect, (result.stdout, result.stderr)
    return result.stdout + result.stderr


def grant(env, username, role, *flags, **extra):
    return owner_command(username, "--role", role, "--approval-ref", "synthetic D-D4 default", *flags, **extra)


def held_by(user) -> set:
    """Every Catalyst permission the account effectively holds, through groups or directly."""
    user = get_user_model().objects.get(pk=user.pk)  # a fresh instance: Django caches permissions per object
    pairs = Permission.objects.filter(content_type__app_label__in=CATALYST_APPS).values_list("content_type__app_label", "codename")
    return {(app, codename) for app, codename in pairs if user.has_perm(f"{app}.{codename}")}


@pytest.mark.django_db
def test_every_permission_a_staff_screen_checks_has_a_grant_path():
    """Any codename a staff view, the dossier or the decision service names must be carried by some role."""
    known = {codename: app for app, codename in Permission.objects.filter(
        content_type__app_label__in=CATALYST_APPS).values_list("content_type__app_label", "codename")}
    source = "".join(inspect.getsource(__import__(m, fromlist=["x"])) for m in STAFF_VIEW_MODULES)
    checked = {(app, codename) for codename, app in known.items() if re.search(rf'["\'.]{codename}["\']', source)}
    assert len(checked) > 20  # the scan found the screens' permissions, not an empty set
    missing = sorted(checked - roles.every_granted_permission())
    assert missing == [], f"no grant path for {missing}"
    # And the matrix names only permissions that exist (no stale codename can be granted).
    assert sorted(roles.every_granted_permission() - {(app, codename) for codename, app in known.items()}) == []


@pytest.mark.parametrize("role", sorted(roles.GROUP_ROLES))
def test_each_group_role_confers_exactly_its_matrix_set(p2, role):
    spec = roles.GROUP_ROLES[role]
    user = staff(p2, f"holder-{role}")
    assert held_by(user) == set()
    assert "granted" in grant(p2, user.username, role)
    assert held_by(user) == spec.expected
    assert "already holds" in grant(p2, user.username, role) and StaffRoleGrant.objects.filter(user=user).count() == 1
    assert "revoked" in grant(p2, user.username, role, "--revoke")
    assert held_by(user) == set()
    assert list(StaffRoleGrant.objects.filter(user=user).order_by("id").values_list("action", "kind", "target")) == [
        ("grant", "group", spec.group), ("revoke", "group", spec.group)]


def test_the_direct_roles_are_never_carried_by_a_group_and_the_decision_needs_the_authority(p2, settings):
    for spec in roles.DIRECT_ROLES.values():
        assert not Group.objects.filter(permissions__codename=spec.codename).exists()
    decider = staff(p2, "decider-launch")
    out = grant(p2, decider.username, "qualification-decision-maker", expect=1)
    assert "no qualification authority is configured" in out and held_by(decider) == set()
    grant(p2, decider.username, "qualification-decision-maker", CATALYST_QUALIFICATION_AUTHORITY="explicit_permission")
    assert held_by(decider) == {("assessments", "record_qualification_decision")}
    settings.CATALYST_QUALIFICATION_AUTHORITY = "explicit_permission"
    assert decisions.can_decide(get_user_model().objects.get(pk=decider.pk))  # a direct grant: the one that counts
    approver = staff(p2, "approver-launch")
    grant(p2, approver.username, "provisioning-approver")
    assert held_by(approver) == {("provisioning", "approve_provisioning")}
    assert set(StaffRoleGrant.objects.values_list("kind", "target")) == {
        ("permission", "assessments.record_qualification_decision"), ("permission", "provisioning.approve_provisioning")}
    # Revocation needs no authority setting (an owner can always take a grant away).
    grant(p2, decider.username, "qualification-decision-maker", "--revoke")
    assert not decisions.can_decide(get_user_model().objects.get(pk=decider.pk))


def test_superusers_unknown_roles_drifted_groups_and_a_missing_approval_are_refused(p2):
    root = staff(p2, "root-launch", superuser=True)
    assert "superuser" in grant(p2, root.username, "agreement-operator", expect=1)
    user = staff(p2, "plain-launch")
    assert "--approval-ref is required" in owner_command(user.username, "--role", "agreement-operator", expect=1)
    assert "invalid choice" in owner_command(user.username, "--role", "no-such-role", "--approval-ref", "x", expect=2)  # argparse
    assert "no account" in grant(p2, "nobody-launch", "agreement-operator", expect=1)
    # A group whose permissions drifted from the matrix is refused, never used as it stands.
    owner = p2.committed.connect("owner", autocommit=True)
    owner.execute("INSERT INTO auth_group_permissions (group_id, permission_id) SELECT g.id, p.id FROM auth_group g,"
                  " auth_permission p WHERE g.name = 'Agreement operator' AND p.codename = 'manage_agreements'")
    assert "does not carry the role matrix" in grant(p2, user.username, "agreement-operator", expect=1)
    assert held_by(user) == set() and not StaffRoleGrant.objects.exists()
    owner.execute("DELETE FROM auth_group_permissions WHERE group_id = (SELECT id FROM auth_group WHERE name = 'Agreement operator')"
                  " AND permission_id = (SELECT id FROM auth_permission WHERE codename = 'manage_agreements')")
    assert "granted" in grant(p2, user.username, "agreement-operator")
    assert "agreement-decision-maker: group 'Agreement decision-maker'" in owner_command("--list")


def test_the_grant_record_is_append_only_for_every_role_and_names_no_secret(p2):
    user = staff(p2, "recorded-launch")
    grant(p2, user.username, "provisioning-operator")
    record = StaffRoleGrant.objects.get()
    assert record.approval_ref == "synthetic D-D4 default" and record.actor_ref.startswith("owner_command")
    for role in ("app", "owner"):
        conn = p2.committed.connect(role, autocommit=True)
        for statement in ("UPDATE accounts_staffrolegrant SET action = 'revoke' WHERE id = %s",
                          "DELETE FROM accounts_staffrolegrant WHERE id = %s"):
            with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
                conn.execute(statement, [record.pk])
        with pytest.raises((errors.InsufficientPrivilege, errors.RaiseException)):
            conn.execute("TRUNCATE accounts_staffrolegrant")
    app = p2.committed.connect("app", autocommit=True)
    with pytest.raises(errors.InsufficientPrivilege):  # the running application never writes a grant
        app.execute("INSERT INTO accounts_staffrolegrant (user_id, role, kind, target, action, approval_ref, actor_ref)"
                    " VALUES (%s, 'x', 'group', 'x', 'grant', 'x', 'x')", [user.pk])


def test_a_role_granted_by_the_command_opens_exactly_its_screens(p2):
    app = Application.objects.create(email="holder@example.test", email_key="holder@example.test", display_name="Synthetic")
    agreements_page = reverse("agreements_staff:agreements", args=[app.public_ref])
    provisioning_page = reverse("provisioning_staff:provisioning", args=[app.public_ref])
    queue = reverse("correspondence_staff:queue")
    expected = {"agreement-decision-maker": (200, 403, 403), "provisioning-operator": (403, 200, 403),
                "correspondence-operator": (403, 403, 200), "read-only-staff": (403, 403, 403)}
    for role, codes in expected.items():
        user = staff(p2, f"screen-{role}")
        grant(p2, user.username, role)
        client = Client()
        client.force_login(get_user_model().objects.get(pk=user.pk))
        assert tuple(client.get(page).status_code for page in (agreements_page, provisioning_page, queue)) == codes, role


def test_no_runbook_or_design_step_grants_with_raw_sql_or_a_shell():
    """029 section 5.2: every grant path is the command; nothing in the filed documents tells an operator to insert
    into the auth tables or to open a Django shell for a grant."""
    pattern = re.compile(r"INSERT INTO (auth_|accounts_user)|manage\.py shell\b|user_permissions\.add", re.I)
    offenders = [str(p.relative_to(ROOT)) for p in (ROOT / "000-docs").rglob("*.md") if pattern.search(p.read_text())]
    assert offenders == []
