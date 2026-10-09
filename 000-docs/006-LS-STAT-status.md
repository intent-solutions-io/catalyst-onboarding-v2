# Status: Catalyst v2

| Field | Value |
|---|---|
| Document | `006-LS-STAT-status` |
| Last updated | 2026-10-09 |
| Source revision | PR #7 (`docs/build-contract-and-first-slice`), approved at `e8a7a4c` |
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

## Blockers

| Blocker | Owner | Blocks |
|---|---|---|
| ADR-03 job mechanism form, ADR-17 runtime versions, ADR-18 custom user model, ADR-14 database trigger | Jeremy Longshore, after bead S1-T1 (bead S1-D) | S1-T2 onward |
| POL-01 duplicate policy confirmation | Jeremy Longshore | GATE-S1 sign-off |

## Next steps

1. Done: contract approved in scope (`011` section 10).
2. Now: handoff 1A only, S1-T1's compatibility and comparison checks (`005` S1.6a); then the owner's ADR-03, ADR-14, ADR-17 and ADR-18 decisions (bead S1-D).
3. Policy decisions in `011` section 6, each before the milestone it blocks.

## Decision log

Decisions live in `011` section 4 and `003` "Architecture decisions"; this file does not duplicate them.
