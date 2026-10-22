#!/usr/bin/env bash
# Before the wrapper deploys <image>: the pre-deploy backup, then the migrations with that image, as the owner (026
# section 4: "Migrations run before the deploy step, after a pre-deploy backup"). CATALYST_BACKUP_CMD must be set; it
# prints the backup's receipt path. Fails closed: no backup, no migration, no deploy.
source "$(dirname "$0")/lib.sh"
target="${1:?usage: predeploy.sh <image>}"
valid_ref "$target" || fail "refused: $target is not a content reference"
: "${CATALYST_BACKUP_CMD:?the pre-deploy backup command (no backup, no migration)}"
receipt="$(eval "$CATALYST_BACKUP_CMD")" || fail "the pre-deploy backup failed; nothing migrated"
CATALYST_IMAGE="$target" compose run --rm --no-deps migrate >/dev/null || fail "the migrations failed with $target"
printf '%s\n' "$receipt"
