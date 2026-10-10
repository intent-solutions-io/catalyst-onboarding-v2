"""Database roles and append-only protection (ADR-14, D-17, D-21, D-22; S1-T3), proved through real
connections as each role. The suite itself runs as the restricted application role (tests/conftest.py).

Tests that commit through their own connections use `privileged_reset` (through the `connect` fixture):
the slice tables are emptied after each such test by the test-only owner reset, so the data here is plain
fixed synthetic data, not unique residue. Read-only catalogue tests use the django_db mark (rollback).
Migrations are reversed and reapplied by the migration owner in a child process, never by the test process.
"""

import os
import sys
import uuid

import psycopg
import pytest
from django.conf import settings
from django.db import ProgrammingError, connection, transaction
from psycopg import errors

from tests.support import ROOT, manage_as_owner, run

ROLES = settings.CATALYST_DB_ROLES
PASSWORDS = {
    "owner": os.environ["CATALYST_DB_OWNER_PASSWORD"],
    "app": os.environ["CATALYST_DB_APP_PASSWORD"],
    "retention": os.environ["CATALYST_DB_RETENTION_PASSWORD"],
}
SECRETS = [*PASSWORDS.values(), os.environ["CATALYST_DB_ADMIN_PASSWORD"]]
# Trigger inventory (003 ADR-14): append-only on versions and events (2), no-truncate on versions, events,
# audit and adoptions (4), audit immutability (1), adoption immutability (1).
TRIGGERS = ("catalyst_append_only", "catalyst_no_truncate", "catalyst_audit_immutable", "catalyst_adoption_immutable")
TRIGGER_COUNT = 8
SLICE_TABLES = [
    "applications_application", "applications_submissionversion", "applications_contactchallenge",
    "applications_versionadoption", "applications_applicationevent", "applications_retentionaudit",
    "workflow_pendingaction", "workflow_automationpause", "correspondence_outboundmessage",
]


@pytest.fixture
def connect(privileged_reset):
    return privileged_reset.connect


def new_application(conn, key="applicant@example.test"):
    app_id = conn.execute(
        "INSERT INTO applications_application (public_ref, email, email_key, display_name, stage, next_version_number)"
        " VALUES (gen_random_uuid(), %s, %s, 'Synthetic', 'submitted', 1) RETURNING id",
        [key, key],
    ).fetchone()[0]
    version_id = conn.execute(
        "INSERT INTO applications_submissionversion (application_id, public_id, version_number, origin, submitted_fields)"
        " VALUES (%s, gen_random_uuid(), 1, 'form', '{}') RETURNING id",
        [app_id],
    ).fetchone()[0]
    event_id = conn.execute(
        "INSERT INTO applications_applicationevent (application_id, kind, actor_type, actor_ref, data)"
        " VALUES (%s, 'submission_received', 'applicant', '', '{}') RETURNING id",
        [app_id],
    ).fetchone()[0]
    conn.commit()
    return app_id, version_id, event_id


def new_adoption(conn, key="adopter@example.test"):
    app_id, version_id, _ = new_application(conn, key)
    challenge_id = conn.execute(
        "INSERT INTO applications_contactchallenge (application_id, public_id, email_at_issue, expires_at)"
        " VALUES (%s, gen_random_uuid(), %s, now() + interval '1 hour') RETURNING id", [app_id, key]
    ).fetchone()[0]
    adoption_id = conn.execute(
        "INSERT INTO applications_versionadoption (application_id, submission_version_id, via_challenge_id)"
        " VALUES (%s, %s, %s) RETURNING id", [app_id, version_id, challenge_id],
    ).fetchone()[0]
    conn.commit()
    return adoption_id


def refused(conn, sql, params=(), match="permission denied"):
    with pytest.raises(errors.InsufficientPrivilege, match=match):
        conn.execute(sql, params)
    conn.rollback()


def row_counts(conn):
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in SLICE_TABLES if t != "applications_retentionaudit"}


def trigger_states(conn):
    return conn.execute(
        "SELECT c.relname, t.tgname, t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
        " WHERE t.tgname = ANY(%s) ORDER BY 1, 2", [list(TRIGGERS)]
    ).fetchall()


# --- role attributes and escalation ---------------------------------------------------------------

