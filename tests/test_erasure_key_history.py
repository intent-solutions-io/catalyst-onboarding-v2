"""Owner-held historical erasure keys preserve signed records, interrupted erasures and real restores."""

import json
import os
import sys
import uuid
from dataclasses import replace
from datetime import date

import pytest

from agreements import keystore
from applications.models import Application
from config import guards
from erasure import record, registry, replay, service
from tests import support
from tests.test_backup_commands import (
    admin,
    drop,
    new_database,
    run_backup,
    run_restore,
)
from tests.test_custody_encryption import custody  # noqa: F401
from tests.test_erasure import AUTHORITY, DECIDED, KEY, REASON, decided, erase, subject  # noqa: F401
from tests.test_erasure_replay import REPLAY_PROBE, printed
from tests.test_erasure_replay_orphans import orphan
from workflow import journal

NEW = "synthetic-rotated-erasure-key-for-tests-only-0123456789abcdef"  # gitleaks:allow


def rotate(settings, old=KEY):
    settings.CATALYST_ERASURE_KEY = NEW
    settings.CATALYST_ERASURE_PREVIOUS_KEYS = [old]


def test_key_history_verifies_old_records_and_signs_new_work_with_current_key(
    privileged_reset, decided, settings
):
    old = subject()
    erase(privileged_reset, old.public_ref)
    # The historical handoff shape had no key identifier.
    data = {
        "provider": "mail_sent",
        "completed_on": date.today().isoformat(),
        "phase": "done",
    }
    key = record.entry_key(old.public_ref)
    data["mac"] = record.entry_mac("erasure_handoff", key, data, KEY.encode())
    journal.append("erasure_handoff", key, data)
    replay.mark(journal.read(), KEY.encode(), subjects=1, erased=1)
    head = record.head_string()
    settings.CATALYST_ERASURE_KEY = NEW
    with pytest.raises(record.RecordError, match="forged_entry"):
        record.verify(head)
    assert replay.current_state() == "forged_marker"
    rotate(settings)
    assert record.verify(head)["erased"] == 1 and replay.current_state() == "replayed"
    states = record.fold(journal.read(), NEW.encode())
    found = {}
    replay._recovery_addresses(
        states, NEW.encode(), {str(old.public_ref): "grace@example.test"}, found
    )
    assert (
        "grace@example.test"
        in found[states[str(old.public_ref)].intent.data["subject"]]
    )
    with pytest.raises(service.Refused, match="replay_address_mismatch"):
        replay._recovery_addresses(
            states, NEW.encode(), {str(old.public_ref): "wrong@example.test"}, {}
        )
    newer = subject("newer@example.test", "Ada Other")
    erase(privileged_reset, newer.public_ref)
    service.handoff(old.public_ref, "mail_inbox", date.today().isoformat())
    recent = [e for e in journal.read() if e.key == record.entry_key(newer.public_ref)]
    recent.append(journal.read()[-1])
    assert all(e.data["key_id"] == record.key_id(NEW.encode()) for e in recent)
    assert all(record.verifies(e, NEW.encode()) for e in recent)
    assert record.verify(record.head_string())["erased"] == 2
    assert not record.fold(journal.read(), NEW.encode())[
        str(old.public_ref)
    ].outstanding


@pytest.mark.parametrize("committed", [False, True])
def test_key_history_resumes_old_intents_without_changing_subject_hash(
    privileged_reset, decided, settings, monkeypatch, committed
):
    app = subject()
    if committed:
        real = record.append_complete

        def interrupted(*args, **kwargs):
            raise record.RecordError("unwritable")

        monkeypatch.setattr(record, "append_complete", interrupted)
        with pytest.raises(service.Refused, match="after_commit"):
            erase(privileged_reset, app.public_ref)
        monkeypatch.setattr(record, "append_complete", real)
    else:
        record.append_intent(
            app.public_ref,
            record.subject_hash(app.email_key, KEY.encode()),
            record.key_id(KEY.encode()),
            AUTHORITY,
            REASON,
            registry.anonymized_classes(DECIDED),
            [],
            [],
            KEY.encode(),
        )
    rotate(settings)
    outcome = erase(privileged_reset, app.public_ref)
    assert outcome.resumed and outcome.status in ("erased", "already_erased")
    state = record.fold(journal.read(), NEW.encode())[str(app.public_ref)]
    assert state.erased
    assert state.complete.data["key_id"] == record.key_id(KEY.encode())
    assert state.complete.data["mac_key_id"] == record.key_id(NEW.encode())
    assert state.complete.data["subject"] == state.intent.data["subject"]
    assert state.complete.data["mac"] == record.entry_mac(
        state.complete.kind, state.complete.key, state.complete.data, NEW.encode()
    )
    assert Application.objects.get(pk=app.pk).email == "[erased]"
    assert record.verify(record.head_string())["erased"] == 1


def test_key_history_unknown_or_tampered_key_ids_never_fall_back(
    privileged_reset, decided, settings
):
    app = subject()
    erase(privileged_reset, app.public_ref)
    entry = next(e for e in journal.read() if e.kind == "erasure_intent")
    rotate(settings)
    for changed in (
        {"key_id": "0" * 16},
        {"mac_key_id": "0" * 16},
        {"key_id": []},
        {"mac_key_id": None},
        {"subject": "0" * 64},
    ):
        bad = replace(entry, data={**entry.data, **changed})
        if "subject" not in changed:
            # Even a valid MAC under a held key cannot authorize a different or malformed declared key id.
            bad.data["mac"] = record.entry_mac(
                bad.kind, bad.key, bad.data, KEY.encode()
            )
        assert not record.verifies(bad, NEW.encode())
        forged = []
        assert record.fold([bad], NEW.encode(), forged) == {} and forged == [
            str(app.public_ref)
        ]
    settings.CATALYST_ERASURE_PREVIOUS_KEYS = []
    assert not record.verifies(entry, NEW.encode())


