# P6 Staging, Deployment, Backup and Cutover Specification (handoff 6A)

| Field | Value |
|---|---|
| Document | `026-AT-DSGN-p6-staging-deployment-specification` |
| Version | 0.2.0 (0.1.1 applies the security and privacy review, section 15; 0.2.0 records the owner's approval, D-49) |
| Status | **APPROVED by the owner 2026-10-19 with every recommendation (D-49 in `011`).** 6B's repository-local tasks are released for synthetic work. Each host task (6B tasks 11 to 13), the pilot and the cutover still needs its own authorization. The owner still sets the values the decisions leave to them: RPO and RTO targets (P6-D-7), alert thresholds and who is paged (P6-D-9), rotation intervals (P6-D-15), and applies the `main` ruleset and protected `release` environment (P6-D-5). |
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
  own SSRF guard (`018`). The fetcher connects with a narrower database role than the app role (only the evidence
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
the proxy, the token paths are skipped from every access log, including the shared learn site's existing log and the
error log, by a matcher **generated from `PRIVATE_PATHS`** so the two cannot drift, covering encoded, case and
double-slash variants. No WSGI access log; the WSGI error log and the container log driver are checked. PostgreSQL
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
| TEST-P6-28 | Staging has no route to production hosts or real providers, and holds no production secret. |
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
    redeliverable ones that still send mail, call a model or fetch), per kind and status, with action ids;
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
- **Logs:** the token paths, generated from `config.redaction.PRIVATE_PATHS`, are skipped from the access log on
  both sites.
- **Request size:** request bodies are capped (128 KB public, 1 MB staff).
- **Headers:** `X-Forwarded-Proto` is set by the proxy (never passed through), and the client's
  `X-Forwarded-Host` and `X-Forwarded-For` are dropped. The upstream is the web process's unix socket, and the
  admin API is off.
- **The staff site** binds to a private address (the tailnet address on the staging host, never all interfaces)
  and carries only the staff screens and the admin's static files.
- **Webhook:** there is no webhook site; it is not mounted until the pilot (P6-D-4).
- **Guards:** they refuse a staff host that is also a local health host (from the PR #63 review).
- **Validation:** `caddy validate` (as an ordinary user) accepts the file.
- **Not proven here, carried to 6B.11 against the running stack:** what Caddy does with real requests:
  - path normalization variants;
  - a forged `X-Forwarded-Proto`, and `Host: localhost` sent to the public listener;
  - sentinel tokens absent from every log.
- **Evidence:** `tests/test_staging_proxy.py` (the rendering, the log skip matching `PRIVATE_PATHS`, the public
  allow-list, the staff site, the headers and the absence of a webhook) and the overlap test in
  `tests/test_startup.py`.
