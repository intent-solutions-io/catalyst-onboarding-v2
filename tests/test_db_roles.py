"""Database roles and append-only protection (ADR-14, D-17; S1-T3), proved through real connections as
each role. Ordinary operations run as the restricted application role, not the owner.

These tests commit through their own connections (the application, retention and owner roles), so each
uses unique synthetic data; the disposable test database is dropped at the end of the session. Django's
transactional test cleanup is not used, because it truncates tables and the protected tables refuse TRUNCATE.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connection
from psycopg import errors

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parent.parent
ROLES = settings.CATALYST_DB_ROLES
PASSWORDS = {
    "owner": os.environ["CATALYST_DB_PASSWORD"],
    "app": os.environ["CATALYST_DB_APP_PASSWORD"],
    "retention": os.environ["CATALYST_DB_RETENTION_PASSWORD"],
}


@pytest.fixture
def connect():
    opened = []

    def _connect(role_key, autocommit=False):
        conn = psycopg.connect(
            host=os.environ["CATALYST_DB_HOST"], port=os.environ.get("CATALYST_DB_PORT", "5432"),
            dbname=connection.settings_dict["NAME"], user=ROLES[role_key], password=PASSWORDS[role_key],
            autocommit=autocommit,
        )
        opened.append(conn)
        return conn

    yield _connect
    for conn in opened:
        conn.close()


def new_application(conn):
    key = f"{uuid.uuid4().hex}@example.test"
    app_id = conn.execute(
        "INSERT INTO applications_application (public_ref, email, email_key, display_name, stage, next_version_number)"
        " VALUES (%s, %s, %s, 'Synthetic', 'submitted', 1) RETURNING id",
        [uuid.uuid4(), key, key],
    ).fetchone()[0]
    version_id = conn.execute(
        "INSERT INTO applications_submissionversion (application_id, public_id, version_number, origin, submitted_fields)"
        " VALUES (%s, %s, 1, 'form', '{}') RETURNING id",
        [app_id, uuid.uuid4()],
    ).fetchone()[0]
    event_id = conn.execute(
        "INSERT INTO applications_applicationevent (application_id, kind, actor_type, actor_ref, data)"
        " VALUES (%s, 'submission_received', 'applicant', '', '{}') RETURNING id",
        [app_id],
    ).fetchone()[0]
    conn.commit()
    return app_id, version_id, event_id


def refused(conn, sql, params=(), match="permission denied"):
    with pytest.raises(errors.InsufficientPrivilege, match=match):
        conn.execute(sql, params)
    conn.rollback()


# --- role attributes and escalation ---------------------------------------------------------------

def test_no_role_is_privileged_and_none_is_a_member_of_another():
    names = list(ROLES.values())
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname = ANY(%s)", [names]
        )
        rows = {r[0]: r[1:] for r in cursor.fetchall()}
        cursor.execute(
            "SELECT count(*) FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member JOIN pg_roles g ON g.oid = m.roleid"
            " WHERE r.rolname = ANY(%s) AND g.rolname = ANY(%s)", [names, names]
        )
        memberships = cursor.fetchone()[0]
    assert set(rows) == set(names)
    for name, (superuser, createrole, createdb, bypassrls) in rows.items():
        assert not superuser and not createrole and not bypassrls
        assert createdb == (name == ROLES["owner"])  # CREATEDB only for the owner, for test databases
    assert memberships == 0


@pytest.mark.parametrize("target", ["owner", "retention"])
def test_application_role_cannot_assume_a_privileged_role(connect, target):
    app = connect("app")
    refused(app, f'SET ROLE "{ROLES[target]}"', match="permission denied to set role")
    assert app.execute("SELECT pg_has_role(current_user, %s, 'USAGE')", [ROLES[target]]).fetchone()[0] is False


def test_application_role_cannot_disable_triggers_or_grant_itself_privileges(connect):
    app = connect("app")
    with pytest.raises(errors.InsufficientPrivilege, match="must be owner"):
        app.execute("ALTER TABLE applications_submissionversion DISABLE TRIGGER catalyst_append_only")
    app.rollback()
    # PostgreSQL answers a GRANT on someone else's table with a warning, not an error; what matters is
    # that no privilege is gained.
    app.execute(f'GRANT UPDATE, DELETE ON applications_submissionversion TO "{ROLES["app"]}"')
    app.commit()
    gained = app.execute(
        "SELECT has_table_privilege(current_user, 'applications_submissionversion', 'UPDATE'),"
        " has_table_privilege(current_user, 'applications_submissionversion', 'DELETE')"
    ).fetchone()
    assert gained == (False, False)


# --- ordinary operations through the application role ----------------------------------------------

def test_application_role_performs_ordinary_operations(connect):
    app = connect("app")
    app_id, version_id, _ = new_application(app)
    app.execute("UPDATE applications_application SET stage = 'contact_verified', next_version_number = 2 WHERE id = %s", [app_id])
    challenge_id = app.execute(
        "INSERT INTO applications_contactchallenge (application_id, public_id, email_at_issue, expires_at)"
        " VALUES (%s, %s, 'x@example.test', now() + interval '1 hour') RETURNING id", [app_id, uuid.uuid4()]
    ).fetchone()[0]
    app.execute("UPDATE applications_contactchallenge SET used_at = now() WHERE id = %s", [challenge_id])
    app.execute(
        "INSERT INTO applications_versionadoption (application_id, submission_version_id, via_challenge_id) VALUES (%s, %s, %s)",
        [app_id, version_id, challenge_id],
    )
    action_id = app.execute(
        "INSERT INTO workflow_pendingaction (kind, subject_type, subject_id, input_ref, idempotency_key, status, attempts,"
        " max_attempts, last_error) VALUES ('send_verification', 'application', %s, '', %s, 'queued', 0, 3, '') RETURNING id",
        [uuid.uuid4(), f"sv:{uuid.uuid4()}"],
    ).fetchone()[0]
    app.execute("UPDATE workflow_pendingaction SET status = 'done', completed_at = now() WHERE id = %s", [action_id])
    subject = uuid.uuid4()
    app.execute("INSERT INTO workflow_automationpause (subject_type, subject_id, reason, actor_ref) VALUES ('application', %s, 'r', 'staff:1')", [subject])
    app.execute("DELETE FROM workflow_automationpause WHERE subject_id = %s", [subject])
    app.execute(
        "INSERT INTO correspondence_outboundmessage (application_id, pending_action_id, attempt_number, template_key,"
        " template_version, recipient, message_id, status) VALUES (%s, %s, 1, 'verification', '1', 'x@example.test', '', 'accepted')",
        [app_id, action_id],
    )
    app.commit()


def test_application_role_reads_but_cannot_change_staff_accounts_beyond_last_login(connect):
    app = connect("app")
    app.execute("SELECT count(*) FROM accounts_user").fetchone()
    refused(app, "INSERT INTO accounts_user (password, is_superuser, username, first_name, last_name, email, is_staff,"
                 " is_active, date_joined) VALUES ('x', true, 'mallory', '', '', '', true, true, now())")
    refused(app, "DELETE FROM accounts_user")


# --- append-only protection ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE applications_submissionversion SET submitted_fields = '{\"x\": 1}' WHERE id = %s",
        "DELETE FROM applications_submissionversion WHERE id = %s",
    ],
    ids=["update-version", "delete-version"],
)
def test_application_role_cannot_change_submission_versions(connect, sql):
    app = connect("app")
    _, version_id, _ = new_application(app)
    refused(app, sql, [version_id])


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE applications_applicationevent SET kind = 'forged' WHERE id = %s",
        "DELETE FROM applications_applicationevent WHERE id = %s",
    ],
    ids=["update-event", "delete-event"],
)
def test_application_role_cannot_change_history_events(connect, sql):
    app = connect("app")
    _, _, event_id = new_application(app)
    refused(app, sql, [event_id])


@pytest.mark.parametrize(
    "sql",
    [
        "TRUNCATE applications_applicationevent",
        "DELETE FROM workflow_pendingaction",
        "SELECT * FROM applications_retentionaudit",
        "INSERT INTO applications_retentionaudit (actor, table_name, row_id, reason) VALUES ('x', 'y', 1, 'z')",
    ],
    ids=["truncate-events", "delete-pending-actions", "read-audit", "write-audit"],
)
def test_application_role_lacks_privileges_it_does_not_need(connect, sql):
    refused(connect("app"), sql)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE applications_submissionversion SET origin = 'form' WHERE id = %s",
        "DELETE FROM applications_applicationevent WHERE id = %s",
    ],
    ids=["update", "delete"],
)
def test_the_trigger_refuses_even_the_migration_owner(connect, sql):
    app = connect("app")
    _, version_id, event_id = new_application(app)
    owner = connect("owner")
    target = version_id if "submissionversion" in sql else event_id
    refused(owner, sql, [target], match="append-only")


def test_the_trigger_refuses_truncate_even_for_the_migration_owner(connect):
    refused(connect("owner"), "TRUNCATE applications_submissionversion CASCADE", match="append-only")


def test_stated_limitation_the_owner_can_disable_the_trigger(connect):
    # ADR-14 keeps this limitation explicit: protection holds only while no process runs as the owner.
    owner = connect("owner")
    owner.execute("ALTER TABLE applications_applicationevent DISABLE TRIGGER catalyst_append_only")
    owner.rollback()


# --- audited retention ---------------------------------------------------------------------------------

def test_retention_delete_requires_a_reason(connect):
    _, _, event_id = new_application(connect("app"))
    refused(connect("retention"), "DELETE FROM applications_applicationevent WHERE id = %s", [event_id], match="append-only")


def test_retention_delete_with_a_reason_is_audited_and_the_audit_is_immutable(connect):
    _, _, event_id = new_application(connect("app"))
    retention = connect("retention")
    retention.execute("SET LOCAL catalyst.retention_reason = 'synthetic retention test'")
    assert retention.execute("DELETE FROM applications_applicationevent WHERE id = %s", [event_id]).rowcount == 1
    retention.commit()
    row = retention.execute(
        "SELECT actor, table_name, reason FROM applications_retentionaudit WHERE row_id = %s AND table_name = 'applications_applicationevent'",
        [event_id],
    ).fetchone()
    assert row == (ROLES["retention"], "applications_applicationevent", "synthetic retention test")
    retention.commit()
    owner = connect("owner")
    refused(owner, "UPDATE applications_retentionaudit SET reason = 'rewritten' WHERE row_id = %s", [event_id], match="append-only")
    refused(owner, "DELETE FROM applications_retentionaudit WHERE row_id = %s", [event_id], match="append-only")


def test_retention_role_cannot_update_history(connect):
    _, version_id, _ = new_application(connect("app"))
    retention = connect("retention")
    retention.execute("SET LOCAL catalyst.retention_reason = 'x'")
    with pytest.raises(errors.InsufficientPrivilege, match="permission denied"):
        retention.execute("UPDATE applications_submissionversion SET origin = 'form' WHERE id = %s", [version_id])


def test_a_temporary_table_cannot_divert_the_audit_record(connect):
    _, _, event_id = new_application(connect("app"))
    retention = connect("retention")
    retention.execute(
        "CREATE TEMP TABLE applications_retentionaudit (id bigserial, at timestamptz default now(), actor text,"
        " table_name text, row_id bigint, reason text)"
    )
    retention.execute("SET LOCAL catalyst.retention_reason = 'shadow attempt'")
    retention.execute("DELETE FROM applications_applicationevent WHERE id = %s", [event_id])
    retention.commit()
    assert retention.execute("SELECT count(*) FROM pg_temp.applications_retentionaudit").fetchone()[0] == 0
    audited = retention.execute(
        "SELECT reason FROM public.applications_retentionaudit WHERE row_id = %s AND table_name = 'applications_applicationevent'",
        [event_id],
    ).fetchone()
    assert audited == ("shadow attempt",)


def test_privileged_trigger_function_has_a_fixed_search_path_and_no_public_execute():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner),"
            " has_function_privilege(%s, p.oid, 'EXECUTE')"
            " FROM pg_proc p WHERE p.oid = 'public.catalyst_history_append_only()'::regprocedure",
            [ROLES["app"]],
        )
        security_definer, config, owner, app_can_execute = cursor.fetchone()
    assert security_definer is True
    assert "search_path=public, pg_temp" in config
    assert owner == ROLES["owner"]
    assert app_can_execute is False


# --- the ORM through the application role ---------------------------------------------------------------

ORM_PROBE = """
import django, uuid
django.setup()
from django.db import transaction
from applications.models import Application, SubmissionVersion
key = uuid.uuid4().hex + "@example.test"
with transaction.atomic():
    app = Application.objects.create(email=key, email_key=key, display_name="Synthetic")
    version = SubmissionVersion.objects.create(application=app, version_number=1, origin="form", submitted_fields={})
    Application.objects.filter(pk=app.pk).update(stage="contact_verified")
