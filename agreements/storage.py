"""Custody storage for signed agreement PDFs (021 section 7; 4B.3; 9kg.34 encrypts at rest; POL-09, owner decision
211.7.9, decides the production location). Synthetic P4 stores into CATALYST_AGREEMENT_STORAGE_DIR, a test or
development directory outside the repository and any web root (config.guards.agreement_problems).

- Keys are system-generated (`<uuid>.pdf`); no path ever comes from input, so traversal is impossible by
  construction, and a key is re-validated before use.
- The directory must be a real directory owned by this process's user with no group or other access.
- Files are created exclusively (`O_EXCL`, never overwriting), without following links (`O_NOFOLLOW`), mode 0600,
  flushed to disk, then re-opened and re-hashed before anything is recorded.
- Reading opens once without following links, checks it is a regular file owned by this user with no group or other
  access and of the recorded size, reads the bytes once and hashes exactly those bytes: what is served is what was
  verified (no re-open between the check and the use).

**Encryption at rest (9kg.34).** Every write is sealed (agreements.keystore): a new data key per document, AES-256-GCM,
the wrapped key outside the backup's rollback domain. A write refuses when the keys are not configured, so no new
document is ever stored in the clear. The file keeps the `<uuid>.pdf` name form (every key check is one pattern) and
holds the sealed bytes; its `CustodyEnvelope` row records the key reference and the SHA-256 and size of the sealed
bytes, which the backup and the restore check without any key. Reading a sealed document checks the sealed bytes
against the envelope, opens them under their own key, then checks the plaintext against `StoredDocument.sha256` and
`size` exactly as before: the recorded hash is still the plaintext's. A document stored before 9kg.34 (no envelope)
is read as plaintext, verified the same way, until the operator migrates it (`catalyst_custody_keys --migrate`),
which seals it under a new name, records the envelope and then removes the plaintext file.

Limit, stated: matching the re-read proves the stored copy equals what was transferred, not that the provider's copy
was never altered. The claim covers v2's custody copy only; the provider's copy is under P4-D-15 until POL-10.
"""

import errno
import hashlib
import os
import re
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from . import keystore

KEY = re.compile(r"[0-9a-f]{32}\.pdf")


