"""Host-side integration checks for Git index handling and Beads hook chaining (no database)."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

from scripts.install_fast_checks import install_chain

CHECKER = Path(__file__).with_name("check_staged.py")
RUFF = shutil.which("ruff")


class StagedChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "core.hooksPath", str(self.root / ".git/hooks"))
        self.git("config", "user.name", "Synthetic Checker")
        self.git("config", "user.email", "checker@example.test")
        version = subprocess.check_output([RUFF, "--version"], text=True).split()[1]
        self.write("requirements/lint.txt", f"ruff=={version}\n")
        self.write("pyproject.toml", '[tool.ruff]\ntarget-version = "py314"\n')
        self.git("add", ".")
        self.git("commit", "-qm", "Synthetic baseline")

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True, text=True
        )

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def check(self):
        return subprocess.run(
            [sys.executable, str(CHECKER), "--ruff", RUFF],
            cwd=self.root,
            capture_output=True,
            text=True,
        )

    def test_staged_content_and_literal_filenames_are_checked_instead_of_dirty_working_files(
        self,
    ):
        name = "space and [brackets].py"
        self.write(name, "answer = 1\n")
        self.git("add", "--", name)
        self.write(name, "answer = undefined_name\n")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 staged Python file(s) passed", result.stdout)

    def test_invalid_staged_code_is_refused_even_when_the_working_file_is_fixed(self):
        self.write("sample.py", "answer = undefined_name\n")
        self.git("add", "sample.py")
        self.write("sample.py", "answer = 1\n")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("F821", result.stdout + result.stderr)

    def test_formatting_and_whitespace_fail_before_commit(self):
        self.write("sample.py", "answer=1\n")
        self.git("add", "sample.py")
        self.assertNotEqual(self.check().returncode, 0)
        self.git("reset", "-q", "--", "sample.py")
        self.write("notes.md", "trailing whitespace  \n")
        self.git("add", "notes.md")
        self.assertNotEqual(self.check().returncode, 0)

    def test_deleted_python_and_prose_do_not_need_python_tools(self):
        self.write("sample.py", "answer = 1\n")
        self.git("add", "sample.py")
        self.git("commit", "-qm", "Synthetic file")
        self.git("rm", "-q", "sample.py")
        self.write("notes.md", "A synthetic note.\n")
        self.git("add", "notes.md")
        result = subprocess.run(
            [sys.executable, str(CHECKER), "--ruff", "/missing/ruff"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_version_drift_and_python_symlinks_are_refused(self):
        self.write("sample.py", "answer = 1\n")
        self.write("requirements/lint.txt", "ruff==0.0.0\n")
        self.git("add", ".")
        self.assertNotEqual(self.check().returncode, 0)
        self.git("reset", "-q", "--", "requirements/lint.txt")
        os.symlink("sample.py", self.root / "link.py")
        self.git("add", "link.py")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-regular staged Python file", result.stderr)

    def test_hook_installation_preserves_beads_and_runs_prior_hook_first(self):
        hooks = self.root / ".git/hooks"
        shim = hooks / "pre-commit"
        shim.write_text(
            '#!/bin/sh\n# bd hooks run pre-commit\nexec "$(dirname "$0")/pre-commit.old"\n'
        )
        shim.chmod(0o755)
        original_shim = shim.read_bytes()
        log = self.root / "order"
        prior = hooks / "pre-commit.old"
        prior.write_text(f"#!/bin/sh\nprintf prior > {shlex.quote(str(log))}\n")
        prior.chmod(0o755)
        original_prior = prior.read_bytes()
        checker = self.write(
            "probe.py",
            f"from pathlib import Path\np=Path({str(log)!r})\np.write_text(p.read_text()+'-checker')\n",
        )
        install_chain(hooks, checker, Path(sys.executable))
        install_chain(hooks, checker, Path(sys.executable))
        result = subprocess.run([str(shim)], cwd=self.root)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(log.read_text(), "prior-checker")
        self.assertEqual(shim.read_bytes(), original_shim)
        self.assertEqual(
            (hooks / "pre-commit.before-catalyst").read_bytes(), original_prior
        )
        # A previous hook's refusal propagates and prevents the checker.
        (hooks / "pre-commit.before-catalyst").write_text("#!/bin/sh\nexit 9\n")
        self.assertEqual(subprocess.run([str(shim)], cwd=self.root).returncode, 9)


if __name__ == "__main__":
    unittest.main()
