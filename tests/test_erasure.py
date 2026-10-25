"""9kg.32: the authorized erasure path (029 section 6.2; council 030 Q3, D-51; ADR-14 pattern).

Proved through real database connections as each role: the erasure runs as the retention login through the one
security-definer function, every protective trigger admits only the audited tombstone change, and the durable record
in the effect journal is written as an intent before the transaction and completed after it. The registry ships
undecided, so most tests install a decided synthetic copy (`decided`). Tests commit through their own connections and
rely on the privileged reset (tests/conftest.py).
"""

import hashlib
import json
import os
import re
import sys
import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from psycopg import errors, sql

from applications.models import Application, ApplicationEvent, ContactChallenge, Invitation, SubmissionVersion
from config import backup
from correspondence.models import InboundMessage, OutboundMessage
from erasure import catalog, record, registry, service
from tests.support import manage_as_owner, run
from tests.test_backup_commands import run_backup
from tests.test_closure import active_member, cl  # noqa: F401  (fixture chain and helper)
from tests.test_outbound import staff
from tests.test_provisioning import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, c, complete, d, ev, g, grant, h, k, nda, of, p2, pv, run_worker, tls,
)
from workflow import journal
from workflow.models import AutomationPause, PendingAction

ROLES = settings.CATALYST_DB_ROLES
KEY = "synthetic-erasure-key-for-tests-only-0123456789abcdef"  # gitleaks:allow (synthetic; never a real key)
AUTHORITY, REASON = "pol-10:synthetic-decision", "subject-request"
DECIDED = {
    **{name: {"treatment": registry.ANONYMIZE, "retention": "synthetic-p90d"} for name in registry.SUBJECT_CLASSES},
    "signed_documents": {"treatment": registry.RETAIN, "retention": "synthetic-p7y"},
    "provider_copies": {"treatment": registry.MANUAL_HANDOFF, "retention": "synthetic-p30d"},
    "erasure_record": {"treatment": registry.RETAIN, "retention": "synthetic-oldest-backup-plus-p30d"},
    "effect_journal": {"treatment": registry.RETAIN, "retention": "synthetic-oldest-backup-plus-p30d"},
}
REFUSED = (errors.InsufficientPrivilege, errors.RaiseException)


class Crash(Exception):
    """An interruption: the operator's terminal closed, the process was killed."""


def raises_sqlstate(code, conn, statement, params):
    with pytest.raises(errors.Error) as raised:
        conn.execute(statement, params)
    conn.rollback()
    assert raised.value.sqlstate == code, raised.value.sqlstate


@pytest.fixture
def decided(monkeypatch, settings):
    """A decided synthetic registry and a synthetic erasure key (the shipped registry is undecided: refuse)."""
    monkeypatch.setattr(registry, "REGISTRY", DECIDED)
    monkeypatch.setattr(registry, "REPLAY_BUILT", True)  # what 9kg.25 will flip; until then nothing real proceeds
    settings.CATALYST_ERASURE_KEY = KEY
    return DECIDED


def subject(email="grace@example.test", name="Grace Example", stage="withdrawn"):
    """A small synthetic subject through the application role: identity, a version, an event with a note, a
    challenge, a finished send with its attempt, and an inbound reply with an attachment."""
    app = Application.objects.create(email=email, email_key=email, display_name=name, stage=stage)
    SubmissionVersion.objects.create(application=app, version_number=1, origin="form",
                                     submitted_fields={"name": name, "email": email, "reason": f"{name} applies"})
    ApplicationEvent.objects.create(application=app, kind="staff_note", actor_type="staff", actor_ref="user:1",
                                    data={"note": f"Spoke with {name}"})
    ContactChallenge.objects.create(application=app, email_at_issue=email, expires_at=timezone.now() + timedelta(hours=1))
    action = PendingAction.objects.create(kind="send_verification", subject_type="application", subject_id=app.public_ref,
                                          idempotency_key=f"sv:{uuid.uuid4()}", status="done")
    OutboundMessage.objects.create(application=app, pending_action=action, attempt_number=1, template_key="verification",
                                   template_version="1", recipient=email, message_id="", status="accepted")
    InboundMessage.objects.create(
        mailbox_ref="synthetic-mailbox", message_id_header=f"<r-{uuid.uuid4().hex}@{email.split('@')[1]}>",
        from_address=f"{name} <{email}>", from_normalized=email, size=10, original_sha256=uuid.uuid4().hex * 2,
        derived_text=f"Regards, {name}", attachments=[{"name": f"{name}.pdf", "size": 10}], application=app)
    return app


def erase(committed, ref, **kwargs):
    return service.erase(committed.connect("retention"), str(ref), kwargs.get("authority", AUTHORITY),
                         kwargs.get("reason", REASON))


def audits(committed, subject_ref=None) -> list:
    """The erasure audit rows, read as the retention role (the application role has no privilege on the table)."""
    conn = committed.connect("retention", autocommit=True)
    rows = conn.execute("SELECT subject_ref, authority, reason_code, actor, classes FROM erasure_erasureaudit"
                        " WHERE %s::uuid IS NULL OR subject_ref = %s::uuid ORDER BY id",
                        [subject_ref, subject_ref]).fetchall()
    return rows


def erasure_entries():
    return [e for e in journal.read() if e.kind.startswith("erasure_")]


def owner_scan(owner, *markers) -> dict:
    """{table: rows whose text holds a marker}: every public table but the staff sessions, read as the owner."""
    hits = {}
    for (table,) in owner.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'django_session'"):
        for marker in markers:
            n = owner.execute(sql.SQL("SELECT count(*) FROM public.{} t WHERE t::text ILIKE %s").format(sql.Identifier(table)),
                              [f"%{marker}%"]).fetchone()[0]
            if n:
                hits[f"{table}:{marker}"] = n
    return hits


def schema_columns(cursor) -> dict:
    """{table: columns} of every ordinary table in public, from the catalog (information_schema shows a role only what
    it may use, and the suite runs as the application role)."""
    cursor.execute("SELECT c.relname, a.attname FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
                   " JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r'"
                   " AND a.attnum > 0 AND NOT a.attisdropped")
    out = {}
    for table, column in cursor.fetchall():
        out.setdefault(table, set()).add(column)
    return out


def digests(owner) -> dict:
    out = {}
    for (table,) in owner.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'django_session'"):
        out[table] = owner.execute(sql.SQL("SELECT md5(coalesce(string_agg(t::text, '|' ORDER BY t::text), '')) FROM public.{} t")
                                   .format(sql.Identifier(table))).fetchone()[0]
    return out


# --- the registry: undecided means refuse ---------------------------------------------------------------------------

