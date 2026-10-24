"""9kg.34: the v2 custody copy of signed documents encrypted at rest, with per-document keys kept outside the
application backup's rollback domain, recoverable by the named holder and destroyable as an erasure step, so a restore
of an older backup cannot open a destroyed subject's document (026 section 6 option c; council 030 Q3 and Q4, D-51).

Proved against this run's PostgreSQL, real backups and restores (the 6B.7a commands as real processes) and the real
key directories in each test's own temporary directory. Every key, document and person here is synthetic.
"""

import json
import os
import secrets
import shutil
import sys
import uuid
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management import call_command

from agreements import custody_policy, keystore, services, storage
from agreements.management.commands import catalyst_custody_drill as drill
from agreements.models import CustodyEnvelope, StoredDocument
from config import backup as backup_module
from config import guards
from erasure import catalog, record, registry, service
from tests.test_agreement_custody import (  # noqa: F401  (fixture chain and helpers)
    a, activate, admitted, approve, c, custody_keys, d, ev, g, grant, h, issued, k, nda, of, p2, run_worker,
    sign_and_settle, tls,
)
from tests.test_backup_commands import admin, drop, new_database, run_backup, run_restore, signed  # noqa: F401
from tests.test_erasure import DECIDED, KEY, decided, erase, erasure_entries, subject  # noqa: F401
from workflow import journal

DESTROYING = {**DECIDED, "signed_documents": {"treatment": registry.DESTROY_KEY, "retention": "synthetic-p7y"}}
PLACEHOLDER = b"synthetic placeholder"  # inside the fake provider's PDF (tests/documenso_fake.py)


@pytest.fixture
def custody(settings, tmp_path):
    """Custody storage and its keys, without the agreement journey: for erasure and key-store tests."""
    settings.CATALYST_AGREEMENT_STORAGE_DIR = str(tmp_path / "custody")
    custody_keys(settings, tmp_path)
    return tmp_path / "custody"


def command(*args) -> tuple[int, dict]:
    out = StringIO()
    try:
        call_command(*args, stdout=out)
        code = 0
    except SystemExit as exc:
        code = exc.code
    return code, json.loads(out.getvalue().strip().splitlines()[-1])


# --- encrypt and retrieve ------------------------------------------------------------------------------------------

def test_9kg_34_a_signed_document_is_sealed_at_rest_under_its_own_key_and_retrieval_returns_the_recorded_plaintext(
        k, monkeypatch, settings):
    app = issued(k, monkeypatch)
    sign_and_settle(k, app, "nda")
    sign_and_settle(k, app, "user_agreement")
    documents = list(StoredDocument.objects.order_by("id"))
    assert len(documents) == 2
    refs = set()
    for document in documents:
        envelope = document.envelope
        sealed = (k.storage / envelope.storage_key).read_bytes()
        assert envelope.storage_key == document.storage_key and not envelope.migrated and envelope.scheme == keystore.SCHEME
        assert sealed.startswith(keystore.MAGIC) and b"%PDF" not in sealed and PLACEHOLDER not in sealed
        assert storage.sha256(sealed) == envelope.cipher_sha256 and len(sealed) == envelope.cipher_size
        assert envelope.cipher_sha256 != document.sha256  # the recorded hash stays the plaintext's
        assert keystore.present(envelope.key_ref) == (True, True)  # in the key directory and its mirror
        _, data = services.retrieve_document(str(document.public_id), k.agreement_decider, "Counsel review copy")
        assert storage.sha256(data) == document.sha256 and len(data) == document.size and PLACEHOLDER in data
        refs.add(envelope.key_ref)
    assert len(refs) == 2  # one key per document
    # The keys are outside the custody directory, and their files hold only the wrapped form.
    assert not [p for p in k.storage.iterdir() if p.suffix == ".key"]
    for ref in refs:
        for directory in (settings.CATALYST_CUSTODY_KEY_DIR, settings.CATALYST_CUSTODY_KEY_MIRROR_DIR):
            path = Path(directory) / f"{ref}.key"
            assert oct(path.stat().st_mode & 0o777) == "0o600"
            data_key = keystore.load(ref)
            assert data_key not in path.read_bytes() and data_key.hex().encode() not in path.read_bytes()
    # A sealed file opens only under its own key and its own name.
    first, second = documents
    sealed = (k.storage / first.storage_key).read_bytes()
    with pytest.raises(keystore.KeyStoreError, match="sealed_file_invalid"):
        keystore.open_sealed(sealed, first.storage_key, second.envelope.key_ref, first.sha256)
    with pytest.raises(keystore.KeyStoreError, match="sealed_file_invalid"):
        keystore.open_sealed(sealed, second.storage_key, first.envelope.key_ref, first.sha256)
    # Review of PR #102, F7: the scheme and the recorded plaintext hash are bound too, so a row that records another
    # hash never opens the file, and the refusal is the document's (corruption), not an outage.
    assert keystore.open_sealed(sealed, first.storage_key, first.envelope.key_ref, first.sha256)[:4] == b"%PDF"
    with pytest.raises(keystore.KeyStoreError, match="sealed_file_invalid"):
        keystore.open_sealed(sealed, first.storage_key, first.envelope.key_ref, "0" * 64)
    with pytest.raises(storage.StorageError, match="stored_file_mismatch"):
        storage.read(first.storage_key, "0" * 64, first.size, first.envelope)
    assert keystore.SCHEME.encode() in keystore.document_aad(first.storage_key, first.envelope.key_ref, first.sha256)


def test_9kg_34_nothing_new_is_stored_in_the_clear_and_a_live_environment_stores_nothing_while_the_decision_is_open(
        settings, tmp_path, monkeypatch):
    settings.CATALYST_AGREEMENT_STORAGE_DIR = str(tmp_path / "custody")
    with pytest.raises(storage.StorageError, match="custody_keys_not_configured"):
        storage.write(b"%PDF-1.7 synthetic")
    custody_keys(settings, tmp_path)
    settings.CATALYST_CUSTODY_WRAPPING_KEY = ""
    with pytest.raises(storage.StorageError, match="custody_keys_not_configured"):
        storage.write(b"%PDF-1.7 synthetic")
    settings.CATALYST_CUSTODY_WRAPPING_KEY = "not-hex"
    with pytest.raises(storage.StorageError, match="custody_key_unavailable"):
        storage.write(b"%PDF-1.7 synthetic")
    assert not list((tmp_path / "custody").glob("*.pdf")) and not list((tmp_path / "custody-keys").glob("*.key"))
    custody_keys(settings, tmp_path)
    settings.CATALYST_ENV = "production"
    with pytest.raises(storage.StorageError, match="custody_undecided"):
        storage.write(b"%PDF-1.7 synthetic")
    assert "custody.location:undecided" in custody_policy.problems()  # the shipped decision is open
    monkeypatch.setattr(custody_policy, "DECISION", {name: f"synthetic-{name}" for name in custody_policy.ROWS})
    key, digest, envelope = storage.write(b"%PDF-1.7 synthetic")
    assert storage.read(key, digest, 18, envelope) == b"%PDF-1.7 synthetic"


# --- destroy -------------------------------------------------------------------------------------------------------

