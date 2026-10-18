# P6 Readiness Matrix and PL Compatibility Plan (preparation)

| Field | Value |
|---|---|
| Document | `024-PP-PLAN-p6-readiness-and-pl-cutover-plan` |
| Version | 0.1.0 (preparation under D-40) |
| Status | **PROPOSED, preparation only.** No staging or VPS, DNS, proxy, secret, or production database change was made or is authorized. No real data was exported or imported, and no legacy code was ported. GATE-STAGING, GATE-PILOT and GATE-CUTOVER stay with the owner. |
| Owner | Jeremy Longshore |
| Date | 2026-10-18 |
| Epics | P6 `catalyst-v2-9kg`; PL `catalyst-v2-dy7` |
| Builds on | `003` (architecture, ADR-14 roles, "Learn and Django routing"); `009` section 5.5 (GitHub protections, releases); `011` POL-10, POL-13, POL-14, POL-15; `021` sections 16 to 18 (webhook, custody); `023` (P5) |

## 1. P6 readiness matrix

Each row gives the requirement, what exists in this repository today, the gap, and the earliest gate it blocks. In
the "Today" column, "proven" means a test passes in CI; it does not mean deployed.

| # | Requirement | Today (in this repository) | Gap | Blocks |
|---|---|---|---|---|
| 1 | Web and worker deployment as separate processes | `config/runtime.py` declares the kinds; `run_worker` exists; a pinned Python 3.14.8 image runs the tests | no production image, process manager or health endpoint | GATE-STAGING |
| 2 | Separate database roles for migration, runtime and retention | ADR-14 roles provisioned by `scripts/provision_db_roles.py`; a web or worker process refuses an owner or superuser connection (proven) | production role passwords in SOPS; a migration job run as the owner only | GATE-STAGING |
| 3 | Private staff access with MFA | staff screens refuse superusers and need named permissions (proven) | MFA, staff hostname and network restriction (POL-13, POL-14); secure cookie flags and HSTS (`9kg`) | GATE-STAGING |
| 4 | Public webhook isolation | the route is mounted only in test and development; secret, size cap and uniform answers (proven) | a separate public path or host behind the proxy; a source allowlist if Documenso's egress IP is stable; proxy rate limit; mount only when the owner decides (P4-D-17) | GATE-STAGING |
| 5 | Token-safe logging (proxy, application, database) | the application never logs bodies, tokens or links (tests scan records and logs); the confirmation token is in the URL path (`9kg` item) | proxy access-log scrubbing of `/confirm/` and webhook paths; PostgreSQL `log_statement` off for parameters | any deployment |
| 6 | Abuse controls | webhook flood coalescing; staff throttling none | an intake form rate limit (POL-01, POL-12), login throttling, a bulk retrieval alert | GATE-PILOT |
| 7 | Monitoring | `correspondence_health` command; staff queues | alert wiring to the operator alert channel; the collector, worker liveness and custody failure counts as checks | GATE-STAGING |
| 8 | Backup of PostgreSQL **and** signed-document storage, taken together | none for v2 | one coherent backup per run: a database dump and the custody directory with a manifest of `StoredDocument` keys and SHA-256 values | GATE-STAGING |
| 9 | Verified restore | none | a restore drill into a disposable database and directory, then a checker that every `StoredDocument` row's file exists and hashes equal and no file is unreferenced (proposal: `scripts/verify_custody_restore.py`) | GATE-STAGING |
| 10 | Rollback | migrations reverse where safe; 0005 and 0006 refuse once used (proven) | a documented rollback for each release; a pre-deploy backup | GATE-STAGING |
| 11 | Reversible LMS routing | `003` records today's routing, checked read-only on 2026-10-09; v2 routing proposed | a staged, reversible proxy change (owner decision); no proxy change authorized | GATE-CUTOVER |
| 12 | Release from a tested commit | the release workflow publishes only main's CI-green head, writes no history and defaults to a dry run (PR #41) | the owner proposals in `009` section 5.5: a `main` ruleset and a protected release environment (today `main` is unprotected) | any real release |
| 13 | Secrets | none configured; guards refuse provider settings outside test | SOPS-managed production secrets (Documenso key, webhook secrets, database passwords); rotation procedure | GATE-STAGING |
| 14 | Custody at rest | plaintext PDFs and details; no erasure path | encryption and location (POL-09); retention and erasure (POL-10) | GATE-PILOT |

## 2. Minimal repository-local proposals

Each proposal is validated only against disposable synthetic resources, such as the test containers.

1. `scripts/verify_custody_restore.py` (proposal): given a database URL and a custody directory, it checks:
   - every `StoredDocument` key exists, is a 0600 regular file and hashes to its recorded SHA-256;
   - no file is unreferenced (orphans are listed, not deleted).

   It can be proven in the test containers by restoring a dump of the test database and a copy of the test
   directory.
2. A `deploy/` example (proposal, not written yet): one compose file for web, worker and PostgreSQL with the three
   roles. Secrets come from SOPS at runtime. The webhook route is off by default.
3. Health endpoints (proposal), cheap read-only views:
   - liveness, with no database call;
   - readiness, a database role check and pending-action age.

None of these touches a real host.

## 3. PL: legacy compatibility and cutover plan

### 3.1 Principles

- **Sanitized and plan-only.** No real record leaves the first-generation system in this batch.
- **One execution owner at a time.** For each applicant, either v1 or v2 runs automated work, never both. A
  per-applicant ownership flag decides which, and it is changed only by an audited cutover step.
- **Keep every live record.** Nothing in v1 is deleted by the migration. POL-10 governs any later deletion.

### 3.2 Phases (proposed)

1. **Inventory.** A read-only field mapping from v1 records to v2 models: applications, submissions, decisions,
   agreements and documents. It is made from schema descriptions only, never from data.
2. **Compatibility rules.**
   - Which v1 states map to which v2 stages.
   - What v2 cannot represent: these stay in v1 and are read-only.
   - How v1 signed agreements are referenced. Custody stays with the v1 gate, and the app never reads its archive
     (the first-generation system's own custody rule).
3. **Dry run on synthetic copies.** A synthetic dataset shaped like v1 is imported into a disposable v2 database.
   The checker verifies counts, stages and history continuity.
4. **Coexistence.** New applicants go to v2. In-flight v1 applicants finish in v1 unless the owner moves a named
   cohort.
5. **Cutover of a cohort.** For each applicant, the ownership flag flips in one audited transaction. v1 automation
   stops for that applicant first, and v2 automation starts after. There is a rollback window.
6. **Decommission.** v1 stays read-only for the POL-10 retention period.

### 3.3 Owner decisions (POL-15)

- Which records move.
- The coexistence period.
- Whether in-flight v1 agreements are re-signed in v2 or referenced.
- The cutover cohort order.
- The rollback window.
- Who executes it.

## 4. Remaining gates beyond a synthetic P4 pass

These are not changed by any synthetic acceptance:

- 3E model evaluation and the live-call protections (`oc4.9`);
- production selection-policy validation (`019`);
- the P3 real-use defects (`oc4.10`);
- real legal templates and countersigning (POL-07, POL-08);
- notices (POL-17);
- custody encryption and location (POL-09);
- retention (POL-10);
- staff MFA and network (POL-13, POL-14);
- a Documenso canary (D-41);
- P5 itself.

**A synthetic P4 pass is not a production-ready onboarding service.**
