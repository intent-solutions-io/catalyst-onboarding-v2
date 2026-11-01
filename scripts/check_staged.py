#!/usr/bin/env python3
"""Fast, offline checks of the index that Git will commit (9kg.95). Never reads unstaged Python content."""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


def git(*args):
    return subprocess.check_output(["git", *args])


def staged(path):
    return git("show", f":{path}")


def check(ruff):
    started = time.monotonic()
    subprocess.run(["git", "diff", "--cached", "--check"], check=True)
    paths = [
        os.fsdecode(p)
        for p in git(
            "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"
        ).split(b"\0")
        if p and p.endswith(b".py")
    ]
    if not paths:
        print("fast checks: staged whitespace passed; no changed Python files")
        return
    required = re.search(rb"^ruff==([^\s\\]+)", staged("requirements/lint.txt"), re.M)
    if required is None:
        raise RuntimeError("staged requirements/lint.txt has no pinned Ruff version")
    actual = subprocess.check_output([str(ruff), "--version"]).decode().strip()
    if actual != f"ruff {required[1].decode()}":
        raise RuntimeError(
            "Ruff version differs from the staged lock; run python3 scripts/install_fast_checks.py"
        )
    with tempfile.TemporaryDirectory(prefix="catalyst-index-") as temporary:
        root = Path(temporary)
        (root / "pyproject.toml").write_bytes(staged("pyproject.toml"))
        for name in paths:
            # Reject symlinks and unresolved entries instead of linting their targets or the working tree.
            entries = git(
                "--literal-pathspecs", "ls-files", "--stage", "-z", "--", name
            ).split(b"\0")
            if len(entries) != 2 or not entries[0].startswith((b"100644 ", b"100755 ")):
                raise RuntimeError(
                    f"cannot check non-regular staged Python file: {name!r}"
                )
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(staged(name))
        files = [str(root / name) for name in paths]
        subprocess.run(
            [
                str(ruff),
                "format",
                "--check",
                "--no-cache",
                "--config",
                str(root / "pyproject.toml"),
                "--",
                *files,
            ],
            check=True,
            cwd=root,
        )
        subprocess.run(
            [
                str(ruff),
                "check",
                "--no-cache",
                "--config",
                str(root / "pyproject.toml"),
                "--",
                *files,
            ],
            check=True,
            cwd=root,
        )
    print(
        f"fast checks: {len(paths)} staged Python file(s) passed in {time.monotonic() - started:.2f}s"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ruff", type=Path)
    args = parser.parse_args()
    os.chdir(os.fsdecode(git("rev-parse", "--show-toplevel")).strip())
    common = Path(os.fsdecode(git("rev-parse", "--git-common-dir")).strip()).resolve()
    try:
        check(args.ruff or common / "catalyst-checks" / "venv" / "bin" / "ruff")
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"fast checks refused the commit: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
