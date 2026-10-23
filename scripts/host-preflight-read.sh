#!/usr/bin/env bash
# Read-only production-host preflight for the internal launch (bead 9kg.42; 029 section 12, U1, U2, U10).
#
# Runs ONLY under the owner's recorded host go (council record 030, Q9; D-50 excluded reading the live proxy
# configuration without one). Every command is read-only. The full record is written to a file OUTSIDE any
# repository (PREFLIGHT_OUT, default under the operator's home); the terminal shows only the item list with
# answered / UNKNOWN, so nothing private is pasted into a public surface by accident. The record contains
# configuration names, hashes, sizes, ports, timer names and aggregate counts; it never reads a secret's value
# and never prints a file under the secrets directory.
#
# Usage: scripts/host-preflight-read.sh <ssh-alias>   (the alias comes from the operator's SSH config; no host
# name lives in this repository). Optional environment: DATA_ROOT, SECRETS_DIR, LEARN_SITE (the learning site's
# host name as it appears in the proxy configuration), PROXY_CONFIG (default /etc/caddy/Caddyfile).
set -uo pipefail

HOST="${1:?usage: $0 <ssh-alias>}"
DATA_ROOT="${DATA_ROOT:-/srv}"
SECRETS_DIR="${SECRETS_DIR:-/etc/intentsolutions}"
LEARN_SITE="${LEARN_SITE:-learn.intentsolutions.io}"
PROXY_CONFIG="${PROXY_CONFIG:-/etc/caddy/Caddyfile}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${PREFLIGHT_OUT:-$HOME/.local/state/catalyst-v2/preflight-$STAMP.md}"
mkdir -p "$(dirname "$OUT")"
chmod 700 "$(dirname "$OUT")"

answered=0; unknown=0
item() {  # item "<label>" <<< "<remote command>"
  local label="$1" cmd; cmd="$(cat)"
  printf '\n## %s\n\n```\n$ %s\n' "$label" "$cmd" >> "$OUT"
  if out=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" "$cmd" 2>&1); then
    printf '%s\n```\n' "$out" >> "$OUT"; printf '%-60s answered\n' "$label"; answered=$((answered+1))
  else
    printf '%s\n```\nUNKNOWN (command failed)\n' "$out" >> "$OUT"; printf '%-60s UNKNOWN\n' "$label"; unknown=$((unknown+1))
  fi
}

{
  echo "# Production-host preflight read, $STAMP"
  echo
  echo "Read-only. Host alias: (operator's SSH alias, not recorded). Items follow 9kg.42. This file is a private"
  echo "operations record: do not commit it; cite its hash from 026 section 16."
} > "$OUT"
chmod 600 "$OUT"

item "Kernel, uptime, load" <<< 'uname -r; uptime'
item "Memory headroom" <<< 'free -h'
item "Disk headroom (data root and root)" <<< "df -h / $DATA_ROOT 2>/dev/null"
item "Data root ownership and mode (top level only)" <<< "ls -ld $DATA_ROOT $DATA_ROOT/* 2>/dev/null"
item "Containers: names, images, ports (isolation, one-writer rule)" <<< "docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'"
item "Compose projects present" <<< "docker compose ls -a 2>/dev/null"
item "Listening ports and owning process names" <<< "ss -ltnp 2>/dev/null | awk '{print \$1, \$4, \$6}'"
item "Timers (names and next run only)" <<< "systemctl list-timers --all --no-pager --no-legend | awk '{print \$NF, \$(NF-1), \$1, \$2, \$3}' | sort"
item "Operator cron entries (names only, no arguments)" <<< "for u in \$(cut -d: -f1 /etc/passwd); do sudo -n crontab -l -u \$u 2>/dev/null | grep -v '^#' | awk -v u=\$u 'NF{print u\": \"\$6}'; done; ls /etc/cron.d 2>/dev/null"
item "Proxy configuration hash and size" <<< "sha256sum $PROXY_CONFIG; wc -l $PROXY_CONFIG"
item "Proxy: site blocks (host names only)" <<< "grep -nE '^[a-z0-9.*-]+(, ?[a-z0-9.*-]+)* *\{' $PROXY_CONFIG"
item "Proxy: the learning site's matchers and handlers (paths, directives; no upstream addresses)" <<< "awk '/^$LEARN_SITE/{f=1} f&&/^\}/{print; f=0} f' $PROXY_CONFIG | grep -vE 'reverse_proxy|to |tls' | sed -E 's/[0-9]{1,3}(\.[0-9]{1,3}){3}/<addr>/g'"
item "Proxy: adapted configuration hash (validate only)" <<< "caddy validate --config $PROXY_CONFIG --adapter caddyfile >/dev/null 2>&1 && caddy adapt --config $PROXY_CONFIG --adapter caddyfile 2>/dev/null | sha256sum"
item "Proxy modules of interest (rate limit, log filters, auth)" <<< "caddy list-modules 2>/dev/null | grep -Ei 'rate|filter|log|auth|forward' "
item "Proxy log files (names, sizes, modes)" <<< "ls -l /var/log/caddy 2>/dev/null"
item "Certificates on disk (names and dates only)" <<< "find /var/lib/caddy -type f -name '*.crt' -printf '%TY-%Tm-%Td %f\n' 2>/dev/null | sort | tail -20"
item "Secrets directory: names, modes and owners (never contents)" <<< "ls -l $SECRETS_DIR 2>/dev/null"
item "Age recipient file present (name only)" <<< "ls -l $SECRETS_DIR/*.age $SECRETS_DIR/*recipient* 2>/dev/null"
item "PostgreSQL service(s) and versions (host or container)" <<< "systemctl list-units --type=service --no-pager --no-legend | grep -i postgres; docker ps --format '{{.Names}} {{.Image}}' | grep -i postgres"
item "PostgreSQL roles (names and attributes; needs a local superuser or a container)" <<< "sudo -n -u postgres psql -Atc \"select rolname, rolsuper, rolcreaterole, rolcanlogin from pg_roles order by 1\" 2>/dev/null || for c in \$(docker ps --format '{{.Names}}' | grep -i postgres); do docker exec \$c psql -U postgres -Atc \"select rolname, rolsuper, rolcreaterole, rolcanlogin from pg_roles order by 1\" 2>/dev/null; done"
item "Backup fabric: repository paths and exclusions (names only)" <<< "ls -ld /backup* /srv/backup* 2>/dev/null; grep -rhoE -- '--exclude [^ ]+' /usr/local/bin/*backup* /etc/cron.d/* 2>/dev/null | sort -u"
item "Alert floor present (names only)" <<< "ls -l /usr/local/bin/notify.sh /usr/local/lib/intentsolutions/alert-floor.sh 2>/dev/null"
item "Staff private path configured on the proxy (count of matching lines only)" <<< "grep -cE 'handle_path|@staff|forward_auth|remote_ip' $PROXY_CONFIG"
item "SSH: listening address families and auth methods (names)" <<< "sudo -n sshd -T 2>/dev/null | grep -E '^(passwordauthentication|pubkeyauthentication|permitrootlogin|listenaddress)'"
item "Firewall summary (rule count and defaults)" <<< "sudo -n ufw status verbose 2>/dev/null | head -8"

printf '\n---\nanswered: %d, unknown: %d\n' "$answered" "$unknown" >> "$OUT"
echo
echo "answered: $answered, UNKNOWN: $unknown"
echo "record: $OUT (private; sha256 $(sha256sum "$OUT" | cut -c1-16)...)"
echo "next: compare the learning site's matchers with 003 and 029 section 4.6; answer U1, U2, U10 in the private record; cite the hash in 026 section 16."
