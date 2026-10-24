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


@pytest.fixture(autouse=True)
def matrix_groups_as_migrated(request):
    """Group permissions are not part of the per-test reset; an earlier test that drifted a group (test_decision's
    group-grant check, now cleaned up) must not fail these. Each test here starts from the migrated matrix."""
    if "p2" not in request.fixturenames:
        return
    env = request.getfixturevalue("p2")
    owner = env.committed.connect("owner", autocommit=True)
    for spec in roles.GROUP_ROLES.values():
        owner.execute("DELETE FROM auth_group_permissions WHERE group_id = (SELECT id FROM auth_group WHERE name = %s)", [spec.group])
        for app, codename in sorted(spec.expected):
            owner.execute("INSERT INTO auth_group_permissions (group_id, permission_id) SELECT g.id, p.id FROM auth_group g,"
                          " auth_permission p JOIN django_content_type c ON c.id = p.content_type_id"
                          " WHERE g.name = %s AND c.app_label = %s AND p.codename = %s", [spec.group, app, codename])


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
    """Inverted (QA review of PR #87): every permission any Catalyst model declares, and every codename a staff view,
    the dossier or the decision service names, must be carried by some role; and the matrix names only permissions
    that exist. The declared set is the stronger check: a permission with no role is a permission nobody can hold."""
    from django.apps import apps

    declared = {(label, codename) for label in CATALYST_APPS for model in apps.get_app_config(label).get_models()
                for codename, _ in model._meta.permissions}
    assert len(declared) >= 27  # the Meta.permissions of P2 to P5
    assert sorted(declared - roles.every_granted_permission()) == []
    known = {codename: app for app, codename in Permission.objects.filter(
        content_type__app_label__in=CATALYST_APPS).values_list("content_type__app_label", "codename")}
    source = "".join(inspect.getsource(__import__(m, fromlist=["x"])) for m in STAFF_VIEW_MODULES)
    checked = {(app, codename) for codename, app in known.items() if re.search(rf'["\'.]{codename}["\']', source)}
    assert len(checked) > 20  # the scan found the screens' permissions, not an empty set
    assert sorted(checked - roles.every_granted_permission()) == []
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


def test_a_role_granted_by_the_command_opens_exactly_its_screens(p2, settings):
    settings.CATALYST_QUALIFICATION_AUTHORITY = "explicit_permission"
    app = Application.objects.create(email="holder@example.test", email_key="holder@example.test", display_name="Synthetic")
    pages = (reverse("agreements_staff:agreements", args=[app.public_ref]),
             reverse("provisioning_staff:provisioning", args=[app.public_ref]), reverse("correspondence_staff:queue"),
             reverse("assessments_staff:decision", args=[app.public_ref]))
    expected = {"agreement-decision-maker": (200, 403, 403, 403), "provisioning-operator": (403, 200, 403, 403),
                "correspondence-operator": (403, 403, 200, 403), "read-only-staff": (403, 403, 403, 403),
                "qualification-decision-maker": (403, 403, 403, 200), "provisioning-approver": (403, 200, 403, 403)}
    for role, codes in expected.items():
        user = staff(p2, f"screen-{role}")
        grant(p2, user.username, role, CATALYST_QUALIFICATION_AUTHORITY="explicit_permission")
        client = Client()
        client.force_login(get_user_model().objects.get(pk=user.pk))
        assert tuple(client.get(page).status_code for page in pages) == codes, role


def test_no_runbook_or_design_step_grants_with_raw_sql_or_a_shell():
    """029 section 5.2: every grant path is the command; nothing in the filed documents tells an operator to insert
    into the auth tables or to open a Django shell for a grant."""
    pattern = re.compile(r"INSERT INTO (auth_|accounts_user)|manage\.py shell\b|user_permissions\.add", re.I)
    offenders = [str(p.relative_to(ROOT)) for p in (ROOT / "000-docs").rglob("*.md") if pattern.search(p.read_text())]
    assert offenders == []


