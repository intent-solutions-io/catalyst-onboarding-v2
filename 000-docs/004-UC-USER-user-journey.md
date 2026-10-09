# User Journey: Catalyst v2 applicant journey, stage by stage

| Field | Value |
|---|---|
| Document | `004-UC-USER-user-journey` |
| Version | 0.2.0 (replaces the seeded template) |
| Status | **PROPOSED.** Stage behaviour becomes binding with the PRD. Every policy reference (`POL-`) is an open owner decision in `011` section 6. |
| Owner | Jeremy Longshore |
| Date | 2026-10-09 |
| Related | `002` (requirements and tests), `003` (components, ADRs), `005` S1 (first slice: J-01 to J-03 only) |
| Classification | Public; synthetic examples only (`example.test` addresses) |

> **Status: PRELIMINARY, subject to review.** Nothing here is implemented. Where a stage depends on an
> open policy, the behaviour shown is the fail-closed default, not an invented policy.

## 1. Conventions used in every stage

- **Transaction boundary.** "One transaction" means one PostgreSQL transaction (`transaction.atomic`).
  External calls (SMTP, IMAP, Documenso, MiniMax, MXroute) never run inside a transaction that holds
  row locks. They run in a worker between a *claim* transaction and a *record result* transaction (ADR-15).
- **Pending action.** Every piece of future system work is a row in the pending-action ledger with a
  kind, a subject, an idempotency key (unique), a due time, attempts (counted at claim), a lease token and
  expiry, and a status (`queued`, `running`,
  `done`, `failed`, `uncertain`, `held`, `cancelled`). The worker claims rows with
  `SELECT ... FOR UPDATE SKIP LOCKED` and complete them with a write fenced by the lease token; all times
  come from the database clock (ADR-03; full rules in `005` S1.4).
- **Paused automation.** When an application's automation is paused (J-09, a pause record in `workflow`),
  the worker leaves its actions untouched until staff resume it.
- **Who owes the next action.** Every stage below names one owner: *system*, *applicant*, *staff*,
  *decision-maker*, *countersigner* or *provider*. Staff views show it on every application (REQ-014).
- **Retries.** Bounded attempts with backoff; the bounds are settings, with no approved numbers yet
  (POL-16). After the last attempt the action becomes `failed` and appears in the staff exception queue.
  Nothing retries forever and nothing is silently dropped.

## 2. Stage state model (proposed)

```text
submitted ──▶ contact_verified ──▶ evidence ──▶ assessing ──▶ awaiting_answers ─┐
                                                   ▲                             │
                                                   └──────── answers received ◀──┘
assessing ──▶ awaiting_decision ──▶ admitted ──▶ agreements ──▶ agreements_complete
          ──▶ provisioning ──▶ active
awaiting_decision ──▶ declined (terminal)      any open stage ──▶ withdrawn | closed (terminal)
awaiting_decision ──▶ on_hold ──▶ awaiting_decision
```

Text inventory: twelve open stages (`submitted`, `contact_verified`, `evidence`, `assessing`,
`awaiting_answers`, `awaiting_decision`, `on_hold`, `admitted`, `agreements`, `agreements_complete`,
`provisioning`, `active`) and three terminal stages (`declined`, `withdrawn`, `closed`). "Open" in a
constraint or rule means any of the twelve, so an `active` person's repeat submission attaches to their
application as an unverified repeat (J-02). The
automation-paused flag is separate from the stage and can be set on any open stage. Transitions only
through service functions that check prerequisites inside the transaction (ADR-13). The stage names are
proposals.

## 3. Stages

### J-01 Intake

- **Trigger and input:** applicant submits the public access-request form (POST). Proposed minimum
  fields: name, email, a short free-text reason. The final field set is open (POL-03).
- **Receives it:** Django web process, `applications` app, service "accept submission".
- **Records:** application (stage `submitted`), submission version 1 (immutable), history event
  "submission received", contact challenge, pending action "send verification".
- **Transaction and next action:** all of the above in one transaction. Next: "send verification" (system).
- **Deterministic checks:** CSRF; request size; required fields; email syntax and normalization
  (lower-cased domain, trimmed); duplicate lookup (J-02). Rate limits at the proxy (P6).
