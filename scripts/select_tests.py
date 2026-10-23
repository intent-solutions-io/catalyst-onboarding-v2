#!/usr/bin/env python3
"""Map changed paths to the runtime test modules worth running first (bead catalyst-v2-9kg.45; 009 section 5.3).

This is the targeted iteration lane's selection hint, never a gate: the required check and the release-candidate gate
stay the complete suite. Usage, from the repository root:

    git diff --name-only origin/main... | xargs python3 scripts/select_tests.py
    PYTEST_ARGS="$(git diff --name-only origin/main... | xargs python3 scripts/select_tests.py)" scripts/test.sh
    python3 scripts/select_tests.py --table

It prints pytest arguments: the selected test files, or `tests` (the whole suite) when the change cannot be mapped.
The reason goes to standard error. Standard library only, so it runs on the host as well as in the test image.

The map is derived from the code at run time, so it cannot drift from it. Each test module's first-party imports are
read with `ast` (module level and inside functions), followed through the test modules and helpers it imports (the
fixture chains), and recorded as the set of application packages it reaches. A changed path then selects:

- `<package>/...` (one of PACKAGES), outside `migrations/`: every test module that reaches that package;
- `tests/<module>.py` other than the FULL_RUN test files: that module, if it is a test module, plus every test module
  that imports it directly or through another test module or helper;
- anything else, or a file no test module imports (the worker child scripts run as processes), including `config/`, migrations, `tests/conftest.py`, requirements, the Dockerfile, compose files,
  `deploy/`, `scripts/` and `.github/`: the whole suite.

The whole suite is also chosen when nothing is selected, or when the selection exceeds half of the test modules, where
a targeted run saves little. Under-selection is possible (a view reached only through a URL, a management command
called by name, a template), which is why a selected run is reported and never gates.
"""

import ast
import functools
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
# The application packages a change can be mapped from. `config` is not one: its settings, URLs and guards load in
# every test, so a change there runs the whole suite.
PACKAGES = ("accounts", "agreements", "applications", "assessments", "correspondence", "provisioning", "workflow")
# Test-tree files every test depends on, or that run as child processes rather than being imported: changing one runs
# the whole suite.
FULL_RUN = frozenset({"tests/__init__.py", "tests/conftest.py", "tests/settings_sqlite.py"})
FULL = ["tests"]


def test_modules():
    return sorted(path.stem for path in TESTS.glob("test_*.py"))


def _first_party_imports(path):
    """The first-party names a file imports: ("pkg", name) for application packages, ("tests", module) for test files."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            # `from tests import support` names the module tests.support.
            names = [f"{node.module}.{alias.name}" if node.module in ("tests", *PACKAGES) else node.module
                     for alias in node.names]
        else:
            continue
        for name in names:
            parts = name.split(".")
            if parts[0] == "tests" and len(parts) > 1 and (TESTS / f"{parts[1]}.py").is_file():
                found.add(("tests", parts[1]))
            elif parts[0] in PACKAGES or parts[0] == "config":
                found.add(("pkg", parts[0]))
    return found


def import_graph():
    """For every file under tests/: the test-tree modules it imports and the packages it imports directly."""
    graph = {}
    for path in sorted(TESTS.glob("*.py")):
        imports = _first_party_imports(path)
        graph[path.stem] = ({name for kind, name in imports if kind == "tests" and name != path.stem},
                            {name for kind, name in imports if kind == "pkg"})
    return graph


def reach(graph):
    """For every file under tests/: every test-tree module and package it reaches, transitively."""
    out = {}
    for start in graph:
        seen, packages, todo = set(), set(), [start]
        while todo:
            module = todo.pop()
            if module in seen:
                continue
            seen.add(module)
            modules, pkgs = graph.get(module, (set(), set()))
            packages |= pkgs
            todo.extend(modules)
        out[start] = (seen - {start}, packages)
    return out


@functools.cache
def _rows():
    """The map as it stands: each package and each test-tree file, with the test modules a change to it selects."""
    reached = reach(import_graph())
    tests = test_modules()
    rows = {f"{package}/": sorted(m for m in tests if package in reached[m][1]) for package in PACKAGES}
    for stem in sorted(reached):
        key = f"tests/{stem}.py"
        if key in FULL_RUN:
            continue
        rows[key] = sorted(m for m in tests if m == stem or stem in reached[m][0])
    return rows


def table():
    """The map as it stands (read once per process): changed path or package prefix -> selected test modules."""
    return {key: list(modules) for key, modules in _rows().items()}


def select(paths):
    """Return (pytest arguments, reason) for a list of changed repository-relative paths."""
    if not paths:
        return FULL, "no changed paths given: the whole suite"
    rows = table()
    chosen = set()
    for raw in paths:
        path = raw.strip().removeprefix("./")
        top = path.split("/", 1)[0]
        if top in PACKAGES and "/migrations/" not in f"/{path}":
            row = rows[f"{top}/"]
        elif path in rows:
            row = rows[path]
        else:
            return FULL, f"{path} is not mapped: the whole suite"
        if not row:
            # A file nothing imports (a child-process script such as tests/worker_child.py) is still exercised.
            return FULL, f"no test module imports {path}: the whole suite"
        chosen.update(row)
    total = len(test_modules())
    if len(chosen) * 2 > total:
        return FULL, f"{len(chosen)} of {total} test modules selected, more than half: the whole suite"
    return [f"tests/{m}.py" for m in sorted(chosen)], f"{len(chosen)} of {total} test modules selected"


def main(argv):
    if argv == ["--table"]:
        total = len(test_modules())
        for key, modules in table().items():
            print(f"{key}\t{len(modules)}/{total}\t{' '.join(modules)}")
        return 0
    if any(arg.startswith("-") for arg in argv):
        print("usage: select_tests.py [--table | CHANGED_PATH ...]", file=sys.stderr)
        return 2
    args, reason = select(argv)
    print(f"select_tests: {reason}", file=sys.stderr)
    print(" ".join(args))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
