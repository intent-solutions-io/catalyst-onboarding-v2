"""9kg.69: the custody wrapping key is rotated (every live data key rewrapped under a new one) and the old key retired,
so a surviving remnant of an erased document's wrapped key has no key left that opens it (security review of PR
#102). Proved against real key directories in each test's own temporary directory; every key and document is synthetic.
"""

import secrets

import pytest

from agreements import keystore, storage
from agreements.management.commands import catalyst_custody_drill as drill
from config import guards
from erasure import record
from tests.test_custody_encryption import command, custody  # noqa: F401  (fixture)
from tests.test_erasure import subject
from workflow import journal


def documents(n=3):
    out = []
    for i in range(n):
        app = subject(email=f"rotation-{i}@example.test", name=f"Rotation Example {i}")
        out.append(drill.synthetic_document(app, f"%PDF-1.7 synthetic rotation {i}".encode()))
    return out


def opens(document) -> bool:
    try:
        data = storage.read(document.storage_key, document.sha256, document.size, document.envelope)
    except storage.StorageError:
        return False
    return storage.sha256(data) == document.sha256


def wrapped_ids(ref) -> set:
    primary, mirror = keystore.directories()
    return {keystore.wrapped_by(keystore._read(d, ref)) for d in (primary, mirror)}


def head():
    return record.head_string() if any(e.kind == keystore.DESTROYED or e.kind.startswith("erasure_")
                                       for e in journal.read()) else "none"


@pytest.mark.django_db
def test_9kg_69_rotation_rewraps_every_live_key_keeps_every_document_open_and_never_revives_a_destroyed_one(
        custody, settings):
    kept = documents(3)
    erased = drill.synthetic_document(subject(email="erased@example.test", name="Other Example"), b"%PDF-1.7 erased")
    keystore.destroy(str(erased.application.public_ref), [erased.envelope.key_ref])
    old = keystore.wrapping_key()
    old_id = keystore.wrapping_key_id(old)
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = secrets.token_hex(32)
    new_id = keystore.wrapping_key_id(bytes.fromhex(settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY))
    code, report = command("catalyst_custody_keys", "--rotate", "--expect-head", head())
    assert code == 0, report
    assert (report["keys"], report["rewrapped"], report["documents_opened"], report["documents_failed"]) == (3, 6, 3, 0)
    assert (report["from_key"], report["to_key"]) == (old_id, new_id)
    assert all(wrapped_ids(d.envelope.key_ref) == {new_id} for d in kept)  # both copies, under the new key only
    primary, mirror = keystore.directories()
    assert erased.envelope.key_ref not in keystore._listing(primary) | keystore._listing(mirror)  # never rewrapped
    # The owner makes the next key the current one and removes the next-key file; every document still opens.
    settings.CATALYST_CUSTODY_WRAPPING_KEY, settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = (
        settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY, "")
    assert all(opens(d) for d in kept)
    with pytest.raises(storage.StorageError, match="custody_key_destroyed"):
        storage.read(erased.storage_key, erased.sha256, erased.size, erased.envelope)
    phases = [e.data["phase"] for e in journal.read() if e.kind == "custody_rotation"]
    assert phases == ["prepare", "done"]
    assert all(set(e.data) <= {"from_key", "to_key", "keys", "documents", "phase"}
               for e in journal.read() if e.kind == "custody_rotation")  # key ids and counts, never a key


@pytest.mark.django_db
def test_9kg_69_after_retirement_no_key_opens_a_remnant_wrapped_under_the_old_key(custody, settings):
    document = documents(1)[0]
    ref = document.envelope.key_ref
    primary, _ = keystore.directories()
    remnant = keystore._read(primary, ref)  # a copy that survives somewhere: a snapshot, unlinked blocks, an archive
    old = keystore.wrapping_key()
    old_id = keystore.wrapping_key_id(old)
    assert keystore._unwrap(old, ref, remnant)  # before rotation, the remnant plus the old key opens the document
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = secrets.token_hex(32)
    assert command("catalyst_custody_keys", "--rotate", "--expect-head", head())[0] == 0
    code, report = command("catalyst_custody_keys", "--retire-old-key", old_id, "--expect-head", head())
    assert code == 1 and report["refused"] == "next_wrapping_key_present"  # the switch to the new key comes first
    settings.CATALYST_CUSTODY_WRAPPING_KEY, settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = (
        settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY, "")
    # A stray old-key copy put back into the store keeps the old key from being retired.
    keystore._replace(primary, ref, remnant)
    code, report = command("catalyst_custody_keys", "--retire-old-key", old_id, "--expect-head", head())
    assert code == 1 and report["refused"] == "rotation_incomplete"
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = settings.CATALYST_CUSTODY_WRAPPING_KEY
    settings.CATALYST_CUSTODY_WRAPPING_KEY = old.hex()  # finish it the supported way: the same rotation again
    assert command("catalyst_custody_keys", "--rotate", "--expect-head", head())[0] == 0
    settings.CATALYST_CUSTODY_WRAPPING_KEY, settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = (
        settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY, "")
    code, report = command("catalyst_custody_keys", "--retire-old-key", old_id, "--expect-head", head())
    assert code == 0 and report["retired_key"] == old_id, report
    # The current key cannot open the remnant; only the old key could, and the owner has destroyed it everywhere.
    with pytest.raises(keystore.KeyStoreError, match="wrapping_key_mismatch"):
        keystore._unwrap(keystore.wrapping_key(), ref, remnant)
    assert opens(document)
    assert [e.key for e in journal.read() if e.kind == "custody_rotation"][-1] == f"custody_rotation_retired:{old_id}"
    code, report = command("catalyst_custody_keys", "--retire-old-key", keystore.wrapping_key_id(keystore.wrapping_key()),
                           "--expect-head", head())
    assert code == 1 and report["refused"] == "retired_key_still_current"