def test_9kg_32_the_registry_ships_undecided_and_refuses_the_erasure_and_a_real_backup(privileged_reset, settings):
    assert registry.REGISTRY.keys() == DECIDED.keys()
    assert all(row == {"treatment": "undecided", "retention": "undecided"} for row in registry.REGISTRY.values())
    assert registry.REPLAY_BUILT is False  # 9kg.25 flips it with the replay
    assert len(registry.problems()) == 2 * len(registry.REGISTRY) + 1
    assert registry.problems(DECIDED) == ["replay:not_built"]  # decided rows still cannot open live backups
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(registry, "REPLAY_BUILT", True)
        assert registry.problems(DECIDED) == []
        assert registry.problems({**DECIDED, "signed_documents": {"treatment": "anonymize", "retention": "p1y"}}) == [
            "signed_documents.treatment:unsupported"]  # `retain` or `destroy_key` (9kg.34), never `anonymize`
        for stranded in registry.KEY_SELECTED_CLASSES:  # their rows are found only by the real key
            assert registry.problems({**DECIDED, stranded: {"treatment": "retain", "retention": "p1y"}}) == [
                "application_identity:retains_key_selected_classes"], stranded
    settings.CATALYST_ERASURE_KEY = KEY
    app = subject()
    with pytest.raises(service.Refused) as refused:
        erase(privileged_reset, app.public_ref)
    assert refused.value.code == "registry_undecided" and "application_identity.treatment:undecided" in refused.value.detail
    assert erasure_entries() == [] and audits(privileged_reset) == []
    assert Application.objects.get(pk=app.pk).email == "grace@example.test"  # nothing changed
    # A backup of real data is refused while anything is undecided; a synthetic environment backs up as before.
    settings.CATALYST_ENV = "production"
    with pytest.raises(backup.BackupError, match="erasure registry has undecided values"):
        backup.backup(None, None, None, "set")  # refused before the connection or any directory is touched
    from config import system_health
    assert system_health.backup_health()["anomalies"] == ["registry_blocked"]
    settings.CATALYST_ENV = "test"
    backup.refuse_real_backup_while_undecided()
    assert system_health.backup_health()["anomalies"] == []


# --- the map ---------------------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_9kg_32_the_erasure_map_classifies_every_table_and_column_of_the_schema():
    from django.db import connection

    with connection.cursor() as cursor:
        schema = schema_columns(cursor)
    mapped = {table: set(spec.columns()) for table, spec in catalog.TABLES.items()}
    assert sorted(set(schema) ^ set(mapped)) == []  # every table, and no stale one
    assert {t: sorted(schema[t] ^ mapped[t]) for t in schema if schema[t] != mapped[t]} == {}  # every column
    for table, spec in catalog.TABLES.items():
        declared = [*spec.staff.split(), *spec.secret.split(), *spec.other.split(), *(spec.subject or {})]
        assert len(declared) == len(set(declared)), table  # a column is classified once
        assert bool(spec.subject) == bool(spec.selector), table  # subject columns need a selector, and only they
    # The rows the reviews named: the event's transaction marker is non-personal and frozen on the erasure path; the
    # new tables of PRs #88, #89 and #91 are in the map with their personal columns.
    assert catalog.TABLES["applications_applicationevent"].columns()["created_txid"] == "non_personal"
    assert catalog.subject_columns("workflow_automationpause") == {"reason": catalog.S("pauses")}
    assert set(catalog.subject_columns("applications_memberagreementonfile")) == {"email_key"}
    assert set(catalog.subject_columns("applications_invitation")) == {"email_key", "note"}
    assert catalog.classes_in_map() == set(registry.SUBJECT_CLASSES)  # every class has columns; every column a class
    for table, columns in catalog.subject_columns().items():
        for column, spec in columns.items():
            assert spec.tombstone in (catalog.TEXT, catalog.EMPTY, catalog.OBJECT, catalog.ARRAY, catalog.OBJECT_OR_NULL,
                                      catalog.KEY, catalog.LOCAL_PART, catalog.NOTES, catalog.DELETE), (table, column)
            assert spec.source == "" or spec.source in schema[table]


@pytest.mark.django_db
def test_9kg_32_the_branch_is_in_every_guarded_function_once_and_the_installed_functions_match_the_map():
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [ROLES["retention"]])
        retention = cursor.fetchone()[0]
        cursor.execute("SELECT p.proname, p.prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
                       " WHERE n.nspname = 'public' AND p.proname LIKE 'catalyst\\_%%'")
        sources = dict(cursor.fetchall())
        existing = schema_columns(cursor)
        cursor.execute("SELECT c.relname, t.tgname, p.proname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
                       " JOIN pg_proc p ON p.oid = t.tgfoid WHERE NOT t.tgisinternal")
        triggers = {(table, name): function for table, name, function in cursor.fetchall()}
    for name in (*catalog.GUARDED_FUNCTIONS, "catalyst_erasable_append_only"):
        assert sources[name].count(catalog.branch(retention)) == 1, name
        assert len(catalog.BRANCH_PATTERN.findall(sources[name])) == 1, name
    with_branch = {name for name, src in sources.items() if catalog.BRANCH_BEGIN in src}
    assert with_branch == {*catalog.GUARDED_FUNCTIONS, "catalyst_erasable_append_only"}
    # The strict refusal, the adoption record, every no-truncate trigger and the pause DELETE guard stay as they were.
    assert catalog.BRANCH_BEGIN not in sources["catalyst_append_only_strict"]
    assert catalog.BRANCH_BEGIN not in sources["catalyst_pause_resume_guard"]
    assert triggers[("applications_versionadoption", "catalyst_adoption_immutable")] == "catalyst_append_only_strict"
    assert {f for (_, n), f in triggers.items() if n == "catalyst_no_truncate"} == {"catalyst_append_only_strict"}
    for table, trigger in catalog.ERASABLE_STRICT:
        assert triggers[(table, trigger)] == "catalyst_erasable_append_only"
    # The installed generated functions are exactly what the map generates for this schema (a new subject column needs
    # a migration that reinstalls them).
    for name, generated in (("catalyst_erasure_admits", catalog.checker_sql(retention, existing)),
                            ("catalyst_erase", catalog.erase_sql(retention, existing))):
        assert sources[name] == generated.split("$fn$")[1], name
    # Derived from the catalog, not a list (PR #99 review): every UPDATE trigger on a table with subject columns calls a
    # function that carries the branch, so no trigger there can refuse the audited path unseen.
    with connection.cursor() as cursor:
        cursor.execute("SELECT c.relname, t.tgname, p.proname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid"
                       " JOIN pg_proc p ON p.oid = t.tgfoid WHERE NOT t.tgisinternal AND (t.tgtype::int & 16) <> 0")
        updates = cursor.fetchall()
    subject_tables = {t for t, cols in catalog.subject_columns().items() if any(s.tombstone != catalog.DELETE for s in cols.values())}
    uncovered = [(t, g, f) for t, g, f in updates if t in subject_tables and f not in with_branch]
    assert uncovered == [] and {t for t, _, _ in updates} & subject_tables


