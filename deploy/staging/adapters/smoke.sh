#!/usr/bin/env bash
# DW_SMOKE_CMD: fail-closed. The serving containers run exactly the recorded image; readiness answers through the
# web socket (polled, because a readiness answer may be up to 5 s old); and, when configured, the public form answers
# through the proxy. Any error, timeout or mismatch is unhealthy.
source "$(dirname "$0")/lib.sh"
expected="$(<"$POINTER")"
for service in web worker fetcher; do
  id="$(compose ps -q "$service")"; [ -n "$id" ] || fail "$service is not running"
  running="$(docker inspect --format '{{.Config.Image}}' "$id")"
  [ "$running" = "$expected" ] || fail "$service runs $running, not the recorded image"
  [ "$(docker inspect --format '{{.State.Running}}' "$id")" = true ] || fail "$service is not running"
done
ready=""
for _ in $(seq "${CATALYST_SMOKE_SECONDS:-30}"); do
  status="$(compose exec -T web python -c "import socket;s=socket.socket(socket.AF_UNIX);s.settimeout(5);s.connect('/run/catalyst/web.sock');s.sendall(b'GET /readyz HTTP/1.0\r\nHost: localhost\r\n\r\n');print(s.recv(256).decode().split(chr(13))[0])" 2>/dev/null || true)"
  if [[ "$status" == *" 200 "* ]]; then ready=1; break; fi
  sleep 1
done
[ -n "$ready" ] || fail "readiness did not answer 200 through the socket"
if [ -n "${CATALYST_SMOKE_URL:-}" ]; then
  code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 ${CATALYST_SMOKE_RESOLVE:+--resolve "$CATALYST_SMOKE_RESOLVE"} "$CATALYST_SMOKE_URL" || true)"
  [ "$code" = 200 ] || fail "the public form answered $code through the proxy"
fi
