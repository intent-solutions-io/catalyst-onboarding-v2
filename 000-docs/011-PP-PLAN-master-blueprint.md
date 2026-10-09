# Master Blueprint: Catalyst v2 build contract

| Field | Value |
|---|---|
| Document | `011-PP-PLAN-master-blueprint` (the only master blueprint for this repository) |
| Version | 0.1.0 |
| Status | **PROPOSED.** Draft for owner review. Merging this document is not approval of the product, of any open policy, or of any deployment. |
| Owner | Jeremy Longshore (product owner and approver) |
| Reviewers | `catalyst-django-architect` (build design), `catalyst-independent-qa` (independent review); results in section 9 |
| Date | 2026-10-09 |
| Classification | Public repository. No applicant data, agreement text, credentials, private paths or private knowledge. |
| Conventions | Intent Blueprint Docs 3.0.0 (stable IDs, evidence status, lifecycle links); doc-filing v4.5 |
| Supersedes | nothing; the earlier planning drafts named in section 2 were not available |

> **Status: PRELIMINARY, subject to review.** This repository has no application code. An assistant
> recommendation in this document is a proposal, never an owner decision.

## 1. How to read the build contract

A fresh session reads this file first, then follows the links. Each fact has one home:

| Question | Canonical home |
|---|---|
| What are we building, for whom, what is out of scope, which requirements are mandatory, how success is proved | `002-PP-PROD-product-requirements.md` (objectives `OBJ-`, requirements `REQ-`, measures `MET-`, gates `GATE-`, traceability matrix) |
| Which components exist, how they talk, which architecture decisions apply | `003-AT-ARCH-architecture.md` (components, data flow, security model, decision records `ADR-`) |
| What happens at every stage of the applicant journey, including failures | `004-UC-USER-user-journey.md` (stages `J-01` to `J-16`) |
| What the first implementation slice includes, excludes and must prove | `005-AT-DSGN-technical-spec.md` section S1 (tests `TEST-S1-`) |
| Who may authorize what, which policies are still open, how work is phased | this document, sections 4 to 7 |
| Where the project stands today | `006-LS-STAT-status.md` |
| How development work is authorized, checked and published | `009` (workflow contract), `010` (hooks and memory), `007`/`008` (specialist agents) |

Task state lives only in Beads. Bead identifiers appear in this document once, in section 7, so the
work graph can be found from the repository.

### Status vocabulary

| Label | Meaning |
|---|---|
| **OWNER-DECIDED** | the owner stated it, with the source named. Changes only by a new owner decision. |
| **PROPOSED** | a recommendation by the planning session or a specialist. Not binding until the owner approves it. |
| **NEEDS OWNER DECISION** | a business, legal or authority question only the owner (and counsel where named) can answer. |
| **NEEDS VERIFICATION** | a factual question about a system, version or provider that a check must settle. |

Evidence labels for work: MERGED (on `main`), DRAFT (open draft PR), LOCAL-ONLY (not pushed),
VERIFIED (observed by a named check), NOT VERIFIED.

## 2. Inputs reviewed and inputs not available

