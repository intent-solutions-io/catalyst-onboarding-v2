#!/usr/bin/env bash
# After a promotion: write the deployment receipt (026 section 4), no personal data. Fails when what is serving does
# not read back as what was intended: the commit in the image differs from its label, migrations are pending, the
# deploy checks fail, or readiness is not 200.
source "$(dirname "$0")/lib.sh"
image="$(<"$POINTER")"
label="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")"
facts="$(compose exec -T web python manage.py catalyst_release receipt)" || fail "cannot read the release facts"
# The receipt keeps the failing check ids (for example security.W004), never the configuration they describe.
check=pass
ids="$(compose exec -T web python manage.py check --deploy --fail-level WARNING 2>&1)" || \
  check="fail: $(grep -oE '\(([a-z_]+\.[A-Z][0-9]+)\)' <<<"$ids" | tr -d '()' | sort -u | tr '\n' ' ')"
"$(dirname "$0")/smoke.sh" >/dev/null 2>&1 && ready=200 || ready=fail
mkdir -p "$CATALYST_DEPLOY_STATE/receipts"
out="$CATALYST_DEPLOY_STATE/receipts/$(date -u +%Y%m%dT%H%M%SZ).json"
python3 - "$image" "$label" "$facts" "$check" "$ready" "${CATALYST_BACKUP_RECEIPT:-}" > "$out" <<'PY'
import datetime, json, sys
image, label, facts, check, ready, backup = sys.argv[1:]
facts = json.loads(facts)
print(json.dumps({"at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"), "image": image,
                  "label_commit": label, **facts, "check_deploy": check, "readyz": ready,
                  "pre_deploy_backup_receipt": backup or None}, indent=2, sort_keys=True))
PY
problems=()
[ "$label" = "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["commit"])' "$out")" ] || problems+=("the image's commit differs from its label")
[ "$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["migrations_pending"])' "$out")" = 0 ] || problems+=("migrations are pending")
[ "$check" = pass ] || problems+=("check --deploy $check")
[ "$ready" = 200 ] || problems+=("the smoke failed at readback")
echo "$out"
[ "${#problems[@]}" = 0 ] || fail "receipt mismatch: ${problems[*]}"
