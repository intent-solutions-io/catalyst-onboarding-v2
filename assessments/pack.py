"""The approved prompt pack (018 5.1, 5.5; P3-D-4, P3-D-8): the system prompt and the rubric, versioned and pinned
by digest. A pack whose files do not match the pinned digest is refused; changing a pack means a new version, and
old runs keep the version and digest they recorded. The rubric is synthetic until POL-04 wording is approved."""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "prompts"
CURRENT = "assessment_v1"
# The digest of assessment_v1 as reviewed. Recomputed at every load; a mismatch refuses the run (TEST-P3-33).
PINNED = {"assessment_v1": '524730fc13cb964271e5fb709e0c58ad9d85c22c960d6f1e0f083806b6d7d892'}


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


def digest(name: str) -> str:
    h = hashlib.sha256()
    for path in sorted((ROOT / name).iterdir()):
        data = path.read_bytes()
        h.update(f"{path.name}\0{len(data)}\0".encode())
        h.update(data)
    return h.hexdigest()


def load(name: str = CURRENT) -> Pack:
    actual = digest(name)
    if PINNED.get(name) != actual:
        raise PackRefused("prompt_pack_digest_mismatch")
    return Pack(name, actual, (ROOT / name / "system.txt").read_text(), json.loads((ROOT / name / "rubric.json").read_text()))
