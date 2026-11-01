#!/usr/bin/env bash
# The alert drill (026 sections 7 and 11; 6B.12): the selected stack health check and dead-man sweep
# (deploy/staging/adapters/health.sh, sweep.sh) against a live synthetic stack on this host, with planted faults.
# Alerts go to a recording stub, so the drill reaches nobody. One real delivery through the estate alert floor is
# a separate, host-side step (026 section 16 records it). Dev box only; removes everything it created.
#
#   scripts/alert_drill.sh
#   CATALYST_STACK_ENV=production scripts/alert_drill.sh  # isolated production definition, synthetic inputs
#
# Cases: TEST-P6-17 (a stopped worker alerts; recovery clears), TEST-P6-19 (a planted unresolved hard bounce and a
# planted backlog alert), TEST-P6-20 (the dead man: a health timer that stopped, alone or with the worker, is caught by
# the sweep) and TEST-P6-38 (a planted sentinel never reaches an alert).
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
export CATALYST_STACK_ENV="${CATALYST_STACK_ENV:-staging}"
case "$CATALYST_STACK_ENV" in
  staging|production) ;;
  *) echo "CATALYST_STACK_ENV must be staging or production" >&2; exit 2 ;;
esac
# Both modes plant faults and remove resources. Refuse remote or production daemons before any write.
refuse() { echo "alert_drill: $1; refusing (dev box only)" >&2; exit 2; }
[ -z "${DOCKER_CONTEXT:-}" ] || [ "$DOCKER_CONTEXT" = default ] || refuse "DOCKER_CONTEXT names another daemon"
[ "$(docker context show 2>/dev/null)" = default ] || refuse "the current Docker context is not the default one"
case "${DOCKER_HOST:-unix:///var/run/docker.sock}" in
  unix:///var/run/docker.sock|unix:///run/docker.sock) ;;
  *) refuse "DOCKER_HOST is not the local socket" ;;
