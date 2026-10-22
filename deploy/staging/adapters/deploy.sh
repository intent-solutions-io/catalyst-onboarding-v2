#!/usr/bin/env bash
# DW_DEPLOY_CMD <image>: make <image> the serving one (the wrapper's revert uses this too). Migrations are not run
# here: they run before the deploy, after the pre-deploy backup (predeploy.sh). Refuses an image that does not know a
# forward-only migration already applied (config.release), because only a restore can undo one. Fails closed: anything
# it cannot read refuses the switch, and the wrapper holds.
source "$(dirname "$0")/lib.sh"
target="${1:?usage: deploy.sh <image>}"
valid_ref "$target" || fail "refused: $target is not a content reference"
docker image inspect "$target" >/dev/null 2>&1 || fail "refused: $target is not present on this host"
target_fwd="$(in_image "$target" forward-only)" || fail "refused: cannot read $target's forward-only list"
recorded="$( [ -s "$FORWARD_ONLY_STATE" ] && cat "$FORWARD_ONLY_STATE" || echo '[]')"
marked="$(python3 -c 'import json,sys;print(json.dumps(sorted(set(json.loads(sys.argv[1]))|set(json.loads(sys.argv[2])))))' \
  "$recorded" "$target_fwd")" || fail "refused: the recorded forward-only list is unreadable"

# Never through the serving containers: during a revert they are the broken release. The applied migrations are read
# by the target image itself (a one-off container with the web service's role and secrets), its migrations offline.
if [ -s "$POINTER" ]; then
  applied="$(CATALYST_IMAGE="$target" compose run --rm --no-deps -T web python manage.py catalyst_release applied)" \
    || fail "refused: cannot read the applied migrations with $target"
  target_known="$(in_image "$target" known)" || fail "refused: cannot read $target's migrations"
  blocked="$(release blockers "$applied" "$target_known" "$marked")" || fail "refused: the forward-only check failed"
  [ -z "$blocked" ] || fail "refused: forward-only migrations applied that $target does not know ($blocked); restore instead"
fi

tmp="$(mktemp "$CATALYST_DEPLOY_STATE/.deploy.XXXXXX")"
trap 'rm -f "$tmp" "$tmp.fwd"' EXIT
printf '%s\n' "$marked" > "$tmp.fwd" && mv -f "$tmp.fwd" "$FORWARD_ONLY_STATE"  # before switching: a revert away knows it
printf '%s\n' "$target" > "$tmp"
CATALYST_IMAGE="$target" compose up -d --no-deps --force-recreate web worker fetcher >/dev/null || fail "compose up failed"
mv -f "$tmp" "$POINTER"  # recorded only once the containers were recreated from it; the smoke checks they stay up
