# The stack the adapters serve (9kg.78.1). Sourced by lib.sh and sweep.sh, never run.
#
# CATALYST_STACK_ENV names it: `staging` (the default, the dev-box stack) or `production`. Anything else is refused,
# so an alert never carries a stack name nobody reviewed. PROBE_TLS holds curl's TLS arguments for the outside-in
# probe of the public form: staging's proxy uses Caddy's internal CA, so -k there only; every other stack verifies the
# certificate, against CATALYST_PROBE_CA_FILE when the host names one.
STACK="${CATALYST_STACK_ENV:-staging}"
case "$STACK" in
  staging) PROBE_TLS=(-k) ;;
  production) PROBE_TLS=(${CATALYST_PROBE_CA_FILE:+--cacert "$CATALYST_PROBE_CA_FILE"}) ;;
  *) echo "CATALYST_STACK_ENV must be staging or production" >&2; exit 2 ;;
esac
