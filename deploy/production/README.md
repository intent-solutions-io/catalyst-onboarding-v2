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

Production defaults to unlimited cumulative assessment requests, tokens, assessment
rounds, reply interpretations and routine correspondence. An explicit numeric quota
still applies when configured; `unlimited` means no cumulative quota and `0` means no
allowance. Remove obsolete deployment overrides before activation.

Set these profile values from the actual MiniMax account and model allocation:

- `CATALYST_MINIMAX_REQUESTS_PER_MINUTE`
- `CATALYST_MINIMAX_TOKENS_PER_MINUTE`

Both default to zero, which refuses live activation until configured. The published
provider ceiling is not proof of this account's allocation. A credential shared with
another application requires a reserved allocation or shared upstream limiter; this
PostgreSQL limiter coordinates only workers using this Catalyst database.

All assessment, clarification-draft, checking and reply-interpretation requests share
the same provider bucket. Preflight checks delay jobs without spending their retry
attempt. Each actual request, including a repair, reserves capacity immediately before
calling MiniMax. Input reservations use serialized request bytes, including tool schemas,
plus framing and the output allowance; they do not rely on a post-response SDK limit.
Reservations count conservatively through the request timeout plus 60 seconds. SDK retries are disabled; the job ledger controls finite retries.

A provider throttle creates a shared cooldown, honoring `Retry-After` and recognized
MiniMax throttle codes. A later, shorter response cannot shorten the cooldown. A
throttle never changes an applicant's qualification decision. Bounded individual
requests and duplicate-send protection remain in force.

## Cutover evidence

Verify the candidate commit's required CI and image checks, then the activated provider
paths from the deployed stack. Reconcile every imported open case before retiring its
old writer. Record deployment, provider and case-continuation evidence in Beads; a
passing synthetic test is not a live canary or a completed migration.
