# Master Blueprint: Catalyst v2 build contract

| Field | Value |
|---|---|
| Document | `011-PP-PLAN-master-blueprint` (the only master blueprint for this repository) |
| Version | 1.2.0 (current status corrected and the candidate selection-quality contract added, section 11, 2026-10-14; 1.1.0 recorded the ADR decisions of 2026-10-10) |
| Status | **APPROVED IN SCOPE** (section 10): project direction, amended requirements and the bounded synthetic first-slice scope; later owner decisions D-16 to D-47 are recorded in section 4. **Current (2026-10-17):** GATE-S1 (D-26) and GATE-P2 (D-33) signed off for synthetic work; P3 accepted for synthetic work: GATE-P3 signed off 2026-10-17 (D-36); P4 accepted for synthetic work: GATE-P4 signed off 2026-10-18 (D-45). **Not approved:** the open policies of section 6 beyond their recorded synthetic decisions, live model use, real applicant data, provider writes, deployment and release; implementation only as each handoff is released. Items marked PROPOSED stay proposals; section 11 and `019` were approved on 2026-10-14 (D-35). |
| Owner | Jeremy Longshore (product owner and approver) |
| Reviewers | `catalyst-django-architect` (build design), `catalyst-independent-qa` (independent review); results in section 9 |
| Date | 2026-10-09 |
| Classification | Public repository. No applicant data, agreement text, credentials, private paths or private knowledge. |
| Conventions | Intent Blueprint Docs 3.0.0 (stable IDs, evidence status, lifecycle links); doc-filing v4.5 |
| Supersedes | nothing; the earlier planning drafts named in section 2 were not available |

> **Status (2026-10-17): synthetic only.** Application code exists only for released handoffs (P1, P2, and P3
> 3B.1 to 3B.4). Nothing is deployed and no real applicant data is used. An assistant recommendation in this
> document is a proposal, never an owner decision. (Until 2026-10-10 this banner read "PRELIMINARY, subject to
> review", with code limited to the 1B.1 skeleton; history in sections 4 and 10.)

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
| Who owns candidate selection quality, how the selection standard changes, which milestone needs what | this document, section 11; methods and validation in `019` |

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

### 4.1 Recorded owner direction (source of D-01 to D-11 and D-14 to D-44)

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

**P2 decisions, 2026-10-12** (source of D-27 to D-32). The owner reviewed `016` version 0.3.2 at PR #20 head
`70818a6` and decided, in the invoking session (quoted from the owner's authorization):

> "I approve the revised P2 architecture in document `016`, version 0.3.2, with the decisions below. This
> authorizes recording the decisions, merging the documentation PR after normal checks, and proceeding
> with 2B.1 only."
>
> "Approve ADR-15's generalized reconciliation-before-retry contract for non-redeliverable sends,
> preserving D-20 exclusively for the S1 verification invitation." "Internal, idempotent collection and
> reply-processing jobs may retry under their documented recovery rules. External sends with uncertain
> outcomes may not blindly resend."
>
> "Approve architecture decisions A-1 through A-11 exactly as specified in version 0.3.2." A-6: "Do not
> build aggregation unless needed." A-5: "for synthetic testing only." A-4: "Real MXroute remains
> prohibited."
>
> "Approve POL-06 for synthetic P2 sending authority: Owner approves template versions. Authorized
> operators approve applicant-specific questions. Only approved/frozen messages may be executed. No real
> applicant-facing message wording or production cadence is approved."
>
> "Approve POL-13's P2 role matrix in section F for synthetic operation only. Identity-affecting
> resolutions, uncertain-send decisions, and collector restarts require elevated decision-maker
> authorization. Template approval remains owner-controlled."
>
> "Approve POL-19's fail-closed identity-dispute handling: mismatches and unverifiable identity produce
> staff exceptions, not automatic identity or dossier changes."
>
> "Approve document 015 as public-safe technical documentation, with future public PDF renderings using
> appropriate unclassified labeling."
>
> "None of these decisions authorizes real email, applicant-data ingestion, provider credentials,
> deployment, or a production staff-access change."

**GATE-P2 sign-off, 2026-10-13** (source of D-33). The owner reviewed the GATE-P2 closeout, draft PR #27 (code
head `1ce791e`, CI run 38439993244). The closeout report proposed this sign-off statement:

> "I accept GATE-P2 for synthetic P2 at main after PR #27, on CI run evidence GATE-S1 25/25 and GATE-P2 54/54, with the case dispositions and scope boundaries in `016` §10.12. This does not authorize real mail, applicant data, model use, P3, release or deployment. The three correction beads (append-only evidence, automatic-pause review, hard-bounce send block) and POL-10 must close before real use."

The owner replied in the invoking session: "plz contunen o approve" (please continue, I approve). This is
recorded as acceptance of the proposed statement and of the `016` §10.12 dispositions, and as authority to
merge PR #27. It authorizes nothing the statement excludes.

**P3 specification and 3B.1 release, 2026-10-14** (source of D-34). The owner reviewed `018` version 0.2.1 at
draft PR #28 (head `57a3041`, CI run 38453711663) and wrote in the invoking session: "approve 018 and release
3B.1". Asked whether that meant a versioned `/release`, the owner chose "Just start building 3B.1"; asked whether
to move the repository to the owner's personal GitHub account now, the owner chose "Later, not now" (the move is
tracked as a separate task). This is recorded as approval of `018` 0.2.1 with its recommended defaults
`P3-D-1` to `P3-D-16` for synthetic P3, and as the release of 3B.1 only.

