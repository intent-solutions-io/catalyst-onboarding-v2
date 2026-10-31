# Production configuration

The base stack runs the existing wave-one configuration. The optional
`parity.compose.yaml` overlay admits the replacement workflow through a mounted,
digest-bound JSON file. It does not approve models, templates, custody or case migration.
Those records and the provider canaries remain prerequisites to activation.

The operator supplies an absolute `CATALYST_PARITY_CONFIG` path and its SHA-256 as
`CATALYST_PARITY_SHA256`. The JSON has exactly two top-level keys: `decision` is `d54`
and `settings` holds the deployment values permitted by `config/parity.py`.
Credentials never belong in this file. Provider credentials are mounted on the worker
and owner-run management container; the public web and fetcher do not receive them.

Use both the base Compose file and the overlay when rendering the candidate stack.
The host wrapper must retain its existing host-specific volumes, routing and backup
configuration. Validate that rendered configuration before recreating services.
The overlay requires the separate custody directories and per-process secret files
named in the YAML. An absent profile retains the base configuration; a wrong digest,
unknown setting or invalid provider target refuses startup.

## MiniMax usage and pacing

Production has no application-imposed input, output, cumulative or per-minute token
limits. No `max_tokens` is sent to MiniMax. Returned token usage is still recorded;
unknown usage stays unknown. The provider's model/context limits and throttling apply.
Synthetic environments retain token-budget fixtures for regression checks.

Assessment rounds, reply interpretations and routine correspondence default to unlimited
cumulative usage. Request timeouts, finite retries and duplicate-send protection remain.

Set `CATALYST_MINIMAX_REQUESTS_PER_MINUTE` from the actual account allocation. It defaults
to zero, refusing activation until configured. The profile no longer accepts
`CATALYST_MINIMAX_TOKENS_PER_MINUTE`. A credential shared with another application needs
a reserved request-rate allocation or a shared upstream limiter; this PostgreSQL limiter
coordinates only workers using this Catalyst database.

Assessment, clarification-draft, checking and reply-interpretation calls share one request
bucket. Preflight checks delay jobs without spending a retry attempt. Every actual call,
including repairs, reserves a request immediately before dispatch. Reservations count
through the request timeout plus 60 seconds. SDK retries are disabled; the job ledger
controls finite retries.

A provider throttle creates a shared cooldown, honoring `Retry-After` and recognized
MiniMax throttle codes. A later, shorter response cannot shorten the cooldown. A
throttle never changes an applicant's qualification decision. Bounded individual
requests and duplicate-send protection remain in force.

## Cutover evidence

Verify the candidate commit's required CI and image checks, then the activated provider
paths from the deployed stack. Reconcile every imported open case before retiring its
old writer. Record deployment, provider and case-continuation evidence in Beads; a
passing synthetic test is not a live canary or a completed migration.
