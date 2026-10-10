# Master Blueprint: Catalyst v2 build contract

| Field | Value |
|---|---|
| Document | `011-PP-PLAN-master-blueprint` (the only master blueprint for this repository) |
| Version | 1.1.0 (ADR decisions of 2026-10-10 recorded) |
| Status | **APPROVED IN SCOPE** (section 10): project direction, amended requirements and the bounded synthetic first-slice scope. ADR-03, ADR-14, ADR-17 and ADR-18 **decided 2026-10-10** (D-16 to D-19). **Not approved:** the 19 open policies, provider writes, deployment, release; implementation only as each handoff is authorized (1B.1 authorized 2026-10-10, to start once PR #8 merges). Items marked PROPOSED elsewhere stay proposals. |
| Owner | Jeremy Longshore (product owner and approver) |
| Reviewers | `catalyst-django-architect` (build design), `catalyst-independent-qa` (independent review); results in section 9 |
| Date | 2026-10-09 |
| Classification | Public repository. No applicant data, agreement text, credentials, private paths or private knowledge. |
| Conventions | Intent Blueprint Docs 3.0.0 (stable IDs, evidence status, lifecycle links); doc-filing v4.5 |
| Supersedes | nothing; the earlier planning drafts named in section 2 were not available |

> **Status: PRELIMINARY, subject to review.** Application code is limited to authorized handoffs (1B.1: the skeleton). An assistant
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
| Earlier phase identifiers and A/B/C handoff labels | **not found** in this repository. Section 7 defines engineering epic identifiers `P0` to `P6` and `PL`. If the owner's earlier identifiers surface, map them onto section 7 rather than adding a parallel plan. |
| First-generation (legacy) implementation | not browsed. Its behaviour enters only through sanitized evidence packets assigned to `catalyst-legacy-analyst` (ADR-12). |

## 3. The product in one paragraph

Catalyst v2 is a new Django application that takes a person who asks for access at
`learn.intentsolutions.io` through a recorded, auditable onboarding: a safely stored application,
proof that they control their email address, deterministic evidence collection, a bounded advisory
assessment by MiniMax through PydanticAI, clarifying questions answered by email, a qualification
decision made by an authorized human, an NDA whose verified completion must come before the User
Agreement is shown or issued (D-15), then the User Agreement and any other required agreements, signed through the existing Documenso installation by every required participant, a
company mailbox provisioned through the existing MXroute service, and activation with a welcome. One
PostgreSQL database holds a progressive dossier of everything that happened. Routine correspondence is
automated under written policy, with explicit stop and escalation rules, and authorized staff can see
and resolve every permitted exception through Django admin and focused Django views, without SSH,
direct database edits or a coding agent. The learning site itself is not replaced.

## 4. Owner decisions and boundaries

### 4.1 Recorded owner direction (source of D-01 to D-11 and D-14 to D-24)

The owner gave this project direction in the build-contract instruction of 2026-10-09, in the
invoking session. It is recorded here verbatim so a fresh session can check the source. The owner
confirms or amends the record by approving or changing this document's pull request.

> - One new Django-native project, with a small number of cohesive apps.
> - PostgreSQL for development database tests, staging, and production; no silent SQLite fallback.
> - One durable PostgreSQL-backed background execution mechanism.
> - MiniMax through PydanticAI for bounded assessments.
> - Existing Documenso for signing.
> - Existing MXroute services for correspondence and approved mailbox provisioning.
> - Django Admin and focused Django views for staff operations.
> - Twenty deferred beyond the MVP.
> - The learning site is not being replaced by default; explicit routing assigns onboarding requests
>   to Django.
> - Development hooks and coding agents never operate the live applicant workflow.
> - The legacy implementation is not the architectural template. Use approved, sanitized
>   behavior/integration evidence; no unrestricted legacy browsing or copying.
>
> "A clean repository does not authorize discarding live records."
>
> "An assistant recommendation is not owner approval. Merging documentation is not automatically
> approval to deploy."

**Amendment of 2026-10-09** (owner-directed amendment to this pull request, recorded verbatim):

> "Verified completion of the required NDA must precede exposure or issuance of the User Agreement.
> The full agreement inventory, templates, versions, participants, countersigning, and additional
> custody prerequisites remain open."
>
> "Email confirmation proves contact control, not authorship or approval of every submission made using
> the address."
>
> "Keep P0-P6 and PL as engineering epic identifiers. Record how they map to numbered A/B/C owner
> handoffs, delivered one at a time and expandable as needed."

**ADR decisions of 2026-10-10** (owner instruction, against the `012` evidence at PR #8 head
`62a4a9dee2f5cb89efb2a123120dd109f2a2a07b`), recorded verbatim in their essentials:

> "ADR-03: Approve the custom PostgreSQL pending-action ledger and Django management-command worker for
> the bounded Catalyst MVP. This is not authorization to build a reusable queue framework, distributed
> scheduler, plugin architecture, or second execution engine."
>
> "ADR-14: Approve privileges plus triggers for the protected append-only tables, with separate
> migration-owner, application, and retention roles. Ordinary operational tables may still be updated
> through approved services. Do not make the whole application database append-only." "Approve the
> capability for a separately authorized, audited retention operation--not a default permission to
> delete real records. POL-10 stays open."
>
> "ADR-17: Approve this initial application baseline: Python 3.14.8, Django 5.2.18 LTS, PostgreSQL
> 16.15, Psycopg 3.3.6." "The test-tool versions reported in 012 were not run." "Pin container images
> by digest."
>
> "ADR-18: Approve a minimal accounts.User subclass of AbstractUser with AUTH_USER_MODEL established
> before the first migration. Applicants remain dossier records, not automatically created accounts."

The full conditions (fair comparison, unproven worker behaviours, role boundaries, retention limits,
test-tool verification) are recorded on each ADR row in `003`.

**S1 recovery policy, 2026-10-10** (owner closeout instruction for PR #9):

> "For S1 only, approve redelivery of the identical verification invitation to the local test sink after
> an interrupted attempt. This does not mean uncertain outcomes cannot occur. S1 still requires attempts,
> bounded recovery, lease fencing, interruption tests, and no duplicate challenge/adoption/next-stage
> action. Provider-specific reconciliation is deferred to P2 or the appropriate later integration phase,
> before real external actions are enabled."

**PR #11 closeout, 2026-10-10** (owner instruction against PR #11 head
`1fb0f1c09332209053ae2bc0c1d506a5e6a62d62`), recorded verbatim in its essentials:

> "Use a test-only privileged reset for the disposable test database where real-transaction/concurrency
> tests require it. Do not create a fresh database for every ordinary test by default. Application
> behavior must execute under the restricted application role with all normal grants, constraints and
> protection triggers enabled." "Do not use a global replication-role switch or blanket constraint
> disabling as the default solution." "Do not add a TESTING bypass to production trigger functions or
> give the application role owner/retention privileges."
>
> "Treat VersionAdoption as protected history." "For this milestone, do not grant the retention role a
> new deletion capability for adoptions. POL-10 stays open." "Do not introduce a cascade or relax
> foreign keys merely to make cleanup easier." "Preserve the stated owner/superuser limitations: owners
> can alter protections; the system is not administrator-proof."
>
> "Keep E002 as a useful diagnostic and add the smallest shared runtime enforcement needed to refuse
> privileged database use by the web process before application operations. The later worker must use
> that same contract when implemented." "A stale environment value naming a migration/management
> process must not silently exempt the actual web entry point."
>
> "Django Admin: Approve necessary session/admin-log grants and creation of the read-only staff group's
> permissions in S1-T7, not in this closeout. Use least privilege and an authorized setup/migration
> path. The runtime application must not gain authority to grant itself staff, superuser or group
> permissions."
>
> "Confirmation: Retain the signed-challenge design specified in 005/ADR-16. The raw
> ContactChallenge.public_id is not sufficient authorization. A valid signature and the existing
> database checks are required. Do not display or export the complete token, signature or usable
> signing link through the staff interface. Do not log them or save them in ApplicationEvent." "No
> read-only staff action may mint applicant confirmation links."
>
> "Retention: POL-10 must include adopted versions and associated records. No real deletion, retention
> schedule or retention UI is authorized."

### 4.2 Decision summary

Decision records with rationale live in `003` section "Architecture decisions". This table is the
summary a reader needs first.

| ID | Boundary | Status | Source |
|---|---|---|---|
| D-01 | One new Django-native project with a small number of cohesive apps | OWNER-DECIDED | section 4.1; README "Why a new repository" (first-generation decision 22, 2026-10-09) |
| D-02 | PostgreSQL for development tests, staging and production; no silent SQLite fallback | OWNER-DECIDED | section 4.1 |
| D-03 | One durable PostgreSQL-backed background execution mechanism; no Temporal, no second workflow engine | OWNER-DECIDED | section 4.1; charter `007` section 3 |
| D-04 | MiniMax through PydanticAI for bounded assessments; model output never authorizes a transition | OWNER-DECIDED | section 4.1; charter section 3 |
| D-05 | Existing Documenso installation for signing | OWNER-DECIDED | section 4.1 |
| D-06 | Existing MXroute services for correspondence and approved mailbox provisioning | OWNER-DECIDED | section 4.1 |
| D-07 | Django admin and focused Django views for staff operations | OWNER-DECIDED | section 4.1 |
| D-08 | Twenty CRM deferred beyond the MVP | OWNER-DECIDED | section 4.1 |
| D-09 | The learning site is not replaced; explicit proxy routing assigns onboarding paths to Django | OWNER-DECIDED | section 4.1; current routing checked read-only on 2026-10-09 (PR #5); the live proxy configuration is the authoritative baseline (`003`) |
| D-10 | Development hooks and coding agents never operate the live applicant workflow | OWNER-DECIDED | section 4.1; `009` section 6 |
| D-11 | The legacy implementation is not the architectural template; only approved, sanitized behaviour and integration evidence is used | OWNER-DECIDED | section 4.1; charter section 3 |
| D-12 | Staff interface on a separate authenticated hostname with network restriction and MFA where supported; hostname and method still to be verified | OWNER-DECIDED (design); details NEEDS VERIFICATION | `009` section 9 decision 5 |
| D-13 | Bead history is public; sanitized engineering work only | OWNER-DECIDED | `009` section 9 decision 2 |
| D-14 | A clean repository does not authorize discarding live first-generation records | OWNER-DECIDED | section 4.1 |
| D-15 | Verified completion of the required NDA must precede exposure or issuance of the User Agreement | OWNER-DECIDED | section 4.1 (amendment) |
| D-16 | ADR-03: custom PostgreSQL pending-action ledger and management-command worker, bounded to the MVP | OWNER-DECIDED | section 4.1 (ADR decisions 2026-10-10); `003` ADR-03 |
| D-17 | ADR-14: privileges plus triggers on protected history tables, three roles; retention capability only, no real deletion until POL-10 | OWNER-DECIDED | section 4.1; `003` ADR-14 |
| D-18 | ADR-17: Python 3.14.8, Django 5.2.18 LTS, PostgreSQL 16.15, psycopg 3.3.6; locked dependencies; digest-pinned images | OWNER-DECIDED | section 4.1; `003` ADR-17 |
| D-19 | ADR-18: minimal `accounts.User(AbstractUser)` before the first migration; applicants are not accounts | OWNER-DECIDED | section 4.1; `003` ADR-18 |
| D-20 | S1 recovery policy: only the identical verification invitation may be redelivered to the local sink after an interrupted attempt; S1 still proves attempts, bounded recovery, lease fencing, interruption and no duplicate challenge, adoption or next-stage action; provider-specific reconciliation is P2 or later, before real external actions | OWNER-DECIDED | section 4.1 (2026-10-10 closeout); `003` ADR-15 |
| D-21 | Test cleanup: the suite runs as the application role; tests that commit use a test-only privileged reset of this run's own test database (identity-marker check, only the named `catalyst_no_truncate` triggers disabled for the reset, trigger and privilege state re-verified, failure fails the run); no bypass in trigger functions, no replication-role switch | OWNER-DECIDED | section 4.1 (PR #11 closeout); `tests/conftest.py` |
| D-22 | `VersionAdoption` is protected history: no role may update, delete or truncate it; no retention path for adoptions until POL-10; same-application foreign keys unchanged | OWNER-DECIDED | section 4.1 (PR #11 closeout); `003` ADR-14; migration `applications.0003` |
| D-23 | Django Admin in S1-T7: only the session and admin-log grants it needs, and the read-only staff group's permissions, created through an authorized setup or migration path; the runtime application never grants itself staff, superuser or group rights | OWNER-DECIDED | section 4.1 (PR #11 closeout); bead S1-T7 |
| D-24 | Confirmation token contract: the signed challenge `public_id` (ADR-16); the raw `public_id` is not authorization, a valid signature plus the database checks are; the token, signature and link are never shown, exported, logged or stored in events, and no staff action can mint a link | OWNER-DECIDED | section 4.1 (PR #11 closeout); `003` ADR-16; bead S1-T6 |

**Contradictions found:**

1. `README.md` promised a Twenty projection and an unnamed email and LLM provider. Corrected in this
   change to match D-04, D-06 and D-08.

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
| POL-03 | Which evidence is required and how it is collected (and from which sources the system may fetch); the final intake form fields | owner | P3 start (evidence); GATE-PILOT (form fields shown to real applicants) | S1 uses a synthetic placeholder field set (name, email, reason) only |
| POL-04 | Assessment rubric, what the model may see, what it may recommend | owner | P3 start | not in slice |
| POL-05 | Qualification authority: who may admit, decline or hold; whether two people are needed; appeal or reconsideration | owner | P3 decision stage (J-10) | not in slice |
| POL-06 | Communications policy: approved templates, reminder cadence and maximum, quiet hours, stop rules for autoresponders, bounces and loops, when staff take over | owner | P2 start | slice sends one verification message only, to a local sink |
| POL-07 | Agreement inventory: the exact approved NDA and User Agreement templates and versions, any other required agreements and their order after the NDA (the NDA-before-User-Agreement rule itself is decided, D-15) | owner with counsel | P4 start | not in slice |
| POL-08 | Signing roles: required participants, signing order, countersigner | owner with counsel | P4 start | not in slice |
| POL-09 | Document custody and its gate: where signed documents are stored, encryption, who may retrieve them, audit, and whether verified custody is required (in addition to verified signing completion) before the next agreement or stage | owner | P4 start | not in slice |
| POL-10 | Retention and deletion for applications, declined and withdrawn records, messages, documents and logs; must cover adopted submission versions together with their adoption records, challenges and audit evidence (D-22) | owner with counsel | GATE-PILOT (no real applicant data before) | synthetic data only; no deletion, retention schedule or retention UI is authorized |
| POL-11 | Provisioning scope: mailbox naming, aliases, any other access granted at activation; who approves | owner | P5 start | not in slice |
| POL-12 | Withdrawal, closure and reopening rules | owner | P5 (J-16); duplicate interaction affects POL-01 | not in slice |
| POL-13 | Staff roles and groups (read-only, operator, decision-maker), MFA package | owner | GATE-STAGING | slice uses one PROPOSED read-only group, local only |
| POL-14 | Staff hostname and network access method | owner | GATE-STAGING | not in slice (local only) |
| POL-15 | Legacy data: which live first-generation records move, coexistence period, cutover rules | owner | GATE-CUTOVER | not in slice; separate epic |
| POL-16 | Numerical operating targets for the measures in `002` (`MET-`) | owner | GATE-PILOT | measures defined, no targets |
| POL-17 | Applicant-facing notices (privacy notice, what the applicant is told about automated assessment) | owner with counsel | GATE-PILOT | placeholder synthetic text only |
| POL-18 | Required details: which personal or business details the agreements and provisioning need, when they are collected and who may see them | owner with counsel | P4 start | not in slice |
| POL-19 | Identity disputes: what staff do when a repeat submission, a reply or a signer conflicts with the verified identity, and who resolves it | owner | P2 start (first staff item from an unverified repeat appears in S1 but needs no resolution there) | S1 records the conflict as a staff item only |

## 7. Phased work graph

`P0` to `P6` and `PL` are **engineering epic identifiers**. Delivery to the owner happens in
**numbered A/B/C handoffs**, one at a time, each released by the owner before it starts:

| Handoff | Content | Ends with |
|---|---|---|
| `<n>A` | specify and decide: checks, comparisons and bead decomposition for phase `P<n>`; no application code | owner decisions recorded |
| `<n>B` | implement: one branch and one PR per task bead; expandable as `<n>B.1`, `<n>B.2`, ... when a real dependency needs more than one step | each PR's required checks green |
| `<n>C` | verify: run the phase's acceptance plan, independent review, the epic after-action report (`009` section 10) | the phase gate |

Mapping so far, without inventing earlier lettered handoffs: P0 is still in review (its exit gate, the
owner's approval, is not met) and has no lettered handoffs; its earlier merged setup work is not
relabelled. The first
lettered handoff is **1A: S1-T1 compatibility and comparison checks only** (`005` S1.6a), followed by the
owner's S1-D decisions; then 1B (S1-T2 to S1-T7) and 1C (S1-T8, GATE-S1). If the owner's own handoff
numbering differs, this table is adjusted to it; no second roadmap is created. A phase starts only when
its predecessor's gate passes and the policies it needs are decided. Later epics stay coarse until then.

| Phase | Epic bead (title) | Bead | Depends on | Exit gate |
|---|---|---|---|---|
| P0 | Develop the master blueprint, PRD, architecture and phased execution plan before any code is written | `catalyst-v2-211` | none | owner approves this contract (bead `catalyst-v2-211.6`) |
| P1 | Build the first working slice: synthetic intake, email verification to a local mail sink, and a read-only staff view | `catalyst-v2-6hl` | contract approval (bead `catalyst-v2-211.6`, on S1-T1); not the open policy beads (corrected 2026-10-10) | GATE-S1 |
| P2 | Run the applicant correspondence loop: outbound policy, inbox correlation, reminders, stop rules and human takeover | `catalyst-v2-7hu` | P1; POL-06, POL-19 | GATE-P2 |
| P3 | Collect evidence, run the bounded MiniMax assessment, and record the authorized qualification decision | `catalyst-v2-oc4` | P2; POL-03, POL-04, POL-05 | GATE-P3 |
| P4 | Issue and verify the NDA, User Agreement and other required agreements through Documenso with protected custody | `catalyst-v2-hdg` | P3; POL-07, POL-08, POL-09, POL-18 | GATE-P4 |
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
| S1-D | `catalyst-v2-6hl.9` | Obtain the owner's decisions on ADR-03, ADR-14, ADR-17 and ADR-18 before the first migration | S1-T1 (decided 2026-10-10: D-16 to D-19) |
| S1-T2 | `catalyst-v2-6hl.2` | Create the Django project skeleton with PostgreSQL-only settings, provider guards and the CI runtime lane | S1-D |
| S1-T3 | `catalyst-v2-6hl.3` | Model the application, submission versions, history events and pending actions with their constraints | S1-T2 |
| S1-T4 | `catalyst-v2-6hl.4` | Accept the public access-request form with validation, duplicate handling and one atomic commit | S1-T3 |
| S1-T5 | `catalyst-v2-6hl.5` | Run the durable worker that sends the verification message to the local mail sink and recovers after interruption | S1-T4 |
| S1-T6 | `catalyst-v2-6hl.6` | Confirm contact control once through an explicit, expiring, single-use confirmation | S1-T5 |
| S1-T7 | `catalyst-v2-6hl.7` | Give authorized staff a read-only view of applications and their history, and refuse everyone else | S1-T4 |
| S1-T8 | `catalyst-v2-6hl.8` | Prove the first slice against its acceptance plan and record the evidence | S1-T6, S1-T7 |

## 8. Definition of success

The product is proved by the gates in `002` section 6, not by this document. In short: every
mandatory requirement has an acceptance test, every test result is recorded as PASS, FAIL, SKIPPED,
NOT RUN or BLOCKED with its evidence, and each gate names who approves it. A planned test is not a
passing test, a written agent definition is not a verified runtime, a saved document is not an
executed agreement, a sent email is not proof of delivery, a backup is not proof of restore, and an
LLM recommendation is not an authorized decision.

## 9. Review record

Both reviews ran on 2026-10-09 with the read-only specialists. Summaries (local paths removed) are
posted as comments on the pull request; the findings and where each landed are listed here.

**`catalyst-django-architect`** reviewed the working tree before the first commit. Verdict: accept with
fixes. All findings adopted:

| Finding | Landed in |
|---|---|
| B1 lease without fencing, clock source or poison rule | `005` S1.4 ledger rules 1-8; `003` ADR-03, ADR-15, error handling; TEST-S1-17, TEST-S1-18 |
| B2 `workflow` foreign key to `applications` creates a dependency cycle | `005` S1.4 subject-generic `PendingAction` and `AutomationPause`; `003` component table and layer rule; `004` J-09; TEST-S1-20 |
| B3 no custom user model decision | `003` ADR-18; `005` S1.4, S1.9; bead S1-D |
| S1 challenge "active" predicate cannot encode expiry | `005` S1.2, S1.4; `004` J-02 |
| S2 race handling: named constraint only, version counter, lock order, email key, no reference on the received page | `005` S1.2 to S1.4; `004` J-03 |
| S3 repeat submission could write into a verified dossier | `005` S1.2, S1.3; `004` J-02; POL-01, POL-19 |
| S4 race and crash tests could pass without exercising the race | `005` S1.7 preamble, TEST-S1-04, TEST-S1-07 |
| S5 token: one expiry authority, random id, dedicated key, logging, headers, CSRF cookie, base URL | `003` ADR-16; `005` S1.2, S1.5; TEST-S1-06, 08, 09, 16 |
| S6 system checks do not run under web servers | `005` S1.5; TEST-S1-13 |
| S7 admin permissions cannot enforce append-only | `003` ADR-14; TEST-S1-21 |
| S8 oversized requests are a 400, not a form error | `005` S1.5; TEST-S1-02 |
| 13 missing test cases | TEST-S1-03, 04, 09, 10, 12, 16 extended; TEST-S1-17 to 20 added |

**`catalyst-independent-qa`** reviewed commit `f6d18b2` (the first commit of this branch). Verdict: accept
with fixes. Disposition:

| # | Finding | Landed in |
|---|---|---|
| 1 | OWNER-DECIDED rows cited an unfiled chat instruction | section 4.1 records the direction verbatim; rows cite it |
| 2 | evidence collection and required details had no requirement | `002` REQ-029, REQ-030; POL-18; `004` J-04, J-12 |
| 3 | TEST-S1-15 had two conditional outcomes | split: TEST-S1-15 (completeness) and TEST-S1-21 (enforcement chosen by ADR-14 before S1-T3) |
| 4 | ADR decisions gating S1 had no bead | bead S1-D (section 7) |
| 5 | S1-T7 depended on the wrong task | now depends on S1-T4 |
| 6 | "refusal record" undefined | removed: refused confirmations are logged (redacted), not written to history |
| 7 | no database-failure case for confirmation | TEST-S1-05 extended |
| 8 | open-stage set and count wrong | `004` section 2 lists the open set |
| 9 | J-02 terminal branch not reachable in S1 | marked "from P5" in `004` J-02 |
| 10 | identity disputes missing | POL-19; `004` J-02 |
| 11 | thin template fields in J-09, J-10, J-12, J-15; envelope expiry | filled in `004` |
| 12 | NDA-first stated as fact | hedged in section 3 and `004` J-11 |
| 13 | verification labels overstated | scoped in `006`, `008` section 5.1, `003` ADR-17, `005` S1.6 |
| 14 | review record unsupported | this section |
| 15 | S1 form fields under a later milestone | POL-03 |
| 16 | README promised Twenty | README corrected |
| notes | later planned tests missing from the matrix | `002` section 7 |

The reviewer also noted that the live route table merged in PR #5 published operational detail; the
owner later directed its removal (amendment item 5 below). **Re-review** of the fixes at commit `9cdce56` by the same reviewer: accept with fixes, nothing blocking.
Findings 1 to 13 and 15 to 16 resolved. Finding 14 was partially resolved: the full reports are
summarized on the pull request, not filed in the repository. A label residual on finding 13 and five
new small problems were fixed in the third commit, and the reviewer then checked those edits (pull
request comment):

| New problem | Landed in |
|---|---|
| POL-18 and POL-19 missing from phase dependencies and GATE-PILOT | section 7 (P2, P4); `002` section 6 |
| J-12 cited POL-07 for required details | `004` J-12 now cites POL-18 |
| this section claimed a re-review before it ran | this paragraph |
| J-02 terminal-stage rule had no test | `004` J-02 and `002` REQ-018 name planned TEST-P5-06 |
| version not bumped; README stated the agreement order as fact | header; README |
| `006` labelled the parent-permission point VERIFIED | `006` relabelled |

**Owner-directed amendment (2026-10-09)** to the reviewed head `d0c632a`:

| # | Item | Disposition |
|---|---|---|
| 1 | NDA gate | restored as D-15 and REQ-031; `004` J-11 and J-12; planned TEST-P4-06. This reverses the QA disposition of finding 12 above, which had wrongly made the order open; only the inventory details stay open (POL-07) |
| 2 | Replies and question status | `004` J-07 rewritten (persist and correlate, then process); J-08 reminder suppression; J-09 staff messages while paused; REQ-013 and REQ-034; `005` S1.4 rule 8; planned TEST-P2-08 to TEST-P2-11 |
| 3 | Signing versus custody | `004` "Agreement facts", J-11 to J-14; REQ-011 and REQ-032; `003` ADR-05 and trust boundary (webhook authentication per installed version); planned TEST-P4-07 and TEST-P4-08 |
| 4 | Submission versions and verification | `004` J-03 and J-05; REQ-007 and REQ-033; `005` S1.2, S1.4 (`VersionAdoption`); TEST-S1-08 extended, TEST-S1-22 added; planned TEST-P3-08 |
| 5 | Public route detail | `003` "Current routing" reduced to a summary; the authoritative baseline stays in the live proxy configuration and private operations records; Git history not rewritten |
| 6 | Delivery handoffs | section 7 maps P-phases to numbered A/B/C handoffs; the next handoff at the time of the amendment was 1A (since delivered: `012`) |
| 7 | Decisions before implementation | `003` ADR-03, ADR-14, ADR-17 and ADR-18 marked PENDING OWNER DECISION; `005` S1.6a defines what S1-T1 returns; beads S1-T1 and S1-D updated |

Independent review of the amended clauses (fresh `catalyst-independent-qa` invocation, commit `a264b97`):
**accept with fixes**, nothing blocking. Items 1, 2, 3 and 7 satisfied; 4, 5 and 6 partial. The six
should-fix findings were applied in the next commit: the pause exemption for staff-class kinds in ledger
rule 1; resume reschedules instead of dropping reminders (`004` J-09); `PendingAction` gains an input
reference; S1 staff items are defined as `needs_staff_attention` events, raised at confirmation for newer
unverified versions, with a refusal case for a foreign or unknown version (TEST-S1-09); stale route-table
references removed from `003`, this section and `009` P5; the P0 handoff sentence and the section 2 label
corrected. Notes applied: hedged webhook wording in `003`, D-15 in section 4.1's heading, S1-D blocking
S1-T2 stated consistently, the `workflow` row described as the ADR-03 mechanism, "ordinary code" in
`005` S1.4. The reviewer's check of those edits is recorded on the pull request.

## 10. Approval record

**Owner approval, 2026-10-09**, of PR #7 at revision `e8a7a4c6ae39062f9b3bdbebbffb2dce5072be60`,
recorded verbatim:

> "I approve the amended build contract and first-slice scope represented by PR #7 at
> e8a7a4c6ae39062f9b3bdbebbffb2dce5072be60. This approves the project direction, the amended
> requirements, and the bounded synthetic first-slice scope. It does NOT approve the four pending ADRs,
> the 19 unresolved policies, application implementation, provider writes, deployment, or a release."

| In scope of the approval | Not approved by it |
|---|---|
| D-01 to D-15 and the project direction (section 4) | ADR-03, ADR-14, ADR-17, ADR-18 (pending; bead S1-D) |
| the amended requirements REQ-001 to REQ-034 (`002`) | POL-01 to POL-19 (open at their milestone gates, section 6) |
| the bounded synthetic first slice S1 and its acceptance plan (`005` S1) | any application code, migration or 1B work |
| the phase and A/B/C handoff structure (section 7), starting handoff 1A only | provider writes, deployment, staging, release |

Approving the contract does not turn planned tests into run tests: all 22 `TEST-S1-` cases remain
NOT RUN. Items labelled PROPOSED in other sections remain proposals unless they are listed in the left
column. Changes after `e8a7a4c` and before the merge: this approval record, the markdownlint version
pin correction (`009` section 5.1, `CLAUDE.md`, `008` section 4.1) and the residual-risk note below; no
requirement or scope changed.

**Residual risk recorded by owner instruction:** non-secret routing descriptions removed from `003` in the
amendment remain available in this public repository's Git history. History is not rewritten. This is
not acceptance of credentials, live tokens, applicant data or confidential agreement content; any such
material found would be reported as a separate exposure.

**ADR decisions, 2026-10-10:** ADR-03, ADR-14, ADR-17 and ADR-18 were decided by the owner against the
`012` evidence (D-16 to D-19, section 4.1). The same instruction authorized handoff **1B.1 only**, to start after PR #8 merges (S1-T2:
skeleton, PostgreSQL-only configuration, provider guards, reproducible environment, minimal CI runtime
lane). The 19 policies, provider writes, deployment and release remain unapproved; all 22 `TEST-S1-`
cases remain NOT RUN until their tasks run them.
