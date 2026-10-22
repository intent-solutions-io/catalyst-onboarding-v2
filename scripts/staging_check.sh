#!/usr/bin/env bash
# Bring the generated staging stack up on this host with synthetic secrets, check what the running containers expose,
# and remove everything again (026 sections 4 and 5; 6B.5b; TEST-P6-04 and 11). Dev box only: it publishes on
# loopback addresses and uses throwaway values. Prints PASS or FAIL per check; exits non-zero on any FAIL.
#
#   scripts/staging_check.sh            # build, up, check, tear down
#   KEEP=1 scripts/staging_check.sh     # leave the stack running for 6B.11 work (tear down later with `down -v`)
set -euo pipefail
cd "$(dirname "$0")/.."

project="catalyst-staging-check-$$"
work="$(mktemp -d)"
secrets="$work/secrets"
fail=0
export CATALYST_IMAGE="catalyst-staging-check:$$" CATALYST_PUBLIC_HOST=catalyst.staging.test \
  CATALYST_STAFF_HOST=staff.staging.test CATALYST_PUBLIC_PUBLISH=127.0.0.1 CATALYST_STAFF_PUBLISH=127.0.0.2 \
  CATALYST_STAGING_SECRETS="$secrets" CATALYST_PUBLIC_PORT=18443 CATALYST_STAFF_PORT=18444  # the host proxy holds 443
compose=(docker compose --project-name "$project" -f deploy/staging/compose.yaml)

cleanup() {
  if [ "${KEEP:-}" != 1 ]; then
    "${compose[@]}" --profile provision down -v --remove-orphans >/dev/null 2>&1 || true
    docker image rm "$CATALYST_IMAGE" >/dev/null 2>&1 || true
    rm -rf "$work"
  else
    echo "kept: project $project, secrets $secrets"
  fi
}
trap cleanup EXIT

check() {  # check <name> <command...>
  local name="$1"; shift
  if "$@"; then echo "PASS $name"; else echo "FAIL $name"; fail=1; fi
}

# Synthetic, random, never reused: each value is also a sentinel the checks search for.
install -d -m 0700 "$secrets"
for name in secret_key verification_key admin_password owner_password app_password retention_password \
            backup_password fetcher_password; do
  printf 'synthetic-%s-%s' "$name" "$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')" > "$secrets/$name"
