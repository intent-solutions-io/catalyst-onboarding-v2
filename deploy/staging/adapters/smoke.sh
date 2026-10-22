#!/usr/bin/env bash
# DW_SMOKE_CMD, the promotion gate, fail-closed. In order: readiness answers 200 through the web socket (polled, since an
# answer may be CACHE_SECONDS old); after a settle period, web, worker and fetcher still run exactly the recorded image
# with no restart; the worker's and the fetcher's heartbeats are fresh; no migration is pending; the commit inside the
# image is its label's; and, when configured, the public form answers through the proxy (curl -k: staging's internal CA).
source "$(dirname "$0")/lib.sh"
expected="$(<"$POINTER")"
expected_id="$(docker image inspect --format '{{.Id}}' "$expected")" || fail "the recorded image is not on this host"
ready=""
for _ in $(seq "${CATALYST_SMOKE_SECONDS:-30}"); do
  status="$(compose exec -T web python -c "import socket;s=socket.socket(socket.AF_UNIX);s.settimeout(5);s.connect('/run/catalyst/web.sock');s.sendall(b'GET /readyz HTTP/1.0\r\nHost: localhost\r\n\r\n');print(s.recv(256).decode().split(chr(13))[0])" 2>/dev/null || true)"
  if [[ "$status" == *" 200 "* ]]; then ready=1; break; fi
  sleep 1
done
[ -n "$ready" ] || fail "readiness did not answer 200 through the socket"
sleep "${CATALYST_SMOKE_SETTLE:-5}"  # a crash-looping process restarts within this; one sample alone would miss it
for service in web worker fetcher; do
  id="$(compose ps -q "$service")"; [ -n "$id" ] || fail "$service is not running"
  state="$(docker inspect --format '{{.Image}} {{.State.Running}} {{.State.Restarting}} {{.RestartCount}}' "$id")"
  [ "$state" = "$expected_id true false 0" ] || fail "$service is not stable on the recorded image ($state)"
done
for service in worker fetcher; do
  age="$(compose exec -T "$service" python -c "import os,time;print(int(time.time()-os.stat(os.environ['CATALYST_WORKER_HEARTBEAT_FILE']).st_mtime))" 2>/dev/null || echo none)"
  [[ "$age" =~ ^[0-9]+$ ]] && [ "$age" -lt "${CATALYST_HEARTBEAT_STALE_SECONDS:-30}" ] || fail "$service has no fresh heartbeat ($age)"
done
facts="$(compose exec -T web python manage.py catalyst_release receipt)" || fail "cannot read the release facts"
label="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$expected")"
# The intended commit, when the deploy step names one (6B.11's force-command will always): a wrong but self-consistent
# image is refused. A revert names none, since it returns to whatever was recorded.
[ -z "${CATALYST_EXPECTED_COMMIT:-}" ] || [ "$label" = "$CATALYST_EXPECTED_COMMIT" ] || fail "not the intended commit"
python3 - "$facts" "$label" <<'PY' || fail "the release facts do not read back as intended"
import json, sys
facts, label = json.loads(sys.argv[1]), sys.argv[2]
problems = [p for p, bad in (("migrations pending", facts["migrations_pending"] != 0),
                             ("the image's commit differs from its label", facts["commit"] != label)) if bad]
print("; ".join(problems), file=sys.stderr)
sys.exit(1 if problems else 0)
PY
if [ -n "${CATALYST_SMOKE_URL:-}" ]; then
  code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 ${CATALYST_SMOKE_RESOLVE:+--resolve "$CATALYST_SMOKE_RESOLVE"} "$CATALYST_SMOKE_URL" || true)"
  [ "$code" = 200 ] || fail "the public form answered $code through the proxy"
fi
