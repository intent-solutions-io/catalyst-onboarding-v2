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

## Staff certificates

For a staff host with an existing certificate, include `staff-tls.compose.yaml` after
the base Compose definition. Set `CATALYST_STAFF_TLS_DIR` to the absolute private
directory containing `cert.pem` and `key.pem`, readable by the proxy's UID 10001.
The directory must already exist. The overlay mounts it read-only into the proxy
alone and selects file-backed TLS only for the named staff site. Public and alias
sites retain their internal upstream certificates. Without the overlay, staff TLS
also uses the existing internal-certificate default.

Render the combined Compose configuration into the host's reviewed stack file before
using the deployment adapters, which accept one `CATALYST_COMPOSE_FILE`. Preserve the
host's existing volume names, addresses, ports and other settings. Use the repository
Caddyfile directly: remove the old host-local positional certificate rewrite before
regenerating the stack. Selecting the second site is unsafe now that a public alias
site precedes the staff site.

Validate Caddy with the actual mounted certificate, then verify the staff hostname
and certificate from an authorized device after deployment. Certificate renewal must
reload the proxy to load renewed files. This setting does not widen staff access or
replace the host's certificate-renewal and device restrictions.

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

The two exact `/request-access/assets/select-services-partner-` URLs ending in
`e4897387bbdb.svg` and `c96bbd4b0d98.png` are served from packaged, unchanged official
artwork. Their filename digests and response ETags are pinned in
`applications/brand_assets.py`. The public and alias proxy sites admit those two paths
only. Verify their full SHA-256 values, MIME types and immutable cache headers through
the real Learn route before retiring its old upstream. Preserve these URLs and bytes
on rollback; revised artwork requires a new content-addressed URL.

## Receiver-initiated journal transfer

The existing `catalyst_journal_ship --to` is for a verified off-host filesystem mount.
Never point it at an ordinary local directory and call that off-host protection. For
the estate's receiver-initiated pull model, use the separate staged transfer path below.
Its deployment destination remains an operator input; these commands do not provision
SSH access, install a timer or prove the receiver's physical location.
Choose one shipping method per source journal. Disable its direct-shipping timer
before enabling the pull sequence; the two methods must not update the watermark
concurrently.

The receiver owns its credentials and storage. The production host receives no login
that can write or delete receiver history. Use authenticated, host-key-pinned SSH with
a dedicated forced command on the source, limited to preparation, exporting the two
named files and returning a receipt for acknowledgment. Do not give the pull key a
general shell, database access, provider credentials or source deletion capability.

1. On the source, create a private staging directory (0700) outside the journal,
   application checkout and backup archive. Provision its marker once with
   `manage.py catalyst_journal_ship --to STAGE --provision`.
2. Run `manage.py catalyst_journal_transfer --stage STAGE`. This takes a chain-verified
   snapshot and writes `effects.jsonl` and `transfer.json` into STAGE. Its receipt says
   `staged`; neither this command nor copying these files clears the shipping alert.
3. From the independent receiver, pull those two files into a private staging directory.
   Use the same approved, digest-pinned application image to run the standalone receiver:

   ```bash
   # Both mount paths are receiver-local directories, precreated with mode 0700.
   # Provision once; omit --provision for each subsequent verified receive.
   docker run --rm --network none --read-only --user "$(id -u):$(id -g)" \
     -v "$RECEIVER_STAGE:/transfer:ro" -v "$RECEIVER_COPY:/copy:rw" \
     "$PINNED_IMAGE" python -m workflow.journal_pull \
     --source /transfer --to /copy --provision
   docker run --rm --network none --read-only --user "$(id -u):$(id -g)" \
     -v "$RECEIVER_STAGE:/transfer:ro" -v "$RECEIVER_COPY:/copy:rw" \
     "$PINNED_IMAGE" python -m workflow.journal_pull \
     --source /transfer --to /copy
   ```

   The receiver loads no production settings or secrets and connects to no database.
   It checks the complete journal chain, package digest and exact head. It refuses an
   export that lacks its previously received head or belongs to another lineage. It
   fsyncs and reads back the journal, compatible `head.json`, and `receipt.json` before
   returning the receipt with state `received`. An interrupted operation returns no
   success; the journal itself anchors recovery if it is ahead of the head file.
4. Only after successful receiver verification, return its exact `receipt.json` over the
   authenticated channel. On the source run
   `manage.py catalyst_journal_transfer --acknowledge RECEIPT_FILE`. The source requires
   the receipt to match its current pending export and still exist in its own chain.
   It cannot acknowledge a staged, superseded, altered or lost-tail export. Successful
   acknowledgment records the original export time, so replaying a receipt cannot
   refresh the health watermark and delayed transfer still shows its real age.
5. Run the receiver's complete pull/verify/acknowledge sequence every five minutes, with
   one timer owner and no overlapping invocation. The ratified journal lag page threshold
   is 15 minutes (033 Q9). Verify a successful copy and source readback, then induce a
   transfer failure and confirm the watermark does not advance and the existing health
   alert reports lag/staleness. Monitor the receiver's own failures independently.

The receipt protocol establishes content consistency. Receipt acknowledgment is an
operator privilege, not a cryptographic proof of a remote host's location or durability:
the host wrapper must accept receipts only from the authenticated receiver after its
successful command. Never fabricate a `received` receipt or acknowledge the source's
own staging files. Source staging and receipt files carry opaque references and digests;
keep them private and outside public logs.

