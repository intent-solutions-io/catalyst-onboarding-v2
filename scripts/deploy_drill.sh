#!/usr/bin/env bash
# The deploy drill (026 sections 4, 9 and 16; 6B.10, 9kg.37, 9kg.38): the estate deploy wrapper drives the Catalyst
# adapters (deploy/staging/adapters) against the generated staging stack on this host, with synthetic secrets, then
# removes everything. Dev box only.
#
#   DW_WRAPPER=<path to the estate deploy-wrapper.sh> scripts/deploy_drill.sh
#
# Cases, each with its positive control: a first release (outside the wrapper: it needs a known-good to revert to); a
# good release promoted with a receipt; broken releases whose smoke fails, reverted automatically to the previous
# image; the deploy operation's gates (TEST-P6-10, 24): an image other than the approved one, an unapproved commit
# label, a stale backup receipt and another deploy's backup are each refused through the wrapper, with the stack
# unchanged; the rollback ladder's step 2 (TEST-P6-25): a release N+1 that expands the schema, then the image reverted
# to N on the expanded schema with the smoke green and the data kept, and a release with a forward-only (contract)
# migration whose revert is refused, naming the migration, with image and data untouched; a forward-only migration
# applied by a predeploy whose deploy never happened; a lost forward-only record; a tag; an unattested tarball.
# Prints PASS or FAIL per case.
set -uo pipefail
cd "$(dirname "$0")/.."
export CATALYST_STACK_ENV=staging  # the adapters require it (9kg.78.1); this drill runs the staging stack only
: "${DW_WRAPPER:?the path of the estate deploy wrapper}"

project="catalyst-deploy-drill-$$"
work="$(mktemp -d)"
fail=0
commit="$(git rev-parse HEAD)"
export CATALYST_PUBLIC_HOST=catalyst.staging.test CATALYST_STAFF_HOST=staff.staging.test \
  CATALYST_PUBLIC_PUBLISH=127.0.0.1 CATALYST_STAFF_PUBLISH=127.0.0.2 CATALYST_PUBLIC_PORT=18443 \
  CATALYST_STAFF_PORT=18444 CATALYST_STAGING_SECRETS="$work/secrets" CATALYST_DEPLOY_STATE="$work/state" \
  CATALYST_COMPOSE_PROJECT="$project" CATALYST_COMPOSE_FILE="$PWD/deploy/staging/compose.yaml" \
  CATALYST_SMOKE_URL="https://catalyst.staging.test:18443/request-access/" \
  CATALYST_SMOKE_RESOLVE="catalyst.staging.test:18443:127.0.0.1" CATALYST_SMOKE_SECONDS=20 \
  CATALYST_EXPECTED_COMMIT="$commit" \
  DW_STATE_DIR="$work/wrapper" DW_STACK=catalyst-staging-drill DW_SMOKE_ATTEMPTS=1 DW_SMOKE_INTERVAL=1
adapters="$PWD/deploy/staging/adapters"
export DW_CAPTURE_CMD="$adapters/capture.sh" DW_DEPLOY_CMD="$adapters/deploy.sh" DW_SMOKE_CMD="$adapters/smoke.sh" \
  DW_NOTIFY_CMD="printf 'notify %s %s\n' >> $work/notify.log" DW_AUDIT_CMD="printf '%s\n' >> $work/audit.ndjson"
