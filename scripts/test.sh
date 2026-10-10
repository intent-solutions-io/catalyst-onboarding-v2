#!/usr/bin/env bash
# Run the runtime test suite in the digest-pinned containers of compose.yaml, isolated per run.
#
# Each run gets its own Compose project name, and startup and cleanup both name that project and this
# compose file explicitly, so cleanup removes only this run's containers, network and volumes. Two runs
# (other sessions, other worktrees) never share or remove each other's resources. Nothing host-wide is
# pruned. The exit status is the test command's; a cleanup failure is reported, never hidden.
set -uo pipefail
cd "$(dirname "$0")/.."
export CATALYST_UID="$(id -u)" CATALYST_GID="$(id -g)"
PROJECT="${CATALYST_TEST_PROJECT:-catalyst-v2-test-$(date +%s)-$$-$RANDOM}"
COMPOSE=(docker compose --project-name "$PROJECT" --file compose.yaml)

cleanup() {
  if ! "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1; then
    echo "test.sh: cleanup of compose project $PROJECT failed; inspect with: docker compose -p $PROJECT ps -a" >&2
  fi
}
trap cleanup EXIT

echo "test.sh: compose project $PROJECT" >&2
"${COMPOSE[@]}" run --rm test
status=$?
exit "$status"
