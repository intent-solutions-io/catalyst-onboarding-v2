# Status: Catalyst v2

| Field | Value |
|---|---|
| Document | `006-LS-STAT-status` |
| Last updated | 2026-10-10 |
| Source revision | contract PR #7 (merged `110bfad`); 1A evidence and ADR decisions in PR #8 |
| Classification | Public |

> **Status: PRELIMINARY, subject to review.** Implementation in progress: skeleton, data model and public intake (1B.1 to 1B.3); the worker (1B.4) is next. No deployment, no real applicant data.

## Current state

| Item | State | Evidence |
|---|---|---|
| Application code | 1B.1 skeleton (PR #9) and 1B.2 data model with ADR-14 roles (PR #11, merged `6f7fbc8`); 1B.3 public intake (S1-T4, PR #12): form, service transaction, duplicate and race handling (including concurrent repeats on an existing application), queued (not sent) verification, and a stated failure guarantee (atomic; a lost commit acknowledgment is resolved by resubmission). 1B.4 worker (S1-T5) in a draft PR, not merged: claim loop, poison rule, fenced results, verification send to a local sink. No confirmation, staff views or providers | PR #9, PR #11, PR #12; 1B.4 draft PR |
| Build contract (`011`, `002`, `003`, `004`, `005` S1) | APPROVED IN SCOPE 2026-10-09 (`011` section 10) | PR #7 |
| Owner approval of the contract and first slice | given 2026-10-09 for the scope in `011` section 10 | bead "Obtain the owner's approval of the build contract and the first-slice scope" |
| Owner-directed amendment of 2026-10-09 | applied | `011` section 9 |
| Open product policies | 19 open (`011` section 6) | bead "Obtain owner decisions on the open product policies listed in the master blueprint" |
| Specialist subagents | all eleven discovered in a fresh session; one (`catalyst-django-architect`) probed at runtime | `008` section 5.1 |
| Documentation and runtime CI | green on `main` `6f7fbc8` (run 38084678198); earlier `main` `95b7537` (run 37891535566) | GitHub Actions |
| Runtime CI lane | job "Runtime checks (Python 3.14.8, PostgreSQL 16.15)", aggregated into the required check; failure path demonstrated (probe run 38030066475: runtime failed, required check failed, `safe-merge` refused) | PR #9, closed probe PR #10 |
| v0.1.0 tag | an automatic tag, not a release (`CHANGELOG.md`) | |

## Verified versus pending (this handoff)

| Check | Result |
|---|---|
| Fresh session discovers the eleven specialists | VERIFIED: all eleven offered as agent types; one invoked by name |
| Specialist cannot write | VERIFIED for one of eleven (`catalyst-django-architect`): the requested probe file was not created; its tool list (Read, Glob, Grep, WebFetch) is the agent's own report. The other ten share the same allowlist pattern but were not probed |
| Restriction independent of parent permissions | DOCUMENTED by the official sub-agents doc and OBSERVED for one of eleven agents: the parent ran in `bypassPermissions`, which overrides the agent's `permissionMode`, so the guarantee comes from the tool allowlist alone |
| Beads context recovered at session start | VERIFIED: the project SessionStart hook output was present; the in-progress task was identifiable with `bd list --status in_progress` |
| Context-loading hook timing | VERIFIED: project hook 0.26-0.28 s, user-scope hook 0.27-0.34 s (three runs each) |
| CI result for `main` `95b7537` | VERIFIED PASS (run 37891535566). The branch head's CI result is recorded in the pull request |
| Resolved model id of a specialist | NOT VERIFIED (not exposed to the parent; `/tasks` shows it, user action) |
| Compaction recovery | NOT RUN (no destructive compaction test, by instruction) |
| Git-hook timings | NOT RUN |
| Auto memory behaviour in a fresh session | NOT VERIFIED (not needed by this contract) |

## Not yet demonstrated (carried, not blocking 1B.1)

| Item | Where it is proved |
|---|---|
| ADR-03 worker behaviours: automatic recovery, pause, bounded attempts, staff visibility | S1-T5, S1-T7, S1-T8 (TEST-S1-07, 12, 17, 18, 19) |
| Provider-specific reconciliation of `uncertain` outcomes | P2 or the relevant integration phase, before real external actions (D-20). S1 still proves attempts, bounded recovery, lease fencing, interruption and no duplicate challenge, adoption or next-stage action |
| ADR-14 role non-inheritance, no owner or superuser credentials in web and worker, privileged `search_path` | **implemented and tested in S1-T3** (PR #11): three non-superuser roles with no memberships, per-table grants, append-only triggers (8, adoptions included, D-22), audited retention path, the `catalyst.E002` diagnostic and runtime refusal on the WSGI connection path (fresh-process tests). The suite runs as the application role with a test-only privileged reset (D-21). Configuring deployed web and worker processes with the application role is P6 |
| TEST-S1-13, still open parts | the worker-command start-up refusal (S1-T5); the remaining parts (manage.py check, WSGI start-up, test-session PostgreSQL assertion) are covered by the 1B.1 tests |
| TEST-S1-14, still open parts | an assertion that CI holds no provider secrets; protection beyond Python sockets (native libraries such as libpq, child processes, collection-time code) is not provided by the test fixture and is not claimed |
| pytest 9.1.1 and pytest-django 4.14.0 | **done**: verified at the start of 1B.1 (bead S1-T2 notes) |

## Blockers

| Blocker | Owner | Blocks |
|---|---|---|
| POL-01 duplicate policy confirmation | Jeremy Longshore | GATE-S1 sign-off |
| POL-10 retention: no real retention or deletion until the policy and an operating authorization exist (ADR-14); the policy must cover adopted versions with their adoptions, challenges and audit (D-22) | Jeremy Longshore | any real deletion; GATE-PILOT |
| Release workflow swallows test failures (`\|\| true`), bead `catalyst-v2-2xy` | Jeremy Longshore | any real release (not 1B.1) |

## Next steps

1. Done: contract approved in scope (`011` section 10).
2. Done: handoff 1A evidence (`012`), and the owner's ADR-03, ADR-14, ADR-17 and ADR-18 decisions
   (2026-10-10, D-16 to D-19).
3. Done: 1B.1 (PR #9), 1B.2 (PR #11) and the 1B.3 intake closeout (PR #12).
   Now: 1B.4, S1-T5 only (the worker and the verification send to a local sink), as one draft PR.
   S1-T6 (confirmation) waits for separate authorization.
4. Policy decisions in `011` section 6, each before the milestone it blocks.

## Decision log

Decisions live in `011` section 4 and `003` "Architecture decisions"; this file does not duplicate them.
