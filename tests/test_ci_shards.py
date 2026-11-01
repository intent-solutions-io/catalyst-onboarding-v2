"""The sharded merge gate must prove complete execution, including tests outside the acceptance map."""

import copy
import json
import subprocess
import sys

import pytest

from scripts import ci_shards
from tests import acceptance
from tests.support import ROOT, child_env
from tests.test_acceptance import GATE_PROBE_CONFTEST

SHA = "a" * 40
MANIFEST = [
    "test_probe.py::test_a[0]",
    "test_probe.py::test_a[1]",
    "test_probe.py::test_unmapped",
]


@pytest.fixture
def small_gate(monkeypatch):
    for name in (
        "CASES",
        "SUPPORTING",
        "P2_CASES",
        "P3_CASES",
        "P3_SUPPORTING",
        "P4_CASES",
        "P4_SUPPORTING",
        "P5_CASES",
        "P5_SUPPORTING",
        "P6_CASES",
        "P6_SUPPORTING",
        "P6_LIVE_ONLY",
        "P6_EVIDENCE",
    ):
        monkeypatch.setattr(acceptance, name, {})
    monkeypatch.setattr(
        acceptance,
        "CASES",
        {"TEST-PROBE": ["test_probe::test_a", "test_probe::test_a[1]"]},
    )


def records():
    return [
        {
            "schema": 1,
            "index": index,
            "count": 2,
            "commit": SHA,
            "run_id": "123",
            "attempt": "1",
            "manifest": MANIFEST.copy(),
            "selected": MANIFEST[index::2],
            "exit_status": 0,
            "skipped": [],
            "reports": {
                node: [
                    [phase, "passed", False] for phase in ("setup", "call", "teardown")
                ]
                for node in MANIFEST[index::2]
            },
        }
        for index in range(2)
    ]


def combine(data):
    return ci_shards.merge(data, 2, SHA, "123", "1")


def test_the_union_covers_every_parametrized_instance_and_unmapped_test(small_gate):
    statuses, total = combine(records())
    assert statuses == {"TEST-PROBE": "PASS"} and total == 3
    data = records()
    del data[0]["reports"]["test_probe.py::test_unmapped"]
    with pytest.raises(ValueError, match="missing, extra"):
        combine(data)


@pytest.mark.parametrize(
    "change",
    [
        "missing-shard",
        "extra-shard",
        "duplicate-index",
        "wrong-count",
        "wrong-commit",
        "wrong-run",
        "wrong-attempt",
        "wrong-schema",
        "collection-drift",
        "duplicate-node",
        "empty-collection",
        "wrong-selection",
        "missing-result",
        "extra-result",
        "failed-exit",
        "collection-skip",
        "missing-call",
        "failed-setup",
        "failed-call",
        "failed-teardown",
        "skip",
        "xfail",
        "xpass",
        "duplicate-execution",
    ],
)
def test_incomplete_stale_duplicate_or_unsuccessful_evidence_is_refused(
    small_gate, change
):
    data = records()
    report = data[0]["reports"][MANIFEST[0]]
    if change == "missing-shard":
        data.pop()
    elif change == "extra-shard":
        data.append(copy.deepcopy(data[0]))
    elif change == "duplicate-index":
        data[1]["index"] = 0
    elif change == "wrong-count":
        data[0]["count"] = 3
    elif change == "wrong-commit":
        data[0]["commit"] = "b" * 40
    elif change == "wrong-run":
        data[0]["run_id"] = "124"
    elif change == "wrong-attempt":
        data[0]["attempt"] = "2"
    elif change == "wrong-schema":
        data[0]["schema"] = 2
    elif change == "collection-drift":
        data[0]["manifest"] = MANIFEST[:-1]
    elif change == "duplicate-node":
        for row in data:
            row["manifest"] = sorted([*MANIFEST, MANIFEST[0]])
    elif change == "empty-collection":
        for row in data:
            row["manifest"] = []
    elif change == "wrong-selection":
        data[0]["selected"] = MANIFEST
    elif change == "missing-result":
        del data[0]["reports"][MANIFEST[0]]
    elif change == "extra-result":
        data[0]["reports"]["unexpected"] = report
    elif change == "failed-exit":
        data[0]["exit_status"] = 1
    elif change == "collection-skip":
        data[0]["skipped"] = ["test_missing.py"]
    elif change == "missing-call":
        report.pop(1)
    elif change.startswith("failed-"):
        report[{"failed-setup": 0, "failed-call": 1, "failed-teardown": 2}[change]][
            1
        ] = "failed"
    elif change == "skip":
        report[1][1] = "skipped"
    elif change == "xfail":
        report[1][1:] = ["skipped", True]
    elif change == "xpass":
        report[1][2] = True
    elif change == "duplicate-execution":
        report.extend(copy.deepcopy(report))
    with pytest.raises(ValueError):
        combine(data)


