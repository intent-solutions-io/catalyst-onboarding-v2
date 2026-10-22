# Shared by the Catalyst deploy adapters (026 section 4; 6B.10). Sourced, never run.
#
# The estate deploy wrapper calls the adapters as hooks: capture.sh (DW_CAPTURE_CMD), deploy.sh <image>
# (DW_DEPLOY_CMD, also the revert), smoke.sh (DW_SMOKE_CMD); receipt.sh runs after a promotion. They read:
#   CATALYST_DEPLOY_STATE    a directory the deploy user owns: current-image (the serving image), receipts/
#   CATALYST_COMPOSE_PROJECT the compose project name
#   CATALYST_COMPOSE_FILE    the generated deploy/staging/compose.yaml
#   CATALYST_SMOKE_URL       optional, the public form's URL through the proxy (an outside-in request)
#   CATALYST_SMOKE_RESOLVE   optional, curl --resolve value for that URL (a staging name with no DNS)
# plus the compose file's own variables (hosts, publish addresses, CATALYST_STAGING_SECRETS).
set -euo pipefail

: "${CATALYST_DEPLOY_STATE:?}" "${CATALYST_COMPOSE_PROJECT:?}" "${CATALYST_COMPOSE_FILE:?}"
POINTER="$CATALYST_DEPLOY_STATE/current-image"
# An image named by content only: a registry reference pinned by digest, or a local image id. Never a mutable tag.
IMAGE_REF='^([a-z0-9][a-z0-9._/-]*(:[A-Za-z0-9._-]+)?@)?sha256:[0-9a-f]{64}$'

# The compose file names its image as a required variable even for ps and exec: default it to the recorded image.
export CATALYST_IMAGE="${CATALYST_IMAGE:-$( [ -s "$POINTER" ] && cat "$POINTER" || echo "sha256:$(printf '0%.0s' $(seq 64))")}"
compose() { docker compose --project-name "$CATALYST_COMPOSE_PROJECT" -f "$CATALYST_COMPOSE_FILE" "$@"; }
valid_ref() { [[ "$1" =~ $IMAGE_REF ]]; }
fail() { echo "catalyst-deploy: $*" >&2; exit 1; }
