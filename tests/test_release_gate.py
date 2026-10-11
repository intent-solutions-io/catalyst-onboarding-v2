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


def test_the_release_workflow_runs_the_gate_before_anything_is_tagged_pushed_or_published():
    text = RELEASE.read_text()
    steps = release_steps()
    gate_at = steps.index("Require green CI on the release commit")
    for later in ("Determine previous tag", "Commit version bump", "Create tag and push", "Create GitHub Release"):
        assert steps.index(later) > gate_at, later
    assert 'python3 scripts/require_green_ci.py "${{ github.sha }}"' in text
    assert re.search(r"^  checks: read\b", text, flags=re.M)  # the gate can read check runs
    gate_step = text.split("- name: Require green CI on the release commit", 1)[1].split("\n      - name: ", 1)[0]
    assert "continue-on-error" not in gate_step and "|| true" not in gate_step  # a failed gate stops the job


def test_no_test_command_in_the_release_workflow_can_swallow_a_failure():
    text = RELEASE.read_text()
    assert not re.search(r"(pytest|make test|npm test|cargo test|go test)[^\n]*\|\| *true", text)
    assert not re.search(r"\b(pytest|make test|npm test|cargo test|go test)\b", text)  # CI owns the tests