@pytest.mark.django_db
def test_9kg_32_only_the_retention_role_may_execute_the_erase_function_and_nobody_but_the_owner_the_checker():
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT r.role, has_function_privilege(r.role, 'public.catalyst_erase(uuid, text, text, text[])', 'EXECUTE'),"
                       " has_function_privilege(r.role, 'public.catalyst_erasure_admits(text, jsonb, jsonb)', 'EXECUTE')"
                       " FROM unnest(%s::text[]) AS r(role)",
                       [[ROLES["app"], ROLES["fetcher"], ROLES["backup"], ROLES["retention"]]])
        rights = {role: (erase_fn, checker) for role, erase_fn, checker in cursor.fetchall()}
        cursor.execute("SELECT has_function_privilege('public', 'public.catalyst_erase(uuid, text, text, text[])', 'EXECUTE')")
        assert cursor.fetchone()[0] is False
        cursor.execute("SELECT has_table_privilege(%s, 'erasure_erasureaudit', 'INSERT'), "
                       "has_table_privilege(%s, 'erasure_erasureaudit', 'SELECT')", [ROLES["retention"], ROLES["app"]])
        assert cursor.fetchone() == (False, False)
    assert rights == {ROLES["app"]: (False, False), ROLES["fetcher"]: (False, False), ROLES["backup"]: (False, False),
                      ROLES["retention"]: (True, False)}


def test_9kg_32_the_function_refuses_every_login_but_the_retention_role(privileged_reset):
    app = subject()
    raises_sqlstate("CE007", privileged_reset.connect("owner"), "SELECT public.catalyst_erase(%s, %s, %s, %s)",
                    [app.public_ref, AUTHORITY, REASON, ["submissions"]])
    with pytest.raises(errors.InsufficientPrivilege):
        privileged_reset.connect("app").execute("SELECT public.catalyst_erase(%s, %s, %s, %s)",
                                                [app.public_ref, AUTHORITY, REASON, ["submissions"]])
    retention = privileged_reset.connect("retention")
    for args in ((AUTHORITY, "free text reason", ["submissions"]), (AUTHORITY, REASON, []),
                 (AUTHORITY, REASON, ["not_a_class"])):
        raises_sqlstate("CE006", retention, "SELECT public.catalyst_erase(%s, %s, %s, %s)", [app.public_ref, *args])
    assert Application.objects.get(pk=app.pk).email == "grace@example.test"


# --- the trigger branch admits exactly the audited tombstone change ------------------------------------------------

PROBE = "catalyst_probe_erasure"  # a stand-in caller with the erase function's shape; created and dropped per test


@pytest.fixture
def probe(privileged_reset):
    owner = privileged_reset.connect("owner", autocommit=True)
    owner.execute(f"CREATE FUNCTION public.{PROBE}(statement text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER"
                  " SET search_path = public, pg_temp AS $$ BEGIN EXECUTE statement; END $$")
    owner.execute(f"REVOKE ALL ON FUNCTION public.{PROBE}(text) FROM PUBLIC")
    owner.execute(sql.SQL("GRANT EXECUTE ON FUNCTION public.{}(text) TO {}").format(
        sql.Identifier(PROBE), sql.Identifier(ROLES["retention"])))
    yield privileged_reset
    owner.execute(f"DROP FUNCTION IF EXISTS public.{PROBE}(text)")


AUDIT_ROW = ("INSERT INTO erasure_erasureaudit (subject_ref, authority, reason_code, classes)"
             " VALUES (gen_random_uuid(), 'test:authority', 'test-reason', '[]')")


def call(conn, *statements):
    for statement in statements:
        conn.execute(f"SELECT public.{PROBE}(%s)", [statement])


def test_9kg_32_the_branch_admits_a_tombstone_only_with_an_audit_row_of_this_transaction_and_the_retention_login(probe):
    app = subject()
    version = SubmissionVersion.objects.get(application=app)
    event = ApplicationEvent.objects.get(application=app, kind="staff_note")
    retention = probe.connect("retention")
    tombstone = f"UPDATE applications_submissionversion SET submitted_fields = '{{}}' WHERE id = {version.pk}"
    with pytest.raises(REFUSED, match="append-only"):  # no audit row in this transaction
        call(retention, tombstone)
    retention.rollback()
    call(retention, AUDIT_ROW)
    retention.commit()
    with pytest.raises(REFUSED, match="append-only"):  # an audit row of an earlier transaction does not count
        call(retention, tombstone)
    retention.rollback()
    for change in (f"UPDATE applications_submissionversion SET submitted_fields = '{{\"x\": 1}}' WHERE id = {version.pk}",
                   f"UPDATE applications_submissionversion SET origin = 'repeat_after_verification' WHERE id = {version.pk}",
                   f"UPDATE applications_submissionversion SET submitted_fields = '{{}}', received_at = now() WHERE id = {version.pk}",
                   f"UPDATE applications_applicationevent SET data = '{{}}', created_txid = 1 WHERE id = {event.pk}",
                   f"DELETE FROM applications_submissionversion WHERE id = {version.pk}"):
        with pytest.raises(REFUSED):  # not a tombstone, outside the allow-list (the txid included), or a deletion
            call(retention, AUDIT_ROW, change)
        retention.rollback()
    call(retention, AUDIT_ROW, tombstone,
         f"UPDATE applications_applicationevent SET data = '{{}}' WHERE id = {event.pk}")
    retention.commit()
    assert SubmissionVersion.objects.get(pk=version.pk).submitted_fields == {}
    assert ApplicationEvent.objects.get(pk=event.pk).data == {}
    # The owner, even with an audit row it wrote itself, is refused: the branch needs the retention login.
    owner = probe.connect("owner")
    owner.execute(AUDIT_ROW)
    with pytest.raises(REFUSED, match="append-only"):
        owner.execute("UPDATE applications_applicationevent SET data = '{\"x\": 1}' WHERE id = %s", [event.pk])
    owner.rollback()
    # The application role's ordinary updates of guarded tables are untouched (the branch never calls the checker).
    OutboundMessage.objects.filter(application=app).update(status="accepted_by_server")