def test_9kg_34_destroying_a_key_journals_it_first_and_leaves_the_document_unreadable_without_blaming_it(k, monkeypatch):
    from agreements import custody
    from correspondence.models import StaffItem

    app = issued(k, monkeypatch)
    sign_and_settle(k, app, "nda")
    document = StoredDocument.objects.get()
    ref = document.envelope.key_ref
    order = []
    real_append, real_unlink = journal.append, keystore._unlink
    monkeypatch.setattr(journal, "append", lambda *a, **kw: order.append("journal") or real_append(*a, **kw))
    monkeypatch.setattr(keystore, "_unlink", lambda *a: order.append("unlink") or real_unlink(*a))
    assert keystore.destroy(str(app.public_ref), [ref]) == 2  # the mirror's copy, then the primary's
    assert order == ["journal", "unlink", "unlink"]
    assert keystore.present(ref) == (False, False)
    entry = [e for e in journal.read() if e.kind == keystore.DESTROYED][-1]
    assert entry.key == f"custody_key:{ref}" and {k: v for k, v in entry.data.items() if k != "mac"} == {
        "subject": str(app.public_ref), "phase": "prepare"}
    with pytest.raises(services.Refused, match="document_erased"):
        services.retrieve_document(str(document.public_id), k.agreement_decider, "Counsel review copy")
    assert not StaffItem.objects.filter(reason_code=custody.CUSTODY_CORRUPTED).exists()  # not corruption
    assert (k.storage / document.storage_key).exists()  # the sealed file and its rows stay
    assert keystore.destroy(str(app.public_ref), [ref]) == 0  # idempotent


# --- an older backup cannot yield a destroyed document --------------------------------------------------------------

def test_9kg_34_a_restore_of_a_backup_taken_before_the_key_was_destroyed_cannot_open_the_document(signed, tmp_path,
                                                                                                    settings):
    out = tmp_path / "sets"
    out.mkdir()
    result = run_backup(out, signed.storage)
    assert result.returncode == 0, result.stderr
    backup_set = out / "set"
    # The key material is in no file of the set (the wrapped key files, the data keys and the wrapping key, in raw,
    # hex and base64 form), and neither is the plaintext.
    report = drill.absent(backup_set, PLACEHOLDER.decode())
    assert report["files"] >= 3 and report["needles"] >= 9
    assert (report["key_material_found"], report["key_files_in_set"], report["plaintext_marker_found"]) == (0, 0, 0)
    documents = {d.instance.agreement_type.key: d for d in StoredDocument.objects.select_related("instance__agreement_type")}
    destroyed, kept = documents["nda"].envelope.key_ref, documents["user_agreement"].envelope.key_ref
    keystore.destroy(str(documents["nda"].application.public_ref), [destroyed])  # the erasure step, after the backup
    database = new_database()
    try:
        restored = tmp_path / "restored-custody"
        result = run_restore(database, backup_set, restored)
        assert result.returncode == 0, result.stderr
        with admin(database) as conn:
            rows = conn.execute("SELECT d.storage_key, d.sha256, d.size, e.storage_key, e.key_ref, e.cipher_sha256,"
                                " e.cipher_size FROM agreements_storeddocument d JOIN agreements_custodyenvelope e"
                                " ON e.document_id = d.id ORDER BY d.id").fetchall()
        assert {row[4] for row in rows} == {destroyed, kept}  # the old rows are back, with their key references
        settings.CATALYST_AGREEMENT_STORAGE_DIR = str(restored)  # read the restored files
        for key, sha, size, sealed_key, ref, cipher_sha, cipher_size in rows:
            envelope = SimpleNamespace(storage_key=sealed_key, key_ref=ref, cipher_sha256=cipher_sha, cipher_size=cipher_size)
            if ref == destroyed:
                with pytest.raises(storage.StorageError, match="custody_key_destroyed"):
                    storage.read(key, sha, size, envelope)
                assert PLACEHOLDER not in (restored / sealed_key).read_bytes()
            else:  # the control: a key that was not destroyed still opens its restored document
                assert storage.sha256(storage.read(key, sha, size, envelope)) == sha
    finally:
        drop(database)


# --- recovery ------------------------------------------------------------------------------------------------------

def test_9kg_34_key_recovery_rebuilds_a_lost_directory_from_its_copy_and_never_brings_back_a_destroyed_key(
        custody, settings):
    primary, mirror = Path(settings.CATALYST_CUSTODY_KEY_DIR), Path(settings.CATALYST_CUSTODY_KEY_MIRROR_DIR)
    names = [f"{uuid.uuid4().hex}.pdf" for _ in range(3)]
    sealed = [keystore.seal(f"%PDF-1.7 synthetic {n}".encode(), name) for n, name in enumerate(names)]
    refs = [ref for ref, _, _ in sealed]
    stale = (mirror / f"{refs[0]}.key").read_bytes()
    keystore.destroy(str(uuid.uuid4()), [refs[0]])
    shutil.rmtree(primary)  # the key directory is lost
    stale_path = mirror / f"{refs[0]}.key"
    stale_path.write_bytes(stale)  # and a copy of the destroyed key reappeared (a point-in-time copy: forbidden)
    stale_path.chmod(0o600)
    with pytest.raises(keystore.KeyStoreError, match="key_store_unavailable"):  # never re-created on the fly
        keystore.load(refs[1])
    assert not primary.exists()
    keystore.provision()  # the holder provisions the replacement directory first
    with pytest.raises(keystore.KeyStoreError, match="key_needs_recovery"):
        keystore.load(refs[1])
    code, report = command("catalyst_custody_keys", "--recover", "--expect-head", record.head_string())  # the holder
    assert code == 0 and report["copied_to_primary"] == 2 and report["destruction_finished"] == 1
    assert report["scope"] == custody_policy.SCOPE
    for (ref, _, blob), name, n in zip(sealed[1:], names[1:], (1, 2)):
        text = f"%PDF-1.7 synthetic {n}".encode()
        assert keystore.open_sealed(blob, name, ref, storage.sha256(text)) == text
    assert keystore.present(refs[0]) == (False, False)  # never restored, and the stale copy is gone
    with pytest.raises(keystore.KeyStoreError, match="key_destroyed"):
        keystore.load(refs[0])
    shutil.rmtree(mirror)  # the mirror is lost: rebuilt from the primary, once re-provisioned
    with pytest.raises(keystore.KeyStoreError, match="key_store_unavailable"):
        keystore.recover(record.head_string())
    keystore.provision()
    assert keystore.recover(record.head_string())["copied_to_mirror"] == 2 and keystore.present(refs[2]) == (True, True)
    # The wrapping key lost from the host: nothing opens and recovery refuses until the escrow copy is back.
    escrow = settings.CATALYST_CUSTODY_WRAPPING_KEY
    settings.CATALYST_CUSTODY_WRAPPING_KEY = ""
    with pytest.raises(keystore.KeyStoreError, match="wrapping_key_missing"):
        keystore.load(refs[1])
    with pytest.raises(keystore.KeyStoreError, match="wrapping_key_missing"):
        keystore.recover(record.head_string())
    settings.CATALYST_CUSTODY_WRAPPING_KEY = secrets.token_hex(32)  # not the escrowed key
    with pytest.raises(keystore.KeyStoreError, match="wrapping_key_mismatch"):
        keystore.load(refs[1])
    (mirror / f"{refs[1]}.key").unlink()
    assert keystore.recover(record.head_string())["unrecoverable"] == 1  # wrapped under another key: reported, never copied
    settings.CATALYST_CUSTODY_WRAPPING_KEY = escrow
    assert keystore.recover(record.head_string())["copied_to_mirror"] == 1 and keystore.present(refs[1]) == (True, True)
    assert keystore.open_sealed(sealed[1][2], names[1], refs[1], storage.sha256(b"%PDF-1.7 synthetic 1")) == b"%PDF-1.7 synthetic 1"
    # Recovery needs the journal: without it, it cannot know what was destroyed, so it refuses.
    head = record.head_string()
    settings.CATALYST_EFFECT_JOURNAL_DIR = ""
    with pytest.raises(keystore.KeyStoreError, match="journal_unavailable"):
        keystore.recover(head)
    # A key never exists without its recovery copy: a mirror that cannot be written leaves no primary copy either.
    settings.CATALYST_EFFECT_JOURNAL_DIR = str(custody.parent / "effects")
    mirror.chmod(0o755)
    with pytest.raises(keystore.KeyStoreError, match="key_store_unsafe"):
        keystore.create()
    mirror.chmod(0o700)
    assert len(keystore.listing()[0]) == 2
    # The holder and the time bound are the owner's rows (211.7.9), shipped undecided.
    assert {"custody.recovery_holder:undecided", "custody.recovery_time_bound:undecided"} <= set(custody_policy.problems())


