"""Custody keys (9kg.34; 026 section 6 option c; council record 030 Q3 and Q4, D-51): per-document data keys, wrapped
under one wrapping key, kept outside the application backup's rollback domain, recoverable while they must be and
destroyable so that a destroyed document's sealed copy, in custody or in any backup, cannot be opened without a surviving copy of the wrapped key and the wrapping key.

**The cryptography** is the reviewed `cryptography` library's AES-256-GCM (`AESGCM`), nothing bespoke:

- each stored document gets its own random 256-bit data key and a random 96-bit nonce; the sealed file is
  `MAGIC || nonce || AES-256-GCM(data key, nonce, plaintext, aad)`, the associated data binding it to the scheme, its
  own file name, its key reference and the recorded plaintext hash, so a file moved to another name, paired with
  another key or claimed by another row does not open;
- each data key is wrapped the same way under the wrapping key, with its reference as associated data, and the
  wrapped form is the only form ever written to disk.

**Where the keys live, and why a restore cannot bring one back.** Not in the database and not in the custody
directory, which are the two things the application backup copies (config.backup): in their own directory,
`CATALYST_CUSTODY_KEY_DIR`, one file `<reference>.key` per document, 0600 in a 0700 directory owned by the process
user. That directory is outside the backup set by construction (the backup copies only the files its snapshot names,
by the custody key pattern) and by rule (config.guards refuses a key directory inside the custody directory, the
journal or the repository, and config.backup refuses an output directory that overlaps a key directory). It is the
same separation 9kg.32 uses for the erasure journal and its head. A restore therefore brings back the database rows
and the sealed files of its time, never a key: once a key is destroyed, the sealed file in an older set cannot be opened without a surviving copy of the wrapped key and the wrapping key
(tests/test_custody_encryption.py shows it through a real backup and restore). The directories must exist and carry
the provisioning marker (`catalyst_custody_keys --provision`); nothing creates them on the fly, so an unmounted volume
fails closed instead of reading as an empty store. `sweep` finishes every journaled destruction at the restore lift and
at the web and worker start-up.

**Recovery, without defeating destruction.** Two safeguards, either of which alone keeps an erased document erased:

1. *The escrow holds the wrapping key only.* Its recovery copy lives in the operator's encrypted secret store (the
   estate's SOPS pattern), with the named holder of `agreements.custody_policy` (`recovery_holder`). A wrapping key
   unwraps a data key only if the wrapped data key still exists somewhere; the escrow never holds a data key, so
   recovering the wrapping key alone does not recover a destroyed document.
2. *The mirror is a live copy, never a point-in-time one, and destruction reaches it first.* Every wrapped data key is
   written to the key directory and to `CATALYST_CUSTODY_KEY_MIRROR_DIR` (a second location the owner names, ideally
   another device) before the document is sealed, and destroyed in the mirror before the primary. `recover` copies
   between the two only keys that the erasure journal does not record as destroyed, and finishes any destruction it
   finds half done. Neither directory may be in a versioned backup: an archive of either would be a point-in-time
   copy that destruction cannot reach (the owner's provisioning rule, stated in 026 section 16).

So a lost primary is recovered from the mirror, a lost wrapping key from the escrow, and a lost primary and mirror
together lose v2's copies of the documents (the provider's copy remains, under P4-D-15): the stated limit of a
destroyable key.

**Destruction** (`destroy`) is an erasure step (erasure.service): it journals `custody_key_destroyed` for each key
before unlinking it (the restrictive class of the journal's consistency model: a destruction recorded but interrupted
is finished by the next run or by `recover`, never undone), then unlinks the mirror's copy, then the primary's, and
fsyncs both directories. It needs the key directories but not the wrapping key: the erasure command never holds it.

**Who may read the wrapping key.** The web process (retrieval for decision-makers only, P4-D-16), the worker (it seals
what custody stores) and the owner-run custody commands. The fetcher, the post-restore step, the backup and the
erasure command never do (config.guards, config.backup, the erasure command).

Limits, stated (review of PR #102, F5, F9, F10):

- A destroyed document stays readable to anyone holding a surviving copy of its wrapped key *and* the wrapping key: a
  stray archive or snapshot of a key directory, an unlinked file's blocks not yet reused, a copy-on-write or SSD
  remnant, or a wrapped key in swap or a core dump. Unlinking does not scrub storage blocks; on SSDs and copy-on-write
  filesystems no overwrite reliably does. The only way to retire such remnants is to rotate the wrapping key (rewrap
  every live data key under a new one) and then destroy the old wrapping key everywhere, the escrow included:
  `rotate` and `retire` below (9kg.69).
- The processes that hold the wrapping key or a data key should run without swap and with core dumps disabled; that
  is host configuration (9kg.28), not this code.
- The wrapping key's escrow is the operator's process, not this code.
- Disk encryption on the host is separate and is not what makes erasure work.
"""

