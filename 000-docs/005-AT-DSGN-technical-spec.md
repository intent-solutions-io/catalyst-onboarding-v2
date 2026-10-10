# Technical Specification: Catalyst v2 implementation slices

| Field | Value |
|---|---|
| Document | `005-AT-DSGN-technical-spec` |
| Version | 0.2.0 (replaces the seeded template) |
| Status | **PROPOSED.** Section S1 is the first-slice specification awaiting owner approval (bead "Obtain the owner's approval of the build contract and the first-slice scope"). Nothing here is installed or written as code. |
| Owner | Jeremy Longshore |
| Date | 2026-10-09 |
| Related | `011` (work graph, policies), `002` (requirements, gates), `003` (components, ADRs), `004` (journey stages J-01 to J-03) |
| Classification | Public; synthetic data only |

> **Status: PRELIMINARY, subject to review.** This handoff specifies the slice; it does not build it.
> No package was installed, no virtual environment created, no migration or application code written.

This document holds one section per implementation slice. Later slices are added at each phase's
handoff A (`011` section 7).

## S1. First slice: synthetic intake, verification to a local mail sink, read-only staff view

### S1.1 Scope

**In scope.** A synthetic applicant submits the form → validation and duplicate handling → the
application, its submission version, a history event, a contact challenge and the next pending action
commit together in PostgreSQL → a worker sends the verification message to a local test mail sink → a
valid, explicit confirmation records verified contact control once → authorized staff inspect the same
application and its history through a read-only Django interface.

**Out of scope (and guarded against).** Real email (MXroute), MiniMax, Documenso, provisioning and Twenty;
deployment of any kind; the learn proxy; the staff hostname, network restriction and MFA (P6); reminders,
inbound mail and resend pages (P2); evidence and assessment (P3); terminal stages and their duplicate
handling (J-02 fail-closed path, P5); every later model; legacy data import (epic PL). Only the minimal
foundation the slice needs: the `config` settings package, the `accounts` app (custom user), the
`workflow` and `applications` apps, a thin outbound-message record in `correspondence`, admin
registrations, the CI runtime lane.

**Runs where.** Developer machines and CI only, against PostgreSQL.

### S1.2 Behaviour

| Step | Behaviour | Journey |
|---|---|---|
| Submit | POST to the public form; CSRF; size and field-count limits; required name, email, reason; email key computed (S1.3) | J-01 |
| Duplicate | one open application per email key (POL-01 PROPOSED default); a repeat becomes a new submission version on the open application. If contact is **unverified**: an expired or failed-to-send active challenge is superseded and a new challenge and send action are created; an unexpired active challenge whose send is queued, running or done is reused (no new work). If contact is **verified**: the version is recorded with source "unverified repeat", never replaces the verified data, and raises a staff item (an unauthenticated third party could otherwise write into a verified dossier). The applicant-facing status, body and redirect target are identical in every case, and the received page carries no application reference. | J-02 |
| Commit | application (or the existing one, locked), submission version, history event, challenge, pending action "send verification" in one transaction | J-01 |
| Send | worker claims the action (S1.4 ledger rules), sends through Django's email backend configured as a local sink, records the outbound message and completes the action with a fenced write; crash recovery by lease expiry | J-03 |
| Confirm | GET shows the confirm page with the answers of the current submission version, sets the CSRF cookie, changes no state, and sends `Referrer-Policy: no-referrer` and `Cache-Control: no-store`; POST names that version, verifies the token, locks application then challenge, checks the challenge is active and unexpired by the database clock and the version belongs to the application, records contact control, marks **only the named version** `adopted` (all others stay `unverified`), raises a staff item if any unverified version newer than the adopted one exists, writes the event and creates the "start evidence collection" action in status `held` with the adopted version as its explicit input (no handler exists in S1), all once. Confirmation proves control of the address, not authorship of other versions | J-03 |
| Staff | Django admin for a read-only staff group: application list and detail, submission versions, history, challenge state (never the token), pending actions for the application | REQ-014 |

