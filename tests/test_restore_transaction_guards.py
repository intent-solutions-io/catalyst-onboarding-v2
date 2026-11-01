"""9kg.58: restored transaction IDs never stand in for fresh authorization evidence."""

import os

import psycopg
from django.conf import settings
from django.db import connection
from django.utils import timezone
from psycopg import errors

from agreements.models import AgreementInstance, AgreementTemplateVersion, AgreementType
from tests.test_backup_commands import (
    admin,
    drop,
    new_database,
    run_backup,
    run_restore,
)
from tests.test_db_roles import new_application
from tests.test_decision import _decision_sql
from tests.test_pause_guard import RESUMED, pause
from tests.support import manage_as_owner

TABLES = {
    "pause": ("applications_applicationevent", "occurred_at"),
    "decision": ("assessments_qualificationdecision", "created_at"),
    "agreement": ("agreements_providerobservation", "observed_at"),
}


def evidence(conn, kind, app_id, instance_id):
    if kind == "pause":
        conn.execute(
            RESUMED,
            [app_id, "staff", "user:synthetic", '{"note":"reviewed synthetic resume"}'],
        )
    elif kind == "decision":
        _decision_sql(conn, app_id)
    else:
        conn.execute(
            "INSERT INTO agreements_providerobservation (instance_id, application_id, source, event, envelope_status,"
            " recipients, identity_match, recipients_match, all_required_signed, content_sha256)"
            " VALUES (%s, %s, 'read', '', 'COMPLETED', '[]', true, true, true, 'synthetic')",
            [instance_id, app_id],
        )


def change(conn, kind, app_id, instance_id):
    if kind == "pause":
        conn.execute(
            "DELETE FROM workflow_automationpause WHERE subject_type = 'application' AND subject_id ="
            " (SELECT public_ref FROM applications_application WHERE id = %s)",
            [app_id],
        )
    elif kind == "decision":
        conn.execute(
            "UPDATE applications_application SET stage = 'on_hold' WHERE id = %s",
            [app_id],
        )
    else:
        conn.execute(
            "UPDATE agreements_agreementinstance SET signing_status = 'signing_complete_verified' WHERE id = %s",
            [instance_id],
        )


def seed(committed):
    owner = committed.connect("owner")
    template = AgreementTemplateVersion.objects.create(
        agreement_type=AgreementType.objects.get(key="nda"),
        version=1,
        provider_template_ref="synthetic-template",
        provider_template_number=1,
        recipient_slots={"SIGNER:1": 1},
        pdf_sha256="0" * 64,
    )
    AgreementTemplateVersion.objects.filter(pk=template.pk).update(
        status="approved", approved_by="user:synthetic", approved_at=timezone.now()
    )
    cases = []
    for role in ("app", "owner"):
        for kind, (table, timestamp) in TABLES.items():
            app_id, _, _ = new_application(owner, key=f"{role}-{kind}@example.test")
            instance_id = None
            if kind == "pause":
                pause(owner, app_id, actor_ref="system:synthetic")
            elif kind == "agreement":
                instance = AgreementInstance.objects.create(
                    application_id=app_id,
                    agreement_type=template.agreement_type,
                    template_version=template,
                    external_key=f"synthetic-{role}",
                    issue_status="create_pending",
                )
                instance_id = instance.pk
                owner.execute(
                    "UPDATE agreements_agreementinstance SET issue_status = 'issued', envelope_id = %s WHERE id = %s",
                    [f"synthetic-envelope-{role}", instance_id],
                )
            evidence(owner, kind, app_id, instance_id)
            owner.commit()
            record_id, when = owner.execute(
                f"SELECT id, {timestamp} FROM {table} WHERE application_id = %s ORDER BY id DESC LIMIT 1",
                [app_id],
            ).fetchone()
            owner.rollback()
            cases.append((role, kind, app_id, instance_id, record_id, when))
    return cases


