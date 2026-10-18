"""Release gate (bead catalyst-v2-2xy): refuse to release a commit unless every required CI check
succeeded on that exact commit.

The release workflow runs this before it tags, pushes or publishes. A non-zero exit stops the job
there. Tests are not re-run in the release job: the suite needs the digest-pinned Python and
PostgreSQL containers, the three database roles and the hash-locked dependencies that ci.yml sets up,
so CI is the one source of test truth.

The gate fails closed. A required check that is missing, still running, or ended in anything but
success (failure, cancelled, skipped, timed out) refuses the release. When a check ran more than once
on the commit (a re-run), the latest run decides, and a run still in progress counts as not green.

Usage: python3 scripts/require_green_ci.py <commit-sha>
  Reads the commit's check runs through `gh api` (GH_TOKEN, GITHUB_REPOSITORY), or from the JSON file
  named by CHECK_RUNS_JSON (tests). Standard library only.
"""

import json
import os
import re
import subprocess
import sys

# The job names in .github/workflows/ci.yml; tests/test_release_gate.py keeps the two in step.
REQUIRED = (
    "Runtime checks (Python 3.14.8, PostgreSQL 16.15)",
    "Markdown lint and doc index check",
)


def check_runs(sha: str) -> list[dict]:
    path = os.environ.get("CHECK_RUNS_JSON")
    if path:
        with open(path) as f:
            return json.load(f)["check_runs"]
    repo = os.environ["GITHUB_REPOSITORY"]
    out = subprocess.run(
        ["gh", "api", "--paginate", f"repos/{repo}/commits/{sha}/check-runs?per_page=100", "--jq", ".check_runs[]"],
        check=True, capture_output=True, text=True,
    ).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def problems(runs: list[dict], sha: str) -> list[str]:
    found = []
    for name in REQUIRED:
        # Only GitHub Actions' own runs count: a same-named check posted by another app proves nothing.
        matching = [r for r in runs if r.get("name") == name and (r.get("app") or {}).get("slug") == "github-actions"]
        if not matching:
            found.append(f"required check '{name}' did not run on {sha}")
            continue
        # Latest decides; a run without completed_at (still running) sorts last, so it decides.
        latest = max(matching, key=lambda r: r.get("completed_at") or "9999")
        status, conclusion = latest.get("status"), latest.get("conclusion")
        if status != "completed" or conclusion != "success":
            found.append(f"required check '{name}' is {status}/{conclusion} on {sha}")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not re.fullmatch(r"[0-9a-f]{40}", argv[1]):
        print("::error::release gate: usage: require_green_ci.py <full 40-character commit SHA>")
        return 2
    sha = argv[1]
    found = problems(check_runs(sha), sha)
    for problem in found:
        print(f"::error::release gate: {problem}")
    if found:
        print("::error::release refused: every required CI check must succeed on the release commit first")
        return 1
    print(f"release gate: all {len(REQUIRED)} required checks succeeded on {sha}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
