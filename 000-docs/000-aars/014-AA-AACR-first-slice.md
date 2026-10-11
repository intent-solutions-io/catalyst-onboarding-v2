# 014-AA-AACR — First working slice after-action report

> Catalyst v2 is Intent Solutions' new onboarding platform for Solution Catalyst applicants, built on
> Django and PostgreSQL. This report closes its first working slice: the smallest end-to-end path that
> proves the architecture. A synthetic applicant asks for access. A background worker emails a
> verification link to a local test mailbox. The applicant confirms the address once. Staff can read
> the whole record without being able to change it. No real email, AI model, signing service or
> deployment was involved.

- **Status:** GATE-S1 signed off by the owner on 2026-10-11 (D-26); the epic is closed.
- **Lane:** full. The epic had incidents during the work (section 5).
- **Epic or milestone:** Build the first working slice: synthetic intake, email verification to a local
  mail sink, and a read-only staff view (bead: `catalyst-v2-6hl`).
- **Acceptance test:** every case TEST-S1-01 to TEST-S1-22 in `005` S1.7 is PASS at one pull-request head
  on PostgreSQL in CI, with QA review and this report (GATE-S1, `002` section 6).
- **GitHub:**
  - specification: PRs #7 and #8;
  - implementation: PRs #9 (S1-T2), #11 (S1-T3), #12 (S1-T4), #13 (S1-T5), #14 (S1-T6) and #15 (S1-T7);
  - evidence: PR #16, merged as `3bd31ac` (CI run 38109732065 on `93fc22c`);
  - umbrella issue: none (this repository tracks work in Beads, not GitHub issues).
- **Period:** 2026-10-09 → 2026-10-11
- **Author:** Jeremy Longshore, with Claude Code as implementer and the Catalyst specialist subagents as reviewers
- **Template:** 000-AA-TMPL v1.0.0

## 1. Summary and business value

The slice runs on PostgreSQL with three database roles. It is made of:

- a Django skeleton that refuses to start on anything but PostgreSQL, a local mail sink and a
  development or test environment;
- a data model whose history tables are append-only by privilege and trigger;
- a public form that records a submission, its history, a challenge and the next action in one transaction;
- a PostgreSQL-backed worker with leases, attempt limits, a poison rule and fenced results;
- a signed, expiring, single-use confirmation that adopts only the submission the applicant saw;
- a read-only Django Admin dossier for staff.

The organization can now show, with evidence rather than a plan, that the chosen architecture does
the hard parts of onboarding correctly before any real applicant or provider is involved:

- duplicate and concurrent submissions;
- crash recovery without duplicate effects;
- adoption of only what the applicant confirmed;
- staff visibility without staff write access;
- no tokens or personal data in logs.

It is the base every later phase (evidence, assessment, agreements, provisioning) builds on.

## 2. Scope — planned, completed, deferred

**Planned (`005` S1.1):** intake, duplicate handling, one-transaction commit, worker send to a local sink,
confirmation, read-only staff view, and the CI runtime lane. Tasks S1-T1 to S1-T8.

**Completed:**

