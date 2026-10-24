"""The targeted lane's selection map (bead catalyst-v2-9kg.45; 009 section 5.3). The map is a hint for iteration and
never a gate, but 009's lane table forbids selecting a subset until the map is itself tested: these tests check that
every test module is reachable through it, that a package change selects every module importing that package (a
regex reading of the sources, independent of the script's `ast` walk), that the fixture chains are followed, and that
anything the map cannot place runs the whole suite. They read the files only; no database is touched.
"""

import importlib.util
import re
import subprocess
import sys

from tests.support import ROOT

SCRIPT = ROOT / "scripts/select_tests.py"
spec = importlib.util.spec_from_file_location("select_tests", SCRIPT)
select_tests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(select_tests)

# Test modules that no package change selects: each tests files outside the application packages (config/, the
# migrations, the image, the workflows, deployment, scripts, the test network guard), and a change to any of those runs
# the whole suite.
# A new test module that reaches no package must be added here on purpose, after checking it does not exercise package
# code through a URL or a command name alone (which the import map cannot see).
# Since PR #88, tests/support.py's resume_pauses imports applications and workflow, so every module that imports
# tests.support reaches those two packages; the map over-selects them for a package change, the safe direction.
REACHES_NO_PACKAGE = {"test_database", "test_health", "test_network_guard", "test_release_gate"}


def test_every_test_module_is_covered_by_the_map():
    modules = select_tests.test_modules()
    on_disk = sorted(path.stem for path in (ROOT / "tests").glob("test_*.py"))
    assert modules == on_disk and len(modules) > 40
    rows = select_tests.table()
    for module in modules:
        assert module in rows[f"tests/{module}.py"], module
    assert set().union(*rows.values()) == set(modules)
    by_package = set().union(*(rows[f"{package}/"] for package in select_tests.PACKAGES))
    assert set(modules) - by_package == REACHES_NO_PACKAGE


def test_a_package_change_selects_every_module_that_imports_the_package():
    rows = select_tests.table()
    for package in select_tests.PACKAGES:
        direct = re.compile(rf"^\s*(?:from|import) {package}(?:[.\s]|$)", flags=re.M)
        importers = {path.stem for path in (ROOT / "tests").glob("test_*.py") if direct.search(path.read_text())}
        assert importers, package
        assert importers <= set(rows[f"{package}/"]), (package, importers - set(rows[f"{package}/"]))


def test_the_fixture_chains_are_followed():
    rows = select_tests.table()
    chain = re.compile(r"^from tests\.(test_\w+) import", flags=re.M)
    followed = 0
    for path in (ROOT / "tests").glob("test_*.py"):
        for source in chain.findall(path.read_text()):
            # A module borrowing another's fixtures runs whenever that other module or anything it reaches changes.
            assert path.stem in rows[f"tests/{source}.py"], (path.stem, source)
            for package in select_tests.PACKAGES:
                if source in rows[f"{package}/"]:
                    assert path.stem in rows[f"{package}/"], (path.stem, source, package)
            followed += 1
    assert followed > 10


def test_a_small_change_selects_its_modules_and_nothing_else():
    args, reason = select_tests.select(["provisioning/handlers.py", "./provisioning/templates/x.html"])
    assert args == [f"tests/{m}.py" for m in select_tests.table()["provisioning/"]]
    assert "tests/test_provisioning.py" in args and "tests/test_image.py" not in args
    assert reason.endswith("test modules selected")
    assert select_tests.select(["tests/test_image.py"])[0] == ["tests/test_image.py"]


def test_anything_the_map_cannot_place_runs_the_whole_suite():
    for paths in ([], ["Dockerfile"], ["config/settings.py"], ["applications/migrations/0001_initial.py"],
                  ["tests/conftest.py"], ["tests/worker_child.py"], ["requirements/base.txt"], ["compose.yaml"],
                  [".github/workflows/ci.yml"], ["scripts/test.sh"], ["deploy/staging/compose.yaml"],
                  ["provisioning/handlers.py", "README.md"]):
        args, reason = select_tests.select(paths)
        assert args == ["tests"], (paths, args)
        assert "whole suite" in reason


def test_a_selection_above_half_the_modules_runs_the_whole_suite():
    rows = select_tests.table()
    total = len(select_tests.test_modules())
    wide = max(select_tests.PACKAGES, key=lambda package: len(rows[f"{package}/"]))
    assert len(rows[f"{wide}/"]) * 2 > total
    args, reason = select_tests.select([f"{wide}/models.py"])
    assert args == ["tests"] and "more than half" in reason


def test_the_command_prints_pytest_arguments_and_its_reason_apart():
    def run(*argv):
        return subprocess.run([sys.executable, str(SCRIPT), *argv], capture_output=True, text=True, timeout=30)

    small = run("accounts/models.py")
    assert small.returncode == 0
    assert small.stdout.split() == [f"tests/{m}.py" for m in select_tests.table()["accounts/"]]
    assert small.stderr.startswith("select_tests: ")
    assert run("Dockerfile").stdout.split() == ["tests"]
    table = run("--table")
    assert table.returncode == 0 and "provisioning/\t" in table.stdout
    assert run("--bogus").returncode == 2
