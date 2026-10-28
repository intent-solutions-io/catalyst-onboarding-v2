# Internal launch: the consolidated owner decision package

| Field | Value |
|---|---|
| Document | `031-PP-PLAN-internal-launch-owner-decision-package` |
| Version | 0.1.0 (draft, 2026-10-26) |
| Status | **PROPOSED.** Every recommendation below is a PROPOSAL. Nothing here records an approval by the owner or by counsel, and nothing here authorizes a host, provider, real-data, routing or launch act. The simulated council of `030` is not legal counsel. |
| Owner | Jeremy Longshore |
| Beads | `211.7.1` (POL-10), `211.7.9` (POL-09), `oc4.8`, `9kg.59`, and the launch-manifest inputs that `9kg.31.6` needs; read on 2026-10-26 |
| Inputs | `002` section 6 (the gates); `011` sections 4 to 6 (D-49 to D-51, the policy register); `029` (sections 1, 6, 7, 9 to 14 and 17); `030`; `026` sections 6 and 16; `027`; `019` (only the separation of dogfooding from selection validation) |
| Code read | `main` at `2a19730`, re-checked at `e9193db` (PR #103 merged) for the replay statements: `erasure/registry.py`, `erasure/catalog.py`, `erasure/record.py`, `erasure/service.py`, `agreements/custody_policy.py`, `agreements/keystore.py`, `config/backup.py`, `config/settings.py`, `config/guards.py`, `assessments/decisions.py`, `assessments/runs.py`, `applications/management/commands/catalyst_invite.py` |
| Merged since drafting | PR #103 (`9kg.25`): erasure replay after a restore, merged 2026-10-26 as `e9193db`. Stated limit filed as `9kg.71`. Merged the same day: PR #104 (`9kg.69`, `0691e02`), #105 (`9kg.70`, `4fc527a`), #106 (`9kg.60`, `7aed4ac`), #107 (`9kg.72`, `0211ce9`). |
| Companion | `032` (release control, the host preflight request and the host preparation request) |
| Classification | Public repository. No applicant data, agreement text, credentials, private paths, named private holders, brain content or transcripts. Roles are named; people are not. |

> **How to read this.** Section 7 is the one-page summary. Sections 2 and 3 are the two policies that gate the first
> real submission (POL-10 and POL-09). Section 4 answers two narrow owner questions. Section 5 lists what the launch
> manifest still lacks. Section 6 is the question list for counsel, not sent. Section 8 lists the conflicts between
> plans and code found while drafting. Labels: **PROPOSAL** (a recommendation awaiting the owner); **INPUT** (a fact or
> value only the owner can supply); **COUNSEL** (a legal question); **EXISTING** (a value already in `029`, `030` or
> the code); **NEW** (no earlier value exists; this document proposes one for the first time).

Boundaries used throughout:

| Code | Boundary |
|---|---|
| A | Repository work and synthetic tests |
| B | The read-only production-host preflight (`9kg.42`) |
| C | Host preparation and the synthetic dark deploy (`9kg.28`, `9kg.31.5`, the production restore drill, `dy7.3`) |
| D | The live-provider canaries (`9kg.31.1` to `.3`) |
| E | GATE-PILOT (`9kg.31.6`) and real internal intake |
| F | Wider enrollment and the public cutover (`9kg.31.10`, GATE-CUTOVER) |

## 1. Scope reminder

- **Real production.** The pilot is the first production deployment. Its users are the owner and a named internal
  cohort. Their information is real personal data from the first real submission onward (`029` section 1, D-51).
- **A dedicated v2 host name.** The cohort reaches v2 on its own host name, per `030` Q1 (D-A, provisional), unless
  the owner supersedes it. The learning host's proxy configuration stays byte-untouched; the preflight records its
  hash before and after the new site block.
- **Nothing of the first-generation service changes.** Learn routes, legacy applicants, the links already in their
  hands, the signing callbacks, the first-generation mailbox and the ownership of its automation all stay as they are.
  No live first-generation case moves.
- **The Learn path switch is GATE-CUTOVER, not GATE-PILOT.** `002` section 6: GATE-CUTOVER applies whenever live
  routing or the execution ownership of a first-generation case changes. GATE-PILOT enables nothing on the learning
  host.
- **Model advice and evidence fetching stay disabled.** Both are off for the initial scope unless the owner decides
  otherwise in a separate record (D-D5, D-E; `029` section 7). The code holds `CATALYST_ASSESSMENT_MODEL = "none"` and
  an empty fetch allow-list.
- **Mailbox provisioning only as the manifest and its canary allow.** D-F is a fixed rule: provisioning disabled, no
  drill touches an existing mailbox, and the provisioning credential is absent from the host. `9kg.31.3` closes as
  "not enabled" unless the owner names a participant and the MXroute canary passes.
- **Dogfooding is not selection.** The internal launch is an operational exercise. It is not an appraisal of existing
  members, it must not inform employment decisions, and it does not validate candidate-selection quality (`019`;
  `029` section 1). D-M records that the cohort is not candidate-impacting selection on four conditions; the answer
  lapses if model advice is enabled or anyone outside the roster enters.

## 2. POL-10: retention, deletion and erasure (`211.7.1`)

### 2.1 What the code does today

- **The registry** (`erasure/registry.py`) has one row per data class. Each row has a `treatment` and a `retention`,
  and every value ships `undecided`.
- **One treatment per class, applied at every erasure.** `catalyst_erase` passes every class the registry marks
  `anonymize` to the database function in one call. A class marked `retain` is never reached by the command. There is
  no per-person or per-outcome treatment.
- **The `retention` value is text that nothing applies.** The docstring says so: "Nothing applies a retention period
  yet." Retention happens only when someone runs `catalyst_erase`.
- **Refusals while undecided.** A new erasure refuses (`registry_undecided`). `catalyst_backup` refuses in a live
  environment (`production` is the only live environment), and health reports `backup.registry_blocked`. On `main`
  the registry reported `replay:not_built` until PR #103 (merged as `e9193db`) removed it, so now a decided registry alone
  unblocks a live backup.
- **Erasure preconditions** (database function, built): every application of the person is terminal (declined,
  withdrawn or closed); nothing of theirs is queued, running, held or uncertain; every access revocation is final. A
  pause with held work therefore blocks an erasure until the work settles (the built default).

### 2.2 Proposed retention clocks (PROPOSAL, NEW)

Because one erasure applies every anonymized class at once, the simplest workable policy is **one clock per person**,
chosen by how their case ended, not one period per class. Different periods per class for the same person would need
either a code release at each step (the registry is a reviewed constant) or a new command option. The proposal
avoids both.

| Clock | Applies to | Starts at | Proposed period (NEW, for counsel to replace) |
|---|---|---|---|
| R1 | A person declined or withdrawn before any agreement was issued to them | the terminal history event (decline or withdrawal) | 12 months |
| R2 | A person invited who never applied (the invitation expired, was superseded or was never used) | the invitation's expiry | 3 months |
| R3 | An admitted participant: any agreement issued in v2, or a first-generation agreement recorded on file | the closure of the participant's application (the end of the engagement) | the period counsel names for the agreements; no figure is proposed here, COUNSEL |
| R4 | A request for erasure from the person | the request | erase within 30 days once the application is terminal and no hold applies |

A hold (section 2.3, "Hold exception" column) stops every clock until it is lifted.

### 2.3 The data-class table

Operator roles (no personal names): **Owner**; **Retention operator** (the owner unless the owner delegates by a
recorded named grant; holds the retention login on the erase service); **Custody recovery holder** (section 3);
**Agreement decision-maker** (the staff group of that name). Evidence names: the erasure record entries in the effect
journal (`erasure_intent`, `erasure_complete`, `erasure_handoff`, `custody_key_destroyed`), each with its mac; the
journal **head** printed after each step and copied off-host by the owner; `catalyst_erasure_record --expect-head`
reporting no open intent and no owed handoff.

: POL-10 per data class, proposed. Every treatment and period is a PROPOSAL.

| Data class | What the data is | Proposed treatment | Proposed retention and starting event | Hold exception | Operator role | Evidence that completes an erasure |
|---|---|---|---|---|---|---|
| `application_identity` | The application's address, address key and display name; the address on each contact challenge | anonymize (EXISTING mechanism: text to `[erased]`, the key to `erased:<public reference>`) | R1, R3 or R4 by outcome | legal hold; open application, work or revocation (built refusal) | Retention operator | intent and completion `erased`; head copied off-host |
| `submissions` | Submitted answers in each submission version; the adoption record itself is kept | anonymize | as `application_identity` | as above | Retention operator | as above |
| `history_events` | The data of application history events; kind, actor and time are kept | anonymize | as above | as above | Retention operator | as above |
| `mail_derivatives` | Inbound mail records (headers, redacted text, attachment list), outbound recipients, frozen approved bodies, staff drafts, questions, reply interpretations | anonymize (must match `application_identity`: retaining a key-selected class while anonymizing identity is refused by the registry) | as above | as above | Retention operator | as above, plus `mail_sent` and `mail_inbox` handoffs (section 2.6) |
| `staff_notes` | Free text staff wrote about the person: item resolutions, revocation notes, evidence notes, document-access reasons | anonymize | as above | as above | Retention operator | as above |
| `agreement_records` | The applicant's recipient name and address on agreements; required-details versions (POL-18, the most sensitive) | anonymize | R3 (agreements issued) or R1/R4 | as above; COUNSEL on records the company must keep | Retention operator | as above |
| `decisions` | Qualification decision text, human-only reason and rationale notes; ratings, outcome and codes are kept | anonymize (`029` 6.1 asked erase or anonymize; anonymize is the superset) | as above | as above | Retention operator | as above |
| `evidence` | Evidence URLs and captured text, assessment snapshots and outputs (at launch: claims refused, no fetch, runs refused by suspension) | anonymize | as above | as above | Retention operator | as above, plus a `model_provider` handoff the code reports even though no request was sent (section 8, item 4) |
| `provisioning_records` | The reserved mailbox name, setup and withdrawal recipients, provisioning evidence facts (disabled at launch) | anonymize | as above | as above; the mailbox-name reissue question (section 5) | Retention operator | as above, plus `mail_host_mailbox` if a mailbox was created |
| `invitations` | The invitation's address key and note; issuer, times and wording digests are kept | anonymize | R2, or with the person's application clock | as above | Retention operator | as above; see section 2.5 for the missing reference |
| `member_on_file` | The first-generation agreement-on-file record's address key; the agreement labels and the recorder are kept | anonymize (must match `application_identity`) | R3 | as above; the record is the reason no decline was recorded | Retention operator | as above |
| `pauses` | The free-text reason of an automation pause; the pause row is never deleted | anonymize | with the person's clock | a pause with held work refuses the erasure (built) | Retention operator | as above |
| `jobs` | The error text of the person's pending actions | anonymize | with the person's clock | as above | Retention operator | as above |
| `audit_residue` | Earlier retention audits' free-text reason and unkeyed row digest | anonymize (COUNSEL: `029` 6.2.1 leaves this to counsel) | with the person's clock | as above | Retention operator | as above |
| `throttle_keys` | The intake throttle bucket keyed on an unkeyed digest of the address | anonymize (the row is deleted) | one throttle window; swept hourly by code (EXISTING, `029` 13.4) | none | none (automatic) or Retention operator at erasure | deletion counted in the completion |
| `admin_log` | The admin log's text for the person's application rows | anonymize | with the person's clock | as above | Retention operator | as above |
| `signed_documents` | v2's encrypted custody copy of signed PDFs and audit certificates | `destroy_key` (EXISTING mechanism, `9kg.34`) | R3; COUNSEL on a jointly signed document (`211.7.9` acceptance) | legal hold; dispute over the agreement | Retention operator; Custody recovery holder for recovery only | `custody_key_destroyed` entries (mirror first), completion `keys_destroyed`; `retained` no longer lists `custody_documents` |
| `provider_copies` | The Documenso copy (envelope, signed PDF, audit certificate); the mail host's Sent and inbox folders for v2's mailbox; a provisioned mailbox; anything a model provider kept | `manual_handoff` (the only supported value) | within 30 days after the erasure (NEW) | legal hold; COUNSEL on the provider's own retention | Owner | one `erasure_handoff` per owed provider with its completion date; head copied off-host again |
| `erasure_record` | The durable record: per person, the keyed hash of the address under the erasure key, the key id, codes, classes, handoffs, counts and times | `retain` (the only supported value) | for the deployment's life until journal rotation (`9kg.61`) exists; never below the oldest restorable backup (EXISTING floor) | not applicable | Owner | not erasable by design; COUNSEL on keeping it (section 6) |
| `effect_journal` | The hash-chained journal holding the erasure record and the effect entries: public references, opaque staff references, codes, digests, counts, times | `retain` | as `erasure_record`, and at least as long as any stale custody key copy could survive (`9kg.28` note) | not applicable | Owner | not erasable by design; off-host copy by `9kg.60` |
| Backups (not a registry row) | The nightly logical dump with the custody files, the host archive and the object-locked off-site copy | none by code: sets age out on the estate's schedule (figures in the private backup record) | EXISTING estate retention per leg | not applicable | Owner | the replay after a restore (PR #103) re-erases before release; the lift requires the replay marker |

### 2.4 What tombstoning actually leaves

Counsel needs this list to judge whether anonymization satisfies a "delete" instruction. After `catalyst_erase` with
every subject class anonymized and `signed_documents` at `destroy_key`:

- **Rows.** Every row stays. Nothing is deleted except the throttle bucket. The person's application row still
  exists with its stage, public reference and times; each child row still points at it.
- **Relationships.** Every foreign key is intact: submission versions and the adoption records that bind them,
  contact challenges, history events, questions and reply links, outbound attempts, inbound messages, agreement
  instances, recipients, provider observations, stored-document and custody-envelope rows, decisions, assessment
  runs, provisioning rows, pauses and pending actions.
- **Counts.** How many submissions, events, questions, messages, attempts, agreements, documents and decisions the
  person had is readable from the row counts. The backup manifest also holds per-table counts.
- **Timestamps.** Every time column is kept: created, updated, received, sent, signed, decided, verified, expired.
- **Public references and provider identifiers.** Random public references (UUIDs) of the application, invitation,
  challenges, messages and agreements; the agreement external keys (`ag_` prefix) and the Documenso envelope
  identifiers, which still point at the provider's copy until the handoff; outbound Message-ID values, which match
  the mail host's Sent copies.
- **Codes, digests and ratings.** Stage and status codes, reason codes, decision outcomes and ratings (rationale notes
  become `[erased]`, ratings stay), model and prompt identifiers, and digests of high-entropy content (approved
  message content, inbound originals, snapshots, stored documents' plaintext hash). A digest can confirm a guessed
  value; it does not reveal one.
- **Audit rows.** One new erasure audit row per erasure (the public reference, authority and reason codes, the
  classes, the transaction id, the time and the database role). Earlier retention audit rows stay with their table
  name, row id and actor; their reason and row digest are tombstoned (`audit_residue`).
- **Staff data.** Staff actor references and staff names stay; they are POL-13 data, not the applicant's.
- **The keyed hash.** The erasure record in the effect journal holds HMAC-SHA-256 of the normalized address under the
  erasure key. Whoever holds that key can confirm a guessed address. The database holds no hash.
- **Kept on purpose by the member-on-file and invitation rows.** The agreement version labels, the recorder, the
  issuer, the times and the wording digests.
- **Sealed custody files.** They stay in custody and in every backup, unreadable without a surviving copy of the
  wrapped key plus the wrapping key (section 3, rotation).
- **Old row versions.** Until the owner runs `VACUUM` on the touched tables (`026` section 16, runbook step 5), the old
  values remain in the database files.
- **Outside the database.** Provider copies until the handoffs are done; backup sets until they age out; mail-host and
  provider backups outside the estate's control.

### 2.5 The retention-application gap

**The gap.** The registry records periods that nothing applies. GATE-PILOT requires "retention and erasure enforced"
(`002` section 6).

**A manual procedure for the small cohort (PROPOSAL).**

1. **Who.** The Retention operator, on the host's erase service, which holds the retention login and the erasure key
   only (`026` section 16).
2. **How often.** Monthly, and within five working days of an erasure request.
3. **Find what is due.** Until `9kg.75` lands: in the read-only staff admin, list applications filtered by stage
   (declined, withdrawn, closed); open each dossier and read the date of its terminal history event; compare with R1
   and R3 and with the private hold list. Once it lands, `catalyst_retention_due` (`9kg.75`) lists the due public
   references by rule.
4. **Erase.** For each due person, run `manage.py catalyst_erase --subject <public reference> --authority <code>
   --reason <code>` with codes such as `pol-10` and `retention_period_elapsed` or `subject_request`. Then follow the
   existing runbook (`026` section 16, steps 2 to 7): copy the head off-host, do each owed handoff and record it with
   `--handoff`, run `VACUUM`, and verify with `catalyst_erasure_record --expect-head`.
5. **Record.** A private review record per run: the date, how many applications were reviewed, the public references
   erased and held (with a hold code), and the final head. Never in the repository.

**Does it meet the proposed policy?** Partly.

- **Meets** R1, R3 and R4 for every person who has an application. The cohort is small; the staff admin lists stage
  and creation date and the dossier shows the terminal event.
- **Does not meet R2.** An invited person who never applied can be erased only by the invitation's public reference.
  `catalyst_invite` does not print that reference, and no staff screen lists invitations. The operator cannot name the
  subject without a database read.
- **Does not reach unassociated inbound mail.** Mail from an address that never had an invitation or an application
  has no erasure subject at all. `catalyst_erase` finds a person only through an application or an invitation. `9kg.71`
  describes the same lookup gap for the replay only. Likelihood is low under invitation-only intake (a misdirected or
  stray sender), but it is not zero.
- **Records erasures, not reviews.** A month with nothing due leaves no journal entry; the private review record
  covers it.
- **Is enforcement by procedure.** "Enforced" in GATE-PILOT then means a recorded owner procedure, not a mechanism.
  The owner must accept that reading explicitly in the go/no-go record.

**The smallest mechanism (PROPOSAL).** No automatic erasure job: the worker can never hold the retention login, and
an owner act per erasure is the right control for this cohort. Instead:

1. `catalyst_invite` prints the invitation's public reference, and one read-only report command lists, by public
   reference only, the terminal applications past their clock and the expired, never-used invitations. No names, no
   addresses. Filed 2026-10-26 as `9kg.72` (the reference and an address lookup, merged as PR #107) and `9kg.75` (the due
   report); the go/no-go `9kg.31.6` depends on both. Boundary: E, because R2 cannot be applied without them. A
   first-generation member record with no application or invitation still has no reference the erase function
   resolves (stated in `026`).
2. Widen `9kg.71` from replay to live erasure: one security-definer lookup that matches candidate keyed hashes
   against unassociated inbound mail serves both the erasure command and the replay. Boundary: F (the risk grows with
   open intake); before E only if the owner judges stray mail likely.

### 2.6 Provider copies, backups, the journal and the erasure record

- **Documenso.** The provider keeps the envelope, the signed PDF and the audit certificate. P4-D-15 governs until
  POL-10. PROPOSAL: delete the envelope at the provider within 30 days of the person's erasure, then record
  `--handoff documenso`. Before the first real deletion, the Documenso canary must show whether deleting an envelope
  emails its recipients (the `documentDeleted` setting is NOT VERIFIED, `029` section 5.2). Deleting the provider copy
  also removes the last recovery source if both custody key directories are ever lost (section 3).
- **The mail host (Sent and inbox of v2's own mailbox).** PROPOSAL: delete the messages to and from the person within
  30 days, then record `--handoff mail_sent` and `--handoff mail_inbox`. The mail host's own backups are outside the
  estate's control: COUNSEL.
- **A provisioned mailbox.** Not applicable at launch (provisioning disabled). If enabled later, the mailbox is
  removed at the provider and recorded with `--handoff mail_host_mailbox`.
- **The model provider.** Nothing is sent at launch. The code still reports a `model_provider` handoff whenever the
  person has an assessment run row, and a run refused by the suspension leaves one (section 8, item 4). PROPOSAL:
  record that handoff with a private note "no request was sent", and fix the report in code before wider enrollment.
- **Backups.** Not a handoff. Sets keep the data until they age out on each leg's schedule; one leg is object-locked.
  After a restore, the replay (PR #103, merged) re-erases every recorded person before the review, and the lift refuses without
  its marker. COUNSEL: whether the privacy notice must state the ageing-out window (`026` section 6, option (a)
  wording).
- **The effect journal and the erasure record.** Kept outside the backup, append-only, never rotated by code. They hold
  no address, name or body. The record keeps a keyed hash per erased person, which is personal data under POL-10.
  PROPOSAL: keep both for the deployment's life until `9kg.61` rotation exists; ship the journal off-host (`9kg.60`)
  before E; until then, the owner copies the head and the person's entries off-host after every erasure.

### 2.7 What the registry would read if adopted

For the reviewer of a later code change, not a decision: every subject class `anonymize` with retention text naming
the person's clock (R1 to R4); `signed_documents` `destroy_key` with R3; `provider_copies` `manual_handoff` with "30
days after the erasure"; `erasure_record` and `effect_journal` `retain` with "deployment life; floor: oldest restorable
backup". Changing a row is a reviewed code change and a release.

## 3. POL-09: custody of signed documents (`211.7.9`)

The mechanism is built (`9kg.34`): AES-256-GCM per document, data keys wrapped under one wrapping key, wrapped keys in a
key directory and a live mirror outside the database, the custody directory and every backup set. Six rows of
`agreements/custody_policy.py` ship `undecided`, and a live environment refuses custody while any is open.

: POL-09 rows. Every answer is a PROPOSAL; inputs are the owner's.

| Row | What it decides | Recommendation | Owner input still needed |
|---|---|---|---|
| `location` | Where the custody directory, the key directory and the key mirror live | Under the managed data root of the v2 stack; custody inside the volume the restore writes into; the key directory and the mirror on two different devices, both outside every archive (the host archive uses an include list that names neither; `9kg.28` note) | INPUT: the concrete locations, recorded in the private operations record; whether the host offers a second device for the mirror (the preflight answers) |
| `access` | Who may retrieve a document | Agreement decision-makers only (permission `retrieve_agreement_document`), through the web process only (D-51, P4-D-16, EXISTING) | INPUT: who holds the Agreement decision-maker role (section 5) |
| `recovery_holder` | Who holds the wrapping key's escrow copy and runs `catalyst_custody_keys --recover` | The owner, as a role ("owner") (EXISTING proposal in `026` section 16); NEW: no deputy holds the escrow during the internal launch | INPUT: whether a deputy is named for the observation period |
| `recovery_time_bound` | How fast custody reads are restored after a key-store loss | 24 hours (EXISTING proposal); the worker is stopped meanwhile, the web serves everything but retrieval | none beyond acceptance |
| `escrow` | Where the wrapping key's recovery copy lives | The estate's encrypted secret store, wrapping key only, never a data key (EXISTING proposal) | INPUT: which store entry and which recipients can decrypt it (private record) |
| `provider_copy` | Treatment of the provider's copy | Keep it for the R3 period; delete it as an erasure handoff (section 2.6); COUNSEL on a jointly signed document | none beyond section 2 |

**The recovery-copy arrangement.** The mirror is a live copy written before each document is sealed and destroyed
before the primary. It is never a point-in-time copy: neither key directory may be in any versioned backup, snapshot
or archive. The `9kg.28` host list carries the proof that both are absent from the newest host archive, the dev-box
replica and the off-site listing.

**Destruction.** An erasure under `destroy_key` journals `custody_key_destroyed` with its mac for each key, then
unlinks the mirror's copy, then the primary's, and verifies both are gone. It needs the key directories and the
erasure key, never the wrapping key. A person whose document is still in the clear is refused before any record.

**Recovery.** The runbook in `026` section 16: stop the worker, read `--status`, re-provision a lost directory, fetch
the wrapping key from escrow for the run only, run `--recover --expect-head <the last off-host head>`, confirm
`healthy`, restart, remove the escrow copy from the host. If both directories are lost, v2's copies are lost and the
provider's copy is the only source; a re-fetch is a separate owner act.

**Wrapping-key rotation (`9kg.69`, in progress).** The only way to retire remnants of destroyed keys (unlinked
blocks, snapshots, swap or core dumps) is to rewrap every live data key under a new wrapping key and destroy the old
one and its escrow copy. `9kg.69` builds that as an owner-run, journaled command. PROPOSAL (NEW): rotate within 30 days
after any erasure that destroyed keys, at least once a year, on suspected leak, and on any change of escrow recipients.
The interval and the escrow procedure become a custody row in `027` (part of `9kg.69`'s acceptance). Until `9kg.69`
merges, the destruction claim carries the remnant limit stated in `029` section 6.2.2.

**Host conditions (not a decision, a requirement on `9kg.28`).** The processes that hold the wrapping key (web,
worker, the owner-run custody commands) run without swap and with core dumps disabled. Key volumes and the wrapping
key reach no other process.

**Boundary.** Custody refuses in production while any row is undecided, and the Documenso canary includes a custody
download and integrity check on the dark-deployed stack. So these rows block **D**, not only E. The bead graph has
`211.7.9` blocking `9kg.31.6` and `9kg.31.7` but not `9kg.31.2` (section 8, item 2).

## 4. Two narrow owner questions

### 4.1 `oc4.8`: what clears a capped assessment snapshot

**The question, quoted from the bead.** "Owner decision: what clears a capped assessment snapshot, then give staff
that path without a shell." Its description: "once a snapshot's request budget is spent, a rerun ends capped again
and re-fetching is only possible in the evidence stage, so a case can sit in assessing. Options: a recorded
per-application budget top-up, or a staff close-assessment path (which, with the proposed P3-D-10 amendment, could
route to human-only assessment)." Its 2026-10-24 note adds: "`CATALYST_CAPPED_EXIT` defaults to `human_only` ... `none`
(wait for the owner's budget decision) is the more conservative value. Not ratified."

**Current behaviour (code).** `config/settings.py` fixes `CATALYST_CAPPED_EXIT = "human_only"`. In
`assessments.decisions.human_only_code`, a capped run on the current snapshot, or a case at the run cap, opens the
authority-gated human-only decision form. With `none`, the case stays in assessing until closed. At the internal
launch the model is `none`, so every case returns `advice_suspended` before the capped branch is reached: a capped
snapshot cannot occur at launch. The screen path is built and tested (`029` appendix B, row 11).

**Recommendation (PROPOSAL).** Ratify `human_only`: a capped or refused case leaves assessing only through the
existing human-only decision form, which keeps the decision backstop. No budget top-up feature. Record the decision in
`011` section 4; the bead's acceptance test exists, so the bead can then close.

**Boundary.** None of A to E (unreachable while the model is off). F, or any earlier decision to enable model advice.

### 4.2 `9kg.59`: the pause-row DELETE

**The question, quoted from the bead.** "Owner decision: replace the application role's DELETE on pause rows with a
security-definer resume function, or accept code-level authorization for resume." Options: "(a) accept, with the
limit recorded in 016 section 10.13 (done in PR #88); (b) revoke the app role's DELETE on the pause table and expose a
SECURITY DEFINER resume function that writes the event, requires the note length and checks the open-cause rule in
SQL." "Earliest boundary blocked: none at launch."

**Current behaviour (code, workflow migration 0005, `9kg.6`).** A deferred constraint trigger refuses, at commit, any
DELETE of an application's pause unless the same top-level transaction inserted an `automation_resumed` history event
by staff with an actor reference (and, for a system pause, a note of at least ten characters). An UPDATE of a pause is
refused outright. Who may resume and whether a cause is still open are checked in code only. A compromised
application role could insert the event itself and then delete the pause. The limit is stated in `016` section 10.15
(the bead points at 10.13; section 8, item 9).

**Recommendation (PROPOSAL).** (a) for the internal launch: accept code-level authorization with the limit recorded.
The supported path is the staff screen; the forged-event path needs a compromised application role, which already
implies a wider compromise; every resume leaves a history event, and `aged_waits.pauses` and the grant-ledger audit
make unexpected changes visible. Revisit (b) before wider enrollment or when more than the owner holds resume rights.

**Boundary.** None of A to E. F (optional).

## 5. Launch-manifest inputs still outstanding

Read first: D-49, D-51 (provisional answers to D-A to D-M) and the bead notes of 2026-10-23 to 2026-10-26. This list
names only what no record yet supplies.

### 5.1 Wording and template versions

- **Message templates, one approved version each with its digest:** `data_notice`, `invitation`, the verification
  message, staff questions, reminders and `decline_notice`. D-51 holds them before the mail canary; the decline notice
  and the data notice also gate E (a live environment refuses an unapproved or synthetic version). The data notice's
  erasure sentence depends on section 2.
- **Agreement templates on v2's own Documenso team:** the NDA and User Agreement versions, their provider template
  references and the registered PDF digests. The decision on binding the registered digest to the provider-side
  template (forbid in-place edits and rely on new versions, read back a digest if the installed version exposes one, or
  accept the risk) is open on `211.7.4`.
- **Decline wording slots** (COUNSEL, `211.7.4`): whether a reason may be requested, whether a new request may be made,
  what is kept and how to request erasure, whether replies are read; and the rule for when staff may withhold the
  notice.

### 5.2 Staff authority (roles only; holders in the private record)

INPUT: who holds each of these, recorded privately before host preparation (D-51 hold for devices and holders):
qualification decision-maker (D-D4: the owner); Agreement decision-maker; Agreement operator; Agreement template owner;
correspondence operator and decision-maker; template owner for message templates; Retention operator; Custody recovery
holder; the break-glass two-factor reset holder; the incident owner and the deputy for the observation period (`029`
section 10); provisioning approver (only if provisioning is enabled). Also: the named staff devices, their enrolment
method and the staff host name (`211.7.5`).

### 5.3 The cohort

PROPOSAL for the selection rule: the owner first, then current team members the owner names, each of whom has
received the data notice and either has both first-generation agreements recorded on file (option (a) of `211.7.4`) or
signs as a new participant. Nobody outside that roster. INPUT: the number of people, stated as a count or an upper
bound in the go/no-go record (names stay in the private record; per `211.7.6`, no count below a safe size is
published).

### 5.4 Configuration still open

| Item | Today | Decision needed | Boundary |
|---|---|---|---|
| `CATALYST_CHALLENGE_LIFETIME_SECONDS` (POL-02) | required, no default in code | a value; a provisional value suffices for C (no applicant route), the approved one before D (D-51) | C, D |
| Invitation lifetime, verification resend limit, withdrawal-link lifetime (open since D-48) | 14 days; 3; synthetic | production values (`211.7.7`) | E |
| Reminder cadence, maximum, quiet hours (`CATALYST_REMINDER_*`) | synthetic defaults | production values (`211.7.7`) | E |
| Public-endpoint throttle limits (`CATALYST_THROTTLE_*`) | synthetic placeholders | values (POL-16, `211.7.2`) | E |
| Aged-wait thresholds and the page list; the countersignature wait's page threshold | three default classes page | values (`211.7.2`, D-51) | C (alerts at the dark deploy) |
| RPO and RTO; the journal's own RPO and destination (`9kg.60`) | proposals in `029` section 10 | ratified from the production restore drill | E |
| `CATALYST_QUALIFICATION_AUTHORITY` on the host | unset (everyone refused) | `explicit_permission`, with the grant to the owner (`211.7.8`) | E |
| Admitting `production` to the allowed environments, and the production provider settings fixed in code (the release decision; P6-D-6 guard amendment) | refused at start-up | a reviewed release; no bead owns it (section 8, item 3) | C |
| The erasure registry and the custody rows | undecided | sections 2 and 3 | C (live backup), D (custody), E |
| Documenso: who sends the signing request, provider reminder cadence, envelope expiry, the countersigner's role (second signer or approver) | P4-D-4 default: the provider sends | `211.7.4` | D |
| Members on file: option (a), both agreements on file, so D-15 stays | (a) recommended | `211.7.4` | E |
| POL-03 form fields and POL-18 details list | synthetic | `211.7.8` | E |
| Two human-only selection rules ("not_shown" needs observed evidence; "decline" needs a not_shown with moderate or strong strength) and the source of the shell-or-database-edit count | not built | `211.7.8` | E |
| The personal-data scan for the first real receipt: fixture names only, or a host-local deny-list | fixture names only | `211.7.1` | E |
| Restore choices: `--expect-manifest-sha256` mandatory (default yes); a journal fault during backup; a restore with a missing journal by override only; RD-1 (reconcile role), RD-2, RD-3 | defaults built | `211.7.2`, `211.7.5` | C (drill), E |
| Reissuing an erased mailbox name; whether a pause with held work outranks an erasure | defaults built (keep reserved; refuse) | `211.7.1` | E |
| Rotation intervals per secret class, including the erasure key and the wrapping key | none set; `027` has no row for either key | P6-D-15; `9kg.69` adds the custody row | E |

## 6. Questions for counsel

**Not sent. External sending needs the owner's authorization.** These are the genuinely legal questions only; the
facts behind each are in sections 2 and 3.

1. For each data class of section 2.3, what retention period applies to (a) a declined or withdrawn applicant, (b) an
   invited person who never applied, and (c) an admitted participant whose agreements are in force or ended? What is
   the legal basis for keeping each?
2. Does anonymization as described in section 2.4 (rows, relationships, counts, timestamps, public references,
   provider identifiers, digests, audit rows and a keyed hash all kept) satisfy a deletion or erasure request? If not,
   which residue must go?
3. May the erasure record keep a keyed hash of an erased person's address, for how long, and must the privacy notice
   say so?
4. May the company keep its copy of a jointly signed NDA or User Agreement after the participant asks for erasure,
   and for how long? Must the provider's copy be deleted, and on what timeline?
5. Is it acceptable that backups keep erased data until they age out (one leg object-locked), given that a restore
   re-erases before any use? What must the notice say about that window?
6. Do the provider terms (signing provider, mail host) allow and require deletion on request? Are the providers'
   own backups an issue for this cohort?
7. Does a first-generation NDA and User Agreement already on file cover v2's processing for an existing member
   ("referenced, not re-signed", D-D)? If not, what must the member sign?
8. Is the one-paragraph data notice (`9kg.52`) sufficient for team members, or does using real team members' data in a
   production exercise need more (consent, a separate notice, a works-related assessment) so that the exercise cannot
   be read as appraisal or used for employment decisions?
9. Who may impose and lift a legal hold on a person's records, and what triggers one?
10. Should the earlier retention audits' reason text and digest (`audit_residue`) be kept as audit evidence or
    anonymized with the person?
11. What may the decline notice say (the slots in section 5.1)?
12. Is the owner's hand countersignature in v2's own Documenso team acceptable for v2 agreements (D-D)?

## 7. One-page summary

: Each decision, the recommended answer and the boundary it blocks. Every answer is a PROPOSAL.

| # | Decision | Bead | Recommended answer | Blocks | Decides |
|---|---|---|---|---|---|
| 1 | Per-class treatment | `211.7.1` | every subject class `anonymize`; `signed_documents` `destroy_key`; `provider_copies` `manual_handoff`; record and journal `retain` | C (a live backup refuses while undecided), E | owner with counsel |
| 2 | Retention clocks | `211.7.1` | one clock per person: R1 12 months, R2 3 months, R3 counsel's period, R4 30 days | E | owner with counsel |
| 3 | Hold exceptions | `211.7.1` | owner records holds privately; counsel resolves disputes; built refusals stand | E | owner with counsel |
| 4 | Provider handoffs | `211.7.1` | within 30 days after the erasure; Documenso deletion behaviour checked at the canary first | E | owner with counsel |
| 5 | Erasure record and journal retention | `211.7.1` | deployment life until `9kg.61`; floor: oldest restorable backup; off-host by `9kg.60` before E | E | owner with counsel |
| 6 | How retention is applied | `211.7.1` | monthly manual procedure (section 2.5), accepted as "enforced" in the go/no-go record | E | owner |
| 7 | Mechanism for R2 | `9kg.72` (merged, PR #107) and `9kg.75` (filed 2026-10-26, open) | print the invitation reference and look up references by address (`9kg.72`); a read-only "retention due" report (`9kg.75`) | E | owner |
| 8 | Unassociated inbound mail | `9kg.71` | widen to live erasure | F | owner |
| 9 | Custody location | `211.7.9` | under the managed data root; key directory and mirror on different devices; outside every archive | C (mounts), D | owner |
| 10 | Custody access | `211.7.9` | Agreement decision-makers only, through web | D, E | owner |
| 11 | Recovery holder and time | `211.7.9` | the owner; 24 hours | D | owner |
| 12 | Wrapping-key escrow | `211.7.9` | the estate's encrypted secret store, wrapping key only | C | owner |
| 13 | Wrapping-key rotation | `211.7.9`, `9kg.69` | within 30 days after a key-destroying erasure, yearly, on leak, on escrow change | D (`9kg.69` blocks `9kg.31.2`) | owner |
| 14 | Capped snapshot | `oc4.8` | ratify `human_only` | F | owner |
| 15 | Pause-row DELETE | `9kg.59` | accept (a) for the internal launch; revisit (b) before F | F (optional) | owner |
| 16 | Message templates and digests | `211.7.7`, `211.7.4` | one approved version each before the mail canary | D, E | owner (counsel for the notices) |
| 17 | Agreement templates and digest binding | `211.7.4` | v2's own team; forbid in-place edits at the provider | D | owner with counsel |
| 18 | Staff holders and devices | `211.7.5`, `211.7.8` | recorded privately before host preparation | C | owner |
| 19 | Cohort | `211.7.6`, `9kg.31.6` | owner first, then named team members; count stated | E | owner |
| 20 | Lifetimes, cadence, throttles, thresholds | `211.7.7`, `211.7.2` | synthetic defaults as starting values; challenge lifetime set before C | C (lifetime, page list), E | owner |
| 21 | Production environment admission | `9kg.31.11` (filed 2026-10-26; blocks `9kg.31.5`) | a reviewed release that admits `production` and its provider settings | C | owner |
| 22 | Coexistence | `211.7.3` | D-51 as provisional; recorded final on the preflight's evidence | C | owner |
| 23 | Documenso sender, reminders, expiry, countersigner role | `211.7.4` | provider sends; owner countersigns by hand in v2's team | D | owner with counsel |
| 24 | Members on file | `211.7.4` | option (a): both agreements on file | E | owner with counsel |
| 25 | Counsel questions | section 6 | send after the owner authorizes | E | owner |

## 8. Conflicts found while drafting

Follow-up recorded on 2026-10-26 by the main session (the numbers are this section's):

- Item 1 (no production backup before POL-10) is the owner's choice, recorded on `9kg.31.5`: decide POL-10 first
  (recommended), or run the dark deploy without the backup and restore proofs and take them after POL-10, before the
  go/no-go.
- Item 2: `9kg.31.2` now depends on `211.7.9`, and host preparation `9kg.28` does too (the custody locations).
- Item 3 (production cannot start) is bead `9kg.31.11`; the dark deploy `9kg.31.5` depends on it.
- Item 4 (a vacuous model-provider handoff) is bead `9kg.73`, non-blocking. It applies only to a person with an
  assessment run row (a run queued, then refused by the live-call suspension); a human-only decision creates none.
- Item 6 (a person invited but never applied cannot be named) is `9kg.72` (merged, PR #107); the due report is `9kg.75`. The
  go/no-go depends on both. Unassociated inbound mail stays with `9kg.71`.
- Item 7: `027` now has an erasure-key row (on this branch): routine rotation is not supported, and the leak
  procedure waits on `9kg.74`. PR #104 (merged) added the wrapping-key row.
- Item 8 is settled by PR #103's review fix-ups: the restore service holds the erasure key for the lift only, and the
  review runs without it (the `9kg.28` bead carries the correction).
- Item 9 is noted on `9kg.59`.
- Item 10: `9kg.31.10` now depends on `oc4.7`, `f1u.2`, `.5`, `.6`, `.7` and `.8`, and on `9kg.71`, `oc4.8` and
  `9kg.74`.
- The go/no-go `9kg.31.6` now also depends on `9kg.60` (the journal's off-host copy before real effects).
- Recorded on 2026-10-28 (`033` section 4): item 3 is superseded, since `config/guards.py` now admits `production`; item 1's
  second option is not available as built, since the pre-deploy step refuses to migrate without a backup.

The items below are as found while drafting; the list above records what was done about each.

1. **The dark deploy cannot take a production backup today.** `config.backup.refuse_real_backup_while_undecided`
   refuses in the `production` environment whenever the registry has a problem, whether or not the data is synthetic.
   `030` Q3 and Q10 and `9kg.31.5`'s acceptance expect the dark deploy's nightly backup and the production restore
   drill to run on synthetic subjects before POL-10. Either the registry is decided before that step, or C proves
   everything except the production backup and restore. The 211.7.1 note "the registry is filled only after `9kg.25`
   has landed and been drilled" adds an ordering constraint.
2. **Custody refuses in production while POL-09 is undecided,** and the Documenso canary checks custody on the
   production stack; `9kg.31.2` does not depend on `211.7.9`.
3. **No bead admits `production`.** `config/guards.py` allows only development, test and staging. The custody key
   directories, the provider URL and token, and the webhook secret path are fixed empty in code outside test and
   staging. The host-proof dark deploy of "the current attested `main` digest" (`030` Q10) cannot start on the
   production host until a reviewed release changes that.
4. **A vacuous `model_provider` handoff.** The erase function reports `model_provider` whenever an assessment run row
   exists; a run refused by the suspension leaves one, so every cohort erasure will owe a model-provider handoff for a
   provider that received nothing.
5. **P6-D-13 is only half built.** D-49 decided crypto-shredding "for custody and the most sensitive fields" before
   GATE-PILOT. Custody is built; the required-details values (POL-18) are anonymized and replayed, not encrypted under
   destroyable keys. The owner either accepts anonymization plus replay for those fields or a bead is needed.
6. **R2 has no subject reference** (section 2.5) and **unassociated inbound mail has no erasure subject** (`9kg.71`
   covers replay only).
7. **`026` cites a `027` rotation row for the erasure key that does not exist.** `027` has no row for the erasure key
   or the wrapping key.
8. **The restore service's erasure key.** The brief for PR #103 says the restore service holds the erasure key for the
   lift only; the 2026-10-26 note on `9kg.25` says "for the review as well as the lift". `032` follows the brief and
   asks for confirmation against the merged PR.
9. **`9kg.59` cites the wrong section.** The pause-guard limit is in `016` section 10.15, not 10.13.
10. **`9kg.31.10` names its deferred blockers in notes only.** `030` section 10 directed that it list `f1u.5`, `f1u.2`,
    `f1u.6`, `f1u.7`, `f1u.8` and `oc4.7` as blockers; it has no such dependency edges.