def test_9kg_32_the_adoption_record_and_the_pause_delete_guard_stay_closed_on_the_audited_path(probe):
    owner = probe.connect("owner", autocommit=True)
    app = subject(stage="withdrawn")
    version = SubmissionVersion.objects.get(application=app)
    challenge = ContactChallenge.objects.get(application=app)
    adoption = owner.execute("INSERT INTO applications_versionadoption (application_id, submission_version_id,"
                             " via_challenge_id) VALUES (%s, %s, %s) RETURNING id", [app.pk, version.pk, challenge.pk]).fetchone()[0]
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason="Paused for Grace Example",
                                   actor_ref="user:1")
    retention = probe.connect("retention")
    with pytest.raises(REFUSED, match="append-only"):
        call(retention, AUDIT_ROW, f"UPDATE applications_versionadoption SET adopted_at = adopted_at WHERE id = {adoption}")
    retention.rollback()
    call(retention, AUDIT_ROW, f"DELETE FROM workflow_automationpause WHERE subject_id = '{app.public_ref}'")
    with pytest.raises(REFUSED, match="automation pause"):  # the deferred guard, at commit: erasure never lifts a pause
        retention.commit()
    call(retention, AUDIT_ROW, f"UPDATE workflow_automationpause SET reason = '[erased]' WHERE subject_id = '{app.public_ref}'")
    retention.commit()
    assert AutomationPause.objects.get(subject_id=app.public_ref).reason == "[erased]"  # anonymized, still in force


# --- the erasure ------------------------------------------------------------------------------------------------------

def test_9kg_32_an_open_subject_or_work_in_flight_is_refused_before_any_record_is_written(privileged_reset, decided):
    open_app = subject("open@example.test", "Opal Example", stage="evidence")
    with pytest.raises(service.Refused, match="subject_open"):
        erase(privileged_reset, open_app.public_ref)
    busy = subject("busy@example.test", "Bea Example")
    PendingAction.objects.create(kind="remind", subject_type="application", subject_id=busy.public_ref,
                                 idempotency_key=f"remind:{uuid.uuid4()}", status="queued")
    with pytest.raises(service.Refused, match="subject_has_open_work"):
        erase(privileged_reset, busy.public_ref)
    with pytest.raises(service.Refused, match="unknown_subject"):
        erase(privileged_reset, uuid.uuid4())
    with pytest.raises(service.Refused, match="malformed_request"):
        erase(privileged_reset, busy.public_ref, reason="Because Busy Example asked")  # a code, never free text
    assert erasure_entries() == [] and audits(privileged_reset) == []
    with pytest.raises(service.Refused, match="not_the_retention_role"):
        service.erase(privileged_reset.connect("owner"), str(busy.public_ref), AUTHORITY, REASON)


def test_9kg_32_the_subject_is_gone_from_every_table_view_job_and_derivative_and_the_custody_copy_is_reported_retained(
        cl, monkeypatch, decided):
    from provisioning import closure

    app, request = active_member(cl, monkeypatch)
    closure.close_application(app.pk, cl.closer, "closed", "Programme ended for this applicant")
    run_worker()
    for kind in ("sessions", "app_credentials"):
        row = closure.AccessRevocation.objects.get(request=request, kind=kind)
        closure.accept_revocation_exception(row.pk, cl.approver, "No documented session revocation exists")
    from django.db.models.functions import Now
    PendingAction.objects.filter(kind=closure.REVOKE, status="queued").update(due_at=Now())
    run_worker()
    assert closure.revocation_complete(request)
    owner = cl.committed.connect("owner", autocommit=True)
    # Records the journey does not make, for the same person: an invitation, the member-on-file record, mail from the
    # address that was never associated, a staff note on a pause, a free-text audit reason, the throttle bucket and
    # the admin log line.
    owner.execute("INSERT INTO applications_invitation (public_id, email_key, issued_by, note, expires_at)"
                  " VALUES (gen_random_uuid(), 'ada@example.test', 'owner_command', 'Invited Ada Example', now() + interval '1 day')")
    owner.execute("INSERT INTO applications_memberagreementonfile (public_id, email_key, covers, completion_verified, recorded_by)"
                  " VALUES (gen_random_uuid(), 'ada@example.test', '{\"nda\": \"v1\"}', true, 'owner_command')")
    InboundMessage.objects.create(mailbox_ref="synthetic-mailbox", message_id_header="<late@example.test>",
                                  from_address="Ada Example <ada@example.test>", from_normalized="ada@example.test",
                                  size=10, original_sha256=uuid.uuid4().hex * 2, derived_text="Ada Example writes again",
                                  attachments=[{"name": "ada.example.pdf", "size": 10}])
    AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref,
                                   reason="Held while Ada Example travels", actor_ref=f"user:{cl.closer.pk}")
    owner.execute("INSERT INTO applications_retentionaudit (actor, table_name, row_id, application_id, row_sha256, reason)"
                  " VALUES ('catalyst_retention', 'applications_applicationevent', 1, %s, repeat('a', 64),"
                  " 'removed a note about ada@example.test')", [app.pk])
    bucket = hashlib.sha256(b"intake-address:ada@example.test").hexdigest()  # intake made it: a digest of the key
    assert owner.execute("SELECT count(*) FROM accounts_requestthrottle WHERE key = %s", [bucket]).fetchone()[0] == 1
    owner.execute("INSERT INTO django_admin_log (action_time, object_id, object_repr, action_flag, change_message,"
                  " content_type_id, user_id) SELECT now(), %s, 'Ada Example <ada@example.test>', 2, 'Viewed Ada Example',"
                  " c.id, %s FROM django_content_type c WHERE c.app_label = 'applications' AND c.model = 'application'",
                  [str(app.pk), cl.closer.pk])
    markers = ("ada@example.test", "Ada Example", "ada.example")
    before = owner_scan(owner, *markers)
    assert len(before) >= 10, before  # the person is in many tables before

    # The protective sweeps of the setup links are due later; erasure waits for work in flight, so let them run now.
    PendingAction.objects.filter(subject_id=app.public_ref, status="queued").update(due_at=Now())
    run_worker()
    assert not PendingAction.objects.filter(subject_id=app.public_ref, status__in=("queued", "running", "held", "uncertain"))
    outcome = erase(cl.committed, app.public_ref)
    assert outcome.status == "erased" and outcome.changed > 20
    assert {"documenso", "mail_sent", "mail_inbox", "mail_host_mailbox"} <= set(outcome.handoffs)
    # Not erased here, and said so: the signed PDFs in custody (registry row signed_documents; 9kg.34 destroys keys).
    assert outcome.retained == ["custody_documents"]
    assert record.fold(journal.read(), KEY.encode())[str(app.public_ref)].retained == {"custody_documents"}
    assert owner_scan(owner, *markers) == {}  # gone from every table: views, jobs, attachments, derivatives
    assert owner.execute("SELECT count(*) FROM accounts_requestthrottle WHERE key = %s", [bucket]).fetchone()[0] == 0
    erased = Application.objects.get(pk=app.pk)
    assert (erased.email, erased.display_name, erased.email_key) == ("[erased]", "[erased]", f"erased:{app.public_ref}")
    assert erased.stage == "closed" and AutomationPause.objects.filter(subject_id=app.public_ref).exists()
    # Staff views: every screen of the application, the admin and the queue.
    viewer = staff(cl, "erasure-viewer")  # every permission, granted directly (screens refuse a superuser by design)
    owner.execute("INSERT INTO accounts_user_user_permissions (user_id, permission_id) SELECT %s, id FROM auth_permission",
                  [viewer.pk])
    browser = Client()
    browser.force_login(viewer)
    ref = app.public_ref
    for path in (reverse("correspondence_staff:application", args=[ref]), reverse("correspondence_staff:applications"),
                 reverse("correspondence_staff:queue"), reverse("assessments_staff:evidence", args=[ref]),
                 reverse("assessments_staff:decision", args=[ref]), reverse("agreements_staff:agreements", args=[ref]),
                 reverse("provisioning_staff:provisioning", args=[ref]), f"/staff/applications/application/{app.pk}/change/",
                 "/staff/applications/application/", "/staff/workflow/pendingaction/", "/staff/workflow/automationpause/",
                 "/staff/correspondence/outboundmessage/"):
        page = browser.get(path)
        assert page.status_code == 200, path
        assert not any(m.lower() in page.content.decode().lower() for m in markers), path
    # Jobs: nothing for the subject is open, and a worker pass sends nothing to anyone.
    assert not PendingAction.objects.filter(subject_id=ref, status__in=("queued", "running", "held", "uncertain")).exists()
    from django.core import mail
    sent = len(mail.outbox)
    run_worker()
    assert len(mail.outbox) == sent
    # The durable record holds no address, name or numeric id.
    with open(os.path.join(journal.directory(), journal.FILE), "rb") as handle:
        raw = handle.read()
    assert not any(m.encode().lower() in raw.lower() for m in markers)


