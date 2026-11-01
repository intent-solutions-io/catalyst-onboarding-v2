"""Partition a full pytest collection and fail closed when combining its CI evidence (9kg.93).

No dependency beyond the standard library: the aggregate runner does not boot Django or PostgreSQL.
Each runner collects the same full manifest, then executes every fourth node in sorted order. This
spreads slow modules and parametrized cases across isolated databases without a maintained test list.
"""

import argparse
import json
from pathlib import Path

from tests import acceptance


def partition(manifest, index, count):
    if not 0 <= index < count or count < 1:
        raise ValueError("invalid shard index/count")
    if not manifest or manifest != sorted(set(manifest)):
        raise ValueError("collection must be nonempty, sorted and unique")
    return manifest[index::count]


def merge(records, count, commit, run_id, attempt):
    """Require one complete successful record per partition of one identical collection and CI attempt."""
    if count < 1 or len(records) != count:
        raise ValueError("missing or extra shard evidence")
    if sorted(r["index"] for r in records) != list(range(count)):
        raise ValueError("missing or duplicate shard index")
    manifest = records[0]["manifest"]
    outcomes = {}
    for record in records:
        for key, expected in {"schema": 1, "count": count, "commit": commit, "run_id": run_id,
                              "attempt": attempt, "manifest": manifest, "exit_status": 0, "skipped": []}.items():
            if record[key] != expected:
                raise ValueError(f"shard {record['index']}: mismatched or unsuccessful {key}")
        selected = partition(manifest, record["index"], count)
        if record["selected"] != selected or set(record["reports"]) != set(selected):
            raise ValueError("missing, extra or wrongly assigned test results")
        for nodeid, reports in record["reports"].items():
            # Requiring all three successful phases rejects missing calls, setup/teardown failures,
            # skips, xfail/xpass and duplicate executions, including tests outside the acceptance map.
            if reports != [["setup", "passed", False], ["call", "passed", False], ["teardown", "passed", False]]:
                raise ValueError(f"incomplete or unsuccessful test: {nodeid}")
            for name in {acceptance.key(nodeid), acceptance.instance_key(nodeid)}:
                outcomes.setdefault(name, set()).add("passed")
    statuses = {}
    for case, names in acceptance.groups().items():
        if not names or any(outcomes.get(name) != {"passed"} for name in names):
            raise ValueError(f"acceptance case incomplete: {case}")
        statuses[case] = "PASS"
    problems = acceptance.check_register()
    if problems:
        raise ValueError("invalid evidence register: " + "; ".join(problems))
    return statuses, len(manifest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--output", type=Path, default=Path("register.json"))
    args = parser.parse_args(argv)
    # A rejected aggregate must not leave an earlier green register behind.
    args.output.unlink(missing_ok=True)
    try:
        records = [json.loads(p.read_text()) for p in sorted(args.directory.glob("*/shard.json"))]
        statuses, total = merge(records, args.count, args.commit, args.run_id, args.attempt)
        acceptance.write_register(statuses, str(args.output), args.commit, 0)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"FAILED GATE: {exc}")
        return 1
    print(f"PASS: all {total} tests executed exactly once across {args.count} shards; "
          f"all {len(statuses)} acceptance groups passed; wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
