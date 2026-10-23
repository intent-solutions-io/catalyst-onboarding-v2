#!/usr/bin/env bash
# DW_DEPLOY_CMD <image>: make <image> the serving one (the wrapper's revert uses this too). Migrations are not run
# here: they run before the deploy, after the pre-deploy backup (predeploy.sh). Fails closed: anything it cannot
# read refuses the switch, and the wrapper reverts and holds. Before anything changes, in this order:
#   - the deploy operation (CATALYST_DEPLOY_ID, config.release) must know <image>: as its approved target, whose
#     commit label must be the approved commit and whose pre-deploy backup must be bound to this operation, still
#     present, unchanged and no older than it (9kg.37: a mismatch is a refusal, never a recorded deviation); or as
#     its previous image, the wrapper's revert, which returns to what was recorded. The image already serving may
#     always be re-applied (the wrapper restores it when an apply was refused before any switch). Anything else is
#     refused.
#   - <image> must know every forward-only migration already applied (config.release), because only a restore can
#     undo one.
source "$(dirname "$0")/lib.sh"
target="${1:?usage: deploy.sh <image>}"
: "${CATALYST_DEPLOY_ID:?the id of the deploy operation}"
valid_ref "$target" || fail "refused: $target is not a content reference"
docker image inspect "$target" >/dev/null 2>&1 || fail "refused: $target is not present on this host"
label="$(image_label "$target")" || fail "refused: cannot read $target's commit label"
serving="$( [ -s "$POINTER" ] && cat "$POINTER" || echo - )"
role="$(operation gate "$target" "$label" "$serving")" || fail "refused: deploy $CATALYST_DEPLOY_ID does not allow switching to $target; nothing changed"
# The record before this switch, plus the target's own marks: a revert away from the target must still know them.
recorded="$(recorded_forward_only)" || exit 1
target_fwd="$(in_image "$target" forward-only)" || fail "refused: cannot read $target's forward-only list"
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

record_forward_only "$target" >/dev/null  # before switching: a revert away knows it (kept even if the switch fails)
tmp="$(mktemp "$CATALYST_DEPLOY_STATE/.deploy.XXXXXX")"
trap 'rm -f "$tmp"' EXIT
printf '%s\n' "$target" > "$tmp"
CATALYST_IMAGE="$target" compose up -d --no-deps --force-recreate web worker fetcher >/dev/null || fail "compose up failed"
mv -f "$tmp" "$POINTER"  # recorded only once the containers were recreated from it; the smoke checks they stay up
echo "catalyst-deploy: $role $target (deploy $CATALYST_DEPLOY_ID)" >&2
