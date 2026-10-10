# Status: Catalyst v2

| Field | Value |
|---|---|
| Document | `006-LS-STAT-status` |
| Last updated | 2026-10-10 |
| Source revision | contract PR #7 (merged `110bfad`); 1A evidence and ADR decisions in PR #8 |
| Classification | Public |

> **Status: PRELIMINARY, subject to review.** Planning phase. No application code, no deployment.

## Current state

| Item | State | Evidence |
|---|---|---|
| Application code | none | repository tree |
| Build contract (`011`, `002`, `003`, `004`, `005` S1) | APPROVED IN SCOPE 2026-10-09 (`011` section 10) | PR #7 |
| Owner approval of the contract and first slice | given 2026-10-09 for the scope in `011` section 10 | bead "Obtain the owner's approval of the build contract and the first-slice scope" |
| Owner-directed amendment of 2026-10-09 | applied | `011` section 9 |
| Open product policies | 19 open (`011` section 6) | bead "Obtain owner decisions on the open product policies listed in the master blueprint" |
| Specialist subagents | all eleven discovered in a fresh session; one (`catalyst-django-architect`) probed at runtime | `008` section 5.1 |
| Documentation CI | green on `main` `95b7537` (run 37891535566, all four checks) | GitHub Actions |
| Runtime CI lane | not created (first-slice bead S1-T2) | |
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
| `uncertain` outcomes and reconciliation | P2 acceptance (first non-redeliverable provider effect) |
| ADR-14 role non-inheritance, no owner or superuser credentials in web and worker, privileged `search_path` | S1-T3 |
| pytest 9.1.1 and pytest-django 4.14.0 | start of 1B.1 |

## Blockers

| Blocker | Owner | Blocks |
|---|---|---|
| POL-01 duplicate policy confirmation | Jeremy Longshore | GATE-S1 sign-off |
| POL-10 retention: no real retention or deletion until the policy and an operating authorization exist (ADR-14) | Jeremy Longshore | any real deletion; GATE-PILOT |
| Release workflow swallows test failures (`\|\| true`), bead `catalyst-v2-2xy` | Jeremy Longshore | any real release (not 1B.1) |

## Next steps

1. Done: contract approved in scope (`011` section 10).
2. Done: handoff 1A evidence (`012`), and the owner's ADR-03, ADR-14, ADR-17 and ADR-18 decisions
   (2026-10-10, D-16 to D-19).
3. Now: handoff 1B.1 only, S1-T2 (skeleton, PostgreSQL-only settings, provider guards, reproducible
   environment, CI runtime lane). It starts by showing that pytest 9.1.1 and pytest-django 4.14.0 install,
   load, collect and run a PostgreSQL-backed check; an incompatibility is a blocker. S1-T3 onward waits for
   separate authorization.
4. Policy decisions in `011` section 6, each before the milestone it blocks.

## Decision log

Decisions live in `011` section 4 and `003` "Architecture decisions"; this file does not duplicate them.
