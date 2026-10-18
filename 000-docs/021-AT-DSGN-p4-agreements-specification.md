# P4 Agreements Specification (handoff 4A)

| Field | Value |
|---|---|
| Document | `021-AT-DSGN-p4-agreements-specification` |
| Version | 0.7.0 (0.2.0 approved, D-37; section 15: the installed-version check and 4B.1, D-38; section 16: 4B.2, D-39; section 17: the recovery corrections and the owner decisions D-40 to D-44; section 18: 4B.3; section 19: 4C, the GATE-P4 run, awaiting the owner) |
| Status | **APPROVED by the owner 2026-10-17 (version 0.2.0; D-37 in `011` section 4), with the recommended defaults `P4-D-1` to `P4-D-20` for synthetic P4.** 4B.1 to 4C each need their own release; the read-only Documenso version check (P4-D-2) needs its own authorization. No real envelope, agreement text, real data or deployment is authorized. |
| Owner | Jeremy Longshore |
| Date | 2026-10-17 |
| Epic | P4, "Issue and verify the NDA, User Agreement and other required agreements through Documenso with protected custody" (`catalyst-v2-hdg`); this task is `catalyst-v2-hdg.1` |
| Baseline | main `da1e6e0` (P3 accepted, D-36) |
| Builds on | `004` J-11, J-12, J-13; `002` REQ-005, REQ-008, REQ-011, REQ-030, REQ-031, REQ-032; `003` ADR-05, ADR-14, ADR-15; `011` D-05, D-15, D-27, D-36; `016` A3 to A6 (uncertain sends); `018` section 7 (the held `issue_nda` hand-off) |
| Classification | Public; synthetic data only; no agreement text, real template, real recipient or provider credential |

## 0. How to read this document

A fresh engineer should be able to answer, from this document alone: which agreements an admitted applicant
signs and in what order; how an envelope is created without ever creating two; how Catalyst knows an agreement is
complete; how the signed document is kept; who may see it; and what happens when anything fails.

Fact tags: **DOCUMENTED** (an official Documenso page says so; URL and access date 2026-10-17), **INSPECTED** (read
in this repository), **PROPOSED** (this document's design), **NOT VERIFIED** (unknown for the installed Documenso
version; a named task must establish it before code depends on it).

## 1. Scope and boundaries

**In scope (synthetic P4):** the agreement records; the envelope lifecycle per J-11 to J-13 against a **local fake
Documenso** (the P2 pattern of isolated test servers, D-28); reconciliation of uncertain provider outcomes (ADR-15,
D-27); completion verification by a fresh provider read; custody as a separate fact; required details (POL-18);
the staff agreement screen; the held hand-off to P5.

**Out of scope:** the real Documenso installation (no request, no credential, no webhook from it) until a separate
authorization; real agreement text and templates (POL-07 with counsel); the decline message (the held
`send_decline` action from 3B.4 stays held: it needs an approved POL-06 template, see P4-D-12); provisioning (P5);
deployment and public webhook exposure (P6).

