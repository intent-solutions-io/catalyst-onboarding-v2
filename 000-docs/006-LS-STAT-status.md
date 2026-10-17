# Status: Catalyst v2

| Field | Value |
|---|---|
| Document | `006-LS-STAT-status` |
| Last updated | 2026-10-17 |
| Source revision | PR #36 (3C, GATE-P3 signed off, D-36) |
| Classification | Public |

> **Status (2026-10-17): P1, P2 and P3 accepted for synthetic work.** GATE-P3 signed off 2026-10-17 (D-36). GATE-S1 signed off 2026-10-11 (D-26), GATE-P2 signed off 2026-10-13 (D-33). P3: `018` approved (D-34); 3B.1 evidence collection (PR #30), 3B.2 bounded assessment with test models only (PR #32) and 3B.3 clarification (PR #34) and 3B.4 qualification decision (PR #35) merged; 3C verification merged (PR #36); GATE-P3 signed off (D-36; after-action report `020`); 3E (live synthetic evaluation) needs separate authorization. The candidate selection-quality contract was approved 2026-10-14 (D-35; `011` section 11, `019`). No deployment, no real applicant data, no live model call; the gates below stay open.
>
> (Previous banner, 2026-10-11: "first slice complete; P2 specified and approved for synthetic work; 2B.1 authorized, not yet built".)

## Current state

| Item | State | Evidence |
|---|---|---|
| Application code | 1B.1 skeleton (PR #9) and 1B.2 data model with ADR-14 roles (PR #11, merged `6f7fbc8`); 1B.3 public intake (S1-T4, PR #12): form, service transaction, duplicate and race handling (including concurrent repeats on an existing application), queued (not sent) verification, and a stated failure guarantee (atomic; a lost commit acknowledgment is resolved by resubmission). 1B.4 worker (S1-T5, PR #13, merged `06f7dbb`): claim loop, poison rule, fenced results, verification send to a local sink. 1B.5 confirmation (S1-T6, PR #14, merged `b2138e2`): signed link, GET preview without state change, one-transaction POST adopting only the named version, `held` next-stage action, token redaction in Django's logs. 1B.6 read-only staff view (S1-T7, PR #15, merged `843f974`). S1-T8 acceptance evidence (PR #16, merged `3bd31ac`): every TEST-S1 case mapped, reported and gated (`013`), after-action report `014`; GATE-S1 signed off (D-26). No providers | PR #9, PR #11 to #16 |
| Build contract (`011`, `002`, `003`, `004`, `005` S1) | APPROVED IN SCOPE 2026-10-09 (`011` section 10) | PR #7 |
| Owner approval of the contract and first slice | given 2026-10-09 for the scope in `011` section 10 | bead "Obtain the owner's approval of the build contract and the first-slice scope" |
| Owner-directed amendment of 2026-10-09 | applied | `011` section 9 |
| P2 correspondence loop | accepted for synthetic work: GATE-P2 PASS 54 (D-33; `016`, after-action report `017`) | PR #21 to #27 |
| P3 evidence and assessment | 3B.1 merged `d564bfa` (PR #30): versioned claims, fixture-backed evidence observations, no model call. 3B.2 merged `8086508` (PR #32): bounded assessment over a frozen snapshot with PydanticAI test models only, budgets, invocation records, failure routing to staff; full run 760 passed, GATE-S1 25/25, GATE-P2 54/54 (CI run 38644672774). 3B.3 clarification merged `2bb3281` (PR #34); 3B.4 qualification decision merged `25603b0` (PR #35); 3C merged, GATE-P3 signed off (D-36). Open in `018` sections 14 to 17: live-call protections, what clears a capped snapshot, the owner decisions of section 17 | PR #30, #32, #34, #35 |
| Candidate selection quality | APPROVED as the governing contract (D-35): authority in `011` section 11; methods, evaluation and scorecard in `019`; open: domain expert, operational delegate, private evaluation location, scorecard minimums, capped-snapshot path | PR #33 |
| Open product policies | POL-01 decided for the slice (D-25); POL-19 decided (D-31); POL-06 and POL-13 decided for synthetic P2 only (D-29, D-30); POL-03, POL-04 and POL-05 synthetic P3 defaults approved with `018` (D-34); production values open (`011` section 6) | bead "Obtain owner decisions on the open product policies listed in the master blueprint" |
| Specialist subagents | all eleven discovered in a fresh session; one (`catalyst-django-architect`) probed at runtime | `008` section 5.1 |
| Documentation and runtime CI | green on every merged head through `main` `25603b0` (PR #35); per-task runs on each pull request | GitHub Actions |
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

## Carried items and where they were proved

| Item | Where it is proved |
|---|---|
| ADR-03 worker behaviours: automatic recovery, pause, bounded attempts, staff visibility | **demonstrated** in S1-T5 and S1-T7 (TEST-S1-07, 12, 17, 18, 19), gated in S1-T8 (`013`) |
| Provider-specific reconciliation of `uncertain` outcomes | P2 or the relevant integration phase, before real external actions (D-20). S1 still proves attempts, bounded recovery, lease fencing, interruption and no duplicate challenge, adoption or next-stage action |
| ADR-14 role non-inheritance, no owner or superuser credentials in web and worker, privileged `search_path` | **implemented and tested in S1-T3** (PR #11): three non-superuser roles with no memberships, per-table grants, append-only triggers (8, adoptions included, D-22), audited retention path, the `catalyst.E002` diagnostic and runtime refusal on the WSGI connection path (fresh-process tests). The suite runs as the application role with a test-only privileged reset (D-21). Configuring deployed web and worker processes with the application role is P6 |
| TEST-S1-13 | **covered**: the worker-command refusal (S1-T5) plus the 1B.1 tests (manage.py check, WSGI start-up, test-session PostgreSQL assertion) |
| TEST-S1-14 | **covered**: the assertion that CI references no secret and sets only synthetic credentials (S1-T8). Protection beyond Python sockets (native libraries such as libpq, child processes, collection-time code, UDP or DNS) is not provided by the test fixture and is not claimed |
| pytest 9.1.1 and pytest-django 4.14.0 | **done**: verified at the start of 1B.1 (bead S1-T2 notes) |

## Blockers

| Blocker | Owner | Blocks |
|---|---|---|
| POL-10 retention: no real retention or deletion until the policy and an operating authorization exist (ADR-14); the policy must cover adopted versions with their adoptions, challenges and audit (D-22) | Jeremy Longshore | any real deletion; GATE-PILOT |
| Release workflow pushes its version-bump commit straight to `main` (no PR, required checks or merge guard), bead `catalyst-v2-oyu`. The test-swallowing bug `catalyst-v2-2xy` is fixed: the release now refuses unless every required CI check succeeded on the release commit (`scripts/require_green_ci.py`) | Jeremy Longshore | any real release |
| Confirmation link in access logs: the signed token is in the URL path; proxy and application-server access logs must not record `/confirm/` paths, or the owner moves the token out of the path (`005` S1-T6 paragraph; bead `catalyst-v2-9kg`) | Jeremy Longshore | any deployment |
| Production transport settings: HTTPS-only links, `CSRF_COOKIE_SECURE`, `SESSION_COOKIE_SECURE`, SSL redirect and HSTS are not set (bead `catalyst-v2-9kg`) | Jeremy Longshore | any deployment |
| POL-13 staff roles, MFA and the staff hostname or network restriction; the slice has one PROPOSED read-only group, local only | Jeremy Longshore | GATE-STAGING |

## Next steps

Current (2026-10-17):

1. The open selection-quality inputs (`019` section 13): domain expert, operational delegate, private evaluation location.
2. The P3 owner decisions (`018` section 18), first POL-05, and the release of the next phase.
3. Owner decision on what clears a capped assessment snapshot; live-call protections before any 3E run.
4. Profiling of the runtime suite (bead `catalyst-v2-egz`).

History (as of 2026-10-11, kept for the record):

1. Done: contract approved in scope (`011` section 10).
2. Done: handoff 1A evidence (`012`), and the owner's ADR-03, ADR-14, ADR-17 and ADR-18 decisions
   (2026-10-10, D-16 to D-19).
3. Done: 1B.1 (PR #9), 1B.2 (PR #11), 1B.3 intake (PR #12), 1B.4 worker (PR #13), 1B.5 confirmation (PR #14)
   and 1B.6 staff view (PR #15), then S1-T8 acceptance evidence (PR #16). GATE-S1 signed off 2026-10-11 (D-26).
4. Done: handoff 2A for P2 (bead `catalyst-v2-7hu.1`, PR #20): the correspondence specification `016`
   0.3.2, approved by the owner with decisions D-27 to D-32 (2026-10-12); merged as `1a6a25f`.
5. Done: 2B.1, outbound foundations (bead `catalyst-v2-7hu.2`, PR #21, merged `349f54e`), and 2B.2, inbound
   collection (bead `catalyst-v2-7hu.3`, PR #22, merged `2aea347`; M6 TLS tests pass). In review: 2B.3, reply
   processing and staff resolution (bead `catalyst-v2-7hu.4`), under the owner's 2026-10-13 instruction to
   continue the P2 beads autonomously.
6. Policy decisions in `011` section 6, each before the milestone it blocks.

## Decision log

Decisions live in `011` section 4 and `003` "Architecture decisions"; this file does not duplicate them.
