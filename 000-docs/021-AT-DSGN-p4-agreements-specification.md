# P4 Agreements Specification (handoff 4A)

| Field | Value |
|---|---|
| Document | `021-AT-DSGN-p4-agreements-specification` |
| Version | 0.2.0 (draft for owner review; the independent security and privacy review applied, section 14) |
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
