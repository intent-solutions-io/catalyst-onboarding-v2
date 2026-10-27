# The stack the adapters serve (9kg.78.1). Sourced by lib.sh and sweep.sh, never run.
#
# CATALYST_STACK_ENV names it and must be set: `staging` (the dev-box stack) or `production`. Unset, empty or anything
# else is refused before any alert, marker or probe, so a host that lost the setting never falls back to staging's -k
# and an alert never carries a stack name nobody reviewed (PR #122 review). PROBE_TLS holds curl's leading arguments for
# the outside-in probe of the public form, and callers pass it first: -q, so no .curlrc of the timer's user can add
# `insecure`; then -k for staging's internal CA only. Production verifies the certificate against the system store, or
# against CATALYST_PROBE_CA_FILE when the host names one; the CA variables of the environment are cleared there, so
# that file is the only way to change what is trusted.
STACK="${CATALYST_STACK_ENV:-}"
case "$STACK" in
  staging) PROBE_TLS=(-q -k) ;;
  production)
    unset CURL_CA_BUNDLE SSL_CERT_FILE SSL_CERT_DIR
    PROBE_TLS=(-q ${CATALYST_PROBE_CA_FILE:+--cacert "$CATALYST_PROBE_CA_FILE"}) ;;
  *) echo "CATALYST_STACK_ENV must be set to staging or production" >&2; exit 2 ;;
esac