- **LLM:** none.
- **Alternate outcomes:** invalid input re-renders the form with errors, no records. A duplicate goes to
  J-02. A database failure shows an error page and commits nothing; the applicant is told to try again.
  A rate-limited request gets a refusal with no records.
- **Retry, timeout, terminal:** applicant resubmission is safe (J-02). No server-side retry.
- **Next action owner and visibility:** system. Staff see the application as "awaiting verification email".
- **Acceptance:** TEST-S1-01, TEST-S1-02, TEST-S1-05, TEST-S1-16. **References:** REQ-001, REQ-003, REQ-027.

### J-02 Duplicate and concurrent submissions

- **Trigger and input:** a valid submission whose email key matches an open application, or two
  submissions racing (double click, network retry).
- **Receives it:** same service as J-01.
- **Records:** a new submission version on the existing application; history event "repeat submission".
  If the email is unverified: an expired or failed-to-send active challenge is superseded and a new
  challenge and "send verification" action are created; an unexpired one is reused. If the email is
  already verified: the version is marked "unverified repeat", never replaces verified data, and raises a
  staff item (otherwise anyone knowing the address could write into a verified dossier).
- **Transaction and next action:** one transaction. A partial unique constraint (one open application per
  normalized email) decides races; the losing request catches the integrity error inside a savepoint,
  re-reads the winner under `select_for_update`, and attaches. Unique idempotency keys stop duplicate actions.
- **Deterministic checks:** as J-01, plus the open-application lookup.
- **LLM:** none.
- **Alternate outcomes:** (from P5, when terminal stages exist; not reachable in S1) an existing application
  in a terminal stage: the fail-closed default records the submission against it, raises a staff item, and
  creates nothing new until POL-01 and POL-12 are decided. Because the partial unique constraint allows a
  new application after a terminal stage, the service must enforce this before terminal stages ship
  (planned TEST-P5-06, epic P5). A
  repeat whose details conflict with the verified identity raises a staff item; how it is resolved is
  POL-19. The applicant always sees the same response as J-01, so the form does not reveal whether an email is known.
- **Retry, timeout, terminal:** none beyond J-01.
- **Next action owner and visibility:** unchanged from the existing application. Staff see every version.
- **Acceptance:** TEST-S1-03, TEST-S1-04. **References:** REQ-002, REQ-006, REQ-027; POL-01.

### J-03 Email verification

- **Trigger and input:** pending action "send verification"; later, the applicant opens the link (GET)
  and confirms (POST).
- **Receives it:** worker (send); Django web (`applications`, confirmation view).
- **Records:** outbound message (template version, idempotency key, attempts, result); on confirmation:
  application `contact_verified_at`, stage `contact_verified`, history event, pending action
  "start evidence collection" (in the first slice it stays `held`, because P3 does not exist yet).
- **Transaction and next action:** worker claims in one transaction, sends outside it, records the
  result in a second. Confirmation locks the application, then the challenge (`select_for_update`; the same order
  everywhere) and writes everything in one transaction. Next: "start evidence collection" (system).
- **Deterministic checks:** signed token valid; challenge exists, not expired by the database clock, not
  used, not superseded, belongs to this application, email unchanged since issue. GET never changes state, so mail
  scanners that prefetch links cannot confirm. Refused confirmations are logged (redacted) and not written
  to history, so unauthenticated requests cannot grow the dossier.
- **LLM:** none.
- **Alternate outcomes:** expired link shows "this link has expired" and the way to get a new one
  (resubmitting the form issues one via J-02; a dedicated resend page waits for POL-02). A used link shows
  "already confirmed" and changes nothing. A tampered or unknown token shows a generic invalid-link page.
  The applicant never confirms: reminder and closure rules belong to POL-02 and POL-06 (P2). A bounce stops
  sending and raises a staff item (P2).
- **Retry, timeout, terminal:** send attempts are bounded. A crash after the mail server accepted the message
  but before the result was recorded leaves the action `running` with an expired lease; the next claim
  sends the same link again (at-least-once delivery of an identical link; proposed as acceptable for this
  message only). After the last attempt the action is `failed` and visible to staff.
