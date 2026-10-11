# First-slice acceptance evidence (S1-T8, GATE-S1)

> This report gives the evidence for the first working slice of Catalyst v2. A synthetic applicant
> submits the access-request form. A worker sends the verification message to a local mail sink. The
> applicant confirms the address through an explicit, single-use link. Authorized staff then read the
> application and its history in a read-only Django Admin view. The acceptance plan is `005` section
> S1.7: 22 cases, TEST-S1-01 to TEST-S1-22.
>
> The report says which tests prove each case, how a run reports and gates them, and what the evidence
> does not show. GATE-S1 (`002` section 6) passes only when every case is PASS at one head, QA has
> reviewed, and the epic's after-action report exists. The owner signs the gate off; this report does
> not.

- **Status:** GATE-S1 signed off by the owner on 2026-10-11 (D-26) on this evidence. Run of record: CI run 38109732065 on `93fc22c` (merged as `3bd31ac`), 315 passed, every case PASS.
- **Epic:** Build the first working slice (bead `catalyst-v2-6hl`); this task is bead `catalyst-v2-6hl.8`.
- **After-action report:** `000-aars/014-AA-AACR-first-slice.md`.

## 1. How a case is proven, reported and gated

| Piece | Where | What it does |
|---|---|---|
| Case-to-test map | `tests/acceptance.py` | Lists, for every case, the test functions that prove it. A plain name counts every parametrized instance. A name with an instance id, such as `[non-postgresql]`, must have run that instance specifically. Three supporting groups are mapped the same way: the ADR-14 runtime role contract, the D-21 test-only reset, and GATE-S1 enforcement. |
| Report | `tests/conftest.py`, `pytest_terminal_summary` | At the end of any run in which a mapped test ran, prints each case as PASS (every mapped entry ran and passed), FAIL (any failed or errored), INCOMPLETE (only some ran) or NOT RUN. |
| Gate | `tests/conftest.py`, `pytest_sessionfinish` | Fails a **full run** unless every case and group is PASS (details below). |
| Skip gate (since 1B.1) | `tests/conftest.py` | A skipped, xfailed or xpassed test fails any run, so a skip can never count as a PASS. |
| Standing proof of the gate | `tests/test_acceptance.py` | Child pytest runs of the real hooks with a replaced map. A complete map exits 0. A missing mapped entry exits 1 although every test passed. `-k` and a path argument are reported as "selected subset: not gated". |
| CI pin | `tests/test_acceptance.py` | CI's runtime step runs exactly `python -m pytest -v`, with no selection, so the gate always binds there. |
| Map integrity | `tests/test_acceptance.py` | The cases equal exactly the 22 IDs in `005` S1.7, and every mapped name is an existing `test_` function. Each status rule is unit-tested. |

**What counts as a full run:**

- no positional path argument, no `-k`, no `-m`, and nothing deselected;
- at least one mapped test ran.

`scripts/test.sh` without `PYTEST_ARGS`, and CI, are full runs.

## 2. Results

**Local full run:** `scripts/test.sh` on Python 3.14.8 and PostgreSQL 16.15, digest-pinned, on the tree committed with this report. The per-case report prints at the end of the run. The test counts and timing are recorded on the S1-T8 bead and in the pull request.

**CI:** the evidence of record is the runtime check on the pull request's final head. It runs the same full suite, so the same gate applies. Its run link, counts and report lines are recorded on the pull request and the S1-T8 bead after the run, because this file cannot carry a link to a run of the commit that contains it.

