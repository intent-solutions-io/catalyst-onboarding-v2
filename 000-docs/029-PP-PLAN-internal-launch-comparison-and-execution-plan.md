# Internal production launch: workflow comparison record and execution plan (handoff PL-A)

| Field | Value |
|---|---|
| Document | `029-PP-PLAN-internal-launch-comparison-and-execution-plan` |
| Version | 0.3.0 (the council record `030` adopts the decision brief provisionally and amends the path, sections 13.2 and 14, 2026-10-23; 0.2.0 applied the compliance audit of 2026-10-23: section 4.7, appendix A, section 16, the corrected batch and brief) |
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
| J-05 Assessment | Observed: four bounded model stages on one job queue; typed outputs with validators; a repair budget; staleness checks; shadow mode records recommendations only; the owner gets a notice per resting outcome; intake-stage public data to the model was accepted by the owner with counsel (recorded decision). | REQ-009, D-04, P3-D-4 to P3-D-8, `019` (the P3-D-10 amendment: a recorded human-only assessment when advice is unavailable or suspended) | `assessments/agent.py` (model requests disabled, no live branch), `runs.py`, budgets, invocation records, failure routing (TEST-P3-01, 02, 07); live-call protections not built (`oc4.9`) | The human-only path's policy and snapshot record (`oc4.10` items 1 to 3); a refused or capped snapshot's exit (`oc4.8`, `9kg.50`); real-model quality and prompt-injection behaviour (fake-model tests are not real-model evidence) | DISABLED (model off; human-only assessment) | **OUT OF INITIAL SCOPE** for model advice; **VERIFY** and complete the human-only path (`oc4.12`). Note the deliberate difference from B1: v2 sends nothing to a model until `oc4.9`, the data-use approval for v2's fields and the evaluation (`oc4.7`) exist. The owner's earlier data-use acceptance was for the first-generation reviewer's fields and must not be assumed to carry over (decision `211.7.4` asks). |
| J-06 Questions | Observed: a clarification sender existed in design but was unregistered at the checkout (reported restored later; UNKNOWN); pacing limits exist; reminders unbuilt. | REQ-012, REQ-034, P3-D-5 (model questions never sent unapproved) | `correspondence`: approved, frozen messages; staff-authored and model-proposed questions through approval; TEST-P2 cases; GATE-P2 PASS 54 | Real delivery and reply collection (mail canary) | INCLUDED (staff-authored questions only) | **PRESERVE** the owner-approval rule; **IMPROVE**: v2 has the loop the first-generation service lacked. |
| J-07 Inbound | Observed: a 60-second poll of one shared service mailbox with a durable UIDVALIDITY plus UID cursor, deterministic classes, no bodies stored; bridge and existing-member replies land in the same inbox; a human reply emails the owner a notice. | REQ-012, REQ-034, D-27, D-28, D-31 (fail-closed identity) | `correspondence/imap.py`, `inbound.py`, `processing.py`; association and trust; staff exceptions (TEST-P2-01, 07, 12 to 24) | Live inbound health (TEST-P6-18); the real mailbox | INCLUDED, on **v2's own mailbox** | **PRESERVE** durable collection; **RETIRE** the shared mailbox for v2 (M8, P6-D-10): a second poller of the first-generation mailbox would duplicate and race. Decision `211.7.3`. The owner reply notice is a MANUAL HANDOFF (the staff queue shows replies; no owner mail). |
| J-08 Reminders, autoresponders, bounces | Observed: autoresponders and bounces classified; nothing suppresses on a bounce (defect); no reminders. | REQ-012, D-27; `9kg.2`, `9kg.3` (closed): hard bounce blocks every send; system pauses need a decision-maker | `correspondence/reminders.py`, `remind`, `escalate_unanswered`; TEST-P2-02, 04, 10 | Live bounce path (mail canary) | INCLUDED | **IMPROVE** (bounce block and reminders exist in v2 only). |
| J-09 Takeover | Observed: no global pause in the service; host-level switches; per-case halts in the bridge cleared by hand. | REQ-013, D-30 | `AutomationPause`, `staff_actions.pause/resume`; the pause row protected in code only (`9kg.6` open) | A database guard on the pause row | INCLUDED | **PRESERVE**; **IMPROVE** `9kg.6` before launch. |
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
| Decline sends the applicant nothing | A decline notice action exists without a handler | INCLUDED once built | IMPROVE (`oc4.11`): a deliberate improvement over silence |
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
| Nothing deletes personal data | An erasure path is designed, not built | required before real data | IMPROVE (`211.7.1`, `9kg.32`, `9kg.25`) |
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
| Verification sent, unconfirmed | applicant | challenge lifetime (POL-02 value open); expiry prompts nothing today | **missing**: no staff resend exists (a failed send is not retried; a new submission issues a new link) (`9kg.50`) | gap |
| Question sent, awaiting reply | applicant | reminder cadence and maximum (POL-06 synthetic values), then `escalate_unanswered` to staff; after escalation, the staff item's age (`9kg.51`) | staff item | built; the post-escalation bound is `9kg.51` |
| Reply awaiting staff processing | staff | none today (reminders and escalation are held while a reply is pending, so the case stalls silently) | staff item | **missing** bound (`9kg.51`) |
| Reply unmatched, unverified, sender-mismatched, or on a closed application | staff | none today | staff exception item (the unmatched rule for a misdirected first-generation reply is `dy7.2`) | built; bound `9kg.51` |
| Uncertain send | worker, then staff | reconcile by Sent-folder read; unknown goes to a staff item | staff decide resend or abandon (decision-maker) | built against the fake; **the live Sent reader is not built** (`9kg.49`) |
| Mailbox cursor in resync, recovery or blocked; SMTP transport blocked | worker | health anomaly codes | staff item; the owner for a transport block | built; live proof in the mail canary |
| Hard bounce | staff | immediate block of every send | decision-maker recovery after the cause is addressed | built (`9kg.3`) |
| Paused (staff or system) | staff | shown with reason; age bound `9kg.51` | resume by the right role; system pauses need review | built; database guard open (`9kg.6`) |
| Refused or capped assessment snapshot (at launch: refused by suspension) | staff | none today | **missing**: the route to the human-only decision form (`oc4.12`, `9kg.50`; default from `oc4.8`) | gap |
| Awaiting decision | decision-maker | **no age signal today** (the health report has no stage-based part) | decision screen | built; the authority value must be configuration-driven and granted (`9kg.30`); the age bound is `9kg.51` |
| Declined | none | terminal | **no notice** today (`oc4.11`) | gap |
| Agreement sent, awaiting signature or countersignature | applicant, then the owner (countersignature) | none today | staff see the age; the decision-maker cancels | **missing** bound and visibility (`9kg.51`) |
| Agreement held (recipient change, custody failure, expiry, rejection) | staff | staff item, pause | decision-maker reissues as a new instance | built |
| Provisioning held | the owner | released only by `activate_provisioning` | the command | built (disabled at launch) |
| Provisioning unknown outcome, or provider unavailable at activation | worker, then staff | reconcile by read; never create again; the unavailable case has no bound | staff item | built against the fake; bound `9kg.51` |
| Withdrawal racing provisioning | worker | the withdrawal services cancel and revoke; unsupported checks stay unresolved | staff item | built against the fake |
| On hold | staff | none | **missing**: no path back to a decision except closure (`9kg.50`, through the decision service) | gap |
| Uncertain Documenso create, distribute or cancel; template approval | decision-maker | staff item | **shell only** today (`9kg.47`) | gap |
| Restore hold | the owner | nothing runs until reconciliation | `catalyst_post_restore` review and lift | built; erasure replay and effect reconciliation open (`9kg.25`, `9kg.33`) |

