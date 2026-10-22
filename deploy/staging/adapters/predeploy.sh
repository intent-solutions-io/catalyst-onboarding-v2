#!/usr/bin/env bash
# Before the wrapper deploys <image>: the pre-deploy backup, then the migrations with that image, as the owner (026
# section 4: "Migrations run before the deploy step, after a pre-deploy backup"). CATALYST_BACKUP_CMD must print the
# path of the backup's receipt, which must exist. Fails closed: no backup receipt, no migration, no deploy. Prints the
# receipt's path for receipt.sh (CATALYST_BACKUP_RECEIPT). The smoke refuses an unmigrated release on its own.
source "$(dirname "$0")/lib.sh"
target="${1:?usage: predeploy.sh <image>}"
valid_ref "$target" || fail "refused: $target is not a content reference"
: "${CATALYST_BACKUP_CMD:?the pre-deploy backup command (no backup, no migration)}"
receipt="$(bash -c "$CATALYST_BACKUP_CMD")" || fail "the pre-deploy backup failed; nothing migrated"
[ -n "$receipt" ] && [ -e "$receipt" ] || fail "the pre-deploy backup printed no receipt that exists; nothing migrated"
# Recorded before migrating: if the deploy then aborts, a later revert still knows what this image applied.
record_forward_only "$target" >/dev/null
CATALYST_IMAGE="$target" compose run --rm --no-deps migrate >/dev/null || fail "the migrations failed with $target"
printf '%s\n' "$receipt"
