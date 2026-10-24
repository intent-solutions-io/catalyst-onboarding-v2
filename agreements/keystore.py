"""Custody keys (9kg.34; 026 section 6 option c; council record 030 Q3 and Q4, D-51): per-document data keys, wrapped
under one wrapping key, kept outside the application backup's rollback domain, recoverable while they must be and
destroyable so that no backup, old or new, can yield a destroyed document again.

**The cryptography** is the reviewed `cryptography` library's AES-256-GCM (`AESGCM`), nothing bespoke:

- each stored document gets its own random 256-bit data key and a random 96-bit nonce; the sealed file is
  `MAGIC || nonce || AES-256-GCM(data key, nonce, plaintext, aad)`, the associated data binding it to its own file
  name and key reference, so a file moved to another name or paired with another key does not open;
- each data key is wrapped the same way under the wrapping key, with its reference as associated data, and the
  wrapped form is the only form ever written to disk.

**Where the keys live, and why a restore cannot bring one back.** Not in the database and not in the custody
directory, which are the two things the application backup copies (config.backup): in their own directory,
`CATALYST_CUSTODY_KEY_DIR`, one file `<reference>.key` per document, 0600 in a 0700 directory owned by the process
user. That directory is outside the backup set by construction (the backup copies only the files its snapshot names,
by the custody key pattern) and by rule (config.guards refuses a key directory inside the custody directory, the
journal or the repository, and config.backup refuses an output directory that overlaps a key directory). It is the
same separation 9kg.32 uses for the erasure journal and its head. A restore therefore brings back the database rows
and the sealed files of its time, never a key: a key destroyed after that backup stays destroyed, and the sealed file
in the old set cannot be opened (tests/test_custody_encryption.py proves it through a real backup and restore).

**Recovery, without defeating destruction.** Two safeguards, either of which alone keeps an erased document erased:

1. *The escrow holds the wrapping key only.* Its recovery copy lives in the operator's encrypted secret store (the
   estate's SOPS pattern), with the named holder of `agreements.custody_policy` (`recovery_holder`). A wrapping key
   unwraps a data key only if the wrapped data key still exists somewhere; the escrow never holds a data key, so
   recovering the wrapping key can never recover a destroyed document.
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

Limits, stated: unlinking a file does not scrub the storage blocks beneath it (the filesystem reuses them); the
wrapping key's escrow is the operator's process, not this code; rotating the wrapping key (rewrapping every data key)
is not built yet and is a follow-up; disk encryption on the host is separate and is not what makes erasure work.
"""

import base64
import errno
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
            os.write(fd, blob)
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
        os.fsync(directory)
        return removed
    finally:
        os.close(directory)


def _listing(path: Path) -> set:
    directory = _open_dir(path)
    try:
        return {m.group(1) for name in os.listdir(directory) if (m := KEY_FILE.fullmatch(name))}
    finally:
        os.close(directory)


# --- wrapping -------------------------------------------------------------------------------------------------------

def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _wrap(secret: bytes, ref: str, data_key: bytes) -> bytes:
    nonce = os.urandom(NONCE)
    sealed = AESGCM(secret).encrypt(nonce, data_key, WRAP_AAD + ref.encode())
    return json.dumps({"v": 1, "scheme": SCHEME, "wrapping_key_id": wrapping_key_id(secret), "nonce": _b64(nonce),
                       "sealed": _b64(sealed)}, sort_keys=True).encode()


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
    _write(primary, ref, blob)
    try:
        _write(mirror, ref, blob)
    except KeyStoreError:
        _unlink(primary, ref)
        raise
    return ref, data_key, wrapping_key_id(secret)


def journaled_destroyed() -> set:
    """The references the journal records as destroyed. Unverified here (the web and worker processes never hold the
    erasure key): a forged entry can only make a key refuse, never make one readable. `journal_unavailable` when the
    journal cannot be read; an unconfigured journal (test and development only) records nothing."""
    from workflow import journal

    if not journal.configured():
        return set()
    try:
        return destroyed_refs(journal.read())
    except journal.JournalError:
        raise KeyStoreError("journal_unavailable") from None


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


def document_aad(storage_key: str, ref: str) -> bytes:
    return DOCUMENT_AAD + f"{storage_key}\n{ref}".encode()


def seal(plaintext: bytes, storage_key: str) -> tuple[str, str, bytes]:
    """Seal one document under a new data key. Returns (reference, wrapping key id, sealed bytes)."""
    ref, data_key, wrapped_by = create()
    nonce = os.urandom(NONCE)
    return ref, wrapped_by, MAGIC + nonce + AESGCM(data_key).encrypt(nonce, plaintext, document_aad(storage_key, ref))


def open_sealed(sealed: bytes, storage_key: str, ref: str) -> bytes:
    """The plaintext of a sealed file; `sealed_file_invalid` when the bytes do not open under their own key and name."""
    if not sealed.startswith(MAGIC) or len(sealed) < len(MAGIC) + NONCE + 16:
        raise KeyStoreError("sealed_file_invalid")
    data_key = load(ref)
    nonce = sealed[len(MAGIC):len(MAGIC) + NONCE]
    try:
        return AESGCM(data_key).decrypt(nonce, sealed[len(MAGIC) + NONCE:], document_aad(storage_key, ref))
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


def destroyed_refs(entries) -> set:
    """The key references the journal records as destroyed (or being destroyed): what recovery must never restore."""
    return {e.key.partition(":")[2] for e in entries if e.kind == DESTROYED}


def destroy(subject_ref: str, refs) -> int:
    """Destroy each key: journal it (before), unlink the mirror's copy, then the primary's, then verify that no file
    of any reference remains in either directory (`destruction_incomplete` otherwise). Idempotent. Returns how many key
    files were removed (the caller reports the number of references separately). Needs the key directories (both
    provisioned) and the journal, not the wrapping key."""
    from workflow import journal

    primary, mirror = directories()
    if not journal.configured():
        raise KeyStoreError("journal_unavailable")
    removed = 0
    for ref in sorted(set(refs)):
        _name(ref)
        if journal.append(DESTROYED, f"custody_key:{ref}", {"subject": str(subject_ref), "phase": "prepare"}) is None:
            raise KeyStoreError("journal_unavailable")  # never unlink what the record does not hold
        removed += int(_unlink(mirror, ref))
        removed += int(_unlink(primary, ref))
    for ref in set(refs):  # verified, not assumed: every reference is gone from both directories
        if _read(mirror, ref) is not None or _read(primary, ref) is not None:
            raise KeyStoreError("destruction_incomplete")
    return removed


def sweep() -> dict:
    """Finish every destruction the journal records (review of PR #102, F4): any key file of a journaled-destroyed
    reference, in either directory, is removed (mirror first) and the removal verified. Needs only the directories and
    the journal, never the wrapping key, so it runs where that key is absent: the restore lift and the start of the web
    and worker processes. A restored or copied key file therefore never outlives its journaled destruction. Not
    configured: nothing to do. A missing directory, marker or journal refuses (`key_store_unavailable`,
    `journal_unavailable`): fail closed."""
    if not configured():
        return {"status": "not_configured", "removed": 0}
    primary, mirror = directories()
    destroyed = journaled_destroyed()
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
    from erasure.record import HEAD
    from workflow import journal

    secret = wrapping_key()
    primary, mirror = directories()
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
        destroyed = destroyed_refs(entries)
    except journal.JournalError as exc:
        raise KeyStoreError("journal_mismatch" if exc.code == "journal_mismatch" else "journal_unavailable") from None
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


def listing() -> tuple[set, set]:
    primary, mirror = directories()
    return _listing(primary), _listing(mirror)
