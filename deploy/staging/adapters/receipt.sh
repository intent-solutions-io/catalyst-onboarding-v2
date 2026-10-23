#!/usr/bin/env bash
# After a promotion: write the deployment receipt (026 section 4), no personal data. Every comparison it records was
# a gate before promotion: the identity and the bound backup in deploy.sh, the readback and `check --deploy` in
# smoke.sh (9kg.37). This is the record of that gate for the operator and the alert floor, and it still fails if the
# serving release no longer reads back as intended or the deploy operation no longer allows it, so a drift after
# promotion is never silent. The receipt counts only once the personal-data scan (config/personal_data_scan.py;
# 9kg.40, TEST-P6-35) has passed over it and over the bound pre-deploy backup's receipt: a hit withholds the
# receipt (nothing is kept) and fails the step.
source "$(dirname "$0")/lib.sh"
: "${CATALYST_DEPLOY_ID:?the id of the deploy operation}"
image="$(<"$POINTER")"
label="$(image_label "$image")"
op="$(operation show)" || fail "cannot read deploy $CATALYST_DEPLOY_ID"
# Asked without the "already serving" allowance: the receipt states whether the serving image is this operation's
# approved target with its backup bound (deploy), its recorded revert, or neither.
role="$(operation gate "$image" "$label" - 2>"$CATALYST_DEPLOY_STATE/.receipt-gate.err")" || role="refused: $(<"$CATALYST_DEPLOY_STATE/.receipt-gate.err")"
rm -f "$CATALYST_DEPLOY_STATE/.receipt-gate.err"
facts="$(compose exec -T web python manage.py catalyst_release receipt)" || fail "cannot read the release facts"
# The receipt keeps the failing check ids (for example security.W004), never the configuration they describe.
check=pass
ids="$(compose exec -T web python manage.py check --deploy --fail-level WARNING 2>&1)" || \
  check="fail: $(grep -oE '\(([a-z_]+\.[A-Z][0-9]+)\)' <<<"$ids" | tr -d '()' | sort -u | tr '\n' ' ' || true)"
"$(dirname "$0")/smoke.sh" >/dev/null 2>&1 && ready=pass || ready=fail
mkdir -p "$CATALYST_DEPLOY_STATE/receipts"
out="$CATALYST_DEPLOY_STATE/receipts/$(date -u +%Y%m%dT%H%M%SZ).json"
pending="$(mktemp "$CATALYST_DEPLOY_STATE/receipts/.pending.XXXXXX")"
python3 - "$image" "$label" "$facts" "$check" "$ready" "$op" "$role" > "$pending" <<'PY'
import datetime, json, sys
image, label, facts, check, ready, op, role = sys.argv[1:]
op = json.loads(op)
backup = op.get("pre_deploy_backup") or {}
print(json.dumps({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "image": image,
                  "label_commit": label, "deploy_id": op["deploy_id"], "operation": role,
                  "expected_commit": op["expected_commit"], "approved_image": op["target"], **json.loads(facts),
                  "check_deploy": check, "smoke_readback": ready,
                  "pre_deploy_backup": {"receipt": backup.get("receipt"), "sha256": backup.get("receipt_sha256"),
                                        "finished_at": backup.get("backup_finished_at_utc"),
                                        "deploy_id": backup.get("deploy_id")}},
                 indent=2, sort_keys=True))
PY
# The scan prints locations and pattern names only, never a value; it fails closed on an unreadable input, so a bound
# backup receipt that is gone withholds the deployment receipt too.
bound="$(python3 -c 'import json,sys;print((json.loads(sys.argv[1]).get("pre_deploy_backup") or {}).get("receipt") or "")' "$op")"
if ! PYTHONPATH="$REPO" python3 -m config.personal_data_scan --class receipt "$pending" ${bound:+"$bound"}; then
  rm -f "$pending"
  fail "receipt withheld: the personal-data scan did not pass over the deployment receipt and the pre-deploy backup receipt"
fi
mv -f "$pending" "$out"
problems=()
[ "$role" = deploy ] || [ "$role" = revert ] || problems+=("$role")
[ "$check" = pass ] || problems+=("check --deploy $check")
[ "$ready" = pass ] || problems+=("the smoke failed at readback")
echo "$out"
[ "${#problems[@]}" = 0 ] || fail "receipt mismatch: ${problems[*]}"
