#!/usr/bin/env bash
# The staging health check (026 section 7; 6B.12), run by a host timer every five minutes. It runs catalyst_health in
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
    1) mapfile -t found < <(python3 -c 'import json,sys;[print(a) for a in json.loads(sys.argv[1]).get("anomalies",[])]' "$report" 2>/dev/null)
       codes+=("${found[@]}") ;;
    *) codes+=("health.check_failed") ;;
  esac
fi
if [ -n "${CATALYST_SMOKE_URL:-}" ]; then
  code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 ${CATALYST_SMOKE_RESOLVE:+--resolve "$CATALYST_SMOKE_RESOLVE"} "$CATALYST_SMOKE_URL" || true)"
  [ "$code" = 200 ] || codes+=("probe.public_form_unreachable")
fi
safe=()
for c in "${codes[@]}"; do [[ "$c" =~ ^[a-z_]+\.[a-z_]+$ ]] && safe+=("$c") || safe+=("health.unrecognised_signal"); done
mapfile -t safe < <(printf '%s\n' "${safe[@]}" | sort -u | sed '/^$/d')
previous="$(cat "$CATALYST_HEALTH_STATE/last-findings" 2>/dev/null || true)"
printf '%s\n' "${safe[@]}" > "$CATALYST_HEALTH_STATE/last-findings"
status=0
if [ "${#safe[@]}" -gt 0 ]; then
  level=high
  [[ " ${safe[*]} " == *" health.worker_unreachable "* || " ${safe[*]} " == *" health.check_failed "* ]] && level=urgent
  bash -c "$CATALYST_NOTIFY_CMD \"\$1\" \"\$2\"" _ "$level" "catalyst staging: ${safe[*]}" || status=3
  [ "$status" = 3 ] || status=1
elif [ -n "$previous" ]; then
  bash -c "$CATALYST_NOTIFY_CMD \"\$1\" \"\$2\"" _ info "catalyst staging: recovered" || status=3
fi
touch "$CATALYST_HEALTH_STATE/health.ok"
exit "$status"