**Selection-quality contract, 2026-10-14** (source of D-35). The owner reviewed draft PR #33 (head `003c8d4`, CI
run 38653570269 green; independent review applied) and wrote in the invoking session: "approve 019 and merge 33".
This is recorded as approval of `019` (as version 1.0.0) and of section 11 of this document, which makes their
contents the governing contract for selection quality: the three assessment purposes, the six criteria and
evidence rules as the draft of `SP-L2-1`, the selection-policy record and change rules (merging never activates),
the evaluation process, the scorecard structure, the cadence and corrective actions, and the amendment to P3-D-10
(a recorded human-only assessment when model advice is unavailable or suspended, applied when 3B.4 is built). It
authorizes no code, no release of 3B.3 or 3B.4, no live model call, no real data, and no activation of a
selection policy (none exists yet). Still open, because they need names or inputs the approval does not give: the
domain expert for the role profile, the operational delegate role, the private location for real evaluation
material, the scorecard's minimum counts, and what clears a capped assessment snapshot.

**GATE-P3 sign-off, 2026-10-17** (source of D-36). The owner reviewed the 3C closeout, draft PR #36 (head `069b39c`,
CI run 39002427812: 846 passed; GATE-S1 PASS 25, GATE-P2 PASS 54, GATE-P3 PASS 60), with the proposed statement in
after-action report `020` section 9, and wrote in the invoking session: "approve GATE-P3 and merge 36". This is
recorded as acceptance of that statement, including its limits (a passing case means its mapped tests passed, with
the gaps listed in `020` section 4; not a validation of selection quality), and as authority to merge PR #36. It
authorizes no live model use, real fetching, real applicant data, release or deployment, and records no POL-05
decision: nobody can decide until POL-05 is recorded.

**P4 specification, 2026-10-17** (source of D-37). The owner reviewed `021` version 0.2.0 at draft PR #37 (head
`f93ea4a`, CI run 39030231519 green; the independent security and privacy review applied) and wrote in the invoking
session: "approve 021 and merge 37". This is recorded as approval of `021` 0.2.0 with its recommended defaults
`P4-D-1` to `P4-D-20` for synthetic P4, and as authority to merge PR #37. It does not release 4B.1 (each 4B task needs
its own release), and it does not itself authorize the read-only check of the installed Documenso version that
P4-D-2 recommends "authorized separately". No real Documenso use, agreement text, real data, release or deployment
is authorized.

**Documenso check and 4B.1, 2026-10-17** (source of D-38). The owner wrote in the invoking session: "authorize the
documenso check and release 4B.1". This is recorded as authority for one read-only check of the installed Documenso
(its version and its published API schema, with no credential, no write and no envelope; findings in `021` section
15) and as the release of 4B.1 (`catalyst-v2-hdg.2`) for synthetic work against a local fake Documenso. It does not
authorize any request that uses a provider credential, any envelope, webhook or email from the real installation,
real agreement text or data, release or deployment, and it does not release 4B.2.

