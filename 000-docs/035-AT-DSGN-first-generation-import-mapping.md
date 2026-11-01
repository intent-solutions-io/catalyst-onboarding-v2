# First-generation import: mapping and run design

| Field | Value |
|---|---|
| Document | 035-AT-DSGN-first-generation-import-mapping |
| Date | 2026-10-31 |
| Purpose | How `catalyst_import_v1` converts every record of the first-generation service into v2's PostgreSQL database: the mapping per first-generation table, the state mapping, what is lossy, what in-flight cases need from v2 afterwards, and how the operator runs it. |
| Owner direction | 2026-10-31: v2 goes live on a dedicated US host whose only database is v2's; the first generation is stopped (not deleted) and all of its data is converted into v2's schema. No copy of the first-generation database lives on the US host. |
| Bead | `catalyst-v2-bgl.16` |
| Status | Built and tested on synthetic data only (section 7). Not yet run against the production first-generation database. |
| Boundary | Describes table and column names of the first generation (034 section 1.5), never its data. No applicant data, credentials, host paths or connection strings. |

Inputs: 034 sections 1.5, 3.4 and 3.5; the first generation's models at its migration 0023; v2's models.
Code: `firstgen/` (models, `source.py`, `mapping.py`, `importer.py`, `threads.py`, the command), `erasure/catalog.py`
and `erasure/migrations/0005_first_generation_import.py`. Tests: `tests/test_first_generation_import.py` with the
synthetic first-generation database in `tests/firstgen_v1.py`.

---

## 1. Shape of the import

- **Read.** One read-only, REPEATABLE READ transaction over the source DSN (`firstgen.source`), so every table is
  read at the same instant. Each table is read with `SELECT *` into plain values: a column the first generation added
  after migration 0023 is carried, never refused. The job queue is counted, with open-job references and only the signing delivery metadata
  needed for timer handover; job payloads and credentials are never loaded. Nothing is written to the source.
- **Write.** The command runs as the migration owner and refuses any other login, because it writes records the
  application role may not (member-on-file records, the import's provenance). One transaction per person (every
  case of one email key): a malformed case fails alone and is reported while the others import. Chose this over one
  transaction for the whole run because one bad first-generation row should not hold 61 other people out of v2, and
  the provenance keys make a re-run resume exactly the failed people. Within each person's transaction the deferred
  decision backstop (assessments 0008) is forced before the commit (`SET CONSTRAINTS ALL IMMEDIATE`), so a dry run
  meets the same refusals a real run would.
- **Idempotent.** Every first-generation case is recorded once (`ImportedCase.v1_case_id`), every first-generation row
  once (`ImportedRecord` unique on table and id). A re-run creates nothing for what exists; a row added to the
  source since (a late case event) is added once. A late row of a table that maps to a v2 record (a revision, a
  credential, details, a mailbox) on an already imported case is kept as a record and reported
  (`late_row_not_applied:<table>`), never applied over the existing v2 records.
- **Dry run.** `--dry-run` runs everything inside one transaction (each person a savepoint) and rolls it back.
- **Schema.** `firstgen` 0001 and 0002 create the three tables after erasure 0004, append-only and readable by the
  application, retention and backup roles; erasure 0005 reinstalls the generated erasure functions with the record
  table's `data` column. Expand-only: the previous image never reads these tables.
- **Nothing automatic.** The import queues no pending action and sends nothing. Every imported application in an open
  stage gets a system safety pause (`workflow.AutomationPause`, reason: imported, awaiting staff review), so no v2
  automation reaches an imported person until a decision-maker resumes it with a recorded reason. Older
  `import:first-generation` pauses require the same review through the staff service. `--schedule-followups` is refused: no v2 action can
  continue a first-generation case without a staff decision first (section 5).

## 2. Mapping per first-generation table

Live row counts are the owner's of 2026-10-31. "Record" means one `firstgen.ImportedRecord` row with the original
row in `data` (erasable, class `history_events`), its original time in `occurred_at` and its application.

