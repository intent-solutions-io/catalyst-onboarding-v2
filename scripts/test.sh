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
# 9kg.64: the commit this run tests, from the host's git (the test image has no git); compose.yaml passes it to the
# test service, and the evidence register stamps it on its report and on register.json.
CATALYST_RUN_COMMIT="$(git rev-parse HEAD 2>/dev/null)" || CATALYST_RUN_COMMIT=unrecorded
export CATALYST_RUN_COMMIT
# CATALYST_TEST_PROJECT lets a caller choose the name; that name is then the caller's responsibility, and
# the script refuses to use one that already has containers so it can never clean up someone else's run.
PROJECT="${CATALYST_TEST_PROJECT:-catalyst-v2-test-$(date +%s)-$$-$RANDOM}"
COMPOSE=(docker compose --project-name "$PROJECT" --file compose.yaml)
if [ -n "$("${COMPOSE[@]}" ps --all --quiet 2>/dev/null)" ]; then
  echo "test.sh: compose project $PROJECT already has containers; refusing to run or clean it up" >&2
  exit 2
fi

cleanup() {
  local err
  if ! err="$("${COMPOSE[@]}" down --volumes --remove-orphans 2>&1 >/dev/null)"; then
    echo "test.sh: cleanup of compose project $PROJECT failed: $err" >&2
    echo "test.sh: inspect with: docker compose -p $PROJECT ps -a" >&2
  fi
}
trap cleanup EXIT

echo "test.sh: compose project $PROJECT" >&2
"${COMPOSE[@]}" run --rm test
status=$?
exit "$status"