def test_every_group_membership_has_a_latest_grant_row(p2):
    """Every command that gives a role writes the same record (accounts.grants): the two account-creating commands
    and the role command; so every membership in the database has a latest `grant` row for its group."""
    env = dict(CATALYST_DB_NAME=connection.settings_dict["NAME"], CATALYST_DB_USER=settings.CATALYST_DB_ROLES["owner"],
               CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"], STAFF_PASSWORD_FOR_TEST="synthetic-password-only-xyz")
    for args in (["add_readonly_staff", "reader-ledger", "--password-env", "STAFF_PASSWORD_FOR_TEST"],
                 ["add_correspondence_staff", "operator-ledger", "--role", "operator", "--password-env", "STAFF_PASSWORD_FOR_TEST"],
                 ["add_correspondence_staff", "reader-ledger", "--role", "template-owner", "--existing"]):
        refused = support.run([sys.executable, "manage.py", *args], **env)
        assert refused.returncode != 0 and "--approval-ref is required" in refused.stderr, args
        result = support.run([sys.executable, "manage.py", *args, "--approval-ref", "synthetic D-30"], **env)
        assert result.returncode == 0, result.stderr
    grant(p2, "operator-ledger", "agreement-operator")
    memberships = list(get_user_model().groups.through.objects.values_list("user_id", "group__name"))
    assert len(memberships) == 4
    for user_id, group_name in memberships:
        latest = StaffRoleGrant.objects.filter(user_id=user_id, kind="group", target=group_name).order_by("-id").first()
        assert latest is not None and latest.action == "grant" and latest.approval_ref.startswith("synthetic"), (user_id, group_name)


def test_9kg_56_the_audit_reports_access_planted_by_raw_owner_sql_and_health_carries_the_counts(p2):
    """`grant_staff_role --audit` is read-only: a membership and a direct permission planted with the owner credential
    by raw SQL, and a recorded grant removed the same way, are each listed and make it exit non-zero; access granted
    by the command is not; the health report carries the counts and never a name; recording through the command
    clears each."""
    import json

    from tests.test_system_health import health

    assert "matches its latest grant record" in owner_command("--audit")  # a clean database
    granted = staff(p2, "granted-by-command")
    grant(p2, granted.username, "correspondence-operator")
    assert "matches its latest grant record" in owner_command("--audit")
    planted = staff(p2, "planted-by-sql", "Correspondence decision-maker")  # raw owner SQL INSERT, no grant record
    owner = p2.committed.connect("owner", autocommit=True)
    owner.execute("INSERT INTO accounts_user_user_permissions (user_id, permission_id) SELECT %s, id FROM auth_permission"
                  " WHERE codename = 'approve_provisioning'", [planted.pk])
    rows_before = StaffRoleGrant.objects.count()
    out = owner_command("--audit", expect=1)
    assert "unrecorded: group 'Correspondence decision-maker' for 'planted-by-sql'" in out
    assert "unrecorded: permission 'provisioning.approve_provisioning' for 'planted-by-sql'" in out
    assert "granted-by-command" not in out and "2 difference(s)" in out
    assert StaffRoleGrant.objects.count() == rows_before  # read-only
    code, report = health()
    assert code == 1 and "staff_roles.role_access_unrecorded" in report["anomalies"]
    assert report["staff_roles"] == {"unrecorded": 2, "recorded_not_held": 0, "anomalies": ["role_access_unrecorded"]}
    assert "planted-by-sql" not in json.dumps(report) and "Correspondence decision-maker" not in json.dumps(report)
    # A recorded grant removed by raw SQL is the other difference.
    owner.execute("DELETE FROM accounts_user_groups WHERE user_id = %s", [granted.pk])
    out = owner_command("--audit", expect=1)
    assert "recorded_not_held: group 'Correspondence operator' for 'granted-by-command'" in out
    assert health()[1]["staff_roles"]["anomalies"] == ["role_access_unrecorded", "role_grant_not_held"]
    # Recording through the command clears each: revoke the planted access (recorded), re-grant the removed one.
    grant(p2, planted.username, "correspondence-decision-maker", "--revoke")
    grant(p2, planted.username, "provisioning-approver", "--revoke")
    grant(p2, granted.username, "correspondence-operator")
    assert "matches its latest grant record" in owner_command("--audit")
    assert health()[1]["staff_roles"] == {"unrecorded": 0, "recorded_not_held": 0, "anomalies": []}
    # Access re-added by raw SQL after a recorded revocation is unrecorded again: the latest record is the revocation.
    owner.execute("INSERT INTO accounts_user_groups (user_id, group_id) SELECT %s, id FROM auth_group WHERE name = %s",
                  [planted.pk, "Correspondence decision-maker"])
    assert "unrecorded: group 'Correspondence decision-maker' for 'planted-by-sql'" in owner_command("--audit", expect=1)


def test_9kg_56_revoke_records_access_a_restore_removed_and_the_audit_names_differences_without_a_remedy(p2):
    """Review of PR #97: access whose latest record is a grant but which is gone (here a restore deactivated the account
    and removed its access) is recorded as ended by `--revoke` instead of a no-op; a difference the command cannot
    correct (a superuser, a group no role maps to) says so; `--audit` takes no other argument."""
    leaver = staff(p2, "leaver")
    grant(p2, leaver.username, "correspondence-operator")
    grant(p2, leaver.username, "provisioning-approver")
    owner = p2.committed.connect("owner", autocommit=True)
    # Test setup only, as the owner: the state a restore leaves (the account deactivated, its access removed).
    owner.execute("UPDATE accounts_user SET is_active = false WHERE id = %s", [leaver.pk])
    owner.execute("DELETE FROM accounts_user_groups WHERE user_id = %s", [leaver.pk])
    owner.execute("DELETE FROM accounts_user_user_permissions WHERE user_id = %s", [leaver.pk])
    out = owner_command("--audit", expect=1)
    assert "recorded_not_held: group 'Correspondence operator' for 'leaver'" in out
    assert "recorded_not_held: permission 'provisioning.approve_provisioning' for 'leaver'" in out
    assert "no command remedy" not in out
    for role in ("correspondence-operator", "provisioning-approver"):
        assert "revoked" in grant(p2, leaver.username, role, "--revoke")
    assert list(StaffRoleGrant.objects.filter(user=leaver).order_by("id").values_list("action", flat=True)) == [
        "grant", "grant", "revoke", "revoke"]
    assert "matches its latest grant record" in owner_command("--audit")
    assert "nothing changed" in grant(p2, leaver.username, "correspondence-operator", "--revoke")  # now a true no-op
    assert StaffRoleGrant.objects.filter(user=leaver).count() == 4
    # Differences the command cannot correct say so on their line.
    staff(p2, "root-planted", "Correspondence operator", superuser=True)
    owner.execute("INSERT INTO auth_group (name) VALUES ('Synthetic unmapped group')")
    try:
        staff(p2, "unmapped-member", "Synthetic unmapped group")
        out = owner_command("--audit", expect=1)
        assert ("unrecorded: group 'Correspondence operator' for 'root-planted' (no command remedy: a superuser holds no"
                " staff role") in out
        assert "unrecorded: group 'Synthetic unmapped group' for 'unmapped-member' (no command remedy: no role maps to" in out
        assert "a superuser" in grant(p2, "root-planted", "correspondence-operator", "--revoke", expect=1)
    finally:
        owner.execute("DELETE FROM accounts_user_groups WHERE group_id = (SELECT id FROM auth_group"
                      " WHERE name = 'Synthetic unmapped group')")
        owner.execute("DELETE FROM auth_group WHERE name = 'Synthetic unmapped group'")
    # --audit is read-only and takes no other argument.
    for extra in (["leaver"], ["--role", "correspondence-operator"], ["--revoke"], ["--list"]):
        assert "--audit is read-only" in owner_command("--audit", *extra, expect=1), extra


def test_9kg_56_the_application_role_reads_everything_the_staff_roles_health_part_reads(p2):
    """Review of PR #97: catalyst_health runs as the application role; the part reads the memberships, the direct
    permissions, their content types and the grant record, and must see a planted difference through that role."""
    from config import system_health

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        assert cursor.fetchone()[0] == settings.CATALYST_DB_ROLES["app"]
    granted = staff(p2, "health-reader-granted")
    grant(p2, granted.username, "correspondence-operator")
    planted = staff(p2, "health-reader-planted", "Template owner")
    owner = p2.committed.connect("owner", autocommit=True)
    owner.execute("INSERT INTO accounts_user_user_permissions (user_id, permission_id) SELECT %s, id FROM auth_permission"
                  " WHERE codename = 'approve_provisioning'", [planted.pk])
    assert system_health.staff_role_health() == {"unrecorded": 2, "recorded_not_held": 0,
                                                 "anomalies": ["role_access_unrecorded"]}
