# Shared by the Catalyst deploy adapters (026 section 4; 6B.10). Sourced, never run.
#
# The estate deploy wrapper calls the adapters as hooks: capture.sh (DW_CAPTURE_CMD), deploy.sh <image>
# (DW_DEPLOY_CMD, also the revert), smoke.sh (DW_SMOKE_CMD); predeploy.sh <image> runs before the wrapper and
# receipt.sh after a promotion. They read:
#   CATALYST_DEPLOY_STATE    a directory the deploy user owns: current-image (the serving image), receipts/,
#                            forward-only.json, operations/<deploy id>/ (the operation and its bound backup)
#   CATALYST_DEPLOY_ID       the deploy operation's id, chosen by the caller (the force-command) and used once per
#                            deploy: predeploy.sh, deploy.sh and receipt.sh require it; smoke.sh honours it
#   CATALYST_EXPECTED_COMMIT optional for predeploy.sh: the approved commit the target image must carry
#   CATALYST_COMPOSE_PROJECT the compose project name
#   CATALYST_COMPOSE_FILE    the generated deploy/staging/compose.yaml
#   CATALYST_SMOKE_URL       optional, the public form's URL through the proxy (an outside-in request)
#   CATALYST_SMOKE_RESOLVE   optional, curl --resolve value for that URL (a staging name with no DNS)
#   CATALYST_STACK_ENV       the stack these adapters run, required: staging or production (9kg.78.1)
#   CATALYST_PROBE_CA_FILE   optional outside staging: the CA file the outside-in probe trusts (a private proxy CA)
# plus the compose file's own variables (hosts, publish addresses, the stack's secrets directory variable).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/stack.sh"

: "${CATALYST_DEPLOY_STATE:?}" "${CATALYST_COMPOSE_PROJECT:?}" "${CATALYST_COMPOSE_FILE:?}"
POINTER="$CATALYST_DEPLOY_STATE/current-image"
# Every forward-only migration any deployed image has named: recorded at each deploy from the image being deployed,
# so a revert never depends on the (possibly broken) serving image to say what it marked. It only grows.
FORWARD_ONLY_STATE="$CATALYST_DEPLOY_STATE/forward-only.json"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
# An image named by content only: a registry reference pinned by digest, or a local image id. Never a mutable tag.
IMAGE_REF='^([a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?@)?sha256:[0-9a-f]{64}$'

# The compose file names its image as a required variable even for ps and exec: default it to the recorded image.
export CATALYST_IMAGE="${CATALYST_IMAGE:-$( [ -s "$POINTER" ] && cat "$POINTER" || echo "sha256:$(printf '0%.0s' $(seq 64))")}"
compose() { docker compose --project-name "$CATALYST_COMPOSE_PROJECT" -f "$CATALYST_COMPOSE_FILE" "$@"; }
valid_ref() { [[ "$1" =~ $IMAGE_REF ]]; }
release() { PYTHONPATH="$REPO" python3 -m config.release "$@"; }  # the tested code (config/release.py), no Django
in_image() { docker run --rm --network none --entrypoint python "$1" -m config.release "${@:2}"; }
# The deploy operation (config.release; 9kg.37): predeploy.sh starts it and binds the pre-deploy backup to it;
# deploy.sh asks it whether <image> is the operation's approved target (with its backup bound) or its revert.
operation() { release operation "$1" "$CATALYST_DEPLOY_STATE" "${CATALYST_DEPLOY_ID:?the id of the deploy operation}" "${@:2}"; }
image_label() { docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$1"; }

# Print the recorded forward-only list. With a serving release recorded, a missing record is lost state, never "none":
# only the very first deploy (no pointer yet) starts from an empty list.
recorded_forward_only() {
  if [ -s "$FORWARD_ONLY_STATE" ]; then cat "$FORWARD_ONLY_STATE"
  elif [ -s "$POINTER" ]; then fail "refused: the forward-only record is missing; restore it from the deploy state backup or hold"
  else echo '[]'
  fi
}

# Add <image>'s forward-only migrations to the record, atomically, before anything can apply them (predeploy) or switch
# to that image (deploy). Prints the merged list. Fails when either list cannot be read.
record_forward_only() {
  local recorded target_fwd merged tmp
  recorded="$(recorded_forward_only)" || exit 1
  target_fwd="$(in_image "$1" forward-only)" || fail "refused: cannot read $1's forward-only list"
  merged="$(python3 -c 'import json,sys;print(json.dumps(sorted(set(json.loads(sys.argv[1]))|set(json.loads(sys.argv[2])))))' \
    "$recorded" "$target_fwd")" || fail "refused: the forward-only lists are unreadable"
  tmp="$(mktemp "$CATALYST_DEPLOY_STATE/.forward-only.XXXXXX")"
  printf '%s\n' "$merged" > "$tmp" && mv -f "$tmp" "$FORWARD_ONLY_STATE"
  printf '%s\n' "$merged"
}
fail() { echo "catalyst-deploy: $*" >&2; exit 1; }
