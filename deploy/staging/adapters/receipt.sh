#!/usr/bin/env bash
# After a promotion: write the deployment receipt (026 section 4), no personal data. The checks that decide promotion
# run in smoke.sh, before it; this is the record, and it fails (for the operator and the alert floor) if the serving
# release no longer reads back as intended or the pre-deploy backup's receipt is missing.
source "$(dirname "$0")/lib.sh"
: "${CATALYST_BACKUP_RECEIPT:?the receipt path of the pre-deploy backup, which predeploy.sh prints}"
[ -e "$CATALYST_BACKUP_RECEIPT" ] || fail "the pre-deploy backup's receipt does not exist"
image="$(<"$POINTER")"
label="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")"
facts="$(compose exec -T web python manage.py catalyst_release receipt)" || fail "cannot read the release facts"
# The receipt keeps the failing check ids (for example security.W004), never the configuration they describe.
check=pass
ids="$(compose exec -T web python manage.py check --deploy --fail-level WARNING 2>&1)" || \
  check="fail: $(grep -oE '\(([a-z_]+\.[A-Z][0-9]+)\)' <<<"$ids" | tr -d '()' | sort -u | tr '\n' ' ' || true)"
"$(dirname "$0")/smoke.sh" >/dev/null 2>&1 && ready=pass || ready=fail
mkdir -p "$CATALYST_DEPLOY_STATE/receipts"
out="$CATALYST_DEPLOY_STATE/receipts/$(date -u +%Y%m%dT%H%M%SZ).json"
python3 - "$image" "$label" "$facts" "$check" "$ready" "$CATALYST_BACKUP_RECEIPT" "${CATALYST_EXPECTED_COMMIT:-}" > "$out" <<'PY'
import datetime, json, sys
image, label, facts, check, ready, backup, expected = sys.argv[1:]
print(json.dumps({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "image": image,
                  "label_commit": label, "expected_commit": expected or None, **json.loads(facts),
                  "check_deploy": check, "smoke_readback": ready, "pre_deploy_backup_receipt": backup},
                 indent=2, sort_keys=True))
PY
problems=()
[ -z "${CATALYST_EXPECTED_COMMIT:-}" ] || [ "$label" = "$CATALYST_EXPECTED_COMMIT" ] || problems+=("not the intended commit")
[ "$check" = pass ] || problems+=("check --deploy $check")
[ "$ready" = pass ] || problems+=("the smoke failed at readback")
echo "$out"
[ "${#problems[@]}" = 0 ] || fail "receipt mismatch: ${problems[*]}"
