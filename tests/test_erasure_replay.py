"""9kg.25: the durable erasure record is replayed after a restore (026 section 6 option d; 029 section 6.2.1;
TEST-P6-29), so restoring an older backup never brings an erased person back.

Proved with a real backup, erasures after it, a real restore into a fresh database and the replay command as the
retention login; the post-restore review and lift run as the owner. Tests commit through their own connections and
rely on the privileged reset (tests/conftest.py); a restored database is dropped by the test that made it.
"""

import json
import os
import sys
import uuid

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from psycopg import errors

from applications.models import Application
from config import backup
from erasure import catalog, record, replay, service
from tests import support
from tests.test_backup_commands import admin, drop, new_database, run_backup, run_restore
from tests.test_erasure import (  # noqa: F401  (the `decided` fixture)
    AUTHORITY, DECIDED, KEY, REASON, Crash, decided, erase, owner_scan, raises_sqlstate, subject,
)
from tests.test_post_restore import LIFT, SENT
from tests.test_post_restore import post_restore as run_post_restore
from workflow import journal
from workflow.models import PendingAction

ROLES = settings.CATALYST_DB_ROLES
REPLAY_PROBE = """
import json, sys
import django
django.setup()
from erasure import registry
registry.REGISTRY = json.loads(sys.argv[1])
from django.core.management import call_command
call_command("catalyst_erasure_replay", "--expect-head", sys.argv[2])
"""
SIGNATURE = "public.catalyst_erase_replay(uuid, text, text, text[])"


def replay_command(database, head, role="retention"):
    """The replay command in its own process, as `role`, with a decided synthetic registry (the shipped one is not)."""
    return support.run([sys.executable, "-c", REPLAY_PROBE, json.dumps(DECIDED), head], timeout=120,
                       CATALYST_DB_NAME=database, CATALYST_DB_USER=ROLES[role],
                       CATALYST_DB_PASSWORD=os.environ[f"CATALYST_DB_{role.upper()}_PASSWORD"], CATALYST_ERASURE_KEY=KEY)


def printed(result) -> dict:
    return json.loads(result.stdout.strip().splitlines()[-1])


def place_hold(committed):
    committed.connect("owner", autocommit=True).execute(
        "INSERT INTO workflow_automationpause (subject_type, subject_id, reason, actor_ref, created_at)"
        " VALUES (%s, %s, 'restore hold (test)', 'catalyst_restore', now())", list(backup.RESTORE_HOLD))


def queued_work(app):
    return PendingAction.objects.create(kind="send_verification", subject_type="application", subject_id=app.public_ref,
                                        idempotency_key=f"sv:{uuid.uuid4()}", status="queued")


