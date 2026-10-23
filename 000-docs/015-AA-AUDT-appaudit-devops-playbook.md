# Catalyst v2: Operator-Grade System Analysis

*Generated: 2026-10-11*
*Version: `v0.1.0-19-gef17aa6` (main `ef17aa6`, after PR #18)*
*Scope: the `catalyst-onboarding-v2` repository as merged; no deployment exists to inspect.*

> **Errata (2026-10-11, handoff 2A).** This is a dated report and stays one; the corrections below
> do not re-run the analysis. Each sentence they name has also been corrected in place, marked
> "(corrected, see errata)".
>
> 1. **Phase count.** The plan does not have "eight phases, P1 to P8". `011` section 7 defines eight
>    engineering epics, `P0` to `P6` plus `PL`. P0 is the planning epic, P1 (the first slice) is
>    implemented, and six (P2 to P6, PL) remain unbuilt. The "7 of the 8 product phases" figure was
>    wrong.
> 2. **Secret scanning.** The claim "secret scanning in CI (gitleaks runs locally only)" was false.
>    `ci.yml` runs gitleaks 8.30.1 (checksum-verified) over the full git history (step "Secret scan
>    (gitleaks, full history)") in the job "Markdown lint and doc index check", which is the required
>    check. The bullet is removed from the "Not implemented" list in section 9.
> 3. **Policy names.** POL-16 is the numerical operating targets for the `002` measures, not "attempts";
>    POL-17 is the applicant-facing notices, not "wording" (`011` section 6). The policies the
>    correspondence loop relies on at P2 start are POL-06 (communications) and POL-19 (identity
>    disputes); POL-02 and the P2 slice of POL-13 follow before real email (`016` section 8).
> 4. **Worker throughput.** The "roughly hundreds per minute" estimate was not measured and is removed.
> 5. **Health score.** "68/100" is the author's unscored judgement, not the output of a scored rubric; read
>    it as a qualitative summary.
> 6. **PDF footer.** A PDF rendering of this report carried a "Confidential" footer. That came from the
>    rendering theme's default, not from a classification decision. The source file is public in this
>    repository. **Decided 2026-10-12 (D-32):** the report is public technical documentation while its
>    content stays public-safe, and future public PDF renderings use unclassified labelling.
> 7. **Since fixed.** The stale README and CHANGELOG findings (sections 1, 8.9 and the roadmap) were
>    true at `ef17aa6` and were fixed in handoff 2A: the README describes the accepted first slice and how
>    to run the tests, and the CHANGELOG lists the merged pull requests. They stay below as dated findings.

---

## 1. This System in 5 Minutes

Catalyst v2 is the second-generation onboarding platform for Solution Catalyst, Intent Solutions' program for bringing external practitioners on board. Its job, when finished, is to take a person from a first access request through email verification, a bounded AI-assisted review with a human decision, the NDA and User Agreement signed through Documenso, and finally a company mailbox and a welcome. Every step is to be recorded in one auditable dossier in PostgreSQL. The first-generation system (a Flask code base) still runs in production and remains the system of record for live applicants. This repository replaces it cleanly, design-first, without copying its code.

What exists today is the **first working slice**, and nothing beyond it:

1. A public access-request form (`/request-access/`) writes the application, its first submission version, a history event, a verification challenge and a queued "send verification" action, all in one database transaction.
2. A PostgreSQL-backed worker (`manage.py run_worker`) claims that action, sends the verification email to a **local mail sink** (never real email), and records the outcome. It survives being killed mid-send.
3. The applicant opens a signed, expiring, single-use link (`/confirm/<token>/`). Confirming it records verified contact and adopts **only the submission the applicant was shown**. It also creates the next step ("start evidence collection") as a `held` action, which nothing runs yet.
4. Staff read the whole record in a read-only Django Admin dossier at `/staff/`. Nobody can change anything there, superusers included.

The slice passed its acceptance gate (GATE-S1) on 2026-10-11. All 22 acceptance cases pass at one commit, an independent QA review confirmed the evidence, and the owner signed it off (decision D-26 in `011`). The current `main` passes 333 tests in CI (run 38118250313, 91 s). The suite now refuses to pass a full run unless every acceptance case passes. There is **no deployment of any kind**: no staging, no production, no backups, no monitoring. That is by design, because deployment is phase P6.

The engineering quality of what was built is high for its size, about 2,150 lines of application Python (excluding migrations) and about 4,650 lines of tests:

- The database enforces its own rules: append-only history by privilege and trigger, three separated roles, and a partial unique index for duplicates.
- Concurrency is proven with real transactions rather than mocks.
- Every task had an independent specialist review.

The **biggest risks are not in the code that exists**:

- **Distance to production.** Real email, the AI assessment, signing, provisioning, deployment, backup and staff MFA are all unbuilt. Six of the eight planned epics (P2 to P6, PL) remain (corrected, see errata).
- **The release path.** The release workflow still pushes its version-bump commit straight to `main`, bypassing review (bead `catalyst-v2-oyu`, P1).
- **Stale front-door documentation.** The README still describes a skeleton with "no applicant feature" (since fixed, see errata).
- **Single-maintainer dependency.** Every decision, review approval and merge runs through one person and AI agents.

---

## 2. Executive Summary

### What It Does

Today the system does one complete, narrow thing. It accepts a synthetic access request, verifies the email address through a worker-sent link, and shows staff the result, with every state change recorded once and in order. It handles duplicates and concurrent submissions without creating a second application, recovers from a worker killed mid-send without duplicating anything but the identical invitation, and refuses stale, tampered, expired, superseded or reused links. These behaviours are specified in `000-docs/005-AT-DSGN-technical-spec.md` (section S1) and proven by `tests/` (section 11 below).

Implementation status is uneven by design. The planning record is extensive: blueprint `011`, PRD `002`, architecture `003`, user journey `004`, specification `005`, and an agent charter and registry (`007`, `008`). It describes eight engineering epics, P0 to P6 plus PL (corrected, see errata). P0 is the planning epic; only P1 (the first slice) is implemented. The correspondence loop (P2), evidence and assessment with MiniMax through PydanticAI (P3), agreements through Documenso (P4), provisioning and activation (P5), deployment and operations (P6), and legacy data compatibility (PL) are planned and tracked as Beads epics, with no code.

The technical foundation:

- Django 5.2.18 on Python 3.14.8;
- PostgreSQL 16.15 through psycopg 3.3.6;
- pytest 9.1.1 with pytest-django 4.14.0.

All dependencies are hash-locked (`requirements/*.txt`), and both container images are pinned by digest in `compose.yaml` and `.github/workflows/ci.yml`. There is no JavaScript build, no task queue library, no cache, and no external service in use.

The key risks are:

- **No path to production yet** (P6 unbuilt, with deployment gates recorded in `006`).
- **A release workflow that can still write directly to `main`.**
- **18 open product policies**, mostly owner decisions due at later gates.
- **Documentation drift** in README and CHANGELOG (since fixed, see errata).
- **A bus factor of one.**

None of these is a defect in the shipped slice. They are the work between here and a pilot.

### Operational Status

| Environment | Status | Uptime Target | Release Cadence | Last Deploy |
|---|---|---|---|---|
| Production | **Does not exist.** The first-generation Flask service is the live system of record | none (not defined) | none | never |
| Staging | **Does not exist** (P6, bead `catalyst-v2-9kg`) | none | none | never |
| Local Dev / CI | Runs: `scripts/test.sh` (per-run Compose project) and the CI runtime job | n/a | every PR; `main` on push | n/a |

There is one tag, `v0.1.0`, created automatically by a templated release on 2026-10-09. It is not a planned release (`CHANGELOG.md`). No release has been cut since.

### Technology Stack

| Category | Technology | Version | Purpose |
|---|---|---|---|
| Language | Python | 3.14.8 (image digest-pinned) | application and tests |
| Web framework | Django | 5.2.18 | forms, views, ORM, migrations, admin, sessions, CSRF, signing |
| Database | PostgreSQL | 16.15 (image digest-pinned) | the only datastore: dossier, ledger, sessions |
| Driver | psycopg (binary) | 3.3.6 | PostgreSQL access |
| Job execution | custom ledger in `workflow/ledger.py` | n/a | durable pending actions (ADR-03, D-16) |
| Tests | pytest, pytest-django | 9.1.1, 4.14.0 | runtime suite, concurrency, subprocess tests |
| Local runtime | Docker Compose | host's | `compose.yaml`: `db` and `test` services only |
| CI | GitHub Actions | n/a | `ci.yml` (two required checks), `release.yml` (manual) |
| Task tracking | Beads (`bd`) on Dolt | 1.1.x | `.beads/issues.jsonl` export in git |
| Planned, not used | MXroute, MiniMax via PydanticAI, Documenso, Twenty | n/a | phases P2 to P5; Twenty deferred beyond MVP |

---

## 3. Architecture

### Stack (Detailed)

| Layer | Technology | Version | Purpose | Why This |
|---|---|---|---|---|
| Presentation | Django templates, server-rendered | 5.2.18 | form, received page, confirm pages | No SPA: the applicant flow is a handful of pages; server rendering keeps CSRF, escaping and no-JS behaviour simple (`011`) |
| Staff UI | Django Admin, read-only | 5.2.18 | applicant dossier, queues | Native admin first was the owner's direction (D-23); a second frontend was explicitly ruled out |
| Domain | `applications` app | n/a | application, versions, challenges, adoptions, events; intake, confirmation, dossier logic | One cohesive app for the applicant dossier (ADR-01) |
| Workflow | `workflow` app | n/a | `PendingAction` ledger, `AutomationPause`, worker command | Subject-generic, with **no foreign key to any domain model** (ADR-01 layer rule), so later phases add kinds without schema coupling |
| Correspondence | `correspondence` app | n/a | `OutboundMessage`, the verification send handler | Separates message records and sending from the dossier |
| Accounts | `accounts` app | n/a | custom `User` (staff only), owner command for staff | Custom user before the first migration (ADR-18, D-19); applicants are never users |
| Configuration | `config` package | n/a | settings, start-up guards, role enforcement, log redaction, admin contract | Guards make wrong environments refuse to start, not misbehave |
| Data | PostgreSQL 16.15 | 16.15 | everything | ADR-02: PostgreSQL in every environment, no SQLite fallback (enforced by `config/guards.py`) |
| CI | GitHub Actions | n/a | runtime job (containers as in compose) + docs job aggregating it | One stable required check per lane (`009` section 5.5) |

### System Diagram

```text
                       (synthetic only; nothing is deployed)

  Applicant browser                                   Staff browser
        |                                                   |
        |  GET/POST /request-access/                        |  /staff/  (login, session cookie)
        |  GET/POST /confirm/<signed token>/                |
        v                                                   v
  +---------------------------------------------------------------+
  |  Django web process (config/wsgi.py declares "web")           |
  |  middleware: PrivateConfirmationResponses (no-store,          |
  |  no-referrer on /confirm/) -> Security -> Session -> Common   |
  |  -> CSRF -> Auth -> Messages -> XFrame                        |
  |  applications.views  (intake, confirm)   admin (read-only)    |
  |  services.accept_submission   confirmation.confirm            |
  +-------------------------------+-------------------------------+
                                  | connects ONLY as catalyst_app
                                  | (connection_created role check,
                                  |  config/runtime.py)
                                  v
  +---------------------------------------------------------------+
  |  PostgreSQL 16.15                                             |
  |  applications_* (dossier; versions/events append-only by      |
  |  privilege + trigger; adoptions immutable for every role)     |
  |  workflow_pendingaction, workflow_automationpause             |
  |  correspondence_outboundmessage                               |
  |  django_session, django_admin_log (SELECT only), auth tables  |
  |  roles: catalyst_owner (migrations), catalyst_app (runtime),  |
  |         catalyst_retention (audited deletes; none enabled)    |
  +-------------------------------^-------------------------------+
                                  | catalyst_app only
  +-------------------------------+-------------------------------+
  |  Worker: manage.py run_worker (declares "worker")             |
  |  claim (SKIP LOCKED, lease) -> check (locks app, challenge)   |
  |  -> send via Django mail backend -> fenced result write       |
  +-------------------------------+-------------------------------+
                                  |
                                  v
                    Local mail sink only: locmem (tests),
                    console or filebased (dev). SMTP is refused
                    at start-up by config/guards.py.
```

Failure domains: there is one datastore, so PostgreSQL unavailability stops everything. Web and worker are independent processes. A dead worker delays sends but loses nothing, because leases expire and another worker reclaims the action.

### The Critical Path

The most important flow is a first access request through to confirmed contact.

1. **Submit (web, one transaction).** `applications/views.py: request_access` validates `AccessRequestForm` (name, email and reason, with column limits; a 64 KiB body and 10-field limit give a 400; a missing CSRF token gives a 403). It then calls `services.accept_submission`.
   - The service computes the identity key (`applications/identity.py`: trim, NFKC, casefold, IDNA domain; plus-addressing kept).
   - It locks or creates the open application. A concurrent first insert loses on the partial unique index `application_one_open_per_email_key`; only that named constraint is caught, inside a savepoint, and the row is re-read under lock.
   - It allocates the version number from the locked counter and writes the version and the `submission_received` event.
   - It reuses or replaces the challenge and inserts the `send_verification` action.
   - **Failure points:** any database error is a 503 "please try again" with only the exception class logged. A connection lost *at* commit leaves the outcome unknown; a resubmission is safe under the duplicate rules (tested by simulation).
   - Every outcome gives the same redirect and page, so the form never reveals whether an email is known.
2. **Send (worker).** `workflow/ledger.py: claim_next` selects one due row with `SKIP LOCKED`, sets a lease token and expiry by the database clock, and counts the attempt.
   - `correspondence/verification.py: SendVerification.check` re-checks eligibility in one short transaction (application lock, then challenge lock), then commits, so no lock is held while sending.
   - The message goes through Django's mail backend, and the result is written by `ledger.finish`, fenced on the lease token.
   - **Failure points:**
     - a send error retries with backoff, up to 3 attempts;
     - a worker that dies on every attempt is stopped by the poison rule;
     - a stale worker's late result is discarded by the fence;
     - if the sink accepted but recording failed, the action is left for lease recovery, which may redeliver the identical link (D-20).
3. **Confirm (web).** `applications/views.py: confirm` with `applications/confirmation.py`:
   - The token is verified with the dedicated signer (`applications/links.py`, key `CATALYST_VERIFICATION_KEY`).
   - GET shows the latest version's answers and writes nothing.
   - POST locks the application, then the challenge, and refuses unless the challenge is unused, not superseded and unexpired by the database clock, the application is open, and the named version belongs to it.
   - It then records contact control, adopts only that version, writes `contact_verified` (plus a staff item if a newer version exists), and creates `start_evidence_collection` as `held`.
   - **Failure points:**
     - a refusal returns 404, 410 or 400 with a reason code logged;
     - a database error returns 503 with nothing recorded;
     - a double POST answers "already confirmed".
4. **Read (staff).** `applications/admin.py` with `applications/staff.py` render the dossier: status, contact state, the adopted version, open attention items, the next responsible party, and the related records. Writes are refused at three layers: group permissions, admin overrides and database grants.

### Dependency Graph

```text
config (settings, guards, runtime role check, redaction, staff_admin)
  ^ imported by every app at start-up (CatalystConfig.ready)
accounts (User)            <- admin, sessions (auth)
workflow (ledger, models)  <- no domain imports (ADR-01)
applications               -> workflow.models (creates actions), config
correspondence             -> applications (FK), workflow (FK, ledger)
```

Build and start order:

1. PostgreSQL is up, with the three roles provisioned (`scripts/provision_db_roles.py`, development and test only).
2. `migrate` runs as `catalyst_owner`.
3. Web and worker start as `catalyst_app`.

What happens when each dependency is unavailable:

- **PostgreSQL down:** the web returns 503 on writes, and the worker loop closes its connections and retries each poll.
- **Mail sink failing:** the send retries with backoff, then ends `failed`, and the dossier shows staff attention.
- **No worker running:** actions queue, the dossier shows "System: waiting to be sent", and nothing is lost.

---

## 4. Design Decisions & Tradeoffs

### Decision Log

#### Custom PostgreSQL ledger over a queue library (ADR-03, D-16)

- **Chosen**: a `PendingAction` table with `SKIP LOCKED` claims, lease tokens, attempt counting at claim, a poison rule and fenced result writes (`workflow/ledger.py`).
- **Over**: Procrastinate (evaluated in `012`: transactional enqueue was demonstrated), Celery or RQ with a broker, and Temporal (ruled out in `011`).
- **Because**: the fenced result, the outbound record and the history event must commit in one transaction under one lease. With a library, job state would live in two places (`012` section 4).
- **Cost**: features a library gives for free must be built and proven: heartbeat, scheduling UI, metrics, retries with jitter. There is **no lease heartbeat**: a handler slower than its lease (300 s default) can be reclaimed while still running, and only the fence protects the result.
- **Revisit when**: action kinds multiply in P2 to P5 and the ledger grows scheduling, rate limits or fan-out; or throughput needs exceed one polling loop (each worker claims one action per transaction).

#### Append-only history by privilege plus trigger, with three roles (ADR-14, D-17, D-22)

- **Chosen**: `catalyst_app` has no UPDATE, DELETE or TRUNCATE on versions and events. Triggers refuse even the migration owner. Adoptions are immutable for every role. An audited retention path exists but no deletion is enabled (POL-10 open).
- **Over**: application-level discipline, or an event-sourcing framework.
- **Because**: the dossier is an audit record. Protection must hold against code bugs and against routine owner sessions.
- **Cost**: every write must be column-granted (no `Model.save()` full-row writes), migrations need trigger-aware review, and the test suite needs a test-only privileged reset (D-21).
- **Revisit when**: POL-10 decides retention or redaction. A redaction need would require a second audited operation.

#### Signed challenge id in the URL path (ADR-16, D-24)

- **Chosen**: `/confirm/<Signer(key, salt).sign(public_id)>/`, with validity decided by the database every time.
- **Over**: a stored random token (hash-at-rest), or the token in a query string or fragment.
- **Because**: deterministic signing makes a permitted redelivery (D-20) carry the identical link, nothing secret is stored, and key rotation has fallback keys.
- **Cost**: the token sits in the path, so **proxy and application-server access logs would record it**. That is a recorded deployment gate (`006` Blockers). Application logs are redacted (`config/redaction.py`).
- **Revisit when**: the deployment design (P6). Either strip the path from access logs, or move the token out of the path, which is an owner decision.

#### Native Django Admin as the staff UI, read-only three times over (D-23)

- **Chosen**: the admin registers four models, all view-only for everyone. The group holds exactly 8 view permissions, created by migration as the owner. The database grants deny writes. Changelist lookups are limited to declared filters.
- **Over**: custom staff views or a separate frontend.
- **Because**: it met every staff requirement with modest customization, and the owner directed native Admin first.
- **Cost**: the admin's own features must be actively closed off: password change is refused, Group and User admin are unregistered, arbitrary lookups are blocked. The dossier logic lives in `applications/staff.py` as display helpers.
- **Revisit when**: staff need actions (P2 onward: pause and resume, resolving attention items, overrides). Each will be a named, permissioned staff action, possibly in focused views.

#### Gate the release on CI, not on re-running tests (bead `catalyst-v2-2xy`, PR #18)

- **Chosen**: `release.yml` runs `scripts/require_green_ci.py` on the release commit and refuses unless both required checks succeeded.
- **Over**: running the suite inside the release job.
- **Because**: the suite needs the pinned containers, the roles and the hash-locked dependencies, and a second copy would drift.
- **Cost**: a release must be dispatched on a commit whose CI already ran green.
- **Revisit when**: the release path is redesigned for `catalyst-v2-oyu`, which removes the direct push to `main`.

#### PostgreSQL everywhere, with refusal guards (ADR-02, ADR-17, D-18)

- **Chosen**:
  - no SQLite anywhere;
  - `config/guards.py` refuses to start on a non-PostgreSQL engine, an environment other than development or test, an SMTP backend, or any provider credential variable;
  - digest-pinned images and hash-locked dependencies.
- **Over**: SQLite for fast unit tests.
- **Because**: locking, `SKIP LOCKED`, partial unique indexes and triggers are the behaviour under test. SQLite cannot prove any of them.
- **Cost**: the suite takes about 1.5 minutes in CI and 3 to 4 minutes locally, Docker is required, and there are no "pure unit" fast paths.
- **Revisit when**: test time grows past what reviewers will wait for. Then split a fast lane, rather than give up PostgreSQL.

### What Was Deliberately Not Built

- **Real email, MiniMax, Documenso, Twenty and provisioning.** All provider access is refused at start-up (`config/guards.py`) and absent from CI (asserted by `tests/test_acceptance.py::test_s1_14_ci_receives_no_provider_secret`).
- **Any deployment, staging, backup, monitoring or alerting** (P6).
- **Staff write actions**: pause and resume, resolving attention items, resend (P2 onward).
- **Reminders, inbound mail, and reconciliation of `uncertain` sends** (P2).
- **A lease heartbeat for the worker.** Fencing is relied on instead.
- **Retention or deletion of real records** (POL-10 open).
- **Legacy (first-generation) data import** (epic `catalyst-v2-dy7`).
- **Learn routing**: `learn.intentsolutions.io` keeps the existing LMS (proposed and verified read-only on 2026-10-09).

### Assumptions the Architecture Rests On

- **One PostgreSQL instance carries everything.** The schema is small (9 slice tables plus Django's); slice volumes are tiny.
- **One polling worker is enough.** The poll interval defaults to 5 s, and each claim is one short transaction. Throughput has not been measured (corrected, see errata); real SMTP latency (`EMAIL_TIMEOUT` 10 s, at most half the 300 s lease) bounds a single send.
- **Email ownership is the identity proof** for the slice (POL-01 confirmed for the slice, D-25). Plus-addressed variants are deliberately different identities.
- **The database clock is the only clock** for expiry, due times and leases. Application clocks are never trusted (tested).
- **Applicants never get accounts.** Only staff are Django users (ADR-18).

---

## 5. Directory Structure

### Layout

```text
catalyst-onboarding-v2/
├── 000-docs/              # the planning record and evidence (filing standard v4.x); 000-INDEX.md lists all
│   └── 000-aars/          # after-action reports (014: first slice)
├── accounts/              # custom staff User; owner command add_readonly_staff; grants + read-only group migration
├── applications/          # applicant dossier: models, intake service, confirmation, links, views, admin dossier
├── workflow/              # pending-action ledger, pauses, run_worker command (no domain imports)
├── correspondence/        # OutboundMessage; the send_verification handler
├── config/                # settings, start-up guards, role enforcement, log redaction, admin contract
├── scripts/               # test.sh, check-docs.sh, provision_db_roles.py, require_green_ci.py
├── tests/                 # runtime suite (333 tests), acceptance map, conftest harness
├── requirements/          # base/dev .in and hash-locked .txt
├── compose.yaml           # db + test services, digest-pinned
├── .github/workflows/     # ci.yml (required checks), release.yml (manual, CI-gated)
├── .beads/                # Beads export (issues.jsonl); Dolt store is local
└── .claude/agents/        # eleven read-only specialist subagents (007, 008)
```

### Load-Bearing Files

| Path | Role | Why it is load-bearing |
|---|---|---|
| `config/settings.py` | all settings; required variables | A missing required variable refuses start-up. Middleware order matters: `PrivateConfirmationResponses` must stay outermost |
| `config/guards.py` | start-up refusals | The only thing stopping SQLite, SMTP, provider credentials or a production environment |
| `config/runtime.py` | `connection_created` role check | Web and worker refuse any login but `catalyst_app`. A new entry point (an ASGI module, say) must declare its kind or it is unenforced |
| `applications/services.py` | intake transaction | Lock order, duplicate handling, challenge reuse rules |
| `applications/confirmation.py` | confirmation transaction | Single use, adoption of only the named version, next action |
| `workflow/ledger.py` | claim, poison rule, fenced result | Every action's correctness under crashes and races |
| `correspondence/verification.py` | send handler | The pre-send boundary and the "left for recovery" path |
| `applications/migrations/0002_history_protection.py`, `0003_protect_version_adoption.py` | grants and triggers | The append-only guarantee lives here |
| `accounts/migrations/0003_staff_view.py` | session and admin grants, read-only group | Staff access precision (D-23) |
| `tests/conftest.py` | role switch, privileged reset, skip gate, acceptance gate | The test suite's honesty depends on it |

---

## 6. Getting Started

### Prerequisites

| Tool | Version | Install | Verify |
|---|---|---|---|
| Docker Engine with Compose v2 | recent | Docker docs | `docker compose version` |
| git | any | OS package | `git --version` |
| bash | 4+ | OS | `bash --version` |
| GitHub CLI (optional) | any | `gh` docs | `gh auth status` |
| Beads `bd` (optional, for tracking) | 1.1.x | estate tooling | `bd version` |
| Node `npx` (for the docs check) | 22.x | nodejs.org | `npx --version` |

No local Python install is needed for tests. Everything runs in the pinned containers.

### Zero to Running

1. `git clone https://github.com/intent-solutions-io/catalyst-onboarding-v2.git && cd catalyst-onboarding-v2`
2. `scripts/test.sh` builds nothing. It pulls the two digest-pinned images, starts a per-run Compose project, provisions the three roles, migrates as the owner, and runs the suite as `catalyst_app`. Expect `333 passed`, followed by the acceptance report ending `PASS 25, FAIL 0, INCOMPLETE 0, NOT RUN 0 (full run: GATE-S1 requires every case PASS)`. The project, including its volumes, is removed afterwards.
3. Subset runs: `PYTEST_ARGS="tests/test_intake.py -q" scripts/test.sh`. Subsets are reported as "selected subset: not gated".
4. `scripts/check-docs.sh` runs markdownlint (same version as CI) and the doc index check.

**There is no "run the app locally" recipe.** `compose.yaml` defines only `db` and `test`. Running `manage.py runserver` and `manage.py run_worker` against the Compose database needs the variables from `compose.yaml` (`CATALYST_ENV=development`, the DB settings, `CATALYST_PUBLIC_BASE_URL`, `CATALYST_VERIFICATION_KEY` and so on) plus role provisioning. That is undocumented, and it is a gap (section 11).

### Common Setup Problems

| Symptom | Cause | Fix |
|---|---|---|
| `Catalyst refuses to start: ...` | a guard: wrong engine, environment, mail backend, or a provider variable in the environment | Read the named problem. Unset the variable (for example `OPENAI_API_KEY`) or set `CATALYST_ENV` to development or test |
| `ImproperlyConfigured: ... required` | a required setting is missing: `CATALYST_PUBLIC_BASE_URL`, `CATALYST_VERIFICATION_KEY`, `CATALYST_CHALLENGE_LIFETIME_SECONDS`, the DB settings | Copy the synthetic values from `compose.yaml` |
| `test.sh: compose project ... already has containers` | a fixed `CATALYST_TEST_PROJECT` name was reused | Leave it unset, or clean that project by hand |
| Web refuses its DB connection | the web or worker connected as the owner, retention or a superuser | Use `catalyst_app` credentials. That is intended (ADR-14) |
| Shell `cp`, `rm` and `mv` prompt and hang scripts | dev-box aliases (`cp -i`) | Use `\cp -f` and so on in scripts. It cost a mutation run once (AAR `014` section 5) |

---

## 7. Operations

### Command Map

| Task | Command | Notes |
|---|---|---|
| Run locally | not packaged | see section 6; a gap |
| Run tests | `scripts/test.sh` | full run is gated on every acceptance case |
| Run a subset | `PYTEST_ARGS="<path or -k>" scripts/test.sh` | not gated |
| Lint and format | `scripts/check-docs.sh` | Markdown only. **No Python linter or formatter is configured** (gap) |
| Build | none | no artifact; Django runs from source |
| Worker | `python manage.py run_worker [--exit-when-idle]` | declares itself a worker; SIGTERM stops after the current action |
| Create staff | `python manage.py add_readonly_staff <user> --approval-ref <decision>` as the owner (every grant is recorded, `9kg.30`; other roles: `grant_staff_role`) | refused to the application role |
| Rotate a staff password | `python manage.py changepassword <user>` as the owner | the admin password form is refused (403) |
| Deploy staging | none | P6 |
| Deploy production | none | P6 |
| View logs | stdout of web and worker | no aggregation; redaction in `config/redaction.py` |
| Release | Actions → Release → `dry_run` first | gated on green CI; still pushes the bump to `main` (`oyu`) |
| Merge | `safe-merge intent-solutions-io/catalyst-onboarding-v2 <PR> --squash` | estate merge guard; config in `~/.config/intentsolutions/merge-guard/repos.yaml` |
| Rollback | revert the PR; reverse migrations as the owner | reverse-and-reapply is tested for `applications`, `workflow` and `accounts.0003` only |

### Deployment

- **Pre-flight, execution, verification and rollback:** not applicable. There is no deployment target. P6 (`catalyst-v2-9kg`) must define them. The recorded gates are:
  - confirmation paths out of access logs;
  - HTTPS-only links, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, SSL redirect and HSTS;
  - session lifetime;
  - the staff host or network restriction and MFA (POL-13);
  - backup with a demonstrated restore;
  - monitoring of the inbox and of pending actions;
  - the reversible Learn routing cutover.
- **Production is refused today.** `CATALYST_ENV=production` fails at start-up (`config/guards.py`, `ALLOWED_ENVIRONMENTS = {"development", "test"}`).

### Monitoring & Alerting

- **Dashboards:** not configured.
- **SLIs and SLOs:** not defined.
- **On-call:** not established.
- **Recommended first SLIs for P6:**
  - age of the oldest due `queued` action;
  - `running` actions with an expired lease;
  - actions ending `failed` or `uncertain` per day;
  - the 503 rate on intake and confirmation;
  - applications with open staff attention.

  The data for all of these already exists in `workflow_pendingaction` and `applications_applicationevent`.

### Incident Response

| Severity | Definition | Response Time | Playbook |
|---|---|---|---|
| P0 | System outage | Immediate | none (no production) |
| P1 | Critical degradation | 15 min | none |
| P2 | Partial impact | 1 hour | none |

Playbooks are a P6 deliverable (`catalyst-release-operations` agent scope). The estate's alert path (the VPS alert floor into Buzz) is the expected integration, but nothing here is wired to it.

---

## 8. Things That Will Bite You

### 8.1 The release workflow pushes straight to `main`

- **Symptom**: a release creates a "chore(release)" commit on `main` with no PR, and the tag points at it.
- **Cause**: `release.yml` commits the version bump and runs `git push origin HEAD <tag>`. The CI gate checks the commit the release was dispatched on, not the bump commit.
- **Fix**: bead `catalyst-v2-oyu` (P1). Either make the bump a PR that goes through `safe-merge`, or tag the already-green merged commit and record the version without a new commit.
- **Prevention**: do not run a non-dry-run release until `oyu` lands.

### 8.2 The merge guard config is shared and can be clobbered

- **Symptom**: `safe-merge` refuses with "repository ... is not configured in repos.yaml".
- **Cause**: `~/.config/intentsolutions/merge-guard/repos.yaml` is edited by several sessions. On 2026-10-11 a rewrite for other repositories dropped this repo's entry.
- **Fix**: restore the entry with the two required checks (done 2026-10-11, with a backup kept). Never add `--admin` or bypass the guard.
- **Prevention**: the guard config should live in version control with a test that lists every registered repo (estate follow-up; see section 11).

### 8.3 A deliberately failed check run blocks merging

- **Symptom**: `safe-merge` refuses because "Release (failure)" is on the head.
- **Cause**: the guard counts every check run on the head commit unless it is advisory. A dry-run release that was refused leaves a failed "Release" run.
- **Fix**: re-run that dry run after CI is green (attempt 2 supersedes), or exercise release refusals on a throwaway commit.
- **Prevention**: dispatch dry runs only on commits whose CI has finished.

### 8.4 The token is in the confirmation URL path

- **Symptom**: a reverse proxy or gunicorn access log contains `/confirm/<uuid>:<signature>/`.
- **Cause**: the ADR-16 link format. Application logs are redacted, but server logs are outside the application.
- **Fix**: at deployment, strip or hash that path in access logs, or the owner moves the token out of the path.
- **Prevention**: it is a recorded gate in `006`. Do not deploy without it.

### 8.5 Full-row saves fail against the column grants

- **Symptom**: `permission denied for table ...` from an ordinary `obj.save()`.
- **Cause**: the application role has column-level UPDATE only (`config/db_roles.py`, the grant migrations).
- **Fix**: use `QuerySet.update()` or `save(update_fields=[...])` limited to granted columns.
- **Prevention**: this also explains the refused admin password form, whose `PasswordChangeForm.save()` saves the full row.

### 8.6 A new entry point is not role-enforced

- **Symptom**: a new process (ASGI, a cron script) connects as the owner without refusal.
- **Cause**: `config/runtime.py` enforces only processes that declare `web` or `worker`. Undeclared processes count as `management`.
- **Fix**: call `runtime.declare_process(...)` before Django loads, as `config/wsgi.py` and `run_worker` do.
- **Prevention**: add a test per entry point, using the fresh-process pattern in `tests/test_db_roles.py`.

### 8.7 Renaming a test breaks the full run

- **Symptom**: CI fails with an acceptance case NOT RUN or INCOMPLETE, although every test passed.
- **Cause**: `tests/acceptance.py` maps cases to test functions by name, and a full run is gated on all PASS.
- **Fix**: update the map in the same change.
- **Prevention**: intended. `tests/test_acceptance.py::test_every_mapped_test_exists` catches stale names.

### 8.8 No lease heartbeat

- **Symptom**: a slow send is reclaimed while still running, and the identical invitation goes out twice.
- **Cause**: the worker has no heartbeat. The lease is 300 s by default, and the mail timeout is capped at half of it.
- **Fix**: the fence discards the late result. A second send is the D-20 redelivery that is allowed for verification only.
- **Prevention**: before any non-redeliverable kind (Documenso, provisioning), add a heartbeat or a provider idempotency key. Those kinds default to `uncertain` on exhaustion.

### 8.9 README and CHANGELOG are stale

- **Symptom**: a reader is told there is "no applicant feature", or that the repo is "planning phase, no code".
- **Cause**: `README.md` and `CHANGELOG.md` have not been updated since 1B.1.
- **Fix**: rewrite the README status section and add the merged work under `[Unreleased]`.
- **Prevention**: add both to the per-task documentation checklist in `009`.

---

## 9. Security & Access

### Access Control

| Role | Purpose | Permissions | MFA |
|---|---|---|---|
| `catalyst_owner` (DB) | migrations, setup | owns tables; refused by the history triggers | n/a |
| `catalyst_app` (DB) | web and worker runtime | per-table and per-column grants; no UPDATE, DELETE or TRUNCATE on history; SELECT-only on users, groups, permissions and the admin log | n/a |
| `catalyst_retention` (DB) | audited deletion | DELETE on versions and events only with a stated reason and an audit row; unused (POL-10) | n/a |
| Read-only staff (Django group) | dossier viewing | exactly 8 view permissions | **none (POL-13 open)** |
| Django superuser | not intended | the admin still refuses every write | none |
| Applicant | none | no account; a signed link only | n/a |

### Secrets

- **Where:**
  - Runtime: environment variables, `CATALYST_SECRET_KEY` and `CATALYST_VERIFICATION_KEY` (which must differ from it), plus the DB role passwords.
  - Development and test: synthetic values in `compose.yaml` and `ci.yml`, asserted synthetic by test.
  - The repository holds no real secret; gitleaks is clean.
- **Rotation:** the verification key supports `CATALYST_VERIFICATION_FALLBACK_KEYS`, and rotation is tested. No other rotation policy exists, and none is needed until deployment.
- **Emergency access:** not established.

### Honest Security Assessment

**Implemented and tested:**

- three separated database roles, enforced at connection time for web and worker;
- append-only history by privilege and trigger, including against the owner;
- CSRF everywhere, and request size and field limits;
- uniform intake responses, so the form cannot be used to probe for known emails;
- signed, expiring, single-use links checked by the database clock;
- token redaction in Django's request, CSRF and server loggers;
- `no-store` and `no-referrer` on every confirmation-path response;
- a read-only staff admin whose own write features are closed;
- start-up refusal of providers, SMTP, SQLite and production;
- the test network guard;
- hash-locked dependencies and digest-pinned images;
- the release gate on green CI.

**Not implemented (aspirational or later):**

- staff MFA, a staff host or network restriction, a session lifetime policy, secure cookie flags, HTTPS;
- access-log handling of the token;
- rate limiting or abuse controls on the public form and the confirmation endpoint (none exist);
- a security headers review beyond the referrer policy;
- dependency vulnerability scanning in CI (no Dependabot alerts check, no `pip-audit`);
- CodeQL or SAST;
- an unpinned action in `release.yml` (`actions/checkout@v7`), whereas `ci.yml` pins by SHA.

**Stated limitations:**

- a superuser bypasses the triggers, and the owner can disable them;
- the test process itself holds administrator database credentials (`catalyst-v2-6hl.10`);
- the network guard is Python-level only: libpq, child processes, UDP and DNS are not covered.

---

## 10. Cost & Performance

### Monthly Costs

| Resource | Cost | Notes |
|---|---|---|
| GitHub Actions | $0 incremental | public repository; runtime job about 1.5 to 2 min per run |
| Hosting | $0 | nothing deployed |
| Providers | $0 | none called |
| Developer time and AI usage | not measured here | the dominant cost |

### Performance

- **Latency (P50, P95, P99):** not measured. There is no load test.
- **Throughput:** not measured. Each worker claim is one short transaction with the send outside any transaction.
- **Error budget:** not defined.
- **Test time:**
  - CI runtime suite: 91 s for 333 tests at `ef17aa6`;
  - local full run: 3 to 4.5 minutes (Docker on the dev box).
  - The slowest tests are subprocess and SIGKILL recovery (about 8 s) and the child-pytest gate probes.

### Scaling Limits

- **The worker is a single polling loop per process.** Several workers are safe (SKIP LOCKED, tested with two loops), but there is no autoscaling or partitioning.
- **Every confirmation and intake for one email key serializes on that application's row lock.** That is correct, and harmless at human request rates.
- **The partial unique index on `email_key`** caps open applications at one per key by design.
- **No pagination or index has been tuned for large dossier lists.** The admin changelist annotates an `Exists` attention predicate per row. Fine for hundreds, untested for tens of thousands.

---

## 11. Current State

### What's Working

- **First slice complete and signed off.** GATE-S1 was signed off 2026-10-11 (`011` D-26): every TEST-S1 case passed in CI run 38109732065 (315 tests). Evidence is in `013`, the AAR in `000-aars/014`.
- **Main is green.** CI run 38118250313 on PR #18's head: 333 passed in 91 s, with `PASS 25, FAIL 0, INCOMPLETE 0, NOT RUN 0`.
- **The acceptance gate is enforced in code** (`tests/conftest.py`, `tests/acceptance.py`), with a standing child-run proof and a CI pin (`tests/test_acceptance.py`).
- **The release cannot publish over failing tests.** PR #18: `scripts/require_green_ci.py` was proven live, refusing in run 38118219016 attempt 1 and passing in run 38118533205.
- **Independent review per task**, with one blocker found and fixed in S1-T7 and one in S1-T8 (AAR `014` section 4).
- **Mutation-tested protections** across intake, worker, confirmation, staff view and the gate (AAR `014` section 4).
- **The planning record is complete** for all phases. Decisions D-01 to D-26 are recorded in `011` section 4.1.

### What Needs Attention

- **[HIGH]** The release still pushes its bump commit to `main` → Impact: unreviewed commits on `main`, and the tag on an untested commit → Fix: bead `catalyst-v2-oyu` before any real release.
- **[HIGH]** No deployment path, backup, restore, monitoring or staff MFA → Impact: nothing can be piloted → Fix: P6 (`catalyst-v2-9kg`) after the correspondence loop. Define staging first.
- **[HIGH]** 18 open product policies (`011` section 6, bead `catalyst-v2-211.7`); POL-01 is the only one decided → Impact: later phases block on owner decisions → Fix: schedule decision sessions by gate, starting with those the correspondence loop relies on (POL-06 communications and POL-19 identity disputes at P2 start; POL-02 link lifetime and resends before real email) (corrected, see errata).
- **[MEDIUM]** README and CHANGELOG are stale → Impact: misleads every new reader and any outside reviewer → Fix: one docs PR.
- **[MEDIUM]** No Python lint, format or type check, and no SAST or dependency audit in CI → Impact: style drift and unseen vulnerable dependencies as the code grows → Fix: add Ruff (lint and format), `pip-audit` and CodeQL as required checks.
- **[MEDIUM]** There is no local "run the app" recipe → Impact: demos and manual QA need tribal knowledge → Fix: add `web` and `worker` services to `compose.yaml` (development only, filebased sink) and a README section.
- **[MEDIUM]** The merge-guard registration is outside the repo and was clobbered once → Impact: merges blocked; a silent removal could also un-watch the repo → Fix: estate-level, versioning `repos.yaml` (intent-os).
- **[MEDIUM]** There is no rate limiting on public endpoints → Impact: form spam and link brute-force attempts (the signature makes brute force infeasible, but load is unbounded) → Fix: a P6 proxy limit, plus an application-level throttle on intake.
- **[LOW]** The test process holds administrator credentials (`catalyst-v2-6hl.10`, now under P6).
- **[LOW]** `release.yml` uses an unpinned action (`actions/checkout@v7`) → Fix: pin by SHA as `ci.yml` does.
- **[LOW]** Reverse migrations are exercised for some apps only (`accounts` 0001-0002 and `correspondence` are not).
- **[LOW]** The orphan check's negative control covers missing subjects only (QA residual, AAR `014`).

### Implementation Status

| Component | Status | Evidence |
|---|---|---|
| Skeleton, guards, CI lane (S1-T2) | **Implemented** | PR #9, `config/guards.py`, `tests/test_startup.py` |
| Data model, roles, append-only history (S1-T3) | **Implemented** | PR #11, `tests/test_db_roles.py` (46 functions) |
| Public intake (S1-T4) | **Implemented** | PR #12, `tests/test_intake.py` |
| Worker and verification send (S1-T5) | **Implemented** (local sink only) | PR #13, `tests/test_worker.py` |
| Confirmation (S1-T6) | **Implemented** | PR #14, `tests/test_confirmation.py` |
| Read-only staff view (S1-T7) | **Implemented** | PR #15, `tests/test_staff.py` |
| Acceptance gate and evidence (S1-T8) | **Implemented** | PR #16, `013`, `014` |
| Release gate on green CI | **Implemented** | PR #18 |
| `start_evidence_collection` action | **Placeholder**: created `held`, no handler | `applications/confirmation.py` |
| Correspondence loop (P2) | Planned | epic `catalyst-v2-7hu` |
| Evidence and MiniMax assessment (P3) | Planned | epic `catalyst-v2-oc4` |
| Agreements via Documenso (P4) | Planned | epic `catalyst-v2-hdg` |
| Provisioning and activation (P5) | Planned | epic `catalyst-v2-tuc` |
| Staging, deployment, backup, monitoring (P6) | Planned | epic `catalyst-v2-9kg` |
| Legacy data compatibility (PL) | Planned | epic `catalyst-v2-dy7` |

---

## 12. Roadmap

### Week 1 — Stabilization

- **Land `catalyst-v2-oyu`.** Outcome: no workflow writes to `main`, and a dry-run release produces a PR, not a push.
- **Refresh the README and CHANGELOG.** Outcome: the README describes the merged slice and how to run it, and the CHANGELOG lists PRs #9 to #18 under `[Unreleased]`.
- **Add Ruff, `pip-audit` and CodeQL to CI**, keeping one stable required-check name per lane (`009` section 5.5). Outcome: all green on `main`.
- **Pin `actions/checkout` in `release.yml` by SHA.**
- **Owner:** decide the policies the correspondence loop relies on (POL-06 communications and POL-19 identity disputes at P2 start; POL-02 link lifetime and resends before real email), ahead of their formal gates (corrected, see errata).

### Month 1 — Foundation

- **P2 correspondence loop** (epic `catalyst-v2-7hu`): outbound policy, reminders, stop rules, inbound correlation design, and staff takeover. Includes the first staff write actions (pause and resume, resolve attention) with audit.
- **Local development services** in `compose.yaml` (web and worker with a filebased sink), and a "run it" README section.
- **Move the merge-guard registry under version control** (estate, intent-os).
- **Resolve `catalyst-v2-6hl.10`:** the administrator login used only for role provisioning.

### Quarter 1 — Strategic

- **P3 evidence and the bounded MiniMax assessment**, with typed outputs, evidence references, rubrics, prompt and version provenance, and usage caps (agent `catalyst-minimax-evaluation`).
- **P4 agreements through Documenso**, including the NDA-before-User-Agreement ordering and custody. Requires the heartbeat or idempotency decision for non-redeliverable kinds.
- **P6 staging** with backup and a **measured restore drill (RTO)**, plus monitoring of pending actions and the inbox. All `006` deployment gates closed. This is a pilot-ready target.
- **PL legacy compatibility plan** before any cutover from the first-generation service.

---

## 13. Quick Reference

### URLs

| Resource | URL |
|---|---|
| Repository | <https://github.com/intent-solutions-io/catalyst-onboarding-v2> |
| CI (Actions) | <https://github.com/intent-solutions-io/catalyst-onboarding-v2/actions> |
| GATE-S1 run of record | <https://github.com/intent-solutions-io/catalyst-onboarding-v2/actions/runs/38109732065> |
| Planning start | `000-docs/011-PP-PLAN-master-blueprint.md` |
| Status | `000-docs/006-LS-STAT-status.md` |
| Acceptance evidence and AAR | `000-docs/013-…`, `000-docs/000-aars/014-…` |

### First-Week Checklist

- [ ] Access to the repository; `gh` authenticated
- [ ] `scripts/test.sh` passes locally, with the acceptance report showing all PASS
- [ ] Read `011` (blueprint), `005` S1 (the slice) and this document
- [ ] Read `009` (workflow and quality contract) and `007` (agent charter)
- [ ] Run `bd ready` and read the open epics
- [ ] (No staging deploy exists yet; skip)
- [ ] Meet the owner (Jeremy Longshore); learn the open policies list

---

## Appendices

### A. Glossary

- **Application**: one person's open request, keyed by the normalized email (`email_key`).
- **Submission version**: one submitted set of answers. Append-only.
- **Adoption**: the record that the address owner confirmed one specific version. Immutable.
- **Challenge**: the verification link's database record (`public_id`, expiry, used, superseded).
- **Pending action**: a durable unit of work in the ledger (`queued`, `running`, `done`, `failed`, `uncertain`, `held`, `cancelled`).
- **Lease and fence**: a claim's token and expiry. A result is written only if the token still matches.
- **Poison rule**: an action whose attempts are exhausted is finished without running again.
- **Staff item**: a `needs_staff_attention` event. Resolution arrives in P2.
- **GATE-S1**: the first-slice acceptance gate (`002` section 6).
- **D-nn, ADR-nn, POL-nn**: decisions, architecture decisions and open policies, in `011` and `003`.

### B. Reference Links

- Django 5.2 documentation: <https://docs.djangoproject.com/en/5.2/>
- PostgreSQL 16 `SELECT ... FOR UPDATE SKIP LOCKED`: <https://www.postgresql.org/docs/16/sql-select.html>
- Keep a Changelog: <https://keepachangelog.com/en/1.1.0/>

### C. Troubleshooting Playbooks

- **Tests hang:** a lock test holds a row lock. The harness closes test connections before joining threads, but a new test might not. Run `docker compose -p <project> exec db psql -U catalyst_admin -c "select pid, wait_event_type, query from pg_stat_activity"`, then stop the project with `docker compose -p <project> down -v`.
- **Full run fails with an acceptance case NOT RUN:** a mapped test was renamed or removed. Update `tests/acceptance.py`.
- **`safe-merge` refuses:** read its `reasons`. Typical causes are a missing registration (8.2), a failed check run on the head (8.3), or a draft PR. Never bypass.
- **Worker sends nothing:** check `workflow_pendingaction` for `held`, `cancelled` or `failed` rows and `last_error`, and check for an `automationpause` row on the subject. The dossier's "next responsible party" line says the same.

### D. Open Questions

1. Which of the 18 open policies does the owner want decided before P2 starts, and in what sessions?
2. Should the release produce a version-bump PR, or tag the merged commit without a bump commit (`oyu`)?
3. Where will staging run (the `intentsolutions` VPS behind Caddy, per estate norms), and does the staff UI get its own hostname and network restriction (POL-13)?
4. Does the confirmation token move out of the URL path, or is access-log stripping at the proxy enough?
5. When does the first-generation service's live applicant data need a compatibility bridge (PL), and what is the cutover rule?

---

**Health score: 68/100 (an unscored judgement, not a rubric result; corrected, see errata).** The engineering of the shipped slice is strong (about 85). The score is pulled down by a pre-production posture: no deployment, monitoring or backup; the open release-path defect; stale front-door docs; and no static analysis or dependency audit in CI. That is appropriate for the phase, but it is the distance to a pilot.