- **Next action owner and visibility:** applicant, after the send. Staff see "awaiting applicant: verify
  email" with the last send time and attempt count.
- **Acceptance:** TEST-S1-06 to TEST-S1-10, TEST-S1-16. **References:** REQ-004, REQ-005, REQ-007, REQ-020;
  ADR-16; POL-02.

### J-04 Evidence collection

- **Trigger and input:** pending action "start evidence collection" after verification.
- **Receives it:** worker; `assessments` app.
- **Records:** one evidence item per source (kind, source reference, retrieved time, checksum, status,
  stored content as data); history events.
- **Transaction and next action:** each fetch runs outside a transaction; each result is recorded in its own.
  When every required item is present or explicitly unavailable: next "run assessment" (system).
- **Deterministic checks (REQ-029):** only sources allowed by POL-03; outbound fetches restricted to approved hosts,
  never private or link-local addresses, with size and time limits (SSRF controls); fetched content is
  stored as untrusted data.
- **LLM:** none.
- **Alternate outcomes:** a source is unreachable: bounded retry, then the item is "unavailable" and the
  stage continues or asks the applicant (J-06), per POL-03. The applicant must supply something: J-06.
- **Retry, timeout, terminal:** bounded per source; a stage that cannot complete goes to the staff queue.
- **Next action owner and visibility:** system, then staff if stuck. Staff see each item and its status.
- **Acceptance:** planned TEST-P3-05 (disallowed host refused), TEST-P3-06 (unavailable source path).
  **References:** REQ-029; POL-03; `003` security model.

### J-05 Assessment, including MiniMax failure

- **Trigger and input:** pending action "run assessment" with the list of evidence items.
- **Receives it:** worker; `assessments` app; a PydanticAI agent using the MiniMax model.
- **Records:** assessment run (provider and model as recorded strings, prompt version, rubric version, input
  evidence references, usage, typed output, validation status), history event.
- **Transaction and next action:** the model call runs outside a transaction; the result is recorded in one.
  Next: questions proposed → J-06; otherwise stage `awaiting_decision`, owner decision-maker.
- **Deterministic checks:** input limited to listed evidence; output validated against the typed schema;
  every cited evidence reference must exist; usage cap per run and per application.
- **LLM (permitted):** summarize evidence against the approved rubric, recommend admit, decline or hold
  with evidence references, and propose clarifying questions. It cannot change the stage, send anything
  on its own authority, or decide.
- **Alternate outcomes:** malformed output: bounded output retries, then `failed`. Provider error or timeout:
  bounded backoff, then `failed`. Usage cap reached: stop, staff item. Evidence that looks like an
  instruction to the model: flag on the run, shown to staff. A failed assessment never becomes a decision:
  the application waits in the staff queue. Whether staff may decide without an assessment is part of
  POL-05.
- **Retry, timeout, terminal:** bounded; `failed` is terminal for the run, not for the application.
- **Next action owner and visibility:** system, then decision-maker or staff. Staff see the run, its
  inputs, output, usage and failures.
- **Acceptance:** planned TEST-P3-01, TEST-P3-02, TEST-P3-03. **References:** REQ-009; D-04; POL-04.

### J-06 Additional answers

- **Trigger and input:** questions proposed by the assessment or added by staff.
- **Receives it:** `assessments` (question records), `correspondence` (sending).
- **Records:** question rows (text, origin model or staff, approval state), outbound message, history
  event; stage `awaiting_answers`, owner applicant.
- **Transaction and next action:** questions and the "send questions" action in one transaction.
- **Deterministic checks:** whether a model-proposed question may be sent automatically, or needs staff
  approval or must come from an approved question bank, is open (POL-04, POL-06). Fail-closed default:
  staff approval required.
- **LLM:** proposes question text only.
- **Alternate outcomes:** answer arrives (J-07) and becomes new evidence; reassessment runs, with a bounded
  number of rounds (POL-04). No answer: reminders (J-08). Partial answer: remaining questions stay open.
  Answer off topic or hostile: staff item.
- **Retry, timeout, terminal:** after the last reminder the application waits in the staff queue with reason "no answer" (POL-06, POL-12).
- **Next action owner and visibility:** applicant; staff see open questions and their age.
- **Acceptance:** planned TEST-P3-07 (answer re-enters assessment once). **References:** REQ-012; POL-04, POL-06.

