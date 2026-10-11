# P2 Correspondence Specification (handoff 2A)

| Field | Value |
|---|---|
| Document | `016-AT-DSGN-p2-correspondence-specification` |
| Version | 0.2.0 (independent security and privacy review applied, section 10) |
| Status | **PROPOSED.** Handoff 2A of phase P2 (`011` section 7: specify and decide; no application code). Nothing here is built, approved or configured. Every choice marked PROPOSED waits for the owner decision named beside it (section 8). |
| Owner | Jeremy Longshore |
| Date | 2026-10-11 |
| Epic | P2, "Run the applicant correspondence loop: outbound policy, inbox correlation, reminders, stop rules and human takeover" (`catalyst-v2-7hu`); this task is `catalyst-v2-7hu.1` |
| Builds on | `004` J-06 to J-09 (journey semantics), `005` S1.4 (ledger rules), `003` ADR-01, ADR-03, ADR-13, ADR-15, `002` REQ-005, REQ-012, REQ-013, REQ-014, REQ-034, and the merged first-slice code |
| Classification | Public; synthetic data only (`example.test` addresses); no provider, mailbox or credential is named |

> **Status: PRELIMINARY, subject to review.** This document specifies P2 in enough detail that an
> engineer can implement each task without guessing. It does not authorize code, real mail, MXroute,
> the VPS or any provider. The P2 task beads (section 9) start only after the owner decisions they
> depend on are recorded in `011` section 4.

## 1. Scope, boundaries and the P2/P3 line

**P2 is deterministic.** It covers:

- sending approved, versioned messages to the verified address only;
- collecting inbound mail from a mailbox over IMAP and persisting it durably;
- authenticating replies as far as the evidence allows;
- correlating replies with outbound messages and the questions they carried;
- classifying automatic messages and bounces;
- reminders with suppression and stop rules;
- staff takeover and resolution.

**Judgement is not automated in P2.** A reply from a person that may answer a question is routed to
staff confirmation. In parallel, a held `interpret_reply` action is created for P3. No reply satisfies a
question by itself, and no code path in P2 calls a model.

**The P3 interface is typed but not implemented.** It is a Python protocol, `ReplyInterpreter`, in
`correspondence/interpreter.py`. It imports neither PydanticAI nor any model client.

- **Input:** the inbound message's public id, the ids of the related open questions, and the message's
  quote-stripped and full text (both untrusted data).
- **Output, per question:** one of `satisfied`, `partial` or `not_addressed`, plus cited spans (offsets
  into the stored text). P3 validates deterministically that every cited span exists, and that a
  question requiring evidence has an attachment or link actually present (`004` J-07 step 2).
- **While the staff-confirmation default holds** (`004` J-07; POL-04, POL-06), even a P3 outcome is a
  proposal that staff confirm.

**Out of scope:**

- Redis, Celery, Temporal, a second database or a second job engine (the existing `PendingAction`
  ledger is the only job system);
- a chatbot, MiniMax or any model call;
- real MXroute, real SMTP or IMAP credentials, the VPS, DNS or a deployment;
- alert delivery (P6);
- any change to the release workflow (the release-blocking defect `catalyst-v2-oyu` is unchanged by
  this work).

**Test environment.** Tests run only against synthetic mailboxes:

- a fake SMTP transport with failure injection;
- a local IMAP test server image pinned by digest. The image is chosen in task 2B.2, not here, and is not
  added to CI in 2A.

## 2. What P2 builds on

Every P2 component extends existing code. No parallel mechanism is introduced.

| Existing piece | File | What P2 reuses | What P2 changes (PROPOSED) |
|---|---|---|---|
| Pending-action ledger: claim with SKIP LOCKED, pause skip for automated kinds, poison rule, lease-fenced `finish` | `workflow/ledger.py` | Every P2 effect is a `PendingAction` kind with a handler registered in `settings.CATALYST_ACTION_HANDLERS` | A `due_at` argument on `finish`. Today `finish(status=queued, refund_attempt=True)` sets `due_at = Now()` (`ledger.py` lines 123-127), so a deferral for quiet hours or a stale collector would loop hot. The alternative is setting `due_at` in the `write` callback; the argument is clearer. Also a `fence(claim)` function that checks and extends a lease without finishing the action (B4, decision A-7). |
| `AutomationPause`, one per subject | `workflow/models.py` | Pause semantics (J-09) | None. Pause and resume become staff services (section 4 F). |
| `uncertain` status | `workflow/models.py` | Kept for provider reconciliation (ADR-15, D-20) | Used for the first time, by non-redeliverable send kinds |
| Pre-send boundary, `LeftForRecovery`, the fault seam after send | `correspondence/verification.py` | The three-phase handler shape: a check transaction, then the send with no lock held, then a fenced result | Generalized into a base send handler (section 4 A). `SendVerification` keeps its D-20 redelivery behaviour; no other kind inherits it. |
| `OutboundMessage`, one row per attempt | `correspondence/models.py` | Per-attempt record | Additions in section 3.2 |
| `ApplicationEvent`, append-only | `applications/models.py` | The audit trail for every state change on an application | None. Events stay append-only. |
| Staff attention rule | `applications/staff.py` (`attention_q`) | One rule for dossier, list column and filter | Extended to open staff items (section 3.8) |
| Read-only admin | `config/staff_admin.py` | View-only for every user, superusers included | Named staff actions behind explicit permissions (section 4 F) |
| Start-up guards | `config/guards.py` | Refusal of providers, non-sink backends and provider variables | An allowance, outside production, for the local SMTP and IMAP test servers (section 6). No real provider is reachable. |
| Log redaction | `config/redaction.py` | Confirmation-token redaction | Extended to mail credentials and content (section 6) |
| Role grants | `config/db_roles.py` | Explicit per-table grants, column-level UPDATE, no DELETE | Every new table gets a grant migration (section 3) |

Three facts about the current code shape this design:

- **The recipient is the verified address.** S1 sends to `challenge.email_at_issue`
  (`verification.py` line 197). The verified address is the `email_at_issue` of the challenge named by
  the application's current `VersionAdoption`. P2 sends only to that address.
- **Message-IDs are not persisted before the send.** S1 generates the Message-ID at send time
  (`verification.py` line 116), so a crash after acceptance loses the only reconciliation key. P2 derives
  the Message-ID from a stable `send_ref` stored before the send.
- **Ordinary retries are blind.** `fail_or_retry` returns a generic failure to `queued` until the final
  attempt (`ledger.py` lines 143-147). ADR-15's "reconcile before retry" is therefore a duty of each
  non-redeliverable handler on every attempt. A handler never returns an ambiguous outcome to `queued`.

## 3. Data model sketch (description, not code)

All new tables follow `config/db_roles.py`:

- explicit grants per table;
- UPDATE limited to the named columns;
- INSERT with sequence usage;
- **no DELETE for any role** on the new tables (the existing `AutomationPause` keeps its INSERT and
  DELETE grant, and every pause and resume writes an event with reason and actor);
- nothing for the retention role until POL-10 is decided.

Raw mail and message bodies are personal data. They stay in POL-10's scope (section 8).

### 3.1 MessageTemplate and MessageTemplateVersion (`correspondence`)

- **`MessageTemplate`:** `key` (unique), `purpose`, and `secret_bearing`. A secret-bearing template's
  rendered body is never stored and never shown to staff; the verification invitation is one. The flag is
  not left to judgement: code and a database check require `secret_bearing = true` for any template whose
  variable allow-list contains a link or token variable.
- **`MessageTemplateVersion`:**
  - fields: template, `version`, `subject`, `body_text`, `variables` (an allow-list), `status` (`draft`,
    `approved`, `retired`), `approved_by`, `approved_at`, `content_sha256`, `synthetic`;
  - unique `(template, version)`; a check that `approved` implies an approver and a time;
  - grants: SELECT, INSERT, and UPDATE of `(status, approved_by, approved_at)` only, so approved text
    cannot change.
