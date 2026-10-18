"""The release gate (bead catalyst-v2-2xy): a release cannot tag, push or publish a commit unless every
required CI check succeeded on it. The gate script runs here as the release runner runs it (a child
process), fed recorded check runs instead of the GitHub API; the workflow's shape is checked as text.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "scripts/require_green_ci.py"
RELEASE = ROOT / ".github/workflows/release.yml"
CI = ROOT / ".github/workflows/ci.yml"
SHA = "a" * 40
RUNTIME = "Runtime checks (Python 3.14.8, PostgreSQL 16.15)"
DOCS = "Markdown lint and doc index check"


def run(name, status="completed", conclusion="success", completed_at="2026-10-11T00:00:00Z"):
    return {"name": name, "status": status, "conclusion": conclusion,
            "completed_at": completed_at if status == "completed" else None}


def gate(tmp_path, runs, sha=SHA):
    data = tmp_path / "check-runs.json"
    data.write_text(json.dumps({"check_runs": runs}))
    return subprocess.run([sys.executable, str(GATE), sha], capture_output=True, text=True, timeout=30,
                          env={"CHECK_RUNS_JSON": str(data), "PATH": "/usr/bin:/bin"})


def test_a_commit_whose_required_checks_all_succeeded_may_be_released(tmp_path):
    result = gate(tmp_path, [run(RUNTIME), run(DOCS), run("CodeRabbit", conclusion="neutral")])
    assert result.returncode == 0, result.stdout
    assert "all 2 required checks succeeded" in result.stdout


@pytest.mark.parametrize(("runs", "reason"), [
    ([run(RUNTIME, conclusion="failure"), run(DOCS)], f"'{RUNTIME}' is completed/failure"),
    ([run(RUNTIME, conclusion="cancelled"), run(DOCS)], "is completed/cancelled"),
    ([run(RUNTIME, conclusion="skipped"), run(DOCS)], "is completed/skipped"),
    ([run(RUNTIME, conclusion="timed_out"), run(DOCS)], "is completed/timed_out"),
    ([run(RUNTIME, status="in_progress", conclusion=None), run(DOCS)], "is in_progress/None"),
    ([run(DOCS)], f"'{RUNTIME}' did not run"),
    ([], "did not run"),
    # A re-run decides: an earlier pass does not outweigh a later failure, nor a run still going.
    ([run(RUNTIME, completed_at="2026-10-11T00:00:00Z"), run(RUNTIME, conclusion="failure", completed_at="2026-10-11T01:00:00Z"),
      run(DOCS)], "is completed/failure"),
    ([run(RUNTIME), run(RUNTIME, status="in_progress", conclusion=None), run(DOCS)], "is in_progress/None"),
], ids=["failed", "cancelled", "skipped", "timed-out", "running", "missing", "no-checks", "rerun-failed", "rerun-running"])
def test_a_commit_without_every_required_check_green_is_refused(tmp_path, runs, reason):
    result = gate(tmp_path, runs)
    assert result.returncode == 1, result.stdout
    assert reason in result.stdout
    assert "release refused" in result.stdout


def test_a_later_successful_rerun_releases(tmp_path):
    runs = [run(RUNTIME, conclusion="failure", completed_at="2026-10-11T00:00:00Z"),
            run(RUNTIME, completed_at="2026-10-11T01:00:00Z"), run(DOCS)]
    assert gate(tmp_path, runs).returncode == 0


@pytest.mark.parametrize("sha", ["", "main", "abc123", "A" * 40])
def test_only_a_full_commit_sha_is_accepted(tmp_path, sha):
    assert gate(tmp_path, [run(RUNTIME), run(DOCS)], sha=sha).returncode == 2


def test_the_gate_requires_exactly_the_ci_job_names():
    import importlib.util

    spec = importlib.util.spec_from_file_location("require_green_ci", GATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    jobs = re.findall(r"^  [a-z_]+:\n    name: (.+)$", CI.read_text(), flags=re.M)
    assert sorted(module.REQUIRED) == sorted(jobs) == sorted([RUNTIME, DOCS])


def release_steps():
    return re.findall(r"^      - name: (.+)$", RELEASE.read_text(), flags=re.M)


def test_the_release_workflow_runs_both_gates_before_anything_is_published():
    text = RELEASE.read_text()
    steps = release_steps()
    publish = steps.index("Create GitHub Release")
    for gate_step in ("Check the version, changelog and merged commit", "Require green CI on the release commit"):
        assert steps.index(gate_step) < publish, gate_step
        body = text.split(f"- name: {gate_step}", 1)[1].split("\n      - name: ", 1)[0]
        assert "continue-on-error" not in body and "|| true" not in body  # a failed gate stops the job
    assert 'python3 scripts/require_green_ci.py "${{ github.sha }}"' in text
    assert 'python3 scripts/release_check.py "${{ inputs.version }}" "${{ github.sha }}"' in text
    assert re.search(r"^  checks: read\b", text, flags=re.M)  # the gate can read check runs


def test_the_release_workflow_writes_nothing_to_the_repository_history():
    """Bead catalyst-v2-oyu: no commit, no local tag, no push; GitHub creates the tag on the tested commit."""
    text = RELEASE.read_text()
    for forbidden in ("git commit", "git push", "git tag", "git add", "issues: write", "discussions: write"):
        assert forbidden not in text, forbidden
    assert '--target "${{ github.sha }}"' in text
    assert "persist-credentials: false" in text
    dry = re.search(r"dry_run:\n(?:        .+\n)+", text)[0]
    assert "default: true" in dry  # a run publishes only when asked to
    for use in re.findall(r"uses: (\S+)", text):
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", use), use  # actions pinned to a commit


def test_no_test_command_in_the_release_workflow_can_swallow_a_failure():
    text = RELEASE.read_text()
    assert not re.search(r"(pytest|make test|npm test|cargo test|go test)[^\n]*\|\| *true", text)
    assert not re.search(r"\b(pytest|make test|npm test|cargo test|go test)\b", text)  # CI owns the tests


def load(name):
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def release_tree(tmp_path, version="0.4.0", changelog="## [v0.4.0] - 2026-10-18\n\n- feat: x\n"):
    (tmp_path / "version.txt").write_text(version + "\n")
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{version}"\n')
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n" + changelog)
    return tmp_path


def fake_git(monkeypatch, module, *, head=SHA, on_main=True, tagged=False):
    class Result:
        def __init__(self, code=0, out=""):
            self.returncode, self.stdout = code, out

    def git(*args):
        if args[:1] == ("rev-parse",) and args[1] == "HEAD":
            return Result(0, head + "\n")
        if args[:2] == ("merge-base", "--is-ancestor"):
            return Result(0 if on_main else 1)
        if args[:1] == ("rev-parse",):
            return Result(0 if tagged else 1)
        raise AssertionError(args)
    monkeypatch.setattr(module, "git", git)


def test_a_merged_tested_commit_with_its_version_and_changelog_may_be_released(tmp_path, monkeypatch):
    check = load("release_check")
    fake_git(monkeypatch, check)
    assert check.problems("v0.4.0", SHA, release_tree(tmp_path)) == []


@pytest.mark.parametrize(("kwargs", "tree", "reason"), [
    ({}, {"version": "0.3.9"}, "version.txt says '0.3.9'"),
    ({}, {"changelog": "## [v0.3.9] - 2026-10-01\n"}, "no '## [v0.4.0]' entry"),
    ({"on_main": False}, {}, "is not on origin/main"),
    ({"tagged": True}, {}, "already exists"),
    ({"head": "b" * 40}, {}, "the checkout is not"),
], ids=["version-mismatch", "no-changelog-entry", "not-merged", "already-tagged", "other-checkout"])
def test_a_release_that_would_need_a_new_commit_or_an_unmerged_commit_is_refused(tmp_path, monkeypatch, kwargs, tree, reason):
    check = load("release_check")
    fake_git(monkeypatch, check, **kwargs)
    found = check.problems("v0.4.0", SHA, release_tree(tmp_path, **tree))
    assert any(reason in p for p in found), found


@pytest.mark.parametrize("args", [["v0.4"], ["0.4.0", SHA], ["v0.4.0", "main"]])
def test_the_release_check_takes_only_a_full_version_and_sha(args):
    assert load("release_check").main(["release_check.py", *args]) == 2


def test_prepare_release_writes_the_change_for_a_pull_request_and_nothing_else(tmp_path, monkeypatch):
    prepare = load("prepare_release")
    release_tree(tmp_path, version="0.3.9", changelog="## [v0.3.9] - 2026-10-01\n\n- old\n")
    calls = []

    class Result:
        stdout = "- feat: new thing (abc1234)"

    def run(args, **kwargs):
        calls.append(args)
        return Result()
    monkeypatch.setattr(prepare.subprocess, "run", run)
    monkeypatch.chdir(tmp_path)
    assert prepare.main(["prepare_release.py", "v0.4.0"]) == 0
    assert (tmp_path / "version.txt").read_text() == "0.4.0\n"
    assert 'version = "0.4.0"' in (tmp_path / "pyproject.toml").read_text()
    changelog = (tmp_path / "CHANGELOG.md").read_text()
    assert changelog.index("## [v0.4.0]") < changelog.index("## [v0.3.9]") and "- feat: new thing" in changelog
    assert all(c[:2] in (["git", "describe"], ["git", "log"]) for c in calls)  # reads history; never commits or pushes