Keep the receiver copy independent of the database-backup archive. Its `effects.jsonl`
and `head.json` remain compatible with `catalyst_restore --shipped-from`. Retained
receiver generations and pruning follow the separately approved retention policy;
production credentials must not gain authority over them. A lineage mismatch or lost
tail requires recovery from the receiver, or the existing explicit accepted-loss and
rebaseline procedure; no automatic rebaseline is provided here. Full off-host loss,
restore and alert drills remain deployment evidence, not claims made by unit tests.

### Restricted SSH transport

`workflow.journal_gateway` supplies the source gateway and receiver stream decoder.
Its version-one wire format is one JSON packet line followed by the exact journal
bytes. Metadata is limited to 4096 bytes; the journal has no transport size quota.
No remote filename or archive member is accepted. The full chain and digest are
checked before receiver staging changes, then the existing receive protocol persists
and reads back the independent copy before returning a receipt.

Install a dedicated source SSH key with `restrict` and a root-owned forced command.
The receiver alone holds the private key. The login must have no Docker-group access,
general sudo, writable wrapper/configuration, forwarding or other unrestricted key.
The forced command passes `SSH_ORIGINAL_COMMAND` as **one quoted operation argument**;
it must never evaluate it or use it as a container command. Only the exact strings
`export-v1` and `ack-v1` are accepted. Paths, image digest, container user and mounts
are fixed by the operator-owned wrapper, not by the SSH request or client environment.

The wrapper's fixed container invocation has this shape (replace the operator inputs
when provisioning; this is not an installation command):

```bash
# Wrapper-owned constants: approved image digest, journal volume, private staging path,
# and the uid:gid allowed to access only those mounts. No production env/secrets file.
exec /usr/bin/timeout --kill-after=5s 120s /usr/bin/docker run --rm -i \
  --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user "$JOURNAL_UID_GID" --entrypoint python \
  --mount "type=volume,src=$JOURNAL_VOLUME,dst=/journal" \
  --mount "type=bind,src=$SOURCE_STAGE,dst=/stage" \
  "$PINNED_IMAGE" -m workflow.journal_gateway source \
  --journal /journal --stage /stage --operation="${SSH_ORIGINAL_COMMAND-}"
```

Provision the source stage as described above. The gateway loads no production
settings, opens no database and needs no provider or custody secret. An SSH transport
timeout must also terminate/clean its specific container; do not rely on killing the
Docker client alone to stop a daemon-managed container. The deployed wrapper must
use a unique container identity and bounded cleanup for that invocation.

On the receiver, precreate private, disjoint `/transfer` and `/copy` directories in
the isolated receiver container. Provision both once using the existing standalone
command (the reversed second invocation provisions staging, not another live journal):

```bash
python -m workflow.journal_pull --source /transfer --to /copy --provision
python -m workflow.journal_pull --source /copy --to /transfer --provision
```

For each serialized receiver cycle:

1. Pin the source host key, use the dedicated identity, batch mode and disabled
   forwarding. Request exactly `export-v1` over SSH and feed its stdout to the
   network-isolated receiver container's
   `python -m workflow.journal_gateway receive --stage /transfer --to /copy`.
2. Require **both** SSH and the receiver process to exit successfully (`pipefail` if
   piping). Save this invocation's returned receipt privately; never substitute a
   previous receipt when either process fails. A partial or corrupt stream cannot
   replace the receiver's copy. A source failure after emitting complete bytes may
   leave a valid copy, but still must not trigger acknowledgment from a failed cycle.
3. Only then request exactly `ack-v1`, sending that receipt on stdin and closing stdin.
   Require a successful source response. Failed acknowledgment leaves a durable
   receiver copy and the source alert outstanding; the next complete cycle may retry.

Keep a receiver-side lock across export, persistence and acknowledgment, and retain
the five-minute cadence and independent failure monitoring above. Local protocol
tests do not establish off-host custody, SSH restrictions, timer operation or recovery.
Those require the independently controlled destination and live host acceptance.

## Local alert rehearsal

Run `CATALYST_STACK_ENV=production bash scripts/alert_drill.sh` on the development
host to exercise the existing health and stale-check adapters against the production
image and Compose definition. Omitting the variable retains the staging drill.
Both modes refuse remote Docker contexts, a nonlocal daemon, and an existing production
stack or retained production journal before creating resources.

The production run uses synthetic credentials, loopback listeners and a separately
named, ownership-labelled external journal volume. It renders all required Compose
profiles, trusts only its local proxy's CA for the production probe, and verifies that
the unapproved intake answers 503 over valid TLS. Existing policy and unshipped-journal
warnings remain visible; worker recovery must return to that exact baseline. Unknown
baseline faults fail the run. Worker loss, overdue work, unresolved bounces, stopped
monitoring and content-free alert output are exercised using the recording stub.

This is local rehearsal evidence. No notification is delivered, no production timer is
installed, and no off-host recovery is demonstrated. Those checks remain open in
`catalyst-v2-9kg.28` and `catalyst-v2-9kg.78.4`; production restore and deploy drills also
remain unfinished. A passing local drill must not close these live acceptance gates.