@pytest.mark.django_db
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
    app.execute("UPDATE accounts_user SET last_login = now() WHERE false")  # permitted column
    app.rollback()
    refused(app, "UPDATE accounts_user SET is_superuser = true WHERE false")
    refused(app, "UPDATE accounts_user SET is_staff = true WHERE false")
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

@pytest.mark.parametrize("reason", [None, "", "   ", "too short"], ids=["unset", "empty", "blank", "short"])
def test_retention_delete_requires_a_stated_reason(connect, reason):
    _, _, event_id = new_application(connect("app"))
    retention = connect("retention")
    if reason is not None:
        retention.execute("SELECT set_config('catalyst.retention_reason', %s, true)", [reason])
    refused(retention, "DELETE FROM applications_applicationevent WHERE id = %s", [event_id], match="append-only")


def test_retention_can_delete_an_unadopted_submission_version_with_audit(connect):
    app_id, version_id, _ = new_application(connect("app"))
    retention = connect("retention")
    retention.execute("SET LOCAL catalyst.retention_reason = 'synthetic retention of a version'")
    assert retention.execute("DELETE FROM applications_submissionversion WHERE id = %s", [version_id]).rowcount == 1
    retention.commit()
    audited = retention.execute(
        "SELECT application_id FROM applications_retentionaudit WHERE row_id = %s AND table_name = 'applications_submissionversion'",
        [version_id],
    ).fetchone()
    assert audited == (app_id,)


def test_retention_delete_with_a_reason_is_audited_and_the_audit_is_immutable(connect):
    _, _, event_id = new_application(connect("app"))
    retention = connect("retention")
    retention.execute("SET LOCAL catalyst.retention_reason = 'synthetic retention test'")
    assert retention.execute("DELETE FROM applications_applicationevent WHERE id = %s", [event_id]).rowcount == 1
    retention.commit()
    row = retention.execute(
        "SELECT actor, table_name, reason, application_id, length(row_sha256) FROM applications_retentionaudit"
        " WHERE row_id = %s AND table_name = 'applications_applicationevent'",
        [event_id],
    ).fetchone()
    assert row[:3] == (ROLES["retention"], "applications_applicationevent", "synthetic retention test")
    assert row[3] is not None and row[4] == 64  # which application, and a digest of the removed row
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


@pytest.mark.django_db
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
import django
django.setup()
from django.db import transaction
from applications.models import Application, SubmissionVersion
with transaction.atomic():
    app = Application.objects.create(email="orm@example.test", email_key="orm@example.test", display_name="Synthetic")
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


def test_orm_through_the_application_role_in_a_fresh_process(privileged_reset):
    # A fresh Django process configured with the application role's credentials, against the test database.
    result = run([sys.executable, "-c", ORM_PROBE], CATALYST_DB_USER=ROLES["app"], CATALYST_DB_PASSWORD=PASSWORDS["app"],
                 CATALYST_DB_NAME=connection.settings_dict["NAME"])
    assert result.returncode == 0, result.stderr
    assert "ordinary operations: ok" in result.stdout
    assert "protected update: refused: ProgrammingError permission denied for table applications_submissionversion" in result.stdout


@pytest.mark.django_db
def test_this_test_process_runs_as_the_application_role():
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_user")
        assert cursor.fetchone()[0] == ROLES["app"]


# --- migration behaviour (the owner, in a child process) ------------------------------------------------------

def test_history_protection_migrations_reverse_and_reapply_and_keep_data(connect):
    app = connect("app")
    app_id, version_id, _ = new_application(app)
    adoption_id = new_adoption(app)
    owner = connect("owner", autocommit=True)
    count = lambda: len(trigger_states(owner))
    assert count() == TRIGGER_COUNT
    manage_as_owner("migrate", "applications", "0002", "--verbosity", "0")
    assert count() == 6  # 0003 reversed: adoption triggers gone, 0002 intact
    manage_as_owner("migrate", "applications", "0001", "--verbosity", "0")
    assert count() == 0
    manage_as_owner("migrate", "applications", "0003", "--verbosity", "0")
    assert count() == TRIGGER_COUNT
    assert {state for _, _, state in trigger_states(owner)} == {"O"}
    assert owner.execute("SELECT count(*) FROM applications_submissionversion WHERE id = %s AND application_id = %s",
                         [version_id, app_id]).fetchone()[0] == 1
    assert owner.execute("SELECT count(*) FROM applications_versionadoption WHERE id = %s", [adoption_id]).fetchone()[0] == 1


