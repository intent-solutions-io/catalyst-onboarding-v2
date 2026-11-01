# Internal production launch: workflow comparison record and execution plan (handoff PL-A)

| Field | Value |
|---|---|
| Document | `029-PP-PLAN-internal-launch-comparison-and-execution-plan` |
| Version | 0.4.0 (appendix B adds the screen and exceptional-state walkthrough, `9kg.41`, 2026-10-23; 0.3.0: the council record `030` adopts the decision brief provisionally and amends the path, sections 13.2 and 14, 2026-10-23; 0.2.0 applied the compliance audit of 2026-10-23: section 4.7, appendix A, section 16, the corrected batch and brief) |
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
| B1 Current operations | The first-generation service (a private repository), live in production for real applicants on the shared learning host, plus an interim set of operator-run timers that bridge agreement signing and activation, plus documented manual operator commands | Source read read-only on 2026-10-23 at a pinned local checkout; the checkout's identifier, its distance from the remote and the release the service's own records report as deployed are kept in the private operations record. **The deployed revision is UNKNOWN** until the preflight reads it on the host (`9kg.42`). | Recorded operator knowledge in the estate brain (early October 2026); three narrow legacy-analyst answers (ADR-12, `007`), each separating intended from observed behaviour |
| B2 Approved business contract | `011` (D-01 to D-49), `002` requirements and gates, `004` journeys J-01 to J-16, the policies decided for synthetic work, the NDA-before-User-Agreement rule (D-15), the separation of signing, custody and access (REQ-032, P4-D-6) | `011` 1.2.0 plus D-16 to D-49; this PR records D-50 | Owner decisions |
| B3 Implemented v2 | The Django application at `main` `45f8b93`: routes, services, registered handlers, screens, permissions, persistence and recovery, with 1,353 passing tests and the P6 drills | `45f8b93` (PR #80); CI run 39797287619; drills in `026` section 16 | Tests, drills, source |
| B4 Proposed live internal scope | The launch manifest of section 7: the cohort, the enabled integrations, the real effects, the manual steps and the exclusions | This document, version 0.2.0, for approval at `9kg.31.6` | Proposal |

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
verifies it, and emails the welcome; its credential-delivery practice is not carried into v2. Every case event is
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
| J-05 Assessment | Observed: four bounded model stages on one job queue; typed outputs with validators; a repair budget; staleness checks; shadow mode records recommendations only; the owner gets a notice per resting outcome; intake-stage public data to the model was accepted by the owner with counsel (recorded decision). | REQ-009, D-04, P3-D-4 to P3-D-8, `019` (the P3-D-10 amendment: a recorded human-only assessment when advice is unavailable or suspended) | `assessments/agent.py` (model requests disabled, no live branch), `runs.py`, budgets, invocation records, failure routing (TEST-P3-01, 02, 07); live-call protections built and tested with no live request, including the pre-call owner approval check (`oc4.9`, `018` section 21) | The human-only path's policy and snapshot record (`oc4.10` items 1 to 3); a refused or capped snapshot's exit (`oc4.8`, `9kg.50`); real-model quality and prompt-injection behaviour (fake-model tests are not real-model evidence) | DISABLED (model off; human-only assessment) | **OUT OF INITIAL SCOPE** for model advice; **VERIFY** and complete the human-only path (`oc4.12`). Note the deliberate difference from B1: v2 sends nothing to a model until `oc4.9`, the data-use approval for v2's fields and the evaluation (`oc4.7`) exist. The owner's earlier data-use acceptance was for the first-generation reviewer's fields and must not be assumed to carry over (decision `211.7.4` asks). |
| J-06 Questions | Observed: a clarification sender existed in design but was unregistered at the checkout (reported restored later; UNKNOWN); pacing limits exist; reminders unbuilt. | REQ-012, REQ-034, P3-D-5 (model questions never sent unapproved) | `correspondence`: approved, frozen messages; staff-authored and model-proposed questions through approval; TEST-P2 cases; GATE-P2 PASS 54 | Real delivery and reply collection (mail canary) | INCLUDED (staff-authored questions only) | **PRESERVE** the owner-approval rule; **IMPROVE**: v2 has the loop the first-generation service lacked. |
| J-07 Inbound | Observed: a 60-second poll of one shared service mailbox with a durable UIDVALIDITY plus UID cursor, deterministic classes, no bodies stored; bridge and existing-member replies land in the same inbox; a human reply emails the owner a notice. | REQ-012, REQ-034, D-27, D-28, D-31 (fail-closed identity) | `correspondence/imap.py`, `inbound.py`, `processing.py`; association and trust; staff exceptions (TEST-P2-01, 07, 12 to 24) | Live inbound health (TEST-P6-18); the real mailbox | INCLUDED, on **v2's own mailbox** | **PRESERVE** durable collection; **RETIRE** the shared mailbox for v2 (M8, P6-D-10): a second poller of the first-generation mailbox would duplicate and race. Decision `211.7.3`. The owner reply notice is a MANUAL HANDOFF (the staff queue shows replies; no owner mail). |
| J-08 Reminders, autoresponders, bounces | Observed: autoresponders and bounces classified; nothing suppresses on a bounce (defect); no reminders. | REQ-012, D-27; `9kg.2`, `9kg.3` (closed): hard bounce blocks every send; system pauses need a decision-maker | `correspondence/reminders.py`, `remind`, `escalate_unanswered`; TEST-P2-02, 04, 10 | Live bounce path (mail canary) | INCLUDED | **IMPROVE** (bounce block and reminders exist in v2 only). |
| J-09 Takeover | Observed: no global pause in the service; host-level switches; per-case halts in the bridge cleared by hand. | REQ-013, D-30 | `AutomationPause`, `staff_actions.pause/resume`; the pause row protected in the database since `9kg.6` (workflow migration 0005) | A database guard on the pause row | INCLUDED | **PRESERVE**; **IMPROVE** `9kg.6` before launch. |
| J-10 Decision | Observed: approval is an owner command that also queues the NDA envelope; decline is an owner command that sends nothing and later cancels open envelopes; a model hold is recorded as "recommended" only. Intended agrees (owner keeps every decision). | REQ-010, POL-05 (P3-D-9: one named decision group), P3-D-11 (decline terminal), P4-D-12 (`send_decline` held until a template exists) | `assessments/decisions.py`: the decision-maker records admit, decline or hold with exact inputs; `CATALYST_QUALIFICATION_AUTHORITY` must be set; `send_decline` has **no handler** | A decline notice; a staff member's permission grant without SQL | INCLUDED | **PRESERVE** human authority; **IMPROVE**: the decline notice (`oc4.11`, a deliberate improvement over "sends nothing"), permission grants (`9kg.30`). |

### 4.3 Agreements and custody (J-11 to J-13)

: Comparison: agreements and custody.

| Stage | Current (B1) | Approved target (B2) | v2 (B3) | Not proven | Launch | Disposition |
|---|---|---|---|---|---|---|
| J-11 NDA | Observed: envelope from an approved template, lookup-first by an opaque external key in a reserved key range, distribution by the service's own email (the provider sends no recipient mail), applicant as signer then the company as approver; completion by an authoritative poll, never a pushed event. | REQ-011, D-15, P4-D-1 to P4-D-5, P4-D-8, P4-D-13 (owner-run activation) | `agreements/handlers.py`: `issue_nda` (held until `activate`), `create_agreement`, `distribute_agreement` (the provider's own notification), `read_agreement`; TEST-P4-01 to 03, 08, 10, 11; `ag_` external keys | Real Documenso: notifications, cancellation, webhook, recipient roles (`9kg.31.2`) | INCLUDED (the agreement step may be enabled only with the Documenso canary passed) | **PRESERVE** lookup-first and fresh-read completion. **Deliberate difference:** v2 lets the provider email the signing request (P4-D-4, P4-D-14); the owner may keep that or ask for a v2-sent cover (decision `211.7.4`). |
| Countersignature | Observed: the service's own manifest describes a human approver, while an operator-run step outside the service applies the company's countersignature under recorded safeguards, with a fallback that emails the owner a link. | POL-08; P4-D-3 (a company countersigner as a second signer once named); D-46 | A second signer role is supported; no automated countersignature exists | Whether that external step could act on v2 envelopes (its matching rules are in the private record; v2 external keys use their own prefix): UNKNOWN until its configuration is read at the preflight | INCLUDED as a **MANUAL HANDOFF**: the owner countersigns in Documenso | **MANUAL HANDOFF** at launch; any automated practice for v2 is an owner-and-counsel decision (`211.7.4`). Risk: a double countersign if templates are shared; mitigated by v2's own templates or team (`dy7.2`). |
| J-12 User Agreement | Observed: created in the same transaction as NDA completion; the applicant types legal name, residence, address and phone into the agreement; the case advances only when those details are captured; early pilot envelopes stayed on an older version; existing-member agreements were sent by the bridge. | D-15, REQ-030, REQ-031, POL-18 (D-46: the designated person may record and confirm a details version) | `advance_agreements` with a fresh read of the previous envelope at the moment of use; `agreements/completion.py`; TEST-P4-05, 06, 19 | Real template versions and the required details list (POL-18 production field list open) | INCLUDED | **PRESERVE** NDA-first; **VERIFY** which versions the cohort signs and whether existing members are referenced rather than re-signed (`211.7.4`, `211.7.6`). |
| J-13 Custody | Observed: a separate completion gate archives sealed PDFs and audit certificates; the service never reads them and learns "archived" from a small status record; one shared team webhook feeds that gate for every envelope. | REQ-032, POL-09, P4-D-6, P4-D-7, P4-D-16 | `store_agreement`: download, SHA-256 compare, `stored_verified`; retrieval limited to decision-makers; plaintext on local disk (carried limit) | Encryption at rest and key custody (`9kg.34`); the production location | INCLUDED (custody is required for the next agreement, P4-D-6) | **PRESERVE** custody as a separate fact; **IMPROVE** encryption (`9kg.34`) before real signed documents; **RETIRE** for v2 the shared gate and webhook (v2's own target, `dy7.2`, P6-D-4). |

### 4.4 Provisioning, activation and closure (J-14 to J-16)

: Comparison: provisioning, activation and closure.

| Stage | Current (B1) | Approved target (B2) | v2 (B3) | Not proven | Launch | Disposition |
|---|---|---|---|---|---|---|
| J-14 Provisioning | Observed: automatic release once deterministic conditions hold; the service picks a username (first name first, then first.last, a reserved list, collisions read at the provider; the pre-existing mailbox population takes precedence); create after an existence read; a present account the service did not request fails permanently and is never adopted; unknown outcomes reconcile by reading. | REQ-016, POL-11, P5-D-1 to P5-D-5 (the owner approves; staff-confirmed `firstname.lastname`; authoritative read; unknown accounts are conflicts) | `provisioning/handlers.py`: `provision` held until `activate_provisioning`, `provision_create`, `provision_reconcile`, `provision_verify`; TEST-P5-01, 02, 06; the adapter interface raises `NotImplementedError` | The live adapter, key custody, privilege separation (`9kg.31.3`); the host-side collision check (P5-D-1) | DISABLED unless the owner enables it with the canary passed | **PRESERVE** read-before-create and never-adopt; **VERIFY** the naming rule against the existing population (the first-generation service prefers first-name-only); **OUT OF INITIAL SCOPE** by default: existing members already hold mailboxes (`211.7.6`). |
| J-15 Activation | Observed: the welcome is login-verified and sent only to the address that signed, with no copy; a resend needs operator confirmation; the case became active before the welcome (defect: an unusable mailbox if every send fails); the CRM projection marks the person active; the welcome promises the mailbox and third-party steps only (no LMS, CRM, GitHub or roster access). The credential-delivery practice is a recorded owner exception in that service and is not carried into v2. | REQ-017, P5-D-6 (set-your-own-password), P5-D-7 (mailbox only) | `/setup/*`: the applicant sets a password; `provision_verify`; welcome after verification (TEST-P5-03, 04) | The mail host's real capability for a set-password flow (P5-D-6 pre-live gate) | DISABLED by default (as J-14) | **IMPROVE** (set-your-own-password) once the canary proves the operation; the CRM projection and every other promise is a **MANUAL HANDOFF** with a named owner or OUT OF INITIAL SCOPE (`211.7.6`). |
| J-16 Withdrawal, closure, recovery | Observed: withdrawal, suspension and offboarding states exist but no route or command reaches them; the service's mailbox revocation capability is narrower than v2's; a case that leaves active before the welcome gets no credentials; declined cases have open envelopes cancelled by a sweep. | REQ-018, POL-12, P5-D-8 to P5-D-11, D-46 | `/withdraw/*` (GET shows, POST commits), closure services, revocation recorded without deletion, unsupported checks stay unresolved (TEST-P5-05, 06, 10, 12) | Verified access revocation at the provider (a changed password is not session revocation), the production withdrawal-link lifetime | INCLUDED for withdrawal; revocation effects only if provisioning is enabled | **IMPROVE** (v2 has the path the first-generation service lacks); **VERIFY** revocation semantics in the canary (`9kg.31.3`); drills never touch an existing member's access (`211.7.6`). |

### 4.5 Handoffs outside any applicant screen

: Comparison: provider-owned and host-owned effects.

| Handoff | Current (B1) | v2 (B3) | Launch | Disposition |
|---|---|---|---|---|
| Owner notices by mail (intake, reply, review outcome, mailbox issued) | Observed: one notice per subject, each with a kill file | None: staff queues and the health report | NOT APPLICABLE | **RETIRE** for v2 (staff queue instead); the owner may ask for a digest later (post-launch). |
| CRM projection | Observed: every case event queues a projection; the client never deletes | None | NOT APPLICABLE | **OUT OF INITIAL SCOPE** (`211.7.6` records the manual handoff, if any). No integration is added by default. |
| Shared service mailbox | Observed: one mailbox is the sender for the service, the bridge and the provider's copies, and the inbox for every cohort's replies | v2 has its own mailbox (premise of P6-D-10) | INCLUDED, separate | **RETIRE** sharing; `dy7.2`, `211.7.3`. |
| Documenso team webhook and completion gate | Observed: one team webhook feeds the gate for every envelope of the team | v2's own POST-only authenticated site (P6-D-4), webhook as a hint, fresh read as authority | INCLUDED with the canary | **VERIFY** at the canary (`9kg.31.2`, `dy7.2`). Public fact (Documenso source at tag v2.21.1, read 2026-10-23): every enabled webhook of a team that subscribes to an event is fired for every envelope of that team, so a second webhook on the shared team would receive every first-generation envelope's events and the first-generation gate would receive v2's. Recommendation in D-B: a separate team, unless both consumers provably ignore envelopes they did not create (U3, U4). |
| Legacy company countersignature step | Observed: an operator-run step outside the first-generation service signs for envelopes it recognizes as that service's | None (v2's countersignature is the owner's manual act, section 4.3) | NOT APPLICABLE to v2 envelopes | **MANUAL HANDOFF** at launch; that step must not match v2 envelopes, proven by the canary's negative control (`dy7.2`, `9kg.31.2`). |
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

### 4.7 First-generation feature inventory: where each lands in v2

The owner's question behind this handoff is whether every first-generation feature made it into v2. Sections 4.1 to
4.5 answer it stage by stage; this table answers it feature by feature, from the plain-English map of section 3.
"Built" means implemented and tested at `45f8b93`; "at launch" is the manifest of section 7.

: First-generation features and their v2 status.

| First-generation feature (B1, as of the checkout read) | In v2 (B3) | At the internal launch | Disposition and where |
|---|---|---|---|
| Branded request form with CSRF, timestamp token, honeypot, per-address rate limit, one-time "received" page | Built, except the rate limit | INCLUDED, invitation-only | PRESERVE; IMPROVE (`9kg.29`, `9kg.43`) |
| Receipt email on submission | Built (verification challenge instead of a bare receipt) | INCLUDED | PRESERVE as a deliberate safe difference (J-03) |
| Owner notice by mail on intake, reply, review outcome, mailbox issued | Not built; the staff queue and the health report replace it | NOT APPLICABLE | RETIRE for v2 (section 4.5); a digest is a post-launch option |
| Duplicate handling: repeat from the same address becomes a revision | Built | INCLUDED | PRESERVE (J-02) |
| AI reviewer reading supplied public links, GitHub lookup from a supplied link, shadow-mode recommendation | Built as the fetcher, evidence collection and the assessment stages; model requests disabled in code | DISABLED (fetching and model advice) | OUT OF INITIAL SCOPE (`9kg.39`, `oc4.9`, `oc4.7`, decision `211.7.4`) |
| Human decision by owner command | Built as the decision screen for the named decision group | INCLUDED | PRESERVE (J-10, `9kg.30`) |
| Decline sends the applicant nothing | Built: the decline notice through the P2 sender (`oc4.11`, section 17.3) | INCLUDED | IMPROVE (`oc4.11`): a deliberate improvement over silence |
| Clarification questions to the applicant (unregistered at the checkout) | Built, with approval, pacing and reminders | INCLUDED (staff-authored questions) | PRESERVE and IMPROVE (J-06, J-08) |
| Shared service mailbox polled every 60 s with a durable cursor | Built, on v2's own mailbox | INCLUDED, separate mailbox | PRESERVE the collection; RETIRE the sharing (J-07, `211.7.3`) |
| Autoresponder and bounce classification (nothing suppresses on a bounce) | Built, with a hard-bounce block | INCLUDED | IMPROVE (J-08) |
| Host-level kill files and per-case halts | Built as the audited pause and resume | INCLUDED | PRESERVE; IMPROVE (`9kg.6`) |
| NDA envelope from a template, lookup-first, service-sent signing email, poll for completion | Built; the provider sends the signing request (P4-D-4) | INCLUDED after the Documenso canary | PRESERVE; deliberate difference on the sender (J-11, `211.7.4`) |
| User Agreement created on NDA completion; applicant types legal details | Built with a fresh read at the moment of use | INCLUDED | PRESERVE NDA-first (J-12) |
| Company countersignature by an operator-run step outside the service | A second signer role; no automation | INCLUDED as a manual act by the owner | MANUAL HANDOFF (section 4.5, `211.7.4`, `dy7.2`) |
| Separate archiving of sealed documents; status file read by the service | Built as custody with hash verification, plaintext today | INCLUDED with encryption | PRESERVE; IMPROVE (`9kg.34`, `211.7.9`) |
| Automatic case release when conditions hold | Built as an owner-run activation (P4-D-13) | INCLUDED | PRESERVE the outcome; deliberate difference (owner act) |
| Mailbox creation through the mail host's API, username rule, read-before-create, never adopt | Built against the adapter interface; no live adapter | DISABLED by default | PRESERVE the rules; OUT OF INITIAL SCOPE unless enabled (`9kg.31.3`, `211.7.6`) |
| Login-verified welcome to the signing address; credential-delivery practice | Built with set-your-own-password; the practice is not carried | DISABLED with provisioning | IMPROVE (J-15) |
| CRM projection of every case event | Not built | NOT APPLICABLE | OUT OF INITIAL SCOPE (`211.7.6` names any manual handoff) |
| Withdrawal, suspension, offboarding states with no path to them | Built with applicant and staff paths and recorded revocation | INCLUDED (revocation effects only with provisioning) | IMPROVE (J-16) |
| Hourly read-only reconcile, frequent monitors, nightly dump, periodic restore drill | Built as the health command, heartbeat, sweep, alerts, backup and restore commands; host timers not installed | INCLUDED once installed | PRESERVE (`9kg.28`); the hourly reconcile as a later timer |
| Outward-flag gate (host approval record for every outward switch) | Built as environment guards plus activation commands with approval references | INCLUDED | PRESERVE (section 4.5) |
| Nothing deletes personal data | The erasure path is built (`9kg.32`, section 6.2); its registry is undecided, so it refuses until POL-10; replay after a restore is built (`9kg.25`) | required before real data | IMPROVE (`211.7.1`, `9kg.32`, `9kg.25`) |
| Whatever the later release added (an explicit confirmation step and a countersignature claim are reported) | UNKNOWN | — | VERIFY (U11, `dy7.4`) |

No feature a candidate or staff member relies on is dropped. Three are handled differently on purpose (owner notices,
the countersignature, the release act), two are not carried (CRM projection, the credential-delivery practice), and
three exist in v2 but stay disabled at launch by default (mailbox provisioning, link fetching, model advice).

## 5. Control ownership and wait states

### 5.1 Who controls what

: Control ownership at the internal launch.

| Effect | Catalyst v2 | Provider | Authorized person | Shared or note |
|---|---|---|---|---|
| Verification, question and reminder mail | sends, reconciles, blocks on bounce, pauses | the mail host accepts or bounces | staff approve questions; the owner approves templates | a pause stops v2's sends only; the provider retains nothing v2 controls |
| Signing request email | none (P4-D-14) | **Documenso sends** and may remind on its own schedule | the owner decides reminder settings in the provider | **shared**: a v2 pause does not stop provider reminders; the canary records the provider's behaviour and `cancel_envelope` is the stop |
| Signature acceptance | verifies by fresh read | **Documenso accepts** signatures after a v2 pause unless the envelope is cancelled | decision-maker cancels | **shared**: cancel is an external, reconciled action (P4-D-18); a pause for cause, a decline or a withdrawal must each trigger the cancel, and an uncertain cancel is a staff decision on the agreements screen (`9kg.47`) |
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
| Verification sent, unconfirmed | applicant | challenge lifetime (POL-02 value open); at expiry of the only link, a `verification_expired` staff item opens once (`9kg.66`, `016` section 10.17) | staff resend on the correspondence screen, bounded (`9kg.50`, built in PR #87); the resend resolves the expiry item | built; no age bound (the lifetime is the bound) |
| Question sent, awaiting reply | applicant | reminder cadence and maximum (POL-06 synthetic values), then `escalate_unanswered` to staff; after escalation, the staff item's age (`9kg.51`) | staff item | built; the post-escalation bound is `9kg.51` |
| Reply awaiting staff processing | staff | `aged_waits.replies_awaiting_processing` (`9kg.51`, built in PR #87; pages by default) | staff item | built |
| Reply unmatched, unverified, sender-mismatched, or on a closed application | staff | `aged_waits.open_staff_items` (`9kg.51`, built; audit only until the owner lists it) | staff exception item (the unmatched rule for a misdirected first-generation reply is `dy7.2`) | built |
| Uncertain send | worker, then staff | reconcile by Sent-folder read; unknown goes to a staff item | staff decide resend or abandon (decision-maker) | built against the fake, the read-only Sent reader and the mail-host allow-list included (`9kg.49`, `016` section 10.12a); the live proof is the mail canary |
| Mailbox cursor in resync, recovery or blocked; SMTP transport blocked | worker | health anomaly codes | staff item; the owner for a transport block | built; live proof in the mail canary |
| Hard bounce | staff | immediate block of every send | decision-maker recovery after the cause is addressed | built (`9kg.3`) |
| Paused (staff or system) | staff | shown with reason; `aged_waits.pauses` (`9kg.51`, built; application pauses only, audit only until listed) | resume by the right role; system pauses need review | built, with its database guard (`9kg.6`, workflow 0005) |
| Refused or capped assessment snapshot (at launch: refused by suspension) | staff | `aged_waits.assessing` (`9kg.51`) | the human-only decision form (`oc4.12`, built in PR #87 on `oc4.8`'s default; `CATALYST_CAPPED_EXIT`) | built |
| Awaiting decision | decision-maker | `aged_waits.awaiting_decision` (`9kg.51`, built; audit only until listed); the dossier flags it | decision screen | built; the authority is configuration and granted by the command (`9kg.30`, built in PR #87) |
| Declined | none (the worker sends the notice) | terminal; the notice waits, with a staff item, while its wording is not approved here | uncertain, failed and bounced notices reach staff items the decision-maker settles; withholding is a choice on the decision form (`oc4.11`, section 17.3) | built; the real wording is the owner's (`211.7.4`, `211.7.7`) |
| Agreement sent, awaiting signature or countersignature | applicant, then the owner (countersignature) | `aged_waits.issued_agreements` (`9kg.51`, built; pages by default; ages from the last status change) | the decision-maker cancels | built as a health bound; the agreements screen shows each agreement's last status change and age, and names the countersignature wait (`9kg.41`, appendix B) |
| Agreement held (recipient change, custody failure, expiry, rejection) | staff | staff item, pause | decision-maker reissues as a new instance | built |
| Provisioning held | the owner | released only by `activate_provisioning`; `aged_waits.held_followons` (`9kg.57`; with the held `send_decline` and `issue_nda`; audit only until listed) | the command | built (disabled at launch) |
| Provisioning unknown outcome, or provider unavailable at activation | worker, then staff | reconcile by read; never create again; `aged_waits.provisioning_activation` for the unavailable case (`9kg.51`, built; pages by default) | staff item | built against the fake |
| Withdrawal racing provisioning | worker | the withdrawal services cancel and revoke; unsupported checks stay unresolved | staff item | built against the fake |
| On hold | staff | `aged_waits.on_hold` (`9kg.51`, built; audit only until listed); the dossier flags it | the decision form: admit or decline (`9kg.50`, built in PR #87) | built |
| Uncertain Documenso create, distribute or cancel; template approval | decision-maker | staff item (links the agreements screen) | the agreements screen and the template screen (`9kg.47`, built in PR #87) | built |
| Restore hold | the owner | nothing runs until reconciliation | `catalyst_post_restore` review and lift | built, with erasure replay (`9kg.25`) and effect reconciliation (`9kg.33`) |

The bounds and whether each pages are the owner's values (`211.7.2`, `211.7.7`); the health part that counts aged
waits is `9kg.51` (`026` section 17). **Still unbounded after PR #87:** verification sent and unconfirmed (the
challenge lifetime is its only bound; since `9kg.66` its expiry opens a staff item), provisioning held (released only
by the owner's command; since `9kg.57` counted with the other held follow-ons in `aged_waits.held_followons`) and the
restore hold (lifted only by `catalyst_post_restore`); the agreement-sent row gained the health bound, and the agreements
screen shows its age (`9kg.41`); the stage, item and pause classes are counted but page only once the owner lists them.

**Found by the code inventory (2026-10-23, `45f8b93`), each a VERIFY turned into a task:**

- **Actions enqueued without a handler:** `send_decline` (held forever; fixed by `oc4.11`, section 17.3: a decline
  now queues it and `assessments.decline` runs it; held ones are cancelled), `interpret_reply` (held until staff cancel
  it, by design) and `provision` (released by `activate_provisioning`, by design). Unknown kinds are never claimed.
- **State changers reachable only from tests or a shell:** the decisions on an uncertain Documenso create,
  distribute or cancel (the only remedy for an unknown outcome), and agreement template approval (which
  `activate_agreements` requires): `9kg.47`. An application `on_hold` has no path back to a decision except closure,
  and no staff verification resend exists: `9kg.50`. Waits with no bound or anomaly (a sent agreement awaiting
  signature or countersignature, a reply awaiting staff processing, an application awaiting decision or on hold, a
  provider-unavailable `provision_activate`, a pause): `9kg.51`.
- **Grant paths:** only the read-only group and the three P2 groups have a command; every assessment, agreements and
  provisioning permission and the qualification-decision permission can be granted only in a shell (`9kg.30`).
- **Non-redeliverable kinds** end `uncertain` on exhaustion and go to staff: `send_message`, `send_staff_message`,
  `create_agreement`, `distribute_agreement`, `cancel_envelope`, `cancel_agreement`, `provision_create`,
  `provision_invite`, `provision_withdraw_send`. Every other kind ends `failed`.
- **Provider effects** are disabled by code-fixed empty settings plus the guards; the provider's reminder behaviour
  and `documentDeleted` email setting are NOT VERIFIED (the Documenso canary).

**Geographic review (`bgl.4`, 034 row 8).** Adopted residence and normalized phone values are
checked against the carried-forward human-review policy in `applications/geographic_review.py`.
The historical list is a conservative review trigger, not a current legal prohibition or an
automatic decline; a phone prefix does not establish residence. The form includes the four
historical residence-region choices, while phone countries retain their country/calling-code list.
The applicant receives the normal received page, receipt and verification flow. Once verified,
a matching case opens `sanctions_concern` for staff and reaches the human-only decision screen
without fetching evidence or calling the model, including when portfolio claims are absent.

Assessment enqueue, an already-queued assessment and reply-model admission all recheck the
adopted answers. An older successful model result cannot support an automatic or model-assisted
decision under a matching policy. Only the existing explicitly authorized decision-maker can
record the human-only disposition, with the normal rationale, snapshot and policy bindings; a
queue acknowledgement cannot release it. The recorded decision includes the review version and
signal categories, never a copied phone number. A later unverified submission cannot lift the
gate. The receipt and applicant pages never expose the review reason. This implementation does
not approve new legal policy or establish deployment/cutover readiness.

## 6. Recovery, retention and custody

### 6.1 Data classes and copies

: Data classes, where copies exist, and the treatment POL-10 must decide.

| Class | Where it lives | Copies | Immutable by design? | Treatment to decide (POL-10) |
|---|---|---|---|---|
| The application row (email, name), contact challenges, application events and their data | PostgreSQL | nightly dump; the host archive; the off-site leg | events yes | anonymize the identity columns with the audited exception (`9kg.32`); the email key becomes a unique tombstone |
| Submission versions and adoptions | PostgreSQL | nightly dump; the host archive; the off-site leg | yes (D-22, triggers) | anonymize personal fields with the audited exception (deletion is refused by the adoption key); keep the adoption record's existence |
| Mail derivatives: redacted inbound (no inbound body stored), outbound attempts with their frozen approved bodies and recipients, staff drafts, questions, reply links | PostgreSQL | dumps | partly (`9kg.1`; `9kg.5` open) | retention period; outbound frozen bodies and recipients are personal data and need the exception |
| The v2 mailbox itself (inbox with original messages; Sent copies) | the mail host | the provider's own backups | no | retention and deletion at the provider are part of POL-10 (`211.7.1`) |
| Staff item resolutions (note, effects), agreement recipients and details versions (POL-18 details: the most sensitive), provisioning reservations, evidence notes, credential-setup and withdrawal recipients, pending-action references and errors, pause rows | PostgreSQL | dumps | partly | per-table treatment in the erasure map; a catalog test keeps the map complete (`9kg.32`) |
| Qualification decisions and their rationale (the main real record at launch) | PostgreSQL | dumps | yes (append-only; the retention role cannot erase today) | POL-10 says whether they may be erased or only anonymized |
| Staff user rows and the backup manifest | PostgreSQL; the backup set | dumps; the archive | no | staff retention under POL-13; manifests hold no personal data |
| Model inputs and results | PostgreSQL (none at launch) | dumps | yes | none at launch |
| Staff notes, drafts, items and resolutions | PostgreSQL | dumps | resolutions yes | retention period |
| Evidence observations and digests | PostgreSQL | dumps | yes (no raw bytes, P3-D-13) | retention period |
| Signed documents | custody directory, sealed at rest under per-document keys (`9kg.34`); the keys in a key directory and its live mirror, outside the backup | the sealed custody copy in every backup set (no key in any); the provider's copy | yes | BUILT (`9kg.34`): registry row `signed_documents` takes `retain` or `destroy_key`; the location, access rule and key recovery are the owner's (`211.7.9`, `agreements/custody_policy.py`, shipped undecided); the provider's copy under P4-D-15 until POL-10 |
| Logs and receipts | host | the host archive | no | code-only by design (TEST-P6-13, 35) |
| Backups | the dump and custody set | the host archive, the off-site leg (object-locked) | by policy | the erasure record replayed on restore (`9kg.25`, built); object-locked copies age out, never purge one person |
| The effect journal (`9kg.33`): public references, opaque staff references, group names, codes, digests, counts and times; no address, name, body or username | the journal volume on the host, outside the backup | the host archive (the volume is the restore's evidence) | yes (append-only, hash-chained; the owner's repair journals itself) | retention and erasure treatment under POL-10 (`211.7.1`): the durable erasure record shares the file (`9kg.32`, section 6.2); kept at least as long as the oldest restorable backup (registry rows `erasure_record`, `effect_journal`) |
| Selection-review material | none in the repository (`f1u.4`) | private location to approve | — | `f1u.4` |
| Invitations (the email key, the issuer, the note, the recorded notice and invitation wording digests) | PostgreSQL | dumps; the host archive; the off-site leg | yes (trigger, `9kg.43`, `9kg.52`) | BUILT (`9kg.32`, class `invitations`): the email key becomes a unique tombstone and the note `[erased]` under the audited exception; issuer, times and digests kept; counsel decides the registry row (POL-10) |
| First-generation agreement-on-file records (the email key, the agreement version labels, the recorder) | PostgreSQL | dumps; the host archive; the off-site leg | yes (trigger, `9kg.52`) | BUILT (`9kg.32`, class `member_on_file`): the email key becomes a unique tombstone under the audited exception; the labels and the attestation kept as the reason a decline was never recorded; counsel decides the registry row (POL-10) |

### 6.2 The erasure design (`9kg.32`, `9kg.33`, `9kg.34` and `9kg.25` built)

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
- **Effects after the backup point** (`9kg.33`; built in PL batch item 4, recorded in `026` section 16): mail
  (Sent-folder read), envelopes (provider read by key), mailbox facts (provider read), closures and revocations,
  staff role changes, and model usage (preserve possibly spent usage), from a hash-chained effect journal outside
  the backup's rollback domain (`workflow/journal.py`), the same file the erasure record will use. Quarantined provider
  reads outside the post-restore transaction with per-effect staff items; the owner's manual exceptional resolution
  (`catalyst_post_restore --resolve`); the lift refuses while evidence is missing, a provider is unreachable or an
  effect item is open. Credentials are not readable at the host and are not reconciled: the review closes every open
  setup and staff reissue.
- **The journal's consistency model** (the PR #89 reviews). Three classes of effect: *journaled before commit*
  (`prepare`, then `done` after commit: the restrictive effects, a closure, a revocation outcome, a pause, a
  withdrawal, a staff role removal, where a prepare whose transaction then failed is replayed as done because a
  restriction re-applied is safe); *journaled after commit* (`on_commit`, robust: resolutions, reply outcomes,
  decisions on uncertain sends, approvals and confirmations, grants, model usage, where a crash between commit and
  append can lose an entry but never invent one); *covered by a provider read* (mail, with `send_begun` written
  after the database claim and before SMTP; envelopes; mailboxes). Three invariants: an entry at or below the
  backup's recorded seq is in the snapshot or is reconciled; a lift implies a journal whose identity and head match
  the receipt; an append failure is observable (a code-only log, a failure counter, a health signal, a readiness
  refusal). Deferred, as beads the main session files: a database-assigned version per key for replay ordering;
  off-host shipping of the journal with a head mirror and a lag alert (the journal's own RPO);
  an item per queued send with no copy instead of the blanket
  `--outward-checked`.
- **Journal segments and request-count cache** (`9kg.61`): owner-run `catalyst_journal_segments --rotate
  --confirm --segment-aware-recovery` closes the active file and starts the next with a `continues` entry naming
  the previous global sequence and hash. Every read verifies the complete chain across hot and archived segments;
  shipping exports the same flattened chain and existing backup anchors keep their meaning. A crash after the
  rename resumes that lineage, and repair moves aside only the active torn tail, never closed evidence.
  `--archive-receipts <json-array> --confirm --complete-backup-inventory` requires the operator's complete inventory
  of retained local and off-host backup receipts. Every anchor must verify; segments containing an anchor stay hot.
  Archival relocates files within the journal volume and retains them in reads and transfers. It never prunes history
  or makes a POL-10 retention decision. Daily request-count high-water marks use constant-size checkpoint/day files
  under the same lock; appends advance the checkpoint. Missing, stale or corrupt cache state rebuilds from the
  verified journal. This is request accounting, with no token cap or new production quota. Cache initialization,
  recovery and a day's first lookup can scan history; steady-state reads/updates do not. Full snapshots and restore
  verification still scan the chain. The first rotation writes a durable format marker: deploy/predeploy refuse
  images without segment support. Recovery readers must be verified before that activation. Production rotation
  and archival have **not** been performed by this repository change.
- **The effect registry** (`9kg.62`, built 2026-10-26): `workflow/effects.py` names each function that performs an
  effect a restore cannot undo, in seven families (journal writes, SMTP, Django mail, Documenso writes, MXroute
  writes, IMAP appends, model runs), with its class: journaled before, journaled after, provider read, checked before
  it acts, covered by the post-restore review, or a marker about the journal itself. Each non-journal class names the
  function that covers it. `tests/test_effect_registry.py` finds those calls in the source and fails on an
  unregistered or stale function, a class that does not match the calls, a journal entry written after the provider
  call it should precede in the same function, a check-first action that writes before it reads, a journal kind that
  is not resolvable or has no writer, a restrictive kind never prepared, a provider client write method the scanner
  does not know, or a new module that reaches the network, starts a process or writes a file. It does not check that
  a named reader reads what the entry claims, receivers held in attributes, or a database write that should be
  journaled and is not; those stay review judgements against the effect list above. Writing and reviewing it found:
  - the revocation's password rotation and forwarder removal run before the transaction that prepares
    `access_revocation`, so the journal does not cover them; the post-restore review's revocation round does
    (`config/post_restore.py`, step 4);
  - the contact-confirmation, password-setup and withdrawal mails go through Django's mailer, not
    `correspondence.transport`; the review supersedes every live link they carry (`close_outstanding_links`);
  - an envelope created after the backup for an agreement the restored database does not hold was read by
    nothing, so a restore could send the signer a second envelope. Built 2026-10-27 (`9kg.76`): the envelope read
    lists the team's documents from every template back to an hour before the backup's start and opens a
    `restore_effect_envelope` item, keyed by the envelope id, for each Catalyst-keyed envelope no restored row names.
    The listing fails closed: it ends only on a short page or past the floor, checks that creation times never
    increase, and a page limit reached, an order not kept or an unconfigured provider where agreements were used
    refuses the lift;
  - a restrictive `prepare` that cannot be written does not stop its effect: the failure is logged, counted and
    refused at readiness; only the erasure and custody records refuse their effect.
- **Custody** (`9kg.34`, built 2026-10-24; section 6.2.2 and `026` section 16): every custody document is sealed
  with AES-256-GCM from a reviewed library under its own data key, wrapped under one wrapping key; the wrapped keys
  live in a key directory and its live mirror, outside the database, the custody directory and every backup set; once
  a key is destroyed its document, in custody or in any backup, cannot be opened without a surviving copy of the wrapped key and the wrapping key. Recovery: the escrow holds the wrapping key only, and destruction
  reaches the mirror first. The approved storage location and access rule remain the owner's (`211.7.9`) and are
  configuration that refuses in a live environment while undecided. Disk encryption is not per-subject erasure.

#### 6.2.1 The erasure path as built (`9kg.32`, 2026-10-24; revised after the PR #99 reviews)

Council record `030` Q3 (D-51) set the shape: build the mechanism now, keep every value in a registry that ships
undecided, and refuse while anything is undecided. Counsel's POL-10 decision (`211.7.1`) then changes registry rows,
never the schema. The code is the `erasure` app. Nothing real can be erased or backed up yet: the registry is
undecided (until `9kg.25` built the replay after a restore, it also reported `replay:not_built`).

**The registry** (`erasure/registry.py`). One row per data class, each with a `treatment` and a `retention`, every
value `undecided`.

- Sixteen subject classes take `anonymize` or `retain`: `application_identity`, `submissions`, `history_events`,
  `mail_derivatives`, `staff_notes`, `agreement_records`, `decisions`, `evidence`, `provisioning_records`,
  `invitations`, `member_on_file`, `pauses`, `jobs`, `audit_residue`, `throttle_keys`, `admin_log`.
- `signed_documents` takes `retain` or `destroy_key` (`9kg.34`, section 6.2.2).
- `provider_copies` takes `manual_handoff`.
- `erasure_record` and `effect_journal` take `retain`, with a period at or above the oldest restorable backup.

`registry.problems()` blocks two further cases (a third, `replay:not_built`, went with `9kg.25`):

- anonymizing `application_identity` while retaining a class found only by the real key (`invitations`,
  `member_on_file`, `mail_derivatives`, `throttle_keys`), because those rows could never be found again;
- a treatment the mechanism does not support.

While any problem stands:

- a new erasure refuses (`registry_undecided`);
- `catalyst_backup` refuses in a live environment (`config.backup.refuse_real_backup_while_undecided`);
- health reports `backup.registry_blocked`.

The synthetic environments back up as before. Anonymization is the superset: an anonymized append-only row with a
tombstone key also satisfies a "delete" answer.

**The erasure map** (`erasure/catalog.py`). Every table and every column of the schema is classified as one of:

- a subject column, with its class and tombstone;
- staff data (POL-13, never part of an applicant's erasure);
- a secret (password hashes, token digests, device keys);
- non-personal.

`applications_applicationevent.created_txid` is non-personal and stays frozen on the erasure path. A catalog test
fails on any table or column the map does not name, and on any name the schema does not have.

Tombstones:

| Column kind | Tombstone |
|---|---|
| Text | `[erased]` |
| Low-entropy digests and deduplication keys | the empty string |
| JSON | empty JSON |
| The three email-key columns | `erased:<public uuid>`: never a real key, held unique by `applications` migration 0009 |
| The reserved mailbox name | `erased-<uuid>` |
| Rationale | notes replaced, ratings kept |
| The intake throttle bucket (an unkeyed digest of the email key) | the row is deleted |

A key counts as a tombstone only when it has the `erased:` prefix *and* no `@`.

The subject's rows are every application with the subject's email key, plus the rows keyed on the key itself
(invitations, the member-on-file record, mail from that address never associated with an application). A subject
whose key is already a tombstone is scoped by its own references; only the key-selected rows are skipped. So a class
or a step added later (`9kg.34`) still reaches an already-erased subject.

**The audited exception** (`erasure` migration 0002, the ADR-14 pattern).

`public.catalyst_erase(subject, authority, reason, classes)`:

- is SECURITY DEFINER, with EXECUTE for the retention role only and `search_path = pg_catalog, public, pg_temp`;
- locks the subject's applications in one transaction;
- refuses unless every application is terminal, nothing of theirs is queued, running, held or uncertain, and every
  access revocation is final;
- writes an `erasure_erasureaudit` row (codes and the public reference only; its transaction id, time and login set
  by trigger; append-only for every role);
- sets each anonymized class to its tombstones;
- reports the provider handoffs owed (`documenso`, `mail_sent`, `mail_inbox`, `mail_host_mailbox`, `model_provider`),
  what it retains (`custody_documents` when the subject has stored documents) and, since erasure migration 0003
  (`9kg.34`), the subject's custody key references and how many of its documents are still in the clear.

A run with nothing to change returns `nothing_to_erase` and writes nothing.

The model-provider handoff follows possible disclosure, not the existence of an assessment run
(`9kg.73`, erasure migration 0008). A queued or suspension-refused run with no reservation and no
recorded request owes no model-provider handoff. Positive assessment/clarification reservations,
recorded assessment requests and reply-interpretation reservations retain the handoff, including
abandoned calls whose provider outcome is uncertain. Reply-only calls count even without an
assessment run. Normal erasure and restore replay use the same rule; previously signed erasure
records are not rewritten by the migration.

The trigger branch:

- Every UPDATE trigger function on a table with subject columns gains one branch after its first BEGIN, by CREATE
  OR REPLACE of its own definition, removed by its begin and end markers on reverse. A test derived from
  `pg_trigger` keeps this complete.
- The branch admits an UPDATE only when all of these hold:
  - the session login is a member of the retention role;
  - an audit row carries the current transaction id (the agreements 0004 pattern);
  - every column outside the table's allow-list is unchanged (the 0015 compare, over the whole row);
  - every changed column equals its tombstone.

Which triggers move or keep their function:

- The strict-refusal row triggers on the retention audit, recipients, document accesses, resolutions and
  provisioning evidence move to `catalyst_erasable_append_only`: the same refusal, with the branch.
- Unchanged: the strict function itself, the adoption record's trigger (the adoption foreign key is untouched),
  every no-truncate trigger, and `catalyst_pause_resume_guard`.

A pause is anonymized, never deleted, so the DELETE guard keeps refusing on this path too. This is a deviation from
the PR #88 data-review note, argued in `026` section 16.

Grants:

- Nothing is granted to the application, fetcher or backup roles.
- The checker function is owner-only.

**The durable record** (`erasure/record.py`) lives in the effect journal (`workflow/journal.py`), outside the
rollback domain. It holds three entry kinds:

- `erasure_intent`, appended and fsynced before the transaction: the subject's HMAC, the key id, the authority and
  reason codes, the classes, the handoffs owed and what is retained.
- `erasure_complete`, after the transaction: `erased`, `already_erased`, `nothing_to_erase` or `refused_<code>`,
  and the number of values changed.
- `erasure_handoff`: the owner's completion of a provider deletion, dated with an ISO date that is not in the
  future (QA finding 12).

Each entry is keyed `erasure:<public reference>`, never a numeric id. `subject` is HMAC-SHA-256 of the normalized
email key under `CATALYST_ERASURE_KEY`. Every entry carries a `mac` under the same key over its kind, key and data:
an entry that does not verify is ignored when folded and refused by verification.

**Key custody.** The key's source of truth is the operator's encrypted secret store; it is in no backup set. It is
mounted as a secret file (`erasure_key` in `CATALYST_SECRETS_DIR`) only into the erasure command's process and the
restore's replay. It is at least 32 characters and distinct from the Django and link-signing keys. A web or worker
process that holds it refuses to start. It is never in the database, the journal, a receipt or a log, and the record
names it only by a 16-hex key id. The database audit row carries no hash.

**Retry and resume.**

- The command first runs the function in a rolled-back transaction, so a refusal comes before any record.
- Then it writes the intent, commits the transaction and writes the completion.
- The next run resumes an open intent, without the registry gate (an erasure already begun is finished). It uses the
  classes of the registry in force and this run's authority and reason, and takes only the hash and key id from the
  intent. While the row still holds a real key, the hash must match it.
- A second erasure finds nothing to change and writes nothing.

**Integrity, freshness, an emptied store.**

- After every erasure and handoff, the command prints the journal head (`<identity>:<seq>:<hash>`).
- The owner copies that head and the subject's erasure entries to an off-host private store. The owner names the
  store; that is an open owner action, recorded in `026` section 16.
- `catalyst_erasure_record --expect-head` checks the chain, every mac, and the head (seq 1 or later). It refuses an
  emptied, replaced or rolled-back journal (`journal_mismatch`, never "no erasures"), and reports open intents, owed
  handoffs and retained items.
- `--list-open` needs no head, so an interrupted first erasure is visible.
- Health reports `erasure.intent_open` and `erasure.handoff_owed`.

**The restore's resurrection guard** (until `9kg.25`; replaced by the replay below). While no replay existed and the
journal held any erasure entry, the post-restore review opened `restore_effect_erasure_unreplayed` and the lift
refused outright.

**Never web or worker.** No view or job reaches the erasure, and the command refuses in a web or worker process.
Stated limit: the retention login can call `catalyst_erase` directly. That would skip the durable record, so the
operating rule is that the function is called only through the command, and only on the host's erase service
(`026` section 16). Replay (`9kg.25`) is the one other caller.

**Replay after a restore, as built (`9kg.25`, 2026-10-26; `026` section 16 has the operations record).**

1. The order: restore, migrate, replay (`catalyst_erasure_replay --expect-head <head>`, the retention login and the
   erasure key), review, lift.
2. The replay verifies the record against the out-of-band head (`erasure.record.verify`) and reads
   `erasure.record.fold(journal.read(), key)`, mac-verified: per public reference, the last intent and its
   completion.
3. For every erased completion and every open intent, it calls `public.catalyst_erase_replay` (erasure 0004) with
   the classes of the registry in force and the intent's authority and reason. This is the erase function without
   its refusals for an open application, work in flight and an unfinished revocation, because the restored rows
   predate the closure. It runs only under the restore hold, which only the restore's load or the owner can place
   (workflow 0006). The handoff named `public.catalyst_erase` here; the refusals made that impossible on the usual
   restore. The replay also matches the recorded subject hash across restored applications, invitations and member
   records (invited before the backup, erased after it), and a restored key that does not hash to the record refuses
   before anything is erased.
4. `unknown_subject` (a subject created after the backup) counts as satisfied.
5. It ends with an `erasures_replayed` marker, with its mac, bound to the restore and to the last erasure entry. The
   review and the lift both refuse until a marker written since the hold was placed covers every erasure entry, so
   the out-of-band head was checked and an erasure made during the hold needs another replay. The lift verifies the
   marker's mac; the review, which reads the providers, holds no key.
6. The review settles what the refusals guarded: the work of erased subjects is cancelled, and a subject still open
   or with an unfinished revocation after the journal's replay gets a `restore_effect_erased_subject_open` item.
7. `REPLAY_BUILT` and `replay:not_built` are removed; a live backup still waits for POL-10's decided registry.

Class names are append-only: a renamed class would orphan recorded intents.

**What `9kg.34` (custody) needed, as built** (section 6.2.2):

- a destruction treatment, `destroy_key`, on the `signed_documents` row;
- a key-destruction step reachable for an already-tombstoned subject: the function names the key references and the
  command destroys the keys;
- no trigger branch on `agreements_storeddocument`: no column changes (the keys are outside the database);
- the keys outside the backup's rollback domain.

Under `retain` the custody PDFs stay, and the erasure says so (`retained: ["custody_documents"]`); under
`destroy_key` they stay sealed, and the erasure counts `keys_destroyed`. They are unreadable unless a copy of the wrapped
key survives with the wrapping key: an archived key directory, unlinked blocks, swap or a core dump (the limits below).

**Owner decisions recorded, not built.**

- **Reissuing a mailbox name.** May a released mailbox name be reissued after erasure while the provider mailbox
  still exists? The default is to keep it reserved. As built, the reservation row stays unreleased with its name
  tombstoned, which frees the real name in the live-name index; keeping the real name reserved needs a keyed
  blocklist (`9kg.28`).
- **Pauses and held work.** Does a pause with held work outrank an erasure request? The default, as built: refuse
  until the work settles.
- **The `audit_residue` treatment:** counsel.

**Limits.**

- Provider-held copies (the Documenso copy, the mail host's Sent and inbox folders, a provisioned mailbox, a model
  provider's retention) are not deleted by code: each is a recorded manual handoff.
- Backups are not a handoff. Existing sets keep the data until they age out, and the replay prevents its return.
- The effect journal's off-host copy and rotation stay deferred (section 6.2 above).
- The admin log is anonymized only for the application's own rows.
- After an erasure the owner runs `VACUUM` on the touched tables, so the old row versions leave the data files.
- As for every ADR-14 guard, the owner can replace these functions and a superuser bypasses them.

#### 6.2.2 Custody encrypted at rest (`9kg.34`, 2026-10-24)

Council record `030` Q3 and Q4 (D-51) set the shape: build now as repo-only work; keys held outside the application
backup's rollback domain; encryption before the Documenso canary; key destruction in the erasure map. The design is
in `agreements/keystore.py`; the operations record, the drill and the evidence are in `026` section 16.

**Encryption.** The reviewed `cryptography` library's AES-256-GCM, nothing bespoke. Each document has its own random
256-bit data key, stored only wrapped under the wrapping key. The sealed file binds its own name and key reference.
A `CustodyEnvelope` row (insert-only) names the sealed file, the key reference and the sealed bytes' digest and size.
`StoredDocument.sha256` is still the plaintext's hash, checked after opening. A write refuses without keys, in every
environment.

Envelope rules (data review of PR #102, K5): one envelope per document; no repair or re-seal until wrapping-key
rotation is built (a follow-up); `wrapping_key_id` is the wrapping key's id at seal time; an envelope not `migrated`
names the document's own file; the database checks the digest and the key reference as hex.

**Keys outside the rollback domain.** The wrapped keys live in `CATALYST_CUSTODY_KEY_DIR` and its live mirror
`CATALYST_CUSTODY_KEY_MIRROR_DIR`, never in the database or the custody directory:

- the backup copies neither, by construction (the set holds only table copies and the custody files its snapshot
  names);
- the guards refuse a key directory inside or around the custody directory, the journal or the repository;
- the backup refuses to hold the wrapping key or to overlap a key directory.

A restore of an older backup therefore brings back rows and sealed files, never a key; a destroyed subject's
document then cannot be opened without a surviving copy of the wrapped key and the wrapping key. The key directories carry provisioning markers and fail closed when missing; `keystore.sweep()`
finishes every journaled destruction at the restore lift and at the web and worker start-up. The backup's overlap check
and the role isolation below are configured, not enforced, until `9kg.28` wires the host (`026` section 16).

**Who holds the wrapping key** (`custody_wrapping_key`, a secret file of 64 hex characters, distinct from every other
key):

- the web process (retrieval, decision-makers only, P4-D-16), the worker (custody writes) and the owner-run custody
  commands may hold it;
- the fetcher and the post-restore step refuse to start with it;
- `catalyst_backup` and `catalyst_erase` refuse to run with it.

**Recovery that cannot defeat destruction.**

- The escrow holds the wrapping key only; recovering it alone does not recover a destroyed data key.
- The mirror is a live copy that destruction reaches first, never a point-in-time one.
- `catalyst_custody_keys --recover --expect-head <head>` (the named holder, holding the erasure key) re-aligns the two
  from the copy that survives, never restoring a key the journal records as destroyed, and finishes any half-done
  destruction. It refuses unless the journal holds the head kept out of band (PR #99) and every destruction entry's
  mac verifies under the erasure key.
- Neither key directory may be in a versioned backup (an operator rule for the `9kg.28` host list).

**The erasure step.** Under `destroy_key`:

- the subject's keys are destroyed after the database transaction and before the completion, each journaled
  (`custody_key_destroyed`) before its files are unlinked, mirror first;
- the completion counts `keys_destroyed`, and `custody_documents` leaves `retained`;
- a subject with a document still in the clear is refused before any record;
- the committed call's own count of documents in the clear is checked again on every run, the resumed one included
  (`custody_plaintext_unmigrated_after_commit`, intent left open), and a lingering migrated plaintext or a missing key
  directory refuses before any record;
- `keys_destroyed` counts references verified gone from both directories, `key_files_removed` the files;
- an interrupted destruction is finished by the next run or by recovery.

**The declared record of a key destruction** (data review of PR #102, K4). The effect journal is the record:
each destruction is a `custody_key_destroyed` entry with its mac, and the completion carries `custody:
keys_destroyed` with the number of references verified gone. The database audit row is not the record of this step:

- on a first erasure under `destroy_key` it lists the class `custody_keys_destroyed` beside the anonymized classes;
- on a later erasure of an already-tombstoned subject (the keys destroyed after an earlier erasure under `retain`) the
  function changes no row, its audit row rolls back, and the journal alone records the destruction.

No new table is added for it.

**What `9kg.25` (replay) needed from custody, as built:** nothing to replay. A destroyed key is outside the rollback domain, so a
restored row already points at a sealed file that cannot be opened without a surviving copy of the wrapped key and the wrapping key. The hook: the journal's `custody_key_destroyed` entries
name every destroyed key, if replay ever needs to report them.

**Migration.** `catalyst_custody_keys --migrate --confirm` seals each document stored in the clear before this change,
verifies it, commits its envelope and removes the plaintext; `--status` reports what remains.

**Owner decisions left open (`211.7.9`).** These are rows of `agreements/custody_policy.py`, shipped `undecided`; a
live environment refuses custody while any is open:

- the location;
- the access rule (D-51 proposes decision-makers only);
- the recovery holder and time bound (proposed: the owner, within 24 hours);
- the escrow location (proposed: the estate's encrypted secret store);
- the provider copy's treatment, with POL-10.

**Limits.** A surviving copy of a wrapped key plus the wrapping key opens a destroyed document. Such a copy can
survive as:

- a stray archive or snapshot of a key directory;
- unlinked blocks not yet reused (on SSDs and copy-on-write filesystems no overwrite reliably scrubs them);
- a key in swap or a core dump.

The only way to retire such remnants is to rotate the wrapping key, then destroy the old one everywhere, the escrow
included. Rotation is a follow-up. The recovery runbook and the deploy order are in `026` section 16.

**Scope.** The claim covers v2's custody copy only; the provider's copy is under P4-D-15 until POL-10, and every
custody command and the erasure output say so.

## 7. Launch manifest (to be approved at `9kg.31.6`)

: The proposed launch manifest.

| Item | Proposal | Decision |
|---|---|---|
| Cohort | the owner, then named internal team members by invitation; list kept in the private operations record | `211.7.6`, `9kg.31.6` |
| Entry | a dedicated v2 host name; invitation mode on (`9kg.43`); public entry on the learning host unchanged | `211.7.3` |
| Verification mail, questions, reminders, inbound collection | ENABLED on v2's own mailbox after the Sent reader and production allow-list exist (`9kg.49`) and the mail canary passes, with the cohort's templates, lifetimes and cadence decided | `211.7.7`, `9kg.49`, `9kg.31.1` |
| Model advice | DISABLED; human-only assessment recorded (`oc4.12`) | `211.7.4` (data use) |
| Qualification decision | ENABLED; the owner is the decision group, decided for the cohort under POL-05 (P3-D-9 was synthetic only) | `211.7.8`, `9kg.30` |
| Decline notice | ENABLED through `oc4.11` (built, section 17.3) once the owner approves real wording; until then a live environment refuses the placeholder and the notice waits with a staff item, so the approved template gates the go/no-go | `211.7.4`, `211.7.7` |
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
| Model advice | disabled | model requests disabled in code; no live branch; the live-call protections and the approval check are built (`oc4.9`) | `oc4.7`, a recorded `approve_model_use` approval, data-use approval |
| CRM or other projections | not applicable | none exists | a separate scope decision |

Fake-model tests are not real-model quality evidence: nothing in the P3 synthetic evidence says anything about the
model's quality or its prompt-injection behaviour, and the go/no-go package must not read it that way.

### 9.2 Improvements, ranked

- **Must fix before the first live internal cohort:** the erasure path and replay (`9kg.32`, `9kg.25`), effect
  reconciliation after restore (`9kg.33`), custody encryption (`9kg.34`), the GitHub protections (`9kg.35`), the
  receipt and pre-deploy-backup gates (`9kg.37`), the N+1 revert drill (`9kg.38`), invitation mode (`9kg.43`), rate
  limits (`9kg.29`), the staff permission command (`9kg.30`), the decline notice (`oc4.11`), the human-only path
  (`oc4.12`), the pause-row guard (`9kg.6`), the provenance freezes (`9kg.5`), the narrowed test credentials
  (`6hl.10`), the personal-data scan (`9kg.40`), the agreements screens for the shell-only states (`9kg.47`), the
  on-hold exit and verification resend (`9kg.50`), the aged-waits bounds (`9kg.51`), the live Sent reader and mail
  allow-list (`9kg.49`), the screen walkthrough (`9kg.41`), the evidence register (`9kg.44`).
- **Required only if a capability is enabled:** the three canaries; `9kg.39` for fetching; `oc4.9` and `oc4.7` for
  the model.
- **Small usability improvements that fit a planned slice:** dossier labels for policy-held actions and stale help
  text (in `9kg.41`); the `P6_LIVE` comment fix (in `9kg.44`).
- **Post-launch or explicit non-goals:** the hourly read-only reconcile as a host timer (noted on `9kg.28`); an owner
  digest; CRM projection; automated countersignature; the targeted CI lane (`9kg.45`); lint (`9kg.46`); any LMS,
  roster, GitHub or chat integration (non-goals unless the owner decides otherwise).

## 10. Operations proposals for the owner (POL-16)

Everything in this section is a proposal for the owner's values (`211.7.2`); nothing here is a commitment until
recorded.

- **RPO.** Proposed: one nightly dump plus a pre-deploy dump (P6-D-7), so the worst-case data loss window is one
  day of ledger writes. External effects in that window are detectable by reconciliation (`9kg.33`), which cannot
  unsend or recreate them; applicant submissions in the window are lost unless re-submitted. A host loss has a
  separate, longer window because the off-site copy lags the dump; the preflight states it. A shorter cadence is a
  later decision once the volume is known.
- **RTO.** Proposed: four hours from the decision to restore to a serving, reconciled system for the internal
  cohort, including erasure replay and effect reconciliation, measured in the production restore drill
  (`9kg.31.5`); the 62 to 63 second dev-box figure is a mechanism proof in a disposable container and covers no
  DNS, certificate, secrets or network rebuild.
- **Realistic-volume proof.** At launch the production archive is nearly empty, so its real size proves little.
  The drill restores a seeded synthetic dataset scaled to the owner's twelve-month volume estimate, times the
  database restore and the custody copy, and extrapolates; a backup growth and capacity check is part of the
  preflight and the nightly receipt. No load-testing platform.
- **Paging.** High and urgent findings page (worker dead, collector dead, backup failed or stale, restore drill
  overdue, an uncertain send unresolved beyond the bound the owner sets, custody failure); routine findings are
  audit-logged; messages carry codes only, never content. The alert floor drops an exact repeat permanently, so a
  persisting condition must vary its message (an age or count) to page again. Values are the owner's (`211.7.2`).
- **Incident ownership.** Proposed: the owner, with a deputy the owner names for the observation period.
- **Abort thresholds (observation period).** Proposed: any duplicate external effect, any personal data in a log
  or receipt, any security event (an unauthorized access, a refused control bypassed, or a secret exposed), or two
  blocked journeys without a staff recovery path ends the exercise and pauses the stack.

## 11. The go/no-go package and the observation period

The package (`9kg.31.4` drafts it; `9kg.31.6` decides) names:

1. the exact release commit and image digest, and the effective repository controls (readback);
2. the target, routes, cohort, staff roles and enabled features;
3. the approved policies and notices for the actual data and use;
4. the backup, restore, erasure and reconciliation evidence, including the live-chain custody drill (`9kg.34`): the
   custody key directories shown absent from every backup set, the off-site object-locked copy included, and a
   restore of a set taken before a key's destruction shown unable to open that document (the repository drill
   cannot reach the off-site leg; `026` section 16);
5. the canary evidence and the agreement versions;
6. the remaining disabled capabilities and their verified enforcement (and the statement that no synthetic
   assessment evidence is model-quality evidence);
7. the operators, the support and recovery procedure (including the owner's restore runbook), the abort thresholds
   and the rollback limits.

Items 4 to 6 exist only after the drills and canaries, so the draft at `9kg.31.4` marks them pending and a final
completeness review after the canaries is an input to `9kg.31.6`.

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
| U3 | The completion gate's webhook route, secret name and allowlist; whether the installed instance behaves as the public source at v2.21.1 (every enabled team webhook fired for every envelope of the team); whether a second team can be created on the installed instance; whether the gate's and the countersign step's tokens are team-scoped | the gate source in the estate repository; the provider's team settings, read-only; then the canary | `9kg.42`, `9kg.31.2` | `dy7.2`, D-B |
| U4 | Whether the countersign sweep could match v2 envelopes (templates, namespace) | the sweep's installed configuration names, no values | `9kg.42` | `dy7.2` |
| U5 | Whether anything else reads the first-generation mailbox; whether its two sender settings are equal | the mailbox's forwarder and filter list; a yes or no from the operator | the owner | `211.7.3` |
| U6 | The mail host's real capability for the set-password flow and for suspend or session revocation | the provider's API document, then the canary | `9kg.31.3` | enabling provisioning |
| U7 | Whether the provider emails the owner on completion of a v2 envelope | the team email settings, read-only | `9kg.31.2` | — |
| U8 | The existing-member population: who already holds a mailbox, signed agreements, a first-generation case | the owner's private roster; aggregate counts only | the owner | `211.7.6`, `dy7.2` |
| U9 | The applicable retention periods and erasure promises in the privacy texts and agreements | the legal texts, read by the owner and counsel | `211.7.1` | `9kg.32` |
| U10 | Whether custody document keys embed personal data; whether the host backup exclusions cover the secret files and the custody key material; free ports and the installed proxy modules | the preflight | `9kg.42` | `9kg.28`, `9kg.34` |
| U11 | What the first-generation service's later release changed (an explicit confirmation step and a countersignature claim are reported) | a read of that release's tree (a separate narrow assignment) | the owner authorizes | compatibility facts only |
| U12 | Whether the first-generation service's operator-run timers outside the host still run, and what each sends | the timer list and the estate automation inventory | the owner | `dy7.2` |
| U13 | After a restore, an envelope or a mailbox created after the backup for an applicant who was also created after the backup: the restored tables hold no row to read against, so the post-restore provider reads cannot find it (`9kg.33`, `026` section 16) | the provider listing over the window by template, and the mail host's domain listing, compared with the restored population; an owner read at the drill | the owner, at each production restore | release of restored records (the lift's `--outward-checked` covers it by hand) |

Missing evidence about an enabled critical step blocks that step's readiness claim; it does not block the repo-only
work.

## 13. The work graph (as it exists in Beads)

> **Status note (2026-10-26).** This section records the graph as planned on 2026-10-23; Beads holds the current
> state. Since then the following merged: `9kg.43`, `9kg.29`, `9kg.37`, `9kg.38`, `9kg.30`, `oc4.12`, `9kg.33`,
> `9kg.6`, `9kg.5`, `9kg.32`, `9kg.34`, `oc4.9`, `oc4.10`, `oc4.11`, `9kg.39` and `9kg.25` (PR #103). Council `030`
> (D-51) removed the POL-10 and POL-09 edges in front of `9kg.32`, `9kg.34` and `9kg.25`; they were built before those
> decisions, with every value shipped undecided, so the "after POL-10" labels in 13.1 and the arrows in 13.2 are
> history. D-51 is the council's provisional adoption (`030`), not the owner's ratification. Merged later the same day: `9kg.69` (PR #104), `9kg.70` (#105), `9kg.60` (#106) and `9kg.72`
> (#107), with the drill evidence and the residual host items on each bead. New beads from the 2026-10-26 reconciliation: `9kg.31.11` (admit `production` in code;
> blocks the dark deploy), `9kg.72` (name an invited-only person for erasure; blocks the go/no-go), `9kg.73`, `9kg.74`
> and `9kg.71` (follow-ups). The owner decision package is `031`, the release-control readback and host requests are
> `032`, and readiness by boundary is in `006`. The "new" and "reused" column says how a bead entered this plan, not
> its state.

Epics reused: P6 `9kg`, PL `dy7`, P3 `oc4`, selection quality `f1u`, policies `211.7`. One new feature bead,
`9kg.31`, is the launch milestone. Authority classes: repo-only; GitHub-admin; target-host read; target-host write;
provider canary; real-data action; launch; wider enrollment; policy. An authority label is not permission.

**Roles.** Unless a bead's "Roles:" note says otherwise: the implementer of a repo-only bead is Claude Code in a
released handoff; the implementer of a GitHub-admin, host, provider, launch or policy bead is the owner (or Claude
Code only under a recorded go); the reviewer is the named specialist agent for that domain (data, operator screens,
correspondence, agreements, release operations, security and privacy, evaluation, independent QA); the approver is
always the owner. Every bead created or updated by this handoff carries its own "Roles:" note.

### 13.1 Beads

: The work graph: bead, status, purpose, earliest boundary, authority.

| Bead | Status | Purpose (plain English) | Earliest boundary it blocks | Authority |
|---|---|---|---|---|
| `dy7.1` | new, in progress | this plan | — | repo-only |
| `dy7.2` | new | the ownership register and the cross-system guards (one writer per case, mailbox, envelope, callback) | the launch manifest | repo-only (provider actions in their own beads) |
| `dy7.3` | new | the rehearsal against the live baseline (needs the prepared host, `9kg.28`) | any routing change, and the deployment | target-host read, then write (awaits a go) |
| `dy7.4` | new (audit 2026-10-23) | the approval-gated legacy evidence packet for U5, U11 and U12 (other readers of the first-generation mailbox, its operator-run timers, its later release), one analyst question at a time | the ownership register (`dy7.2`) and the coexistence decision | target-host read plus an operator answer (awaits a go) |
| `9kg.42` | new | the read-only production-host preflight | host preparation | target-host read (awaits a go) |
| `9kg.28` | updated | host preparation: secrets, database access, backups, timers, the force-command | the dark deploy | target-host write (awaits a go) |
| `9kg.43` | new | invitation-only intake, server-side | the internal launch | repo-only |
| `9kg.29` | updated | rate limits on every public endpoint with correct proxy identity | the internal launch | repo-only |
| `9kg.30` | updated | the staff permission command | release preparation | repo-only |
| `9kg.5`, `9kg.6`, `6hl.10` | reused | provenance freezes, the pause-row guard, narrowed test credentials | release preparation | repo-only |
| `oc4.11` | updated | the decline notice | release preparation | repo-only (template is a decision) |
| `oc4.12` | new | the human-only assessment path | release preparation | repo-only |
| `oc4.8` | reused, title labelled | the capped-snapshot exit decision; `oc4.12` builds on its recommended default and does not wait for it | none (a later value change needs no redesign) | policy (owner) |
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
| `9kg.41` | new | the screen and exceptional-state walkthrough (after `9kg.47`, `9kg.50`, `9kg.51`) | the go/no-go package | repo-only |
| `9kg.47` | new, split 2026-10-23 | the agreements screens for the shell-only states (uncertain Documenso create, distribute and cancel decisions; template approval) | release preparation | repo-only |
| `9kg.50` | new (audit 2026-10-23) | the on-hold exit through the decision service and a staff verification resend | release preparation | repo-only |
| `9kg.51` | new (audit 2026-10-23) | the aged-waits health part and page thresholds for every unbounded wait | release preparation | repo-only |
| `9kg.49` | new (audit 2026-10-23) | the read-only Sent-folder evidence source and the production mail-host allow-list, without which no uncertain send can be settled live | the mail canary; release preparation | repo-only |
| `9kg.48` | new (audit 2026-10-23) | the package version aligned with `version.txt`; the docs job's one unpinned dependency hash-pinned | none (not a launch blocker) | repo-only |
| `9kg.44` | new | the machine-checkable evidence register | the go/no-go package | repo-only |
| `9kg.45`, `9kg.46` | new | CI profiling and lane; scoped lint | none | repo-only |
| `211.7.1` to `211.7.9` | new (split) | POL-10; POL-16; POL-15 coexistence; POL-07/08/17 legal and model data use; POL-13/14 staff; POL-11/12 welcome and existing members; POL-02/06 lifetimes and templates; POL-05/03/18 authority, form fields and details; POL-09 custody | see each; all block the go/no-go | policy (owner, counsel) |
| `9kg.31` | new feature | the launch milestone (its last two children run after launch, so it closes with the wider-enrollment decision); it carries no order edge of its own, since `9kg.31.6` already waits on `dy7.2` | — | launch |
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
211.7.1 POL-10 ──► 9kg.32 erasure ──► 9kg.25 replay ◄── 9kg.34 custody ◄── 211.7.9 POL-09
                                          │                   │
repo-only batch (9kg.37, .38, .43, .29,   │                   │        9kg.35 admin (owner go) ──► 9kg.36
 .30, .47, .50, .51, .49, oc4.12, 9kg.33, │                   │              │
 .44, .40, .5, .6, 6hl.10, then .41)      ▼                   ▼              ▼
   └──────────────────────────────────► 9kg.31.4 release prep ◄── oc4.11 ◄── 211.7.4
                                                │
211.7.3 coexist ─┬─► 9kg.28 host prep ◄── 9kg.42 preflight (owner go)
211.7.5 staff ───┘        │                     │
                          ▼                     ▼
                   9kg.31.5 dark deploy    dy7.2 register ◄── dy7.4 packet (owner go)
                          │                     │
                          │              dy7.3 rehearsal (owner go) ◄── 9kg.28
                          ▼                     │
          canaries 9kg.31.1 (◄ 9kg.49), 9kg.31.2 (◄ dy7.3, dy7.2), 9kg.31.3 (◄ 211.7.6)
                          │
211.7.2, .6, .7, .8 ──────┴─► 9kg.31.6 GO/NO-GO ◄── dy7.3, 9kg.33
                                     │
                              9kg.31.7 deploy ─► 9kg.31.8 verify ─► 9kg.31.9 ─► 9kg.31.10
```

**Critical path to the first internal launch (serial, not parallel):** the POL-10 and POL-09 decisions → the
erasure path → custody encryption → erasure replay → release preparation (which also waits on the whole repo-only
batch, the decline notice and the GitHub protections) → the dark deploy of that attested digest (which waits on
host preparation, which waits on the preflight, the coexistence and staff decisions and the admin step) → the three
canaries from the dark stack (the Documenso canary also waits on the ownership register, the legacy evidence packet
and the rehearsal) → the go/no-go, which also waits on the remaining policy decisions and the rehearsal. Four owner
goes sit on the path (the protections, the preflight, the packet, the rehearsal) before the canaries' own goes. The
longest build is the erasure chain; the repo-only batch runs beside it. A digest that was never drilled with
erasure, replay, reconciliation and custody encryption cannot reach the go/no-go.

**Council amendments to the path (2026-10-23, `030` Q3, Q9 and Q10; D-51).** The erasure chain (`9kg.33`, then
`9kg.32`, `9kg.34`, `9kg.25`) is built now as repo-only work beside the batch, with every retention value shipped
as "undecided: refuse"; POL-10 and POL-09 move from gating the code to gating the first real submission and the
go/no-go. Under the host go, the production host is proved first: the preflight, host preparation, a dark deploy of
the current attested `main` digest with every activation held, the production restore drill (RPO and RTO
measured) and the rehearsal; the launch candidate is then released (`9kg.31.4`, after the batch's last migration
and the screen walkthrough `9kg.41`) and redeployed through the drilled wrapper. The remaining goes are three: the
host lane, the provider canaries, and the launch. The protections (`9kg.35`) are applied by the owner's own hand
from a prepared script before any deploy credential, with a scoped agent token from that moment.

### 13.3 The first ready repo-only batch (bounded authorization)

Independent of every host and provider action, and small enough for one release. Three items proceed on the
recommended default of a decision rather than wait for it: `9kg.37` (D-I, the receipt as a gate), `9kg.30` (the P3
to P5 role names, decided for P2 only by D-30) and `oc4.12` (`oc4.8`, the capped-snapshot exit); each records the
default it built on, and the owner's later decision can change a value without redesign.

1. `9kg.29` rate limits (lands the client-identity helper first), then `9kg.43` invitation mode (both intake-facing);
2. `9kg.37` receipt and backup gates; `9kg.38` the N+1 revert drill (both deploy-wrapper drills);
3. `9kg.30` the staff permission command; `9kg.47` the agreements screens for the shell-only states; `9kg.50` the
   on-hold exit and verification resend; `9kg.51` the aged-waits bounds; `oc4.12` the human-only path;
4. `9kg.33` effect reconciliation after restore (fakes only; it defines the durable journal `9kg.32` reuses);
   `9kg.49` the Sent reader and mail allow-list;
5. `9kg.44` the evidence register; `9kg.40` the personal-data scan; `9kg.6` the pause-row guard;
6. `9kg.5` the provenance freezes; `6hl.10` the narrowed test credentials; then `9kg.41` the screen walkthrough,
   which becomes ready once `9kg.47`, `9kg.50` and `9kg.51` land (all block release preparation `9kg.31.4` and are
   on the must-fix list of section 9.2).

Ready but deliberately outside this batch: `9kg.39` (only if fetching is enabled), `9kg.45`, `9kg.46` and `9kg.48`
(not launch blockers), `oc4.9` and `oc4.10` (`oc4.12` fixes `oc4.10` items 2 and 3 and records item 1; both were
built together afterwards, `018` section 21), and the
decision and approval-gated beads, whose titles say so. The epics, the policy register `211.7` and the milestone
`9kg.31` also appear as ready because they have no blocker of their own; they are containers, not claimable work.

Subsequent batches, each separately authorized: **GitHub-admin** (`9kg.35`, then `9kg.36`); **host** (`9kg.42`,
then `9kg.28`, `9kg.31.5`, `dy7.3`); **legacy evidence** (`dy7.4`, which feeds `dy7.2`); **provider canaries** from
the dark stack (`9kg.31.1` to `.3`); **after POL-10 and POL-09** (`9kg.32`, `9kg.25`, `9kg.34`).

### 13.4 Batch item 1 as built: rate limits and invitation-only intake (`9kg.29`, `9kg.43`)

Built 2026-10-23 under the section 13.3 authorization; repo-only, synthetic data, nothing deployed. The decisions
recorded here are the implementer's defaults on the Django review of 2026-10-23; the owner's values (POL-16) replace
the placeholders without redesign.

- **Client identity** (`config.client_identity`): one value from one place, selected by `CATALYST_CLIENT_IDENTITY`,
  fixed in code: `proxy` reads `X-Forwarded-For`, which the proxy overwrites with the peer address and trusts from no
  one (section 4.6; `026` section 8), so the header is trusted because the web process listens only on the proxy's
  socket; `direct` (test and development only) reads the peer. The value must be exactly one address literal: a list,
  a blank or anything else is "no identity", and issuance is then refused. IPv4 buckets by address, IPv6 by its /64.
  The guards refuse any other value, an environment-sourced value, and `direct` outside the local environments.
- **Store** (`config.throttle`, `accounts.RequestThrottle`): a PostgreSQL table in the login-throttle pattern (hashed
  key, fixed window, an F() increment under the row lock, the database clock, swept hourly with the staff sessions).
  Chosen over a cache throttle because no cache backend is configured and a process-local counter would count per
  worker process. Only `sha256(scope:value)` is stored: never a client address, an address key or a token.
- **Buckets and refusal**: intake per client and per hashed address key (the address bucket limits verification
  issuance only, never confirmation, so it cannot lock the holder out of a link they have); confirmation, password
  setup and withdrawal per client and per token, on reads and writes; the webhook per client, before the secret is
  compared. One 429 page for every endpoint and every bucket, so which bucket refused and whether an address or token
  is known cannot be read from it; a refused request does not extend the window. The store unavailable or the
  identity missing fails closed for issuance (503) and open for reading. The limits are `CATALYST_THROTTLE_*`
  settings (window, intake per client and per address, link per client and per token, webhook per client) with
  synthetic placeholders.
- **Invitation mode** (`applications.invitations`, `applications.Invitation`, `manage.py catalyst_invite`):
  `CATALYST_INTAKE_MODE` is fixed in code, `invitation` by default, `open` the only other value; an unset, mistyped
  or environment-sourced value refuses start-up; the release receipt and the health report name the mode and the
  dossier shows it per applicant. An invitation is an address-bound row on the existing email key (no bearer token:
  the mail confirmation already proves control of the address, and a token would need redaction, a route and header
  handling). Only the owner path inserts one: the application role has no INSERT, the row is the audit record
  (issuer, time, expiry, fixed by trigger), a repeat issuance supersedes the live one. The check runs inside the
  intake transaction after every write an invited submission makes and rolls the transaction back, so an uninvited,
  expired, used, superseded or wrong-address submission gets the accepted submission's response and timing and
  nothing is recorded. The invitation is spent at confirmation (one conditional update after the application and
  challenge locks; a concurrent redemption admits one), never at acceptance, so an unconfirmed submission does not
  burn it; a confirmation with none live is "no longer valid", the expired-challenge page. With the mode `open` the
  intake is the S1 intake unchanged. The suite opens the mode and the limits per test and proves the shipped defaults
  from a fresh process; the staging check invites its synthetic address before the dark-deploy submission.
- **Evidence**: `tests/test_throttle.py` and `tests/test_invitation.py`, mapped as P6 design rules in
  `tests/acceptance.py`; the migration round trip and the role, trigger and constraint inventories updated
  (`tests/test_db_roles.py`, `tests/test_database.py`, `tests/test_acceptance.py`).
- **Not done here**: the owner's limit values and lifetimes (POL-16, `211.7.2`); the host preflight for a Caddy
  rate-limit module (`9kg.42`), which would add a second, outer layer and replaces nothing above; the live staging
  check (`scripts/staging_check.sh`), which is a dev-box drill, not a CI test.

## 14. Decision brief (recommended choice, alternative, consequence, first task blocked)

**Council record (2026-10-23).** Every row below was put to the seven-seat council in `030` under the owner's
designation; the council adopted the recommended column on every row, provisionally, with the binding constraints
`030` section 6 records (the Documenso fallback is "agreements disabled", never the shared team; the erasure chain is
built now with every value "undecided: refuse" and POL-10/POL-09 gate the first real submission; the repository
move is after launch or never; D-M carries four flip conditions and seven items that are not deferred). `011`
records the adoption as D-51. The owner ratifies or overrides at the go/no-go or earlier in session.

: Owner decisions, each with a recommended default.

| Decision | Recommended | Alternative | Consequence of the recommendation | First task blocked |
|---|---|---|---|---|
| D-A Host for the internal cohort (`211.7.3`) | a dedicated v2 host name for the cohort; the learning host untouched; D-09 kept for the public cutover. **This amends P6-D-11 ("keep D-09 for now") for the internal cohort only** and departs from the first-generation team's recorded preference for path routing on the learning host; the owner's record must say so | the learning host with changed matchers (a partial cutover now, consistent with P6-D-11 as written) | no collision with outstanding first-generation links; one extra DNS name and certificate under the estate single-ingress procedure (validate, then reload; added to `9kg.28`); the public cutover stays a later GATE-CUTOVER act | `dy7.2`, `dy7.3` |
| D-B The Documenso webhook target (`211.7.3`) | v2's own webhook target on a **separate Documenso team**. Public fact (the provider's documentation, which says webhooks are available for teams only and are created from the team settings, and its source at the release tag v2.21.1 of 2026-10-22, read on 2026-10-23: the webhook lookup is a find-many on the team filtered by event and enabled, and the trigger fires every match): several webhooks may exist per team and every enabled one subscribed to an event is fired for every envelope of that team. On the shared team, v2's endpoint would receive every first-generation envelope's events and the first-generation completion gate would receive v2's and could archive v2's sealed documents into its own store (a custody and erasure breach). **This pulls forward the webhook item P6-D-10 left to GATE-CUTOVER**, because the internal launch enables agreements; the separate v2 mailbox is already decided there | a second webhook on the shared team, acceptable only if the preflight and canary prove both consumers ignore envelopes they did not create (U3, U4) | no cross-delivery of envelope events between the two services; two team configurations and template sets to keep; whether the installed instance matches, and whether a second team can be created on it, is verified at the canary (U3) | `dy7.2`, `9kg.31.2` |
| D-C Retention and erasure (`211.7.1`) | decide with counsel before any real backup; the data-class table of section 6 is the checklist; provider-held copies are a manual handoff the decision names | launch with a documented hold on erasure requests | without it, real data enters object-locked backups with no erasure path | `9kg.32` |
| D-D Agreements for the cohort (`211.7.4`) | existing members are referenced, not re-signed; new participants sign the current versions; the owner countersigns by hand at launch | automated countersignature carried over now | no automated signature until counsel confirms it for v2 | `9kg.31.2` |
| D-D2 Custody (`211.7.9`) | the location under the managed data root, decision-makers only, encrypted with recoverable keys | plaintext as today | signed documents of real people are unreadable from a lost disk or an old backup | `9kg.34` |
| D-D3 Lifetimes and templates (`211.7.7`) | the synthetic defaults of `016` section 10 as starting values, the cohort's templates approved one version each | — | no real wording goes out unapproved | `9kg.31.1` (content), `oc4.11` |
| D-D4 Authority, form fields, details (`211.7.8`) | the owner as the decision group; the current form fields; the details list the agreements need | — | the decision setting is configured and granted through `9kg.30` | `9kg.30` (value) |
| D-D5 Evidence fetching (`211.7.8`) | disabled at launch (REQ-029) | an allow-list of a few public hosts | nothing is fetched on an internal participant's behalf | `9kg.39` if enabled |
| D-E Model data use (`211.7.4`) | model advice off for the internal launch; human-only assessment | re-use the earlier acceptance for v2's fields | no provider sees internal participants' data at launch | `oc4.12` |
| D-F Existing members and provisioning (`211.7.6`) | provisioning disabled by default; no drill touches an existing mailbox | provision throwaway mailboxes for everyone | no second mailbox, no accidental revocation | `9kg.31.3` |
| D-G RPO, RTO, thresholds (`211.7.2`) | section 10's proposals | other values | the drill measures against them | `9kg.31.4` |
| D-H Staff devices and roles (`211.7.5`) | option A as decided (P6-D-3); this decision only completes it with the named devices and holders | — | the host preparation can configure the restriction | `9kg.28` |
| D-I Receipt mismatch (`9kg.37`) | a gate | a recorded deviation | a mismatch refuses the deploy | `9kg.37` |
| D-J GitHub protections (`9kg.35`) | execute P6-D-5 now, before any deploy credential (D-49): a pull request plus the two required checks pinned to the Actions app, linear history, an empty bypass list, a release environment limited to `main` with the owner as (non-independent) reviewer and the force-command as the real second key. Two sub-decisions: (1) agent sessions keep owner credentials, or get a scoped token without administration or environment-approval rights (without which "owner as reviewer" is not a control); (2) the repository move `9kg.4` happens before `9kg.35` or after the launch, never between a deploy credential's creation and its first use | a required-approval rule (deadlocks with one maintainer) | the single-maintainer caveat is recorded; a ruleset change alerts | `9kg.35` |
| D-M Is the internal cohort candidate-impacting selection? (`211.7.4`) | no: participants are pre-selected team members and the admission is an operational act, so the notices, alternative-evidence routes and SP-L2-1 (`011` section 7's "before real candidate-impacting use" list, `f1u.5`) are deferred to external applicants, with each deferred item named in the record | yes: `f1u.5` and SP-L2-1 become launch blockers | without the record, `011` governs and the launch would be blocked by `f1u.5` | `f1u.5` (if yes) |
| D-K Scan policy (`9kg.36`) | fixable high and critical fail the required contract | advisory only | a vulnerable image cannot merge | `9kg.36` |
| D-L The 2026-10-22 GATE-STAGING sign-off | already given; recorded as D-50 in this PR with its exact scope (`028` section 9), for the owner's confirmation that the record is faithful | — | `011` stays the single record of gate state | — |

Decisions already recorded are not asked again: D-49's P6-D-1 to P6-D-15 (including the separate v2 mailbox),
D-46, D-47, D-48 and the selection-quality decisions of D-35, except where a row above says it amends, completes or
pulls forward one of them (D-A amends P6-D-11 for the cohort; D-B pulls forward P6-D-10's webhook item; D-H
completes P6-D-3; D-J executes P6-D-5). The synthetic policy defaults (D-29, D-30, D-34) are starting values only;
their production values are the decisions above.

## 15. Proposed go-live sign-off wording (for `9kg.31.6`; not a signature)

> "I approve the internal production launch of Catalyst v2 for the cohort named in the private operations record,
> on release commit `<sha>` and image digest `<digest>`, built under the repository controls read back on `<date>`,
> reached on `<host name>` with invitation mode on, with the staff roles and operators named in the private record,
> with the capabilities the launch manifest (029 section 7, version `<n>`) enables and every other capability
> verified disabled from inside the running containers, and under the policies and notices recorded as D-`<n>` to
> D-`<m>`. I accept the recorded evidence for backup, restore, erasure replay, effect reconciliation, the route and
> rollback rehearsal, the mail and Documenso canaries, and the agreement versions named there, and the recovery
> procedure, abort thresholds and rollback limits of the package. This does not enable public intake, mailbox
> provisioning (unless named), evidence fetching, model advice, any routing change on the learning host, or any
> wider enrollment; each needs its own decision."

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
  reproduced here. **Input conflict, on record:** the analyst was given a specified read-only location (a pinned
  local checkout of the private repository), which its definition allows in one line and forbids in another ("you
  are not pointed at the private repository"); the owner's planning instruction sided with the latter, and the owner
  repeated on 2026-10-23 that the live workflow is the private first-generation repository. Resolution: the three
  answers stand as described behaviour only (nothing excerpted); no further legacy read happens outside the
  approval-gated packet bead `dy7.4`; the agent definition's two lines are reconciled in a later docs change.
- **Compliance audit** (main session, 2026-10-23, clause by clause against the owner's planning instruction, posted
  as a comment on PR #81): 102 clauses; at `8b0e99e` 79 done, 18 partial, 5 not done (the per-finding
  reconciliation, roles per bead, the GitHub capability readback, Beads memory, targeted research); all closed in
  this fix-up (appendix A, section 4.7, the acceptance and "Roles:" fields on every bead this handoff created or
  updated, `dy7.4`, four Beads memories, the corrected batch, brief and PR body). A fresh-eyes read-only check
  preceded it (10 items, 17 gaps, all applied).
- **Specialist reviews of the changed material** (2026-10-23, eleven read-only assignments at the owner's request,
  one per domain; dispositions kept with the audit record): security and privacy (safe to publish; three
  acceptance criteria tightened, two wording scrubs); independent QA re-check (no blocker; the bead and document
  inconsistencies it found are fixed); release operations (the erasure, replay, reconciliation and custody beads
  now gate release preparation; the rehearsal gates the Documenso canary and the go/no-go; host and deploy
  acceptance made observable; section 10 relabelled as proposals); Documenso lifecycle (the canary and the
  countersign-collision proof enumerated; the sender, reminder and expiry questions owned by `211.7.4`; an
  awaiting-countersignature wait added); correspondence and jobs (the interim decline path removed as unworkable;
  the live Sent reader `9kg.49` created; wait rows added; the reconciliation bead corrected); data model (the
  erasure design restated as anonymization under a tightly specified trigger exception; the data-class inventory
  completed; replay depends on custody encryption); operator experience (two "built" claims corrected; `9kg.47`
  split into `9kg.47`, `9kg.50`, `9kg.51`; the walkthrough sequenced after them); assessment boundaries (D-M added;
  `oc4.12` and `oc4.9` acceptance bound to the recorded suspension and approval; the fake-model sentence added);
  Django design (throttle, invitation and grant designs recorded on the beads); estate knowledge (the brief now
  says where it amends or executes P6-D-3, P6-D-5, P6-D-10 and P6-D-11; the alert floor's duplicate suppression
  noted); Beads hygiene (labels trimmed to three, fields completed on the reused beads). The legacy analyst was not
  used: no packet exists and the owner's instruction forbids pointing it at the private repository.
- **GitHub capability readback** (read-only `gh api`, 2026-10-23, recorded on `9kg.35`): the repository is public
  on a plan where rulesets and protected environments are available; no server-side protection exists yet
  (`9kg.35`); there is a single maintainer. A required-approval rule or an independent environment reviewer would
  deadlock, so `9kg.35` relies on a pull request plus the two required checks and records the owner as a
  non-independent environment reviewer; the detailed readback stays in the private operations record.
- **Targeted research** (only what changes a decision): Documenso's public documentation (webhooks are per team,
  created from the team settings) and its source at tag v2.21.1 (2026-10-22): every enabled webhook of a team
  subscribed to an event is fired for every envelope of that team. This changed D-B from "whichever the provider
  supports" to a separate team by default. Whether the installed instance matches stays an account unknown (U3) for
  the canary. No other research was needed: the GitHub questions were answered by the readback above, and the
  retention, legal and provider-account questions are the owner's.

## 17. Records of the repo-only batch (section 13.3), 2026-10-23

Each record states the recommended default it built on; the owner's later decision changes a value, not a design.

### 17.1 Staff roles and the grant command (`9kg.30`)

**Built:** `accounts/roles.py` (the role matrix), `manage.py grant_staff_role` (grant or revoke one role for one
account, owner-run as the migration owner), the append-only record `accounts.StaffRoleGrant` (migration accounts
0007) and the P4 and P5 role groups (agreements 0009, provisioning 0007). Tests: `tests/test_staff_roles.py`.

- **Default built on:** D-D4 (section 14): the owner is the decision group; the role names are the ones the designs
  use (`016` F; `018` section 7; `021` section 9; `023` sections 8 and 15). `211.7.8` names the production holders;
  that changes no code.
- **Groups and permission sets are defined by migration, membership by the command.** Group roles: the S1 read-only
  group; the three P2 groups; the P3 `Assessment operator` and `Evidence source owner`; new P4 groups `Agreement
  operator` (view, operate), `Agreement decision-maker` (view, uncertain decisions, cancel and reissue and stop,
  integrity holds, document retrieval, required details) and `Agreement template owner`; new P5 groups
  `Provisioning operator` (view, operate) and `Provisioning decision-maker` (the same plus `close_application`,
  POL-12). The command refuses a group whose permissions differ from the matrix, so a role never quietly carries more
  than it says.
- **Direct roles, never a group:** `qualification-decision-maker` (`assessments.record_qualification_decision`, which
  `decisions.can_decide` accepts only as a direct grant) and `provisioning-approver` (`provisioning.approve_provisioning`,
  P5-D-3). The qualification grant is refused until the authority is configured.
- **The qualification authority is configuration, not code:** `CATALYST_QUALIFICATION_AUTHORITY` is read from the
  environment (unset: everyone refused, POL-05 undecided) and the start-up guard accepts only `explicit_permission`,
  the one rule the code implements; `CATALYST_SELECTION_POLICY` stays code-only (TEST-P3-53 amended accordingly). The
  launch host sets the value when `211.7.8` is recorded, with no release.
- **The grant record's home (a design decision):** its own table in `accounts`, not the application history (a grant
  is about a staff account, not an applicant) and not the admin log (which the application role may not write).
  Every grant and revocation inserts one row naming the account, the role, the group or permission, the approval
  reference the owner cites (`--approval-ref`, required) and the command actor; the strict append-only and
  no-truncate triggers protect it for every role, the application role reads it, and the backup role reads it.
  A no-op (already held, not held) writes nothing.
- **Superusers** hold no role (refused by the command, as on the staff site). **No raw SQL** in any filed step: a test
  scans `000-docs` for grant statements and for instructions to open a shell session.
- **Reviewer:** `catalyst-django-operator` (the roster in `008`); the owner approves the role names.
- **The ledger audit (`9kg.56`, 2026-10-24).** The owner credential can still change memberships and permissions
  without a record, so `manage.py grant_staff_role --audit` reconciles the two, read-only (`accounts.grants.differences`):
  every group membership and direct permission whose latest record for that account, kind and target is missing or a
  revocation is `unrecorded`; every latest `grant` record whose membership or permission is gone is
  `recorded_not_held`. It lists each with the account and the group or permission and exits 1 when any exists, 0 when
  the record and the database agree. `catalyst_health` carries the counts in the part `staff_roles` (anomalies
  `role_access_unrecorded`, `role_grant_not_held`; counts only, no name). **Remedy, through the command only:**
  unrecorded access is removed with `--revoke` (which records it), then granted again with its approval if it is
  authorized; a recorded grant no longer held is recorded as ended with `--revoke`, which records a revocation when
  the latest record is a grant even though the access is already gone (for example after a restore deactivated the
  account or replayed a revocation from the effect journal, `9kg.33`), or granted again with its approval. A
  difference the command cannot correct says so on its audit line: a superuser (the command refuses superusers; the
  owner corrects it through `manage.py`) or a group or permission no role maps to. `--audit` takes no other argument.
  Tests: `tests/test_staff_roles.py` (`9kg.56`).

### 17.2 The data notice, the member-on-file record and the decline refusal (`9kg.52`)

**Built:** the one-paragraph data notice of `030` Q8 as the message template `data_notice` and the invitation mail as
`invitation` (correspondence migration 0018), `applications.notices` with the template source
`correspondence.notices` behind `CATALYST_NOTICE_SOURCE`, the notice on the request-access page in invitation mode,
`catalyst_invite` printing the mail (JSON or `--format text`) and recording the notice's version and digest and the
invitation wording's digest on the row (applications 0007, fixed by trigger in 0008); the record
`applications.MemberAgreementOnFile` and `manage.py catalyst_member_on_file` (`030` Q4); the agreement path's
"referenced" state (`agreements.completion.referenced`); the decline refusal (`018` section 20). Tests:
`tests/test_intake_notice.py`.

- **Default built on:** the council's Q8 content list (what is collected, who sees it, that no model reads it and no
  link is fetched, how to withdraw and how to request erasure) and its Q4 answer ("referenced, not re-signed", recorded
  by hand from the private roster, no legacy identifier, no document copy). The wording is the owner's to approve with
  the templates (`211.7.7`); the seeded placeholder holds the content list with bracketed slots where counsel must
  state the recipients, the withdrawal route and the erasure route. **The erasure sentence depends on POL-10 and on
  the treatment of the two rows added to section 6.1**; it cannot be approved before them.
- **One template, two surfaces, never a constant.** The page and the mail render the same approved version. In
  `development`, `test` and `staging` (`config.guards.DRAFT_WORDING_ENVIRONMENTS`, listed by name) an unapproved
  version renders with a visible draft marker; anywhere else the page is withheld (503, a sampled reason-code log
  line), no invitation is issued, and the health report names `data_notice_unapproved`. The same holds for an approved
  version still marked synthetic, for a withdrawn one (the newest approved-or-retired version is retired: nothing
  older is served instead) and for a broken placeholder.
- **The member-on-file record.** The owner names which agreement types are covered (`--nda`, `--user-agreement`),
  each with its version as a plain label, and `--completion-verified`; the address must already be known to v2 (an
  invitation or an application). Labels and the recorder match an allowlist (letters, digits, spaces and `.,()+-`; no
  `@`; no run of 20 characters without a space). The same coverage again is a no-op; different coverage needs
  `--correct` and supersedes the live row, and the dossier names what it was corrected from. The application role
  only reads it; every column is fixed by trigger; nothing is deleted. The dossier says the completion was verified
  by the owner off-system (attested, not read from the provider).
- **Referenced, not re-signed.** A covered required type with no live instance is "referenced": the automated start
  does not issue a covered NDA (it starts the sequence at the advance), `completion.next_step` and `prerequisites`
  treat it as satisfied by the reference (the prerequisite digest binds the record, so a correction changes it), the
  provider read before provisioning covers only issued types, and the agreements screen shows "first-generation
  agreement on file, version X, referenced; counsel confirms coverage before launch" with no issue action and no
  details form. It is never a verified instance, so the signing, custody and countersignature paths are untouched. An
  uncovered type is still issued, with one exception the database decides: the D-15 backstop (agreements 0002 and
  0006) refuses any User Agreement without a verified NDA instance, so a member whose record covers the NDA but not
  the User Agreement gets nothing issued and an owner item (`agreement_reference_needs_decision`) instead. **Owner
  decision needed:** record the User Agreement as on file too, or decide a change to D-15 that accepts the
  reference. Recommended (recorded on the legal-posture bead, 2026-10-24): the first, so a member on file has both
  agreements covered and D-15 stays as it is. The owner's activation still requires an approved NDA template, which
  the cohort needs for new participants anyway.
- **Counsel's confirmation of coverage** (the compromise of D-D, `030` Q4) is the owner's go/no-go item for the
  internal launch (section 11): v2 records the reference, it does not decide that the first-generation agreement
  covers v2's use. Until counsel confirms, the reference is the owner's attestation only.
- **No v2 decline for an existing member** (`030` Q8): the decision service refuses a decline while a live record
  exists (`decline_refused_member_on_file`) and the decision form does not offer it; hold, or withdraw through the
  withdrawal path, instead.
- **Not done here:** the real wording and counsel's answers; the erasure treatment of the two section 6.1 rows
  (`9kg.32`); the private roster, which stays outside the repository.

### 17.3 The decline notice (`oc4.11`), 2026-10-24

**Built:** a recorded decline queues one `send_decline:<application>` (`assessments.decisions`), run by
`assessments.decline.SendDecline`, which freezes the notice from the `decline_notice` template and queues its
`send_message`; the `decline` kind of approved message and the seeded template (correspondence migration 0019); the
send check's one exception for that kind on a `declined` application (`correspondence.outbound.declined_notice`); the
`decline_not_notified` item for a permanent bounce, opened before the closed-application exception
(`correspondence.inbound`); the send or withhold choice on the decision form; the wording's state in the health
report's decision section. The full design is `016` section 10.19. Tests: `tests/test_decline_notice.py`.

- **Default built on:** council record `030` Q3's pattern (D-51) as applied to this bead on 2026-10-24: the mechanism is
  built now and the template ships as an unapproved synthetic placeholder, refused in a live environment until the
  owner approves real wording (`211.7.4` for the notice wording with counsel, `211.7.7` for template approval). That
  approval still gates the go/no-go through `9kg.31.6`. The first-generation service sends no decline message, so this
  is a deliberate improvement, not parity (section 4.2).
- **Chose the P2 sender over a decline-specific send** because every uncertain-send rule, staff decision, hard-bounce
  block and restore reconciliation then applies unchanged; the one exception is narrow (the `decline` kind, the
  `declined` stage) and tested in both directions.
- **No rationale is ever sent.** The template's one variable is the display name; a test spies on the only rendering
  call and searches the frozen and wire message for the decision's reason code, reason text, rationale notes, policy
  reference and identifiers.
- **Withholding** is a recorded choice of the decision-maker with a reason (the decision record and an event); when it
  is appropriate is the owner's rule (the bead's "deliberate-withholding rule"), not decided here.
- **Held actions from before the handler are cancelled, never released** (migration 0019; a hand-released one is
  cancelled by the handler because its decision made no choice about the notice).
- **Owner decisions needed:** the real decline wording with counsel (the bracketed slots: whether a reason may be
  requested, whether a new request may be made, what is kept and how to request erasure, whether replies are read),
  approved on the template screen (`211.7.4`, `211.7.7`); and the withholding rule.
- **Reviewer:** `catalyst-workflow-correspondence` (the roster in `008`); the owner approves the template.

## Appendix A. Reconciliation of the 2026-10-22 audit findings

The refreshed application audit of 2026-10-22 (a private review pack; only its repository-relevant findings are
named here) was reconciled on 2026-10-23 against `main` `45f8b93`, the tests, the open PRs and the live tracker.
States: **confirmed** (reproduced on the current tree), **already fixed** (fixed before or by this PR, with the
evidence), **needs reproduction** (not reproduced; not treated as a fact), **superseded** (a later decision
replaces it), **approved limitation** (recorded by decision, not a gap), **unverified** (cannot be checked from the
repository). A prior assistant assertion counts as a lead, not proof; nothing closed was reopened.

: The audit's findings, each with its state, evidence and bead.

| Finding (audit section) | State | Evidence (2026-10-23) | Bead or record |
|---|---|---|---|
| 8.1 Front-door documents describe an earlier phase (README, `006`, `011` banner, CHANGELOG) | already fixed | this PR updates `011` (1.3.0), `006`, README, CHANGELOG and the index; `check-docs` 0 issues | `dy7.1` |
| 8.2 A gate PASS is not "proven": 17 partial cases print as PASS; stale `P6_LIVE` comment | confirmed | `tests/conftest.py` has four states (PASS, FAIL, INCOMPLETE, NOT RUN) and no "partly proven" state; AAR `028` section 4 lists the 17 | `9kg.44` (register; the comment fix noted there) |
| 8.3 Nothing on GitHub stops a direct push to `main` | confirmed | read-only readback 2026-10-23: rulesets `[]`, branch protection 404, environments 0 | `9kg.35` (owner, GitHub-admin) |
| 8.4 The image scan does not block a merge | confirmed | the image workflow's header says it is not a required check | `9kg.36`; scan policy D-K |
| 8.5 Enabling a P3 to P5 staff member needs raw SQL | confirmed | code inventory of 2026-10-23 (section 5.2, "Grant paths") | `9kg.30` |
| 8.6 A slow handler can be reclaimed mid-flight (no lease renewal) | fixed for model calls by `oc4.9` (the fence before each request, the heartbeat and the half-lease guard, `018` section 21; deferred at GATE-P3, D-36, `018` section 14); approved limitation for the provider adapters (D-45, D-48: non-redeliverable kinds end `uncertain` and reconcile by read, section 5.2) | the mail timeout and one model attempt are shown to stay under half the lease; the MXroute pre-create read is proven at the canary | `oc4.9` (built); `9kg.31.3` |
| 8.7 A restore needs the owner present | approved limitation (D-49: the restore hold and the post-restore step, `026` section 6) | the owner's recovery procedure is item 7 of the go/no-go package | `9kg.31.4` |
| 8.8 Held actions nothing will run (`send_decline`, `interpret_reply`, `provision`) | confirmed for `send_decline`; approved limitation for `provision` (P4-D-13, owner-run activation) and `interpret_reply` (cancel-only by the P2 design accepted at D-33) | section 5.2 "Actions enqueued without a handler", verified at `45f8b93` | `oc4.11`; the "waiting on policy" label in `9kg.41` |
| 8.9 Stale help text and docstrings | confirmed | the four strings named by the audit are still in the tree | `9kg.41` (noted) |
| 8.10 Beads lag the merged work | already fixed | the 2026-10-22 cleanup closed `9kg.23`, `9kg.15`, re-homed `9kg.20` to `9kg.22` into `9kg.28`, closed the P4 and P5 epics; `bd orphans` clean | D-50 row in `011` |
| HIGH: no erasure path or POL-10 decision | confirmed | the post-restore step records that erasure replay needs an erasure path that does not exist; no decision in `011` section 6 | `211.7.1`, `9kg.32`, `9kg.25`, `9kg.34` |
| HIGH: no server-side protection of `main`, no release environment | confirmed | as 8.3 | `9kg.35` |
| HIGH: GATE-STAGING sign-off verbal only | already fixed | D-50 in `011` section 4.1 with the owner's words, the CI run and the `028` scope | `011` 1.3.0 (this PR) |
| MEDIUM: 17 partial cases report as PASS | confirmed | as 8.2 | `9kg.44`; `9kg.27` split into `9kg.37` to `9kg.40` |
| MEDIUM: front-door drift | already fixed | as 8.1 | `dy7.1` |
| MEDIUM: image scan not required | confirmed | as 8.4 | `9kg.36` |
| MEDIUM: no Python lint, type check, CodeQL or pip-audit | confirmed | no Ruff, mypy or pip-audit configuration in the tree | `9kg.46` (post-launch; not a launch blocker) |
| MEDIUM: no grant path for P3 to P5 permissions | confirmed | as 8.5 | `9kg.30` |
| MEDIUM: no rate limiting on public intake and confirmation | confirmed | only the staff login throttle exists | `9kg.29` |
| MEDIUM: the suite takes 18 to 20 minutes | confirmed | the runtime lane on `8b0e99e` took 18 m 37 s | `9kg.45` |
| LOW: bead state lags | already fixed | as 8.10 | — |
| LOW: stale help text | confirmed | as 8.9 | `9kg.41` |
| LOW: `pyproject.toml` version 0.0.0 against `version.txt` 0.1.0; CHANGELOG preamble below the release entries | confirmed (both; the preamble sits after the first release entry) | read on 2026-10-23 | `9kg.48` (version and hash); the preamble moves in the same chore |
| LOW: `6hl.10` open (administrator credentials in the test process) | confirmed | `compose.yaml` and the CI workflow still set the administrator variables for the whole test container and job | `6hl.10` |
| LOW: `9kg.5` and `9kg.6` open | confirmed | no column-freeze trigger on the inbound provenance columns; the application role still holds DELETE on the pause table | `9kg.5`, `9kg.6` |
| Not implemented: custody encryption | confirmed | plaintext on local disk (carried P4 limit) | `9kg.34`, `211.7.9` |
| Not implemented: named-device staff restriction (TEST-P6-15) | confirmed | dev-box staging only | `211.7.5`, `9kg.28` |
| Not implemented: deny-by-name of the estate's hosts in the egress proxy (TEST-P6-28) | confirmed | `9kg.27` clause | `9kg.39` |
| Stated limitation: a compromised owner role can drop the triggers | approved limitation | ADR-14 | — |
| Stated limitation: the CI docs job installs one dependency without a hash | confirmed | the docs job's install line | `9kg.48` |
| Section 12: pilot host work not done; live providers unproven; erasure replay missing; PL plan-only; open policies | confirmed | the basis of this plan | `9kg.28`, `9kg.42`, `9kg.31.1` to `.3`, `9kg.25`, `dy7.2` to `dy7.4`, `211.7.1` to `.9` |

Nothing in the audit was found superseded or unverifiable from the repository; the two states are listed for
completeness. The audit's roadmap (week, month, quarter) is advisory and is replaced by section 13.

## Appendix B. Screen and exceptional-state walkthrough (9kg.41)

Walked on 2026-10-23 against `main` `3477231` plus this appendix's PR. Scope (council record `030` Q10): every wait
state of section 5.2, the states the bead adds, and the refusals of the three disabled capabilities. Each state was
driven with synthetic data through the real Django views using the Django test client in the pinned containers
(`scripts/test.sh`). Where an earlier test already walks a state through its screen, the row cites that test. The
walkthrough's own tests are in `tests/test_screen_walkthrough.py` (23 tests, mapped in `tests/acceptance.py` under
P6 supporting `9kg.41`).

**Phone and desktop.** When this walkthrough ran the repository had no browser-test tooling (no Playwright or
Selenium), so the phone check was a rendered-HTML check, not a rendered-pixel one; GAP 6 below has since been addressed
by a real browser check of the public pages (`9kg.68`). Every page template declares the phone viewport. The public pages
(request access, received, confirm, set password, withdraw) now carry phone-width rules: long links and answers wrap,
and form controls never overflow the screen. The request form keeps every typed value after a validation error. The
staff screens are desktop-first tables used on named devices (section 7); on a phone, wide tables scroll sideways.

**Outcome codes.** OK: the screen handles the state as it stands. FIXED: changed in this PR, with a test. GAP: found,
larger than a small fix, recorded with a bead suggestion and not changed here.

: The walkthrough, one row per state.

| # | State | Screen (URL name) | Who acts | What the screen shows | Exit | Outcome and evidence |
|---|---|---|---|---|---|---|
| 1 | Verification sent, unconfirmed | public `applications:confirm`; staff `correspondence_staff:application` | applicant; staff for a resend | the answers and a Confirm button; on the staff page, the resends used and a warning when a usable link is out | confirm; staff resend (`resend_verification`) | FIXED: a double-submitted resend sent two messages. The form now names the resend it offers, and a repeat is refused as `resend_already_recorded` (`test_walk_a_double_submitted_verification_resend_sends_one_message`). Confirm twice: OK (`test_confirmation::test_s1_08_confirming_records_contact_control_once`). The challenge lifetime stays the only bound (section 5.2). |
| 2 | Verification link expired or superseded | public `applications:confirm` | applicant | 410, "This link is not valid" | a new submission or a staff resend | OK (`test_confirmation::test_s1_09_an_expired_challenge_is_refused_by_the_database_clock`). GAP 1, fixed by `9kg.66`: the expiry of the only link opens a `verification_expired` staff item, resolved by the resend. |
| 3 | Question sent, awaiting reply; unanswered after the last reminder | `correspondence_staff:queue`, `correspondence_staff:item` | applicant; then staff | the `escalate_unanswered` item, now with "What happened" in plain words | acknowledge (after acting) | FIXED: plain-language reason (`test_walk_an_unanswered_question_escalates_to_a_staff_item_with_plain_words`). |
| 4 | Reply awaiting staff processing | `correspondence_staff:reply` | staff (confirm outcomes) | the escaped derivative and one outcome per question, none preselected | confirm the outcomes, or close without one | OK (`test_staff_screens::test_p2_42_reply_confirmation_shows_the_derivative_escaped_and_checks_its_digest`). |
| 5 | Reply unmatched, unverified, from another sender, or for a closed application | `correspondence_staff:item` | staff; the decision-maker for identity | the message facts and only the lawful resolutions for the viewer | associate, dismiss, mark as spoofed, acknowledge | OK (`test_staff_screens::test_p2_42_identity_resolution_needs_the_decision_maker_through_the_screen`, `::test_p2_42_the_item_page_shows_the_evidence_and_offers_only_lawful_decisions`). |
| 6 | Uncertain send | `correspondence_staff:item`, `send_decision` | the decision-maker | the attempts table, the decisions and the duplicate-risk note | authorize a resend, abandon, revise | OK: a second click is refused as `nothing_to_decide` (`test_walk_an_uncertain_send_is_decided_once_on_the_item_page`). The live Sent reader is `9kg.49`. |
| 6a | SMTP transport blocked (`smtp_transport_blocked`) | `correspondence_staff:item`, `send_decision` | the decision-maker, once the owner has fixed the channel | "What happened: the mail channel is blocked", the held attempts and the decisions | authorize a resend after the fix, abandon, revise | OK: the resend goes out once and a second click is refused (`test_walk_a_blocked_mail_channel_is_decided_on_the_item_page_and_the_send_goes_once_resent`). |
| 6b | Permanent rejection (`send_rejected_permanent`) | `correspondence_staff:item`, `send_decision` | the decision-maker | only abandon and revise (a permanent rejection is never resent unchanged) | abandon, or revise from the current template | OK (`test_staff_screens::test_p2_42_the_item_page_shows_the_evidence_and_offers_only_lawful_decisions`). |
| 7 | Mailbox cursor blocked | `correspondence_staff:queue`, `item`, `restart` | the decision-maker | cursor state and reason under "Mail collection" | restart the collector | OK (`test_staff_screens::test_p2_52_restart_needs_the_decision_maker_through_the_screen`). |
| 7a | Mailbox cursor in resync or recovery | `correspondence_staff:queue`; the `mailbox_uidvalidity_changed` item | the worker; staff acknowledge | the cursor's state (`resync`, `recovery`) under "Mail collection", and the item | none needed: the worker completes the pass; staff acknowledge the item | OK (`test_walk_a_mailbox_resync_shows_on_the_queue_and_clears_itself`; recovery: `test_inbound::test_4_1_a_regressed_cursor_becomes_a_recovery_and_skips_nothing`, service level). |
| 8 | Hard bounce | `correspondence_staff:item`, `resolve` | the decision-maker, with a reason | the reason in plain words, and the consequence of resolving | `address_usable_again` | OK: an operator sees no resolution, a short reason is refused, and a second submit is refused as `item_already_resolved` (`test_walk_a_hard_bounce_and_its_system_pause_through_the_queue_item_and_application_screens`). |
| 9 | Paused by staff; system pause | `correspondence_staff:application`, `pause`, `resume` | staff; the decision-maker for a system pause | who paused, when and why; a system pause says it needs decision-maker review | resume (a reason of at least 10 characters for a system pause) | OK: a second resume is refused as `not_paused` (same test; `test_staff_screens::test_p2_42_pause_resume_withdraw_and_approve_through_the_screens`, `test_processing::test_9kg_2_the_screen_offers_a_system_resume_only_to_a_decision_maker_with_a_required_reason`). |
| 10 | Assessment refused by suspension (model advice disabled) | `assessments_staff:decision`, `decide`; the item on `correspondence_staff:item` | the decision-maker | "Refused by suspension", the suspension record, the human-only reason field | a human-only decision (the only way the item closes) | FIXED: the item was acknowledge-only, so acknowledging it left the dossier reading "System: Assessing" while nothing ran. It now closes only through the human-only decision or a later successful run; the item page offers no acknowledgement, says where it closes, and links the decision screen only for a viewer who may open it (`test_walk_a_suspended_assessment_item_closes_only_through_the_decision_and_links_by_permission`; `test_human_only::test_a_run_refused_under_the_suspension_is_labelled_so_and_leaves_assessing_through_the_decision_form`). |
| 11 | Capped snapshot | `assessments_staff:decision`, `decide` | the decision-maker | the human-only form under `CATALYST_CAPPED_EXIT` | a human-only decision | FIXED with row 10: the capped item is no longer acknowledge-only (`test_assessment::test_failed_runs_leave_resolvable_items_that_a_rerun_and_a_success_settle`; `test_human_only::test_a_capped_snapshot_leaves_assessing_through_the_decision_form_and_no_close_action_exists`). With `CATALYST_CAPPED_EXIT=none` (not the launch default) the item stays open until the application is closed. |
| 12 | Awaiting decision | `assessments_staff:decision`, `decide` | the decision-maker | the snapshot, the evidence manifest, the criteria; only the permitted outcomes | admit, hold, decline | FIXED: a refused decision redirected and lost every typed rationale. It now re-renders (409) with the reasoning kept and the outcome cleared ("choose the outcome again"). When the refusal is `changed_since_shown` (the case changed under the form), every capability, strength and the outcome are cleared, only the free-text notes return, and the page says so. A second submit records nothing (`test_walk_a_refused_decision_keeps_the_typed_reasoning_never_the_outcome_and_a_second_submit_records_nothing`, `test_walk_a_decision_refused_because_the_case_changed_clears_every_judgment_and_keeps_only_notes`). |
| 13 | Declined | `assessments_staff:decision`; the dossier | none | "not at a stage where a decision can be recorded (declined)"; the dossier now reads `send_decline: held on policy: no decline notice is sent until ...` | none | FIXED: the label (same test). GAP 3: no decline notice (`oc4.11`, already a release gate in section 7). |
| 14 | Agreement sent, awaiting signature | `agreements_staff:agreements` | applicant | issue, signing and custody statuses; now the last status change and its age | the decision-maker cancels | FIXED: the age on the screen (`test_walk_the_countersignature_wait_is_named_and_every_agreement_shows_its_age`; `test_agreement_custody::test_p4_21_the_screen_shows_three_statuses_and_enforces_permissions`). |
| 15 | Countersignature wait | `agreements_staff:agreements` | the countersigner (the owner, by hand), then the system | "partly signed"; the next action now names the remaining signer | the countersignature at the provider | FIXED: the next action said the applicant owed it (same test). |
| 16 | Agreement held: declined, expired or cancelled at the provider | `agreements_staff:agreements`, `act` | the decision-maker | the status, "Automation is paused", the reissue button | reissue as a new instance; then resolve the pause cause | OK: a second reissue is refused as `already_superseded` (`test_walk_a_declined_agreement_is_reissued_once_from_the_screen`). |
| 17 | Agreement held: integrity hold (recipient change) and custody failure | `agreements_staff:agreements`, `act` | the integrity decision-maker; the operator for custody | the hold, the fresh-read state and the dispositions; retry custody | continue, replace, escalate; retry custody | OK (`test_agreement_custody::test_p4_21_a_refused_integrity_disposition_keeps_the_typed_reason`). FIXED: a refused required-details draft lost the typed values (`test_walk_a_refused_details_draft_keeps_the_typed_values`). GAP 4: duplicate envelopes have no screen action (`9kg.53`). |
| 18 | Uncertain Documenso create | `agreements_staff:agreements`, `act` | the decision-maker | the unknown attempt, its reconcile checks, the duplicate risk; no choice preselected | not sent and create again, or abandon | OK (`test_agreement_screens::test_an_unknown_create_is_decided_on_the_screen_and_refused_without_the_permission`). |
| 19 | Uncertain distribute | same | the decision-maker | as above | send again, or cancel | OK (`test_agreement_screens::test_an_unknown_distribute_is_decided_on_the_screen_and_cancelling_needs_the_manage_permission`). |
| 20 | Uncertain cancel | same | the agreement manager | "Decide the unknown cancel" | cancel again (reconciled) | OK (`test_agreement_screens::test_an_unknown_cancel_is_decided_on_the_screen_and_refused_without_the_permission`). |
| 21 | Template approval (agreement and message templates) | `agreements_staff:templates`; `correspondence_staff:template` | the template owner | the digest shown; a repeat changes nothing | approve exactly this version | OK (`test_agreement_screens::test_a_template_version_is_approved_on_its_own_screen_by_the_digest_shown`, `test_staff_screens::test_p2_42_template_approval_through_the_screen_approves_exactly_what_was_shown`). FIXED: the staff index now lists the queue, the message templates, the agreement templates and the evidence sources, each only for the role that acts there, and nothing for a superuser or the read-only role (`test_walk_the_admin_index_lists_the_staff_screens_a_role_can_open`). |
| 22 | On hold, and its exit | `assessments_staff:decision`, `decide` | the decision-maker | admit and decline offered, hold not | admit or decline | OK (`test_hold_and_resend::test_an_on_hold_case_comes_back_through_the_decision_form_and_a_refused_user_sees_403`). |
| 23 | Aged waits | no screen: a health command, `manage.py catalyst_health` (`aged_waits.*`) | the owner, by alert | codes and ages per wait class | the matching screen above | OK (`test_system_health::test_9kg_51_each_aged_wait_raises_its_code_and_clears_when_resolved`). Only the three default classes page; the stage, item and pause classes are counted but page only once the owner lists them (`211.7.2`). |
| 24 | Provisioning held | `provisioning_staff:provisioning` | the owner | "Release provisioning (owner command activate_provisioning)" | the owner's command | OK (`test_walk_held_provisioning_names_the_owner_command`). |
| 25 | Provisioning unknown create | `provisioning_staff:provisioning`, `act` | system, then the operator | the phase, the attempts, "Confirm whether the found mailbox is ours" | confirm ours or not ours | OK (`test_p5_journey::test_p5_24_the_journey_from_intake_to_activation_and_from_withdrawal_to_revocation_over_http`). |
| 26 | Activation with the signing provider unavailable | `provisioning_staff:provisioning` | system; staff watch | "Password set; activation pending" and nothing else, so a stalled case looked busy | it retries on its own | FIXED: "Activation waits: provider_unavailable", with the first-queued time and the age (`test_walk_activation_waiting_on_an_unavailable_provider_is_shown_with_its_reason`). |
| 27 | Withdrawal (link) and withdrawal racing provisioning | `provisioning_staff:act` (withdrawal link, close); public `withdrawal:withdraw` | the closer; the applicant | the links with their states; revocation per kind | the applicant confirms; staff close | OK: two link requests send one message (`test_walk_a_double_requested_withdrawal_link_sends_one_message`); the withdraw page acts once (`test_closure::test_p5_21_get_shows_post_commits_and_the_link_works_once`). The race itself (a withdrawal during an uncertain create) is proven by service tests only (`test_closure::test_p5_17_a_withdrawal_during_an_uncertain_create_recovers_the_late_mailbox_without_a_welcome` and its neighbours), not through the screen. |
| 28 | Unsupported revocation | `provisioning_staff:act` (`accept_exception`) | the approver | "no documented mechanism: owner decision" | accept as an exception, with a reason | OK (`test_provisioning_screen::test_p5_19_closing_through_the_screen_shows_revocation_and_the_owner_accepts_an_exception`). |
| 29 | Restore hold | none: `manage.py catalyst_post_restore` | the owner | the review run | lift after both confirmations | OK by design (`test_post_restore::test_6b7b_lifting_needs_a_review_run_and_both_confirmations`). |
| 30 | Disabled: model advice | `assessments_staff:decision` | the decision-maker | refused by suspension, never a failure; no model call | a human-only decision | OK (row 10). |
| 31 | Disabled: evidence fetching | `assessments_staff:evidence` | nobody (the case moves on) | each claim `refused (no_approved_source)`, and "an unavailable or private source never counts against the applicant"; nothing fetched | assessment proceeds | OK: the test also asserts that the stage moves on to assessment (`test_walk_evidence_fetching_disabled_refuses_every_claim_visibly_and_the_case_moves_on`). |
| 32 | Disabled: mailbox provisioning | `provisioning_staff:provisioning` | the owner | the held hand-off (row 24); without an adapter nothing is committed and staff are told | none at launch | OK (`test_provisioning::test_review_without_an_adapter_nothing_is_committed_and_staff_are_told`). |

**Totals:** 35 states walked. 24 are OK as they stand, each with one or more cited tests. 11 were FIXED in this
PR, each with a test: rows 1, 3, 10, 11, 12, 13, 14, 15, 17, 21 and 26. Five GAPs remained open (below): rows 2, 13 and
17 point at GAPs 1, 3 and 4, and GAPs 5 and 6 cover all the screens (GAP 6 since addressed by `9kg.68`). GAP 2 was fixed in this PR (rows 10 and 11).

**Double submits.** One form acted twice: the verification resend (row 1, fixed). These POSTs were each submitted twice
through the view in a test and acted once:

- the hard-bounce resolution and the system resume (row 8);
- the escalation acknowledgement (row 3);
- the uncertain-send and blocked-channel decisions (rows 6, 6a);
- the qualification decision (row 12);
- the clarification question (`test_walk_a_refused_clarification_keeps_the_typed_question_and_a_double_submit_stores_one`);
- the staff-message confirmation (`test_walk_more_double_submits_act_once`);
- the assessment rerun (`test_walk_a_double_submitted_rerun_queues_one_run`);
- the agreement reissue and cancel (row 16, `test_walk_a_double_submitted_agreement_cancel_cancels_once`);
- the provisioning approval and closure (`test_walk_double_submitted_provisioning_approve_and_close_act_once`);
- the withdrawal link (row 27).

The public confirmation and withdrawal pages act once by their existing tests (rows 1 and 27). The agreements stop,
resume and integrity recheck were checked by reading the code only, not by a test:

- a repeated stop finds nothing live to cancel and records a second stop event;
- a repeated resume queues a second sequence advance, which issues nothing new because the sequence reads the state;
- a repeated recheck queues at most one read per agreement.

**Also fixed (text only, the bead's sweep and audit item 8.9).** These changes affect no behaviour:

- the worker's help line no longer says "local mail sink only in this slice";
- the dossier no longer says "blocked in this slice" or "accepted by the local mail sink";
- the admin site no longer says the staff actions "arrive in later phases";
- the guard and settings docstrings that said test-only now say test and staging where the guard allows staging;
- the provider guard, the mail-host guard, the verification handler and the mail-backend comment no longer say
  "outside production" or "local mail sink" (production is not an allowed environment yet);
- the agreements screen no longer says the provisioning hand-off is "held for P5": it is held until the owner releases
  it with `activate_provisioning`;
- `016` no longer says a pause holds an unknown staff send's reconcile (reversed in its own 10.11).

The staff index lists the screens each role can open, so the queue is reachable without knowing its address. The
staff item page states each reason in plain words, and the dossier shares the same words.

**GAPs (open ones not changed here; each with one bead suggestion):**

1. *Verification expiry prompts nothing.* An expired link waits for the applicant to submit again, or for staff to
   notice. Suggest: a bead to open a staff item when an unverified application's only link expires (POL-02 sets
   the lifetime). *(Fixed by `9kg.66`: a recurring sweep opens one `verification_expired` item per expired only link,
   which the staff resend resolves; `016` section 10.17.)*
2. *(Fixed in this PR: a suspended or capped assessment item now closes only through the human-only decision; rows
   10 and 11.)*
3. *No decline notice.* Already `oc4.11`, a release gate (section 7).
4. *Duplicate envelopes have no screen action.* Already `9kg.53`.
5. *Resolution buttons show codes.* For example `address_usable_again` and `mark_spoof` are shown as codes, not
   plain labels; the reason is now in plain words. Suggest: a small bead giving each resolution code a plain label,
   with the tests that match on the codes updated. *(Fixed by `9kg.67`: each resolution, acknowledgement and decision button shows a
   plain label and still submits its code; `016` section 10.18.)*
6. *No rendered phone check.* **Addressed by `9kg.68`:** `tests/browser_phone_check.py`, run by
   `scripts/browser_check.sh` (a pre-release step, and dispatchable in CI as "Phone-width browser check"; `009` section
   5.3), renders request access (open and invitation mode), received, confirm, set password and withdraw, and each
   result page, in headless Chromium at 375 px and 1,280 px: no horizontal scroll, the viewport declaration honoured,
   every control visible, usable and reached by the Tab key. All passed on first measurement with no template change.
   It is listed for the wider-enrollment decision (`9kg.31.10`).

### B.1 Screens the internal cohort will not exercise at launch (for the go/no-go package)

The go/no-go package (section 11) lists these beside the screens the cohort did exercise. A screen in this list has
synthetic evidence only.

- **Provisioning (disabled by default, section 7):** the provisioning screen's approval, creation, unknown-create,
  verification, credential and activation phases (rows 24 to 26); the public set-password page; revocation and the
  unsupported-revocation exception (row 28). Withdrawal stays enabled, so the withdrawal link and page (row 27) can be
  exercised; access revocation applies only where provisioning ran.
- **Evidence fetching (disabled):** re-fetch, proceed without an item, and the evidence-source screens; every claim
  is shown refused (row 31).
- **Model advice (disabled):** the advisory reply reading on the reply screen, the assessment rerun, and model-assisted
  decisions. Every decision is human-only (rows 10, 30).
- **Agreement paths skipped for a member on file:** for a member whose first-generation agreements are recorded on
  file (`9kg.52`, section 17.2), the agreements screen shows each covered type as referenced and issues nothing, so
  the agreement sequence, the countersignature wait, custody and required details (rows 14 to 21) are not exercised
  for that member. The decision screen offers that member no decline (`030` Q8). This walkthrough predates the merge
  of `9kg.52` and did not walk the referenced state; its own tests are in section 17.2.
- **Provider-fault states, unless a canary provokes them:** the uncertain send (row 6), the uncertain Documenso
  create, distribute and cancel (rows 18 to 20), and the integrity hold (row 17) appear only on a provider fault. Their
  evidence is the synthetic tests cited above.
- **Restore hold (row 29):** exercised only by the production restore drill (lane C, `030` Q10).