import base64
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

SCHEME = "aes-256-gcm/v1"
REF = re.compile(r"[0-9a-f]{32}")
KEY_FILE = re.compile(r"([0-9a-f]{32})\.key")
WRAPPING_KEY = re.compile(r"[0-9a-f]{64}")
MAGIC = b"CATALYST-CUSTODY-AES256GCM-1\n"
NONCE = 12
WRAP_AAD = b"catalyst-custody-data-key\n"
DOCUMENT_AAD = b"catalyst-custody-document\n"
KEY_ID_PREFIX = b"catalyst-custody-wrapping-key-id\n"
DESTROYED = "custody_key_destroyed"  # the journal kind (workflow.journal.KINDS)
# Each key directory carries this marker, written only by `provision` (`catalyst_custody_keys --provision`). A directory
# without it (an unmounted volume, an empty replacement) is never read as "no keys" and never created on the fly.
MARKER = ".catalyst-custody-key-store"
MARKER_TEXT = b"catalyst custody key store v1\n"


class KeyStoreError(Exception):
    """A reason code: `keys_not_configured`, `wrapping_key_missing`, `wrapping_key_invalid`, `wrapping_key_mismatch`,
    `key_destroyed` (journaled as destroyed), `key_lost` (absent from both directories and not journaled),
    `key_needs_recovery`, `key_corrupt`, `key_store_unsafe`, `key_store_unavailable` (a directory or its provisioning
    marker is missing), `destruction_incomplete`, `journal_unavailable`, `sealed_file_invalid`."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --- configuration ------------------------------------------------------------------------------------------------

def wrapping_key() -> bytes:
    value = getattr(settings, "CATALYST_CUSTODY_WRAPPING_KEY", "") or ""
    if not value:
        raise KeyStoreError("wrapping_key_missing")
    if not WRAPPING_KEY.fullmatch(value):
        raise KeyStoreError("wrapping_key_invalid")  # 64 lower-case hex: exactly 32 random bytes
    return bytes.fromhex(value)


def next_wrapping_key() -> bytes:
    """9kg.69: the new wrapping key, present only for the owner-run rotation (`custody_next_wrapping_key`)."""
    from config import runtime

    value = getattr(settings, "CATALYST_CUSTODY_NEXT_WRAPPING_KEY", "") or ""
    if not value:
        raise KeyStoreError("next_wrapping_key_missing")
    if runtime.process_kind() != "management":  # review of PR #104, F3: a worker declares itself after the guards ran
        raise KeyStoreError("next_wrapping_key_not_allowed")
    if not WRAPPING_KEY.fullmatch(value):
        raise KeyStoreError("wrapping_key_invalid")
    secret = bytes.fromhex(value)
    if secret == wrapping_key():
        raise KeyStoreError("next_wrapping_key_same")
    return secret


def wrapping_key_id(secret: bytes) -> str:
    """Names the wrapping key in each wrapped key and envelope row, never the key itself."""
    return hashlib.sha256(KEY_ID_PREFIX + secret).hexdigest()[:16]


def directories() -> tuple[Path, Path]:
    primary = str(getattr(settings, "CATALYST_CUSTODY_KEY_DIR", "") or "")
    mirror = str(getattr(settings, "CATALYST_CUSTODY_KEY_MIRROR_DIR", "") or "")
    if not primary or not mirror:
        raise KeyStoreError("keys_not_configured")
    primary_path, mirror_path = Path(primary), Path(mirror)
    if not primary_path.is_absolute() or not mirror_path.is_absolute() or primary_path.resolve() == mirror_path.resolve():
        raise KeyStoreError("key_store_unsafe")
    return primary_path, mirror_path


def configured() -> bool:
    return bool(getattr(settings, "CATALYST_CUSTODY_KEY_DIR", "") and getattr(settings, "CATALYST_CUSTODY_KEY_MIRROR_DIR", ""))


# --- the two directories ------------------------------------------------------------------------------------------

def _open_dir(path: Path) -> int:
    """Opened once without following a link and checked through its descriptor (agreements.storage's rule). Never
    created here, and refused unless it carries the provisioning marker: a missing or unmounted directory fails closed
    (`key_store_unavailable`), it is never mistaken for an empty key store (security review of PR #102, F1)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise KeyStoreError("key_store_unavailable") from None
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        os.close(fd)
        raise KeyStoreError("key_store_unsafe")
    try:
        marker = os.stat(MARKER, dir_fd=fd, follow_symlinks=False)
    except OSError:
        os.close(fd)
        raise KeyStoreError("key_store_unavailable") from None
    if not stat.S_ISREG(marker.st_mode):
        os.close(fd)
        raise KeyStoreError("key_store_unavailable")
    return fd


def provision() -> dict:
    """The one step that creates the key directories (0700) and writes their markers (`catalyst_custody_keys
    --provision`). Idempotent: an existing marked directory is left as it is."""
    report = {}
    for name, path in zip(("primary", "mirror"), directories()):
        os.makedirs(path, mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)
        marker = path / MARKER
        if marker.exists():
            report[name] = "already_provisioned"
            continue
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, MARKER_TEXT)
            os.fsync(fd)
        finally:
            os.close(fd)
        directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        report[name] = "provisioned"
    return report


def _name(ref: str) -> str:
    if not REF.fullmatch(ref or ""):
        raise KeyStoreError("key_store_unsafe")
    return f"{ref}.key"


def _write(path: Path, ref: str, blob: bytes) -> None:
    directory = _open_dir(path)
    try:
        try:
            fd = os.open(_name(ref), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        except OSError:
            raise KeyStoreError("key_store_unavailable") from None
        try:
            view = memoryview(blob)
            while view:  # a short write is completed, never taken for the whole key (review of PR #102)
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
            os.fsync(fd)
        except OSError:
            raise KeyStoreError("key_store_unavailable") from None
        finally:
            os.close(fd)
        os.fsync(directory)
    finally:
        os.close(directory)


def _read(path: Path, ref: str) -> bytes | None:
    """The wrapped key's bytes, or None when the file is absent. A link, a wrong owner or mode is refused."""
    directory = _open_dir(path)
    try:
        try:
            fd = os.open(_name(ref), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        except OSError as exc:
            if exc.errno == errno.ENOENT:
                return None
            raise KeyStoreError("key_store_unsafe" if exc.errno == errno.ELOOP else "key_store_unavailable") from None
    finally:
        os.close(directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise KeyStoreError("key_store_unsafe")
        return os.read(fd, 4096)
    finally:
        os.close(fd)


def _unlink(path: Path, ref: str) -> bool:
    directory = _open_dir(path)
    try:
        try:
            os.unlink(_name(ref), dir_fd=directory)
            removed = True
        except FileNotFoundError:
            removed = False
        except OSError:
            raise KeyStoreError("key_store_unavailable") from None
        try:  # an interrupted rotation's temporary copy of the same key goes with it (review of PR #104, F1)
            os.unlink(f"{_name(ref)}.rotating", dir_fd=directory)
            removed = True
        except FileNotFoundError:
            pass
        except OSError:
            raise KeyStoreError("key_store_unavailable") from None
        os.fsync(directory)
        return removed
    finally:
        os.close(directory)


def _replace(path: Path, ref: str, blob: bytes) -> None:
    """9kg.69: replace a wrapped key file atomically (a temporary name the listing ignores, fsynced, renamed over the
    old one, the directory fsynced): an interruption leaves the old wrapped key or the new one, never neither."""
    directory = _open_dir(path)
    temporary = f"{_name(ref)}.rotating"
    try:
        try:
            os.unlink(temporary, dir_fd=directory)  # a leftover of an interrupted run
        except FileNotFoundError:
            pass
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        except OSError:
            raise KeyStoreError("key_store_unavailable") from None
        try:
            view = memoryview(blob)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError("short write")
                view = view[written:]
            os.fsync(fd)
        except OSError:
            raise KeyStoreError("key_store_unavailable") from None
        finally:
            os.close(fd)
        try:
            os.rename(temporary, _name(ref), src_dir_fd=directory, dst_dir_fd=directory)
        except OSError:
            raise KeyStoreError("key_store_unavailable") from None
        os.fsync(directory)
    finally:
        with contextlib.suppress(OSError):  # review of PR #104, F1: no wrapped key is ever left under another name
            os.unlink(temporary, dir_fd=directory)
        os.close(directory)


def _listing(path: Path) -> set:
    directory = _open_dir(path)
    try:
        return {m.group(1) for name in os.listdir(directory) if (m := KEY_FILE.fullmatch(name))}
    finally:
        os.close(directory)


def strays() -> int:
    """Files in either key directory that are neither the provisioning marker nor `<reference>.key`: an interrupted
    rotation's temporary copy, or anything else that does not belong (review of PR #104, F1)."""
    count = 0
    for path in directories():
        directory = _open_dir(path)
        try:
            count += sum(1 for name in os.listdir(directory) if name != MARKER and not KEY_FILE.fullmatch(name))
        finally:
            os.close(directory)
    return count


@contextlib.contextmanager
def store_lock(exclusive: bool):
    """An advisory lock on the primary key directory (review of PR #104, F2 and F5): a rotation holds it exclusively,
    and creating or destroying a key holds it shared, so no key is created under the old wrapping key or destroyed
    while a rotation reads and replaces it. A rotation that finds it held refuses (`custody_operation_in_progress`)."""
    primary, _ = directories()
    directory = _open_dir(primary)
    try:
        try:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB if exclusive else fcntl.LOCK_SH)
        except BlockingIOError:
            raise KeyStoreError("custody_operation_in_progress") from None
        yield
    finally:
        os.close(directory)  # closing the descriptor releases the lock


# --- wrapping -------------------------------------------------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _wrap(secret: bytes, ref: str, data_key: bytes) -> bytes:
    nonce = os.urandom(NONCE)
    sealed = AESGCM(secret).encrypt(nonce, data_key, WRAP_AAD + ref.encode())
    return json.dumps({"v": 1, "scheme": SCHEME, "wrapping_key_id": wrapping_key_id(secret), "nonce": _b64(nonce),
                       "sealed": _b64(sealed)}, sort_keys=True).encode()


def wrapped_by(blob: bytes) -> str | None:
    """The id of the wrapping key a wrapped key file was written under (9kg.69), or None when the file is unreadable."""
    try:
        value = json.loads(blob)["wrapping_key_id"]
    except (ValueError, KeyError, TypeError):
        return None
    return value if isinstance(value, str) else None


def _unwrap(secret: bytes, ref: str, blob: bytes) -> bytes:
    try:
        record = json.loads(blob)
        nonce, sealed = base64.b64decode(record["nonce"], validate=True), base64.b64decode(record["sealed"], validate=True)
        wrapped_by = record["wrapping_key_id"]
    except (ValueError, KeyError, TypeError):
        raise KeyStoreError("key_corrupt") from None
    if wrapped_by != wrapping_key_id(secret):
        raise KeyStoreError("wrapping_key_mismatch")
    try:
        data_key = AESGCM(secret).decrypt(nonce, sealed, WRAP_AAD + ref.encode())
    except (InvalidTag, ValueError):
        raise KeyStoreError("key_corrupt") from None
    if len(data_key) != 32:
        raise KeyStoreError("key_corrupt")
    return data_key


# --- the operations -------------------------------------------------------------------------------------------------

def create() -> tuple[str, bytes, str]:
    """A new data key, wrapped and durable in both directories before it is used. Returns (reference, data key,
    wrapping key id). A key never exists without its recovery copy: if the mirror write fails, the primary's copy is
    removed and the store refuses."""
    secret = wrapping_key()
    primary, mirror = directories()
    ref = secrets.token_hex(16)
    data_key = AESGCM.generate_key(bit_length=256)
    blob = _wrap(secret, ref, data_key)
    with store_lock(exclusive=False):
        _write(primary, ref, blob)
        try:
            _write(mirror, ref, blob)
        except KeyStoreError:
            _unlink(primary, ref)
            raise
    return ref, data_key, wrapping_key_id(secret)


def journaled_destroyed(verify: bool = False) -> set:
    """The references the journal records as destroyed. Unverified here (the web and worker processes never hold the
    erasure key): a forged entry can only make a key refuse, never make one readable. `journal_unavailable` when the
    journal cannot be read; an unconfigured journal (test and development only) records nothing."""
    from workflow import journal

    if not journal.configured():
        return set()
    try:
        entries = journal.read()
    except journal.JournalError:
        raise KeyStoreError("journal_unavailable") from None
    return _verified_destroyed(entries) if verify else destroyed_refs(entries)


def load(ref: str) -> bytes:
    """The data key, unwrapped from the primary directory. A reference the journal records as destroyed is refused
    (`key_destroyed`) even if a file for it is present (a restored or copied key never revives it). Absent from the
    primary: `key_needs_recovery` while the mirror holds it, else `key_lost` (absent and never journaled: a lost or
    unmounted store, not an erasure; security review of PR #102, F1)."""
    secret = wrapping_key()
    primary, mirror = directories()
    if ref in journaled_destroyed():
        raise KeyStoreError("key_destroyed")
    blob = _read(primary, ref)
    if blob is None:
        raise KeyStoreError("key_needs_recovery" if _read(mirror, ref) is not None else "key_lost")
    return _unwrap(secret, ref, blob)


def document_aad(storage_key: str, ref: str, plaintext_sha256: str) -> bytes:
    """The associated data of a sealed document: the scheme, its file name, its key reference and the plaintext's
    recorded SHA-256 (review of PR #102, F7), so a sealed file opens only for the row that records it."""
    return DOCUMENT_AAD + f"{SCHEME}\n{storage_key}\n{ref}\n{plaintext_sha256}".encode()


def seal(plaintext: bytes, storage_key: str) -> tuple[str, str, bytes]:
    """Seal one document under a new data key. Returns (reference, wrapping key id, sealed bytes)."""
    ref, data_key, wrapped_by = create()
    nonce = os.urandom(NONCE)
    aad = document_aad(storage_key, ref, hashlib.sha256(plaintext).hexdigest())
    return ref, wrapped_by, MAGIC + nonce + AESGCM(data_key).encrypt(nonce, plaintext, aad)


def open_sealed(sealed: bytes, storage_key: str, ref: str, plaintext_sha256: str) -> bytes:
    """The plaintext of a sealed file; `sealed_file_invalid` when the bytes do not open under their own key, name and
    recorded plaintext hash."""
    if not sealed.startswith(MAGIC) or len(sealed) < len(MAGIC) + NONCE + 16:
        raise KeyStoreError("sealed_file_invalid")
    data_key = load(ref)
    nonce = sealed[len(MAGIC):len(MAGIC) + NONCE]
    try:
        return AESGCM(data_key).decrypt(nonce, sealed[len(MAGIC) + NONCE:], document_aad(storage_key, ref, plaintext_sha256))
    except InvalidTag:
        raise KeyStoreError("sealed_file_invalid") from None


def discard(ref: str) -> None:
    """Remove a key that was never used (its sealed file was never recorded): not an erasure, so nothing is journaled.
    Mirror first, as for a destruction."""
    primary, mirror = directories()
    _name(ref)
    _unlink(mirror, ref)
    _unlink(primary, ref)


def present(ref: str) -> tuple[bool, bool]:
    primary, mirror = directories()
    return _read(primary, ref) is not None, _read(mirror, ref) is not None


def destroyed_refs(entries, secret: bytes | None = None, forged: list | None = None) -> set:
    """The key references the journal records as destroyed (or being destroyed): what recovery must never restore.
    With the erasure key, an entry whose `mac` does not verify is left out and its reference added to `forged`, as
    `erasure.record.fold` does (review of PR #102, F6); without it (the web and worker processes, which never hold that
    key) entries count unverified, which can only make a key refuse, never make one readable."""
    import hmac

    from erasure.record import entry_mac

    out = set()
    for entry in entries:
        if entry.kind != DESTROYED:
            continue
        ref = entry.key.partition(":")[2]
        if secret is not None and not hmac.compare_digest(str(entry.data.get("mac", "")),
                                                          entry_mac(entry.kind, entry.key, entry.data, secret)):
            if forged is not None:
                forged.append(ref)
            continue
        out.add(ref)
    return out


def _erasure_secret() -> bytes | None:
    """The erasure key when this process holds one (the erasure command, the owner-run custody commands, the restore),
    else None. A key that is set but unusable refuses."""
    from erasure import record

    if not getattr(settings, "CATALYST_ERASURE_KEY", ""):
        return None
    try:
        return record.key()
    except record.RecordError as exc:
        raise KeyStoreError(f"erasure_{exc.code}") from None


def _verified_destroyed(entries) -> set:
    """Destroyed references for an operation that removes files (sweep, recovery): verified under the erasure key, and
    refused (`forged_entry`) if any entry does not verify. Refused (`erasure_key_missing`) without that key: anyone who
    can write the journal could otherwise append an entry that removes another person's key for good (CodeRabbit on
    PR #102)."""
    secret, forged = _erasure_secret(), []
    if secret is None:
        raise KeyStoreError("erasure_key_missing")
    refs = destroyed_refs(entries, secret, forged)
    if forged:
        raise KeyStoreError("forged_entry")
    return refs


def destroy(subject_ref: str, refs) -> int:
    """Destroy each key: journal it (before), unlink the mirror's copy, then the primary's, then verify that no file
    of any reference remains in either directory (`destruction_incomplete` otherwise). Idempotent. Returns how many key
    files were removed (the caller reports the number of references separately). Needs the key directories (both
    provisioned) and the journal, not the wrapping key."""
    from workflow import journal

    from erasure.record import entry_mac

    primary, mirror = directories()
    if not journal.configured():
        raise KeyStoreError("journal_unavailable")
    secret = _erasure_secret()
    if secret is None:
        raise KeyStoreError("erasure_key_missing")  # every destruction entry carries a mac under the erasure key
    removed = 0
    with store_lock(exclusive=False):  # never while a rotation reads and replaces the files (review of PR #104, F2)
        for ref in sorted(set(refs)):
            _name(ref)
            key, data = f"custody_key:{ref}", {"subject": str(subject_ref), "phase": "prepare"}
            if journal.append(DESTROYED, key, {**data, "mac": entry_mac(DESTROYED, key, data, secret)}) is None:
                raise KeyStoreError("journal_unavailable")  # never unlink what the record does not hold
            removed += int(_unlink(mirror, ref))
            removed += int(_unlink(primary, ref))
    for ref in set(refs):  # verified, not assumed: every reference is gone from both directories
        if _read(mirror, ref) is not None or _read(primary, ref) is not None:
            raise KeyStoreError("destruction_incomplete")
    return removed


def sweep(require_key: bool = False) -> dict:
    """Finish every destruction the journal records (review of PR #102, F4): any key file of a journaled-destroyed
    reference, in either directory, is removed (mirror first) and the removal verified. Needs only the directories and
    the journal, never the wrapping key. It removes files only on entries verified under the erasure key: the restore lift
    holds that key and passes `require_key` (`erasure_key_missing` without it), so a restored or copied key file never
    outlives its journaled destruction. The web and worker processes never hold it: at their start the sweep only checks
    (`checked`) and removes nothing, since an unverified entry may be forged; `load` refuses a journaled reference anyway.
    Not configured: nothing to do. A missing directory, marker or journal refuses (`key_store_unavailable`,
    `journal_unavailable`): fail closed, with or without the key."""
    if not configured():
        return {"status": "not_configured", "removed": 0}
    primary, mirror = directories()
    if _erasure_secret() is None:
        if require_key:
            raise KeyStoreError("erasure_key_missing")
        journaled_destroyed()  # an unreadable journal still refuses
        _listing(primary), _listing(mirror)  # and so does a missing directory or marker
        return {"status": "checked", "removed": 0}
    destroyed = journaled_destroyed(verify=True)
    in_primary, in_mirror = _listing(primary), _listing(mirror)
    removed = 0
    for ref in sorted((in_primary | in_mirror) & destroyed):
        removed += int(_unlink(mirror, ref)) + int(_unlink(primary, ref))
        if _read(mirror, ref) is not None or _read(primary, ref) is not None:
            raise KeyStoreError("destruction_incomplete")
    return {"status": "swept", "removed": removed}


def recover(expected_head: str) -> dict:
    """The named holder's recovery (custody_policy `recovery_holder`): make the primary and the mirror hold the same
    keys again, copying each wrapped key that one lacks from the other after checking that it unwraps under the
    wrapping key; and finish every destruction the journal records, in both. A key the journal records as destroyed is
    never copied anywhere. Refuses without a readable journal, and unless the journal holds `expected_head` (the
    out-of-band head the erasure command prints, PR #99; `none` only for a journal with no erasure and no destruction):
    an emptied, truncated or replaced journal would forget destructions and let recovery revive their keys (review of
    PR #102, F4). The mismatch is `journal_mismatch`."""
    secret = wrapping_key()
    primary, mirror = directories()
    destroyed = _destroyed_at_head(expected_head)
    report = {"copied_to_primary": 0, "copied_to_mirror": 0, "destruction_finished": 0, "unrecoverable": 0}
    in_primary, in_mirror = _listing(primary), _listing(mirror)
    for ref in sorted((in_primary | in_mirror) & destroyed):
        report["destruction_finished"] += int(_unlink(mirror, ref)) + int(_unlink(primary, ref))
    for ref in sorted((in_primary ^ in_mirror) - destroyed):
        source, target, field = (mirror, primary, "copied_to_primary") if ref in in_mirror else (primary, mirror, "copied_to_mirror")
        blob = _read(source, ref)
        try:
            _unwrap(secret, ref, blob or b"")
        except KeyStoreError:
            report["unrecoverable"] += 1  # corrupt or wrapped under another key: reported, never copied
            continue
        _write(target, ref, blob)
        report[field] += 1
    return report


def _destroyed_at_head(expected_head: str) -> set:
    """The verified destroyed references of a journal that holds the out-of-band head (`none` only for a journal with
    no erasure and no destruction): an emptied, truncated or replaced journal would forget destructions."""
    from erasure.record import HEAD
    from workflow import journal

    if not journal.configured():
        raise KeyStoreError("journal_unavailable")
    try:
        entries = journal.read()
        if expected_head == "none":
            if any(e.kind == DESTROYED or e.kind.startswith("erasure_") for e in entries):
                raise journal.JournalError("journal_mismatch")
        else:
            found = HEAD.fullmatch(expected_head or "")
            if found is None or int(found.group(2)) < 1:
                raise KeyStoreError("bad_head")
            journal.verify_anchor(entries, found.group(1), int(found.group(2)), found.group(3))
        return _verified_destroyed(entries)
    except journal.JournalError as exc:
        raise KeyStoreError("journal_mismatch" if exc.code == "journal_mismatch" else "journal_unavailable") from None


def rotate(expected_head: str) -> dict:
    """9kg.69: rewrap every live data key under the next wrapping key, in both directories. Run by the owner with the
    worker and web stopped, holding the current key and the next one (`custody_next_wrapping_key`, this run only).

    The journal must hold the out-of-band head, as for `recover`. Every destruction it records is finished first, and
    a destroyed key is never rewrapped: a rotation cannot revive one. The two directories must hold the same keys
    (`key_needs_recovery` otherwise: run `--recover` first), so no key is rotated in one copy and lost in the other.
    Each copy is unwrapped under the current key, wrapped under the next, checked to unwrap to the same data key, and
    replaced atomically. A copy already under the next key is checked and left; one under any third key is
    `unrecoverable`, and the rotation refuses at the end (`rotation_incomplete`) without journaling completion.
    Interruption is safe: every copy is under one key or the other, both keys are still held, and the same command
    run again finishes the rest. The journal records the start and the completion (`custody_rotation`)."""
    current, upcoming = wrapping_key(), next_wrapping_key()
    with store_lock(exclusive=True):
        return _rotate(current, upcoming, expected_head)


def _rotate(current: bytes, upcoming: bytes, expected_head: str) -> dict:
    from workflow import journal

    primary, mirror = directories()
    destroyed = _destroyed_at_head(expected_head)
    old_id, new_id = wrapping_key_id(current), wrapping_key_id(upcoming)
    key = f"custody_rotation:{old_id}:{new_id}"
    if journal.append("custody_rotation", key, {"from_key": old_id, "to_key": new_id, "phase": "prepare"}) is None:
        raise KeyStoreError("journal_unavailable")
    report = {"from_key": old_id, "to_key": new_id, "rewrapped": 0, "already_rotated": 0, "destruction_finished": 0,
              "unrecoverable": 0}
    in_primary, in_mirror = _listing(primary), _listing(mirror)
    for ref in sorted((in_primary | in_mirror) & destroyed):
        report["destruction_finished"] += int(_unlink(mirror, ref)) + int(_unlink(primary, ref))
    live_primary, live_mirror = in_primary - destroyed, in_mirror - destroyed
    if live_primary != live_mirror:
        raise KeyStoreError("key_needs_recovery")
    for ref in sorted(live_primary):
        held = None  # the data key the two copies must agree on (review of PR #104, F6)
        for directory in (mirror, primary):
            blob = _read(directory, ref) or b""
            by = wrapped_by(blob)
            try:
                if by == new_id:
                    data_key = _unwrap(upcoming, ref, blob)
                elif by == old_id:
                    data_key = _unwrap(current, ref, blob)
                else:
                    raise KeyStoreError("key_corrupt")
            except KeyStoreError:
                report["unrecoverable"] += 1
                continue
            if held is not None and data_key != held:
                report["unrecoverable"] += 1  # the mirror and the primary disagree: never rotated into agreement
                continue
            held = data_key
            if by == new_id:
                report["already_rotated"] += 1
                continue
            rewrapped = _wrap(upcoming, ref, data_key)
            if _unwrap(upcoming, ref, rewrapped) != data_key:
                raise KeyStoreError("key_corrupt")
            _replace(directory, ref, rewrapped)
            report["rewrapped"] += 1
    if report["unrecoverable"] or strays():
        raise KeyStoreError("rotation_incomplete")
    report["keys"] = len(live_primary)
    return report


def retire(retired_id: str, expected_head: str) -> dict:
    """9kg.69: after the owner destroyed the old wrapping key everywhere (its secret file and its escrow copy), check
    that a rotation from it was journaled done, that this process holds neither it nor a next key, that neither
    directory holds a stray file, a file of a destroyed key or a file still under it, and that every live key unwraps
    under the current key; then journal the retirement. The entry is the owner's attestation that the old key is
    destroyed (code cannot see the escrow or a running process's memory). From then on no key opens a remnant wrapped
    under the old key (a stray archive, unlinked blocks, an off-site copy). A data key itself leaked in swap or a core
    dump is outside this claim: rotation changes the wrapping, not the data keys."""
    from workflow import journal

    if not re.fullmatch(r"[0-9a-f]{16}", retired_id or ""):
        raise KeyStoreError("bad_key_id")
    current = wrapping_key()
    if getattr(settings, "CATALYST_CUSTODY_NEXT_WRAPPING_KEY", ""):
        raise KeyStoreError("next_wrapping_key_present")  # the rotation's secret file is removed before retirement
    if wrapping_key_id(current) == retired_id:
        raise KeyStoreError("retired_key_still_current")
    primary, mirror = directories()
    destroyed = _destroyed_at_head(expected_head)
    rotated = [e for e in journal.read() if e.kind == "custody_rotation" and e.data.get("phase") == "done"
               and e.key.startswith(f"custody_rotation:{retired_id}:")]
    if not rotated:
        raise KeyStoreError("rotation_not_done")  # review of PR #104, F4: never an id no rotation retired
    if strays() or (_listing(primary) | _listing(mirror)) & destroyed:
        raise KeyStoreError("rotation_incomplete")
    still = 0
    for directory in (primary, mirror):
        for ref in sorted(_listing(directory) - destroyed):
            blob = _read(directory, ref) or b""
            if wrapped_by(blob) == retired_id:
                still += 1
                continue
            _unwrap(current, ref, blob)  # every live key opens under the current key, or this raises
    if still:
        raise KeyStoreError("rotation_incomplete")
    if journal.append("custody_rotation", f"custody_rotation_retired:{retired_id}",
                      {"from_key": retired_id, "to_key": wrapping_key_id(current), "phase": "done"}) is None:
        raise KeyStoreError("journal_unavailable")
    return {"retired_key": retired_id, "current_key": wrapping_key_id(current)}


def listing() -> tuple[set, set]:
    primary, mirror = directories()
    return _listing(primary), _listing(mirror)