| Case | Mapped tests | Files | Notes |
|---|---|---|---|
| TEST-S1-01 valid submission | 4 | `test_intake` | |
| TEST-S1-02 invalid submissions | 6 | `test_intake` | field errors, 400 limits, 403 CSRF, zero rows |
| TEST-S1-03 repeat submissions | 11 | `test_intake` | identity key, reuse and supersede rules, repeat after verification |
| TEST-S1-04 concurrent submissions | 5 | `test_intake` | seam barrier; lock-holder races on an existing application; a smoke loop (random interleavings, supporting) |
| TEST-S1-05 failure injection | 7 | `test_intake`, `test_confirmation` | named fault instances; the lost commit acknowledgment is a labelled simulation through the commit call |
| TEST-S1-06 worker sends | 7 | `test_worker` | includes a real worker process with a file sink |
| TEST-S1-07 worker interruption | 5 | `test_worker` | (c) deviates from the plan's wording on purpose (see below) |
| TEST-S1-08 open, then confirm | 6 | `test_confirmation` | |
| TEST-S1-09 refusals | 8 | `test_confirmation` | each refusal's logged reason is asserted, without secrets |
| TEST-S1-10 concurrent confirmation | 3 | `test_confirmation` | race with a repeat, in both orders, as named instances |
| TEST-S1-11 staff access | 9 | `test_staff`, `test_acceptance` | includes an established non-staff session, and a Django superuser refused every write |
| TEST-S1-12 staff dossier | 6 | `test_staff` | the application is created by the same intake POST as TEST-S1-01 |
| TEST-S1-13 PostgreSQL only | 9 | `test_startup`, `test_worker`, `test_guards`, `test_database` | `manage.py check`, WSGI and the worker command, as named instances |
| TEST-S1-14 provider isolation | 14 | `test_startup`, `test_worker`, `test_guards`, `test_network_guard`, `test_acceptance` | scope limits below |
| TEST-S1-15 history completeness | 5 | `test_acceptance`, `test_db_roles` | exact event sequence across the whole flow; no admin page edits versions or events |
| TEST-S1-16 log capture | 3 | `test_acceptance`, `test_confirmation` | whole-flow sweep; details below |
| TEST-S1-17 lease fencing | 2 | `test_worker` | |
| TEST-S1-18 poison and bounded attempts | 6 | `test_worker`, `test_acceptance` | includes a handler that crashes the worker on every attempt |
| TEST-S1-19 held, paused, racing, done | 4 | `test_worker` | |
| TEST-S1-20 schema integrity | 13 | `test_acceptance`, `test_database`, `test_data_model` | 22 named constraints by introspection (behaviour in `test_data_model`); no migration drift; an orphan check over actions, pauses and messages, with a negative control |
| TEST-S1-21 append-only enforcement | 11 | `test_db_roles` | privilege and trigger variant (D-17), including adoptions (D-22) |
| TEST-S1-22 intervening versions | 2 | `test_confirmation` | |
| ADR-14 runtime role contract (supporting) | 8 | `test_db_roles`, `test_worker`, `test_staff` | fresh processes |
| GATE-S1 enforcement (supporting) | 4 | `test_acceptance` | |
| D-21 test-only reset (supporting) | 3 | `test_db_roles` | |

Some tests prove more than one case, for example two `test_db_roles` tests serve TEST-S1-15 and 21, so these counts must not be summed.

**TEST-S1-07(c):** the plan says lease expiry is simulated by writing a past lease time. Cases (a) and (b) do that. Case (c) instead kills a real worker process with SIGKILL and lets a second, already running worker loop recover it after a real 6-second lease. That proves recovery "without manual steps". It is timing-sensitive: the survivor must be polling before the lease expires, which the test asserts, and a much slower runner could fail it.

**TEST-S1-16 sweep:**

- **Flow:**
  - form errors, a CSRF 403, an oversized body (400) and an injected database failure (503) at intake;
  - intake, then the worker, whose first send fails at the sink and is retried and sent;
  - on the link: a tampered link (404), a PUT (405), a CSRF 403, a bad version (400), the confirmation and "already confirmed";
  - a repeat submission;
  - staff: a wrong password, a real login, the dossier, a refused write (403), a hidden-column lookup (400) and logout.
- **Capture:** every record at DEBUG on the root logger and on every logger that does not propagate to it. Each record is formatted, so traceback text exists.
- **Check:** no record's message, traceback text or request attribute contains the token, the link path, the challenge id, the address, the name, either reason, the staff password or a signing key.
- **Coverage asserted:** `applications.views`, `correspondence.verification`, `django.request` and `django.security.csrf` all logged. The `Not Found` line reads `/confirm/[redacted]/`.

## 3. What this evidence does not show

- **No deployment.** No staging or production run happened, so nothing here proves behaviour behind a proxy or a real application server. These are open deployment gates (`006` Blockers; bead `catalyst-v2-9kg`):
  - confirmation paths out of access logs;
  - HTTPS-only links, secure cookies and HSTS;
  - session lifetime;
  - the staff host or network restriction;
  - MFA (POL-13).
- **No real provider.** Mail goes only to a local sink. Sink acceptance is not inbox delivery, and nothing claims exactly-once external effects. Reconciliation of `uncertain` outcomes is P2 (D-20).
- **Provider isolation (TEST-S1-14) is a Python-level aid:**
  - The test network guard covers `socket.connect` and `connect_ex` inside test functions. It does not cover native libraries such as libpq, child processes, collection-time code, UDP or DNS.
  - The CI check reads the runtime workflow (`ci.yml`) only. The release workflow uses GitHub's own token, which is not a provider secret.
- **Simulations, labelled as such:**
  - The lost commit acknowledgment goes through the commit call.
  - The worker reconnect covers a client-side drop at the claim query only.
  - The race tests prove the application lock serializes requests, not interleavings the lock rules out.
- **Granularity:** a plain map entry counts every parametrized instance. Only the instances named in the map are required individually.
- **Test harness credentials:** the test session itself still holds the bootstrap administrator's credentials, tracked by bead `catalyst-v2-6hl.10` (unsolved). Spawned workers receive only application-role credentials.
- **Policies:** POL-01 is confirmed for the slice (D-25). POL-02 (challenge lifetime), POL-13 (staff roles) and POL-16 (send attempts) use synthetic or proposed values.
- **Release blocker:** `catalyst-v2-2xy` (the release workflow swallowed test failures) was fixed after GATE-S1: a release now requires every required CI check green on its commit. `catalyst-v2-oyu` (the release pushes its version bump straight to `main`) still blocks any real release.