The bounds and whether each pages are the owner's values (`211.7.2`, `211.7.7`); the health part that counts aged
waits is `9kg.51`.

**Found by the code inventory (2026-10-23, `45f8b93`), each a VERIFY turned into a task:**

- **Actions enqueued without a handler:** `send_decline` (held forever; `oc4.11`), `interpret_reply` (held until
  staff cancel it, by design) and `provision` (released by `activate_provisioning`, by design). Unknown kinds are
  never claimed.
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
| Verification mail, questions, reminders, inbound collection | ENABLED on v2's own mailbox after the Sent reader and production allow-list exist (`9kg.49`) and the mail canary passes, with the cohort's templates, lifetimes and cadence decided | `211.7.7`, `9kg.49`, `9kg.31.1` |
| Model advice | DISABLED; human-only assessment recorded (`oc4.12`) | `211.7.4` (data use) |
| Qualification decision | ENABLED; the owner is the decision group, decided for the cohort under POL-05 (P3-D-9 was synthetic only) | `211.7.8`, `9kg.30` |
| Decline notice | ENABLED through `oc4.11` with an approved template; there is no interim path (a declined case is terminal and staff sends refuse closed cases), so `oc4.11` gates release preparation | `211.7.7` |
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
4. the backup, restore, erasure and reconciliation evidence;
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