def test_grant_migrations_reverse_and_reapply(connect):
    owner = connect("owner", autocommit=True)
    app_can = lambda table, privilege: owner.execute(
        "SELECT has_table_privilege(%s, %s, %s)", [ROLES["app"], table, privilege]).fetchone()[0]
    assert app_can("workflow_pendingaction", "INSERT")
    manage_as_owner("migrate", "workflow", "0001", "--verbosity", "0")
    assert not app_can("workflow_pendingaction", "INSERT") and not app_can("workflow_pendingaction", "SELECT")
    manage_as_owner("migrate", "workflow", "0002", "--verbosity", "0")
    assert app_can("workflow_pendingaction", "INSERT")


def test_the_owner_still_runs_management_commands(privileged_reset):
    # The separate, authorized administration path: management commands as the owner keep working.
    assert "[X] 0003_protect_version_adoption" in manage_as_owner("showmigrations", "applications").stdout
    manage_as_owner("migrate", "--verbosity", "0")


# --- the diagnostic role check (catalyst.E002) ------------------------------------------------------------

def check_database(**env):
    return run([sys.executable, "manage.py", "check", "--database", "default"], **env)


def test_a_superuser_connection_is_refused():
    # The one child process that receives administrator credentials, explicitly, to prove refusal.
    result = check_database(CATALYST_DB_USER=os.environ["CATALYST_DB_ADMIN_USER"],
                            CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_ADMIN_PASSWORD"])
    assert result.returncode != 0
    assert "catalyst.E002" in result.stderr and "superuser" in result.stderr


def test_a_web_process_connecting_as_the_owner_is_refused():
    result = check_database(CATALYST_PROCESS="web")
    assert result.returncode != 0
    assert "catalyst.E002" in result.stderr and "not the application role" in result.stderr


def test_a_worker_process_connecting_as_the_retention_role_is_refused():
    result = check_database(CATALYST_PROCESS="worker", CATALYST_DB_USER=ROLES["retention"],
                            CATALYST_DB_PASSWORD=PASSWORDS["retention"])
    assert result.returncode != 0
    assert "catalyst.E002" in result.stderr and "not the application role" in result.stderr


def test_a_worker_process_connecting_as_the_application_role_passes():
    result = check_database(CATALYST_PROCESS="worker", CATALYST_DB_USER=ROLES["app"], CATALYST_DB_PASSWORD=PASSWORDS["app"])
    assert result.returncode == 0, result.stderr


def test_a_web_process_connecting_as_the_application_role_passes():
    result = check_database(CATALYST_PROCESS="web", CATALYST_DB_USER=ROLES["app"], CATALYST_DB_PASSWORD=PASSWORDS["app"])
    assert result.returncode == 0, result.stderr


# --- runtime enforcement on the real WSGI path (config.runtime) ----------------------------------------------

WSGI_PROBE = """
import config.wsgi
from django.db import connection
connection.ensure_connection()
with connection.cursor() as cursor:
    cursor.execute("SELECT current_user")
    print("connected as", cursor.fetchone()[0])
"""


def wsgi_connect(role_key=None, **env):
    if role_key == "admin":
        env.update(CATALYST_DB_USER=os.environ["CATALYST_DB_ADMIN_USER"], CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_ADMIN_PASSWORD"])
    elif role_key:
        env.update(CATALYST_DB_USER=ROLES[role_key], CATALYST_DB_PASSWORD=PASSWORDS[role_key])
    result = run([sys.executable, "-c", WSGI_PROBE], **env)
    output = result.stdout + result.stderr
    assert not [s for s in SECRETS if s in output], "a password value appeared in the output"
    return result


def test_the_web_process_connects_as_the_application_role():
    result = wsgi_connect("app")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"connected as {ROLES['app']}"


@pytest.mark.parametrize(("role_key", "reason"), [
    ("owner", "not the application role"),
    ("retention", "not the application role"),
    ("admin", "connects as superuser"),
])
def test_the_web_process_refuses_a_privileged_connection(role_key, reason):
    result = wsgi_connect(role_key)
    assert result.returncode != 0
    assert "ImproperlyConfigured: Catalyst refuses the database connection 'default'" in result.stderr
    assert reason in result.stderr
    assert "connected as" not in result.stdout


def test_a_stale_management_value_does_not_exempt_the_web_process():
    result = wsgi_connect("owner", CATALYST_PROCESS="management")
    assert result.returncode != 0
    assert "web process connects as" in result.stderr and "not the application role" in result.stderr


def test_child_processes_do_not_receive_the_administrator_login():
    result = run([sys.executable, "-c", "import os; print(sorted(k for k in os.environ if k.startswith('CATALYST_DB_ADMIN')))"])
    assert result.stdout.strip() == "[]"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE applications_application SET email = 'x@example.test' WHERE false",
        "UPDATE applications_application SET email_key = 'x@example.test' WHERE false",
        "UPDATE applications_application SET public_ref = gen_random_uuid() WHERE false",
        "UPDATE applications_contactchallenge SET expires_at = now() WHERE false",
        "UPDATE workflow_pendingaction SET idempotency_key = 'x' WHERE false",
        "UPDATE workflow_pendingaction SET max_attempts = 99 WHERE false",
        "UPDATE correspondence_outboundmessage SET recipient = 'x@example.test' WHERE false",
    ],
    ids=["app-email", "app-email-key", "app-public-ref", "challenge-expiry", "action-key", "action-max-attempts", "outbound-recipient"],
)
def test_application_role_updates_only_the_columns_its_services_need(connect, sql):
    refused(connect("app"), sql)