- **Rendering:** only an `approved` version renders. Variables are substituted from the allow-list; the
  Django template engine is not used for message text. Subjects are static. An unknown or missing
  variable fails closed and nothing is sent.
- **Content:** the synthetic placeholder versions are seeded by migration. Real wording needs POL-06
  and POL-17.

### 3.2 OutboundMessage additions (`correspondence`)

The existing one-row-per-attempt semantics and `UniqueConstraint(pending_action, attempt_number)` are
kept.

- **New columns:**
  - `send_ref` (UUID shared by every attempt and every staff resend of one logical message);
  - `kind`;
  - `template_version` (foreign key, nullable; S1 rows keep their strings);
  - `staff_authored` and `actor_ref`;
  - `rendered_sha256`;
  - `rendered_body` (stored only when the template is not secret-bearing; always for staff messages);
  - `in_reply_to`;
  - `copy_state` (`none`, `pending`, `filed`, `failed`, `found_by_reconcile`);
  - `smtp_accepted_at`.
- **Statuses:** the check grows from `rendered, accepted, failed` to `rendered, sending, accepted,
  unknown, failed`.
- **Message-ID:** `<c{send_ref hex}@{CATALYST_MAIL_DOMAIN}>`, recomputable after any crash. Whether the
  production provider preserves a supplied Message-ID is **UNKNOWN**. It is verified only in a separately
  authorized step before real mail (section 8, before real MXroute).
- **Indexes:** on `message_id` and on `send_ref`.
- **Grants:** UPDATE widened to `(status, message_id, sent_at, smtp_accepted_at, copy_state)`. Identity
  and content columns stay fixed.

### 3.3 OutboundMessageQuestion (`correspondence`)

Records which questions an outbound message carried.

- Fields: the message's Message-ID, the question, and `purpose` (`initial`, `reminder`, `resend`).
- Unique `(message_id, question)`. A partial unique `(question)` where `purpose = 'initial'` stops a
  double approval from sending twice.

### 3.4 Question and QuestionReplyLink

**Home (PROPOSED, decision A-1 in section 8): `correspondence` in P2.** `003` ADR-01 places questions in
`assessments`, which does not exist yet and does not depend on `correspondence`. Reply handling and
reminders must lock and update question status, so in P2 the question lives where it is used.
`assessments` later depends on `correspondence` for it. Either placement amends the proposed app split
in ADR-01.

- **`Question`:**
  - fields: `public_id`, application, `text` (fixed after approval), `origin` (`staff` in P2; `model`
    arrives with P3), `approval_state` (`proposed`, `approved`), `status`, timestamps;
  - `status` is one of `open`, `reply_pending`, `partially_answered` or `satisfied` (`004` J-07), with a
    check constraint;
  - a model-origin question stays `proposed` until staff approve it (fail-closed, `004` J-06);
  - grants: UPDATE `(status, approval_state, updated_at)`.
- **`status` is derived by one function, `refresh_question_status`,** which runs inside every
  transaction that changes a link or an outcome:
  - `reply_pending` if any link is `pending`;
  - otherwise `satisfied` if a staff-confirmed outcome says so;
  - otherwise `partially_answered` if an applied partial outcome exists;
  - otherwise `open`.
- **`QuestionReplyLink`:**
  - fields: question, inbound message, `state` (`pending`, `applied`, `ignored_automated`, `stale`),
    `outcome` (nullable: `satisfied`, `partial`, `not_addressed`), `actor_ref`, timestamps;
  - unique `(question, inbound_message)`;
  - grants: UPDATE `(state, outcome, actor_ref, updated_at)`.

### 3.5 InboundMessage and InboundMessageRaw (`correspondence`)

- **`InboundMessage`:**
  - location: `mailbox_ref` (a configuration key, never the address), `folder`, `uidvalidity`, `uid`;
  - headers: `message_id_header`, `in_reply_to`, `references`, `from_address`, `from_normalized`; a
    Message-ID with invalid syntax is stored but never reused in an outbound header;
  - times: `received_at` by the database clock; the `Date` header kept as untrusted text, never used for
    ordering;
  - content: `size`, `raw_sha256`, `text_plain` and `text_stripped` (NUL escaped), `quote_strip_version`;
  - attachments: a list of metadata only (sanitized name, type, size, digest);
  - trust: `auth_results` (recorded evidence) and `from_matches_verified_address` (the `From` equals the
    verified address; this is **not** proof of authentication);
  - links: application (nullable) and the matched outbound message (nullable);
  - processing: `classification`, `status`, `exception_reason`, `processed_at`.
- **Statuses:** `received`, `awaiting_processing`, `processed`, `automated_reply` or `exception`
  (`004` J-07).
- **Constraints:** unique `(mailbox_ref, folder, uidvalidity, uid)`; a check on status.
- **`InboundMessageRaw`:** one-to-one with the message, holding `raw` as bytes. It is a separate table so
  no admin query ever selects it, and no staff view retrieves it. **Raw is stored only for a message
  matched to an application whose `From` equals the verified address and that is not automatic.** B4
  decides this at ingestion, using the same pure header check D1 uses for automatic messages and bounces,
  so nothing is written that would later need deleting. Unmatched, mismatched and automatic mail keeps
  headers, a truncated scrubbed text and the digest only. A raw size cap and an aggregate quota are named
  settings. When the quota is reached, collection continues but no further raw bytes are stored (headers,
  scrubbed text and digest only), a staff item is opened, and G7 alarms.
- **Primary key:** the raw row's primary key is the one-to-one link to its message, so inserting it needs
  no `RETURNING` of an automatic id and therefore no SELECT privilege.
- **Confirmation tokens never reach storage (D-24).** A reply that quotes the verification invitation, an
  auto-reply or a bounce can carry the signed `/confirm/<token>` link. Before any text or raw field is
  written, every URL under the confirmation path is replaced by a fixed marker, with the same pattern as
  `config/redaction.py`. A message matched to a secret-bearing outbound message stores no raw bytes at
  all, only the scrubbed text and the digest.
- **Grants:**
  - `InboundMessage`: SELECT, INSERT, and UPDATE of `(status, classification, exception_reason,
    processed_at, application_id, from_matches_verified_address)`;
  - `InboundMessageRaw`: **INSERT only.** Nothing in P2 reads raw (resync and reconciliation use the
    digest and Message-ID), so neither web nor worker can select it. SELECT is granted only in the phase
    that adds a reader, with its own review. No fourth role is needed.

### 3.6 MailboxCursor (`correspondence`)

