#!/usr/bin/env bash
# The cutover rehearsal on staging (026 section 9; TEST-P6-26): the route snippets deploy/cutover/catalyst-r1.caddy and
# catalyst-r2.caddy are switched into a stand-in Learn site and rolled back, against stand-in upstreams, on this host.
# The stand-in Learn site is synthetic: the live Learn configuration is read (read-only) only under the cutover plan,
# with the owner's go. Removes everything it created.
#
#   scripts/cutover_rehearsal.sh
#
# Shows: before the switch every path is the LMS's; after it R1 and R2 (with path-normalization variants) reach v2 and
# every LMS path answers byte-identically; after the R1 rollback R1 is the LMS's again, R2 stays on v2, and the LMS
# paths are still byte-identical.
set -uo pipefail
cd "$(dirname "$0")/.."
caddy_image="caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d"
net="catalyst-cutover-$$"
work="$(mktemp -d)"
fail=0
cleanup() {
  docker rm -f "$net-learn" "$net-lms" "$net-v2" >/dev/null 2>&1
  docker network rm "$net" >/dev/null 2>&1
  rm -rf "$work"
}
trap cleanup EXIT
check() { local name="$1"; shift; if "$@"; then echo "PASS $name"; else echo "FAIL $name"; fail=1; fi; }
mkdir -p "$work/routes"
docker network create "$net" >/dev/null
# Stand-in upstreams: each answers with its own name and the path it received.
for name in lms v2; do
  label="$(tr a-z A-Z <<<"$name")"
  docker run -d --name "$net-$name" --network "$net" --network-alias "$name" "$caddy_image" \
    caddy respond --listen :8080 "$label {http.request.uri.path}" >/dev/null
done
# The stand-in Learn site: whatever route snippets are present, then everything else to the LMS.
cat > "$work/Caddyfile" <<'CADDY'
{
	admin localhost:2019
}
:8080 {
	import /etc/caddy/routes/*.caddy
	handle {
		reverse_proxy lms:8080
	}
}
CADDY
docker run -d --name "$net-learn" --network "$net" -p 127.0.0.1:18080:8080 -e CATALYST_UPSTREAM=v2:8080 \
  -v "$work/Caddyfile:/etc/caddy/Caddyfile:ro" -v "$work/routes:/etc/caddy/routes:ro" "$caddy_image" >/dev/null
for _ in $(seq 20); do curl -s -o /dev/null http://127.0.0.1:18080/ && break; sleep 0.5; done
get() { curl -s --path-as-is "http://127.0.0.1:18080$1"; }
reload() { docker exec "$net-learn" caddy reload --config /etc/caddy/Caddyfile >/dev/null 2>&1; }
LMS_PATHS=(/ /login/ /courses/intro/ /confirmation/ /setupwizard/ /withdrawal-policy/ /request-accessible/ /static/app.css)
R1=(/request-access/ /request-access/received/ /REQUEST-ACCESS/ //request-access/)
R2=(/confirm/abc/ /setup/abc/ /withdraw/abc/ /CONFIRM/abc/ //setup/abc/)
snapshot() { for p in "${LMS_PATHS[@]}"; do printf '%s %s\n' "$p" "$(get "$p" | sha256sum | cut -c1-16)"; done; }
all_to() {  # all_to <LMS|V2> <paths...>: every path is answered by that upstream
  local want="$1" p; shift
  for p in "$@"; do [[ "$(get "$p")" == "$want "* ]] || { echo "  $p -> $(get "$p")" >&2; return 1; }; done
}

before="$(snapshot)"
check "before the switch, the LMS answers every LMS path" all_to LMS "${LMS_PATHS[@]}"
check "before the switch, R1 and R2 paths are the LMS's" all_to LMS "${R1[@]}" "${R2[@]}"

cp deploy/cutover/catalyst-r1.caddy deploy/cutover/catalyst-r2.caddy "$work/routes/"
check "the switch reloads cleanly" reload
check "after the switch, R1 (with normalization variants) reaches v2" all_to V2 "${R1[@]}"
check "after the switch, R2 (with normalization variants) reaches v2" all_to V2 "${R2[@]}"
check "after the switch, every LMS path is still the LMS's" all_to LMS "${LMS_PATHS[@]}"
check "after the switch, every LMS path answers byte-identically" test "$(snapshot)" = "$before"

rm "$work/routes/catalyst-r1.caddy"
check "the R1 rollback reloads cleanly" reload
check "after the R1 rollback, R1 is the LMS's again" all_to LMS "${R1[@]}"
check "after the R1 rollback, R2 stays on v2 (applicants' links keep working)" all_to V2 "${R2[@]}"
check "after the R1 rollback, every LMS path answers byte-identically" test "$(snapshot)" = "$before"

rm "$work/routes/catalyst-r2.caddy"
check "removing R2 as well reloads cleanly" reload
check "with no route imported, the Learn site is exactly as before" test "$(snapshot)" = "$before"
check "with no route imported, R2 paths are the LMS's" all_to LMS "${R2[@]}"
exit "$fail"