# --- migration of documents stored in the clear --------------------------------------------------------------------

@pytest.mark.django_db
def test_9kg_34_documents_stored_in_the_clear_are_sealed_by_the_operator_and_the_plaintext_is_removed(custody):
    app = subject()
    texts = [b"%PDF-1.7 synthetic legacy one", b"%PDF-1.7 synthetic legacy two"]
    legacy = [drill.synthetic_document(app, text, sealed=False) for text in texts]
    for document, text in zip(legacy, texts):
        assert (custody / document.storage_key).read_bytes() == text  # in the clear, as before 9kg.34
        assert storage.read(document.storage_key, document.sha256, document.size) == text  # and still verified
    code, report = command("catalyst_custody_keys", "--status")
    assert code == 1 and not report["ok"] and report["in_the_clear"] == 2
    code, report = command("catalyst_custody_keys", "--migrate")
    assert code == 1 and report["refused"] == "confirm_required"
    code, report = command("catalyst_custody_keys", "--migrate", "--confirm")
    assert code == 0 and (report["sealed"], report["plaintext_removed"]) == (2, 2)
    assert report["scope"] == custody_policy.SCOPE
    for document, text in zip(legacy, texts):
        envelope = CustodyEnvelope.objects.get(document=document)
        assert envelope.migrated and envelope.storage_key != document.storage_key
        assert not (custody / document.storage_key).exists()  # the plaintext is gone
        sealed = (custody / envelope.storage_key).read_bytes()
        assert sealed.startswith(keystore.MAGIC) and text not in sealed
        assert storage.read(document.storage_key, document.sha256, document.size, envelope) == text  # the same hash
    code, report = command("catalyst_custody_keys", "--status")
    assert code == 0 and report["ok"] and report["in_the_clear"] == 0 and report["sealed"] == 2
    assert command("catalyst_custody_keys", "--migrate", "--confirm")[1]["sealed"] == 0  # re-runnable
    # A migration interrupted after its commit (sealed copy recorded, plaintext still on disk) is finished next run.
    third = drill.synthetic_document(app, b"%PDF-1.7 synthetic legacy three", sealed=False)
    envelope = storage.seal_existing(third.storage_key, third.sha256, third.size)
    CustodyEnvelope.objects.create(document=third, migrated=True, **envelope.fields())
    code, report = command("catalyst_custody_keys", "--status")
    assert code == 1 and report["plaintext_lingering"] == 1
    assert command("catalyst_custody_keys", "--migrate", "--confirm")[1]["plaintext_removed"] == 1
    assert command("catalyst_custody_keys", "--status")[1]["ok"] and not (custody / third.storage_key).exists()
    with pytest.raises(storage.StorageError, match="stored_file_mismatch"):  # sealed bytes are never sealed twice
        sealed_key = CustodyEnvelope.objects.get(document=third).storage_key
        storage.seal_existing(sealed_key, storage.sha256((custody / sealed_key).read_bytes()),
                              (custody / sealed_key).stat().st_size)


# --- the erasure step and the registry -----------------------------------------------------------------------------

def test_9kg_34_the_registry_admits_destroy_key_for_signed_documents_only_and_ships_undecided(monkeypatch):
    monkeypatch.setattr(registry, "REPLAY_BUILT", True)
    assert registry.problems(DESTROYING) == []
    assert registry.ALLOWED["signed_documents"] == (registry.RETAIN, registry.DESTROY_KEY)
    assert "submissions.treatment:unsupported" in registry.problems(
        {**DECIDED, "submissions": {"treatment": registry.DESTROY_KEY, "retention": "p1y"}})
    assert "signed_documents.treatment:unsupported" in registry.problems(
        {**DECIDED, "signed_documents": {"treatment": registry.ANONYMIZE, "retention": "p1y"}})
    assert registry.REGISTRY["signed_documents"]["treatment"] == registry.UNDECIDED
    assert set(catalog.TABLES["agreements_custodyenvelope"].columns().values()) == {"non_personal"}
    assert "custody_key_destroyed" in journal.KINDS and "keys_destroyed" in journal.KINDS["erasure_complete"]


