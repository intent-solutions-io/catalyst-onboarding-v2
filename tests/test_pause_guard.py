"""9kg.6 (016 section 10.13; ADR-14): the automation pause row is cleared only by an audited resume, enforced in
PostgreSQL for every role. Proved through real connections as the application and owner roles (`connect`, from the
privileged reset), since a deferred constraint trigger only speaks at commit, and through the staff service."""

import json
import uuid

import psycopg
import pytest
from psycopg import errors

from correspondence import staff_actions
from tests.test_db_roles import connect, new_application  # noqa: F401  (fixture and helper)
from tests.test_inbound import tls  # noqa: F401
from tests.test_outbound import p2, ready, staff, verified_application  # noqa: F401
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

RESUMED = ("INSERT INTO applications_applicationevent (application_id, kind, actor_type, actor_ref, data)"
           " VALUES (%s, 'automation_resumed', %s, %s, %s)")


def pause(conn, app_id, actor_ref="user:1"):
    """An application's pause row, inserted and committed by `conn`; returns the application's public_ref."""
    subject = conn.execute("SELECT public_ref FROM applications_application WHERE id = %s", [app_id]).fetchone()[0]
    conn.execute("INSERT INTO workflow_automationpause (subject_type, subject_id, reason, actor_ref)"
                 " VALUES ('application', %s, 'synthetic pause', %s)", [subject, actor_ref])
    conn.commit()
    return subject


def paused(conn, subject) -> bool:
    conn.rollback()  # a fresh snapshot, whatever the last statement did
    return conn.execute("SELECT count(*) FROM workflow_automationpause WHERE subject_id = %s", [subject]).fetchone()[0] == 1


def refused(conn, match, *statements):
    """Run the statements in one transaction and commit: the guard refuses with insufficient_privilege."""
    with pytest.raises(errors.InsufficientPrivilege, match=match):
        for statement, params in statements:
            conn.execute(statement, params)
        conn.commit()
    conn.rollback()


def test_9kg6_a_bare_delete_or_update_by_the_application_role_is_refused(connect):
    app = connect("app")
    app_id, _, _ = new_application(app)
    subject = pause(app, app_id)
    refused(app, "automation_resumed event for the application, recorded by staff",
            ("DELETE FROM workflow_automationpause WHERE subject_id = %s", [subject]))
    assert paused(app, subject)
    # Every resume is a staff act: a system actor, or staff with no actor reference, does not clear a staff pause.
    for actor_type, actor_ref in (("system", ""), ("system", "system:correspondence"), ("applicant", "user:1"), ("staff", "")):
        refused(app, "recorded by staff with an actor reference",
                (RESUMED, [app_id, actor_type, actor_ref, json.dumps({"note": "a note of ten+ chars"})]),
                ("DELETE FROM workflow_automationpause WHERE subject_id = %s", [subject]))
        assert paused(app, subject)
    # The application role holds no UPDATE grant, so the privilege refuses first; the trigger answers the owner.
    refused(app, "permission denied|UPDATE refused", ("UPDATE workflow_automationpause SET reason = 'edited' WHERE subject_id = %s", [subject]))
    refused(app, "permission denied|UPDATE refused", ("UPDATE workflow_automationpause SET actor_ref = 'user:2' WHERE subject_id = %s", [subject]))
    assert paused(app, subject)
    # A resume event for another application does not count; one for this application, in the transaction, does.
    other_id, _, _ = new_application(app, key="other@example.test")
    refused(app, "automation_resumed event for the application",
            (RESUMED, [other_id, "staff", "user:1", json.dumps({"note": "wrong application"})]),
            ("DELETE FROM workflow_automationpause WHERE subject_id = %s", [subject]))
    assert paused(app, subject)
    app.execute(RESUMED, [app_id, "staff", "user:1", json.dumps({"note": "resumed"})])
    app.execute("DELETE FROM workflow_automationpause WHERE subject_id = %s", [subject])
    app.commit()
    assert not paused(app, subject)


def test_9kg6_the_migration_owner_is_refused_the_same_way_and_truncate_is_refused_for_every_role(connect):
    app, owner = connect("app"), connect("owner")
    app_id, _, _ = new_application(app)
    subject = pause(app, app_id)
    refused(owner, "automation_resumed event", ("DELETE FROM workflow_automationpause WHERE subject_id = %s", [subject]))
    refused(owner, "UPDATE refused", ("UPDATE workflow_automationpause SET reason = 'x' WHERE subject_id = %s", [subject]))
    refused(owner, "append-only: TRUNCATE", ("TRUNCATE workflow_automationpause", []))
    refused(app, "permission denied|TRUNCATE", ("TRUNCATE workflow_automationpause", []))  # no grant, and the trigger
    assert paused(owner, subject) and paused(app, subject)