def test_application_role_cannot_switch_off_triggers_for_its_session(connect):
    refused(connect("app"), "SET session_replication_role = replica", match="permission denied")


def test_application_role_can_claim_with_skip_locked(connect):
    app = connect("app")
    key = f"sv:{uuid.uuid4()}"
    app.execute(
        "INSERT INTO workflow_pendingaction (kind, subject_type, subject_id, input_ref, idempotency_key, status, attempts,"
        " max_attempts, last_error) VALUES ('send_verification', 'application', %s, '', %s, 'queued', 0, 3, '')",
        [uuid.uuid4(), key],
    )
    app.commit()
    claimed = app.execute(
        "SELECT id FROM workflow_pendingaction WHERE idempotency_key = %s FOR UPDATE SKIP LOCKED", [key]
    ).fetchone()
    assert claimed is not None
    other = connect("app")
    assert other.execute(
        "SELECT id FROM workflow_pendingaction WHERE idempotency_key = %s FOR UPDATE SKIP LOCKED", [key]
    ).fetchone() is None  # locked by the first claimant: skipped, not waited for
    app.rollback()
    other.rollback()


# --- protected adoptions (D-22) ------------------------------------------------------------------------------

@pytest.mark.parametrize("sql", [
    "UPDATE applications_versionadoption SET adopted_at = now() WHERE id = %s",
    "DELETE FROM applications_versionadoption WHERE id = %s",
], ids=["update", "delete"])
def test_application_role_cannot_change_an_adoption(connect, sql):
    app = connect("app")
    refused(app, sql, [new_adoption(app)])


@pytest.mark.parametrize("role_key", ["app", "retention"])
def test_no_ordinary_role_can_truncate_or_delete_adoptions(connect, role_key):
    adoption_id = new_adoption(connect("app"))
    conn = connect(role_key)
    if role_key == "retention":  # no retention path for adoptions (POL-10 open), even with a stated reason
        conn.execute("SET LOCAL catalyst.retention_reason = 'synthetic retention of an adoption'")
    refused(conn, "DELETE FROM applications_versionadoption WHERE id = %s", [adoption_id])
    refused(conn, "TRUNCATE applications_versionadoption")


@pytest.mark.parametrize("sql", [
    "UPDATE applications_versionadoption SET adopted_at = now() WHERE id = %s",
    "DELETE FROM applications_versionadoption WHERE id = %s",
    "TRUNCATE applications_versionadoption CASCADE",
], ids=["update", "delete", "truncate"])
def test_the_trigger_refuses_adoption_changes_even_for_the_migration_owner(connect, sql):
    adoption_id = new_adoption(connect("app"))
    refused(connect("owner"), sql, [adoption_id] if "%s" in sql else (), match="append-only")