def test_9kg_34_the_erasure_destroys_the_subjects_custody_keys_under_destroy_key_and_records_it(
        privileged_reset, decided, custody, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY", DESTROYING)
    app = subject()
    documents = [drill.synthetic_document(app, b"%PDF-1.7 synthetic one"),
                 drill.synthetic_document(app, b"%PDF-1.7 synthetic two")]
    other = drill.synthetic_document(subject(email="other@example.test", name="Other Example"),
                                 b"%PDF-1.7 synthetic other")
    refs = [d.envelope.key_ref for d in documents]
    outcome = erase(privileged_reset, app.public_ref)
    assert outcome.status == "erased" and outcome.retained == []
    assert (outcome.keys_destroyed, outcome.key_files_removed) == (2, 4)  # references, and files in both directories
    assert all(keystore.present(ref) == (False, False) for ref in refs)
    assert keystore.present(other.envelope.key_ref) == (True, True)  # another person's key is untouched
    for document in documents:
        with pytest.raises(storage.StorageError, match="custody_key_destroyed"):
            storage.read(document.storage_key, document.sha256, document.size, document.envelope)
        assert (custody / document.storage_key).exists()  # the rows and sealed files stay
    entries = journal.read()
    destroyed = [e for e in entries if e.kind == keystore.DESTROYED]
    complete = [e for e in entries if e.kind == "erasure_complete" and e.key == f"erasure:{app.public_ref}"][-1]
    assert {e.key for e in destroyed} == {f"custody_key:{ref}" for ref in refs}
    assert all(e.data["subject"] == str(app.public_ref) and e.seq < complete.seq for e in destroyed)
    assert (complete.data["keys_destroyed"], complete.data["key_files_removed"], complete.data["custody"]) == (2, 4, "keys_destroyed")
    assert complete.data["status"] == "erased"
    assert record.fold(entries, KEY.encode())[str(app.public_ref)].retained == set()  # custody no longer retained
    count = len(journal.read())
    again = erase(privileged_reset, app.public_ref)  # a second erasure is harmless and writes nothing
    assert again.status == "nothing_to_erase" and len(journal.read()) == count


def test_9kg_34_under_retain_custody_is_reported_retained_and_a_later_destroy_key_reaches_the_tombstoned_subject(
        privileged_reset, decided, custody, monkeypatch):
    app = subject()
    ref = drill.synthetic_document(app, b"%PDF-1.7 synthetic").envelope.key_ref
    first = erase(privileged_reset, app.public_ref)  # DECIDED: signed_documents retain
    assert first.retained == ["custody_documents"] and first.keys_destroyed == 0 and keystore.present(ref) == (True, True)
    monkeypatch.setattr(registry, "REGISTRY", DESTROYING)
    second = erase(privileged_reset, app.public_ref)
    assert (second.status, second.changed, second.keys_destroyed, second.key_files_removed, second.retained) == (
        "erased", 0, 1, 2, [])
    assert keystore.present(ref) == (False, False)


def test_9kg_34_a_document_still_in_the_clear_refuses_destroy_key_before_any_record(privileged_reset, decided, custody,
                                                                                  monkeypatch):
    from applications.models import Application

    monkeypatch.setattr(registry, "REGISTRY", DESTROYING)
    app = subject()
    drill.synthetic_document(app, b"%PDF-1.7 synthetic legacy", sealed=False)
    with pytest.raises(service.Refused, match="custody_plaintext_unmigrated"):
        erase(privileged_reset, app.public_ref)
    assert erasure_entries() == [] and Application.objects.get(pk=app.pk).email == "grace@example.test"
    assert command("catalyst_custody_keys", "--migrate", "--confirm")[1]["sealed"] == 1
    assert erase(privileged_reset, app.public_ref).keys_destroyed == 1


def test_9kg_34_an_interrupted_destruction_is_finished_by_recovery_or_the_next_run_and_never_undone(
        privileged_reset, decided, custody, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY", DESTROYING)
    app = subject()
    ref = drill.synthetic_document(app, b"%PDF-1.7 synthetic").envelope.key_ref
    real = keystore._unlink

    def unlink(path, key_ref):
        raise keystore.KeyStoreError("key_store_unavailable")  # the key volume went away mid-erasure
    monkeypatch.setattr(keystore, "_unlink", unlink)
    with pytest.raises(service.Refused, match="custody_key_store_unavailable_after_commit"):
        erase(privileged_reset, app.public_ref)
    assert record.list_open()["open"] == [str(app.public_ref)]  # the intent stays open
    assert keystore.present(ref) == (True, True)
    assert [e.key for e in journal.read() if e.kind == keystore.DESTROYED] == [f"custody_key:{ref}"]  # recorded first
    monkeypatch.setattr(keystore, "_unlink", real)
    assert keystore.recover(record.head_string())["destruction_finished"] == 2  # recovery finishes it; it never restores the key
    assert keystore.present(ref) == (False, False)
    outcome = erase(privileged_reset, app.public_ref)  # the next run completes the record
    assert outcome.resumed and outcome.status == "already_erased" and record.list_open()["open"] == []


# --- the start-up guards and who may hold the wrapping key ---------------------------------------------------------

def test_9kg_34_the_start_up_guards_check_the_wrapping_key_the_key_directories_and_who_may_hold_the_key(
        tmp_path, monkeypatch):
    key = "ab" * 32
    good = SimpleNamespace(
        CATALYST_ENV="staging", SECRET_KEY="s" * 50, CATALYST_VERIFICATION_KEY="v" * 40,
        CATALYST_VERIFICATION_FALLBACK_KEYS=[], CATALYST_ERASURE_KEY="e" * 40, CATALYST_PROCESS_ROLE="worker",
        CATALYST_CUSTODY_WRAPPING_KEY=key, CATALYST_CUSTODY_KEY_DIR=str(tmp_path / "keys"),
        CATALYST_CUSTODY_KEY_MIRROR_DIR=str(tmp_path / "mirror"), CATALYST_AGREEMENT_STORAGE_DIR=str(tmp_path / "custody"),
        CATALYST_EFFECT_JOURNAL_DIR=str(tmp_path / "effects"))
    assert guards.custody_key_problems(good, "worker") == []
    assert guards.custody_key_problems(SimpleNamespace(**{**vars(good), "CATALYST_PROCESS_ROLE": "web"}), "web") == []
    repository = Path(guards.__file__).resolve().parent.parent
    for change, kind, expected in (
            ({"CATALYST_CUSTODY_WRAPPING_KEY": "ab" * 16}, "worker", "64 lower-case hex"),
            ({"CATALYST_CUSTODY_WRAPPING_KEY": "AB" * 32}, "worker", "64 lower-case hex"),
            ({"SECRET_KEY": key}, "worker", "differ from every other key"),
            ({"CATALYST_ERASURE_KEY": key}, "worker", "differ from every other key"),
            ({"CATALYST_VERIFICATION_FALLBACK_KEYS": [key]}, "worker", "differ from every other key"),
            ({"CATALYST_PROCESS_ROLE": "fetcher"}, "worker", "fetcher"),
            ({"CATALYST_PROCESS_ROLE": "reconcile"}, "reconcile", "reconcile"),
            ({"CATALYST_CUSTODY_KEY_DIR": "relative/keys"}, "worker", "absolute"),
            ({"CATALYST_CUSTODY_KEY_DIR": str(repository / "keys")}, "worker", "outside the repository"),
            ({"CATALYST_CUSTODY_KEY_MIRROR_DIR": str(tmp_path / "keys")}, "worker", "separate directories"),
            ({"CATALYST_CUSTODY_KEY_MIRROR_DIR": str(tmp_path / "keys" / "mirror")}, "worker", "separate directories"),
            ({"CATALYST_CUSTODY_KEY_DIR": str(tmp_path / "custody" / "keys")}, "worker", "CATALYST_AGREEMENT_STORAGE_DIR"),
            ({"CATALYST_AGREEMENT_STORAGE_DIR": str(tmp_path / "keys" / "custody")}, "worker", "CATALYST_AGREEMENT_STORAGE_DIR"),
            ({"CATALYST_CUSTODY_KEY_DIR": str(tmp_path / "effects" / "keys")}, "worker", "CATALYST_EFFECT_JOURNAL_DIR"),
            ({"CATALYST_CUSTODY_KEY_DIR": ""}, "worker", "needs CATALYST_CUSTODY_KEY_DIR"),
            ({"CATALYST_ENV": "production"}, "worker", "custody decision is open")):
        problems = guards.custody_key_problems(SimpleNamespace(**{**vars(good), **change}), kind)
        assert any(expected in p for p in problems), (change, problems)
    monkeypatch.setattr(custody_policy, "DECISION", {name: f"synthetic-{name}" for name in custody_policy.ROWS})
    assert guards.custody_key_problems(SimpleNamespace(**{**vars(good), "CATALYST_ENV": "production"}), "worker") == []
    # The directories are fixed in code (never from the environment) and synthetic-only until the owner decides; the
    # wrapping key comes from its secret file outside test and development.
    staging = SimpleNamespace(CATALYST_ENV="staging", CATALYST_PUBLIC_BASE_URL="https://catalyst.staging.test")
    assert any("CATALYST_CUSTODY_KEY_DIR may not be set from the environment" in p
               for p in guards.agreement_problems(staging, {"CATALYST_CUSTODY_KEY_DIR": "/k"}))
    assert any("CATALYST_CUSTODY_KEY_MIRROR_DIR is allowed only in the test and staging" in p for p in guards.agreement_problems(
        SimpleNamespace(CATALYST_ENV="production", CATALYST_CUSTODY_KEY_MIRROR_DIR="/m"), {}))
    assert any("CATALYST_CUSTODY_WRAPPING_KEY may not be in the environment" in p for p in guards.secret_problems(
        SimpleNamespace(CATALYST_ENV="staging", CATALYST_SECRETS_DIR="/run/secrets"), {"CATALYST_CUSTODY_WRAPPING_KEY": key}))
    assert "CATALYST_CUSTODY_WRAPPING_KEY" in guards.SECRET_ENV_NAMES


def test_9kg_34_the_backup_and_the_erasure_command_never_hold_the_wrapping_key_and_no_backup_touches_a_key_directory(
        settings, tmp_path):
    out, storage_dir = tmp_path / "sets", tmp_path / "custody"
    out.mkdir()
    storage_dir.mkdir()
    settings.CATALYST_CUSTODY_WRAPPING_KEY = secrets.token_hex(32)
    with pytest.raises(backup_module.BackupError, match="may not hold the custody wrapping key"):
        backup_module.refuse_custody_keys(out, storage_dir)
    err = StringIO()
    with pytest.raises(SystemExit):
        call_command("catalyst_erase", "--subject", str(uuid.uuid4()), "--authority", "x:y", "--reason", "abc",
                     stderr=err)
    assert "custody_wrapping_key_present" in err.getvalue()
    settings.CATALYST_CUSTODY_WRAPPING_KEY = ""
    for keys in (out, out / "keys", storage_dir / "keys", tmp_path):
        settings.CATALYST_CUSTODY_KEY_DIR = str(keys)
        with pytest.raises(backup_module.BackupError, match="custody key directory"):
            backup_module.refuse_custody_keys(out, storage_dir)
    settings.CATALYST_CUSTODY_KEY_DIR = str(tmp_path / "keys")
    backup_module.refuse_custody_keys(out, storage_dir)  # separate directories: allowed


# --- the drill's command -------------------------------------------------------------------------------------------

@pytest.mark.django_db
def test_9kg_34_the_drill_command_seeds_reads_destroys_and_checks_a_set_for_key_material(settings, tmp_path):
    settings.CATALYST_CUSTODY_WRAPPING_KEY = secrets.token_hex(32)
    settings.CATALYST_ERASURE_KEY = KEY  # the destruction's mac
    settings.CATALYST_AGREEMENT_STORAGE_DIR = settings.CATALYST_CUSTODY_KEY_DIR = ""  # restored after the test
    settings.CATALYST_CUSTODY_KEY_MIRROR_DIR = ""
    dirs = ["--storage-dir", str(tmp_path / "custody"), "--key-dir", str(tmp_path / "keys"),
            "--mirror-dir", str(tmp_path / "mirror")]
    assert command("catalyst_custody_drill", "provision", *dirs)[1]["provisioned"] == {
        "primary": "provisioned", "mirror": "provisioned"}
    seeded = command("catalyst_custody_drill", "seed", *dirs)[1]
    assert seeded["seeded"] and seeded["marker"].startswith("SYNTHETIC-CUSTODY-DRILL-")
    assert command("catalyst_custody_drill", "read", *dirs, "--document", seeded["document"])[1] == {
        "read": "opened", "sha256_matches": True, "sealed": True, "scope": custody_policy.SCOPE}
    backup_set = tmp_path / "set"
    shutil.copytree(tmp_path / "custody", backup_set / "custody")
    clean = command("catalyst_custody_drill", "absent", *dirs, "--set", str(backup_set), "--marker", seeded["marker"])[1]
    assert (clean["key_material_found"], clean["plaintext_marker_found"], clean["sealed_files_in_set"]) == (0, 0, 1)
    leaked = next((tmp_path / "keys").glob("*.key"))
    shutil.copy(leaked, backup_set / "leaked.key")  # the negative control: a set that did hold a key
    (backup_set / "plain.pdf").write_text(f"%PDF {seeded['marker']}")
    dirty = command("catalyst_custody_drill", "absent", *dirs, "--set", str(backup_set), "--marker", seeded["marker"])[1]
    assert dirty["key_material_found"] >= 1 and dirty["plaintext_marker_found"] == 1 and dirty["key_files_in_set"] == 1
    assert command("catalyst_custody_drill", "destroy", *dirs, "--document", seeded["document"])[1]["destroyed"] == 2
    assert command("catalyst_custody_drill", "read", *dirs, "--document", seeded["document"])[1]["code"] == "custody_key_destroyed"
    assert command("catalyst_custody_drill", "journaled", *dirs, "--document", seeded["document"])[1] == {
        "journaled_destroyed": True, "verified": True, "forged": 0, "scope": custody_policy.SCOPE}
    settings.CATALYST_ENV = "development"
    from django.core.management.base import CommandError
    with pytest.raises(CommandError, match="synthetic"):
        call_command("catalyst_custody_drill", "read", *dirs, "--document", seeded["document"], stdout=StringIO())


def test_9kg_34_the_restore_drill_pins_its_custody_leg():
    """The drill carries the behaviour through the real staging backup and restore and is run on the dev box; this
    gate pins its shape only: a sealed document, the set checked for key material and plaintext, the key destroyed
    after the backup, the older set restored into a fresh database, the restored document refused, and the off-site
    leg reported NOT RUN."""
    script = (Path(__file__).resolve().parent.parent / "scripts" / "restore_drill.sh").read_text()
    for line in ("catalyst_custody_drill", "custody_wrapping_key", "absent --set", "destroy --document",
                 "positive control", "negative control: the backup refuses", "sealed_files_in_set", "needles",
                 "volumes_before", "journaled --document",
                 "custody/restored read --document", "custody_key_destroyed", "NOT RUN 9kg.34 the off-site, object-locked copy",
                 'docker volume rm "$keys_vol" "$mirror_vol"'):
        assert line in script, line


# --- the review of PR #102, A: the key store never fails open --------------------------------------------------------

def test_9kg_34_a_missing_or_unmarked_key_directory_refuses_and_is_never_created_or_read_as_empty(
        privileged_reset, decided, custody, settings, monkeypatch):
    from applications.models import Application

    monkeypatch.setattr(registry, "REGISTRY", DESTROYING)
    app = subject()
    document = drill.synthetic_document(app, b"%PDF-1.7 synthetic")
    ref = document.envelope.key_ref
    mirror = Path(settings.CATALYST_CUSTODY_KEY_MIRROR_DIR)
    moved = mirror.with_name("mirror-unmounted")
    mirror.rename(moved)  # the mirror's volume is not mounted
    with pytest.raises(keystore.KeyStoreError, match="key_store_unavailable"):
        keystore.destroy(str(app.public_ref), [ref])
    assert not mirror.exists()  # nothing re-created it
    with pytest.raises(service.Refused, match="custody_key_store_unavailable"):
        erase(privileged_reset, app.public_ref)  # refused at the dry run, before any record
    assert erasure_entries() == [] and Application.objects.get(pk=app.pk).email == "grace@example.test"
    moved.rename(mirror)
    (mirror / keystore.MARKER).unlink()  # a directory without its provisioning marker is not a key store
    with pytest.raises(keystore.KeyStoreError, match="key_store_unavailable"):
        keystore.present(ref)
    with pytest.raises(keystore.KeyStoreError, match="key_store_unavailable"):
        keystore.create()
    keystore.provision()
    assert keystore.present(ref) == (True, True)


@pytest.mark.django_db
def test_9kg_34_empty_key_volumes_make_a_never_destroyed_document_unavailable_never_erased(custody, settings):
    document = drill.synthetic_document(subject(), b"%PDF-1.7 synthetic")
    for directory in (settings.CATALYST_CUSTODY_KEY_DIR, settings.CATALYST_CUSTODY_KEY_MIRROR_DIR):
        shutil.rmtree(directory)  # replaced by empty volumes, then provisioned again
    keystore.provision()
    with pytest.raises(keystore.KeyStoreError, match="key_lost"):
        keystore.load(document.envelope.key_ref)
    with pytest.raises(storage.StorageError, match="custody_key_unavailable"):
        storage.read(document.storage_key, document.sha256, document.size, document.envelope)


@pytest.mark.django_db
def test_9kg_34_a_restored_key_file_for_a_destroyed_reference_is_still_refused(custody, settings):
    document = drill.synthetic_document(subject(), b"%PDF-1.7 synthetic")
    ref = document.envelope.key_ref
    path = Path(settings.CATALYST_CUSTODY_KEY_DIR) / f"{ref}.key"
    blob = path.read_bytes()
    keystore.destroy(str(document.application.public_ref), [ref])
    path.write_bytes(blob)  # an old copy of the key comes back (a restored volume, a stray archive)
    path.chmod(0o600)
    with pytest.raises(keystore.KeyStoreError, match="key_destroyed"):
        keystore.load(ref)
    with pytest.raises(storage.StorageError, match="custody_key_destroyed"):
        storage.read(document.storage_key, document.sha256, document.size, document.envelope)


# --- the review of PR #102, B: no orphan key or sealed file -----------------------------------------------------------

def _keys_and_sealed(settings, custody_dir):
    keys = sorted(p.name for d in (settings.CATALYST_CUSTODY_KEY_DIR, settings.CATALYST_CUSTODY_KEY_MIRROR_DIR)
                  for p in Path(d).glob("*.key"))  # one entry per file: a key's copy in each directory
    sealed = sorted(p.name for p in Path(custody_dir).glob("*.pdf") if p.read_bytes().startswith(keystore.MAGIC))
    return keys, sealed


def test_9kg_34_an_interrupted_write_leaves_no_key_and_no_sealed_file(custody, settings, monkeypatch):
    real_write, real_read = storage._write_new, storage.read

    def fail_write(key, data):
        raise storage.StorageError("storage_write_failed")
    monkeypatch.setattr(storage, "_write_new", fail_write)
    with pytest.raises(storage.StorageError, match="storage_write_failed"):
        storage.write(b"%PDF-1.7 synthetic")
    assert _keys_and_sealed(settings, custody) == ([], [])
    monkeypatch.setattr(storage, "_write_new", real_write)

    def fail_verify(*args):
        raise storage.StorageError("stored_file_mismatch")
    monkeypatch.setattr(storage, "read", fail_verify)
    with pytest.raises(storage.StorageError, match="stored_file_mismatch"):
        storage.write(b"%PDF-1.7 synthetic")
    assert _keys_and_sealed(settings, custody) == ([], [])
    monkeypatch.setattr(storage, "read", real_read)
    storage.write(b"%PDF-1.7 synthetic")
    assert [len(x) for x in _keys_and_sealed(settings, custody)] == [2, 1]


@pytest.mark.django_db
def test_9kg_34_an_interrupted_or_concurrent_migration_leaves_no_orphan(custody, settings, monkeypatch):
    app = subject()
    first = drill.synthetic_document(app, b"%PDF-1.7 synthetic one", sealed=False)
    real_create = CustodyEnvelope.objects.create

    def crash(**kwargs):
        raise RuntimeError("interrupted before the envelope was recorded")
    monkeypatch.setattr(CustodyEnvelope.objects, "create", crash)
    with pytest.raises(RuntimeError):
        call_command("catalyst_custody_keys", "--migrate", "--confirm", stdout=StringIO())
    assert _keys_and_sealed(settings, custody) == ([], [])  # discarded, and the plaintext is intact
    assert (custody / first.storage_key).read_bytes() == b"%PDF-1.7 synthetic one"
    monkeypatch.setattr(CustodyEnvelope.objects, "create", real_create)
    # Another run seals the same document between our seal and our record: ours is discarded, nothing crashes.
    real_seal = storage.seal_existing

    def sealed_meanwhile(key, sha, size):
        theirs = real_seal(key, sha, size)
        real_create(document=StoredDocument.objects.get(storage_key=key), migrated=True, **theirs.fields())
        return real_seal(key, sha, size)
    monkeypatch.setattr(storage, "seal_existing", sealed_meanwhile)
    code, report = command("catalyst_custody_keys", "--migrate", "--confirm")
    assert code == 0 and report["already_sealed"] == 1 and report["sealed"] == 0
    monkeypatch.setattr(storage, "seal_existing", real_seal)
    code, report = command("catalyst_custody_keys", "--status")
    assert report["orphan_keys"] == 0 and report["orphan_sealed_files"] == 0
    assert [len(x) for x in _keys_and_sealed(settings, custody)] == [2, 1]  # exactly the recorded pair


@pytest.mark.django_db
def test_9kg_34_reap_lists_then_removes_planted_orphans_and_status_is_unhealthy_until_then(custody, settings):
    drill.synthetic_document(subject(), b"%PDF-1.7 synthetic")  # a recorded pair, never touched
    orphan_key, _, _ = keystore.create()
    planted = storage._seal(b"%PDF-1.7 synthetic orphan", f"{uuid.uuid4().hex}.pdf")  # a crash before the record
    code, report = command("catalyst_custody_keys", "--status")
    assert code == 1 and (report["orphan_keys"], report["orphan_sealed_files"]) == (2, 1)  # the planted pair's key too
    code, report = command("catalyst_custody_keys", "--reap-orphans", "--min-age-seconds", "0")
    assert code == 0 and (report["orphan_keys"], report["orphan_sealed_files"], report["removed_keys"]) == (2, 1, 0)
    assert keystore.present(orphan_key) == (True, True)  # a dry run removes nothing
    code, report = command("catalyst_custody_keys", "--reap-orphans")  # too young: a write in progress is left alone
    assert report["orphan_keys"] == 0
    code, report = command("catalyst_custody_keys", "--reap-orphans", "--confirm", "--min-age-seconds", "0")
    assert (report["removed_keys"], report["removed_files"]) == (2, 1)
    assert keystore.present(orphan_key) == (False, False) and not (custody / planted.storage_key).exists()
    reaped = [e for e in journal.read() if e.kind == "custody_orphan_reaped"]
    assert sorted(e.data["kind"] for e in reaped) == ["key", "key", "sealed_file"]
    code, report = command("catalyst_custody_keys", "--status")
    assert code == 0 and report["healthy"] and report["sealed"] == 1


# --- the review of PR #102, C: lingering plaintext -------------------------------------------------------------------

def _interrupted_migration(document):
    """A migration interrupted after its commit: the sealed copy is recorded, the plaintext file is still on disk."""
    sealed = storage.seal_existing(document.storage_key, document.sha256, document.size)
    CustodyEnvelope.objects.create(document=document, migrated=True, **sealed.fields())
    return CustodyEnvelope.objects.get(document=document)


def test_9kg_34_the_erasure_refuses_while_a_migrated_documents_plaintext_lingers(privileged_reset, decided, custody,
                                                                                 monkeypatch):
    from applications.models import Application

    monkeypatch.setattr(registry, "REGISTRY", DESTROYING)
    app = subject()
    document = drill.synthetic_document(app, b"%PDF-1.7 synthetic legacy", sealed=False)
    _interrupted_migration(document)
    assert (custody / document.storage_key).exists()
    with pytest.raises(service.Refused, match="custody_plaintext_lingering"):
        erase(privileged_reset, app.public_ref)
    assert erasure_entries() == [] and Application.objects.get(pk=app.pk).email == "grace@example.test"
    assert command("catalyst_custody_keys", "--migrate", "--confirm")[1]["plaintext_removed"] == 1
    assert erase(privileged_reset, app.public_ref).keys_destroyed == 1


@pytest.mark.django_db
def test_9kg_34_lingering_plaintext_of_a_destroyed_key_is_removed_and_one_failure_blocks_nothing(custody, settings):
    app = subject()
    erased, damaged, fine = (drill.synthetic_document(app, f"%PDF-1.7 synthetic {n}".encode(), sealed=False)
                             for n in ("erased", "damaged", "fine"))
    envelopes = {d.pk: _interrupted_migration(d) for d in (erased, damaged, fine)}
    keystore.destroy(str(app.public_ref), [envelopes[erased.pk].key_ref])  # its sealed copy can never open again
    sealed_path = custody / envelopes[damaged.pk].storage_key
    sealed_path.write_bytes(sealed_path.read_bytes()[:-1] + b"X")  # this one cannot be verified
    code, report = command("catalyst_custody_keys", "--migrate", "--confirm")
    assert code == 1 and report["plaintext_cleanup_failed"] == 1 and report["plaintext_removed"] == 2
    assert not (custody / erased.storage_key).exists()  # removed without opening the sealed copy
    assert not (custody / fine.storage_key).exists()
    assert (custody / damaged.storage_key).exists()  # kept: the only verifiable copy, and reported



# --- the review of PR #102, D: a restore cannot undo a destruction ----------------------------------------------------

@pytest.mark.django_db
def test_9kg_34_the_sweep_finishes_journaled_destructions_without_the_wrapping_key_and_fails_closed(custody, settings):
    from django.core.exceptions import ImproperlyConfigured

    from config.apps import sweep_custody_keys

    document = drill.synthetic_document(subject(), b"%PDF-1.7 synthetic")
    ref = document.envelope.key_ref
    copies = {d: (Path(d) / f"{ref}.key").read_bytes()
              for d in (settings.CATALYST_CUSTODY_KEY_DIR, settings.CATALYST_CUSTODY_KEY_MIRROR_DIR)}
    keystore.destroy(str(document.application.public_ref), [ref])
    for directory, blob in copies.items():  # a restored volume brings both copies back
        (Path(directory) / f"{ref}.key").write_bytes(blob)
        (Path(directory) / f"{ref}.key").chmod(0o600)
    settings.CATALYST_CUSTODY_WRAPPING_KEY = ""  # the restore lift and the start-up sweep never hold it
    assert keystore.sweep() == {"status": "swept", "removed": 2}
    assert keystore.present(ref) == (False, False) and keystore.sweep()["removed"] == 0
    (Path(settings.CATALYST_CUSTODY_KEY_MIRROR_DIR) / keystore.MARKER).unlink()
    with pytest.raises(ImproperlyConfigured, match="custody key sweep failed .key_store_unavailable."):
        sweep_custody_keys()  # web and worker refuse to start rather than run with an unchecked store
    settings.CATALYST_CUSTODY_KEY_DIR = settings.CATALYST_CUSTODY_KEY_MIRROR_DIR = ""
    assert keystore.sweep() == {"status": "not_configured", "removed": 0}
    root = Path(__file__).resolve().parent.parent  # where it runs: the lift, the worker's start, the web's start
    assert "keystore.sweep()" in (root / "config/post_restore.py").read_text()
    assert "sweep_custody_keys()" in (root / "workflow/management/commands/run_worker.py").read_text()
    assert 'process_kind() == "web"' in (root / "config/apps.py").read_text()


@pytest.mark.django_db
def test_9kg_34_recovery_needs_the_out_of_band_head_and_refuses_a_journal_that_lost_it(custody, settings):
    document = drill.synthetic_document(subject(), b"%PDF-1.7 synthetic")
    keystore.destroy(str(document.application.public_ref), [document.envelope.key_ref])
    head = record.head_string()
    code, report = command("catalyst_custody_keys", "--recover")
    assert code == 1 and report["refused"] == "expect_head_required"
    identity, seq, digest = head.split(":")
    for wrong, reason in ((f"{identity}:{seq}:{'0' * 64}", "journal_mismatch"),
                          (f"{'0' * 32}:{seq}:{digest}", "journal_mismatch"),
                          ("none", "journal_mismatch"), ("not-a-head", "bad_head")):
        code, report = command("catalyst_custody_keys", "--recover", "--expect-head", wrong)
        assert code == 1 and report["refused"] == reason, wrong
    assert command("catalyst_custody_keys", "--recover", "--expect-head", head)[0] == 0


# --- the review of PR #102, E: the destruction record carries a mac --------------------------------------------------

@pytest.mark.django_db
def test_9kg_34_a_destruction_entry_carries_a_mac_and_a_forged_one_is_reported_never_acted_on(custody, settings):
    document = drill.synthetic_document(subject(), b"%PDF-1.7 synthetic")
    keep = drill.synthetic_document(subject(email="other@example.test", name="Other Example"), b"%PDF-1.7 other")
    keystore.destroy(str(document.application.public_ref), [document.envelope.key_ref])
    entry = [e for e in journal.read() if e.kind == keystore.DESTROYED][-1]
    secret = settings.CATALYST_ERASURE_KEY.encode()
    assert entry.data["mac"] == record.entry_mac(entry.kind, entry.key, entry.data, secret)
    # Someone who can write the journal but lacks the erasure key forges a destruction of another person's key.
    ref = keep.envelope.key_ref
    journal.append(keystore.DESTROYED, f"custody_key:{ref}", {"subject": str(uuid.uuid4()), "phase": "prepare",
                                                             "mac": "f" * 64})
    forged = []
    assert keystore.destroyed_refs(journal.read(), secret, forged) == {document.envelope.key_ref} and forged == [ref]
    with pytest.raises(keystore.KeyStoreError, match="forged_entry"):
        keystore.sweep()  # it removes files, so it acts only on verified entries
    assert keystore.present(ref) == (True, True)  # the forged entry removed nothing
    with pytest.raises(keystore.KeyStoreError, match="forged_entry"):
        keystore.recover(record.head_string())
    # Read paths (web, worker: no erasure key) count it unverified, which can only refuse a key, never revive one.
    with pytest.raises(keystore.KeyStoreError, match="key_destroyed"):
        keystore.load(ref)
    settings.CATALYST_ERASURE_KEY = ""
    with pytest.raises(keystore.KeyStoreError, match="erasure_key_missing"):
        keystore.destroy(str(keep.application.public_ref), [ref])  # no destruction without its mac


# --- the data review of PR #102, K1: erasure 0003 reverses cleanly ---------------------------------------------------

def test_9kg_34_erasure_0003_reverses_to_exactly_the_function_0002_installs(privileged_reset):
    """A database migrated only to erasure 0002 (and its dependencies) and this database after `migrate erasure 0002`
    hold the same erase function, byte for byte, and it reads no custody table; the reapply restores the custody part."""
    from psycopg import sql as psql

    from tests.support import manage_as_owner, run

    query = ("SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
             " WHERE n.nspname = 'public' AND p.proname = 'catalyst_erase'")
    owner = privileged_reset.connect("owner", autocommit=True)
    with_custody = owner.execute(query).fetchone()[0]
    assert "agreements_custodyenvelope" in with_custody and catalog.CUSTODY_BEGIN in with_custody
    fresh = f"catalyst_erasure_{uuid.uuid4().hex[:10]}"
    from django.conf import settings as live

    roles = live.CATALYST_DB_ROLES
    with admin("postgres") as conn:
        conn.execute(psql.SQL("CREATE DATABASE {} OWNER {}").format(psql.Identifier(fresh), psql.Identifier(roles["owner"])))
    try:
        env = {"CATALYST_DB_NAME": fresh, "CATALYST_DB_USER": roles["owner"],
               "CATALYST_DB_PASSWORD": os.environ["CATALYST_DB_OWNER_PASSWORD"]}
        result = run([sys.executable, "manage.py", "migrate", "erasure", "0002", "--verbosity", "0"],
                     timeout=300, **env)
        assert result.returncode == 0, result.stderr
        with admin(fresh) as conn:
            before_0003 = conn.execute(query).fetchone()[0]
    finally:
        with admin("postgres") as conn:
            conn.execute(psql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(psql.Identifier(fresh)))
    manage_as_owner("migrate", "erasure", "0002", "--verbosity", "0")
    try:
        reversed_ = owner.execute(query).fetchone()[0]
        assert reversed_ == before_0003 == catalog.without_custody(with_custody)
        assert "agreements_custodyenvelope" not in reversed_ and catalog.CUSTODY_BEGIN not in reversed_
    finally:
        manage_as_owner("migrate", "--verbosity", "0")
    assert owner.execute(query).fetchone()[0] == with_custody


# --- the data review of PR #102, K2: the plaintext refusal is the committed call's own --------------------------------

def test_9kg_34_a_document_left_in_the_clear_past_the_dry_run_is_refused_after_the_commit_and_the_rerun_finishes(
        privileged_reset, decided, custody, monkeypatch):
    monkeypatch.setattr(registry, "REGISTRY", DESTROYING)
    app = subject()
    sealed = drill.synthetic_document(app, b"%PDF-1.7 synthetic sealed")
    drill.synthetic_document(app, b"%PDF-1.7 synthetic legacy", sealed=False)
    real_call = service._call

    def racing(conn, *args, commit):
        result = real_call(conn, *args, commit=commit)
        if not commit:  # the dry run read the documents before a concurrent change: it saw none in the clear
            result = {**result, "custody_plaintext": 0}
        return result
    monkeypatch.setattr(service, "_call", racing)
    with pytest.raises(service.Refused, match="custody_plaintext_unmigrated_after_commit"):
        erase(privileged_reset, app.public_ref)
    assert record.list_open()["open"] == [str(app.public_ref)]  # the intent stays open
    assert keystore.present(sealed.envelope.key_ref) == (True, True)  # nothing destroyed
    monkeypatch.setattr(service, "_call", real_call)
    with pytest.raises(service.Refused, match="custody_plaintext_unmigrated_after_commit"):
        erase(privileged_reset, app.public_ref)  # the resumed branch makes the same check
    assert command("catalyst_custody_keys", "--migrate", "--confirm")[1]["sealed"] == 1
    outcome = erase(privileged_reset, app.public_ref)
    assert outcome.resumed and outcome.keys_destroyed == 2 and outcome.retained == []
    assert record.list_open()["open"] == []


# --- the data review of PR #102, K4: the audit row names the key destruction -----------------------------------------

def test_9kg_34_the_first_erasure_under_destroy_key_names_the_key_destruction_in_its_audit_row(
        privileged_reset, decided, custody, monkeypatch):
    from tests.test_erasure import audits

    kept = subject(email="other@example.test", name="Other Example")
    drill.synthetic_document(kept, b"%PDF-1.7 synthetic other")
    erase(privileged_reset, kept.public_ref)  # under retain: no mention
    assert catalog.CUSTODY_AUDIT_CLASS not in audits(privileged_reset, kept.public_ref)[0][4]
    monkeypatch.setattr(registry, "REGISTRY", DESTROYING)
    app = subject()
    drill.synthetic_document(app, b"%PDF-1.7 synthetic")
    erase(privileged_reset, app.public_ref)
    classes = audits(privileged_reset, app.public_ref)[0][4]
    assert classes == [*registry.anonymized_classes(DESTROYING), catalog.CUSTODY_AUDIT_CLASS]
    intent = [e for e in erasure_entries() if e.kind == "erasure_intent" and e.key == f"erasure:{app.public_ref}"][0]
    assert catalog.CUSTODY_AUDIT_CLASS not in intent.data["classes"]  # the replay's classes stay the registry's


# --- the data review of PR #102, K5: the envelope's rules -------------------------------------------------------------

@pytest.mark.django_db
def test_9kg_34_envelope_rules_one_per_document_hex_formats_and_unmigrated_means_the_documents_own_file(custody):
    from django.db import IntegrityError, transaction

    app = subject()
    stored = drill.synthetic_document(app, b"%PDF-1.7 synthetic stored")
    legacy = drill.synthetic_document(app, b"%PDF-1.7 synthetic legacy", sealed=False)
    _interrupted_migration(legacy)
    for envelope in CustodyEnvelope.objects.select_related("document"):
        if not envelope.migrated:  # sealed when stored: the document's own file
            assert envelope.storage_key == envelope.document.storage_key
        else:
            assert envelope.storage_key != envelope.document.storage_key
    assert CustodyEnvelope.objects.filter(migrated=False).count() == 1
    fields = {**{f: getattr(stored.envelope, f) for f in ("scheme", "wrapping_key_id", "cipher_size")},
              "storage_key": f"{uuid.uuid4().hex}.pdf"}
    for bad in ({"cipher_sha256": "X" * 64, "key_ref": secrets.token_hex(16)},
                {"cipher_sha256": "0" * 64, "key_ref": "not-a-reference"}):
        with pytest.raises(IntegrityError), transaction.atomic():
            CustodyEnvelope.objects.create(document=drill.synthetic_document(app, b"%PDF-1.7 x", sealed=False),
                                           **fields, **bad)
    with pytest.raises(IntegrityError), transaction.atomic():  # one envelope per document
        CustodyEnvelope.objects.create(document=stored, **fields, cipher_sha256="0" * 64, key_ref=secrets.token_hex(16))


# --- the review of PR #102, H: no staging service holds custody keys yet ---------------------------------------------

def test_9kg_34_no_staging_service_holds_the_custody_key_volumes_or_the_wrapping_key_until_9kg_28():
    """The rendered staging stack gives no service the key volumes or the wrapping key's secret; when 9kg.28 wires them,
    only web (read-only) and worker may hold them. scripts/staging_check.sh checks the same on the running stack."""
    import importlib.util

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("render", root / "scripts" / "render_staging_compose.py")
    render = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(render)
    services = render.definition()["services"]
    for name, svc in services.items():
        text = json.dumps({"volumes": svc.get("volumes", []), "secrets": svc.get("secrets", [])})
        assert "custody-keys" not in text and "custody_wrapping_key" not in text, name
    assert "custody_wrapping_key" not in render.SECRET_FILES
    script = (root / "scripts" / "staging_check.sh").read_text()
    assert "custody_free_config" in script and "for service in web worker fetcher egress proxy db" in script