def test_9kg_58_real_restore_refuses_old_evidence_with_a_reused_txid_for_all_three_guards(
    privileged_reset, tmp_path
):
    cases = seed(privileged_reset)
    sets, custody = tmp_path / "sets", tmp_path / "custody"
    sets.mkdir()
    custody.mkdir(mode=0o700)
    saved = run_backup(sets, custody)
    assert saved.returncode == 0, saved.stderr
    database = new_database()
    failures = []
    try:
        restored = run_restore(database, sets / "set", tmp_path / "restored")
        assert restored.returncode == 0, restored.stderr
        with admin(database) as fixture:
            for role, kind, app_id, instance_id, record_id, old_when in cases:
                table, timestamp = TABLES[kind]
                with psycopg.connect(
                    host=connection.settings_dict["HOST"],
                    port=connection.settings_dict["PORT"],
                    dbname=database,
                    user=settings.CATALYST_DB_ROLES[role],
                    password=os.environ[f"CATALYST_DB_{role.upper()}_PASSWORD"],
                ) as conn:
                    txid, started = conn.execute(
                        "SELECT pg_current_xact_id()::text::bigint, transaction_timestamp()"
                    ).fetchone()
                    assert old_when < started
                    # Model the collision deterministically after a real restore, without resetting the
                    # shared test cluster's transaction counter. Only this isolated fixture bypasses history
                    # protection; all guarded writes below use ordinary app/owner connections and live triggers.
                    with fixture.transaction():
                        fixture.execute("SET LOCAL session_replication_role = replica")
                        fixture.execute(
                            f"UPDATE {table} SET created_txid = %s WHERE id = %s",
                            [txid, record_id],
                        )
                    assert conn.execute(
                        f"SELECT created_txid, {timestamp} FROM {table} WHERE id = %s",
                        [record_id],
                    ).fetchone() == (txid, old_when)
                    try:
                        change(conn, kind, app_id, instance_id)
                        conn.commit()
                    except errors.InsufficientPrivilege:
                        conn.rollback()
                    else:
                        failures.append(f"{role}:{kind}")
                        continue
                    # A fresh record in a savepoint of the current transaction still authorizes the write.
                    conn.execute("SAVEPOINT fresh_evidence")
                    evidence(conn, kind, app_id, instance_id)
                    conn.execute("RELEASE SAVEPOINT fresh_evidence")
                    change(conn, kind, app_id, instance_id)
                    conn.commit()
            assert not failures, (
                f"restored old evidence authorized new writes: {failures}"
            )
    finally:
        drop(database)


def test_9kg_58_migrations_reverse_and_reapply_without_changing_rows_or_protections(
    privileged_reset,
):
    from tests.conftest import protection_state

    cases = seed(privileged_reset)
    owner = privileged_reset.connect("owner", autocommit=True)
    names = [
        "catalyst_pause_resume_guard",
        "catalyst_decided_stage_needs_decision",
        "catalyst_agreement_verified_needs_read",
    ]

    def functions():
        return owner.execute(
            "SELECT p.proname, pg_get_functiondef(p.oid), p.proowner, p.proacl FROM pg_proc p"
            " JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE n.nspname = 'public' AND p.proname = ANY(%s) AND p.pronargs = 0 ORDER BY 1",
            [names],
        ).fetchall()

    def records():
        return [
            owner.execute(
                f"SELECT row_to_json(t) FROM {table} t ORDER BY id"
            ).fetchall()
            for table, _ in TABLES.values()
        ]

    before, rows, protections = functions(), records(), protection_state(owner)
    assert len(cases) == 6 and len(before) == 3
    assert all(
        "pg_catalog.transaction_timestamp()" in definition
        for _, definition, _, _ in before
    )
    try:
        for app, previous in (
            ("workflow", "0006"),
            ("assessments", "0011"),
            ("agreements", "0012"),
        ):
            manage_as_owner("migrate", app, previous, "--verbosity", "0")
        assert all(
            "pg_catalog.transaction_timestamp()" not in definition
            for _, definition, _, _ in functions()
        )
        assert records() == rows and protection_state(owner) == protections
    finally:
        manage_as_owner("migrate", "--verbosity", "0")
    assert functions() == before
    assert records() == rows and protection_state(owner) == protections