| First-generation table | Rows (live) | Becomes in v2 | Notes |
|---|---|---|---|
| `onboarding_case` | 62 | `applications.Application` at the mapped stage (section 3), `firstgen.ImportedCase` (state verbatim, cohort, times, mapped stage, findings), one `ApplicationEvent` `imported_first_generation` | The application's `created_at` is the case's. Open stages get an automation pause. |
| `intake_request` | 62 | `SubmissionVersion` 1 (`origin` `form`, `received_at` the original), plus a record of its non-personal columns | Answers in `submitted_fields` (section 4). The confirm-link token hash is dropped (a secret). A verified address becomes a used `ContactChallenge` and a `VersionAdoption` of version 1 at the verification time. |
| `intake_revision` | 1 | `SubmissionVersion` 2+ (`form`, or `repeat_after_verification` when after the verification), plus a record | Never adopted, as in the first generation. |
| `applicant_credential` | 70 | Rows in the version they belong to: education in `education`, certifications in `claims.credentials`; the full row as a record | Year, verification status and evidence fields are kept only in the record (lossy, section 6). |
| `case_event` | 961 | Record per event (the timeline, original timestamps) | Also read to find a lapse's resume state and a decline's reason. |
| `agreement` | 86 | Record per agreement; completed ones (`completed`, `archived`, `durable`) feed the person's `MemberAgreementOnFile` | Not `AgreementInstance` (section 3.2). An open envelope is a finding and a follow-up. |
| `legacy_agreement_import` | 5 | Record (provenance) | |
| `agreement_details` | 32 | `AgreementDetailsVersion` (User Agreement type, `confirmed`, recorded and confirmed by the import, confirmed at the capture time), plus a record of its non-personal columns | Values keep the first generation's keys (legal name, residence, mailing address, phone, the structured address parts, field set). |
| `ua_details_capture` | 58 | Record; with a case on the application, without one with no application | Without a case the name, address and signer hash are dropped (a person v2 has no subject for), reported as `personal_columns_dropped_no_case`. |
| `outbound_message` | 264 | Record with the Message-ID in `message_id` | Owner notices without a case: record without an application. |
| `inbound_message` | 258 | Record (position, Message-ID digest, classification, link to the outbound message) | The first generation kept no sender, subject or body here. |
| `applicant_message` | 42 | Record with subject and body | v2 keeps message derivatives, so the bodies are kept. |
| `mailbox_cursor` | 1 | Record without an application | Not a v2 `MailboxCursor`: recorded, never activated. |
| `review_run` | 359 | Record | Model output included. |
| `review_evidence` | 84 | Record | |
| `review_question` | 51 | Record | Not v2 `Question` rows: their text is in the drafts and no v2 message carried them. |
| `review_draft` | 32 | Record | |
| `crm_projection` | 62 | Record; the Twenty person id and note id also on `ImportedCase` | |
| `crm_review_item` | 21 | Record | |
| `case_release` | 32 | Record | |
| `mailbox_account` | 32 | `AddressReservation` (live, `reviewed_exception`, reviewed by the import) and a `ProvisioningRequest` (`active` when created, `failed_needs_staff` when only approved), plus a record of its non-personal columns | So v2 never reserves or creates the address again. A name v2's mailbox rule refuses, or one already reserved, stays a record and a finding. |
| `job` | 66,465 | Operational rows are not replayed; narrow signing delivery metadata becomes `signing_history` snapshots (section 11) | Counts by kind and status in the report; open or failed jobs of a case are listed as that case's follow-up `v1_jobs_not_carried`. |
| `intake_rate_event` | 11 | Not imported (operational) | Rate counters keyed on a hash of a client address. |
| `setup_*`, `agreement_acceptance`, `interest_track_change` | 0 | Not mapped | A row in any of them fails the run (exit 1): it would be data with no rule. |

