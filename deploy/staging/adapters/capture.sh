#!/usr/bin/env bash
# DW_CAPTURE_CMD: print the serving image, or fail (no known-good release, so the wrapper refuses to deploy).
source "$(dirname "$0")/lib.sh"
[ -s "$POINTER" ] || fail "no serving image recorded"
current="$(<"$POINTER")"
valid_ref "$current" || fail "the recorded serving image is not a content reference"
printf '%s\n' "$current"