def test_9kg_32_a_second_erasure_is_harmless(privileged_reset, decided):
    app = subject()
    first = erase(privileged_reset, app.public_ref)
    assert first.status == "erased"
    owner = privileged_reset.connect("owner", autocommit=True)
    state, entries, written = digests(owner), erasure_entries(), audits(privileged_reset)
    again = erase(privileged_reset, app.public_ref)
    assert again.status == "nothing_to_erase" and again.changed == 0
    assert digests(owner) == state and erasure_entries() == entries and audits(privileged_reset) == written
    assert len(written) == 1
    # The function itself is harmless too, called directly a second time.
    retention = privileged_reset.connect("retention")
    result = retention.execute("SELECT public.catalyst_erase(%s, %s, %s, %s)",
                               [app.public_ref, AUTHORITY, REASON, registry.anonymized_classes(DECIDED)]).fetchone()[0]
    retention.commit()
    assert result["status"] == "nothing_to_erase" and digests(owner) == state


def test_9kg_32_an_interrupted_erasure_resumes(privileged_reset, decided, monkeypatch):
    # 1. Interrupted after the intent, before the transaction: the intent is open, nothing changed; a re-run finishes.
    one = subject("one@example.test", "Hedy Example")
    real_call = service._call

    def crash_before_commit(conn, *args, commit):
        if commit:
            raise Crash("the operator's terminal closed")
        return real_call(conn, *args, commit=commit)
    monkeypatch.setattr(service, "_call", crash_before_commit)
    with pytest.raises(Crash):
        erase(privileged_reset, one.public_ref)
    state = record.fold(journal.read(), KEY.encode())[str(one.public_ref)]
    assert state.open and Application.objects.get(pk=one.pk).email == "one@example.test"
    monkeypatch.setattr(service, "_call", real_call)
    resumed = erase(privileged_reset, one.public_ref)
    assert resumed.status == "erased" and resumed.resumed and resumed.handoffs == ["mail_inbox", "mail_sent"]
    assert Application.objects.get(pk=one.pk).email == "[erased]"
    # 2. The transaction fails after the function ran: all or nothing; a re-run finishes.
    two = subject("two@example.test", "Joan Example")

    def fail_inside(conn, *args, commit):
        if commit:
            conn.execute("SELECT public.catalyst_erase(%s, %s, %s, %s)", list(args[:3]) + [list(args[3])])
            conn.close()  # the connection is lost before the commit: the server rolls the transaction back
            raise ConnectionError("the database went away before the commit")
        return real_call(conn, *args, commit=commit)
    monkeypatch.setattr(service, "_call", fail_inside)
    with pytest.raises(ConnectionError):
        erase(privileged_reset, two.public_ref)
    assert Application.objects.get(pk=two.pk).email == "two@example.test"  # rolled back with the connection
    assert audits(privileged_reset, two.public_ref) == []
    monkeypatch.setattr(service, "_call", real_call)
    assert erase(privileged_reset, two.public_ref).status == "erased"
    # 3. Interrupted after the commit, before the completion: the re-run finds it done and completes the record,
    #    changing nothing and writing no second audit row.
    three = subject("three@example.test", "Mary Example")
    real_complete = record.append_complete
    monkeypatch.setattr(record, "append_complete", lambda *a, **k: (_ for _ in ()).throw(record.RecordError("unwritable")))
    with pytest.raises(service.Refused, match="record_unwritable_after_commit"):
        erase(privileged_reset, three.public_ref)
    assert Application.objects.get(pk=three.pk).email == "[erased]" and record.fold(journal.read(), KEY.encode())[str(three.public_ref)].open
    monkeypatch.setattr(record, "append_complete", real_complete)
    done = erase(privileged_reset, three.public_ref)
    assert done.status == "already_erased" and done.resumed and done.handoffs == ["mail_inbox", "mail_sent"]
    assert len(audits(privileged_reset, three.public_ref)) == 1
    folded = record.fold(journal.read(), KEY.encode())
    assert all(folded[str(s.public_ref)].erased and not folded[str(s.public_ref)].open for s in (one, two, three))