@pytest.mark.django_db
def test_9kg_69_an_interrupted_rotation_leaves_every_document_openable_and_the_same_command_finishes_it(
        custody, settings, monkeypatch):
    docs = documents(3)
    old = keystore.wrapping_key()
    upcoming = secrets.token_hex(32)
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = upcoming
    real, calls = keystore._replace, []

    def crash(path, ref, blob):
        if len(calls) == 2:
            raise KeyboardInterrupt  # the operator's terminal closed mid-run
        calls.append(ref)
        real(path, ref, blob)
    monkeypatch.setattr(keystore, "_replace", crash)
    with pytest.raises(KeyboardInterrupt):
        command("catalyst_custody_keys", "--rotate", "--expect-head", head())
    monkeypatch.setattr(keystore, "_replace", real)
    new = bytes.fromhex(upcoming)
    ids = {keystore.wrapping_key_id(old): old, keystore.wrapping_key_id(new): new}
    primary, mirror = keystore.directories()
    mixed = set()
    for d in docs:  # in between, every copy is under one of the two keys the owner still holds, and opens under it
        for directory in (primary, mirror):
            blob = keystore._read(directory, d.envelope.key_ref)
            by = keystore.wrapped_by(blob)
            mixed.add(by)
            assert keystore._unwrap(ids[by], d.envelope.key_ref, blob)
    assert mixed == set(ids)  # the run stopped part way
    assert [e.data["phase"] for e in journal.read() if e.kind == "custody_rotation"] == ["prepare"]  # not done
    code, report = command("catalyst_custody_keys", "--rotate", "--expect-head", head())
    assert code == 0 and report["already_rotated"] == 2 and report["rewrapped"] == 4, report
    settings.CATALYST_CUSTODY_WRAPPING_KEY, settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = upcoming, ""
    assert all(opens(d) for d in docs)


@pytest.mark.django_db
def test_9kg_69_rotation_refuses_without_the_next_key_the_head_or_aligned_directories(custody, settings):
    document = documents(1)[0]
    code, report = command("catalyst_custody_keys", "--rotate", "--expect-head", head())
    assert code == 1 and report["refused"] == "next_wrapping_key_missing"
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = settings.CATALYST_CUSTODY_WRAPPING_KEY
    code, report = command("catalyst_custody_keys", "--rotate", "--expect-head", head())
    assert code == 1 and report["refused"] == "next_wrapping_key_same"
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = secrets.token_hex(32)
    assert command("catalyst_custody_keys", "--rotate")[1]["refused"] == "expect_head_required"
    _, mirror = keystore.directories()
    keystore._unlink(mirror, document.envelope.key_ref)  # the mirror lost a key: recover first
    code, report = command("catalyst_custody_keys", "--rotate", "--expect-head", head())
    assert code == 1 and report["refused"] == "key_needs_recovery"
    assert keystore.wrapped_by(keystore._read(keystore.directories()[0], document.envelope.key_ref)) == \
        keystore.wrapping_key_id(keystore.wrapping_key())  # nothing was rewrapped


def test_9kg_69_only_the_owner_run_rotation_may_hold_the_next_key(settings):
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = secrets.token_hex(32)
    for kind in ("web", "worker", "reconcile"):
        assert any("held only by the owner-run rotation" in p for p in guards.custody_key_problems(settings, kind)), kind
    assert not any("NEXT_WRAPPING_KEY" in p for p in guards.custody_key_problems(settings, "management"))
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = "0" * 64
    assert any("64 lower-case hex" in p for p in guards.custody_key_problems(settings, "management"))
    assert "CATALYST_CUSTODY_NEXT_WRAPPING_KEY" in guards.SECRET_ENV_NAMES  # a secret file, never the environment


def test_9kg_69_the_rotation_runbook_has_a_custody_row():
    from pathlib import Path

    runbook = (Path(__file__).resolve().parent.parent / "000-docs" / "027-OD-OPNS-secret-rotation-runbook.md").read_text()
    for line in ("custody_next_wrapping_key", "--rotate --expect-head", "--retire-old-key", "escrow"):
        assert line in runbook, line


