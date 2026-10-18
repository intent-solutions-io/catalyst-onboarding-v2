# P5 Provisioning, Activation and Withdrawal Specification (handoff 5A)

| Field | Value |
|---|---|
| Document | `023-AT-DSGN-p5-provisioning-specification` |
| Version | 0.2.1 (0.1.0 prepared under D-40; 0.2.0 records the owner's P5 decisions, D-47, and corrects the MXroute research from the public API reference; 0.2.1 and 0.2.2 resolve the pre-build security and reliability reviews and their re-checks, section 11) |
| Status | **P5 decisions DECIDED by the owner 2026-10-18 (D-47) for synthetic work; 5A amended and 5B.1 to 5B.3 released for synthetic implementation against a local fake MXroute.** Not authorized: live MXroute access, any provider key, real mailboxes or passwords, real applicant data, role grants to real staff, deployment, and GATE-P5 acceptance (5C stays a draft for the owner). |
| Owner | Jeremy Longshore |
| Date | 2026-10-18 |
| Epic | P5, "Provision the approved mailbox, activate the applicant, and support withdrawal and recovery" (`catalyst-v2-tuc`) |
| Builds on | `004` J-14, J-15, J-16; `011` POL-11, POL-12, POL-01, POL-10, POL-13; `021` (the held `provision:<application>` hand-off, section 18); `016` (correspondence, delivery blocks); ADR-15 (uncertain outcomes) |
| Classification | Public; synthetic only; no real domain, mailbox, quota or credential |

## 0. How to read this document

Fact tags as in `021`:

- **DOCUMENTED:** an official provider page says so (with the URL).
- **INSPECTED:** read in this repository.
- **PROPOSED:** this document's design.
- **NOT VERIFIED:** unknown for our account; a named task must establish it before code depends on it.

## 1. Scope and boundaries

**In scope (synthetic P5, once released):**

- releasing the held `provision` action under an owner-run activation (the 3B.1 and 4B pattern);
- a provisioning request with the P2 and P4 "never twice" discipline;
- verifying that the mailbox exists before anything else;
- delivering credentials (method decided by POL-11);
- activation with a welcome message;
- withdrawal and closure, with their effect on agreements and access;
- the staff screen;
- the GATE-P5 acceptance plan.

**Out of scope:** real mailbox creation, any MXroute API key or panel access, choosing the real domain, naming or
quotas, and deployment (P6).

## 2. Starting point (INSPECTED)

4B.3 ends with the stage `agreements_complete` and exactly one held `provision:<application>` action, whose input is
a digest of the exact prerequisites: live instances, stored documents and details versions (`021` section 18).
Nothing runs it.

**P5 must re-check every prerequisite when it releases the action.** A custody corruption or an integrity hold after
the hand-off does not change the held action itself.

## 3. MXroute capabilities (research, 2026-10-18, public pages only; amended in 0.2.0)

**Correction (0.2.0).** Version 0.1.0 said the panel API's operations were documented only inside the account. That
was wrong. The API reference is public: [api.mxroute.com/docs](https://api.mxroute.com/docs) and
[openapi.yaml](https://api.mxroute.com/openapi.yaml). No key is needed to read it.

The schema was read on 2026-10-18T15:16:40Z. It is OpenAPI 3.0.3, `info.version` 1.0.0, 46,447 bytes, SHA-256
`25272af35138b6ef4dc79eccd6ea1876fa1b30c97ae56be6dc0ba8a01d6e879d`. No authenticated request was made, and no API
explorer was used against the service.

Tags used in this section:

- **DOCUMENTED:** stated by an official page or the published schema.
- **NOT VERIFIED:** documented but not exercised. Our account's entitlement and real behaviour are unknown, and the
  live path stays blocked.
- **NOT DOCUMENTED:** no official page or the schema says it. Catalyst must not assume it.

| # | Fact | Tag |
|---|---|---|
| 1 | **Mailboxes** (`/domains/{domain}/email-accounts`): list (GET); create (POST `username`, `password` 8 to 72 characters, `quota` in MB default 1024, `limit` daily sends default 9600 and maximum 9600) returning 201; read one (GET `/{user}`); update (PATCH `password`, `quota`, `limit`; omitted fields unchanged; the local part is resolved case-insensitively, and an ambiguous lookup refuses); delete (DELETE, 204). Errors: 400 for a rejected password, 404, and 500 for a failed or ambiguous lookup. Raw backend errors are hidden. **A 500 is an unknown outcome, never "absent".** | DOCUMENTED; NOT VERIFIED |
| 2 | **Quota 0 means unlimited.** It is never a way to disable a mailbox. | DOCUMENTED |
| 3 | **Authentication** uses three headers: `X-Server`, `X-Username` (or `reseller\|user`) and `X-API-Key`. In the reseller-impersonation section the schema says "the key's DirectAdmin restrictions remain in force". So the panel's lack of a per-key permission editor does not prove a key is unrestricted. A reseller key can impersonate any owned user and reach the reseller endpoints (suspend, delete, packages), so it is far broader than a key for one hosting user. | DOCUMENTED; restriction scope NOT VERIFIED |
| 4 | **Errors** are `{success, error: {code, message, field}}`. The codes include `CONFLICT` (resource exists), `FORBIDDEN`, `RATE_LIMITED` (with `Retry-After`), `BUSINESS_ERROR` and `SERVER_ERROR`. | DOCUMENTED |
| 5 | **Rate limits:** 200 reads, 60 writes and 10 bulk requests per minute, with `X-RateLimit-*` headers. Impersonated users share the reseller's bucket. | DOCUMENTED |
| 6 | **Forwarders** (list, create, delete per domain), **catch-all** and **pointers** exist. | DOCUMENTED |
| 7 | The mailbox schema includes a `suspended` flag, but **no documented operation sets it for one mailbox.** Suspend exists only for a whole reseller user (`/reseller/users/{u}/suspend`), and mail can be disabled only for a whole domain (`PATCH /domains/{d}/mail-status`). Neither is ever used to remove one person's access. | DOCUMENTED |
| 8 | Not in the schema: idempotency keys; session revocation; app passwords; a password-setup or reset link; forced change at first login; the semantics of a create that meets an existing mailbox beyond `CONFLICT`. | NOT DOCUMENTED |
| 9 | From the panel and docs pages: the 200-row CSV import cap, a separate 400 per hour maximum, and "Deletion removes the mailbox's messages and data". | DOCUMENTED ([email accounts](https://docs.mxroute.com/docs/email-accounts.html)) |
| 10 | The SMTP API sends mail only and uses mailbox credentials. | DOCUMENTED ([SMTP API](https://docs.mxroute.com/docs/api/smtp-api.html)) |

**Consequence (decided, P5-D-4).**

- **API-first, against a local fake** of the documented mailbox operations, with the recorded operator checklist kept
  as a fallback. It is one provisioning workflow with one narrow adapter, not two engines.
- **The live path stays blocked** until the owner separately authorizes three things:
  - a key and its custody;
  - a check of our account's entitlement and the key's DirectAdmin restrictions;
  - the integration tests.
- **No account-wide key in ordinary settings.** Only the dedicated provisioning worker may ever hold one, through a
  narrow adapter with every call audited. It never sits in web settings or a routine worker's environment.
- **Not-documented features are never assumed:** no idempotent create, no reset link, no suspension, no session
  revocation. The synthetic workflow labels where it relies on Catalyst-side behaviour instead.

## 4. Records (`provisioning` app, ADR-01), amended 0.2.0

| Record | Holds | Protection |
|---|---|---|
| `AddressReservation` | The local part and domain reserved for one application, why (`naming_rule` or `reviewed_exception`), and who reviewed an exception. | One live reservation per address. A reserved or system address cannot be reserved. Released only by an audited act. |
| `ProvisioningRequest` | The application. The reserved address. The method (`api` or `checklist`). The **prerequisite digest** it was approved under (immutable). Quota and send limit. Who approved it and when, against the digest of what they were shown. A status: `awaiting_approval`, `approved`, `create_pending`, `create_uncertain`, `created`, `verified`, `conflict`, `failed_needs_staff`, `stopped`. | Identity and approval are set once. One live request per application. A changed prerequisite needs a new request and a new approval; it never mutates the old one. |
| `ProvisioningAttempt` | Each create or update exchange: committed before the call, then its outcome (`succeeded`, `rejected`, `conflict`, `unknown`, `found_by_evidence`). | Insert-only identity; one outcome. |
| `ProvisioningEvidence` | **API path:** the allowlisted read of the mailbox (name, quota, limit, suspended), with no credential. **Checklist path:** what the creator recorded, and the verifier's separate attestation. | Append-only. The verifier must differ from the creator (a database check). |
| `CredentialSetup` | The invitation's hashed token, its expiry, the verified external address it was sent to, and its states: `invited` (accepted by mail transport), `presented` (the page was opened), `set_pending`, `set_uncertain`, `completed`, `expired` or `cancelled`. | The token is hash-only and single-use. The password is never stored. |
| `AccessRevocation` | One row per obligation on withdrawal or closure: setup links, password rotation, forwards, sessions, client connections, app or delegated credentials. Each has its state: `requested`, `pending`, `verified`, `unsupported` or `exception`. | Append-only transitions. `unsupported` never reads as done. |

## 5. The P5 journey, amended 0.2.0

| # | Step | Records and transaction | Outcomes | Recovery |
|---|---|---|---|---|
| 1 | Release | An owner-run, versioned activation releases the held `provision:<application>` action. **The prerequisites are re-checked at every effect boundary, not only at release:** agreement integrity, custody, confirmed details, the verified contact, pause, delivery blocks and withdrawal. | requested; refused | A refusal leaves the action held, with a staff item. |
| 2 | Address | A reservation under P5-D-1, checked against reserved names, our reservations and (through the adapter, or a checklist attestation) the provider's mailboxes and forwarders. | reserved; conflict | A conflict goes to staff, who choose another address or review an exception. |
| 3 | Approve | The approver (P5-D-3) confirms the exact address, quota, limit, method and prerequisite digest, against the digest of what they were shown. | approved | A stale screen refuses and needs a fresh confirmation. |
| 4 | Create | **API:** the attempt is committed first, then one create call with a random password nobody sees (the setup flow replaces it). A `CONFLICT`, or an unknown outcome, is reconciled by reading that specific mailbox. A mailbox that exists is never assumed to be ours. **Checklist:** a staff task with the recorded steps. | created; conflict; uncertain | Never retried blindly. Duplicates are serialized per address. |
| 5 | Verify | **API:** an authoritative read of that mailbox, tied to the request. **Checklist:** a different named verifier's attestation (P5-D-5). | verified; not found; conflict | Bounded re-checks, then staff. |
| 6 | Credential setup | An invitation to the **previously verified external address**, not to the new mailbox. It goes through a secret-bearing message kind that 5B.2 builds (P2 refuses secret-bearing templates today; section 11.2). The page shows on GET and sets the password on POST. The password is handed over only transiently to the privileged operation (section 7). An unknown outcome blocks activation and opens a safe recovery path. | invited; presented; completed; expired; uncertain | A new invitation cancels the old one. A credential operation is never replayed blindly. |
| 7 | Activate | One transaction: the prerequisites are current, provisioning is verified **and** setup is completed. The stage moves `provisioning → active` and the approved welcome is queued; the worker sends it later, outside the transaction. Protective jobs stay. | active | A welcome bounce opens a staff item; the stage stays `active`. |

"Invitation accepted by the mail server", "link presented", "credential set" and "access ready" are four
different facts, and only the last allows activation.

## 6. Withdrawal, closure and recovery (J-16), amended 0.2.0

- **Withdrawal** (P5-D-8): an explicit, verified confirmation page, where GET displays and POST commits. An emailed
  "withdraw" becomes a review item. A staff-mediated path covers an unavailable contact channel.
- **Closure:** a decision-maker closes the application, with a reason. There is no automatic no-response closure
  (P5-D-11).
- **Stop intent is durable,** even while provisioning or a credential operation is in flight. A late-created mailbox
  is recovered without a welcome, without reactivation and without deletion.
- **Revocation** (P5-D-9) records each obligation in `AccessRevocation`:
  - cancel outstanding setup links;
  - rotate the password to an unknown value;
  - remove forwards;
  - mark sessions, client connections and app or delegated credentials `unsupported` until a documented provider
    mechanism exists.

  A terminal application does not mean remote access is revoked. The staff screen shows what is still open.
- **Never:** suspend a whole hosting user or domain for one person, or delete mailbox data. POL-10 governs deletion.
- **Reopening:** a new application inherits nothing (P5-D-10).
- **System recovery:** the pending-action ledger, with audited retry, reconcile or abandon.

## 7. Security and privacy, amended 0.2.0

| Control | Status |
|---|---|
| The applicant's chosen password never enters the ledger payload, the database, an event, a log, an exception, a model, browser storage or a test artifact. It travels only in the POST request and the in-process call to the privileged operation. | PROPOSED; tested in 5B.2 |
| The setup token: CSPRNG, stored only as a hash, single-use, bound to the request and the verified address, short expiry (a synthetic fixture value is not policy), rate-limited, never in logs or analytics. No third-party assets, link-preview consumption or Host-derived links. | PROPOSED; tested in 5B.2 |
| No account-wide key in web settings or routine worker environments. Only one dedicated provisioning worker would ever hold it, through a narrow adapter with every call audited and an alert on any deletion. Rotation and revocation are procedures, not assumptions. | PROPOSED; live use blocked |
| The fake adapter and the live adapter share one interface. The live adapter refuses to start outside an authorized environment (the agreements guard pattern). | PROPOSED; tested in 5B.1 |
| Address rules are enforced deterministically, never from free text. Reserved and role addresses are refused. | PROPOSED; tested in 5B.1 |
| Permission to manage access is separate from reading applicant mail or signed documents. | PROPOSED; tested in 5B.3 |
| A delivery block or a pause stops the invitation and the welcome (9kg.3). | Applies through the P2 send path |
| Mailbox deletion is never automatic. | PROPOSED |

## 8. Owner decisions P5-D-1 to P5-D-11 (decided 2026-10-18, D-47)

The owner decided these on 2026-10-18 (D-47 in `011`). They replace the 0.1.0 recommendations. Each one is for
synthetic work only. Every live value and every live operation stays a separate activation decision.

| # | Decision |
|---|---|
| P5-D-1 Naming | **The address.** One configured domain, with a staff-confirmed `firstname.lastname`-style local part and a numeric suffix on collision. Only `example.test` is used now. **Exceptions:** a reviewed exception for one-part, non-Latin or preferred professional names. **Conflict checks:** system and role addresses are reserved, and mailboxes, aliases (forwarders) and pending reservations are all checked. Someone else's address is never silently reused. The production domain is a separate activation decision. |
| P5-D-2 Quota and sending | 1024 MB and 100 messages per day as configurable, labelled synthetic test defaults. They are not permission to change the real plan and not a capacity estimate. No unlimited quota, and no quota-0 "disable". Live limits need the account's capacity verified. |
| P5-D-3 Approver | The owner is the initial approval authority. Delegates need explicit named grants. The approval covers the exact address, quota, prerequisite snapshot and method shown. No model or generic operator may approve access. Only synthetic identities and grants are created here. |
| P5-D-4 Method | API-first against a local fake of the documented operations, with a recorded operator-checklist fallback. One workflow, one narrow adapter. No account-wide key is stored in web settings or routine worker environments (section 3). |
| P5-D-5 Verification | **Preferred:** an authoritative read of that specific mailbox, tied to the controlled request. **Checklist fallback:** a panel-listing attestation by a different named verifier from the creator. **Not proof:** an accepted SMTP test message is supplementary delivery evidence only; it does not prove a particular mailbox, its ownership or the applicant's access. **Conflicts:** an existing account Catalyst did not create is a conflict, never adopted or reset automatically. |
| P5-D-6 Credentials | **Target: option (a), a one-time "set your own password" flow.** No initial password is emailed. The application behaviour is built against the fake. **Pre-live gates:** the account's real capability and secure privilege separation. No forced first-login change is implemented or described unless provider enforcement is established. Option (b) is a separately approved contingency, never a silent fallback. |
| P5-D-7 Other access | The company mailbox only. No LMS, GitHub, Slack or other grants in this batch. Those future dependencies are recorded without calling the applicant "active" in every external system. |
| P5-D-8 Withdrawal path | An explicit, authenticated and verified withdrawal confirmation: GET displays, POST commits. Email text creates a review item and never withdraws anyone automatically. A staff-mediated path is available if the original contact channel is unavailable. |
| P5-D-9 Effect on access | **Goal:** revoke access without deleting mailbox data, preferring verified provider suspension or session revocation where supported (neither is documented today, section 3 fact 8). **Steps, not proof:** password rotation and removing forwards. Revocation outcomes are tracked separately as requested, pending, verified and exception. **On withdrawal:** outstanding setup links are cancelled, and old credentials, existing sessions, client connections, delegated and app credentials, and forwarding and filter paths are checked where applicable. A check that cannot be supported stays unresolved; it is never assumed successful. **Never:** disabling a whole hosting account or domain to remove one person's access. POL-10 controls any later deletion. |
| P5-D-10 Reopening | No generic reopening of terminal cases. A new application never inherits earlier permissions, mailbox control or valid links. Existing policy exceptions and identity conflicts need review. |
| P5-D-11 No response | No automatic closure when there is no response. Staff close explicitly. Aging work is shown with its owner, without endless reminders or silent abandonment. |

**Carried from P4 (D-46):** the correspondence decision-maker resolves routine agreement causes, and one qualified
person may record and confirm required details as two audited actions.

## 9. Acceptance plan (GATE-P5), amended 0.2.0

TEST-P5-01 to TEST-P5-05 keep their meaning from `004`. The numbered cases below are mapped in `tests/acceptance.py`
in 5C.

| Case | Must show |
|---|---|
| TEST-P5-01 | Provisioning starts only through the owner's activation, on an application at `agreements_complete` whose prerequisites still hold. |
| TEST-P5-02 | A changed prerequisite (an integrity hold, custody, details, contact, pause, delivery block, withdrawal) refuses at every effect boundary, not only at release. |
| TEST-P5-03 | Activation needs verified provisioning **and** completed credential setup. A sent invitation is not enough. |
| TEST-P5-04 | The welcome is queued in the activation transaction and sent later; a welcome bounce opens a staff item. |
| TEST-P5-05 | Withdrawal and closure stop provisioning and record every revocation obligation, without deleting anything. |
| TEST-P5-06 | Naming: reserved and role addresses are refused; a collision gets the next suffix; an exception needs review; someone else's address is never reused. |
| TEST-P5-07 | Approval binds the exact address, quota, limit, method and prerequisite digest; a stale screen refuses. |
| TEST-P5-08 | A request and its attempt are committed before any adapter call. |
| TEST-P5-09 | An uncertain create is reconciled by reading that mailbox. An existing mailbox Catalyst did not create is a conflict, never adopted. |
| TEST-P5-10 | Duplicate or concurrent requests never create a second mailbox or overwrite another. |
| TEST-P5-11 | On the checklist path, the verifier must differ from the creator. |
| TEST-P5-12 | An SMTP acceptance alone never verifies a mailbox. |
| TEST-P5-13 | The setup token is hash-only, single-use and expiring. A repeated or expired link refuses. A new invitation cancels the old one. |
| TEST-P5-14 | The invitation goes to the verified external address, re-checked at send time and at redemption, never to the new mailbox or any company-domain address; the token is minted at send time and only its hash is stored. |
| TEST-P5-15 | The chosen password appears in no record, event, log, exception or payload. |
| TEST-P5-16 | An unknown password-set outcome blocks activation and is never replayed blindly. |
| TEST-P5-17 | Stop intent survives an in-flight create or credential operation. A late mailbox is recovered without a welcome or reactivation. |
| TEST-P5-18 | Revocation outcomes are tracked separately. An unsupported check stays unresolved. No whole-account suspend is ever called. |
| TEST-P5-19 | The staff screen shows approval, creation, verification, setup, activation and revocation separately; actions need their permissions and CSRF; typed values are kept on a refusal. |
| TEST-P5-20 | Managing access never grants reading applicant mail or signed documents. |
| TEST-P5-21 | Withdrawal confirmation: GET displays and POST commits; an emailed "withdraw" only creates a review item. |
| TEST-P5-22 | No automatic no-response closure; reopening inherits nothing. |
| TEST-P5-23 | The live adapter and any provider key are refused outside an authorized environment. |
| TEST-P5-24 | The synthetic journey from intake to agreements to mailbox to activation, and from withdrawal to revocation, over Django HTTP. |

## 10. Build slices, amended 0.2.0

| Key | Scope | Bead |
|---|---|---|
| 5B.1 | records, release and effect-boundary rechecks, naming reservations, approval, the fake adapter, the checklist with an independent verifier, uncertain-create reconciliation, collision serialization | `catalyst-v2-tuc.3` |
| 5B.2 | the setup invitation and token, the set-password page, transient credential transfer, unknown-outcome recovery, activation and the queued welcome | `catalyst-v2-tuc.4` |
| 5B.3 | withdrawal and closure, durable stop intent, revocation obligations, late-mailbox recovery, the provisioning staff screen, separated permissions | `catalyst-v2-tuc.5` |
| 5C | the GATE-P5 map, the journey, the after-action report; a draft for the owner | `catalyst-v2-tuc.6` |

Each slice gets a focused security and reliability review before it is built where it is sensitive (5B.2 and
5B.3), then a QA review before its merge.

## 11. Design resolutions after the pre-build reviews (0.2.1)

A focused security review and a reliability review read 0.2.0 before any 5B code. Their blockers and highs are
resolved below.

- **Engineering defaults** (no tag) are design choices inside the owner's decisions. The owner may change them.
- **OWNER** marks a question only the owner can settle. None of them blocks synthetic work.
- Where a resolution changes an earlier section, this section governs.

### 11.1 Where the privileged operation runs (security BLOCKER 1)

- **Live design: a separate credential service.**
  - It runs as its own process and OS user, holding the provider key as a service credential rather than an
    environment variable.
  - It uses a key for one hosting user, never a reseller key.
  - It exposes one narrow local call per operation: create mailbox, set password for a setup, rotate, list and
    remove forwarders, read the catch-all.
  - It validates the setup token's hash and state itself, so the web process cannot pick an arbitrary target.
  - The password exists only in the web request and in the service's memory. It never enters the database or a
    queue.
- **Synthetic build.** The same interface is implemented by the local fake, in process. 5B builds against the
  interface and never against a key.
- **Before live:** running the real service, its key custody and its OS isolation are the pre-live privilege
  separation that P5-D-6 already names.
- **OWNER, at pre-live:** this design (P1) or the sealed-box fallback (P2, a short-lived ciphertext in a job row).

### 11.2 The setup invitation (security BLOCKER 2; reliability BLOCKER 1)

The invitation is a new secret-bearing kind built in 5B.2. It is a deliberate, recorded exception to the `016`
re-render pattern.

- **Minting.** The worker mints a CSPRNG token at send time and stores only its hash on `CredentialSetup`. The frozen
  message holds identifiers only (the setup and its series). The body with the link exists only in memory during
  the send.
- **No Sent copy** is filed (as for every secret-bearing kind).
- **Uncertain send.** An uncertain or unknown send is never reconciled by evidence. It **supersedes**: the old token
  is cancelled and a new series mints a new token. After `CATALYST_SETUP_INVITE_MAX_SERIES` series (a synthetic
  default of 3), staff decide. **OWNER:** the production bound.
- **Base URL.** The link uses the configured public base URL only, never the Host header.

### 11.3 When a mailbox is "ours" (reliability BLOCKER 2)

A mailbox counts as ours only by **evidence within a window**:

1. In the same claim, immediately before the create call, an authoritative read of that exact normalized address
   returns "absent". The read and its result are recorded on the attempt.
2. After an unknown or `CONFLICT` outcome, a later read finds the mailbox.

Anything else is a `conflict` for staff, never adoption: an existing mailbox with no recorded "absent" read, a read
answering 500, or a found mailbox whose quota or limit differ from the request. The residual risk is a person
creating the same address in the panel inside the window. Staff therefore confirm every `found_by_evidence`
outcome with a one-step item before verification.

**OWNER, at pre-live:** whether a login probe with a create password derived in the service may strengthen this.

### 11.4 Fresh reads and effect boundaries (reliability HIGH 3)

The prerequisite function factored out of the P4 hand-off is evaluated at each boundary, with a fresh Documenso
read outside any transaction where noted. It covers agreement integrity, custody, details, the verified contact,
pause, delivery blocks and stop intent.

| # | Boundary | Fresh provider read |
|---|---|---|
| B1 | release | yes |
| B2 | the create's check transaction | yes |
| B3 | the create's result transaction | no (stop flag only) |
| B4 | before an invitation is sent | no (P2 send checks plus the request state) |
| B5 | the password-set compare-and-set | no (stop flag and token) |
| B6 | activation | yes |
| B7 | the welcome send | no (P2 checks) |

### 11.5 Password set, stop and revocation ordering (reliability HIGH 4 and 5)

**The set-password protocol** is a web request with compare-and-set; it is not a ledger action, so the password never
enters a payload.

1. Under a row lock, check the state is `invited` or `presented`, the token hash, the expiry, a non-terminal
   application and no stop intent. Then move to `set_pending` and stamp the start time. Commit.
2. The service call runs outside any lock.
3. A second transaction records `completed`, or `set_uncertain` on an unknown outcome.
4. A sweep moves any `set_pending` older than the provider timeout to `set_uncertain`.

`set_uncertain` cannot be resolved by reading. The recovery is a new invitation; the old setup is superseded.

**Stop intent** is a `stop_requested_at` column on `ProvisioningRequest`, not a status. It is written in the
withdrawal or closure transaction together with:

- the stage change;
- cancelling queued invitations and welcome sends;
- cancelling the setup;
- the revocation obligations;
- the event.

Every result transaction takes the application lock first, so it serializes with the stop. A mailbox found under
stop is `recovered_after_stop`: no welcome, no reactivation, and its revocation obligations are added.

**Rotation never runs while any setup is `set_pending`.** It then repeats once after a settle delay longer than the
provider timeout. This is safe because the new value is random and unknown. It means a late password write cannot
outlive revocation.

### 11.6 Revocation states (security HIGH 4; reliability MEDIUM 11)

**States for each obligation:**

- `requested`
- `applied_unverified`: a write was accepted but cannot be read back, as with a password rotation
- `verified`: only for state that can be read back, such as a forwarder list or the catch-all
- `not_applicable`
- `unsupported`
- `exception`

**Obligations**, unique per request and kind:

- cancel setup links;
- rotate the password;
- remove forwarders owned by the mailbox, and forwarders whose destinations name the address;
- the domain catch-all and pointers naming the address;
- existing sessions, client connections, and app or delegated credentials. These are `unsupported` until a
  documented mechanism exists.

**Rollup:** revocation is complete only when the request is settled and every row is `verified`,
`applied_unverified` (with the accepted limitation shown), `not_applicable`, or an owner-accepted `exception` (11.11).
An `unsupported` or `pending` row keeps a staff item open, with its age shown.

### 11.7 States, keys and the stage (reliability HIGH 5 and 6, MEDIUM 12; LOW 16)

**`ProvisioningRequest`:**

```text
awaiting_approval -> approved -> create_pending -> created | create_uncertain | conflict | failed_needs_staff
create_uncertain -> found_by_evidence (staff confirm) -> created | conflict | failed_needs_staff
created -> verified | verify_uncertain -> verified | failed_needs_staff
verified -> setup_pending -> setup_complete -> active
with stop_requested_at: create_* -> stopping -> stopped | recovered_after_stop; created and later -> stopped
```

**`CredentialSetup`:**

```text
invitation_pending -> invited | invitation_uncertain | invitation_failed
invitation_uncertain -> superseded (bounded) | staff
invited -> presented -> set_pending -> completed | set_uncertain | presented (a definite rejection, bounded) | superseded
set_uncertain -> superseded
invited | presented -> expired | cancelled | superseded
```

**Keys.** `provision:<application>` stays the release gate only. The request's own actions carry their own keys:

- `provision_create:<request>:<series>`
- `provision_reconcile:<attempt>:<n>`
- `provision_verify:<request>:<n>`
- `setup_invite:<setup>:<series>`
- `setup_sweep:<setup>`
- `activate:<request>`
- `revoke_<kind>:<request>`

The welcome uses the P2 send key.

**Stage.** The existing `provisioning` stage marks provisioning in flight. Release moves `agreements_complete ->
provisioning` by compare-and-set, and activation moves it to `active`.

### 11.8 Smaller rules (security MEDIUM 6 to 10; reliability MEDIUM 9, 10, 13 and LOW 14, 15, 17)

**The set-password view:**

- `sensitive_post_parameters`; the password field is never re-rendered, and the page keeps no typed values;
- a test with a deliberate exception;
- `Referrer-Policy: no-referrer` and `Cache-Control: no-store`;
- GET never consumes the token, so link previews are harmless;
- identical failure pages for an unknown, used, expired and cancelled token.

Access-log redaction of the setup path is a P6 item (`024` row 5).

**The invitation recipient** is re-checked at send time and at redemption: still the current verified contact, no
delivery block, no stop, and never an address in the company domain.

**The adapter:**

- it has no delete method at all;
- it refuses any path outside the configured domain's mailbox, forwarder, catch-all and pointer endpoints, and every
  reseller endpoint;
- it uses the P4 error taxonomy, where only a 4xx other than 429 is definite;
- its audit uses an allowlisted schema, so a password is never logged and request bodies and HTTP-client exceptions
  are never captured;
- a create password is generated inside the call, never in a plan object.

**The database:**

- reservations are unique on the normalized `lower(local)@domain`;
- one live request per application;
- quota of at least 1, and a limit between 1 and 9600.

**Leases.** A fence between sub-steps, and a settle grace before the first reconcile read.

**Provider password rules beyond 8 to 72 characters are unknown.** A 400 with `field: password` is definite and safe
to retry with a new choice, with a generic message to the applicant.

### 11.9 Welcome recipient (reliability HIGH 8)

The welcome goes to the verified external address and names the new mailbox. The applicant may not yet read the new
mailbox. **OWNER:** confirm.

### 11.10 Owner questions left open

None of these blocks synthetic work:

- P1 or P2 for the live credential service (11.1);
- a login probe to strengthen "ours" (11.3);
- the production bound on invitation series (11.2);
- the welcome recipient (11.9);
- the key type our account allows, and the server's password rules. These are pre-live checks that need a separately
  authorized live look.

### 11.11 Re-check amendments (0.2.2)

- **Retiring a live request.**
  - A `ProvisioningRequest` can end `superseded`. Staff open a replacement when a prerequisite changed after release,
    and that needs a new approval.
  - The stage stays `provisioning` while any request is live. It returns to `agreements_complete` by compare-and-set
    only when the last request ends without a mailbox (`superseded`, `conflict` or `failed_needs_staff`) and no watch
    is open.
- **Watching an abandoned create.**
  - A create that ended `conflict` or `failed_needs_staff` after an unknown outcome gets a bounded watch, in the D-44
    pattern, with keys `provision_reconcile:<attempt>:watch:<n>` and a re-arm limit.
  - The reservation stays held while any watch is open.
  - A late match is treated like `recovered_after_stop`: rotate and revoke, never delete, and open a staff item.
- **B2 ordering.** The fresh Documenso read runs outside any transaction. The check transaction then re-checks the
  database facts and the read's digest, and commits the attempt as `sending`. The mailbox "absent" read and the
  create call run after that commit.
- **`CONFLICT` provenance.** A `CONFLICT` on a first create, with no earlier unknown attempt of ours, is a foreign
  mailbox: straight to `conflict`. Only an unknown outcome, or a `CONFLICT` after our own earlier unknown attempt,
  reaches the `found_by_evidence` confirmation.
- **Repeating keys.** Every revocation kind that can repeat carries a sequence number, for example
  `revoke_rotate:<request>:<n>`.
- **The invitation kind.** It has its own handler, and its uncertain outcome never enqueues the P2 `reconcile_send`
  or opens `send_outcome_unknown`; it supersedes instead (11.2). The P2 `_freeze` refusal of secret-bearing
  templates stays for every other kind.
- **A definite password rejection.** A 400 on `field: password` moves `set_pending` back to `presented` for another
  choice, up to `CATALYST_SETUP_SET_ATTEMPTS` (a synthetic default of 3), then `superseded`.
- **Shared forwarders.** Only forwarders owned by the mailbox are deleted automatically. A forwarder that names the
  address among other destinations, a catch-all or a pointer naming it becomes an `exception` for staff. The API
  cannot edit a forwarder, and deleting a shared one would cut off its other recipients. The service gains a
  pointer read.
- **"No delete method"** means no mailbox, domain or reseller deletion. The adapter still deletes forwarders owned by
  the mailbox.
- **Open revocation items can end.** `unsupported` rows (sessions, app credentials) end only by an explicit,
  owner-accepted `exception` with a recorded reason. That acceptance is shown on the screen and is never automatic.
- **Setup-path log redaction** stays a blocking pre-live gate (`024` row 5).

## 12. The 5B.1 record: approved provisioning against the fake (D-47)

**Built** (the `provisioning` app; migrations `0001` and `0002`):

- **Records:** `AddressReservation`, `ProvisioningRequest`, `ProvisioningAttempt` and `ProvisioningEvidence`, with
  their constraints.
  - One live reservation per normalized address, and one live request per application.
  - The quota is at least 1, and the send limit is between 1 and 9600.
  - Approval is consistent and written once.
  - At most one open create per request.
- **Protections, for every role:**
  - a request's identity, limits and digests are fixed, and its approval, stop and supersession are set once;
  - a reservation's address is fixed, and its release is written once;
  - an attempt's identity is fixed, and a settled outcome is final;
  - evidence is append-only;
  - a checklist attestation by the creator is refused;
  - nothing is deleted or truncated.
- **Permissions:** `approve_provisioning` and `operate_provisioning`, assigned to no group.
- **`agreements.completion.prerequisites`:** one function for the P4 hand-off and every P5 boundary.
  `fresh_read_problem` is the fresh Documenso read, outside any transaction, and opens the D-43 integrity hold on a
  mismatch.
- **The release command `activate_provisioning`:** versioned, and needs an approval reference. Its steps:
  - B1's fresh read;
  - the database checks under the lock;
  - the naming rule, with suffixes, reserved and role names, and a reviewed exception through `reserve_exception`;
  - one request awaiting approval;
  - the stage `agreements_complete -> provisioning`.
- **`approve`:** the approval digest covers the exact address, limits, method and prerequisite digest.
- **`CreateMailbox`, the 11.4 B2 order:**
  1. a fresh read;
  2. the check transaction, which commits the attempt;
  3. the authoritative "absent" read;
  4. one create with a random password nobody sees;
  5. the fenced result.

  A mailbox present before the create, or a `CONFLICT` with no earlier unknown create of ours, is foreign and never
  adopted. A `CONFLICT` after our own earlier unknown create, and every unknown outcome (a 429 after sending included),
  goes to `ReconcileMailbox`, never to a blind repeat.
- **`ReconcileMailbox`:**
  - a present mailbox, absent before our create and with matching limits, is `found_by_evidence` for staff to
    confirm;
  - an absent one after the bounded checks is "not created", and a new series runs;
  - a 500 is unknown;
  - in watch mode, after supersession, it reports a late mailbox and keeps the reservation until the watch ends.
- **`VerifyMailbox`:** the authoritative read; an SMTP acceptance never counts.
- **The checklist path:** a recorded creation, and an attestation by a different named operator (refused for the
  creator by the service and the database).
- **`supersede`:** the reservation is released only when no mailbox may exist. With no live request left, the stage
  returns and a new held hand-off awaits release and a new approval.
- **Guards:** the adapter must be a test fake and the domain a `.test` domain, never set from the environment, and
  empty outside `test`. The quota is never unlimited.

**Evidence:** `tests/test_provisioning.py` (20 tests, TEST-P5-01, 02, 06 to 11 and 23, supersession, the watch and
the protections), with the fake in `tests/mxroute_fake.py`.

**Not yet:** the credential setup and activation (5B.2); withdrawal, revocation and the staff screen (5B.3). Stop
intent is honoured where 5B.1 records an outcome (`recovered_after_stop`); writing it is 5B.3.

**After the reviews of PR #53** (QA: three HIGH; security: one HIGH; no blocker):

- **A 429 after the create was sent is unknown.** It is reconciled by reading, so an address is never freed while a
  mailbox may exist.
- **Release** records a prerequisite change since the P4 hand-off and binds today's snapshot into the new approval
  (the approver always confirms the current state). It reuses only an unused reviewed exception. Otherwise it proposes a fresh address that is not live for
  anyone and was never tried at the host by this application. A returned hand-off is checked against today's
  prerequisites. Every refusal leaves a staff item. A dry run writes nothing.
- **The stage returns only when no live request and no watch remain** (`return_stage_if_idle`). A watch never
  releases a reservation that a live request uses. `release_address` lets staff release a held address after a watch,
  with a reason, so the application can move to another address.
- **A request can be superseded once no work is in flight**, including after a stuck reconcile.
- **Every effect boundary includes the pause.**
- **Ordering:**
  - an earlier open attempt is reconciled before any other check;
  - the adapter and domain are checked before an attempt is committed;
  - the absent read is recorded under the fence.
- **New series after "not created" are bounded.**
- **The adapter's error codes are sanitized**, so no body or address can reach a record. No exception traceback
  outlives the create call.
- **Notes that look like credentials are refused.** Mail-host credential names in the environment are refused.
- **The database refuses `..` in a local part.**

**Residual limits:**

- The provider-side check of a proposed address (existing mailboxes and forwarders) happens only at the create's
  absent read: the adapter has no list or forwarder operation yet.
- No two-worker race test exists (NOT RUN). Serialization rests on the one-open-create and one-live-request unique
  indexes, which are tested directly. A lost lease between the absent read and the create is handled by the fence
  but is not exercised by a test.
- After an attempt settles, its `code` and `finished_at` stay writable; the outcome itself is final.
- **OWNER:** one `approve_provisioning` holder may both reserve a reviewed exception and approve it, which is a
  one-person control. This matches D-47's owner-as-approver; confirm it is accepted.
- **OWNER (POL-10):** free-text notes in append-only evidence have no purge path.

## 13. The 5B.2 record: setting the password and activation (D-47)

**Built:**

- **`CredentialSetup`** (migrations `0003` and `0004`): one invitation series for a verified mailbox.
  - The recipient (the verified external address) and the series are fixed.
  - The token's SHA-256 is written once.
  - A settled series is final, and an uncertain one can only be superseded.
  - There is one live series per request. Nothing is deleted or truncated.
- **Opening a series** (`open_setup`): a verified mailbox, by the API read or the checklist attestation, opens a
  series. The recipient is never the new mailbox or any address in the company domain.
- **`SendSetupInvitation`:**
  - It re-checks the effect boundary and the recipient at send time.
  - The worker mints the token, sends the link (built from the configured base URL) and stores only the hash.
  - An uncertain send supersedes the series and opens a new one with a new token, up to
    `CATALYST_SETUP_INVITE_MAX_SERIES`; then staff decide. A crash after sending counts as uncertain.
- **The applicant's page** (`/setup/<token>/`):
  - GET shows the form and never consumes the link.
  - POST commits under 11.5's compare-and-set. The credential operation runs outside any lock, with the password in
    memory only.
  - A definite rejection lets the applicant choose again, up to `CATALYST_SETUP_SET_ATTEMPTS`.
  - An unknown outcome is `set_uncertain`, never read back, and a new invitation follows.
  - Every refusal is the same page.
  - `sensitive_post_parameters`; nothing typed is re-rendered.
  - Private, no-referrer responses, and the token is redacted from Django's logs (the confirmation-link protections,
    extended to the setup path).
- **Inbound mail:** redaction version 2 removes a quoted setup link the way it removes a confirmation link.
- **`SweepSetup`:** a `set_pending` past the timeout becomes `set_uncertain`, and a new series opens.
- **`Activate`:**
  - B6's fresh Documenso read;
  - then one transaction: the prerequisites, verified provisioning and a completed setup;
  - `provisioning -> active`;
  - the approved `provisioning_welcome` (a synthetic draft seeded by migration, sent only once the owner approves
    it) is frozen and queued for the P2 sender, to the verified external address, naming the new mailbox.

  Without an approved welcome, or before setup completes, activation refuses with a staff item.
- **The `welcome` approved-message kind** (correspondence migration `0016`).

**Evidence:** `tests/test_credentials.py` (22 tests, with the review regressions): TEST-P5-03, 04, 13 to 16, the
protections and the recipient re-check at send and redemption, plus the redaction case in `tests/test_inbound.py`.

**Limits:**

- The link has no per-IP rate limit. Attempts are bounded per setup (`CATALYST_SETUP_SET_ATTEMPTS`), and unknown
  tokens cost one indexed lookup each.
- Access-log redaction at a proxy is a P6 gate (`024` row 5).
- The credential service's process isolation is the pre-live P1/P2 choice (11.1). Synthetic P5 calls the fake in
  process.
- The welcome's own delivery failures follow P2 (a bounce opens a staff item; the stage stays `active`).

**After the reviews of PR #54** (security: one HIGH; QA: four HIGH; no blocker):

- **The recipient is re-checked at redemption.** At GET and in the POST's locked check, it must still be the current
  verified contact and outside the company domain. Otherwise the same closed page, and nothing is set.
- **An unused link ends visibly.** At expiry, `setup_expire` moves it to `expired` and opens a new series, bounded.
  At the bound, or after a cancelled or refused series, staff send a fresh link with `reissue` (a reason; any live
  series is superseded first).
- **Activation is never silently final.**
  - It now needs the request at `setup_complete`, a completed setup with its timestamp, and a recorded verification
    of this request.
  - The welcome is frozen before the stage moves, so there is no activation without a welcome to send.
  - A refusal opens a staff item. Staff run it again with `retry_activation`, a reason and every check repeated, once
    the cause is fixed (for example after the owner approves the welcome template).
- **A sweep acts only on its own attempt, and only after the timeout.**
- **The password is protected in error reports:** `sensitive_variables` on the view and on `set_password`, and a test
  that fails inside the recording transaction.
- **The checklist path never calls the API for the credential.** It opens a staff item, because option (b) is a
  separately approved contingency.
- **An https guard:** outside test and development the public base URL must be https.

**Recorded deviation.** The invitation is sent by its own handler, in the S1 verification pattern (a link built at
send time, only the hash kept). It is not sent as a frozen P2 `ApprovedMessage`, so it has no `OutboundMessage` row
and no P2 Message-ID: a bounced invitation is not matched to the application. The protective behaviour is that an
uncertain send supersedes, and an unused link expires into a new series or a staff reissue.

**Pre-live gates added:**

- The credential operation's timeout must be well below `CATALYST_SETUP_SET_TIMEOUT_SECONDS`, so a late write cannot
  land after a newer series.
- Secure cookies, HSTS and an https redirect (`024`).

**OWNER:**

- the password policy beyond 8 to 72 characters (validators, or rely on the provider);
- the production link lifetime;
- the set of company domains the invitation must avoid;
- whether to accept, until P6, that `/setup/` has no rate limit.

## 14. The 5B.3a record: withdrawal, closure and access revocation (D-47)

5B.3 is split into two pull requests: 5B.3a (this record) builds the service and revocation, and 5B.3b builds the
applicant-centred staff screen (TEST-P5-19, 20).

**Built** (migrations `0005` and `0006`; `provisioning/closure.py`):

- **`close_locked`: the one POL-12 move to `withdrawn` or `closed`.** In one transaction it:
  - stops unfinished agreements (P4 `stop_locked`, factored out of `stop_agreements`);
  - records the stop intent on every live or active provisioning request: a create in flight becomes `stopping`, and
    everything else `stopped`;
  - cancels queued creates, invitations, activations and the held hand-off;
  - cancels live setups;
  - records the revocation obligations wherever a mailbox may exist.

  It never deletes mailbox data, never suspends a whole hosting user or domain, and never reopens or closes twice
  (P5-D-10).
- **Staff `close_application`:** needs the `close_application` permission (assigned to no group) and a reason. It
  covers a closure, and a withdrawal the applicant asked for through staff (the staff-mediated path of P5-D-8).
- **The applicant's withdrawal** (`request_withdrawal_link`, `/withdraw/<token>/`):
  - Staff send a one-time link on the applicant's request.
  - The worker mints the token at send time and stores only its hash.
  - GET shows what withdrawing means, and POST commits.
  - The recipient is re-checked, a new link supersedes the old one, and every refusal is the same page.
  - Private, no-referrer responses and log redaction. Inbound redaction version 3 removes a quoted withdrawal link.
  - An emailed "withdraw" is only ever a review item.
- **`AccessRevocation` and `RevokeAccess`.** The obligations are:
  - **Setup links:** cancelled, so verified.
  - **Password rotation:** to an unknown value; `applied_unverified`, because it cannot be read back. It never runs
    while a set is pending, and repeats once after a settle delay.
  - **Owned forwarders:** removed, and verified by listing again.
  - **Forwarders that name the address among other destinations, and a catch-all naming it:** `pending` with a staff
    item, never deleted automatically.
  - **Sessions and app credentials:** `unsupported`, ending only by `accept_revocation_exception` (the approver, with a
    reason).

  A late mailbox found under stop (`recovered_after_stop`) gets the same obligations, with no welcome and no
  reactivation. Revocation is complete only when every obligation is verified, applied with its stated limit, not
  applicable, or an accepted exception.
- **The adapter** gains the documented forwarder list and delete, and the catch-all read. The fake supports them.

**Evidence:** `tests/test_closure.py` (20 tests, with the review regressions): TEST-P5-05, 17, 18, 21, 22, the
protections, the settle and proof rules, and the stop paths.

**Not yet (5B.3b):** the staff screen through which staff do all of this (TEST-P5-19, 20), and a staff action for
shared forwarders and the catch-all.

**No automatic no-response closure exists** (P5-D-11). Closure is always an explicit act.

**After the reviews of PR #55** (QA: one BLOCKER and four HIGH; security: one HIGH; all fixed):

- **Revocation acts only on a mailbox proven ours, and only once the request is settled.**
  - "Proven ours" means our create succeeded, the checklist creator recorded it, or staff confirmed a found mailbox
    (`confirm_found_mailbox`, now also for a mailbox found under a stop or by a watch).
  - "Settled" means no create or reconcile is still open.
  - A mailbox present at the address but not proven ours waits for staff; a refusal settles it as foreign. A
    foreign mailbox is never rotated or touched.
  - "Not applicable" is written only for a settled request that never produced a mailbox of ours. So it is never
    written early and then frozen.
  - Under a stop, a create judged "not made" starts a bounded watch, and revocation stays unsettled until the watch
    ends.
- **The stop covers every request of the application.** Superseded, failed and conflicted requests record stop intent
  too. A request never sticks at `stopping` (a not-sent create, a block, or a rejected or foreign result settles it).
- **Sessions and app credentials are `unsupported` only for a mailbox of ours.** For a request that never had one they
  are not applicable.
- **Exceptions:** only sessions, app credentials, shared forwarders and the catch-all can be accepted as exceptions. A
  rotation or an owned forwarder never can. The rollup resolves the staff item.
- **Each removed forwarder is recorded** (its alias and a digest of its destinations).
- **A shared forwarder or catch-all fixed in the panel is verified only by a new read** (`recheck_revocation`).
- **The rotation's random value** is confined to a helper, and any failure is reduced to a code.
- **The withdrawal link:**
  - a refused withdrawal gives the same closed page and a staff item, never a server error;
  - a new link supersedes one still sending;
  - a lost send opens a staff item;
  - a pause never holds the applicant's own request;
  - the request and the confirmation are recorded with identifiers.
- **Items are tidied on close.** Open checklist, setup, activation, failed and blocked items are resolved; a confirm
  item stays until staff decide.

**Limits:**

- A verified shared-forwarder or catch-all check is a point-in-time read.
- MXroute's behaviour when a forwarder and a mailbox share a name is NOT VERIFIED.
- Forwarder listing completeness (pagination) is a live-adapter gate.
- **OWNER:** the withdrawal link's production lifetime, and whether a notice follows a withdrawal.