def test_9kg_25_a_restore_of_an_older_backup_replays_every_later_erasure_and_nothing_brings_the_person_back(
        privileged_reset, decided, tmp_path):
    # At the backup: one person still open with work queued (as a person usually is when the backup runs), one whose
    # address changes before the erasure, and a control nobody erases.
    grace = subject("grace@example.test", "Grace Example", stage="submitted")
    work = queued_work(grace)
    opal = subject("opal@example.test", "Opal Example")
    subject("ruth@example.test", "Ruth Control")
    sets, custody = tmp_path / "sets", tmp_path / "custody"
    sets.mkdir()
    custody.mkdir(mode=0o700)
    result = run_backup(sets, custody)
    assert result.returncode == 0, result.stderr
    # After the backup: Grace is closed out (journaled, as every closure is) and erased; Opal's address changes, then
    # she is erased; Iris applies and is erased. The durable record outside the backup names all three.
    journal.append("application_closed", f"application:{grace.public_ref}", {"outcome": "withdrawn", "phase": "done"})
    Application.objects.filter(pk=grace.pk).update(stage="withdrawn")
    PendingAction.objects.filter(pk=work.pk).update(status="done")
    privileged_reset.connect("owner", autocommit=True).execute(  # a contact correction (the owner; no screen does it)
        "UPDATE applications_application SET email = %s, email_key = %s WHERE id = %s",
        ["opal.moved@example.test", "opal.moved@example.test", opal.pk])
    iris = subject("iris@example.test", "Iris Later")
    for person in (grace, opal, iris):
        assert erase(privileged_reset, person.public_ref).status == "erased"
    head = record.head_string()
    database = new_database()
    sent = tmp_path / "sent"
    sent.mkdir()
    env = {**SENT, "CATALYST_TEST_SENT_DIR": str(sent)}
    try:
        result = run_restore(database, sets / "set", tmp_path / "restored")
        assert result.returncode == 0, result.stderr
        with admin(database) as conn:  # the negative control: restored as it was, the erased are back
            assert owner_scan(conn, "grace@example.test", "Opal Example")
        refused, _ = run_post_restore(db=database, replayed=False, **env)
        assert refused.returncode == 1 and "erasure replay missing (unreplayed)" in refused.stderr, refused.stderr
        # Missing or stale evidence refuses and writes no marker: `none` while erasures exist, a head the journal lacks.
        identity, seq, _ = head.split(":")
        for bad in ("none", f"{identity}:{int(seq) + 50}:{'0' * 64}"):
            result = replay_command(database, bad)
            assert result.returncode == 1 and "erasure replay refused: record_journal_mismatch" in result.stderr, bad
        for role in ("owner", "app"):
            result = replay_command(database, head, role=role)
            assert result.returncode == 1 and "not_the_retention_role" in result.stderr, result.stderr
        assert replay.current_state() == "unreplayed"

        result = replay_command(database, head)
        assert result.returncode == 0, result.stderr
        report = printed(result)
        assert (report["subjects"], report["erased"], report["already"], report["absent"]) == (3, 2, 0, 1)
        assert report["mismatched"] == [str(opal.public_ref)] and report["open"] == []  # erased all the same
        assert "example.test" not in result.stdout and "Example" not in result.stdout  # references and counts only
        assert replay.current_state() == "replayed"
        with admin(database) as conn:
            assert owner_scan(conn, "grace", "opal", "Example Grace", "Grace Example", "Opal Example") == {}
            assert owner_scan(conn, "ruth@example.test", "Ruth Control")  # the control is untouched
            stage = conn.execute("SELECT stage, email_key FROM applications_application WHERE public_ref = %s",
                                 [grace.public_ref]).fetchone()
            assert stage == ("submitted", f"erased:{grace.public_ref}")  # open, as at the backup, until the review
            assert conn.execute("SELECT status FROM workflow_pendingaction WHERE id = %s", [work.pk]).fetchone() == ("queued",)
        second = replay_command(database, head)  # a second replay changes nothing and is harmless
        assert second.returncode == 0, second.stderr
        assert (printed(second)["erased"], printed(second)["already"], printed(second)["absent"]) == (0, 2, 1)

        # The review replays Grace's closure, cancels her work, opens nothing for the erased and reaches reconciled.
        reviewed, review = run_post_restore(db=database, replayed=False, **env)
        assert reviewed.returncode == 0, reviewed.stderr
        assert (review["erased_subjects"], review["erased_subjects_open"], review["erased_actions_cancelled"]) == (2, 0, 1)
        assert review["effects"]["blocked"] == [] and review["effect_items_open"] == []
        with admin(database) as conn:
            assert conn.execute("SELECT stage FROM applications_application WHERE public_ref = %s",
                                [grace.public_ref]).fetchone() == ("withdrawn",)
            assert conn.execute("SELECT status, last_error FROM workflow_pendingaction WHERE id = %s",
                                [work.pk]).fetchone() == ("cancelled", "subject_erased")
            live = conn.execute("SELECT count(*) FROM workflow_pendingaction WHERE subject_id = ANY(%s)"
                                " AND status IN ('queued', 'running', 'held', 'uncertain')",
                                [[grace.public_ref, opal.public_ref]]).fetchone()[0]
            items = conn.execute("SELECT count(*) FROM correspondence_staffitem i JOIN applications_application a"
                                 " ON a.id = i.application_id WHERE a.public_ref = ANY(%s)",
                                 [[grace.public_ref, opal.public_ref]]).fetchone()[0]
            assert (live, items) == (0, 0)  # no job and no staff item reaches an erased person
            assert owner_scan(conn, "grace", "opal", "Grace Example", "Opal Example") == {}
        lifted, outcome = run_post_restore(*LIFT, db=database, replayed=False, **env)
        assert lifted.returncode == 0 and outcome == {"hold": "lifted"}, lifted.stderr
    finally:
        drop(database)


