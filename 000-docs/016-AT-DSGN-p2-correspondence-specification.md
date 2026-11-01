# P2 Correspondence Specification (handoff 2A)

| Field | Value |
|---|---|
| Document | `016-AT-DSGN-p2-correspondence-specification` |
| Version | 0.3.2 (consolidated 2A closeout: corrections 1 to 9 applied; independent QA review and re-check recorded in sections 10.3 and 10.4) |
| Status | **APPROVED by the owner 2026-10-12 (version 0.3.2; decisions D-27 to D-32 in `011` section 4).** Handoff 2A of phase P2. Approval covers synthetic P2 only: no real email, applicant data, provider credentials, deployment or production staff access. Items still marked PROPOSED or open in section 8.2 to 8.4 are not covered. The owner released 2B.1 on 2026-10-12 and 2B.2 to 2C on 2026-10-13 (autonomous build; limited to P2 by the owner's closeout direction of 2026-10-13: not P3, a release or a deployment); GATE-P2 sign-off stays the owner's. |
| Owner | Jeremy Longshore |
| Date | 2026-10-12 |
| Epic | P2, "Run the applicant correspondence loop: outbound policy, inbox correlation, reminders, stop rules and human takeover" (`catalyst-v2-7hu`); this task is `catalyst-v2-7hu.1` |
| Builds on | `004` J-06 to J-09 (journey semantics), `005` S1.4 (ledger rules), `003` ADR-01, ADR-03, ADR-13, ADR-15, `002` REQ-005, REQ-012, REQ-013, REQ-014, REQ-022, REQ-034, and the merged first-slice code |
| Primary sources | RFC 5321 (SMTP) sections 2.1, 4.1.1.4, 4.2.1, 6.1; RFC 9051 (IMAP4rev2) sections 2.3.1.1, 6.3.12; RFC 8601 (Authentication-Results) sections 1.6, 5; RFC 9989 (DMARC, Proposed Standard, obsoletes RFC 7489) section 5.3.5; RFC 3834 (automatic responses). Each is cited where it is used. |
| Classification | Public; synthetic data only (`example.test` addresses); no provider, mailbox or credential is named |

> **Status: APPROVED for synthetic P2 (2026-10-12).** The owner approved version 0.3.2 and recorded D-27
> to D-32. That approval unblocked 2B.1. The owner separately released 2B.2 to 2C on 2026-10-13 for an
> autonomous build (source: the owner's instruction in the build session on 2026-10-13: "we will be away from the office for about the next three to four hours. I need you to work autonomously and continue to keep working, completing the beads and building this out"). Its limit to P2 is the owner's closeout direction of 2026-10-13 (`016` 10.12): it does not
> authorize P3, a release or a deployment, and GATE-P2 sign-off stays the owner's. Neither authorizes real mail, MXroute, the VPS or any
> provider; provider-specific behaviour stays unverified until a separately authorized check. Any later
> substantive change to this document is reviewed by one independent specialist.

**The standard this document must meet.**

- A worker can recover the exact authorized message after a crash.
- A temporary rejection, a permanent rejection, an acceptance and an unknown outcome stay distinct.
- An unanswered question cannot become `satisfied` for convenience.
- Inbound content cannot silently acquire trust.

## 1. Scope, boundaries and the P2/P3 line

**P2 is deterministic.** It covers:

- sending approved, frozen messages to the verified address only;
- collecting inbound mail over IMAP and persisting a sanitized, provenance-labelled record of it;
- recording the authentication evidence and deciding trust from an explicit table;
- correlating replies with outbound messages and the questions they carried;
- classifying automatic messages and bounces;
- reminders with suppression and stop rules;
- staff takeover, withdrawal and resolution.

**Judgement is not automated in P2.** A trusted reply from a person that may answer a question is routed
to staff confirmation, and a held `interpret_reply` action is created for P3. No reply satisfies a
question by itself, and no code path in P2 calls a model. Staff-confirmed outcomes are an intermediate
implementation, not a change to the longer-term automation objective.

**The P3 interface is typed but not implemented.** It is a Python protocol, `ReplyInterpreter`, in
`correspondence/interpreter.py`. It imports neither PydanticAI nor any model client.

- **Input:**
  - the inbound message's public id;
  - the ids of the related questions that are still open (never a withdrawn question);
  - the message's sanitized derivative text, which is untrusted data and is labelled as a derivative.
- **Output, per question:** one of `satisfied`, `partial` or `not_addressed`, plus cited spans (offsets
  into the derivative text). P3 validates deterministically that every cited span exists, and that a
  question requiring evidence has an attachment or link actually present (`004` J-07 step 2).
- **While the staff-confirmation default holds** (`004` J-07; POL-04, POL-06), even a P3 outcome is a
  proposal that staff confirm.

**Out of scope:**

- Redis, Celery, Temporal, a second database or a second job engine. The existing `PendingAction` ledger
  is the only job system.
- A chatbot, MiniMax or any model call.
- Real MXroute, real SMTP or IMAP credentials, the VPS, DNS or a deployment.
- Alert delivery (P6).
- A persistent store of original MIME bytes (section 3.5).
- Any change to the release workflow. The release-blocking defect `catalyst-v2-oyu` is unchanged by this
  work.

**Test environment.** Tests run only against synthetic mailboxes:

- an SMTP test server bound to loopback, with scripted replies per protocol phase and failure injection;
- a local IMAP test server image pinned by digest, chosen in task 2B.2.

## 2. What P2 builds on

Every P2 component extends existing code. No parallel mechanism is introduced.

| Existing piece | File | What P2 reuses | What P2 changes (PROPOSED) |
|---|---|---|---|
| Pending-action ledger: claim with SKIP LOCKED, pause skip for automated kinds, poison rule, lease-fenced `finish` | `workflow/ledger.py` | Every P2 effect is a `PendingAction` kind with a handler registered in `settings.CATALYST_ACTION_HANDLERS` | Two small additions (A-7). (1) A `due_at` argument on `finish` (implemented in 2B.1 as `due_in`, an offset from the database clock, because application clocks are never trusted). Today `finish(status=queued, refund_attempt=True)` sets `due_at = Now()` (lines 123-127), so a deferral would loop hot. (2) A `fence(claim)` function that checks and extends a lease inside a transaction without finishing the action. (3) `finish(status=held)` treated as non-terminal: no `completed_at` is set. |
| `AutomationPause`, one per subject | `workflow/models.py` | Pause semantics (J-09) | None. Pause and resume become staff services (F). |
| `uncertain` status | `workflow/models.py` | Kept for provider reconciliation (ADR-15, D-20) | Used for the first time, by non-redeliverable send kinds |
| Pre-send boundary, the fault seam after send, and `LeftForRecovery` (defined in `workflow/ledger.py` line 61, raised by `verification.py` line 153) | `correspondence/verification.py` | The three-phase handler shape: a check transaction, then the send with no lock held, then a fenced result | Generalized into a base send handler (A). `SendVerification` keeps its D-20 redelivery behaviour; no other kind inherits it. |
| `OutboundMessage`, one row per attempt | `correspondence/models.py` | Per-attempt record | Linked to a new message-level record, `ApprovedMessage` (3.2); attempt outcome classes extended |
| `ApplicationEvent`, append-only | `applications/models.py` | The audit trail for every state change on an application | None |
| Staff attention rule | `applications/staff.py` (`attention_q`) | One rule for dossier, list column and filter | Reads open staff items (3.8) |
| Read-only admin | `config/staff_admin.py` | View-only for every user, superusers included | Named staff actions behind explicit permissions (F) |
| Start-up guards | `config/guards.py` | Refusal of providers, non-sink backends and provider variables | An allowance in `development` and `test` for the local SMTP and IMAP test servers, with a connect-time check (section 6). No real provider is reachable. |
| Log redaction | `config/redaction.py` | Confirmation-path pattern | The same pattern drives inbound redaction (3.5). The logging rule in section 6 is the control. |
| Role grants | `config/db_roles.py` | Explicit per-table grants, column-level UPDATE, no DELETE | Every new table gets a grant migration (section 3) |

Three facts about the current code shape this design:

- **The recipient is the verified address.** S1 sends to `challenge.email_at_issue` (`verification.py`
  line 197). The verified address is the `email_at_issue` of the challenge named by the application's
  current `VersionAdoption`.
- **Message-IDs are not persisted before the send.** S1 generates the Message-ID at send time
  (`verification.py` line 116), so a crash after acceptance loses the only correlation key. P2 derives
  every Message-ID from a logical identity committed before the first attempt (3.2).
- **Ordinary retries are blind.** `fail_or_retry` returns a generic failure to `queued` until the final
  attempt (`ledger.py` lines 143-147). Each non-redeliverable handler must therefore classify its own
  outcome (A3). It never returns an unknown or permanent outcome to `queued`.

## 3. Data model sketch (description, not code)

All new tables follow `config/db_roles.py`:

- explicit grants per table;
- UPDATE limited to the named columns;
- INSERT with sequence usage;
- no DELETE for any role on the new tables (the existing `AutomationPause` keeps its INSERT and DELETE
  grant, and every pause and resume writes an event with reason and actor);
- nothing for the retention role until POL-10 is decided.

Message content is personal data and stays in POL-10's scope.

### 3.1 MessageTemplate and MessageTemplateVersion (`correspondence`)

**`MessageTemplate`:**

- Fields: `key` (unique), `purpose` and `secret_bearing`.
- A secret-bearing template's rendered body is never stored and never shown to staff. The verification
  invitation is one.
- Code and a database check require `secret_bearing = true` for any template whose variable allow-list
  contains a link or token variable.

**`MessageTemplateVersion`:**

- Fields: template, `version`, `subject`, `body_text`, `variables` (an allow-list), `status` (`draft`,
  `approved`, `retired`), `approved_by`, `approved_at`, `content_sha256`, `synthetic`.
- Unique `(template, version)`. A check requires that `approved` has an approver and a time.
- Grants: UPDATE of `(status, approved_by, approved_at)` only, so approved text cannot change.
- Approval needs permission `approve_template_version` (F, role matrix).

**Rendering:**

- Only an `approved` version renders.
- Variables are substituted from the allow-list. The Django template engine is not used for message
  text, and subjects are static. The owner-directed parity amendment (`bgl.5`, `034` row 9) permits one
  fixed suffix: `[CAT-XXXX-XXXX]`, appended by the sender when the approved version's
  `subject_reference` flag requests it. The flag and any HTML alternative are included in the version
  digest and frozen after approval. No arbitrary subject variable is permitted; a threaded reminder
  retains the already-frozen subject and its single reference suffix.
- An unknown or missing variable fails closed.

**Content:** synthetic placeholder versions are seeded by migration. Real wording needs POL-06 and
POL-17.

### 3.2 ApprovedMessage and its attempts (`correspondence`)

**One canonical message-level record, committed at enqueue, separate from the attempt history.** A
worker reconstructs what to send from this record alone. It never reads the "latest" template, answers
or address.

- **`ApprovedMessage` (new):**
  - identity: `send_ref` (UUID, the logical identity; the Message-ID is derived from it);
  - kind, application, and `recipient` (the verified address, frozen at approval);
  - `template_version` (an exact foreign key, never "latest"; required by a check for every kind except
    `staff_message`, which has no template);
  - content: either `frozen_body` and `frozen_subject` with `content_sha256` (non-secret templates and
    staff messages), or `reproducible_inputs` (the identifiers needed to re-render a secret-bearing
    template, never the secret itself) with `inputs_sha256`;
  - authorization: `authorized_by` (actor reference), `authority` (`system_policy` or `staff`) and
    `authorized_at`, all set **at insert**. A row exists only once it is authorized; unconfirmed staff
    drafts live in a separate table (3.4);
  - `supersedes` (nullable link to a predecessor `ApprovedMessage`);
  - `staff_draft` (nullable, unique link to the confirmed `StaffMessageDraft`, 3.4);
  - `disposition`: `active`, `accepted_by_server`, `accepted_by_evidence`, `rejected_permanent`,
    `retries_exhausted` (only temporary rejections were seen; staff may authorize a resend),
    `transport_blocked` (held while the sending channel itself is refused; see A3), `operator_abandoned` or
    `superseded`.
- **Constraints and grants:**
  - every identity and content column is INSERT-only;
  - UPDATE is limited to `(disposition, disposition_at, disposition_by)`;
  - unique `send_ref`.
- **`ApprovedMessageQuestion`** (replaces the earlier Message-ID-keyed join): `(approved_message,
  question, purpose)` with purpose `initial`, `reminder` or `revision` (a revised message, A6; added in
  2B.1), unique `(approved_message, question)`. A
  partial unique `(question)` where `purpose = 'initial'` stops a double approval from sending twice.
- **Content digest (the comparison basis for A5):** `content_sha256` is SHA-256 over the canonical
  rendered form: the decoded subject, a line feed, and the decoded text body with line endings normalized
  to line feeds. For a secret-bearing kind, whose body is never stored, the worker computes the same digest
  at render time and records it on the attempt as `rendered_sha256`. A provider record is compared by
  computing the same canonical digest from its decoded subject and body.
- **Message-ID:** `<c{send_ref hex}@{CATALYST_MAIL_DOMAIN}>`, recomputable after any crash. Whether a
  production provider preserves a supplied Message-ID is **UNKNOWN** until the provider check (8.3).
- **`OutboundMessage` stays one row per attempt**, with `UniqueConstraint(pending_action,
  attempt_number)` kept:
  - new columns: `approved_message` (foreign key, nullable for S1 rows), `attempt_series`,
    `protocol_phase_reached`, `smtp_reply_code` (no reply text is stored), `rendered_sha256`,
    `server_accepted_at`, and `filed_copy_state`;
  - attempt status check: `rendered`, `sending`, `accepted_by_server`, `rejected_temporary`,
    `rejected_permanent`, `transport_blocked` or `unknown`;
  - S1 statuses stay readable: `accepted` and `failed` remain valid for S1 rows;
  - **attempt numbering:** for P2 rows, `attempt_number` is a per-`ApprovedMessage` sequence allocated
    under the application lock in the A3 check transaction (the previous maximum plus one). It is
    independent of the ledger's `attempts` count, so a refunded ledger attempt (a channel fault, A3) never
    reuses a number, and `UniqueConstraint(pending_action, attempt_number)` holds;
  - grants: UPDATE of `(status, protocol_phase_reached, smtp_reply_code, server_accepted_at,
    filed_copy_state)` only.

**Retry versus revised resend:**

| Case | Identity | Allowed when |
|---|---|---|
| Automatic retry | Same `ApprovedMessage`, same attempt series, new attempt row, same Message-ID | Only after `rejected_temporary`, within the bounded attempts (A3) |
| Staff-authorized resend of the same content | Same `ApprovedMessage`, a **new attempt series** (with its own action key), same Message-ID. The decision is recorded, and earlier attempts keep their statuses (an `unknown` stays `unknown`). | After `unknown`, `retries_exhausted` or `transport_blocked`, with permission `decide_uncertain_send` (F); the duplicate risk is shown. Never after `rejected_permanent`. |
| Revised message (corrected text, a new template version, a different question set) | A **new** `ApprovedMessage` with `supersedes` pointing at the predecessor, a new `send_ref` and a new Message-ID; the predecessor becomes `superseded` | A new authorization, as for any message |

A change of recipient is never a resend. A new verified address is a new identity process, outside P2
(POL-19).

### 3.3 Question and QuestionReplyLink (`correspondence`)

**Home (PROPOSED, decision A-1):** `correspondence` in P2. `003` ADR-01 places questions in
`assessments`, which does not exist yet. Reply handling and reminders must lock and update question
status, so in P2 the question lives where it is used. `assessments` later depends on `correspondence`
for it.

**`Question`:**

- Fields: `public_id`, application, `text` (fixed after approval), `origin` (`staff` in P2; `model`
  arrives with P3), `approval_state` (`proposed`, `approved`), `status`, and timestamps.
- A model-origin question stays `proposed` until staff with `approve_question` approve it (fail-closed,
  `004` J-06).
- `status` is one of `open`, `reply_pending`, `partially_answered`, `satisfied` or **`withdrawn`**.
  - The first four are the `004` J-07 statuses.
  - `withdrawn` is an explicit staff disposition (A-8). It is **not** an answer.
- Withdrawal fields: `withdrawn_by`, `withdrawn_reason` (a reason code and a short sanitized note) and
  `withdrawn_at`. An append-only `question_withdrawn` event is written in the same transaction.
- Grants: UPDATE of `(status, approval_state, approved_by, approved_at, withdrawn_by, withdrawn_reason,
  withdrawn_at, updated_at)`. The approver and time are recorded with the approval (added in 2B.1).

**`status` is derived by one function, `refresh_question_status`,** inside every transaction that changes
a link, an outcome or a disposition:

1. `withdrawn` if withdrawn (terminal; nothing below is evaluated);
2. `reply_pending` if any link is `pending`;
3. `satisfied` if a staff-confirmed outcome says so;
4. `partially_answered` if an applied partial outcome exists;
5. `open` otherwise.

**Withdrawal effects** (service `withdraw_question`, one transaction, application lock first):

- Every reminder and escalation action of that question in `queued` or `held` becomes `cancelled`, with
  reason `question_withdrawn`. Completed or failed actions are untouched.
- Its `pending` links become `void_withdrawn`. The reply message itself is never dropped. If no other
  pending link remains on that message, its `reply_needs_review` item stays open, so a human reply is
  still read.
- Its held `interpret_reply` actions are cancelled, and P3 never receives a withdrawn question.
- Open staff items about that question only are resolved with code `question_withdrawn`, through the
  normal immutable resolution record (3.8).
- A withdrawn question is **never reopened**. Asking again creates a new question, which may name the old
  one as `replaces`.

**`QuestionReplyLink`:**

- Fields: question, inbound message, `state` (`pending`, `applied`, `ignored_automated`, `stale`,
  `void_withdrawn`), `outcome` (nullable: `satisfied`, `partial`, `not_addressed`), `actor_ref`, and
  timestamps.
- Unique `(question, inbound_message)`.
- Grants: UPDATE of `(state, outcome, actor_ref, updated_at)`.

### 3.4 Staff-authored messages (`correspondence`)

A staff message is a synthetic capability in P2. Real sending stays separately gated (8.3).

1. **Compose.** A user with `send_staff_message` writes free text for one application.
2. **Preview.** The server renders the exact subject and body and the recipient (always the application's
   verified address, never typed). It inserts a **`StaffMessageDraft`** row: application, author, subject,
   body, recipient, `content_sha256` and `created_at`. The table is INSERT-only; every preview is a new
   row, and a draft is never edited. The preview page shows exactly that content and recipient, and
   carries the draft's id and digest. A draft is not a message: it is never sent and never counted by G3.
3. **Confirm.** The same user submits the draft id and digest. In one transaction, the server re-checks:
   - that the digest equals the stored draft;
   - that the recipient still equals the current verified address;
   - that the user still holds `send_staff_message`;
   - that the draft has not already been confirmed (a unique link from `ApprovedMessage` to the draft).

   It then inserts the `ApprovedMessage`, authorized at insert and linked to the draft, and enqueues the
   send under key `send:<send_ref>:0`. A mismatch (tampering between preview and submission, an address
   that changed, or a lost permission) refuses with nothing enqueued.
   - Alternative considered: a single `ApprovedMessage` table with an `awaiting_confirmation`
     disposition. Rejected, because authorization columns would then need UPDATE, and drafts would look
     like committed messages.
4. **Content checks.** A body containing a confirmation link or credential-like text is refused. This is
   defence in depth, **not** authorization, and it does not promise to detect every secret.

The action is not automated, so it runs while the application is paused (J-09). It creates no reminder,
changes no question status and never resumes automation. **Synthetic only:** the start-up and
connect-time guards (section 6) refuse any real mail host, so no staff message can leave the test
environment in P2.

### 3.5 Inbound records: derivatives, metadata and digests (`correspondence`)

**Recommendation (A-9): no persistent store of original MIME bytes in synthetic P2.** Original-message
custody (who may hold the exact bytes, for how long, and how they are deleted) waits for POL-10. P2
keeps an auditable correspondence history without it. The source mail stays in the mailbox: the
collector opens it read-only and never deletes or moves it.

| What | Stored? | Notes |
|---|---|---|
| Original MIME bytes | **No** (P2) | Read into memory, size-capped, then discarded |
| `original_sha256` | Yes | Computed over the exact original bytes before discarding them; it identifies content without retaining it |
| Metadata | Yes | Header fields named below, the size, the server's internal date, and each observed mailbox location |
| Sanitized derivative | Yes | Text produced by the bounded pipeline below, **labelled as a derivative**: it is never described as, or used as, the original |
| Attachments | Metadata only | Sanitized name, declared type, size and digest; contents never opened, unpacked or stored |

**`InboundMessage`:**

- Headers: `message_id_header` (a syntactically invalid one is stored but never reused outbound),
  `in_reply_to`, `references`, `from_address`, `from_normalized`, and `auto_markers` (the RFC 3834 and
  list headers seen).
- Times: `received_at` by the database clock. The `Date` header is kept as untrusted text and never used
  for ordering.
- Content: `size`, `original_sha256`, and `derived_text` with its provenance fields:
  - `derivation_version` and `redaction_version`;
  - `truncated`, plus `truncated_at_bytes` when truncated;
  - `omitted_parts` (a list of part types and reasons);
  - `redactions` (counts by kind);
  - `is_derivative = true`, which is a fixed check.
- Trust: `auth_evidence` (the parsed trusted result, or `missing` or `untrusted`), `trust_decision`
  (section 4 C, trust table) and `from_matches_verified_address`. A matching `From` is not
  authentication.
- Links: application (nullable) and the matched `ApprovedMessage` (nullable).
- Processing: `classification`, `status`, `exception_reason`, `processed_at`, and `identity_state`
  (`established` or `unestablished`, see B5).
- Statuses: `received`, `awaiting_processing`, `processed`, `automated_reply` or `exception` (`004`
  J-07).
- Grants: UPDATE of `(status, classification, exception_reason, processed_at, application_id,
  trust_decision, identity_state)`, plus the derivative columns (`derived_text` and its provenance
  fields), which only the re-derivation service writes.
- **Re-derivation** (a remedy for a redaction defect): when `redaction_version` or `derivation_version`
  is bumped, the management command `correspondence_rederive` re-reads each affected message from its
  mailbox location (read-only) and replaces the derivative.
  - If the source is no longer in the mailbox, the new redaction is applied to the stored derivative
    itself, and the derivative is flagged `rederived_from_derivative`.
  - The old text is **not** kept, because it may hold the unredacted secret the bump exists to remove.
  - An append-only event records the old and new versions and the old and new text digests.

**`InboundMessageLocation`** (new). Every place a message was observed is kept:

- Fields: message, `mailbox_ref`, `folder`, `uidvalidity`, `uid`, `observed_at` and `matched_by` (`new`,
  `digest` or `metadata`).
- Unique `(mailbox_ref, folder, uidvalidity, uid)`; INSERT-only.
- A message seen again (after a resync, or in a second folder) gets a new location row and **no new
  downstream effect**. A message whose identity is `unestablished` (no digest) is linked the same way
  when Message-ID, size and internal date all match an existing unestablished message. That link is
  recorded as `matched_by_metadata`, so a resync never creates a second row or a second staff item for it.

**The bounded derivation pipeline** (`correspondence/mime.py`, pure functions, versioned):

1. **Size gate.** Size is read before the body. Over the cap, metadata only, recorded as `omitted_parts`.
2. **Parse.** With `email.policy.default`. Defects are recorded, never raised. Header count and length,
   MIME depth and part count are capped.
3. **Decode before redaction.** Content-transfer encodings (base64, quoted-printable including soft line
   breaks) and declared charsets are decoded, with replacement characters on error and a decoded-size
   cap. Redaction then sees the decoded text, so an encoded confirmation link cannot slip past it.
4. **Reduce.** The text parts are kept. An HTML-only part is reduced to text by a pure function; it is
   never rendered and no remote content is fetched. `message/rfc822` (forwarded) parts are reduced in
   the same way, within the depth cap.
5. **Redact.** Every confirmation-path URL is replaced by a fixed marker (D-24), including:
   - percent-encoded forms;
   - forms broken across lines;
   - forms in quoted or forwarded material;
   - forms in link targets recovered from HTML.

   The pattern is shared with `config/redaction.py`. NUL bytes are escaped. **No universal secret
   detection is promised.**
6. **Bound.** The result is truncated at a named cap, with `truncated` and the cap recorded.
7. **Record provenance.** `derivation_version`, `redaction_version`, `omitted_parts` and `redactions`
   are stored with the text.

Messages matched to a secret-bearing outbound message go through the same pipeline. Their derivative is
what staff see.

### 3.6 MailboxCursor (`correspondence`)

- **Identity:** `public_id` (the collector action's subject id), `mailbox_ref`, `folder`.
- **Position:**
  - `uidvalidity` (nullable before bootstrap) and `last_uid`;
  - the **completed-collection watermark**: `complete_through_uid` and `complete_through_at`, set only
    by a pass that reached the mailbox's last UID as observed at that pass's start (4.1).
- **State:** `state` (`ok`, `resync`, `recovery`, `blocked`), `blocked_reason`, `epoch`, `pass_number`,
  and `start_mode` (`from_now` or `from_uid`, recorded at bootstrap).
- **Health:** `last_batch_at` (a successful batch, which may be partial), `last_error_code`,
  `consecutive_failures`, `duplicates_seen`.
- Unique `(mailbox_ref, folder)`. Grants: UPDATE of every column except the identity columns.
- **Folders:** the collected folder and the folder that receives filed copies (A4) are different
  settings, and start-up refuses them if they are equal. A filed copy found in any collected folder is
  recognized by its `X-Catalyst-Filed-Copy` header together with our Message-ID, and is recorded as
  `own_copy` with no effect.

### 3.7 Action keys and the pause subject

Reminders are `PendingAction` rows; no reminder table is added.

| Effect | Idempotency key | Note |
|---|---|---|
| Send an approved message (question, reminder, staff message) | `send:<send_ref>:<attempt series>` | The series is `0` for automatic attempts, then `1`, `2` and so on for each staff-authorized resend (after `unknown`, `retries_exhausted` or `transport_blocked`) |
| Reminder number n for a question | `remind:<question public id>:<n>` | Creates the reminder's `ApprovedMessage` when it fires (E2) |
| Escalation after the last reminder | `escalate_unanswered:<question public id>` | Opens a staff item |
| File a mailbox copy of an accepted message | `file_copy:<send_ref>` | A record for humans only; never evidence (A4) |
| Reconcile an unknown attempt | `reconcile:<send_ref>:<n>` | Bounded |
| One collector pass | `collect:<cursor public id>:<pass number>` | |
| Process one reply | `process_reply:<inbound public id>` | |
| Hold for P3 | `interpret_reply:<inbound public id>:<question public id>` | Created `held`; never claimed (TEST-S1-19) |

**Pause subject (REQ-013).** The ledger skips a paused subject's automated actions only when the pause and
the action share `(subject_type, subject_id)` (`ledger.py` lines 84-93). Every per-application automated
kind (`send` for automated messages, `remind`, `escalate_unanswered`, `process_reply`, `reconcile`,
`file_copy`) therefore has subject type `application` and the application's public reference. The
question or message is named in `input_ref`. Only `collect` has the cursor as its subject, so collection
continues while an application is paused (J-07).

Grants on `PendingAction` already allow status, due time, attempts and lease changes and never allow a
change of kind, input or key (`workflow/migrations/0002_role_grants.py`).

### 3.8 Staff exception queue: `StaffItem` and an immutable resolution record (A-2)

**A table, with immutable records for audit.** Events alone cannot work:

- unmatched mail may have no application, and `ApplicationEvent.application` is not nullable;
- resolution needs a single-resolution rule;
- a partial unique key, `(reason_code, dedupe_key)` where `status = 'open'`, stops a retrying collector or
  a mail flood from opening duplicates.

**`StaffItem`:**

- Fields: `public_id`, `reason_code`, `dedupe_key` (identifiers or digests only, never an address),
  application (nullable), inbound message and `ApprovedMessage` (nullable), `question_id` and
  `pending_action_id` (plain identifiers), `status` (`open`, `resolved`), and `opened_at`.
- Grants: UPDATE `(status)` only.

**`StaffItemResolution`** (new, INSERT-only, never updated or deleted):

- Fields: item, `resolution_code`, `resolved_by`, `resolved_at`, `note` (length-capped, control
  characters stripped, confirmation links refused), and `effects` (the identifiers changed).
- Exactly one per item, by a unique key.
- This record exists **whether or not an application is known**, so an unmatched item's resolution is
  auditable without a dummy application.
- When an application is known, a `staff_item_resolved` event is also written.

**Content rule.** Items, resolutions, events and `exception_reason` carry identifiers and reason codes
only: no address, subject or body.

**Compatibility with S1.** `attention_q` reads open `StaffItem` rows. A data migration creates one open
item for each existing S1 `needs_staff_attention` event. Their resolution semantics belong to POL-19.

## 4. Lifecycle A to G

Each row gives one step's contract:

- input and owning component;
- persisted records and transaction boundary;
- permitted action and failure outcomes, with recovery;
- tests and the next responsible party.

New modules are PROPOSED paths under `correspondence/`. Numbers (cadence, maximum, quiet hours, gaps,
caps) are **named settings, not values**. They are synthetic in P2; POL-06 sets production values later.

### A. Outbound

| Step | Input and owner | Records and transaction | Permitted action; failures and recovery | Tests; next party |
|---|---|---|---|---|
| A1 Templates | owner-approved text; `models.py` | Version rows INSERT-only; one transaction per approval | Only `approved` versions render; allow-listed variables; static subjects; an unknown variable fails closed | TEST-P2-37, 38; owner |
| A2 Enqueue | a question approved, a reminder firing, or a confirmed staff message; `outbound.py` services | **One transaction under the application lock:** the `ApprovedMessage` (frozen content or reproducible inputs, frozen recipient, exact template version, authorization), its `ApprovedMessageQuestion` rows, the `send` action with `input_ref = send_ref`, and an event | A double approval hits the unique `initial` row and does nothing. A restarted worker reads only this record. | TEST-P2-12, 36, 49; worker |
| A3 Attempt | a claimed `send`; a base handler in `outbound.py`, one thin subclass per kind; `redeliverable = False`; subject `application`; transport `correspondence/transport.py` (a thin `smtplib` wrapper that records the protocol phase reached, with a total deadline below half the lease) | (1) Check transaction: lock the application, then its questions; re-check the pause (automated kinds only; a staff message ignores it, J-09), eligibility, and that the recipient still equals the verified address. If an earlier attempt **of the current attempt series** is `sending` or `unknown`, go to A5 and never send. A new series exists only through a recorded `decide_uncertain_send` decision, so earlier series never block it. Allocate the attempt number (3.2) and INSERT the attempt row `sending`; commit. (2) SMTP with no lock held. (3) Fenced finish transaction with the classified outcome. | Outcome by protocol phase and reply, never by exception class alone (table A3 below). The handler records each classified outcome with `ledger.finish` directly: `queued` with backoff for a temporary rejection, `failed` for a permanent rejection or exhausted temporary rejections, `uncertain` for unknown. It never uses `fail_or_retry` for a classified outcome, because that function would turn a definite non-acceptance on the final attempt into `uncertain` (`ledger.py` lines 143-147). `fail_or_retry` stays only for unexpected handler defects. | TEST-P2-03, 25, 27, 48; worker, then staff |
| A4 Mailbox copy (built in 2B.2, with the IMAP client) | an `accepted_by_server` attempt; the `file_copy` kind; the verification invitation excluded | Its own action, after acceptance is recorded | IMAP APPEND places a copy in a mailbox; it is **not** a delivery operation (RFC 9051 section 6.3.12). The copy carries `X-Catalyst-Filed-Copy: <send_ref>` and is **never** evidence of acceptance. Searching before APPEND reduces duplicates but is **not** exactly-once: a lost APPEND acknowledgment or a concurrent attempt can leave two copies. That is recorded, not hidden. An APPEND failure retries the APPEND only, then opens staff item `filed_copy_failed`; it **never** triggers SMTP. | TEST-P2-26; worker, then staff |
| A5 Reconcile | an attempt left `unknown`; the `reconcile` kind | Searches only the **admissible evidence** listed under A5 below | Admissible evidence moves the `ApprovedMessage` to `accepted_by_evidence`, with the evidence recorded, and the attempt stays `unknown`. No admissible evidence by the bounded deadline: the outcome **stays unknown** and staff item `send_outcome_unknown` is opened. | TEST-P2-03, 25, 26, 27; staff |
| A6 Staff decision on an unknown or exhausted outcome | `decide_uncertain_send` (F); one service for `unknown`, `retries_exhausted` and `transport_blocked` | One transaction: an immutable resolution record plus the effect | `abandon`: the message becomes `operator_abandoned` ("operator abandoned further attempts"). `authorize_resend`: a new attempt series of the same `ApprovedMessage`, with the duplicate risk shown (not offered after `rejected_permanent`); in the same transaction, any `held` action of an earlier series is set to `cancelled`, so no held action is left behind. `revise`: a new `ApprovedMessage` that supersedes this one. **None of these rewrites the historical attempt:** it stays `unknown`. | TEST-P2-26, 52; staff |
| A7 End states | a permanent rejection, attempts exhausted by temporary rejections, a channel held after repeated blocks, or the poison rule | `rejected_permanent` (staff item `send_rejected_permanent`), `retries_exhausted` (`retries_exhausted`), `transport_blocked` (`smtp_transport_blocked`; action `held`, not terminal), or `unknown` under the poison rule (`ledger.py` lines 157-162; `send_outcome_unknown`), each with an event | Visible in admin and through G3 | TEST-P2-48; staff |

**A3 outcome classes** (RFC 5321: a 4yz reply is transient and the client should try again; a 5yz reply
is permanent and the client should not repeat the exact request, section 4.2.1; a 250 reply after the end
of data hands over responsibility, sections 2.1 and 4.1.1.4):

**Channel phases** (connection, greeting, TLS, EHLO, STARTTLS, AUTH, MAIL FROM) concern the sending channel,
not this message. **Message phases** (RCPT TO, DATA, the body, the end of data) concern this message.

| Observed | Attempt status | Handling |
|---|---|---|
| Connection refused or failed, TLS failure, or a 4yz reply in a channel phase | `transport_blocked` | Not accepted, and not a verdict on the message. The attempt row is kept (it has its own number, 3.2), but **no ledger attempt is consumed**: `finish(status=queued, refund_attempt=True, due_at=<backoff>)` uses the A-7 `due_at` argument, so there is no hot loop. The count of consecutive blocks is the run of trailing `transport_blocked` attempt rows **in the current attempt series**, so no extra counter is stored and a staff resume (a new series) starts the count again. When it reaches the bound, the disposition becomes `transport_blocked`, the action is `held` (non-terminal, A-7) and one deduplicated staff item `smtp_transport_blocked` is opened. Staff resume it through `decide_uncertain_send`. |
| A 5yz reply in a channel phase (for example, authentication refused) | `transport_blocked` | As above, but held immediately with the staff item: a configuration fault, not a message rejection |
| A 4yz reply at RCPT TO, DATA or the end of data, or a failure **known to happen before the body write starts** (for example, the connection closed at the DATA command) | `rejected_temporary` | Definitely not accepted. Bounded automatic retry with backoff. When the bound is reached, the disposition becomes `retries_exhausted` with a staff item; staff may authorize a resend of the same message. |
| A 5yz reply at RCPT TO, DATA or the end of data | `rejected_permanent` | Terminal for this `ApprovedMessage`. **No unchanged retry, automatic or staff-authorized.** A staff item for correction; a correction is a revised message. |
| A 250 reply after the end of data | `accepted_by_server` | Record server acceptance. **This is not delivery to the recipient's inbox**, and nothing calls it that. |
| The write carrying the body and the end-of-data marker has **started**, then that write fails, or a timeout, a disconnect or an unparseable reply follows | `unknown` | The action becomes `uncertain` and goes to A5. **Never** an ordinary retry. Python's `socket.sendall` (used by `smtplib.SMTP.send`) documents that after an error "there is no way to determine how much data, if any, was successfully sent", so a failed write may still have delivered the marker; RFC 5321 section 6.1 notes that timeouts at this point can cause duplicate delivery. After the write has started nothing more is sent on the connection (no QUIT), so cleanup cannot complete or alter a partial DATA transaction (owner closeout of PR #21, 2026-10-13). |

"Definitely not accepted" and "safe to retry automatically" are separate questions. A permanent rejection
is the first without the second.

**A5 admissible evidence.** Evidence may resolve acceptance only when its origin and meaning are
established:

- **Not admissible:**
  - a copy Catalyst filed itself (A4), identified by its header and `filed_copy_state`;
  - a copy whose Message-ID matches but whose recipient or content digest does not match this
    `ApprovedMessage`;
  - any mailbox copy whose creation semantics are unverified.
- **Admissible only after the provider check (8.3) verifies it:** a provider-created record that is made
  only on SMTP acceptance and that matches this message's Message-ID, recipient and canonical content digest
  (3.2: `content_sha256`, or the attempt's `rendered_sha256` for a secret-bearing kind).
  Until then, P2 has **no** admissible automatic evidence for real providers, so every unknown outcome
  goes to staff. The synthetic SMTP test server exposes a test evidence source with declared semantics,
  so the mechanism itself is tested.
- **The limit of any admissible evidence.** It shows that the logical message was accepted at least once.
  It does not certify which attempt was accepted, so the unknown attempt row is never rewritten.

A crash after acceptance and before recording leaves the attempt `sending`. The next claim treats it as
`unknown` and goes to A5. In that case Catalyst never scheduled its own copy, which does not matter,
because that copy is never evidence.

### B. IMAP collection

| Step | Input and owner | Records and transaction | Permitted action; failures and recovery | Tests; next party |
|---|---|---|---|---|
| B0 Bootstrap and recovery | the management commands `correspondence_bootstrap_mailbox` and `correspondence_recover_mailbox`, run by whoever operates the host (shell access is an owner-level act outside the Django role matrix; the event records the actor as the command and the operating-system user) | Bootstrap creates the cursor with an explicit `start_mode` and an event. Recovery creates or resets the cursor in `recovery` state when locations already exist. | `from_now`: messages already in the mailbox are **explicitly out of scope**, and that is recorded. `from_uid`: start at a named UID. Bootstrap **refuses** if any `InboundMessageLocation` already exists for the mailbox; that case is the recovery command, never a fresh start. | TEST-P2-51; host operator |
| B1 Single owner | a `collect` action whose subject is the cursor; `inbound.py` | The finish transaction marks the pass done, updates health, and enqueues the next pass unless the cursor is `blocked` | One owner, by SKIP LOCKED and the per-message fence. **A blocked cursor schedules no successor.** Ordinary failures schedule a successor with backoff, and after a bounded run of consecutive failures the cursor becomes `blocked`. Only `restart_collector` (F) schedules a pass on a blocked cursor; it is separate from ordinary retry. | TEST-P2-21, 22, 23; worker |
| B2 Session | the cursor; `transport.py` (`MailboxClient`, a TLS-only `imaplib.IMAP4_SSL` wrapper, plus a fake) | Cursor updates only on validity or state changes | A verifying SSL context is passed explicitly. Timeout at most half the lease. `SELECT` is read-only, with `BODY.PEEK[]` only. Authentication failure: the cursor becomes `blocked` with reason `auth_failed`, staff item `mailbox_auth_failed`, and **no successor** (no retry chain against bad credentials). Unreachable: backoff, as in B1. | TEST-P2-23, 24; worker, then operator |
| B3 Fetch and derive | UIDs greater than `last_uid`, ascending, with a batch cap and a time budget; `mime.py` | none | The derivation pipeline (3.5). The client re-applies `uid > last_uid` itself. The client never relies on server range semantics: a UID range ending in `*` can return the highest existing UID even when it is below the start of the range. | TEST-P2-14, 15, 47; worker |
| B4 Per-message commit | one derived message; `inbound.py`, `association.py` | **One transaction per message:** lock the cursor, then the application, then its questions by id. Run identity and deduplication (B5); a known identity becomes a new location row only. Otherwise INSERT the message and its location; apply C0 to C3; enqueue `process_reply` where C allows; write the event; advance `last_uid` conditionally; **last**, `ledger.fence`. If the fence fails, roll back and stop the pass. | A message that fails processing is stored as `exception` with reason `processing_error`, so the cursor passes it. Only a database failure aborts the pass. Collection never marks a question answered and never cancels a reminder. | TEST-P2-01, 12, 19; worker |
| B5 Identity and deduplication | a fetched message | inside B4 | Message-ID, size and date are **candidate-match metadata, not proof**. A candidate is a duplicate only if `original_sha256` is equal. Equal digest: a new location row with `matched_by = digest`, no new downstream effect. An unestablished message matching on Message-ID, size and internal date: a location row with `matched_by = metadata` (3.5). Same Message-ID with a different digest: a new message plus staff item `message_id_conflict`. When the digest cannot be computed (for example, the size cap was exceeded): `identity_state = unestablished`, recorded as "identity could not be established", with no automatic downstream effect until staff resolve it. No distinct message is silently dropped. | TEST-P2-12, 13, 20, 46; staff |

#### 4.1 Watermark, checkpoint, crash, resync and recovery

The cursor's `last_uid` advances inside the message transaction, as its last data statement before the
fence, so no crash window exists between storing a message and passing it. The location unique key is a
second defence.

**Completed-collection watermark.**

1. At the start of a pass, the collector reads the mailbox's next UID and records `target = next UID -
   1` and `pass_started_at`.
2. Only when the pass has committed every UID up to `target` does it set `complete_through_uid = target`
   and `complete_through_at = pass_started_at`.
3. A successful partial batch updates `last_batch_at` and nothing else.

Reminder freshness (E2) reads `complete_through_at`, **never** `last_batch_at`. A reply that arrived
before `pass_started_at` has a UID at or below `target`, so it was collected.

| Crash point | Result |
|---|---|
| Before or during fetch or derivation | Nothing committed; the next pass re-reads the same UID |
| Inside the message transaction, before commit | Rolled back; re-read; nothing doubled |
| After the commit | The message and the cursor have both advanced |
| Lease lost | The fence fails; rollback; the stale pass stops; the new owner re-reads |
| Pass ends, but the successor is not enqueued | The pass is not `done`, so lease recovery re-runs it; the pass key is unique |
| Final failure or poison | The successor is enqueued with backoff, unless the cursor is `blocked`; a staff item is opened |

**`UIDVALIDITY` change** (RFC 9051 section 2.3.1.1: when UIDs do not persist, the value must increase).
One fenced transaction:

- sets `state = resync`, increments `epoch`, stores the new validity and resets `last_uid`;
- clears the watermark;
- opens staff item `mailbox_uidvalidity_changed`.

Resync passes then walk every UID through B5, so a message seen before gets a new location row and no
new effect. The cursor returns to `ok` when a pass sets the watermark.

**Lost or regressed cursor.** This covers a missing row while locations exist, or a `last_uid` behind the
highest stored location. The state becomes `recovery`, and the next passes walk from UID 1 through B5. A
recovery **never** uses `from_now` and **never** silently skips messages already in the mailbox.

### C. Association and trust

| Step | Input and owner | Records and transaction | Permitted action; failures and recovery | Tests; next party |
|---|---|---|---|---|
| C0 Automatic and bounce first | `auto_markers` and delivery-status reports; `association.py`, using the same pure check as D1 | inside B4 | Runs **before** trust and association. A bounce is matched only through the original Message-ID embedded in it, is never a reply, and its effects are fail-safe (D1). Its `message/delivery-status` and `message/rfc822` parts are parsed as headers only. An automatic message never sets `reply_pending`. | TEST-P2-02, 10, 33; system |
| C1 Association | `In-Reply-To`, then `References` | the matched application and `ApprovedMessage` | Exact, case-insensitive match against our stored Message-IDs only. No match: `exception` with reason `unmatched`, plus a staff item. A reply to a closed application resolves to that application and becomes an exception; it is never applied to a newer application with the same address. | TEST-P2-01, 18; staff |
| C2 Sender | `From` | `from_matches_verified_address` | Exactly one mailbox, compared by exact case-folded comparison of the ASCII (IDNA) form. If Unicode normalization would change the address, it counts as a mismatch. `Reply-To`, `Sender` and display names are never used. | TEST-P2-16; staff |
| C3 Authentication evidence and trust | `Authentication-Results`; the trust table below | `auth_evidence`, `trust_decision` | Only the **topmost** header whose authserv-id equals the configured trusted id is read; any other is `untrusted`. **Catalyst reads that header's `dmarc=` result and never computes alignment itself**: the trusted receiving MTA does. Its `spf=` and `dkim=` results are recorded for staff only. RFC 8601 requires the receiving MTA to delete forged instances of its own authserv-id (section 5) and leaves the trust relationship to configuration (section 1.6). Whether the production provider does this is unverified (8.3). In P2 the trusted id is a synthetic setting, and the test server stamps the header. | TEST-P2-17; staff |
| C4 Queue | exception rows; `StaffItem` | one open item per dedupe key | Staff associate, dismiss or mark as spoofed, under the permission matrix (F). **No association or resolution changes the verified identity, the recipient, adopted evidence or the admission stage.** Associating a message links it to an application and nothing more. | TEST-P2-06, 18, 53, 54; staff |

**Trust table** (DMARC under RFC 9989: a pass needs an authenticated identifier, from SPF or DKIM,
aligned with the author domain, section 5.3.5. An SPF failure alone is therefore not a DMARC failure when
an aligned DKIM signature passes):

| Evidence from the trusted authserv-id | `From` matches | `trust_decision` | Effect on questions and reminders | Staff queue |
|---|---|---|---|---|
| DMARC `pass` | yes | `trusted` | The related questions become `reply_pending`, so reminders are suppressed; a person's reply goes to D2 | `reply_needs_review` |
| DMARC `fail` (no aligned identifier passed) | yes | `auth_failed` | **None**: questions and reminders unchanged | `reply_auth_failed` exception |
| `dmarc=pass` reported together with `spf=fail` (the MTA found an aligned DKIM pass) | yes | `trusted` | As the first row: an SPF failure alone is not a spoofing verdict, and Catalyst follows the DMARC result | as the first row |
| No `dmarc=` result, or `none`, `temperror` or `permerror`, or any header from an untrusted authserv-id | yes | `unverified` | **None** until staff associate it: not observing a failure does not establish authentication | `reply_unverified` |
| any | no | `sender_mismatch` | **None** | `sender_mismatch` exception (POL-19) |

No row grants authority to change the verified identity or to satisfy a question automatically. When
staff associate an `unverified` message, it then behaves as `trusted` for that message only, with the
actor recorded.

### D. Reply processing

| Step | Input and owner | Records and transaction | Permitted action; failures and recovery | Tests; next party |
|---|---|---|---|---|
| D1 Classify | `process_reply` (automated, subject `application`, so a pause holds it); `processing.py` | One transaction: application, questions, message, then the fenced action | A delivery-status report is a **bounce**. A hard bounce (5.x.x) for our message and the verified recipient pauses automation and opens a staff item; a soft bounce (4.x.x) is recorded only. RFC 3834 markers (`Auto-Submitted` other than `no`) or `Precedence: bulk, junk or auto_reply`, auto-reply headers and list headers mean **automatic**. **The autoresponder rule (one rule, used everywhere):** a single automatic message is classified `automated_reply`, never answered, satisfies nothing, and neither suppresses reminders nor pauses automation. Automatic messages count toward the loop threshold, and crossing it pauses automation and opens a staff item. | TEST-P2-02, 10, 33, 34; system |
| D2 Reply from a person | a `trusted` (or staff-associated) message | The message stays `awaiting_processing`; a held `interpret_reply` per question that is still open; item `reply_needs_review` | Questions stay `reply_pending` until staff confirm (D3), close the reply (D4) or withdraw the question. P3 proposals, once they exist, also go to staff for confirmation. | TEST-P2-08, 09, 43, 44; staff, then P3 |
| D3 Outcome | `confirm_question_outcome` (F) | One transaction: application, questions, message; compare-and-set the message from `awaiting_processing` to `processed`; apply each link; refresh question status; synchronize reminders (E3); cancel held `interpret_reply`; event | `satisfied`, `partial` (question becomes `partially_answered`) or `not_addressed` (question returns to `open`). Links already `void_withdrawn` or `stale` are skipped. A concurrent loser does nothing. P2 changes no application stage (ADR-13). | TEST-P2-08, 09, 32; staff, then P3 |
| D4 Close without outcome | `close_reply_without_outcome` (permission `confirm_question_outcome`), for a reply with no pending link left (for example, all its questions were withdrawn) or with no questions at all | One transaction: compare-and-set the message from `awaiting_processing` to `processed`, with a reason code; resolve its `reply_needs_review` item; write the event | No question changes. A human reply is still read before it is closed. | TEST-P2-50; staff |

### E. Reminders

| Step | Input and owner | Records and transaction | Permitted action; failures and recovery | Tests; next party |
|---|---|---|---|---|
| E1 Schedule | `reminders.py` | Reminder 1 is created in the transaction that records `accepted_by_server` (or `accepted_by_evidence`) for the question's initial message; reminder n+1 in the transaction that records reminder n's acceptance. Due time by the database clock. | No reminder while a send is unknown. After the maximum, `escalate_unanswered` opens a staff item ("no response", J-08). Unique keys make creation idempotent. | TEST-P2-29; system |
| E2 Fire | a claimed reminder | Check transaction: application, then the question; when eligible, A2 freezes the reminder's `ApprovedMessage` and A3 sends it | Eligible only if all hold: the question is `open` or `partially_answered`; the application is open and not paused; no link is pending; not quiet hours; the minimum gap has passed; n is within the maximum; and **`complete_through_at` is at or after the reminder's due time** (4.1). Results: `reply_pending` → held; `satisfied` or `withdrawn` → cancelled; ineligible for time reasons → deferred with an explicit `due_at`; a stale watermark past a bounded number of deferrals → staff item `collector_stale`. Automated mail carries `Auto-Submitted: auto-generated`. | TEST-P2-04, 28, 29; system |
| E3 Projection | every change of question status | `sync_reminders(question)` in the same transaction | **Acts only on that question's reminder and escalation actions currently `queued` or `held`.** `open` or `partially_answered`: `held` becomes `queued`. `reply_pending`: `queued` becomes `held`. `satisfied`: `queued` or `held` becomes `cancelled`. `withdrawn`: `queued` or `held` becomes `cancelled` with reason `question_withdrawn`. It **never** touches `done`, `failed`, `uncertain` or `cancelled` actions, never resets counts or exhaustion, and never creates a reminder (only E1 creates them). Only `satisfied` and `withdrawn` cancel; `withdrawn` never counts as an answer. A reminder change never changes a question's status. | TEST-P2-04, 30, 50; system |
| E4 Resume | `resume` (F) | One transaction: application lock, delete the pause, reschedule | Each `queued` reminder that fell due during the pause gets `due_at` = now + a resume grace + its rank × the minimum gap. No catch-up copies, counts unchanged, held reminders untouched, question statuses unchanged (J-09). | TEST-P2-05, 31; system |

### F. Staff intervention and the role matrix

Services live in `correspondence/staff_actions.py` (A-3). Each is one transaction that:

- starts with the application lock (or the item lock when there is no application);
- checks a named permission;
- writes an immutable record or event with the staff actor.

**The interface is admin-first:**

- Named admin actions act on one object at a time; there is no bulk action for a sensitive service.
- Focused views are used only where admin cannot collect the input: the staff-message preview and
  confirmation, outcome confirmation with the derivative text beside the questions, and exception
  resolution.
- Whether admin actions fit `ReadOnlyAdminMixin` (`actions = None` today) without weakening it is a short
  spike in 2B.4.

**Role matrix (PROPOSED, one matrix for POL-06, POL-13 and POL-19):**

| Permission | Service | Operator | Decision-maker | Owner |
|---|---|---|---|---|
| `approve_template_version` | A1 | — | — | yes |
| `approve_question` | J-06 approval | yes | yes | yes |
| `withdraw_question` | 3.3 | yes | yes | yes |
| `send_staff_message` | 3.4 | yes | yes | yes |
| `pause_automation`, `resume_automation` | F, E4 | yes | yes | yes |
| `resolve_exception` | non-identity items (unmatched dismissal, collector, soft-bounce records) | yes | yes | yes |
| `confirm_question_outcome` | D3, D4 | yes | yes | yes |
| `resolve_identity_exception` | associate an unmatched message, or an `unverified` or mismatched sender; mark as spoofed; any POL-19 item | — | yes | yes |
| `decide_uncertain_send` | A6 | — | yes | yes |
| `restart_collector` | the admin action that resumes a blocked cursor (B1, B2); bootstrap and recovery are host-level (B0) | — | yes | yes |

**Which permission resolves which staff item:**

| Reason codes | Permission |
|---|---|
| `unmatched` (dismiss), `processing_error`, `message_id_conflict`, `mailbox_uidvalidity_changed`, `collector_stale`, `filed_copy_failed`, loop-threshold items | `resolve_exception` |
| `reply_needs_review` | `confirm_question_outcome` (D3, or D4 when no outcome remains) |
| `unmatched` (associate with an application), `reply_unverified`, `reply_auth_failed`, `sender_mismatch`, any item that would mark a message as spoofed, the S1 POL-19 items | `resolve_identity_exception` |
| `hard_bounce` (`address_usable_again` only, with a reason; 9kg.3), `send_outcome_unknown`, `retries_exhausted`, `smtp_transport_blocked`, `send_rejected_permanent` (abandon or revise only), `send_refused` (a pre-send re-check refused the message, for example the recipient no longer equals the verified address; added in 2B.1) | `decide_uncertain_send` |
| `mailbox_auth_failed`, `collector_blocked` (TLS refused, peer refused, unreachable past the bound) and other blocked-cursor items | `restart_collector` (admin action); the bootstrap and recovery commands are host-level (B0) |
| `inbound_oversize`, `application_closed`, `collector_pass_failed`, `mailbox_history_out_of_scope` (informational, opened by a `from_now` bootstrap) | `resolve_exception` (added in 2B.2) |
| `escalate_unanswered` ("no response") | `resolve_exception`, or `withdraw_question` |

Notes on the matrix:

- The S1 read-only group keeps exactly its view permissions.
- No account can act until the owner creates these groups.
- Against real mail, no account receives a write permission and no staff-authored send is enabled until
  POL-13's MFA and network restriction are decided (8.3).

### G. Monitoring (definitions; each built in its B task)

These are read-only queries in `correspondence/health.py`, surfaced as admin filters and dossier lines,
plus `manage.py correspondence_health` (an exit status that P6 can wire to alerting). Each query is
built and tested **in the B task that creates its tables**, never first in 2C.

| Signal | Definition | Built in |
|---|---|---|
| G1 Collector | `complete_through_at` older than k × the poll interval; a `blocked` cursor (by reason); an unblocked cursor with no `queued` or `running` collect action (broken chain); `consecutive_failures` | 2B.2 |
| G2 Oldest unprocessed | the oldest `awaiting_processing` message, overall and per application; messages with `identity_state = unestablished` | 2B.3 |
| G3 Sends | messages by disposition, including `retries_exhausted` and `transport_blocked`; `unknown` and `sending` attempts older than the lease; `rejected_permanent` | 2B.1 |
| G4 Overdue conversations | reminders queued past due by more than a margin; open questions with no live reminder while under the maximum | 2B.4 |
| G5 Staff items | open items by reason and age; paused applications by pause age | 2B.4 |
| G6 Consistency | a `reply_pending` question with no pending link; a pending link whose message is not `awaiting_processing`; a held reminder whose question is not `reply_pending`; a live reminder on a withdrawn question | 2B.3 and 2B.4 |
| G7 Mail behaviour and storage | automatic inbound per application per window; hard bounces; growth of the inbound tables | 2B.4 |

## 5. Lock order and transactions

**Order** (extends `005` S1.4, which is application, then challenge):

1. mailbox cursor (collector only, always outermost);
2. application (or a staff item, when there is no application);
3. challenge and question rows, by id;
4. inbound message;
5. approved message, then outbound attempts;
6. pending-action rows, by id.

Nothing takes the application and then the cursor, so the order has no cycle. Inside the ledger's fenced
result transaction the action row is updated before the handler writes message rows; that is safe
because every path that touches either has already locked the application (2B.1 review). For reminder, processing
and send kinds, `lock_subject` locks the application, then the named questions, before the fenced action
update. Providers are never called while a row lock is held (`ledger.py` rule 3).

**Reply versus reminder:**

- **Collector commits first.** The reminder check sees `reply_pending` and holds the reminder; it is not
  cancelled.
- **Reminder check commits first.** The reminder goes out, and the reply then sets `reply_pending`. This is
  lawful.
- **The guarantee:** no reminder check passes after a committed trusted reply. It is not "no reminder is
  sent after the applicant pressed send", because providers are never called under a lock.
- **Collector lag:** covered by the completed-collection watermark (4.1). A partial batch never counts as
  fresh.
- **Staff confirmation versus `process_reply`:** a compare-and-set on `awaiting_processing` lets exactly
  one win.
- **Withdrawal versus a firing reminder:** both lock the application, then the question. A reminder
  check that runs after the withdrawal sees `withdrawn` and cancels itself.
- **A late reply to a satisfied or withdrawn question:** the link is `stale` or `void_withdrawn`, and the
  question is unchanged.
- **Pause versus an in-flight automated action:** the check re-reads the pause; an action past its check
  completes. Staff messages ignore pauses by design.

## 6. Security and privacy

| Threat | Control |
|---|---|
| Spoofed `From` | The trust table (C3): only `trusted` affects questions or reminders; satisfaction always needs staff confirmation; no row changes identity |
| A learned Message-ID in a forged reply | Association uses the Message-ID; trust needs the sender and the evidence, against the matched application only |
| Forged `Authentication-Results` | Only the topmost header with the trusted authserv-id is read; safe only if the provider deletes forged copies (RFC 8601 section 5), which is unverified (8.3) |
| Forged bounce | Counts only for our embedded Message-ID and the verified recipient; the effect fails safe |
| Header injection outbound | Static subjects, allow-listed variables, a standard-library `EmailMessage` whose header policy rejects newlines, the frozen recipient only, no CC or BCC from any input |
| Look-alike addresses, `Reply-To`, display names | Never used for identity; staff see the normalized address as plain text |
| Autoresponder storms and backscatter | Automatic mail is never answered; ours carries `Auto-Submitted: auto-generated`; the loop threshold and a circuit breaker pause automation |
| Malicious MIME | The bounded pipeline (3.5): size gate, decoding caps, depth and part caps, recorded defects; attachments never opened |
| Active content | Never rendered; HTML reduced to text; Django auto-escaping; bidirectional-override and control characters stripped for display |
| Prompt injection aimed at P3 | P2 interprets nothing; text is stored as a labelled, untrusted derivative |
| Confirmation tokens in inbound mail (D-24) | Decoded before redaction, redacted in quoted, forwarded and encoded forms, and no original bytes stored; not a universal secret detector |
| Untrusted mail accumulating | No original-bytes store; bounded derivatives; G7; original custody waits for POL-10 |
| IMAP or SMTP downgrade | TLS-only clients, a verifying context passed explicitly, no plaintext fallback. **Verified in 2B.2** (owner decision M6): on the real SMTP (STARTTLS) and IMAP (implicit TLS) transport paths, a verified certificate succeeds, an untrusted certificate and a wrong hostname are refused before any credential, a refused STARTTLS never falls back to plaintext, and IMAP has no plaintext path. Test certificates are generated at run time; none is committed |
| Secrets or bodies in logs | **The control is a tested rule:** reason codes, identifiers and exception class names only; no `logger.exception`, no exception text, no `set_debuglevel`. `config/redaction.py` is a backstop. |
| Preview tampering on staff messages | Digest and recipient re-checked on confirmation (3.4) |
| Silent identity change | No association, resolution or staff message can change the verified address, the recipient, adopted evidence or the stage (C4) |

**Content storage (PROPOSED, POL-10).** Derivatives, metadata and digests are stored in PostgreSQL.
Nothing is deleted (D-17, D-22). Original bytes are not stored in P2.

**Start-up and connect-time guards (PROPOSED, decision A-4; amends REQ-022).** REQ-022 requires settings
to refuse non-sink mail hosts outside production. A local SMTP or IMAP test server is not a sink, so this
is an explicit amendment.

- Provider variables named `MXROUTE_`, `SMTP_` or `EMAIL_HOST` are still refused. The new settings are
  named `CATALYST_MAIL_*`.
- In `development` and `test`, a mail host must be a literal loopback IP, or the one named test-service
  host in `test`. This mirrors the database-host allowance in `tests/conftest.py`'s network guard.
- The transports re-check the connected peer address and refuse, before any credential is sent, unless
  it is loopback or the test service's private address.
- `CATALYST_MAIL_USER` and `CATALYST_MAIL_PASSWORD` are refused unless the host passes the same check.

Real MXroute stays refused until separately authorized.

## 7. GATE-P2 acceptance plan

GATE-P2 (`002` section 6) requires every case below to PASS in CI, with the loopback SMTP test server and
the local IMAP test server, plus the phase after-action report.

- **Built with their code.** Each case is written and passing in the B task that builds its behaviour
  (section 9). In 2C the cases are only gathered into `tests/acceptance.py`.
- **GATE-S1 stays mapped.** Its 22 cases remain mapped and gated in every full run.
- **No skips.** No mandatory test may be skipped: the existing skip gate fails any skip, xfail or xpass.
- **How hard cases are tested.** Concurrency cases use real transactions and barrier seams, and crash
  cases a real worker subprocess killed with SIGKILL (the TEST-S1-07c pattern).

**Already named in `004` and `002`** (11 cases):

| ID | Case | Section |
|---|---|---|
| TEST-P2-01 | A reply is correlated to its approved message and the questions it carried | B4, C1 |
| TEST-P2-02 | A single autoresponder is classified and never answered, without suppressing or pausing; crossing the loop threshold pauses automation | C0, D1 |
| TEST-P2-03 | An unknown send outcome is reconciled, never blindly retried | A3, A5 |
| TEST-P2-04 | Reminder race: a reminder is held, not cancelled, while a trusted reply awaits processing | E2, E3, section 5 |
| TEST-P2-05 | A pause stops every automated kind; resume reschedules without a burst and changes no question status | F, E4 |
| TEST-P2-06 | Staff resolve an exception without SSH, leaving an immutable resolution record | F, 3.8 |
| TEST-P2-07 | A `UIDVALIDITY` change resynchronizes with no new downstream effect and alerts staff | 4.1 |
| TEST-P2-08 | A partial answer leaves the rest open | D3 |
| TEST-P2-09 | An acknowledgement is not an answer | D3 |
| TEST-P2-10 | An autoresponder satisfies nothing | D1 |
| TEST-P2-11 | A confirmed staff message is sent while paused, and no automated action runs | 3.4, F |

**Added in 2A (PROPOSED; cases 12 to 47 revised in 0.3.0 where marked, 48 to 54 new):**

| ID | Case |
|---|---|
| TEST-P2-12 | Duplicates cause no new effect: the same UID fetched twice, a question approved twice, identical bytes seen at a second location (a location row only), our own filed copy seen in a collected folder |
| TEST-P2-13 | *(revised)* The same Message-ID with different bytes, **including identical Message-ID, size and date**, is kept as a distinct message with a staff item |
| TEST-P2-14 | Malformed MIME gives an `exception` row with recorded defects, and the cursor passes it |
| TEST-P2-15 | An oversize message or part is recorded as omitted, with no body fetch beyond the cap |
| TEST-P2-16 | A mismatched sender has no effect on questions or reminders and opens a staff item |
| TEST-P2-17 | *(revised)* One fixture per trust-table row, each a header from the trusted authserv-id unless stated: `dmarc=pass`; `dmarc=fail`; `dmarc=pass` with `spf=fail`; no `dmarc=` result; `dmarc=temperror`; a `dmarc=pass` from an untrusted authserv-id; and a `From` mismatch. Each asserts the stored decision and its effect on `reply_pending`. No row changes identity or satisfies a question. |
| TEST-P2-18 | Unmatched mail reaches the queue; a reply to a closed application is never applied to a newer one |
| TEST-P2-19 | A collector killed mid-message loses nothing and duplicates nothing |
| TEST-P2-20 | *(revised)* A lost or regressed cursor enters `recovery` (through the recovery command when the row is missing), walks from UID 1, skips nothing, and creates no new effect, including for messages whose identity is unestablished |
| TEST-P2-21 | Two collectors: the fence stops the stale one, including a lease that expires between two messages |
| TEST-P2-22 | *(revised)* Two workers race for one collect action: one claim, one successor; an ordinary final failure keeps the chain; a `blocked` cursor schedules nothing |
| TEST-P2-23 | *(revised)* An authentication failure blocks the cursor with no successor and no retry chain, and only `restart_collector` resumes it. An unreachable server backs off. A sentinel test proves no credential, address, subject or body appears in any log output. |
| TEST-P2-24 | A plaintext server and a bad certificate are refused |
| TEST-P2-25 | *(revised)* An unknown outcome becomes `uncertain`. Test-declared provider evidence with the matching Message-ID, recipient and canonical digest moves the message to `accepted_by_evidence`, and the attempt stays `unknown`; evidence with the wrong recipient or digest is ignored (2B.1). A Catalyst-filed copy never resolves it (2B.2). |
| TEST-P2-26 | *(revised)* With no admissible evidence the outcome stays unknown and goes to staff. `abandon` records `operator_abandoned` and the attempt stays `unknown`. `authorize_resend` opens a new attempt series that **is** sent, while the earlier attempt stays `unknown`; it is refused after `rejected_permanent` (2B.1). An APPEND failure or lost APPEND acknowledgment never triggers SMTP (2B.2). |
| TEST-P2-27 | *(revised)* A crash after a 250 reply and before recording leaves the attempt `sending`; the next claim goes to reconciliation, never to a new send. Proven twice: in-process through a seam, and with a **real worker process killed with SIGKILL** and a fresh real worker recovering through the normal lease path (owner decision M7, 2026-10-13) |
| TEST-P2-28 | *(revised)* Reminder-race matrix, including a recent partial batch that does **not** satisfy the watermark |
| TEST-P2-29 | Cadence, maximum, quiet hours and minimum gap (synthetic settings); escalation after the last reminder |
| TEST-P2-30 | *(revised)* Only `satisfied` and `withdrawn` cancel; a partial answer keeps reminders; the projection never revives `done`, `failed`, `uncertain` or `cancelled` actions, never resets exhaustion and never creates reminders |
| TEST-P2-31 | A pause during a running reminder; resume across several questions and applications causes no burst |
| TEST-P2-32 | Staff confirmation racing `process_reply`: exactly one wins |
| TEST-P2-33 | A hard bounce for our Message-ID and the verified recipient pauses automation; a soft bounce is recorded only; a bounce whose embedded Message-ID is not ours, or whose original recipient is not the verified address, is recorded with no effect. A forgery that copies both still only fails safe (a pause and a staff item), which is the accepted residual risk. |
| TEST-P2-34 | The loop threshold pauses automation and opens a staff item |
| TEST-P2-35 | A late reply to a satisfied or withdrawn question changes nothing |
| TEST-P2-36 | The recipient is always the frozen verified address, never `From`, `Reply-To` or typed text |
| TEST-P2-37 | Template approval and immutability, the allow-list, and enforcement of the secret-bearing flag |
| TEST-P2-38 | Header-injection attempts are rejected outbound |
| TEST-P2-39 | *(revised)* Schema and grants: column-level UPDATE only, no DELETE, `ApprovedMessage` content fixed after insert, `StaffItemResolution` INSERT-only, and **no table stores original MIME bytes** |
| TEST-P2-40 | Guards: start-up refusal, the connect-time peer check before any credential, and refusal of credentials or provider variables for other hosts |
| TEST-P2-41 | *(revised)* Each G query returns its seeded anomaly, tested in the B task named in section 4 G |
| TEST-P2-42 | Admin: each named action needs its permission; everything else stays read-only; hostile text is escaped |
| TEST-P2-43 | A held `interpret_reply` is never claimed; no model client is imported; no network call outside the transports |
| TEST-P2-44 | Quote stripping and derivation golden cases per `derivation_version` |
| TEST-P2-45 | *(revised)* Staff message: preview and confirmation of the exact content and recipient. A changed digest, a changed verified address, a permission removed between preview and confirmation, or a second confirmation of the same draft all refuse. No side effects. A credential-like or confirmation-link body is refused. The send cannot reach a non-test host. |
| TEST-P2-46 | A `UIDVALIDITY` change mid-batch, and a crash during resync |
| TEST-P2-47 | *(revised)* Confirmation links are redacted from base64, quoted-printable (soft breaks), percent-encoded, HTML-link, quoted and forwarded forms. The stored text is flagged as a derivative with versions, truncation and omissions recorded. No original bytes are stored. A redaction-version bump re-derives from the mailbox, or from the derivative when the source is gone, and keeps no old text. |
| TEST-P2-48 | *(new)* SMTP outcome matrix by protocol phase. Channel phases (connection, greeting, TLS, AUTH, MAIL FROM) give `transport_blocked` with no attempt consumed and a hold after 5yz or repeated 4yz. A 4yz at RCPT, DATA or the end of data, or a failure known before the body write starts, gives a bounded retry, then `retries_exhausted`. A failure once the marker-carrying write has started (including a simulated write error after the server received the whole message) gives `unknown`, reconciliation and staff, never a second send. A 5yz at RCPT, DATA or the end of data gives `rejected_permanent` with no unchanged retry. A 250 after data gives `accepted_by_server` (never "delivered"). A disconnect after the end-of-data marker gives `unknown`. Each classified outcome is recorded without `fail_or_retry`. |
| TEST-P2-49 | *(new)* A restarted worker sends exactly the frozen approved message, even after a new template version is approved or an answer changes; a revised message has a new identity and Message-ID and links to its predecessor |
| TEST-P2-50 | *(new)* Withdrawal: it records actor, reason and an event; cancels only that question's `queued` and `held` reminder and escalation actions; voids pending links without dropping the reply; cancels held `interpret_reply`; resolves its own items; never counts as an answer; never reopens. A reply left with no pending link is closed through D4. |
| TEST-P2-51 | *(new)* Bootstrap records its start mode, and `from_now` records the omitted history; bootstrap refuses when locations exist; recovery never uses `from_now` |
| TEST-P2-52 | *(new)* Role matrix: each service refuses without its permission; identity resolution, unknown-send decisions and collector restart need the decision-maker role |
| TEST-P2-53 | *(new)* An unmatched item's resolution leaves an immutable record with no application; no dummy application is ever created |
| TEST-P2-54 | *(new)* No association, resolution or staff message changes the verified address, the recipient, an adoption or the application stage |

Every case runs on synthetic mailboxes with `example.test` addresses. TEST-P2-40 also proves that no test
reaches a real provider.

## 8. Owner decisions brief

**Decision state (2026-10-12).** The owner approved the architecture of 0.3.2 as a whole, and the named
decisions are D-27 to D-32. Section 8.1 is decided (D-27 to D-31). In 8.2, A-5, A-6, A-8, A-9, A-10 and
POL-19 are decided (D-28, D-31). The 8.2 items not named in a decision (the trust table, the autoresponder
rule, and POL-06 cadence and stop values, which stay synthetic settings) are confirmed when their task is
released. Sections 8.3 and 8.4 remain open. Section 8.6 is decided (D-32). Outbound foundations (2B.1) do **not** need production cadence, the later
policies or the deployment design.

### 8.1 What blocks 2B.1 (outbound foundations)

| Item | Question | Recommended default |
|---|---|---|
| ADR-15 generalization | Does every non-redeliverable send use the A3 outcome classes, the `uncertain` status, the A5 evidence rule and staff decisions (A6)? | Yes, as written in A3 to A6. D-20 stays limited to the verification invitation. `collect` and `process_reply` may retry, because they have no external effect; the owner confirms that reading of D-20. |
| A-11 Approved message | One immutable `ApprovedMessage` per logical message, separate from attempts; retry versus revised resend as in 3.2 | Adopt 3.2 |
| A-4 Guard amendment (amends REQ-022) | Allow a loopback SMTP test server in `development` and `test`, with a connect-time peer check | Adopt section 6. Without it, 2B.1 cannot test protocol phases. |
| A-1 Question home | Questions in `correspondence` (amends the proposed ADR-01 app split) | Adopt; 2B.1 creates the minimal `Question` needed by `ApprovedMessageQuestion` |
| A-7 Ledger additions | `due_at` on `finish`; `fence(claim)` | Adopt both. `fence` is first used in 2B.2. |
| POL-06, send authority only | Who approves templates and who may cause a send | Owner approves template versions; operators approve questions; synthetic wording only (wording itself is POL-17, before pilot) |
| A-2 Staff items | `StaffItem` with the INSERT-only `StaffItemResolution` (3.8) | Adopt; 2B.1 opens the first items (`send_outcome_unknown`, `retries_exhausted`, `smtp_transport_blocked`) |
| A-3 Service home | Staff services in `correspondence/staff_actions.py` | Adopt; 2B.1 builds `decide_uncertain_send` |
| POL-13 role matrix (P2 slice) | The single matrix in F, decided once for all of P2 | Adopt the matrix in F. 2B.1 needs `approve_template_version`, `approve_question` and `decide_uncertain_send`; later tasks use the rest without a new decision. |

### 8.2 What blocks each later B task

| Task | Items | Recommended default |
|---|---|---|
| 2B.2 collection | A-9 inbound storage (3.5); A-10 bootstrap and recovery (B0, 4.1); the trust table (C3); POL-19, the default part (2B.2 opens the first `unmatched`, `sender_mismatch` and `message_id_conflict` items); A-6 aggregation of unmatched items | Adopt: no original bytes; explicit `start_mode`, with recovery never `from_now`; the trust table as written. POL-19: a staff item only, with no automatic effect. A-6: one item per message with a hashed dedupe key. |
| 2B.3 processing | POL-19, the resolution part (who resolves identity items: the decision-maker role, F); the autoresponder rule (D1) | Adopt as written |
| 2B.4 reminders and staff | POL-06 cadence and stop rules (synthetic settings); A-5 staff messages (3.4); A-8 withdrawal (3.3) | Adopt as written; production numbers are decided later |

### 8.3 What blocks real provider access (MXroute)

| Item | Recommended default |
|---|---|
| POL-02 link lifetime and resends | Decide before the first real email |
| POL-10 for messages | Decide whether, where and for how long original bytes may be held, who may read derivatives, and deletion; until then no original bytes are stored |
| Provider facts, verified by a separately authorized read-only check | Whether a supplied Message-ID is preserved; whether provider-created Sent records exist, and whether they are made only on acceptance (this decides whether A5 has any admissible evidence); the authserv-id and whether forged `Authentication-Results` headers are deleted; reply-address support; whether a provider-side copy of the invitation holds a confirmation link |
| POL-13 MFA and network | No P2 write permission and no staff-authored send against real mail until decided |
| Guard lift | A separate authorization, after the items above |

### 8.4 What blocks staging and pilot

- **POL-10 in full:** retention for messages, derivatives, staff items and resolutions.
- **POL-13 in full:** MFA and network restriction (GATE-STAGING).
- **POL-16:** operating targets for the G signals.
- **POL-17:** applicant-facing wording.
- **Production values** for the POL-06 settings.

### 8.5 Architecture choices (the A list)

| ID | Choice | Recommended default |
|---|---|---|
| A-1 | Home of `Question` | `correspondence` in P2 |
| A-2 | Staff exception queue | `StaffItem` plus the INSERT-only `StaffItemResolution` (3.8) |
| A-3 | Home of pause, resume and takeover services | `correspondence/staff_actions.py` |
| A-4 | Guard amendment for local test servers (amends REQ-022; owner-decided D-10 unchanged) | Section 6 |
| A-5 | Staff messages | Free text with permission, a preview, digest-checked confirmation and an immutable approved message; synthetic only (3.4) |
| A-6 | Unmatched-mail items | One per message; aggregate per sender digest and day only if floods appear |
| A-7 | Ledger additions | `due_at` on `finish`; `fence(claim)`; one action row per collector pass |
| A-8 | Question withdrawal | An explicit `withdrawn` disposition with actor, reason and an event; not an answer; never reopened (3.3) |
| A-9 | Inbound storage | No persistent original MIME bytes in synthetic P2; a labelled sanitized derivative, metadata, locations and the original digest (3.5) |
| A-10 | Mailbox bootstrap and recovery (replaces the former "decision B-4") | An explicit `start_mode` at bootstrap; `from_now` records that earlier history is out of scope; bootstrap refuses when locations exist; recovery walks from UID 1 and never skips |
| A-11 | Approved message | 3.2 |

### 8.6 Classification of `015`

The PDF rendering of `015` carried a "Confidential" footer from the rendering theme's default, and the
source is public. Options:

- (a) public, with future PDFs using an unclassified theme;
- (b) internal, and moved out of the repository.

Recommended: (a). The owner decides.

## 9. Bead map and the 2B/2C mapping

The phase plan is unchanged: 2A, then 2B.1 to 2B.4, then 2C, on beads `7hu.1` to `7hu.6`. No task is
split. Health and reconciliation behaviour is built in the B tasks; 2C is verification only.

| Key | Bead | Title | Depends on |
|---|---|---|---|
| 2A | `catalyst-v2-7hu.1` | Specify the P2 correspondence design and prepare the owner's P2 decisions | GATE-S1 |
| 2B.1 | `catalyst-v2-7hu.2` | Build the outbound communication foundations: versioned templates, a generalized send handler, the uncertain status and SMTP-fake reconciliation (includes the first staff items and `decide_uncertain_send`; no IMAP) | 2A; section 8.1 |
| 2B.2 | `catalyst-v2-7hu.3` | Collect inbound mail from the local IMAP test server and correlate it durably with outbound messages (includes the filed-copy action A4, `restart_collector`, and the bootstrap and recovery commands) | 2B.1; 8.2 (2B.2 row) |
| 2B.3 | `catalyst-v2-7hu.4` | Process replies deterministically and route judgment to staff confirmation or a held interpretation action (includes the services `confirm_question_outcome`, `close_reply_without_outcome`, `resolve_exception` and `resolve_identity_exception`) | 2B.2; 8.2 (2B.3 row) |
| 2B.4 | `catalyst-v2-7hu.5` | Run reminders and controlled staff intervention: suppression, stop rules, pause and resume, staff messages and exception resolution | 2B.3; 8.2 (2B.4 row) |
| 2C | `catalyst-v2-7hu.6` | Verify the correspondence loop: the GATE-P2 acceptance run, independent QA and the after-action report | 2B.1 to 2B.4 |

| Tests and monitoring | Task |
|---|---|
| TEST-P2-03, 12 (approval side), 25 (SMTP and evidence side), 26 (decision side), 27, 36 to 38, 48, 49; the SMTP half of 40; G3 | 2B.1 |
| TEST-P2-01, 07, 12 (fetch and own-copy side), 13 to 24, 25 and 26 (filed-copy side), 46, 47, 51; the IMAP half of 40; G1 | 2B.2 |
| TEST-P2-02, 06, 08 to 10, 32 to 34, 43, 44, 53, 54; G2, G6 (questions) | 2B.3 |
| TEST-P2-04, 05, 11, 28 to 31, 35, 42, 45, 50; G4, G5, G6 (reminders), G7 | 2B.4 |
| TEST-P2-39, 41 and 52: each task tests the grants, G queries and permissions of the tables and services it creates | 2B.1 to 2B.4 |
| Gathering every case into `tests/acceptance.py`, the full GATE-P2 run, QA and the AAR | 2C |

## 10. Review record

### 10.1 Version 0.2.0 (2026-10-11)

One independent `catalyst-security-privacy` review applied 5 HIGH, 9 MEDIUM and 7 LOW findings, and a
re-check fixed six follow-on errors. The detail is in PR #20's review comment. Where 0.3.0 supersedes a
0.2.0 disposition, the table below says so. The most important case: the raw-store and INSERT-only grant
design is replaced by no original-bytes store.

### 10.2 Version 0.3.0: the consolidated 2A closeout (2026-10-12)

The owner's consolidated review of PR #20 at `f3201fa` asked for nine corrections. Each disposition below
was **fixed by the author** in 0.3.0. Section 10.3 records the independent review of 0.3.0, the fixes in
0.3.1, and the independent re-check of 0.3.1.

| # | Correction | Disposition (where fixed) |
|---|---|---|
| 1 | Question withdrawal: an explicit disposition, not "satisfied with a note" | Fixed: `withdrawn` status with actor, reason and an event; effects on reminders, links, staff items and P3; never reopened; "only satisfied cancels" replaced by "satisfied or withdrawn" (3.3, E3, D2, section 5, A-8, TEST-P2-30, 35, 50) |
| 2 | Staff messages: permission, preview and confirmation, a frozen message, tamper rejection; credential detection is not authorization | Fixed (3.4, A-5, TEST-P2-11, 45) |
| 3 | Inbound storage: originals, derivatives, metadata and digests distinguished; no original-raw store; decode before redaction; provenance | Fixed: `InboundMessageRaw` removed; derivation pipeline with versions, truncation and omissions; derivative labelled; source mail left in the mailbox (3.5, A-9, TEST-P2-39, 47) |
| 4 | A durable approved message before the first attempt | Fixed: `ApprovedMessage`, with retry versus revised resend (3.2, A2, A-11, TEST-P2-49) |
| 5 | Temporary, permanent, accepted and unknown SMTP outcomes by protocol phase | Fixed: the A3 outcome table, citing RFC 5321 (TEST-P2-48) |
| 6 | Reconciliation evidence | Fixed: admissible evidence rules; a Catalyst-filed copy is never evidence; the crash-before-record case; abandonment is not rejection; APPEND is not delivery and not exactly-once (A4 to A6, TEST-P2-25 to 27) |
| 7 | Inbound identity, deduplication and the trust table | Fixed: digest-based identity, location rows, `unestablished` identity; trust table per RFC 8601 and RFC 9989; no silent identity change (B5, C3, C4, TEST-P2-12, 13, 17, 54) |
| 8 | Collector correctness | Fixed: a completed-collection watermark separate from partial batches; a blocked cursor schedules nothing; restart is a separate permission; bootstrap separated from recovery; "decision B-4" replaced by A-10 (3.6, B0 to B2, 4.1, TEST-P2-20, 22, 23, 28, 51) |
| 9 | Questions, reminders and staff controls | Fixed: one role matrix aligning POL-06, POL-13 and POL-19; the projection restricted to `queued` and `held` actions; one autoresponder rule; immutable resolution records without an application (F, E3, D1, 3.8, TEST-P2-02, 30, 52, 53) |
| D | Phase plan and decision authority | Fixed: the plan is unchanged; G queries are built in the B tasks; 2C is verification only; the decision table is split into 8.1 to 8.4 |
| — | Affected references | Updated: `002` (REQ-012 wording, traceability), `003` (ADR-15 note), `004` (J-06 to J-08), `005` (S2 pointer), `011` (the P2 phase row and the P2 task table, including blockers and the 2C title) |

### 10.3 Independent QA review of 0.3.0, and the fixes in 0.3.1 (2026-10-12)

One focused, read-only review by `catalyst-independent-qa`, a reviewer that did not write this document,
covered the correspondence reliability of 0.3.0, its proposed test expectations and the reference edits.

- **What it found correct.** It found every one of the nine corrections and D present, with no item NOT
  FIXED, but it rated each one PARTIAL. It confirmed that no decision is stated as approved, that all 54
  test IDs and A-1 to A-11 resolve, that the lock order has no cycle, and that every claim about existing
  code (`ledger.py`, `verification.py`, guards, grants, the skip gate) is accurate.
- **What it found wrong.** 2 BLOCKER, 4 HIGH, 10 MEDIUM and 6 LOW findings. The author fixed each one in
  0.3.1, as below; the re-check in 10.4 qualifies four of them:

| Severity | Finding | Fix in 0.3.1 |
|---|---|---|
| BLOCKER | 0.3.0 claimed an independent re-check that did not exist | Header and 10.2 corrected; this section records the review |
| BLOCKER | 2B.1 depended on staff items, the staff decision service, the role matrix, IMAP and guard tests that 8.1 and the test map put elsewhere | 8.1 adds A-2, A-3 and the role matrix; IMAP work (A4, filed-copy tests, the IMAP half of TEST-P2-40) moves to 2B.2; grants, G queries and permissions are tested in the task that creates them (section 9) |
| HIGH | A3's pre-send check blocked the resend that A6 authorizes | The check is scoped to the current attempt series; a new series exists only through a recorded decision; TEST-P2-26 sends it |
| HIGH | Staff drafts needed UPDATE on authorization columns and looked like committed messages; staff messages have no template | `StaffMessageDraft` (INSERT-only), promoted into an `ApprovedMessage` authorized at insert; `template_version` optional only for `staff_message` (3.2, 3.4) |
| HIGH | Exhausted temporary rejections were labelled permanent; channel faults (AUTH, TLS) were treated as message verdicts; `fail_or_retry` would turn a definite rejection into `uncertain` | `retries_exhausted` and `transport_blocked` dispositions; channel versus message phases; handlers record classified outcomes with `finish` directly (A3, TEST-P2-48) |
| HIGH | Stale text outside 016: bead descriptions ("cancellation only on satisfied", "Message-ID lookup in the Sent folder"), `004` (protected body storage, Message-ID deduplication, bounce pauses) and `002` REQ-012 (bounces stop automation) | Bead descriptions rewritten; `004` J-07 and J-08 and `002` REQ-012 updated |
| MEDIUM | Undefined digest basis for evidence | A canonical rendered digest, plus `rendered_sha256` for secret-bearing kinds (3.2, A5) |
| MEDIUM | Unestablished identities duplicated on every resync | Location-only linking by metadata, recorded as `matched_by_metadata` (3.5, TEST-P2-20) |
| MEDIUM | Trust-table method undefined | Catalyst reads the trusted header's `dmarc=` result and never computes alignment; exact fixtures in TEST-P2-17 |
| MEDIUM | No mapping from staff-item reason to permission; bootstrap authority unclear | Reason-to-permission table (F); bootstrap and recovery commands are host-level acts (B0) |
| MEDIUM | Test mapping errors (TEST-P2-02, 35, services needed by 2B.3) | Section 9 remapped; the 2B.3 services are named in its bead row |
| MEDIUM | A reply could stay `awaiting_processing` forever once its questions were withdrawn | D4 `close_reply_without_outcome`; D3 skips void links |
| MEDIUM | A redaction defect could not be remedied | `correspondence_rederive`, keeping no old text (3.5, TEST-P2-47) |
| MEDIUM | Nobody could recreate a lost cursor | The recovery command (B0) |
| MEDIUM | A disconnect between the 354 reply and the end-of-data marker was unclassified | `rejected_temporary` row (A3, TEST-P2-48) |
| MEDIUM | Test wording drifted (TEST-P2-30, 33, 45, 50) | Each aligned with the body |
| LOW | `LeftForRecovery` location; unused RFC citations; the RFC 9051 `*` claim; "or P3 ships"; the `005` date; the filed-copy folder | Fixed (section 2, header, B3, D2, `005`, 3.6) |

The fixes above are the author's. Whether they hold is recorded by the re-check in 10.4.

### 10.4 Independent re-check of 0.3.1, and the fixes in 0.3.2 (2026-10-12)

**The same reviewer re-checked 0.3.1:**

- **Its own findings:** 18 of 22 CONFIRMED (findings 1, 3, 4 and 7 to 22 except 19), 4 PARTIAL (2, 5, 10
  and 19), none NOT FIXED.
- **The owner's corrections:** 3 (inbound storage), 6 (reconciliation evidence), 7 (deduplication and
  trust) and 8 (collector) independently rated **FIXED-CONFIRMED**. Corrections 1, 2, 4, 5 and 9 and D
  were rated PARTIAL.
- **New defects in 0.3.1:** one HIGH, three MEDIUM and three LOW.

The author fixed them in 0.3.2. **These 0.3.2 fixes are the author's and have not been independently
re-checked.**

| ID | Finding | Fix in 0.3.2 |
|---|---|---|
| N1 (HIGH) | Refunding a channel-fault attempt would reuse `attempt_number`, which is unique; no counter for consecutive blocks; no `due_at` on the refund | Attempt numbers are a per-message sequence independent of the ledger count; consecutive blocks are counted from attempt rows; the refund uses the A-7 `due_at` (3.2, A3) |
| N2 (MEDIUM) | `transport_blocked` was missing from A7, the resend rules, the key note and G3; `held` had no non-terminal `finish` | Added everywhere; A-7 makes `held` non-terminal |
| N3 (MEDIUM) | No reason codes for a permanent rejection or an APPEND failure | `send_rejected_permanent` and `filed_copy_failed`, mapped to permissions |
| N4 (MEDIUM) and finding 2 | 2B.2 opens identity items, but POL-19 and A-6 blocked only 2B.3; the `011` P2 row was stale | POL-19 split into a default part (2B.2) and a resolution part (2B.3); A-6 moved to 2B.2; `011` updated |
| N5 (LOW to MEDIUM) and finding 10 | `reply_needs_review` permission conflict; matrix rows stale | `reply_needs_review` maps to `confirm_question_outcome`; the matrix rows corrected |
| N6 (LOW) | A3 re-checked the pause for staff messages | Automated kinds only |
| N7 (LOW) and finding 6 | Stale bead notes, the `011` P2 row and the 10.2 reference list | Bead notes replaced with the current blockers; `011` and 10.2 corrected |
| Finding 19 | An unverified RFC 9051 citation for `*` in UID sets | The citation is dropped; the client-side re-check stands on its own (B3) |
| Findings 4 and 8 (LOW parts) | The draft link and `matched_by` were absent from the field lists | Added (3.2, 3.5, B5) |

**Confirmation of 0.3.2 (2026-10-12).** The same reviewer confirmed N1 to N7 and findings 2, 5 and 10,
and found no BLOCKER or HIGH that would stop 2B.1. It left two MEDIUM clarifications (the block count is
scoped to the current attempt series; an authorized resend cancels any earlier held action) and two LOW
leftovers (an uncited RFC 9051 section in the header; this paragraph's stale wording). All four were
applied after the owner's approval as clarifications within the approved design, recorded here. The
owner approved 0.3.2 with D-27 to D-32, and 2B.1 is the only P2 task authorized.

### 10.5 2B.1 closeout decisions (owner, 2026-10-13)

The owner reviewed PR #21 at `23d4a34` and decided:

- **M6, TLS certificate tests:** deferred to the start of 2B.2, on the real SMTP and IMAP transport paths
  (verified TLS, untrusted certificate, wrong hostname, refusal of plaintext fallback when TLS is
  required). Until then TLS verification is implemented but unverified.
- **M7, real-process crash test:** required before merging PR #21, and added (TEST-P2-27).
- **M9, staff-screen visibility:** 2B.3 projects staff items into staff attention and migrates the S1
  attention events; 2B.4 builds the permissioned staff screens and resolution actions. The staff experience
  is complete before GATE-P2. Until then the records and `correspondence_health` are the inspection path.
- **Transport correction:** a failure of the write carrying the end-of-data marker is `unknown`, not a
  retryable rejection (A3 table), because `sendall`'s progress is unknowable after an error.

### 10.6 Implementation notes from 2B.2 (2026-10-13)

- IMAP collection always logs in: `CATALYST_MAIL_USER` is required for the collector (IMAP selection needs an
  authenticated session), and the connected peer is checked before LOGIN.
- `process_reply` actions are queued by collection and wait, visible, until 2B.3 registers their handler (the
  ledger never claims a kind without a handler).
- Filed copies (A4) are filed only when `CATALYST_MAIL_SENT_FOLDER` is set; start-up refuses it if it equals
  the collected folder.
- Reason codes added: `collector_blocked`, `collector_pass_failed`, `inbound_oversize`, `application_closed`,
  `mailbox_history_out_of_scope` (F, reason-to-permission table).
- The scripted IMAP and SMTP test servers run in-process on loopback; no IMAP server image was added to CI.

### 10.7 2B.2 independent review and recorded deviations (2026-10-13)

One independent `catalyst-independent-qa` review of PR #22 found 4 HIGH, 14 MEDIUM and 11 LOW, all addressed:

- C3 parses RFC 8601 resinfo entries with quoted strings and comments removed, so text inside a property
  value cannot be read as a result; conflicting DMARC entries count as unverified.
- A database failure during association aborts the pass instead of becoming `processing_error`.
- Association follows the candidate order: In-Reply-To first, then References newest first.
- The SMTP M6 tests run with real credentials configured and prove no AUTH reaches a refused server.
- Smaller fixes:
  - the collector-crash test kills inside the per-message transaction;
  - watermark and metadata-identity tests;
  - a regressed cursor becomes a recovery;
  - recovery refuses a blocked cursor;
  - LOGIN aborts count as unreachable, and network errors are classified the same way everywhere;
  - redaction unwraps hard and quoted line breaks and decodes partial percent-encoding and HTML entities;
  - MIME defects are recorded;
  - secret-bearing messages are never filed;
  - re-derivation provenance;
  - content sentinel and source-scan tests.

**Recorded deviations:**

- B0 is one command, `correspondence_mailbox`, with `bootstrap` and `recover` modes, instead of two
  commands.
- Bootstrap and recovery cannot write an application event (there is no application). The cursor keeps the
  start mode; a `from_now` bootstrap opens the `mailbox_history_out_of_scope` item; and the command logs the
  host user.

### 10.8 Implementation notes from 2B.3 (2026-10-13)

- Staff attention reads open staff items (3.8, M9, 2B.3 part). The S1 intake and confirmation code opens a
  staff item alongside each `needs_staff_attention` event (dedupe `event:<id>`). Migration correspondence
  0008 opened one for each earlier event. The events stay as history; resolving the item clears the mark.
- Reason-to-resolution allow-list (F):
  - **Identity reasons**, decision-maker only:
    - `unmatched` associate;
    - `reply_unverified` and `reply_auth_failed`: associate, dismiss or mark as spoofed;
    - `sender_mismatch`: dismiss or mark as spoofed, never associate;
    - the two S1 reasons: acknowledge.
  - **Operational reasons**, acknowledge with `resolve_exception`. `unmatched` dismissal is also
    `resolve_exception`.
- A staff association sets `trust_decision = staff_associated` for that message only, links its answerable
  questions, and queues `process_reply`. It changes no identity, recipient, adoption or stage.
- Bounces read the delivery-status report's first per-recipient `Status` and `Final-Recipient`, stored in
  `auto_markers`.
- The P3 interface is the `ReplyInterpreter` protocol in `correspondence/processing.py` (not a separate
  `interpreter.py`). `strip_quotes` provides the quote-stripped view, version 1.

### 10.9 2B.3 specialist reviews (2026-10-13)

At the owner's request, the specialist agents were used beyond QA. PR #23 was reviewed in parallel by
`catalyst-independent-qa`, `catalyst-django-architect`, `catalyst-django-data` and `catalyst-minimax-evaluation`.
None found a blocker. Applied:

- **QA:**
  - a reply whose processing fails finally becomes `processing_error` with a staff item, never silence;
  - D3 and D4 decide only a person's trusted or staff-associated reply, and need every outcome;
  - closing reasons are an allow-list;
  - the loop count restarts after staff resolve a loop, and the threshold minimum is 2;
  - bounce recipient matching fails closed;
  - staff association writes an event and records prior values;
  - a real race test of confirmation against `process_reply`;
  - wider allow-list, health and network-scan tests.
- **Architecture:** `applications` never imports `correspondence`. The S1 code opens staff items through the
  `CATALYST_ATTENTION_OPENER` seam (one creation path) and reads them through the reverse relation, with an
  import-direction test. Shared pieces moved to the leaf modules `common.py` and `messages.py`, which removes
  the hidden outbound and inbound cycle.
- **Data:**
  - indexes for the ingest Message-ID lookup and the health queries;
  - the 0008 backfill keeps each event's time, maps an unknown reason to a resolvable one, and tolerates a
    removed group.
- **P3 interface:**
  - a typed request and result (`InterpretRequest`, `QuestionProposal`, `Span` as half-open code-point offsets
    into the full derivative, `Provenance`, `InterpretUnavailable`);
  - `quoted_ranges` and a pure `validate_proposals` (no span inside quoted text or citing our own sent text,
    evidence required for `satisfied` and `partial`, no `not_addressed` on truncated text);
  - `eligible()`;
  - `derived_text_sha256`, pinned with the versions in each held `interpret_reply`;
  - `strip_quotes` no longer cuts at "From:" lines and catches wrapped attributions.
  - Approved question text is immutable: the application role cannot update it.

**Open owner decision (data review, HIGH):** whether `StaffItemResolution`, `InboundMessageLocation` and the
frozen `ApprovedMessage` columns are ADR-14 protected history. If they are, they need protection triggers
(today grants alone protect them for the application role), a `StaffItem` status transition trigger, and an
audited retention path under POL-10. This is not decided here.

Re-check round (QA and `catalyst-security-privacy`):

- A `processing_error` item uses the plain `inbound:<id>` key, so staff can resolve it; the test now
  resolves it.
- A start-up guard (`config/guards.dispatch_problems`) pins `CATALYST_ATTENTION_OPENER` and
  `CATALYST_ACTION_HANDLERS` to the Catalyst apps and refuses them from the environment.
- `validate_proposals` is total (a malformed result is a code). It binds to the stored digest, refuses any
  overlap with quoted text, caps span length and usage, and checks the model note.
- Staff association refuses a non-exception message, a non-human message, a closed target and a message
  that belongs to another application.
- `NoteRefused` is a `Refused`, and the note filter also removes zero-width characters and U+061C.

Owner questions carried forward (security review): whether staff-associated unverified mail may go to a
model provider at all, applicant text leaving to MiniMax and its retention, retention of free-text
resolution notes, and whether one decision-maker may both associate and confirm.

### 10.10 Implementation notes from 2B.4 (2026-10-13)

**Reminders (E1 to E4)**

- `correspondence/scheduling.py` is a leaf module. It holds E1 scheduling (called from the acceptance
  transaction, by server or by evidence), E3 `sync_reminders` (called from `refresh_question_status`) and the
  E4 resume reschedule.
- `correspondence/reminders.py` holds the `remind` and `escalate_unanswered` handlers. Both are automated and
  redeliverable, because their whole effect is one fenced transaction.
- **Synthetic settings (POL-06):**
  - at most 2 reminders, 3 days apart, with a 1-day minimum gap;
  - quiet hours 21:00 to 07:00 UTC;
  - a 1-hour resume grace;
  - 6 stale-watermark deferrals, 10 minutes apart.
  - Production numbers remain an owner decision (8.2).
- **Watermark.** The watermark is the oldest `complete_through_at` of all cursors. A stale-watermark deferral
  counts toward the bound. At the bound a `collector_stale` item opens and the reminder keeps waiting.
  Deferrals for quiet hours, the minimum gap or a pause are refunded.
- **Escalation.** `escalate_unanswered` ignores quiet hours and the minimum gap, because it opens a staff item
  and sends no mail.
- **Reminder template.** Reminders use a seeded synthetic `question_reminder` template. It is a draft until
  the owner approves it (D-29). A missing template or a refused render opens `reminder_refused`.

**Staff services (F, 3.3, 3.4)**

- **Pause and resume.** `pause` needs a sanitized reason of at least 10 characters. `resume` reschedules, and
  is refused with a code when nothing is paused.
- **Withdrawal.** `withdraw_question` takes reason codes from an allow-list and refuses a question that is
  already satisfied.
- **Staff messages.**
  - A staff message is previewed and then confirmed. Confirmation is refused if the confirming user is not
    the draft's author.
  - The message is sent under its own kind, `send_staff_message`, which is not automated (M5).
  - Its reconciliation (`reconcile_send`) is not automated, so a pause never holds the reconciliation of an
    unknown staff send (the deviation first recorded here was reversed in 10.11; corrected 2026-10-23, `9kg.41`).
- The new permissions (`withdraw_question`, `send_staff_message`, `pause_automation` and `resume_automation`)
  go to operators and decision-makers, following the matrix.
- Owner question: whether an operator may resume after an automatic pause (`hard_bounce` or
  `loop_threshold`), or only a decision-maker.

**Spike result (M9).** Admin actions do not fit `ReadOnlyAdminMixin`:

- they cannot collect a note, per-question outcomes, a target or a body;
- a changelist action receives a queryset, which is the bulk path S1 refuses;
- enabling them would weaken the S1 tests.

The admin therefore stays read-only. The staff screens are a focused view module, `correspondence/staff_views.py`,
mounted at `/staff/p2/` before the admin. Its rules:

- a GET page needs a correspondence permission;
- each action is a POST that names one object, is CSRF-checked and calls one named service;
- a superuser is refused;
- a refusal shows its code;
- pages are never cached, and nothing writes the admin log.

Untrusted text is autoescaped and shown through the `visible` filter, which turns control and format
characters into markers. The reply confirmation submits the digest of the derivative it showed
(`confirm_question_outcome(expected_digest=)`). A link from the admin dossier to these screens is deferred;
for now the screens link to the dossier.

**Monitoring.** `reminder_health` covers G4, G5 and G6 for reminders; `mail_behaviour_health` covers G7. Both
are reported by `correspondence_health`.

### 10.11 2B.4 specialist reviews (2026-10-13)

PR #24 was reviewed by `catalyst-independent-qa`, `catalyst-security-privacy`, `catalyst-workflow-correspondence`,
`catalyst-django-operator` and `catalyst-release-operations`. The operator review raised one blocker (no screen
offered template approval). Applied:

**Reminders.**

- The minimum gap counts every automated message already frozen for the application, so reminders due together
  never leave in a burst.
- A frozen reminder still waiting to be sent follows its question: it is cancelled when the question is
  satisfied and deferred while a reply is pending.
- A reminder released after a reply waits at least the resume grace.
- A configuration problem (no approved template, no verified address) defers the reminder with a staff item
  instead of ending the chain. A chain ended by a defect opens `reminder_failed`.
- A cursor that never completed a pass makes the watermark stale.
- Escalations take no rank in the resume spread, and queued reminder mails are spread with the reminders.
- Deviation reversed: `reconcile_send` is no longer automated (it sends nothing), so a pause never holds the
  reconciliation of an unknown staff send. This amends 3.7, which listed it among the automated kinds.

**Staff services.**

- The pause reason, the resume note and a pause attempted while paused are kept in the append-only history.
- A staff-message preview expires after `CATALYST_STAFF_DRAFT_TTL_SECONDS` (30 minutes).
- The content checks use the inbound redaction decoding for links, and the character categories of the display
  filter for controls.
- Template approval takes the digest of the version shown.

**Screens.**

- Each page names the permissions whose holders need it: a template owner reads only templates, never
  applicant mail.
- Added pages for templates (read and approve), for applications (list, find, filter paused or with a proposed
  question) and for mail collection state on the queue.
- The item page shows the message evidence (trust, authentication, sender match, a link to the text) or the
  send (recipient, subject, disposition, attempts). Decisions are offered per reason; a permanent rejection
  offers no resend.
- A malformed target is refused with a code. A refused preview keeps the typed text. Withdrawal needs a chosen
  reason. The queue shows its count, age and the 200 limit.
- The `visible` filter also marks non-ASCII spaces and blank fillers.

**Monitoring.**

- G4 ignores closed applications and a reminder still in flight, counts only completed escalations, and
  reports a chain ended by a failed action separately (`broken_reminder_chain`).
- G7 is windowed (hard bounces, inbound growth) and counts automatic mail matched to no application.
- `correspondence_health` exits 2 when the check itself fails, never 1, and stamps `generated_at`.

**Not changed, owner questions:**

- who may read derivative text beyond the resolving roles (POL-10);
- whether an operator may resume after an automatic pause;
- whether staff mail may go to an address that hard-bounced;
- retention of unconfirmed drafts and free-text notes;
- alert thresholds and ages for G2, G5 and G7 (P6);
- a staff re-arm for a broken reminder chain.

Recorded: in P2 each approval creates one message per question (a revision carries the same questions), so a
message mixing a withdrawn and a live question cannot arise yet.

### 10.12a The read-only Sent-folder evidence source and the production mail-host allow-list (9kg.49, 2026-10-23)

Found by the correspondence review of 2026-10-23 (PL-A, `029` section 5.2): no Sent-folder reader existed, the guards
refused any evidence source outside the test environment, and the mail-host guard admitted only loopback, so the live
reconcile of an uncertain send could not run. Built in PL batch item 4 and hardened after the PR #89 reviews:

- **`correspondence/sent_reader.py`, `SentFolderSource`:** the production value of `CATALYST_SEND_EVIDENCE_SOURCE`.
  It reads `CATALYST_MAIL_SENT_FOLDER` through `ReadOnlyMailbox`, a view of the TLS-only IMAP client without
  `append`: EXAMINE, UID SEARCH, UID FETCH (sizes, dates, BODY.PEEK) and LOGOUT after CAPABILITY and LOGIN; the test
  asserts the command set is a subset of those six, so COPY, MOVE, STORE, APPEND, DELETE, RENAME and CREATE are
  covered. `find(message_id)` serves the ordinary A5 reconciliation; `within(since)` enumerates the folder by
  internal date (IMAP `SINCE`, a calendar day, so the read starts a day early and the caller drops copies before the
  window by their date). More than `CATALYST_MAIL_SENT_SCAN_LIMIT` copies is `scan_limit_exceeded`, never a silent
  truncation; a copy above `CATALYST_MAIL_MAX_MESSAGE_BYTES` is not fetched, and any copy that cannot be fetched or
  parsed makes the read `incomplete`; both block a post-restore lift. Every copy becomes an `Evidence` record of
  origin `provider` with its Message-ID, `To` address (parsed, display-name forms included), canonical content digest,
  internal date and whether it carries `X-Catalyst-Filed-Copy`; the A5 admissibility rule is unchanged, so Catalyst's
  own filed copy is never evidence, and absence of a copy is never "not sent".
- **`ReconcileSend`:** a source that cannot be read is not "no evidence": the action ends with
  `evidence_unreadable:<code>`, the event `send_evidence_unreadable` and the `send_outcome_unknown` item at once, and
  nothing is checked again blindly. Checks that find no admissible copy end as before, now with the event
  `send_evidence_absent` (the check number and the copies read). Records carry codes only.
- **The allow-list** (`config.guards`): `CATALYST_MAIL_ALLOWED_HOSTS` is an exact list of lower-case host names
  (every label plain, the last one with a letter, never an address), required and non-empty in a live environment
  (`LIVE_ENVIRONMENTS`, today `production`), refused in test, staging and development, which never leave loopback
  (or the named test host in test). The start-up check asks only whether the configured host is listed; which
  process may use it is decided at use time from the **process kind declared in code** (`config.runtime`, never only
  an environment variable): `web` and `worker` may send and read, the owner-run `reconcile` kind (declared by
  `catalyst_post_restore`, which refuses the web and worker roles) may read the Sent folder only and never send; a
  management process neither. The connected peer must be a global unicast address, and a replaced trust store
  (`CATALYST_MAIL_CA_FILE`) is refused. Admitting `production` to `ALLOWED_ENVIRONMENTS` is the release decision
  (`029` section 13, `9kg.31.4`): the rule changes one constant, not the guard.
- **The mailbox identity** (security review of PR #89): in a live environment the rule is never opt-in.
  `CATALYST_MAIL_USER_SHA256` pins the one v2 mailbox login (`CATALYST_MAIL_USER` must hash to it, re-checked in
  `transport.send` and `MailboxClient.__init__` before any credential is sent) and `CATALYST_MAIL_DENIED_USER_SHA256`
  must list the first-generation mailbox; both hold SHA-256 hex digests only, and a denied login refuses to start in
  every environment. **The digest values are private: never pasted into a pull request, a document or a log.**
  There is no second poller or reader of the first-generation mailbox.
- **RD-1 (the owner's decision; the default is built):** the post-restore Sent read runs as the `reconcile` kind on
  the restore service, admitted for IMAP only. The alternative is a worker job with the lift gated on it. The
  production restore service then needs the mailbox password secret mounted; today's staging has no mail secret.
- **Still the canary's finding (8.3):** whether the provider's Sent copies are created only on acceptance, which
  decides whether A5 has admissible evidence live. Until then the reader is proven against the fake only.
- **Evidence:** `tests/test_inbound.py` and `tests/test_guards.py` (the `9kg_49` tests, mapped under
  `P6_SUPPORTING`).

### 10.12 GATE-P2 acceptance closeout (owner direction, 2026-10-13)

The owner reviewed `e049870` and held GATE-P2 sign-off for one bounded closeout. The concern: a mapped test
passing is not the same as the requirement being proven. This section records what the closeout added and
how every case that the 2C audit called partial is now settled. It also records the eight policy directions.
The owner signs GATE-P2; this section does not.

**Proofs added.**

- **TEST-P2-08.** One application has two outstanding questions, each in its own message. Staff confirm a
  partial answer, then a full answer, to the first question only. Only the first question changes; the
  second question and its reminder stay as they were, and nothing applies application-wide.
- **TEST-P2-15.** The scripted IMAP server now records every fetch request and the bytes it returned. For an
  oversized message, the collector asked for the size and the headers only. It never sent a full-body fetch,
  and fewer than 4 kB crossed the boundary for a 50 kB message. The cap is the whole-message size; no
  attachment-specific limit is claimed.
- **Reminder races.** Four tests run on separate connections. An application-role session holds the
  application row, and reply ingestion and the reminder or send check queue behind it in a chosen order.
  No two coordinated sessions hold the same lock, and the waits are bounded.

  | Ordering | Outcome |
  |---|---|
  | The reply commits before the reminder check | No reminder is sent; the reminder action is held |
  | The reminder check commits first | The reminder is authorized once; its frozen send then defers while the reply is pending and is cancelled when the question is satisfied |
  | The reply commits before a frozen send's check | Nothing is sent |
  | A frozen send passes its check first | That one mail is sent; the next reminder exists but is held |

  In every ordering there is no deadlock, no duplicate scheduling and no false outcome.
- **TEST-P2-45.** A confirmed staff message, with the host changed to a non-test host after start-up, is
  refused before any socket opens: no connection, no AUTH, MAIL or DATA. The message becomes
  `transport_blocked` with a staff item. No real host was contacted.
- **Smaller assertions:**
  - the projection never resets attempt counts (TEST-P2-30);
  - drafts, resolutions and locations are insert-only for the application role (TEST-P2-39).

**Disposition of every case the 2C audit called partial.**

| Case | Disposition |
|---|---|
| 05 | **Closed.** The ledger skips every automated kind of a paused subject (`test_worker::test_s1_19_*`). P2 kinds are covered by `test_p2_05_*`. Reconciliation is deliberately not automated (10.11). |
| 08 | **Closed** by the two-question proof above. |
| 09 | **Closed within scope.** P2 never interprets content, so any reply, including an acknowledgement, only makes the question `reply_pending` until staff decide; `not_addressed` returns it to `open` (`test_p2_08_09_*`). Automatic content interpretation is P3. |
| 12, 20, 22, 48, 49, 51 | **Closed by mapping** the tests the audit named. |
| 15 | **Closed** by the boundary proof above. |
| 18, 36, 46, 50, 54 | **Closed** by the tests added in 2C (AAR `017` §4). |
| 30, 35 | **Closed by mapping**, plus the attempt-count assertion. |
| 39, 47 | **Closed** by the schema scan (no binary or raw-message column) and the insert-only grant assertions. |
| 40 | **Closed by mapping** the provider-variable and external-network tests. |
| 41 | **Approved scope boundary.** P2 proves each measurement and anomaly query. Production threshold values are P6 and POL-16. |
| 42, 52 | **Closed:** a negative permission test for every screen action, per-model admin read-only (`test_staff::test_every_registered_admin_*`), the dossier link and the operator journey. |
| 44 | **Closed** for derivation version 1. A golden case is required with every version bump. |
| 45 | **Closed, with an approved scope boundary.** Refusal is proven before any connection. No real infrastructure is contacted to prove the prohibition. |
| Reminder races | **Closed** by the four separate-connection tests above. |

**Still open (not claimed):**

- No screen lets staff author a question. In the journey, the question is created as test setup, as P3 or
  a future staff authoring screen would create it.
- Multi-question messages do not exist in P2, by design.
- No attachment-specific size guarantee is made.

**Policy directions (owner, 2026-10-13).**

| Direction | Current implementation | Conforms? | Correction | Gate it blocks |
|---|---|---|---|---|
| **Correspondence evidence.** Extend the append-only protections to immutable audit records and frozen identity and content fields. Do not freeze operational state or drafts. | **9kg.1 (correspondence migration 0015):** triggers refuse, for every role, an update or delete of a staff item resolution, an inbound message location or an approved message's question link; any change to an approved message other than its disposition, and its deletion; and any change to an approved or retired template version other than approved to retired, and its deletion; a template version is always inserted as a draft. All five tables refuse truncation. Drafts (staff message drafts, draft template versions) and delivery state (dispositions, outbound messages) stay updatable. | Yes | None. Limits: the owner role can disable a trigger it owns, and a superuser bypasses all of them, so these are append-only protections, not tamper-proofing (the ADR-14 pattern). No ordinary role, the retention role included, can erase these rows: a retention or erasure path is a POL-10 owner decision. The follow-up, freezing inbound message provenance and the outbound and reply-link identity columns, is 9kg.5 (migration 0017, section 10.13). | Real applicant data (staging and pilot) |
| **Mail-text readers.** Correspondence operators and decision-makers may read the sanitized text their work needs. Template-owner, collector-restart, pause-only or generic staff authority alone does not grant it. | The reply page needs `confirm_question_outcome`, `resolve_exception` or `resolve_identity_exception` (operator and decision-maker permissions). A template owner reaches only template pages. Pause-only or restart-only users reach no reply text; the item page shows the sender address and codes, not the body. | Yes | None in P2 | None |
| **Automatic pauses.** A routine resume does not clear a system safety pause; that needs decision-maker review, a reason, and the cause addressed. | **9kg.2:** `resume()` still needs `resume_automation`. A system safety pause (actor `system...`: a hard bounce, the loop threshold, or an agreement declined, expired or cancelled at the provider) also needs `decide_uncertain_send` (decision-maker) and a reason of at least 10 characters. Every pause is refused (`pause_cause_open`) while one of those causes' staff items is still open, whoever paused first, so a staff resume cannot clear a system cause that arrived behind it. Resuming never resolves an identity, delivery or agreement-integrity item; each keeps its own path. The three agreement causes are settled on the agreements screen and then recorded by the correspondence decision-maker with a reason (`agreement_decided`; the role decided by the owner, D-46). The resume event records who, the reason and whether the pause was a system pause; a refused resume is recorded too (`automation_resume_refused`, with the code and the open causes). The staff screen shows the resume form for a system pause only to a decision-maker, with a required reason. Limit at the time: the pause row was protected in code only (the application role may delete it). Since `9kg.6` (section 10.15) the row is cleared only together with a same-transaction staff resume event; authorization and the open-cause checks remain in code. | Yes | None | Real mail |
| **Hard bounces.** No automated or staff mail goes to an address with an unresolved hard bounce; resuming or revising is no bypass. | **9kg.3:** an open `hard_bounce` item holds every P2 send in the handler, whatever its kind (questions, reminders, staff messages and resends), and the S1 verification send. A send with an exchange already in flight still goes to reconciliation first, which sends nothing. The send stays queued with its attempt refunded and looks again hourly (`CATALYST_HARD_BOUNCE_RECHECK_SECONDS`). Confirming a staff message, and a resend or revision decision, are refused up front (`hard_bounce_open`). Documenso distribution uses the same rule (`correspondence.staff_items.hard_bounce_open`) but is protective rather than held: a refused distribution fails to a staff item, and after the bounce is resolved staff cancel and reissue that agreement on the agreements screen (no automatic resume). The item is no longer acknowledge-only: only `address_usable_again`, needing `decide_uncertain_send` (decision-maker) and a reason of at least 10 characters, resolves it. The resolution is recorded and releases the held sends at once; each re-checks everything under lock. The automation pause the bounce set is cleared separately (9kg.2). | Yes | None | Real mail |
| **Retention.** Drafts, notes, approved messages and audit records each get their own POL-10 treatment. No period is invented and nothing is deleted now. | Nothing is deleted. Drafts are insert-only and kept; notes are kept. | Yes, for synthetic use | The POL-10 approval | Real-data ingestion |
| **Association and confirmation.** The same qualified person may do both, recorded separately. Identity conflicts stay elevated; association alone does not establish trust. | A decision-maker holds both permissions. Association writes its resolution record and event, and confirmation writes its own. Associating unverified or auth-failed mail needs `resolve_identity_exception`. A sender mismatch cannot be associated. Association marks the message `staff_associated`, which lets it be confirmed. | Yes, with a note: that elevated resolution is how an unverified reply becomes confirmable | None in P2 | None |
| **MiniMax.** No real applicant correspondence goes to a model. | No model client is imported, no handler exists for `interpret_reply`, and no key is read (TEST-P2-43). | Yes | P3 specifies minimized inputs, allowed use, provider handling, budgets, provenance and authority. | Live model use (P3) |
| **Alerts.** Production thresholds are a P6 decision. | Synthetic settings. `correspondence_health` exits 1 on an anomaly and 2 on a failed check. | Yes | None in P2 | P6 |

**Authority.** The 2026-10-13 instruction to build autonomously named no phase limit. The owner's closeout
direction of the same day limits it to P2: it does not authorize P3, a release or a deployment.

**Review policy.** A later task gets one primary independent reviewer, plus one narrowly scoped specialist
only when the change crosses a specific security, data or integration boundary. The full specialist roster
is not a standing requirement.

**Test cost.** The full suite now takes about 11.5 minutes locally and about 7.5 minutes in CI. Use focused
tests while editing and the full suite on the final candidate. The slowest tests are named in the closeout
pull request.

**Sign-off.** The owner accepted this closeout and signed off GATE-P2 for synthetic P2 on 2026-10-13 (D-33 in
`011`). The excluded scope and the before-real-use conditions above stand.

### 10.13 Provenance freezes for every role (9kg.5, 2026-10-23)

**Finding (security review of PR #44, MEDIUM 3).** An inbound message's provenance and the identity of an outbound
attempt and a reply link were fixed only by the application role's column grants: the owner, or any role granted
UPDATE later, could rewrite them.

**Built (correspondence migration 0017, the 0015 pattern; internal-launch batch item 6).** Three `BEFORE UPDATE OR
DELETE` triggers refuse the change for every role, with a tuple compare of the frozen columns; `DELETE` is refused and
`catalyst_no_truncate` refuses `TRUNCATE`, as in 0015.

| Table | Frozen at insert | Still updatable |
|---|---|---|
| `InboundMessage` | `public_id`, `mailbox_ref`, the headers (`message_id_header`, `in_reply_to`, `references`, `from_address`, `from_normalized`, `auto_markers`, `date_header`, `internal_date`), `received_at`, `size`, `original_sha256`, `attachments`, `is_derivative` | status, classification, exception reason, processed time, application and approved-message links, trust (`auth_evidence`, `trust_decision`, `from_matches_verified_address`, `identity_state`) and the derivative columns re-derivation writes |
| `OutboundMessage` | application, pending action, attempt number, template key and version, recipient, approved message, attempt series, rendered digest; `message_id` is set once (empty may be filled, a value never changes) | status, protocol phase, reply code, `sent_at`, `server_accepted_at`, filed-copy state, `created_at` (the owner ages an attempt in tests; it is not identity) |
| `QuestionReplyLink` | question, inbound message | state, outcome, actor, `updated_at` |

**The audited retention path, kept open for erasure.** The freeze must never block the erasure `9kg.32` builds under
POL-10 (`029` section 6.2). The inbound and outbound functions therefore carry one branch, the ADR-14 retention
exception of `applications` migration 0002: a session whose login is a member of the retention role and that has set
`catalyst.retention_reason` (ten characters or more) may change the personal columns only (inbound: `from_address`,
`from_normalized`, `message_id_header`, `in_reply_to`, `references`, `attachments`; outbound: `recipient`), and the
trigger records the change in `applications_retentionaudit` with a digest of the row before the change (application
`0` when the message was never associated). The fixed provenance stays frozen on that path too, and deletion is
refused to it: erasure anonymizes. Nothing is granted to the retention role by this migration. The branch is checked
on `session_user`, so `9kg.32`'s security-definer erase function (EXECUTE for the retention role only) passes it while
the update runs as the owner; `9kg.32` may replace the reason-and-audit condition with its erasure-audit row and the
tombstone allow-list, and the frozen tuples stay. The two functions that write the audit row are `SECURITY DEFINER`
owned by the owner, with a fixed `search_path` and no public EXECUTE; the reply-link function writes nothing.

**Tests (`tests/test_provenance_freezes.py`).** Every frozen column refuses an update by the application role (its
grants) and by the owner (the trigger); the updatable columns still update through both; no role deletes or truncates,
the retention role with a reason included; the retention path anonymizes the personal columns through a stand-in
security-definer function (with and without an application), writes the audit row, refuses the owner, refuses without a
reason, and refuses a fixed column even with one; `message_id` is set once; the migration reverses and reapplies with
the rows kept. The harness lists the six triggers in its expected set (`tests/conftest.py`), and the role suite counts
them (`tests/test_db_roles.py`).

**Not decided here (named in the same review, owner decisions):** whether a `StaffMessageDraft` is frozen once an
approved message links to it, and whether a disposition may leave a terminal state. Both stay as 9kg.1 left them.

**Limits.** As in 0015: the owner can disable or drop a trigger it owns, and a superuser bypasses them.

### 10.14 The staff verification resend (9kg.50, 2026-10-23)

The wait "verification sent, unconfirmed" had no staff recovery (`029` section 5.2): a failed send was not retried
and only a new submission issued a new link. Built, on the correspondence application screen:

- `staff_actions.resend_verification`, under `send_staff_message` (a staff-authorized send, the matrix in F), one
  locked transaction: the application must be open with contact unverified, no hard bounce open (9kg.3), and the
  resends under `CATALYST_VERIFICATION_RESEND_LIMIT` (3, a synthetic default until POL-02's values, `211.7.7`).
- The resend goes through intake's own path (`applications.services.reissue_challenge`): the active challenge is
  superseded and a new one is issued with the same lifetime, the same `send_verification` action and the same
  message, so the applicant sees exactly what issuance sends; the superseded link answers "no longer valid" as it
  always did. The event `verification_resent` carries the resend number and the note only, never a challenge
  identifier or link (S1-T7).
- The screen shows the resends used and offers the action only while it could do anything; a refusal shows its
  code; a holder of another correspondence permission reaches the page but the act is refused.

Tests: `tests/test_hold_and_resend.py`. The dossier's next-step text now names this path.

### 10.15 The pause-row guard (`9kg.6`, 2026-10-23)

The security review of PR #46 (HIGH 2) noted that the application role holds DELETE on `workflow_automationpause`,
so the 9kg.2 decision-maker and cause rules were enforced in code only. Workflow migration `0005` adds the guard in
the ADR-14 pattern, for every role: a deferred constraint trigger refuses, at commit, the DELETE of an application's
pause unless the same top-level transaction inserted an `automation_resumed` history event for that application
(pauses are keyed by the application's `public_ref`, events by its id, so the guard joins the two), recorded by
staff with a non-empty actor reference; for a system pause (actor `system` or `system:...`) that event must also
carry a resume note of at least ten characters, the service's own minimum. Only the restore hold's `system` rows
are exempt; a pause of any other subject type has no application to join and cannot be cleared at all (fail
closed). The guard binds the shape, not the authority: who may resume and whether a cause is still open remain the
service's checks in code, and the application role can insert the event itself. "Same transaction" is a new `created_txid` column on `ApplicationEvent` (applications migration
`0006`), always the database's own value through a BEFORE INSERT trigger, as the decision backstop of `018` does;
it holds inside a savepoint, where `xmin` would not. An UPDATE of an application's pause is refused outright (a pause
is created and resumed, never changed) and TRUNCATE by the shared no-truncate function; the restore hold keeps its
own rule (workflow `0004`). `staff_actions.resume()` already records that event in its transaction, so the
supported path is unchanged; tests that stepped past a pause as setup now use `tests.support.resume_pauses`, which
records the same shape. Tests (`tests/test_pause_guard.py`, through real connections as the application and owner
roles): a bare DELETE or UPDATE by the application role is refused, the owner is refused the same way, TRUNCATE is
refused for every role, a staff pause clears only with a staff event carrying an actor reference, a system pause
only with a note of ten characters or more as well, in the same transaction (an earlier transaction's event, the
migration's included, and an event whose savepoint was rolled back do not count), an unknown subject type is
guarded, the marker survives a savepoint, cannot be supplied and reaches no read surface, the supported resume
path clears the pause and work resumes, and the restore hold is untouched. Every `catalyst_*` function is checked
from the catalog for its owner, search path and the application role's lack of EXECUTE. Stated limitation, as for
every ADR-14 guard: the owner can disable the trigger, a superuser bypasses it, and a compromised application role can
insert the event itself; the guard binds code paths and stray writes.

### 10.16 The intake data notice and the invitation mail as templates (9kg.52, 2026-10-23)

Two templates join the register by correspondence migration 0018, seeded as unapproved synthetic placeholders:
`data_notice` (no variables; the one-paragraph notice of `030` Q8: what is collected, who sees it, that no model
reads it and no link is fetched, how to withdraw and how to request erasure, with bracketed slots where counsel must
state the recipients, the withdrawal route and the erasure route) and `invitation` (one variable, `notice`; the mail
the owner sends by hand to an invited member). The owner approves each on the template screen like every other
template (A1, D-29), through the same digest guard; approving one does not approve the other. The renderer is
unchanged: only an approved version renders. `correspondence.notices` reads and renders the templates and is reached
from `applications.notices` only through the `CATALYST_NOTICE_SOURCE` seam, so `applications` never imports this app
(`003` ADR-01; `tests/test_processing.py` enforces it). The notice is rendered into the invitation as a value and is
not re-expanded.

**What may be served where.** In the draft environments (`config.guards.DRAFT_WORDING_ENVIRONMENTS`: development,
test, staging) the newest draft renders with a visible marker, substituted with the standard library, never the
template engine. Anywhere else only an approved version that is not `synthetic` is served: an approved placeholder
is refused (`<key>_synthetic`), and when the newest approved-or-retired version is retired nothing older is served in
its place (`<key>_retired`). A broken placeholder is a refusal with a reason code, never an error page.

**How real wording is authored.** As every template version is (`question_request` in 0004, the reminder in 0012, the
welcome in 0016, these two in 0018): a correspondence **data migration** adds a new draft version, with
`synthetic=False`, its digest computed as in section 3.2, and the owner approves it on the template screen. No command
and no screen writes template text, and an approved version is never edited. The design record is `029` section 17.2.

### 10.17 An expired only link opens a staff item (9kg.66, 2026-10-24)

The screen walkthrough (`029` appendix B, GAP 1) found that an unverified application whose only verification link
expires prompts nothing: the applicant holds no working link and staff are not told. Built:

- **The sweep.** `verification_expiry_sweep` (`correspondence.verification`) is a recurring ledger action like the
  session clean-up: each pass opens the items, then queues its successor `CATALYST_VERIFICATION_SWEEP_SECONDS` (900,
  fixed in code) later, and the chain survives a final failure. `manage.py schedule_verification_sweep` (idempotent)
  starts it at deployment, after migrate, beside `schedule_session_cleanup` (`deploy/staging/compose.yaml`); outside
  the local environments `catalyst_health` reports `verification.verification_sweep_unscheduled` when no pass is
  queued or running. It sends nothing and is not automation, so an application's pause does not hold it; the restore
  hold stops it like every action.
- **What opens.** For an open application with contact unverified whose active challenge (unused, not superseded;
  there is at most one, since issuance supersedes the previous) has expired by the database clock, one
  `verification_expired` item keyed `challenge:<challenge>`, re-checked with the application locked. **Once per
  challenge:** an item for that challenge, open or resolved, is never opened again, so a re-run, a redelivered pass or
  an acknowledged item adds nothing; a resent link that also expires is a new challenge and a new item. Items carry
  identifiers and the reason code only.
- **How it closes.** The staff resend (section 10.14) resolves the application's open `verification_expired` item in
  its own transaction, with the resolution code `verification_resent`, the staff member as the actor and the resend
  number in the effects. The item page states the reason in plain words and links the application's correspondence
  screen, where the resend is. Each pass first closes, as the system (code `verification_superseded`, with the
  application locked), every open item whose application has since been verified or has left the open stages, so a
  confirmation through a new submission or a closure ends the item without staff (review of PR #97). A holder of
  `resolve_exception` may also acknowledge it.
- **The first pass after deployment** opens an item for every open, unverified application whose link has already
  expired (200 per pass, oldest expiry first, the rest on the next passes); once per challenge is intended, so this
  backlog appears once.
- **Chosen over** a per-challenge check queued by intake or by the send: that adds a second action to the S1 path and
  changes the accepted GATE-S1 histories and counts; the sweep leaves the S1 path exactly as accepted.

Tests: `tests/test_hold_and_resend.py` (`9kg.66` in `tests/acceptance.py`).

### 10.18 Plain labels on the resolution buttons (9kg.67, 2026-10-24)

The walkthrough (`029` appendix B, GAP 5) found the staff item page's buttons showing internal codes such as
`address_usable_again`. Each resolution code and the acknowledgement now has a plain-English label
(`processing.RESOLUTION_LABELS`), and so does each send decision (`staff_actions.DECISION_LABELS`). The label is the
button text only: the code stays the submitted value, the allow-list key in `resolve_exception`, the resolution
record and the audit trail, so nothing a service checks or records changes. Chose labels in code beside the
allow-lists over labels in the template because the allow-list and its words then change together, and a test
fails when a new code has no label. Tests: `tests/test_staff_screens.py` (`9kg.67` in `tests/acceptance.py`): every
code has a label that is not itself a code; on the item page no button text equals a raw code and each code is the
value of a form whose button shows its label; the earlier tests that matched button text now match the submitted
values.

### 10.19 The decline notice on the outbound path (oc4.11, 2026-10-24)

A recorded decline now tells the applicant. Before this, `assessments.decisions` created a held `send_decline`
action that nothing ran (`029` section 5.2). The design reuses the outbound path of section 4 A and the template
pattern of section 10.16; nothing new is added to the sender itself beyond one narrow exception.

**The kind and the template.** Correspondence migration 0019 adds the `decline` kind of `ApprovedMessage` (the kind
CHECK widened by one value, recorded as expand-safe in `config.release`) and seeds the `decline_notice` template as an
unapproved synthetic placeholder: one variable, `display_name`, and bracketed slots where counsel must state whether a
reason may be requested, whether a new request may be made, what is kept and how to request erasure, and whether
replies are read. It makes no promise and no legal claim. Because the only value rendered into it is the display
name, no reason code, reason text, per-criterion rationale, policy reference or model output can reach the applicant.
Real wording arrives as every template version does: a data migration adds a new draft with `synthetic=False` and the
owner approves it on the template screen (`211.7.4`, `211.7.7`).

**Who freezes it.** `assessments.decline.SendDecline` (kind `send_decline`, automated, redeliverable: one fenced
transaction that freezes and queues, so nothing leaves the process there). It lives in `assessments` because it reads
the decision, and `correspondence` never imports a later app (`003` ADR-01). It reads the wording through
`applications.notices.wording`, the same function as the data notice: in the draft environments the newest draft with
its visible marker; anywhere else only an approved, non-synthetic, unretired version. It freezes an `ApprovedMessage`
(`decline`, authority `system_policy`, the exact template version, the frozen subject and body and their canonical
digest) and queues `send_message` for it, then records `decline_notice_queued` with the template version, its digest
and whether it was a draft.

**Sent like any other message, with one exception.** `SendMessage` re-checks everything as in A3 and records each
outcome class as before. Its check skips a message for a terminal stage, except that `declined_notice` lets exactly
the `decline` kind through to an application that is `declined` (never one that is withdrawn or closed). So an unknown
outcome reconciles and reaches `send_outcome_unknown`; temporary rejections end at `retries_exhausted`; a channel
fault at `smtp_transport_blocked`; a permanent rejection at `send_rejected_permanent`; and the decision-maker settles
each with the usual `decide_uncertain_send`, which already ignores the stage. A resend keeps the same Message-ID; a
revision is refused for this kind (`revision_not_supported_for_this_kind`), so the remedy after a permanent rejection
is to abandon it and tell the applicant another way. The hard-bounce block (9kg.3) and the automation pause apply as
for every automated send.

**A bounce.** Reply processing never runs for a terminal application, so a bounce of the notice would otherwise appear
only as `application_closed`. Association (C0) now opens `decline_not_notified` first when a delivery report matched
to a decline notice carries anything but a delayed status: a permanent one (5.x.x), or none at all, which is treated
as a possible failure; then the closed-application exception as before. Only a delayed report (4.x.x) is not a
failure and gets only the exception. The decision-maker resolves `decline_not_notified` with a
note (`decide_uncertain_send`, the reason-to-permission table of section F); nothing is resent from that item.

**When it is not sent.** Each is a recorded outcome, never silence:

- *Withheld:* the decision form offers "send" (the default) or "withhold"; withholding needs a reason of at least ten
  characters, is recorded in the decision (`decision_inputs["decline_notice"]`) with a `decline_notice_withheld`
  event, and queues nothing. When withholding is appropriate is the owner's rule; the code records the choice.
- *Wording not usable here* (unapproved, synthetic or retired in a live environment, missing anywhere) or *no verified
  address:* the action looks again every `CATALYST_DECLINE_NOTICE_RECHECK_SECONDS` (code-fixed, 900) with its attempt
  refunded, and one `decline_notice_refused` item says why; it is resolved by the system when the notice is queued,
  and one acknowledged by staff reopens at the next look while the cause stays.
  The health report's decision section names `decline_notice_unapproved` once decisions can be recorded.
- *A member on file* (`030` Q8): the decision already refuses a decline; a record made after the decline cancels the
  action with its own `decline_notice_member_on_file` item, and a record made after the freeze makes the send skip
  as `member_on_file`.
- *After a restore:* a `send_decline` that was queued, running or held at the backup is an outward kind
  (`config.post_restore.OUTWARD_REDELIVERABLE`), so the review makes it uncertain with a
  `restore_effect_outward_action` item and it never runs again by itself; the owner compares it with the Sent folder
  (`--outward-checked`) and the decision-maker decides on the item. The accepted remedy is that staff decision, never
  an automatic re-queue. Separately, while a `restore_effect_unknown_send` item is open for the application, a live
  `send_decline` waits instead of freezing. Together these keep a restore from sending a second notice by itself.
- *Held before this release:* migration 0019 cancels every held `send_decline` (`held_before_the_decline_handler`);
  one released by hand is cancelled by the handler, because its decision made no choice about the notice
  (`decided_before_the_decline_notice`).

**Exactly one.** The action's key is `send_decline:<application>` and the handler finds an existing `decline` message
before freezing another (`already_queued`), so a redelivered action never makes a second notice. Tests:
`tests/test_decline_notice.py` (the `oc4.11` group in `tests/acceptance.py`). The design record is `029` section 17.3.
