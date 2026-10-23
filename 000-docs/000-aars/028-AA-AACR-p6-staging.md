# 028-AA-AACR — P6 staging after-action report

> P6 is the stage where Catalyst stops being a test suite and becomes a system that runs. It now has:
>
> - a deployable image;
> - a staging stack with its own database roles, secrets read from files, a proxy, two-factor staff login and an
>   egress-controlled evidence fetcher;
> - a deploy path that reverts itself;
> - health checks that alert to Buzz;
> - a backup that has been restored and measured;
> - a rehearsed plan for routing Learn traffic to it.
>
> Everything ran on the dev box with synthetic data. No production host, Learn configuration, provider key or real
> applicant was touched.

- **Status:** filed for the owner. **GATE-STAGING was signed off on 2026-10-22 (D-50, `011` section 4)** on the
  statement in section 9, with the partial clauses of section 4 accepted and carried as beads. (At filing, 2026-10-22,
  this line read "GATE-STAGING is not signed off: that is the owner's decision, on the statement in section 9.")
- **Lane:** full. Every task had an independent review, and every review found something (section 5).
- **Epic:** "Prepare staging, deployment, backup with demonstrated restore, monitoring and the reversible Learn
  routing cutover" (bead `catalyst-v2-9kg`).
- **Acceptance test:** in a full run on PostgreSQL, every gated case must PASS. `tests/acceptance.py` `P6_CASES`
  maps 37 of the 38 cases in `026` section 11 to their tests. The 38th, TEST-P6-27 (the dark deploy), is shown only
  live (`P6_LIVE_ONLY`). GATE-S1 to GATE-P5 must still PASS. The live drills are evidence beside that gate, recorded
  in `026` section 16.
- **GitHub:** PR #58 (6A) and PRs #59 to #79 (6B; #60 and #62 are unrelated). Each 6B task is recorded in `026`
  section 16.
- **Period:** 2026-10-19 to 2026-10-22.
- **Author:** Jeremy Longshore. Claude Code implemented the work; the Catalyst specialist subagents reviewed it.
- **Template:** 000-AA-TMPL v1.0.0

## 1. Summary and business value

- **Catalyst can be deployed and taken back.**
  - A release is an image built and scanned on every pull request, and attested only from `main`.
  - The host verifies the attestation on a private copy before loading it.
  - A bad release reverts itself and holds, and a migration that cannot be undone refuses the revert, naming the
    migration.
  - Shown by `scripts/deploy_drill.sh`, 28 of 28, with the estate deploy wrapper.
- **A broken system says so.**
  - A stopped worker, a stale heartbeat, an unresolved bounce, an overdue backlog, a stale backup and an overdue
    restore drill each raise a code-only alert.
  - A dead health check is caught by the sweep.
  - One alert was delivered for real to Buzz `sys-health` and read back from Buzz.
- **Data comes back.**
  - Recovery from an empty host to a serving stack took 62 to 63 seconds.
  - Every link and session issued before the backup stops working after the restore, and the worker stays held
    until staff lift the hold.
- **Applicants and staff are protected at the edge.**
  - The public site forwards only applicant paths, and Django refuses the rest by itself.
  - Token paths never reach a log.
  - Staff need a second factor, and a superuser gets no staff session.
  - The evidence fetcher reaches the internet only through a proxy that refuses private, loopback, metadata and
    tailnet addresses.
- **The Learn cutover is rehearsed.** Two route snippets switch applicant paths to v2, and removing one rolls the
  entry back while links already sent keep working. LMS paths answered byte-identically throughout.

## 2. Scope: planned, completed, deferred

