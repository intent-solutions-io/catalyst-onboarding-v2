# Internal production launch: workflow comparison record and execution plan (handoff PL-A)

| Field | Value |
|---|---|
| Document | `029-PP-PLAN-internal-launch-comparison-and-execution-plan` |
| Version | 0.1.0 (draft for the owner's review) |
| Status | **PROPOSED.** A planning record. Nothing in it is authorized by being written: no deployment, provider call, host access, credential, real-data action, erasure, routing change, release or gate sign-off. Every task below runs only under its own authorization. |
| Owner | Jeremy Longshore |
| Date | 2026-10-23 |
| Direction | "Our pilot will be go live and we dogfood ourselves" (owner, 2026-10-23). Paraphrased from the owner's planning instruction of the same day: the first production deployment, limited to the owner and an explicitly named internal cohort; the production architecture and real controls; only the integrations the launch manifest enables; internal participants' information is real data. |
| Epics | PL `catalyst-v2-dy7` (this plan is `dy7.1`); P6 `catalyst-v2-9kg` (the launch milestone is `9kg.31`); P3 `catalyst-v2-oc4`; policies `catalyst-v2-211.7` |
| Builds on | `011` (the only master blueprint; sections 6, 7 and 11), `002` section 6 (gates), `004` (J-01 to J-16), `016`, `018`, `019`, `021`, `023`, `024`, `026`, `027`, after-action report `028`, the refreshed audit of 2026-10-22 (private review pack; its repository-relevant findings are reproduced here with their evidence) |
| Classification | Public repository. The first-generation service is described by behaviour only: no private paths, hostnames, addresses, identifiers, participant data or agreement text. Its live route table and operational detail stay in the private operations record (`003`, "Learn and Django routing"). |

> **How to read this.** Section 2 pins four baselines. Section 4 is the comparison record, one row per journey
> stage or handoff, with a disposition. Sections 7 and 9 are the launch manifest and the enablement matrix the owner
> approves. Section 13 is the work graph as it exists in Beads. Section 14 is the decision brief. "UNKNOWN" means a
> necessary fact is missing and names the smallest read that settles it. A disagreement between two sources stays
> explicit until resolved under `011` section 5.

## 1. Purpose, scope and what this document is not

- **Purpose.** Compare what the current service does, what the owner approved, what v2 implements and what the
  internal launch will actually enable; turn the verified gaps into a dependency-correct work graph inside the
  existing blueprint and Beads; isolate the few genuine owner decisions.
- **The launch.** One production deployment on the estate host, for an invited internal cohort, with real data and
  production controls. It is not another disposable environment, not open to outside applicants, and not a licence
  to deploy now. Broader enrollment is a later, separate scope decision (`9kg.31.10`).
- **Not a second blueprint and not a task tracker.** `011` stays the master blueprint; task state lives in Beads.
  This document holds the contract, the comparison and the traceability.
- **Selection quality.** Internal dogfooding is an operational exercise. It proves nothing about talent selection
  (`019`), and it must not be used for covert staff appraisal or employment decisions. Participants are told what is
  recorded and what, if anything, is sent to a provider.

## 2. The four baselines

: The four baselines, their revisions and evidence dates.

| Baseline | What it is | Revision or date pinned | Evidence class |
|---|---|---|---|
| B1 Current operations | The first-generation service (a private Flask repository), live in production for real applicants on the shared learning host, plus an interim set of operator-run timers that bridge agreement signing and activation, plus documented manual operator commands | Source read read-only on 2026-10-23 at a pinned local checkout; the checkout's identifier, its distance from the remote and the release the service's own records report as deployed are kept in the private operations record. **The deployed revision is UNKNOWN** until the preflight reads it on the host (`9kg.42`). | Recorded operator knowledge in the estate brain (early October 2026); three narrow legacy-analyst answers (ADR-12, `007`), each separating intended from observed behaviour |
| B2 Approved business contract | `011` (D-01 to D-49), `002` requirements and gates, `004` journeys J-01 to J-16, the policies decided for synthetic work, the NDA-before-User-Agreement rule (D-15), the separation of signing, custody and access (REQ-032, P4-D-6) | `011` 1.2.0 plus D-16 to D-49; this PR records D-50 | Owner decisions |
| B3 Implemented v2 | The Django application at `main` `45f8b93`: routes, services, registered handlers, screens, permissions, persistence and recovery, with 1,353 passing tests and the P6 drills | `45f8b93` (PR #80); CI run 39797287619; drills in `026` section 16 | Tests, drills, source |
| B4 Proposed live internal scope | The launch manifest of section 7: the cohort, the enabled integrations, the real effects, the manual steps and the exclusions | This document, version 0.1.0, for approval at `9kg.31.6` | Proposal |

**Rules applied.** A source path is not proof it is reached or scheduled; a proposed journey is not implemented
behaviour; an implemented feature is not necessarily enabled or demonstrated. Where a later decision supersedes a
stale document banner, the decision governs (for example D-49 over `024`'s "no staging"). Legacy behaviour is
evidence about operations, not policy authority.

### 2.1 What was and was not read for B1

- **Read:** the service's source at the pinned checkout (routes, case state machine, mail kinds, agreement
  lifecycle, mailbox provisioning, review worker, timers, deploy and ops configuration) and its filed design
  documents; the estate brain's recorded decisions and runbooks.
- **Not read, by rule:** any environment, secret, data, state, log or export file; the production host; the
  provider accounts; the private legal texts; the estate ingress source (the live route table); the service's later
  release (which its own records say adds an explicit confirmation step; not inspected).
- **Consequence:** every B1 statement below is "as of the checkout read, reported deployed state", and the
  missing-evidence register (section 12) lists what the preflight must confirm.

## 3. Plain-English map

**Today (B1).** A person submits the request form on the learning host. The service records the case, emails a
receipt and tells the owner. An AI reviewer reads the public links the person supplied and writes a recommendation,
but acts on nothing (shadow mode). The owner approves from a command; the service creates the NDA envelope in
Documenso and emails the signing link itself. When the NDA is observed complete, the User Agreement envelope is
created in the same transaction and its cover email goes out; the applicant types legal details into the agreement.
An operator-run countersignature step outside the service signs for the company; a separate archiving component
keeps the sealed documents, and the service only reads a small status file. Once the User Agreement is complete and
archived, the service releases the case automatically, creates the company mailbox through the mail host's API,
verifies it, and emails the welcome; its credential-delivery practice differs from v2's. Every case event is
projected into the CRM. Hourly read-only reconciles, frequent monitors, a nightly dump and a periodic restore drill
run on the host. Replies land in one shared mailbox that the service polls; a human reply makes the owner a notice.
Declines are an owner command that sends the applicant nothing. Withdrawal, suspension and offboarding exist as
states but no application path reaches them, and the service's revocation capability is narrower than v2's. Nothing
deletes personal data.

**The internal launch (B4, proposed).** v2 runs on the estate host as its own stack, reached by an invited cohort on
a dedicated host name (owner decision `211.7.3`), with the first-generation service untouched and still owning every
existing case. An invited person applies, confirms their address explicitly, answers staff questions by mail from
v2's own mailbox, is assessed by a person (model advice disabled), is admitted by the decision-maker, signs the NDA
and then the User Agreement in Documenso with v2's own webhook target and custody, and, if the owner decides so, gets
a mailbox through the narrow adapter with a set-your-own-password flow. Every effect is a ledger action with
reconciliation; every wait has an owner, a bound and a staff screen; every exceptional state is handled without a
shell. Backups restore into a held system that replays erasures and reconciles effects before it serves.

```text
B1 today                              B4 internal launch (proposed)
learning host ─┬─ LMS (default)       learning host ─┬─ LMS (default)      unchanged
               └─ v1 entry + setup +                  └─ v1 entry + setup + unchanged, owns every
                  signing return                         signing return      existing case
                                       dedicated v2 host name ──▶ v2 proxy ──▶ v2 web (unix socket)
                                         invitation mode on        │ worker, fetcher (held), egress
                                                                   └─ own mailbox, own webhook target,
                                                                      own custody, own backups
```

## 4. Comparison record

Columns: **Current (B1)** gives intended (docs), observed (code at the pinned checkout) and any manual workaround; **v2 (B3)**
gives the implementation, its executable entry point and its persisted evidence; **Not proven** says what the
existing test or drill does not show; **Launch** is the status in the initial cohort (INCLUDED, DISABLED,
NOT APPLICABLE); **Disposition** is one of PRESERVE, IMPROVE, RETIRE, MANUAL HANDOFF, OUT OF INITIAL SCOPE, VERIFY,
with the affected user, risk, owner and bead. Stage IDs are `004`'s.

### 4.1 Entry, intake and verification (J-01 to J-03)

: Comparison: entry, intake and verification.

| Stage | Current (B1) | Approved target (B2) | v2 (B3) | Not proven | Launch | Disposition |
|---|---|---|---|---|---|---|
| J-01 Intake | Observed: a branded form with CSRF, a signed timestamp token, a honeypot, a per-address rate limit and a one-time "received" page; one transaction creates the case and queues a receipt; the owner gets a notice. Intended and observed agree. | REQ-003, REQ-027, POL-01 (D-25) | `applications/urls.py`, the intake service: one transaction (TEST-S1-01, 05, 20); uniform responses; CSRF and size limits; **no rate limit** (audit 9); no owner notice by design (staff queue instead) | Rate limiting; behaviour behind a real proxy's forwarded headers | INCLUDED, invitation-only | **IMPROVE**: server-side invitation mode (`9kg.43`) and per-endpoint limits with correct proxy identity (`9kg.29`). Affected: applicants, staff. Risk: abuse of the public form and of verification mail. Owner: engineering. The owner notice is a MANUAL HANDOFF to the staff queue (no mail). |
| J-02 Duplicates | Observed: a repeat from the same normalized address inside a short duplicate window becomes a stored revision, flagged if any field differs; no second receipt. Intended agrees. | POL-01 (D-25): one open application per key; repeats become versions; a repeat after verification is unverified with a staff item | TEST-S1-03, 04, 20; concurrent repeats proven on PostgreSQL | A returning internal participant who already holds a first-generation case, a mailbox and signed agreements: v2 cannot see those records | INCLUDED | **PRESERVE** the one-open-application rule; **VERIFY** the cross-system duplicate guard (`dy7.2`): a decision whether an existing-member record is checked by hand before invitation (`211.7.6`). Risk: two systems acting on one person. |
| J-03 Verification | Observed at the checkout: "contact verified" meant the receipt was accepted by SMTP; the applicant did nothing (defect noted by the analyst). The service's later release reportedly adds an explicit confirmation step (UNKNOWN, not read). | REQ-007 (D-24): an explicit POST on a valid, single-use challenge; never a link prefetch | `applications/confirmation.py`; `/confirm/*`; TEST-S1-05, 08, 09, 10, 22; the dark deploy proves the real mail path to a sink (TEST-P6-27) | Delivery through the real mail host (the mail canary `9kg.31.1`) | INCLUDED | **IMPROVE** (a deliberate safe difference): explicit confirmation is required. Risk: none to legacy cases; v2 links never point at the first-generation service. |

### 4.2 Evidence, assessment, clarification and decision (J-04 to J-10)

: Comparison: evidence, assessment, correspondence and decision.

| Stage | Current (B1) | Approved target (B2) | v2 (B3) | Not proven | Launch | Disposition |
|---|---|---|---|---|---|---|
| J-04 Evidence | Observed: the reviewer fetches only links the applicant supplied through an address-pinned, SSRF-guarded transport; a GitHub lookup derived from a link the applicant gave (one bounded summary, never the email field); web search prepared but off. Contact details are scrubbed before any text leaves the process. | REQ-029, POL-03, P3-D-2, P3-D-3 (real fetching at GATE-PILOT with an allow-list) | `assessments/collection.py`, `fetch.py`, the fetcher process and egress proxy (TEST-P3-05, 06; TEST-P6-30); the allow-list is empty in code, so every fetch is refused | Deny of the estate's own public hosts by name (TEST-P6-28); real fetching | DISABLED (allow-list empty; `start_evidence_collection` runs and records "unavailable") | **OUT OF INITIAL SCOPE** for fetching; the IMPROVE items `9kg.39` (deny by name, redirects, resolution changes) land before any allow-list entry. Affected: applicants (missing evidence is never evidence against them, REQ-036). |
| J-05 Assessment | Observed: four bounded model stages on one job queue; typed outputs with validators; a repair budget; staleness checks; shadow mode records recommendations only; the owner gets a notice per resting outcome; intake-stage public data to the model was accepted by the owner with counsel (recorded decision). | REQ-009, D-04, P3-D-4 to P3-D-8, `019` (the P3-D-10 amendment: a recorded human-only assessment when advice is unavailable or suspended) | `assessments/agent.py` (model requests disabled, no live branch), `runs.py`, budgets, invocation records, failure routing (TEST-P3-01, 02, 07); live-call protections not built (`oc4.9`) | The human-only path's policy and snapshot record (`oc4.10` items 1 to 3); a capped snapshot's exit (`oc4.8`) | DISABLED (model off; human-only assessment) | **OUT OF INITIAL SCOPE** for model advice; **VERIFY** and complete the human-only path (`oc4.12`). Note the deliberate difference from B1: v2 sends nothing to a model until `oc4.9`, the data-use approval for v2's fields and the evaluation (`oc4.7`) exist. The owner's earlier data-use acceptance was for the first-generation reviewer's fields and must not be assumed to carry over (decision `211.7.4` asks). |
| J-06 Questions | Observed: a clarification sender existed in design but was unregistered at the checkout (reported restored later; UNKNOWN); pacing limits exist; reminders unbuilt. | REQ-012, REQ-034, P3-D-5 (model questions never sent unapproved) | `correspondence`: approved, frozen messages; staff-authored and model-proposed questions through approval; TEST-P2 cases; GATE-P2 PASS 54 | Real delivery and reply collection (mail canary) | INCLUDED (staff-authored questions only) | **PRESERVE** the owner-approval rule; **IMPROVE**: v2 has the loop the first-generation service lacked. |
| J-07 Inbound | Observed: a 60-second poll of one shared service mailbox with a durable UIDVALIDITY plus UID cursor, deterministic classes, no bodies stored; bridge and existing-member replies land in the same inbox; a human reply emails the owner a notice. | REQ-012, REQ-034, D-27, D-28, D-31 (fail-closed identity) | `correspondence/imap.py`, `inbound.py`, `processing.py`; association and trust; staff exceptions (TEST-P2-01, 07, 12 to 24) | Live inbound health (TEST-P6-18); the real mailbox | INCLUDED, on **v2's own mailbox** | **PRESERVE** durable collection; **RETIRE** the shared mailbox for v2 (M8, P6-D-10): a second poller of the first-generation mailbox would duplicate and race. Decision `211.7.3`. The owner reply notice is a MANUAL HANDOFF (the staff queue shows replies; no owner mail). |
| J-08 Reminders, autoresponders, bounces | Observed: autoresponders and bounces classified; nothing suppresses on a bounce (defect); no reminders. | REQ-012, D-27; `9kg.2`, `9kg.3` (closed): hard bounce blocks every send; system pauses need a decision-maker | `correspondence/reminders.py`, `remind`, `escalate_unanswered`; TEST-P2-02, 04, 10 | Live bounce path (mail canary) | INCLUDED | **IMPROVE** (bounce block and reminders exist in v2 only). |
| J-09 Takeover | Observed: no global pause in the service; flags and kill files on the host; per-case halts in the bridge cleared by hand. | REQ-013, D-30 | `AutomationPause`, `staff_actions.pause/resume`; the pause row protected in code only (`9kg.6` open) | A database guard on the pause row | INCLUDED | **PRESERVE**; **IMPROVE** `9kg.6` before launch. |
| J-10 Decision | Observed: approval is an owner command that also queues the NDA envelope; decline is an owner command that sends nothing and later cancels open envelopes; a model hold is recorded as "recommended" only. Intended agrees (owner keeps every decision). | REQ-010, POL-05 (P3-D-9: one named decision group), P3-D-11 (decline terminal), P4-D-12 (`send_decline` held until a template exists) | `assessments/decisions.py`: the decision-maker records admit, decline or hold with exact inputs; `CATALYST_QUALIFICATION_AUTHORITY` must be set; `send_decline` has **no handler** | A decline notice; a staff member's permission grant without SQL | INCLUDED | **PRESERVE** human authority; **IMPROVE**: the decline notice (`oc4.11`, a deliberate improvement over "sends nothing"), permission grants (`9kg.30`). |

### 4.3 Agreements and custody (J-11 to J-13)

: Comparison: agreements and custody.

| Stage | Current (B1) | Approved target (B2) | v2 (B3) | Not proven | Launch | Disposition |
|---|---|---|---|---|---|---|
| J-11 NDA | Observed: envelope from an approved template, lookup-first by an opaque external key in a reserved namespace, distribution by the service's own email (the provider sends no recipient mail), applicant as signer then the company as approver; completion by an authoritative poll, never a pushed event. | REQ-011, D-15, P4-D-1 to P4-D-5, P4-D-8, P4-D-13 (owner-run activation) | `agreements/handlers.py`: `issue_nda` (held until `activate`), `create_agreement`, `distribute_agreement` (the provider's own notification), `read_agreement`; TEST-P4-01 to 03, 08, 10, 11; `ag_` external keys | Real Documenso: notifications, cancellation, webhook, recipient roles (`9kg.31.2`) | INCLUDED (the agreement step may be enabled only with the Documenso canary passed) | **PRESERVE** lookup-first and fresh-read completion. **Deliberate difference:** v2 lets the provider email the signing request (P4-D-4, P4-D-14); the owner may keep that or ask for a v2-sent cover (decision `211.7.4`). |
| Countersignature | Observed: the service's own manifest describes a human approver, while an operator-run step outside the service applies the company's countersignature under recorded safeguards, with a fallback that emails the owner a link. | POL-08; P4-D-3 (a company countersigner as a second signer once named); D-46 | A second signer role is supported; no automated countersignature exists | Whether that external step could act on v2 envelopes (its matching rules are in the private record; v2 external keys use their own prefix): UNKNOWN until its configuration is read at the preflight | INCLUDED as a **MANUAL HANDOFF**: the owner countersigns in Documenso | **MANUAL HANDOFF** at launch; any automated practice for v2 is an owner-and-counsel decision (`211.7.4`). Risk: a double countersign if templates are shared; mitigated by v2's own templates or team (`dy7.2`). |
| J-12 User Agreement | Observed: created in the same transaction as NDA completion; the applicant types legal name, residence, address and phone into the agreement; the case advances only when those details are captured; early pilot envelopes stayed on an older version; existing-member agreements were sent by the bridge. | D-15, REQ-030, REQ-031, POL-18 (D-46: the designated person may record and confirm a details version) | `advance_agreements` with a fresh read of the previous envelope at the moment of use; `agreements/completion.py`; TEST-P4-05, 06, 19 | Real template versions and the required details list (POL-18 production field list open) | INCLUDED | **PRESERVE** NDA-first; **VERIFY** which versions the cohort signs and whether existing members are referenced rather than re-signed (`211.7.4`, `211.7.6`). |
| J-13 Custody | Observed: a separate completion gate archives sealed PDFs and audit certificates; the service never reads them and learns "archived" from a small status file; one shared team webhook feeds that gate for every envelope. | REQ-032, POL-09, P4-D-6, P4-D-7, P4-D-16 | `store_agreement`: download, SHA-256 compare, `stored_verified`; retrieval limited to decision-makers; plaintext on local disk (carried limit) | Encryption at rest and key custody (`9kg.34`); the production location | INCLUDED (custody is required for the next agreement, P4-D-6) | **PRESERVE** custody as a separate fact; **IMPROVE** encryption (`9kg.34`) before real signed documents; **RETIRE** for v2 the shared gate and webhook (v2's own target, `dy7.2`, P6-D-4). |

### 4.4 Provisioning, activation and closure (J-14 to J-16)

: Comparison: provisioning, activation and closure.

| Stage | Current (B1) | Approved target (B2) | v2 (B3) | Not proven | Launch | Disposition |
|---|---|---|---|---|---|---|
| J-14 Provisioning | Observed: automatic release once deterministic conditions hold; the service picks a username (first name first, then first.last, a reserved list, collisions read at the provider; the pre-existing mailbox population takes precedence); create after an existence read; a present account the service did not request fails permanently and is never adopted; unknown outcomes reconcile by reading. | REQ-016, POL-11, P5-D-1 to P5-D-5 (the owner approves; staff-confirmed `firstname.lastname`; authoritative read; unknown accounts are conflicts) | `provisioning/handlers.py`: `provision` held until `activate_provisioning`, `provision_create`, `provision_reconcile`, `provision_verify`; TEST-P5-01, 02, 06; the adapter interface raises `NotImplementedError` | The live adapter, key custody, privilege separation (`9kg.31.3`); the host-side collision check (P5-D-1) | DISABLED unless the owner enables it with the canary passed | **PRESERVE** read-before-create and never-adopt; **VERIFY** the naming rule against the existing population (the first-generation service prefers first-name-only); **OUT OF INITIAL SCOPE** by default: existing members already hold mailboxes (`211.7.6`). |
| J-15 Activation | Observed: the welcome is login-verified and sent only to the address that signed, with no copy; a resend needs operator confirmation; the case became active before the welcome (defect: an unusable mailbox if every send fails); the CRM projection marks the person active; the welcome promises the mailbox and third-party steps only (no LMS, CRM, GitHub or roster access). The credential-delivery practice is a recorded owner exception in that service and is not carried into v2. | REQ-017, P5-D-6 (set-your-own-password; no password emailed), P5-D-7 (mailbox only) | `/setup/*`: the applicant sets a password; `provision_verify`; welcome after verification (TEST-P5-03, 04) | The mail host's real capability for a set-password flow (P5-D-6 pre-live gate) | DISABLED by default (as J-14) | **IMPROVE** (no emailed password) once the canary proves the operation; the CRM projection and every other promise is a **MANUAL HANDOFF** with a named owner or OUT OF INITIAL SCOPE (`211.7.6`). |
| J-16 Withdrawal, closure, recovery | Observed: withdrawal, suspension and offboarding states exist but no route or command reaches them; the service's mailbox revocation capability is narrower than v2's; a case that leaves active before the welcome gets no credentials; declined cases have open envelopes cancelled by a sweep. | REQ-018, POL-12, P5-D-8 to P5-D-11, D-46 | `/withdraw/*` (GET shows, POST commits), closure services, revocation recorded without deletion, unsupported checks stay unresolved (TEST-P5-05, 06, 10, 12) | Verified access revocation at the provider (a changed password is not session revocation), the production withdrawal-link lifetime | INCLUDED for withdrawal; revocation effects only if provisioning is enabled | **IMPROVE** (v2 has the path the first-generation service lacks); **VERIFY** revocation semantics in the canary (`9kg.31.3`); drills never touch an existing member's access (`211.7.6`). |

### 4.5 Handoffs outside any applicant screen

: Comparison: provider-owned and host-owned effects.

| Handoff | Current (B1) | v2 (B3) | Launch | Disposition |
|---|---|---|---|---|
| Owner notices by mail (intake, reply, review outcome, mailbox issued) | Observed: one notice per subject, each with a kill file | None: staff queues and the health report | NOT APPLICABLE | **RETIRE** for v2 (staff queue instead); the owner may ask for a digest later (post-launch). |
| CRM projection | Observed: every case event queues a projection; the client never deletes | None | NOT APPLICABLE | **OUT OF INITIAL SCOPE** (`211.7.6` records the manual handoff, if any). No integration is added by default. |
| Shared service mailbox | Observed: one mailbox is the sender for the service, the bridge and the provider's copies, and the inbox for every cohort's replies | v2 has its own mailbox (premise of P6-D-10) | INCLUDED, separate | **RETIRE** sharing; `dy7.2`, `211.7.3`. |
| Documenso team webhook and completion gate | Observed: one team webhook feeds the gate for every envelope of the team | v2's own POST-only authenticated site (P6-D-4), webhook as a hint, fresh read as authority | INCLUDED with the canary | **VERIFY** whether a second webhook on the same team or a separate team is needed (`9kg.31.2`, `dy7.2`). |
| Company countersignature step | Observed: an operator-run step outside the service signs for envelopes it recognizes as the first-generation service's | None | NOT APPLICABLE | **MANUAL HANDOFF** at launch; that step must not match v2 envelopes (`dy7.2`). |
| Monitors, reconcile, restore drill, nightly dump | Observed: frequent outcome checks, an hourly read-only reconcile against every provider, a periodic isolated restore drill, a verified dump before each nightly archive | Health command, heartbeat, dead-man sweep, alerts to Buzz; backup and restore drilled on the dev box; no host timers yet | INCLUDED once installed on the host (`9kg.28`) | **PRESERVE** the pattern; **IMPROVE** with the hourly read-only reconcile as a later task (noted on `9kg.28`). |
| Outward-flag gate (host-side approval records for every outward switch) | Observed: deploy and CI refuse an outward flag without an approval record on the host | Guards refuse provider settings outside the allowed environments; activation commands with approval references (P4-D-13) | INCLUDED | **PRESERVE** the principle: every enabled capability is a recorded owner act (section 7). |

### 4.6 Path collisions on the shared host

The first-generation service serves, on the learning host, paths that overlap v2's planned R1 entry family and part
of its R2 return family, in some cases with different semantics behind the same prefix and with links already in
applicants' hands. The exact live table stays in the private operations record (`003`); the preflight (`9kg.42`)
compares it with v2's `PRIVATE_PATHS` and records each collision. **Consequence:** the internal cohort cannot share
the learning host's path space without either breaking outstanding first-generation links or changing the live
matchers together with a cutover. The recommended resolution is a dedicated v2 host name for the cohort
(decision `211.7.3`), keeping D-09 for the later public cutover; the preflight (`9kg.42`) confirms the live table.

## 5. Control ownership and wait states

### 5.1 Who controls what

: Control ownership at the internal launch.

| Effect | Catalyst v2 | Provider | Authorized person | Shared or note |
|---|---|---|---|---|
| Verification, question and reminder mail | sends, reconciles, blocks on bounce, pauses | the mail host accepts or bounces | staff approve questions; the owner approves templates | a pause stops v2's sends only; the provider retains nothing v2 controls |
| Signing request email | none (P4-D-14) | **Documenso sends** and may remind on its own schedule | the owner decides reminder settings in the provider | **shared**: a v2 pause does not stop provider reminders; the canary records the provider's behaviour and `cancel_envelope` is the stop |
| Signature acceptance | verifies by fresh read | **Documenso accepts** signatures after a v2 pause unless the envelope is cancelled | decision-maker cancels | **shared**: cancel is an external, reconciled action (P4-D-18) |
| Countersignature | records the second signer | holds the envelope | **the owner signs** (manual handoff) | no automation at launch |
| Custody | downloads, verifies, stores, limits retrieval | keeps its own copy (P4-D-15 until POL-10) | decision-makers retrieve | the provider's copy is outside v2's retention until POL-10 |
| Mailbox creation and password | reads, creates, verifies, sets | **the mail host owns the account** | the owner approves each address (P5-D-3) | DISABLED by default at launch |
| Access after withdrawal | records revocation outcomes | the mail host keeps sessions until a verified revocation | staff resolve unsupported checks | **shared**; a changed password alone is not revocation |
| Model calls | none at launch | none | the owner (data-use approval) | DISABLED |
| Routing | none | none | the owner through the estate ingress procedure | a routing rollback is not a data rollback |
| Backups and restore | nightly dump, receipts, the restore hold | none | the owner lifts a hold after reconciliation | the host backup fabric archives the dump |

### 5.2 Wait states: who owes the next action

: Wait states, bounds and recovery at the internal launch.

| Wait state | Who owes | Bound or escalation | Staff recovery without a shell | Status |
|---|---|---|---|---|
| Verification sent, unconfirmed | applicant | challenge lifetime (POL-02 value open); a resend is a staff act | staff resend from the dossier | built; the production lifetime is an owner value |
| Question sent, awaiting reply | applicant | reminder cadence and maximum (POL-06 synthetic values), then `escalate_unanswered` to staff | staff item | built |
| Uncertain send | worker, then staff | reconcile by Sent-folder read; unknown goes to a staff item | staff decide resend or abandon (decision-maker) | built; live reconcile in the mail canary |
| Hard bounce | staff | immediate block of every send | decision-maker recovery after the cause is addressed | built (`9kg.3`) |
| Paused (staff or system) | staff | shown with reason and age | resume by the right role; system pauses need review | built; database guard open (`9kg.6`) |
| Capped assessment snapshot | staff | none today | **missing**: a screen to leave assessing (`oc4.8`, `oc4.12`) | gap |
| Awaiting decision | decision-maker | queue age in the health report | decision screen | built; the authority setting must be configured (`9kg.30`) |
| Declined | none | terminal | **no notice** today (`oc4.11`) | gap |
| Agreement held (recipient change, custody failure, expiry, rejection) | staff | staff item, pause | decision-maker reissues as a new instance | built |
| Provisioning held | the owner | released only by `activate_provisioning` | the command | built (disabled at launch) |
| Provisioning unknown outcome | worker, then staff | reconcile by read; never create again | staff item | built against the fake |
| Withdrawal racing provisioning | worker | the withdrawal services cancel and revoke; unsupported checks stay unresolved | staff item | built against the fake |
| On hold | staff | none | **missing**: no path back to a decision (`9kg.47`) | gap |
| Uncertain Documenso create or distribute | decision-maker | staff item | **shell only** today (`9kg.47`) | gap |
| Restore hold | the owner | nothing runs until reconciliation | `catalyst_post_restore` review and lift | built; erasure replay and effect reconciliation open (`9kg.25`, `9kg.33`) |

**Found by the code inventory (2026-10-23, `45f8b93`), each a VERIFY turned into a task:**

- **Actions enqueued without a handler:** `send_decline` (held forever; `oc4.11`), `interpret_reply` (held until
  staff cancel it, by design) and `provision` (released by `activate_provisioning`, by design). Unknown kinds are
  never claimed.
- **State changers reachable only from tests or a shell:** the decisions on an uncertain Documenso create or
  distribute (the only remedy for an unknown outcome), and agreement template approval (which `activate_agreements`
  requires). An application `on_hold` has no path back to a decision except closure. Three waits have no bound or
  anomaly: a sent agreement awaiting signature, a reply awaiting staff processing, and a provider-unavailable
  `provision_activate`. All in one bead (`9kg.47`).
- **Grant paths:** only the read-only group and the three P2 groups have a command; every assessment, agreements and
  provisioning permission and the qualification-decision permission can be granted only in a shell (`9kg.30`).
- **Non-redeliverable kinds** end `uncertain` on exhaustion and go to staff: `send_message`, `send_staff_message`,
  `create_agreement`, `distribute_agreement`, `cancel_envelope`, `cancel_agreement`, `provision_create`,
  `provision_invite`, `provision_withdraw_send`. Every other kind ends `failed`.
- **Provider effects** are disabled by code-fixed empty settings plus the guards; the provider's reminder behaviour
  and `documentDeleted` email setting are NOT VERIFIED (the Documenso canary).

## 6. Recovery, retention and custody

### 6.1 Data classes and copies

: Data classes, where copies exist, and the treatment POL-10 must decide.

| Class | Where it lives | Copies | Immutable by design? | Treatment to decide (POL-10) |
|---|---|---|---|---|
| Submission versions and adoptions | PostgreSQL | nightly dump; the host archive; the off-site leg | yes (D-22, triggers) | erase or anonymize personal fields with an audited exception; keep the adoption record's existence |
| Mail derivatives (redacted inbound, outbound attempts, reply links) | PostgreSQL | dumps | partly (`9kg.1`; `9kg.5` open) | retention period; bodies never stored |
| Model inputs and results | PostgreSQL (none at launch) | dumps | yes | none at launch |
| Staff notes, drafts, items and resolutions | PostgreSQL | dumps | resolutions yes | retention period |
| Evidence observations and digests | PostgreSQL | dumps | yes (no raw bytes, P3-D-13) | retention period |
| Signed documents | custody directory (plaintext today) | the custody copy in every backup set; the provider's copy | yes | encryption and key destruction (`9kg.34`); the provider's copy under P4-D-15 |
| Logs and receipts | host | the host archive | no | code-only by design (TEST-P6-13, 35) |
| Backups | the dump and custody set | the host archive, the off-site leg (object-locked) | by policy | the erasure record replayed on restore (`9kg.25`); object-locked copies age out, never purge one person |
| Selection-review material | none in the repository (`f1u.4`) | private location to approve | — | `f1u.4` |

### 6.2 The erasure design (proposed; `9kg.32`, `9kg.25`, `9kg.33`)

- An erasure is an authorized command run by the retention role, never by web or worker, under POL-10.
- The smallest durable erasure record (keyed hashes of the erased identifiers, the time and the authority; never a
  copy of the erased content) lives outside the application backup's rollback domain, with integrity, access,
  freshness and recoverability checks. It is sensitive and minimized. No distributed ledger.
- Deletion or anonymization is retry-safe, interruption-safe and reconciled; the audit evidence that an erasure
  happened is retained; the exception to the append-only triggers is a deliberate, audited retention path, not a
  weakening of every trigger or a grant to ordinary roles.
- A restore stays held until newer erasures are replayed and external effects reconciled; missing, corrupt, stale or
  unavailable erasure evidence never releases restored records.
- **Acceptance scenario:** back up a synthetic subject; erase afterward; restore the older backup; replay; prove that
  no web or staff view, job, attachment, derivative or enabled integration can expose or reuse the erased data; a
  second replay is harmless; an interruption recovers.
- **Effects after the backup point** (`9kg.33`): mail (Sent-folder read), envelopes (provider read by key),
  credential changes and mailbox facts (provider read), closures and revocations, staff role changes, and model usage
  (preserve possibly spent usage). Quarantined provider reconciliation with the smallest durable evidence; a manual
  exceptional resolution; conditions for lifting the hold.
- **Custody** (`9kg.34`): approved storage and access, a reviewed library, a recoverable key strategy, and a proof
  that an old backup cannot recover a destroyed key. Disk encryption is not per-subject erasure.

## 7. Launch manifest (to be approved at `9kg.31.6`)

: The proposed launch manifest.

| Item | Proposal | Decision |
|---|---|---|
| Cohort | the owner, then named internal team members by invitation; list kept in the private operations record | `211.7.6`, `9kg.31.6` |
| Entry | a dedicated v2 host name; invitation mode on (`9kg.43`); public entry on the learning host unchanged | `211.7.3` |
| Verification mail, questions, reminders, inbound collection | ENABLED on v2's own mailbox after the mail canary, with the cohort's templates, lifetimes and cadence decided | `211.7.7`, `9kg.31.1` |
| Evidence fetching | DISABLED (allow-list empty; refusal recorded) | — |
| Model advice | DISABLED; human-only assessment recorded (`oc4.12`) | `211.7.4` (data use) |
| Qualification decision | ENABLED; the owner is the decision group, decided for the cohort under POL-05 (P3-D-9 was synthetic only) | `211.7.8`, `9kg.30` |
| Decline notice | ENABLED once `oc4.11` is built with an approved template; until then a decline is recorded and the applicant is told through a staff-authored message on the existing P2 send path (`send_staff_message`), recorded on the dossier | `211.7.7` |
| Evidence fetching (REQ-029) | DISABLED: the allow-list stays empty and every fetch is refused and recorded | `211.7.8` |
| Agreements | ENABLED after the Documenso canary; v2's own webhook target and templates; the owner countersigns by hand | `211.7.4`, `9kg.31.2` |
| Custody | ENABLED with encryption (`9kg.34`) at the decided location | `211.7.9`, `211.7.1` |
| Mailbox provisioning and activation | DISABLED by default (existing members hold mailboxes); enabled only for a named participant after the MXroute canary | `211.7.6`, `9kg.31.3` |
| Withdrawal | ENABLED (revocation effects apply only where provisioning was enabled) | — |
| Backups, restore, erasure, reconciliation | nightly dump with receipts, the restore drill from the production archive, the erasure path and replay, effect reconciliation | `211.7.1`, `9kg.32`, `9kg.25`, `9kg.33` |
| Monitoring | health timer, sweep, alerts to Buzz with the owner's thresholds | `211.7.2` |
| Staff access | named devices, two-factor, the named roles | `211.7.5` |
| Routing changes to the learning host | NONE at launch (GATE-CUTOVER applies if the decision says otherwise) | `211.7.3` |
| Disabled capabilities' enforcement | verified from inside the running containers at the dark deploy and the deploy (`9kg.31.5`, `9kg.31.7`) | — |

## 8. Representative scenarios and their evidence

: Representative scenarios, existing evidence and the missing proof.

| Scenario | Existing evidence (synthetic) | Missing proof | Where |
|---|---|---|---|
| An eligible new participant completes the approved sequence and receives exactly the intended access | the P1 to P5 journey tests; TEST-P5-04 (full dossier) | the live providers; the first internal journey | `9kg.31.1` to `.3`, `9kg.31.8` |
| A returning internal participant already has a mailbox, account or agreement | P5-D-5 and P5-D-10 tests (never adopt, never inherit) | the cross-system check and the owner's rule | `dy7.2`, `211.7.6` |
| Private work or incomplete evidence; clarification without forced disclosure | REQ-036 flag test; P2 question loop | the alternative-evidence routes (`f1u.5`) before external applicants; at launch, human-only assessment | `oc4.12`, `f1u.5` (later) |
| Duplicate submission, expired link, partial reply, autoresponder, spoofed sender, hard bounce | TEST-S1-03, 04, 09; TEST-P2-02, 08, 10, 12 to 24; `9kg.3` | the live bounce and spoof paths | `9kg.31.1`, `9kg.31.8` |
| A held or declined application produces the right staff and candidate outcomes | TEST-P3-04 and the decision tests | the decline notice | `oc4.11` |
| Signing, custody, recipient changes and cancellation uncertainty never advance the wrong case | TEST-P4-02 to 04, 07, 13, 14, 17; the recipient-set check | the provider's real behaviour | `9kg.31.2` |
| Provisioning unknown outcome, or withdrawal racing it | TEST-P5-06, 10, 12 | the live adapter | `9kg.31.3` |
| A worker or provider outage or a restore loses no obligation, resurrects nothing erased, repeats no external effect, reactivates no access | the ledger recovery tests; the restore drill (28 of 28); the post-restore step | erasure replay; effect reconciliation | `9kg.25`, `9kg.33` |
| Legacy and v2 coexist without two owners for one case | none | the ownership register, the guards, the rehearsal | `dy7.2`, `dy7.3` |

Fault and rollback demonstrations stay synthetic or isolated; nothing is injected into colleagues' existing access.

## 9. Enablement matrix and improvements

### 9.1 Per capability

: Capability enablement at the internal launch.

| Capability | At the internal launch | Demonstrated block if disabled | Required proof if enabled |
|---|---|---|---|
| Mail (SMTP, IMAP) on v2's mailbox | required | — | the mail canary; TEST-P6-18, 19 live |
| Documenso agreements | required for any participant reaching admission | guards refuse the client outside `.test` until the setting is released | the Documenso canary; webhook refusals (TEST-P6-13, 16, 34) |
| Mailbox provisioning | later expansion by default | the adapter interface raises; the `provision` action stays held | the MXroute canary |
| Evidence fetching | disabled | the empty allow-list; the fetcher's refusals (TEST-P3-05, 06) | `9kg.39` and an allow-list decision |
| Model advice | disabled | model requests disabled in code; no live branch | `oc4.9`, `oc4.7`, data-use approval |
| CRM or other projections | not applicable | none exists | a separate scope decision |

### 9.2 Improvements, ranked

- **Must fix before the first live internal cohort:** the erasure path and replay (`9kg.32`, `9kg.25`), effect
  reconciliation after restore (`9kg.33`), custody encryption (`9kg.34`), the GitHub protections (`9kg.35`), the
  receipt and pre-deploy-backup gates (`9kg.37`), the N+1 revert drill (`9kg.38`), invitation mode (`9kg.43`), rate
  limits (`9kg.29`), the staff permission command (`9kg.30`), the decline notice (`oc4.11`), the human-only path
  (`oc4.12`), the pause-row guard (`9kg.6`), the provenance freezes (`9kg.5`), the narrowed test credentials
  (`6hl.10`), the personal-data scan (`9kg.40`), the screen walkthrough (`9kg.41`), the evidence register (`9kg.44`).
- **Required only if a capability is enabled:** the three canaries; `9kg.39` for fetching; `oc4.9` and `oc4.7` for
  the model.
- **Small usability improvements that fit a planned slice:** dossier labels for policy-held actions and stale help
  text (in `9kg.41`); the `P6_LIVE` comment fix (in `9kg.44`).
- **Post-launch or explicit non-goals:** the hourly read-only reconcile as a host timer (noted on `9kg.28`); an owner
  digest; CRM projection; automated countersignature; the targeted CI lane (`9kg.45`); lint (`9kg.46`); any LMS,
  roster, GitHub or chat integration (non-goals unless the owner decides otherwise).

## 10. Operations proposals for the owner (POL-16)

- **RPO.** Proposed: one nightly dump plus a pre-deploy dump (P6-D-7), so the worst-case data loss window is one
  day of ledger writes; every external effect in that window is recoverable by reconciliation (`9kg.33`), not by
  the dump. A shorter cadence is a later decision once the volume is known.
- **RTO.** Proposed: four hours from the decision to restore to a serving, reconciled system for the internal
  cohort, measured in the production restore drill from the production archive (`9kg.31.5`); the 62 to 63 second
  dev-box figure is a mechanism proof only.
- **Realistic-volume proof.** The drill uses the production archive at its real size; a backup growth and capacity
  check is part of the preflight and the nightly receipt. No load-testing platform.
- **Paging.** High and urgent findings page (worker dead, collector dead, backup failed or stale, restore drill
  overdue, uncertain send unresolved beyond a bound, custody failure); routine findings are audit-logged. Values are
  the owner's (`211.7.2`).
- **Incident ownership.** The owner, with a named deputy for the observation period.
- **Abort thresholds (observation period).** Any duplicate external effect, any personal data in a log or receipt,
  any security event, or two blocked journeys without a staff recovery path ends the exercise and pauses the stack.

## 11. The go/no-go package and the observation period

The package (`9kg.31.4` drafts it; `9kg.31.6` decides) names:

1. the exact release commit and image digest, and the effective repository controls (readback);
2. the target, routes, cohort, staff roles and enabled features;
3. the approved policies and notices for the actual data and use;
4. the backup, restore, erasure and reconciliation evidence;
5. the canary evidence and the agreement versions;
6. the remaining disabled capabilities and their verified enforcement;
7. the operators, the support and recovery procedure, the abort thresholds and the rollback limits.

**Observation period.** Short and scenario-based, not a number of days: the owner's own journey; each cohort
member's journey; the safe scenarios of section 8; one tested stop or pause; the first weekly review. Launch
readiness is separate from continued-use success; the defect queue (`9kg.31.9`) and the wider-enrollment decision
(`9kg.31.10`) follow.

## 12. Missing-evidence register

: Facts the available evidence cannot establish, and the smallest read that settles each.

| # | Unknown | Smallest read | Owner | Blocks |
|---|---|---|---|---|
| U1 | The deployed first-generation revision, schema and flag state | the readiness endpoint and the in-container flag readback on the host | preflight `9kg.42` | the ownership register |
| U2 | The live route table on the learning host and whether the LMS serves `/confirm` or `/withdraw` | the estate ingress source, read-only | `9kg.42` | `211.7.3`, `dy7.3` |
| U3 | The completion gate's webhook route, secret name, allowlist and whether the team supports a second webhook target | the gate source in the estate repository; the provider's team settings, read-only | `9kg.42`, `9kg.31.2` | `dy7.2` |
| U4 | Whether the countersign sweep could match v2 envelopes (templates, namespace) | the sweep's installed configuration names, no values | `9kg.42` | `dy7.2` |
| U5 | Whether anything else reads the first-generation mailbox; whether its two sender settings are equal | the mailbox's forwarder and filter list; a yes or no from the operator | the owner | `211.7.3` |
| U6 | The mail host's real capability for the set-password flow and for suspend or session revocation | the provider's API document, then the canary | `9kg.31.3` | enabling provisioning |
| U7 | Whether the provider emails the owner on completion of a v2 envelope | the team email settings, read-only | `9kg.31.2` | — |
| U8 | The existing-member population: who already holds a mailbox, signed agreements, a first-generation case | the owner's private roster; aggregate counts only | the owner | `211.7.6`, `dy7.2` |
| U9 | The applicable retention periods and erasure promises in the privacy texts and agreements | the legal texts, read by the owner and counsel | `211.7.1` | `9kg.32` |
| U10 | Whether custody document keys embed personal data; whether the Borg exclusions cover the secret files; free ports and the installed Caddy modules | the preflight | `9kg.42` | `9kg.28` |
| U11 | What the first-generation service's later release changed (an explicit confirmation step and a countersignature claim are reported) | a read of that release's tree (a separate narrow assignment) | the owner authorizes | compatibility facts only |
| U12 | Whether the first-generation service's operator-run timers outside the host still run, and what each sends | the timer list and the estate automation inventory | the owner | `dy7.2` |

Missing evidence about an enabled critical step blocks that step's readiness claim; it does not block the repo-only
work.

## 13. The work graph (as it exists in Beads)

Epics reused: P6 `9kg`, PL `dy7`, P3 `oc4`, selection quality `f1u`, policies `211.7`. One new feature bead,
`9kg.31`, is the launch milestone. Authority classes: repo-only; GitHub-admin; target-host read; target-host write;
provider canary; real-data action; launch; wider enrollment; policy. An authority label is not permission.

### 13.1 Beads

: The work graph: bead, status, purpose, earliest boundary, authority.

| Bead | Status | Purpose (plain English) | Earliest boundary it blocks | Authority |
|---|---|---|---|---|
| `dy7.1` | new, in progress | this plan | — | repo-only |
| `dy7.2` | new | the ownership register and the cross-system guards (one writer per case, mailbox, envelope, callback) | the launch manifest | repo-only (provider actions in their own beads) |
| `dy7.3` | new | the rehearsal against the live baseline (needs the prepared host, `9kg.28`) | any routing change, and the deployment | target-host read, then write (awaits a go) |
| `9kg.42` | new | the read-only production-host preflight | host preparation | target-host read (awaits a go) |
| `9kg.28` | updated | host preparation: secrets, database access, backups, timers, the force-command | the dark deploy | target-host write (awaits a go) |
| `9kg.43` | new | invitation-only intake, server-side | the internal launch | repo-only |
| `9kg.29` | updated | rate limits on every public endpoint with correct proxy identity | the internal launch | repo-only |
| `9kg.30` | updated | the staff permission command | release preparation | repo-only |
| `9kg.5`, `9kg.6`, `6hl.10` | reused | provenance freezes, the pause-row guard, narrowed test credentials | release preparation | repo-only |
| `oc4.11` | updated | the decline notice | release preparation | repo-only (template is a decision) |
| `oc4.12` | new | the human-only assessment path | release preparation | repo-only |
| `oc4.8` | reused | the capped-snapshot exit decision | `oc4.12` | policy (owner) |
| `oc4.9`, `oc4.10`, `oc4.7` | reused | live-call protections; real-use defects; the evaluation | before any model call | repo-only; `oc4.7` needs authorization |
| `9kg.32` | new | the erasure path and record | real-data storage | repo-only (after POL-10) |
| `9kg.25` | reused, updated | erasure replay after restore | real-data storage | repo-only |
| `9kg.33` | new | effect reconciliation after restore | the internal launch | repo-only |
| `9kg.34` | new | custody encryption and crypto-shredding | the internal launch | repo-only (after POL-09, POL-10) |
| `9kg.35` | new | the `main` ruleset, the release environment, the merge-guard registration (owner-only; its interaction with the repository ownership move `9kg.4` is noted there) | any deploy credential; host preparation | GitHub-admin (awaits a go) |
| `9kg.36` | new | the image scan as part of the required contract | release preparation | repo-only plus admin |
| `9kg.37` | split from `9kg.27` | receipt mismatch refuses; pre-deploy backup bound | release preparation | repo-only |
| `9kg.38` | split from `9kg.27` | migrate N+1 then revert to N | release preparation | repo-only |
| `9kg.39` | split from `9kg.27` | egress deny of production hosts | enabling fetching | repo-only |
| `9kg.40` | split from `9kg.27` | personal-data scan of evidence and receipts | the first real-data receipt | repo-only |
| `9kg.27` | reused, re-scoped | the live clauses carried by the canaries | — | — |
| `9kg.41` | new | the screen and exceptional-state walkthrough | the go/no-go package | repo-only |
| `9kg.47` | new | supported paths for the shell-only states (uncertain Documenso decisions, template approval, leaving on-hold) and bounds on the unbounded waits | release preparation | repo-only |
| `9kg.44` | new | the machine-checkable evidence register | the go/no-go package | repo-only |
| `9kg.45`, `9kg.46` | new | CI profiling and lane; scoped lint | none | repo-only |
| `211.7.1` to `211.7.9` | new (split) | POL-10; POL-16; POL-15 coexistence; POL-07/08/17 legal and model data use; POL-13/14 staff; POL-11/12 welcome and existing members; POL-02/06 lifetimes and templates; POL-05/03/18 authority, form fields and details; POL-09 custody | see each; all block the go/no-go | policy (owner, counsel) |
| `9kg.31` | new feature | the launch milestone (its last two children run after launch, so it closes with the wider-enrollment decision) | — | launch |
| `9kg.31.1` to `.3` | new | the mail, Documenso and MXroute canaries, run from the dark-deployed production stack (`9kg.31.5`) with provider settings released for the canary only; `.3` closes as "not enabled" if provisioning stays disabled | enabling each capability | provider canary (await a go) |
| `9kg.31.4` | new | release preparation and the package draft | the dark deploy | repo-only plus the release workflow |
| `9kg.31.5` | new | the dark deploy on the production host | the go/no-go | target-host write (awaits a go) |
| `9kg.31.6` | new | the owner's go/no-go (GATE-PILOT for the internal cohort) | the deployment | launch (owner) |
| `9kg.31.7` | new | the deployment and capability release | post-launch verification | target-host write, launch |
| `9kg.31.8` | new | the first internal journey and the observation scenarios | wider enrollment | real-data action |
| `9kg.31.9` | new | the defect queue and weekly review | wider enrollment | repo-only |
| `9kg.31.10` | new | the wider-enrollment decision | public intake on v2 | wider enrollment (owner) |
| `f1u.2` to `f1u.8` | reused | selection-quality work; `f1u.5` before external applicants; `f1u.7` scorecard for the weekly summary | before real candidate-impacting use | policy and repo-only |

### 13.2 Dependency map and critical path

```text
POL decisions ──► 211.7.1 POL-10 ──► 9kg.32 erasure ──► 9kg.25 replay ─────┐
               ├─ 211.7.9 POL-09 ──► 9kg.34 custody ────────────────────────┤
               ├─ 211.7.3 coexist ──┬─► 9kg.28 host prep ◄── 9kg.42 preflight ◄── (owner go)
               │                    │        ▲    │                         │
               ├─ 211.7.5 staff ────┘        │    └─► dy7.3 rehearsal ◄── dy7.2 ◄── 9kg.42
               │                     9kg.35 admin (owner go)                │
               ├─ 211.7.4 legal ──► oc4.11 ─┐                               │
               ├─ 211.7.2, .6, .7, .8 ──────┼───────────────────────────────┤
repo-only batch ────────────────────────────┴─► 9kg.31.4 release prep       │
(9kg.37, 9kg.38, 9kg.43, 9kg.29, 9kg.30, 9kg.47,         │                  │
 oc4.12, 9kg.44, 9kg.40, 9kg.41, 9kg.5, 9kg.6, 6hl.10,   ▼                  │
 9kg.36 after 9kg.35)                        9kg.31.5 dark deploy ──────────┤
                                                   │                        │
                     canaries 9kg.31.1, .2, .3 ◄───┘ (from the dark stack) ─┤
9kg.33 reconcile ───────────────────────────────────────────────────────────┴─► 9kg.31.6 GO/NO-GO
                                                                                     │
                                                       9kg.31.7 deploy ◄── dy7.3 ◄───┘
                                                            │
                                                 9kg.31.8 verify ─► 9kg.31.9 ─► 9kg.31.10
```

**Critical path to the first internal launch:** POL-10 decision → erasure path → erasure replay (repo-only, the
longest build), in parallel with the coexistence and staff decisions → the GitHub protections (owner go) → the
preflight (owner go) → host preparation → the dark deploy → the three canaries from the dark stack; everything
feeds the go/no-go, which also waits on the nine policy decisions.

### 13.3 The first ready repo-only batch (bounded authorization)

Independent of every host and provider action, and small enough for one release. Three items proceed on the
recommended default of a decision rather than wait for it: `9kg.37` (D-I, the receipt as a gate), `9kg.30` (the P3
to P5 role names, decided for P2 only by D-30) and `oc4.12` (`oc4.8`, the capped-snapshot exit); each records the
default it built on, and the owner's later decision can change a value without redesign.

1. `9kg.43` invitation mode; `9kg.29` rate limits (both intake-facing);
2. `9kg.37` receipt and backup gates; `9kg.38` the N+1 revert drill (both deploy-wrapper drills);
3. `9kg.30` the staff permission command; `9kg.47` the shell-only operator paths; `oc4.12` the human-only path;
4. `9kg.33` effect reconciliation after restore (fakes only);
5. `9kg.44` the evidence register; `9kg.40` the personal-data scan; `9kg.6` the pause-row guard.

Subsequent batches, each separately authorized: **GitHub-admin** (`9kg.35`, then `9kg.36`); **host** (`9kg.42`,
then `9kg.28`, `9kg.31.5`, `dy7.3`); **provider canaries** from the dark stack (`9kg.31.1` to `.3`); **after
POL-10 and POL-09** (`9kg.32`, `9kg.25`, `9kg.34`).

## 14. Decision brief (recommended choice, alternative, consequence, first task blocked)

: Owner decisions, each with a recommended default.

| Decision | Recommended | Alternative | Consequence of the recommendation | First task blocked |
|---|---|---|---|---|
| D-A Host for the internal cohort (`211.7.3`) | a dedicated v2 host name; the learning host untouched; D-09 kept for the public cutover | the learning host with changed matchers (a partial cutover now) | no collision with outstanding first-generation links; one extra DNS name and certificate under the estate DNS and ingress procedures (added to `9kg.28`); the public cutover stays a later GATE-CUTOVER act | `dy7.2`, `dy7.3` |
| D-B The Documenso webhook target (`211.7.3`) | v2's own webhook target (a second webhook on the team or a separate team, whichever the provider supports); the separate v2 mailbox is already decided (P6-D-10) | share the first-generation completion gate | no second consumer of one webhook; two provider configurations to keep | `9kg.31.2` |
| D-C Retention and erasure (`211.7.1`) | decide with counsel before any real backup; the data-class table of section 6 is the checklist; provider-held copies are a manual handoff the decision names | launch with a documented hold on erasure requests | without it, real data enters object-locked backups with no erasure path | `9kg.32` |
| D-D Agreements for the cohort (`211.7.4`) | existing members are referenced, not re-signed; new participants sign the current versions; the owner countersigns by hand at launch | automated countersignature carried over now | no automated signature until counsel confirms it for v2 | `9kg.31.2` |
| D-D2 Custody (`211.7.9`) | the location under the managed data root, decision-makers only, encrypted with recoverable keys | plaintext as today | signed documents of real people are unreadable from a lost disk or an old backup | `9kg.34` |
| D-D3 Lifetimes and templates (`211.7.7`) | the synthetic defaults of `016` section 10 as starting values, the cohort's templates approved one version each | — | no real wording goes out unapproved | `9kg.31.1` (content), `oc4.11` |
| D-D4 Authority, form fields, details (`211.7.8`) | the owner as the decision group; the current form fields; the details list the agreements need | — | the decision setting is configured and granted through `9kg.30` | `9kg.30` (value) |
| D-D5 Evidence fetching (`211.7.8`) | disabled at launch (REQ-029) | an allow-list of a few public hosts | nothing is fetched on an internal participant's behalf | `9kg.39` if enabled |
| D-E Model data use (`211.7.4`) | model advice off for the internal launch; human-only assessment | re-use the earlier acceptance for v2's fields | no provider sees internal participants' data at launch | `oc4.12` |
| D-F Existing members and provisioning (`211.7.6`) | provisioning disabled by default; no drill touches an existing mailbox | provision throwaway mailboxes for everyone | no second mailbox, no accidental revocation | `9kg.31.3` |
| D-G RPO, RTO, thresholds (`211.7.2`) | section 10's proposals | other values | the drill measures against them | `9kg.31.4` |
| D-H Staff devices and roles (`211.7.5`) | option A as decided (P6-D-3), with the named devices and holders | — | the host preparation can configure the restriction | `9kg.28` |
| D-I Receipt mismatch (`9kg.37`) | a gate | a recorded deviation | a mismatch refuses the deploy | `9kg.37` |
| D-J GitHub protections (`9kg.35`) | apply now, before any deploy credential (D-49) | — | the only remaining single-maintainer caveat is recorded | `9kg.35` |
| D-K Scan policy (`9kg.36`) | fixable high and critical fail the required contract | advisory only | a vulnerable image cannot merge | `9kg.36` |
| D-L The 2026-10-22 GATE-STAGING sign-off | already given; recorded as D-50 in this PR with its exact scope (`028` section 9), for the owner's confirmation that the record is faithful | — | `011` stays the single record of gate state | — |

Decisions already recorded are not asked again: D-49's P6-D-1 to P6-D-15 (including the separate v2 mailbox),
D-46, D-47, D-48 and the selection-quality decisions of D-35. The synthetic policy defaults (D-29, D-30, D-34) are
starting values only; their production values are the decisions above.

## 15. Proposed go-live sign-off wording (for `9kg.31.6`; not a signature)

> "I approve the internal production launch of Catalyst v2 for the cohort named in the private operations record,
> on release commit `<sha>` and image digest `<digest>`, reached on `<host name>` with invitation mode on, with the
> capabilities the launch manifest (029 section 7, version `<n>`) enables and every other capability verified
> disabled from inside the running containers. I accept the recorded evidence for backup, restore, erasure replay,
> effect reconciliation, the mail and Documenso canaries, and the agreement versions named there. This does not
> enable public intake, mailbox provisioning (unless named), evidence fetching, model advice, any routing change on
> the learning host, or any wider enrollment; each needs its own decision. The abort thresholds of section 10 apply."

## 16. Review record

- **Independent review** (`catalyst-independent-qa`, 2026-10-23, of PR #81 at `ac34c90`): 1 blocker (a
  parenthetical in `002`'s GATE-PILOT row read as narrowing the gate; rewritten so the scoped decision beads are a
  minimum, not a substitute), 4 high (operational detail of the private service in this document, scrubbed to
  behaviour; six production policies with no decision bead, added as `211.7.7` to `211.7.9`; two must-fix beads
  blocking nothing, wired; the canary environment unspecified, now the dark-deployed stack), 8 medium (dependency
  edges and labels, the D-50 wording, stale index rows, brief hygiene, unowned handoffs, the conditional MXroute
  canary) and 8 low, all applied in the fix-up commit. The reviewer could not run `bd`, `git` or `gh` and read the
  Beads export instead of the live tracker; the main session re-ran `bd ready` and `check-docs` after the fixes.
- **Legacy questions:** three narrow assignments to `catalyst-legacy-analyst` on 2026-10-23 (routes and states;
  activation and closure; external effects), each at the pinned checkout, each with its unknowns carried into
  section 12. The answers are session artifacts, not filed; no private path, identifier or data from them is
  reproduced here.