- Fields:
  - identity: `public_id` (the UUID used as the collector action's subject id), `mailbox_ref`, `folder`;
  - position: `uidvalidity` (nullable before the first run), `last_uid`;
  - state: `state` (`ok`, `resync`, `blocked`), `epoch`, `pass_number`;
  - health: `last_success_at`, `last_error_code`, `consecutive_failures`, `resync_duplicates`.
- Unique `(mailbox_ref, folder)`.
- Grants: UPDATE of every column except the identity columns.

### 3.7 Reminder and other action keys

Reminders are `PendingAction` rows; no new reminder table is added. Idempotency keys:

| Effect | Idempotency key | Note |
|---|---|---|
| First send of a question | `send_question:<send_ref>`, plus the `initial` row guard in 3.3 | One send per approval |
| Reminder number n | `remind:<question public id>:<n>` | Reminder n+1 is created in the finish transaction of reminder n |
| Escalation after the last reminder | `escalate_unanswered:<question public id>` | Opens a staff item |
| Staff message | `send_staff_message:<request token>` | The token is rendered into the form, so a double submit is a no-op |
| File the Sent copy | `file_sent_copy:<send_ref>` | Looks up the Message-ID before appending |
| Reconcile an uncertain send | `reconcile_send:<send_ref>:<n>` | Bounded |
| Staff resend after an unknown outcome | `<original key>:resend:<k>` | Same `send_ref`, so the same Message-ID |
| One collector pass | `collect:<cursor public id>:<pass number>` | |
| Process one reply | `process_reply:<inbound public id>` | |
| Hold for P3 | `interpret_reply:<inbound public id>:<question public id>` | Created `held`; never claimed (TEST-S1-19) |

**Pause subject (REQ-013).** The ledger skips a paused subject's automated actions only when the pause and
the action share `(subject_type, subject_id)`. Every per-application automated kind (`send_question`,
`remind`, `escalate_unanswered`, `process_reply`, `reconcile_send`, `file_sent_copy`) therefore has
subject type `application` and the application's public reference; the question or message is named in
`input_ref`. Only `collect` has the cursor as its subject, so collection continues while an application is
paused (J-07).

Grants on `PendingAction` already allow status, due time, attempts and lease changes and never allow a
change of kind, input or key (`workflow/migrations/0002_role_grants.py`). Rescheduling, holding and
cancelling reminders therefore needs no grant change. Changing an action's input is impossible by
design.

### 3.8 Staff exception queue: a `StaffItem` table (PROPOSED, decision A-2)

**Recommendation: a table, with append-only events for audit.** Events alone cannot work, for three
reasons:

1. Unmatched and mismatched mail may have no application, and `ApplicationEvent.application` is not
   nullable.
2. Resolution needs a mutable state and a single-resolution rule. Events are append-only.
3. A partial unique key, `(reason_code, dedupe_key)` where `status = 'open'`, stops a retrying collector
   or a mail flood from opening duplicate items.

Fields and rules:

- **Fields:** `public_id`, `reason_code`, `dedupe_key`, application (nullable), inbound and outbound
  message (nullable), `question_id` and `pending_action_id` (plain identifiers; `workflow` takes no
  domain foreign key, ADR-01), `status` (`open`, `resolved`), `opened_at`, `resolved_at`, `resolved_by`,
  `resolution_code`, `note`.
- **Grants:** UPDATE `(status, resolved_at, resolved_by, resolution_code, note)`.
- **Content:** `note` is length-capped and stripped of control characters, and a note containing a
  confirmation link is refused. Like every P2 event and `exception_reason`, items carry identifiers and
  reason codes only: no address, subject or body.
- **Audit:** opening or resolving an item also writes an append-only `staff_item_opened` or
  `staff_item_resolved` event when an application is known.
- **Compatibility with S1:** `applications/staff.py` treats every `needs_staff_attention` event as open
  forever ("resolving one arrives in P2"). In P2, `attention_q` reads open `StaffItem` rows instead. A
  data migration creates one open item for each existing S1 attention event (`repeat_after_verification`,
  `newer_unverified_version`). Their resolution semantics belong to POL-19.

## 4. Lifecycle A to G

Each row gives one step's contract:

- input and owning component;
- persisted records and transaction boundary;
- permitted action and failure outcomes, with recovery;
- acceptance tests and the next responsible party.

New modules are PROPOSED paths under `correspondence/`. Numbers (cadence, maximum, quiet hours, gaps,
caps) are **named settings, not values**: POL-06 is open, and tests set small synthetic values.

### A. Outbound

| Step | Input and owner | Records and transaction | Permitted action; failures and recovery | Tests; next party |
|---|---|---|---|---|
| A1 Templates | owner-approved text; `correspondence/models.py` | Version rows INSERT-only; one transaction per approval | Only `approved` versions render; allow-listed variables; static subjects. Unknown variable: fail closed, nothing sent | TEST-P2-37, TEST-P2-38; owner (wording, POL-06 and POL-17) |
| A2 Enqueue | a question approved, a reminder due, or a staff message; `correspondence/outbound.py` services | One transaction under the application lock: question rows, `OutboundMessageQuestion`, `PendingAction` (keys in 3.7), event. The action's `input_ref` is the `send_ref` | A double approval hits the unique `initial` row: no-op | TEST-P2-12, TEST-P2-36; worker |
| A3 Attempt | claimed send action; a base handler in `outbound.py`, a thin subclass per kind, registered in `settings.CATALYST_ACTION_HANDLERS`; every P2 send kind `redeliverable = False`; subject `application` (M3, section 10); transport a thin `smtplib` wrapper in `correspondence/transport.py` (Django's mail backend cannot tell a rejection from an ambiguous outcome), with a total-deadline setting below half the lease | (1) Check transaction: lock application, then questions; re-check pause and eligibility; INSERT the attempt row with status `sending`; commit. (2) SMTP with no lock held. (3) Fenced finish transaction. | Recipient is the verified address only. Outcome classes: **accepted**; **definitely rejected** (failure before the end of DATA, or a 4xx or 5xx reply after it): ordinary retry with backoff, then `failed`; **ambiguous** (timeout or disconnect after DATA was sent): attempt `unknown`, action `uncertain`, a `reconcile_send` action enqueued. An ambiguous attempt is never retried directly. A reclaimed action that finds an earlier `sending` attempt row for the same `send_ref` goes to reconcile, never to a new send. | TEST-P2-03, TEST-P2-25, TEST-P2-27; worker, then staff |
| A4 Sent copy | an accepted attempt of a P2 send kind; the `file_sent_copy` kind. The verification invitation (secret-bearing, S1 kind) is **excluded**: no Sent copy of a confirmation link is filed | Accepted is recorded first; the IMAP APPEND is its own action | The Message-ID is searched before APPEND, so a repeat is idempotent. A failed APPEND retries the APPEND only, then opens a staff item; it never re-sends. The send counts as done. | TEST-P2-26; worker, then staff |
| A5 Reconcile | `reconcile_send`; `outbound.py` | IMAP search of the Sent folder by Message-ID. Found: one transaction moves the action `uncertain` to `done` (compare-and-set on `uncertain`), the attempt to `accepted`, and runs the after-send effects (next reminder, event). Not found after the bounded grace and attempts: staff item `send_outcome_unknown`. | **A missing Sent copy does not prove the message was not sent.** The automatic path never re-sends. Staff choose `mark_sent`, `resend` (a new action with the same `send_ref` and Message-ID) or `mark_failed`. | TEST-P2-03, TEST-P2-25, TEST-P2-26; staff |
| A6 Terminal | attempts exhausted | `failed` (definite) or `uncertain` (poison rule, `ledger.py` lines 157-162), with an event and a staff item | Visible in admin and in the G queries | TEST-P2-39; staff |

### B. IMAP collection

| Step | Input and owner | Records and transaction | Permitted action; failures and recovery | Tests; next party |
|---|---|---|---|---|
| B1 Single owner | a `collect` action whose subject is the cursor; `correspondence/inbound.py` | Finish transaction marks the pass done, updates cursor health and enqueues the next pass (`due_at` = now + interval). One action row per pass. | One owner by SKIP LOCKED and the per-message lease fence. The chain survives failure: the final-failure and poison events enqueue the successor and open a staff item. A management command bootstraps the first pass; G1 detects a broken chain. Because the subject is the mailbox cursor, an application pause never stops collection (J-07). | TEST-P2-21, TEST-P2-22; worker |
| B2 Session | the cursor; `correspondence/transport.py` (`MailboxClient`, a TLS-only `imaplib.IMAP4_SSL` wrapper, plus a fake) | Cursor updates only on validity changes | A verifying SSL context is passed explicitly (the standard library's default does not verify the certificate or hostname). Timeout at most half the lease. `SELECT` read-only and `BODY.PEEK[]` only, so the mailbox is never modified. Authentication failure: no retry loop; cursor `blocked` and staff item `mailbox_auth_failed`. Unreachable: ledger backoff, then a staff item after a bounded count. | TEST-P2-23, TEST-P2-24; worker, then operator |
| B3 Fetch and parse | UIDs greater than `last_uid`, ascending, with a batch cap and a time budget under half the lease; `correspondence/mime.py` (pure functions) | none | Size read before the body. Over the size cap: a metadata-only row, status `exception`, reason `oversize`, and the cursor passes it. Parsing with `email.policy.default`; defects are recorded, never raised. Caps on header count and length, MIME depth and part count. NUL bytes escaped. Attachments are never opened, unpacked or written to disk. The server's UID filter is re-applied on the client (`uid > last_uid`). | TEST-P2-14, TEST-P2-15; worker |
| B4 Per-message commit | one parsed message; `inbound.py` and `correspondence/association.py` | **One transaction per message:** lock the cursor (check `uidvalidity` and `last_uid < uid`), then the application, then its questions by id; INSERT the message (a unique-key conflict is a no-op skip); associate (C); set related open questions to `reply_pending`; enqueue `process_reply`; write the event; advance `last_uid` with a conditional UPDATE; **last**, a lease-fence check of the collect action that also extends its lease (a new `ledger.fence` function, decision A-7; `finish` is today's only fence and also changes status). If the fence matches no row, roll back and stop the pass. | A message that fails processing is persisted as `exception`, reason `processing_error`, so one bad message never blocks the cursor. Only a database failure aborts the pass. Collection never marks a question answered and never cancels a reminder (J-07). | TEST-P2-01, TEST-P2-12, TEST-P2-19; worker |
| B5 Resync | a `UIDVALIDITY` change, or a lost or restored cursor; `inbound.py` | See section 4.1 | Duplicates are removed by Message-ID plus size and date, then by digest. Nothing is processed twice. A staff item is opened (the operator alert of J-07). | TEST-P2-07, TEST-P2-20, TEST-P2-46; staff |

#### 4.1 Checkpoint, crash and resync rules

The cursor advances inside the message transaction, as its last data statement before the lease fence.
That gives no crash window between storing a message and advancing past it. The unique key
`(mailbox_ref, folder, uidvalidity, uid)` is a second defence, so a reset or restored cursor is harmless.

| Crash point | Result |
|---|---|
| Before or during fetch or parse | Nothing committed; the next pass re-reads the same UID |
| Inside the message transaction, before commit | Rolled back; re-read; nothing doubled |
| After the commit | The message and the cursor have both advanced |
| Lease lost (a second collector now owns the pass) | The fence fails; rollback; the stale pass stops; the new owner re-reads |
| Pass ends, but the successor is not enqueued | The pass is not `done`, so lease recovery re-runs it; the pass key is unique |
| Final failure or poison | The successor is enqueued and a staff item opened |

**First run:** no history is ingested by default. The cursor starts at the mailbox's current highest UID
and an informational staff item is opened, unless an operator supplies a start UID (decision B-4).

**`UIDVALIDITY` change.** One fenced transaction:

- sets `state = resync` and increments `epoch`;
- records the old validity and `last_uid`, then sets the new validity and `last_uid = 0`;
- opens staff item `mailbox_uidvalidity_changed`.

Resync passes then walk every UID:

- Cheap metadata (Message-ID, size, internal date) is fetched first.
- A Message-ID, size and date that match a stored row are a duplicate: skipped and counted.
- A matching Message-ID with different metadata is fetched and compared by digest. The same digest is a
  duplicate. A different digest is stored as a new row and opens a staff item (a replay or a forgery).
- A message without a Message-ID is fetched and compared by digest.

The cursor returns to `ok` when a pass completes up to the server's next UID. Reminders defer while the
cursor is not `ok` (E2).

### C. Association and trust

| Step | Input and owner | Records and transaction | Permitted action; failures and recovery | Tests; next party |
|---|---|---|---|---|
| C0 Bounce first | a delivery-status report; `association.py` | — | Detected **before** C1 and C2, because a bounce's `From` is a mailer, not the applicant. A bounce is matched only through the original Message-ID embedded in it and is never treated as a reply. Its structured `message/delivery-status` and `message/rfc822` parts are parsed as headers only; no other part is opened. Its only effects are fail-safe (D1), so a forged bounce can at worst pause automation. | TEST-P2-33; system |
| C1 Association | `In-Reply-To`, then `References`; `association.py` | Inside B4: the message's application and matched outbound message, and a `pending` link for each open or partially answered question the matched outbound carried | Exact, case-insensitive match against our stored Message-IDs only; no fuzzy matching. A delivery-status report is routed by the original Message-ID embedded in it. No match: status `exception`, reason `unmatched`, staff item. A reply to a closed application resolves to that application by Message-ID and becomes an exception; it is never applied to a newer application with the same address. | TEST-P2-01, TEST-P2-18; staff |
| C2 Trust | the `From` header; `association.py` | `from_matches_verified_address` | `From` must hold exactly one mailbox, equal to the matched application's verified address by an exact case-folded comparison of the ASCII (IDNA) form. If Unicode normalization would change the inbound address, it is treated as a mismatch, so a look-alike never matches. `Reply-To`, `Sender` and display names are never used. Mismatch: status `exception`, reason `sender_mismatch`, staff item; **no** `reply_pending`, no question or reminder effect (POL-19 default). | TEST-P2-16, TEST-P2-17; staff |
| C3 Authentication evidence | `Authentication-Results` | `auth_results`, recorded only | Only the **topmost** header whose authserv-id equals a configured trusted id is parsed; others are ignored. That is safe only if the receiving provider strips such headers from incoming mail, which is an unverified provider fact (section 8.2). Results are shown to staff and never cause a positive effect. PROPOSED: an explicit DMARC or SPF `fail` from the trusted id makes the message an exception with no `reply_pending`, so a spoofed `From` cannot suppress reminders. The production authserv-id is UNKNOWN. | TEST-P2-17; staff |
| C4 Unmatched and mismatch queue | exception rows; `StaffItem` | One open item per dedupe key | Staff `associate`, `dismiss` or `mark_spoof`. Staff association runs the same effects as C1, with the actor recorded. | TEST-P2-06, TEST-P2-18; staff |

### D. Reply processing

| Step | Input and owner | Records and transaction | Permitted action; failures and recovery | Tests; next party |
|---|---|---|---|---|
| D1 Classify | `process_reply` (automated, subject `application`, so a pause holds it); `correspondence/processing.py` | One transaction: application, questions, message, then the fenced action | Deterministic order: a delivery-status report is a **bounce**; `Auto-Submitted` other than `no` (RFC 3834), `Precedence: bulk, junk or auto_reply`, auto-reply headers and list headers mark an **automatic** message; a subject pattern is a supporting signal only. Automatic: message `automated_reply`, links `ignored_automated`, question status recomputed, no outbound, the loop counter counts it. Hard bounce (5.x.x): automation paused and a staff item. Soft bounce (4.x.x): recorded only. A bounce counts only if the embedded Message-ID is ours and its recipient is the verified address. | TEST-P2-02, TEST-P2-10, TEST-P2-33, TEST-P2-34; system |
| D2 Reply from a person | the same transaction | The message stays `awaiting_processing`; an `interpret_reply` action is created `held` per question; staff item `reply_needs_review` | Questions stay `reply_pending`, so reminders stay suppressed, until staff confirm (D3) or P3 ships. Both the full and the quote-stripped text are kept, with `quote_strip_version`; ambiguous input keeps the full text and is flagged. | TEST-P2-08, TEST-P2-09, TEST-P2-43, TEST-P2-44; staff, then P3 |
| D3 Outcome | the staff service `confirm_question_outcome` (F) | One transaction: application, questions, message; compare-and-set the message from `awaiting_processing` to `processed`; set each link's outcome to `applied`; refresh question status; synchronize reminders (E3); cancel the held `interpret_reply` actions; write the event | Outcomes: `satisfied`, `partial` (question becomes `partially_answered`) or `not_addressed` (question returns to `open`; reminders resume). A concurrent loser sees `processed` and does nothing. When every question is satisfied, P2 records an event only: **P2 changes no application stage** (ADR-13); reassessment is P3. | TEST-P2-08, TEST-P2-09, TEST-P2-32; staff, then P3 |

### E. Reminders

| Step | Input and owner | Records and transaction | Permitted action; failures and recovery | Tests; next party |
|---|---|---|---|---|
| E1 Schedule | `correspondence/reminders.py` | Reminder 1 is created in the finish transaction of an **accepted** (or reconciled-accepted) question send; reminder n+1 in the finish transaction of reminder n. Due time by the database clock. | No reminder while the send is `uncertain`. After the maximum, an `escalate_unanswered` action opens a staff item; the application waits in the staff queue with reason "no response" (J-08). Unique keys make creation idempotent. | TEST-P2-29; system |
| E2 Fire | a claimed reminder | Check transaction: lock the application, then the question; then the A3 send path | Sent only if: the question is `open` or `partially_answered`; the application is open and not paused; no link is pending; it is not quiet hours; the minimum gap since the last automated message to the application has passed; n is within the maximum; the collector is fresh (cursor `ok` and `last_success_at` at or after the reminder's due time). `reply_pending`: suppressed (held). `satisfied`: cancelled. Ineligible for time reasons: deferred with an explicit `due_at` (section 2). A stale collector beyond a bounded deferral count opens staff item `collector_stale`. Every automated message carries `Auto-Submitted: auto-generated`. | TEST-P2-04, TEST-P2-28, TEST-P2-29; system |
| E3 Projection | every change of question status | `sync_reminders(question)` in the same transaction | `open` or `partially_answered`: queued; `reply_pending`: held; `satisfied`: cancelled. **Only `satisfied` cancels.** Rescheduling or cancelling a reminder never changes a question's status. The handler's own re-check stays authoritative. | TEST-P2-04, TEST-P2-30; system |
| E4 Resume | the `resume` staff service | One transaction: application lock, delete the pause, reschedule | Each queued reminder that fell due during the pause gets `due_at` = now + a resume grace + its rank × the minimum gap. No catch-up copies; counters unchanged; held reminders untouched; question statuses unchanged (J-09). | TEST-P2-05, TEST-P2-31; system |

**Loop detection.** More than a set number of automatic messages for one application in a set window
pauses automation and opens a staff item (J-08). A per-application circuit breaker bounds automated
outbound in the same way. Both are named settings.

### F. Staff intervention

Services live in `correspondence/staff_actions.py` (PROPOSED, decision A-3). Each is one transaction that
starts with the application lock, checks a named permission, and writes an append-only event with the
staff actor. The interface is admin-first:

- named admin actions on the relevant change lists, each behind its permission, while the read-only
  posture of `config/staff_admin.py` stays in force everywhere else;
- focused views only where admin cannot collect the input: the staff message form, the outcome
  confirmation form showing message text beside the questions, and the exception resolution form with a
  per-reason allow-list.

Whether admin actions fit the read-only mixin without weakening it needs a short spike in task 2B.4
(`ReadOnlyAdminMixin` sets `actions = None` today). Sensitive services act on **one object at a time**;
there is no bulk action for `resolve_exception`, `resolve_identity_exception` or
`confirm_question_outcome`.

| Service | Permission (PROPOSED, POL-13) | Effect | Tests |
|---|---|---|---|
| `pause(application, reason)` | `pause_automation` | INSERT `AutomationPause` (unique, so idempotent) and an event. An automated action already past its check completes (the S1 boundary). | TEST-P2-05, TEST-P2-31 |
| `resume(application)` | `resume_automation` | E4 | TEST-P2-05, TEST-P2-31 |
| `resolve_exception(item, code, note)` | `resolve_exception`; identity-affecting codes (`associate` of a mismatched sender, `mark_spoof`, any POL-19 resolution) need `resolve_identity_exception` | Compare-and-set the item from `open` to `resolved`, then the resolution effect from the allow-list for its reason: `associate`, `dismiss`, `mark_spoof`, `mark_sent`, `resend`, `mark_failed` or `restart_collector`. Resolving twice is a no-op. No SSH, database edit or coding agent is needed (REQ-014). | TEST-P2-06 |
| `send_staff_message(application, body, request token)` | `send_staff_message` | A `send_staff_message` action, **not automated**, so it runs while paused (J-09). Stored body, `staff_authored`, actor. Verified recipient only. It creates no reminder, changes no question status and never resumes automation. A body containing a confirmation link or credential-like text is refused. Whether staff may write free text or only use templates is decision A-5. | TEST-P2-11, TEST-P2-45 |
| `confirm_question_outcome(message, outcomes)` | `confirm_question_outcome` | D3 | TEST-P2-08, TEST-P2-09, TEST-P2-32 |

No P2 staff account can act until the owner creates an operator group with these six permissions
(POL-13, P2 slice). The S1 read-only group keeps exactly its view permissions. Against real mail, no
account receives a write permission and no staff-authored send is enabled until POL-13's MFA and network
restriction are decided (section 8.2).

### G. Monitoring (definitions only)

Read-only queries over the tables above, in `correspondence/health.py`. They are surfaced as admin
filters and dossier lines in P2, plus a `manage.py correspondence_health` command whose exit status P6
can wire to alerting. **Alert delivery is P6.**

| Signal | Definition |
|---|---|
| G1 Collector health | `now - last_success_at` above k × the poll interval; `consecutive_failures`; cursor `state` not `ok`; a cursor with no `queued` or `running` collect action (broken chain) |
| G2 Oldest unprocessed | oldest `awaiting_processing` message, overall and per application |
| G3 Failed and uncertain sends | `failed` and `uncertain` actions by kind and age; attempts in `sending` older than the lease |
| G4 Overdue conversations | reminders queued past due by more than a set margin; open questions with no live reminder while under the maximum |
| G5 Unresolved staff items | open `StaffItem` rows by reason and age; paused applications by pause age (J-09) |
| G6 Consistency | a `reply_pending` question with no pending link; a pending link whose message is not `awaiting_processing`; a held reminder whose question is not `reply_pending` |
| G7 Mail behaviour and storage | automatic inbound per application per window; hard bounces; growth of the inbound and raw tables against the quota |

## 5. Lock order and transactions

**Order** (extends `005` S1.4, which is application, then challenge):

1. mailbox cursor (collector only; always outermost);
2. application;
3. challenge and question rows, by id;
4. inbound message;
5. outbound message;
6. pending-action rows, by id.

Staff services, reminder handlers and `process_reply` all start at the application, and nothing takes
the application and then the cursor, so the order has no cycle. For reminder, processing and send kinds,
`lock_subject` locks the application and then the named question before the ledger's fenced action
update. `SendVerification.lock_subject` keeps locking only the application, which is correct for its
kind. Providers are never called while a row lock is held (`ledger.py` rule 3).

**Reply versus reminder:**

- **Collector commits first.** The reminder check then sees `reply_pending`, inserts no outbound row and
  holds the reminder. TEST-P2-04 asserts that the reminder is held, not cancelled.
- **Reminder check commits first.** The attempt row exists and the reminder goes out. The reply then sets
  `reply_pending`. This is lawful, because the reply was collected after the check.
- **The guarantee, stated exactly:** no reminder check passes after a committed reply. It is not "no
  reminder is sent after the applicant pressed send". The window between the check's commit and the SMTP
  reply cannot be closed without calling the provider under a lock, which the ledger forbids. This is the
  same boundary S1 states for verification.
- **Collector lag:** a reply that has reached the mailbox but not yet been collected is covered by the
  freshness gate (E2). It becomes a bounded wait, then a staff item, instead of a silent miss.
- **Staff confirmation versus `process_reply` on one message:** both lock application, question,
  message. The compare-and-set on `awaiting_processing` lets exactly one win.
- **A late reply to a satisfied question:** the link is `stale` and the question stays `satisfied`.
- **A pause racing an in-flight automated action:** the action's check re-reads the pause. An action
  already past its check completes. Staff messages ignore pauses by design.

## 6. Security and privacy

| Threat | Control |
|---|---|
| Spoofed `From` | The sender must equal the matched application's verified address; a mismatch is an exception with no automatic effect; authentication results never cause a positive effect, and an explicit DMARC or SPF fail from the trusted id makes the message an exception (C3); satisfaction needs staff confirmation |
| A learned Message-ID used in a forged reply | Association uses the Message-ID and trust uses the sender; both must hold, against the matched application only |
| Forged `Authentication-Results` | Only the topmost header with the configured trusted authserv-id is read, which is safe only if the provider strips incoming copies (an unverified provider fact, 8.2) |
| Forged bounce | Counts only for our embedded Message-ID and the verified recipient; the effect fails safe (pause and staff item) |
| Header injection outbound | Static subjects, allow-listed variables, the `smtplib` wrapper receives a standard-library `EmailMessage` whose header policy rejects newlines, the verified recipient only, no CC or BCC from any input |
| `Reply-To`, `Sender`, display names, look-alike characters | Never used for identity; staff see the normalized address as plain text |
| Autoresponder storms and backscatter | Automatic mail is never answered; our automated mail carries `Auto-Submitted: auto-generated`; loop detection and the circuit breaker pause automation |
| Malicious MIME (nesting, huge parts, bad charsets, NUL bytes, archive bombs) | Size gate before the body fetch; depth and part caps; defects recorded; NUL escaped; attachments are never opened, unpacked or written to disk; scanning and custody are decided before P3 uses attachments (POL-09, POL-10) |
| Active content (HTML, scripts, remote images) | **Never rendered.** The text part is stored; an HTML-only message is reduced to sanitized text by a pure function; Django auto-escaping everywhere; no `mark_safe` in admin |
| Prompt injection aimed at P3 | P2 interprets nothing. Text is stored as untrusted data, full and stripped versions kept separately, for P3's input boundary (`004` J-05) |
| Replay of old messages | The unique key and the digest comparison in resync |
| Unmatched mail floods | Batch cap; one open staff item per dedupe key; aggregation of unmatched items is decision A-6 |
| IMAP or SMTP downgrade or interception | TLS-only client classes, a verifying context passed explicitly, no plaintext fallback |
| Secrets or bodies in logs | The control is a rule, enforced by test: mail code logs reason codes, identifiers and exception class names only (the S1 pattern in `verification.py`); no `logger.exception`, no exception text, and no `set_debuglevel` on the SMTP or IMAP client. `config/redaction.py` rewrites confirmation paths on three Django loggers only and cannot recognize credentials or content, so it is a backstop, not the control. `last_error` stays sanitized |
| Confirmation tokens in inbound mail (D-24) | Confirmation URLs are scrubbed before storage; no raw bytes for messages matched to a secret-bearing outbound; no Sent copy of the invitation (sections 3.5, A4) |
| Untrusted mail stored without a deletion path | Raw only for matched mail from the verified sender; size cap and quota; G7; POL-10 must give the retention role its DELETE path before pilot |
| Hostile text in staff views | HTML escaped, plus bidirectional-override and control characters stripped for display |
| A credential sent by email | No template may carry a credential; secret-bearing templates store and show no body; the staff message form refuses credential-like text as a defence in depth, not a guarantee; secrets an applicant sends sit in the raw store under POL-10 |
| The `Date` header | Never trusted for ordering; the database clock and UID order are |

**Protected body storage (PROPOSED, POL-10).** Bodies and raw messages are stored in PostgreSQL only, in
the tables above, until POL-10 decides retention, access and deletion. No retention path exists and no
message is deleted, in line with the owner's no-deletion direction (D-17, D-22). Raw messages are
written by the worker and read by nothing in P2.

**Start-up and connect-time guards (PROPOSED, decision A-4; amends REQ-022).** REQ-022 requires
settings to refuse non-sink mail hosts outside production. A local SMTP or IMAP test server is not a sink,
so this is an explicit amendment the owner approves, not an implementation detail. The proposal:

- `config/guards.py` keeps refusing provider variables named `MXROUTE_`, `SMTP_` or `EMAIL_HOST`; the new
  settings are named `CATALYST_MAIL_*`;
- in `development` and `test` (the only environments `guards.py` allows today), a mail host must be a
  literal loopback IP, or the one named test-service host for the `test` environment, mirroring the
  database-host allowance in `tests/conftest.py`'s network guard, which 2B.2 extends to it;
- the transports re-check the **connected peer address** at connect time and refuse, before sending any
  credential, unless it is loopback or the test service's private address. A start-up check alone could
  be bypassed by a direct `smtplib` or `imaplib` call or by a name that changes between start-up and
  connect;
- `CATALYST_MAIL_USER` and `CATALYST_MAIL_PASSWORD` are refused unless the host passes the same check.

Real MXroute stays refused until separately authorized.

## 7. GATE-P2 acceptance plan

GATE-P2 (`002` section 6): every case below PASS in CI with fakes and the local IMAP test server, plus the
phase after-action report. The cases are appended to `tests/acceptance.py` in task 2C. GATE-S1's 22 cases
remain mapped and gated in every full run. No mandatory test may be skipped: the existing skip gate fails
any run with a skip, xfail or xpass. Concurrency cases use real transactions and barrier seams (the
pattern of `ledger._after_claim_select`). Crash cases use a real worker subprocess killed with SIGKILL
(the pattern of TEST-S1-07c).

**Already named in `004` and `002`:**

| ID | Case | Section |
|---|---|---|
| TEST-P2-01 | A reply is correlated to its outbound message and the questions it carried | B4, C1 |
| TEST-P2-02 | An autoresponder and a loop stop automation | D1, E2 |
| TEST-P2-03 | An uncertain send is reconciled, never blindly retried | A3 to A5 |
| TEST-P2-04 | Reminder race: a reminder is suppressed, not cancelled, while a reply awaits processing | E2, E3, section 5 |
| TEST-P2-05 | A pause stops every automated kind; resume reschedules without a burst and changes no question status | F, E4 |
| TEST-P2-06 | Staff resolve an exception without SSH | F |
| TEST-P2-07 | A `UIDVALIDITY` change resynchronizes without double processing and alerts staff | B5 |
| TEST-P2-08 | A partial answer leaves the rest open | D3 |
| TEST-P2-09 | An acknowledgement is not an answer | D3 |
| TEST-P2-10 | An autoresponder satisfies nothing | D1 |
| TEST-P2-11 | A staff message is sent while paused and no automated action runs | F |

**Added in 2A (PROPOSED):**

| ID | Case |
|---|---|
| TEST-P2-12 | Duplicates are no-ops: the same UID fetched twice, a question approved twice, identical bytes replayed |
| TEST-P2-13 | The same Message-ID with different bytes is stored as a new row and opens a staff item |
| TEST-P2-14 | Malformed MIME (bad charset, NUL bytes, deep nesting, missing headers) gives an `exception` row, and the cursor passes it |
| TEST-P2-15 | An oversize message or attachment gives a metadata-only row and no body fetch |
| TEST-P2-16 | A spoofed or mismatched sender causes no `reply_pending` and no reminder change, and opens a staff item |
| TEST-P2-17 | Authentication results are recorded; a header from an untrusted authserv-id, or below the topmost trusted one, is ignored; a pass causes no positive effect; an explicit fail from the trusted id makes the message an exception with no `reply_pending` |
| TEST-P2-18 | Unmatched mail reaches the staff queue and staff can associate it; a reply to a closed application is never applied to a newer one |
| TEST-P2-19 | A collector killed mid-message loses nothing and duplicates nothing |
| TEST-P2-20 | A lost cursor, or one restored to an older position, causes no double processing |
| TEST-P2-21 | Two collectors: the lease fence stops the stale one, including a lease that expires between two messages of one pass |
| TEST-P2-22 | Two workers race for one collect action: one claim, the successor created exactly once, and the chain survives a final failure |
| TEST-P2-23 | An unreachable server retries with a bound; an authentication failure does not loop; a sentinel test proves no credential, address, subject or body appears in any log output of the mail code |
| TEST-P2-24 | A plaintext server and a bad certificate are refused |
| TEST-P2-25 | An ambiguous SMTP outcome becomes `uncertain`; reconciliation finds the Sent copy; nothing is re-sent |
| TEST-P2-26 | No Sent copy found: the send stays `uncertain` with a staff item; an APPEND failure after acceptance causes no re-send |
| TEST-P2-27 | A crash after SMTP acceptance and before recording is recovered without a blind re-send |
| TEST-P2-28 | Reminder-race matrix: reply first, reminder first, interleaved, and a lagging collector held by the freshness gate |
| TEST-P2-29 | Cadence, maximum, quiet hours and minimum gap are enforced; escalation follows the last reminder |
| TEST-P2-30 | Only `satisfied` cancels a reminder; a partial answer keeps reminders |
| TEST-P2-31 | A pause during a running reminder; resume across several questions and applications causes no burst |
| TEST-P2-32 | Staff confirmation racing `process_reply` on one message: exactly one wins |
| TEST-P2-33 | A hard bounce pauses automation; a soft bounce is recorded only; a forged bounce is ignored |
| TEST-P2-34 | The loop threshold pauses automation and opens a staff item |
| TEST-P2-35 | A late reply to a satisfied question is `stale` and changes nothing |
| TEST-P2-36 | The recipient is always the verified address, never `From`, `Reply-To` or staff-typed text |
| TEST-P2-37 | An unapproved template version is refused; an approved one is immutable; the variable allow-list is enforced; a template with a link variable cannot be saved as not secret-bearing |
| TEST-P2-38 | Header-injection attempts are rejected outbound |
| TEST-P2-39 | Schema and grants for every new table: column-level UPDATE only, no DELETE for any role, and no SELECT on the raw table |
| TEST-P2-40 | Guards: a non-allowed SMTP or IMAP host refuses start-up; a connection whose peer address is not allowed is refused before any credential is sent; mail credentials with a non-allowed host and provider variables are refused |
| TEST-P2-41 | Each G query returns its seeded anomaly |
| TEST-P2-42 | Admin: each named action needs its permission; everything else stays read-only; hostile message text is escaped |
| TEST-P2-43 | A held `interpret_reply` is never claimed; `correspondence` imports no model client and makes no network call outside its transports |
| TEST-P2-44 | Quote stripping golden cases per `quote_strip_version` |
| TEST-P2-45 | A staff message has no side effects on reminders or questions; a credential-like body is refused |
| TEST-P2-46 | A `UIDVALIDITY` change mid-batch, and a crash during resync |
| TEST-P2-47 | A reply quoting the verification invitation, an auto-reply and a bounce that embed a confirmation link store no token anywhere (text, raw, events, staff views); unmatched mail stores no raw bytes |

Every case runs on synthetic mailboxes with `example.test` addresses. TEST-P2-40 also proves that no test
reaches a real provider.

## 8. Owner decisions brief

Nothing below is approved. Each item gives options, a recommended default (PROPOSED), and the earliest
point it blocks. Recording a decision in `011` section 4 is a separate owner act.

### 8.1 Before 2B starts (each blocks the task named)

| Item | Question | Options | Recommended default | Blocks |
|---|---|---|---|---|
| POL-06 (templates, send authority) | Which message kinds exist, who approves their wording, and who may cause a send | (a) owner approves every template version; (b) owner approves templates and named staff approve per-application questions; (c) any staff member sends | (b), with fail-closed approval of model-origin questions (J-06); synthetic placeholder text until POL-17 | 2B.1 |
| ADR-15 generalization | Whether every non-redeliverable external effect uses `uncertain` and reconciles before retry | (a) generalize as drafted; (b) per-kind decisions | (a): every P2 send kind `redeliverable = False`; an ambiguous outcome becomes `uncertain`; reconciliation by Message-ID; staff decide when it is inconclusive. D-20 stays limited to the verification invitation. Read-only and internal kinds (`collect`, `process_reply`) may retry because they have no external effect; the owner confirms that reading of D-20. | 2B.1 |
| POL-19 (identity disputes) | What happens when a reply's sender, or a later repeat submission, conflicts with the verified identity; who resolves it | (a) staff item only, no automatic effect, any operator resolves; (b) as (a), but only a decision-maker resolves `mark_spoof` and identity changes; (c) automatic rejection | (b). Ambiguity always becomes a staff item; no automatic effect from a mismatch | 2B.3 |
| POL-06 (cadence and stops) | Reminder cadence, maximum count, quiet hours and their time zone, minimum gap, loop threshold, bounce rules, escalation, when staff take over | numbers chosen by the owner | Named settings with no production numbers; tests use synthetic values. Stop on any autoresponder or loop, on a hard bounce and at the maximum; escalate to the staff queue with reason "no response" | 2B.4 |
| POL-13 (P2 slice) | Who may pause, resume, resolve exceptions, resolve identity exceptions, confirm question outcomes and send staff messages | (a) one operator group with all six permissions; (b) operator group plus a decision-maker group holding `resolve_identity_exception` and `confirm_question_outcome` | (a) for P2 synthetic use; the six permissions are separate, so (b) and POL-19 (b) need no code change. MFA and network restriction are decided before any real mail (8.2) and at GATE-STAGING | 2B.4 |

**Architecture choices** the owner approves with the 2A PR, because they amend PROPOSED records:

| ID | Choice | Recommended default |
|---|---|---|
| A-1 | Home of `Question` (`003` ADR-01 places it in `assessments`) | `correspondence` in P2; `assessments` depends on it later |
| A-2 | Staff exception queue | The `StaffItem` table, with events for audit (section 3.8); S1 attention events migrated to open items |
| A-3 | Home of pause, resume and takeover services (`003` says `applications` sets pauses) | `correspondence/staff_actions.py`, because resume reschedules reminders |
| A-4 | Guard change for local test servers (**amends REQ-022**; owner-decided D-10 is unchanged) | Literal loopback or the one named test-service host in `development` and `test`; a connect-time peer check; settings named `CATALYST_MAIL_*`; provider refusals unchanged (section 6) |
| A-5 | Staff message content | Free text in P2, stored, staff-authored, refused if it looks like a credential |
| A-6 | Unmatched-mail staff items | One per message, with a dedupe key; aggregate per sender digest and day only if floods appear (the dedupe key holds a hash, never an address) |
| A-7 | Ledger changes | A `due_at` argument on `finish`; a `fence(claim)` function that checks and extends the lease inside a transaction without finishing the action (used per message by the collector); one action row per collector pass (re-arming one row is rejected because it needs a larger ledger change) |
| A-8 | Question withdrawal | Not in P2: the four statuses of `004` stand; a mistaken question is answered by staff confirming `satisfied` with a note |
| A-9 | Raw mail store | Raw only for matched mail from the verified sender; INSERT-only grant; confirmation URLs scrubbed; no raw for messages matched to a secret-bearing outbound; a size cap and quota as settings |

### 8.2 Before any real MXroute connection

| Item | Question | Recommended default |
|---|---|---|
| POL-02 | Verification link lifetime, resend limits, what an expired link offers | Decide before the first real email; P2 keeps the setting with synthetic values |
| POL-10 (messages) | What is stored from inbound mail (raw, text, attachments), who may read it, retention and deletion | Store raw and text in PostgreSQL only; no staff view of raw messages; attachments as metadata until POL-09; no deletion until decided |
| Provider facts | Whether the provider keeps a supplied Message-ID, files Sent copies itself (a provider-side copy of the invitation would hold a confirmation link), its authserv-id, whether it strips incoming `Authentication-Results` headers, and per-application reply addresses | Verified in a separately authorized, read-only provider check; unknown until then |
| POL-13 MFA and network | Whether staff write permissions and staff-authored sends may exist against real mail before MFA | No: no account receives a P2 write permission and no staff-authored send is enabled against real mail until MFA and the network restriction are decided |
| Guard lift | Allowing a real SMTP and IMAP host anywhere | A separate authorization, after the items above |

### 8.3 Before pilot (GATE-PILOT and GATE-STAGING)

- **POL-10 in full:** retention for messages, bodies, attachments and staff items.
- **POL-13 in full:** MFA and the staff network restriction.
- **POL-16:** operating targets for the G signals.
- **POL-17:** real applicant-facing wording.

### 8.4 Classification of `015`

The PDF rendering of `015` carried a "Confidential" footer from the rendering theme's default. The source
file is public in this repository. Options:

- (a) the report is public, and future PDFs use an unclassified theme;
- (b) it is internal, and is moved out of the public repository.

Recommended: (a), because it contains no applicant data, credentials or private paths. The owner decides.

## 9. Bead map and the 2B/2C mapping

| Key | Bead | Title | Depends on |
|---|---|---|---|
| 2A | `catalyst-v2-7hu.1` | Specify the P2 correspondence design and prepare the owner's P2 decisions | GATE-S1 |
| 2B.1 | `catalyst-v2-7hu.2` | Build the outbound communication foundations: versioned templates, a generalized send handler, the uncertain status and SMTP-fake reconciliation | 2A; POL-06 (templates, send authority); ADR-15 |
| 2B.2 | `catalyst-v2-7hu.3` | Collect inbound mail from the local IMAP test server and correlate it durably with outbound messages | 2B.1 (outbound Message-IDs) |
| 2B.3 | `catalyst-v2-7hu.4` | Process replies deterministically and route judgment to staff confirmation or a held interpretation action | 2B.2; POL-19 |
| 2B.4 | `catalyst-v2-7hu.5` | Run reminders and controlled staff intervention: suppression, stop rules, pause and resume, staff messages and exception resolution | 2B.3; POL-06 (cadence); POL-13 (P2 slice) |
| 2C | `catalyst-v2-7hu.6` | Verify the correspondence loop: reconciliation and health views, the GATE-P2 acceptance run, independent QA and the after-action report | 2B.1 to 2B.4 |

Owner decisions are tracked as notes on the existing policy bead `catalyst-v2-211.7`; no separate
decision bead is created.

| Test range | Task |
|---|---|
| TEST-P2-03, 12 (send side), 25 to 27, 36 to 39 | 2B.1 |
| TEST-P2-01, 07, 12 (fetch side), 13 to 24, 40, 46, 47 | 2B.2 |
| TEST-P2-08 to 10, 32 to 35, 43, 44 | 2B.3 |
| TEST-P2-02, 04 to 06, 11, 28 to 31, 42, 45 | 2B.4 |
| TEST-P2-41, the full acceptance map and the GATE-P2 run | 2C |

## 10. Review record

One independent review by `catalyst-security-privacy` (2026-10-11), read-only, of this document, the
drift edits and the decision brief. It found no blocker and no public-exposure problem, and it confirmed
every claim about existing code (`ledger.py`, `verification.py`, grants, guards, `staff.py`) and every
drift correction. Its findings and their disposition in version 0.2.0:

| Severity | Finding | Disposition |
|---|---|---|
| HIGH | Confirmation tokens would reach inbound storage through quoted replies, auto-replies, bounces and Sent copies (D-24) | Applied: URL scrubbing before storage, no raw for messages matched to a secret-bearing outbound, the invitation excluded from Sent copies, TEST-P2-47 (3.5, A4, section 6) |
| HIGH | Raw mail from anyone stored in full with no deletion path | Applied: raw only for matched mail from the verified sender, size cap, quota, G7 growth signal, POL-10 requirement (3.5, A-9) |
| HIGH | Web process could read raw mail | Applied: INSERT-only grant; TEST-P2-39 asserts no SELECT (3.5) |
| HIGH | Guard change silently amended REQ-022; start-up-only check | Applied: named as an amendment; connect-time peer check; credentials refused for other hosts; loopback versus test-network wording made consistent (section 6, A-4, TEST-P2-40) |
| HIGH | Staff write powers and real mail not tied to MFA | Applied: precondition in 8.2 and F |
| MEDIUM | Forgeable `Authentication-Results`; field name implied authentication | Applied: topmost header, provider stripping listed as unknown, field renamed, explicit fail becomes an exception (C3) |
| MEDIUM | Bounces would fail the sender check | Applied: C0, bounce detection before association and trust |
| MEDIUM | Pause subject of new kinds unspecified | Applied: subject `application` for every per-application automated kind (3.7) |
| MEDIUM | POL-19 (b) not supported by the permission set | Applied: sixth permission `resolve_identity_exception` |
| MEDIUM | Per-message fence is a new ledger mechanism | Applied: `fence(claim)` in A-7; TEST-P2-21 extended |
| MEDIUM | SMTP outcome classes need a custom transport; reclaim rule | Applied: `smtplib` wrapper with a total deadline; reclaim goes to reconcile (A3) |
| MEDIUM | `secret_bearing` left to judgement | Applied: enforced by code and a check; TEST-P2-37 extended |
| MEDIUM | Redaction narrower than stated | Applied: the control is the logging rule; redaction is a backstop; TEST-P2-23 sentinel |
| MEDIUM | Event and item content unconstrained | Applied: identifiers and reason codes only; `note` capped and sanitized (3.8) |
| LOW | Look-alike addresses, untrusted Message-IDs reused outbound, control characters in staff views, bulk admin actions, pause deletion, links in staff messages, unlabelled storage statement | Applied (C2, 3.5, section 6, F, section 3, 3.8) |
| — | Drift: `015` still called the README stale; `006` CI line and source revision stale; `011` P2 row | Applied in those files |

**Re-check (same reviewer).** Eleven HIGH and MEDIUM findings CONFIRMED and H2 PARTIAL; none NOT APPLIED;
no decision stated as approved. Six new errors were reported and fixed in this version:

- the raw-store rule is now decided at ingestion, and the quota has a defined effect (completes H2);
- A-4 amends REQ-022 only; D-10 (hooks and agents never operate the live workflow) is not amended;
- pause and resume have separate permissions, so the six permissions are real names;
- the raw table's primary key is the message link, so the INSERT-only grant works without `RETURNING`;
- section 6 and TEST-P2-17 are aligned with C3;
- section 2 lists the fence and the test-host allowance, the header-injection control names the
  standard-library message policy, the A-6 dedupe key holds a hash, and A-8 and A-9 are in order.