Missing evidence about an enabled critical step blocks that step's readiness claim; it does not block the repo-only
work.

## 13. The work graph (as it exists in Beads)

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
(not launch blockers), `oc4.9` and `oc4.10` (`oc4.12` fixes `oc4.10` items 2 and 3 and records item 1), and the
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

### 13.5 The data notice and the member-on-file flag as built (`9kg.52`, first pass)

Built 2026-10-23 from the council record `030` (Q8: a plain data notice is not deferred; Q4: existing members are
referenced, not re-signed); repo-only, synthetic data, nothing deployed. The decline refusal for a member on file and
the decision policy identifier `none: internal cohort, D-M` wait for the decision form of PR #87 and are not here.

- **One template, two surfaces** (`applications.notices`; correspondence migration 0018): the notice is the message
  template `data_notice` and the invitation mail the template `invitation`, whose one variable is the notice. Both
  are seeded as unapproved placeholders (status draft, synthetic) and approved by the owner on the template screen
  like every other template (211.7.7, D-29); the wording is a template the owner approves, never a constant in code,
  and a test proves the placeholder phrase appears in the seed migration alone. The request-access page in
  invitation mode renders the newest approved version with its version and content digest in the markup; the open
  intake is the S1 page unchanged. The templates are read and rendered by `correspondence.notices`, reached only through the
  `CATALYST_NOTICE_SOURCE` seam (`003` ADR-01: `applications` never imports `correspondence`).
- **Unapproved wording**: in `development`, `test` and `staging` (`config.guards.DRAFT_WORDING_ENVIRONMENTS`, listed
  by name) the newest draft renders with a visible draft marker so the page and the mail can be exercised before
  approval; anywhere else the page is withheld with the one 503 try-again page, no invitation is issued, the log
  carries a reason code and the health report names `data_notice_unapproved`. The health report and the release
  path see the notice's state (approved, draft or missing, with version and digest), never its wording.
- **The invitation mail**: v2 contacts nobody on an invitation (section 5.1), so `catalyst_invite` renders the mail
  before any write and prints it for the owner to send by hand, with the notice's version and digest; the invitation
  row records them (two columns fixed by the 0005 trigger, replaced in 0007). A live environment refuses to issue
  while either wording is unapproved.
- **Agreement on file, first-generation** (`applications.members`, `applications.MemberAgreementOnFile`, `manage.py
  catalyst_member_on_file`): keyed on the email key like the invitation, so it exists before any application does;
  only the owner-run command inserts (the application role has SELECT for the dossier and nothing else); the row is
  the audit record (the agreement version as a plain label, that completion was verified, who recorded it, when),
  fixed by trigger, a correction supersedes the live row, nothing is deleted or truncated. `--completion-verified` is
  required (a member without a verified completion is a new participant: nothing recorded), and a value that reads
  as a link, a path, a long identifier or a pasted record is refused, so no legacy identifier and no document copy
  enter v2. The dossier shows the state per applicant as one line.
- **Evidence**: `tests/test_intake_notice.py`, mapped as a P6 design rule in `tests/acceptance.py`; the migration
  round trip and the role, trigger and constraint inventories updated (`tests/test_db_roles.py`,
  `tests/test_database.py`, `tests/test_acceptance.py`); the health assertion in `tests/test_invitation.py`.
- **Not done here**: the real wording (the owner approves it with the templates, 211.7.7; counsel's POL-10 answer
  may change the erasure sentence); the decline refusal and the policy identifier (after PR #87); the private
  roster itself stays outside the repository.

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
| 8.6 A slow handler can be reclaimed mid-flight (no lease renewal) | confirmed for model calls (the fence was deferred at GATE-P3, D-36, `018` section 14); approved limitation for the provider adapters (D-45, D-48: non-redeliverable kinds end `uncertain` and reconcile by read, section 5.2) | only the mail timeout is shown to stay under half the lease today; the MXroute pre-create read is proven at the canary | `oc4.9` (the fence); `9kg.31.3` |
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
