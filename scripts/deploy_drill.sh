#!/usr/bin/env bash
# The deploy drill (026 sections 4 and 9; 6B.10): the estate deploy wrapper drives the Catalyst adapters
# (deploy/staging/adapters) against the generated staging stack on this host, with synthetic secrets, then removes
# everything. Dev box only.
#
#   DW_WRAPPER=<path to the estate deploy-wrapper.sh> scripts/deploy_drill.sh
#
# Cases: a first release (outside the wrapper: it needs a known-good to revert to); a good release promoted with a
# receipt; a broken release whose smoke fails, reverted automatically to the previous image; and a revert refused
# because a forward-only migration is applied that the older image does not know. Prints PASS or FAIL per case.
set -uo pipefail
cd "$(dirname "$0")/.."
: "${DW_WRAPPER:?the path of the estate deploy wrapper}"

project="catalyst-deploy-drill-$$"
work="$(mktemp -d)"
fail=0
export CATALYST_PUBLIC_HOST=catalyst.staging.test CATALYST_STAFF_HOST=staff.staging.test \
  CATALYST_PUBLIC_PUBLISH=127.0.0.1 CATALYST_STAFF_PUBLISH=127.0.0.2 CATALYST_PUBLIC_PORT=18443 \
  CATALYST_STAFF_PORT=18444 CATALYST_STAGING_SECRETS="$work/secrets" CATALYST_DEPLOY_STATE="$work/state" \
  CATALYST_COMPOSE_PROJECT="$project" CATALYST_COMPOSE_FILE="$PWD/deploy/staging/compose.yaml" \
  CATALYST_SMOKE_URL="https://catalyst.staging.test:18443/request-access/" \
  CATALYST_SMOKE_RESOLVE="catalyst.staging.test:18443:127.0.0.1" CATALYST_SMOKE_SECONDS=20 \
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

install -d -m 0700 "$work/secrets" "$work/state" "$work/wrapper"
for name in secret_key verification_key admin_password owner_password app_password retention_password \
            backup_password fetcher_password; do
  # 64 random characters: Django's deploy check (security.W009) wants a key of at least 50.
  printf 'synthetic-%s-%s' "$name" "$(head -c 96 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 64)" > "$work/secrets/$name"
done
chmod 0444 "$work/secrets"/*

good="$(docker build -q --target staging --build-arg "CATALYST_COMMIT=$(git rev-parse HEAD)" -t "$(tag good)" .)" || exit 1
images+=("$good")
export CATALYST_BACKUP_CMD="echo synthetic-staging-drill-no-backup"  # staging data is synthetic; 6B.11 wires the job
export CATALYST_IMAGE="$good"
compose up -d --wait db >/dev/null 2>&1
compose --profile provision run --rm provision-roles >/dev/null 2>&1
compose up -d --wait collect-static >/dev/null 2>&1 || true

# 1. The first release: migrate, deploy, start the proxy, smoke, receipt. The wrapper is not used yet.
check "the first release migrates after the (synthetic) pre-deploy backup" "$adapters/predeploy.sh" "$good"
check "the first release deploys" "$adapters/deploy.sh" "$good"
compose up -d --no-deps proxy >/dev/null 2>&1
check "the first release passes the smoke" "$adapters/smoke.sh"
check "the first release's receipt reads back as intended" "$adapters/receipt.sh"
check "capture reports the first release" test "$("$adapters/capture.sh")" = "$good"

# 2. A good release through the wrapper: promoted.
next="$(derive good next "echo next > /app/RELEASE_MARK")"
check "the predeploy step runs for the next release" "$adapters/predeploy.sh" "$next"
"$DW_WRAPPER" "$next" >/dev/null 2>&1; rc=$?
check "the wrapper promotes a good release (exit 0)" test "$rc" = 0
check "the promoted release is serving" test "$("$adapters/capture.sh")" = "$next"
check "the promoted release's receipt reads back as intended" "$adapters/receipt.sh"

# 3. A broken release: its smoke fails, and the wrapper reverts to the previous image through the same deploy hook.
broken="$(derive next broken "rm /app/config/health.py")"
"$DW_WRAPPER" "$broken" >/dev/null 2>&1; rc=$?
check "the wrapper reverts a release whose smoke fails (exit 3)" test "$rc" = 3
check "the previous release is serving again" test "$("$adapters/capture.sh")" = "$next"
check "the reverted stack passes the smoke" "$adapters/smoke.sh"
check "the wrapper audited the revert" grep -q '"revert' "$work/audit.ndjson"
rm -f "$work/wrapper/HOLD"  # the wrapper holds after a revert, by design; the drill releases it for the next case

# 4. A forward-only migration applied: switching to an image that does not know it is refused before anything changes.
fwd="$(derive next fwd "sed -i 's/^FORWARD_ONLY: frozenset\[str\] = frozenset()/FORWARD_ONLY: frozenset[str] = frozenset({\"workflow.0004_restore_hold_protection\"})/' /app/config/release.py")"
older="$(derive next older "rm /app/workflow/migrations/0004_restore_hold_protection.py")"
check "the release that marks a migration forward-only deploys" "$adapters/deploy.sh" "$fwd"
out="$("$adapters/deploy.sh" "$older" 2>&1)"; rc=$?
check "switching to an image that lacks an applied forward-only migration is refused" test "$rc" != 0
check "the refusal names the migration and says restore" grep -q "workflow.0004_restore_hold_protection.*restore instead" <<<"$out"
check "nothing changed: the forward-only release is still serving" test "$("$adapters/capture.sh")" = "$fwd"
check "a tag is refused as an image reference" bash -c "! '$adapters/deploy.sh' catalyst:latest 2>/dev/null"

exit "$fail"