# --- the security review of PR #104 -------------------------------------------------------------------------------

@pytest.mark.django_db
def test_9kg_69_an_interrupted_replace_leaves_no_temporary_copy_and_a_destruction_removes_one_anyway(
        custody, settings, monkeypatch):
    """F1: a rotation's temporary copy of a wrapped key never outlives the run, and never a destruction."""
    import os

    document = documents(1)[0]
    ref = document.envelope.key_ref
    primary, mirror = keystore.directories()
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = secrets.token_hex(32)
    real_rename = os.rename

    def disk_full(*args, **kwargs):
        raise OSError("no space left")
    monkeypatch.setattr(os, "rename", disk_full)
    code, report = command("catalyst_custody_keys", "--rotate", "--expect-head", head())
    assert code == 1 and report["refused"] == "key_store_unavailable"
    monkeypatch.setattr(os, "rename", real_rename)
    assert keystore.strays() == 0  # the temporary copy was removed on the failure
    # A leftover from a harder crash (the process killed before its cleanup) goes with the key's destruction.
    (primary / f"{ref}.key.rotating").write_bytes(keystore._read(primary, ref))
    (primary / f"{ref}.key.rotating").chmod(0o600)
    assert keystore.strays() == 1
    keystore.destroy(str(document.application.public_ref), [ref])
    assert keystore.strays() == 0 and not (primary / f"{ref}.key.rotating").exists()
    assert keystore._read(mirror, ref) is None


@pytest.mark.django_db
def test_9kg_69_a_rotation_holds_the_store_exclusively_and_a_second_one_is_refused(custody, settings):
    """F2 and F5: creation and destruction take the store lock shared; a rotation takes it exclusively."""
    documents(1)
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = secrets.token_hex(32)
    with keystore.store_lock(exclusive=False):  # a key being created or destroyed elsewhere
        code, report = command("catalyst_custody_keys", "--rotate", "--expect-head", head())
    assert code == 1 and report["refused"] == "custody_operation_in_progress"
    assert command("catalyst_custody_keys", "--rotate", "--expect-head", head())[0] == 0


@pytest.mark.django_db
def test_9kg_69_the_next_key_is_refused_outside_the_owner_run_management_process(custody, settings):
    """F3: a worker declares its kind after the start-up guards ran, so the key itself refuses there too."""
    from django.core.management import call_command
    from django.core.management.base import CommandError

    from config import runtime

    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = secrets.token_hex(32)
    runtime.declare_process("worker")
    try:
        with pytest.raises(keystore.KeyStoreError, match="next_wrapping_key_not_allowed"):
            keystore.next_wrapping_key()
    finally:
        runtime.declare_process("management")
    with pytest.raises(CommandError, match="held only by the owner-run rotation"):
        call_command("run_worker", "--exit-when-idle")
    runtime.declare_process("management")
    settings.SECRET_KEY = settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = "ab" * 32  # the same value as another secret
    assert any("every other key" in p for p in guards.custody_key_problems(settings, "management"))


@pytest.mark.django_db
def test_9kg_69_retirement_needs_a_finished_rotation_from_that_key_and_a_clean_store(custody, settings):
    """F4: no id no rotation finished, and no stray file or destroyed key's file left behind."""
    document = documents(1)[0]
    old_id = keystore.wrapping_key_id(keystore.wrapping_key())
    code, report = command("catalyst_custody_keys", "--retire-old-key", "a" * 16, "--expect-head", head())
    assert code == 1 and report["refused"] == "rotation_not_done"
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = secrets.token_hex(32)
    assert command("catalyst_custody_keys", "--rotate", "--expect-head", head())[0] == 0
    settings.CATALYST_CUSTODY_WRAPPING_KEY, settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = (
        settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY, "")
    primary, _ = keystore.directories()
    (primary / "left-behind").write_bytes(b"x")
    (primary / "left-behind").chmod(0o600)
    code, report = command("catalyst_custody_keys", "--retire-old-key", old_id, "--expect-head", head())
    assert code == 1 and report["refused"] == "rotation_incomplete"
    (primary / "left-behind").unlink()
    assert command("catalyst_custody_keys", "--retire-old-key", old_id, "--expect-head", head())[0] == 0
    assert opens(document)


@pytest.mark.django_db
def test_9kg_69_copies_that_disagree_on_the_data_key_are_never_rotated_into_agreement(custody, settings):
    """F6: the mirror and the primary must hold the same data key."""
    document = documents(1)[0]
    ref = document.envelope.key_ref
    _, mirror = keystore.directories()
    keystore._replace(mirror, ref, keystore._wrap(keystore.wrapping_key(), ref, b"\x01" * 32))
    settings.CATALYST_CUSTODY_NEXT_WRAPPING_KEY = secrets.token_hex(32)
    code, report = command("catalyst_custody_keys", "--rotate", "--expect-head", head())
    assert code == 1 and report["refused"] == "rotation_incomplete"
    assert [e.data["phase"] for e in journal.read() if e.kind == "custody_rotation"] == ["prepare"]
