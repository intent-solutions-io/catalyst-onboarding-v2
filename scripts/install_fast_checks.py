#!/usr/bin/env python3
"""Install the offline staged-file checker through Beads' supported pre-commit.old chain."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import venv

MARKER = "# Catalyst staged checks (9kg.95)"


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def install_chain(hooks, checker, python):
    hook = hooks / "pre-commit"
    if not hook.is_file() or "bd hooks run pre-commit" not in hook.read_text():
        raise RuntimeError(
            "expected the existing Beads pre-commit shim; install it with bd hooks install first"
        )
    chained = hooks / "pre-commit.old"
    prior = hooks / "pre-commit.before-catalyst"
    if (chained.exists() or chained.is_symlink()) and MARKER not in chained.read_text():
        if (
            prior.exists()
            or prior.is_symlink()
            or "bd hooks run" in chained.read_text()
        ):
            raise RuntimeError(
                "existing chained hook needs review; no hook was replaced"
            )
        chained.rename(prior)
    lines = ["#!/bin/sh", MARKER]
    if prior.exists():
        lines.append(
            f'[ ! -x {shlex.quote(str(prior))} ] || {shlex.quote(str(prior))} "$@" || exit $?'
        )
    lines.append(f"exec {shlex.quote(str(python))} {shlex.quote(str(checker))}")
    temporary = chained.with_suffix(".installing")
    temporary.write_text("\n".join(lines) + "\n")
    temporary.chmod(0o755)
    temporary.replace(chained)


def main():
    root = Path(git("rev-parse", "--show-toplevel"))
    os.chdir(root)
    common = Path(git("rev-parse", "--git-common-dir")).resolve()
    hooks = Path(git("rev-parse", "--git-path", "hooks")).resolve()
    tools = common / "catalyst-checks"
    tools.mkdir(parents=True, exist_ok=True)
    venv.EnvBuilder(with_pip=True).create(tools / "venv")
    python = tools / "venv" / "bin" / "python"
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--require-hashes",
            "--no-deps",
            "-r",
            str(root / "requirements/lint.txt"),
        ],
        check=True,
    )
    checker = tools / "check_staged.py"
    shutil.copyfile(root / "scripts/check_staged.py", checker)
    install_chain(hooks, checker, python)
    print(
        f"Installed staged-file checks at {hooks / 'pre-commit.old'}; Beads shim preserved."
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"fast-check installation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
