#!/usr/bin/env bash
# The dead man (026 section 7; 6B.12), run by a separate host timer: alerts when the health check has not completed
# within CATALYST_HEALTH_STALE_SECONDS (default 15 minutes, three missed five-minute runs), whatever the reason (its
# timer stopped, the host was down, or the check hangs). It never depends on the stack: a stopped stack and a stopped
# timer together are caught the same way. Exit 0 fresh, 1 stale and sent, 3 the notify command failed.
set -euo pipefail
: "${CATALYST_HEALTH_STATE:?}" "${CATALYST_NOTIFY_CMD:?}"
stale="${CATALYST_HEALTH_STALE_SECONDS:-900}"
ok="$CATALYST_HEALTH_STATE/health.ok"
age=$(( $(date +%s) - $(stat -c %Y "$ok" 2>/dev/null || echo 0) ))
[ "$age" -gt "$stale" ] || exit 0
bash -c "$CATALYST_NOTIFY_CMD \"\$1\" \"\$2\"" _ urgent "catalyst staging: health.check_stale" || exit 3
exit 1