| Item | Status |
|---|---|
| 6A specification `026`, the P6 decisions (D-49) | done |
| 6B.1 to 6B.9: the staging environment, web security, health, the image and secrets, roles, backup and restore commands, post-restore, proxy, two-factor | done, recorded in `026` section 16 |
| 6B.5b compose, 6B.10 deploy and attested image, 6B.10a rotation runbook `027` | done |
| 6B.11 live cases, egress proxy, dark deploy, cutover rehearsal | done on the dev box (PRs #75, #76, #79) |
| 6B.12 alerts to Buzz, 6B.13 the measured restore drill | done on the dev box (PRs #77, #78) |
| 6C evidence map and this report | this PR |
| A persistent staging stack, with host timers, scheduled backups and receipts | **deferred** to the pilot host (beads `9kg.20` to `9kg.22`) |
| The live Learn switch | **not started**: needs the cutover plan and the owner's go |
| GATE-STAGING sign-off | **not done at filing; the owner's decision** (signed off 2026-10-22, D-50) |

## 3. Architecture and tradeoffs

- **One image, many processes.** Web, worker, fetcher, egress, migrate, backup and restore are the same image with
  different commands, roles and secret mounts. Each process mounts only its own secrets.
  - Chose one image over per-process images, so a release is one attested artifact.
- **Secrets are files, never environment variables.** The settings refuse a secret found in the environment.
  - Chose files over environment variables because `docker inspect` and crash reports show the environment.
- **The deploy wrapper owns promotion and revert.** Catalyst supplies adapters that take content references only,
  and a smoke check that is the single gate.
  - Chose the estate wrapper over a Catalyst-specific deployer, so every repository reverts the same way.
- **Forward-only migrations are recorded, not inferred at revert time.** The list is written before migrating, so a
  revert is refused even when the serving release is broken.
- **Egress is one CONNECT proxy with one deny function.** The fetcher has no DNS and no route out except the proxy.
  The proxy, the fetcher and the peer check all use the same `classify` function.
- **Alerts carry codes only.** Every word of an alert matches `^[a-z_]+\.[a-z_]+$`, so applicant data cannot reach
  Buzz.
- **The cutover is two snippet files, not one edited block.** Rolling back is removing a file and reloading, which
  cannot be mistyped under pressure.

## 4. Verification evidence

Status per case. **Proven** means every clause of the case is shown. **Partly** means some clauses are shown and the
rest are named. "Unit" means the gated tests in `P6_CASES`; "live" means a drill on the dev box, recorded in `026`
section 16.

| Case | Status | Evidence, and what is not yet shown |
|---|---|---|
| TEST-P6-01 | partly | Unit: digest base, hash-locked, non-root, read-only root, no secret in a layer. Live: an unattested tarball is refused. A real attestation was made on `main` (image run 39780920293). **Not yet:** verifying it on the host with the force-command (bead `9kg.20`) |
| TEST-P6-02 | proven | Live and unit |
| TEST-P6-03 | proven | Unit (guards) |
| TEST-P6-04 | proven | Live secret and role checks; unit |
| TEST-P6-05 | proven | Live: a second migrate applies nothing. `deploy_drill.sh`: migrate runs as the owner, and readiness is red for the release deployed without its migrations. §16 called this partly before the drill's evidence was joined to it |
| TEST-P6-06 | proven | Live: a second provisioning run, five roles read back, random credentials per run. Unit: attributes, memberships and grants. §16 called this partly because the attributes were unit-only; the case's clauses are now each shown |
| TEST-P6-07 | proven | Live: database stopped (liveness 200, readiness 503) and health paths refused on the public listener (TEST-P6-12). Unit: the wrong role. §16 called this partly because the wrong role is unit-only |
| TEST-P6-08 | proven | `deploy_drill.sh` (a good release promoted; three faults reverted and held; forward-only refused). The unit test pins the adapters' shape only |
| TEST-P6-09 | proven | `deploy_drill.sh`; unit |
| TEST-P6-10 | partly | `deploy_drill.sh`: the receipt is written and reads back as intended. **Not yet:** a mismatch failing the deploy. By design the smoke is the gate and the receipt is a record (6B.10); either a mismatch check is added or the owner records the deviation (bead `9kg.27`) |
| TEST-P6-11 | partly | Live: secrets only as files, none in configuration. Unit: a role password rotation. **Not yet:** tmpfs on the host (SOPS, pilot; bead `9kg.20`) |
| TEST-P6-12 | proven | Live, with variants; unit |
| TEST-P6-13 | partly | Live and unit for token sentinels. **Not yet:** the webhook secret, since the webhook is mounted only at the pilot (bead `9kg.27`) |
| TEST-P6-14 | proven | Live: HSTS, CSP, the CSRF cookie, `no-store` on a token path, a spoofed forwarded header overwritten. Unit: the session cookie's flags. §16 called this "mostly" because the session cookie was unit-only |
| TEST-P6-15 | partly | Live (second factor, superuser). **Not yet:** the named-device network restriction (host; bead `9kg.20`) |
| TEST-P6-16 | partly | Live: unmounted. Unit: authentication, uniform answers, two secrets. **Not yet:** live enabled refusals, size and source limits (bead `9kg.27`) |
| TEST-P6-17 | proven | `alert_drill.sh`; unit |
| TEST-P6-18 | partly | Unit only. **Not yet:** live, since staging has no inbound mail until the pilot (bead `9kg.27`) |
| TEST-P6-19 | partly | Live: bounce and backlog. Unit: uncertain send and custody. **Not yet:** those two live (bead `9kg.27`) |
| TEST-P6-20 | proven | `alert_drill.sh`; unit |
| TEST-P6-21 | partly | Live and unit: set, manifest, a failed run keeps the good set. **Not yet:** the failed run's alert (scheduled job; bead `9kg.22`) |
| TEST-P6-22 | proven at `720e8cf`, pending re-run | `restore_drill.sh`, with times measured; PR #89 extends the drill with the effect journal and the reconciliation (`026` section 16, 9kg.33) and the figures are re-measured there. **The owner sets** the RPO and RTO targets |
| TEST-P6-23 | proven at `720e8cf`, pending re-run | `restore_drill.sh` (five controls on their exact refusals, plus the empty-journal refusal added by PR #89); unit |
| TEST-P6-24 | partly | `deploy_drill.sh`: a missing receipt is refused. The backup runs in the same step, so it is fresh by construction. **Not yet:** refusing a backup command that prints an older receipt's path (bead `9kg.27`) |
| TEST-P6-25 | partly | The restore path: `restore_drill.sh`. The forward-only refusal: `deploy_drill.sh`. **Not yet:** migrating N+1 (expand) and reverting to N on that schema; the drill's reverts are of releases that never migrated (bead `9kg.27`) |
| TEST-P6-26 | proven on a stand-in | `cutover_rehearsal.sh` 19 of 19. The gated unit tests pin only the route sets. **Not yet:** the live Learn read (the preconditions in `026` section 16; owner's go) |
| TEST-P6-27 | proven | Live only (`staging_check.sh`) |
| TEST-P6-28 | partly | Live: web, worker and fetcher reach nothing outside the database, and names do not resolve; no production secret (TEST-P6-04). **Not yet:** the fetcher's proxy admits any public name, so the estate's own production hosts are not denied by name (bead `9kg.27`) |
| TEST-P6-29 | partly | Live: a link from before the backup. Unit: sessions, passwords, revocations. **Not yet:** erasure replay (bead `9kg.25`) |
| TEST-P6-30 | proven | Live (egress); unit |
| TEST-P6-31 | partly | Unit: only `main` attests, with split permissions. Live: an unattested tarball is refused. **Not yet:** the deploy force-command (bead `9kg.20`) |
| TEST-P6-32 | proven | Live (through the socket, no proxy); unit |
| TEST-P6-33 | proven | Live; unit |
| TEST-P6-34 | partly | Unit only (P4 webhook tests). **Not yet:** live, with the webhook at the pilot (bead `9kg.27`) |
| TEST-P6-35 | partly | Backup receipts, the set's modes and alerts carry no personal data (live and unit). **Not yet:** a check over committed evidence and the deployment receipt (bead `9kg.27`) |
| TEST-P6-36 | partly | Unit: link key (routine and leak), Django key, role passwords, webhook overlap. **Not yet:** the administrator's password and provider tokens (procedures only, `027`; bead `9kg.27`) |
| TEST-P6-37 | proven | Image run 39780920293 on `main` (head `178da42`): build, content check, SPDX bill of materials, scan and attestation all succeeded; the same build job runs on every pull request |
| TEST-P6-38 | proven | `alert_drill.sh`, plus one real delivery read back from Buzz |

**Totals:** 21 proven (one of them on a stand-in), 17 partly, none not run. Every "not yet" is named above with the
bead that carries it.

**What a gate PASS means.** For TEST-P6-08, 24, 25, 26 and 31 the gated tests pin the shape of the code (the
adapters, the workflow, the route sets); the behaviour is shown by the drills named above. A PASS on those cases in
the full run is not, by itself, evidence of behaviour.

**Live drill results** (each run twice or more, all PASS):

| Script | Checks |
|---|---|
| `staging_check.sh` | 127 |
| `deploy_drill.sh` | 28 |
| `alert_drill.sh` | 15 |
| `restore_drill.sh` | 28 |
| `cutover_rehearsal.sh` | 19 |

The full-run gate counts, and the CI run and head they come from, are on this report's pull request.

## 5. Issues and root causes

Every review found something real. The most instructive:

- **Checks that pass vacuously.**
  - A `bash -c` cannot see shell functions, so two checks once passed without running.
  - A grep for "confirmed" also matched "unconfirmed".
  - A deny-list of provider actions missed seventeen kinds.

  The fix each time was a positive control, an exact string, or a registry-derived list.
- **The revert path read through the broken release.** It now reads migrations from the recorded state.
- **A variable read only at start.** The cutover snippets read their upstream from Caddy's environment, which a reload
  does not refresh. They now carry a default.
- **The image tarball could be swapped between verify and load.** Now one private copy is both verified and loaded.
- **The suite outgrew CI's limit.** The runtime job hit its 20-minute limit and was cancelled; the limit is now 35
  minutes.
- **A failed drill counted as done.** The overdue check now reads only passing receipts.

## 6. Lessons learned

- A live check is only evidence with a control that shows it could fail.
- Generate a list from its source (the private paths, the action registry), and test that the two agree. Do not
  copy it.
- Synthetic stand-ins prove the mechanism, not the target. Every stand-in here names what the live read must confirm.

## 7. Operational impact, including cost

- **No production change.** Nothing ran on the VPS, Learn's Caddy, a provider or DNS.
- **Dev box:** drills create and remove stacks named after their process IDs, on ports 18443 to 19444. The box's disk
  is near full, so drills clean up after themselves.
- **CI:** the runtime job takes 18 to 20 minutes, with a 35-minute limit. The image workflow adds a build and scan
  to every pull request.
- **Cost:** none beyond CI minutes.

## 8. Rollback procedure and validation

Every P6 change is repository code, documentation or a dev-box drill. Reverting a squash commit removes it. No
deployed system depends on it yet.

## 9. Next steps

**Proposed GATE-STAGING sign-off statement (for the owner):**

> "I accept GATE-STAGING for synthetic staging on the dev box, on the full-run gate at the final head of the 6C
> pull request (its CI run linked there) and the live drills recorded in `026` section 16. I accept that 17 cases are
> only partly proven, with the gaps listed in section 4 of this report and carried on beads `9kg.20`, `9kg.22`,
> `9kg.25` and `9kg.27`. TEST-P6-26 is proven on a synthetic stand-in of the Learn site only.
>
> This does not authorize: a persistent staging or pilot host; a production deploy; reading or changing Learn's
> live proxy configuration; enabling the webhook or real inbound mail; live provider keys; real applicants or real
> personal data in any backup (erasure replay, `9kg.25`, comes first). It does not set the RPO and RTO targets,
> alert thresholds, rotation intervals or scan policy, which remain open decisions. Each needs its own plan and
> go."

**Open owner decisions:**

- the RPO and RTO targets (P6-D-7);
- alert thresholds (POL-16);
- rotation intervals (P6-D-15);
- the scan policy;
- when `CATALYST_EXPECTED_COMMIT` becomes mandatory;
- whether the backup login must use the local socket only before the pilot;
- the `main` ruleset and the protected release environment (P6-D-5);
- whether R2 needs a signing-return path (`026` section 16).

**Carried to the pilot host** (bead `9kg.20`):

- the secrets-directory mode check;
- the staff publish-address validator;
- `pg_hba` limits;
- a persistent Caddy data directory;
- the egress environment parameter;
- the deploy force-command;
- `forward-only.json` in the backup set;
- scheduled backups with receipts;
- custody storage;
- receipt failures wired to alerts;
- the cutover's live-read rehearsals: the error-log filter, an adverse import order, and the socket's ownership.

**Then:** the pilot and cutover plan, offered to the owner for one explicit go.