def test_9kg6_a_system_pause_clears_only_with_a_staff_resume_event_with_a_note_in_the_same_transaction(connect):
    app = connect("app")
    app_id, _, _ = new_application(app)
    subject = pause(app, app_id, actor_ref="system:correspondence")
    delete = ("DELETE FROM workflow_automationpause WHERE subject_id = %s", [subject])
    for actor_type, actor_ref, data in (
            ("system", "", {"note": "a system cannot resume itself"}),
            ("staff", "", {"note": "no actor reference"}),
            ("staff", "user:1", {}),
            ("staff", "user:1", {"note": ""}),
            ("staff", "user:1", {"note": "nine char"}),  # 9: below the service's minimum of 10
            ("staff", "user:1", {"note": "   padded   "})):  # blanks do not count
        refused(app, "clearing a system pause needs an automation_resumed event recorded by staff",
                (RESUMED, [app_id, actor_type, actor_ref, json.dumps(data)]), delete)
        assert paused(app, subject)
    # The right shape, but committed in an earlier transaction: not this transaction's resume.
    app.execute(RESUMED, [app_id, "staff", "user:1", json.dumps({"note": "earlier"})])
    app.commit()
    refused(app, "clearing a system pause", delete)
    assert paused(app, subject)
    app.execute(RESUMED, [app_id, "staff", "user:1", json.dumps({"note": "ten chars!"})])  # exactly ten
    app.execute(*delete)
    app.commit()
    assert not paused(app, subject)
    # The plain `system` actor is a system pause too.
    subject = pause(app, app_id, actor_ref="system")
    refused(app, "clearing a system pause", (RESUMED, [app_id, "staff", "user:1", "{}"]), delete)
    assert paused(app, subject)


def test_9kg6_a_staff_pause_clears_with_the_resume_event_even_inside_a_savepoint(connect):
    """The transaction marker is the top-level id, so an event inserted inside a savepoint (a nested atomic block)
    still counts for the delete that follows."""
    app = connect("app")
    app_id, _, _ = new_application(app)
    subject = pause(app, app_id)
    app.execute("SAVEPOINT s")
    app.execute(RESUMED, [app_id, "staff", "user:1", json.dumps({"note": "inside a savepoint"})])
    app.execute("RELEASE SAVEPOINT s")
    app.execute("DELETE FROM workflow_automationpause WHERE subject_id = %s", [subject])
    app.commit()
    assert not paused(app, subject)


def test_9kg6_no_earlier_event_and_no_rolled_back_savepoint_event_clears_a_staff_pause(connect):
    """An event from any earlier transaction (the migration's included: its rows carry the migration's own
    transaction id) and an event whose savepoint was rolled back are not this transaction's resume."""
    app = connect("app")
    app_id, _, _ = new_application(app)
    subject = pause(app, app_id)
    delete = ("DELETE FROM workflow_automationpause WHERE subject_id = %s", [subject])
    app.execute(RESUMED, [app_id, "staff", "user:1", json.dumps({"note": "an earlier transaction"})])
    app.commit()
    refused(app, "in the same transaction", delete)
    assert paused(app, subject)
    app.execute("SAVEPOINT s")
    app.execute(RESUMED, [app_id, "staff", "user:1", json.dumps({"note": "rolled back with its savepoint"})])
    app.execute("ROLLBACK TO SAVEPOINT s")
    refused(app, "in the same transaction", delete)
    assert paused(app, subject)
    # The pre-existing events of this application (the migration-time shape) do not help either: only this
    # transaction's event does.
    assert app.execute("SELECT count(*) FROM applications_applicationevent WHERE application_id = %s", [app_id]).fetchone()[0] >= 2
    app.rollback()