### S1.3 Proposed defaults the owner may change

| Default | Value in S1 | Policy |
|---|---|---|
| Identity key | a stored `email_key`: trimmed, Unicode-normalized, case-folded whole address; plus-addressing **not** folded; internationalized domains converted to their ASCII form. The address as typed is kept for sending. | POL-01 |
| Open applications per identity | one | POL-01 |
| Repeat submission after verification | recorded as "unverified repeat", staff item, no effect on verified data | POL-01 |
| Challenge lifetime | a setting; tests use short synthetic values; no production number proposed | POL-02 |
| Verification message delivery | at-least-once (the identical invitation may be redelivered to the local sink after an interrupted attempt); **owner-decided for S1 only (D-20)**; no other kind inherits it | POL-06 |
| Send attempts | a setting; tests use small synthetic values | POL-16 |
| Read-only staff group | one group with exactly the view permissions on slice models, created by a data migration | POL-13 |
| Message wording | synthetic placeholder text | POL-17 |

### S1.4 Minimal data model and ledger rules (description, not code)

| Model (app) | Key fields | Constraints |
|---|---|---|
| User (`accounts`) | custom user model extending Django's `AbstractUser`, no extra fields yet | set as `AUTH_USER_MODEL` before the first migration (ADR-18) |
| Application (`applications`) | public reference (random UUID), email as typed, `email_key`, display name, stage, contact verified at, next version number, timestamps | partial unique on `email_key` where stage is open |
| SubmissionVersion (`applications`) | application, version number, origin (form submission, or repeat after verification), submitted fields (JSON), received at | unique (application, version number); content never updated by ordinary code (ADR-14) |
| VersionAdoption (`applications`) | submission version, adopted at, via challenge | unique per version; at most one current adoption per application in S1. Trust status (`unverified` or `adopted`) is derived from it, so the version row itself stays append-only |
| ApplicationEvent (`applications`) | application, kind, actor type, actor reference, occurred at, data (JSON, no secrets or tokens) | index (application, occurred at); never updated or deleted by ordinary code (ADR-14). A **staff item** in S1 is an event of kind `needs_staff_attention` with a reason; the read-only admin lists applications that have one (resolving it arrives in P2) |
| ContactChallenge (`applications`) | application, random public id, email at issue, created at, expires at, used at, superseded at | partial unique: at most one **active** challenge per application, where active means not used and not superseded (expiry is a time comparison, so an expired challenge stays "active" until a repeat submission supersedes it under the application lock) |
| PendingAction (`workflow`) | kind, subject type (string), subject id (UUID), input reference (string naming the exact input, e.g. the adopted submission version's public id; no foreign key), idempotency key, status, due at, attempts, maximum attempts, lease token, lease expires at, last error (sanitized), timestamps | unique idempotency key; index (status, due at); **no foreign key to any domain model** (ADR-01 layer rule) |
| AutomationPause (`workflow`) | subject type, subject id, reason, actor, created at | unique (subject type, subject id); S1 creates none but the worker honours it |
| OutboundMessage (`correspondence`) | application, pending action, attempt number, template key and version, recipient, Message-ID, status, sent at | unique (pending action, attempt number) |

**Allocation and locking.** Version numbers come from the application's counter while its row is locked.
Lock order everywhere is application, then challenge. The losing side of a race catches the integrity
error **for the named constraint only** (read from the database error's diagnostics), inside a savepoint,
then re-reads under `select_for_update`; any other integrity error propagates. Idempotency keys
(proposed): "send verification" keyed by challenge; "start evidence collection" keyed by application.

**Ledger rules (ADR-03, ADR-15).** ADR-03 was decided on 2026-10-10 (D-16): the custom ledger. These rules
are its requirements. The `012` proof demonstrated claiming and fenced completion only; automatic recovery
by a polling worker, pause handling, bounded attempts with the poison rule's history event, `uncertain`
outcomes, reconciliation and operational visibility are **not yet demonstrated**. S1 tests cover recovery
(TEST-S1-07, TEST-S1-17), bounded attempts and the poison rule (TEST-S1-18), pause (TEST-S1-19) and
staff visibility of pending actions (TEST-S1-12). **Recovery policy (D-20, owner 2026-10-10):** in S1 the
identical verification invitation may be redelivered to the local sink after an interrupted attempt; that
does not mean outcomes cannot be uncertain. S1 still proves attempts, bounded recovery, lease fencing,
interruption and no duplicate challenge, adoption or next-stage action. Provider-specific reconciliation
is P2 or the relevant integration phase, before real external actions are enabled; the ledger keeps the
`uncertain` status for it, and the redelivery exception applies to no other kind.

1. **Claim** is one short transaction: select one due row (`status` queued, or running with an expired
   lease) with `select_for_update(skip_locked=True, of=("self",))` and no outer joins, skip it if an
   `AutomationPause` exists for its subject and the kind is automated-class (staff-class kinds still run, rule 8), then set `running`, a new random lease token, the lease
   expiry and `attempts + 1`, and commit. Attempts are counted at claim so a killed worker still counts.
2. **Poison rule:** a claimable row whose attempts already reached the maximum becomes `failed` (or
   `uncertain` for kinds that are not redeliverable) without running the handler, and a history event is
   written.
3. **Handler** runs outside any transaction. Its network timeout (`EMAIL_TIMEOUT` for the sink path) is
   well below the lease length.
4. **Result** is a fenced write in a second transaction: update only where the row is still `running`
   with the same lease token. Zero rows updated means the lease was lost; the result is discarded and
   logged. The outbound message's unique (action, attempt) stops a late writer recording a duplicate.
5. **Clock:** due and lease times are set and compared with the database clock (`Now()`), never worker
   clocks. Settings: `USE_TZ = True`, `TIME_ZONE = "UTC"`, `ATOMIC_REQUESTS = False` (services own
   transactions).
6. **Redelivery:** each action kind declares whether a repeated effect is acceptable. Only
   "send verification" does in S1; every later provider kind defaults to `uncertain` and reconciliation.
7. **Connections:** the worker loop closes and reopens its database connection after an
   `OperationalError` and between idle polls.
8. **Held** actions are never claimed. A pause blocks **automated** action kinds for its subject; each kind
   declares its class (automated or staff). Staff kinds (a staff-authored message, from P2) are created
   only by an authorized staff action and may run while paused without resuming anything. S1 defines
   automated kinds only.

### S1.5 Django capabilities used (built-in first)

| Need | Built-in | Notes |
|---|---|---|
| Input validation | `forms.Form`, field validators, `EmailField` | server-side only |
| CSRF, request limits | `CsrfViewMiddleware`, `DATA_UPLOAD_MAX_MEMORY_SIZE`, `DATA_UPLOAD_MAX_NUMBER_FIELDS` | an oversized request is a 400 (`RequestDataTooBig`), not a form error |
| One commit | `transaction.atomic`, nested `atomic` savepoints | `ATOMIC_REQUESTS = False` |
| Race safety | `UniqueConstraint(condition=...)`, `select_for_update(of=...)`, `select_for_update(skip_locked=True)` | PostgreSQL; READ COMMITTED (Django's default) |
| Database clock | `django.db.models.functions.Now` | |
| Signed links | `django.core.signing.Signer` with a dedicated salt and a dedicated key setting with fallbacks (`Signer(key=..., fallback_keys=...)`) | signs the challenge's random public id; the database alone decides expiry and use (ADR-16) |
| Link base URL | a `PUBLIC_BASE_URL` setting | the worker has no request; never built from the `Host` header |
| Mail sink | `locmem` backend in in-process tests; `filebased` backend for local runs and the subprocess crash test | no SMTP host configured outside production |
| Worker | a management command (`BaseCommand`) running the claim loop | ADR-03 decided (D-16): custom ledger |
| Custom user | `AbstractUser`, `AUTH_USER_MODEL` | before the first migration |
| Staff view | `django.contrib.admin`, view permission, `Group`, `has_add/change/delete_permission` returning false | read-only even for superusers on dossier models |
| Startup guards | system checks registered without the `database` tag, **and** the same assertions in `AppConfig.ready()` | web servers do not run system checks; `ready()` runs in every process |
| Logging | `logging` filters on application **and** Django's own loggers (`django.request`, `django.server`, `django.security.*`) | tokens and email addresses redacted |

### S1.6 Dependencies, proposed versions and compatibility checks

**Not installed in the contract handoff.** S1-T1 has since performed the checks; results are in `012`; ADR-17 decided 2026-10-10 (D-18); pytest and pytest-django are still to be verified at the start of 1B.1.
Reported by the Django architect specialist from the Django 5.2 documentation on 2026-10-09 (INSPECTED by
the main session; S1-T1 re-checks): Django 5.2 supports Python 3.10 to 3.14 and PostgreSQL 14 and later, requires psycopg 3.1.8 or later (or
psycopg2), and is a long-term-support release with security updates for at least three years from
2 April 2025. The rest of this table was proposed before S1-T1; `012` section 5 supersedes it with sourced versions.

| Component | Proposed choice | Why | Compatibility check in S1-T1 |
|---|---|---|---|
| Python | **3.14.8** (decided, D-18) | longest support of the lines tested; all `012` proofs passed on it | the official image pinned by digest; no change to the system interpreter |
| Django | **5.2.18 LTS** (decided, D-18) | long-term support until April 2028 | installed from the hash-locked file in 1B.1 |
| PostgreSQL | **16.15** (decided, D-18) | inside Django 5.2's range; supported until November 2028 | the production host's server version stays an open P6 check |
| Driver | **psycopg 3.3.6** (decided, D-18; binary wheel in development and CI) | Django requires 3.1.8 or later | production wheel choice belongs to P6 |
| Test runner | pytest 9.1.1 with pytest-django 4.14.0 | integrates with the estate testing SOP tooling | **verified 2026-10-10** at the start of 1B.1: installed from hashes, loaded, collected and passed a PostgreSQL-backed check on Python 3.14.8 and PostgreSQL 16.15 (bead S1-T2 notes) |
| Network guard in tests | a small autouse fixture in `tests/conftest.py`, no dependency (chosen in 1B.1) | TEST-S1-14 | Python-level only: covers `socket.connect` and `connect_ex` inside test functions; not native libraries, child processes or collection-time code |
| Coverage | `coverage` (through pytest) | GATE-S1 evidence | version check; mutation tooling deferred until code exists |
| Settings source | environment variables read with the standard library; production values from SOPS at runtime (P6) | no extra dependency | none |
| Job mechanism | **custom ledger and management-command worker** (decided, D-16) | one mechanism; one source of truth | `012` comparison; unproven behaviours carried as stated in S1.4 (S1-T5, S1-T7, S1-T8; P2 for `uncertain` and reconciliation) |
| Environment and lock | `uv` with a hash-pinned lockfile | reproducible installs | lockfile resolves on the CI runner |
| CI database | official PostgreSQL 16.15 image **pinned by digest**, as a service container | parity with the decided version | job starts, migrations apply, `connection.vendor == "postgresql"`, server version 16.15 |

Nothing else: no Celery, Redis, Mailpit, HTTP client or model SDK in S1.

### S1.6a S1-T1 compatibility and comparison checks (what the owner receives before deciding)

S1-T1 returns evidence, not a choice made on the owner's behalf. **Result (2026-10-09): `012`. Decisions (2026-10-10): D-16 to D-19, recorded on the ADR rows in `003`.** Do not copy versions from any older
worktree; record exact versions from current official sources.

| Decision | S1-T1 must return |
|---|---|
| ADR-03 job mechanism | a bounded comparison of the custom ledger and at least one PostgreSQL-backed library (Procrastinate; Django's tasks interface with a database backend, if one supports Django 5.2), each against: enqueue in the same transaction as the domain write; lease or heartbeat recovery after a killed worker; an `uncertain` outcome and reconciliation; per-subject pause that still lets staff kinds run; staff visibility of every pending action; maintenance burden (code size, dependencies, release activity). Each claim cites documentation or a throwaway spike outside this repository. Procrastinate's transaction-aware deferral was not found on the pages first read; it was later found in its external-connection guide and **demonstrated** with the candidate versions (`012` proof 1). Temporal stays out of scope (D-03) |
| ADR-14 append-only | how a database trigger blocks ordinary application updates and deletes on versions and events, and the separate privileged, audited path that approved retention or deletion (POL-10) will use, so append-only never means "keep every personal record forever" |
| ADR-17 versions | exact current patch versions of Python, Django 5.2, PostgreSQL 16, psycopg 3, pytest and pytest-django, with the support statements that justify them |
| ADR-18 user model | confirmation that a minimal `AbstractUser` subclass is set before any migration, and that applicants are dossier records, not user accounts |

### S1.7 Acceptance plan

Every case runs on PostgreSQL in CI. Cases that involve locking or concurrency use real transactions
(`TransactionTestCase`, or pytest-django's `transaction=True`), each thread with its own connection,
closed at the end; Django's `TestCase` cannot test `select_for_update` behaviour. Results are reported
PASS, FAIL, SKIPPED, NOT RUN or BLOCKED with the run link. **None has run; all are planned.**

| ID | Case | Expected | Requirement |
|---|---|---|---|
| TEST-S1-01 | valid synthetic submission | one application, version 1, one "submission received" event, one active challenge, one queued "send verification" action; redirect to the received page | REQ-001, REQ-003 |
| TEST-S1-02 | invalid submissions: missing fields, malformed email, over-long fields, too many fields, oversized body, missing CSRF token | no rows in any slice table; form errors, or 400/403 for size and CSRF | REQ-027 |
| TEST-S1-03 | repeat submissions: same email key with case, whitespace and Unicode variants; a plus-addressed variant (distinct key); repeat after the challenge expired; repeat after a failed send; repeat after verification | per S1.2: correct attach-or-new; superseded and new challenge only where S1.2 says; "unverified repeat" version and staff item after verification; status, body and redirect target identical to TEST-S1-01 | REQ-002, REQ-006, REQ-027 |
| TEST-S1-04 | concurrent submissions with one email key, using a deterministic seam (both requests pass the "no open application" read, then a barrier, then insert), plus a repeated smoke loop; the seam proves one interleaving, the loop is supporting evidence only | one application, both submissions recorded with distinct version numbers, one send action, no server error | REQ-006 |
| TEST-S1-05 | database failure injected after the application insert and after the action insert; connection loss; failure injected during confirmation after the verification write | acceptance: zero rows in every slice table and the applicant never sees the received page; confirmation: verification, event and next action all absent, challenge still active | REQ-003, REQ-007 |
| TEST-S1-06 | worker processes the send action | one message in the local sink to the synthetic address with a link built from `PUBLIC_BASE_URL`; outbound message recorded; action done; event written | REQ-004 |
| TEST-S1-07 | worker interruption: (a) claimed, then stopped before sending; (b) the sink accepted the message, then stopped before recording (explicit fault seam); (c) a real worker subprocess, `filebased` sink, committed test data, killed with SIGKILL mid-action | lease expiry is simulated by writing a past lease time (no clock mocking); (a) exactly one message; (b) two identical links, one challenge, attempts recorded; (c) recovery without manual steps | REQ-004, REQ-005 |
| TEST-S1-08 | open the link (GET), then confirm (POST) | GET shows the current version's answers, changes nothing, sets the CSRF cookie and the no-referrer and no-store headers; POST sets verified once, adopts the named version, writes one event and one `held` action whose input is that version | REQ-007, REQ-033 |
| TEST-S1-09 | expired (by database clock), already-used, superseded and tampered tokens; a token signed with a retired key past its fallback; a POST naming a version of another application or a nonexistent version | refusal or "already confirmed"; no state change; no new action or history event (refusals are logged, redacted) | REQ-007 |
| TEST-S1-10 | two concurrent confirmations of one valid link; a confirmation racing a repeat submission | one verification event and one next-stage action; no deadlock (fixed lock order) | REQ-007, REQ-008 |
| TEST-S1-11 | access by anonymous, authenticated non-staff, staff without the group, and read-only staff attempting add, change or delete | redirect to login, then refusal; 403 on every write path; no data in refused responses | REQ-015 |
| TEST-S1-12 | read-only staff open the application created in TEST-S1-01; the group's permission set | list and detail show the same application with versions, events, challenge state (no token) and actions; the group holds exactly the view permissions on slice models; applications carrying a `needs_staff_attention` event are listed as such | REQ-014 |
| TEST-S1-13 | settings pointed at a non-PostgreSQL engine, checked through `manage.py check`, the worker command and application start-up | refused in each; the test session asserts PostgreSQL | REQ-021 |
| TEST-S1-14 | provider isolation: SMTP backend or any provider credential variable outside production; network access to a non-loopback address during tests | refused at start-up; the network guard blocks the connection; CI has no provider secrets | REQ-022 |
| TEST-S1-15 | history completeness across the whole flow | the expected event sequence exactly; admin denies change and delete of versions and events to everyone | REQ-001, REQ-002 |
| TEST-S1-16 | log capture across the whole flow, including refused confirmations and 4xx responses, on application and Django loggers | no raw token, email address or name in any log record | REQ-020 |
| TEST-S1-17 | lease fencing: a stale worker's late result after another worker reclaimed the action | late write updates zero rows and is discarded; one outcome recorded | REQ-004, REQ-005 |
| TEST-S1-18 | poison action: a handler that always crashes the worker, and one that always raises | attempts count at claim; the action reaches `failed` at the maximum and is not run again; event written | REQ-004 |
| TEST-S1-19 | the worker ignores `held` actions and actions of a paused subject; two workers racing for one action; re-running a completed action | never claimed; exactly one claim; no-op on `done` | REQ-004, REQ-013 |
| TEST-S1-20 | schema integrity: constraints exist by introspection; `makemigrations --check` reports no drift; no `workflow` row points at a missing subject | all present; no drift; no orphans | REQ-003, REQ-006 |
| TEST-S1-21 | append-only enforcement on the protected history tables (ADR-14 decided: privileges plus triggers, D-17) | the application role is refused `UPDATE`, `DELETE` and `TRUNCATE` by privilege, and the migration-owner role is refused them by the trigger, including raw SQL; the application role cannot disable the trigger | REQ-001, REQ-002 |
| TEST-S1-22 | intervening unverified submissions: version 1 submitted and its link sent; version 2 (different answers, same email key) submitted before confirmation; then confirm. Variant: version 3 arrives between GET and POST | contact control recorded once; only the version shown and named in the POST is adopted; the others stay `unverified` and are kept; the `held` action names the adopted version, never "the latest"; in the variant, version 3 stays `unverified` and raises a staff item | REQ-007, REQ-033 |

GATE-S1 (`002` section 6) passes only when every `TEST-S1-` case is PASS at the PR head, with QA review
and the epic's after-action report.

### S1.8 Legacy data

S1 creates only synthetic records in disposable databases. It neither reads nor changes any
first-generation record. A clean repository does not authorize discarding live records; their
compatibility plan is the separate epic PL and blocks cutover, not this slice.

### S1.9 What blocks S1 implementation

1. Owner approval of this contract and slice scope.
2. ~~Owner decisions on ADR-03, ADR-14, ADR-17 and ADR-18.~~ Decided 2026-10-10 (D-16 to D-19).
3. Confirmation or replacement of the POL-01 defaults (identity key, repeat after verification) before
   GATE-S1 (not before coding).