def test_9kg_25_only_the_retention_role_runs_the_replay_function_and_only_under_the_restore_hold(privileged_reset, decided):
    assert catalog.RESTORE_HOLD_ROW == backup.RESTORE_HOLD
    owner = privileged_reset.connect("owner", autocommit=True)
    rights = dict(owner.execute(f"SELECT r.role, has_function_privilege(r.role, '{SIGNATURE}', 'EXECUTE')"
                                " FROM unnest(%s::text[]) AS r(role)",
                                [[ROLES["app"], ROLES["fetcher"], ROLES["backup"], ROLES["retention"]]]).fetchall())
    assert rights == {ROLES["app"]: False, ROLES["fetcher"]: False, ROLES["backup"]: False, ROLES["retention"]: True}
    assert owner.execute(f"SELECT has_function_privilege('public', '{SIGNATURE}', 'EXECUTE')").fetchone()[0] is False
    grace = subject(stage="submitted")
    queued_work(grace)
    call = "SELECT public.catalyst_erase_replay(%s, %s, %s, %s)"
    args = [grace.public_ref, AUTHORITY, REASON, list(registry_classes())]
    retention = privileged_reset.connect("retention")
    # The erase function refuses an open subject with work queued; the replay variant refuses without the hold.
    raises_sqlstate("CE003", retention, "SELECT public.catalyst_erase(%s, %s, %s, %s)", args)
    raises_sqlstate("CE008", retention, call, args)
    raises_sqlstate("CE007", privileged_reset.connect("owner"), call, args)  # its owner may call it, and is refused
    app_conn = privileged_reset.connect("app")
    with pytest.raises(errors.InsufficientPrivilege):
        app_conn.execute(call, args)
    app_conn.rollback()
    place_hold(privileged_reset)
    result = retention.execute(call, args).fetchone()[0]
    retention.commit()
    assert result["status"] == "erased" and result["changed"] > 0
    assert owner_scan(owner, "grace@example.test", "Grace Example") == {}
    audit = privileged_reset.connect("retention", autocommit=True).execute(
        "SELECT authority, reason_code, actor FROM erasure_erasureaudit WHERE subject_ref = %s", [grace.public_ref]).fetchall()
    assert audit == [(AUTHORITY, REASON, ROLES["retention"])]  # the same audited path, the same login


def registry_classes():
    from erasure import registry

    return registry.anonymized_classes(DECIDED)


def test_9kg_25_missing_corrupt_or_stale_erasure_evidence_keeps_the_restore_held(privileged_reset, decided, settings):
    grace = subject()
    erase(privileged_reset, grace.public_ref)
    head = record.head_string()
    place_hold(privileged_reset)
    conn = privileged_reset.connect("retention")
    settings.CATALYST_ERASURE_KEY = ""  # the key is not mounted: nothing can be verified
    with pytest.raises(service.Refused, match="record_key_missing"):
        replay.replay(conn, head, rows=DECIDED)
    settings.CATALYST_ERASURE_KEY = KEY
    with pytest.raises(service.Refused, match="registry_undecided"):  # the shipped, undecided registry
        replay.replay(conn, head, rows={n: {"treatment": "undecided", "retention": "undecided"} for n in DECIDED})
    assert replay.current_state() == "unreplayed"
    assert replay.replay(conn, head, rows=DECIDED)["already"] == 1
    assert replay.current_state() == "replayed"
    # An erasure made while the restore is held (a later entry) is not covered: stale until the next replay.
    opal = subject("opal@example.test", "Opal Example")
    erase(privileged_reset, opal.public_ref)
    assert replay.current_state() == "stale"
    from config import post_restore

    assert post_restore.erasure_replay_problem() == "stale"
    assert replay.replay(conn, record.head_string(), rows=DECIDED)["already"] == 2
    assert replay.current_state() == "replayed"
    # A marker for a later restore that does not verify (written without the key) is never taken as a replay.
    journal.append("restore", "restore:test", {"backup_seq": 0, "backup_head": "", "backup_journal_id": ""})
    assert replay.current_state() == "unreplayed"
    seq = replay.restore_seq(journal.read())
    journal.append(replay.MARKER, replay.marker_key(seq), {"restore": seq, "through": 10**6, "subjects": 0, "erased": 0,
                                                          "already": 0, "absent": 0, "mismatched": 0, "phase": "done",
                                                          "mac": "a" * 64})
    assert replay.current_state() == "forged_marker"
    # A forged erasure entry refuses the whole replay.
    journal.append("erasure_handoff", f"erasure:{uuid.uuid4()}", {"provider": "mail_sent", "completed_on": "2026-10-24",
                                                                  "phase": "done", "mac": "b" * 64})
    with pytest.raises(service.Refused, match="record_forged_entry"):
        replay.replay(conn, record.head_string(), rows=DECIDED)
    assert replay.current_state() == "forged_marker"


def test_9kg_25_an_interrupted_replay_writes_no_marker_and_the_next_run_finishes(privileged_reset, decided, monkeypatch):
    for email, name in (("grace@example.test", "Grace Example"), ("opal@example.test", "Opal Example")):
        erase(privileged_reset, subject(email, name).public_ref)
    head = record.head_string()
    place_hold(privileged_reset)

    def crash(*args, **kwargs):
        raise Crash("killed before the marker")
    real = replay.mark
    monkeypatch.setattr(replay, "mark", crash)
    with pytest.raises(Crash):
        replay.replay(privileged_reset.connect("retention"), head, rows=DECIDED)
    assert replay.current_state() == "unreplayed"  # no marker: the review and the lift still refuse
    monkeypatch.setattr(replay, "mark", real)
    finished = replay.replay(privileged_reset.connect("retention"), head, rows=DECIDED)
    assert (finished["subjects"], finished["already"], finished["erased"]) == (2, 2, 0)
    assert replay.current_state() == "replayed"