| Task | Bead | Merged as |
|---|---|---|
| S1-T1 compatibility evidence | 6hl.1 | #8 |
| S1-T2 skeleton | 6hl.2 | `7570dbc` (#9) |
| S1-T3 data model and roles | 6hl.3 | `6f7fbc8` (#11) |
| S1-T4 intake | 6hl.4 | `9b3972c` (#12) |
| S1-T5 worker | 6hl.5 | `06f7dbb` (#13) |
| S1-T6 confirmation | 6hl.6 | `b2138e2` (#14) |
| S1-T7 staff view | 6hl.7 | `843f974` (#15) |
| S1-T8 acceptance evidence | 6hl.8 | this report, `013` and the case map |

**Deferred, and where it went:**

- **Deployment gates** (`006` Blockers, bead `catalyst-v2-9kg`):
  - keeping confirmation paths out of access logs;
  - HTTPS-only links, secure cookies and HSTS;
  - session lifetime;
  - the staff host or network restriction.
- **POL-13 (GATE-STAGING):** staff roles beyond read-only, MFA, self-service password change and offboarding.
- **P2:** resolving staff-attention items, reminders, inbound mail, and reconciliation of `uncertain` sends.
- **Parent-harness administrator credentials** in the test session (bead `catalyst-v2-6hl.10`).

No required documentation row was skipped.

## 3. Architecture and tradeoffs

- **Job system: a custom PostgreSQL ledger (ADR-03, D-16), not a queue library.**
  - How it works: claims use `SKIP LOCKED` with a lease token and count the attempt at claim. Results are fenced by that token. Every time comparison uses the database clock.
  - Chose this over Procrastinate. `012` showed Procrastinate can enqueue inside the domain transaction, but job state would then live in two places, and the fenced result and the history event must commit in one transaction under one lease.
  - Tradeoff: there is no lease heartbeat. A slow send can be reclaimed, and the fence then discards its late result.
- **History protection: privileges plus triggers with three roles (ADR-14, D-17), not application discipline alone.**
  - The application role cannot update or delete history, and even the migration owner is refused by the trigger.
  - Stated limitation: an owner can disable the trigger, and a superuser bypasses it.
- **Confirmation token: a signed challenge id in the path (ADR-16, D-24), not a stored random token.**
  - Validity (expiry, use, supersession) is decided by the database every time.
  - Tradeoff: proxy access logs could record the token. That is now a deployment gate.
- **Staff interface: native Django Admin, read-only three times over (D-23).** The group has view permissions only, the admin overrides refuse every write (including for superusers), and the database grants back both. Chose Admin over custom views because it met every requirement, with modest customization.
- **One lock order everywhere: application, then challenge, then action.** This rules out deadlocks between intake, confirmation and the worker.
- **Interfaces left for later phases:**
  - the `start_evidence_collection` action, held, with the adopted version as its explicit input;
  - the attention rule in `applications/staff.py`;
  - the fixed handler registry `CATALYST_ACTION_HANDLERS`.

## 4. Verification evidence

The acceptance test in the header is checked in `013-TQ-TEST-first-slice-acceptance-evidence.md`:

- a machine-checked case-to-test map (`tests/acceptance.py`);
- a per-case report printed by every run;
- a gate that fails any full run unless every case is PASS;
- child-run tests of that gate;
- a test pinning CI to a full run.

**Evidence of record:** [CI run 38109732065](https://github.com/intent-solutions-io/catalyst-onboarding-v2/actions/runs/38109732065) on the S1-T8 head `93fc22c` (PR #16, merged as `3bd31ac`): 315 passed in 80.6 s, every TEST-S1 case PASS, "PASS 25, FAIL 0, INCOMPLETE 0, NOT RUN 0 (full run)". The owner signed GATE-S1 off on it (D-26).

**Per-task CI runs** on the head each pull request was merged from:

| Task | Merged as | CI run on the merged head | Tests passed |
|---|---|---|---|
| S1-T4 | `9b3972c` | 38094130159 | 207 |
| S1-T5 | `06f7dbb` | 38096517878 | 245 |
| S1-T6 | `b2138e2` | 38104654472 | 270 |
| S1-T7 | `843f974` | 38106758485 | 297 |

**Result categories at the S1-T8 head:** PASS 25 (22 cases and 3 supporting groups), FAIL 0, INCOMPLETE 0, NOT RUN 0, SKIPPED 0 (a skip fails the run), BLOCKED 0.

**Mutation checks**, recorded in each pull request's body (each change made at least one test fail):

| Area (PR) | Mutations |
|---|---|
| Intake (#12) | no open-application row lock; no outer transaction; the race path always re-raising |
| Worker (#13) | no lease fence; no SKIP LOCKED; no superseded check; no poison rule |
| Confirmation (#14) | no locks; no expiry check, or expiry by the application clock; no supersede check; no version-ownership check; no log redaction; no private-response middleware |
| Staff view (#15) | admin change allowed; a change permission in the group; admin-log INSERT granted; challenge id shown; attention marker removed; any lookup allowed; the stuck-link attention clause removed |
| Acceptance gate (S1-T8) | a mapped entry that never runs, now a standing child-run test |

**Independent reviews, one per task.** Each finding was applied, or recorded as a later gate where noted:

| Task | Reviewer | Result |
|---|---|---|
| S1-T4 | `catalyst-django-architect` | 3 medium defects, fixed |
| S1-T4 closeout | `catalyst-independent-qa` | 4 should-fix, applied |
| S1-T5 | `catalyst-workflow-correspondence` | 3 issues, fixed and re-confirmed |
| S1-T6 | `catalyst-security-privacy` | 0 blockers, 4 should-fix: headers and log handling fixed; access logs and HTTPS recorded as deployment gates |
| S1-T7 | `catalyst-django-operator` | 1 blocker plus should-fix, fixed and confirmed on re-check |
| S1-T8 | `catalyst-independent-qa` | 1 blocker and several should-fix items, details below |

**S1-T8 review, what was fixed:**

- Results were stated before any run at the head existed (the blocker); the reports now point to the run of record.
- The gate itself had no standing test, and nothing pinned CI to a full run.
- The map counted functions where a case needs a specific instance.
- Coverage gaps: a handler that crashes the worker on every attempt; worker and failure paths in the log sweep; pause orphans with a negative control; the logged reason for every refusal; an established non-staff session.
- Stale status lines in `006`, and overstatements in this report.

## 5. Issues and root causes

- **A race test hung the suite (S1-T4 closeout).**
  - Root cause: the test waited for two sessions blocked by the lock holder. PostgreSQL reports the second waiter as blocked by the first waiter's tuple lock, not by the holder.
  - Fix: count sessions waiting on a lock. The harness now also closes its own connections before joining threads, so a failed lock test cannot hang.
- **The test network guard was silently disabled (S1-T4 closeout, found in review).**
  - Root cause: `monkeypatch.undo()` undoes every patch in the test, including the autouse guard.
  - Fix: `monkeypatch.context()`.
- **A recording failure after a successful send was marked `failed` (S1-T5, found in review).**
  - Root cause: one exception path treated "the message left" and "the message did not leave" alike.
  - Fix: a separate `LeftForRecovery` outcome. The action stays `running` for lease recovery.
- **Hidden columns could be probed through the admin (S1-T7, blocker in review).**
  - Root cause: Django Admin accepts a query-string lookup on any local field, whether or not it is shown.
  - Fix: only declared filters are accepted.
- **The grant helper failed on `django_session` (S1-T7; fixed in `843f974`, `config/db_roles.py`).**
  - Root cause: it assumed every table has an `id` sequence.
  - Fix: look the column up first.
- **Mutation checks ran stacked (S1-T6, process; observed in the session, no repository artefact).**
  - Root cause: the shell's `cp` is aliased to `cp -i`, so the restores silently did not run.
  - Fix: `\cp -f` in every restore. The counts were re-run one mutation at a time.

## 6. Lessons learned

- **Prove concurrency with a lock holder that both requests queue behind, never with a barrier behind the contested lock.** This is now the pattern in `tests/test_intake.py`, `test_confirmation.py` and `test_staff.py`.
- **Hiding a field is not access control.** Every admin now accepts only declared filters, and a registry test (`tests/test_staff.py`) keeps every admin read-only.
- **"Every case PASS at one head" must be enforced in code, not asserted in prose.** It is now the gate in `tests/conftest.py`.
- **Independent review per task found a real defect almost every time.** Keep one reviewer per task, as `009` already says.

## 7. Operational impact, including cost

- **Automations:** none added. There is no new hook, cron or deployed service.
- **CI:** the runtime check takes about 75 to 85 s for the suite (job about 1 m 50 s) on the free GitHub runner, so the money cost delta is nil.
- **Footprint:** development and CI only. Containers are per-run and removed afterwards.
- **Attention burden:** one per-case report to read per run.
- **Recovery objectives:** none affected. No production data or service exists, so there is nothing to recover (the RPO and RTO are not applicable until P6).

## 8. Rollback procedure and validation

- **Code:** each task is one squash-merged pull request and can be reverted on its own, in reverse order.
- **Migrations:** every migration in the slice declares a reverse operation. Reverse-and-reapply is exercised in `tests/test_db_roles.py` only for `applications` (to `0001`), `workflow` (to `0001`) and, by dependency, `accounts.0003`. The `accounts` `0001` and `0002` migrations and `correspondence` are not exercised.
- **Code rollback:** argued, not exercised. Each task reverts on its own because each is one squash commit with its own migrations.
- **Data:** no real data exists. Rollback of data is not applicable.
- **Last relevant restore drill:** none. No backup exists for this system yet. Backup with a demonstrated restore is P6 (bead `catalyst-v2-9kg`), and it is not claimed here.

## 9. Next steps

1. Done 2026-10-11: the owner confirmed POL-01 (D-25) and signed off GATE-S1 (D-26).
2. Fix the release workflow that swallows test failures (bead `catalyst-v2-2xy`) before any release.
3. Remove the bootstrap administrator's credentials from the test process (bead `catalyst-v2-6hl.10`).
4. **P2:** reminders, inbound mail, resolving staff-attention items and `uncertain` reconciliation. Each needs a new handoff and approval.
5. **P6 deployment gates and POL-13** (bead `catalyst-v2-9kg`) before any staging run.
