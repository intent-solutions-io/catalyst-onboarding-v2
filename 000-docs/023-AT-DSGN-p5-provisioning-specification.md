# P5 Provisioning, Activation and Withdrawal Specification (handoff 5A)

| Field | Value |
|---|---|
| Document | `023-AT-DSGN-p5-provisioning-specification` |
| Version | 0.1.0 (draft for owner review) |
| Status | **PROPOSED.** Prepared under D-40 as preparation only: no P5 code, no mailbox, no MXroute account access, no credential, no policy activation. Nothing here is approved until the owner records a decision in `011` section 4. |
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

## 3. MXroute capabilities (research, 2026-10-18, public pages only)

| # | Fact | Tag |
|---|---|---|
| 1 | Mailboxes are created, deleted, re-passworded and given quotas in the control panel. Username before the @; password 8 to 72 characters; quota in MB (0 means no separate cap); a daily send limit of 1 to 9600. Bulk CSV import is capped at 200 rows and skips existing accounts. The pages also state a separate 400 per hour maximum. "Deletion removes the mailbox's messages and data." | DOCUMENTED, [email accounts](https://docs.mxroute.com/docs/email-accounts.html) |
| 2 | Control Panel API keys "grant programmatic hosting-management access". Each request sends `X-Server`, `X-Username` and `X-API-Key`. There is no per-key permission editor and no IP restriction. Request formats and operations are documented only behind a "View API Documentation" link inside the panel. | DOCUMENTED, [API keys](https://docs.mxroute.com/docs/panel/api-keys.html) |
| 3 | The SMTP API sends mail only and uses mailbox credentials. | DOCUMENTED, [SMTP API](https://docs.mxroute.com/docs/api/smtp-api.html) |
| 4 | Which mailbox operations the panel API supports, whether our plan includes it, and its idempotency and error behaviour. | **NOT VERIFIED**: the documentation is behind the account login |
| 4a | Whether the panel offers a way to **disable or suspend** a mailbox. The pages document create, delete, password change and quota only; a quota of 0 means "no separate cap", so it is **not** a way to disable. | **NOT VERIFIED** |
| 4b | Whether an applicant-facing "set your own password" flow exists. None is documented. | **NOT VERIFIED** |
| 5 | Community reports of a DirectAdmin-style call failing with "You do not own that domain". | community only, [thread](https://community.mxroute.com/t/api-you-do-not-own-that-domain/1778); not evidence |

**Consequence.**

- **Proposed default path.** The fallback in `004` J-14 is the proposed default design: an **operator checklist with recorded
  evidence**. Staff create the mailbox in the panel and record what they did, and Catalyst then verifies the
  mailbox exists (section 5).
- **Automation is a separate later step (proposed).** An automated adapter stays behind an owner decision.
  - **Reading the API documentation may itself mint the credential.** The page says to open "View API
    Documentation" after creating a key. So the documentation look must be authorized under the same written owner
    acceptance as a production key, and that key revoked afterwards.
  - **The key is all-powerful** (no scopes, no IP limits; fact 2). Encrypting it at rest (SOPS) is necessary but not
    sufficient. Acceptance should also require:
    - a dedicated worker kind as the only process that decrypts it;
    - a narrow adapter exposing only the approved operations;
    - an audit record for every call;
    - an alert on any deletion;
    - a rotation and revocation procedure.

## 4. Records (`provisioning` app, ADR-01) — PROPOSED

| Record | Holds | Protection |
|---|---|---|
| `ProvisioningRequest` | the application; the proposed address (local part and domain); how it is provisioned (`operator_checklist` or `api`); the prerequisite digest it was released under; a status; who approved it | approval columns set once; identity insert-only; one live request per application |
| `ProvisioningEvidence` | for the checklist path, what staff recorded (the panel action done, when, by whom, a free-text note); for the API path, the allowlisted response | append-only |
| `MailboxVerification` | how existence was checked (a second person's panel-listing attestation or a test message, P5-D-5) and the outcome; never a password | append-only |
| `CredentialDelivery` | the method (POL-11), when, by whom, an opaque reference, and confirmation of receipt; **never the credential** | append-only |

## 5. The P5 journey — PROPOSED

| # | Step | Records and transaction | Outcomes | Recovery |
|---|---|---|---|---|
| 1 | Release | An owner-run, versioned activation re-checks the prerequisites against the digest: every agreement still verified and stored, no integrity hold, details confirmed, not paused or stopped, the applicant's address not delivery-blocked. It then creates the `ProvisioningRequest`. | requested; refused (prerequisite changed) | a refusal leaves the action held, with a staff item |
| 2 | Address | The proposed address follows the POL-11 naming rule. Before approval, conflicts are checked: a reserved name (deterministic), and an existing mailbox or alias (on the checklist path, a recorded staff attestation from the panel, because the API is NOT VERIFIED). | approved; conflict | conflict goes to staff, who choose an alternative within the naming rule |
| 3 | Approve | A named decision-maker approves the exact address (POL-11 authority), confirmed against the digest of what they were shown. | approved | — |
| 4a | Create (checklist) | A staff task with the checklist: create the mailbox in the panel with the approved address, quota and send limit, then record the evidence. | recorded | an unrecorded task stays visible with its owner |
| 4b | Create (API, later) | The request is committed before the call; an uncertain result is reconciled by checking existence before any retry (ADR-15). | created; uncertain | never retried blindly |
| 5 | Verify | Existence is checked without using the applicant's credential (P5-D-5): a different named staff member than the creator confirms the panel listing (to be enforced in 5B.1), or a test message to the address is accepted. A failed check goes to staff. | verified; not found | bounded re-checks, then staff |
| 6 | Credentials | Delivery by the POL-11 method. The credential never enters history, logs, email bodies or this repository. | delivered; failed | staff |
| 7 | Activate | One transaction: the stage moves `agreements_complete → active`, the welcome message is sent through P2 (an approved template, delivery checks), and remaining actions close. | active | a welcome bounce opens a staff item; the stage stays `active` |

## 6. Withdrawal, closure and recovery (J-16) — PROPOSED, needs POL-12

- **Withdrawal.** The applicant asks through an explicit confirmation page reached from a link. An emailed
  "withdraw" goes to staff, never to a model or an automatic action.
- **Closure.** A decision-maker closes the application, with a reason.
- **Disabling access (interim, until a disable mechanism is verified, fact 4a):** rotate the mailbox password to an
  unknown value nobody records, remove forwards, and record the evidence. Never edit the quota to "disable" it.
  Deletion is irreversible (fact 1), so it waits for POL-10. A deletion checklist would need a second person and an
  export decision first.
- **What happens to live work:**
  - agreements: P4 `stop_agreements` (D-42);
  - provisioned access: per POL-11 and POL-12. The proposed default is a staff task to disable the mailbox by the
    interim below,
    **never automatic deletion**: MXroute deletion removes the mailbox's data (fact 1), and POL-10 governs
    retention.
- **Reopening.** Never a generic button. Whether a new application is created follows POL-01 and POL-12.
- **System recovery.** Unchanged: the pending-action ledger plus audited retry, reconcile or abandon.

## 7. Security and privacy

| Control | Status |
|---|---|
| No credential ever stored, logged, emailed in a body or shown on a screen after delivery. On the checklist path the creating operator necessarily sees an initial password (P5-D-6) | PROPOSED |
| A one-time password link, if built: the token is stored only as a hash, single-use, bound to the verified address, short-lived, resistant to enumeration, and kept out of access logs (the confirmation token's URL-path issue, `024` row 5, must not repeat). Anyone who controls the applicant's external inbox can use it, so its lifetime is short and use is audited | PROPOSED |
| The panel API key, if ever authorized, held in SOPS on the server, never in settings or the repository; its full scope accepted in writing by the owner | PROPOSED; needs the owner (fact 2) |
| Address rules enforced deterministically, never from free text | PROPOSED |
| Existence verification independent of the creation call | PROPOSED |
| Mailbox deletion never automatic | PROPOSED |
| A delivery block or a pause stops the welcome message and credential email (`9kg.3`) | PROPOSED |

## 8. POL-11 and POL-12 decision brief

| # | Decision | Recommended default | Alternatives | Blocks |
|---|---|---|---|---|
| P5-D-1 | POL-11 naming: the mailbox domain and the local-part rule | one domain chosen by the owner; local part `firstname.lastname`, with a numeric suffix on conflict | initials; an applicant-chosen name within rules | step 2 |
| P5-D-2 | POL-11 quota and daily send limit | conservative synthetic values; production values by the owner | provider defaults (1024 MB) | step 4 |
| P5-D-3 | POL-11 approval authority | a named decision-maker (the POL-05 pattern), explicit grant | any operator | step 3 |
| P5-D-4 | Provisioning method | operator checklist with recorded evidence, plus independent verification | the panel API, after the owner accepts the full-scope key in writing (reading its documentation may itself mint that key; section 3) | steps 4a and 4b |
| P5-D-5 | Existence verification method | a check that never uses the applicant's credential: a second person's panel-listing attestation on the checklist path, or an accepted test message | an IMAP or SMTP login probe (rejected as the default: Catalyst or staff would authenticate as the applicant, coupling verification to credential delivery and risking lockouts) | step 5 |
| P5-D-6 | Credential delivery | **open; needs a decision.** On the checklist path, the operator who creates the mailbox necessarily sets an initial password. Options: (a) the operator sets a random password nobody records, then a Catalyst-built one-time "set your password" link changes it (this needs the panel API, so the API decision P5-D-4 comes first); (b) the operator gives the initial password to the applicant through a channel the owner approves, and the applicant must change it at first login | email the password (refused: J-14 forbids it) | step 6 |
| P5-D-7 | Other access at activation (LMS, Slack, and so on) | none in P5; each is a separate later decision | — | step 7 |
| P5-D-8 | POL-12 withdrawal path | an explicit confirmation page from a link; an email goes to staff | email keyword | J-16 |
| P5-D-9 | POL-12 effect on provisioned access | a staff task: rotate the password to an unknown value, remove forwards, record evidence; no automatic deletion; retention by POL-10 | delete at withdrawal (irreversible) | J-16 |
| P5-D-10 | POL-12 reopening | a new application under POL-01; no reopening of a closed one | reopen in place | J-16 |
| P5-D-11 | POL-12 no-response timeout | none until decided; staff close manually | close after N days | J-16 |

## 9. Acceptance plan (proposed, built in 5B)

TEST-P5-01 to TEST-P5-05 keep their meaning from `004`. New cases:

- the prerequisite re-check at release refuses a changed digest;
- naming conflicts;
- the approval digest;
- checklist evidence without verification never activates;
- an uncertain API create is reconciled by existence;
- credentials are absent from every record and log;
- a delivery block stops the welcome message;
- withdrawal stops P4 work and opens the mailbox-disable task without deleting anything;
- the disable task never uses a quota change, and records the password rotation and removed forwards;
- the verification attestation is by a different staff member than the creator;
- reopening follows POL-01.

## 10. Build slices (proposed)

| Key | Scope |
|---|---|
| 5B.1 | records, release and re-check, address rules and approval, the checklist path, verification |
| 5B.2 | credential delivery (POL-11), activation and the welcome message |
| 5B.3 | withdrawal and closure (POL-12), the staff screen |
| 5C | the GATE-P5 run and the after-action report |