| Input | Status |
|---|---|
| `CLAUDE.md`, `AGENTS.md`, `000-INDEX.md`, `007` to `010`, `003` routing and staff-access sections | read at `main` `95b7537` (MERGED) |
| `001`, `002`, `004`, `005`, `006` | seeded templates with no project content before this revision |
| Beads (installed `bd` 1.1.2) | read; planning epic open, one workflow task in progress |
| Pull requests | #3 to #6 MERGED; #1 and #2 open Dependabot action bumps, unrelated to this contract |
| **Planning ZIP and earlier planning drafts** | **NOT AVAILABLE.** No ZIP or earlier blueprint draft exists in this repository, its Git history, or the maintainer's projects folder (searched 2026-10-09). Nothing in this contract claims to reflect their contents. |
| Earlier document numbering | the brief notes that earlier drafts used `009` and `010` for other purposes. In this repository `009` is the workflow contract and `010` the hook and memory register (MERGED, PR #5). Neither is renumbered. This blueprint takes the next free number, `011`. |
| Earlier phase identifiers and A/B/C handoff labels | **not found** in this repository. Section 7 defines provisional phase IDs `P0` to `P6` and `PL`. If the owner's earlier identifiers surface, map them onto section 7 rather than adding a parallel plan. |
| First-generation (legacy) implementation | not browsed. Its behaviour enters only through sanitized evidence packets assigned to `catalyst-legacy-analyst` (ADR-12). |

## 3. The product in one paragraph

Catalyst v2 is a new Django application that takes a person who asks for access at
`learn.intentsolutions.io` through a recorded, auditable onboarding: a safely stored application,
proof that they control their email address, deterministic evidence collection, a bounded advisory
assessment by MiniMax through PydanticAI, clarifying questions answered by email, a qualification
decision made by an authorized human, an NDA and then a User Agreement (and any other required
agreement) signed through the existing Documenso installation by every required participant, a
company mailbox provisioned through the existing MXroute service, and activation with a welcome. One
PostgreSQL database holds a progressive dossier of everything that happened. Routine correspondence is
automated under written policy, with explicit stop and escalation rules, and authorized staff can see
and resolve every permitted exception through Django admin and focused Django views, without SSH,
direct database edits or a coding agent. The learning site itself is not replaced.

## 4. Owner decisions and boundaries

Decision records with rationale live in `003` section "Architecture decisions". This table is the
summary a reader needs first.

| ID | Boundary | Status | Source |
|---|---|---|---|
| D-01 | One new Django-native project with a small number of cohesive apps | OWNER-DECIDED | owner build-contract instruction, 2026-10-09; README "Why a new repository" (first-generation decision 22, 2026-10-09) |
| D-02 | PostgreSQL for development tests, staging and production; no silent SQLite fallback | OWNER-DECIDED | owner instruction 2026-10-09 |
| D-03 | One durable PostgreSQL-backed background execution mechanism; no Temporal, no second workflow engine | OWNER-DECIDED | owner instruction 2026-10-09; charter `007` section 3 |
| D-04 | MiniMax through PydanticAI for bounded assessments; model output never authorizes a transition | OWNER-DECIDED | owner instruction 2026-10-09; charter section 3 |
| D-05 | Existing Documenso installation for signing | OWNER-DECIDED | owner instruction 2026-10-09 |
| D-06 | Existing MXroute services for correspondence and approved mailbox provisioning | OWNER-DECIDED | owner instruction 2026-10-09 |
| D-07 | Django admin and focused Django views for staff operations | OWNER-DECIDED | owner instruction 2026-10-09 |
| D-08 | Twenty CRM deferred beyond the MVP | OWNER-DECIDED | owner instruction 2026-10-09 |
| D-09 | The learning site is not replaced; explicit proxy routing assigns onboarding paths to Django | OWNER-DECIDED | owner instruction 2026-10-09; current routing VERIFIED read-only in `003` |
| D-10 | Development hooks and coding agents never operate the live applicant workflow | OWNER-DECIDED | owner instruction 2026-10-09; `009` section 6 |
| D-11 | The legacy implementation is not the architectural template; only approved, sanitized behaviour and integration evidence is used | OWNER-DECIDED | owner instruction 2026-10-09; charter section 3 |
| D-12 | Staff interface on a separate authenticated hostname with network restriction and MFA where supported; hostname and method still to be verified | OWNER-DECIDED (design); details NEEDS VERIFICATION | `009` section 9 decision 5 |
| D-13 | Bead history is public; sanitized engineering work only | OWNER-DECIDED | `009` section 9 decision 2 |
| D-14 | A clean repository does not authorize discarding live first-generation records | OWNER-DECIDED | owner instruction 2026-10-09 |

**Contradictions found and not resolved here (flagged for the owner):**

1. `README.md` lists "a Twenty CRM projection of the relationship" in the platform description,
   while D-08 defers Twenty beyond the MVP. This contract treats Twenty as out of MVP scope;
   the README sentence should be corrected in a later docs change.
2. The README's target shape says "the existing email provider" and "an LLM provider abstraction".
   D-04 and D-06 are more specific (MiniMax through PydanticAI; MXroute). PydanticAI is the
   abstraction; MiniMax is the only provider in scope.

## 5. Who may authorize what

| Action | Authority | Status |
|---|---|---|
| Approve this contract, a PRD revision, an ADR | owner, in a merged PR that records the approval | OWNER-DECIDED (`009` section 2) |
| Merge code or documents | owner, through the estate merge guard | OWNER-DECIDED (`009` section 5.5) |
| Deploy to staging or production; change proxy, DNS, provider configuration or secrets | owner, as a separate act from merge approval | OWNER-DECIDED (`009` section 2) |
| Admit, decline or hold an applicant | **NEEDS OWNER DECISION** (POL-05). Until decided, the product must not let anyone record an admission or a decline: the stage is blocked, not defaulted. | fail-closed default PROPOSED |
| Approve agreement texts and the agreement inventory | owner with counsel (POL-07) | NEEDS OWNER DECISION |
| Countersign agreements | NEEDS OWNER DECISION (POL-08) | |
| Approve mailbox provisioning for an applicant | NEEDS OWNER DECISION (POL-11) | |
| Create or change staff accounts and groups | owner (POL-13) | PROPOSED |
| Pause or resume automation for one application | staff in a group the owner names (POL-13) | PROPOSED |
| MiniMax assessment output | advisory only; never an authorization | OWNER-DECIDED (D-04) |
| Coding agents and hooks | no authority over the live workflow | OWNER-DECIDED (D-10) |

## 6. Open policy register

Nothing here is invented. Each entry states the question, who decides, and the earliest milestone it
actually blocks. Where the first slice needs a working value, it uses a labelled PROPOSED default
that the owner can change without code redesign. Tracked by the bead "Obtain owner decisions on the
open product policies listed in the master blueprint".

| ID | Open question | Decides | Earliest milestone blocked | First-slice handling |
|---|---|---|---|---|
| POL-01 | Applicant identity key and duplicate policy: is "same applicant" the normalized email address; may a person hold more than one open application; what happens after a decline or withdrawal | owner | GATE-S1 acceptance sign-off (the slice encodes a default) | PROPOSED defaults (`005` S1.3): identity is a case-folded email key with plus-addressing kept distinct; one open application per key; a repeat becomes a new submission version; a repeat after verification is recorded as unverified and goes to staff, never overwriting verified data |
| POL-02 | Verification link lifetime, resend limits, what an expired link offers | owner | GATE-STAGING | PROPOSED default: lifetime is a setting; no number is approved; tests use a short synthetic value |
| POL-03 | Which evidence is required and how it is collected (and from which sources the system may fetch) | owner | P3 start | not in slice |
| POL-04 | Assessment rubric, what the model may see, what it may recommend | owner | P3 start | not in slice |
| POL-05 | Qualification authority: who may admit, decline or hold; whether two people are needed; appeal or reconsideration | owner | P3 decision stage (J-10) | not in slice |
| POL-06 | Communications policy: approved templates, reminder cadence and maximum, quiet hours, stop rules for autoresponders, bounces and loops, when staff take over | owner | P2 start | slice sends one verification message only, to a local sink |
| POL-07 | Agreement inventory: NDA, User Agreement and any other required agreement, their versions and order | owner with counsel | P4 start | not in slice |
| POL-08 | Signing roles: required participants, signing order, countersigner | owner with counsel | P4 start | not in slice |
| POL-09 | Document custody: where executed documents are stored, encryption, who may retrieve them, audit | owner | P4 start | not in slice |
| POL-10 | Retention and deletion for applications, declined and withdrawn records, messages, documents and logs | owner with counsel | GATE-PILOT (no real applicant data before) | synthetic data only |
| POL-11 | Provisioning scope: mailbox naming, aliases, any other access granted at activation; who approves | owner | P5 start | not in slice |
| POL-12 | Withdrawal, closure and reopening rules | owner | P5 (J-16); duplicate interaction affects POL-01 | not in slice |
| POL-13 | Staff roles and groups (read-only, operator, decision-maker), MFA package | owner | GATE-STAGING | slice uses one PROPOSED read-only group, local only |
| POL-14 | Staff hostname and network access method | owner | GATE-STAGING | not in slice (local only) |
| POL-15 | Legacy data: which live first-generation records move, coexistence period, cutover rules | owner | GATE-CUTOVER | not in slice; separate epic |
| POL-16 | Numerical operating targets for the measures in `002` (`MET-`) | owner | GATE-PILOT | measures defined, no targets |
| POL-17 | Applicant-facing notices (privacy notice, what the applicant is told about automated assessment) | owner with counsel | GATE-PILOT | placeholder synthetic text only |

## 7. Phased work graph

Provisional phase identifiers (section 2). Each phase runs as small sequential handoffs: **A** specify
and decompose into beads, **B** implement in one branch and one PR per task, **C** independent
verification and the epic's after-action report (`009` section 10). A phase starts only when its
predecessor's gate passes and the policies it needs are decided. Later epics stay coarse until then.

| Phase | Epic bead (title) | Bead | Depends on | Exit gate |
|---|---|---|---|---|
| P0 | Develop the master blueprint, PRD, architecture and phased execution plan before any code is written | `catalyst-v2-211` | none | owner approves this contract (bead `catalyst-v2-211.6`) |
| P1 | Build the first working slice: synthetic intake, email verification to a local mail sink, and a read-only staff view | `catalyst-v2-6hl` | P0 | GATE-S1 |
| P2 | Run the applicant correspondence loop: outbound policy, inbox correlation, reminders, stop rules and human takeover | `catalyst-v2-7hu` | P1; POL-06 | GATE-P2 |
| P3 | Collect evidence, run the bounded MiniMax assessment, and record the authorized qualification decision | `catalyst-v2-oc4` | P2; POL-03, POL-04, POL-05 | GATE-P3 |
| P4 | Issue and verify the NDA, User Agreement and other required agreements through Documenso with protected custody | `catalyst-v2-hdg` | P3; POL-07, POL-08, POL-09 | GATE-P4 |
| P5 | Provision the approved mailbox, activate the applicant, and support withdrawal and recovery | `catalyst-v2-tuc` | P4; POL-11, POL-12 | GATE-P5 |
| P6 | Prepare staging, deployment, backup with demonstrated restore, monitoring and the reversible Learn routing cutover | `catalyst-v2-9kg` | P5, PL; POL-10, POL-13, POL-14 | GATE-STAGING, GATE-PILOT, GATE-CUTOVER |
| PL | Plan legacy data compatibility so no live first-generation record is discarded | `catalyst-v2-dy7` | P0 | feeds GATE-CUTOVER |

P6 is listed last for dependency, not as one late phase: staging preparation (environments, backups,
monitoring) can be decomposed and started after P1 once the owner authorizes it. Every phase ships
working, tested behaviour; no phase defers all integration to the end.

**First-slice tasks (P1), in order:**

| Key | Bead | Title | Depends on |
|---|---|---|---|
| S1-T1 | `catalyst-v2-6hl.1` | Select and verify the Django, Python, PostgreSQL, driver and job-runner versions for the first slice | owner approval (`catalyst-v2-211.6`) |
| S1-T2 | `catalyst-v2-6hl.2` | Create the Django project skeleton with PostgreSQL-only settings, provider guards and the CI runtime lane | S1-T1 |
| S1-T3 | `catalyst-v2-6hl.3` | Model the application, submission versions, history events and pending actions with their constraints | S1-T2 |
| S1-T4 | `catalyst-v2-6hl.4` | Accept the public access-request form with validation, duplicate handling and one atomic commit | S1-T3 |
| S1-T5 | `catalyst-v2-6hl.5` | Run the durable worker that sends the verification message to the local mail sink and recovers after interruption | S1-T4 |
| S1-T6 | `catalyst-v2-6hl.6` | Confirm contact control once through an explicit, expiring, single-use confirmation | S1-T5 |
| S1-T7 | `catalyst-v2-6hl.7` | Give authorized staff a read-only view of applications and their history, and refuse everyone else | S1-T3 |
| S1-T8 | `catalyst-v2-6hl.8` | Prove the first slice against its acceptance plan and record the evidence | S1-T6, S1-T7 |

## 8. Definition of success

The product is proved by the gates in `002` section 6, not by this document. In short: every
mandatory requirement has an acceptance test, every test result is recorded as PASS, FAIL, SKIPPED,
NOT RUN or BLOCKED with its evidence, and each gate names who approves it. A planned test is not a
passing test, a written agent definition is not a verified runtime, a saved document is not an
executed agreement, a sent email is not proof of delivery, a backup is not proof of restore, and an
LLM recommendation is not an authorized decision.

## 9. Review record

Filled in by the reviewing session; see the pull request for the full reports.

| Reviewer | Revision reviewed | Verdict | Material findings and disposition |
|---|---|---|---|
| `catalyst-django-architect` | working tree before first commit, 2026-10-09 | accept with fixes | 3 blocking (lease fencing, clock and poison rules; `workflow` foreign key would create a dependency cycle; no custom user model decision), 8 should-fix (challenge predicate, constraint-specific race handling, repeat submission into a verified dossier, race test seams, token key and logging, start-up guards, append-only enforcement, request limits), 13 test gaps. **All adopted** into `005` S1.2 to S1.7, `003` (components, error handling, ADR-03, ADR-14 to ADR-18), `004` (J-02, J-03, J-09) and POL-01. Re-reviewed by the independent reviewer below, not by the architect |
| `catalyst-independent-qa` | pending | pending | pending |