def test_9kg_25_an_erased_subject_left_open_after_the_journal_replay_holds_the_lift_until_the_owner_resolves_it(
        privileged_reset, decided, tmp_path):
    """A closure the journal did not carry: the replay erased the person, the review cancels the work and opens one
    item for the owner instead of a link, a setup or a revocation round, and the lift waits for it."""
    grace = subject(stage="submitted")
    work = queued_work(grace)
    Application.objects.filter(pk=grace.pk).update(stage="withdrawn")
    PendingAction.objects.filter(pk=work.pk).update(status="done")
    erase(privileged_reset, grace.public_ref)
    owner = privileged_reset.connect("owner", autocommit=True)
    owner.execute("UPDATE applications_application SET stage = 'submitted' WHERE id = %s", [grace.pk])  # as restored
    owner.execute("UPDATE workflow_pendingaction SET status = 'queued' WHERE id = %s", [work.pk])
    place_hold(privileged_reset)
    replay.replay(privileged_reset.connect("retention"), record.head_string(), rows=DECIDED)
    sent = tmp_path / "sent"
    sent.mkdir()
    env = {**SENT, "CATALYST_TEST_SENT_DIR": str(sent)}
    reviewed, review = run_post_restore(replayed=False, **env)
    assert reviewed.returncode == 0, reviewed.stderr
    assert (review["erased_subjects_open"], review["erased_actions_cancelled"]) == (1, 1)
    assert [i.split(":")[0] for i in review["effect_items_open"]] == ["restore_effect_erased_subject_open"]
    assert review["confirmation_links_closed"] == 1  # the link closes, and no item asks anyone to write to her
    assert owner.execute("SELECT count(*) FROM correspondence_staffitem WHERE reason_code = 'restore_confirmation_link_closed'"
                         ).fetchone()[0] == 0
    refused, _ = run_post_restore(*LIFT, replayed=False, **env)
    assert refused.returncode == 1 and "effects are unresolved" in refused.stderr, refused.stderr


def test_9kg_25_the_replay_command_never_runs_in_a_web_or_worker_process_or_beside_the_custody_key(settings):
    from config import runtime

    runtime.declare_process("web")
    try:
        with pytest.raises(SystemExit):
            call_command("catalyst_erasure_replay", "--expect-head", "none")
    finally:
        runtime.declare_process("management")
    settings.CATALYST_CUSTODY_WRAPPING_KEY = "0" * 64
    with pytest.raises(SystemExit):
        call_command("catalyst_erasure_replay", "--expect-head", "none")


def test_9kg_25_the_drill_command_is_synthetic_only_and_traces_rows_by_a_marker(privileged_reset, settings):
    subject("trace-marker-0123@example.test", "Trace Example")
    traced = support.manage_as_owner("catalyst_erasure_drill", "trace", "--needle", "trace-marker-0123")  # as in the drill
    assert json.loads(traced.stdout.strip().splitlines()[-1])["rows"] >= 2
    settings.CATALYST_ENV = "production"
    with pytest.raises(CommandError, match="synthetic"):
        call_command("catalyst_erasure_drill", "trace", "--needle", "trace-marker-0123")


def test_9kg_25_the_restore_drill_pins_its_erasure_replay_legs():
    """The drill runs the replay through the real staging stacks on the dev box; this gate pins its shape only: the
    review refused before the replay, the replay as the retention login with the erasure key (head `none` on the main
    leg; on the custody leg a real erasure after the backup, a refused head, the replay, its control and a second
    harmless run), the review and lift holding the key, a backup afterwards, and the web hold stated as procedural."""
    from pathlib import Path

    script = (Path(__file__).resolve().parent.parent / "scripts" / "restore_drill.sh").read_text()
    for line in ("CATALYST_DB_USER=catalyst_retention", "erasure-secrets", "catalyst_erasure_replay --expect-head none",
                 "erasure replay missing (unreplayed)", "catalyst_erasure_drill erase --subject",
                 'catalyst_erasure_drill replay --expect-head "$erasure_head"', "record_journal_mismatch",
                 "a second replay is harmless", "positive control: the applicant nobody erased",
                 "the lift keeps the hold for the missing envelope evidence, not for the erasure",
                 "a backup after the erasure and its replay runs",
                 "BY DESIGN the restore hold is procedural for the web process", "/run/secrets/erasure_key:ro\" restore"):
        assert line in script, line
