"""Release preconditions (bead catalyst-v2-oyu): the release publishes an already-tested, already-merged commit and
writes nothing to the repository's history.

The version and changelog change arrives through an ordinary reviewed pull request (`scripts/prepare_release.py`
writes it locally). The release workflow then calls this script on the commit it would publish, which must:

- carry the requested version in `version.txt` and in `pyproject.toml`'s `version`;
- have a `## [vX.Y.Z]` entry in CHANGELOG.md;
- be the current head of `origin/main` (merged and tested; never an older commit or a branch);
- not already be tagged with that version.

Only after this and `scripts/require_green_ci.py` pass does the workflow ask GitHub to create the release, with the
tag created server-side on exactly that commit: no commit, no `git push`, no client-side tag.

Usage: python3 scripts/release_check.py <vX.Y.Z> <commit-sha>   (run in a checkout of that commit)
Standard library only. Exit 0 when releasable, 1 when refused, 2 on bad arguments.
"""

import re
import subprocess
import sys
from pathlib import Path

VERSION = re.compile(r"v(\d+)\.(\d+)\.(\d+)")


def git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def problems(version: str, sha: str, root: Path) -> list[str]:
    found = []
    number = version[1:]
    if git("rev-parse", "HEAD").stdout.strip() != sha:
        found.append(f"the checkout is not {sha}")
    text = (root / "version.txt").read_text().strip() if (root / "version.txt").exists() else ""
    if text != number:
        found.append(f"version.txt says {text!r}, not {number!r}")
    pyproject = (root / "pyproject.toml").read_text() if (root / "pyproject.toml").exists() else ""
    declared = re.search(r'^version = "([^"]*)"', pyproject, flags=re.M)
    if declared is None:
        found.append("pyproject.toml declares no version")
    elif declared[1] != number:
        found.append(f"pyproject.toml says {declared[1]!r}, not {number!r}")
    changelog = (root / "CHANGELOG.md").read_text() if (root / "CHANGELOG.md").exists() else ""
    if not re.search(rf"^## \[{re.escape(version)}\]", changelog, flags=re.M):
        found.append(f"CHANGELOG.md has no '## [{version}]' entry")
    if git("rev-parse", "origin/main").stdout.strip() != sha:
        found.append(f"{sha} is not the head of origin/main: release only main's current, merged, tested commit")
    if git("rev-parse", "--verify", "--quiet", f"refs/tags/{version}").returncode == 0:
        found.append(f"tag {version} already exists")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 3 or not VERSION.fullmatch(argv[1]) or not re.fullmatch(r"[0-9a-f]{40}", argv[2]):
        print("usage: release_check.py vX.Y.Z <40-hex commit sha>")
        return 2
    found = problems(argv[1], argv[2], Path.cwd())
    if found:
        print("release refused:\n" + "\n".join(f"- {p}" for p in found))
        return 1
    print(f"{argv[1]} may be released from {argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