def test_9kg_32_the_record_is_written_before_the_transaction_and_is_sensitive_and_minimal(privileged_reset, decided, tmp_path):
    app = subject()
    order = []
    real_intent, real_call = record.append_intent, service._call

    def intent(*args, **kwargs):
        order.append("intent")
        return real_intent(*args, **kwargs)

    def call_(conn, *args, commit):
        order.append("commit" if commit else "dry_run")
        return real_call(conn, *args, commit=commit)
    import unittest.mock as mock
    with mock.patch.object(record, "append_intent", intent), mock.patch.object(service, "_call", call_):
        outcome = erase(privileged_reset, app.public_ref)
    assert order == ["dry_run", "intent", "commit"]
    entries = erasure_entries()
    assert [e.kind for e in entries] == ["erasure_intent", "erasure_complete"]
    for entry in entries:
        assert entry.key == f"erasure:{app.public_ref}"  # a public reference, never a numeric id
        assert set(entry.data) <= journal.KINDS[entry.kind]
    intent_data = entries[0].data
    assert intent_data["subject"] == record.subject_hash("grace@example.test", KEY.encode())  # keyed: HMAC of the key
    assert intent_data["subject"] != hashlib.sha256(b"grace@example.test").hexdigest()
    assert intent_data["subject"] != record.subject_hash("grace@example.test", b"another-synthetic-key-0123456789abcdef")
    assert intent_data["key_id"] == record.key_id(KEY.encode()) and KEY not in json.dumps([e.data for e in entries])
    assert intent_data["classes"] == registry.anonymized_classes(DECIDED) and intent_data["authority"] == AUTHORITY
    assert {k: v for k, v in entries[1].data.items() if k != "mac"} == {
        "subject": intent_data["subject"], "key_id": intent_data["key_id"], "status": "erased", "changed": outcome.changed,
        "phase": "done"}
    for entry in entries:  # each entry carries a mac under the erasure key over its kind, key and data
        assert entry.data["mac"] == record.entry_mac(entry.kind, entry.key, entry.data, KEY.encode())
    with open(os.path.join(journal.directory(), journal.FILE), "rb") as handle:
        assert b"grace" not in handle.read().lower()
    assert all(v != app.pk for e in entries for v in e.data.values())  # no numeric id anywhere
    with pytest.raises(journal.JournalError):  # the journal refuses an address in an erasure entry
        journal.check_content("erasure_handoff", "erasure:x", {"provider": "ada@example.test"})
    # The audit row in the database holds codes and the public reference only, no keyed hash and no free text.
    assert audits(privileged_reset) == [(app.public_ref, AUTHORITY, REASON, ROLES["retention"],
                                         registry.anonymized_classes(DECIDED))]
    # The record is outside the backup: a backup set never carries the keyed hash (nor the erased address).
    out = tmp_path / "sets"
    out.mkdir(mode=0o700)
    storage = tmp_path / "custody"
    storage.mkdir(mode=0o700)
    privileged_reset.release()
    made = run_backup(out, storage, "after-erasure")
    assert made.returncode == 0, made.stderr
    blobs = b"".join(p.read_bytes() for p in (out / "after-erasure").rglob("*") if p.is_file())
    assert intent_data["subject"].encode() not in blobs and b"grace@example.test" not in blobs


def test_9kg_32_the_record_verifies_against_the_out_of_band_head_and_an_emptied_store_is_refused(privileged_reset, decided):
    app = subject()
    journal.append("model_usage", "usage:2026-10-24", {"requests": 1})  # the journal holds other effects already
    head_before = record.head_string()
    assert record.verify("none")["erased"] == 0  # no erasure yet: `none` is the right head
    outcome = erase(privileged_reset, app.public_ref)
    report = record.verify(outcome.journal_head)
    assert report == {"journal_head": outcome.journal_head, "erased": 1, "open": [], "handoffs_outstanding": 2, "retained": 0}
    with pytest.raises(record.RecordError, match="journal_mismatch"):
        record.verify("none")  # erasures exist: the head kept out of band is required
    with pytest.raises(record.RecordError, match="bad_head"):
        record.verify("not-a-head")
    assert record.verify(head_before)["erased"] == 1  # an older head is still in the chain
    path = os.path.join(journal.directory(), journal.FILE)
    saved = open(path, "rb").read()
    open(path, "wb").close()  # the store emptied (or replaced by an empty one)
    with pytest.raises(record.RecordError, match="journal_mismatch"):
        record.verify(outcome.journal_head)
    lines = saved.splitlines(keepends=True)
    open(path, "wb").write(b"".join(lines[:-1]) + lines[-1].replace(b'"erased"', b'"edited"'))  # one entry altered
    with pytest.raises(record.RecordError, match="chain_broken"):
        record.verify(outcome.journal_head)
    open(path, "wb").write(saved)
    call_command("catalyst_erasure_record", "--expect-head", outcome.journal_head)
    with pytest.raises(SystemExit):
        call_command("catalyst_erasure_record", "--expect-head", "none")


def test_9kg_32_provider_handoffs_are_recorded_with_their_completion_date(privileged_reset, decided):
    app = subject()
    with pytest.raises(service.Refused, match="not_erased"):
        service.handoff(str(app.public_ref), "mail_sent", "2026-10-24")
    outcome = erase(privileged_reset, app.public_ref)
    assert outcome.handoffs == ["mail_inbox", "mail_sent"]
    with pytest.raises(service.Refused, match="handoff_not_owed"):
        service.handoff(str(app.public_ref), "documenso", "2026-10-24")
    with pytest.raises(service.Refused, match="record_malformed"):
        service.handoff(str(app.public_ref), "mail_sent", "24 October")
    head = service.handoff(str(app.public_ref), "mail_sent", "2026-10-24")
    assert record.verify(head)["handoffs_outstanding"] == 1
    state = record.fold(journal.read(), KEY.encode())[str(app.public_ref)]
    assert state.handoffs_done == {"mail_sent": "2026-10-24"} and state.outstanding == ["mail_inbox"]


def test_9kg_32_tombstoned_email_keys_are_unique_and_never_a_real_key(privileged_reset, decided):
    first, second = subject("first@example.test", "Flo Example"), subject("second@example.test", "Sid Example")
    owner = privileged_reset.connect("owner", autocommit=True)
    owner.execute("INSERT INTO applications_invitation (public_id, email_key, issued_by, note, expires_at)"
                  " VALUES (gen_random_uuid(), 'first@example.test', 'owner_command', '', now() + interval '1 day')")
    erase(privileged_reset, first.public_ref)
    erase(privileged_reset, second.public_ref)
    keys = list(Application.objects.filter(pk__in=(first.pk, second.pk)).values_list("email_key", flat=True))
    assert len(set(keys)) == 2 and all(k.startswith("erased:") and "@" not in k for k in keys)
    invitation = Invitation.objects.get(email_key__startswith="erased:")
    assert invitation.email_key == f"erased:{invitation.public_id}" and invitation.used_at is None
    with pytest.raises(errors.UniqueViolation):
        owner.execute("INSERT INTO applications_application (public_ref, email, email_key, display_name, stage,"
                      " next_version_number) VALUES (gen_random_uuid(), 'x', %s, 'x', 'closed', 1)", [keys[0]])
    with pytest.raises(errors.UniqueViolation):
        owner.execute("INSERT INTO applications_memberagreementonfile (public_id, email_key, covers, completion_verified,"
                      " recorded_by, superseded_at) VALUES (gen_random_uuid(), %s, '{\"nda\": \"v1\"}', true, 'owner_command',"
                      " now()), (gen_random_uuid(), %s, '{\"nda\": \"v1\"}', true, 'owner_command', now())",
                      ["erased:same", "erased:same"])


# --- the command -------------------------------------------------------------------------------------------------------

ERASE_PROBE = """
import json, sys
import django
django.setup()
from erasure import registry
registry.REGISTRY = json.loads(sys.argv[1])
registry.REPLAY_BUILT = True
from django.core.management import call_command
call_command("catalyst_erase", "--subject", sys.argv[2], "--authority", "pol-10:synthetic-decision", "--reason", "subject-request")
"""