esac
[ "$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null)" = unix:///var/run/docker.sock ] \
  || refuse "the default context does not use the local socket"
[ "$(docker info --format '{{.Name}}' 2>/dev/null)" = "$(uname -n)" ] || refuse "the Docker daemon is not this host's"
production_containers="$(docker ps -aq --filter label=com.docker.compose.project=catalyst-production)" || refuse "cannot inspect containers"
production_volumes="$(docker volume ls -q --filter label=com.docker.compose.project=catalyst-production)" || refuse "cannot inspect volumes"
[ -z "$production_containers$production_volumes" ] || refuse "a catalyst-production project exists on this daemon"
# A retained production journal also marks this daemon as unsuitable for a destructive synthetic drill.
docker volume inspect catalyst-production-effects >/dev/null 2>&1 && refuse "the volume catalyst-production-effects exists"
project="catalyst-alert-drill-$$-$RANDOM"
work="$(mktemp -d)"
fail=0 created_effects=0
effects_volume="$project-effects"
export CATALYST_PUBLIC_HOST=catalyst.staging.test CATALYST_STAFF_HOST=staff.staging.test \
  CATALYST_PUBLIC_PUBLISH=127.0.0.1 CATALYST_STAFF_PUBLISH=127.0.0.2 CATALYST_PUBLIC_PORT=18443 \
  CATALYST_STAFF_PORT=18444 CATALYST_STAGING_SECRETS="$work/secrets" CATALYST_DEPLOY_STATE="$work/state" \
  CATALYST_COMPOSE_PROJECT="$project" CATALYST_COMPOSE_FILE="$PWD/deploy/$CATALYST_STACK_ENV/compose.yaml" \
  CATALYST_HEALTH_STATE="$work/health" CATALYST_IMAGE="catalyst-alert-drill:$$" \
  CATALYST_SMOKE_URL="https://catalyst.staging.test:18443/request-access/" \
  CATALYST_SMOKE_RESOLVE="catalyst.staging.test:18443:127.0.0.1"
export CATALYST_NOTIFY_CMD="printf '%s %s\n' >> $work/alerts.log"  # the recording stub
compose() { docker compose --project-name "$project" -f "$CATALYST_COMPOSE_FILE" "$@"; }
ours() {
  [ "$(docker volume inspect --format '{{index .Labels "catalyst.alert-drill"}}' "$effects_volume" 2>/dev/null)" = "$project" ]
}
cleanup() {
  compose --profile provision --profile ops down -v --remove-orphans >/dev/null 2>&1
  [ "$created_effects" = 1 ] && ours && docker volume rm "$effects_volume" >/dev/null 2>&1
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

install -d -m 0700 "$work/secrets" "$work/state" "$work/health" "$work/ship"
# Never inherit live receipt paths or trust overrides into this isolated drill.
unset CATALYST_BACKUP_RECEIPTS CATALYST_DRILL_RECEIPTS CATALYST_PROBE_CA_FILE
secret_names="secret_key verification_key admin_password owner_password app_password retention_password backup_password fetcher_password"
if [ "$CATALYST_STACK_ENV" = production ]; then
  CATALYST_MAIL_USER_SHA256="$(printf '%s' v2-check@example.test | sha256sum | cut -d' ' -f1)" || exit 1
  CATALYST_MAIL_DENIED_USER_SHA256="$(printf '%s' legacy-check@example.test | sha256sum | cut -d' ' -f1)" || exit 1
  export CATALYST_MAIL_USER_SHA256 CATALYST_MAIL_DENIED_USER_SHA256
  export CATALYST_PRODUCTION_SECRETS="$work/secrets" CATALYST_CHALLENGE_LIFETIME_SECONDS=3600 \
    CATALYST_MAIL_ALLOWED_HOSTS=mail.production-check.test CATALYST_MAIL_HOST=mail.production-check.test \
    CATALYST_MAIL_PORT=587 CATALYST_MAIL_USER=v2-check@example.test CATALYST_MAIL_SENT_FOLDER=Sent \
    CATALYST_MAIL_TRUSTED_AUTHSERV_ID=mail.production-check.test \
    CATALYST_JOURNAL_SHIP_LAG_SECONDS=900 CATALYST_FROM_EMAIL=onboarding@catalyst.production-check.test \
    CATALYST_HEALTH_AGED_WAITS_PAGE=replies_awaiting_processing CATALYST_HEALTH_PENDING_AGE_SECONDS=3600 \
    CATALYST_EGRESS_DENY_FILE="$PWD/deploy/staging/egress-deny" CATALYST_JOURNAL_SHIP_DIR="$work/ship"
  secret_names="$secret_names mail_password"
  # Preserve external-volume semantics while giving this run its own name and ownership label.
  compose --profile provision --profile ops config --format json > "$work/rendered.json" || exit 1
  python3 - "$work/rendered.json" "$work/compose.json" "$effects_volume" <<'PYCODE' || exit 1
import json, sys
from pathlib import Path
config = json.loads(Path(sys.argv[1]).read_text())
config["volumes"]["catalyst-effects"]["name"] = sys.argv[3]
Path(sys.argv[2]).write_text(json.dumps(config))
PYCODE
  export CATALYST_COMPOSE_FILE="$work/compose.json"
  docker volume inspect "$effects_volume" >/dev/null 2>&1 && refuse "the drill journal already exists"
  docker volume create --label "catalyst.alert-drill=$project" "$effects_volume" >/dev/null || exit 1
  ours || refuse "the journal is not this run's"
  created_effects=1
fi
for name in $secret_names; do
  printf 'synthetic-%s-%s' "$name" "$(head -c 96 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 64)" > "$work/secrets/$name"
done
: > "$work/secrets/verification_fallback_keys"
chmod 0444 "$work/secrets"/*
docker build -q --target "$CATALYST_STACK_ENV" --build-arg "CATALYST_COMMIT=$(git rev-parse HEAD)" -t "$CATALYST_IMAGE" . >/dev/null || exit 1
compose up -d --wait db > "$work/db-start.log" 2>&1 || { cat "$work/db-start.log"; echo "FAIL database startup"; exit 1; }
compose --profile provision run --rm provision-roles > "$work/provision.log" 2>&1 || { cat "$work/provision.log"; echo "FAIL database role provisioning"; exit 1; }
compose up -d --wait web worker fetcher egress proxy >/dev/null 2>&1 || { echo "FAIL the stack did not come up"; exit 1; }
sleep 3

if [ "$CATALYST_STACK_ENV" = production ]; then
  # Trust this isolated proxy's CA; production adapters must never gain curl -k.
  compose exec -T proxy cat /data/caddy/pki/authorities/local/root.crt > "$work/proxy-ca.crt" || { echo "FAIL reading the isolated proxy CA"; exit 1; }
  export CATALYST_PROBE_CA_FILE="$work/proxy-ca.crt"
  code="$(env -u CURL_CA_BUNDLE -u SSL_CERT_FILE -u SSL_CERT_DIR curl -q --cacert "$CATALYST_PROBE_CA_FILE" \
    -sS --max-time 10 --resolve "$CATALYST_SMOKE_RESOLVE" -o /dev/null -w '%{http_code}' "$CATALYST_SMOKE_URL")" || exit 1
  check "production TLS verifies and the unapproved form answers 503" test "$code" = 503
  # The unapproved intake correctly answers 503. Keep that finding visible, alongside policy findings.
  expected_baseline="$(compose exec -T worker python manage.py catalyst_health 2>/dev/null)"
  baseline_codes="$(python3 -c 'import json,sys; print(" ".join(sorted(json.loads(sys.argv[1])["anomalies"])))' "$expected_baseline")" || exit 1
  # Fixed allowlist: a broken worker, database or journal must never become an accepted baseline.
  read -r -a baseline <<< "$baseline_codes"
  for code in "${baseline[@]}"; do
    case "$code" in
      decision.decline_notice_unapproved|intake.data_notice_unapproved|intake.registry_provisional|intake.verification_template_unapproved|intake.receipt_template_unapproved|backup.registry_blocked|journal.effect_journal_never_shipped) ;;
      *) echo "FAIL unexpected production baseline: $code"; exit 1 ;;
    esac
  done
  expected_alert="high catalyst production: $(printf '%s\n' "${baseline[@]}" probe.public_form_unreachable | sort -u | paste -sd ' ' -)"
  check "production reports its standing policy and withheld-form findings" test "$(health)" = 1
  check "production baseline contains exactly the expected findings" test "$(cat "$work/alerts.log")" = "$expected_alert"
  echo "NOT RUN live production alert delivery, timer installation and off-host dead-man: this is an isolated local drill"
else
  expected_alert=""
  check "a healthy stack sends no alert" test "$(health)" = 0
fi
check "and leaves the dead man's marker" test -e "$work/health/health.ok"

# TEST-P6-17: a stopped worker alerts at once; recovery clears it with one recovery note.
compose stop worker >/dev/null 2>&1
rc="$(health)"
check "TEST-P6-17 a stopped worker raises an alert" test "$rc" = 1
check "TEST-P6-17 the alert names the worker and is urgent" grep -q "^urgent catalyst $CATALYST_STACK_ENV: .*health.worker_unreachable" "$work/alerts.log"
compose start worker >/dev/null 2>&1; sleep 8
rc="$(health)"
if [ "$CATALYST_STACK_ENV" = production ]; then
  check "TEST-P6-17 worker recovery preserves standing production findings" test "$rc" = 1
  check "TEST-P6-17 worker recovery returns to the exact baseline" test "$(cat "$work/alerts.log")" = "$expected_alert"
else
  check "TEST-P6-17 recovery sends no alert" test "$rc" = 0
  check "TEST-P6-17 recovery sends exactly one recovery note" test "$(cat "$work/alerts.log")" = "info catalyst staging: recovered"
fi

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
  "sed 's/^[a-z]* catalyst $CATALYST_STACK_ENV: //' '$work/alerts.log' | tr ' ' '\n' | grep -v '^\$' | grep -vqE '^[a-z_]+\.[a-z_]+\$' && exit 1 || exit 0"

# TEST-P6-20: the dead man. A health timer that has not completed for longer than the limit is caught by the sweep,
# whether the stack is up or the worker is stopped too.
check "TEST-P6-20 a fresh marker raises nothing" bash -c "CATALYST_HEALTH_STALE_SECONDS=900 deploy/staging/adapters/sweep.sh"
touch -d '20 minutes ago' "$work/health/health.ok"; : > "$work/alerts.log"
check "TEST-P6-20 a stopped health timer is caught by the sweep" bash -c "! deploy/staging/adapters/sweep.sh && grep -q '^urgent catalyst $CATALYST_STACK_ENV: health.check_stale' '$work/alerts.log'"
compose stop worker >/dev/null 2>&1; : > "$work/alerts.log"
check "TEST-P6-20 the timer and the worker stopped together are caught by the sweep" bash -c "! deploy/staging/adapters/sweep.sh && grep -q 'health.check_stale' '$work/alerts.log'"
rm -f "$work/health/health.ok"; : > "$work/alerts.log"
check "TEST-P6-20 a health check that never completed at all is caught" bash -c "! deploy/staging/adapters/sweep.sh && grep -q 'health.check_stale' '$work/alerts.log'"

exit "$fail"
