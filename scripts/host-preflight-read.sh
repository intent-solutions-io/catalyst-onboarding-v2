#!/usr/bin/env bash
# Read-only production-host preflight for the internal launch (bead 9kg.42; 029 section 12, U1, U2, U10).
#
# Runs ONLY under the owner's recorded host go (council record 030, Q9; D-50 excluded reading the live proxy
# configuration without one). Every remote command is a read; nothing is written on the host (the proxy
# configuration is parsed with `caddy adapt`, never validated, because validation provisions log writers). The
# full record is written to a file OUTSIDE any repository (CATALYST_PREFLIGHT_OUT, an absolute path; the default
# is under the operator's state directory); the terminal shows only the item list with answered / UNKNOWN and the
# record's hash. The record holds configuration names, hashes, sizes, ports, timer names and aggregate counts;
# IPv4, IPv6 and host:port literals are masked before anything is written; a secret's value is never read and no
# file under the secrets directory is printed. An empty read is UNKNOWN, not an answer.
#
# Usage: scripts/host-preflight-read.sh <ssh-alias>   (the alias comes from the operator's SSH config; no host
# name lives in this repository). Optional environment: CATALYST_PREFLIGHT_DATA_ROOT, CATALYST_PREFLIGHT_SECRETS_DIR,
# CATALYST_PREFLIGHT_LEARN_SITE (the learning site's host name as written in the proxy configuration),
# CATALYST_PREFLIGHT_PROXY_CONFIG (default /etc/caddy/Caddyfile), CATALYST_PREFLIGHT_OUT (absolute path).
set -uo pipefail
umask 077

