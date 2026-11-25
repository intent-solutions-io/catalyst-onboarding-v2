# Status: Catalyst v2

| Field | Value |
|---|---|
| Document | `006-LS-STAT-status` |
| Last updated | 2026-11-01 |
| Source revision | Repository `fdf5b5d` (PR #188); deployed `3fbbd34`; deployment receipt and current Beads/GitHub/host readbacks of 2026-11-01 |
| Classification | Public |

> **Current evidence snapshot (2026-11-01): the combined implementation is deployed; the full replacement is not activated or cut over.**
> The US stack serves revision `3fbbd34` with a matching deployment receipt, passing smoke checks and no pending
> migrations. Learn still routes to healthy v1 services. The owner's D-54 parity decisions remain recorded;
> provider approval/activation, independent recovery custody, staff-device proof and final case handover remain
> separate prerequisites. Repository completion is not proof of live applicant continuation.

## Current workflow evidence (2026-11-01)

| Workflow boundary | Verified implementation/deployment | Remaining production work |
|---|---|---|
| Invitation, verification and staff dossier | Existing bounded D-53 journey; the deployed staff certificate configuration now comes directly from the repository (`9kg.88`) | An unapproved workstation verifies TLS and receives 403. Approved-device authenticated access remains NOT RUN (`9kg.28`); the synthetic browser canary's final closure/erasure remains open (`9kg.87`). |
| Public URLs, form parity, client identity and CAT receipt | Merged and included in deployed `3fbbd34`; trusted-client and spoof controls passed, with distinct application rate buckets; prepared Learn aliases serve the exact assets | Public Learn still belongs to v1. The serving intake mode remains invitation; form/receipt activation and final route handover remain in `bgl.3`, `bgl.5`, `bgl.18`. |
| Geographic review and talent search | PRs #180 and #181 merged; their code is on the serving image | Geographic matches require human review before research/model use. This implementation does not supply the remaining production provider or staff-access evidence. |
| MiniMax research, correspondence and routine advance | Integration PR #161 merged. Deployed code has no application-imposed token caps or `max_tokens`; shared request pacing, Retry-After, bounded retries/timeouts and duplicate protection remain | The production profile/approval is not activated. Actual account RPM allocation, approved rubric/prompt and model-use/provider proofs remain required (`bgl.12`, `bgl.22`). |
| Agreements, countersignature and release | Parity implementation and current-template correction PR #183 are merged and deployed | Live signing/custody canary, approved templates and activation remain open. Agreement migration `0014` makes the previous image incompatible as an image-only rollback target. |
| Mailbox and welcome | Production adapter, first-name naming, credential mode and welcome implementation are merged and deployed | Approved welcome content, controlled provisioning/revocation proof and production activation remain open (`bgl.11`, `9kg.31.3`, `bgl.22`). |
| Reminders, lapse/reopen, sender/Reply-To and Twenty | Integration code and imported-mailbox/timer continuation repairs are merged and deployed | One poller/writer per mailbox; approved wording and live handover remain required. Twenty remains off. |
| Legacy records and open-case continuation | Import mapping `035`, native successor paths, mailbox ownership/recovery, envelope adoption and timer reconciliation are implemented and synthetic-tested | No final frozen import or all-case live continuation receipt exists. Preserve every record and ownership boundary before retiring v1 (`bgl.16`, `bgl.17`, `bgl.23`). |
| Community access | PR #184 is merged and deployed; design `036` records the contract | Adapter is unconfigured/default-off. Provider verification and admission remain `9kg.82`; deployment alone is not community activation. |
| Recovery and journal | Restored erasure/transaction protections and key-history recovery are deployed. PR #188 adds chained segments and constant-size steady request-count reads on `main` | PR #188 is not deployed; no journal rotation or archival has occurred. Independent backup/journal custody, shipping and live restore/alert drills remain open. |
| Full cutover | The prepared route and compatible recovery image have bounded verification | No public Learn switch or v1 retirement has occurred. Final import, provider continuation and recovery/observation evidence remain mandatory (`bgl.17`, `bgl.18`). |

## Current verification and launch limits (2026-11-01)

- Integration PR #161 merged after 2,308 tests and 300 acceptance groups passed; the older failed integration
  runs below are historical. Its superseded component PRs were closed with branches retained.
- Deployed `3fbbd34` passed [exact-main CI](https://github.com/intent-solutions-io/catalyst-onboarding-v2/actions/runs/41309238789)
  with 2,556 tests exactly once and 320 acceptance groups, plus the
  [image scan and attestation](https://github.com/intent-solutions-io/catalyst-onboarding-v2/actions/runs/41309238927).
  Promotion completed at 13:31:06 UTC with a fresh bound backup, exact approved/label/runtime commit match,
  passing deploy/smoke checks and zero pending migrations. Subsequent readback found stable services and no HOLD.
- Repository PR #188 merged as `fdf5b5d` after
  [CI](https://github.com/intent-solutions-io/catalyst-onboarding-v2/actions/runs/41314038119)
  verified all 2,568 tests exactly once and 321 acceptance groups. Its image scan passed.
  This is repository evidence, not a deployment receipt.
- An isolated rehearsal used the actual attested `3fbbd34` and compatible `a913212` images on one migrated
  PostgreSQL database, preserving template history and approval metadata through a forward/recovery/forward
  sequence. Readiness and intake passed. The compatible recovery image is staged; no production fallback or
  restore was performed. The old `3a5d7c2` image cannot alone reverse forward-only agreement migration `0014`.
- Production health still reports the unapproved decline notice and a never-shipped effect journal. Worker-context
  verification found a fresh heartbeat and no worker anomalies. Only backup and staff-certificate timers are
  installed; health/sweep timers and independent alert delivery remain outstanding.
- The proposed recovery receiver's source-reachable administrative access prevents an independent-custody claim.
  Local backup/staging does not establish off-host protection. Destination isolation, transfer scheduling and loss/
  lag drills remain open; no local staged export has been acknowledged as an independent received copy.
- Main protection now requires the existing documentation, runtime and image build/scan checks. Both installed
  merge-guard copies enforce the same floor; a real failed-scan probe was refused and closed unmerged, and the
  scheduled watchdog passed. `032` section 1.8 retains the remaining broader release-control work.
- D-53 and D-54 retain their bounded authority. Counsel-dependent retention, model-use and signing items are
  not inferred from successful code checks. Existing owner decisions are not new approval requests.
- `009` section 11 records the installed fast commit hook and measured CI improvements. Four shards, download
  caches and parallel static checks are in place; the complete required suite remains intact. The low-single-digit
  CI target, broader fixture optimization, paid runner choice and reduced-test selection are not complete.

## Historical snapshots

The following snapshots preserve their original dates and failure evidence. Their draft-PR, absent-feature,
protection and deployment statements are superseded by the current evidence above.

> **Historical evidence snapshot (2026-10-31): wave one is deployed; the full first-generation replacement is not release-ready.**
> D-53 authorized the bounded invitation/verification journey. Bead `bgl.19` records its move to the dedicated US
> host on image `5e8eaf8`, independently confirmed by the subsequent readback. Public intake and form
> parity are merged on `main`; the remaining combined workflow is published in draft PR #161.
> The owner's nine parity decisions are already recorded in `bgl.1` and mirrored as D-54 in `011`; they are not nine new
> approval requests. Live provider proofs, production admission, legacy-case continuation and the cutover remain
> distinct from those decisions. Task state and subsequent verification belong in Beads.

## Workflow evidence (2026-10-31)

| Workflow boundary | Evidence and implementation state | Production limit |
|---|---|---|
| Invitation, form, verification mail, explicit confirmation, staff dossier | Existing: D-53; live browser proof in `9kg.87` on 2026-10-30; US move recorded in `bgl.19` on 2026-10-31 | The US stack is running and Tailscale reports online without a health warning. Staff login recovery and the off-host backup leg remain separately tracked in `bgl.19`. |
| Public URLs, open-intake setting, bot checks and first-generation form fields | Merged: PR #148 (`77faf17`) and #151 (`61e48d1`) | Learn is not switched. Candidate `825353b` fixes trusted-proxy client identity; exact deployment proxy trust and a live check remain in `bgl.20`. |
| CAT reference and receipt before confirmation | In development: `bgl.5`, local `feat/parity-reference-receipt` at `361e9b5` | Not in the integration candidate at this snapshot. |
| Residence/phone screening and talent search | Open: `bgl.4`, `bgl.15`; no corresponding implementation found in the integration candidate | Do not describe them as delivered parity. GitHub research (`bgl.13`) is explicitly deferred by the owner's instruction, not a launch blocker. |
| Model review, routine advance and clarification | In development: PR #149, included in draft integration PR #161 | Candidate production admission exists behind a pinned profile (`bgl.22`); deployed activation remains off. Production token usage is uncapped, with shared request-rate pacing. An approved production rubric, model-use records and provider proof remain required. |
| NDA then User Agreement, service-sent links, details, company countersign and automatic release | In development: PRs #150 and #155, included in the integration candidate | Distribution remains `provider`, countersigning `manual`, release `owner`; live signing/custody prerequisites and canary `9kg.31.2` remain separate. |
| Mailbox creation, first-name naming and one-time-password welcome | In development: PR #152, included in the integration candidate | The candidate admits the specified production adapter through the pinned profile; the deployed adapter/domain are empty and canary `9kg.31.3` remains open. |
| Business-day reminders, lapse/reopen, sender/Reply-To, HTML wording and Twenty | In development: PRs #154, #156, #157 and #158, included in the integration candidate | Owner-approved wording must be loaded; mailbox polling has one owner; Twenty remains off in production; the candidate has an opt-in production boundary. |
| Legacy records | In development: PR #153; import mapping document `035` exists on that branch and the integration branch | Import is synthetic-tested, not production-run. It pauses open cases, queues no jobs and does not turn open legacy envelopes into v2 agreement instances. Read-only legacy status found 19 open cases, including 12 signing paths. Continuation is tracked in `bgl.23`; those cases cannot be orphaned at retirement. |
| Full cutover | Open: `bgl.17` rehearsal and `bgl.18` live cutover | No completed replacement-workflow canary or cutover receipt was found in the reviewed records. |

## Verification and record reconciliation (2026-10-31)

- P1 to P5 synthetic sign-offs remain D-26, D-33, D-36, D-45 and D-48; GATE-STAGING is D-50.
  They are evidence for their recorded revisions and scope, not a pass for the new parity integration.
- The integration's Markdown/index and Python lint checks pass. Its acceptance register has no structural errors.
  A full synthetic run at `f47632d` collected 2,258 tests and exposed two erasure failures; it was stopped for repair.
  A focused diagnostic confirmed `provisioning_credentialsetup.mode` was absent from the erasure catalog. The mode
  migration also replaced the trigger without preserving its erasure branch. Repair `f908358` passed seven targeted schema, erasure, migration round-trip and credential-identity checks.
  The subsequent full CI run `41246997416` failed: 26 failures, 2,233 passes and 375 errors. Its first failure
  compared an obsolete migration baseline; failure cleanup left the schema reversed and caused cascading errors.
  Two independent failures concerned fixture-name coverage and the notice-source import boundary. The repairs
  passed 95 focused checks, including erasure reversal/reapply and legacy import. Full CI `41250209345` then
  passed 2,270 tests with four failures in existing test registries and the provider import check. Those checks
  are corrected in the current update; passing full CI on the final head is still required (`bgl.21`).
- Production-configuration checks passed 38 tests. The earlier request/token pacing revision passed 42 focused
  checks. The owner subsequently removed all local token limits. Request-rate pacing and provider Retry-After
  remain. The request-rate-only update passed 233 focused checks, including the four prior CI failures.
  The account RPM allocation and live canaries remain deployment prerequisites.
  See `deploy/production/README.md` for the profile and shared-credential rate-allocation constraint.
- GitHub readback confirms an active `main` ruleset: PRs, linear history and both required CI checks, with zero
  required approving reviews. Older statements that `main` has no protection are historical (`032` section 1.8).
- The erasure key was created on 2026-10-30 (`032` section 3.12). The canary record still leaves the first erasure
  unfinished; key existence is not evidence of successful erasure.
- D-53 accepted a bounded wave-one launch before counsel's answers. D-54 records the later product decisions;
  it does not establish counsel clearance for every data class or live signing/model use. The reviewed Beads
  records (`211.7.1`, `211.7.4`) still distinguish those unresolved items.
- Read `034` as the parity inventory of its named baseline. Its absent features and policy refusals are not all
  current: later merged code, local work and the D-54 decisions must be considered separately.

## Earlier historical snapshots

The records below preserve their original dates and evidence. They do not describe current deployment state,
current GitHub protections or the current parity work graph.

> **Status (2026-10-26): the internal-launch candidate's launch-critical repository work is merged, apart from two open
> beads (`9kg.31.11`, `9kg.75`); nothing is deployed,
> enabled or owner-approved for real use.** Merged since 2026-10-23 (PRs #82 to #103, all through `safe-merge` on
> green required checks): the internal-launch batches, effect reconciliation after a restore (`9kg.33`), the erasure
> path (`9kg.32`), custody encryption (`9kg.34`), the live-call protections (`oc4.9`, `oc4.10`), the decline notice
> (`oc4.11`), the egress deny list (`9kg.39`) and erasure replay after a restore (`9kg.25`, TEST-P6-29 now full).
> Also merged on 2026-10-26: custody wrapping-key rotation (`9kg.69`), the custody health part (`9kg.70`), the
> journal's off-host copy (`9kg.60`) and naming an invited-only person for erasure (`9kg.72`). The owner decision package is `031`; the release-control readback and the host
> requests are `032`. Readiness, boundary by boundary, is in "Readiness" below. The restore drill's off-site,
> object-locked leg remains NOT RUN.
>
> **Previous banner (2026-10-23): P1 to P5 accepted for synthetic work; P6 staging built, drilled on the dev box and signed
> off (GATE-STAGING, D-50, 2026-10-22); the internal production launch is planned (`029`, handoff PL-A, PROPOSED)
> and not authorized.** GATE-S1 (D-26), GATE-P2 (D-33), GATE-P3 (D-36), GATE-P4 (D-45), GATE-P5 (D-48). Full-run
> CI 39797287619 at `d1e67e0`: 1353 passed; every gate PASS (GATE-STAGING 38, 17 of its cases partly proven per
> `028` section 4). Nothing is deployed; no real applicant data, live model, live Documenso, real mailbox or live
> provider key is used. The first production deployment is an invited internal cohort (the owner's dogfooding
> pilot) with its own gate (GATE-PILOT), decisions and go; see `029` sections 7, 13 and 14 and the "Next steps"
> below. The work graph lives in Beads (`bd ready`).
>
> **Previous banner (2026-10-17): P1, P2 and P3 accepted for synthetic work.** GATE-P3 signed off 2026-10-17 (D-36). GATE-S1 signed off 2026-10-11 (D-26), GATE-P2 signed off 2026-10-13 (D-33). P3: `018` approved (D-34); 3B.1 evidence collection (PR #30), 3B.2 bounded assessment with test models only (PR #32) and 3B.3 clarification (PR #34) and 3B.4 qualification decision (PR #35) merged; 3C verification merged (PR #36); GATE-P3 signed off (D-36; after-action report `020`); 3E (live synthetic evaluation) needs separate authorization. The candidate selection-quality contract was approved 2026-10-14 (D-35; `011` section 11, `019`). No deployment, no real applicant data, no live model call; the gates below stay open.
>
> (Previous banner, 2026-10-11: "first slice complete; P2 specified and approved for synthetic work; 2B.1 authorized, not yet built".)

## Readiness (2026-10-26)

| Boundary | Ready? | What stands between |
|---|---|---|
| A. Repository work, synthetic verification | the launch-critical repository beads are merged except two | open: `9kg.31.11` (admit `production`; blocks the dark deploy), `9kg.75` (the retention-due report; blocks the go/no-go, and needs POL-10's values); follow-ups: `9kg.71`, `9kg.73`, `9kg.74` |
| B. Read-only host preflight (`9kg.42`) | request prepared (`032` section 2) | the owner's go |
| C. Host preparation and the synthetic dark deploy (`9kg.28`, `9kg.31.5`) | **not ready** | the preflight (`9kg.42`); `9kg.35` (no server-side protection exists: `032` section 1.8); `9kg.31.11`; `9kg.31.4` (release preparation, which waits on `9kg.36`); the host name and coexistence (`211.7.3`); the custody locations (`211.7.9`); staff holders and devices (`211.7.5`); the challenge lifetime and page list (`211.7.7`, `211.7.2`); the journal-copy destination; and the owner's choice on `9kg.31.5`: POL-10 decided first (a live backup refuses while the registry is undecided) or the backup and restore proofs taken after it |
| D. Live-provider canaries (`9kg.31.1` to `.3`) | **not ready** | the dark deploy; POL-09 (`211.7.9`); the agreement inventory (`211.7.4`); `dy7.2`, `dy7.3`; `9kg.69`, `9kg.70`; each canary's own go |
| E. GATE-PILOT and real internal intake (`9kg.31.6`) | **not ready** | POL-10 and POL-09 decided (with counsel where `031` section 6 says); `211.7.2`, `211.7.4` to `211.7.8`; the canaries; `dy7.2`, `dy7.3`; `9kg.60`'s host wiring (merged code, destination PENDING); `9kg.75`; the go/no-go package (`9kg.31.4`); the owner's acceptance of the manual retention procedure as "enforced" and ratification of D-51 and D-M |
| F. Wider enrollment and the public cutover | **not in scope** | `9kg.31.10` and GATE-CUTOVER, separately authorized; `oc4.7`, `oc4.8`, `f1u.*`, `9kg.71`, `9kg.74` |

## State recorded on 2026-10-26

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
| Documentation and runtime CI | green on every merged head through `main` `0211ce9`; the last full run before a merge: CI run 40262971591 on PR #103's head `19c5b31` (merged as `e9193db`), its summary line "1821 passed in 1718.72s" (no failure, skip or error reported) | GitHub Actions |
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

## Blockers recorded on 2026-10-26

| Blocker | Owner | Blocks |
|---|---|---|
| POL-10 retention: no real retention or deletion until the policy and an operating authorization exist (ADR-14); the policy must cover adopted versions with their adoptions, challenges and audit (D-22) | Jeremy Longshore | any real deletion; GATE-PILOT |
| No server-side protection on `main`: no ruleset, no branch protection, no environment (readback 2026-10-26, `032` section 1.8); `safe-merge` is a dev-box discipline only (`9kg.35`, `9kg.36`) | Jeremy Longshore | host preparation; any deploy credential |
| `production` is not an admitted environment in code (`9kg.31.11`) | Jeremy Longshore (decisions), Claude Code (code) | the dark deploy |
| Confirmation link in the production proxy's access log: the staging proxy redacts the token; the production proxy filter is `dy7.3` | Jeremy Longshore | the cutover rehearsal |
| (Resolved since 2026-10-23: the release workflow's push to `main`, `oyu`, closed 2026-10-18; production transport settings, built in 6B.2; POL-13 staff two-factor and the role command, built in 6B.9 and `9kg.30`) | | |

## Next steps recorded on 2026-10-26

Current (2026-10-26): the owner decision package `031` (one set of recommended answers, all PROPOSALS) and the
requests in `032`. In order of what unblocks most:

1. The owner's go for the read-only host preflight (`9kg.42`, boundary B).
2. The owner's answers to `031` section 7, above all POL-10 (`211.7.1`) and POL-09 (`211.7.9`), with counsel's
   input on `031` section 6 (not sent; sending needs the owner's authorization).
3. The owner applies the GitHub protections (`9kg.35`, `9kg.36`; `032` section 1), then the readback and the
   refusal probes.
4. Repository work already authorized: `9kg.31.11`, `9kg.72`, then the release preparation (`9kg.31.4`).
5. After the preflight: host preparation (`9kg.28`, `032` section 3) and the synthetic dark deploy (`9kg.31.5`).

Earlier (2026-10-23, from `029` section 13):

1. The owner reviews the PL-A planning PR (`029`): the launch manifest (section 7), the decision brief (section
   14) and the first repo-only batch (section 13.3).
2. The first repo-only batch, under one bounded authorization: invitation mode, rate limits, the receipt and backup
   gates, the N+1 revert drill, the staff permission command, the human-only assessment path, effect reconciliation
   after restore, the evidence register, the personal-data scan, the pause-row guard.
3. Separately authorized batches: the GitHub protections (`9kg.35`); the read-only host preflight (`9kg.42`); the
   provider canaries (`9kg.31.1` to `.3`); after POL-10, the erasure path, replay and custody encryption.
4. Then release preparation, the dark deploy, the owner's go/no-go (GATE-PILOT for the internal cohort), the
   deployment, verification and the observation period; wider enrollment is a later decision.

History (as of 2026-10-17):

1. The open selection-quality inputs (`019` section 13): domain expert, operational delegate, private evaluation location.
2. P4: `021` approved (D-37); the read-only Documenso check done and 4B.1 merged (D-38, PR #38); 4B.2 released (D-39, draft pull request); next, the release of 4B.3; the P3 owner decisions (`018` section 18), first POL-05.
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
