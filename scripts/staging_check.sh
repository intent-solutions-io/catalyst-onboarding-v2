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
  printf 'synthetic-%s-%s' "$name" "$(head -c 96 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 64)" > "$secrets/$name"
done
: > "${CATALYST_STAGING_SECRETS}/verification_fallback_keys"  # empty: no rotation under way (027)
chmod 0444 "$secrets"/*  # read by uid 10001 and by postgres through bind mounts; the 0700 directory guards them

docker build --quiet --target staging --build-arg "CATALYST_COMMIT=$(git rev-parse HEAD)" -t "$CATALYST_IMAGE" . >/dev/null
"${compose[@]}" up -d --wait db >/dev/null
"${compose[@]}" --profile provision run --rm provision-roles >/dev/null
if ! "${compose[@]}" up -d --wait web worker fetcher egress proxy >/dev/null 2>&1; then
  for service in migrate web worker fetcher egress proxy; do  # the last lines say why; no secret is ever logged (checked below)
    echo "--- $service"; "${compose[@]}" logs --no-log-prefix "$service" 2>&1 | tail -4
  done
  echo "FAIL the stack did not come up"; exit 1
fi
sleep 3

values=()
for f in "$secrets"/*; do [ -s "$f" ] && values+=("$(cat "$f")"); done  # an empty file is no sentinel
no_value_in() {  # no secret value appears in the text on stdin
  local text; text="$(cat)"
  for v in "${values[@]}"; do [[ "$text" == *"$v"* ]] && return 1; done
  return 0
}

inspect() { docker inspect --format "$2" "$("${compose[@]}" ps -q "$1")"; }
status() { docker exec "$("${compose[@]}" ps -q "$1")" sh -c "grep -E '^($2):' /proc/1/status | awk '{print \$2}' | tr '\n' ' '"; }

for service in web worker fetcher egress proxy db; do
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
    web|worker|fetcher|egress) check "$service: runs as 10001 with no effective capability" test "$(status "$service" 'Uid|CapEff')" = "10001 0000000000000000 " ;;
    proxy) check "proxy: runs as 10001 with only the bind capability" test "$(status proxy 'Uid|CapEff')" = "10001 0000000000000400 " ;;
  esac
done
for service in web worker fetcher; do
  check "$service: CATALYST_ENV is staging and no GUNICORN_CMD_ARGS" bash -c "docker exec $("${compose[@]}" ps -q "$service") env | grep -qx CATALYST_ENV=staging && ! docker exec $("${compose[@]}" ps -q "$service") env | grep -q GUNICORN_CMD_ARGS"
  check "$service: /tmp and /dev/shm are tmpfs" bash -c "[ \"\$(docker exec $("${compose[@]}" ps -q "$service") sh -c 'grep -cE \" /(tmp|dev/shm) tmpfs \" /proc/mounts')\" = 2 ]"
done

mounted() { docker exec "$("${compose[@]}" ps -q "$1")" ls /run/secrets | sort | tr '\n' ' '; }
check "web mounts only its own secrets" test "$(mounted web)" = "db_password secret_key verification_fallback_keys verification_key "
check "fetcher mounts only its own secrets" test "$(mounted fetcher)" = "db_password secret_key "
check "/run/catalyst is 0750 and the socket 0660, both group 10001" test "$(docker exec "$("${compose[@]}" ps -q web)" stat -c '%a %g' /run/catalyst /run/catalyst/web.sock | tr '\n' ' ')" = "750 10001 660 10001 "
check "the proxy cannot replace the socket" bash -c "! docker exec $("${compose[@]}" ps -q proxy) rm -f /run/catalyst/web.sock 2>/dev/null && docker exec $("${compose[@]}" ps -q web) test -S /run/catalyst/web.sock"
check "the mail sink is 0700" test "$(docker exec "$("${compose[@]}" ps -q worker)" stat -c '%a' /var/lib/catalyst/mail)" = 700

code() {  # code <host> <address> <port> <path>: the HTTP status, or 000 when there was no HTTP answer
  curl -sk --path-as-is -o /dev/null -w '%{http_code}' --resolve "$1:$3:$2" "https://$1:$3$4"
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

# --- GATE-STAGING live cases (6B.11; 026 section 11) ------------------------------------------------------------
web="$("${compose[@]}" ps -q web)"
socket_get() {  # socket_get <path> [host]: the HTTP status straight from Django through the web socket (no proxy),
  # with the forwarded scheme the proxy always sets; the host defaults to the local health name.
  docker exec "$web" python -c "import socket,sys;s=socket.socket(socket.AF_UNIX);s.settimeout(5);s.connect('/run/catalyst/web.sock');s.sendall(('GET '+sys.argv[1]+' HTTP/1.0\r\nHost: '+sys.argv[2]+'\r\nX-Forwarded-Proto: https\r\n\r\n').encode());print(s.recv(64).decode().split(' ')[1])" "$1" "${2:-localhost}" 2>/dev/null || echo none
}
owner_run() { "${compose[@]}" run --rm --no-deps -T "$@" 2>/dev/null; }  # the migrate service: the owner role

check "TEST-P6-02 check --deploy is clean under staging settings" \
  docker exec "$web" python manage.py check --deploy --fail-level WARNING
check "TEST-P6-05 migrate is idempotent (a second run applies nothing)" \
  bash -c "\"\$@\" | grep -q 'No migrations to apply'" _ "${compose[@]}" run --rm --no-deps -T migrate python manage.py migrate --noinput
check "TEST-P6-06 role provisioning is idempotent and reads its roles back" \
  bash -c "\"\$@\" | grep -q '5 roles ready'" _ "${compose[@]}" --profile provision run --rm -T provision-roles

# TEST-P6-07: liveness needs no database; readiness fails while it is down and recovers after.
"${compose[@]}" stop db >/dev/null 2>&1
sleep 6  # past the readiness cache
check "TEST-P6-07 with the database down, liveness answers 200" test "$(socket_get /healthz)" = 200
check "TEST-P6-07 with the database down, readiness answers 503" test "$(socket_get /readyz)" = 503
"${compose[@]}" up -d --wait db >/dev/null 2>&1  # back, and healthy by its own check
for _ in $(seq 60); do [ "$(socket_get /readyz)" = 200 ] && break; sleep 1; done  # at most a minute (3-5 s seen)
# Each web worker caches its readiness answer for up to 5 s, so one may still hold the outage's 503: wait that out,
# then every answer must be 200.
sleep 6
recovered() { for _ in 1 2 3; do [ "$(socket_get /readyz)" = 200 ] || return 1; done; }
check "TEST-P6-07 readiness recovers when the database returns (three answers in a row)" recovered

# TEST-P6-12: path variants of staff, admin and health paths never pass the public site. The last two match the
# applicant pattern, so the proxy forwards them and Django refuses them.
check "TEST-P6-12 control: a listed applicant path is forwarded" test "$(code catalyst.staging.test 127.0.0.1 18443 /request-access/)" = 200
for path in /STAFF/ //staff/ /%73taff/ /staff/../staff/ /admin/ /healthz /%68ealthz /readyz \
            /confirm/../staff/login/ /confirm/..%2fstaff/login/; do
  check "TEST-P6-12 the public site refuses $path" test "$(code catalyst.staging.test 127.0.0.1 18443 "$path")" = 404
done
# TEST-P6-32: Django itself, with no proxy in front, refuses staff, admin and health paths on the public host name.
check "TEST-P6-32 control: Django serves the staff login on the staff host" test "$(socket_get /staff/login/ staff.staging.test)" = 200
for path in /staff/ /staff/login/ /STAFF/ //staff/ /admin/ /healthz /readyz; do
  check "TEST-P6-32 Django refuses $path on the public host" test "$(socket_get "$path" catalyst.staging.test)" = 404
done

# TEST-P6-14: cookies, HSTS, CSP, no-store on token paths, and a spoofed forwarded header ignored.
headers="$(curl -sk -D - -o /dev/null --resolve catalyst.staging.test:18443:127.0.0.1 https://catalyst.staging.test:18443/request-access/)"
check "TEST-P6-14 HSTS is sent" grep -qi '^strict-transport-security: max-age=300' <<<"$headers"
check "TEST-P6-14 a content security policy is sent" grep -qi "^content-security-policy: default-src 'self'; script-src 'self'" <<<"$headers"
check "TEST-P6-14 the CSRF cookie is __Host-, Secure, HttpOnly and SameSite=Lax" bash -c \
  "grep -i '^set-cookie: __Host-catalyst-csrf=' <<<\"\$1\" | grep -i 'secure' | grep -i 'httponly' | grep -qi 'samesite=lax'" _ "$headers"
check "TEST-P6-14 a token path answers with no-store" bash -c "curl -sk -D - -o /dev/null --resolve catalyst.staging.test:18443:127.0.0.1 https://catalyst.staging.test:18443/confirm/not-a-token/ | grep -i '^cache-control:' | grep -qi 'no-store'"
check "TEST-P6-14 a spoofed X-Forwarded-Proto is overwritten (no redirect to http)" test \
  "$(curl -sk -o /dev/null -w '%{http_code}' -H 'X-Forwarded-Proto: http' --resolve catalyst.staging.test:18443:127.0.0.1 https://catalyst.staging.test:18443/request-access/)" = 200

# TEST-P6-16: the Documenso webhook is not mounted, at the proxy or in Django.
check "TEST-P6-16 the webhook is not mounted at the proxy" test \
  "$(curl -sk -o /dev/null -w '%{http_code}' -X POST --resolve catalyst.staging.test:18443:127.0.0.1 https://catalyst.staging.test:18443/hooks/documenso/)" = 404
check "TEST-P6-16 the webhook is not mounted in Django" test "$(socket_get /hooks/documenso/)" = 404

# TEST-P6-28: no route out of the backend network (no production host, no provider, nothing on the internet).
probe() {  # probe <service> <python>: the exit status of a network probe that exits 42 when the network refuses it
  docker exec "$("${compose[@]}" ps -q "$1")" python -c "import socket,sys
try:
    $2
except OSError:
    sys.exit(42)" 2>/dev/null
  echo $?
}
for service in web worker fetcher; do
  # The control proves the probe itself runs: the database, on the same network, is reachable.
  check "TEST-P6-28 control: $service reaches the database" test "$(probe "$service" "socket.create_connection(('db',5432),3)")" = 0
  check "TEST-P6-28 $service reaches nothing outside (refused, not errored)" test "$(probe "$service" "socket.create_connection(('1.1.1.1',443),3)")" = 42
done
check "TEST-P6-28 names do not resolve from the backend network" test "$(probe web "socket.getaddrinfo('example.com',443)")" = 42

# TEST-P6-30: the fetcher's only way out is the egress proxy, which refuses every denied range. Names on a public
# wildcard DNS service resolve to the denied addresses themselves, so the proxy's own lookup is what is tested.
check "TEST-P6-30 control: the fetcher reaches the egress proxy" test "$(probe fetcher "socket.create_connection(('egress',3128),3)")" = 0
for service in web worker; do  # only the fetcher shares a network with the proxy
  check "TEST-P6-30 $service cannot reach the egress proxy" test "$(probe "$service" "socket.create_connection(('egress',3128),3)")" = 42
done
via_proxy() {  # via_proxy <authority>: the egress proxy's status and refusal code for CONNECT <authority>, from the fetcher
  docker exec "$("${compose[@]}" ps -q fetcher)" python -c "import socket,sys
s=socket.create_connection(('egress',3128),5);s.settimeout(15);s.sendall(('CONNECT '+sys.argv[1]+' HTTP/1.1\r\n\r\n').encode())
head=s.recv(1024).decode().split('\r\n');refusal=[l.split(': ')[1] for l in head if l.startswith('X-Catalyst-Refusal')]
print(head[0].split(' ')[1], refusal[0] if refusal else '-')" "$1" 2>/dev/null || echo "none -"
}
via_proxy_settled() {  # a policy answer (200 or 403) is final; a transient one (502, none) is retried, at most 3 times
  local answer
  for _ in 1 2 3; do
    answer="$(via_proxy "$1")"
    case "$answer" in 200\ *|403\ *|400\ *) break ;; esac
    sleep 2
  done
  printf '%s\n' "$answer"
}
check "TEST-P6-30 control: through the proxy, a public name is tunnelled" test "$(via_proxy_settled example.com:443)" = "200 -"
for authority in 127.0.0.1.nip.io:443 10.0.0.1.nip.io:443 172.17.0.1.nip.io:443 192.168.0.1.nip.io:443 \
                 169.254.169.254.nip.io:443 100.64.0.1.nip.io:443; do
  check "TEST-P6-30 the proxy refuses a name resolving into a denied range ($authority)" test "$(via_proxy_settled "$authority")" = "403 address_not_allowed"
done
for authority in 10.0.0.1:443 169.254.169.254:443 "[::1]:443"; do
  check "TEST-P6-30 the proxy refuses an IP literal ($authority)" test "$(via_proxy "$authority")" = "403 ip_literal_refused"
done
check "TEST-P6-30 the proxy refuses a port other than 443" test "$(via_proxy_settled example.com:22)" = "403 port_not_allowed"
check "TEST-P6-30 the proxy refuses a single-label name (the database's)" test "$(via_proxy db:443)" = "400 bad_host"
check "TEST-P6-30 the egress proxy mounts no secret" test -z "$(docker exec "$("${compose[@]}" ps -q egress)" ls /run/secrets 2>/dev/null)"

# TEST-P6-27: a dark deploy. An applicant goes through the real form and confirmation link; the evidence collection that
# follows is held until the owner's activation command, and no action that reaches a provider exists in any other state.
jar="$work/dark-jar"
# 9kg.43: intake is invitation-only by default, so the owner path invites the synthetic address first (as the owner role).
check "TEST-P6-27 the owner invites the dark-deploy address (invitation-only intake)" \
  bash -c "\"\$@\" | grep -q '\"issued\": true'" _ "${compose[@]}" run --rm --no-deps -T migrate \
  python manage.py catalyst_invite dark-deploy@example.test --issued-by "staging check" --note "dark deploy, TEST-P6-27"
form="$(curl -sk -c "$jar" --resolve catalyst.staging.test:18443:127.0.0.1 https://catalyst.staging.test:18443/request-access/)"
csrf="$(grep -oE 'name="csrfmiddlewaretoken" value="[^"]+"' <<<"$form" | head -1 | sed 's/.*value="//; s/"$//')"
check "TEST-P6-27 an applicant is accepted through the form" test "$(curl -sk -b "$jar" -o /dev/null -w '%{http_code}' \
  --resolve catalyst.staging.test:18443:127.0.0.1 -H 'Referer: https://catalyst.staging.test:18443/request-access/' \
  -H 'Origin: https://catalyst.staging.test:18443' --data-urlencode "csrfmiddlewaretoken=$csrf" \
  --data-urlencode 'name=Dark Deploy' --data-urlencode 'email=dark-deploy@example.test' \
  --data-urlencode 'reason=Synthetic reason for access.' https://catalyst.staging.test:18443/request-access/)" = 302
dark_link=""
for _ in $(seq 30); do
  dark_link="$(docker exec "$("${compose[@]}" ps -q worker)" sh -c 'grep -l dark-deploy@example.test /var/lib/catalyst/mail/* 2>/dev/null | xargs -r cat' | grep -oE '/confirm/[^/[:space:]]+/' | head -1 || true)"
  [ -n "$dark_link" ] && break; sleep 1
done
check "TEST-P6-27 the verification mail reached the private file sink, not a provider" test -n "$dark_link"
page="$(curl -sk -c "$jar" -b "$jar" --resolve catalyst.staging.test:18443:127.0.0.1 "https://catalyst.staging.test:18443$dark_link")"
version="$(grep -oE 'name="version" value="[^"]+"' <<<"$page" | head -1 | sed 's/.*value="//; s/"$//' || true)"
csrf="$(grep -oE 'name="csrfmiddlewaretoken" value="[^"]+"' <<<"$page" | head -1 | sed 's/.*value="//; s/"$//' || true)"
check "TEST-P6-27 the confirmation page offered its form" test -n "$version" -a -n "$csrf"
answer="$(curl -sk -b "$jar" -w '\n%{http_code}' --resolve catalyst.staging.test:18443:127.0.0.1 \
  -H "Referer: https://catalyst.staging.test:18443$dark_link" -H 'Origin: https://catalyst.staging.test:18443' \
  --data-urlencode "csrfmiddlewaretoken=$csrf" --data-urlencode "version=$version" \
  "https://catalyst.staging.test:18443$dark_link" || true)"
check "TEST-P6-27 the applicant confirms (200, and the confirmed page's own sentence)" bash -c \
  "[ \"\$(tail -1 <<<\"\$1\")\" = 200 ] && grep -q 'Your email address is confirmed' <<<\"\$1\"" _ "$answer"
sleep 3  # the worker loop has had its turn: anything not held would have started
# Every registered kind is counted except an explicit allow-list (the verification mail to the file sink, the session
# clean-up), so a provider-reaching kind added later is covered without editing this check.
dark="$(owner_run migrate python manage.py shell -c "
from django.conf import settings
from workflow.models import PendingAction as P
allowed = {'send_verification', 'clear_sessions'}
registry = set(settings.CATALYST_ACTION_HANDLERS)
print(int(allowed <= registry), P.objects.filter(kind='start_evidence_collection', status='held').count(),
      P.objects.filter(kind__in=registry - allowed).exclude(status='held').count())" | tail -1 || true)"
read -r allow_ok held_count others <<<"$dark"
check "TEST-P6-27 control: the allow-list names registered kinds" test "${allow_ok:-}" = 1
check "TEST-P6-27 the evidence collection is held until activation" test "${held_count:-}" = 1
check "TEST-P6-27 no other registered action exists outside the held state" test "${others:-}" = 0

# TEST-P6-15: the staff login needs the second factor, and a superuser gets no session at all.
staff_url=https://staff.staging.test:18444
jar="$work/jar"
totp() {  # totp <base32 secret>: the current 6-digit code (RFC 6238, SHA-1, 30 s)
  python3 -c "import base64,hmac,struct,sys,time;k=base64.b32decode(sys.argv[1]+'='*(-len(sys.argv[1])%8));h=hmac.new(k,struct.pack('>Q',int(time.time()//30)),'sha1').digest();o=h[-1]&15;print('%06d'%((struct.unpack('>I',h[o:o+4])[0]&0x7fffffff)%1000000))" "$1"
}
staff_post() {  # staff_post <user> <password> [device] [token]: the login POST's status, with a fresh CSRF pair
  rm -f "$jar"
  local page csrf
  page="$(curl -sk -c "$jar" --resolve staff.staging.test:18444:127.0.0.2 "$staff_url/staff/login/")"
  csrf="$(grep -oE 'name="csrfmiddlewaretoken" value="[^"]+"' <<<"$page" | head -1 | sed 's/.*value="//; s/"$//')"
  curl -sk -b "$jar" -c "$jar" -o "$work/login.html" -w '%{http_code}' --resolve staff.staging.test:18444:127.0.0.2 \
    -H "Referer: $staff_url/staff/login/" -H "Origin: $staff_url" \
    --data-urlencode "csrfmiddlewaretoken=$csrf" --data-urlencode "username=$1" --data-urlencode "password=$2" \
    --data-urlencode "otp_device=${3:-}" --data-urlencode "otp_token=${4:-}" "$staff_url/staff/login/?next=/staff/"
}
staff_index() { curl -sk -b "$jar" -o /dev/null -w '%{http_code}' --resolve staff.staging.test:18444:127.0.0.2 "$staff_url/staff/"; }
staff_password="synthetic-staff-$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
owner_run -e GATE_PW="$staff_password" migrate python manage.py add_readonly_staff gate-staff --password-env GATE_PW >/dev/null
owner_run -e DJANGO_SUPERUSER_PASSWORD="$staff_password" migrate python manage.py createsuperuser --noinput \
  --username gate-super --email gate-super@example.test >/dev/null
secret_of() { owner_run migrate python manage.py enroll_staff_two_factor "$1" | grep -oE 'secret=[A-Z2-7]+' | cut -d= -f2; }
staff_secret="$(secret_of gate-staff)"; super_secret="$(secret_of gate-super)"
check "TEST-P6-15 the staff accounts were enrolled" test -n "$staff_secret" -a -n "$super_secret"
check "TEST-P6-15 the password alone does not sign in" test "$(staff_post gate-staff "$staff_password")" = 200
device="$(grep -oE 'value="otp_totp\.totpdevice/[0-9]+"' "$work/login.html" | head -1 | cut -d'"' -f2)"
check "TEST-P6-15 the login then offers the enrolled device" test -n "$device"
check "TEST-P6-15 a wrong token does not sign in" test "$(staff_post gate-staff "$staff_password" "$device" 000000)" = 200
sleep 2  # the wrong token's throttle delay
check "TEST-P6-15 the password and the current token sign in" test "$(staff_post gate-staff "$staff_password" "$device" "$(totp "$staff_secret")")" = 302
check "TEST-P6-15 the verified session reaches the staff site" test "$(staff_index)" = 200
check "TEST-P6-15 a superuser with the right password is refused at the login form" test "$(staff_post gate-super "$staff_password")" = 200
check "TEST-P6-15 the refusal names the superuser rule" grep -q "cannot sign in to the staff site" "$work/login.html"
check "TEST-P6-15 the refused superuser has no staff session" test "$(staff_index)" = 302

exit "$fail"
