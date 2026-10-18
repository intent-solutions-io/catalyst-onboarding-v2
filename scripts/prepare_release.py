"""Prepare a version change for an ordinary pull request (bead catalyst-v2-oyu). Writes `version.txt`, the
`pyproject.toml` version and a CHANGELOG.md entry built from the commit subjects since the previous tag. It never
commits, tags or pushes: review and merge the change like any other, then run the release workflow on the merged
commit.

Usage: python3 scripts/prepare_release.py vX.Y.Z
"""

import datetime
import re
import subprocess
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not re.fullmatch(r"v\d+\.\d+\.\d+", argv[1]):
        print("usage: prepare_release.py vX.Y.Z")
        return 2
    version, root = argv[1], Path.cwd()
    previous = subprocess.run(["git", "describe", "--tags", "--abbrev=0"], capture_output=True, text=True).stdout.strip()
    span = [f"{previous}..HEAD"] if previous else []
    subjects = subprocess.run(["git", "log", *span, "--pretty=format:- %s (%h)"], capture_output=True, text=True).stdout
    (root / "version.txt").write_text(version[1:] + "\n")
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        pyproject.write_text(re.sub(r'^version = "[^"]*"', f'version = "{version[1:]}"', pyproject.read_text(), count=1, flags=re.M))
    changelog = root / "CHANGELOG.md"
    entry = f"## [{version}] - {datetime.date.today().isoformat()}\n\n{subjects}\n\n"
    text = changelog.read_text() if changelog.exists() else "# Changelog\n\n"
    head, _, rest = text.partition("\n")
    changelog.write_text(f"{head}\n\n{entry}{rest.lstrip(chr(10))}")
    print(f"prepared {version}: review the diff, open a pull request, merge it, then run the release workflow")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