class StorageError(Exception):
    """Storage refused or failed; the message is a reason code."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def root() -> Path:
    configured = settings.CATALYST_AGREEMENT_STORAGE_DIR
    if not configured:
        raise StorageError("storage_not_configured")
    path = Path(configured)
    if not path.is_absolute():
        raise StorageError("storage_not_absolute")
    return path


def _open_dir() -> int:
    """The storage directory, opened once without following a link and checked through its descriptor; every file
    operation then works relative to that descriptor, so the directory cannot be swapped underneath (security review
    of PR #43)."""
    path = root()
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise StorageError("storage_unavailable") from None
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        os.close(fd)
        raise StorageError("storage_directory_unsafe")
    return fd


def _key(key: str) -> str:
    if not KEY.fullmatch(key or ""):
        raise StorageError("storage_key_invalid")
    return key


def _checked(fd: int, size: int | None = None) -> os.stat_result:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise StorageError("stored_file_unsafe")
    if size is not None and info.st_size != size:
        raise StorageError("stored_file_size_mismatch")
    return info


def _read_all(fd: int) -> bytes:
    chunks = []
    while chunk := os.read(fd, 65536):
        chunks.append(chunk)
    return b"".join(chunks)


# Codes that mean the stored bytes themselves are wrong, as opposed to storage being unavailable.
INTEGRITY = ("stored_file_missing", "stored_file_unsafe", "stored_file_size_mismatch", "stored_file_mismatch")
# 9kg.34: the document's key was destroyed (an erasure): neither an outage nor corruption.
DESTROYED = "custody_key_destroyed"


@dataclass(frozen=True)
class Sealed:
    """What a `CustodyEnvelope` row records about a sealed file (the same field names, so either may be passed)."""

    storage_key: str
    key_ref: str
    wrapping_key_id: str
    cipher_sha256: str
    cipher_size: int
    scheme: str = keystore.SCHEME

    def fields(self) -> dict:
        return {"storage_key": self.storage_key, "key_ref": self.key_ref, "wrapping_key_id": self.wrapping_key_id,
                "cipher_sha256": self.cipher_sha256, "cipher_size": self.cipher_size, "scheme": self.scheme}


def refuse_live_undecided() -> None:
    """A live environment stores nothing while the owner's custody decision (agreements.custody_policy) is open."""
    from config.guards import LIVE_ENVIRONMENTS

    from . import custody_policy

    if getattr(settings, "CATALYST_ENV", "") in LIVE_ENVIRONMENTS and custody_policy.problems():
        raise StorageError("custody_undecided")


def _write_new(key: str, data: bytes) -> None:
    directory = _open_dir()
    try:
        try:
            fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        except OSError:
            raise StorageError("storage_write_failed") from None
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        except OSError:
            raise StorageError("storage_write_failed") from None
        finally:
            os.close(fd)
        try:
            os.fsync(directory)  # the new name is durable too
        except OSError:
            raise StorageError("storage_write_failed") from None
    finally:
        os.close(directory)


def _seal(data: bytes, key: str) -> Sealed:
    """Seal `data` for the file `key` and write it; the key is durable in both key directories first."""
    try:
        ref, wrapped_by, sealed = keystore.seal(data, key)
    except keystore.KeyStoreError as exc:
        raise StorageError("custody_keys_not_configured" if exc.code in ("keys_not_configured", "wrapping_key_missing")
                           else "custody_key_unavailable") from None
    try:
        _write_new(key, sealed)
    except BaseException:
        _discard_key(ref)  # no sealed file was recorded: the new key goes with it (review of PR #102, F2)
        raise
    return Sealed(storage_key=key, key_ref=ref, wrapping_key_id=wrapped_by, cipher_sha256=sha256(sealed),
                  cipher_size=len(sealed))


def _discard_key(ref: str) -> None:
    try:
        keystore.discard(ref)
    except keystore.KeyStoreError:
        pass  # the store is unavailable: the key stays an orphan, which `--status` reports and `--reap-orphans` removes


def discard(sealed) -> None:
    """Undo a sealed write that will not be recorded: its never-used key and its file (a write, a migration or a custody
    run that failed or found the work decided meanwhile; review of PR #102, F2). Best effort: what cannot be removed
    now is an orphan that `catalyst_custody_keys --status` reports and `--reap-orphans` removes."""
    _discard_key(sealed.key_ref)
    try:
        directory = _open_dir()
    except StorageError:
        return
    try:
        os.unlink(_key(sealed.storage_key), dir_fd=directory)
        os.fsync(directory)
    except (OSError, StorageError):
        pass
    finally:
        os.close(directory)


def write(data: bytes) -> tuple[str, str, Sealed]:
    """Store `data` sealed under a new key and verify it by re-reading and opening it. Returns (key, plaintext sha256,
    the envelope to record). Never overwrites; refuses without custody keys (9kg.34: nothing new in the clear)."""
    refuse_live_undecided()
    if not keystore.configured():
        raise StorageError("custody_keys_not_configured")
    key = f"{uuid.uuid4().hex}.pdf"
    digest = sha256(data)
    os.close(_open_dir())  # the directory first: no key is made for a write that cannot land
    envelope = _seal(data, key)
    try:
        if read(key, digest, len(data), envelope) != data:
            raise StorageError("storage_verify_failed")
    except BaseException:
        discard(envelope)
        raise
    return key, digest, envelope


def seal_existing(key: str, expected_sha256: str, size: int) -> Sealed:
    """9kg.34 migration: read a plaintext document (verified against its recorded hash), seal it under a new name and
    verify the sealed copy opens to the same bytes. The plaintext file is left for `dispose_plaintext`, after the
    envelope row is committed, so a reader always finds one verifiable copy."""
    refuse_live_undecided()
    data = read(key, expected_sha256, size)
    if data.startswith(keystore.MAGIC):
        raise StorageError("stored_file_mismatch")  # sealed bytes where plaintext was recorded: never sealed twice
    new_key = f"{uuid.uuid4().hex}.pdf"
    envelope = _seal(data, new_key)
    try:
        if read(key, expected_sha256, size, envelope) != data:
            raise StorageError("storage_verify_failed")
    except BaseException:
        discard(envelope)
        raise
    return envelope


def dispose_plaintext(key: str) -> bool:
    """Remove a migrated document's plaintext file (its envelope is committed). True when a file was removed."""
    directory = _open_dir()
    try:
        try:
            os.unlink(_key(key), dir_fd=directory)
            removed = True
        except FileNotFoundError:
            removed = False
        except OSError:
            raise StorageError("storage_unavailable") from None
        os.fsync(directory)
        return removed
    finally:
        os.close(directory)


def discard_file(key: str) -> bool:
    """Remove one custody file by its key (an orphan the owner reaps). True when a file was removed."""
    return dispose_plaintext(key)


def exists(key: str) -> bool:
    directory = _open_dir()
    try:
        os.stat(_key(key), dir_fd=directory, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False
    finally:
        os.close(directory)


def _read_verified(key: str, expected_sha256: str, size: int) -> bytes:
    directory = _open_dir()
    try:
        try:
            fd = os.open(_key(key), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        except OSError as exc:
            # Missing, a link, or not ours is about the file; anything else (descriptor limits, I/O) is the
            # environment and never blames the document (reviews of PR #43).
            code = "stored_file_missing" if exc.errno in (errno.ENOENT, errno.ELOOP, errno.EACCES) else "storage_unavailable"
            raise StorageError(code) from None
    finally:
        os.close(directory)
    try:
        _checked(fd, size)
        try:
            data = _read_all(fd)
        except OSError:
            raise StorageError("storage_unavailable") from None
    finally:
        os.close(fd)
    if len(data) != size or sha256(data) != expected_sha256:
        raise StorageError("stored_file_mismatch")
    return data


def read(key: str, expected_sha256: str, size: int, envelope=None) -> bytes:
    """The stored bytes, opened once and verified: wrong type, owner, mode, size or hash refuses. What is returned is
    exactly what was hashed (no re-open between the check and the use). With an envelope (a `CustodyEnvelope` row or a
    `Sealed`), the sealed file it names is verified against its own hash and size, opened under its own key, and the
    plaintext is verified against `expected_sha256` and `size`: a destroyed key refuses with `custody_key_destroyed`, a
    key store that cannot be read with `custody_key_unavailable` (the environment), sealed bytes that do not open with
    `stored_file_mismatch` (the document)."""
    if envelope is None:
        return _read_verified(key, expected_sha256, size)
    sealed = _read_verified(envelope.storage_key, envelope.cipher_sha256, envelope.cipher_size)
    try:
        data = keystore.open_sealed(sealed, envelope.storage_key, envelope.key_ref)
    except keystore.KeyStoreError as exc:
        if exc.code == "key_destroyed":
            raise StorageError(DESTROYED) from None
        # key_lost, key_needs_recovery, a store that is missing or unmarked, the journal: the environment, never an
        # erasure (security review of PR #102, F1)
        if exc.code == "sealed_file_invalid":
            raise StorageError("stored_file_mismatch") from None
        raise StorageError("custody_key_unavailable") from None
    if len(data) != size or sha256(data) != expected_sha256:
        raise StorageError("stored_file_mismatch")
    return data