**Designed on Documenso API v2 envelopes only.** The documents and templates endpoints and API v1 are deprecated,
with removal stated for 1 March 2027 (DOCUMENTED,
[migrate to envelopes](https://docs.documenso.com/docs/developers/api/migrate-to-envelopes)). The installed version
and whether it serves the envelope endpoints are **NOT VERIFIED** (P4-D-2).

## 2. Starting point from P3 (INSPECTED)

An `admit` decision (`018` section 7, 3B.4) creates exactly one held action `issue_nda:<application public ref>` (the
key 3B.4 builds; `018` writes it `issue_nda:<application>`) whose
`input_ref` is the decision's public id. Held actions are never claimed by the worker. P4 releases it through a
versioned, owner-run activation command (the 3B.1 pattern), and only for applications still `admitted`, not paused,
with that decision unchanged. Nothing in P4 reads the model's assessment.

## 3. Records (`agreements` app, ADR-01) — PROPOSED

| Record | Holds | Protection |
|---|---|---|
| `AgreementType` | the inventory: key (`nda`, `user_agreement`, …), order, required flag, the gate it must pass before the next type (signing only, or signing and custody) | owner-approved configuration; changes are new versions |
| `AgreementTemplateVersion` | the type, the Documenso template reference, version number, digest of the synthetic PDF, approval (owner, and counsel where POL-07 says), status | an approved version is never edited (the P2 template pattern) |
| `AgreementInstance` | the application, type, template version, a minted opaque `external_key`, the envelope id once known, `issue_status`, `signing_status`, `custody_status`, timestamps | status columns only are updatable; one live instance per (application, type) |
| `AgreementRecipient` | the instance, role (`SIGNER`, `APPROVER`, `VIEWER`, `CC`), signing order, required flag, who (the applicant's verified address, or a named staff countersigner) | insert-only |
| `ProviderObservation` | the instance, source (`webhook` or `read`), envelope status, each recipient's signing status, provider response digest (of the allowlisted fields only), observed time | append-only; unique on (envelope, source event, recipient, status), so an exact duplicate is a no-op and a replay with a changed status is a new, harmless row |
| `StoredDocument` | the instance, storage key, SHA-256, size, the provider item id, retrieved time, re-verified time | insert-only; bytes never in the database or the repository |
| `DocumentAccess` | every staff retrieval: who, when, which document, why | append-only |
| `RequiredDetails` | a versioned submission of the details an agreement needs (POL-18), linked to the instance | follows the S1 submission-version rules |

**How the protections are enforced** (ADR-14, D-17 pattern; enforced in the database, not only in services):

- `ProviderObservation`, `StoredDocument` and `DocumentAccess` are protected history: insert-only grants for the
  application role plus the append-only and no-truncate triggers. `AgreementRecipient` is insert-only.
- `AgreementTemplateVersion`: only its approval columns are updatable, and only while it is a draft.
- A partial unique index allows one live instance per (application, type) (live = not `superseded`, `cancelled`).
- **D-15 backstop:** a trigger refuses inserting a `user_agreement` instance unless the application's `nda`
  instance is `signing_complete_verified` (the 3B.4 backstop pattern). Tests bypass the services to prove each of
  these.
- `RequiredDetails` is personal data: field-level protection is a POL-18 and POL-10 decision; it is never logged.

The three statuses are separate facts and never derive from one another (names as in `004` J-11 to J-13):

- `issue_status`: `held` → `create_pending` → `created` (draft exists) → `distribute_pending` → `issued`; side states
  `create_uncertain`, `distribute_uncertain`, `failed_needs_staff`, `cancelled`, `superseded`.
- `signing_status`: `not_started` → `partially_signed` (some required recipients signed) → `signing_complete_observed` (a
  webhook or read claims completion) → `signing_complete_verified` (a fresh read confirms every required recipient signed);
  side states `declined` (Documenso `REJECTED`), `expired`, `cancelled`.
- `custody_status`: `not_due` → `pending` → `stored_verified`; side states `failed_retry_pending`,
  `failed_needs_staff`.

## 4. The P4 journey, step by step — PROPOSED

Lock order everywhere: application, then the instance, then the pending action. Provider calls run between a
claim transaction and a fenced record transaction, never under a domain lock (as P2 and P3).

| # | Step | Trigger | Records and transaction | Outcomes | Recovery | Acceptance |
|---|---|---|---|---|---|---|
| 1 | Release the NDA | the activation command releases `issue_nda` | stage `admitted → agreements` (compare-and-set); the `nda` instance with its minted `external_key` and its recipients, committed **before** any provider call; action `create_agreement` | created; refused (stage changed, paused) | refusal leaves the action held | TEST-P4-09 |
| 2 | Create the draft envelope | `create_agreement` (not redeliverable) | call `envelope/use` from the approved template with `externalId = external_key` and **`distributeDocument: false`**; record the envelope id | `created`; `create_uncertain` | uncertain → reconcile (section 5), never a blind retry | TEST-P4-03, 10, 11 |
| 3 | Distribute | `distribute_agreement` (not redeliverable) | Documenso, not P2, will email the applicant, so the P2 send checks run here: the recipient still equals the currently verified address, the application is not paused, no hard-bounce block applies (else refused, staff item). Then re-read: already `PENDING` → `issued`; else `envelope/distribute`; record | `issued`; `distribute_uncertain`; refused | uncertain → wait a settle window, re-read; still unknown → decision-maker | TEST-P4-12, 25 |
| 4 | Observe | a webhook, or the reconciliation sweep | an observation; a webhook only enqueues a fresh read (`read_agreement`) | progress recorded | duplicates are no-ops; out-of-order events are harmless | TEST-P4-08, 13, 14 |
| 5 | Verify completion | `read_agreement` | fresh `GET envelope/{id}`: envelope `COMPLETED` **and** every required recipient `SIGNED` **and** the provider's recipient set and emails equal the local `AgreementRecipient` rows (a recipient added or swapped in the provider's interface fails) **and** envelope id and `externalId` match (template identity on the read is NOT VERIFIED) → `signing_complete_verified` | verified; still in progress; rejected; cancelled | a read failure retries (bounded), then staff | TEST-P4-01, 02, 15, 16 |
| 6 | Custody | `signing_complete_verified` | download outside any transaction; store; re-read and compare SHA-256; record `stored_verified` in one transaction | stored; failed | bounded retry, then `failed_needs_staff`; **signing stays verified** | TEST-P4-04, 07, 17 |
| 7 | Next agreement | the previous type passed its gate | a fresh read of the previous envelope immediately before issuing (REQ-011 "at the moment of use"), then the next type's instance (step 1 again); D-15: the User Agreement is never created, linked or shown before the NDA is `signing_complete_verified` (and custody, if the gate says so) | next issued; waiting for required details | details missing → asked through P2 (J-06 pattern) | TEST-P4-05, 06, 18 |
| 8 | Hand off to P5 | the last required type passed its gate | stage `agreements → agreements_complete`; one held `provision:<application>` action | held hand-off | no P5 action runs | TEST-P4-19 |

**Alternate outcomes (each a staff item, no automatic re-send):** a recipient rejects → `declined`, automation
paused; the envelope expires → `expired`; staff cancel → `cancelled`; the provider rate-limits (429 with
`Retry-After`, DOCUMENTED, [rate limits](https://docs.documenso.com/docs/developers/api/rate-limits)) → retry after
that time within the attempt bound; the provider is down → bounded retry, then staff. Reissue after a rejection,
expiry or cancellation is a decision-maker act that creates a new instance and marks the old one `superseded`.

**Cancelling is an external operation.** A local `cancelled` or `superseded` instance is only safe once the envelope
is voided at the provider (`POST /envelope/cancel`, PENDING envelopes only, DOCUMENTED,
[documents](https://docs.documenso.com/docs/developers/api/documents)). Cancel therefore runs as its own action with
`cancel_pending` and `cancel_uncertain` and the section 5 reconciliation. A completion observed on a superseded or
cancelled instance is never verified and never dropped: it opens a staff item.

**Withdrawal, closure or a hold during `agreements`** (POL-12): every live envelope is cancelled as above; no
further agreement is issued; the stage moves only through the POL-12 services (P5).

## 5. Uncertain outcomes: never two envelopes — PROPOSED

`externalId` is optional at creation and editable only while the envelope is a draft (DOCUMENTED,
[documents](https://docs.documenso.com/docs/developers/api/documents)); the documentation states **no** uniqueness,
lookup or idempotency for it (NOT VERIFIED). Duplicate prevention therefore rests on Catalyst's own action key, as in
P2 (D-27, `016` A3 to A6):

- The instance and its `external_key` (opaque; no applicant data) are committed before the call.
- A lost response (timeout, 5xx, crash after the request) makes the step `create_uncertain`. It is **not** retried.
- `reconcile_agreement` looks for admissible evidence: an envelope carrying our `external_key` (by lookup if the
  installed version supports it; otherwise a bounded listing matched on `externalId`, template and recipient), and
  nothing else. Found → `created` with that envelope id.
- The listing for reconciliation is bounded (a time window around the attempt and a page limit).
- No admissible evidence by the deadline → the outcome stays unknown and a staff item opens. Only a decision-maker
  may decide (the P2 rule): mark it not sent and allow one new create, or abandon. The screen shows the duplicate
  risk. A staff decision never rewrites an unknown outcome into a known one.
- **A late orphan.** A second create always mints a **new** `external_key`. The sweep keeps looking for the old one;
  a late match is never verified: it opens a staff item and is cancelled at the provider (as in section 4).
- Distribute is a separate step so the draft's `externalId` is fixed before anything is sent; a repeat distribute is
  avoided by re-reading the status first (repeat-distribute behaviour NOT VERIFIED).

## 6. Webhooks and polling — PROPOSED

Webhooks are **hints**, never proof:

- Authentication: the installed version's documented mechanism. The current documentation describes a plain shared
  secret in the `X-Documenso-Secret` header, not a signature, with no timestamp or replay protection (DOCUMENTED,
  [webhook verification](https://docs.documenso.com/docs/developers/webhooks/verification)); compare in constant time;
  an empty or wrong secret is refused with no detail. The installed mechanism is NOT VERIFIED.
- A valid webhook records an observation and enqueues a `read_agreement` under a unique per-instance key, so a read
  is coalesced while one is pending, with a per-instance minimum read interval. A leaked or replayed secret
  therefore cannot flood the queue or drain the provider's rate limit.
- The webhook routes by the stored `external_key`; an unknown key gets the same 2xx as a known one, so nothing is
  revealed. Request size is capped. The view alone is exempt from CSRF. Bodies and headers are never logged.
- The secret can be rotated with two secrets valid during the overlap (P4-D-17).
- The route is not mounted outside the test and development settings until the P6 exposure decision. Webhooks "may be retried",
  must be answered with a 2xx within 10 seconds, and have no documented order (DOCUMENTED,
  [events](https://docs.documenso.com/docs/developers/webhooks/events)).
- A reconciliation sweep reads every `issued` instance on a schedule, so a lost webhook only delays completion.
- `signing_complete_verified` comes only from a fresh read (step 5), at the moment of use (REQ-011).
- The webhook endpoint is public-facing in production (a P6 deployment decision); in synthetic P4 it is exercised
  only by the fake server in tests.

**Signing links never leave the adapter.** Envelope reads and webhook payloads may carry per-recipient signing
tokens or links (`envelope/use` returns `signingUrl` and `token`, DOCUMENTED,
[templates](https://docs.documenso.com/docs/developers/api/templates); in reads and webhooks NOT VERIFIED). They act as
the applicant's credential. Provider responses are parsed into an allowlist of fields; a token or signing link is
never stored, logged, digested in a way that could be reversed, or rendered on any screen.

## 7. Custody — PROPOSED (POL-09 decides the production rules)

- The signed file is downloaded from the envelope item (`GET /envelope/item/{id}/download`, named on the
  [migration page](https://docs.documenso.com/docs/developers/api/migrate-to-envelopes); whether it returns the sealed
  PDF only after completion is NOT VERIFIED), stored outside the web root and outside the repository, hashed by
  Catalyst (Documenso documents no checksum), and re-read to compare before `stored_verified`.
- Synthetic P4 stores into a test-only directory created per test run.
- A custody failure never changes `signing_status`, never re-signs and never issues anything. Whether progression
  waits for custody is the type's gate (P4-D-6).
- Staff retrieve a document only through an audited view. The `DocumentAccess` row is written before any byte is
  released, and a failed audit write means no release; denied attempts are recorded too; the stated reason is
  length-capped, escaped and never logged.
- Every retrieval re-hashes the stored file; a mismatch refuses the retrieval and opens a staff item.
- Served as an attachment, `Content-Type: application/pdf` with `nosniff`, never inline and never public media; the
  storage key is system-generated (no path from user input); file permissions are restrictive; encryption at rest
  is a POL-09 decision.
- Limit, stated: the re-download comparison proves the stored copy matches what was transferred, not that the
  provider's copy was never altered.
- **The provider keeps its own copy** of the signed document and the recipients' data, outside `DocumentAccess`.
  Whether and when Catalyst asks the provider to delete it after custody is verified is a POL-10 decision
  (P4-D-15); under D-17 nothing is deleted until POL-10 is recorded.

## 8. Required details (POL-18) — PROPOSED

The fields an agreement needs, when they are collected and who may see them are POL-18. Synthetic default: no extra
details for the synthetic NDA and User Agreement. When an agreement type needs details, the applicant is asked
through the P2 question loop, the answer is recorded as a versioned submission, and the agreement waits until it is
adopted. Visibility is limited to the roles POL-18 names.

## 9. The staff experience — PROPOSED

One agreement screen per application (permission-gated like the P2 and P3 screens):

- the sequence of types with each instance's issue, signing and custody status shown separately, and who owes the
  next step ("Signing: complete, verified; Custody: failed, retry pending; Next: blocked by the custody gate");
- each recipient's role, order and status;
- the observations behind each status, with source and time;
- actions, each a one-object POST to one service: reconcile an uncertain step (decision-maker), cancel and reissue
  (decision-maker), retry custody (operator), retrieve a document (named role; audited), resolve agreement staff
  items.

New permissions are assigned to no group by migration except where `011` POL-13 already maps a role.

## 10. Security and privacy summary

| Control | Status |
|---|---|
| Real Documenso host refused outside an authorized environment; a test-only fake server pinned like the P2 mail servers | PROPOSED (a start-up guard, as `config.guards` for mail) |
| The provider client: a host and port allowlist with a connect-time peer check (as `016`), no redirect off the allowed host, TLS verification, a response size cap, a timeout, and a `%PDF` check on downloads | PROPOSED |
| Provider credentials only in SOPS-managed secrets, never in settings or logs; none configured in P4; the API key and the webhook secret separate; least-privilege API scope where the installed version allows it; never in exceptions, `repr` or fake-server fixtures; the start-up guard refuses any credential variable outside an authorized environment | PROPOSED |
| What leaves for Documenso: recipient name and verified email, the approved template reference, the opaque `external_key`, no custom message; provider payloads (names, emails) are never logged | PROPOSED |
| Fake-server fixtures are synthetic, never copied from real Documenso responses | PROPOSED |
| `external_key` opaque; no name, email or reference to the applicant | PROPOSED |
| Webhook secret compared in constant time; refusals give no detail; replay harmless because a webhook only triggers a read | PROPOSED |
| Signed documents never public media, never in the repository or database; checksum re-verified on every retrieval | PROPOSED (REQ-032; POL-09 for location and encryption) |
| Every retrieval audited | PROPOSED |
| No agreement text in this public repository; tests use synthetic placeholder PDFs | OWNER-DECIDED (REQ-019) |
| Staff MFA and network restriction | GATE-STAGING (POL-13, POL-14) |

## 11. Owner decisions brief (recommendations, not decisions)

| # | Decision | Recommended | Alternative | Earliest blocking task |
|---|---|---|---|---|
| P4-D-1 | POL-07 inventory for synthetic P4 | two types: `nda` then `user_agreement`, synthetic placeholder PDFs; real inventory and text with counsel later | add other agreements now | 4B.1 |
| P4-D-2 | Documenso API generation | v2 envelopes only; before 4B.1, a read-only check of the installed version and its OpenAPI schema, authorized separately | design on the deprecated documents API | 4B.1 |
| P4-D-3 | POL-08 roles and order | the applicant as the only required `SIGNER` for synthetic P4; a company countersigner as a second `SIGNER` (order 2) once POL-08 names one | countersign from day one | 4B.1 |
| P4-D-4 | Creation and distribution | `envelope/use` from an approved template as a draft, then a separate distribute | create and distribute in one call (cannot fix `externalId` first) | 4B.1 |
| P4-D-5 | Completion learning | webhook as a hint plus a reconciliation sweep; completion only from a fresh read | polling only | 4B.2 |
| P4-D-6 | POL-09 custody gate | the next agreement waits for `stored_verified` as well as `signing_complete_verified` (fail-closed) | signing only | 4B.3 |
| P4-D-7 | POL-09 storage for synthetic P4 | a test-only directory; production location, encryption and retention decided before GATE-PILOT | — | 4B.3 |
| P4-D-8 | Uncertain create with no evidence | staff decision-maker: mark not sent and allow one new create, or abandon | automatic retry | 4B.1 |
| P4-D-9 | Rejection, expiry, cancellation | staff item and pause; reissue only by a decision-maker as a new instance | automatic reissue | 4B.2 |
| P4-D-10 | Reminders and expiry | follow POL-06 values, none in synthetic P4 | provider defaults | 4B.2 |
| P4-D-11 | POL-18 required details | none for the synthetic types | collect details now | 4B.3 |
| P4-D-12 | The held decline message (`send_decline`) | stays held until a POL-06 decline template is approved; not part of P4 | send it in P4 | none |
| P4-D-13 | Activation of held `issue_nda` | an owner-run, versioned activation command with an approval reference (the 3B.1 pattern) | release automatically | 4B.1 |
| P4-D-14 | Who sends the applicant the signed copy (`004` J-13 left it open) | Documenso's completion email to the recipients (no Catalyst send); Catalyst keeps custody only | Catalyst sends it through P2 | 4B.3 |
| P4-D-15 | POL-10 for the provider's copy | keep it until POL-10 is recorded (D-17); options then: no deletion, delete after custody is verified, or a fixed retention period | delete now | GATE-PILOT |
| P4-D-16 | POL-08 and POL-09 roles | the countersigner role unfilled in synthetic P4; document retrieval limited to decision-makers | wider retrieval | 4B.3 |
| P4-D-17 | Webhook secret rotation and production exposure | two secrets valid during rotation; the route mounted in production only at the P6 deployment decision | — | 4B.2; P6 |
| P4-D-18 | Cancel at the provider | cancel as its own reconciled action; a completion on a superseded or cancelled instance goes to staff | local cancel only | 4B.2 |
| P4-D-19 | A late orphan envelope | a new key on every new create; a late match of the old key is cancelled and goes to staff, never verified | — | 4B.1 |
| P4-D-20 | Withdrawal, closure or hold during `agreements` | cancel every live envelope; no further agreement; stage moves only through POL-12 services | leave envelopes live | 4B.2 |

## 12. Acceptance plan

TEST-P4-01 to TEST-P4-08 keep their meaning from `002` and `004`; new cases continue from TEST-P4-09. All run in CI
against the local fake Documenso (proof A); none touches a real installation.

| Case | Proves | Built in |
|---|---|---|
| TEST-P4-01 | no next agreement before the previous one passed its gate | 4B.2 |
| TEST-P4-02 | completion needs a fresh provider read at the moment of use | 4B.2 |
| TEST-P4-03 | a duplicate create is never sent; one envelope per instance | 4B.1 |
| TEST-P4-04 | checksum recorded and re-verified; custody stored outside the database and repository | 4B.3 |
| TEST-P4-05 | an agreement waits for its required details; visibility limited to named roles | 4B.3 |
| TEST-P4-06 | the User Agreement is neither shown, linked nor created before NDA `signing_complete_verified` | 4B.2 |
| TEST-P4-07 | a custody failure leaves signing verified, issues nothing, and blocks only under the custody gate | 4B.3 |
| TEST-P4-08 | webhook authentication: a missing or wrong secret is refused, compared in constant time | 4B.2 |
| TEST-P4-09 | activation releases only eligible held `issue_nda` rows, versioned, with events | 4B.1 |
| TEST-P4-10 | the instance and its key are committed before any provider call | 4B.1 |
| TEST-P4-11 | an uncertain create reconciles on admissible evidence, else goes to a decision-maker; never a blind retry | 4B.1 |
| TEST-P4-12 | distribute re-reads first; an uncertain distribute reconciles without a second send | 4B.1 |
| TEST-P4-13 | duplicate and out-of-order webhooks are no-ops; a webhook alone never verifies | 4B.2 |
| TEST-P4-14 | a lost webhook is caught by the reconciliation sweep | 4B.2 |
| TEST-P4-15 | partial signing, rejection, expiry and cancellation each reach the right status and a staff item | 4B.2 |
| TEST-P4-16 | a read showing another template, envelope or `externalId` never verifies | 4B.2 |
| TEST-P4-17 | every document retrieval is audited; access needs its permission | 4B.3 |
| TEST-P4-18 | 429 with `Retry-After` is honoured within the attempt bound; provider down goes to staff (create and distribute in 4B.1; reads in 4B.2) | 4B.1, 4B.2 |
| TEST-P4-19 | after the last gate: `agreements_complete` and one held provisioning action, nothing more | 4B.3 |
| TEST-P4-20 | a real Documenso host and credentials are refused outside an authorized environment | 4B.1 |
| TEST-P4-21 | the staff screen shows the three statuses separately; actions need their permissions; hostile text escaped | 4B.3 |
| TEST-P4-22 | a pause stops every automated agreement action; resume reschedules without a burst (create and distribute in 4B.1; the rest in 4B.2) | 4B.1, 4B.2 |
| TEST-P4-23 | webhook flooding is harmless: reads coalesce per instance with a minimum interval; an unknown key gets the same 2xx; size capped; nothing logged | 4B.2 |
| TEST-P4-24 | signing tokens and links from the provider are never stored, logged or rendered (the fake returns them) | 4B.1, 4B.2 |
| TEST-P4-25 | distribute refuses when the recipient is no longer the verified address, the application is paused or a hard bounce blocks it | 4B.1 |
| TEST-P4-26 | protected history, one live instance per type and the D-15 database backstop hold for every role, bypassing services | 4B.1 |
| TEST-P4-27 | retrieval: audit written before release, denied attempts recorded, a checksum mismatch refuses and opens a staff item, served as an attachment | 4B.3 |
| TEST-P4-28 | the provider client refuses redirects off host, oversize responses, bad TLS and non-PDF downloads | 4B.1 |
| TEST-P4-29 | cancel is reconciled at the provider; a completion on a superseded or cancelled instance goes to staff, never verified | 4B.2 |
| TEST-P4-30 | a late orphan envelope (the old key) is never verified, is cancelled and opens a staff item | 4B.1 |
| TEST-P4-31 | the next agreement waits for a fresh read at the moment of issue; a recipient set changed at the provider never verifies | 4B.2 |
| TEST-P4-32 | withdrawal, closure or a hold during `agreements` cancels every live envelope and issues nothing more | 4B.2 |

## 13. Build slices (4B) and verification (4C)

| Key | Scope | Depends on |
|---|---|---|
| 4B.1 | records, migrations and their database protections; the fake Documenso server; the hardened client and guards; the activation command; create and distribute with reconciliation and the P2 send checks; TEST-P4-03, 09 to 12, 18, 20, 22, 24 to 26, 28, 30 | 4A approval; P4-D-1 to P4-D-4, P4-D-8, P4-D-13; the read-only version check (P4-D-2) |
| 4B.2 | webhook endpoint, observations, the reconciliation sweep, completion verification, the D-15 sequence, decline, expiry, cancellation at the provider, withdrawal during agreements; TEST-P4-01, 02, 06, 08, 13 to 16, 18, 22 to 24, 29, 31, 32 | 4B.1; P4-D-5, P4-D-9, P4-D-10 |
| 4B.3 | custody and retrieval, required details, the staff agreement screen, the P5 hand-off; TEST-P4-04, 05, 07, 17, 19, 21, 27 | 4B.2; P4-D-6, P4-D-7, P4-D-11 |
| 4C | the GATE-P4 run (a P4 acceptance map), one independent QA review, the after-action report | 4B.1 to 4B.3 |

## 14. Review record

**Independent security and privacy review** (`catalyst-security-privacy`, version 0.1.0, 2026-10-17): no blocker;
8 HIGH, 9 MEDIUM, 5 LOW. All applied in 0.2.0:

- **Webhook flooding.** Coalesced reads, a minimum interval, uniform 2xx, size cap, CSRF scope, no logging and
  rotation (section 6).
- **Signing tokens.** Never stored, logged or shown (section 6).
- **Provider-sent email.** It runs the P2 send checks at distribute (step 3).
- **Database protections.** Protected history, the live-instance index and the D-15 backstop (section 3).
- **Retrieval.** Audit before release, mismatch refusal, safe serving, the provider's own copy (section 7).
- **Client hardening.** Section 10.
- **Cancel at the provider, and late orphans.** Sections 4 and 5.
- **The mediums.** Fresh read at the gate, recipient-set equality, the distribute settle window, privacy of what is
  sent, required details as personal data, credential scope, pause coverage in 4B.1, withdrawal during
  agreements, and the route not mounted outside test.
- **The lows.** Status names aligned with `004`, the held key clarified, fixtures synthetic, the observation key
  explained, the 429 case split.

New owner decisions P4-D-14 to P4-D-20 and cases TEST-P4-23 to 32. The reviewer's remaining question, whether 4B.1
may start before the database protection and cancel designs are approved, is answered by putting both inside 4B.1
and 4B.2 under this specification.

## 15. Installed-version check and the 4B.1 record (D-38)

**The check (P4-D-2), 2026-10-17, read-only.** The owner authorized one check of the installed Documenso: its
container image tag and its published OpenAPI document, fetched without a credential. No envelope, webhook, email or
write was made. Findings, now **INSPECTED** for the installed version (they replace the matching NOT VERIFIED tags
above):

| # | Finding | Effect on the design |
|---|---|---|
| 1 | Image tag `v2.20.0`; the OpenAPI document is "Documenso v2 API" (OpenAPI 3.0.3) with 89 paths, 31 of them envelope paths | v2 envelopes are served (P4-D-2 holds) |
| 2 | `POST /envelope/use` takes `multipart/form-data` with a `payload` object: `envelopeId` (the template), `externalId`, `recipients` (`id`, `email`, `name`, `signingOrder`), `distributeDocument`; it returns `id` and per recipient `token` and `signingUrl` | step 2 as designed; tokens dropped by the adapter |
| 3 | `POST /envelope/distribute` takes `envelopeId` and `meta` (`distributionMethod` `EMAIL` or `NONE`, optional subject and message) and also returns tokens and signing links | step 3 sends no subject or message |
| 4 | `GET /envelope/{id}` returns `externalId`, a numeric `templateId`, `status` (`DRAFT`, `PENDING`, `COMPLETED`, `REJECTED`, `CANCELLED`) and per recipient `signingStatus` (`NOT_SIGNED`, `SIGNED`, `REJECTED`) and `token` | the H2 finding is confirmed for reads: the allowlist is required |
| 5 | `GET /envelope` filters by `templateId`, `type`, `status` and others, pages of at most 100, ordered by `createdAt`; there is **no `externalId` filter** | reconciliation uses the bounded listing (section 5); the free-text `query` is not relied on |
| 6 | Authentication is an API key in the `Authorization` header | the client sends it there and nowhere else |
| 7 | `v2.20.0` refuses a non-GET API request without `Authorization` (an Origin check) | API-key calls are unaffected |
| 8 | `GET /envelope/item/{id}/download` takes `version` (`signed`, `original`, `pending`); its schema declares a JSON response | the binary download is **NOT VERIFIED**; 4B.3 establishes it before custody depends on it |
| 9 | `POST /envelope/cancel` takes `envelopeId` and an optional `reason` | used for orphans in 4B.1 |
| 10 | Webhook signing is not in the OpenAPI document | still NOT VERIFIED; 4B.2 establishes it before the endpoint depends on it |
| 11 | `envelope/use` names a template by its envelope id (a string); created envelopes carry a numeric `templateId` | each template version stores both; that they correspond is NOT VERIFIED until a credentialed check is authorized |

**4B.1 as built** (bead `catalyst-v2-hdg.2`; tests `tests/test_agreements.py` against `tests/documenso_fake.py`):

- **Records.** The `agreements` app holds types (seeded: `nda`, then `user_agreement`), template versions, instances,
  recipients and a new record, `EnvelopeAttempt`: one row per create, distribute or cancel exchange, written
  `sending` before the request leaves and keeping every key ever used (the P2 attempt pattern).
  `ProviderObservation`, `StoredDocument`, `DocumentAccess` and `RequiredDetails` come with 4B.2 and 4B.3, each with
  its protection.
- **Protections (migration `agreements` 0002), each enforced by a trigger for every role unless noted:**
  - A template version is born an unapproved draft. It changes only while a draft, and then only its approval
    columns. It is never deleted.
  - An instance is born in its initial state, on an approved template version of its own type. Its identity
    columns are fixed, its envelope id is set once and a key is never reused.
  - Recipients are added only before the first provider call, then append-only.
  - One live instance per (application, type), enforced by a unique index.
  - The D-15 backstop refuses a User Agreement instance until the application's live NDA is
    `signing_complete_verified`.
  - Attempt identities and the agreement types are protected from the application role by column grants only; the
    migration owner can change them (ADR-14).
  - **Stated limit:** the status columns are the application role's to write. That `signing_complete_verified` came
    from a fresh read is an application control. 4B.2 decides whether to make it database-visible, for example by
    requiring a read observation row.
- **The client** (`agreements/provider.py`) is new rather than the evidence fetcher, because it must POST. It keeps
  the same pinned address, peer check, deadline and TLS rules, and adds:
  - no redirect, even on the same host;
  - a size cap;
  - a `%PDF` check on downloads;
  - an allowlist that drops tokens and signing links.
- **Outcome classes.** A failure before sending, a 429 or any other 4xx means the provider did not act. Anything else
  after sending is an unknown outcome: a timeout, a reset, a 5xx, a 408, a redirect, a truncated or unreadable
  response, or a defect during the exchange. An unknown outcome is reconciled and never retried. Every later claim
  reconciles an earlier `sending` or `unknown` attempt before any other check, so no pause, stage change or refusal
  can strand it. A step or reconciliation that cannot finish opens a staff item.
- **Provider strings** are validated before they reach a record. An envelope id must match `[A-Za-z0-9_-]{1,64}`.
  Statuses, signing statuses, roles and types map to the known values, and anything else reads as `UNKNOWN`.
- **Before distributing**, the re-read must show exactly our recipients (address and role). An added or swapped
  recipient refuses the distribute, so Documenso never emails an unverified address.
- **Deviations, each recorded here:**
  - A successful create goes straight to `distribute_pending`, because the distribute is queued in the same
    transaction, so `created` is not a resting state.
  - An unknown distribute that the settle window does not resolve opens a staff item. The decision service for it
    comes in 4B.2, with cancel at the provider for instances.
  - 4B.1 cancels orphans only. It cancels a `PENDING` orphan; it leaves a `DRAFT` orphan alone, because a draft was
    never sent; a completed orphan opens a staff item.
  - 4B.1 cannot cancel a draft orphan, because the installed API cancels pending envelopes only, and our creates
    are always drafts. The attempt records `left_draft`, the late-orphan staff item stays open, and the draft is left
    at the provider. P4-D-19 says "cancelled at the provider"; for a draft, deleting it is a provider-side retention
    act, so it waits for the owner (with POL-10).
  - The orphan watch is a count of checks (`CATALYST_AGREEMENT_ORPHAN_CHECKS`, synthetic default 6 at the
    reconcile grace, about 30 minutes), not an endless sweep. The "deadline" for an unknown create is likewise a
    count of checks (default 3). A match after the watch ends is not detected; 4B.2's sweep can extend it.
  - Instances are born `create_pending`; `held` and `created` are not used as resting states.
  - The instance's `external_key` is updatable, but only to a key never used before.
  - A pause at create or distribute defers the step (the P2 rule for automated sends). It does not refuse it.
  - Template approval is the owner's alone. Counsel's approval (POL-07) is added when counsel is named.
  - The provider URL, its pinned loopback address, the trust store and the API token are fixed in code. They are
    empty in every environment and set only by test fixtures. The URL must name a `.test` host. A production token
    arrives through SOPS at P6.
  - Staff services refuse superusers: authority is the named permission, held by an active staff user (as P2 and
    P3).
  - A distribute refused by a P2 send check, or because the provider's recipients differ from ours, leaves the draft
    at the provider and the instance `failed_needs_staff`. The resolution services come in 4B.2.
- **Limits.**
  - The fake follows the published schema, not observed behaviour (proof A only).
  - A compromised migration owner can drop the triggers (ADR-14).
  - Whether repeating a distribute is safe remains NOT VERIFIED, so it is never repeated.

## 16. The 4B.2 record (D-39)

**Webhook mechanism, INSPECTED.** Read from the installed version's public source at tag `v2.20.0`
(`packages/lib/server-only/webhooks/execute-webhook-call.ts` and the job that calls it). No credential was used and
no request was made to the installation:

- The provider POSTs JSON with a plain shared secret in `X-Documenso-Secret`. There is no signature and no
  timestamp. It waits at most 10 seconds and follows no redirect.
- The body is `{event, payload, createdAt, webhookEndpoint}`. `payload` is the document: its legacy numeric id,
  `externalId`, `status`, `templateId`, and recipients including their tokens.
- The provider refuses private webhook URLs, so a public endpoint is needed at P6 (P4-D-17).
- The provider stores our response body and headers, so the endpoint answers with an empty body.

**4B.2 as built** (bead `catalyst-v2-hdg.3`; tests `tests/test_agreement_completion.py`):

- **Webhooks** (`agreements/views.py`). The route is mounted only in `test` and `development`.
  - At most two secrets (one rotation), each compared in constant time. A missing or wrong secret gets a bare 401.
  - The body is size-capped and parsed into an allowlist. CSRF is exempt for this view only, and the view logs
    nothing.
  - It routes by our key alone. Unknown keys and unreadable bodies get the same empty 200.
  - A known key records a webhook observation (an exact replay is a no-op) and schedules a coalesced read. A
    completion hint moves the status to `signing_complete_observed`, never further.
  - A set-aside old key triggers an early orphan check, which extends the counted watch of section 15.
- **Reads** (`agreements/completion.py`).
  - One queued or running read per instance at most. A new read never runs sooner than a minimum interval after the
    last one.
  - Each read is recorded as an observation of allowlisted facts. Statuses and roles are stored, and whether the
    envelope and recipients are ours; addresses and tokens are not.
  - A pending envelope schedules the next read at the sweep interval: the sweep is per instance, not one global
    job.
  - Reads are automated: a pause holds them, and resuming runs the one coalesced read. **Superseded by D-44 (section
    17):** reads now run while paused.
- **Verification is database-visible**, deciding the limit stated in section 15.
  - `signing_complete_verified` is accepted only while the instance is issued, and only with a read observation in
    the same transaction showing completion, our identity, exactly our recipients and every required signature.
  - A verified status never changes.
  - Observations are protected history.
  - Remaining limit: a compromised application role could insert such an observation itself.
- **Outcomes of a read:**
  - **Declined:** automation is paused and a staff item opens (P4-D-9).
  - **Expired:** a staff item opens.
  - **Cancelled in the provider's interface:** a staff item opens.
  - **Completed with changed recipients:** observed, never verified.
  - **Another envelope, key or template:** never verified.
  - **A completion on a cancelled or superseded instance:** a staff item, never verified (TEST-P4-29).
- **The D-15 sequence.** When a type passes its gate, `advance_agreements` re-reads the previous envelope at the
  moment of issue (REQ-011) and only then starts the next type. A stale or changed read issues nothing and opens a
  staff item.
- **Staff services, permission `manage_agreements`, assigned to no group:**
  - **Cancel at the provider** (P4-D-18): its own reconciled action, with `cancel_pending` and `cancel_uncertain`.
  - **Reissue** after a decline or a cancellation: a new instance, the old one marked superseded.
  - **Stop agreements** for a withdrawal, closure or hold (P4-D-20): every live envelope is cancelled; an unknown
    create is set aside and its key watched; nothing more is issued.
  - **Decide an unknown distribute:** distribute again (the step re-reads first) or cancel.
- **After the 4B.2 reviews:**
  - **Reads are never delayed by coalescing.** A webhook brings the queued sweep read forward to "now, but not
    sooner than the minimum interval". A hint during a running read queues one follow-up.
  - **The sweep survives an outage.** A read that fails for good opens a staff item and arms the next periodic
    read.
  - **Verification is fixed once reached.** The database also refuses verification on any instance that was not
    already issued, so a cancelled or superseded instance cannot be resurrected and verified. A verified instance
    never changes its signing or issue status.
  - **Stop and cancel wait for exchanges in flight.** They refuse while a create, distribute or cancel is running.
    A distribute that lands on an instance a cancel already closed queues a new cancel.
  - **Pauses follow P4-D-9 as approved.** Decline, expiry and a cancel made in the provider's interface each pause
    automation and open a staff item.
  - **Hold versus stop.** A hold can be resumed by a decision-maker (`resume_agreements`, which also re-runs the
    sequence after staff fix what stopped it). Withdrawal and closure are final.
  - **Staff items and permissions.**
    - A failed advance opens a staff item.
    - Reissue refuses an already-superseded instance, and refuses while a completion-after-cancel item is open.
    - Cancelling from the unknown-distribute decision also needs `manage_agreements`.
    - `cancel_agreement` is the remedy for `cancel_uncertain` once its reconciliation has ended.
  - **The webhook is hardened.**
    - A digits-only `Content-Length` check.
    - Malformed or deeply nested bodies and internal failures all get the uniform empty 200.
    - The secrets and the body are marked sensitive for error reports.
    - At most 20 recipients per body.
    - A repeat of the last observation is not stored.
    - A completion hint moves only an issued instance with our identity.
    - Old-key orphan checks have a minimum interval and a per-key cap.
- **Open for the owner:**
  - Whether Documenso emails the applicant when an envelope is cancelled is NOT VERIFIED. If it does, that email
    is not subject to the P2 bounce and address checks.
  - How a verified NDA whose recipients changed before the gate read is resolved, beyond the staff item and
    `resume_agreements`.
- **Deviations and limits:**
  - The NDA gate needs custody too (P4-D-6), and custody is 4B.3. Until then the User Agreement is never issued in
    the normal flow; the sequence tests set the NDA gate to signing alone.
  - The P5 hand-off after the last type is 4B.3.
  - Stopping agreements does not move the stage: that is POL-12, in P5.
  - An expired envelope must be cancelled before reissue.
  - A draft cannot be cancelled at the provider (section 15). Cancelling an instance whose envelope is still a draft
    closes it locally (`left_draft`); the draft was never sent.
  - Reminders and expiry settings (P4-D-10) are provider defaults in the fake; none are configured.
  - Whether the real read and webhook carry exactly our recipient roles is NOT VERIFIED. A false refusal is possible
    until a credentialed check is authorized.

## 17. Recovery corrections and the owner decisions of 2026-10-18 (D-40 to D-44)

Bead `catalyst-v2-hdg.6`; tests in `tests/test_agreement_recovery.py` and the updated 4B.1 and 4B.2 files.

**D-41: provider email, INSPECTED from public source at `v2.20.0`:**

- `packages/trpc/server/envelope-router/cancel-envelope.ts` calls `cancelDocument`.
- `packages/lib/server-only/document/cancel-document.ts` cancels only pending envelopes, writes an audit log entry,
  queues the job `send.document.cancelled.emails`, and triggers the `DOCUMENT_CANCELLED` webhook.
- `packages/lib/jobs/definitions/emails/send-document-cancelled-emails.handler.ts` sends nothing when any of these
  holds:
  - the organization has email disabled, or the owner is disabled;
  - the recipient limit is exceeded;
  - the derived `documentDeleted` setting is off.

  Otherwise it mails each non-CC recipient who was sent or opened the document and did not reject it, within the
  organization's email quota.
- Cancellation therefore can send email. The supported per-envelope control is `emailSettings`: `override` on
  `envelope/use`, and `meta` on `envelope/distribute`.

**Provider-owned email**, inventoried apart from Catalyst's (which P2 governs). P2 does not control any of these once
an envelope is distributed:

| Provider email | Trigger | Setting | Catalyst's choice |
|---|---|---|---|
| Signing request | distribute | `recipientSigningRequest` | on: it is the purpose |
| Reminders | provider schedule | template and team settings | none configured in synthetic P4 (P4-D-10) |
| Pending notice, completed copy | signing | `documentPending`, `documentCompleted` | provider default, on (P4-D-14) |
| Cancellation | cancel | `documentDeleted` | **off** (D-41) |
| Owner notices | various | `owner*`, `recipientSigned`, `recipientRemoved` | provider default |

- **Applying the suppression.** Catalyst sends the whole `emailSettings` object on both create and distribute. A
  distribute that left it out would fall back to the all-on default; the fake models that fallback.
- **The cancel reason** is a fixed generic sentence, never staff notes.
- **Not yet proven.** That the installation honours the suppression is NOT VERIFIED. Before real use there must be
  an authorized synthetic-recipient canary, or the owner's narrow written acceptance.
- **Protective cancellation** runs while automation is paused and while delivery is blocked. A bounce must not
  leave a signing request live. It never sends a new invitation or a Catalyst message.

**D-42, hold, cancel and resume:**

- A stop or cancel that meets an exchange in flight records `cancel_requested_at` (once) instead of refusing. The
  exchange records its own result first, because a request already sent may have taken effect:
  - a created draft is kept and never distributed;
  - a sent envelope goes to the reconciled cancel;
  - an unknown outcome is reconciled the same way.
- An ordinary automation pause cancels nothing.
- Verified agreements are never cancelled by a stop.
- `resume_agreements` is refused until every cancel has settled and while an integrity hold is open. Withdrawal
  and closure are final.
- An advance may issue a type again (a new instance and key; nothing copied from the old one) only under a
  decision-maker's resume. Otherwise it opens a staff item.

**D-43, agreement integrity:**

- When a read of a verified agreement, or the gate re-read, no longer shows it complete with our identity and
  exactly our recipients, an `agreement_integrity_hold` opens. The verified columns stay as they were (they are
  immutable).
- The hold fails the gate, so the User Agreement and the P5 hand-off wait. Generic resume does not clear it.
- `resolve_agreement_integrity`, assigned to no group, offers three things:
  - a recheck;
  - **continue**, only on a read recorded after the hold that matches fully;
  - **replace**: `replaced_at` and its reason are set once, the verified history is kept, and a new generation
    becomes the eligible instance;
  - **escalate**: the hold stays for the owner or counsel.
- Each resolution needs a reason and the digest of the state shown; a stale digest is refused.
- The expected recipients are never changed, and no disposition claims to void an agreement.

**D-44, carried defaults:**

- A late draft is kept, excluded and left with staff. A late pending one is cancelled. A late completed one is an
  exception.
- When the orphan watch ends, an `agreement_orphan_watch_ended` item opens. A decision-maker may re-arm it three
  times, each re-arm giving the configured number of checks.
- Closed instances whose provider still shows them open get bounded follow-up reads, then an
  `agreement_closed_watch_ended` item. A completion found that way is an exception, never verified.
- Reads are now protective: they run while paused or stopped. What a read may lead to (the next agreement) is
  automated and waits for the pause to end. **This replaces the 4B.2 behaviour, in which a pause held reads.**
- A follow-up read queued during a running read keeps the minimum interval after that read.

**`hdg.6` corrections**, each with a test:

- the `cancel_uncertain` remedy;
- a superseded reissue refused, and an unverified contact reported as a refusal;
- deeply nested webhook bodies get the uniform answer;
- an advance that keeps failing opens a staff item;
- a false completion hint is reset by the read;
- a hint never moves an instance that was not issued;
- a stop interleaved with a running distribute, tested from a separate thread and connection;
- a lost completion of a closed instance is caught;
- follow-up reads keep the minimum interval.

**After the reviews of PR #42** (independent QA and security; one HIGH each, the same finding):

- **Replace issues only into open work, after earlier agreements pass.** It issues a new signing request, so it is refused unless agreements are
  open: stage `agreements`, not stopped, not paused. It also needs `manage_agreements` as well as
  `resolve_agreement_integrity`, and every earlier agreement must pass its gate. The create and distribute checks close
  a pending instance of a stopped application without calling the provider.
- **Withdrawal and closure stay final.** They can never be turned into a resumable hold.
- **Two more refusals.** A resume or reissue never issues over an open completion-after-cancel item. A User
  Agreement is never reissued while an earlier agreement fails its gate (D-15, D-43).
- **"Continue" resumes the sequence.**
- **Every left draft is watched.** Closed on request, created after a stop, or found by evidence after a stop, each
  gets the bounded follow-up reads. A cancel the provider confirmed (`CANCELLED`) is terminal there (the installed
  version cancels pending envelopes only, and a cancelled one cannot be signed), so it gets no follow-up read; a
  webhook about it still triggers one.
- **Replaced history is not a closed agreement.** A read of replaced verified history is not treated as one.
- **The staff-written integrity reason is stored once.** It goes in the resolution note, or, for an escalation, in
  its event. The retention of these notes is an owner decision under POL-10.
- **The replacement fields are tied together.** A check constraint requires `replaced_at` and its one reason code
  to be set together.
- **No rollback once used.** Migrations 0005 and 0006 refuse to roll back once a stop request or a replacement is
  recorded.

**Database:** migrations `agreements` 0005 and 0006 add the new columns, which are set once for every role. A
replacement needs its reason. The live-instance index and the D-15 backstop ignore a replaced NDA. Tests bypass
the services to prove each.

## 18. The 4B.3 record: custody, retrieval, required details, the staff screen and the hand-off (D-40)

Bead `catalyst-v2-hdg.4`; tests in `tests/test_agreement_custody.py`.

**Download contract, INSPECTED from public source at `v2.20.0`:**

- `packages/trpc/server/envelope-router/download-envelope-item.ts` is a stub (`NOT_IMPLEMENTED`). The API v2
  download is implemented in `apps/remix/server/api/download/download.ts`: `GET
  /api/v2/envelope/item/{id}/download?version=…`. It authenticates with the API key, limits access to the token's
  team, and serves through `apps/remix/server/api/files/files.helpers.ts`.
- `version=signed` serves the item's current stored data; `original` serves the uploaded data. The signed branch
  does not check that signing finished.
- The response is the PDF bytes, with `Content-Disposition` and `no-store` headers. Its ETag is a SHA-256 of the
  storage reference, not of the bytes.
- **What Catalyst does with this:**
  - Before any download, it checks completion, identity and every required recipient on a fresh read.
  - It downloads only the item ids that read lists, always with `version=signed`.
  - It hashes the bytes itself.
  - Neither the header nor the ETag counts as evidence.

**Custody** (`agreements/custody.py`, `agreements/storage.py`):

- **Trigger.** Custody runs after `signing_complete_verified`. It only reads from the provider, so, like
  reconciliation, a pause does not hold it (D-44).
- **Storage.** Each item is downloaded through the hardened adapter (bounded size and time, no redirect, `%PDF`
  check). It is written under a new system-generated key with an exclusive, no-follow, mode 0600 create, flushed to
  disk, re-opened, checked as a regular file owned by this user with no group or other access, and re-hashed. Only
  then does one transaction record a `StoredDocument` (insert-only, append-only; one per instance and item) and
  move custody to `stored_verified`. The sequence then advances.
- **Location.** `CATALYST_AGREEMENT_STORAGE_DIR` is fixed in code and test-only. It must be absolute and outside the
  repository, and its directory must be private to this user. Production location and encryption are POL-09.
- **Failure.** A provider or storage failure retries within the attempt bound (`failed_retry_pending`), then
  becomes `failed_needs_staff` with an item. An operator may retry. Signing stays verified, and nothing is
  re-signed, reissued or advanced.
- **Changed provider view.** If the fresh read no longer matches, an integrity hold opens (D-43) and nothing is
  stored.
- **Interruption.** If the run stops between the file and the record, the file is left unreferenced and is never
  served. When no record exists yet, the retry writes a new key; the unique record allows only one authoritative
  copy, and a retry is refused once a copy exists (see below).

**Retrieval** (`services.retrieve_document`; `POST /staff/p4/documents/<id>/retrieve/`):

- **Who.** Only the `retrieve_agreement_document` permission, assigned to no group (P4-D-16), with a stated reason.
- **Audit first.** The `DocumentAccess` row (append-only) is committed before any byte is read for release. If the
  audit write fails, nothing is released.
- **Denials.** A missing permission, a missing document and a non-staff or anonymous caller all return the same 404.
  Staff refusals leave a `denied` row naming only the reference asked for; outsiders are logged, not recorded.
- **Integrity.** The bytes are read once with no link following, checked against the recorded size and SHA-256, and
  exactly those bytes are served. A mismatch, a link, the wrong owner or loose permissions refuses. Each refusal is
  recorded as `refused_integrity`, opens a corruption item and sets custody back to `failed_needs_staff`.
- **Response.** Served as an attachment: `application/pdf`, `nosniff`, `private, no-store`.

**Required details** (POL-18; synthetic fields only):

- `CATALYST_AGREEMENT_REQUIRED_DETAILS` is fixed in code and empty. Tests set synthetic field names; the production
  field list is undecided.
- With the `confirm_required_details` permission, staff record what the applicant provided as a new draft version,
  then confirm exactly the values shown (a digest). A received email is never adopted as an answer, and the adopted
  application is never overwritten.
- A confirmed version is final for every role (a trigger).
- An agreement type with required details is not issued until a confirmed version holds every field. Until then a
  staff item explains the wait.

**The staff screen** (`/staff/p4/applications/<ref>/agreements/`, linked from the dossier):

- **What it shows.** For each instance: issue, signing and custody separately, in plain words; the recipients; the
  latest observations; any integrity hold, with the evidence and the allowed remedies. Also the required details,
  the open agreement items, the next action and who owns it.
- **Actions.**
  - Each action is a CSRF-protected POST to one service, shown only to its permission.
  - A refusal re-renders the page with the refusal code and what was typed.
  - Choices are never preselected.
  - Superusers are refused.
  - Untrusted text is escaped.
- **Permissions.**
  - Readers have `view_agreementinstance`.
  - Operators have `operate_agreements`.
  - Decision-makers hold the `manage`, `decide`, `resolve`, `retrieve` and `confirm` permissions.
  - None is assigned to a group.

**The P5 hand-off** (021 step 8):

- **Prerequisites.** When every required type has a live, unreplaced instance that passes its gate (signing and
  custody by default, with no integrity hold), and every required detail is confirmed, the advance re-checks all of
  it under the application lock.
- **The move.** It then moves the stage `agreements → agreements_complete` with a compare-and-set, and creates one
  held `provision:<application>` action.
- **What it records.** The action's input is a digest of the exact prerequisites (instances, stored documents,
  details versions), which the stage event lists.
- **Duplicates.** A duplicate or stale advance creates nothing more.
- **Nothing runs it.** No `provision` handler exists.

**After the reviews of PR #43** (independent QA and security; QA found two HIGH, security none):

- **A stored copy is never replaced by a retry.** After corruption, retrieval refuses, records it, opens an item
  and marks custody failed. Retrying custody is then refused (`stored_copy_exists`). Whether and how a corrupt copy
  is replaced is the owner's POL-09 and POL-10 decision. A store run that meets an existing record goes to staff;
  it never sits silently at `pending`.
- **Details can come before the first agreement.** Required details may be recorded and confirmed while the
  application is `admitted`. An NDA held for its details opens a staff item; confirming the details lets it run
  again only when the owner's activation command runs again (P4-D-13). The confirmation resolves the details
  item, recomputes the digest from the stored values, checks the stage and stop state, refuses a superseded draft,
  and must name who and when. The details table cannot be truncated.
- **Storage is pinned by descriptor.** The storage directory is opened once without following links, checked
  through its descriptor, and every file operation works relative to it. A new file's name is flushed to disk.
- **"Unavailable" is not "corrupt".** Storage being unavailable refuses retrieval without blaming the document;
  only wrong bytes count as corruption.
- **Retrieval refuses inside a transaction**, so the audit always commits first.
- **Outsiders add nothing to the audit table.** Non-staff and anonymous callers get the same 404 and are logged,
  not recorded, so outsiders cannot grow the append-only table. Staff refusals are recorded.
- **A second fresh read after the downloads** confirms the envelope, its items, completion and every required
  signer (recipients included) did not change while its items were fetched.
- **Malformed identifiers** on the staff screen are refused (409), never a server error.
- **The PDF response** also carries `Content-Security-Policy: sandbox`.

**Open for the owner, and blocking real data:**

- Required details and PDFs are stored in plaintext. Neither can be erased (insert-only and append-only), and no
  correction path exists beyond a new version. These need POL-09, POL-10 and POL-18 before any real data.
- Whether the same person may both record and confirm details (POL-18).
- How a corrupt stored copy is replaced (POL-09, POL-10).
- **P5 must re-check every prerequisite when it releases the held `provision` action.** A corruption or an
  integrity hold after the hand-off does not change the held action itself.

**Deviations and limits:**

- Unreferenced files from interrupted runs are not swept. Deleting them is a retention act (POL-10).
- The stored PDF is not encrypted (POL-09).
- The download's binary behaviour comes from the public source and the fake. It is NOT VERIFIED on the installation
  until a credentialed check is authorized.
- One item per synthetic template. Up to `CATALYST_AGREEMENT_MAX_ITEMS` per envelope are stored.

## 19. The 4C record: the GATE-P4 run and the local demonstration (D-40)

**The gate.** `tests/acceptance.py` `P4_CASES` maps TEST-P4-01 to 32. `P4_SUPPORTING` maps D-41 to D-44, the
hardening 9kg.1 to 9kg.3 and three removed-gate controls. A full run gates GATE-P4 with GATE-S1 to GATE-P3: every
case must PASS at one head. The after-action report and its statement are in `000-aars/022`. **GATE-P4 was signed
off by the owner on 2026-10-18 (D-45)** on CI run 39103156421 at `f11ca36`.

**The journey** (`tests/test_p4_journey.py`):

- intake over HTTP, then the P3 decision;
- the owner's activation command;
- staff log in through the admin form, and every staff POST carries a CSRF token;
- signing at the fake provider, with the webhook posted over HTTP;
- the fresh read; custody; then the User Agreement; then custody;
- the stage `agreements_complete`, with one held `provision` action;
- audited retrieval over HTTP.

The default gate is used for both agreements, with no signing-only override.

**Run it locally** (synthetic only; Docker, no credentials, nothing external is contacted):

```bash
scripts/test.sh                                              # the whole suite: the gate report for GATE-S1 to GATE-P4
PYTEST_ARGS="-v tests/test_p4_journey.py" scripts/test.sh    # the P4 journey and the removed-gate controls only
```

A selected run prints the gate report marked "selected subset: not gated". Only the full run gates. Each run
starts its own pinned PostgreSQL 16.15 and Python 3.14.8 containers and removes them afterwards. The fake Documenso
server, its TLS certificates and the custody directory are created per test in temporary storage.

**What a browser harness would add:** none exists in this repository. The journey uses Django's test client, which
runs the full middleware stack (sessions, CSRF, authentication) in-process, with no socket, proxy or real host.