def test_9kg_32_the_command_runs_only_as_the_retention_login_and_never_as_web_or_worker(privileged_reset, decided):
    from django.db import connection

    app = subject()
    base = {"CATALYST_DB_NAME": connection.settings_dict["NAME"], "CATALYST_ERASURE_KEY": KEY}

    def as_role(role, *args, registry_rows=DECIDED):
        return run([sys.executable, "-c", ERASE_PROBE, json.dumps(registry_rows), str(app.public_ref), *args],
                   CATALYST_DB_USER=ROLES[role], CATALYST_DB_PASSWORD=os.environ[f"CATALYST_DB_{role.upper()}_PASSWORD"],
                   **base)
    for role in ("app", "owner"):
        refused = as_role(role)
        assert refused.returncode == 1 and "erasure refused: not_the_retention_role" in refused.stderr, refused.stderr
    undecided = as_role("retention", registry_rows={n: {"treatment": "undecided", "retention": "undecided"} for n in DECIDED})
    assert undecided.returncode == 1 and "erasure refused: registry_undecided" in undecided.stderr
    shipped = run([sys.executable, "manage.py", "catalyst_erase", "--subject", str(app.public_ref), "--authority",
                   AUTHORITY, "--reason", REASON], CATALYST_DB_USER=ROLES["retention"],
                  CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_RETENTION_PASSWORD"], **base)
    assert shipped.returncode == 1 and "registry_undecided" in shipped.stderr  # the shipped registry refuses
    assert erasure_entries() == [] and Application.objects.get(pk=app.pk).email == "grace@example.test"
    done = as_role("retention")
    assert done.returncode == 0, done.stderr
    printed = json.loads(done.stdout.strip().splitlines()[-1])
    assert printed["status"] == "erased" and printed["subject"] == str(app.public_ref)
    assert re.fullmatch(r"[0-9a-f]{32}:\d+:[0-9a-f]{64}", printed["journal_head"])
    assert "grace" not in done.stdout.lower() and str(app.pk) not in printed.values()
    assert Application.objects.get(pk=app.pk).email == "[erased]"
    # Never a web or worker process: the command refuses there, and those processes cannot hold the login anyway
    # (config.runtime refuses a retention connection for them; tests/test_db_roles.py).
    from config import runtime
    runtime.declare_process("worker")
    try:
        with pytest.raises(SystemExit):
            call_command("catalyst_erase", "--subject", str(app.public_ref), "--authority", AUTHORITY, "--reason", REASON)
    finally:
        runtime.declare_process("management")


# --- the migration -----------------------------------------------------------------------------------------------------

def test_9kg_32_the_erasure_migration_reverses_and_reapplies_and_keeps_the_rows(privileged_reset, decided):
    """The reverse leaves every guarded function exactly as it is in a database that never ran erasure 0002 (a fresh
    one migrated to 0002's dependencies only), and the reapply restores the branches."""
    import importlib

    from tests.test_backup_commands import admin

    app = subject()
    owner = privileged_reset.connect("owner", autocommit=True)
    query = ("SELECT p.proname, pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
             " WHERE n.nspname = 'public' AND p.proname = ANY(%s)")
    installed = dict(owner.execute(query, [list(catalog.GUARDED_FUNCTIONS)]).fetchall())
    fresh = f"catalyst_erasure_{uuid.uuid4().hex[:10]}"
    with admin("postgres") as conn:
        conn.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(fresh), sql.Identifier(ROLES["owner"])))
    try:
        env = {"CATALYST_DB_NAME": fresh, "CATALYST_DB_USER": ROLES["owner"],
               "CATALYST_DB_PASSWORD": os.environ["CATALYST_DB_OWNER_PASSWORD"]}
        for app_label, name in importlib.import_module("erasure.migrations.0002_erasure_path").Migration.dependencies:
            result = run([sys.executable, "manage.py", "migrate", app_label, name, "--verbosity", "0"], timeout=300, **env)
            assert result.returncode == 0, result.stderr
        with admin(fresh) as conn:
            before = dict(conn.execute(query, [list(catalog.GUARDED_FUNCTIONS)]).fetchall())
        assert set(before) == set(catalog.GUARDED_FUNCTIONS)
        manage_as_owner("migrate", "erasure", "0001", "--verbosity", "0")
        assert dict(owner.execute(query, [list(catalog.GUARDED_FUNCTIONS)]).fetchall()) == before  # exactly as before
        assert all(definition == catalog.without_branch(installed[name]) for name, definition in before.items())
    finally:
        with admin("postgres") as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(fresh)))
    assert owner.execute("SELECT count(*) FROM pg_proc WHERE proname IN ('catalyst_erase', 'catalyst_erasure_admits',"
                         " 'catalyst_erasable_append_only')").fetchone()[0] == 0
    assert owner.execute("SELECT count(*) FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid"
                         " WHERE p.proname = 'catalyst_append_only_strict' AND t.tgname <> 'catalyst_no_truncate'"
                         " AND t.tgrelid::regclass::text IN ('applications_retentionaudit', 'agreements_agreementrecipient',"
                         " 'agreements_documentaccess', 'correspondence_staffitemresolution',"
                         " 'provisioning_provisioningevidence')").fetchone()[0] == 5
    manage_as_owner("migrate", "--verbosity", "0")
    assert dict(owner.execute(query, [list(catalog.GUARDED_FUNCTIONS)]).fetchall()) == installed
    assert erase(privileged_reset, app.public_ref).status == "erased"


# --- the reviews of PR #99 ---------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_9kg_32_the_new_functions_have_their_owner_definer_and_search_path():
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT p.proname, p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner) FROM pg_proc p"
                       " JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = 'public' AND p.proname = ANY(%s)",
                       [["catalyst_erase", "catalyst_erasure_admits", "catalyst_erasable_append_only",
                         "catalyst_erasure_audit_txid"]])
        rows = {name: (definer, config, owner) for name, definer, config, owner in cursor.fetchall()}
    assert rows == {
        "catalyst_erase": (True, ["search_path=pg_catalog, public, pg_temp"], ROLES["owner"]),
        "catalyst_erasure_admits": (True, ["search_path=pg_catalog, public, pg_temp"], ROLES["owner"]),
        "catalyst_erasable_append_only": (False, ["search_path=public, pg_temp"], ROLES["owner"]),
        "catalyst_erasure_audit_txid": (False, ["search_path=public, pg_temp"], ROLES["owner"]),
    }


