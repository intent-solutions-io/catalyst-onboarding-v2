"""Recovery of erased addresses absent from the backup's identity tables (9kg.71)."""

import hashlib
import json
import subprocess
import sys
import uuid

import pytest
from psycopg import errors

from correspondence.models import InboundMessage
from erasure import record, registry, replay, service
from tests.test_backup_commands import (
    admin,
    drop,
    new_database,
    run_backup,
    run_restore,
)
from tests.test_erasure import AUTHORITY, DECIDED, KEY, REASON, decided, erase, subject  # noqa: F401
from tests.test_erasure_replay import place_hold, printed, replay_command


def orphan(owner, address):
    mail = InboundMessage.objects.create(
        mailbox_ref="synthetic-mailbox",
        message_id_header=f"<{uuid.uuid4()}@example.test>",
        from_address=address,
        from_normalized=address,
        size=10,
        original_sha256=uuid.uuid4().hex * 2,
        derived_text=f"A synthetic message from {address}",
        attachments=[{"name": "synthetic.txt", "size": 10}],
    )
    bucket = hashlib.sha256(f"intake-address:{address}".encode()).hexdigest()
    owner.execute(
        "INSERT INTO accounts_requestthrottle (key, count, window_start, updated_at)"
        " VALUES (%s, 1, now(), now())",
        [bucket],
    )
    return mail.pk, bucket


def test_9kg_71_real_restore_replays_unmatched_mail_and_its_counter(
    privileged_reset, decided, tmp_path
):
    owner = privileged_reset.connect("owner", autocommit=True)
    erased_mail, erased_bucket = orphan(owner, "orphan@example.test")
    control_mail, control_bucket = orphan(owner, "control@example.test")
    sets, custody = tmp_path / "sets", tmp_path / "custody"
    sets.mkdir()
    custody.mkdir(mode=0o700)
    saved = run_backup(sets, custody)
    assert saved.returncode == 0, saved.stderr
    later = subject("orphan@example.test", "Later Example")
    assert erase(privileged_reset, later.public_ref).status == "erased"
    head = record.head_string()
    database = new_database()
    try:
        restored = run_restore(database, sets / "set", tmp_path / "restored")
        assert restored.returncode == 0, restored.stderr
        with admin(database) as conn:
            for table in (
                "applications_application",
                "applications_invitation",
                "applications_memberagreementonfile",
            ):
                assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
            assert conn.execute(
                "SELECT from_normalized FROM correspondence_inboundmessage WHERE id = %s",
                [erased_mail],
            ).fetchone() == ("orphan@example.test",)
        result = replay_command(database, head)
        assert result.returncode == 0, result.stderr
        report = printed(result)
        assert (report["erased"], report["absent"], report["matched_by_key"]) == (
            1,
            0,
            1,
        )
        assert "orphan@example.test" not in result.stdout + result.stderr
        with admin(database) as conn:
            assert conn.execute(
                "SELECT from_normalized, derived_text, attachments"
                " FROM correspondence_inboundmessage WHERE id = %s",
                [erased_mail],
            ).fetchone() == ("[erased]", "[erased]", [])
            assert (
                conn.execute(
                    "SELECT count(*) FROM accounts_requestthrottle WHERE key = %s",
                    [erased_bucket],
                ).fetchone()[0]
                == 0
            )
            assert conn.execute(
                "SELECT from_normalized FROM correspondence_inboundmessage WHERE id = %s",
                [control_mail],
            ).fetchone() == ("control@example.test",)
            assert (
                conn.execute(
                    "SELECT count(*) FROM accounts_requestthrottle WHERE key = %s",
                    [control_bucket],
                ).fetchone()[0]
                == 1
            )
        repeated = replay_command(database, head)
        assert repeated.returncode == 0, repeated.stderr
        assert printed(repeated)["erased"] == 0
    finally:
        drop(database)


def recorded_erasure(address):
    ref, secret = uuid.uuid4(), KEY.encode()
    digest, kid = record.subject_hash(address, secret), record.key_id(secret)
    record.append_intent(
        ref,
        digest,
        kid,
        AUTHORITY,
        REASON,
        registry.anonymized_classes(DECIDED),
        [],
        [],
        secret,
    )
    record.append_complete(ref, digest, kid, "erased", 1, secret)
    return str(ref)