print("ordinary operations: ok")
try:
    with transaction.atomic():
        SubmissionVersion.objects.filter(pk=version.pk).update(submitted_fields={"x": 1})
    print("protected update: allowed")
except Exception as exc:
    print("protected update: refused:", type(exc).__name__, str(exc).splitlines()[0])
"""


def test_orm_through_the_application_role():
    # A fresh Django process configured with the application role's credentials, against the test database.
    env = {**os.environ, "CATALYST_DB_USER": ROLES["app"], "CATALYST_DB_PASSWORD": PASSWORDS["app"],
           "CATALYST_DB_NAME": connection.settings_dict["NAME"], "DJANGO_SETTINGS_MODULE": "config.settings"}
    result = subprocess.run([sys.executable, "-c", ORM_PROBE], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "ordinary operations: ok" in result.stdout
    assert "protected update: refused: ProgrammingError permission denied for table applications_submissionversion" in result.stdout


# --- migration behaviour ----------------------------------------------------------------------------------

def test_history_protection_migration_reverses_and_reapplies():
    def protected():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname IN ('catalyst_append_only', 'catalyst_no_truncate', 'catalyst_audit_immutable')"
            )
            return cursor.fetchone()[0]

    # append-only on 2 protected tables, no-truncate on those 2 plus the audit table, audit immutability: 6
    assert protected() == 6
    call_command("migrate", "applications", "0001", verbosity=0)
    assert protected() == 0
    call_command("migrate", "applications", "0002", verbosity=0)
    assert protected() == 6


# --- start-up role check (catalyst.E002) -------------------------------------------------------------------

def check_database(**env):
    full = {**os.environ, **env}
    return subprocess.run([sys.executable, "manage.py", "check", "--database", "default"], cwd=ROOT,
                          env=full, capture_output=True, text=True, timeout=60)


def test_a_superuser_connection_is_refused():
    result = check_database(CATALYST_DB_USER=os.environ["CATALYST_DB_ADMIN_USER"],
                            CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_ADMIN_PASSWORD"])
    assert result.returncode != 0
    assert "catalyst.E002" in result.stderr and "superuser" in result.stderr


def test_a_web_process_connecting_as_the_owner_is_refused():
    result = check_database(CATALYST_PROCESS="web")
    assert result.returncode != 0
    assert "catalyst.E002" in result.stderr and "migration owner" in result.stderr


def test_a_web_process_connecting_as_the_application_role_passes():
    result = check_database(CATALYST_PROCESS="web", CATALYST_DB_USER=ROLES["app"], CATALYST_DB_PASSWORD=PASSWORDS["app"])
    assert result.returncode == 0, result.stderr
