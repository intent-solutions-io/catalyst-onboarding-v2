#!/usr/bin/env bash
# The phone-width browser check (bead catalyst-v2-9kg.68; 009 section 5.3): tests/browser_phone_check.py against a
# real headless Chromium, in the digest-pinned containers of compose.yaml plus the browser overlay compose.browser.yaml.
# Not part of the full suite and never a required check; a pre-release step, also dispatchable in CI
# (.github/workflows/browser.yml runs this same script).
#
# Isolation and cleanup are scripts/test.sh's: a per-run Compose project name, cleanup that names only that project,
# nothing host-wide pruned, and the exit status is the check's. Two runs of the test container share one database
# container:
#   1. compose.yaml's own test command with `pytest --version`: it installs dev.txt and provisions the database roles
#      exactly as scripts/test.sh does, and runs no test. The administrator login stays where 6hl.10 put it, on
#      compose.yaml's provisioning command, and is never repeated here.
#   2. dev.txt plus browser.txt, then the one module, with the browser service up. Arguments are passed to pytest
#      (for example -k phone); a test stuck for five minutes has every thread's stack printed.
set -uo pipefail
cd "$(dirname "$0")/.."
export CATALYST_UID="$(id -u)" CATALYST_GID="$(id -g)"
PROJECT="${CATALYST_TEST_PROJECT:-catalyst-v2-browser-$(date +%s)-$$-$RANDOM}"
COMPOSE=(docker compose --project-name "$PROJECT" --file compose.yaml --file compose.browser.yaml)
if [ -n "$("${COMPOSE[@]}" ps --all --quiet 2>/dev/null)" ]; then
  echo "browser_check.sh: compose project $PROJECT already has containers; refusing to run or clean it up" >&2
  exit 2
fi

cleanup() {
  local err
  if ! err="$("${COMPOSE[@]}" down --volumes --remove-orphans 2>&1 >/dev/null)"; then
    echo "browser_check.sh: cleanup of compose project $PROJECT failed: $err" >&2
    echo "browser_check.sh: inspect with: docker compose -p $PROJECT ps -a" >&2
  fi
}
trap cleanup EXIT

echo "browser_check.sh: compose project $PROJECT" >&2
if ! PYTEST_ARGS="--version" "${COMPOSE[@]}" run --rm test; then
  echo "browser_check.sh: installing or provisioning failed; the check did not run" >&2
  exit 1
fi
# Arguments reach pytest as positional parameters of the inner shell, never spliced into its script.
"${COMPOSE[@]}" run --rm test sh -c 'python -m venv /tmp/venv \
  && /tmp/venv/bin/pip install --quiet --disable-pip-version-check --require-hashes --no-deps \
       -r requirements/dev.txt -r requirements/browser.txt \
  && exec /tmp/venv/bin/python -m pytest -v -rP -o faulthandler_timeout=300 tests/browser_phone_check.py "$@"' sh "$@"
status=$?
exit "$status"
