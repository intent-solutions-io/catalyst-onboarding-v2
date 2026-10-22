#!/usr/bin/env bash
# DW_DEPLOY_CMD <image>: make <image> the serving one (the wrapper's revert uses this too). Migrations are not run
# here: they run before the deploy, after the pre-deploy backup (predeploy.sh). Refuses an image that does not know a
# forward-only migration already applied (config.release), because only a restore can undo one.
source "$(dirname "$0")/lib.sh"
target="${1:?usage: deploy.sh <image>}"
valid_ref "$target" || fail "refused: $target is not a content reference"
docker image inspect "$target" >/dev/null 2>&1 || fail "refused: $target is not present on this host"

# Never through the serving containers: during a revert they are the broken release. The applied migrations are read by
# the target image itself (a one-off container with the web service's role and secrets); the forward-only lists are
# read from both images offline.
if [ -s "$POINTER" ]; then
  serving="$(<"$POINTER")"
  applied="$(CATALYST_IMAGE="$target" compose run --rm --no-deps -T web python manage.py catalyst_release applied)" \
    || fail "cannot read the applied migrations with $target"
  serving_fwd="$(docker run --rm --network none --entrypoint python "$serving" -m config.release forward-only)" \
    || serving_fwd="[]"  # an unreadable serving image cannot mark anything; the target's own list still applies
  target_known="$(docker run --rm --network none --entrypoint python "$target" -m config.release known)" \
    || fail "cannot read the target image's migrations"
  target_fwd="$(docker run --rm --network none --entrypoint python "$target" -m config.release forward-only)" \
    || fail "cannot read the target image"
  blocked="$(python3 - "$applied" "$target_known" "$serving_fwd" "$target_fwd" <<'PY'
import json, sys
applied, known, fwd_a, fwd_b = (json.loads(a) for a in sys.argv[1:])
print(" ".join(sorted(set(applied) & (set(fwd_a) | set(fwd_b)) - set(known))))
PY
)"
  [ -z "$blocked" ] || fail "refused: forward-only migrations applied that $target does not know ($blocked); restore instead"
fi

tmp="$(mktemp "$CATALYST_DEPLOY_STATE/.current-image.XXXXXX")"
printf '%s\n' "$target" > "$tmp"
CATALYST_IMAGE="$target" compose up -d --no-deps --force-recreate web worker fetcher >/dev/null
mv -f "$tmp" "$POINTER"  # recorded only once the containers were recreated from it