HOST="${1:?usage: $0 <ssh-alias>}"
[[ "$HOST" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "ssh alias must be a plain name" >&2; exit 2; }
DATA_ROOT="${CATALYST_PREFLIGHT_DATA_ROOT:-/srv}"
SECRETS_DIR="${CATALYST_PREFLIGHT_SECRETS_DIR:-/etc/intentsolutions}"
LEARN_SITE="${CATALYST_PREFLIGHT_LEARN_SITE:-learn.intentsolutions.io}"
PROXY_CONFIG="${CATALYST_PREFLIGHT_PROXY_CONFIG:-/etc/caddy/Caddyfile}"
for v in DATA_ROOT SECRETS_DIR PROXY_CONFIG; do
  [[ "${!v}" =~ ^/[A-Za-z0-9_./-]+$ ]] || { echo "$v must be an absolute plain path" >&2; exit 2; }
done
[[ "$LEARN_SITE" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "site name must be a plain host name" >&2; exit 2; }
LEARN_RE="${LEARN_SITE//./\\.}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${CATALYST_PREFLIGHT_OUT:-$HOME/.local/state/catalyst-v2/preflight-$STAMP.md}"
[[ "$OUT" = /* ]] || { echo "CATALYST_PREFLIGHT_OUT must be absolute" >&2; exit 2; }
OUT_DIR="$(dirname "$OUT")"
install -d -m 700 "$OUT_DIR"
if git -C "$OUT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "refusing to write the record inside a git work tree" >&2; exit 2
fi

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes --)
answered=0; unknown=0

redact() {  # mask IPv4, IPv6 and host:port literals; never trust a denylist for secrets, so items also allowlist
  sed -E -e 's/[0-9]{1,3}(\.[0-9]{1,3}){3}/<addr>/g' \
         -e 's/([0-9a-fA-F]{0,4}:){2,7}[0-9a-fA-F]{0,4}/<addr6>/g' \
         -e 's/<addr6?>:[0-9]+/<addr:port>/g' \
         -e 's/\b[A-Za-z0-9.-]+\.(io|com|net|org|dev|ts\.net):[0-9]+/<host:port>/g'
}

item() {  # item "<label>" <<< "<remote command>"; the command is a fixed literal with validated path parameters
  local label="$1" cmd out status
  cmd="$(cat)"
  printf '\n## %s\n\n```\n$ %s\n' "$label" "$cmd" >> "$OUT"
  out=$("${SSH[@]}" "$HOST" "$cmd" 2>&1); status=$?
  out="$(printf '%s' "$out" | redact)"
  if [ "$status" -eq 0 ] && [ -n "$(printf '%s' "$out" | tr -d '[:space:]')" ]; then
    printf '%s\n```\n' "$out" >> "$OUT"; printf '%-62s answered\n' "$label"; answered=$((answered+1))
  else
    printf '%s\n```\nUNKNOWN (%s)\n' "$out" "$([ "$status" -eq 0 ] && echo 'empty output' || echo "exit $status")" >> "$OUT"
    printf '%-62s UNKNOWN\n' "$label"; unknown=$((unknown+1))
  fi
}

{
  echo "# Production-host preflight read, $STAMP"
  echo
  echo "Read-only. Host alias: (operator's SSH alias, not recorded). Items follow 9kg.42. Private operations"
  echo "record: never commit it; cite its hash from 026 section 16. Addresses are masked; an empty read is UNKNOWN."
} > "$OUT"

item "Kernel, uptime, load" <<< 'uname -r; uptime'
item "Memory headroom" <<< 'free -h'
item "Disk headroom (data root and root)" <<< "df -h / $DATA_ROOT 2>/dev/null"
item "Data root ownership and mode (top level only)" <<< "ls -ld $DATA_ROOT $DATA_ROOT/* 2>/dev/null"
item "Containers: names, images, status (isolation, one-writer rule)" <<< "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'"
item "Containers: published ports (addresses masked)" <<< "docker ps --format '{{.Names}}: {{.Ports}}'"
item "Compose projects present" <<< "docker compose ls -a 2>/dev/null"
item "Listening ports and owning process names" <<< "ss -ltnp 2>/dev/null | awk 'NR>1{split(\$4,a,\":\"); print a[length(a)], \$6}' | sort -u"
item "Timers (names and next run only)" <<< "systemctl list-timers --all --no-pager --no-legend | awk '{print \$NF, \$(NF-1), \$1, \$2, \$3}' | sort"
item "Operator cron entries (user and command path only; anything else redacted)" <<< "for u in \$(cut -d: -f1 /etc/passwd); do sudo -n crontab -l -u \$u 2>/dev/null | grep -vE '^\s*(#|\$)' | awk -v u=\$u '{c=\$6; if (c !~ /^\\/[A-Za-z0-9_.\\/-]+\$/) c=\"<redacted>\"; print u\": \"c}'; done; ls /etc/cron.d 2>/dev/null"
item "Proxy configuration hash and size" <<< "sha256sum $PROXY_CONFIG; wc -l $PROXY_CONFIG"
item "Proxy: site blocks (host names only)" <<< "grep -nE '^[a-z0-9.*-]+(, ?[a-z0-9.*-]+)* *\{' $PROXY_CONFIG"
item "Proxy: the learning site's routing directives (allowlisted directives only)" <<< "awk '/^$LEARN_RE/{f=1} f&&/^\}/{f=0} f' $PROXY_CONFIG | awk '{d=\$1; sub(/^[ \t]+/, \"\", d)} d ~ /^(handle|handle_path|route|@|path|redir|rewrite|file_server|root|encode|try_files|respond|log|rate_limit|\})/ {print}'"
item "Proxy: adapted configuration hash (parse only, no validate)" <<< "h=\$(caddy adapt --config $PROXY_CONFIG --adapter caddyfile 2>/dev/null) && printf '%s' \"\$h\" | sha256sum"
item "Proxy modules of interest (rate limit, log filters, auth)" <<< "caddy list-modules 2>/dev/null | grep -Ei 'rate|filter|auth|forward'"
item "Proxy log files (names, sizes, modes)" <<< "ls -l /var/log/caddy 2>/dev/null"
item "Certificates on disk (names and dates only)" <<< "find /var/lib/caddy -type f -name '*.crt' -printf '%TY-%Tm-%Td %f\n' 2>/dev/null | sort | tail -20"
item "Secrets directory: names, modes and owners (never contents)" <<< "ls -l $SECRETS_DIR 2>/dev/null"
item "PostgreSQL service(s) and images (host or container)" <<< "systemctl list-units --type=service --no-pager --no-legend | grep -i postgres; docker ps --format '{{.Names}} {{.Image}}' | grep -i postgres"
item "PostgreSQL roles (names and attributes only)" <<< "sudo -n -u postgres psql -Atc \"select rolname, rolsuper, rolcreaterole, rolcanlogin from pg_roles order by 1\" 2>/dev/null || for c in \$(docker ps --format '{{.Names}}' | grep -i postgres); do docker exec \$c psql -U postgres -Atc \"select rolname, rolsuper, rolcreaterole, rolcanlogin from pg_roles order by 1\" 2>/dev/null; done"
item "Backup fabric: repository paths and exclusions (names only)" <<< "ls -ld /backup* /srv/backup* 2>/dev/null; grep -rhoE -- '--exclude [^ ]+' /usr/local/bin/*backup* /etc/cron.d/* 2>/dev/null | sort -u"
item "Alert floor present (names only)" <<< "ls -l /usr/local/bin/notify.sh /usr/local/lib/intentsolutions/alert-floor.sh 2>/dev/null"
item "Staff private path configured on the proxy (count of matching lines)" <<< "grep -cE 'handle_path|@staff|forward_auth|remote_ip' $PROXY_CONFIG || true"
item "SSH: auth methods (names only)" <<< "sudo -n sshd -T 2>/dev/null | grep -E '^(passwordauthentication|pubkeyauthentication|permitrootlogin) '"
item "Firewall: status, defaults and allow-rule count" <<< "sudo -n ufw status verbose 2>/dev/null | grep -E '^(Status|Default)'; sudo -n ufw status 2>/dev/null | grep -c ALLOW || true"

printf '\n---\nanswered: %d, unknown: %d\n' "$answered" "$unknown" >> "$OUT"
echo
echo "answered: $answered, UNKNOWN: $unknown"
echo "record: $(basename "$OUT") in the operator's state directory (mode 600; sha256 $(sha256sum "$OUT" | cut -c1-16)...)"
echo "next: compare the learning site's directives with 003 and 029 section 4.6; answer U1, U2, U10 in the private record; cite the hash in 026 section 16."