def test_missing_acceptance_cases_and_invalid_registers_are_refused(
    small_gate, monkeypatch
):
    monkeypatch.setattr(
        acceptance, "CASES", {"TEST-MISSING": ["test_probe::test_not_collected"]}
    )
    with pytest.raises(ValueError, match="acceptance case incomplete"):
        combine(records())
    monkeypatch.setattr(acceptance, "CASES", {"TEST-PROBE": ["test_probe::test_a"]})
    monkeypatch.setattr(acceptance, "check_register", lambda: ["missing evidence"])
    with pytest.raises(ValueError, match="invalid evidence register"):
        combine(records())


def test_the_aggregate_writes_the_full_register_and_removes_stale_success_on_failure(
    small_gate, tmp_path
):
    for row in records():
        directory = tmp_path / f"shard-{row['index']}"
        directory.mkdir()
        (directory / "shard.json").write_text(json.dumps(row))
    output = tmp_path / "register.json"
    args = [
        str(tmp_path),
        "--count",
        "2",
        "--commit",
        SHA,
        "--run-id",
        "123",
        "--attempt",
        "1",
        "--output",
        str(output),
    ]
    assert ci_shards.main(args) == 0
    result = json.loads(output.read_text())
    assert result["commit"] == SHA and result["exit_status"] == 0
    assert result["gates"]["GATE-S1"]["numbered"]["PASS"] == 1
    (tmp_path / "shard-1" / "shard.json").unlink()
    assert ci_shards.main(args) == 1 and not output.exists()


def probe(tmp_path, *args):
    (tmp_path / "conftest.py").write_text(GATE_PROBE_CONFTEST % "'test_probe::test_a'")
    (tmp_path / "test_probe.py").write_text(
        "import pytest\n@pytest.mark.parametrize('value', range(8))\ndef test_a(value):\n    assert value >= 0\n"
    )
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.conftest",
            "-p",
            "no:cacheprovider",
            "-q",
            *args,
        ],
        cwd=tmp_path,
        env=child_env(
            PYTHONPATH=str(ROOT),
            CATALYST_RUN_COMMIT=SHA,
            GITHUB_RUN_ID="123",
            GITHUB_RUN_ATTEMPT="1",
            PYTEST_ADDOPTS=None,
            CATALYST_EVIDENCE_REGISTER=str(tmp_path / "register.json"),
        ),
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_real_pytest_shards_collect_the_same_manifest_and_merge_without_losing_instances(
    small_gate, tmp_path, monkeypatch
):
    data = []
    monkeypatch.setattr(acceptance, "CASES", {"TEST-PROBE": ["test_probe::test_a"]})
    for index in range(4):
        path = tmp_path / f"{index}.json"
        result = probe(tmp_path, f"--ci-shard={index}/4", f"--ci-shard-output={path}")
        assert result.returncode == 0, result.stdout + result.stderr
        record = json.loads(path.read_text())
        assert len(record["selected"]) == 2 and len(record["manifest"]) == 8
        assert not (
            tmp_path / "register.json"
        ).exists()  # a shard alone is never full-suite proof
        data.append(record)
    assert ci_shards.merge(data, 4, SHA, "123", "1") == ({"TEST-PROBE": "PASS"}, 8)


@pytest.mark.parametrize(
    "selection",
    [
        ["test_probe.py"],
        ["-k", "test_a"],
        ["-m", "not slow"],
        ["--deselect=test_probe.py::test_a[0]"],
        ["--ignore=other.py"],
        ["--collect-only"],
    ],
)
def test_sharding_refuses_selected_or_collection_only_runs(tmp_path, selection):
    path = tmp_path / "shard.json"
    result = probe(tmp_path, "--ci-shard=0/4", f"--ci-shard-output={path}", *selection)
    assert result.returncode != 0 and not path.exists(), result.stdout + result.stderr


def test_required_checks_preserve_parallel_fast_feedback_and_complete_evidence():
    text = (ROOT / ".github/workflows/ci.yml").read_text()
    shards = text.split("\n  shards:\n")[1].split("\n  runtime:\n")[0]
    runtime = text.split("\n  runtime:\n")[1].split("\n  docs:\n")[0]
    docs = text.split("\n  docs:\n")[1]
    assert "shard: [0, 1, 2, 3]" in shards and "fail-fast: false" in shards
    assert "if-no-files-found: error" in shards and "continue-on-error" not in shards
    assert "needs: shards" in runtime and "if: ${{ always() }}" in runtime
    assert 'test "$SHARDS_RESULT" = success' in runtime and "--count 4" in runtime
    assert "pattern: test-shard-*-${{ github.run_attempt }}" in runtime
    assert "needs:" not in docs and "Runtime checks succeeded" not in docs
