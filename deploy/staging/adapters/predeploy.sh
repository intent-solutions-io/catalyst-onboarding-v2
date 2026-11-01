#!/usr/bin/env bash
# Before the wrapper deploys <image>: start the deploy operation (CATALYST_DEPLOY_ID), the pre-deploy backup bound to
# it, then the migrations with that image, as the owner (026 section 4: "Migrations run before the deploy step, after
# a pre-deploy backup"). Fails closed, in this order, and nothing after a refusal runs:
#   - the image must carry the approved commit (CATALYST_EXPECTED_COMMIT) as its label, or nothing is backed up or
#     migrated with it (9kg.37: the serving identity must equal the approved artifact);
#   - CATALYST_BACKUP_CMD must print the path of the backup's receipt, which must exist and be no older than this
#     operation; an older receipt's path is refused as stale, and nothing is migrated;
#   - the binding (the deploy id, the receipt's path, digest and time) is what deploy.sh checks before switching.
# Prints the binding's path. A migration that fails leaves the operation bound and the deploy to the smoke, which
# refuses an unmigrated release on its own (the wrapper then reverts and holds).
source "$(dirname "$0")/lib.sh"
target="${1:?usage: predeploy.sh <image>}"
: "${CATALYST_DEPLOY_ID:?the id of the deploy operation}"
valid_ref "$target" || fail "refused: $target is not a content reference"
docker image inspect "$target" >/dev/null 2>&1 || fail "refused: $target is not present on this host"
if [ -n "${CATALYST_EXPECTED_COMMIT:-}" ]; then
  label="$(image_label "$target")" || fail "refused: cannot read $target's commit label"
  [ "$label" = "$CATALYST_EXPECTED_COMMIT" ] || fail "refused: $target's commit label is not the approved commit; nothing backed up or migrated"
fi
check_journal_layout "$target" >&2
previous="$( [ -s "$POINTER" ] && cat "$POINTER" || echo - )"
operation start "$target" "${CATALYST_EXPECTED_COMMIT:--}" "$previous" >/dev/null || fail "refused: cannot start deploy $CATALYST_DEPLOY_ID"
: "${CATALYST_BACKUP_CMD:?the pre-deploy backup command (no backup, no migration)}"
receipt="$(bash -c "$CATALYST_BACKUP_CMD")" || fail "the pre-deploy backup failed; nothing migrated"
[ -n "$receipt" ] && [ -e "$receipt" ] || fail "the pre-deploy backup printed no receipt that exists; nothing migrated"
binding="$(operation bind "$receipt")" || fail "the pre-deploy backup is not bound to deploy $CATALYST_DEPLOY_ID; nothing migrated"
# Recorded before migrating: if the deploy then aborts, a later revert still knows what this image applied.
record_forward_only "$target" >/dev/null
CATALYST_IMAGE="$target" compose run --rm --no-deps migrate >/dev/null || fail "the migrations failed with $target"
printf '%s\n' "$binding"