**4B.2, 2026-10-17** (source of D-39). After 4B.1 merged (PR #38), the owner wrote in the invoking session: "release
4B.2". This is recorded as the release of 4B.2 (`catalyst-v2-hdg.3`) for synthetic work against the local fake
Documenso. The open 4B.1 items (the draft-orphan handling, the bounded watch, the public version tag) were not
answered, so their recorded defaults stand (`021` sections 15 and 16). It authorizes no real Documenso request,
webhook or email, no public webhook exposure (P6), no agreement text or real data, and not 4B.3, release or
deployment.

**Bounded autonomous build, 2026-10-18** (source of D-40 to D-44). After PR #39 (4B.2), the owner gave a written
instruction in the invoking session titled "CATALYST V2 -- OWNER DECISIONS AND BOUNDED AUTONOMOUS BUILD". It is
summarized here by decision. Its full scope is recorded in D-40.

- **D-40, scope.** The instruction authorizes, for synthetic work only, a finite development batch:
  - **P4 delivery:** merging PR #39 after review; the 4B.2 corrections and tests (`catalyst-v2-hdg.6`); 4B.3
    (`hdg.4`); 4C (`hdg.5`), with the acceptance PR left as a draft for the owner.
  - **Pre-production hardening:** suite profiling (`egz`); `9kg.1` to `.3`; `oyu`; a read-only check of the
    effective GitHub protections; a reconciliation of earlier audit findings.
  - **Preparation only:** the 5A specification, a POL-11 and POL-12 decision brief, and P6 and PL readiness
    planning.
  - **Rules:** merges go only through the merge guard, after independent review and green required checks on the
    exact head.
  - **The GATE-P4 result is not pre-approved.**
  - **Not authorized:**
    - deployment, live providers, real data or agreements;
    - real mailboxes, policy activation, credential use;
    - a versioned release, organization or protection changes;
    - P5 implementation.
- **D-41, Documenso cancellation email.** Accepted for synthetic development only.
  - Upstream `v2.20.0` cancel (`cancel-envelope.ts` calls `cancel-document.ts`, which queues
    `send.document.cancelled.emails`) can email recipients. The handler checks owner and organization eligibility,
    recipient eligibility, quotas and the derived `documentDeleted` setting.
  - Catalyst uses the supported per-envelope suppression: `emailSettings.documentDeleted = false`, on create and on
    distribute.
  - The fake models provider email. Provider-owned email is inventoried separately from Catalyst's.
  - Protective cancellation stays possible while paused or delivery-blocked, with a fixed generic reason and never
    staff notes.
  - Before real provider use: a separately authorized synthetic-recipient canary, or the owner's narrow written
    acceptance of the risk.
- **D-42, agreement hold, cancel and resume** (amends P4-D-20).
  - An explicit agreement hold cancels unfinished live envelopes, including partially signed ones, through
    reconciled actions. An ordinary automation pause does not.
  - The stop intent is durable even while an exchange is in flight: it is recorded first, and the cancel follows
    reconciliation.
  - Verified signing, completed agreements, observations and stored copies are kept.
  - Resume is an explicit decision-maker act after cancellation and review. It reissues only the unfinished
    agreements still needed, as new instances.
  - Withdrawal and closure are not resumable here (POL-12, P5).
- **D-43, agreement integrity.** A verified agreement whose provider recipients later differ gets an
  agreement-integrity hold.
  - The hold is recorded separately from the earlier verified fact.
  - It blocks User Agreement progression and the P5 hand-off until a permissioned resolution, and generic resume
    does not clear it.
  - Continuing needs a fresh matching read. Replacement makes a new agreement generation with prior records kept
    and an explicit change of the eligible instance.
  - The expected recipient is never changed to match the provider's.
  - No software disposition claims to void an agreement. Legal questions stay blocked for the owner and counsel.
- **D-44, carried defaults.**
  - **Late envelopes.** A late draft is kept at the provider, excluded and left with staff. A late pending envelope
    gets a reconciled protective cancel. A late completed envelope is an exception, never verified.
  - **The orphan watch** is bounded but never silently ends. Exhaustion records an unresolved-uncertainty staff
    obligation, with a permissioned, bounded re-arm. Its six checks are a labelled synthetic default, not a
    production horizon.
  - **Cancelled and superseded instances** get bounded follow-up reconciliation.
  - **Protective cleanup** (read-only reconciliation and authorized cancellation) may run while paused or stopped.
    It never issues, distributes, advances or provisions.
  - **The `v2.20.0` reference** stays as dated compatibility evidence.
  - **The same-transaction verification backstop** stays, proven by direct database tests. It is not tamper-proof
    against a compromised privileged role.

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
| D-21 | Test cleanup: the suite runs as the application role; tests that commit use a test-only privileged reset of a test database this run created (no `--reuse-db`; identity-marker check; only the named `catalyst_no_truncate` triggers disabled for the reset, trigger and privilege state re-verified, failure fails the run); no bypass in trigger functions, no replication-role switch | OWNER-DECIDED | section 4.1 (PR #11 closeout); `tests/conftest.py` |
| D-22 | `VersionAdoption` is protected history: no role may update, delete or truncate it; no retention path for adoptions until POL-10; same-application foreign keys unchanged | OWNER-DECIDED | section 4.1 (PR #11 closeout); `003` ADR-14; migration `applications.0003` |
| D-23 | Django Admin in S1-T7: only the session and admin-log grants it needs, and the read-only staff group's permissions, created through an authorized setup or migration path; the runtime application never grants itself staff, superuser or group rights | OWNER-DECIDED | section 4.1 (PR #11 closeout); bead S1-T7 |
| D-24 | Confirmation token contract: the signed challenge `public_id` (ADR-16); the raw `public_id` is not authorization, a valid signature plus the database checks are; the token, signature and link are never shown, exported, logged or stored in events, and no staff action can mint a link | OWNER-DECIDED | section 4.1 (PR #11 closeout); `003` ADR-16; bead S1-T6 |
| D-25 | POL-01 confirmed for the first slice with its PROPOSED defaults (`005` S1.3): the identity key is the trimmed, Unicode-normalized, case-folded email with plus-addressing kept distinct and IDN domains in ASCII form; one open application per key; a repeat becomes a new submission version; a repeat after verification is recorded unverified with a staff item and never overwrites verified data; terminal applications do not count as open. Duplicates around terminal stages (decline, withdrawal, reopening) stay with POL-12 (P5) | OWNER-DECIDED 2026-10-11 | owner, in session after the S1-T8 handoff ("ok please do it", answering the request to sign off GATE-S1 and confirm POL-01) |
| D-26 | GATE-S1 signed off: every TEST-S1 case PASS on PostgreSQL in CI at one head (CI run 38109732065 on `93fc22c`, merged as `3bd31ac`; 315 passed; PASS 25, FAIL 0, INCOMPLETE 0, NOT RUN 0), independent QA review of the evidence (`catalyst-independent-qa`, confirmed), after-action report `014` filed, POL-01 confirmed (D-25). The first-slice epic `catalyst-v2-6hl` closes; deployment gates (`006` Blockers), `catalyst-v2-2xy` and `catalyst-v2-6hl.10` stay open | OWNER-DECIDED 2026-10-11 | owner, same instruction; evidence `013`, `014` |
| D-27 | ADR-15 generalized: every non-redeliverable external send reconciles before any further send (`016` A3 to A6: outcome classes by protocol phase, admissible evidence only, unknown stays unknown and goes to staff). D-20 remains the only redelivery exception (the S1 verification invitation). Internal idempotent jobs (`collect`, `process_reply`) may retry under their documented recovery rules | OWNER-DECIDED 2026-10-12 | section 4.1 (P2 decisions); `003` ADR-15; `016` |
| D-28 | Architecture choices A-1 to A-11 of `016` 0.3.2 approved as specified: questions in `correspondence`; `StaffItem` with immutable `StaffItemResolution`; staff services in `correspondence/staff_actions.py`; isolated local test mail servers with connect-time peer checks (amends REQ-022; real MXroute prohibited); previewed, digest-confirmed staff messages for synthetic testing only; per-message hashed deduplication with no aggregation unless needed; the `due_at` and `fence()` ledger extensions; explicit question withdrawal; sanitized derivatives and metadata only, no persistent original MIME bytes in synthetic P2; explicit bootstrap and recovery modes that never silently skip; immutable `ApprovedMessage` records distinct from attempts | OWNER-DECIDED 2026-10-12 | section 4.1; `016` section 8.5 |
| D-29 | POL-06, synthetic P2 send authority only: the owner approves each template version; authorized operators approve applicant-specific questions; only approved, frozen messages execute. No real applicant-facing wording, production cadence, quiet hours, limits or stop thresholds are approved | OWNER-DECIDED 2026-10-12 (partial) | section 4.1; `016` 8.1 |
| D-30 | POL-13, P2 role matrix (`016` section F) for synthetic operation only: operators handle routine correspondence; identity-affecting resolutions, uncertain-send decisions and collector restarts need the decision-maker role; template approval stays with the owner. MFA, network restriction and production staff access remain undecided | OWNER-DECIDED 2026-10-12 (P2 slice) | section 4.1; `016` F |
| D-31 | POL-19 fail-closed: a mismatched or unverifiable identity produces a staff exception with no automatic positive effect and no identity or dossier change; only the decision-maker resolves identity-affecting cases | OWNER-DECIDED 2026-10-12 | section 4.1; `016` C3, C4, F |
| D-34 | `018` (P3 evidence, assessment and qualification specification) version 0.2.1 approved with its recommended defaults `P3-D-1` to `P3-D-16` for synthetic P3; 3B.1 (`catalyst-v2-oc4.2`) released. Not authorized: a live model call, real fetching, real applicant data, 3B.2 to 3C (each needs its own release), a versioned release or a deployment. The decisions marked for GATE-PILOT or later (real fetching, the applicant notice, retention, live model use) stay conditions at those gates | OWNER-DECIDED 2026-10-14 | section 4.1; `018` section 8 |
| D-47 | P5 decisions P5-D-1 to P5-D-11 for synthetic work, and the release of the amended 5A and 5B.1 to 5B.3 (`023` 0.2.0 section 8). Summary: one configured domain with staff-confirmed `firstname.lastname` and a numeric suffix, `example.test` only now; 1024 MB and 100 messages a day as labelled synthetic defaults, never unlimited or quota-0; the owner approves, delegates only by named grant; API-first against a local fake with a recorded checklist fallback, one adapter, no account-wide key in web or routine worker settings; verification by an authoritative mailbox read or a different named verifier, SMTP acceptance never proof, unknown accounts are conflicts; credentials by a one-time set-your-own-password flow (option a), option (b) only by separate approval; company mailbox only; explicit verified withdrawal (GET shows, POST commits); revoke without deleting, outcomes tracked separately, unsupported checks stay unresolved, never a whole-account suspend; no generic reopening; no automatic no-response closure. Not authorized: live MXroute or Documenso access, provider keys, real data, real mailboxes or passwords, real role grants, deployment, release; 5C and GATE-P5 stay with the owner | OWNER-DECIDED 2026-10-18 | owner directive after D-45; `023` sections 3 and 8 |
| D-46 | Two carried P4 answers. (1) Agreement causes: the explicitly designated correspondence decision-maker may resolve routine declined, expired or cancelled agreement causes with a reason and the existing permitted remedy (`agreement_decided`, 9kg.2). It grants no blanket document access, no identity-change authority and no automatic readmission. It does not bypass a separate integrity or delivery block or a provider fact. Legal disputes escalate to the owner and counsel. (2) Required details: the same qualified person may record and confirm a details version when holding both permissions, as two separate audited actions on the exact version. This does not replace any required applicant adoption, signature or consent (amends POL-18 for synthetic work; the production field list stays open) | OWNER-DECIDED 2026-10-18 | owner directive after D-45; `021` section 18 |
| D-45 | GATE-P4 signed off for synthetic P4: every TEST-P4 case and the eight supporting groups (D-41 to D-44, 9kg.1 to 9kg.3, the removed-gate controls) PASS on PostgreSQL in CI at one head (CI run 39103156421 on `f11ca36`; 1000 passed; GATE-P4 PASS 40, GATE-P3 PASS 60, GATE-P2 PASS 54, GATE-S1 PASS 25; FAIL 0, INCOMPLETE 0, NOT RUN 0), the final independent QA and security reviews, after-action report `022` filed with its limits (section 4) and its proposed statement (section 9). Not a live-provider proof. Not authorized: real templates, real signing, real applicant data, provider credentials, provisioning, release, deployment. The four production limits stay carried and are not accepted for real use (pause row without a database guard, plaintext custody, no erasure path, webhook shared secret without a production secret path) | OWNER-DECIDED 2026-10-18 | owner, in session ("approve GATE-P4 and merge 47"); `022` |
| D-44 | Carried defaults. Late envelopes: a draft is kept and excluded; a pending one is cancelled; a completed one is an exception. The bounded orphan watch ends visibly, with a bounded re-arm. Closed instances get a bounded follow-up. Protective reads and cancels run while paused. The v2.20.0 reference stays as dated evidence. The verification backstop is kept and is not tamper-proof | OWNER-DECIDED 2026-10-18 | section 4.1; `021` section 17 |
| D-43 | Agreement integrity: a separate hold, recorded apart from verified history, blocks progression and P5 until a permissioned, reasoned, state-bound resolution (continue on a fresh matching read, replace as a new generation, or escalate) | OWNER-DECIDED 2026-10-18 | section 4.1; `021` section 17 |
| D-42 | Agreement hold, cancel and resume (amends P4-D-20): the stop intent is durable while an exchange is in flight; resume is a decision-maker act that reissues only unfinished agreements as new instances; withdrawal and closure are not resumable here | OWNER-DECIDED 2026-10-18 | section 4.1; `021` section 17 |
| D-41 | Documenso cancellation email: accepted for synthetic development only; per-envelope `documentDeleted` suppression; a generic reason; a canary or a narrow owner acceptance before real use | OWNER-DECIDED 2026-10-18 | section 4.1; `021` section 17 |
| D-40 | Bounded autonomous build: the P4 close-out (#39, hdg.6, 4B.3, 4C with the acceptance PR left for the owner), egz, 9kg.1 to .3, oyu, a read-only protection check, audit reconciliation, and 5A/P6/PL preparation. Not authorized: deployment, live providers, real data, policy activation, a versioned release, P5 implementation; the GATE-P4 result is not pre-approved | OWNER-DECIDED 2026-10-18 | section 4.1 |
| D-39 | 4B.2 released for synthetic work against the local fake Documenso: webhooks as hints, observations, the sweep, database-visible completion verification, the D-15 sequence, decline, expiry, cancel at the provider, withdrawal during agreements. Not authorized: real Documenso use, public webhook exposure, agreement text, real data, 4B.3, release, deployment | OWNER-DECIDED 2026-10-17 | section 4.1; `021` section 16 |
| D-38 | The read-only check of the installed Documenso (version and published API schema; no credential, write or envelope) authorized and done (`021` section 15); 4B.1 released for synthetic work against a local fake Documenso. Not authorized: credentialed provider requests, real envelopes, webhooks or email, agreement text, real data, 4B.2, release, deployment | OWNER-DECIDED 2026-10-17 | section 4.1; `021` section 15 |
| D-37 | `021` (P4 agreements specification) version 0.2.0 approved with its recommended defaults `P4-D-1` to `P4-D-20` for synthetic P4 (a local fake Documenso, synthetic placeholder PDFs). Not authorized: 4B.1 to 4C (each needs its own release), the read-only Documenso version check (P4-D-2, separately), real Documenso use, agreement text, real data, release, deployment | OWNER-DECIDED 2026-10-17 | section 4.1; `021` section 11 |
| D-36 | GATE-P3 signed off for synthetic P3: every TEST-P3 case and the three D-35 groups PASS on PostgreSQL in CI at one head (CI run 39002427812 on `069b39c`; 846 passed; GATE-P3 PASS 60, GATE-P2 PASS 54, GATE-S1 PASS 25; FAIL 0, INCOMPLETE 0, NOT RUN 0), one independent QA review of the closeout, after-action report `020` filed with its limits. Not a validation of selection quality. Not authorized: live model use, real fetching, real data, release, deployment; POL-05 stays open | OWNER-DECIDED 2026-10-17 | section 4.1; `020` |
| D-35 | `019` (candidate selection quality and validation) approved as version 1.0.0 together with section 11: assessment purposes, criteria and evidence rules as the draft of `SP-L2-1`, the selection-policy record and change rules (merging never activates), evaluation, scorecard structure, cadence and corrective actions, and the P3-D-10 amendment (human-only assessment when model advice is unavailable or suspended, for 3B.4). Not authorized: code, the 3B.3 or 3B.4 release, live model use, real data, policy activation. Open: domain expert, operational delegate, private evaluation location, scorecard minimums, capped-snapshot path | OWNER-DECIDED 2026-10-14 | section 4.1; `019` section 13 |
| D-33 | GATE-P2 signed off for synthetic P2: every TEST-P2 case PASS on PostgreSQL in CI at one head (CI run 38439993244 on `1ce791e`; 624 passed; GATE-P2 PASS 54 and GATE-S1 PASS 25, FAIL 0, INCOMPLETE 0, NOT RUN 0), one independent QA review of the closeout, after-action report `017` filed, case dispositions and scope boundaries in `016` §10.12 accepted. The P2 epic `catalyst-v2-7hu` closes. Not authorized: real mail, applicant data, model use, P3, release or deployment. Before real use: the three correction beads (append-only evidence, automatic-pause review, hard-bounce send block) and POL-10 | OWNER-DECIDED 2026-10-13 | section 4.1; `016` 10.12; `017` |
| D-32 | `015` is public technical documentation, provided its content stays public-safe; future public PDF renderings use unclassified labelling, not the theme's "Confidential" footer | OWNER-DECIDED 2026-10-12 | section 4.1; `016` 8.6; `015` errata item 6 |

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
| POL-01 | Applicant identity key and duplicate policy: is "same applicant" the normalized email address; may a person hold more than one open application; what happens after a decline or withdrawal | owner | GATE-S1 acceptance sign-off (the slice encodes a default) | **DECIDED for the slice (D-25, 2026-10-11)**: the `005` S1.3 defaults are confirmed; terminal-stage duplicates (decline, withdrawal, reopening) stay with POL-12 (P5) |
| POL-02 | Verification link lifetime, resend limits, what an expired link offers | owner | GATE-STAGING | PROPOSED default: lifetime is a setting; no number is approved; tests use a short synthetic value |
| POL-03 | Which evidence is required and how it is collected (and from which sources the system may fetch); the final intake form fields | owner | P3 start (evidence); GATE-PILOT (form fields shown to real applicants) | S1 uses a synthetic placeholder field set (name, email, reason) only. **Synthetic P3 defaults approved (D-34: `018` P3-D-1, P3-D-2, P3-D-3)**; real sources and real form fields stay open |
| POL-04 | Assessment rubric, what the model may see, what it may recommend | owner | P3 start (synthetic); before real candidate-impacting use (production rubric) | **Synthetic P3 defaults approved (D-34: P3-D-4 rubric shape without a numeric score, P3-D-5 staff-approved questions, P3-D-6 data-use boundary)**; the five-criterion rubric in code is synthetic. The production standard (role, criteria, evidence rules, versioning) is proposed in `019` and governed by section 11; **open** |
| POL-05 | Qualification authority: who may admit, decline or hold; whether two people are needed; appeal or reconsideration | owner | P3 decision stage (J-10) | Synthetic P3 recommendations P3-D-9 to P3-D-11 approved with `018` (D-34) for 3B.4; the authority setting stays unset until POL-05 itself is recorded; a P3-D-10 amendment is proposed in `019` section 7 |
| POL-06 | Communications policy: approved templates, reminder cadence and maximum, quiet hours, stop rules for autoresponders, bounces and loops, when staff take over | owner | P2 start | slice sends one verification message only, to a local sink. **DECIDED for synthetic P2 send authority only (D-29, 2026-10-12)**; production wording, cadence, quiet hours, limits and stop thresholds stay open |
| POL-07 | Agreement inventory: the exact approved NDA and User Agreement templates and versions, any other required agreements and their order after the NDA (the NDA-before-User-Agreement rule itself is decided, D-15) | owner with counsel | P4 start | not in slice |
| POL-08 | Signing roles: required participants, signing order, countersigner | owner with counsel | P4 start | not in slice |
| POL-09 | Document custody and its gate: where signed documents are stored, encryption, who may retrieve them, audit, and whether verified custody is required (in addition to verified signing completion) before the next agreement or stage | owner | P4 start | not in slice |
| POL-10 | Retention and deletion for applications, declined and withdrawn records, messages, documents and logs; must cover adopted submission versions together with their adoption records, challenges and audit evidence (D-22) | owner with counsel | GATE-PILOT (no real applicant data before) | synthetic data only; no deletion, retention schedule or retention UI is authorized |
| POL-11 | Provisioning scope: mailbox naming, aliases, any other access granted at activation; who approves | owner | P5 start | not in slice |
| POL-12 | Withdrawal, closure and reopening rules | owner | P5 (J-16); duplicate interaction affects POL-01 | not in slice |
| POL-13 | Staff roles and groups (read-only, operator, decision-maker), MFA package | owner | GATE-STAGING | slice uses one PROPOSED read-only group, local only. **P2 role matrix DECIDED for synthetic operation (D-30, 2026-10-12)**; MFA, network restriction and production access stay open |
| POL-14 | Staff hostname and network access method | owner | GATE-STAGING | not in slice (local only) |
| POL-15 | Legacy data: which live first-generation records move, coexistence period, cutover rules | owner | GATE-CUTOVER | not in slice; separate epic |
| POL-16 | Numerical operating targets for the measures in `002` (`MET-`) | owner | GATE-PILOT | measures defined, no targets |
| POL-17 | Applicant-facing notices (privacy notice, what the applicant is told about automated assessment) | owner with counsel | GATE-PILOT | placeholder synthetic text only |
| POL-18 | Required details: which personal or business details the agreements and provisioning need, when they are collected and who may see them | owner with counsel | P4 start | not in slice |
| POL-19 | Identity disputes: what staff do when a repeat submission, a reply or a signer conflicts with the verified identity, and who resolves it | owner | P2 start (first staff item from an unverified repeat appears in S1 but needs no resolution there) | S1 records the conflict as a staff item only. **DECIDED fail-closed (D-31, 2026-10-12)**: staff exception, no automatic positive effect; decision-maker resolves |

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
| P2 | Run the applicant correspondence loop: outbound policy, inbox correlation, reminders, stop rules and human takeover | `catalyst-v2-7hu` | P1; POL-06, POL-19 (P2 decisions D-27 to D-31 recorded 2026-10-12 for synthetic P2; still open: POL-06 production values, POL-02, POL-10 for messages and POL-13 MFA before any real mail) | GATE-P2 |
| P3 | Collect evidence, run the bounded MiniMax assessment, and record the authorized qualification decision | `catalyst-v2-oc4` | P2; POL-03, POL-04, POL-05 | GATE-P3 |
| P4 | Issue and verify the NDA, User Agreement and other required agreements through Documenso with protected custody | `catalyst-v2-hdg` | P3; POL-07, POL-08, POL-09, POL-18; POL-10 for the provider's copy; a read-only check of the installed Documenso version before 4B.1 (`021` P4-D-2) | GATE-P4 |
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

**Correspondence loop tasks (P2), specified in handoff 2A (`016`).** Handoff 2A is the P2 specification and
the owner's P2 decision brief (`016` section 8); 2B is the four implementation tasks, one PR each, and 2C
is the GATE-P2 verification. The owner approved `016` 0.3.2 and recorded D-27 to D-32 on 2026-10-12,
which unblock 2B.1 (`016` 8.1). The owner released 2B.1 on 2026-10-12 and 2B.2 to 2B.4 and 2C on
2026-10-13; the items in `016` 8.2 not covered by D-27 to D-31 use the synthetic defaults recorded in `016`
section 10, and GATE-P2 sign-off stays the owner's. The 2026-10-13 release was an autonomous build (source quoted in
`016`'s status note); the owner's closeout direction of the same day limits it to P2, so it does not extend to
P3, a release or a deployment (`016` 10.12).

| Key | Bead | Title | Depends on |
|---|---|---|---|
| 2A | `catalyst-v2-7hu.1` | Specify the P2 correspondence design and prepare the owner's P2 decisions | GATE-S1 (D-26) |
| 2B.1 | `catalyst-v2-7hu.2` | Build the outbound communication foundations: versioned templates, a generalized send handler, the uncertain status and SMTP-fake reconciliation | 2A; the owner decisions in `016` section 8.1 (ADR-15 generalization, A-11, A-4, A-1, A-2, A-3, A-7, the POL-13 role matrix, POL-06 send authority) |
| 2B.2 | `catalyst-v2-7hu.3` | Collect inbound mail from the local IMAP test server and correlate it durably with outbound messages | 2B.1; `016` 8.2 (A-9, A-10, trust table, POL-19 default part, A-6) |
| 2B.3 | `catalyst-v2-7hu.4` | Process replies deterministically and route judgment to staff confirmation or a held interpretation action | 2B.2; POL-19 resolution part; the autoresponder rule |
| 2B.4 | `catalyst-v2-7hu.5` | Run reminders and controlled staff intervention: suppression, stop rules, pause and resume, staff messages and exception resolution | 2B.3; POL-06 cadence (synthetic settings); A-5, A-8 |
| 2C | `catalyst-v2-7hu.6` | Verify the correspondence loop: the GATE-P2 acceptance run, independent QA and the after-action report (health and reconciliation behaviour is built in 2B.1 to 2B.4) | 2B.1 to 2B.4 |

**Evidence and assessment tasks (P3), specified in handoff 3A (`018`, approved 0.2.1, D-34).** The owner asked for 3A
after GATE-P2 (D-33). 3A is the specification and the owner's P3 decision brief (`018` section 8, proposals `P3-D-1` to `P3-D-16`). The
owner approved `018` 0.2.1 and released 3B.1 on 2026-10-14 (D-34), then 3B.2 the same day ("release 3B.2");
3B.3 and 3B.4 each need their own release; 3C is the GATE-P3 verification. Live model use and
real fetching are not authorized by any of these. 3B.1 merged as `d564bfa` (PR #30) and 3B.2 as `8086508`
(PR #32); the owner released 3B.3 on 2026-10-16 ("release 3B.3") and 3B.4 on 2026-10-17 ("release 3B.4"), merged as `2bb3281` (PR #34) and `25603b0` (PR #35); 3C was
released the same day ("release 3C"); GATE-P3 was signed off on 2026-10-17 (D-36; after-action report `020`). Selection-quality work (section 11) attaches to 3B.3, 3B.4, 3C and 3E without changing their release or
gate.

| Key | Bead | Title | Depends on |
|---|---|---|---|
| 3A | `catalyst-v2-oc4.1` | Specify the P3 evidence collection and bounded MiniMax assessment, and prepare the owner's P3 decisions | GATE-P2 (D-33) |
| 3B.1 | `catalyst-v2-oc4.2` | Collect versioned applicant claims and deterministic, fixture-backed evidence observations that staff can see, without any model call | 3A approval; `018` P3-D-1, P3-D-2, P3-D-12, P3-D-14 |
| 3B.2 | `catalyst-v2-oc4.3` | Run the bounded assessment over a frozen snapshot with PydanticAI test models, budgets, invocation records and failure routing to staff | 3B.1; P3-D-4, P3-D-6, P3-D-7, P3-D-8 |
| 3B.3 | `catalyst-v2-oc4.4` | Run the clarification loop: model-proposed questions through P2 approval, staff question authoring, coalesced reply interpretation, reassessment | 3B.2; P3-D-5, P3-D-6 |
| 3B.4 | `catalyst-v2-oc4.5` | Record the authorized qualification decision with its exact inputs and hand admitted applicants to P4 as held work | 3B.2; P3-D-9, P3-D-10, P3-D-11, P3-D-16 |
| 3C | `catalyst-v2-oc4.6` | Verify P3: the GATE-P3 acceptance run, one independent QA review and the after-action report | 3B.1 to 3B.4 |
| 3E | `catalyst-v2-oc4.7` | Evaluate MiniMax compatibility and quality on synthetic applications under a stated budget, once separately authorized (not part of GATE-P3) | owner authorization, API entitlement, provider review, P3-D-6; the evaluation set `catalyst-v2-f1u.3`; the live-call protections `catalyst-v2-oc4.9` |
| (3B.2 follow-up) | `catalyst-v2-oc4.8` | Decide what clears a capped assessment snapshot and give staff that path without a shell | owner decision; not a GATE-P3 blocker unless the owner says so |
| (3B.2 follow-up) | `catalyst-v2-oc4.9` | Build the live-call protections before any live model call | before any live call, including 3E |

**Agreement tasks (P4), specified in handoff 4A (`021`, approved 0.2.0, D-37).** The owner released 4A on 2026-10-17 ("release
4A") after GATE-P3 (D-36). 4A is the specification and the owner's P4 decision brief (`021` section 11, proposals
`P4-D-1` to `P4-D-20`); 4B.1 to 4B.3 each need their own release; 4C is the GATE-P4 verification. No real Documenso
use is authorized by any of these. The read-only version check was done and 4B.1 released on 2026-10-17 (D-38).

| Key | Bead | Title | Depends on |
|---|---|---|---|
| 4A | `catalyst-v2-hdg.1` | Specify the P4 agreements lifecycle on Documenso and prepare the owner's P4 decisions | GATE-P3 (D-36) |
| 4B.1 | `catalyst-v2-hdg.2` | Create and distribute agreement envelopes against a local fake Documenso without ever creating two | 4A approval; P4-D-1 to P4-D-4, P4-D-8, P4-D-13; the read-only version check |
| 4B.2 | `catalyst-v2-hdg.3` | Verify signing completion by a fresh read, enforce NDA before User Agreement, and handle webhooks as hints | 4B.1; P4-D-5, P4-D-9, P4-D-10 |
| 4B.3 | `catalyst-v2-hdg.4` | Keep signed documents in audited custody, collect required details, and hand completed applicants to P5 | 4B.2; P4-D-6, P4-D-7, P4-D-11 |
| 4C | `catalyst-v2-hdg.5` | Verify P4: the GATE-P4 acceptance run, one independent QA review and the after-action report | 4B.1 to 4B.3 |

**Candidate selection-quality tasks (section 11, approved D-35).** Epic `catalyst-v2-f1u`, "Improve candidate selection
through a versioned standard, a small evaluation and operational feedback". It does not block GATE-P3.

| Bead | Title | Depends on | Earliest gate |
|---|---|---|---|
| `catalyst-v2-f1u.1` | Specify the candidate selection-quality contract and amend the blueprint, PRD, P3 specification and status | none | owner review of `019` |
| `catalyst-v2-f1u.2` | Complete the supervised-delivery role profile and behavioural criteria with a domain expert as draft selection policy SP-L2-1 | `f1u.1` | before real use |
| `catalyst-v2-f1u.3` | Write the versioned synthetic evaluation set with separate development and held-out cases | `f1u.2` | 3E |
| `catalyst-v2-f1u.4` | Approve a private location with access and retention rules for real evaluation material | `catalyst-v2-211.7` (the policy-decisions bead, where POL-10 is tracked; the coarse coupling is intentional until POL-10 has its own bead) | before any real case review |
| `catalyst-v2-f1u.5` | Define candidate notices, alternative evidence routes, the correction path and reviewer preparation | `f1u.2` | GATE-PILOT |
| `catalyst-v2-f1u.6` | Approve and activate the first selection policy SP-L2-1 on its evaluation evidence | `f1u.2`, `f1u.3`, `f1u.4`, `f1u.5`, `catalyst-v2-oc4.7` (and through it `oc4.9`), `catalyst-v2-9kg.1` to `.3` | before real use |
| `catalyst-v2-f1u.7` | Build the selection-quality scorecard and the one-page owner report from existing records | `f1u.6` | pilot (P6) |
| `catalyst-v2-f1u.8` | Validate selection against delivery outcomes after the pilot | `f1u.7` | after pilot |

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

## 11. Candidate selection quality

**Status: APPROVED 2026-10-14 (D-35)** for the governing contract; it authorizes no code, release, live use, real
data or policy activation (section 4.1). Items still open are listed in D-35. Methods, criteria, the evaluation protocol and the scorecard live in `019`; this
section holds only authority, lifecycle and phase mapping.

**Purpose.** The standard by which people are selected must improve through evidence, controlled revisions and
operational feedback, never through ad hoc prompt changes. A model's reading is advice to a human (D-04); this
section governs the standard that both the human and the model apply.

**What is approved today and what is not:**

| Item | Status |
|---|---|
| Advisory model, human decision, no numeric score, staff-approved questions, no decision without an assessment | APPROVED DIRECTION for synthetic P3 (D-04, D-34: P3-D-4, P3-D-5, P3-D-10) |
| The five-criterion rubric and prompt pack in code | IMPLEMENTED (3B.2), synthetic only; not a production standard |
| The role being selected for, the criteria and evidence rules for real candidates, the selection-policy record, the evaluation process, the scorecard, the review cadence | APPROVED as the governing contract (D-35, `019` sections 3 to 12); the role profile itself and `SP-L2-1` are drafts until completed and activated |
| Whether any assessment predicts delivery quality | UNRESOLVED until after a pilot |

**Ownership.** The owner approves every selection policy version and its activation. A named
operational delegate role prepares reviews and carries out suspensions and rollbacks under a standing authorization
the owner records in advance in section 4, naming the triggers it covers (`019` section 10). Coding agents and hooks have no authority over the standard or the live workflow
(D-10).

**Lifecycle of a selection policy.** A selection policy (`SP-<role>-<n>`, `019` section 6) is drafted,
evaluated against the current version (`019` section 8), reviewed, approved by the owner, and then **activated by
a separate recorded owner act with an effective date** (a decision row in section 4); merging a document or code change never activates it. It
can be suspended (model advice off; human-only review under the amended P3-D-10, D-35; never automatic rejection) or rolled back. Historical
assessments and decisions keep the versions they used; nothing is silently rescored.

**Change authority.** A material change (`019` section 6: role, criteria, evidence rules, exercises,
decision authority, model or provider, prompt pack or rubric, evidence source or derivation, notices) needs a
stated reason, affected uses, an evaluation comparison, a reviewer, owner approval, an effective date and a
rollback procedure. Non-material changes (wording that `019`'s change rules exclude) follow the ordinary PR path.

**Phase mapping (no new P-phase).** Each addition sits at its earliest milestone; synthetic P3 is never
blocked on real-world outcome data, and production policy is never inferred from synthetic defaults:

| Milestone | Selection-quality addition | Proves |
|---|---|---|
| 3B.3 | clarification tied to evidence gaps, alternative evidence routes, candidate-safe questions, staff usability | software behaviour |
| 3B.4 | the decision records per-criterion rationale, the snapshot digest and the policy identifier; human-only assessment under the amended P3-D-10 (D-35) | software behaviour |
| 3C (GATE-P3) | software, permissions, provenance and workflow | not selection quality |
| 3E | synthetic evaluation against human-reviewed examples and a non-model baseline | evidence, not predictive validity |
| Before real candidate-impacting use | approved role profile and `SP-L2-1`, data-use boundary, notices and alternatives (POL-17), reviewer preparation, legal review where counsel names it, live-call protections, correction beads, POL-10 | GATE-PILOT conditions |
| Pilot (P6) | the scorecard and the review cadence | operating records |
| After pilot | outcome validation and reviewed improvements as new policy versions | outcome review |

Task state lives in Beads under the epic "Improve candidate selection through a versioned standard, a small
evaluation and operational feedback", which does not block GATE-P3.