def test_key_history_recovery_finishes_legacy_custody_destructions(custody, settings):
    old = settings.CATALYST_ERASURE_KEY
    ref, _, _ = keystore.create()
    data = {"subject": str(uuid.uuid4()), "phase": "prepare"}
    key = f"custody_key:{ref}"
    data["mac"] = record.entry_mac(keystore.DESTROYED, key, data, old.encode())
    journal.append(keystore.DESTROYED, key, data)
    head = record.head_string()
    rotate(settings, old)
    assert keystore.recover(head)["destruction_finished"] == 2
    assert keystore.present(ref) == (False, False)
    newer, _, _ = keystore.create()
    keystore.destroy(str(uuid.uuid4()), [newer])
    entry = journal.read()[-1]
    assert entry.data["key_id"] == record.key_id(NEW.encode())
    assert keystore._verified_destroyed(journal.read()) == {ref, newer}
    settings.CATALYST_ERASURE_PREVIOUS_KEYS = []
    with pytest.raises(keystore.KeyStoreError, match="forged_entry"):
        keystore.recover(record.head_string())


def test_key_history_real_restore_replays_old_orphan_and_current_subject(
    privileged_reset, decided, settings, tmp_path
):
    owner = privileged_reset.connect("owner", autocommit=True)
    orphan_id, bucket = orphan(owner, "historical@example.test")
    newer = subject("current@example.test", "Ada Two")
    sets, custody_dir = tmp_path / "sets", tmp_path / "custody"
    sets.mkdir()
    custody_dir.mkdir(mode=0o700)
    saved = run_backup(sets, custody_dir)
    assert saved.returncode == 0, saved.stderr
    old = subject("historical@example.test", "Hedy Example")
    erase(privileged_reset, old.public_ref)
    rotate(settings)
    erase(privileged_reset, newer.public_ref)
    database = new_database()
    try:
        restored = run_restore(database, sets / "set", tmp_path / "restored")
        assert restored.returncode == 0, restored.stderr
        result = support.run(
            [
                sys.executable,
                "-c",
                REPLAY_PROBE,
                json.dumps(DECIDED),
                record.head_string(),
            ],
            timeout=120,
            CATALYST_DB_NAME=database,
            CATALYST_DB_USER=settings.CATALYST_DB_ROLES["retention"],
            CATALYST_DB_PASSWORD=os.environ["CATALYST_DB_RETENTION_PASSWORD"],
            CATALYST_ERASURE_KEY=NEW,
            CATALYST_ERASURE_PREVIOUS_KEYS=KEY,
        )
        assert result.returncode == 0, result.stderr
        assert printed(result)["erased"] == 2 and printed(result)["matched_by_key"] == 1
        with admin(database) as conn:
            assert conn.execute(
                "SELECT email FROM applications_application WHERE public_ref=%s",
                [newer.public_ref],
            ).fetchone() == ("[erased]",)
            assert conn.execute(
                "SELECT from_normalized FROM correspondence_inboundmessage WHERE id=%s",
                [orphan_id],
            ).fetchone() == ("[erased]",)
            assert conn.execute(
                "SELECT count(*) FROM accounts_requestthrottle WHERE key=%s", [bucket]
            ).fetchone() == (0,)
        assert replay.current_state() == "replayed"
    finally:
        drop(database)


def test_key_history_secret_file_loading_and_process_boundary(settings, tmp_path):
    for name, value in {
        "secret_key": settings.SECRET_KEY,
        "verification_key": settings.CATALYST_VERIFICATION_KEY,
        "db_password": "synthetic-password",
        "erasure_key": NEW,
        "erasure_previous_keys": KEY + "\n",
    }.items():
        (tmp_path / name).write_text(value)
    probe = "from config import settings as s; from erasure import record; print(record.key_id(s.CATALYST_ERASURE_KEY.encode())); print(len(s.CATALYST_ERASURE_PREVIOUS_KEYS))"
    result = support.run(
        [sys.executable, "-c", probe], CATALYST_SECRETS_DIR=str(tmp_path)
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [record.key_id(NEW.encode()), "1"]
    settings.CATALYST_ERASURE_KEY = ""
    settings.CATALYST_ERASURE_PREVIOUS_KEYS = [KEY]
    for kind in ("web", "worker"):
        assert guards.erasure_key_problems(settings, kind)
    settings.CATALYST_PROCESS_ROLE = "fetcher"  # A fetcher declares the worker kind.
    assert guards.erasure_key_problems(settings, "worker")
    assert guards.erasure_key_problems(settings, "management") == []
    assert "CATALYST_ERASURE_PREVIOUS_KEYS" in guards.SECRET_ENV_NAMES
    settings.CATALYST_ERASURE_KEY = NEW
    settings.SECRET_KEY = "synthetic-shared-secret-for-reuse-check-0123456789"
    for keys, code in (
        (["short"], "key_weak"),
        ([settings.SECRET_KEY], "key_reused"),
        (KEY, "keys_malformed"),
    ):
        settings.CATALYST_ERASURE_PREVIOUS_KEYS = keys
        with pytest.raises(record.RecordError, match=code):
            record.key()