### J-07 Inbound correspondence correlation

- **Trigger and input:** a collector job polls the MXroute mailbox over IMAP (P2). Deterministic code; no model.
- **Receives it:** worker; `correspondence` app.
- **Records:** inbound message (mailbox, folder, `UIDVALIDITY`, UID unique together; Message-ID; headers;
  body in protected storage), correlation result, mailbox cursor.
- **Transaction and next action:** one transaction per message: insert, associate, mark the question
  answered, cancel the matching reminder by its key, write the event, enqueue processing, then advance the
  cursor last. (The shape came from the workflow specialist's smoke test, `008` section 6.)
- **Deterministic checks:** association by `In-Reply-To` and `References` against our outbound Message-IDs;
  sender must equal the verified address; a per-application reply address is a candidate if MXroute supports
  it (NEEDS VERIFICATION).
- **LLM:** none.
- **Alternate outcomes:** no match: unmatched queue for staff. Sender mismatch: staff item (possible
  spoofing), no automatic effect. Duplicate fetch: unique key makes it a no-op. `UIDVALIDITY` changes:
  resynchronize with de-duplication by Message-ID and raise an operator alert. Mailbox unreachable:
  retry, alert after a bound.
- **Retry, timeout, terminal:** cursor only advances after a committed message, so a crash re-reads safely.
- **Next action owner and visibility:** system; staff see unmatched messages and collector health.
- **Acceptance:** planned TEST-P2-01, TEST-P2-07 (UIDVALIDITY change). **References:** REQ-012; D-06.

### J-08 Reminders, autoresponders and loops

- **Trigger and input:** a reminder action becomes due; or an inbound message is automatic.
- **Receives it:** worker; `correspondence`.
- **Records:** reminder actions keyed by (application, question or challenge, reminder number); outbound
  messages; history events.
- **Transaction and next action:** the reminder claim locks the question row in the same lock order as the
  collector and re-checks that it is still open before creating any outbound row (reply-versus-reminder race).
- **Deterministic checks:** never reply to a message marked `Auto-Submitted` other than `no` (RFC 3834) or
  carrying common auto-reply or bulk markers; delivery-status reports are bounces; maximum reminders and
  quiet hours from POL-06; more than a set number of automatic exchanges in a window stops automation.
- **LLM:** none.
- **Alternate outcomes:** autoresponder: recorded, ignored for reminders, no reply. Bounce: automation
  paused, staff item. Loop detected: automation paused, staff item. Reply arrives while a reminder is
  pending: J-07 cancels the reminder.
- **Retry, timeout, terminal:** after the last reminder the application waits in the staff queue with reason "no response", owner staff.
- **Next action owner and visibility:** applicant, then staff. Staff see reminder history and stop reasons.
- **Acceptance:** planned TEST-P2-02, TEST-P2-04. **References:** REQ-012; POL-06.

### J-09 Human takeover

- **Trigger and input:** staff pause automation on one application, or a stop rule pauses it.
- **Receives it:** staff view (P2), `workflow` service.
- **Records:** a pause record in `workflow` (subject, reason, actor, time); history event. Pending actions
  stay, unclaimed.
- **Transaction and next action:** one transaction. While paused staff may send a manual message, which is
  recorded as staff-authored and sent through the same outbound path.
- **Deterministic checks:** permission (POL-13); the worker checks for a pause inside the claim transaction.
- **LLM:** none.
- **Alternate outcomes:** resume: an explicit staff action; due reminders that went stale while paused
  are cancelled, not burst-sent.
- **Retry, timeout, terminal:** no automatic timeout: a paused application waits for staff. Staleness is
  surfaced, not acted on: the queue sorts by pause age, and an age threshold for highlighting is part of
  POL-16.
- **Next action owner and visibility:** staff; a "paused" queue shows reason and age.
- **Acceptance:** planned TEST-P2-05, TEST-P2-06. **References:** REQ-013, REQ-014.

### J-10 Qualification decision

- **Trigger and input:** application in `awaiting_decision`; a decision-maker records admit, decline or hold.
- **Receives it:** focused staff view; `applications` service.
- **Records:** decision (outcome, actor, reason, referenced assessment run, time), history event. Admit:
  next "issue first agreement". Decline: next "send decline message" (approved template, POL-06), stage
  `declined`. Hold: stage `on_hold`, owner staff.
- **Transaction and next action:** one transaction with the application locked.
- **Deterministic checks:** actor holds the decision permission defined by POL-05; prerequisites met
  (verified contact, assessment complete or an authorized waiver if POL-05 allows one).
- **LLM:** the recommendation is shown, labelled advisory, beside the evidence. It is never pre-selected.
- **Alternate outcomes:** until POL-05 is decided no account holds the permission, so the stage cannot be
  passed. Reversal or appeal follows POL-05.
- **Retry, timeout, terminal:** no retry (a human act). No automatic timeout: an undecided application
  waits in the decision queue, sorted by age. Decline is terminal unless POL-12 allows reopening.
- **Next action owner and visibility:** decision-maker; staff see a decision queue with age.
- **Acceptance:** planned TEST-P3-04. **References:** REQ-008, REQ-010; POL-05.

### J-11 First agreement (the owner's journey names the NDA)

- **Trigger and input:** action "issue first agreement" after admission. Which agreement comes first is
  set by the inventory (POL-07); the owner's journey names the NDA first and the User Agreement after it.
- **Receives it:** worker; `agreements` app; Documenso API (installed version NEEDS VERIFICATION; the
  public API is v2 with envelopes, `008` section 2).
- **Records:** agreement instance (type, template version, idempotency key, envelope reference),
  recipients (role, order, required), observations (source webhook or poll, provenance, time), events.
- **Transaction and next action:** the instance and its key are committed before the provider call; the
  envelope reference is recorded after it. If the response is lost, the next attempt first looks up the
  envelope by its external reference (support NEEDS VERIFICATION) instead of creating a second one.
- **Deterministic checks:** completion requires every required recipient complete, confirmed by a fresh
  provider read at the moment of use, not by one webhook. Webhook signatures verified.
- **LLM:** none.
- **Alternate outcomes:** a recipient declines: automation paused, staff item. A participant does not sign
  before the envelope expires: reminders follow POL-06, and at expiry the instance is marked expired and a
  staff item is raised; reissue or closure follows POL-08 and POL-12, never an automatic re-send. Webhook lost: periodic reconciliation read. One of two signatures present: waiting,
  owner shown as the missing participant. Provider down: bounded retry, then staff.
- **Retry, timeout, terminal:** bounded; uncertain creation is reconciled, never blindly retried.
- **Next action owner and visibility:** applicant or countersigner named; staff see each participant's state.
- **Acceptance:** planned TEST-P4-01, TEST-P4-02, TEST-P4-03. **References:** REQ-005, REQ-008, REQ-011;
  POL-07, POL-08.

### J-12 User Agreement and other required agreements

- **Trigger and input:** the previous agreement verified complete and stored (J-13); the inventory says
  which agreement is next (POL-07). Any "required details" the agreements need are collected first (field
  list open, POL-18).
- **Receives it:** worker; `agreements`; Documenso, as J-11.
- **Records:** one agreement instance per agreement in the inventory, with its recipients and
  observations; the required-details submission (POL-18) linked to the instance that needed it.
- **Transaction and next action:** as J-11, per agreement. Next: the following agreement in the inventory,
  or, after the last one, the provisioning prerequisites check (J-14).
- **Deterministic checks:** the next agreement is never issued while an earlier required one is incomplete
  or not in custody (REQ-008); required details present and recorded before the agreement that needs them
  (REQ-030).
- **LLM:** none.
- **Alternate outcomes:** as J-11 (decline, expiry, lost webhook, partial signatures, provider down). Required
  details missing: the applicant is asked through the correspondence loop (J-06 pattern), and the agreement
  waits.
- **Retry, timeout, terminal:** as J-11.
- **Next action owner and visibility:** as J-11; staff see the agreement sequence and position.
- **Acceptance:** planned TEST-P4-01, TEST-P4-05. **References:** REQ-008, REQ-011, REQ-030; POL-07,
  POL-08, POL-18.

### J-13 Document custody and retrieval

- **Trigger and input:** completion verified (J-11, J-12).
- **Receives it:** worker; `agreements`.
- **Records:** stored document (storage key, SHA-256, size, source envelope, retrieved time), history
  event; an access record for every retrieval.
- **Transaction and next action:** download outside a transaction; store; record in one transaction. The
  agreement counts as executed only after the stored copy is recorded.
- **Deterministic checks:** checksum recorded and re-verified on retrieval; storage location and
  encryption per POL-09; never public media, never the repository.
- **LLM:** none.
- **Alternate outcomes:** download fails: retry, then staff. Checksum mismatch: staff item. Storage
  unavailable: the custody gate stays closed. Who distributes copies to the applicant (Documenso or
  Catalyst) NEEDS VERIFICATION on the installed version.
- **Next action owner and visibility:** system; staff retrieve through an authorized, audited view only.
- **Acceptance:** planned TEST-P4-04. **References:** REQ-011; POL-09.

### J-14 Provisioning

- **Trigger and input:** every required agreement executed and stored, required details complete, and
  an authorized provisioning approval (POL-11).
- **Receives it:** worker; `provisioning` app; MXroute (provisioning interface NEEDS VERIFICATION; if no
  usable interface exists, the fallback is an operator task with a recorded checklist in the staff view).
- **Records:** provisioning request (address, idempotency key, status), history events.
- **Transaction and next action:** request committed before the call; result recorded after. Uncertain
  outcome: check whether the mailbox exists before any retry. Next: "verify provisioning".
- **Deterministic checks:** address within approved naming rules (POL-11); prerequisites rechecked inside
  the transaction. Initial credentials are never written to history, logs or email bodies; how they reach
  the applicant is open (POL-11).
- **LLM:** none.
- **Alternate outcomes:** address conflict: staff. Provider failure: bounded retry, then staff.
- **Next action owner and visibility:** system, then staff if stuck.
- **Acceptance:** planned TEST-P5-01, TEST-P5-02. **References:** REQ-005, REQ-016; POL-11.

### J-15 Activation

- **Trigger and input:** provisioning verified by a check, not by the request's success alone.
- **Receives it:** worker; `provisioning`, `correspondence`.
- **Records:** welcome message, stage `active`, history event; remaining pending actions closed.
- **Transaction and next action:** one transaction; no further automatic actions.
- **Deterministic checks:** provisioning verified; no open prerequisite.
- **LLM:** none.
- **Alternate outcomes:** welcome bounces: staff item.
- **Retry, timeout, terminal:** the welcome send uses bounded retries, then `failed` for staff; `active` is
  the journey's end state (still "open" for duplicate handling).
- **Next action owner and visibility:** none (complete); staff see the full dossier from first contact.
- **Acceptance:** planned TEST-P5-03, TEST-P5-04. **References:** REQ-001, REQ-017.

### J-16 Withdrawal, closure and recovery

- **Trigger and input:** applicant asks to withdraw (proposed: an explicit confirmation page reached from a
  link; an emailed "withdraw" reply goes to staff, never to a model); staff close; or a no-response timeout
  under POL-12.
- **Receives it:** `applications` service; staff view.
- **Records:** stage `withdrawn` or `closed`, actor, reason, history event; pending actions `cancelled`.
- **Transaction and next action:** one transaction. In-flight envelopes and provisioned access are handled
  per POL-08 and POL-11 (proposed: staff item, no automatic voiding until decided).
- **Deterministic checks:** permission for staff closure (POL-13).
- **LLM:** none.
- **Alternate outcomes:** reopening, and whether a new application is created, follow POL-01 and POL-12.
  System recovery (crashes, restarts) is not this stage: it is covered by the pending-action ledger
  (REQ-004); staff recover a `failed` or `uncertain` action by retry, reconcile or abandon, each audited (P2).
- **Retry, timeout, terminal:** terminal stages keep history under POL-10.
- **Next action owner and visibility:** none, or staff for in-flight items.
- **Acceptance:** planned TEST-P5-05. **References:** REQ-018; POL-01, POL-10, POL-12.
