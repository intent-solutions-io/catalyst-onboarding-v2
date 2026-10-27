#!/usr/bin/env bash
# The stack's health check (026 section 7; 6B.12; the stack named by CATALYST_STACK_ENV, 9kg.78.1), run by a host timer every five minutes. It runs catalyst_health in
# the worker container (which holds the heartbeat), probes the public form from outside, and hands any finding to
# "$CATALYST_NOTIFY_CMD <level> <message>" (the host wires that to the estate alert floor; Buzz delivers high and
# urgent). A message is built from signal codes alone, each matching ^[a-z_]+\.[a-z_]+$, so no content of any kind
# can reach an alert (TEST-P6-38). Writes health.started before and health.ok after every completed run, for the
# dead-man sweep (sweep.sh). Exit 0 healthy, 1 findings were sent, 3 the notify command failed.
source "$(dirname "$0")/lib.sh"
: "${CATALYST_HEALTH_STATE:?a directory the timer owns}" "${CATALYST_NOTIFY_CMD:?the notify command}"
mkdir -p "$CATALYST_HEALTH_STATE"
touch "$CATALYST_HEALTH_STATE/health.started"
codes=()
worker="$(compose ps -q worker 2>/dev/null || true)"
if [ -z "$worker" ] || [ "$(docker inspect --format '{{.State.Running}}' "$worker" 2>/dev/null)" != true ]; then
  codes+=("health.worker_unreachable")  # no worker: no heartbeat, nothing claims work
else
  rc=0; report="$(docker exec "$worker" python manage.py catalyst_health 2>/dev/null)" || rc=$?
  case "$rc" in
    0) ;;
    1) found=()
       mapfile -t found < <(python3 -c 'import json,sys;[print(a) for a in json.loads(sys.argv[1]).get("anomalies",[])]' "$report" 2>/dev/null)
       # Exit 1 with no readable finding is a check that failed before it could report (a settings or import error,
       # an unknown command), never "healthy" (6B.12 review).
       [ "${#found[@]}" -gt 0 ] || found=("health.check_failed")
       codes+=("${found[@]}") ;;
    *) codes+=("health.check_failed") ;;
  esac
fi
# 026 section 7: the newest backup receipt must be under 26 hours old, and the newest *passing* restore-drill receipt
# under 35 days (6B.13): a failed drill never counts as a drill done (6B.13 review). Each is checked only when the
# host names its directory; an empty or missing directory counts as stale.
newest_age() {  # newest_age <dir> [required text]: seconds since the newest file (containing the text), or a large number
  local f
  for f in $(ls -t "$1" 2>/dev/null); do
    if [ -z "${2:-}" ] || grep -q "$2" "$1/$f" 2>/dev/null; then echo $(( $(date +%s) - $(stat -c %Y "$1/$f") )); return; fi
  done
  echo 999999999
}
if [ -n "${CATALYST_BACKUP_RECEIPTS:-}" ] && [ "$(newest_age "$CATALYST_BACKUP_RECEIPTS")" -gt $((26 * 3600)) ]; then
  codes+=("backup.stale")
fi
if [ -n "${CATALYST_DRILL_RECEIPTS:-}" ] && [ "$(newest_age "$CATALYST_DRILL_RECEIPTS" '"result": "pass"')" -gt $((35 * 86400)) ]; then
  codes+=("restore_drill.overdue")
fi
if [ -n "${CATALYST_SMOKE_URL:-}" ]; then
  code="$("${PROBE_ENV[@]}" curl "${PROBE_TLS[@]}" -s -o /dev/null -w '%{http_code}' --max-time 10 ${CATALYST_SMOKE_RESOLVE:+--resolve "$CATALYST_SMOKE_RESOLVE"} "$CATALYST_SMOKE_URL" || true)"
  [ "$code" = 200 ] || codes+=("probe.public_form_unreachable")
fi
safe=()
for c in "${codes[@]}"; do [[ "$c" =~ ^[a-z_]+\.[a-z_]+$ ]] && safe+=("$c") || safe+=("health.unrecognised_signal"); done
mapfile -t safe < <(printf '%s\n' "${safe[@]}" | sort -u | sed '/^$/d')
previous="$(cat "$CATALYST_HEALTH_STATE/last-findings" 2>/dev/null || true)"
status=0
if [ "${#safe[@]}" -gt 0 ]; then
  level=high
  # A worker that is gone, or alive but no longer making progress, and a check that cannot run, are urgent.
  for urgent in health.worker_unreachable health.check_failed worker.heartbeat_stale worker.heartbeat_missing; do
    [[ " ${safe[*]} " == *" $urgent "* ]] && level=urgent
  done
  if bash -c "$CATALYST_NOTIFY_CMD \"\$1\" \"\$2\"" _ "$level" "catalyst ${STACK}: ${safe[*]}"; then status=1; else status=3; fi
elif [ -n "$previous" ]; then
  bash -c "$CATALYST_NOTIFY_CMD \"\$1\" \"\$2\"" _ info "catalyst ${STACK}: recovered" || status=3
fi
# The findings are recorded only once they were handed over, so a failed recovery note is retried next run.
[ "$status" = 3 ] || printf '%s\n' "${safe[@]}" > "$CATALYST_HEALTH_STATE/last-findings"
touch "$CATALYST_HEALTH_STATE/health.ok"
exit "$status"