images=()
compose() { docker compose --project-name "$project" -f deploy/staging/compose.yaml "$@"; }
cleanup() {
  CATALYST_IMAGE="sha256:$(printf '0%.0s' $(seq 64))" compose --profile provision down -v --remove-orphans >/dev/null 2>&1
  for image in "${images[@]}"; do docker image rm -f "$image" >/dev/null 2>&1; done
  docker image ls -q "catalyst-deploy-drill-$$" | xargs -r docker image rm -f >/dev/null 2>&1
  rm -rf "$work"
}
trap cleanup EXIT
check() { local name="$1"; shift; if "$@"; then echo "PASS $name"; else echo "FAIL $name"; fail=1; fi; }
tag() { printf 'catalyst-deploy-drill-%s:%s' "$$" "$1"; }  # BuildKit builds FROM a tag, never a bare id
derive() {  # derive <base name> <new name> <shell run as root>: the derived image's id (deploys use ids, never tags)
  local id
  id="$(printf 'FROM %s\nUSER root\nRUN %s\nUSER catalyst\n' "$(tag "$1")" "$3" | docker build -q -t "$(tag "$2")" -)" \
    || return 1
  images+=("$id"); printf '%s\n' "$id"
}
put() { printf 'echo %s | base64 -d > %s' "$(printf '%s' "$2" | base64 -w0)" "$1"; }  # put <path> <content>: a RUN step
op() { export CATALYST_DEPLOY_ID="drill-$1"; }  # one deploy operation per case, as the force-command names them
wrapper() { "$DW_WRAPPER" "$1" >/dev/null 2>"$work/wrapper-$CATALYST_DEPLOY_ID.err"; }
serving() { "$adapters/capture.sh"; }
latest_receipt() { ls -t "$CATALYST_DEPLOY_STATE/receipts" | head -1 | sed "s|^|$CATALYST_DEPLOY_STATE/receipts/|"; }
applied_with() { CATALYST_IMAGE="$1" compose run --rm --no-deps -T web python manage.py catalyst_release applied 2>/dev/null; }
in_web() { compose exec -T web python manage.py shell -c "$1" 2>/dev/null | tail -1; }
drill_column() { in_web "from django.db import connection as c; cur = c.cursor(); cur.execute(\"select count(*) from information_schema.columns where table_name = 'workflow_pendingaction' and column_name = 'drill_note'\"); print(cur.fetchone()[0])"; }
applications() { in_web "from applications.models import Application; print(Application.objects.count())"; }
invite() {  # invite <email>: 9kg.63, intake is invitation-only (9kg.43), so the owner invites the address first, as
  # restore_drill.sh does: the owner-run command on the serving image, as the migration owner.
  CATALYST_IMAGE="$(serving)" compose run --rm --no-deps -T migrate python manage.py catalyst_invite "$1" \
    --issued-by "deploy drill" --note "synthetic drill applicant" 2>/dev/null | grep -q '"issued": true'
}
submit() {  # submit <email>: the owner's invitation, then an applicant through the real form, via the proxy
  local jar="$work/jar-$1" form csrf
  invite "$1" || return 1
  form="$(curl -sk -c "$jar" --resolve catalyst.staging.test:18443:127.0.0.1 https://catalyst.staging.test:18443/request-access/)"
  csrf="$(grep -oE 'name="csrfmiddlewaretoken" value="[^"]+"' <<<"$form" | head -1 | sed 's/.*value="//; s/"$//')"
  [ "$(curl -sk -b "$jar" -o /dev/null -w '%{http_code}' --resolve catalyst.staging.test:18443:127.0.0.1 \
    -H 'Referer: https://catalyst.staging.test:18443/request-access/' -H 'Origin: https://catalyst.staging.test:18443' \
    --data-urlencode "csrfmiddlewaretoken=$csrf" --data-urlencode 'name=Deploy Drill' --data-urlencode "email=$1" \
    --data-urlencode 'reason=Synthetic reason for access.' https://catalyst.staging.test:18443/request-access/)" = 302 ]
}

install -d -m 0700 "$work/secrets" "$work/state" "$work/wrapper" "$work/backups"
for name in secret_key verification_key admin_password owner_password app_password retention_password \
            backup_password fetcher_password; do
  # 64 random characters: Django's deploy check (security.W009) wants a key of at least 50.
  printf 'synthetic-%s-%s' "$name" "$(head -c 96 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 64)" > "$work/secrets/$name"
done
: > "${CATALYST_STAGING_SECRETS}/verification_fallback_keys"  # empty: no rotation under way (027)
chmod 0444 "$work/secrets"/*

good="$(docker build -q --target staging --build-arg "CATALYST_COMMIT=$commit" -t "$(tag good)" .)" || exit 1
images+=("$good")
# Staging data is synthetic, so the drill's backup stand-in writes one receipt per deploy operation, as the host's
# backup job writes one per run; 9kg.22 wires the real job. The receipt's time is what the binding dates.
printf '#!/usr/bin/env bash\nf="%s/backups/$CATALYST_DEPLOY_ID.json"; echo "{\\"synthetic\\": true}" > "$f" && echo "$f"\n' "$work" > "$work/backup-stand-in.sh"
chmod 0700 "$work/backup-stand-in.sh"
export CATALYST_BACKUP_CMD="$work/backup-stand-in.sh"
export CATALYST_IMAGE="$good"
compose up -d --wait db >/dev/null 2>&1
compose --profile provision run --rm provision-roles >/dev/null 2>&1
compose up -d --wait collect-static >/dev/null 2>&1 || true

# 1. The first release: migrate, deploy, start the proxy, smoke, receipt. The wrapper is not used yet.
op first
check "a backup that prints no receipt is refused, and nothing is migrated" bash -c \
  "! CATALYST_BACKUP_CMD=true '$adapters/predeploy.sh' '$good' 2>/dev/null && ! CATALYST_IMAGE='$good' docker compose --project-name '$project' -f deploy/staging/compose.yaml ps -a --format '{{.Service}}' | grep -q migrate"
binding="$("$adapters/predeploy.sh" "$good")"
check "the first release migrates after the (synthetic) pre-deploy backup, bound to its deploy" test -e "$binding"
check "the pre-deploy backup receipt carries the deploy id, the backup receipt's digest and its time" python3 -c '
import json, sys
b = json.load(open(sys.argv[1]))
assert b["deploy_id"] == "drill-first" and len(b["receipt_sha256"]) == 64 and b["backup_finished_at"] > 0, b
assert b["receipt"].endswith("/backups/drill-first.json") and b["backup_finished_at_utc"].endswith("+00:00"), b' "$binding"
check "the first release deploys" "$adapters/deploy.sh" "$good"
compose up -d --no-deps proxy >/dev/null 2>&1
unset CATALYST_IMAGE  # from here the adapters name the image from their own state, as on the host
check "the first release passes the smoke" "$adapters/smoke.sh"
check "the first release's receipt reads back as intended" "$adapters/receipt.sh"
check "capture reports the first release" test "$(serving)" = "$good"

# 2. A good release through the wrapper: promoted, and its receipt names the deploy and the bound backup.
next="$(derive good next "echo next > /app/RELEASE_MARK")"
op next
check "the predeploy step runs for the next release" "$adapters/predeploy.sh" "$next"
wrapper "$next"; rc=$?
check "the wrapper promotes a good release (exit 0)" test "$rc" = 0
check "the promoted release is serving" test "$(serving)" = "$next"
check "the promoted release's receipt reads back as intended" "$adapters/receipt.sh"
check "the deployment receipt names the deploy, the approved image and commit, and the bound backup" python3 -c '
import json, sys
r = json.load(open(sys.argv[1]))
assert r["deploy_id"] == "drill-next" and r["operation"] == "deploy" and r["approved_image"] == sys.argv[2], r
assert r["expected_commit"] == r["label_commit"] == sys.argv[3] and r["check_deploy"] == "pass", r
b = r["pre_deploy_backup"]
assert b["deploy_id"] == "drill-next" and len(b["sha256"]) == 64 and b["finished_at"] and b["receipt"].endswith("/drill-next.json"), b' \
  "$(latest_receipt)" "$next" "$commit"

# 3. A broken release: its smoke fails, and the wrapper reverts to the previous image through the same deploy hook.
broken="$(derive next broken "rm /app/config/health.py")"
op broken
"$adapters/predeploy.sh" "$broken" >/dev/null 2>&1 || true  # its backup is bound either way; the fault is for the smoke
wrapper "$broken"; rc=$?
check "the wrapper reverts a release whose smoke fails (exit 3)" test "$rc" = 3
check "the previous release is serving again" test "$(serving)" = "$next"
check "the reverted stack passes the smoke" "$adapters/smoke.sh"
check "the wrapper audited the revert" grep -q '"revert' "$work/audit.ndjson"
rm -f "$work/wrapper/HOLD"  # the wrapper holds after a revert, by design; the drill releases it for the next case

# 3b. A release whose worker and fetcher crash-loop: readiness alone would pass; the stability check reverts it.
crashing="$(derive next crashing "rm /app/workflow/management/commands/run_worker.py")"
op crashing
"$adapters/predeploy.sh" "$crashing" >/dev/null 2>&1 || true
wrapper "$crashing"; rc=$?
check "the wrapper reverts a release whose worker crash-loops (exit 3)" test "$rc" = 3
check "the previous release is serving after the crash-loop revert" test "$(serving)" = "$next"
rm -f "$work/wrapper/HOLD"

# 3c. A release whose migration fails at predeploy (so its schema is behind): deployed anyway, the smoke refuses it
# (readiness red, migrations pending), so it is reverted.
failing='from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("workflow", "0005_pause_resume_guard")]
    operations = [migrations.RunSQL("SELECT 1/0", migrations.RunSQL.noop)]
'
unmigrated="$(derive next unmigrated "$(put /app/workflow/migrations/0006_drill.py "$failing")")"
op unmigrated
check "a release whose migration fails is refused at predeploy" bash -c "! '$adapters/predeploy.sh' '$unmigrated' 2>/dev/null"
wrapper "$unmigrated"; rc=$?
check "the wrapper reverts a release whose migrations did not run (exit 3)" test "$rc" = 3
check "the previous release is serving after the unmigrated revert" test "$(serving)" = "$next"
rm -f "$work/wrapper/HOLD"

# 4. The deploy operation's gates (9kg.37; TEST-P6-10, 24): the serving identity must equal the approved artifact,
# and a deploy proceeds only with a successful pre-deploy backup bound to this operation.
approved="$(derive next approved "echo approved > /app/RELEASE_MARK")"
swapped="$(derive next swapped "echo swapped > /app/RELEASE_MARK")"
# 4a. The wrapper is given an image other than the one the operation approved and backed up for.
op approved
check "the predeploy step approves the intended image" "$adapters/predeploy.sh" "$approved"
wrapper "$swapped"; rc=$?
check "an image other than the approved one is refused through the wrapper's top-level path (exit 3)" test "$rc" = 3
check "the refusal names the identity mismatch" grep -q "neither deploy drill-approved's approved image nor its revert target" "$work/wrapper-drill-approved.err"
check "the stack is unchanged: the previous release still serves" test "$(serving)" = "$next"
check "nothing was promoted for the other image" bash -c "! grep -q \"smoke passed for $swapped\" '$work/audit.ndjson'"
rm -f "$work/wrapper/HOLD"
wrapper "$approved"; rc=$?
check "control: the approved image itself is promoted by the same operation (exit 0)" test "$rc" = 0
check "control: the approved image is serving, with its receipt" bash -c "[ \"\$('$adapters/capture.sh')\" = '$approved' ] && '$adapters/receipt.sh' >/dev/null"
# 4b. An image whose commit label is not the approved commit: refused before the backup and the migration.
op unapproved
check "an image whose commit label is not the approved commit is refused before any backup or migration" bash -c \
  "! CATALYST_EXPECTED_COMMIT=$(printf 'f%.0s' $(seq 40)) '$adapters/predeploy.sh' '$swapped' 2>'$work/unapproved.err' \
   && grep -q 'not the approved commit' '$work/unapproved.err' && [ ! -e '$work/backups/drill-unapproved.json' ] \
   && [ ! -e '$CATALYST_DEPLOY_STATE/operations/drill-unapproved' ]"
wrapper "$swapped"; rc=$?
check "with no operation started, the wrapper's deploy is refused (exit 3) and the stack is unchanged" \
  bash -c "[ $rc = 3 ] && grep -q 'no deploy operation drill-unapproved' '$work/wrapper-drill-unapproved.err' && [ \"\$('$adapters/capture.sh')\" = '$approved' ]"
rm -f "$work/wrapper/HOLD"
# 4c. A backup command that prints an older receipt's path: stale, so nothing is bound or migrated.
op stale
printf '{"synthetic": true, "older": true}\n' > "$work/backups/older.json"
touch -d '2 hours ago' "$work/backups/older.json"
check "a backup receipt older than the operation is refused (stale), and nothing is bound or migrated" bash -c \
  "! CATALYST_BACKUP_CMD='echo $work/backups/older.json' '$adapters/predeploy.sh' '$swapped' 2>'$work/stale.err' \
   && grep -q 'stale' '$work/stale.err' && [ ! -e '$CATALYST_DEPLOY_STATE/operations/drill-stale/pre-deploy-backup.json' ]"
wrapper "$swapped"; rc=$?
check "with no backup bound, the wrapper's deploy is refused (exit 3) and the stack is unchanged" \
  bash -c "[ $rc = 3 ] && grep -q 'not bound to deploy drill-stale' '$work/wrapper-drill-stale.err' && [ \"\$('$adapters/capture.sh')\" = '$approved' ]"
rm -f "$work/wrapper/HOLD"
# 4d. Another deploy's backup, bound a moment ago: fresh, but not this operation's.
op other
"$adapters/predeploy.sh" "$swapped" >/dev/null
cp "$CATALYST_DEPLOY_STATE/operations/drill-other/pre-deploy-backup.json" "$CATALYST_DEPLOY_STATE/operations/drill-stale/"
op stale
wrapper "$swapped"; rc=$?
check "a backup receipt from another deploy with a fresh timestamp is refused (exit 3) and the stack is unchanged" \
  bash -c "[ $rc = 3 ] && grep -q 'bound to another deploy (drill-other)' '$work/wrapper-drill-stale.err' && [ \"\$('$adapters/capture.sh')\" = '$approved' ]"
rm -f "$work/wrapper/HOLD"
op other
wrapper "$swapped"; rc=$?
check "control: the deploy whose backup it is promotes the same image (exit 0)" test "$rc" = 0 -a "$(serving)" = "$swapped"
check "the receipt of a promoted deploy is bound to that deploy's backup" python3 -c '
import json, sys
r = json.load(open(sys.argv[1]))
assert r["deploy_id"] == r["pre_deploy_backup"]["deploy_id"] == "drill-other" and r["operation"] == "deploy", r' "$("$adapters/receipt.sh")"

# 5. The rollback ladder's step 2 (9kg.38; TEST-P6-25): a release N+1 that expands the schema, then the image
# reverted to N on the expanded schema; a release with a forward-only (contract) migration whose revert is refused.
expand_migration='from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workflow", "0005_pause_resume_guard")]
    operations = [migrations.AddField(model_name="pendingaction", name="drill_note", field=models.TextField(null=True))]
'
contract_migration='from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("workflow", "0006_expand")]
    operations = [migrations.RemoveField(model_name="pendingaction", name="drill_note")]
'
n="$swapped"  # image N, serving
expand="$(derive swapped expand "$(put /app/workflow/migrations/0006_expand.py "$expand_migration")")"
check "an applicant is accepted on image N before the drill" submit n-before@example.test
before="$(applications)"
op expand
check "N+1's predeploy applies the expand migration" bash -c "'$adapters/predeploy.sh' '$expand' >/dev/null && [ \"\$(CATALYST_IMAGE='$expand' docker compose --project-name '$project' -f deploy/staging/compose.yaml run --rm --no-deps -T web python manage.py catalyst_release applied 2>/dev/null | grep -c 0006_expand)\" = 1 ]"
wrapper "$expand"; rc=$?
check "N+1 (expand) is promoted (exit 0)" test "$rc" = 0 -a "$(serving)" = "$expand"
check "the expanded column exists while N+1 serves" test "$(drill_column)" = 1
check "an applicant is accepted on N+1" submit n-plus-one@example.test
op revert-to-n
check "the revert to N is its own operation: backed up, nothing to migrate" "$adapters/predeploy.sh" "$n"
wrapper "$n"; rc=$?
check "the image is reverted to N on the expanded schema through the wrapper (exit 0)" test "$rc" = 0 -a "$(serving)" = "$n"
check "the reverted stack passes the smoke on the expanded schema" "$adapters/smoke.sh"
check "the schema was not rolled back: the column stays and the expand migration stays applied" \
  test "$(drill_column)" = 1 -a "$(applied_with "$expand" | grep -c 0006_expand)" = 1
check "the data is kept across the revert: both applicants are still there" test "$(applications)" = "$((before + 1))"
check "an applicant is accepted on N after the revert" submit n-after@example.test
# 5b. A release with a contract migration, marked forward-only: promoted, then a revert across it is refused.
contract="$(derive expand contract "$(put /app/workflow/migrations/0007_contract.py "$contract_migration") && sed -i 's/^FORWARD_ONLY: frozenset\\[str\\] = frozenset(.*)$/FORWARD_ONLY: frozenset[str] = frozenset({\"workflow.0007_contract\"})/' /app/config/release.py")"
op contract
check "the contract release's predeploy records it forward-only before migrating" bash -c \
  "'$adapters/predeploy.sh' '$contract' >/dev/null && grep -q 'workflow.0007_contract' '$CATALYST_DEPLOY_STATE/forward-only.json'"
wrapper "$contract"; rc=$?
check "the contract release is promoted (exit 0)" test "$rc" = 0 -a "$(serving)" = "$contract"
check "the contract migration removed the column" test "$(drill_column)" = 0
count="$(applications)"
op revert-across-contract
"$adapters/predeploy.sh" "$expand" >/dev/null
wrapper "$expand"; rc=$?
check "a revert across a forward-only migration is refused through the wrapper (exit 3)" test "$rc" = 3
check "the refusal names the migration and says restore" grep -q "workflow.0007_contract.*restore instead" "$work/wrapper-drill-revert-across-contract.err"
check "the image is untouched: the contract release still serves" test "$(serving)" = "$contract"
check "the data is untouched: the migration stays applied, the column stays gone, every applicant is there" \
  test "$(applied_with "$contract" | grep -c 0007_contract)" = 1 -a "$(drill_column)" = 0 -a "$(applications)" = "$count"
check "the forward-only list is recorded in the deploy state, not read from the serving image" \
  grep -q "workflow.0007_contract" "$CATALYST_DEPLOY_STATE/forward-only.json"
rm -f "$work/wrapper/HOLD"

# 6. A forward-only migration applied by the predeploy step of a release whose deploy then never happens: it was
# recorded before migrating, so switching to any image that does not know it is still refused.
staged_migration='from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("workflow", "0007_contract")]
    operations = [migrations.RunSQL("SELECT 1", migrations.RunSQL.noop)]
'
staged="$(derive contract staged "$(put /app/workflow/migrations/0008_staged.py "$staged_migration") && sed -i 's/^FORWARD_ONLY: frozenset\\[str\\] = frozenset(.*)$/FORWARD_ONLY: frozenset[str] = frozenset({\"workflow.0007_contract\", \"workflow.0008_staged\"})/' /app/config/release.py")"
op staged
check "the predeploy step applies a forward-only migration" "$adapters/predeploy.sh" "$staged"
out="$("$adapters/deploy.sh" "$contract" 2>&1)"; rc=$?
check "after an aborted deploy, an image without that migration is refused" bash -c "[ $rc != 0 ] && grep -q 'workflow.0008_staged' <<<'$out'"
check "nothing changed: the contract release is still serving" test "$(serving)" = "$contract"
check "a tag is refused as an image reference" bash -c "! '$adapters/deploy.sh' catalyst:latest 2>/dev/null"

# 6b. With a release serving, a lost forward-only record is refused, never read as "nothing is forward-only".
mv "$CATALYST_DEPLOY_STATE/forward-only.json" "$work/forward-only.saved"
out="$("$adapters/deploy.sh" "$contract" 2>&1)"; rc=$?
check "a missing forward-only record is refused while a release serves" bash -c "[ $rc != 0 ] && grep -q 'record is missing' <<<'$out'"
mv "$work/forward-only.saved" "$CATALYST_DEPLOY_STATE/forward-only.json"

# 7. The host check refuses a tarball with no attestation from this repository's main-branch workflow.
docker save "$(tag good)" -o "$work/unattested.tar"
check "an unattested image tarball is refused before it is loaded" bash -c \
  "! scripts/verify_image_attestation.sh '$work/unattested.tar' '$commit' 2>/dev/null"

exit "$fail"