def test_adoption_grants_are_unchanged(connect):
    owner = connect("owner", autocommit=True)
    privileges = owner.execute(
        "SELECT has_table_privilege(%(app)s, t, 'SELECT'), has_table_privilege(%(app)s, t, 'INSERT'),"
        " has_any_column_privilege(%(app)s, t, 'UPDATE'), has_table_privilege(%(app)s, t, 'DELETE'),"
        " has_table_privilege(%(retention)s, t, 'SELECT'), has_table_privilege(%(retention)s, t, 'DELETE')"
        " FROM (SELECT 'public.applications_versionadoption'::regclass AS t) x",
        {"app": ROLES["app"], "retention": ROLES["retention"]},
    ).fetchone()
    assert privileges == (True, True, False, False, False, False)


@pytest.mark.django_db
def test_the_orm_cannot_rewrite_or_remove_an_adoption():
    from datetime import timedelta

    from django.utils import timezone

    from applications.models import Application, ContactChallenge, SubmissionVersion, VersionAdoption

    app = Application.objects.create(email="orm@example.test", email_key="orm@example.test", display_name="Synthetic")
    version = SubmissionVersion.objects.create(application=app, version_number=1, origin="form", submitted_fields={})
    challenge = ContactChallenge.objects.create(application=app, email_at_issue=app.email,
                                                expires_at=timezone.now() + timedelta(hours=1))
    adoption = VersionAdoption.objects.create(application=app, submission_version=version, via_challenge=challenge)
    for change in (lambda: VersionAdoption.objects.filter(pk=adoption.pk).update(adopted_at=timezone.now()),
                   lambda: VersionAdoption.objects.filter(pk=adoption.pk).delete()):
        with pytest.raises(ProgrammingError, match="permission denied for table applications_versionadoption"):
            with transaction.atomic():
                change()


# --- the privileged reset itself (D-21) ----------------------------------------------------------------------

def test_a_committed_write_is_removed_by_an_explicit_reset(privileged_reset):
    app = privileged_reset.connect("app")
    new_application(app)
    new_adoption(app)
    assert row_counts(privileged_reset.connect("app"))["applications_versionadoption"] == 1  # committed, seen elsewhere
    privileged_reset.reset()
    assert set(row_counts(privileged_reset.connect("app")).values()) == {0}


def test_the_next_test_starts_empty_with_identities_restarted(privileged_reset):
    # Runs after the test above (file order) and after every committing test before it.
    app = privileged_reset.connect("app")
    assert set(row_counts(app).values()) == {0}
    app_id, version_id, event_id = new_application(app)
    assert (app_id, version_id, event_id) == (1, 1, 1)  # RESTART IDENTITY


def test_protection_holds_after_a_reset(privileged_reset):
    privileged_reset.reset()
    app = privileged_reset.connect("app")
    _, version_id, event_id = new_application(app)
    adoption_id = new_adoption(app)
    owner = privileged_reset.connect("owner")
    assert {state for _, _, state in trigger_states(owner)} == {"O"} and len(trigger_states(owner)) == TRIGGER_COUNT
    refused(owner, "UPDATE applications_submissionversion SET origin = 'form' WHERE id = %s", [version_id], match="append-only")
    refused(owner, "DELETE FROM applications_applicationevent WHERE id = %s", [event_id], match="append-only")
    refused(owner, "DELETE FROM applications_versionadoption WHERE id = %s", [adoption_id], match="append-only")
    for table in ("applications_submissionversion", "applications_applicationevent",
                  "applications_retentionaudit", "applications_versionadoption"):
        refused(owner, f"TRUNCATE {table} CASCADE", match="append-only")
    refused(app, "UPDATE applications_submissionversion SET origin = 'form' WHERE id = %s", [version_id])


IDENTITY_PROBE = """
import tests.conftest as harness


def test_reset_against_a_database_without_this_runs_identity(privileged_reset):
    harness.RUN_IDENTITY["marker"] = "catalyst-test-run:some-other-run"
"""


def test_a_reset_against_the_wrong_identity_fails_the_run(tmp_path):
    # A child pytest run with its own test database; its reset must refuse and the run must not pass.
    # The harness is loaded as a conftest (not with -p) so its django_db_setup overrides pytest-django's.
    (tmp_path / "conftest.py").write_text("from tests.conftest import *  # noqa: F403\n")
    probe = tmp_path / "test_identity_probe.py"
    probe.write_text(IDENTITY_PROBE)
    result = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(probe)],
                 timeout=120, CATALYST_TEST_DB_SUFFIX=f"probe{os.getpid()}")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "1 passed, 1 error" in result.stdout
    assert "does not carry this test run's identity marker" in result.stdout