done
chmod 0444 "$secrets"/*  # read by uid 10001 and by postgres through bind mounts; the 0700 directory guards them

docker build --quiet --target staging --build-arg "CATALYST_COMMIT=$(git rev-parse HEAD)" -t "$CATALYST_IMAGE" . >/dev/null
"${compose[@]}" up -d --wait db >/dev/null
"${compose[@]}" --profile provision run --rm provision-roles >/dev/null
if ! "${compose[@]}" up -d --wait web worker fetcher proxy >/dev/null 2>&1; then
  for service in migrate web worker fetcher proxy; do  # the last lines say why; no secret is ever logged (checked below)
    echo "--- $service"; "${compose[@]}" logs --no-log-prefix "$service" 2>&1 | tail -4
  done
  echo "FAIL the stack did not come up"; exit 1
fi
sleep 3

values=()
for f in "$secrets"/*; do values+=("$(cat "$f")"); done
no_value_in() {  # no secret value appears in the text on stdin
  local text; text="$(cat)"
  for v in "${values[@]}"; do [[ "$text" == *"$v"* ]] && return 1; done
  return 0
}

inspect() { docker inspect --format "$2" "$("${compose[@]}" ps -q "$1")"; }
status() { docker exec "$("${compose[@]}" ps -q "$1")" sh -c "grep -E '^($2):' /proc/1/status | awk '{print \$2}' | tr '\n' ' '"; }

for service in web worker fetcher proxy db; do
  id="$("${compose[@]}" ps -q "$service")"
  check "$service is running" test -n "$id"
  check "$service: docker inspect shows no secret value" bash -c "docker inspect '$id' | { $(declare -f no_value_in); values=($(printf '%q ' "${values[@]}")); no_value_in; }"
  # db included: the image's POSTGRES_PASSWORD_FILE handling must not leave the value in the server's environment.
  check "$service: the process environment holds no secret value" bash -c "docker exec '$id' sh -c 'cat /proc/1/environ | tr \"\\0\" \"\\n\"; env' | { $(declare -f no_value_in); values=($(printf '%q ' "${values[@]}")); no_value_in; }"
  if [ "$service" != proxy ]; then  # the proxy's binary needs its file capability, which no-new-privileges blocks
    check "$service: no new privileges" test "$(status "$service" NoNewPrivs)" = "1 "
  fi
  if [ "$service" != db ]; then  # the official postgres image starts as root and drops to its own user itself
    check "$service: the root filesystem is read-only (from the engine)" test "$(inspect "$service" '{{.HostConfig.ReadonlyRootfs}}')" = true
  fi
  case "$service" in
    web|worker|fetcher) check "$service: runs as 10001 with no effective capability" test "$(status "$service" 'Uid|CapEff')" = "10001 0000000000000000 " ;;
    proxy) check "proxy: runs as 10001 with only the bind capability" test "$(status proxy 'Uid|CapEff')" = "10001 0000000000000400 " ;;
  esac
done
for service in web worker fetcher; do
  check "$service: CATALYST_ENV is staging and no GUNICORN_CMD_ARGS" bash -c "docker exec $("${compose[@]}" ps -q "$service") env | grep -qx CATALYST_ENV=staging && ! docker exec $("${compose[@]}" ps -q "$service") env | grep -q GUNICORN_CMD_ARGS"
  check "$service: /tmp and /dev/shm are tmpfs" bash -c "[ \"\$(docker exec $("${compose[@]}" ps -q "$service") sh -c 'grep -cE \" /(tmp|dev/shm) tmpfs \" /proc/mounts')\" = 2 ]"
done

mounted() { docker exec "$("${compose[@]}" ps -q "$1")" ls /run/secrets | sort | tr '\n' ' '; }
check "web mounts only its own secrets" test "$(mounted web)" = "db_password secret_key verification_key "
check "fetcher mounts only its own secrets" test "$(mounted fetcher)" = "db_password secret_key "
check "/run/catalyst is 0750 and the socket 0660, both group 10001" test "$(docker exec "$("${compose[@]}" ps -q web)" stat -c '%a %g' /run/catalyst /run/catalyst/web.sock | tr '\n' ' ')" = "750 10001 660 10001 "
check "the proxy cannot replace the socket" bash -c "! docker exec $("${compose[@]}" ps -q proxy) rm -f /run/catalyst/web.sock 2>/dev/null"
check "the mail sink is 0700" test "$(docker exec "$("${compose[@]}" ps -q worker)" stat -c '%a' /var/lib/catalyst/mail)" = 700

code() {  # code <host> <address> <port> <path>: the HTTP status, or 000 when there was no HTTP answer
  curl -sk -o /dev/null -w '%{http_code}' --resolve "$1:$3:$2" "https://$1:$3$4"
}
exits() {  # exits <code> <host> <address> <port> <path> [curl args]: curl's exit status is exactly <code>
  local want="$1" host="$2" address="$3" port="$4" path="$5"; shift 5
  curl -sk -o /dev/null --http1.1 --max-time 5 --resolve "$host:$port:$address" "$@" "https://$host:$port$path"
  [ $? = "$want" ]
}
# Over HTTP/1.1, curl exits 52 (empty reply) when the TLS handshake succeeded and the proxy then closed the connection
# unanswered (the catch-all's abort), 35 when the handshake itself was refused (no certificate for that name), and 7
# when nothing listens: so each "no answer" below is proven to be the catch-all, never a proxy that is down.
closed() { exits 52 "$@"; }
unanswered() { exits 52 "$@" || exits 35 "$@"; }  # closed after the handshake, or refused at it: never 7, never HTTP
for _ in $(seq 30); do  # the proxy issues its internal certificates on first use: wait for both sites, bounded
  [ "$(code catalyst.staging.test 127.0.0.1 18443 /request-access/)" = 200 ] \
    && [ "$(code staff.staging.test 127.0.0.2 18444 /staff/login/)" = 200 ] && break
  sleep 1
done
check "the public site serves the request form" test "$(code catalyst.staging.test 127.0.0.1 18443 /request-access/)" = 200
check "the public site refuses staff paths" test "$(code catalyst.staging.test 127.0.0.1 18443 /staff/)" = 404
check "the staff site answers on its private address" test "$(code staff.staging.test 127.0.0.2 18444 /staff/login/)" = 200
check "the staff name on the public port is closed unanswered" closed staff.staging.test 127.0.0.1 18443 /staff/login/
check "Host: localhost on the public listener is closed unanswered" closed catalyst.staging.test 127.0.0.1 18443 /readyz -H 'Host: localhost'
# The staff listener may or may not present the public name's certificate: either way there is no HTTP answer, and the
# staff site's own 200 above proves this listener is up.
check "the public name on the staff port gets no answer" unanswered catalyst.staging.test 127.0.0.2 18444 /request-access/
check "an unknown name is refused at the TLS handshake" exits 35 other.staging.test 127.0.0.1 18443 /request-access/
check "the staff port is not published on the public address" bash -c "! curl -sk -o /dev/null --max-time 3 https://127.0.0.1:18444/"
check "the public port is not published on the staff address" bash -c "! curl -sk -o /dev/null --max-time 3 https://127.0.0.2:18443/"
check "readiness answers through the socket" bash -c "docker exec $("${compose[@]}" ps -q web) python -c \"import socket;s=socket.socket(socket.AF_UNIX);s.connect('/run/catalyst/web.sock');s.sendall(b'GET /readyz HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n');print(s.recv(4096).decode())\" | head -1 | grep -q ' 200 '"

# A token in a request must reach no log (gunicorn's error log, Caddy's logs). The positive control first: the
# proxy's access log must show those very requests, with the token replaced.
sentinel="SENTINEL$(head -c 9 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
code catalyst.staging.test 127.0.0.1 18443 "/confirm/$sentinel/" >/dev/null
code catalyst.staging.test 127.0.0.1 18443 "/%63onfirm/$sentinel/" >/dev/null
curl -sk --max-time 5 --resolve catalyst.staging.test:18443:127.0.0.1 "https://catalyst.staging.test:18443/setup/$sentinel/" \
  -H 'Content-Length: 99999999' -X POST -o /dev/null || true
sleep 1
logs="$("${compose[@]}" logs --no-color 2>&1)"
check "the proxy logged the requests, redacted" bash -c "grep -q '/confirm/REDACTED' <<<\"\$1\" && grep -q '/%63onfirm/REDACTED' <<<\"\$1\"" _ "$logs"
check "no token in any container log" bash -c "[ -n \"\$1\" ] && ! grep -q '$sentinel' <<<\"\$1\"" _ "$logs"

exit "$fail"