def test_9kg6_an_unknown_subject_type_is_guarded_and_cannot_be_cleared(connect):
    """Only the restore hold's `system` rows are exempt; a pause of any other subject type has no application to
    join and is refused outright (fail closed)."""
    app = connect("app")
    subject = uuid.uuid4()
    app.execute("INSERT INTO workflow_automationpause (subject_type, subject_id, reason, actor_ref)"
                " VALUES ('mailbox', %s, 'synthetic', 'user:1')", [subject])
    app.commit()
    refused(app, "automation_resumed event", ("DELETE FROM workflow_automationpause WHERE subject_id = %s", [subject]))
    refused(app, "permission denied|UPDATE refused", ("UPDATE workflow_automationpause SET reason = 'x' WHERE subject_id = %s", [subject]))
    owner = connect("owner")
    refused(owner, "UPDATE refused", ("UPDATE workflow_automationpause SET reason = 'x' WHERE subject_id = %s", [subject]))
    refused(owner, "automation_resumed event", ("DELETE FROM workflow_automationpause WHERE subject_id = %s", [subject]))
    assert paused(app, subject)


def test_9kg6_the_transaction_marker_is_on_no_read_surface():
    """created_txid is the guard's business: it reaches no admin field list, template, form or serialised dict."""
    import re
    from pathlib import Path

    from applications.admin import EventInline

    assert "created_txid" not in EventInline.fields
    root = Path(__file__).resolve().parent.parent
    where = {str(p.relative_to(root)) for app in ("accounts", "agreements", "applications", "assessments", "config",
                                                   "correspondence", "provisioning", "workflow")
             for p in (root / app).rglob("*") if p.is_file() and p.suffix in (".py", ".html", ".txt")
             and "migrations" not in p.parts and re.search(r"\bcreated_txid\b", p.read_text())}
    assert where == {"applications/models.py", "assessments/models.py", "agreements/models.py"}, where


def test_9kg6_the_event_transaction_marker_is_always_the_databases_own(connect):
    app = connect("app")
    app_id, _, event_id = new_application(app)
    supplied = app.execute(
        "INSERT INTO applications_applicationevent (application_id, kind, actor_type, actor_ref, data, created_txid)"
        " VALUES (%s, 'automation_resumed', 'staff', 'user:1', '{}', 1) RETURNING created_txid, pg_current_xact_id()::text::bigint",
        [app_id]).fetchone()
    app.commit()
    assert supplied[0] == supplied[1] != 1  # overwritten with this transaction's id
    earlier = app.execute("SELECT created_txid FROM applications_applicationevent WHERE id = %s", [event_id]).fetchone()[0]
    assert earlier < supplied[0]  # an earlier transaction's event carries an earlier id
    app.rollback()


def test_9kg6_the_supported_resume_path_clears_the_pause_and_work_resumes(ready):
    """The staff service records the resume event in the transaction that deletes the pause, so it passes the guard
    unchanged, and the ledger claims the application's queued work again."""
    app = ready.app
    action = PendingAction.objects.create(kind="send_message", subject_type="application", subject_id=app.public_ref,
                                          input_ref="", idempotency_key=f"guard-probe:{uuid.uuid4()}")
    staff_actions.pause(app.pk, ready.operator, "synthetic staff pause for the guard")
    assert ledger.claim_next(ledger.handlers()) is None  # paused: nothing is claimed
    assert staff_actions.resume(app.pk, ready.operator, "synthetic resume") == 0
    assert not AutomationPause.objects.filter(subject_id=app.public_ref).exists()
    event = app.events.filter(kind="automation_resumed").get()
    assert event.actor_type == "staff" and event.actor_ref and event.data["note"] == "synthetic resume"
    assert event.created_txid > 0
    claim = ledger.claim_next(ledger.handlers())
    assert claim is not None and claim.id == action.pk  # work resumes


def test_9kg6_the_restore_hold_keeps_its_own_rule(connect):
    """A `system` row (the restore hold) is outside the resume guard: the owner lifts it with no event, as the
    post-restore step does; the application role is still refused by the restore-hold trigger."""
    from config.backup import RESTORE_HOLD

    owner, app = connect("owner"), connect("app")
    owner.execute("INSERT INTO workflow_automationpause (subject_type, subject_id, reason, actor_ref)"
                  " VALUES (%s, %s, 'restore hold (test)', 'test')", list(RESTORE_HOLD))
    owner.commit()
    refused(app, "restore hold", ("DELETE FROM workflow_automationpause WHERE subject_type = %s", [RESTORE_HOLD[0]]))
    owner.execute("UPDATE workflow_automationpause SET reason = 'reviewed' WHERE subject_type = %s", [RESTORE_HOLD[0]])
    owner.execute("DELETE FROM workflow_automationpause WHERE subject_type = %s", [RESTORE_HOLD[0]])
    owner.commit()
    assert owner.execute("SELECT count(*) FROM workflow_automationpause").fetchone()[0] == 0