def test_9kg_32_a_forged_intent_or_handoff_is_refused_and_a_resume_trusts_nothing_from_the_journal(
        privileged_reset, decided, monkeypatch):
    app = subject()
    ref = str(app.public_ref)
    # A forged intent (no valid mac) for a subject: the erasure refuses rather than resume it.
    journal.append("erasure_intent", f"erasure:{ref}", {"subject": "0" * 64, "key_id": "0" * 16, "authority": "x:forged",
                                                       "reason": "forged", "classes": ["submissions"], "handoffs": [],
                                                       "retained": [], "phase": "intent", "mac": "f" * 64})
    with pytest.raises(service.Refused, match="record_forged_entry"):
        erase(privileged_reset, ref)
    with pytest.raises(record.RecordError, match="forged_entry"):
        record.list_open()
    assert Application.objects.get(pk=app.pk).email == "grace@example.test"
    # An intent with a valid mac but another person's hash (as if moved from another subject): refused on resume.
    other = subject("other.person@example.test", "Hedy Example")
    secret = KEY.encode()
    record.append_intent(other.public_ref, record.subject_hash("someone.else@example.test", secret),
                         record.key_id(secret), AUTHORITY, REASON, ["submissions"], [], [], secret)
    with pytest.raises(service.Refused, match="record_subject_mismatch"):
        erase(privileged_reset, other.public_ref)
    # A resume takes the classes from the registry and the codes from this run, never from the intent.
    third = subject("third.person@example.test", "Joan Example")
    record.append_intent(third.public_ref, record.subject_hash("third.person@example.test", secret),
                         record.key_id(secret), "old:authority", "old-reason", ["submissions"], ["mail_sent"], [], secret)
    resumed = erase(privileged_reset, third.public_ref)
    assert resumed.resumed and resumed.status == "erased"
    assert Application.objects.get(pk=third.pk).email == "[erased]"  # identity erased though the intent named submissions
    assert audits(privileged_reset, third.public_ref)[-1][1:3] == (AUTHORITY, REASON)
    # A forged handoff (no valid mac) closes nothing, and verification refuses the record.
    done = subject("done.person@example.test", "Mary Example")
    erase(privileged_reset, done.public_ref)
    journal.append("erasure_handoff", f"erasure:{done.public_ref}", {"provider": "mail_sent", "completed_on": "2026-10-24",
                                                                     "phase": "done", "mac": "a" * 64})
    assert record.fold(journal.read(), secret)[str(done.public_ref)].outstanding == ["mail_inbox", "mail_sent"]
    with pytest.raises(record.RecordError, match="forged_entry"):
        record.verify(record.head_string())


def test_9kg_32_an_interrupted_first_erasure_is_listed_without_a_head_and_raises_a_health_anomaly(
        privileged_reset, decided, monkeypatch):
    from config import system_health

    app = subject()

    def crash(conn, *args, commit):
        if commit:
            raise Crash("killed")
        return real(conn, *args, commit=commit)
    real = service._call
    monkeypatch.setattr(service, "_call", crash)
    with pytest.raises(Crash):
        erase(privileged_reset, app.public_ref)
    monkeypatch.setattr(service, "_call", real)
    assert record.list_open()["open"] == [str(app.public_ref)]
    assert system_health.erasure_health()["anomalies"] == ["intent_open"]
    with pytest.raises(SystemExit):
        call_command("catalyst_erasure_record", "--list-open")
    # The resume needs no registry gate: an erasure already begun is finished even while a value is undecided.
    monkeypatch.setattr(registry, "REPLAY_BUILT", False)
    assert erase(privileged_reset, app.public_ref).status == "erased"
    assert record.list_open()["open"] == []
    assert system_health.erasure_health()["anomalies"] == ["handoff_owed"]


def test_9kg_32_handoff_dates_and_heads_are_checked(privileged_reset, decided):
    app = subject()
    outcome = erase(privileged_reset, app.public_ref)
    tomorrow = (timezone.now().date() + timedelta(days=1)).isoformat()
    for bad in (tomorrow, "2026-13-01", "2026-10-24T10:00", "24 October"):
        with pytest.raises(service.Refused, match="record_malformed"):
            service.handoff(str(app.public_ref), "mail_sent", bad)
    identity, _, digest = outcome.journal_head.split(":")
    with pytest.raises(record.RecordError, match="bad_head"):
        record.verify(f"{identity}:0:{digest}")  # a head names seq 1 or later


def test_9kg_32_the_erasure_key_is_refused_in_web_and_worker_processes(settings):
    from config import guards

    settings.CATALYST_ERASURE_KEY = KEY
    assert guards.erasure_key_problems(settings, "web") and guards.erasure_key_problems(settings, "worker")
    assert guards.erasure_key_problems(settings, "management") == [] == guards.erasure_key_problems(settings, "reconcile")
    settings.CATALYST_ERASURE_KEY = ""
    assert guards.erasure_key_problems(settings, "web") == []


def test_9kg_32_a_key_that_starts_like_a_tombstone_but_has_an_at_sign_is_a_real_key(privileged_reset, decided):
    app = subject("erased:real@example.test", "Opal Example")
    outcome = erase(privileged_reset, app.public_ref)
    assert outcome.status == "erased"
    assert Application.objects.get(pk=app.pk).email_key == f"erased:{app.public_ref}"


def test_9kg_32_an_already_tombstoned_subject_still_runs_the_classes_scoped_by_its_references(privileged_reset, decided):
    app = subject()
    erase(privileged_reset, app.public_ref)
    owner = privileged_reset.connect("owner", autocommit=True)
    # A row the first run could not see (as a class added later would find): an event with a note.
    owner.execute("INSERT INTO applications_applicationevent (application_id, kind, actor_type, actor_ref, data)"
                  " VALUES (%s, 'late_note', 'staff', 'user:1', '{\"note\": \"Grace Example again\"}')", [app.pk])
    again = erase(privileged_reset, app.public_ref)
    assert again.status == "erased" and again.changed == 1
    assert ApplicationEvent.objects.get(application=app, kind="late_note").data == {}


def test_9kg_32_a_restore_hold_cannot_lift_while_the_journal_holds_an_unreplayed_erasure(privileged_reset, decided):
    from django.db import connection

    from config import post_restore

    app = subject()
    erase(privileged_reset, app.public_ref)
    assert post_restore.erasures_unreplayed() is False  # replay "built" in this test's registry
    owner = privileged_reset.connect("owner", autocommit=True)
    owner.execute("INSERT INTO workflow_automationpause (subject_type, subject_id, reason, actor_ref, created_at)"
                  " VALUES ('system', '00000000-0000-0000-0000-00000000aaaa', %s, 'catalyst_restore|::', now())",
                  [post_restore.RECONCILED])
    result = run([sys.executable, "manage.py", "catalyst_post_restore", "--confirm-database", connection.settings_dict["NAME"],
                  "--lift", "--outward-checked", "--no-closures-after-backup"], timeout=120,
                 CATALYST_DB_NAME=connection.settings_dict["NAME"], CATALYST_DB_USER=ROLES["owner"],
                 CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_OWNER_PASSWORD"])
    assert result.returncode != 0 and post_restore.ITEM_ERASURE in result.stderr, result.stderr
    assert owner.execute("SELECT count(*) FROM workflow_automationpause WHERE subject_type = 'system'").fetchone()[0] == 1