def test_9kg_71_retention_reads_only_sender_and_counter_key_and_cannot_write(
    privileged_reset,
):
    owner = privileged_reset.connect("owner", autocommit=True)
    mail, bucket = orphan(owner, "orphan@example.test")
    conn = privileged_reset.connect("retention")
    assert conn.execute(
        "SELECT from_normalized FROM correspondence_inboundmessage"
    ).fetchall() == [("orphan@example.test",)]
    assert conn.execute("SELECT key FROM accounts_requestthrottle").fetchall() == [
        (bucket,)
    ]
    conn.rollback()
    for statement in (
        "SELECT derived_text FROM correspondence_inboundmessage",
        "SELECT attachments FROM correspondence_inboundmessage",
        "SELECT * FROM correspondence_inboundmessage",
        "SELECT count FROM accounts_requestthrottle",
        "DELETE FROM correspondence_inboundmessage",
        "DELETE FROM accounts_requestthrottle",
    ):
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(statement)
        conn.rollback()
    assert (
        owner.execute(
            "SELECT count(*) FROM correspondence_inboundmessage WHERE id = %s", [mail]
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize(
    "address",
    ["orphan@example.test", "a" * 64 + "@" + ("b" * 63 + ".") * 3 + "example.test"],
    ids=["ordinary", "long-intake-address"],
)
def test_9kg_71_counter_only_restore_requires_a_matching_private_hint_before_any_write(
    privileged_reset, decided, address
):
    owner = privileged_reset.connect("owner", autocommit=True)
    bucket = hashlib.sha256(f"intake-address:{address}".encode()).hexdigest()
    owner.execute(
        "INSERT INTO accounts_requestthrottle (key, count, window_start, updated_at) VALUES (%s, 1, now(), now())",
        [bucket],
    )
    ref = recorded_erasure(address)
    place_hold(privileged_reset)
    head = record.head_string()
    conn = privileged_reset.connect("retention")
    with pytest.raises(service.Refused, match="replay_address_required") as exc:
        replay.replay(conn, head, rows=DECIDED)
    assert exc.value.detail == [ref]
    with pytest.raises(service.Refused, match="replay_address_mismatch"):
        replay.replay(
            conn, head, rows=DECIDED, recovery_addresses={ref: "control@example.test"}
        )
    # Refuse both raw overflow and an address whose case folding expands beyond intake's limit.
    for invalid in ("a" * 321 + "@example.test", "\u00df" * 160 + "@example.test"):
        with pytest.raises(service.Refused, match="replay_addresses_malformed"):
            replay.replay(conn, head, rows=DECIDED, recovery_addresses={ref: invalid})
    assert record.head_string() == head
    assert owner.execute("SELECT count(*) FROM erasure_erasureaudit").fetchone()[0] == 0
    assert owner.execute("SELECT key FROM accounts_requestthrottle").fetchall() == [
        (bucket,)
    ]
    report = replay.replay(
        conn, head, rows=DECIDED, recovery_addresses={ref: address.upper()}
    )
    assert report["erased"] == 1 and report["matched_by_key"] == 1
    assert (
        owner.execute("SELECT count(*) FROM accounts_requestthrottle").fetchone()[0]
        == 0
    )
    assert address not in json.dumps(report) + json.dumps(
        [e.data for e in record._read()]
    )
    assert replay.replay(conn, record.head_string(), rows=DECIDED)["erased"] == 0


def test_9kg_71_tombstoned_identity_does_not_hide_restored_orphan_mail(
    privileged_reset, decided
):
    app = subject("orphan@example.test", "Orphan Example")
    erase(privileged_reset, app.public_ref)
    owner = privileged_reset.connect("owner", autocommit=True)
    mail, bucket = orphan(owner, "orphan@example.test")
    place_hold(privileged_reset)
    report = replay.replay(
        privileged_reset.connect("retention"), record.head_string(), rows=DECIDED
    )
    assert report["erased"] == 1 and report["matched_by_key"] == 1
    assert owner.execute(
        "SELECT from_normalized FROM correspondence_inboundmessage WHERE id = %s",
        [mail],
    ).fetchone() == ("[erased]",)
    assert (
        owner.execute(
            "SELECT count(*) FROM accounts_requestthrottle WHERE key = %s", [bucket]
        ).fetchone()[0]
        == 0
    )


def test_9kg_71_command_reads_private_hints_from_stdin_without_echoing_them(
    privileged_reset, decided
):
    from tests import support
    from tests.test_erasure_lookup import _env

    owner = privileged_reset.connect("owner", autocommit=True)
    orphan(owner, "orphan@example.test")
    ref = recorded_erasure("orphan@example.test")
    place_hold(privileged_reset)
    script = """
import json, sys, django
django.setup()
from erasure import registry
registry.REGISTRY = json.loads(sys.argv[1])
from django.core.management import call_command
call_command("catalyst_erasure_replay", "--expect-head", sys.argv[2], "--recovery-addresses-stdin")
"""

    def invoke(raw):
        return subprocess.run(
            [sys.executable, "-c", script, json.dumps(DECIDED), record.head_string()],
            cwd=support.ROOT,
            env=support.child_env(**_env("retention"), CATALYST_ERASURE_KEY=KEY),
            input=raw,
            text=True,
            capture_output=True,
            timeout=60,
        )

    result = invoke(json.dumps({ref: "orphan@example.test"}))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["erased"] == 1
    assert "orphan@example.test" not in result.stdout + result.stderr
    for raw in ('{"bad":', '"' + "x" * 262145 + '"', '["orphan@example.test"]', "null"):
        result = invoke(raw)
        assert result.returncode == 1
        assert "replay_addresses_malformed" in result.stderr
        assert "orphan@example.test" not in result.stdout + result.stderr
