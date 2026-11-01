"""The approved prompt pack (018 5.1, 5.5; P3-D-4, P3-D-8): the system prompt and the rubric, versioned and pinned
by digest. A pack whose files do not match the pinned digest is refused; changing a pack means a new version, and
old runs keep the version and digest they recorded. The rubric is synthetic until POL-04 wording is approved."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "prompts"
CURRENT = "assessment_v3"
INTERPRET = "interpret_v1"  # 3B.3: the reply-interpretation pack (system prompt only, no rubric)
CLARIFY = "clarify_v1"  # bgl.12: the clarification draft pack (system prompt only), used only under the routine activation
CHECK = "check_v1"  # bgl.12: the second pass that checks a draft before it may be sent
# The digest of each pack version as reviewed. Recomputed at every load; a mismatch refuses the run (TEST-P3-33).
PINNED = {
    "assessment_v3": "75e5859c746e62f14d1c99a4bdbb75a4dec1eecdedefe035c24291847ead931f",
    "interpret_v1": "e375064b56dfa787c628dbc6822b65f76edfaa1373a92ce312ef6e0c79250592",
    "clarify_v1": "d851f7b591a0037e8f02e40299085a96616c396ce738cb4292f6ab595631efb2",
    "check_v1": "197adc0d76d4aedd1dc0f5605e1d2728628611406378d1e8a78b4e31d9136970",
    "assessment_v2": "6ac79ac9cbc34c8e0b824f4127c5b4975bc2a803e5320fe47531369b68499dd5",
    "assessment_v1": "524730fc13cb964271e5fb709e0c58ad9d85c22c960d6f1e0f083806b6d7d892",
}


class PackRefused(Exception):
    pass


@dataclass(frozen=True)
class Pack:
    name: str
    sha256: str
    system: str
    rubric: dict

    @property
    def criteria(self) -> list:
        return self.rubric["criteria"]

    @property
    def rubric_version(self) -> int:
        return self.rubric["rubric_version"]


_NAME = re.compile(r"^(assessment|interpret|clarify|check)_v[0-9]{1,3}$")


def _files(name: str) -> dict:
    """Each file's bytes, read once (the digest and the content come from the same read)."""
    if name not in PINNED or not _NAME.match(name):
        raise PackRefused("prompt_pack_unknown")
    try:
        return {p.name: p.read_bytes() for p in sorted((ROOT / name).iterdir()) if p.is_file()}
    except OSError:
        raise PackRefused("prompt_pack_unreadable") from None


def _digest(files: dict) -> str:
    h = hashlib.sha256()
    for file_name, data in files.items():
        h.update(f"{file_name}\0{len(data)}\0".encode())
        h.update(data)
    return h.hexdigest()


def load(name: str = CURRENT) -> Pack:
    files = _files(name)
    actual = _digest(files)
    if PINNED[name] != actual:
        raise PackRefused("prompt_pack_digest_mismatch")
    try:
        rubric = json.loads(files["rubric.json"].decode("utf-8"))
        system = files["system.txt"].decode("utf-8")
    except (KeyError, UnicodeDecodeError, ValueError):
        raise PackRefused("prompt_pack_malformed") from None
    criteria = rubric.get("criteria") or []
    if not 1 <= len(criteria) <= 8 or any(len(c.get("id", "")) > 40 or not c.get("id") for c in criteria):
        raise PackRefused("prompt_pack_malformed")
    return Pack(name, actual, system, rubric)


@dataclass(frozen=True)
class TextPack:
    name: str
    sha256: str
    system: str


def load_text(name: str = INTERPRET) -> TextPack:
    """A pinned pack holding only a system prompt (reply interpretation, 018 5.4)."""
    files = _files(name)
    actual = _digest(files)
    if PINNED[name] != actual:
        raise PackRefused("prompt_pack_digest_mismatch")
    try:
        return TextPack(name, actual, files["system.txt"].decode("utf-8"))
    except (KeyError, UnicodeDecodeError):
        raise PackRefused("prompt_pack_malformed") from None
