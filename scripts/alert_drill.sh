#!/usr/bin/env bash
# The alert drill (026 sections 7 and 11; 6B.12): the staging health check and dead-man sweep
# (deploy/staging/adapters/health.sh, sweep.sh) against a live synthetic stack on this host, with planted faults.
# Alerts go to a recording stub, so the drill reaches nobody. One real delivery through the estate alert floor is
# a separate, host-side step (026 section 16 records it). Dev box only; removes everything it created.
#
#   scripts/alert_drill.sh
#
# Cases: TEST-P6-17 (a stopped worker alerts; recovery clears), TEST-P6-19 (a planted unresolved hard bounce and a
# planted backlog alert), TEST-P6-20 (the dead man: a health timer that stopped, alone or with the worker, is caught by
# the sweep) and TEST-P6-38 (a planted sentinel never reaches an alert).
set -uo pipefail
cd "$(dirname "$0")/.."
export CATALYST_STACK_ENV=staging  # the adapters require it (9kg.78.1); this drill runs the staging stack only
project="catalyst-alert-drill-$$"
work="$(mktemp -d)"
fail=0
export CATALYST_PUBLIC_HOST=catalyst.staging.test CATALYST_STAFF_HOST=staff.staging.test \
  CATALYST_PUBLIC_PUBLISH=127.0.0.1 CATALYST_STAFF_PUBLISH=127.0.0.2 CATALYST_PUBLIC_PORT=18443 \
  CATALYST_STAFF_PORT=18444 CATALYST_STAGING_SECRETS="$work/secrets" CATALYST_DEPLOY_STATE="$work/state" \
  CATALYST_COMPOSE_PROJECT="$project" CATALYST_COMPOSE_FILE="$PWD/deploy/staging/compose.yaml" \
  CATALYST_HEALTH_STATE="$work/health" CATALYST_IMAGE="catalyst-alert-drill:$$" \
  CATALYST_SMOKE_URL="https://catalyst.staging.test:18443/request-access/" \
  CATALYST_SMOKE_RESOLVE="catalyst.staging.test:18443:127.0.0.1"
export CATALYST_NOTIFY_CMD="printf '%s %s\n' >> $work/alerts.log"  # the recording stub
compose() { docker compose --project-name "$project" -f deploy/staging/compose.yaml "$@"; }
cleanup() {
  compose --profile provision down -v --remove-orphans >/dev/null 2>&1
  docker image rm "$CATALYST_IMAGE" >/dev/null 2>&1
  rm -rf "$work"
}
trap cleanup EXIT
check() { local name="$1"; shift; if "$@"; then echo "PASS $name"; else echo "FAIL $name"; fail=1; fi; }
health() { : > "$work/alerts.log"; deploy/staging/adapters/health.sh >/dev/null 2>&1; echo $?; }
alerted() { grep -q -- "$1" "$work/alerts.log"; }
owner_sql() {  # owner_sql <python>: run Django ORM code as the owner role in a one-off migrate container
  compose run --rm --no-deps -T migrate python manage.py shell -c "$1" >/dev/null 2>&1
}

install -d -m 0700 "$work/secrets" "$work/state" "$work/health"
for name in secret_key verification_key admin_password owner_password app_password retention_password \
            backup_password fetcher_password; do
  printf 'synthetic-%s-%s' "$name" "$(head -c 96 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 64)" > "$work/secrets/$name"
done
: > "$work/secrets/verification_fallback_keys"
chmod 0444 "$work/secrets"/*
docker build -q --target staging --build-arg "CATALYST_COMMIT=$(git rev-parse HEAD)" -t "$CATALYST_IMAGE" . >/dev/null || exit 1
compose up -d --wait db >/dev/null 2>&1
compose --profile provision run --rm provision-roles >/dev/null 2>&1
compose up -d --wait web worker fetcher egress proxy >/dev/null 2>&1 || { echo "FAIL the stack did not come up"; exit 1; }
sleep 3

check "a healthy stack sends no alert" test "$(health)" = 0
check "and leaves the dead man's marker" test -e "$work/health/health.ok"

# TEST-P6-17: a stopped worker alerts at once; recovery clears it with one recovery note.
compose stop worker >/dev/null 2>&1
rc="$(health)"
check "TEST-P6-17 a stopped worker raises an alert" test "$rc" = 1
check "TEST-P6-17 the alert names the worker and is urgent" grep -q '^urgent catalyst staging: .*health.worker_unreachable' "$work/alerts.log"
compose start worker >/dev/null 2>&1; sleep 8
rc="$(health)"
check "TEST-P6-17 recovery sends no alert" test "$rc" = 0
check "TEST-P6-17 recovery sends exactly one recovery note" test "$(cat "$work/alerts.log")" = "info catalyst staging: recovered"

# TEST-P6-19, 38: planted faults (an unresolved hard bounce past its target, an overdue backlog), one of them carrying
# a sentinel in its stored data, raise their signals; the alert carries signal codes and nothing else.
sentinel="SENTINEL$(head -c 9 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
owner_sql "
import uuid; from datetime import timedelta; from django.utils import timezone
from correspondence.models import StaffItem; from workflow.models import PendingAction
item = StaffItem.objects.create(reason_code='hard_bounce', dedupe_key='drill:$sentinel')
StaffItem.objects.filter(pk=item.pk).update(opened_at=timezone.now() - timedelta(days=2))
PendingAction.objects.create(kind='drill_never_claimed', subject_type='application', subject_id=uuid.uuid4(),
                             input_ref='$sentinel', idempotency_key='drill:$sentinel')
PendingAction.objects.filter(idempotency_key='drill:$sentinel').update(due_at=timezone.now() - timedelta(hours=2))
"
check "TEST-P6-19 the planted faults raise an alert" test "$(health)" = 1
check "TEST-P6-19 the unresolved hard bounce is named" alerted "bounces.hard_bounce_unresolved"
check "TEST-P6-19 the overdue backlog is named" alerted "queue.backlog"
check "TEST-P6-38 the sentinel planted in the data never reaches the alert" bash -c "! grep -q '$sentinel' '$work/alerts.log'"
check "TEST-P6-38 every word of the alert after its prefix is a signal code" bash -c \
  "sed 's/^[a-z]* catalyst staging: //' '$work/alerts.log' | tr ' ' '\n' | grep -v '^\$' | grep -vqE '^[a-z_]+\.[a-z_]+\$' && exit 1 || exit 0"

# TEST-P6-20: the dead man. A health timer that has not completed for longer than the limit is caught by the sweep,
# whether the stack is up or the worker is stopped too.
check "TEST-P6-20 a fresh marker raises nothing" bash -c "CATALYST_HEALTH_STALE_SECONDS=900 deploy/staging/adapters/sweep.sh"
touch -d '20 minutes ago' "$work/health/health.ok"; : > "$work/alerts.log"
check "TEST-P6-20 a stopped health timer is caught by the sweep" bash -c "! deploy/staging/adapters/sweep.sh && grep -q '^urgent catalyst staging: health.check_stale' '$work/alerts.log'"
compose stop worker >/dev/null 2>&1; : > "$work/alerts.log"
check "TEST-P6-20 the timer and the worker stopped together are caught by the sweep" bash -c "! deploy/staging/adapters/sweep.sh && grep -q 'health.check_stale' '$work/alerts.log'"
rm -f "$work/health/health.ok"; : > "$work/alerts.log"
check "TEST-P6-20 a health check that never completed at all is caught" bash -c "! deploy/staging/adapters/sweep.sh && grep -q 'health.check_stale' '$work/alerts.log'"

exit "$fail"
