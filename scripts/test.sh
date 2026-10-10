#!/usr/bin/env bash
# Run the runtime test suite locally in the digest-pinned containers (compose.yaml), then remove them.
set -euo pipefail
cd "$(dirname "$0")/.."
export CATALYST_UID="$(id -u)" CATALYST_GID="$(id -g)"
trap 'docker compose down --volumes --remove-orphans >/dev/null 2>&1' EXIT
docker compose run --rm test
