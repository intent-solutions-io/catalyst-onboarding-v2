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
  after migration 0023 is carried, never refused. The job queue is never loaded row by row (counts by kind and
  status, and the open jobs' references only). Nothing is written to the source.
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
| `job` | 66,465 | Not imported (operational) | Counts by kind and status in the report; open or failed jobs of a case are listed as that case's follow-up `v1_jobs_not_carried`. |
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

### 3.2 Agreements are not `AgreementInstance` rows

A v2 instance is born unsigned and uncreated (agreements 0002), `signing_complete_verified` needs a read observation
by v2 in the same transaction (agreements 0004), a User Agreement needs a verified NDA instance (D-15), and v2's
recipient check would reject the first generation's envelopes (they carry the company approver as a second
recipient). Writing first-generation envelopes as instances would either fake that evidence or leave them in an
integrity hold. Instead a completed NDA and User Agreement become the person's member-on-file record
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
| `contact_verified`, `assessing`, `awaiting_decision` | A staff decision on the decision screen | No |
| `awaiting_answers` | Staff read replies to the first-generation questions and decide; replies associate through `firstgen.threads` in the reply path (section 8) | No |
| `agreements` | The owner checks the open first-generation envelope at Documenso and records completion with `catalyst_member_on_file`, or cancels it and issues v2's | No |
| `agreements_complete` | Staff approve the mailbox on the provisioning screen | No |
| `provisioning` | Check MXroute for the mailbox the first generation was creating | No |
| every open stage | Staff resume the import's automation pause once the case is reviewed | No |
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
continuation. The ordinary `submitted` confirmation still starts the normal assessment path. Issuing
a verification while paused does not bypass the pause on its send; delivery still requires the
existing handover review and resume procedure.

Open continuation work remains in `bgl.23`: an operator must reconcile the open signing envelopes,
questions, contact-verification gaps and uncertain mailbox operations before resuming each case.
Showing preserved history is not proof of continuation. In particular, imported `agreements` cases do
not yet have the admission and provider-read evidence needed by the normal v2 agreement path.
