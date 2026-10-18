"""Custody storage for signed agreement PDFs (021 section 7; 4B.3; POL-09 decides the production location and
encryption). Synthetic P4 stores into CATALYST_AGREEMENT_STORAGE_DIR, a test or development directory outside the
repository and any web root (config.guards.agreement_problems).

- Keys are system-generated (`<uuid>.pdf`); no path ever comes from input, so traversal is impossible by
  construction, and a key is re-validated before use.
- The directory must be a real directory owned by this process's user with no group or other access.
- Files are created exclusively (`O_EXCL`, never overwriting), without following links (`O_NOFOLLOW`), mode 0600,
  flushed to disk, then re-opened and re-hashed before anything is recorded.
- Reading opens once without following links, checks it is a regular file owned by this user with no group or other
  access and of the recorded size, reads the bytes once and hashes exactly those bytes: what is served is what was
  verified (no re-open between the check and the use).

Limit, stated: matching the re-read proves the stored copy equals what was transferred, not that the provider's copy
was never altered.
"""

import hashlib
import os
import re
import stat
import uuid
from pathlib import Path

from django.conf import settings

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


def write(data: bytes) -> tuple[str, str]:
    """Store `data` under a new key and verify it by re-reading. Returns (key, sha256). Never overwrites."""
    key = f"{uuid.uuid4().hex}.pdf"
    digest = sha256(data)
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
    if read(key, digest, len(data)) != data:
        raise StorageError("storage_verify_failed")
    return key, digest


def read(key: str, expected_sha256: str, size: int) -> bytes:
    """The stored bytes, opened once and verified: wrong type, owner, mode, size or hash refuses. What is returned is
    exactly what was hashed (no re-open between the check and the use)."""
    directory = _open_dir()
    try:
        try:
            fd = os.open(_key(key), os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        except OSError:
            raise StorageError("stored_file_missing") from None
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
