#!/usr/bin/env bash
# DW_CAPTURE_CMD: print the serving image, or fail (no known-good release, so the wrapper refuses to deploy). The image
# must still be on this host: a revert target that was pruned is no known-good at all.
source "$(dirname "$0")/lib.sh"
[ -s "$POINTER" ] || fail "no serving image recorded"
current="$(<"$POINTER")"
valid_ref "$current" || fail "the recorded serving image is not a content reference"
docker image inspect "$current" >/dev/null 2>&1 || fail "the recorded serving image is no longer on this host"
printf '%s\n' "$current"
