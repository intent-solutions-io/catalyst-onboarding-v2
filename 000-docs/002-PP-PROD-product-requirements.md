# Product Requirements: Catalyst v2 onboarding

| Field | Value |
|---|---|
| Document | `002-PP-PROD-product-requirements` (the only PRD for this repository) |
| Version | 0.2.0 (replaces the seeded template 0.1.0) |
| Status | **PROPOSED.** Requirements become binding when the owner approves this document in a merged PR. |
| Owner | Jeremy Longshore |
| Date | 2026-10-09 |
| Hub | `011-PP-PLAN-master-blueprint.md` (decisions, authority, open policies, work graph) |
| Classification | Public repository; synthetic examples only |

> **Status: PRELIMINARY, subject to review.** Nothing here is implemented. A planned test is not a
> passing test. Status labels follow `011` section 1.

## 1. Objectives

| ID | Objective | Status |
|---|---|---|
| OBJ-01 | Every person who asks for access gets one recorded, auditable path from first accepted contact to activation, decline or withdrawal. | PROPOSED (derived from the owner's journey, charter `007` section 2) |
| OBJ-02 | Routine onboarding work (acknowledgement, verification, reminders, status checks) runs without a person or a coding agent pushing it along. | PROPOSED |
| OBJ-03 | Authorized staff can see what is happening and resolve every permitted exception in a Django interface. | OWNER-DECIDED in direction (`011` D-07) |
| OBJ-04 | No applicant progresses through an unmet legal, signing or approval prerequisite. | PROPOSED (mandatory invariant) |
| OBJ-05 | Protected information never reaches the public repository, public bead history, CI logs or public assets. | OWNER-DECIDED (`011` D-13; `009` section 3) |

## 2. Users

| Role | Needs | Notes |
|---|---|---|
| Applicant | request access, prove email control, answer questions, sign agreements, receive access | public, unauthenticated until verified; never sees internal assessment |
| Staff reader | see applications, history and pending work | first slice provides only this role (POL-13) |
| Staff operator | pause and resume automation, answer correspondence, resolve exceptions | P2 onward; group defined by POL-13 |
| Decision-maker | admit, decline or hold | authority undecided (POL-05); fail-closed until decided |
| Owner | approves policies, deployments, staff accounts | `011` section 5 |

## 3. Scope

**MVP (all of `004` journey stages J-01 to J-16):** intake, duplicates, verification, evidence,
assessment, clarification, correspondence correlation, reminders and stop rules, human takeover,
qualification decision, NDA, User Agreement and other required agreements, document custody,
provisioning, activation, withdrawal and recovery, staff operations.

**Non-goals:**

- Replacing or migrating the learning site (LMS); only assigned onboarding paths route to Django (`011` D-09).
- Twenty CRM integration (deferred, `011` D-08).
- A second workflow engine, Temporal, or an external queue service (`011` D-03).
- Automated admission or decline by a model (`011` D-04).
- Writing agreement text, choosing legal terms, or deciding retention law (owner and counsel).
- Porting first-generation code or architecture (`011` D-11).
- Bulk import of legacy records in the MVP build phases (separate plan, epic PL).

## 4. Requirements

Priority: MUST (release-blocking), SHOULD, COULD. "Invariant" marks a safety property that may not be
waived by schedule. Component names refer to `003` section "Component design".

| ID | Requirement | Priority | Component / decision | Status |
|---|---|---|---|---|
| REQ-001 | From the first accepted submission, one application record holds a progressive dossier: every submission version, contact verification, evidence item, assessment, question, message, decision, agreement event, provisioning step and staff action is linked to it. | MUST, invariant | `applications`; ADR-14 | PROPOSED |
| REQ-002 | Submission versions are immutable; a correction or repeat submission creates a new version. History events are append-only. | MUST, invariant | `applications`; ADR-14 | PROPOSED |
| REQ-003 | Accepting a submission commits the application (or the existing one it attaches to), the submission version, the history event and the next pending action in one PostgreSQL transaction, or commits none of them. | MUST, invariant | `applications`, `workflow`; ADR-03, ADR-13 | PROPOSED |
| REQ-004 | Every pending system action is a durable PostgreSQL record that survives process crashes and restarts and is resumed by a worker without human help. | MUST, invariant | `workflow`; ADR-03 | PROPOSED |
| REQ-005 | Every external operation (send, sign request, provision) carries an idempotency key; an uncertain outcome is reconciled against the provider where the provider allows it, and is otherwise surfaced to staff instead of blindly retried. | MUST, invariant | `workflow`; ADR-15 | PROPOSED |
| REQ-006 | Duplicate and concurrent submissions never create a second open application for the same applicant identity or duplicate next-stage work. | MUST, invariant | `applications`; POL-01 | PROPOSED; policy NEEDS OWNER DECISION |
| REQ-007 | Contact control is recorded only after an explicit confirmation (a POST, not a link prefetch) of a valid, unexpired, unused challenge, and only once. Confirmation proves control of the address only, not authorship of every submission made with it. | MUST, invariant | `applications`; ADR-16; POL-02 | PROPOSED |
| REQ-008 | No stage transition happens unless its prerequisites hold (verification, required evidence, an authorized decision, every required signature, approval). Transitions happen only through service functions that check prerequisites inside the transaction. | MUST, invariant | `applications`; ADR-13 | PROPOSED |
| REQ-009 | MiniMax assessments run through PydanticAI with typed output that references evidence; output is advisory; a model failure, timeout or malformed output is retried within a bound and then queued for staff, never treated as a decision. | MUST | `assessments`; D-04 | OWNER-DECIDED (layer); details PROPOSED |
| REQ-010 | Admission, decline and hold are recorded only by a human with the authority defined in POL-05, with the actor, time and reason in history. Until POL-05 is decided, the system refuses to record them. | MUST, invariant | `applications`, staff views; POL-05 | NEEDS OWNER DECISION |
| REQ-011 | Signing completion is recorded as verified only when Documenso reports every required participant complete and a fresh provider read confirms it at the moment of use; the system records these provider facts and does not infer legal execution. Webhook requests are authenticated with the installed Documenso version's documented mechanism. | MUST, invariant | `agreements`; D-05; POL-07, POL-08 | PROPOSED |
| REQ-012 | Routine correspondence is automated under written policy; inbound replies are correlated deterministically (no model); autoresponders, bounces, loops, opt-outs and reminder limits stop automation and escalate to staff. | MUST | `correspondence`; D-06; POL-06 | PROPOSED; policy NEEDS OWNER DECISION |
| REQ-013 | Authorized staff can pause automation for one application; no automated action runs for it until staff resume it. An explicitly authorized staff-authored message can still be sent while paused, without resuming or triggering any automated action. | MUST | `workflow`, staff views | PROPOSED |
| REQ-014 | For every application, authorized staff can see the current stage, who owes the next action, the full history, and pending, failed and uncertain actions, and can resolve permitted exceptions through Django admin or focused views with an audit record, without SSH, database edits or a coding agent. | MUST | staff views; D-07 | PROPOSED |
| REQ-015 | Staff access uses individual accounts, groups with least privilege, MFA where supported, and a separate restricted host; anonymous and unauthorized users are refused. | MUST | staff views; D-12; POL-13, POL-14 | OWNER-DECIDED (design); details NEEDS VERIFICATION |
| REQ-016 | Mailbox provisioning runs only after every prerequisite holds and an authorized approval exists, within the approved scope, idempotently. | MUST, invariant | `provisioning`; D-06; POL-11 | NEEDS OWNER DECISION (scope) |
| REQ-017 | Activation (welcome) is sent only after provisioning is verified, not merely requested. | MUST | `provisioning` | PROPOSED |
| REQ-018 | An applicant can withdraw; staff can close; reopening follows POL-12; history is retained under POL-10. | MUST | `applications`; POL-10, POL-12 | NEEDS OWNER DECISION |
| REQ-019 | No applicant data, agreement text, credentials, private paths or private knowledge in the repository, bead history, CI logs or public static assets. | MUST, invariant | all; `009` section 3 | OWNER-DECIDED |
| REQ-020 | Logs never contain tokens, full email bodies or applicant personal data beyond internal identifiers; token-bearing query strings are redacted at the proxy and in Django. | MUST, invariant | all; `003` security model | PROPOSED |
| REQ-021 | Every environment that runs tests, staging or production uses PostgreSQL; the application refuses to start on any other database engine. | MUST, invariant | settings; D-02 | OWNER-DECIDED |
| REQ-022 | Non-production environments cannot reach real providers (MXroute, Documenso, MiniMax, Twenty); settings refuse provider credentials and non-sink mail hosts outside production. | MUST, invariant | settings; D-10 | PROPOSED |
| REQ-023 | No development hook, CI job or coding agent operates the live applicant workflow. | MUST, invariant | `009` section 6; D-10 | OWNER-DECIDED |
| REQ-024 | No live first-generation record is discarded; a separate approved compatibility plan precedes cutover. | MUST, invariant | epic PL; D-14; POL-15 | OWNER-DECIDED (principle) |
| REQ-025 | Production data has backups and a demonstrated restore before real applicants use the system. | MUST | operations; P6 | PROPOSED |
| REQ-026 | Only assigned onboarding paths route to Django; the LMS default route is unchanged; the cutover is reversible. | MUST | proxy; D-09 | OWNER-DECIDED (principle) |
| REQ-027 | The public form has abuse controls: rate limits, body-size limits, CSRF, no account enumeration (the same response whether or not the email is known). | MUST | `applications`; `003` security model | PROPOSED |
| REQ-028 | Retention and deletion follow the approved policy and are enforced by a job, with an audit record. | MUST before pilot | `workflow`; POL-10 | NEEDS OWNER DECISION |
| REQ-029 | Evidence is collected only from sources POL-03 allows; outbound fetches are restricted to approved hosts, never private or link-local addresses, with size and time limits; fetched content is stored as untrusted data with its source and checksum. | MUST, invariant | `assessments`; POL-03 | PROPOSED; sources NEEDS OWNER DECISION |
| REQ-030 | Details the agreements or provisioning require are collected from the verified applicant in a recorded submission before the agreement or step that needs them, and are visible only to the staff roles POL-18 names. | MUST | `applications`, `agreements`; POL-18 | NEEDS OWNER DECISION |
| REQ-031 | **Owner requirement (D-15):** verified signing completion of the required NDA precedes any exposure or issuance of the User Agreement (no text, link or envelope before it). | MUST, invariant | `agreements`; D-15 | OWNER-DECIDED; inventory, templates, participants and countersigning NEEDS OWNER DECISION (POL-07, POL-08) |
| REQ-032 | Custody is a separate fact from signing completion, with its own status, evidence and recovery. A custody failure never downgrades signing completion, triggers re-signing or issues another agreement. Progression requires custody as well only where the approved gate policy says so. | MUST, invariant | `agreements`; POL-09 | PROPOSED; gate policy NEEDS OWNER DECISION |
| REQ-033 | Every submission version keeps its origin and trust status (`unverified`, `adopted`). Only a version the verified address owner explicitly confirms is adopted. Every assessment and later decision names its exact input versions; none uses "the latest answers". | MUST, invariant | `applications`, `assessments`; ADR-14 | PROPOSED |
| REQ-034 | A received reply is persisted and correlated before it is interpreted. Receiving it never by itself marks a question answered. Question status changes only after processing (`satisfied`, `partially_answered`, back to `open`). Automated replies satisfy nothing. A relevant reply awaiting processing suppresses reminders without closing the question. | MUST | `correspondence`, `assessments`; POL-04, POL-06 | PROPOSED |

## 5. Operating measures (proposed; no targets)

Measures are derived from the dossier and job tables, so they need no separate instrumentation
store. **No numerical target is set.** A target needs a stated rationale and owner approval (POL-16).
No measured value exists yet.

| ID | Measure | How measured |
|---|---|---|
| MET-01 | Time from accepted submission to verification message accepted by the mail server | history timestamps: submission event to outbound message accepted |
| MET-02 | Share of accepted submissions that complete verification, and time to complete | history events |
| MET-03 | Pending actions past their due time: count and oldest age | pending-action table |
| MET-04 | Action attempts, retries and terminal failures by action kind | pending-action table |
| MET-05 | Applications waiting on staff: count and oldest age, by reason | stage and next-action owner |
| MET-06 | Assessment runs that failed, timed out or returned invalid output | assessment records |
| MET-07 | Time from agreement issue to verified completion | agreement observations |
| MET-08 | Time from first accepted contact to activation, decline or withdrawal | history events |
| MET-09 | Restore time and data loss window in a restore drill | drill record (P6) |
| MET-10 | Model usage (tokens and cost) per application | PydanticAI usage records stored with each run |

## 6. Release gates

A gate passes only on recorded evidence. "Planned" rows are not evidence.

| Gate | Passes when | Approver |
|---|---|---|
| GATE-S1 | every `TEST-S1-` case in `005` S1.7 is PASS on PostgreSQL in CI at the PR head; none SKIPPED or NOT RUN; independent QA review of the evidence; epic after-action report filed; POL-01 default confirmed or replaced | owner (merge through merge guard) |
| GATE-P2 to GATE-P5 | each phase's planned tests (section 7) PASS in CI with provider fakes or non-production providers; phase AAR filed | owner |
| GATE-STAGING | security and privacy review; staff host, network restriction and MFA configured and tested (POL-13, POL-14); provider guards proven; backups configured | owner, separate deployment authorization |
| GATE-PILOT | policies POL-01 to POL-12 and POL-16 to POL-19 decided; retention enforced; restore demonstrated (MET-09 recorded); approved provider canaries pass in isolated staging | owner (and counsel for POL-07, POL-08, POL-10, POL-17) |
| GATE-CUTOVER | epic PL plan approved and executed; route switch and rollback rehearsed against the current route baseline (the live proxy configuration, re-read read-only at P6; `003`); in-flight first-generation cases handled per POL-15 | owner |

## 7. Traceability matrix

Requirement → component or decision → epic or bead → acceptance test → required evidence → gate.
Slice tests are specified in `005` S1.7. Tests outside the slice are **planned** (named for
traceability, not written); their phase refines them at handoff A.

| Requirement | Component / decision | Epic / bead | Acceptance test | Required evidence | Gate |
|---|---|---|---|---|---|
| REQ-001 | `applications`, ADR-14 | P1 S1-T3, S1-T4; extended each phase | TEST-S1-01, TEST-S1-15, TEST-S1-21; planned TEST-P5-04 (full dossier from contact to activation) | CI run on PostgreSQL with test report | GATE-S1; GATE-P5 |
| REQ-002 | `applications`, ADR-14 | P1 S1-T3 | TEST-S1-03, TEST-S1-15, TEST-S1-21 | CI run | GATE-S1 |
| REQ-003 | `applications`, `workflow`, ADR-03, ADR-13 | P1 S1-T4 | TEST-S1-01, TEST-S1-05, TEST-S1-20 | CI run incl. forced-failure cases | GATE-S1 |
| REQ-004 | `workflow`, ADR-03 | P1 S1-T5 | TEST-S1-06, TEST-S1-07, TEST-S1-17, TEST-S1-18, TEST-S1-19 | CI run with worker interruption case | GATE-S1 |
| REQ-005 | `workflow`, ADR-15 | P1 S1-T5; P2, P4, P5 | TEST-S1-07, TEST-S1-17; planned TEST-P2-03 (uncertain send), TEST-P4-03 (duplicate envelope), TEST-P5-02 (uncertain provisioning) | CI runs | GATE-S1; phase gates |
| REQ-006 | `applications`, POL-01 | P1 S1-T4 | TEST-S1-03, TEST-S1-04, TEST-S1-20 | CI run with concurrent transactions on PostgreSQL | GATE-S1 |
| REQ-007 | `applications`, ADR-16 | P1 S1-T6 | TEST-S1-05 (confirmation case), TEST-S1-08, TEST-S1-09, TEST-S1-10, TEST-S1-22 | CI run | GATE-S1 |
| REQ-008 | `applications`, ADR-13 | P1 (verification gate); P3, P4, P5 | TEST-S1-10; planned TEST-P3-04 (no decision without authority), TEST-P4-01 (no next agreement before completion), TEST-P5-01 (no provisioning before prerequisites) | CI runs | GATE-S1; phase gates |
| REQ-009 | `assessments`, D-04 | P3 | planned TEST-P3-01 (typed output), TEST-P3-02 (model failure goes to staff), TEST-P3-03 (prompt-injection evidence), TEST-P3-07 (an answer re-enters assessment once) | CI with PydanticAI test model | GATE-P3 |
| REQ-010 | staff views, POL-05 | P3 | planned TEST-P3-04 | CI run | GATE-P3 |
| REQ-011 | `agreements`, D-05 | P4 | planned TEST-P4-01, TEST-P4-02 (fresh re-read), TEST-P4-08 (webhook authentication per installed version) | CI with Documenso fake; staging canary | GATE-P4; GATE-PILOT |
| REQ-012 | `correspondence`, POL-06 | P2 | planned TEST-P2-01 (reply correlation), TEST-P2-02 (autoresponder and loop stop), TEST-P2-04 (reminder race), TEST-P2-07 (`UIDVALIDITY` change) | CI with local IMAP test server | GATE-P2 |
| REQ-013 | `workflow`, staff views | P1 S1-T5 (worker honours pauses); P2 | TEST-S1-19; planned TEST-P2-05 (pause stops all automated kinds; resume reschedules without a burst), TEST-P2-11 (staff message sent while paused, no automated action runs) | CI run | GATE-P2 |
| REQ-014 | staff views | P1 S1-T7 (read-only); P2 onward | TEST-S1-12; planned TEST-P2-06 (resolve an exception without SSH) | CI run; operator walkthrough record | GATE-S1; GATE-P2 |
| REQ-015 | staff views, D-12 | P1 S1-T7 (authorization only); P6 | TEST-S1-11; planned TEST-P6-01 (MFA and host restriction) | CI run; staging check | GATE-S1; GATE-STAGING |
| REQ-016 | `provisioning`, POL-11 | P5 | planned TEST-P5-01, TEST-P5-02 | CI with MXroute fake; staging canary | GATE-P5; GATE-PILOT |
| REQ-017 | `provisioning` | P5 | planned TEST-P5-03 (welcome only after verified provisioning) | CI run | GATE-P5 |
| REQ-018 | `applications`, POL-12 | P5 | planned TEST-P5-05 (withdrawal stops automation, keeps history), TEST-P5-06 (a repeat after a terminal stage creates no new application until POL-01 and POL-12 allow it) | CI run | GATE-P5 |
| REQ-019 | all | every PR | gitleaks in CI (exists); manual sensitive-content review (`009` section 5.1) | CI log; PR review note | every merge |
| REQ-020 | all | P1 S1-T4, S1-T6 | TEST-S1-16 | CI run | GATE-S1 |
| REQ-021 | settings, D-02 | P1 S1-T2 | TEST-S1-13 | CI run | GATE-S1 |
| REQ-022 | settings | P1 S1-T2 | TEST-S1-14 | CI run | GATE-S1; GATE-STAGING |
| REQ-023 | `009` section 6 | all | review check: no workflow operation from hooks or CI | PR review | every merge |
| REQ-024 | epic PL | PL | planned TEST-PL-01 (reconciliation counts of migrated versus source records) | migration rehearsal record | GATE-CUTOVER |
| REQ-025 | operations | P6 | planned TEST-P6-02 (restore drill) | drill record with MET-09 | GATE-PILOT |
| REQ-026 | proxy, D-09 | P6 | planned TEST-P6-03 (route table versus baseline, rollback rehearsal) | rehearsal record | GATE-CUTOVER |
| REQ-027 | `applications` | P1 S1-T4 (CSRF, size, enumeration); P6 (rate limits at proxy) | TEST-S1-02, TEST-S1-03; planned TEST-P6-04 | CI run; staging check | GATE-S1; GATE-STAGING |
| REQ-028 | `workflow`, POL-10 | P6 | planned TEST-P6-05 | CI run | GATE-PILOT |
| REQ-029 | `assessments`, POL-03 | P3 | planned TEST-P3-05 (disallowed and private hosts refused), TEST-P3-06 (unavailable source path) | CI run | GATE-P3 |
| REQ-030 | `applications`, `agreements`, POL-18 | P4 | planned TEST-P4-05 (an agreement waits for its required details; visibility limited to named roles) | CI run | GATE-P4 |
| REQ-031 | `agreements`, D-15 | P4 | planned TEST-P4-06 (User Agreement neither shown nor issued before NDA signing completion is verified) | CI with Documenso fake | GATE-P4 |
| REQ-032 | `agreements`, POL-09 | P4 | planned TEST-P4-04 (checksum and custody), TEST-P4-07 (custody failure leaves signing verified, issues nothing) | CI with storage fault injection | GATE-P4 |
| REQ-033 | `applications`, `assessments` | P1 S1-T6; P3 | TEST-S1-22; planned TEST-P3-08 (assessment records its explicit input version) | CI run | GATE-S1; GATE-P3 |
| REQ-034 | `correspondence`, `assessments` | P2 | planned TEST-P2-08 (partial answer), TEST-P2-09 (acknowledgement is not an answer), TEST-P2-10 (autoresponder satisfies nothing), TEST-P2-04 (reminder suppressed, not cancelled, while a reply awaits processing) | CI with local IMAP test server | GATE-P2 |

## 8. Dependencies

Existing services: Documenso (installed version NEEDS VERIFICATION), MXroute (provisioning interface
NEEDS VERIFICATION), MiniMax platform (structured-output support NEEDS VERIFICATION, `008` section 8),
the reverse proxy in front of `learn.intentsolutions.io` (route baseline VERIFIED in `003`).
Libraries: see `005` S1.6 for the first slice; later libraries are chosen at each phase's handoff A.