The report gives, per table, rows read, mapped, already imported, skipped with their reason and unaccounted; a
personal-data row that is unaccounted for (dropped without a reason) makes the command exit 2.

## 3. Case states

### 3.1 State to stage

| First-generation state | v2 stage | Finding (kept on `ImportedCase.findings`) |
|---|---|---|
| `requested` | `submitted`, or `contact_verified` when the address was verified | |
| `reviewing` | `assessing` | |
| `needs_information` | `awaiting_answers` | |
| `held` | `awaiting_decision` | `v1_held_maps_to_awaiting_decision` |
| `lapsed` | the stage it lapsed from (`awaiting_answers` or `agreements`), else `awaiting_decision` | `v1_lapsed_maps_to_resume_stage`; the resume state is kept |
| `nda_pending`, `setup_pending` | `agreements` | `open_v1_envelope:<type>` when an envelope is open |
| `release_pending` | `agreements_complete` | |
| `provisioning` | `provisioning` | |
| `active` | `active` | |
| `suspended` | `active` (paused) | `v1_suspended_has_no_v2_stage` |
| `offboarding` | `closed` | `v1_offboarding_incomplete_revoke_by_hand` |
| `offboarded` | `closed` | |
| `withdrawn` | `withdrawn` | |
| `declined` | `declined`, with a `QualificationDecision` (decline, human-only, code `first_generation`, the first generation's reason code and actor) | `v1_decline_recorded_as_human_only_decision` |
| anything else | refused: the person fails with `unknown_v1_state:<state>` | |

`held` and `lapsed` deliberately avoid `on_hold`: v2 admits `on_hold`, `admitted` and `declined` only with a decision
in the same transaction (assessments 0008), and no decision was taken on the first generation for a hold or a lapse.
The decline was an owner command on the first generation, so it is recorded as a human-only decision; its
`created_at` is the import time (the database sets it) and the original time is in `decision_inputs.decided_at`.

### 3.2 Automatic import preserves agreement history

A v2 instance is born unsigned and uncreated (agreements 0002), `signing_complete_verified` needs a read observation
by v2 in the same transaction (agreements 0004), a User Agreement needs a verified NDA instance (D-15), and v2's
recipient check requires the configured company approver as well as the applicant. Automatic import has no fresh
provider evidence or approved historical-template mapping, so it never creates verified instances. The explicit
adoption path in section 10 binds an existing envelope to those native checks. In the import itself, a completed
NDA and User Agreement become the person's member-on-file record
(`applications.members`, "referenced, not re-signed", label `<version> (first generation)`), which v2's agreement path
already honours, and every agreement is kept as a record. An owner-recorded member-on-file record that differs is kept,
never superseded (`member_on_file_not_recorded:different_record_needs_correct`).

## 4. Submission fields

The keys are those the form-fields work writes (bgl.3): `name`, `email`, `reason` (what they are building),
`residence_country`, `phone_e164`, `phone_country`, `interest_track` (`cert_only`, `cert_and_work`, `undecided`),
`marketing_opt_in` with `marketing_wording_version` (`marketing-updates.v1`), `age_attested`, `education`
(`institution`, `credential`), `no_degree`, `no_certifications`, `verification_consent` with
`verification_wording_version` (`credential-verification.v1`), and `claims` (work links as `work`, certifications as
`credentials` with `identifier` or `url`). The first generation's own wording versions are carried as recorded, never
replaced. A value an older form never asked is null, never defaulted. What has no v2 key is under `first_generation`:
the `CAT-` reference, form and interest wording versions, provenance, and the submission, consent and opt-in times.

## 5. In-flight cases: what v2 must do next

The report lists, per open case, what it needs (`followups`). The import queues none of it.

| v2 stage after import | Next v2 step | Queued by the import |
|---|---|---|
| `submitted` | Staff re-send the verification: the first generation's confirm link is not honoured by v2 | No (sends mail) |
| `contact_verified`, `assessing`, `awaiting_decision` | Complete the bound history and ownership review (section 9), then use the qualification decision screen | No |
| `awaiting_answers` | Review the old questions/replies and explicitly prepare human qualification review (section 9); old-thread replies associate through section 8 | No |
| `agreements` | Adopt the existing envelope through section 10 with approved historical templates and a frozen source. Verify the NDA before adopting the UA; resume separately | No |
| `agreements_complete` | Reconcile agreement evidence and establish the native release/provisioning request before approval (`bgl.23`, incomplete) | No |
| `provisioning` | Read back the existing MXroute operation and reconcile native ownership before further creation (`bgl.23`, incomplete) | No |
| every open stage | Resume only after its supported continuation or disposition and the transfer of source ownership are recorded | No |
| any case with open first-generation jobs | `v1_jobs_not_carried: <kind>/<status> xN` (reminders, signing sweeps, reviews): each is done by hand or replaced by the v2 step above | No |

## 6. What is lossy

- Applicant credential detail (year, verification status, evidence) is only in the imported record, not in v2's claim
  fields.
- Review history (runs, questions, drafts, evidence) is history only: no v2 assessment run, question or evidence row is
  invented.
- Message bodies the first generation never stored (its outbound bodies outside `applicant_message`) do not exist to
  import; inbound mail has only a Message-ID digest and the mailbox position.
- The decline decision's `created_at` is the import time; the original is in its inputs.
- Open first-generation envelopes and jobs are not continued automatically (section 5).
- `suspended` and `offboarding` have no v2 stage; both are findings with a manual step.

## 7. Verification

`tests/test_first_generation_import.py` builds a first-generation database in its own schema of the test database
(column for column as at its migration 0023, synthetic rows only) and runs the owner command against it over libpq. It
covers a case in every state, a completed NDA and User Agreement with details, an open envelope, a released case with
a mailbox, replies with Message-IDs, a dry run that leaves nothing, report counts equal to the rows, a re-run that
creates nothing and adds one late row once, a failed person reported while the rest import, the owner-only and
no-followups refusals, and an erasure of an imported person that leaves no trace in any table. Mapped in
`tests/acceptance.py` as the supporting group "bgl.16".

## 8. Operator run and follow-ups

```bash
# On the host that runs v2, as the migration owner, against the stopped first generation (read-only):
manage.py catalyst_import_v1 --source-dsn "<libpq DSN of the first-generation database>" --run-by "<who>" --dry-run
manage.py catalyst_import_v1 --source-dsn "<libpq DSN of the first-generation database>" --run-by "<who>"
```

Exit 0: everything accounted for. Exit 1: a person failed, a dormant table holds rows or a table is missing (re-run
after fixing; it resumes). Exit 2: a personal-data row is unaccounted for. The DSN is never printed. The source can be
a temporary restore of the first generation's nightly dump on another host or a tunnel to the stopped container: the
direction says no copy of its database lives on the US host, so do not restore it there.

The foreign-thread resolver is wired through `CATALYST_FOREIGN_THREAD_RESOLVER=firstgen.threads` and
`correspondence.association`. A source Message-ID or CAT reference associates a reply; it never bypasses
sender matching or authentication checks.

The application dossier links to `/staff/legacy/<application-public-ref>/`. This read-only history needs
active staff access and the existing `applications.view_application` permission. It shows the recorded
legacy state, current v2 stage, contact-verification and pause state, import findings and state-specific
handover guidance. Records are paginated and can be filtered by source table. Only explicitly selected
fields are displayed: case events, question drafts and statuses, applicant messages, agreement state,
mailbox state and release metadata. Source text is escaped and control characters are made visible;
confirmation, setup, withdrawal and signing links are redacted. Only the known outgoing clarification
body is displayed; other outgoing bodies, arbitrary imported JSON, provider payloads and hidden source
keys are not displayed. Reading the page
creates no job, changes no pause and makes no provider request.

If an imported case has already progressed beyond `submitted` without recorded contact verification,
confirming a new v2 challenge adopts only the displayed submission and records address control. It
preserves the existing stage and pause, queues no new assessment, and opens a staff review item for
continuation. A still-`submitted` import moves to `contact_verified` and the same staff review,
without queuing an assessment before its history is reviewed. New native submissions retain the
ordinary assessment path. Issuing a verification while paused does not bypass the pause on its
send; delivery still requires the existing handover review and resume procedure.

For an unverified import, staff record the review and resume needed for the verification mail,
then the applicant confirms the delivered link. Staff pause the case again, acknowledge the
contact-review item and perform the explicit history review or envelope adoption. The first
handover accepts this staff pause only when the case's append-only history contains the reviewed
resume of its original import pause, preceding the current pause. The handover records that
resume event. An ordinary pause/resume, another case's receipt or an unresolved identity/safety
item cannot substitute for it. The handover itself never resumes automation.

Open continuation work remains in `bgl.23`: an operator must reconcile the open signing envelopes,
questions, contact-verification gaps and uncertain mailbox operations before resuming each case.
Showing preserved history is not proof of continuation. In particular, imported `agreements` cases
must complete the explicit envelope handover in section 10 before v2 can rely on native provider-read evidence.

## 9. Pre-signing cases: recorded human review (bgl.23)

The legacy history has a separate POST action for a verified case still in contact verification, assessment,
questions or decision review. It requires dossier access and the existing directly granted qualification-decision
permission; superuser status or a group grant does not substitute for that authority. The reviewer explicitly
attests that v1 no longer owns this case, its replies or its timers, and records the handover evidence and how the
preserved questions and replies will inform a human decision. The action itself cannot stop the source service;
the freeze and ownership receipt must be checked during the operational handover.

The service locks the application, checks the digest shown with the form, requires verified contact and an adopted
submission, and refuses signing/mailbox/release records, native admission or decline, work in flight, identity and safety
exceptions, and pending native questions. The first review requires the original import pause. Later reviews may
renew the receipt after a reply or a human hold, including after a separate resume; they preserve any current pause.
Every review requires the explicit ownership and history confirmations again. It records a staff event binding
the preserved records and adopted version, then moves the case to `awaiting_decision`. It neither removes the
pause nor queues an assessment, sends mail, creates an envelope or fabricates a confirmed answer.
If a later import records a withdrawal or signing transition, the original pre-signing case label cannot authorize
this review; the later state requires its own reconciliation.

The normal qualification snapshot is unavailable until the current imported history has that review. Its digest
then includes the review event and source-history digest. A late source record or a different adopted submission
invalidates the review and requires a fresh one. The digest also binds replies received in v2; messages still
awaiting processing refuse preparation. The review links to current correspondence as well as imported history.
The decision inputs retain the review event and digest explicitly. The decision screen links to the legacy history; model advice
does not silently inherit the old answers as verified evidence. The routine model admit refuses this imported
history: the person with decision authority must make the qualification decision.

After the separate reviewed resume, a human-only decision can use the existing rationale, snapshot, authority and
transaction guards and create the normal held NDA handoff. This is a functioning path for the reviewed pre-signing
case, not evidence that every imported state is ready. Section 10 handles existing signing envelopes. Completed
Section 12 covers explicit ownership of already-created mailboxes and native access revocation; section 13
covers release-pending cases. Uncertain provisioning effects and live ownership transfer remain unverified.

## 10. Existing signing envelopes: explicit adoption (bgl.23)

The legacy-history screen offers a separate POST action for imported `agreements` cases. The operator must hold
both the review authority from section 9 and `manage_agreements`, choose the preserved agreement and an approved
historical template, and attest source shutdown/ownership and the template/recipient mapping. The case must remain
paused. Configuration must identify the real applicant and company recipient slots, roles and signing order; this
action does not approve templates, grant authority, or infer legal approval from a provider response.

A bounded provider read runs outside the transaction. Its envelope ID, external key, document type, template number,
recipient addresses, roles and order must match the preserved record and approved configuration. The transaction
then locks the application and rechecks the form digest, paused state and current history. Foreign case records,
cross-case envelope ownership, conflicting native instances, multiple old envelopes of a type, later source final
states, unresolved safety items and unrelated native work refuse adoption.

The instance starts unsigned under the existing database guards. Its original provider envelope and external key
are then attached; no create request or fictitious create attempt is written. A pending or completed envelope queues
only the normal read job. That job performs a new provider read, records its observation and verifies completion
through the normal database guard before custody can proceed. A legacy completion label alone never verifies a
signature. The User Agreement cannot be adopted until its native NDA has been read-verified without an integrity
hold. Existing member-on-file metadata alone does not satisfy this requirement.

A provider draft is accepted only when the source says `prepared`. It queues distribution of that same envelope,
which the existing automation pause blocks until a separate resume. The normal distributor re-reads before sending;
a stale delivery cannot create or distribute another envelope. Already pending envelopes do not replay the signing
request. The adoption event binds source history, the exact template, confirmations and the operator's note;
repeating the same adoption creates no second instance or job.

Agreement advancement refuses a fresh create or release while an old envelope of the relevant type remains
unadopted. An older completed member reference cannot hide a newer pending envelope. Read polling and custody can
run while paused; automatic countersignature, progression and provisioning retain their existing pause and approval
checks. Historical reminder timing, unsupported/ambiguous old envelopes, approved live template mappings, provider
canaries, provisioning continuity and the source/mailbox/callback/timer transfer still require the handover rehearsal.
No live adoption or retirement is claimed by the synthetic tests.

## 11. Signing reminder and lapse handover (bgl.23)

The import also preserves a compact `signing_history` snapshot for each agreement. This contains
its current source state and delivery-job metadata: status, attempts, known outcome, completion
time and applicant resend round. Job payloads, credentials and raw action keys are excluded.
Completed resends matter: v1 counted them against the reminder allowance. A changed source
snapshot is appended; earlier evidence is never rewritten. A missing job table or unknown resend
key cannot be interpreted as zero prior deliveries.

After envelope adoption, the legacy-history screen offers a separate **Continue signing
follow-ups** action. A decision-maker with agreement management records the frozen-source and
timer review. A fresh provider read must still match the adopted identity and recipients. The
service refuses uncertain, running or previously attempted queued source sends. An unattempted
queued reminder may transfer to v2; the attestation means its v1 writer has stopped.

The remaining reminder is due from the historical last delivery, not the import date. Already
sent reminders and successful operator resends consume the configured allowance. Once that
allowance is spent, only the closing-note timer remains, using the historical quiet-period clock.
Replies received before handover still prevent lapse. A signed applicant, an already lapsed
source case or a recorded applicant return receives no duplicate follow-up. Prepared drafts use
the native distribution path to schedule their first reminder after sending.

The operation records its source digest, consumed allowance, due date and resulting action (or
reason for no action). Repeating the same handover creates nothing new. It leaves the case paused;
the ordinary resume spreads overdue timers using the configured grace period. No mail or provider
write happens in the handover action itself. Production source freeze, mailbox collection and
case-by-case ownership verification remain cutover requirements under `bgl.17`.

## 12. Existing mailbox ownership and access revocation (bgl.23)

An imported mailbox reservation and an `active` request record what v1 knew; they do not
by themselves satisfy native ownership evidence. Until ownership is reviewed, closure keeps
access-removal obligations open instead of declaring them `not_applicable`. Superseding the
request or releasing its address also refuses an unreviewed imported mailbox.

The legacy-history screen offers a separate POST action to staff with dossier access and
`operate_provisioning`. It requires source-stop and ownership-review attestations, a note,
current imported history and either an automation pause or a terminal case. Only a preserved
`created` mailbox with its provider creation time and exact reservation target qualifies.
An approved mailbox whose create outcome is unknown uses the separate reconciliation in section 15.

A fresh mail-host read must return the same address. The transaction locks the application
and request and rechecks history, stage, reservation and outstanding work before writing
native staff-confirmed ownership evidence. Provider errors, absent accounts, mismatched
identities, previously refused ownership and conflicting native work leave ownership
unconfirmed. A suspended source case requires a suspended provider account; the action
never resumes automation, creates a mailbox, changes its password or sends another welcome.
Observed provider limits are recorded as evidence without changing the existing account.

For an already closed or withdrawn case, confirming ownership records stop intent and queues
native protective revocation. That worker can run while automation is paused. For an active
case, a later ordinary closure uses the same worker. It rotates the password, removes owned
forwarders and preserves mailbox data. Sessions, app credentials and shared routing retain
the native unsupported/pending obligations and require their documented owner decisions;
this handover does not claim those obligations are complete. Duplicate confirmation records
no second ownership receipt. Source freeze, live account reconciliation and rollback remain
cutover requirements; synthetic tests do not establish that v1 has been retired.

## 13. Release-pending handover (bgl.23)

A source `release_pending` case imports as `agreements_complete` without replaying its release
job. The legacy-history screen can now prepare exactly one native held `provision` handoff.
The operator needs the section 9 review authority and `approve_provisioning`, must attest that
the source writer and release jobs have stopped, verify the agreement completion evidence and
historical references, and confirm that no release or mailbox creation already occurred.

The form digest binds current imported history, contact, adopted submission, pause and native
agreement prerequisites, including the exact live member-on-file record. The case must retain
its reviewed import pause. Latest agreement snapshots must still show a release-pending case
and completed agreements; missing history, uncertain signing delivery, later source states,
existing release/mailbox records, unresolved identity or safety items and native work refuse
handover. A correction of the member reference invalidates the form. The service rechecks all
of this under the application lock after the normal fresh-read gate for any native instances.

Completed historical references remain references under the existing member-on-file policy;
they are not new signatures or provider-verified native instances. The handover creates no
mailbox or new agreement, sends nothing and leaves the stage and pause intact. It records the
reviewer and evidence and creates one held action with the native prerequisite digest. In
owner mode the existing release command and exact-mailbox approval remain necessary. If the
already-configured mode is automatic, the existing automatic release is queued and refuses
the pause until a separate reviewed resume. Its normal release, approval, create and verify
steps then apply. Repeated handover cannot create another action, and an old native action
key cannot be silently reused.

A v1 release or mailbox record makes this a reconciliation case instead. Section 15 handles approved-but-uncertain mailbox creation and welcome-delivery reconciliation.
Live provider checks and the cutover/rollback rehearsal remain separate requirements. This path does not authorize a production source stop.

## 14. Current release and mailbox history (bgl.23)

Original imported mailbox rows remain immutable. Each import now also captures a minimal
`mailbox_history` snapshot per case, in the same read-only source snapshot and destination
transaction as the import. It includes the current case state, release references, mailbox
creation markers, welcome round and delivery markers, and release/create/welcome/owner-notice
job status, attempts and uncertainty. It stores an address digest for identity comparison,
not another copy of the mailbox address. Job payloads, passwords, raw action keys and welcome
content are excluded. Known action keys are reduced to case/mailbox/round references; unknown
or conflicting identities remain visible and prevent a handover from treating them as settled.

An unchanged import creates no duplicate snapshot. A changed row appends a new revision;
returning to an earlier value also creates a new current revision. Missing source tables are
explicitly incomplete, never evidence that no mailbox or delivery exists. Existing imports
must be topped up from the frozen source before the release or mailbox handover can proceed.

Both handovers require complete current snapshots. Running/reconciling jobs, unknown outcomes,
attempted queued jobs and mismatched identities require reconciliation. Unattempted queued jobs
may remain only under the handover's explicit source-stop attestation; v2 never replays them.
Mailbox ownership also checks the current address, creation status and source case state, and
refuses a welcome-start marker without a sent marker even if the original import says an older
welcome was sent. The fresh provider read is followed by the same lock-time digest revalidation.
A release-pending handover refuses a changed case state or any existing release/mailbox effect.

These snapshots supply reconciliation evidence, not a claim that uncertain creates or welcome
sends are resolved. No source job is cancelled by import, no provider operation is replayed,
and source freeze, explicit dispositions and live rollback verification remain required.

## 15. Recorded mailbox reconciliation and native continuation (bgl.23)

The legacy-history screen offers a separate POST action to staff with dossier access,
`operate_provisioning` and `approve_provisioning`. Current mailbox-history fields are shown
through an explicit allowlist, including creation markers, welcome round and source job
uncertainty; arbitrary JSON, credentials and raw job payloads remain hidden.

The reviewer must record the evidence and attest that source writers have stopped, in-flight
operations cannot complete later or retry, account ownership and limits were checked, and the
current welcome round and recipient evidence were reviewed. Running or reconciling source
jobs still refuse the action. An unknown create or welcome recorded as needing reconciliation
can receive an explicit disposition; it is never silently treated as failed or absent.

The service requires a complete current source snapshot with consistent case, mailbox and job
identities. Open cases also need verified contact, current native agreement prerequisites and
fresh reads for native envelopes, a verified source release referring to completed source
agreements, and no unresolved identity/safety item or unprocessed correspondence. It refuses
conflicting native operations, an address changed since import, or a released reservation.
The host read occurs outside the transaction; the application/request lock and a fresh digest
check follow it. Provider errors do not mean absence. A foreign address or a changed provider
identity cannot be adopted. No provider write or applicant message occurs in this transaction.

| Reviewed outcome | Result |
|---|---|
| Absent, open case | Only an originally uncreated mailbox qualifies. Keep its address reserved; supersede the imported request with a native API request bound to current prerequisites. Separate resume and exact-mailbox approval are required before native creation, whose own absent-before-create check still runs. |
| Owned, recover credentials | Require source evidence that creation was requested or recorded, plus an exact host identity and matching reviewed limits. Preserve the immutable source approval, create a separately approved native successor and queue native verification. Automation stays paused. After separate resume, the configured credential flow sets/replaces credentials and delivers its message through the existing guarded worker. This is an explicit recovery decision, not a replay of the v1 send. |
| Existing welcome/access received | Require a completed source account, an active source case and a source welcome marker, with the reviewer's confirmation of existing delivery/access. Record ownership and inherited completion without manufacturing a v2 credential setup or SMTP receipt. Keep the existing password and send nothing. |
| Foreign account | Record the ownership conflict and preserve the other account. An open case returns to a held native provisioning handoff for a new address. A closed case remains closed and settles its access-removal obligations without touching the foreign account. |
| Closed case, owned account | Record ownership and queue the existing protective access-removal worker, which may run while paused. It cannot reopen onboarding or send credentials. Unsupported access-removal obligations remain visible. |
| Closed case, absent account | Record the authoritative absence and settle through the native protective worker; create no successor, mailbox or credential flow. |

A successor keeps the same reservation and receives its own prerequisite and approval digests;
the original request's identity and approval never change. Once transferred, the original
request cannot release that reservation or independently revoke the successor's mailbox.
Native successors use the normal unknown-create, verification, credential and closure guards.
A repeated identical reconciliation returns its receipt; a changed decision, source snapshot
or supplied limits cannot silently replace that decision. Later source changes require review.

The receipt distinguishes staff-attested existing delivery from a new native send and records
the selected outcome, source snapshot, prerequisite references, reviewed limits and successor.
This operation does not stop v1, remove a pause, approve legal wording or establish live canary
or rollback evidence. Those remain prerequisites for the production handover.
