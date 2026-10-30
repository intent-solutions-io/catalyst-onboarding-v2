# P6 Staging, Deployment, Backup and Cutover Specification (handoff 6A)

| Field | Value |
|---|---|
| Document | `026-AT-DSGN-p6-staging-deployment-specification` |
| Version | 0.2.0 (0.1.1 applies the security and privacy review, section 15; 0.2.0 records the owner's approval, D-49) |
| Status | **APPROVED by the owner 2026-10-19 with every recommendation (D-49 in `011`); GATE-STAGING signed off 2026-10-22 (D-50) for the dev-box scope, with the 17 partly proven cases of `028` section 4 carried as beads (`029` section 13).** 6B's repository-local tasks are released for synthetic work. Each host task (6B tasks 11 to 13), the pilot and the cutover still needs its own authorization. The owner still sets the values the decisions leave to them: RPO and RTO targets (P6-D-7), alert thresholds and who is paged (P6-D-9), rotation intervals (P6-D-15), and applies the `main` ruleset and protected `release` environment (P6-D-5). |
| Owner | Jeremy Longshore |
| Date | 2026-10-18 |
| Epic | P6 `catalyst-v2-9kg` ("Prepare staging, deployment, backup with demonstrated restore, monitoring and the reversible Learn routing cutover") |
| Gates | GATE-STAGING (this document's acceptance plan), GATE-PILOT and GATE-CUTOVER (outlined; each needs its own decisions) |
| Builds on | `024` (P6 readiness matrix, PL plan), `003` (ADR-14 roles, "Learn and Django routing"), `009` section 5.5, `011` POL-10, POL-13 to POL-16, `021` (webhook, custody), `023` (P5), the estate operations records (private; cited by name only) |

> **What P6 is.** P1 to P5 are built and accepted for synthetic work (GATE-S1 to GATE-P5, D-26 to D-48). They have only
> ever run inside test containers. P6 makes the same application deployable: an image and processes, secrets,
> backup with a demonstrated restore, monitoring that reaches the operator, staff access fit for real use, and a
> release and rollback path. Then a staged, reversible move of `learn.intentsolutions.io`'s applicant paths from the
> first-generation service to v2. GATE-STAGING proves all of it on a synthetic staging stack. Real applicants, real
> providers and the public cutover each come later, behind their own gates.

## 1. Sources and evidence labels

Claims are labelled **VERIFIED** (read in the named file) or **INFERRED** (reasoned, to be confirmed). Two kinds of
estate input are used:

- **Estate authority** (binding on any host change; private, so this public document cites it by name only and
  keeps no host paths, host names, retention figures or topology from it): the estate operations records (deploy,
  backup, ingress, observability and alerting, host and secrets) and the managed-service filesystem standard
  (`093`). Concrete paths and figures for Catalyst v2 are recorded there, not here (section 15, B1).
- **First-generation Catalyst precedent** (not binding on v2; cited because the estate already reviewed it):
  production on the estate VPS isolated by container, database and role; staging as a synthetic compose
  stack on the dev box; one image in several roles with a loopback-only web process; SOPS files decrypted to tmpfs;
  a snapshot `pg_dump` placed where the estate archive picks up logical dumps, by a hook that never blocks the estate backup; a monthly
  restore drill. These live in the governed brain's decision and convention records.

The design input came from the `catalyst-release-operations` specialist (read-only), 2026-10-18.

## 2. What exists today (VERIFIED in this repository)

| Area | Today | Consequence for P6 |
|---|---|---|
| Environments | `config/guards.py` allows only `development` and `test` ("production settings are not authorized before phase P6") | a `staging` value and its rules are needed before any stack starts |
| Fakes and provider settings | the agreement provider, custody directory, provisioning adapter and evidence hosts are refused outside `test`; provider-prefixed variables (`MINIMAX_`, `DOCUMENSO_`, `MXROUTE_`, `SMTP_`, `EMAIL_HOST`) are refused everywhere | staging needs a guard change, not only a compose file; production secrets have no read path yet |
| Deployment artifacts | no Dockerfile, no `deploy/`, no health endpoint; CI and release workflows only | the deployment unit is all new |
| Web security settings | only `SECURE_REFERRER_POLICY`; no secure-cookie, HSTS or proxy-header settings | needed before any non-local host |
| Worker liveness | `run_worker` writes no heartbeat | monitoring has no liveness signal |
| Health | `correspondence_health` (sends and collector; exit 0, 1, 2; counts only) | custody, provisioning and pending-action age have no check |
| Database roles | owner, app and retention (ADR-14); `provision_db_roles.py` refuses other environments; web and worker refuse any login but the app role | provisioning must gain explicit staging and production modes |
| Custody | write-once files (`O_EXCL`, `O_NOFOLLOW`, 0600); `verify_custody_restore --manifest`; a local backup and restore rehearsal (9kg.7) | the coherent-backup design can rely on write-once files |
| Webhook | mounted only in `test` and `development`; 64 KiB cap | exposure is an owner decision (P4-D-17) |
| Release | manual, dry-run-default release workflow (PR #41); `main` unprotected; merge guard lists one required check of two | protections come before any deploy credential |

## 3. Environments and topology (proposed)

| Part | Staging | Pilot and production | Estate pattern reused |
|---|---|---|---|
| Host | the estate dev box, brought up for a gate window, not always on (it runs no production daemons and has strict memory limits) | the estate VPS | precedent: staging on the dev box, production on the VPS |
| Compose project | `catalyst-v2-staging` | `catalyst-v2` (distinct from the first-generation project) | per-project isolation, as `scripts/test.sh` |
| Database | its own PostgreSQL 16.15 container at the digest in `compose.yaml`, a named volume, an internal network, no published port | the same; data under the managed-service data root for `catalyst-v2` | `093` |
| Roles | owner, app, retention; an operator-only admin for bootstrap; proposed backup role (P6-D-7) | the same, with distinct credentials per environment | ADR-14 |
| Web | a unix socket only (section 4) | a unix socket only, behind the existing Caddy | precedent (loopback), tightened |
| Worker | an egress network that reaches only the staging fakes | egress to approved providers, only after the pre-live gates | precedent |
| Proxy | its own Caddy container bound to the tailnet address | the existing VPS Caddy, changed only through the estate ingress procedure | the estate ingress procedure |
| Providers | fake Documenso, the fake mail host, a local SMTP and IMAP sink | real, behind each phase's pre-live gates | precedent |
| Custody | its own volume | its own directory under the managed-service data root | `093` |
| Ports | allocated from the estate inventory before use; never the first-generation port | the same | the estate inventory |

**What staging cannot prove** (pilot-gate items): the real VPS Caddy; Documenso's delivery to a webhook (the provider
refuses private webhook URLs, `021`); the offsite backup legs for Catalyst (the staging archive stays on the dev
box).

**Recorded exception, production:** keep the PostgreSQL data directory outside every Borg source root, because a
copy of a live cluster is torn. The backup is the logical dump (section 6). This needs a `093` section 8 exception
record (P6-D-8).

## 4. The deployment unit (proposed)

- **One image.** `python:3.14.8-slim` at the digest already pinned for the tests; dependencies installed
  `--require-hashes --no-deps`; non-root, read-only root filesystem, capabilities dropped, no new privileges; the
  commit as an OCI label and a read-only file; no secret in any layer.
- **Processes from that image:**

  | Process | Command | Connects as | Lifetime |
  |---|---|---|---|
  | `web` | a WSGI server on a unix socket, **no access log** (links carry bearer tokens) | app | service |
  | `worker` | `manage.py run_worker` for every handler except evidence fetching: correspondence, the collector, reminders, agreements, provisioning | app | service |
  | `fetcher` | `manage.py run_worker` limited to the evidence-fetch handler (`018`), holding **no provider secret**, behind a host-level egress deny (section 5) | app | service |
  | `migrate` | `manage.py migrate` | owner | one-shot, before web and worker |
  | `provision-roles` | the role provisioning step, with the admin credential | admin | operator-run one-shot |

  No retention process exists; starting one is a separate authorization (ADR-14).
- **Process manager.** The compose project under a systemd unit (INFERRED from `093`).
- **Health.** `/healthz`: liveness, no database call. `/readyz`: the runtime role check, the migration plan empty
  (schema at head), and the oldest pending-action age, answered as a fixed status token. **No version, commit or
  configuration is ever returned over HTTP** (`003`: health "never returns version, configuration or dependency
  detail"). The deployed commit is compared through the image label and a `manage.py` command, and recorded in the
  deployment receipt. The listener is a unix socket (mode 0660, the proxy's group), not TCP loopback, and Django
  itself refuses the health paths on any public host name (a host-to-URL guard, tested). Returning the commit over
  HTTP would need an amendment to `003` (P6-D-12).
- **Into the estate deploy wrapper.** The wrapper (capture, deploy, fail-closed smoke, then promote or auto-revert
  once and hold; VERIFIED in the private deploy record) drives Catalyst through its hooks:

  | Hook | Catalyst adapter |
  |---|---|
  | capture | read the current image-digest pointer |
  | deploy (also the revert) | write the pointer, `docker compose up -d web worker fetcher` |
  | smoke | the estate smoke check against `/readyz` (the fixed token) through the socket, plus an outside-in request through Caddy |
  | notify, audit | the estate alert floor and action audit |

  A stack entry in the wrapper configuration and an installed force-command are estate changes (host authorization).
- **Migrations and auto-revert (the key rule).** The wrapper reverts the image, never the data. Migrations run before
  the deploy step, after a pre-deploy backup. Every release must be compatible with the previous image (expand, then
  contract). A release whose migration is not compatible is marked **forward-only**, its auto-revert is refused, and
  its only rollback is a restore. Held activations are the first mitigation.
- **Deployment receipt** (kept, no personal data): commit, image digest, schema revision per app, activation state
  (held counts per kind, activation versions in code), the `/readyz` readback, the `check --deploy` result and the
  pre-deploy backup's receipt. A mismatch between intended and read-back values fails the deploy.

## 5. Secrets and egress (proposed)

| Secret | Staging | Pilot or production | Reaches |
|---|---|---|---|
| App, owner and retention role passwords | synthetic, distinct from test | SOPS | app: web, worker and fetcher; owner: `migrate` only; retention: nothing until authorized |
| Admin bootstrap credential | synthetic | SOPS, operator only | `provision-roles` only |
| Django secret key and the verification key (with fallbacks) | synthetic | SOPS | web, worker and fetcher (Django needs its secret key; the verification key only web and worker) |
| Documenso webhook secrets (at most two, for rotation) | synthetic | SOPS | web (the route) |
| Documenso API token | none | SOPS | worker only |
| Mail credentials (SMTP and IMAP) | none (the local sink) | SOPS | worker only |
| MiniMax key | none | SOPS | worker only, and only after the P3 live-call protections (3E) |
| Mail-host provisioning credential | none | SOPS | a separate credential service only; never web, worker or fetcher (`023` 11.1) |
| Backup role credential | synthetic | SOPS | the backup job only |

- **Where:** SOPS-encrypted files per process kind in the estate secrets directory for `catalyst-v2`, decrypted at
  deploy into tmpfs (0600, atomic replace) as the filesystem standard `093` requires. Concrete paths are in the
  private operations record.
- **How they reach a process (H1).** Settings read **each secret from its own file**; the values never enter the
  process environment, where `/proc/<pid>/environ`, `docker exec env`, child processes and crash dumps would expose
  them. Each process kind mounts only its own files, read-only. A compose `env_file` is not used (its values persist
  in container configuration). Tests assert that `docker inspect` and `docker exec env` of each container show none of
  the owner, admin, API-token or mail values (TEST-P6-04, 11).
- **Who can decrypt.** The deploy step decrypts with the host's key, so a compromise of the deploy force-command
  exposes every Catalyst secret. The force-command therefore accepts only a commit and an attested image digest
  (section 9) and runs nothing else.
- **Rotation (H2),** per secret class, routine and on suspected leak, in a runbook with a test each:

  | Class | Effect of rotation | Procedure |
  |---|---|---|
  | Django secret key, verification key | invalidates sessions, and every bearer link already in applicants' hands unless the old key stays a fallback | new key first, old as fallback until the longest link lifetime passes; on a leak, no fallback, and the outstanding links are reissued |
  | Webhook secret | none, with the two-secret overlap | add the new, switch Documenso, remove the old |
  | Role passwords | none after recreation | rotate in SOPS, recreate the containers |
  | Provider tokens and mail credentials | none after recreation | rotate at the provider and in SOPS, recreate |

- **Never in web:** the owner, retention, admin or backup credentials, the Documenso API token, mail credentials, the
  MiniMax key, the provisioning credential.
- **Egress (H5).** The fetcher fetches applicant-supplied addresses, so it is the SSRF target; it holds no provider
  secret. Its only internal destination is the database (one address and port); every outbound fetch goes through a
  dedicated egress proxy, so the deny can be absolute: loopback, the private ranges, link-local, the shared tailnet
  range (100.64.0.0/10), cloud metadata addresses and the container bridge gateway, in addition to the application's
  own SSRF guard (`018`). The proxy also denies the estate's own production hosts, by name and by every address
  those names resolve to, from an operator-supplied, secret-free list of logical host names (`9kg.39`, section 16);
  without that list it refuses everything (a transient refusal, an unhealthy container). The list is read at start,
  so a change needs a restart (mount its directory, not the file). The fetcher connects with a narrower database role than the app role (only the evidence
  tables), proposed under P6-D-14. The worker reaches only its approved providers. A pilot-gate test proves the fetcher reaches
  none of the denied ranges.
- **The guards:** the pilot needs a narrow, file-based secret path for the worker and an amendment to the guards
  that today refuse provider variables everywhere (P6-D-6). Staging needs none of it.

## 6. Backup and demonstrated restore (proposed)

**One coherent backup set per run:**

1. A dedicated backup login role (a fourth role, P6-D-7): read access granted per table, excluding session data;
   no network login (local socket only in the access rules); its credential only in the backup job.
2. One session opens a REPEATABLE READ read-only transaction and exports its snapshot. `pg_dump` in custom format
   runs against that snapshot inside the database container (matching the server version). The same session writes
   the manifest: per-table row counts and order-independent digests, the migration list, and each `StoredDocument`
   key, size and SHA-256. This is the procedure the local rehearsal (9kg.7) already proves.
3. Then the custody files named in the manifest are copied and verified. Because custody files are write-once, the
   copy is always a superset of the snapshot's rows; a missing file fails the run.
4. A roles manifest (names, attributes, memberships; no passwords). Roles are re-created by provisioning, not
   restored.
5. Everything is written to an in-progress path whose name matches the estate archive's in-progress exclusion, synced,
   checked with `pg_restore --list`, then renamed atomically. Every step has a timeout (the snapshot transaction at
   most 15 minutes, so it never holds back vacuum for long). The output directory is root-owned, mode 0700. A
   receipt records size, SHA-256, schema revision, commit, image digest and PostgreSQL version, and **no personal
   data**.
   - **The manifest is personal-data-adjacent** (row counts reveal volume; digests confirm known content): mode 0600,
     kept only with the dump, never copied into receipts, alerts, after-action reports or pull requests. Evidence
     committed to this repository comes from synthetic runs only.
6. **Destination (production):** the host's logical-dump directory, which the estate's nightly encrypted archive
   already covers along with its offsite legs (VERIFIED in the private backup record). A hook before the nightly
   archive makes a fresh set; a failed dump never fails the estate backup, but it alerts and writes a failed receipt.
   An on-demand run is the pre-deploy backup.

**The restore drill (GATE-STAGING):**

1. Seed synthetic data, including agreements with custody files. Run the backup; record the last committed row and
   the archive time.
2. In a fresh PostgreSQL container with no roles, extract from the archive (not from the source dump), create the
   roles from SOPS through provisioning, and `pg_restore` as the owner.
3. Verify: the migration list equals the manifest and nothing is unapplied; every table digest matches;
   `verify_custody_restore --manifest` passes; the append-only protections refuse the owner; role privileges equal
   the expected set.
4. **Hold every activation by a database write** (a recorded restore hold), not by an operator step the restored
   state might contradict. Start web only; the worker and fetcher stay stopped. `/readyz` is green.
5. **Before the worker starts, the post-restore command** (one command, with a test):
   - **invalidates every outstanding token and session** (confirmation, password setup, withdrawal links; staff
     sessions and second-factor state), because a restore to time T makes tokens consumed after T valid again (H3);
     staff re-authenticate;
   - **replays erasure** from the erasure record kept outside the backups (H4), so a restore never resurrects an
     erased person. The record holds keyed hashes, not raw identifiers; it has its own durable, backed-up store,
     because losing it would let a restore resurrect erased people; and it is itself personal data under POL-10;
   - **re-runs revocation reconciliation,** because mailboxes and staff accounts revoked or disabled after T come back
     as active;
   - **reconciles external effects** (`reconcile_send`, agreement and provisioning reconciliation), because mail
     sent, envelopes issued and mailboxes created after T are unrecorded.
6. Record RPO (failure time minus the last restorable commit) and RTO (extract, restore, verify and start, each
   timed). The drill measures; the owner sets targets (P6-D-7).
7. Negative controls must each fail the drill: a truncated dump, a missing custody file, a wrong migration list, a
   missing role, **and a token consumed after T that still works after the restore.**

**Cadence:** before GATE-STAGING, monthly afterwards (precedent), and after any change to the backup tooling. Drills
on staging use synthetic data only. **A drill with production data runs only on the production host, with no egress
and a destroyed scratch volume, never on the dev box.**

**Erasure against backups (H4; a decision before GATE-PILOT, P6-D-13).** Retention on every backup leg exceeds an
erasure request, and one leg has no automatic expiry (figures in the private backup record). Options:

| Option | Effect |
|---|---|
| (a) accept the window and state it in the privacy notice | simple; the window is unbounded on the leg with no expiry |
| (b) shorten retention for Catalyst | not available: archive retention is estate-wide and the offsite copy is locked |
| (c) crypto-shredding: encrypt custody PDFs and personal fields under keys kept out of the backups, and delete the key on erasure | erasure takes effect in every backup at once; key custody becomes critical |
| (d) an erasure record kept outside the backups and replayed by every restore before the worker starts | a restore never resurrects an erased person; old archives still hold the data until they age out |

**Recommended: (d) now (it is needed whatever else is chosen), and (c) for custody and the most sensitive fields
before GATE-PILOT.**

## 7. Monitoring (proposed)

A host timer runs the health commands in the web image every five minutes and submits typed, content-safe events
(counts and signal names only) to the estate alert floor, which delivers high and urgent events to Buzz. Delivery is
checked from Buzz itself, never assumed (VERIFIED in the private alerting runbook).

| Signal | Source | Exists | Trigger (placeholder until POL-16) |
|---|---|---|---|
| Worker liveness | a heartbeat written each loop | no | stale for more than twice the lease |
| Collector | `collector_health` | yes | any anomaly |
| Oldest pending action | readiness or health | no | over a target age |
| Uncertain sends | `send_health` | yes | any |
| Custody failures | health over custody outcomes | no | any |
| Unresolved hard bounces | health over the 9kg.3 block | no | older than a target |
| Agreement and provisioning uncertain states | health | no | any |
| Backup freshness | the backup receipt | no | older than 26 hours, or failed |
| Restore drill overdue | the drill receipt | no | older than 35 days |
| A check itself failed | exit 2 from any health command | yes | any |
| Aged waits (stages, staff items, pauses, replies, sent agreements, activation) | `aged_waits_health` (9kg.51, section 17) | yes | per class, over its own threshold; only the classes in the page list page |

**Dead-man coverage:** the health timer writes a start marker and a success marker, and a separate estate sweep
alerts on a stale success marker; an outside-in probe of the public intake path; a planted-fault test per signal on
staging.

## 8. Ingress, staff access and web security (proposed)

**Public routes** follow `003`'s routing matrix: only the listed applicant paths reach Django on the public host;
everything else stays on the LMS. Staff, admin and health paths never reach Django on the public host.

**Staff access (POL-13, POL-14):**

| Option | Strength | Cost |
|---|---|---|
| A. A staff host reachable only from **named staff devices** (a tagged tailnet ACL, not the whole tailnet), plus Django two-factor | network restriction and identity both enforced | staff devices must be enrolled; certificates for the name to be settled |
| B. A public staff host behind a Caddy forward-auth | works off the tailnet | a second identity system that can fail open; Django two-factor still needed |
| C. A public staff host with two-factor and an IP allowlist | — | **rejected**: an allowlist does not isolate sessions (`003`) |

**Recommended: A.** The two-factor package must cover the admin site, every focused staff view, the password-reset
path and recovery codes, with a recorded lost-device break-glass procedure, login throttling and an idle session
timeout (Django has none built in, so it is code with a test). Path denial for staff, admin and health paths on the
public host is enforced twice: by the Caddy allowlist and by a Django host-to-URL guard (tested with a staff-host
request on the public listener).

**Webhook (P6-D-4):** its own Caddy site; mounted only by an explicit setting fixed in code (tested), off by default;
POST only, a 64 KiB cap, uniform answers, idempotent handling of duplicate and replayed deliveries. The secret is a
shared bearer value, not a signature: compared in constant time and never in any log (no header logging on that
site). A source allowlist is weak where Documenso's traffic arrives through a shared address, so it is a supplement,
not the control. If the proxy has no rate-limit module, the application's own coalescing (P4) is the fallback.

**Logs (M6):** the application's redaction covers only Django's request loggers (`config/redaction.py` says so). At
the proxy, the token segment of every private path is redacted in every log, including the shared learn site's
existing log and the error log (a skip alone covers only an access log), by a pattern **generated from
`PRIVATE_PATHS`** so the two cannot drift, covering case, percent-encoded and repeated-slash variants. No WSGI access log; the WSGI error log and the container log driver are checked. PostgreSQL
is pinned to `log_statement=none` and `log_parameter_max_length=0` (also on error). Staging asserts the settings and
then searches every log for sentinel tokens.

**Web settings** (all absent today): secure and `__Host-` cookies, CSRF and session cookies secure, CSRF trusted
origins, an idle session timeout, HSTS. Django's proxy SSL header has no hop count, so "one hop" holds only because
the proxy overwrites the header and the web process is reachable only through the proxy's unix socket. The client
address used for throttling is the single value the proxy overwrites, and that is tested. HSTS starts with a short
`max-age`, **without** `includeSubDomains` or `preload` for the shared parent domain. `check --deploy` is a
deploy gate. On the learn host, Catalyst's headers are set inside Catalyst's own route blocks and the LMS's are left
alone.

## 9. Release, rollback and the Learn cutover (proposed)

**Release.** Before any deploy credential exists, the owner applies the `009` section 5.5 proposals: a `main` ruleset
with both required checks (and the merge-guard registration updated), and a protected `release` environment with a
required reviewer. Then: a release PR, the release workflow from `main` at the CI-green head (dry run by default), and
a separately dispatched deploy from the protected environment using the released commit and image digest (P6-D-5).

**Provenance (H6).** The image is built in CI on `main` and carries a build attestation from this repository's
workflow. The host's deploy force-command accepts only a commit and a digest, verifies that attestation before
pulling, and refuses anything else. The deploy credential's identity is bound to the protected `release` environment
and the `main` ref, so no fork or pull-request run can reach it. Third-party actions are pinned by commit. With a
single owner, the protected environment's "required reviewer" is not an independent check; it is recorded as such.
The image also gets a vulnerability scan and a software bill of materials, and is checked to contain no `tests/`,
`.git` or `.beads` content.

**Rollback ladder:** (1) hold effects (activations held, worker stopped); (2) revert the image through the wrapper,
only for a release compatible with the previous image; (3) restore from the pre-deploy backup, then reconcile. **No
rollback undoes** sent mail, issued or signed envelopes, created or revoked mailboxes, links already in applicants'
hands, provider records, or anything written after the backup point.

**The Learn cutover (GATE-CUTOVER), outlined:**

- **Two route sets, because reversal is asymmetric.** R1, entry: the access-request form and its received page. R2,
  return paths: confirmation, password setup, withdrawal and signing return. Once v2 has applicants, their emailed
  links point at R2. A rollback may move R1 back to the first-generation service, but R2 stays on v2 until no v2
  applicant holds a live link.
- **Stages:** preconditions (GATE-STAGING and GATE-PILOT signed; POL-10, 13, 14 and 15 decided; security review; a
  current restore drill; monitoring live) → re-read the live proxy configuration read-only and record its hash, and
  check R2 paths for collisions with the first-generation service (a collision is a blocker) → dark deploy on the VPS
  with every activation held and no routes → rehearse the exact Caddy change and its rollback on staging against
  stand-in upstreams, including path-normalization variants, and prove the LMS default unchanged → a pilot cohort on a
  v2-only link → switch R1 under the estate ingress procedure → rollback by restoring the captured Caddyfile, with R2
  kept.
- **One writer per effect (M8).** v1 and v2 never act on the same applicant and never poll one mailbox. v2 needs its
  own applicant mailbox, with credentials scoped to it and sender authentication (SPF, DKIM, DMARC) aligned for its
  sender. A shared Documenso webhook target or team would give each system the other's applicants' data; v2 needs its
  own secret or team and refuses unknown envelopes uniformly without logging payloads. A per-applicant ownership
  flag is a **precondition for any R1 rollback**, because rolling R1 back to v1 could otherwise create a duplicate
  applicant for an email v2 already holds.
- **Rollback mechanics.** Restoring a captured copy of the shared estate Caddyfile would also revert unrelated estate
  changes made since; the Catalyst routes live in an imported snippet and rollback reverses that snippet only. The
  live configuration's hash and diff stay in the private operations record.
- **Further preconditions:** a privacy notice and a data-protection assessment for real applicants.

## 10. Owner decisions (P6-D-1 to P6-D-15), decided 2026-10-19 as recommended (D-49)

| # | Decision | Options | Recommendation | Earliest blocker |
|---|---|---|---|---|
| P6-D-1 | Staging host | dev box on demand; a second VPS stack; a permanent dev-box stack | **dev box, on demand** (memory checked first; secrets only in tmpfs, destroyed with the gate window) | 6B task 11 |
| P6-D-2 | `staging` environment semantics | a new environment with the same strict fake rules as `test`; reuse `test` | **a new environment, test-strict fakes** | 6B task 1 |
| P6-D-3 | Staff access and two-factor (POL-13, POL-14) | A or B (C rejected, section 8) | **A**, named staff devices, with the package verified | 6B task 9; GATE-STAGING |
| P6-D-4 | Webhook exposure (P4-D-17) | a dedicated host; a path on the learn host; a source allowlist | **its own Caddy site, POST only, allowlisted** | pilot with real Documenso |
| P6-D-5 | Build and release | an image built in CI by digest, or built on the host; apply the `main` ruleset and protected `release` environment | **CI-built digest; protections first** | any deploy credential |
| P6-D-6 | Secret delivery and the guard amendment | settings read per-secret files, never exported; or an entrypoint; or `env_file` | **settings read per-secret files; no `env_file`; a narrow guard change** | pilot |
| P6-D-7 | Backup design and targets | a fourth backup role with per-table read; cadence (nightly plus pre-deploy, or more often); RPO and RTO targets (POL-16) | **fourth role; nightly plus pre-deploy; the owner sets targets** | GATE-STAGING |
| P6-D-8 | The production data directory and Borg | outside Borg's roots with a `093` exception; registered with the runner | **outside, with the exception** | the first VPS host task |
| P6-D-9 | Alert thresholds and who is paged (POL-16) | owner values | the owner sets them; staging uses the placeholders | pilot |
| P6-D-10 | Cutover premise (POL-15) | R1/R2 separation; a separate v2 mailbox; which records move; coexistence; in-flight agreements; cohort order; rollback window; executor; duplicate applicants; Documenso webhook sharing | **R1/R2 separation and a separate v2 mailbox as the premise**; the rest at GATE-CUTOVER | mailbox: pilot; the rest: GATE-CUTOVER |
| P6-D-11 | Shared learn origin or a dedicated applicant host | keep D-09; add a host | **keep D-09 for now**, residual risk recorded | cutover design |
| P6-D-12 | The deployed commit over HTTP | never over HTTP (receipt, label, `manage.py`); or amend `003` and serve it on the unix socket only | **never over HTTP**, so `003` stands | 6B task 3 |
| P6-D-13 | Erasure against backups (POL-10) | options (a) to (d), section 6 | **(d) now; (c) for custody and the most sensitive fields** | (d): 6B task 7; (c): GATE-PILOT |
| P6-D-14 | Split evidence fetching into its own process with no provider secret | split; keep one worker | **split** | 6B task 5 |
| P6-D-15 | Secret rotation policy | the per-class procedures in section 5, with routine intervals the owner sets | **adopt the procedures; the owner sets intervals** | pilot |

## 11. GATE-STAGING acceptance plan (proposed)

Every case runs on the staging stack with synthetic data, and is mapped to tests and gated in a full run the same way
as GATE-S1 to GATE-P5, in 6C.

| Case | Must show |
|---|---|
| TEST-P6-01 | The image: digest-pinned base, hash-locked dependencies, non-root, read-only root filesystem, no secret in any layer, and a commit label equal to the deployed commit. |
| TEST-P6-02 | `check --deploy` is clean under staging settings. |
| TEST-P6-03 | The guards accept `staging`, refuse unknown environments and provider variables, and refuse a production-shaped provider configuration. |
| TEST-P6-04 | Web, worker and fetcher connect only as their roles (the fetcher's narrower); none has an owner, retention, admin or another process's secret in its environment, in `docker exec env` or in its container configuration. |
| TEST-P6-05 | `migrate` runs once as the owner and is idempotent; `/readyz` is red while the schema is behind. |
| TEST-P6-06 | Role provisioning is idempotent; attributes and memberships match; staging credentials differ from test. |
| TEST-P6-07 | Liveness makes no database call; readiness fails on a database outage, a wrong role or a schema behind; the public listener exposes neither. |
| TEST-P6-08 | A deploy through the wrapper's hooks goes green; a planted fault auto-reverts and holds; a revert never runs a backward migration. |
| TEST-P6-09 | A forward-only release is refused by the auto-revert path. |
| TEST-P6-10 | The deployment receipt is written and matches the readback; a mismatch fails the deploy. |
| TEST-P6-11 | Secrets exist only in tmpfs and never in container configuration; rotation by recreation takes effect. |
| TEST-P6-12 | The public proxy forwards only the listed applicant paths, including path-normalization variants. |
| TEST-P6-13 | Sentinel token and webhook-secret strings appear in no proxy, application, WSGI or database log. |
| TEST-P6-14 | Cookie flags, HSTS, CSP and `no-store` on token paths are present; a spoofed forwarded header is ignored. |
| TEST-P6-15 | The staff host is unreachable from any device not enrolled as a named staff device; a login without the second factor is refused; a superuser is refused. |
| TEST-P6-16 | The webhook is unmounted by default; enabled, it refuses a bad secret, a wrong method, an oversized body and a non-allowed source; two-secret rotation works. |
| TEST-P6-17 | Stopping the worker raises the liveness alert, and recovery clears it. |
| TEST-P6-18 | Stopping the fake IMAP server raises the collector alert, verified as delivered (dry run first). |
| TEST-P6-19 | Planted faults raise the uncertain-send, hard-bounce and custody-failure signals. |
| TEST-P6-20 | Dead man: stopping the health timer alerts; stopping timer and worker together is caught by the sweep. |
| TEST-P6-21 | Backup coherence: dump, custody copy and manifest verify; a row committed mid-backup is absent; a failed run keeps the previous good set and alerts. |
| TEST-P6-22 | The full restore drill from the archive, with RPO and RTO recorded and reconciliation before the worker starts. |
| TEST-P6-23 | Each restore negative control fails the drill. |
| TEST-P6-24 | A deploy is refused when the pre-deploy backup is missing or stale. |
| TEST-P6-25 | Rollback rehearsal: image N+1 to N against an expanded schema, and the restore path. |
| TEST-P6-26 | The cutover rehearsal on the staging proxy: switch and rollback, the LMS default byte-identical, R2 paths kept. |
| TEST-P6-27 | A dark deploy makes zero provider calls with every activation held. |
| TEST-P6-28 | Staging has no route to production hosts or real providers, and holds no production secret; the fetcher's egress proxy refuses the estate's production hosts by name, by resolved address, on redirect and after a DNS change (`9kg.39`). |
| TEST-P6-29 | After a restore, every token and session issued before it is refused, a token consumed after the restore point stays refused, erasures are replayed, and revocations reconciled, before the worker starts. |
| TEST-P6-30 | The fetcher reaches only the database and the egress proxy; through the proxy it reaches none of the denied ranges (loopback, private, link-local, the tailnet range, metadata, the bridge gateway); it holds no provider secret. |
| TEST-P6-31 | The deploy force-command refuses an image digest without this repository's attestation, and no fork or pull-request run can reach the deploy credential. |
| TEST-P6-32 | Django refuses staff, admin and health paths on the public host name, independent of the proxy. |
| TEST-P6-33 | The proxy's skip matcher equals `PRIVATE_PATHS` (generated from it), and PostgreSQL's logging parameters are as pinned. |
| TEST-P6-34 | Duplicate and replayed webhook deliveries change nothing twice. |
| TEST-P6-35 | Backup receipts, alerts and committed evidence contain no personal data; the manifest and output directory have their modes. |
| TEST-P6-36 | Each secret-class rotation works as section 5 states, including link fallback and a leak rotation. |
| TEST-P6-37 | The image has a vulnerability scan and a bill of materials, and contains no test, git or beads content. |
| TEST-P6-38 | A planted sentinel never reaches an alert delivered to Buzz. |

### 11.1 The evidence register (`9kg.44`, 2026-10-23; reviewed the same day)

A gate count can be read as more than it proves. `tests/acceptance.py` therefore carries, beside the case map, an
evidence register (`P6_EVIDENCE`): one explicit entry per numbered case, with the proof types in order (`pytest`,
the gated run; `drill`, a script above run on the staging stack, whose commit and section 16 record `DRILLS`
carries; `inspected`, a configuration or run read and recorded; `canary`, one real delivery through a real provider;
`walkthrough`), each with an environment (a drill's is the staging stack on the dev box unless the proof names
its own, as TEST-P6-26's cutover rehearsal does for its stand-in Learn site, `9kg.64`), a revision (a commit or a workflow run id for every proof but pytest, whose
revision is the run) and a record pointer; what the gated tests show (`behaviour`, or `shape` where they pin only
the code's shape and a drill shows the behaviour: TEST-P6-08, 24, 25, 26 and 31); completeness (`full`, or
`partial` with the residual bead and what it still has to show); and the approval boundary the evidence is good up to
(GATE-STAGING for a full case; for a partial one, the earliest boundary its residual bead blocks, from `029` section
13.1: host preparation `9kg.28` for the host clauses 028 carried on `9kg.20` and `9kg.22`, the canaries for `9kg.27`,
release preparation for `9kg.37` and `9kg.38`, and so on). There are no optimistic defaults: a case without an
entry, an unknown drill or proof type, a partial case without its residual, a residual bead without a boundary or a
proof without a commit or run id is refused as data (`check_register()`), and a full run whose register is refused
exits 1.

The per-gate report in `tests/conftest.py` reads the register, not this text. For every gate it counts the numbered
cases apart from the supporting groups; for GATE-STAGING it stamps the run's commit, prints each case's proofs,
completeness and boundary on its line and, on a second indented line, each proof as type, environment and revision
with the residual of a partial case; lists TEST-P6-27 as `LIVE ONLY` (never as a pytest result); and ends with the
register totals: full cases, of which proven by this run (full, PASS and behaviour: a shape-only case is never
counted as proven, nor is the live-only case), and partial cases with their residual beads. A run that can be full
(no file, `-k` or `-m` selection) first deletes the last `register.json`, so a refused, crashed or deselected run
never leaves an earlier run's file behind (`9kg.64`). At the end of a full run
it writes `register.json` (`CATALYST_EVIDENCE_REGISTER`, or the repository root, ignored by git): the rows, the run's
commit, its exit status, the image digest when known, each proof's record pointer, the summary, GATE-STAGING's
supporting-group statuses and every gate's numbered and supporting counts, so the go/no-go package reads it
rather than transcribing the report. The run's commit is `CATALYST_RUN_COMMIT`, which `scripts/test.sh` exports from
the host's `git rev-parse HEAD` (with `-dirty` appended when the working tree has changes) and `compose.yaml` passes to the test service (the image has no git), else CI's
`GITHUB_SHA`; CI uploads `register.json` from the runtime job as the `evidence-register` artifact whatever the
result, through `actions/upload-artifact` pinned by commit, a step that cannot fail the required check
(`continue-on-error`); the file is written to `register.json.tmp` and moved into place (`9kg.64`). The gate itself is unchanged: a full run still needs every numbered case and
supporting group PASS. `tests/test_acceptance.py` checks the register's shape and its refusals, that it reproduces
after-action report `028` section 4 case by case (21 proven, one of them on a stand-in, and 17 partly; a later change
to a case's completeness must carry a `since_028` note in its entry, so the AAR stays historical and the register and
the report cannot drift apart silently), and the report shape, `register.json` and the failing full run in a child
run. Deferred to a later task, since it needs git state: marking a proof for review when an implementation file
listed against it changes.

### 11.2 The personal-data scan (`9kg.40`, TEST-P6-35, 2026-10-23; reviewed the same day)

`config/personal_data_scan.py` (standard library only, so the host runs it with its own `python3`, which must be
Python 3.11 or later: the secret-assignment pattern uses a possessive quantifier, which `re` accepts from 3.11 and
earlier versions refuse at import, `9kg.64`) scans four
input classes for personal data: the committed evidence (`EVIDENCE_PATHS`, globs: every after-action report,
analysis evidence, test evidence and decision record filed under `000-docs`, this specification with its section 16
records, and `029`; a new record of one of those classes is scanned without a change to the list, which a test
checks), backup and restore-drill receipts, alert text (a log or stdin) and the deployment receipt. Its patterns
are classes, not people: an email address outside the reserved example domains (the domain itself or a subdomain of
it; an address at a domain that merely ends in the letters of a reserved one is a hit), a phone number with separators or a bracketed area code, a street address, a
fixture person's name (case-insensitive; the fixtures' generic labels only in their exact case), a secret assignment
(the keyword alone, inside a wider identifier such as `DB_PASSWORD` or as a quoted key, with a value not marked
synthetic or redacted and not a code expression), a bearer token, a private-key block, a long mixed-case token
(judged per path segment: a digest is hex, a path and a slug are names) and an IPv4 address that is neither loopback,
unspecified, link-local nor a documentation address. Each document is scanned line by line and again as
whitespace-normalised paragraphs, so a name or number split across a wrapped line is found and reported at the
paragraph's first line. It prints the location and the pattern's name, never the matched value (a non-UTF-8 input
is reported with a fixed message); it exits 0 clean, 1 on a hit and 2 when nothing was scanned or an input could
not be read, so an empty result is meaningful only when something was read.

**Floor, stated.** The fixture-name list detects the fixtures' names and no real person's; a deny-list of invited
names on the host would be an owner decision and is not built. An unseparated phone number, a postcode and a
free-text name are below the pattern floor. The scan is a floor under the evidence, not proof of absence.

It runs in CI with the suite (`tests/test_personal_data_scan.py`: the committed evidence passes; a planted
synthetic address, name, phone, email and token in each input class fails the scan with the value never printed;
zero files or an unreadable input fails closed; reserved addresses, digests, run ids, timestamps, CIDR ranges and
production-shaped paths are not hits) and on the host in the receipt step: `receipt.sh` writes the deployment
receipt to a pending file (removed on any exit), scans it together with the bound pre-deploy backup's receipt, sets
its mode and only then moves it into `receipts/`; a hit removes the pending file and fails the step for the operator.
Today `receipt.sh` runs after a promotion in the force-command's sequence, not on a wrapper hook, so the wrapper and
the alert floor learn of a withheld receipt through that sequence; the wiring of the receipt step into the wrapper's
notification path waits on 6B.11's host work. The step is tested under docker stubs and ran in the deploy drill on
the dev box (section 16, PL batch 5). Not yet wired: restore-drill receipts and the scheduled backup job's receipts
(both written by scripts that do not call the scan yet) and alert text (codes only by construction, `health.sh`);
the register carries TEST-P6-35 as partial against the dark deploy, `9kg.31.5`, with those surfaces named. The scan
does not replace the alert message rule in `health.sh` or gitleaks (credentials in history); it adds the
personal-data check `009` section 5.1 listed as manual.

## 12. 6B task graph (proposed)

R = repository-local (reviewed PRs, synthetic tests only). H = needs a separate host authorization from the owner.

| # | Task | Type | Depends on |
|---|---|---|---|
| 1 | A `staging` environment and its guard rules, with tests | R | P6-D-2 |
| 2 | Production-grade cookie, HSTS, proxy-header and session settings, and a `check --deploy` test | R | 1 |
| 3 | Liveness and readiness endpoints on the unix-socket listener | R | 1 |
| 4 | Worker heartbeat and one Catalyst-wide health command (custody, provisioning, pending age, hard bounces) | R | 3 |
| 5 | Dockerfile, per-secret file reading in settings, the staging compose file (web, worker, fetcher) | R | 1, P6-D-6, P6-D-14 |
| 6 | Staging and production role provisioning (explicit environments, credentials from files), and the backup role | R | 5, P6-D-7 |
| 7 | Backup and restore tooling: the coherent set, manifest, receipts, the restore hold, the post-restore command (token and session invalidation, erasure replay, revocation and effect reconciliation), the drill harness and its negative controls | R | 6, P6-D-13 |
| 8 | Staging Caddy configuration: the generated log-skip matcher, webhook limits, path-normalization tests; the Django host-to-URL guard | R | 5, P6-D-4 |
| 9 | Staff two-factor | R | P6-D-3 |
| 10 | Deploy adapters (capture, deploy, smoke, notify, receipt, forward-only check, attestation verification) and the CI image build with attestation, scan and bill of materials, tested against the wrapper's disposable harness | R | 3, 5, P6-D-5 |
| 10a | Secret rotation runbook and tests | R | 5, P6-D-15 |
| 11 | Bring up staging on the dev box and run the cases | **H** | 1 to 10, P6-D-1 |
| 12 | Alert wiring on the dev box (dry run first) and the liveness sweep registration | **H** | 4, 11 |
| 13 | Staging backup into the dev box's archive and the measured restore drill | **H** | 7, 11 |
| 14 | The GATE-STAGING evidence map and the after-action report (6C, for the owner) | R | 11 to 13 |

Pilot and cutover work (the VPS force-command, the Borg pre-archive hook, the read-only re-read of the live Caddy
configuration, real provider credentials) is outside 6B and needs its own authorization.

## 13. Risks

- **R1. Auto-revert can mask a data change.** The image reverts while a migration stays applied; forward-only
  marking is mandatory (section 4).
- **R2. Health versus `003`.** Resolved by never returning the commit over HTTP (P6-D-12).
- **R3. Backup retention versus erasure** (section 6, P6-D-13): a GATE-PILOT blocker.
- **R8. The fetcher is the SSRF target;** only the egress deny and the process split keep it away from credentials and
  internal services.
- **R9. The deploy force-command can decrypt every secret;** provenance verification limits what it will run.
- **R4. A nightly dump is a coarse RPO;** restore without reconciliation could duplicate mail or envelopes.
- **R5. Staging on the dev box** adds memory pressure to a box with a strict do-not-break list; it stays on demand.
- **R6. A `staging` environment weakens "no provider outside test"** unless it keeps test's strict fake rules.
- **R7. Not deciding** leaves production tokens unreadable and `main` bypassable.

## 14. Unknowns (to settle in 6B or before the host tasks)

Whether custody document keys embed personal data (they are random hexadecimal names in code; to confirm against
stored rows); collisions between v2's return paths and the first-generation service's live routes (the live proxy
configuration was not read); whether the first-generation service shares the applicant mailbox or the Documenso
webhook target; whether the estate restore tooling tolerates a custom-format set; the tailnet ACL model;
free ports and the installed Caddy modules (rate limiting, log filters); whether the Borg exclusion patterns cover
Catalyst's encrypted secret files; staff count and tailnet membership; certificates for a tailnet-only name; the alert-floor
interface; PostgreSQL 16 option behaviour for snapshot dumps and role-only dumps (to confirm against the official
documentation).

## 15. The security and privacy review (0.1.1)

`catalyst-security-privacy` reviewed 0.1.0 on 2026-10-18 and found one BLOCKER and seven HIGH. All were folded in as
specification text; nothing is built.

| Finding | Disposition |
|---|---|
| B1 private estate paths, host names, retention figures and topology in a public document | removed; symbolic names here, concrete values in the private operations record |
| H1 secrets in the process environment | per-secret files read by settings, never exported; tests on `docker inspect` and `docker exec env` (section 5) |
| H2 no rotation story | per-class procedures, including link fallback and leak rotation; TEST-P6-36; P6-D-15 |
| H3 a restore revives consumed tokens, sessions and revoked access | a database restore hold and a post-restore command; TEST-P6-29 (section 6) |
| H4 erasure against backups | options (a) to (d); (d) now, (c) before pilot; P6-D-13 |
| H5 one worker holds the SSRF surface and the credentials | a separate fetcher with no provider secret behind a host egress deny; TEST-P6-30; P6-D-14 |
| H6 deploy credential and image provenance | attested CI image, a force-command that verifies it, identity bound to the protected environment; TEST-P6-31, 37 |
| H7 the commit over HTTP against `003` | never over HTTP; unix socket; Django host guard; P6-D-12; TEST-P6-32 |
| M1 backup role and manifest | per-table read without sessions, local-socket login, manifest treated as personal-data-adjacent; TEST-P6-35 |
| M2 in-progress naming and modes | the in-progress name matches the archive's exclusion; directory 0700 |
| M3 drills with production data | production host only, no egress, destroyed volume |
| M4 staff access | named staff devices; option C rejected; two-factor scope, break-glass, throttling, idle timeout; Django host guard |
| M5 webhook | own site, constant-time compare, idempotent, allowlist only a supplement, rate-limit fallback; TEST-P6-34 |
| M6 log scrubbing | matcher generated from `PRIVATE_PATHS`, every log including the shared site's, PostgreSQL parameters pinned; TEST-P6-33 |
| M7 proxy header and HSTS | unix socket, the overwritten client address, short HSTS without subdomains |
| M8 cutover | scoped v2 mailbox with aligned sender authentication; separate Documenso secret or team; ownership flag before any R1 rollback; snippet-based rollback; privacy notice and assessment |
| Re-review (0.1.1) | B1 cleared; remaining private file names replaced by generic references; P6-D-6 aligned with H1; the fetcher's single database destination and egress proxy; the erasure record as keyed hashes in its own durable store; stale loopback and process text corrected. Verdict: MERGEABLE-AS-PROPOSAL |
| LOW items | image scan and bill of materials (TEST-P6-37), sentinel never reaches Buzz (TEST-P6-38), a snapshot timeout, dev-box tmpfs secrets destroyed with the gate window |

## 16. The 6B records

**6B.1, the staging environment (P6-D-2).**

- `config.guards` allows `staging` and adds `SYNTHETIC_ENVIRONMENTS = {test, staging}` with `synthetic(env)`.
- Every setting that was test-only for the fakes is now allowed in staging under exactly the same rules:
  - the agreement provider: https, a `.test` host, a loopback pinned address, custody storage outside the
    repository, at most two webhook secrets;
  - the provisioning adapter (a test fake) and a `.test` domain;
  - the assessment `test` model;
  - evidence fixtures, which staging also limits to `.test` hosts, a loopback fixture address and an absolute CA
    path.
- Runtime code follows the same helper: evidence fixture sources (`assessments.fetch` and `collection`) and the
  test model (`assessments.agent`).
- Still test-only:
  - the named test mail host (the staging sink is on loopback, since the fakes share the worker's network
    namespace);
  - the send-evidence source;
  - the Documenso webhook route, which is unmounted in staging until the 6B.8 setting.
- Staging links must be https. Every non-synthetic environment, production included, still refuses every fake, and
  provider variables are refused everywhere.
- **After the security review of PR #59** (no blocker or high; two medium, both fixed):
  - staging's default mail backend is a private file sink, never the console, whose output would carry bearer links
    into the container log; the guards refuse the console backend in staging and require an absolute
    `EMAIL_FILE_PATH`;
  - staging tests now cover its runtime branches: a fixture fetch, the test model, and a private mail peer refused as
    in development.
- **Evidence:** `tests/test_guards.py` (6B.1 tests), the staging leg of the TEST-P3-05 fetch test and the updated
  TEST-P5-23 test.

**6B.2, web security settings.**

- Every environment: a 30-minute idle session timeout (the expiry slides on every request; Django has none built
  in), sessions end when the browser closes, and the CSRF cookie is not readable by scripts.
- Outside test and development (staging and anything later):
  - secure `__Host-` session and CSRF cookies;
  - the proxy's https header trusted (the web process listens only on the proxy's local socket);
  - https redirects, except the two health paths reached through that socket;
  - HSTS of 300 seconds without subdomains or preload, with Django's two warnings about that silenced
    deliberately (P6-D-3);
  - CSRF trusted origins limited to the public base URL.
- Staging links may not name a production host (`intentsolutions.io` or a subdomain), closing the PR #59 LOW item.
- **After the security review of PR #61** (no blocker or high; five medium):
  - every response gets a Content-Security-Policy (`config/security_headers.py`): same-origin only, inline styles
    but no inline script, no framing, plugins, base rewriting or cross-site form posts; the audited PDF download
    keeps its stricter sandbox;
  - framing, opener, no-sniff and SameSite values are pinned rather than left to Django's defaults;
  - staging refuses a wildcard or production entry in `ALLOWED_HOSTS` and any host name that is not plain ASCII;
  - behaviour tests read real responses (`tests/test_web_security.py`);
  - moved to their tasks: proof that the proxy header cannot be forged (6B.5 and 6B.8), and an absolute session
    lifetime with scheduled session clean-up (6B.9).
- **Evidence:** `tests/test_web_security.py` (redirects and exempt health paths, HSTS only over https, cookie
  attributes, CSP and framing headers, no session for an anonymous page, an idle session refused) and
  `tests/test_startup.py`:
  - `manage.py check --deploy --fail-level WARNING` is clean under staging settings;
  - the cookie and HSTS values, read from a staging process;
  - a production link host refused in staging;
  - local environments keep plain cookies but still time out.

**6B.3, liveness, readiness and the public-host guard (P6-D-12).**

- `/healthz` answers `ok` with no database call. `/readyz` answers `ready`, or `not-ready` with status 503. It
  checks that the database login is the application role (the strict web check from ADR-14) and that every
  migration is applied. Neither ever returns a version, commit or reason; the reason goes to the log as a short code.
- **Deviation from section 4:** the oldest pending-action age is not part of readiness. A backlog must not mark a
  process unready, because the deploy wrapper would then revert a healthy release. It belongs to the health command
  and alerting (6B.4).
- `config.health.HostGuard` is an allow-list by host name, independent of the proxy (TEST-P6-32):
  - the health paths answer only on `CATALYST_LOCAL_HOSTS` (the proxy's socket);
  - the staff screens and the admin answer only on `CATALYST_STAFF_HOST`, which staging requires;
  - in test and development with no staff host, staff and admin answer on any host but the public one;
  - paths are normalised first (repeated slashes, dot segments, case), and every refusal is a 404.

  The guards refuse a staff or local host that is a wildcard, a domain pattern or the public host.
- After the security review of the first version (one HIGH: it denied only the public host and so failed open for
  every other allowed host), the guard became the allow-list above. `/readyz` reuses its answer for five seconds,
  so probes cannot load the database, and the header test asserts the full header set. The WSGI server's own
  `Server` header is checked on staging (NOT RUN here).
- **Evidence:** `tests/test_health.py`.

**6B.4, the worker heartbeat and the health command.**

- The worker rewrites a heartbeat file (`CATALYST_WORKER_HEARTBEAT_FILE`) atomically on every loop, including while
  the database is down. A failed write never stops the worker; the stale heartbeat raises the alert instead.
- `manage.py catalyst_health` (`config/system_health.py`) prints JSON (counts and signal names only) and exits 0
  when healthy, 1 on any anomaly, and 2 when the check itself fails. It adds these signals to the correspondence
  ones:
  - a missing or stale heartbeat (default: twice the lease);
  - the oldest due action still queued (moved here from readiness, 6B.3), and running actions whose lease expired
    long ago;
  - agreements in an uncertain or failed state, and custody failures;
  - provisioning still settling (an uncertain create or verify, a found mailbox);
  - provisioning staff items that mean something went wrong (alert at once; they clear when staff resolve them),
    and routine waiting items (checklist, name review, blocked) only once overdue;
  - a revocation round that never ran;
  - hard bounces unresolved past a target.
- The thresholds are configurable placeholders until POL-16 (P6-D-9).
- After the QA review of PR #64 (two HIGH, four MEDIUM):
  - terminal provisioning states no longer alert forever; the open staff item is the signal, and it clears when
    staff resolve it;
  - every failure of the check itself, including a malformed report, exits 2 and never 1;
  - the heartbeat also beats on every lease renewal (in the write phase, after the external call); a handler that
    makes several slow calls before its first renewal can still look quiet for longer, which twice the lease allows
    for one call each of at most half the lease;
  - staging requires a heartbeat file;
  - tests now cover each signal both firing and clearing, with a real leak check on seeded applicant data.
- **Runbook note:** a stopped worker (a deploy, for example) leaves the heartbeat to age; the alert fires only past
  twice the lease.
- **Evidence:** `tests/test_system_health.py`:
  - the heartbeat's atomic write and failure tolerance, and the worker beating;
  - a quiet system reported healthy, with counts only;
  - a dead worker detected and cleared on recovery (TEST-P6-17);
  - a backlog and an expired lease;
  - an unknown mailbox create reported (TEST-P6-19);
  - a failing check exits 2 without leaking its message.

**6B.5a, the image, secrets from files and the fetcher split (P6-D-6, P6-D-14).**

- **`Dockerfile`:**
  - It builds from the same Python image digest the tests run on, with dependencies installed only from the
    hash-locked requirements.
  - It runs as a non-root user (uid 10001) with read-only application files, records the commit as an image label
    and a file, and collects the admin's static files at build time using throwaway values.
  - The web command is gunicorn on the proxy's unix socket, with no access log.
  - The `production` target carries the application only. The `staging` target adds only the two synthetic fakes.
- **`.dockerignore`** denies by default, so tests, history, the tracker and the docs never enter the build context.
- **Secrets:** outside test and development, `config/settings.py` reads each secret from its own file in
  `CATALYST_SECRETS_DIR`, named after the setting in lower case without the prefix, and never exports it. The
  guards refuse a secret in the environment there, and a missing directory or file stops start-up.
- **Worker split:** `run_worker --only` and `--exclude` split the process kinds. The fetcher runs only
  `fetch_evidence`, and the worker runs everything else. An unknown kind is an error.
- **WSGI server:** gunicorn 23.0.0 is added to the hash-locked requirements.
- **Evidence:**
  - `tests/test_image.py`: the base digest, hash locking, the non-root user, no access log and only a socket, no
    secret in any layer, and the build context;
  - `tests/test_startup.py`: secrets from files, a secret in the environment refused, a missing directory or file
    refused;
  - `tests/test_worker.py`: kind selection.

  Building and inspecting the images needs Docker, which the test containers lack; they were built and inspected
  locally (the pull request records it), and staging (6B.11) runs them.
- **After the security review of PR #65** (no blocker, two HIGH, seven MEDIUM):
  - gunicorn gets `--umask 0o117`, so the socket is `0660` (the proxy's group only), plus `--worker-tmp-dir
    /dev/shm` for the read-only root and an explicit error log. A run with a read-only root, tmpfs mounts and
    secrets mounted as files, with no database, showed the socket at `660`, `/healthz` answering 200 over it, and
    no secret value in the process environment or `docker inspect`.
  - The fetcher (`CATALYST_PROCESS_ROLE=fetcher`) no longer needs the link-signing key.
  - A worker with nothing to run refuses to start.
  - Secret-shaped files are excluded from the build at any depth.
  - A secret file loses only its line ending. An empty file is missing, and an unreadable one (a directory, the
    wrong permissions, non-UTF-8) stops start-up, naming the secret but never its bytes.
  - Settings and the guards share one list of secret names.
  - A process with mounted secrets may not call itself `development`.
  - `pip-audit` of the locked dependencies found no known vulnerability.
  - Carried to 6B.5b (recorded on its bead): per-kind secret mounts, the fetcher's database role and egress, the
    pinned environment and worker arguments, the tmpfs and socket-directory mounts, and tests against the running
    stack.
- **6B.5b** (next): the staging compose stack.

**6B.6, database roles for staging and the backup role (P6-D-7).**

- `scripts/provision_db_roles.py` provisions in test, development and staging; production stays refused. In
  staging every password comes from a file in `CATALYST_SECRETS_DIR` (`owner_password`, `app_password`,
  `retention_password`, `backup_password`, `admin_password`), never the environment, and the owner gets no
  `CREATEDB` (only test needs it).
- **A fourth role, `backup`** (`CATALYST_DB_ROLES["backup"]`): a login with no other attribute, which reads every
  table except `django_session` and writes nothing (`workflow/migrations/0003_backup_role_reads.py`). Grants stay
  explicit per table: a later table gets nothing until its own migration grants it, and
  `tests/test_db_roles.py` fails until it does.
- **Deviation:** the narrower fetcher database role (P6-D-14) is deferred out of 6B.6. It must land before the
  staging bring-up (6B.11), which its bead blocks, and so also before the pilot. The exact grant set needs tracing
  every table the fetch path writes.
- **After the security review of PR #66** (two HIGH, six MEDIUM):
  - role passwords are hashed with SCRAM in the client, and that session logs no statement, so a clear password
    never reaches the server, its log or `pg_stat_activity`;
  - the backup role reads every sequence (`pg_dump` needs their values) but can neither draw nor set one;
  - after provisioning, the script reads the attributes and memberships back and fails if they differ;
  - the grant migration names a missing role clearly (provision, then migrate);
  - the backup role holds staff password hashes and applicant contact data by design: a restore needs them, and
    the dump is treated as personal data (section 6).
  - **Intended, not enforced here:** the provisioner's staging gate is the environment name (production
    provisioning is not authorized at all), and the backup role's local-socket-only login is host configuration
    for 6B.7 and 6B.13.
- **Evidence:** `tests/test_db_roles.py`:
  - the backup role reads every table but sessions and writes none;
  - it reads history but cannot change it, and cannot read sessions;
  - staging provisioning refuses passwords in the environment, needs the files, and production stays refused.

  The protection inventory in `tests/conftest.py` now covers the backup role's privileges too.

**6B.7a, the backup and restore commands and the restore hold (P6-D-7).**

- **`manage.py catalyst_backup`** (`config/backup.py`), run as the backup role, writes one coherent set:
  - a REPEATABLE READ, read-only snapshot of every table except `django_session` (COPY), with a 15-minute
    statement timeout;
  - the custody files those rows name, each checked against its record;
  - a manifest: per-table row counts and order-independent digests, each document's key, size and digest, and the
    migration list;
  - a receipt holding counts, digests and versions only.

  It writes to `<name>.pending` and renames when complete. A failed run removes everything it started. The set is
  `0700` and its files `0600`.
- **`manage.py catalyst_restore`** runs as the bootstrap administrator into an already-migrated, unused database.
  - It refuses before loading anything unless the receipt matches the manifest, every table copy and custody file
    matches its digest, and the target is at the backup's migrations.
  - It loads with triggers off for the load only, resets the sequences, re-checks every loaded table against the
    manifest, and restores the custody files into an empty directory.
  - It records the **restore hold**: a database row the worker ledger honours by claiming nothing until the
    post-restore step lifts it.
- **After the security review of PR #67** (one BLOCKER, three HIGH, six MEDIUM):
  - **A restore never touches a database in use or not named.** It requires `--confirm-database` to match, refuses
    while another session is connected or the core tables hold rows, and sets a lock timeout.
  - **A tampered set cannot write elsewhere.** Every custody key must have the safe shape. The set's tables must
    equal the target's. The set must be private with no links. The manifest can also be checked against a digest
    given on the command line.
  - **A database error prints only its class and code,** never the row it quoted.
  - **The hold is checked inside the claim query, and a trigger refuses the application role any change to it.**
    Tests show that nothing is claimed while it is present, at the worker level and for a staff-initiated kind,
    and that it is claimable once the owner lifts it.
  - **The custody copy and restore are safer:**
    - the custody files are copied after the snapshot, with an idle-transaction timeout and a wall-clock deadline;
    - every file and directory is fsynced before the rename;
    - the restore stages and verifies the files before the load and moves them after the commit;
    - every loaded table is re-checked before the hold is written;
    - a hold already in the set is tolerated.
  - **The receipt carries no counts.** The command prints only the set's name and the manifest digest.
  - **Recorded:** the hold does not gate the web process. A restored database serves no web traffic until the
    post-restore step has run.
- **Not in 6B.7a:**
  - the post-restore step itself (6B.7b): invalidating links and sessions, revocation rounds, reconciliation, and
    lifting the hold;
  - wiring the backup into the estate archive (6B.13);
  - running `pg_dump` (the COPY-based set is what the 9kg.7 rehearsal proved; the backup role can also read
    sequences, so `pg_dump` remains possible).
- **Evidence:** `tests/test_backup_commands.py`:
  - a set restored elsewhere byte for byte, with its files and the hold, then verified;
  - the worker claims nothing while the hold is present;
  - a truncated table copy, a mismatched receipt and a missing custody file are each refused before anything loads;
  - a target at other migrations is refused;
  - a failed backup leaves nothing that looks usable.

**6B.7b, the post-restore step (026 section 6 steps 4, 5 and 7).**

- **`manage.py catalyst_post_restore`** (`config/post_restore.py`) runs as the owner after `catalyst_restore`. It
  refuses unless the restore hold is present and `--confirm-database` names the database. It runs in two phases,
  and **neither the web nor the worker process starts until both have run** (this corrects step 4 above, which
  started web first).
- **The review run** (no `--lift`), in one transaction:
  - closes every outstanding applicant link (unused confirmation links, open password links, open withdrawal links)
    and opens a staff item for each applicant left without one;
  - turns a password set that was in flight into "outcome unknown", with a staff item to send a fresh link through
    the existing reissue path;
  - **makes every staff password unusable and ends every staff session,** so staff disabled or re-keyed after T
    never return. The owner checks the roster and re-issues passwords (`manage.py changepassword`) only after the
    last review run, because each review run disables them again;
  - lets every running action expire its lease;
  - queues a revocation round for every stopped request whose access removal is not complete;
  - reports every queued or running action that reaches the outside world (the non-redeliverable kinds plus the
    redeliverable ones that still send mail, call a model or fetch), per kind and status, with action ids, and
    makes each one uncertain with a staff item. A decline notice's freeze (`send_decline`) is one of them: it is
    never re-queued by itself. The owner compares it with the Sent folder before `--outward-checked`, and the
    decision-maker settles its item: re-queue by hand only when no notice left, otherwise leave it. That staff
    decision is the accepted remedy for an uncertain decline after a restore;
  - records on the hold that the review happened.
- **The lift run** (`--lift`) refuses unless a review run happened and the operator confirms `--outward-checked`
  and `--no-closures-after-backup`.
- **Stated limits,** which is why lifting needs those two confirmations:
  - **Expiring a lease** makes the ledger run the action again. A handler reconciles instead of repeating only
    where the restored record shows its exchange began. An exchange after T leaves no mark, so the operator must
    check the reported actions against the providers and cancel any already done.
  - **A closure after T** is not in the restored database at all, so its access removal cannot be found here. The
    operator confirms there was none, or removes that access again by hand.
- **Not here: erasure replay** (P6-D-13 option d). Erasure itself does not exist yet (POL-10). The bead
  "Replay erasures after a restore before any real personal data is backed up" must land before the pilot.
- **Carried from the review of PR #67:**
  - the session check counts only client sessions, so autovacuum cannot refuse a restore;
  - an existing custody directory is set to 0700;
  - the backup prints only the set's name and digest.
- **Runbook rules** (for 6B.13 and production):
  - **Record the digest.** Keep the printed manifest digest with the set, and always restore with
    `--expect-manifest-sha256`. Whether this is mandatory for production is the owner's decision; it is the default
    here.
  - **If moving files into place fails after the commit,** the database is loaded and held. Copy the remaining
    files from the set's `custody/` directory and run `verify_custody_restore --manifest` before the post-restore
    step.
- **After the QA review of PR #68** (four HIGH, five MEDIUM): staff passwords, the two lift confirmations, staff
  items for stranded applicants and stranded setup requests, the report's scope and ids, an accurate revocation
  count, and the negative-control tests.
- **Evidence:** `tests/test_post_restore.py`:
  - the 026 section 6 step 7 negative control: a confirmation link and a password link that worked before the step
    are refused after it, and staff items are opened;
  - staff passwords and sessions from before the restore never return;
  - withdrawal links close, and an in-flight password set becomes unknown;
  - unfinished access removal gets exactly one new round, even across runs;
  - the report lists queued and running outward actions with ids, and running ones are recovered;
  - lifting needs a review run and both confirmations, after which work resumes;
  - a refusal without a hold or a named database.

**6B.8, the staging proxy (026 section 8; P6-D-4).**

- **`deploy/staging/Caddyfile`** is generated by `scripts/render_caddyfile.py` from the application's own path
  lists. A test fails while the committed file and the rendering differ.
- **The public site** serves only the applicant routes: the request form, its received page, and the
  confirmation, password and withdrawal links. Every other path on the public host is a 404, so the staff screens,
  the admin, the health paths and any webhook never answer there; `HostGuard` refuses them too.
- **Logs:** in every log line, the error log and the default logger included, the token segment of a private path
  (generated from `config.redaction.PRIVATE_PATHS`) is replaced with `REDACTED`. The pattern ignores case, percent-encoding
  and repeated slashes. Lines are kept for the audit trail.
- **Request size:** request bodies are capped (128 KB public, 1 MB staff).
- **Headers:** Caddy is the edge and trusts no proxy. It sets `X-Forwarded-Proto` and `X-Forwarded-For` (the real
  peer address, for throttling) itself and drops the client's `X-Forwarded-Host`. Its own responses carry
  set-if-absent `nosniff` and `no-referrer`, no `Server` header, and `no-store` on the 404.
- **The proxy instance:** the upstream is the web process's unix socket, with connection timeouts against slow
  clients. This is a dedicated staging instance with its admin API off (a change means a restart). It is never
  imported into the shared estate Caddyfile.
- **Certificates:** `tls internal` uses Caddy's own root. Only staging devices install it, its key stays on the
  host, and it is never used for production names.
- **The staff site** binds to a private address (the tailnet address on the staging host, never all interfaces)
  and carries only the staff screens and the admin's static files.
- **Webhook:** there is no webhook site; it is not mounted until the pilot (P6-D-4).
- **Guards:** they refuse a staff host that is also a local health host (from the PR #63 review).
- **After the security review of PR #69** (two HIGH, seven MEDIUM):
  - tokens are redacted in every log rather than skipped from the access log alone (a 502 from the proxy logs the
    full URI to the error log);
  - there are no trusted proxies;
  - the real client address is passed;
  - Caddy-generated responses carry safe headers;
  - there are timeouts, and hidden dotfiles under `/static`;
  - the renderer checks its prefixes;
  - a URLconf walk proves every token route is a private path.
- **Validation:** `caddy validate` (as an ordinary user) accepts the file.
- **Not proven here, carried to 6B.11 against the running stack:** what Caddy does with real requests:
  - path normalization variants;
  - a forged `X-Forwarded-Proto` from a private address, and `Host: localhost` sent to the public listener;
  - sentinel tokens absent from every log, including after a 502 with the socket down;
  - the actual listening addresses, with a preflight that refuses `0.0.0.0`, `::` or an empty staff bind.
- **Evidence:** `tests/test_staging_proxy.py` (the rendering, the log skip matching `PRIVATE_PATHS`, the public
  allow-list, the staff site, the headers and the absence of a webhook) and the overlap test in
  `tests/test_startup.py`.

**6B.9, staff two-factor (026 section 8; P6-D-3, POL-13, POL-14).**

- **Package:** `django-otp` 1.7.5 alone (TOTP devices and single-use recovery codes; it depends only on Django),
  chosen over `django-two-factor-auth`, which adds phone, QR and form-wizard dependencies. The lock's wheel hash was
  checked against the downloaded wheel, and the one change from 1.7.4 was read (a session whose device is no longer
  confirmed loses its verification).
- **Scope:** outside the local environments every request under `/staff/` (the admin and every focused staff view,
  including any added later) needs a session verified by a second factor (`accounts.staff_access.StaffAccess`, after
  django-otp's middleware). An unverified session is signed out and sent to the login page, which asks for the token.
  The requirement is fixed in code (`CATALYST_STAFF_TWO_FACTOR`), never read from the environment.
- **No self-service:** the owner enrols a device (`manage.py enroll_staff_two_factor`, which prints the
  authenticator URI and ten recovery codes once, to the terminal only). There is no password-reset path: the admin's
  password change is refused and no reset view is mounted.
- **Break-glass** for a lost or compromised device: the owner runs `manage.py reset_staff_two_factor`, which removes
  the devices and codes, makes the password unusable and ends that account's sessions. The owner then confirms the
  person out of band (never by email alone), sets a new password and enrols again.
- **Throttling:** password failures are counted per username in PostgreSQL, shared by every web process. After five
  failures the username is refused for 15 minutes, even with the right password. Only a hash of the username is
  stored. Token failures are throttled per device by django-otp. A deliberate lock-out of a staff username is
  possible, and accepted because the staff host is reachable only from named staff devices (option A).
- **Lifetimes:** the idle timeout stays the 30-minute sliding session (6B.2). An absolute lifetime of eight hours
  from login is checked from the login time recorded in the session (from the PR #61 review).
- **Session clean-up:** `clear_sessions` is a ledger action that deletes expired session rows hourly and queues its
  successor, even after a final failure. `manage.py schedule_session_cleanup` (idempotent) starts the chain at
  deployment, and `catalyst_health` reports `session_cleanup_unscheduled` where two-factor is required.
  `manage.py schedule_verification_sweep` starts the verification expiry sweep the same way in the same deployment
  step (`9kg.66`, `016` section 10.17); `catalyst_health` reports `verification_sweep_unscheduled` outside the local
  environments. The first pass opens an item for every open unverified application whose link already expired
  (batched 200 per pass); once per challenge is intended.
- **Database:** django-otp saves a whole device row when a token is verified, so the application role has UPDATE on
  the device tables. A trigger refuses any change by that role except the counters and timestamps. The role cannot
  add or remove a device; it may delete a recovery code, which is how a used code is spent.
- **Backups:** the two-factor tables are excluded (TOTP keys and recovery codes are credentials), so after a restore
  every staff member is enrolled again, alongside the new password the post-restore step already requires.
- **After the security review of this task** (no BLOCKER or HIGH; six MEDIUM, all fixed here):
  - an anonymous request reaches only the login page under `/staff/`, so a staff view added later without its
    own check is still closed; the gate matches on the path without the script prefix;
  - throttle rows are removed by the hourly clean-up, and the break-glass reset clears that username's lock;
  - each enrolment and reset logs one line naming the account id, never the username: the record of each use,
    beside this documented procedure;
  - a locked username still costs one password hash, so the lock state cannot be timed;
  - the tests below were extended.
- **Found by the full suite:** django-otp registers its device models with the admin. They are unregistered, so staff
  never browse TOTP keys or recovery codes. The backup role's grant migration (6B.6) now takes its exclusions from
  `config.backup.EXCLUDED_TABLES`, and a later migration revokes the two-factor tables explicitly, so whichever order
  the apps migrate in, the backup role never reads a credential table.
- **Evidence:** `tests/test_staff_two_factor.py`:
  - an anonymous request reaches only the login page, including a path no view serves yet;
  - a session without a recorded login time is ended;
  - an unverified session reaches no staff page (the admin and one screen of each staff app), and is signed out;
  - the login refuses the password alone, a wrong token and a replayed token; a verified session reaches every
    staff page;
  - a recovery code signs in once;
  - the application role may count failures but never change, add or remove a device;
  - repeated password failures lock the username, even for the right password, until the lock runs out, and the
    login page locks a username that does not exist in the same way;
  - a session older than its absolute lifetime is ended;
  - expired sessions are removed by a self-renewing action;
  - health reports an unscheduled clean-up where two-factor is required;
  - the break-glass reset leaves nothing from before it working;
  - the requirement holds in staging (a fresh staging process), is fixed in code, and the middleware order is
    pinned.

**9kg.24, the fetcher's own database role (026 P6-D-14).**

- **Role:** a fifth login role, `catalyst_fetcher`, provisioned like the others by `scripts/provision_db_roles.py`
  (staging reads `fetcher_password` from the secrets directory).
- **Connection check:** a worker started with `CATALYST_PROCESS_ROLE=fetcher` must connect as exactly that role, and
  may not be a member of the application, owner or retention role. An ordinary worker may not borrow the fetcher's
  login.
- **Kinds:** the fetcher runs only `fetch_evidence` and refuses to start with any other kind selected.
- **Completion moved out of the fetcher** (after the PR #71 security review): when an item finishes, the fetcher
  only queues `complete_evidence_collection`. The worker runs that action, as the application role: it moves the
  stage, opens the "required evidence unavailable" item, and queues the assessment run. The check is idempotent,
  and two racing checks still complete collection exactly once.
- **Grants** (`assessments` 0009): the fetcher reads the application, the item and its source, and pauses. It writes
  the item's result, a capture, history events, the evidence staff item, its own action's progress and the
  completion request. It reads three application columns (never contact details), and may lock an application
  row but never change it. It has no access to submissions,
  inbound mail, questions, assessment runs, staff, sessions, two-factor, agreements, provisioning or outbound mail.
- **Pinned writes:** a trigger per write refuses, for a session in the fetcher role:
  - any pending-action insert but a completion request exactly as the fetch makes it (due now, its key and version
    naming a real evidence item of that application), so it cannot queue a send for the worker to run or squat a
    real request;
  - any update but to a live `fetch_evidence` action, so it cannot revive or cancel another action;
  - any change to an application;
  - a change to an evidence item that is no longer pending;
  - a history event or staff item of a kind the fetch never writes.
- **Stated residual:** the fetcher is the process that produces fetch results, so a compromised fetcher can record
  a forged result for any item still pending (it can always claim that item's fetch first). It cannot touch a
  finished item, another kind of action, an application, or anything outside the evidence path. Captures keep the
  peer address and digests, and staff review every assessment. The process-role check is a misconfiguration guard;
  the controls are the grants, the triggers and the custody of the fetcher's password, which only the fetcher's
  container mounts (6B.5b).
- **Evidence:** `tests/test_fetcher_role.py`:
  - real fetches through the worker command, connected as the fetcher role, with completion run by the worker:
    success with collection completed and the assessment queued, plus a retried 503, a 403 and a 404;
  - the role refused on ten statements outside its grant;
  - a compromised fetcher refused when it tries to queue a send or an assessment, squat a completion request with
    another key, version or junk, revive a finished action, move or touch an application, change a finished item,
    forge a history event or staff item, read an applicant's contact details, or read submissions, mail or
    assessment runs;
  - a fetcher process refused as the application role, or with another kind selected, and an ordinary worker refused
    as the fetcher role.

**6B.5b, the staging compose stack (026 sections 4 and 5; P6-D-6, P6-D-14).**

- **`deploy/staging/compose.yaml`** is generated by `scripts/render_staging_compose.py`. A test fails while the
  committed file and the rendering differ. The output is JSON, which is YAML, so Docker Compose and the
  standard-library tests read the same file.
- **Services:**
  - `db`: PostgreSQL pinned by digest, logging no statements or parameters;
  - `provision-roles`: operator-run, with the `provision` profile;
  - `migrate`: as the owner, which also schedules the session clean-up;
  - `collect-static`: no network;
  - `web`, `worker` (everything but the fetch) and `fetcher` (only the fetch, as the fetcher role);
  - `proxy`: Caddy pinned by digest.
- **Secrets are files, never environment:** each process mounts only its own, read-only, under `/run/secrets`, with
  no `env_file`. Each process sees its own role's database password. The bootstrap administrator's password reaches
  only the database and the operator-run provisioning; the backup password only provisioning.
- **Every Catalyst container** runs as 10001, with a read-only root, every capability dropped, no new privileges,
  tmpfs at `/tmp` and `/dev/shm`, `CATALYST_ENV=staging` fixed, the attested image named by digest, and a fixed
  command.
- **Networks:** web, worker, fetcher and the database share an internal network that reaches nothing outside. Only
  the proxy publishes ports.
- **The proxy** runs as 10001, which reaches the 0660 socket through its group, on high container ports (8443 and
  8444). The socket volume is mounted read-only. Caddy's state is in tmpfs, so its internal CA is re-created at each
  start; a persistent, host-owned directory is a 6B.11 item. The official Caddy binary carries the file capability
  `cap_net_bind_service`, and the kernel refuses to run a binary whose file capability it cannot grant. That one
  capability therefore stays, and no-new-privileges is off for this container alone; it binds no low port.
- **The staff site** has its own container port (8444), published only on a named private address
  (`CATALYST_STAFF_PUBLISH`, required, with no default). Inside a container every interface is the container's own,
  so the publish address is the control.
- **Unknown hosts:** an explicit catch-all on both listeners closes the connection for any other host name (an
  unknown name, the staff name on the public port, `localhost`). Caddy otherwise answers an unmatched host with an
  empty 200, which the live check found.
- **After the security review of PR #72** (four HIGH, seven MEDIUM):
  - the live checks now read each container's real state: a read-only root from the engine, the effective
    capabilities and no-new-privileges from `/proc`, the directory modes, `CATALYST_ENV`, tmpfs, and the database's
    own environment;
  - each "no answer" is proven by curl's exact exit status: 52 when the TLS handshake succeeded and the connection
    was then closed unanswered, 35 when the handshake was refused, and never 7 (nothing listening);
  - the log check first proves the proxy logged those requests with the token redacted;
  - the database stops logging failing statement text, and its health check uses TCP so the image's init-time
    server never looks ready;
  - staging provisioning revokes database access from `PUBLIC`, grants it to the Catalyst roles only, and revokes
    `CREATE` on `public`;
  - a test pins the fetcher to the internal network.
- **Carried to 6B.11, from the same review:**
  - the deploy unit refuses to start unless the secrets directory is 0700 and the files are not writable;
  - a preflight refuses a staff publish address of `0.0.0.0` or `::`;
  - the bootstrap administrator should be accepted only from the provisioning container (`pg_hba`);
  - the provisioning script might move to the staging image only.
- **Found by bringing the stack up:**
  - PostgreSQL 15 and later let only a database's owner create tables in `public`, so staging provisioning hands the
    database to the owner role;
  - every staging process needs the heartbeat setting;
  - `localhost` must be an allowed host for the health paths through the socket (`HostGuard` serves it nothing else);
  - the image now creates its mount points with their owners and modes, and carries the provisioning script.
  - two sites on the staff port that bound differently became two Caddy servers on one port, and the kernel
    spread connections between them at random. The staff port's catch-all now binds like the staff site, and a
    test requires one server per port.
- **Evidence:**
  - `tests/test_staging_compose.py` (the definition);
  - `scripts/staging_check.sh`, run on the dev box, 50 of 50 PASS in five consecutive runs: it builds the staging
    image, provisions with random synthetic secrets, brings the stack up and checks that:
    - `docker inspect` of every container and `docker exec env` of every Catalyst process show no secret value
      (TEST-P6-04, 11);
    - each process runs as 10001 on a read-only root and mounts only its own secrets;
    - the socket is 0660 in the proxy's group, and the mail sink is 0700;
    - the public site serves the form and refuses staff paths, and the staff site answers only on its private
      address;
    - an unknown name, the staff name on the public port and `Host: localhost` get no answer;
    - readiness answers through the socket;
    - a token in a plain, an encoded and an oversized request reaches no container log.

    It then removes everything it created.
- **Carried to 6B.11 (host tasks):** the fetcher's egress proxy and host-level deny, the deploy unit's 0700 secrets
  directory, and the systemd unit.

**6B.10, the deploy adapters and the attested image (026 sections 4 and 9; P6-D-5).**

- **Adapters** (`deploy/staging/adapters/`), driven by the estate deploy wrapper's hooks:
  - `capture.sh` prints the serving image recorded in the deploy state. It fails when none is recorded, or when that
    image is no longer on the host: a pruned revert target is no known-good.
  - `deploy.sh <image>` makes an image the serving one, and the wrapper's revert uses it too. It takes only a
    content reference (an image id or a digest, never a tag), and it fails closed.
  - `smoke.sh` is **the promotion gate**:
    - readiness answers 200 through the web socket, polled for 30 seconds because an answer may be up to five
      seconds old (from the PR #63 review);
    - after a settle period, web, worker and fetcher still run exactly the recorded image (its resolved id), with no
      restart;
    - the worker's and the fetcher's heartbeats are fresh;
    - no migration is pending;
    - the commit inside the image is its label's;
    - when configured, the public form answers through the proxy (with `-k`, because staging uses an internal CA).
  - `predeploy.sh <image>` runs the pre-deploy backup and then the migrations with that image, as the owner. The
    backup command must print the path of a receipt that exists, or nothing is migrated.
  - `receipt.sh` writes the deployment receipt (no personal data) after a promotion. The receipt holds:
    - the image, its commit label, and the intended commit when one is given;
    - the schema head per app and the pending migrations;
    - the held actions per kind and the forward-only list;
    - `check --deploy` (failing check ids only), the smoke readback, and the pre-deploy backup's receipt, which
      is required.

    The decisions about promotion are made in the smoke, before it, so a failing receipt is a record for the operator
    and the alert floor, not a second gate.
- **Forward-only (`config/release.py`):**
  - Every migration is expand-then-contract, and Django ignores an applied migration it does not know, so an older
    image runs on a newer schema.
  - A release that breaks that rule lists its migration in `FORWARD_ONLY`.
  - The deploy state records every forward-only migration any image has named: `predeploy.sh` records the image's
    list before migrating, and `deploy.sh` before switching. The list only grows. `deploy.sh` refuses any image that
    does not know an applied, recorded forward-only migration ("restore instead").
  - With a release serving, a missing record is refused as lost state, never read as "none". Only the very first
    deploy starts from an empty list.
  - The applied list is read through the target image; nothing is read through the serving containers, which during
    a revert are the broken release.
  - Anything unreadable refuses the switch, and the wrapper then holds. Never treat an unreadable list as empty: that
    was the PR #73 review's blocker.
  - The blocker computation runs the tested `config.release` code.
- **Not left to memory:**
  - `config.release.contracting()` finds every migration after the baseline with an operation that can break the
    previous image: removing, renaming or altering a field or model; a constraint on an existing table; a NOT NULL
    column without a database default; a table rename.
  - A test fails until each is in `FORWARD_ONLY` or in `EXPAND_SAFE` with its reviewed reason.
  - The baseline is every migration that existed when this guard arrived. No image without them can ever serve,
    because `deploy.sh` refuses any image that cannot answer `config.release`. They were not all expand-safe:
    `correspondence.0013` added NOT NULL columns with Python-only defaults, which the scan still finds when the
    baseline is set aside (tested).
  - RunSQL and RunPython cannot be read this way; their authors and reviewers decide.
  - A test keeps the release app list equal to the installed first-party apps.
- **Stated limits:**
  - An image built before 6B.10 cannot answer `config.release`, so the first guarded release has no older revert
    target.
  - A database that cannot be read also refuses a revert, so the wrapper holds and a person decides.
  - The previous image must stay on the host (no image pruning between releases).
  - A switch that fails after the record was written keeps that image's marks in the record. This is conservative: a
    mark only ever refuses more.
  - The forward-only arithmetic runs from the deploy host's checkout of this repository, so that checkout must sit
    at the deployed commit (6B.11's force-command).
- **The image workflow** (`.github/workflows/image.yml`, not a required check):
  - **every pull request:** a read-only build job builds the production target, checks its content and `COMMIT`,
    writes an SPDX bill of materials (Syft) and scans it (Grype);
  - **main only:** a separate job, which alone holds the signing permissions, attests the exact image tarball and
    keeps it as the build artifact;
  - **no registry push**, and every action is pinned by commit;
  - **scan policy, for the owner to confirm:** a fixable high or critical finding fails the build; unfixed findings
    are listed but pass; there is no waiver file yet; the scan runs at build time only.
- **Verification on the host** (`scripts/verify_image_attestation.sh`): the tarball is copied into a private
  directory, and that copy is the one verified and the one loaded, so nothing can be swapped between the two. It
  refuses unless:
  - the attestation comes from the image workflow, on `refs/heads/main`, for exactly the commit being deployed,
    built on a GitHub-hosted runner;
  - the loaded image's commit label matches.

  It prints the id for `deploy.sh`.
- **After the review of PR #73:**
  - **first review** (one BLOCKER, four HIGH, nine MEDIUM): the recorded forward-only list; the smoke as the single
    gate (stability, heartbeats, pending migrations, commit); the contracting scan; a required backup receipt; the
    private-copy verification; the split workflow; a pruned revert target refused at capture;
  - **re-review** (two HIGH): the list recorded before migrating, and a lost record refused;
  - the scan covers NOT NULL columns without a database default;
  - the smoke checks the intended commit when one is named. Making it mandatory comes with 6B.11's force-command.
- **Evidence:**
  - `tests/test_release.py`:
    - the migration list with no settings, the forward-only rule and its command;
    - the contracting scan, both on the real migrations and on a synthetic removed field and new table;
    - the release app list, and the release facts from the database;
    - the adapters' reference pattern, smoke gates and fail-closed rules;
    - the workflow's pins, split permissions and absence of a registry push, and the verification's private copy
      and flags;
  - `scripts/deploy_drill.sh`, run with the estate wrapper on the dev box, 28 of 28 PASS twice:
    - a backup that prints no receipt refused, with nothing migrated;
    - a first release migrated, deployed, smoked and receipted;
    - a good release promoted through the wrapper (exit 0), with a matching receipt;
    - automatic reverts (exit 3) of a broken release (its readiness module removed), of a release whose worker and
      fetcher crash-loop, and of a release deployed without its migrations, each leaving the previous release
      serving;
    - a forward-only revert refused, naming the migration, with nothing changed, and the list read from the
      recorded state;
    - a forward-only migration applied by a predeploy whose deploy never happened, still refusing an image without it;
    - a missing record refused while a release serves;
    - a tag refused;
    - an unattested tarball refused before it is loaded.
- **Found by the drill:** synthetic secret keys shorter than Django's deploy check requires, which the receipt
  caught (`security.W009`); and the revert path reading migrations through the broken serving release.
- **Carried to 6B.11:**
  - the pre-deploy backup job on the host (the drill states its synthetic stand-in);
  - the deploy force-command, which accepts a commit, runs the verification and then predeploy;
  - the wrapper's stack entry;
  - wiring a failed receipt into the alert floor.

**6B.10a, the secret rotation runbook (026 section 5; P6-D-15).**

- **The runbook** is `027`. For each secret class it gives the routine procedure, the leak procedure, what users
  notice, and whether the procedure is tested. It also states the rules: a leaked key is never a fallback; one class
  at a time; a record without values; intervals are the owner's.
- **Only confirmation links are signed with the link key.** Password-setup and withdrawal links are random tokens
  stored as hashes, so a key rotation neither breaks nor protects them. The routine fallback window is therefore the
  confirmation link's lifetime alone.
- **Leak tooling:** `manage.py catalyst_close_links --confirm-database <name> --leaked-key-sha256 <hex>`, run as the
  owner.
  - It closes every outstanding confirmation link record, and opens a staff item for each applicant left waiting,
    labelled as a rotation.
  - It reuses the post-restore step's link closing (`config.post_restore.close_outstanding_links`, now shared, with
    `signed_only` for this case).
  - It refuses while the leaked key, named by its digest and never its value, is still the link key or any fallback
    key. The new key must therefore be deployed first, or staff would reissue links under the leaked one.
- **Staging:** the compose file now mounts `verification_fallback_keys` (empty unless a rotation is under way) in
  web, worker and migrate, so the routine procedure can run there.
- **Corrects the secrets table in section 5:** the link key also reaches migrate, which signs no links but loads the
  same settings.
- **The administrator's password** has its own procedure, because the provisioning step logs in with it. That
  procedure, removing an old webhook secret, and the pilot's provider credentials are procedures only, stated as
  untested.
- **After the QA review of PR #74** (four HIGH):
  - the leak procedure closes confirmation links only, and a password link survives it (tested);
  - the administrator's procedure;
  - the staging fallback mount;
  - the leaked-key ordering is enforced by the command.
- **Evidence:** `tests/test_secret_rotation.py`, each with a positive control:
  - a routine link-key rotation keeps links in hand working while the old key is a fallback, and ends them when it
    goes;
  - after a leak, links signed with the leaked key fail at once. Exactly the confirmation links are closed, each
    with a staff item to reissue, and not even the leaked key opens them again;
  - closing refuses while the leaked key is still the link key, while a fallback remains, or for another database;
  - a password-setup link survives the key's rotation and the leak procedure;
  - rotating the Django key ends every staff session;
  - a rotated role password takes effect, and the old one stops working.

  The webhook secrets' two-secret overlap is tested in `tests/test_agreement_completion.py`.

**6B.11 (part 1), the live GATE-STAGING cases on the dev box (026 section 11; host go recorded on bead `9kg.20`).**

- **`scripts/staging_check.sh`** runs these cases against the live stack. Each check has a positive control or an
  exact signal, so it cannot pass because something unrelated failed. Status per case:

  | Case | Status | What the live check shows |
  |---|---|---|
  | TEST-P6-02 | proven | `check --deploy` is clean under staging settings (W005 and W021 silenced, as section 8 decided) |
  | TEST-P6-05 | partly | a second `migrate` applies nothing. Running as the owner, and readiness red while the schema is behind, are shown by `deploy_drill.sh` (the unmigrated release) |
  | TEST-P6-06 | partly | a second provisioning run succeeds and reads its five roles back. Staging's credentials are random per run, never the test values |
  | TEST-P6-07 | partly | with the database stopped, liveness answers 200 and readiness 503. Readiness recovers, with three answers in a row after the five-second cache. A wrong role is unit-tested |
  | TEST-P6-12 | proven | variants of the staff, admin and health paths are refused by the public site, while a listed path is forwarded. Variants the proxy forwards (`/confirm/../staff/login/`, `/confirm/..%2fstaff/login/`) are refused by Django |
  | TEST-P6-32 | proven | Django itself, reached through the socket with no proxy, refuses staff, admin and health paths and their variants on the public host name, and serves the staff login on the staff host |
  | TEST-P6-14 | mostly | HSTS, the content security policy, the `__Host-` CSRF cookie (Secure, HttpOnly, SameSite=Lax), `no-store` on a token path, and a spoofed `X-Forwarded-Proto: http` overwritten. The session cookie's flags are unit-tested |
  | TEST-P6-15 | partly | an enrolled staff account is refused with the password alone and with a wrong token, and signed in with both factors. A superuser is refused at the login form, with a message and no session. The named-device network restriction is a host item (staff publish address) |
  | TEST-P6-16 | partly | the webhook is mounted neither at the proxy nor in Django. The enabled webhook's refusals and rotation are unit-tested |
  | TEST-P6-28 | partly | web, worker and fetcher reach the database (the control) and nothing outside, refused by the network, not by an error; names do not resolve there. "No production secret" is shown by the secret checks (TEST-P6-04) |

- **Superusers:** outside test and development, a superuser account is refused at the staff login form, and
  `accounts.staff_access` ends any superuser session as a backstop. The owner works through `manage.py`. Unit tests
  cover both.
- **Found while making the checks honest:** each web worker caches its readiness answer for up to five seconds, so
  just after an outage one worker can still answer 503 while another answers 200. This is the designed behaviour, and
  the reason the deploy smoke polls rather than sampling once.
- **Earlier checks in the same script** cover TEST-P6-01 (in part), 04, 11, 13 and 33. TEST-P6-08 to 10, 24 and 25
  are covered by `scripts/deploy_drill.sh` with the estate wrapper; TEST-P6-36 by the rotation tests, and TEST-P6-37
  by the image workflow.
- **Result:** 98 of 98 PASS, in three consecutive runs.
- **Still to come in 6B.11 to 6B.13:**
  - alerts and the dead man to Buzz (TEST-P6-17 to 20, 38);
  - the backup and restore drill (TEST-P6-21 to 23, 29, 35);
  - a dark deploy with data (TEST-P6-27);
  - the cutover rehearsal (TEST-P6-26);
  - the webhook enabled, and its replay (TEST-P6-16 and 34, at the unit level today).

**6B.11 (part 2), the fetcher's egress proxy (026 section 5, H5; TEST-P6-30).**

- **`assessments/egress.py`** is an HTTP CONNECT proxy, run from the same image as its own service, `egress`. It
  holds no secret and no database login, and it alone joins the outbound network.
- **Networks:** the proxy shares an internal `fetch` network with the fetcher alone, and is never on `backend`, so
  web, worker and migrate cannot reach it (from the PR #76 review). The fetcher sits on `backend` (for the database)
  and on `fetch`, with no DNS and no other route, so every fetch goes through the proxy. The proxy:
  - accepts CONNECT only, to port 443 (and, in a synthetic environment, the fixture's port), with a deadline for the
    request head;
  - takes a DNS name, never an IP literal, except the one pinned fixture address of a synthetic environment;
  - refuses unless every address the name resolves to passes `assessments.fetch.classify`, the fetcher's own pure
    function: global unicast only, so no loopback, private, shared (the tailnet range), link-local or metadata
    address, and not the proxy's own host;
  - checks the connected peer again and reports it, and the fetcher checks it a third time before its TLS
    handshake;
  - leaves TLS end to end, verified against the real host name, so the proxy never sees the path or the content;
  - tries each classified address in turn;
  - refuses all-numeric names;
  - bounds tunnels in number (16), in idle time and in total time, with every send bounded too, so a peer that
    stops reading cannot pin a slot;
  - refuses to start if a fixture address or port is set outside a synthetic environment;
  - logs outcome codes only.
- **The peer check in the fetcher** is defence against a proxy bug, not an independent control: the proxy reports
  the peer itself. The controls that hold even against a compromised proxy are the host allow-list, TLS hostname
  verification and the network isolation.
- **The fetcher** (`assessments.fetch`) uses the tunnel whenever `CATALYST_EVIDENCE_PROXY` is set. A refusal from
  the proxy is a refusal and is never retried; a proxy that cannot connect is transient. Fixture sources go through
  the proxy too, to their pinned address. The guards refuse a fetcher without the proxy in every environment but
  test and development, and refuse a malformed proxy setting.
- **Evidence:**
  - `tests/test_egress.py`:
    - the policy refuses anything but a CONNECT to a name on an allowed port;
    - the fixture address is admitted only in a synthetic environment;
    - a name resolving to loopback, private, metadata, tailnet or bridge addresses, or to a mix with a private one,
      is refused by the live proxy, and so is a single-label name;
    - evidence is fetched through the proxy end to end, with the reported peer recorded;
    - a proxy refusal ends the item as refused, with nothing fetched;
  - `tests/test_startup.py`: the staging fetcher's guard;
  - `scripts/staging_check.sh` (TEST-P6-30), 120 of 120 PASS in three consecutive runs, shows that:
    - the fetcher reaches the database and the proxy, and nothing else, while web and worker cannot reach the
      proxy;
    - through the proxy a public name is tunnelled (the control);
    - names on a public wildcard DNS service that resolve into each denied range are refused, as are IP literals,
      other ports and the database's single-label name;
    - the proxy mounts no secret, runs as 10001 with no capability, and holds no secret in its environment.
- **Stated limit:** the public wildcard DNS service and the control's public name are outside dependencies of the
  check. A policy answer (200 or 403) is final; a transient one (no answer, or a lookup failure) is retried at most
  three times. If they cannot be reached, those checks fail, never pass.

**6B.12, staging alerts to Buzz (026 sections 7 and 11; host go recorded on bead `9kg.21`).**

- **`deploy/staging/adapters/health.sh`** is run by a host timer every five minutes. It runs `catalyst_health` in the
  worker container (which holds the heartbeat), probes the public form from outside, and hands any finding to
  `$CATALYST_NOTIFY_CMD <level> <message>`, which the host wires to the estate alert floor. Its rules:
  - **the message is built from signal codes alone;** every word must match `part.name`, and anything else is
    replaced by `health.unrecognised_signal`, so no content of any kind can reach an alert;
  - **severity:** urgent for a worker that is gone, or alive with a stale or missing heartbeat, and for a health check
    that itself failed. A check that exits without a readable report counts as failed, never healthy (from the
    review of PR #77). Other findings are high;
  - **recovery:** a recovery after findings sends one info note, which the alert floor records without paging. The
    findings are recorded only once handed over, so a failed note is retried;
  - **repeats:** a finding that persists is sent every run, and the alert floor suppresses exact duplicates;
  - **markers:** it writes `health.started` before and `health.ok` after every completed run.
- **`deploy/staging/adapters/sweep.sh`**, the dead man, is run by a separate timer. It sends an urgent
  `health.check_stale` when the health check has not completed for 15 minutes (three missed runs), so a stopped
  timer, a stopped host and a hanging check are caught the same way.
- **Stated limit:** both scripts share the notify command, so a broken notify path is invisible to both. The host
  timers must surface exit 3 themselves (an `OnFailure` unit), which is part of their installation.
- **Where it runs:** the check runs in the worker container, not the web image as section 7 says, because the
  heartbeat lives there.
- **Deferred to 6B.13:** the backup-freshness and restore-drill-overdue signals of section 7.
- **Evidence:**
  - `tests/test_staging_alerts.py` runs the real scripts against stubbed `docker` and `curl`:
    - a healthy report sends nothing and leaves the marker;
    - a check that fails without a report is never healthy;
    - findings are codes, an unrecognised one is replaced, and a stale heartbeat is urgent;
    - a stopped worker and an unreachable form are reported;
    - recovery is noted once, and retried if the note failed;
    - the sweep is quiet when fresh, and alerts when stale or never run;
  - `scripts/alert_drill.sh` on the dev box, against a live synthetic stack with a recording stub, 15 of 15 PASS
    twice:

    | Case | Shown live |
    |---|---|
    | TEST-P6-17 | a stopped worker raises an urgent alert naming it; recovery sends no alert and exactly one recovery note |
    | TEST-P6-19 (partly) | a planted unresolved hard bounce and a planted overdue backlog raise their signals. The uncertain-send and custody signals are unit-tested (`test_system_health`) |
    | TEST-P6-20 | a stopped health timer, alone or with the worker stopped, and a health check that never completed, are each caught by the sweep |
    | TEST-P6-38 | a sentinel planted in the stored data never reaches the alert, and every word of the alert is a signal code |

  - **one real delivery:** a drill alert was dry-run through the estate alert floor, then sent for real at high
    severity to the `sys-health` channel. It was read back from Buzz itself, signed by the notifier bot: the only
    message in that window, created at Unix time 1792672504, beginning "catalyst staging drill (6B.12): alert
    delivery check". TEST-P6-18
    (the collector alert) needs staging's inbound mail, which is configured only from the pilot (P6-D-6), so it is
    unit-tested here.
- **Not yet installed:** the host timers for the health check and the sweep. Staging on the dev box runs as
  disposable drills, so a permanent timer would page `worker_unreachable` every five minutes. The timers are
  installed with the first persistent staging stack, using the same adapters and notify command (bead `9kg.21`).

**6B.13, the measured restore drill (026 sections 6 and 11; host go recorded on bead `9kg.22`).**

- **Operator services:** the staging stack gains two, under the `ops` profile:
  - `backup` runs `catalyst_backup` as the backup role into a private volume;
  - `restore` runs `catalyst_restore` as the owner, with the bootstrap administrator's credential, which only the
    restore uses. Its target directory lives inside the custody volume, because the restore stages beside its
    target and the image root is read-only.
- **The image** creates private mount points for backup sets and custody files. Staging holds no custody files
  until the pilot connects Documenso.
- **`scripts/restore_drill.sh`**, on the dev box, synthetic data only, 28 of 28 PASS twice:
  - a source stack takes three applicants through its public form, and a confirmation link from before the backup
    is shown to open;
  - the backup writes a set with a manifest digest, and its receipt holds no personal data;
  - an applicant after the backup is accepted;
  - the set is archived on the host, private (0700, files 0600), and the source stack is removed;
  - a separate target stack is provisioned and migrated, then, each with its own reason (not merely an error), it
    refuses:
    - a restore naming the wrong database;
    - a wrong manifest digest;
    - a tampered copy;
    - a set that is not private;

    and those refusals change nothing. The real restore then succeeds from the archive with its digest, and a second
    restore into the now non-empty target is refused;
  - the control: restored as it was, the pre-backup link still opens. After the post-restore review and lift the
    application answers "This link is not valid" for it, a specific answer rather than any failure;
  - the restored stack serves the form, holds exactly the backup's three applications (not the later one), and
    takes a new applicant.
- **Measured, synthetic scale, for the owner's targets (P6-D-7):**
  - the backup takes 4 seconds;
  - recovery from an empty host to a serving stack takes 62 to 63 seconds. This covers preparing the target, the
    negative controls, the restore, the post-restore step and the start;
  - the restore, post-restore step and start alone take 27 to 28 seconds, an upper bound that includes the drill's
    own checks;
  - the RPO is the backup's point by design (checked: the applicant accepted after it is absent from the restored
    stack).

  The owner decides which of these the RTO target means. The drill writes a receipt (date, commit, result, timings,
  no personal data) when `CATALYST_DRILL_RECEIPTS` names a directory.
- **Health:** the health check now also reports `backup.stale` (no backup receipt within 26 hours) and
  `restore_drill.overdue` (no *passing* drill receipt within 35 days; a failed drill never counts, from the review of
  PR #78) when the host names those directories. A missing or empty directory counts as stale. Both are tested at
  their boundaries. Nothing writes backup receipts to that directory yet: the scheduled backup job does (bead
  `9kg.22`).
- **Case status:**
  - **TEST-P6-22:** proven.
  - **TEST-P6-23:** proven for the five negative controls above.
  - **TEST-P6-29:** shown for an unused link from before the backup. Sessions, staff passwords, revocations and
    links used after the restore point are covered by the post-restore unit tests; erasure replay is bead `9kg.25`.
  - **TEST-P6-21:** partly.
    - Shown: the set and its manifest are written; a failed backup keeps the previous good set intact and verifiable
      (`test_backup_commands`, added with this task).
    - Not separately tested: the snapshot's isolation from a write made during the backup, which holds by design
      (one REPEATABLE READ snapshot), and the failed run's alert, which belongs to the scheduled backup job.
  - **TEST-P6-35:** shown for the receipt and the set's modes.
- **Deviations and limits:**
  - The staging backup service connects over TCP with a password. Sections 6 and the controls table ask for a backup
    login on the local socket only, which is host configuration for the pilot (`pg_hba`, bead `9kg.20`).
  - The backup service mounts the link keys, because staging settings refuse to load without them.
  - Custody is not exercised: staging holds no custody files until the pilot. The restore writes into a directory
    inside the custody volume, which the pilot's storage setting must point at.
- **Not yet:** a scheduled backup job writing its receipts, and the archive on the host's own backup fabric. These
  come with the first persistent staging stack (bead `9kg.22`).

**6B.11 (part 3), the dark deploy and the cutover rehearsal (026 sections 9 and 11; TEST-P6-26, 27).**

- **TEST-P6-27, the dark deploy** (`scripts/staging_check.sh`): on the live staging stack:
  - an applicant goes through the real form;
  - the verification mail reaches the private file sink, not a provider;
  - the applicant confirms through the emailed link;
  - the confirmation answers 200 with the confirmed page's own sentence;
  - the evidence collection that follows stays held until the owner's activation command (the held count is the
    control);
  - every registered action kind except an explicit allow-list (the verification mail to the file sink and the
    session clean-up) is held or absent, so a provider-reaching kind added later is covered without editing the check;
  - "zero provider calls" rests on this together with the egress checks (TEST-P6-28 and 30).
- **The cutover's route snippets** (`deploy/cutover/`), imported into the Learn site at cutover:
  - `catalyst-r1.caddy` holds the entry pages (the request form and its received page);
  - `catalyst-r2.caddy` holds the token return paths (confirmation, password setup, withdrawal).

  Removing R1 alone is the R1 rollback; R2 stays while any v2 applicant holds a live link.
  - **Upstream:** each snippet's upstream defaults to the v2 web socket, so reloading the live site needs no new
    environment variable (Caddy reads one only at start).
  - **Forwarded headers:** each sets `X-Forwarded-Proto` and `X-Forwarded-For` itself and drops `X-Forwarded-Host`,
    as the staging proxy does.
  - **Logging:** `catalyst-learn-log.caddy`, generated from `PRIVATE_PATHS`, is the Learn site's access log with
    R2's token segments redacted.
  - **Tests:** `tests/test_cutover.py` keeps R2 equal to `PRIVATE_PATHS`, R1 equal to the staging proxy's entry
    pages, and the two together equal to every applicant route, with no staff or health path. It also pins the log
    snippet to its rendering, and the upstream and forwarded-header lines.
  - **Signing return:** section 9 lists a signing return path in R2. v2 has no signing return route, because
    Documenso sends no applicant back to Catalyst, so R2 holds none. The owner confirms this with the cutover plan.
- **TEST-P6-26, the rehearsal** (`scripts/cutover_rehearsal.sh`), 19 of 19 PASS twice. A stand-in Learn site in the
  pinned Caddy, using the log snippet, fronts stand-in LMS and v2 upstreams, and the rehearsal shows:
  - the snippets parse with no upstream variable set;
  - **before the switch**, every path is the LMS's;
  - **after the switch:**
    - R1 and R2, with case, repeated-slash, encoded-letter and dot-segment variants, reach v2;
    - v2 receives the forwarded scheme set by the snippet, and a client's spoofed one is overwritten;
    - token paths sent in five forms never reach the Learn log, while the redacted form does (the control);
    - every LMS path is still the LMS's and answers byte-identically, including near misses: `/confirmation/`,
      `/setupwizard/`, `/request-accessible/`, `/request-access` without its slash, and a bare `/confirm`;
  - **after the R1 rollback:** R1 is the LMS's again, R2 stays on v2, and the LMS paths are still byte-identical;
  - **with both removed**, the site is exactly as before.

  Each change is a reload, never a restart.
- **Stated limit, and the preconditions for the live switch:** the Learn site in the rehearsal is a synthetic
  stand-in. The live Learn configuration lives on the production host, so it is read only under the cutover plan,
  with the owner's go. That read must:
  - record its hash, and check R1 and R2 for collisions with the LMS;
  - confirm the snippets can be imported before any other `handle`, `route`, `rewrite` or `redir` that could match
    their paths;
  - confirm the import is a glob, which tolerates the removal of R1;
  - confirm the site's `log` can be replaced by the log snippet, and the error log given the same filter;
  - confirm the live Caddy version, and that no `trusted_proxies` setting lets a client's forwarded headers through.

**6C, the GATE-STAGING evidence map and the after-action report (026 sections 11 and 12, task 14).**

- **The map:** `tests/acceptance.py` `P6_CASES` maps 37 of the 38 cases to the tests that prove them. The 38th,
  TEST-P6-27, is shown only live (`P6_LIVE_ONLY`). `P6_SUPPORTING` holds the P6 design rules that are not cases: the
  9kg.2 pause rule and, since PR #87, the five internal-launch groups (`9kg.30`, `9kg.50`, `9kg.51`, `oc4.12`, `9kg.47`),
  which sit inside GATE-STAGING's supporting map by design (every staff-path test gates a full run).
- **The gate:** `tests/conftest.py` reports GATE-STAGING and gates it in a full run like GATE-S1 to GATE-P5.
- **Two new tests:**
  - every case in this section is gated or live-only, never both and never neither;
  - every test written for P6 is mapped here or in an earlier gate.
- **Per-case status:** in `000-aars/028-AA-AACR-p6-staging.md` section 4. 21 cases are proven (one on a stand-in) and
  17 are partly proven, each with what is not yet shown and the bead that carries it (`9kg.27` holds the new ones).
  - Joining the unit and live evidence moves TEST-P6-05, 06, 07 and 14 from partly to proven; the report names the
    clause each one gained.
  - The QA review of PR #80 moved TEST-P6-10, 25, 28 and 35 from proven to partly. TEST-P6-10's receipt is a record,
    not a gate. TEST-P6-25's drill never reverts a migrated release. TEST-P6-28's fetcher proxy admits any public
    name. TEST-P6-35 has no check over committed evidence.
  - For TEST-P6-08, 24, 25, 26 and 31, a gate PASS pins the code's shape; the drills carry the behaviour.
- **GATE-STAGING sign-off:** left for the owner, on the statement in that report's section 9.

**9kg.33, effects after the backup point reconciled before the hold lifts (029 section 6.2; PL batch item 4;
hardened after the PR #89 reviews).**

- **The effect journal** (`workflow/journal.py`): a hash-chained JSON Lines file in `CATALYST_EFFECT_JOURNAL_DIR`, a
  directory outside the database's rollback domain. An entry is `seq`, `at`, `kind`, `key` (a public reference or an
  opaque staff reference, never a numeric id or a username), `data` (an allow-list per kind: codes, references,
  counts, digests and times; anything else is refused before it reaches the file), `prev` and `hash`. The first
  entry is a `genesis` with a random journal identity. Writers hold an exclusive advisory lock, readers a shared one;
  appends are O_APPEND and fsynced; a file that does not end in a newline is a torn tail that stops appends until
  the owner runs `catalyst_journal_repair --confirm`, which moves the torn bytes to `effects.jsonl.torn-<time>` and
  journals a `repair` entry. The consistency model and its three invariants are stated in `029` section 6.2.
- **Production path, owner and mode (operator provisioning, not code):** `/var/lib/catalyst/effects`, owned by
  uid 10001, mode 0700, file 0600, on an **external volume** that `compose down -v` never removes (the staging
  renderer declares `catalyst-effects` as a project volume for the drill; production must declare it external and
  back it up with the host archive, since it is the restore's evidence). The host-side append-only attribute
  (`chattr +a` on `effects.jsonl`, lifted only for the owner's repair) is the operator's provisioning step; the
  application never sets it. Mounted by web, worker, migrate, restore (read-write) and backup (read-only); the
  fetcher mounts nothing and names a path that does not exist.
- **Observability:** an append that fails is logged by code, counted in `effects.failures`, reported by
  `catalyst_health` (`journal` part: `effect_journal_<problem>`, `effect_journal_append_failed`), and a web process
  whose directory is missing, not private or unwritable answers `not-ready`; a worker refuses to start. The journal
  guard runs only in environments the guards admit: `production` must be in `ALLOWED_ENVIRONMENTS` (the release
  decision) for it to run there.
- **The backup point:** the backup reads the journal's identity, seq and head into its receipt before the snapshot
  opens (a journal fault is recorded as `effect_journal_error`, the set is finished and the command exits 1); the
  restore refuses before the load when the configured journal is another lineage or lacks the receipt's head at its
  seq (`journal_mismatch`), then appends a `restore` marker. The post-restore step reconciles the entries between
  the two and refuses with `journal_mismatch` if an empty or truncated journal sits behind a marker.
- **The post-restore step** (`config.post_restore`, run as the code-declared `reconcile` kind): the review's one
  transaction disables staff passwords on the first run only, makes every outward action that was queued, running or
  held uncertain with a staff item (a send gets its decidable `send_outcome_unknown` item), replays the journal per app
  under `journal.replaying()`, clears every mailbox cursor's completed-collection watermark so no reminder fires
  before the first post-restore collection pass, and queues revocation rounds. Provider reads then run outside the
  transaction, feeding `restore_effect_*` items through one opener that never reopens an item of the same reason and
  key resolved after the restore marker (re-run convergence). The hold moves to *reconciled* only when the journal
  was readable and matched and every needed read completed; the lift refuses while any `restore_effect_*` item is
  open; `--resolve <item> --note "..."` is the owner's manual resolution, its note passing the staff-message content
  checks.
- **Rules by class:** a closure is re-applied through `close_locked`; a final revocation state is written onto a
  restored obligation that is not final; the last journaled pause state per application wins (a database-assigned
  version per key for ordering is deferred); a resolution, a withdrawal and a reply outcome are re-applied when the
  restored row is open again; `abandon` is re-applied; `authorize_resend` and `revise` open blocking items unless the
  Sent read finds the copy (or the revised message is in the backup); a reminder that left (`send_begun` of kind
  reminder, or `reminder_queued`) cancels the restored reminder of that number and schedules the next, and reminders
  E1 recreates at or below the highest journaled position are cancelled again after acceptance by evidence; a staff
  deactivation or group removal is re-applied, a creation, reactivation or grant opens `restore_effect_staff_account`.
  Each replay counts `target_missing` for an entry naming a row the restored tables do not hold. Model usage needs no
  write: `daily_requests_used` is never below the journal's high-water mark for the day; a missing or unreadable
  journal refuses the call.
- **The Sent read:** every copy since the backup (`within(since)`), matched by Message-ID with the 016 A5 rule;
  copies whose Message-ID is not Catalyst's `c<32 hex>` family, or dated before the window, are dropped; a copy of a
  question approved after the backup (journaled `question_approved`) is linked to the question on the
  `restore_effect_unknown_send` item, and `approve_question` refuses that question while the item is open, so a
  re-approval cannot send a second copy. In a live environment the Sent read is always required.
- **Known limits (also `029` section 12):** envelopes and mailboxes created after the backup for entities created
  after the backup are not found (the restored tables hold no row to read against); absence of a Sent copy is never
  a verdict; credentials at the mail host are write-only and not reconciled (the review closes every open setup);
  the side effects of a replayed resolution are not replayed; nothing is created, cancelled or repaired at a provider.
- **RD-1 (the owner's decision; the default is built):** the post-restore Sent read runs as the `reconcile` process
  kind, which the allow-list admits for the IMAP Sent read only and never for SMTP, on the restore service; in
  production that service needs the mailbox password secret mounted. The alternative is a worker job that reads the
  folder with the lift gated on it. Recorded in `016` section 10.12a as well.
- **The drill** (`scripts/restore_drill.sh`): a staff account created after the backup is journaled; the journal is
  carried to the recovery host like the archive (checked and cleaned up as root, since it is owned by 10001); the
  post-restore step runs through the restore service (the reconcile role); the review opens its item, the lift is
  refused, the owner resolves it, the lift passes and the restored stack has no such account; a second leg restores
  the same set into a stack with an empty journal volume and is refused before the load with `journal_mismatch`.
  The gate test pins the script's shape only. A provider read in the drill (an envelope, a mailbox, a Sent copy)
  needs a provider fake running in the dark stack, which none does today: recorded as a limit, not shown.
- **Evidence:** `tests/test_post_restore.py` (the `9kg_33` tests), `tests/test_startup.py` and
  `tests/test_guards.py` (the directory guard), mapped under `P6_SUPPORTING`.
- **The drill on the dev box, 2026-10-23** (`scripts/restore_drill.sh` at the branch head after the merge from
  `main`): **43 of 43 PASS**. Measured: backup 10 s; recovery from an empty host to serving (target prepared,
  negative controls, restore, post-restore with the journal replay and the owner's resolution, start) 162 s; restore,
  post-restore and start alone 92 s. By design RPO is the backup's point (the applicant accepted after the backup is
  absent). Three earlier runs that day found, and the branch fixed: the drill did not invite its applicants after
  intake became invitation-only on `main` (#85), so none were recorded; the backup's read-only journal mount made
  the reader fail, so the receipt held no anchor; a journal with no effects yet anchored at seq 0, so an emptied
  journal went undetected (now the worker writes the genesis entry at start). One run's third leg failed on the
  host (Docker's address pools exhausted with three stacks up), which the drill now avoids by taking the restored
  stack down first and reports separately from the check.

**PL batch 2 (`029` section 13.3, item 2; beads `9kg.37` and `9kg.38`): the deploy operation, the receipt as a gate
and the N+1 revert drill (TEST-P6-10, 24, 25).**

- **The decision built on (D-I).** The recommended default, *a gate, not a recorded deviation*: a deployment
  receipt that would not match is never written as a deviation; every comparison the receipt records is decided
  before promotion, and a mismatch refuses the deploy through the wrapper's own path (the deploy hook fails, the
  wrapper reverts to the captured image and holds). The owner's later decision can only relax this, not redesign it.
- **The deploy operation** (`config/release.py`, the tested code; `lib.sh`): every deploy is one operation named by
  `CATALYST_DEPLOY_ID`, which the caller chooses (the force-command, once per deploy) and `predeploy.sh`,
  `deploy.sh` and `receipt.sh` require. The operation lives in the deploy state under `operations/<id>/`:
  - `operation.json`, written by `predeploy.sh` before the backup: the approved artifact (the target image and,
    when `CATALYST_EXPECTED_COMMIT` names one, the approved commit), the serving image it would revert to, and
    the start time;
  - `pre-deploy-backup.json`, the pre-deploy backup receipt the deploy side keeps: the deploy id, the path of the
    receipt the backup command printed, that receipt's SHA-256 and its time (the file's modification time).
- **The gates, in order.** `predeploy.sh` refuses an image whose commit label is not the approved commit before
  anything is backed up or migrated; then starts the operation; then refuses a backup command that prints no
  receipt, or an older receipt's path (older than the operation: stale), binding nothing and migrating nothing;
  only a bound backup is followed by the forward-only record and the migration. `deploy.sh` asks the operation
  before anything changes: the operation's target may switch only with its label equal to the approved commit and
  its backup bound, still present, unchanged (the digest) and no older than the operation; the operation's previous
  image, the wrapper's revert, may switch back with no expectation (it returns to what was recorded); the image
  already serving may always be re-applied (what the wrapper restores when an apply was refused before any switch);
  anything else is refused by name. The forward-only check follows, unchanged. `smoke.sh` now also runs
  `check --deploy` and takes the approved commit from the operation, for its target only, so a revert's smoke
  never fails on a commit it was never meant to carry. `receipt.sh` records the deploy id, the operation's answer
  for the serving image, the approved image and commit, and the bound backup's receipt path, digest and time; it
  still fails on any readback drift after promotion, as a record, not as the gate.
- **Stated limits.** The gate compares image references as the caller passes them (the force-command passes the
  same reference to `predeploy.sh` and the wrapper). The receipt's time is its modification time on the deploy
  host, so the backup job must write it where the deploy user reads it (bead `9kg.22`). A deploy id is not refused
  on reuse; a retried `predeploy.sh` replaces the operation and drops its binding, so a retry always takes a new
  backup. A migration that fails after the backup was bound leaves the deploy to the smoke, which refuses the
  unmigrated release (drilled). Nothing here is the attestation check, which stays before `predeploy.sh`.
- **The N+1 revert drill (`9kg.38`; TEST-P6-25).** `scripts/deploy_drill.sh` now builds a release N+1 whose only
  change is an expand migration (a nullable column added to an existing table), promotes it through the wrapper,
  accepts an applicant on it, then reverts the image to N through the wrapper as its own operation (backed up,
  nothing to migrate): the smoke is green on the expanded schema, the column and the applied migration stay (a
  revert never runs a backward migration), every applicant is kept, and N accepts another. A further release with
  a contract migration (the column removed), marked forward-only, is promoted; the revert to N+1 across it is
  refused through the wrapper, naming the migration and saying restore, with the contract release still serving
  and the migration, the schema and every applicant untouched. The contracting scan is run on the drill's own two
  migrations in the gate (expand passes, contract is flagged), so the fixture is the rule it tests.
- **Evidence.**
  - `tests/test_release.py` (`9kg_37`, `9kg_38`; mapped to TEST-P6-10, 24 and 25 in `tests/acceptance.py`): the
    binding and its refusals (missing, stale, the same second allowed), the gate's every answer (approved image with
    its backup; wrong label; another image; the recorded revert; the serving image; a receipt gone, rewritten,
    another deploy's or dated before the operation; no approved commit; no previous), a retried operation, bad ids
    and commits, the commands the adapters run (exit 0, 1 with the reason, 2 usage; no data in any output), the
    adapters' order (label, start, backup, bind, record, migrate; gate before `compose up`; `check --deploy` in the
    smoke; nothing but `predeploy.sh` reading the approved commit from the environment), and the drill's fixtures
    and order.
  - `scripts/deploy_drill.sh` with the estate wrapper on the dev box, 60 of 60 PASS twice (the first run was 59 of
    60 and found that a revert's smoke failed closed on an operation that never started, which the smoke now treats
    as carrying no expectation). The cases, each with its control:
    - a backup that prints no receipt refused, nothing migrated; the binding carrying the deploy id, digest and time;
    - the first release migrated, deployed, smoked and receipted; a good release promoted (exit 0), its receipt
      naming the deploy, the approved image and commit, and the bound backup;
    - automatic reverts (exit 3) of a broken release, of a crash-looping one, and of one whose migration failed at
      predeploy and was deployed anyway (the smoke refuses it: readiness red, migrations pending);
    - TEST-P6-10: an image other than the approved one refused through the wrapper's top-level path (exit 3), the
      refusal naming the identity mismatch, the previous release still serving, nothing promoted; the approved image
      then promoted by the same operation (exit 0) with its receipt; an image whose commit label is not the approved
      commit refused before any backup or migration, and the wrapper refused with no operation started;
    - TEST-P6-24: an older receipt's path refused as stale with nothing bound or migrated, and the wrapper refused
      with no backup bound; another deploy's binding with a fresh timestamp refused (exit 3); the deploy whose
      backup it is promoted (exit 0), its receipt bound to that deploy's backup; in every refusal the stack unchanged;
    - TEST-P6-25: an applicant accepted on N; N+1 (expand) promoted with the column present and an applicant
      accepted; the image reverted to N through the wrapper (exit 0) on the expanded schema, the smoke green, the
      column and the applied migration kept, both applicants kept, a third accepted; the contract release promoted
      with the column removed and recorded forward-only; the revert across it refused (exit 3), naming the
      migration and saying restore, with the image, the migration, the schema and every applicant untouched;
    - a forward-only migration applied by a predeploy whose deploy never happened still refusing an image without
      it; a lost record refused; a tag refused; an unattested tarball refused.
- **Case status:** TEST-P6-10, 24 and 25 move from partly (`028` section 4, bead `9kg.27`) to proven for the
  synthetic stack; `028` stays the point-in-time record of the sign-off.

**6hl.10, the administrator login reaches only the role-provisioning step (026 section 5; internal-launch batch
item 6, 2026-10-23).**

- **Finding (security review of the PR #11 closeout, finding 3):** `compose.yaml` and `ci.yml` set
  `CATALYST_DB_ADMIN_USER` and `CATALYST_DB_ADMIN_PASSWORD` for the whole test container and CI job, so pip, the venv
  and the pytest process itself held the bootstrap administrator's login. Child processes were already stripped of it
  (`tests/support.py`), and the values are synthetic.
- **Built:** the two variables exist only where `scripts/provision_db_roles.py` runs: an `env` prefix on that command
  in `compose.yaml`, and a step-level `env` on the provisioning step in `ci.yml`. The pytest process, pip and the venv
  never see them. The superuser-refusal probes and the tests that must act as the administrator (the staging
  provisioning check, password rotation, the restore command and the restore rehearsal) take the login from one
  probe-only pair, `CATALYST_TEST_SUPERUSER_PROBE_USER` and `CATALYST_TEST_SUPERUSER_PROBE_PASSWORD`, through
  `tests.support.superuser_probe()`; no application, provisioning or deployment code reads those names, and a test
  proves it by reading the source tree. `child_env()` strips both prefixes, so a child receives the administrator login
  only when a test passes it explicitly.
- **What the test process holds:** in the test cluster the probe pair carries the bootstrap superuser's own login,
  because PostgreSQL has no lesser role that can prove "a superuser connection is refused". The gain is structural: the
  names every operational path consumes (`catalyst_restore`, the provisioning script, the staging compose) are absent
  from the test process and from every child it spawns, so nothing can act as the administrator by inheritance; the
  probe name is read by test code alone, and only where a test states that it needs the administrator.
- **Tests (`tests/test_db_roles.py`):** the pytest process holds no `CATALYST_DB_ADMIN_*` name; the probe name is read
  nowhere outside `tests/support.py`; a child process receives neither prefix; a spawned worker's environment carries
  neither (`tests/test_worker.py`); and the staging `web`, `worker` and `fetcher` services carry no administrator
  variable or secret (`tests/test_staging_compose.py`). The full suite runs with the narrowed environment.
- **Staging is unchanged:** the administrator's password was already a file mounted only into the database, the
  operator-run provisioning and the restore service (section 5; the 6B.5b and 6B.13 records).

**PL batch 5 (`029` section 13.3, item 5; beads `9kg.44`, `9kg.40` and `9kg.6`): the evidence register, the
personal-data scan and the pause-row guard (TEST-P6-35).**

- **Designs:** section 11.1 (the register), section 11.2 (the scan) and `016` section 10.15 (the guard).
- **The deploy drill with the scanning receipt step**, `scripts/deploy_drill.sh` with the estate wrapper on the dev
  box, run twice on 2026-10-23 at the branch's head. The first run was 44 of 60: the drill's fixture migrations
  (`0005_drill`, `0005_expand`, `0006_contract`, `0007_staged` in `workflow`) collided with the guard's
  `0005_pause_resume_guard` ("conflicting migrations detected"), so every N+1, contract and staged case failed at
  predeploy; the fixtures are renumbered `0006` to `0008` on the guard (and `tests/test_release.py`'s 9kg.38 pins
  with them). The second run was 59 of 60. The receipt step's scan ran in every receipt case (the first release,
  the promoted release, the approved-image control and the other-deploy receipt): `personal-data scan (receipt):
  2 files, 32 lines, 0 hits` each time, over the deployment receipt and the bound backup receipt, and every
  receipt was kept and read back as intended, so the scan sits in the step without changing a clean deploy. The one
  failure, "the data is kept across the revert: both applicants are still there", is not the receipt step's: the
  drill submits its applicants through the public form without an invitation, and since PL batch 1 (`9kg.43`,
  PR #85) intake is invitation-only by default, so the submit gets the invited response and records nothing; the
  count check then reads the same number before and after. The same check fails on `main` today; batch 2's
  60-of-60 record predates that merge. Carried as a follow-up for the drill (an invitation issued by
  `catalyst_invite` before each submit, or the open mode for the drill's stack), not fixed here.
- **Case status in the register:** TEST-P6-10 and 24 are full since batch 2 (`since_028` notes name PR #84);
  TEST-P6-25 is partial against `9kg.63` until the drill issues an invitation and runs green; TEST-P6-35 stays partial against the dark deploy with the unwired surfaces named (section 11.2).
- **Evidence:** `tests/test_personal_data_scan.py` (the receipt step under docker stubs: a planted value in the
  release facts or in the bound backup receipt withholds the receipt; a bound receipt that is gone fails closed; a
  clean deploy keeps exactly one receipt at mode 0640), `tests/test_acceptance.py` (the register) and
  `tests/test_pause_guard.py` (the guard, through real connections as each role); the drill log above.

**9kg.63, the deploy drill under invitation-only intake (2026-10-24; follows PL batch 5).**

- **Built:** `scripts/deploy_drill.sh` issues an invitation before each intake submission, as `scripts/restore_drill.sh`
  does since PR #89: `invite` runs the owner-run `catalyst_invite` on the serving image as the migration owner
  (`compose run --rm --no-deps -T migrate`), and `submit` returns failure unless the invitation was issued, so a
  refused invitation fails the submission's check rather than letting a count compare equal numbers. The invitation
  sits inside `submit`, so the drill's case list and count (60) are unchanged. `tests/test_release.py` (the 9kg.38
  test, TEST-P6-25) pins the order: the invitation before the form post, through the owner-run command.
- **Found on the first run and fixed here:** the drill's first smoke failed with "fetcher is not stable". Since PR #89
  (9kg.33) the staging fetcher names an effect-journal directory it never mounts
  (`/var/lib/catalyst/effects-none`, on purpose: it makes no effect), but the start-up check required every staging
  process's directory to exist, so the fetcher refused to start and crash-looped; the deploy smoke's stability check
  caught it. `config.guards.journal_problems` now exempts the fetcher role (read from `CATALYST_PROCESS_ROLE`, since
  the check runs before the worker command declares its kind; a web process may not carry that role at all,
  `process_role_problems`); every other process still needs a private, writable directory.
  `tests/test_guards.py` covers both sides, including the whole start-up check (`all_problems`) still refusing a web
  process that claims the fetcher role with no journal directory.
- **The other two drills that start the fetcher, re-run once on the dev box, 2026-10-24** at `7963943` (this change's
  second commit; the review follow-ups touch only tests, `scripts/test.sh` and CI, none of them in the image):
  `scripts/staging_check.sh` **128 of 128 PASS, exit 0** (154 s), with "fetcher is running" and every fetcher
  isolation check green; `scripts/restore_drill.sh` **43 of 43 PASS, exit 0** (226 s). Both removed their stacks.
- **The drill on the dev box, 2026-10-24**, `scripts/deploy_drill.sh` with the estate wrapper, run against `main` at
  `dba8a85` (PR #93) with this change's drill script and start-up check in the image (the image is built from the
  working tree and labelled with `HEAD`): **60 of 60 PASS, exit 0, 17 minutes 22 seconds.** Two earlier runs that
  day stopped early on the fetcher fault above (the first before the guard change, the second with a kind-based
  exemption that never applied at start-up); both were interrupted and their stacks, images and work directories
  removed by hand. In the green run every TEST-P6-25 case passed: an applicant accepted on N, on N+1 and on N after
  the revert, "the data is kept across the revert: both applicants are still there", and the contract revert refused
  with every applicant untouched; the receipt step's scan printed `2 files, 32 lines, 0 hits` in all four receipt
  cases.
- **Case status in the register:** TEST-P6-25 is full again (its `since_028` note names 9kg.38, PR #84, and this
  re-run); the residual bead `9kg.63` leaves `RESIDUAL_BOUNDARIES`. The register totals become 24 full and 14
  partial; proven by a full run stays 19, since TEST-P6-25's gated tests pin the shape and the drill shows the
  behaviour.

**9kg.32, the authorized erasure path (`029` section 6.2.1; council `030` Q3, D-51; P6-D-13 option d's record;
revised after the PR #99 data, security and release-operations reviews).**

- **What it is.** The `erasure` app:
  - a registry that ships undecided and refuses, and also reported `replay:not_built` until `9kg.25` built the replay
    (record below);
  - an erasure map of every column;
  - one security-definer erase function for the retention role;
  - one audited branch in every UPDATE trigger function on a table with subject columns;
  - a mac-verified intent-and-completion record in the effect journal.

  The design is in `029` section 6.2.1. This record covers what the operations side needs.
- **Backups.**
  - `catalyst_backup` refuses in a live environment while the registry has a problem, `replay:not_built` included.
    Health reports this as `backup.registry_blocked`.
  - The synthetic and local environments are unaffected, so the restore and deploy drills run as before.
  - The erasure audit table is in the backup (the backup role reads it). The durable record is not: it lives in the
    journal volume, which the restore must carry like the archive (as for `9kg.33`).
- **The restore's resurrection guard.** Until replay existed, a journal that held any erasure entry made the review
  open `restore_effect_erasure_unreplayed`, and the lift refused outright. `9kg.25` replaced it with the replay and
  its marker (record below).
- **Operator runbook (production, after POL-10 and `9kg.25`):**
  1. On the host's erase service, run `manage.py catalyst_erase --subject <public reference> --authority <code>
     --reason <code>`.
  2. Copy the printed `journal_head` and the subject's erasure entries to the off-host private store. The owner names
     that store; it is not chosen yet.
  3. If the output lists `retained` (`custody_documents`), the registry's `signed_documents` row says `retain` and
     the signed PDFs stay. Under `destroy_key` (`9kg.34`) the output instead counts `keys_destroyed`: the subject's
     custody keys are verified gone from the key directory and its mirror, so a copy of those PDFs, in custody or in
     any backup, cannot be opened without a surviving copy of the wrapped key and the wrapping key (`9kg.34` record below).
  4. For each handoff listed, delete the provider's copy by hand. Then run `catalyst_erase --subject <ref> --handoff
     <provider> --completed-on <date>` and copy the new head off-host again.
  5. Run `VACUUM` on the touched tables as the owner, so the old row versions leave the data files.
  6. `catalyst_erasure_record --expect-head <head>` checks the record. `--list-open` lists unfinished erasures with no
     head.
  7. After an interruption, re-run step 1 with the same reference.
- **Naming the person (`9kg.72`, 2026-10-26).** `catalyst_erasure_subjects <address>`, read-only and only as the
  retention login (where the erasure runs, so it is no "is this address known?" oracle for any other login; security
  review of PR #107), prints the application and invitation references held for the address the request came from,
  never the address, and counts member records it cannot name (`member_on_file`); exit 3 when nothing is nameable;
  `catalyst_invite` prints each invitation's reference. A person invited who never applied is erased by the
  invitation's reference. A first-generation member record with no application or invitation has no reference the
  erase function resolves; it is erased with the person's application or invitation, when one exists.
- **Process rule (a stated limit).** The retention login can call `catalyst_erase` directly, which would skip the
  durable record. The rule is that it is called only through the command, on the erase service; the replay is the one
  other caller.
- **The `9kg.28` host list.**
  - An operator-run erase service, separate from web and worker. It holds the retention login and the erasure key
    and nothing else.
  - The key file is `erasure_key` in `CATALYST_SECRETS_DIR`, 0400, on tmpfs, mounted only there and into the restore
    service for the replay. Its source is the operator's encrypted secret store, and it is in no backup set.
  - A web or worker process given the key refuses to start.
  - Rotation (`027`): keep the old key while any restorable backup predates the change, because the record names
    each entry's key id. A rotation never rewrites the journal.
- **The reviewed-safe reason for `erasure.0002`, and its rollback limits.**
  - It adds a table, functions and one guarded branch per trigger function. It removes and renames nothing.
  - A previous image runs on it unchanged: its writes never reach the checker, because the branch tests the
    retention login first.
  - The reverse strips the branches by their markers and restores the definitions byte for byte (tested against a
    database that never ran it).
  - A reverse after a real erasure leaves the tombstones and the journal entries in place: an erasure is never
    undone by a rollback. A reverse also removes the erase path until the migration is reapplied.
- **Deviation from the PR #88 data-review note.** The note asked for the retention-role branch in both pause-guard
  functions.
  - `catalyst_pause_fixed` has it.
  - `catalyst_pause_resume_guard`, the DELETE guard, does not. Erasure anonymizes a pause's reason and never deletes
    the pause, so a restriction is never lifted on the erasure path. A branch in a DELETE-only guard would admit
    nothing the erasure needs and would only widen the exception.
  - The test shows that a pause DELETE is still refused at commit, even with an audit row and the retention login.
- **Why the audit holds no hash.** The new audit holds codes only (a `CHECK` refuses free text) and no row digest.
  The keyed hash lives only in the journal, under a key that is never in the database. For an erased subject, the
  older `RetentionAudit` rows' free-text reason and unkeyed digest are tombstoned too (class `audit_residue`; its
  treatment is counsel's). The 0017 reason-based branch on inbound and outbound mail stays in place. It cannot be
  reached, because the retention role holds no UPDATE on those tables.
- **Chose** a branch injected after each function's first BEGIN (from its own `pg_get_functiondef`, removed by its
  markers on reverse) **over** copying the function bodies into the migration. **Chose** an erasure map generated into
  SQL **over** hand-written UPDATEs. The catalog test, the `pg_trigger` coverage test and the installed-function test
  keep the map, the schema and the database in step.
- **Not here.**
  - Replay after a restore (`9kg.25`; its handoff is in `029` section 6.2.1).
  - Custody key destruction (`9kg.34`; built since, recorded below).
  - Wiring the erase service and the key into the stacks (`9kg.28`).
  - The journal's off-host copy and rotation.
  - The owner decisions recorded in `029` section 6.2.1 (reissuing a mailbox name; pause versus erasure; the
    `audit_residue` treatment).
- **Evidence.**
  - `tests/test_erasure.py`: 25 tests, mapped under `P6_SUPPORTING` in group "9kg.32".
  - `tests/test_db_roles.py`: `TRIGGER_COUNT` 47 and the reverse-and-reapply offsets.
  - `tests/conftest.py`: the expected triggers.
  - `tests/test_database.py`: the approved migrations.
  - `tests/test_acceptance.py`: the named constraints.

**9kg.34, the custody copy encrypted at rest, with recoverable keys and crypto-shredding against old backups (P6-D-13
option c; council `030` Q3 and Q4, D-51 provisional; the storage location and access rules stay the owner's, `211.7.9`;
hardened after the PR #102 security, release-operations and data reviews).**

- **The claim.** Once a document's key is destroyed, its sealed copy, in custody or in any backup, old or new, cannot
  be opened without a surviving copy of the wrapped key and the wrapping key. Nothing here makes such a copy
  impossible; the limits below say where one can survive. The claim covers v2's custody copy only: the provider's
  copy is under P4-D-15 until POL-10, and every custody command and the erasure output say so.
- **What it is.** Every custody write is sealed with AES-256-GCM from the reviewed `cryptography` library (50.0.2,
  hash-locked in `requirements/base.txt`; `pip-audit` clean; the image installs wheels only). Each document gets its
  own random 256-bit data key, stored only wrapped under one wrapping key. The design is in `agreements/keystore.py`
  and the storage path in `agreements/storage.py`.
  - The sealed file keeps its `<uuid>.pdf` name, so every key check stays one pattern. A `CustodyEnvelope` row
    (agreements migration 0010, insert-only for every role) records the key reference and the SHA-256 and size of the
    sealed bytes.
  - `StoredDocument.sha256` is still the plaintext's hash. A read checks the sealed bytes against the envelope, opens
    them under their own key, then checks the plaintext against the recorded hash and size.
  - The associated data binds each sealed file to the scheme, its own name, its key reference and the recorded
    plaintext hash, and each wrapped key to its reference.
  - A write refuses without keys, in every environment. A write, a migration or a custody run that fails or finds the
    work decided meanwhile discards its new key and sealed file. A crash between the write and the record leaves an
    orphan pair that `--status` reports as unhealthy and `--reap-orphans` removes (a dry run by default; only orphans
    older than an hour; journaled).
  - Envelope rules (data review of PR #102, K5): one envelope per document; no repair or re-seal until wrapping-key
    rotation is built (a follow-up); `wrapping_key_id` is the wrapping key's id at seal time; an envelope not
    `migrated` names the document's own file. The database checks the digest and the key reference as hex.
- **Where the keys live.** Two directories, `CATALYST_CUSTODY_KEY_DIR` and its live mirror
  `CATALYST_CUSTODY_KEY_MIRROR_DIR`, one `<reference>.key` file per document (0600, in a 0700 directory owned by the
  process user). This is the same separation `9kg.32` uses for the erasure journal and its head.
  - Each directory carries a provisioning marker, written only by `catalyst_custody_keys --provision`. Nothing else
    creates a directory. A missing directory or marker refuses every operation (`key_store_unavailable`), so an
    unmounted volume is never read as an empty store.
  - A key absent from both directories and not journaled is `key_lost`, an outage (`custody_key_unavailable`), never
    an erasure. A reference the journal records as destroyed is refused even when a key file for it is present.
  - The backup copies only the database and the custody files its snapshot names by the custody-key pattern. It reads
    sealed files against the envelope's digest and needs no key.
  - The guards refuse a key directory inside or around the custody directory, the effect journal or the repository.
    `catalyst_backup` refuses to run holding the wrapping key, or with an output or custody directory that overlaps a
    key directory.
  - **Configured, not enforced, until `9kg.28`.** The backup's overlap check sees only the directories its own settings
    name, and the role isolation below is the compose definition and the guards, not a host boundary. Until
    `9kg.28` wires the volumes and the secret on the host, both are configuration. `scripts/staging_check.sh` checks
    that no staging service (backup, restore, fetcher, db and proxy included) mounts a key volume or the wrapping
    key, and it passed on the dev box (below).
  - A restore brings back rows and sealed files, never a key. `keystore.sweep(require_key=True)` finishes every
    journaled destruction at the restore lift (directories, journal and the erasure key; no wrapping key), so a
    restored or copied key file never outlives its destruction, and the lift refuses without the erasure key. At the
    web and worker start-up, which never hold the erasure key, the sweep only checks the directories and the journal
    (fail closed) and removes nothing: an unverified entry may be forged (CodeRabbit on PR #102), and `load` refuses
    a journaled reference meanwhile.
  - Like the custody directory, both settings are fixed in code and empty outside `test` and `staging` until the
    owner's custody decision.
- **The wrapping key.** `custody_wrapping_key` in `CATALYST_SECRETS_DIR`: 64 lower-case hex characters (32 random
  bytes), never one character repeated, distinct from the Django and link-signing keys, the erasure key, the
  database and mail passwords and the webhook secrets the process holds, and refused in the environment outside test
  and development.
  - It may reach the web process (retrieval, decision-makers only, P4-D-16), the worker (custody writes) and the
    owner-run custody commands.
  - The fetcher and the post-restore step refuse to start with it. `catalyst_backup` and `catalyst_erase` refuse to
    run with it: destroying a key needs only its directories.
- **Recovery, without defeating destruction.** Two safeguards, either of which alone keeps an erased document erased:
  1. *The escrow holds the wrapping key only.* Its recovery copy lives in the operator's encrypted secret store. A
     wrapping key opens a data key only while the wrapped data key still exists somewhere, so recovering the wrapping
     key alone does not recover a destroyed document.
  2. *The mirror is a live copy, and destruction reaches it first.* Every wrapped key is written to both directories
     before the document is sealed (a failed mirror write removes the primary copy too). It is destroyed in the
     mirror before the primary, and the destruction is verified in both.

  `catalyst_custody_keys --recover --expect-head <head>` copies between the two only keys the journal does not record
  as destroyed, and finishes any destruction left half done. It refuses a journal that does not hold the head kept
  out of band (PR #99), because an emptied or rolled-back journal would forget destructions.
  - Each `custody_key_destroyed` entry carries a mac under the erasure key. Sweep, recovery and the erasure remove
    files only on verified entries, refuse a forged one, and remove nothing without that key (recovery and the lift
    refuse `erasure_key_missing`).
  - Neither key directory may be in any versioned backup. That is an operator provisioning rule for the `9kg.28` host
    list: an archive of either would be a point-in-time copy that destruction cannot reach.
  - The named holder, the time bound and the escrow location are rows of `agreements/custody_policy.py`. They ship
    `undecided`, and a live environment refuses custody until they are decided. **Proposed for the owner:** the owner
    as holder, custody reads restored within 24 hours of a key-store loss, and the escrow in the estate's encrypted
    secret store.
- **The recovery runbook** (the named holder, on the host, with the worker stopped):
  1. Stop the worker (`docker compose stop worker`); web may keep serving everything but document retrieval.
  2. Run `catalyst_custody_keys --status` and read which directory lost what (`mirror_missing`,
     `primary_missing_recoverable`, `lost`).
  3. If a directory itself was lost, replace its volume and run `catalyst_custody_keys --provision`.
  4. Fetch the wrapping key from the escrow into the `custody_wrapping_key` secret file for this run only.
  5. Run `catalyst_custody_keys --recover --expect-head <the last head from the private operations record>`.
  6. Run `catalyst_custody_keys --status` again; it must report `healthy`.
  7. Restart the worker, then remove the secret file from wherever the escrow copy was placed for the run.
  8. *If both directories were lost:* recovery cannot rebuild them. v2's copies of every sealed document are lost;
     the provider's copy (P4-D-15) is the only source, and a re-fetch from it is a separate, owner-authorized act
     that this code does not perform. Record the loss in the incident record.
- **The erasure step.** The registry's `signed_documents` row now takes `retain` or `destroy_key` (shipped
  `undecided`, like every row).
  - Erasure migration 0003 re-installs `catalyst_erase`. Its custody part sits between inline markers, and the
    reverse reinstalls the function without it: byte for byte what 0002 installs, so a rollback of agreements 0010
    never leaves a function that reads a dropped table. A later migration that adds a subject column must reinstall
    the function (the PR #99 rule).
  - In one statement, the function reads the subject's sealed-document key references and the number of documents
    still in the clear. It is reachable for an already-tombstoned subject.
  - Under `destroy_key`, a subject is refused before any record when:
    - any of its documents is still in the clear;
    - a migrated document's plaintext still lingers;
    - a key directory is missing.

    The committed call's own count is checked again on every run, the resumed one included
    (`custody_plaintext_unmigrated_after_commit`, intent left open). A resumed run, which has no dry run, also checks
    both key directories before its committed call (`custody_key_store_unavailable`, nothing committed).
  - The command destroys each key after the database transaction and before the completion. Each destruction is
    journaled with its mac before its files are unlinked, mirror first, and verified gone from both directories.
  - The completion records `custody: keys_destroyed`, `keys_destroyed` (references) and `key_files_removed` (files).
    `custody_documents` leaves `retained` only then.
  - On a first erasure, the audit row's classes include `custody_keys_destroyed`. For an already-tombstoned subject
    the audit row rolls back and the journal is the declared record (`029` section 6.2.2).
  - An interrupted destruction leaves the intent open. The next run, recovery or the sweep finishes it.
  - The restore's lift and replay rules from PR #99 are unchanged, with the sweep added before the lift. Replay
    (`9kg.25`) needs no custody step.
- **Documents stored before this change, and the deploy order.** `catalyst_custody_keys --migrate --confirm` (one run
  at a time) reads each plaintext document (verified against its recorded hash), seals it under a new name and key,
  verifies it, commits its envelope and removes the plaintext. A lingering plaintext whose key is already destroyed
  goes without reopening the sealed copy, and one failure never blocks the rest: a document that cannot be sealed
  (missing, unsafe or changed) is counted in `seal_failed`, later documents still seal, and the run fails at the end.
  The order on a host:
  1. Apply the migrations (agreements 0010, erasure 0003).
  2. Mount the key volumes and the wrapping key's secret (`9kg.28`), and run `--provision` once.
  3. Deploy the image.
  4. Stop the worker and run `--migrate --confirm`.
  5. Run `--status`: `in_the_clear` and `plaintext_lingering` must be 0. Then restart the worker.
  6. Take the next backup: it is the first set with no plaintext custody file.
  7. Let the older sets, which may hold plaintext custody files, age out. Until they do, the claim does not cover
     them. None exists with real data: encryption precedes the Documenso canary.
- **Limits, stated** (review of PR #102, F5, F9, F10):
  - A surviving copy of a wrapped key plus the wrapping key opens a destroyed document. Such a copy can survive as:
    - a stray archive or snapshot of a key directory;
    - unlinked blocks not yet reused (unlinking does not scrub them, and on SSDs and copy-on-write filesystems no
      overwrite reliably does);
    - a key in swap or a core dump.

    The only way to retire such remnants is to rotate the wrapping key (rewrap every live data key), then destroy
    the old wrapping key everywhere, the escrow included. Rotation is built since (9kg.69, record below).
  - The processes that hold the wrapping key or a data key should run without swap and with core dumps disabled:
    host configuration for `9kg.28`.
  - Host disk encryption is separate, and it is not what makes erasure work.
- **The drill** (`scripts/restore_drill.sh`, a fourth stack). The drill command `catalyst_custody_drill`, synthetic
  only, provisions two key volumes of its own and points custody at them for its run:
  1. It stores two synthetic documents through the real write path, and both open with matching hashes.
  2. With the wrapping key mounted, the backup refuses (the negative control). Without it, the real staging backup
     writes a set that is checked:
     - the set holds both sealed files, and at least three files and eight needles were read;
     - it holds no key file, no wrapped key, no data key and no wrapping key (raw, hex or base64), and no plaintext
       marker.
  3. One key is destroyed with the erasure's step (journaled with its mac), and the live copy is refused. The erasure
     command itself refuses while the POL-10 registry is undecided.
  4. The database is removed and re-created, and the older set is restored into it with its rows and both sealed files:
     - the restored directory holds both sealed files and no plaintext;
     - the document whose key survived opens with a matching hash (the positive control);
     - the destroyed one is refused with `custody_key_destroyed`;
     - the journal names its key with a verified mac.
  5. The volume list is the same before and after the leg.
- **The drill on the dev box, 2026-10-25** (`scripts/restore_drill.sh` at `6e29c2f`, the branch after the merge from
  `main`): **59 PASS, 0 FAIL, 1 NOT RUN** (the off-site leg, below). The custody leg's 16 cases all passed, the positive
  and negative controls included, and the leg left no volume behind. Measured: backup 4 s; recovery from an empty host
  to serving 93 s; restore, post-restore and start alone 46 s. The earlier run of 54 PASS at `4d8f7b9` came before the
  custody leg was rewritten in review G and is superseded.
- **The staging check on the dev box, 2026-10-24** (`scripts/staging_check.sh` at `8ee1d10`): **140 PASS, 0 FAIL, 0 NOT
  RUN**. The seven 9kg.34 cases are among them: no service's configuration (the operator profiles included) names a
  key volume or the wrapping key, and none of web, worker, fetcher, egress, proxy and db mounts one.
- **NOT RUN: the off-site, object-locked copy.** It is reached only through the host's backup fabric, never from this
  repository. The live-chain drill (the key directories shown absent from every backup set, including the off-site
  leg) is an item of the go/no-go evidence (`029` section 11) and of TEST-P6-21's residual in the evidence register.
- **Owner decisions left open (`211.7.9`):** the custody location, the access rule (D-51 proposes decision-makers
  only), the recovery holder and time bound, the escrow location, and the provider copy's treatment with POL-10.
- **Evidence.**
  - `tests/test_custody_encryption.py`: 32 tests, mapped under `P6_SUPPORTING` in group "9kg.34". They cover:
    - encrypt and retrieve;
    - destroy-key;
    - the restore of an older backup through the real backup and restore commands;
    - recovery and the out-of-band head;
    - migration and lingering plaintext;
    - orphans;
    - the sweep and the mac;
    - the start-up guards;
    - the erasure step and the registry;
    - erasure 0003's reverse;
    - the plaintext race;
    - the audit class;
    - the envelope rules;
    - the staging services;
    - the drill's shape.
  - `tests/test_agreement_custody.py`: the custody fixture provisions keys, the stored file is sealed, and a changed
    envelope leaves no key or file.
  - `tests/test_db_roles.py`: `TRIGGER_COUNT` 51 (49 before main's oc4.9 approvals were merged in).
  - `tests/conftest.py`: the expected triggers.
  - `tests/test_database.py`: the approved migrations.
  - `tests/test_acceptance.py`: the named constraints.
  - `tests/test_image.py`: the wheels-only install.

**9kg.39, the egress proxy's deny list of the estate's production hosts (TEST-P6-28; split from `9kg.27`;
2026-10-24).**

- **Built.** `assessments/egress.py` loads a deny list from the file named by `CATALYST_EGRESS_DENY_FILE`, read by
  the proxy alone (the fetcher, the Documenso and mail adapters never read it, and only the `egress` service has the
  variable).
  - Format: ASCII, at most 64 KiB and 256 names, one dotted DNS name per line, `#` comments and blank lines
    ignored. Each entry denies itself and every name under it. An address, a single label, a name with an all-hex
    label (`0x7f.0x0.0x0.0x1`) or any other entry makes the file malformed.
  - A missing, unreadable, oversized, empty or malformed file refuses every request with a 503
    (`deny_list_unavailable`), which the fetcher treats as transient and retries; the code is logged once at start,
    and the egress service's healthcheck (`python -m assessments.egress --check`) fails while the list does not load.
  - A denied name is refused before any lookup (`host_denied`).
  - Every address the target resolves to is refused when it is an address of a denied name (`address_denied`), and
    so is the connected peer (`peer_denied`). The denied names are resolved afresh at both checks, in one lookup
    pass (one thread) under one deadline. Each name keeps its fresh answer in full and up to 64 addresses in all, the
    oldest address not in the fresh answer evicted first, so a DNS change toward a production address between the
    check and the connection is caught at the peer, and one away from it does not at once reopen the old address.
    There is no global limit that could latch the proxy shut.
  - Addresses compare in one form: the zone dropped and IPv4-mapped IPv6 unwrapped.
  - A denied name that does not exist denies nothing. One whose lookup fails or times out keeps its last good
    answer (logged as `deny_lookup_stale`); only a name that has never resolved refuses, as transient (502,
    `deny_list_unresolved`). A list in which no name resolves to anything refuses everything (503,
    `deny_list_resolves_nothing`), and at start the proxy logs `deny_names_unresolved=N`, a count, never a name.
  - Each fetch and each redirect hop is its own CONNECT, so every hop passes every check. The outcomes are codes
    only; the file's content is never logged.
- **The real list.** The repository holds synthetic names only (`tests/egress-deny.example`,
  `deploy/staging/egress-deny`). The estate's real production host names are an operator-supplied file, mounted
  read-only into the egress service at deploy time; that is a host-preparation item of `9kg.28`. The evidence
  register keeps TEST-P6-28 partial on `9kg.39`, whose boundary is enabling fetching, so the real list blocks
  exactly that (PR #101 security review).
- **Staging.** `deploy/staging/egress-deny` holds the synthetic names and one public stand-in for a production host
  (`one.one.one.one`, not a host of this estate), bind-mounted read-only at `/etc/catalyst/egress-deny` into the
  `egress` service alone, the way production mounts the real list.
- **Evidence.**
  - `tests/test_egress.py`: 25 new tests (17, then 8 from the security review), mapped under TEST-P6-28, cover:
    - the name, and a name under it, refused before any lookup;
    - a resolved production address in IPv4, IPv6 and both IPv4-mapped spellings;
    - a DNS change between requests and between the check and the connection (the peer), and the union kept
      across a move;
    - an unresolvable deny name, and missing, empty, comment-only, malformed, non-ASCII and oversized files;
    - a redirect to a production name and to a name resolving to its address, with a positive control fetch to a
      `.test` fixture through the proxy;
    - link-local, metadata, private and tailnet answers in IPv4, IPv6 and mapped forms;
    - numeric encodings (decimal, octal, hex, short) and IP literals;
    - schemes other than https and ports other than 443;
    - that only the proxy reads the list.
  - The production addresses in the tests are documentation addresses, which the test admits as public so that only
    the deny list refuses them, as it must for a real production host.
  - `scripts/staging_check.sh`: five TEST-P6-28 checks, run once on the dev box on 2026-10-24 (132 PASS, 1 FAIL).
    All five new checks and every TEST-P6-30 check passed: the stand-in refused by name, a name under it refused,
    `1.1.1.1.nip.io` and `1.0.0.1.nip.io` refused by resolved address, and the file present in the proxy and absent
    from the fetcher. The tunnelled public name is the control and shows the list loaded.
  - The one FAIL was outside this change: "TEST-P6-27 no other registered action exists outside the held state".
    Since PR #97 (`9kg.66`), migrate schedules the verification-expiry sweep, whose kind was not in that check's
    allow-list.
- **Scope extension (decided by the coordinator, its own commit): the TEST-P6-27 check admits the sweep.** The
  dark-deploy check counts every registered action outside the held state except an allow-list. It now also admits
  `verification_expiry_sweep`, and only as itself: its one system subject, in the states `queued`, `running` or `done`
  (a pass that ran and queued its successor). A failed or uncertain sweep, or any other new kind, still fails the
  check, and the control now also requires the sweep's kind to be registered. No test pinned the allow-list, so
  none changed. Re-run once on the dev box, 2026-10-24: `scripts/staging_check.sh` **133 of 133 PASS, exit 0**,
  every TEST-P6-27, 28 and 30 check included. That run's image was built from the working tree with the extension
  not yet committed, so the drill revision in the evidence register is left unchanged.
- **Security review of PR #101 (2026-10-24), one commit per finding:** the per-name address bound without a latch;
  the last good answer and one lookup pass; the visible all-unresolved list; the broken list as a transient 503
  with a start-up code and a healthcheck; all-hex labels refused; a test that egress refusal codes stay staff-only
  (never in the model request the clarification path starts from, a mail or a non-staff template); the register's
  blocker edge to enabling fetching (above); and the staging by-address checks reported NOT RUN, never FAIL, when
  the proxy cannot reach public DNS. `scripts/staging_check.sh` after the review, on the dev box, 2026-10-24: at
  `078d481`, 132 PASS, 0 FAIL, 1 NOT RUN (one by-address case on a single transient lookup failure, the next one
  passing), after which the DNS probe retries like the other proxy checks; at `6ea22c5` (committed, clean tree),
  **133 of 133 PASS, exit 0**, with the egress healthcheck passing `compose up --wait` and every TEST-P6-27, 28 and
  30 check green.
- **Stated limits.**
  - The proxy trusts its resolver: a resolver that answered the deny names falsely would hide their addresses, so
    network isolation and the host allow-list stay the controls that hold against that.
  - A `peer_denied` connection has completed its TCP handshake with the denied host before the proxy refuses it;
    no byte is sent through it and it is closed at once.
  - The file is read once, at start: a change to the list needs a restart. A bind-mounted file replaced on the host
    (a new inode, as most editors and `mv` produce) leaves the running container on the old content, so mount the
    directory rather than the file, or restart the egress service after every change.
  - The "only the proxy reads the list" test scans a fixed list of application packages (`APP_PACKAGES` in
    `tests/test_egress.py`); a new package must be added there.
  - The staging stand-in and `nip.io` are outside dependencies of the staging check, like the existing TEST-P6-30
    cases; without public DNS the by-address cases print NOT RUN.

**9kg.25, the erasure record replayed after a restore (TEST-P6-29; P6-D-13 option d; `029` section 6.2.1;
2026-10-26).**

- **Why.** A restore takes the tables back to the backup's time T, so every erasure made after T is undone in them.
  The durable record (`9kg.32`) is in the effect journal, outside the backup's rollback domain, and still names each
  one. Until this change, the lift refused whenever the journal held an erasure, so a restore after any erasure stayed
  held for good, and `catalyst_backup` refused in a live environment (`replay:not_built`).
- **The order on a restored host:** restore, migrate, **replay**, review, lift.
- **The replay** (`catalyst_erasure_replay --expect-head <head>`, `erasure/replay.py`), run by the owner with the
  retention login and the erasure key (the erase service's mounts; never the custody wrapping key):
  1. It verifies the record: the key, the chain, every entry's mac, and the head kept out of band from the last
     erasure (`none` only when no erasure was ever made). An emptied, replaced, truncated or rolled-back journal, a
     missing key, a forged entry or an undecided registry refuses, and the restore stays held.
  2. For every subject with an erasure, completed or still open, it calls `public.catalyst_erase_replay` in the
     subject's own transaction, with the registry's classes and the intent's authority and reason. The audit row is
     written as for an erasure, under the same login.
  3. It appends one `erasures_replayed` marker with its mac, keyed by the restore it answers (the seq of the
     journal's last `restore` entry) and naming the seq of the last erasure entry it covered.

  The replay also finds a person by the recorded subject hash, over every restored application, invitation and
  first-generation member record. That covers the usual case under invitation-only intake: invited before T, then
  applied and erased after it. A key that only a member record carries is erased through the function's optional
  `p_key`. A subject with nothing left in the restored tables is satisfied (`absent`). One the backup already held
  erased changes nothing (`already`). A restored key that does not hash to the recorded subject refuses the whole
  replay before anything is erased (`replay_subject_mismatch`): no code path changes an application's key, so a
  mismatch is an altered row or record, never a moved address. Each subject is re-erased with the classes its
  erasure anonymized together with those the registry anonymizes now.
- **Why a second function.** The erase function refuses an open application, work in flight and an access revocation
  that is not final. The restored rows are as they were before the person was closed out, so those refusals would
  hold the restore for good. Erasure migration 0004 installs `catalyst_erase_replay`, generated by
  `catalog.erase_sql(..., replay=True)` from the same map: the same function under its own name, without those three
  refusals, and refusing instead unless the restore hold row is present (`CE008`). That means it can never skip them
  on a database in service. It is SECURITY DEFINER, owned by the owner, and EXECUTE for the retention role only. Expand-only;
  the reverse drops it. A later migration that adds a subject column reinstalls it beside `catalyst_erase`.
- **The review and the lift.** Both refuse until a marker for the current restore verifies under the erasure key and
  covers every erasure entry (`erasure replay missing (<code>)`: `unreplayed`, `stale`, `forged_marker`, or a key or
  journal code). Only a marker written after the hold was placed counts, so a marker from an earlier restore or
  drill never answers this one. An erasure made during the hold is a later entry, so it needs another replay. The
  review checks the marker's presence and coverage without the key, so the run that reads the providers never holds
  it; the lift verifies the mac under the erasure key, which it already held for the custody sweep. Where no journal
  is configured (test and development only) there is nothing to replay.
- **What the refusals guarded, settled as the owner** (`settle_erased`, after the journal's replay in the review):
  - every live action of an erased subject is cancelled (`subject_erased`): it would act on tombstones or reach a
    provider for a person who is gone;
  - an erased subject still open, or with an access revocation that is not final, after the journal's closures and
    revocation outcomes are re-applied gets one `restore_effect_erased_subject_open` item. The lift waits for it: the
    owner confirms at the provider and closes the application by hand;
  - the link, setup and withdrawal items and the revocation rounds leave erased subjects out, so nobody is asked to
    write to an erased person.
- **Custody.** A destroyed key is outside the rollback domain. The restored row points at a sealed file no
  surviving key opens, and the lift's sweep removes any key file journaled destroyed. The erased subject's sealed file
  keeps its ciphertext hash, so later backups verify it as before (the drill takes one). One exception: a set taken
  before a document was sealed brings its plaintext back. Under `destroy_key` the replay writes no marker while an
  erased subject's document with no envelope has its file on disk (`replay_custody_plaintext_restored`); the owner
  removes the file and replays again. No such set holds real data (custody encryption precedes the Documenso canary).
- **A second replay is harmless** (every subject `already`, another marker). **An interrupted replay** wrote no
  marker; it is run again.
- **Stated limits.**
  - The hold is procedural for the web process: it serves the restored rows as soon as it starts, so nothing starts
    before the lift (section 6). The drill says so.
  - The retention login can call `catalyst_erase_replay` while a hold is present, which would skip the marker. As for
    `catalyst_erase`, the rule is that it is called only through the command, on the erase service. The hold itself
    can be placed only by the restore's load or the owner: workflow migration 0006 refuses an application-role INSERT
    of a `system` pause row, as 0004 already refused its UPDATE and DELETE (security review of PR #103).
  - Rows found only through the address and readable only by the erase function stay as restored when no
    application, invitation or member record at T carries that address: inbound mail from it and its intake throttle
    bucket. The retention role cannot read inbound mail (follow-up bead `9kg.71`).
  - An erasure still open at T (its completion never written) is replayed too, without the refusals: the owner
    authorized it and its intent names the person, so re-applying it is the restrictive direction.
  - The mailbox read leaves erased subjects out: their reserved name is a tombstone, so a read by it says nothing (the
    mailbox is a recorded handoff).
  - `registry.REPLAY_BUILT` and the `replay:not_built` problem are removed. A live backup still refuses while any
    registry value is undecided (POL-10).
- **Operator runbook addition** (after the restore and `migrate`, before `catalyst_post_restore`): on the erase
  service, run `catalyst_erasure_replay --expect-head <the last head from the private operations record>`. Keep its
  printed head with the others. Run it again after any erasure made during the hold.
- **The drill** (`scripts/restore_drill.sh`):
  - main leg: the review refuses before the replay; the replay runs as the retention login with head `none`; the
    review and lift hold the erasure key;
  - fourth stack, rewritten from the custody leg: the seeded applicant is erased after the backup by the real
    erasure command (`catalyst_erasure_drill` installs a decided synthetic registry for its own process). Then:
    1. the older set is restored, and holds the address again (the control);
    2. the review refuses;
    3. a replay with head `none` is refused (`record_journal_mismatch`);
    4. the replay with the head re-erases the subject, and no table holds the address;
    5. the applicant nobody erased is still there;
    6. a second replay changes nothing;
    7. the review runs past the replay gate. Its only missing evidence is the envelope read: staging has no
       Documenso, and this stack holds the seeded agreement records. So the lift keeps the hold for that evidence,
       never for the erasure. The lift after a replay is shown on the main leg, and the marker's re-read at the lift
       is in pytest;
    8. a backup afterwards runs.
- **Reviews of PR #103 (data, security), fixed in the same PR:** the subject-hash match, the mismatch refusal, the
  class union, the plaintext check and the mailbox exclusion (data); the hold's INSERT guard, the marker bound to the
  hold's time and the key kept out of the review (security). Erasure 0004 now depends on workflow 0006.
- **The drill on the dev box, 2026-10-26** (`scripts/restore_drill.sh` at `c5dcb17`, after the review fixes; the
  reviews now run without the erasure key): **76 PASS, 0 FAIL, 1 NOT RUN** (the off-site, object-locked leg, as
  before). All 17 new 9kg.25 cases passed, the controls included. Measured: backup 4 s; recovery from an empty host to
  serving 109 s; restore, post-restore and start alone 58 s. The same tally at `923ac37`, before the review fixes.
  Re-run on `main` at `0211ce9` (2026-10-26), after the rotation's store lock (#104), the custody health part (#105),
  the journal's off-host copy (#106) and the subject lookup (#107) touched code the drill exercises: **76 PASS, 0 FAIL,
  1 NOT RUN** (the off-site leg); backup 4 s, recovery from an empty host to serving 97 s. No proof was invalidated.

  The run before it, at `8b80642`, had 74 PASS and 1 FAIL. That FAIL expected the fourth stack's lift to release,
  which it cannot without Documenso evidence; the check was corrected to what the stack can show (step 7 above).
- **Evidence.**
  - `tests/test_erasure_replay.py`, mapped under TEST-P6-29 and in group "9kg.25". The tests cover:
    - a real backup, three erasures after it (one open with queued work at the backup, one whose address changed,
      one created after), a real restore, the refusals, the replay, a second replay, the review and the lift;
    - grants and the hold;
    - missing, forged and stale evidence;
    - an interruption;
    - a subject left open;
    - the process guards;
    - the drill command and the drill's shape.
  - `tests/test_erasure.py`: the installed functions, definer and reverse tests extended to the new function.
  - `tests/test_post_restore.py`: its helper writes the marker for tests about other things.
  - `tests/test_database.py`: the approved migration.

**9kg.60, the effect journal shipped off the host (029 section 6.2's deferred item; 2026-10-26).**

- **Why.** The journal lives on a volume on the same host as the database. Host loss is the usual reason to restore,
  and the effects after the last backup then have no copy anywhere. The restore drill carries the journal by hand
  from a volume that still exists, which models a planned move, not a loss.
- **Built** (`workflow/shipping.py`, revised after the release-operations review of PR #106):
  - `catalyst_journal_ship --to <dir> --provision`, once, writes a marker on the mounted destination. Every run
    refuses a destination without it (`destination_unprovisioned`), so an unmounted mount point is never shipped to.
  - `catalyst_journal_ship --to <dir>` takes an exclusive lock on the marker. It copies the journal bytes whose chain
    it verified in one locked read, under a temporary name, then fsyncs and renames. It reads the copy back (its digest
    must match), then writes `head.json` and reads it back, then records the run beside the journal (`effects.shipped`,
    with `shipped_at`). An interruption leaves the copy's journal at or ahead of its head, never behind it. A copy
    with no head is anchored on its own last entry.
  - It refuses a destination inside the journal, the repository, custody or a key directory.
  - It refuses (`destination_ahead_of_journal`) when the copy holds entries the local journal lacks. **Operator
    action:** stop; restore the local journal from the copy; ship again. Only after an owner-accepted loss (below),
    `--rebaseline` moves the old copy aside under a dated name (it is kept) and the next run starts a new copy.
  - The `journal` health part, when `CATALYST_JOURNAL_SHIP_LAG_SECONDS` is above 0, pages under these codes:
    - `effect_journal_ship_lag`: the oldest unshipped entry is older than the threshold;
    - `effect_journal_ship_stale`: no completed run within the threshold, so a dead timer pages even with no new
      effects;
    - `effect_journal_never_shipped`;
    - `effect_journal_behind_shipped`: the local journal lost what it shipped;
    - `effect_journal_shipped_unreadable`: the local record cannot be read.

    A live environment refuses to start with the threshold at 0.
  - `catalyst_restore --shipped-from <dir | none>` reads the copy's head from the provisioned destination; it is
    never typed. Before the load, it refuses a local journal that does not hold that head. The owner's override is
    `--accept-journal-behind-shipped`. The restore entry records `behind_shipped` and the copy's `shipped_seq`. A
    live restore must name the copy; `none` (nothing was ever shipped) is accepted there only with the override.
- **The host runbook after a host loss** (a `9kg.28` item):
  1. Mount the destination on the new host.
  2. Copy `effects.jsonl` from it into the new journal volume (directory 0700, file 0600, owned by the service user).
  3. Restore the newest backup whose receipt head the copied journal holds, with `--shipped-from <destination>`.
     `check_journal` refuses a backup newer than the copy.
  4. Ship once immediately before every backup, so the newest backup's head is always in the copy (the backup
     timer's pre-step).
- **The host's part** (`9kg.28`). Each item below is PENDING:
  - the destination: another machine or mount, never inside the backup output (a backup store is not a backup
    source), and its own retention and immutability;
  - the timer and its cadence, and where a failed run is routed;
  - the threshold value, which is the journal's RPO and the owner's (`211.7.2`);
  - a real host-loss drill: ship, destroy the source volume, copy, restore, lift;
  - alert drills for the lag, stale, never-shipped and behind-shipped codes.
- **Evidence:** `tests/test_journal_shipping.py`, 11 tests, mapped under `P6_SUPPORTING` in group "9kg.60". They cover:
  - a whole copy with a matching head, and unsafe destinations refused;
  - a rolled-back local journal never overwriting the copy;
  - the lag, never-shipped and behind-shipped signals;
  - the live threshold guard;
  - the shipped-head check, with its override;
  - a real restore refused before the load, then accepted and recorded;
  - the command;
  - from the review: an unmounted destination refused and a second run waiting, a copy without its head anchored on
    itself, a rebaseline that keeps the old copy, and the stale and unreadable codes.
- **Not yet shown:** the restore drill still carries the journal by hand. A drill leg that ships to an off-host
  directory and restores from it after the source is gone belongs with the host destination (`9kg.28`).

**9kg.69, rotating the custody wrapping key (`027` section 2; 2026-10-26).**

- **Why.** A surviving copy of an erased document's wrapped key, plus the wrapping key, still opens that document.
  Such a copy can be a snapshot, unlinked blocks, a copy-on-write or SSD remnant, or an object-locked off-site copy. No
  code can reach those copies. Rotating the wrapping key and then destroying the old one everywhere leaves them with
  no key that opens them.
- **Built.** `catalyst_custody_keys --rotate --expect-head <head>` (`agreements.keystore.rotate`), run by the owner
  with web and worker stopped and the next key mounted for that run only (`custody_next_wrapping_key`; every other
  process refuses to start holding it):
  1. The journal must hold the out-of-band head, as for `--recover`.
  2. Every journaled destruction is finished first, and a destroyed key is never rewrapped.
  3. Both directories must hold the same live keys (`key_needs_recovery` otherwise).
  4. Each copy is unwrapped under the current key, wrapped under the next, checked to give the same data key, and
     replaced atomically (a temporary name, fsync, rename).
  5. Every live document is opened under the next key and its hash checked. Only then is `custody_rotation` `done`
     journaled (key ids and counts, never a key).

  `--retire-old-key <from_key> --expect-head <head>` runs after the owner made the next key current and destroyed the
  old one, escrow included. It refuses while this process still holds a next key, while the named key is still
  current, or while any key file is still under it. Then it journals the retirement.
- **Interruption** is safe and deterministic: each wrapped key names the key it is under, every copy is under one of
  the two keys the owner still holds, and the same command run again finishes the rest. A key wrapped under a third
  key refuses the run (`rotation_incomplete`), and nothing is journaled as done.
- **Security review of PR #104, fixed in the same PR:**
  - a rotation's temporary copy is removed on any failure, and a destruction removes it too;
  - retirement and the health part refuse any stray file in a key directory;
  - a rotation holds the key store exclusively, and creating or destroying a key holds it shared, so neither can
    interleave with the rewrap;
  - the next key refuses outside the owner-run management process, and the worker refuses to start holding it (the
    start-up guards run before a worker declares itself);
  - retirement needs a rotation from that key journaled done, and no destroyed key's file left behind;
  - the two copies of a key must carry the same data key;
  - the next key must differ from every other secret.
- **The claim, precisely:** after retirement no key opens a remnant wrapped under the old key. A data key that itself
  leaked (in swap or a core dump) is outside it: rotation changes the wrapping, not the data keys. The retirement
  entry is the owner's attestation that the old key is destroyed; code cannot see the escrow or a running process.
- **Not covered by code:** destroying the old key's escrow copy and any copy outside the host, which is the owner's
  act, recorded by `--retire-old-key`. The rotation interval is the owner's (211.7.9). On the host, the next key's
  mount for one run is part of 9kg.28.
- **Evidence:** `tests/test_custody_rotation.py`, mapped under `P6_SUPPORTING` in group "9kg.69". It covers:
  - every live key rewrapped, every document open, a destroyed key never revived, and the journal shape;
  - a remnant under the old key that no current key opens after retirement, and a stray old-key copy that blocks
    retirement until the same rotation finishes it;
  - an interruption part way through, with every copy still openable, finished by a rerun;
  - the refusals;
  - the next key held only by the owner-run rotation;
  - `027`'s custody row.

**9kg.70, the custody health part (release-ops review of PR #102; 2026-10-26).**

- **Why.** Until now `catalyst_custody_keys --status` was manual. A lost mirror, a lost key, a destroyed key still
  present, an orphan, or plaintext still in the clear reached neither the health command nor Buzz.
- **Built.** `config.system_health.custody_health`, part `custody` of `catalyst_health`. It reads the store without
  the wrapping key, in the health process's role, and reports counts only. Each fault pages under its own code:

  | Code | Condition | Operator action |
  |---|---|---|
  | `custody.key_store_unavailable` | a key directory or its marker is missing (`store` names which) | mount it, or `--provision` a replaced volume, then `--recover` |
  | `custody.key_store_unsafe` | a key directory has the wrong owner or mode (`store` names which) | restore 0700 and the service owner |
  | `custody.wrapping_key_mismatch` | key files under a wrapping key this process does not hold (a replaced secret file, an older key directory put back) | mount the right key from the escrow; never re-key by hand |
  | `custody.key_lost` | a sealed document's key is in neither directory and was never journaled destroyed | `--recover` from the mirror's device; if both are gone, the provider's copy is the only source (`027`) |
  | `custody.recovery_incomplete` | a live key in one directory only | `--recover` |
  | `custody.copies_differ` | the two copies of a key differ | stop the worker; `--status`; restore the copy that unwraps, through `--recover` |
  | `custody.destroyed_still_present` | a destroyed key still has a file | the restore lift's sweep, or `--recover` |
  | `custody.destroyed_without_erasure` | a destruction whose subject has no erasure in the record | treat as an incident: a mistaken or forged entry may be hiding a real loss |
  | `custody.in_the_clear` | a document stored unsealed, or a migrated document's plaintext lingers | `--migrate --confirm` |
  | `custody.orphans` | a key or a sealed file no record names, older than the settle window | after a crash, `--reap-orphans`; after a database restore to an older time, do not reap (those keys may be needed) |
  | `custody.key_invalid` | a key file that is unreadable or does not unwrap, or a stray file such as a rotation's temporary copy | `--status`; finish or rerun the rotation |
  | `custody.rotation_incomplete` | a rotation begun and not done, or keys under two wrapping keys | run the same rotation again (`027`) |
  | `custody.journal_unavailable` | the journal cannot be read, so `key_lost` and `orphans` are withheld | the journal's own codes (`effect_journal_*`) |

  A key file, a sealed file or a destruction younger than the settle window (`CUSTODY_SETTLE_SECONDS`, 600 s) is left
  out of the orphan, recovery and destruction counts, so a write or a destruction in progress never pages. A planned
  rotation or migration pages by design while it runs. When this process holds the wrapping key, each key under it
  is also unwrapped.
  An erased document's absent key is the intended outcome. It is counted (`erased_documents`) and never paged.
- **Deviation from the bead:** a missing mirror copy pages instead of warning. The mirror is the only recovery
  copy, so one more loss would lose the document, and the health adapter has no warning level.
- **The release-operations review of PR #105**, fixed in the same PR:
  - the wrong wrapping key and copies that differ;
  - a destruction with no erasure on record;
  - a settle window against false pages;
  - loss codes withheld while the journal is unreadable;
  - the store fault split and named;
  - every read guarded, so the part never fails the whole report;
  - the operator-action column above.
- **The page path** is the generic one, `health.sh`, then the alert floor at `high`, which the alert drill proves
  for other codes. A custody code is shaped like every other (`part.name`).
- **NOT RUN:** the staging alert drill for a custody condition. The staging services hold no custody configuration
  until `9kg.28`, so the part reports `configured: false` there. That case is a host-preparation verification item.
- **Evidence:** `tests/test_custody_health.py`, mapped under `P6_SUPPORTING` in group "9kg.70". It covers:
  - a healthy store with an erased document, which raises nothing and prints counts only;
  - each fault under its own code;
  - keys under two wrapping keys;
  - an unconfigured store;
  - the health command exiting 1 and naming the code.

### The production-host preflight (9kg.42, 2026-10-29)

- **Record:** the private operations record, sha256 `bc25928665f34337ea8dccf7943bbf889a3a09e745ed90abda1d11a6e42f5aea`.
  Read-only, items H1 to H17, 22 answered and 3 UNKNOWN (H11, H13, H14). Re-read after `9kg.86`: sha256
  `4bb39320ca983ec98411571e714b987bbcdad0a946ce8934b174b6dfeace10fb`, 24 answered.
- **Findings and consequences:** `032` section 2.3.

## 17. The aged-waits health part (9kg.51, 2026-10-23)

`029` section 5.2 listed the waits with no bound once the first-generation owner notices retire: an application in
`assessing`, `awaiting_decision` or `on_hold`; an open staff item; a pause; a reply awaiting staff processing; a
sent agreement awaiting the applicant's signature or the countersignature; a `provision_activate` action requeued
because the provider was unavailable. Built, in `config.system_health.aged_waits_health`, one part of the health
report (`catalyst_health`, the staging adapter `health.sh`, the Buzz floor):

- **One class per wait.** Each class is counted past its own threshold and its oldest age is printed
  (`waiting`, `aged`, `oldest_seconds`, `threshold_seconds`, `pages`). A stage's age runs from the latest transition
  event into that stage; the others from the row's own time (opened, created, received, last status change).
- **Thresholds and paging are the owner's values** (`211.7.2`, `211.7.7`): `CATALYST_HEALTH_AGED_WAIT_<CLASS>_SECONDS`
  each defaults to the pending-age target `CATALYST_HEALTH_PENDING_AGE_SECONDS` (3600 s, a placeholder), and
  `CATALYST_HEALTH_AGED_WAITS_PAGE` (default: every class) names the classes that raise the anomaly
  `aged_waits.<class>`, which the floor delivers as high; a class outside the list is counted and printed, audit only.
- **Codes only.** No identifier of an application, item, message or agreement is in the report (tested). No action
  is taken and no mail is sent: the part is a signal, staff act on their screens.
- **Age semantics (review of 2026-10-23).** `assessing`, `awaiting_decision` and `on_hold` age from the latest
  transition event into the stage; `open_staff_items` from `opened_at`; `pauses` from `created_at` and count
  application pauses only (the restore hold is a `system` pause with its own signal, `catalyst_post_restore`);
  `replies_awaiting_processing` from `received_at`; `issued_agreements` from the instance's `updated_at`, the last
  status change, not the send itself; `provisioning_activation` from the action's `created_at`.
- **Default page list.** Until the owner sets values, only the three classes that are bad in themselves page:
  `replies_awaiting_processing`, `issued_agreements`, `provisioning_activation`; the stage, item and pause classes
  are counted and printed, audit only. The health report also carries `decision.qualification_authority_configured`.
- **Held follow-ons (`9kg.57`, 2026-10-24).** The class `held_followons` counts the follow-ons left held for the owner's
  release or a policy: `send_decline` (the decline notice, `oc4.11`), `issue_nda` (released by `activate_agreements`)
  and `provision` (released by `activate_provisioning`). An application in `agreements_complete` waits on exactly
  that held `provision` hand-off (`021` step 8, `023` 11.11), so the stage is counted once, through its hand-off, not
  as a second class. Counted by kind and status (`held`) only, whether or not a handler exists for the kind. **Age
  semantics:** from the action's `updated_at`, which is when it was created held or last returned to held (a refused
  `issue_nda` goes back to held with a new `updated_at`); nothing else updates a held row, and a released, cancelled
  or done follow-on leaves the class. Its threshold is its own setting,
  `CATALYST_HEALTH_AGED_WAIT_HELD_FOLLOWONS_SECONDS` (default: the pending-age target, a placeholder until `211.7.2`).
  It is **not** in the default page list: at the internal launch a held decline notice and a held provisioning
  hand-off are the plan, not a fault; the owner lists it when the release is due. The class also prints
  `aged_by_kind` (kind names and counts only).

Tests: `tests/test_system_health.py` (`9kg.51` in `tests/acceptance.py` P6_SUPPORTING): every class fresh raises
nothing, past its threshold raises its code, and clears when resolved; thresholds and paging per class. `9kg.57`: each held
follow-on kind aged past the class threshold raises `aged_waits.held_followons`, a released or cancelled follow-on and a
held action of another kind are not counted, and a follow-on returned to held ages from its return.

## 18. Production admitted in code (9kg.31.11, 2026-10-27)

`031` section 8, conflict 3: the guards admitted only `development`, `test` and `staging`, and the compose renderer
hard-coded `staging`, so no release could start as production. Built, as repository work only; nothing here starts
production on a host, which stays the owner's go (`9kg.31.5`, `029` section 13).

- **Admission.** `config.guards.ALLOWED_ENVIRONMENTS` names `production`; `DEPLOYED_ENVIRONMENTS` (`staging`,
  `production`) carries the deployment rules; `LIVE_ENVIRONMENTS` (`production`) the live ones. Every rule written
  for "outside test and development" now applies to production: secrets only from per-secret files, the staff host
  and local hosts, the worker heartbeat, the effect journal directory, https behind the proxy with secure host-only
  cookies, staff two-factor, and `check --deploy` clean.
- **Live refusals kept, each tested in production.** The mail allow-list with the pinned v2 login, the denied
  first-generation login and the Sent-folder evidence source (`9kg.49`); the journal ship-lag threshold (`9kg.60`);
  custody refused while the owner's custody decision is open (`211.7.9`); the backup refused while the erasure
  registry is undecided (`211.7.1`); no unapproved wording served (`9kg.52`). Off in production, as in every
  non-synthetic environment: model advice (`CATALYST_ASSESSMENT_MODEL` is `none`), evidence fetching (no fetchable
  host, fixture or trust store), the agreement provider and the provisioning adapter (every setting refused), and
  every provider credential in the environment.
- **New live rails** (`config.guards.live_problems`), failing closed after the PR #118 security review:
  - intake stays invitation-only (open intake is the public cutover);
  - the public base URL is exactly `https://<host>`, with no user part, port, path, query, fragment, backslash,
    percent sign or white space;
  - the public and staff hosts are distinct plain lower-case DNS names, never the learning site's host (moving Learn
    is GATE-CUTOVER) and never a production domain's apex or `www` name;
  - `ALLOWED_HOSTS` holds exactly those two and `CATALYST_LOCAL_HOSTS`;
  - the sender address (`CATALYST_FROM_EMAIL`) is set and is not the synthetic default.
- **Mail.** Applicant mail in production leaves only through `correspondence.transport` to the allow-listed host.
  Django's own mails (contact confirmation, password setup, withdrawal link) use `config.mail.TransportEmailBackend`
  in production (`9kg.77`, 2026-10-27): each message goes through the same transport, with its allow-list, pinned
  login, verified TLS, peer check and web-and-worker rule, one recipient and no copies, and any outcome but
  `accepted_by_server` raises so the sender takes its failure path (`MailUncertain` when the server may have accepted
  it). `config.mail.RefusingEmailBackend` stays admitted as the owner's hold. No file or console sink, and not
  Django's own SMTP backend, is ever admitted in production, so no live link or address is written to disk.
- **Roles.** `scripts/provision_db_roles.py` admits production with staging's rules: passwords from files only, the
  database taken over by the owner role, grants read back.
- **Stack.** `scripts/render_staging_compose.py` renders `deploy/production/compose.yaml` from the staging
  definition; `scripts/render_caddyfile.py` writes the same Caddyfile beside it. A test pins the difference to these
  inputs: `CATALYST_ENV`, the project name, the secrets directory variable (`CATALYST_PRODUCTION_SECRETS`), the
  owner's challenge lifetime (no default, POL-02), the live mail rules, the ship-lag threshold, the sender address
  and the paging values (no defaults, `211.7.2`), the operator-supplied egress deny list, and the effect journal on
  an external volume (`catalyst-production-effects`), which `docker compose down -v` cannot remove. A second test
  starts each of the six Django services (web, worker, fetcher, migrate, backup, restore) with its rendered
  environment and the host's inputs filled in.

- **Mail route** (`9kg.79`, 2026-10-27). Production adds a `mail` network that is not internal, joined by the
  worker and by a new owner-run `post-restore` service, and by no other Catalyst process. Those two alone receive
  the mail host settings (`CATALYST_MAIL_HOST`, `_PORT`, `_USER`, `_SENT_FOLDER`, no defaults) and the
  `mail_password` secret. The post-restore step (the reconcile kind: the Sent-folder read, never SMTP) runs in
  `post-restore` with the owner's login, and its lift runs in `restore` with the erasure key added for that run only,
  so the erasure key and the mail password are never in one process. `restore` keeps the administrator password and
  has no route out. The trusted authserv-id is a required input too, or every inbound reply reads unverified. The
  host firewall restricts the network's destinations to the mail host, and its readback is a deploy gate (`9kg.28`);
  Documenso's route is a separate decision with its canary (`9kg.31.2`). A test pins which services hold the route
  and the secret; the staging definition is unchanged.

- **Journal shipping and the egress check** (`9kg.78.2`, 2026-10-27). Production adds an owner-run `journal-ship`
  service (profile `ops`, run by a host timer): `catalyst_journal_ship --to /var/lib/catalyst/ship`, with the journal
  mounted read-write (the shipped head is recorded beside it) and the host's off-host destination
  (`CATALYST_JOURNAL_SHIP_DIR`, no default) as its only other mount. It has no network at all, and holds the
  least-privileged database login only because the settings need one. Production's egress service declares
  `CATALYST_EGRESS_FETCHING=disabled`, so its health check passes on an intentionally empty deny list (blank lines and
  comments only) and still fails on a missing, unreadable or malformed one; the policy itself still refuses every
  fetch on an empty list (`assessments.egress.deny_file_state`, `check`).

- **The stack check against production** (`9kg.78.3`, 2026-10-27). `CATALYST_STACK_ENV=production
  scripts/staging_check.sh` builds the image's production target, renders `deploy/production/compose.yaml` with
  synthetic inputs on the dev box, and runs the same shape checks (no secret in any environment or `docker inspect`,
  read-only roots, no capabilities, uid 10001, the proxy's sites and refusals, readiness, log redaction,
  `check --deploy`, idempotent migrate and role provisioning, the database outage, the path refusals, headers, the
  webhook, the network and egress rules, staff two-factor, custody). Where production differs on purpose it checks
  that instead: the worker alone is on the mail network and holds the mail password; the request form and the
  owner's invitation are refused until real, non-synthetic wording is approved (503 and `data_notice_*`); no
  applicant means no held action. Five checks are NOT RUN with their reason: the worker's outside reach (its limit
  is the host firewall) and the four intake and confirmation steps (they wait for the owner's wording, the
  approvable verification mail `9kg.80`, and a delivered mail, the mail canary `9kg.31.1`). It runs only against a local Docker daemon that holds no
  `catalyst-production` project and no `catalyst-production-effects` volume, and removes only the volume it created.
  The production run ends with a summary that keeps apart the applicant journey (not demonstrated), the protective
  refusals, the structural checks, host and provider evidence (none: this is the dev box) and each NOT RUN with the
  task that completes it. Runs of 2026-10-27 at the PR head: staging 140 PASS, 0 FAIL, 0 NOT RUN; production 138 PASS
  (2 protective refusals, 136 structural), 0 FAIL, 5 NOT RUN. A refusal is never counted as the journey. The
  restore, deploy and alert drills against production are `9kg.78.4`: the first two take a production backup, which
  refuses until POL-10 is recorded.

- **Adapters** (`9kg.78.1`, 2026-10-27). The deploy adapters require `CATALYST_STACK_ENV` (`staging` or
  `production`; unset, empty or anything else exits 2 before any alert, marker or probe, so a host that lost the
  setting never falls back to staging's `-k`). The staging drills set it. Every alert names the stack (`catalyst
  production: <codes>`). The outside-in probes of the public form pass `-q` first (no `.curlrc` is read) and `-k`
  for staging's internal CA only; production verifies the certificate against the system store, or against
  `CATALYST_PROBE_CA_FILE` when the host names one, with `CURL_CA_BUNDLE`, `SSL_CERT_FILE` and `SSL_CERT_DIR`
  cleared for the probe alone, not for the notify command (`deploy/staging/adapters/stack.sh`). This is the probe's code; that the host's certificate verifies is
  host evidence (`9kg.28`, `9kg.31.5`).

**Limits** (the PR #118 reviews):

- **Topology.** The production stack is the staging topology: an in-stack proxy with Caddy's internal CA
  (`tls internal`, a per-start CA in tmpfs), publishing on addresses the host names. That serves a dark deploy reached
  only by the operator; it is not usable by applicants. Whether the host's proxy fronts the stack or the in-stack
  proxy gets a public certificate is the owner's topology decision with the host preparation (`9kg.28`). The
  refusal of an all-interfaces publish address is also a host preflight item there; the compose file only says so.
- **Owned elsewhere.** The `erase` and `custody` services of `032` section 3.2, the custody key mounts and the
  erasure key wait on the owner's decisions (`211.7.1`, `211.7.9`). The restore, deploy and alert drills still name
  the staging stack (`9kg.78.4`, after POL-10). The `restore` service holds the administrator password,
  so it has no route out (`9kg.79`).
- **No live adapters.** None exists for Documenso or MXroute; their canaries need a reviewed guard amendment first
  (`9kg.31.2`, `9kg.31.3`).
- **Expected red at the dark deploy.** Health reports the undecided erasure registry (the backup refuses) and the
  unapproved notice wordings until the owner records POL-10 and the wordings. `9kg.31.5` records these as expected,
  or POL-10 is settled first (`031` section 8, item 1).

Tests: `tests/test_guards.py`, `tests/test_startup.py`, `tests/test_db_roles.py`, `tests/test_staging_compose.py`,
`tests/test_staging_proxy.py` (`9kg.31.11` in `tests/acceptance.py` P6_SUPPORTING).
