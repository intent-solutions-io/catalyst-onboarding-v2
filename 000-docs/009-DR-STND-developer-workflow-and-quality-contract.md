# Developer Workflow and Quality Contract

**Version:** 0.3.0 (preliminary, subject to owner review; owner decisions of 2026-10-09 recorded in section 9)
**Date:** 2026-10-09
**Status:** **proposed.** Nothing here is approved until the owner says so in a merged pull request.
**Companion documents:** `010-DR-REFF-hook-and-memory-responsibility-register.md` (what runs, where,
and what it costs), `003-AT-ARCH-architecture.md` section "Learn and Django routing" (route ownership),
`007-DR-STND-agent-operating-charter.md` (rules for the specialist subagents).

> **Status: PRELIMINARY, subject to review.** Documentation maintenance only. This document changes
> no hook, setting, workflow, service or route in this repository. Two machine-local changes outside
> the repository were made on the owner's in-chat instruction before this task's full instruction
> arrived (P1 and P3, section 7); every other configuration change it names is a proposal.
> Timing figures labelled "target" are engineering goals, not measurements or vendor guarantees.

## 1. One job per system

The rule: instructions explain the rules; Beads tracks work; approved documents record decisions;
the brain supplies scoped institutional knowledge; hooks perform small bounded actions; CI supplies
reproducible check evidence. None of them stores another's truth, and none reruns another's checks.

| System | Its one job | Where | It is not |
|---|---|---|---|
| Approved PRD, architecture, ADRs, success contract | versioned project intent and acceptance requirements with review status and stable identifiers | `000-docs/` (none approved yet; `001`-`006` are seeded templates) | a scratchpad; an unapproved draft is not a requirement |
| `CLAUDE.md` | Claude Code's entry point: essential boundaries, canonical commands, links | repository root | a specification or a copy of managed guidance |
| `AGENTS.md` | the same entry point for other coding agents (Codex and similar) | repository root | something Claude Code reads here: with a `CLAUDE.md` present, Claude Code reads `CLAUDE.md` only (memory doc, "When Claude Code reads AGENTS.md") |
| `.claude/rules/` | scoped topic rules, if and when a topic needs one | not used yet | an access-control sandbox (rules are guidance) or a second copy of `CLAUDE.md` |
| Beads (`bd`) | task identity, dependencies, progress, evidence-linked handoffs, task recovery | embedded Dolt database; `.beads/issues.jsonl` is a passive export; Dolt history pushed to `refs/dolt/data` on this repository, **which is public**: bead titles and notes are publishable text and never carry sensitive content | a design record; a Markdown task list beside it |
| Claude native auto memory | optional local convenience for one user's working preferences | `~/.claude/projects/<project>/memory/MEMORY.md` on that user's machine (memory doc, "Auto memory") | project policy, a decision store, a backlog mirror, or anything published |
| Bob's Big Brain / Intent OS | scoped institutional retrieval; governed publication of approved knowledge | the estate's governed brain, reached read-only by `catalyst-intent-knowledge` | a session log or a place to copy into this public repository |
| Skills | reusable procedures invoked for a relevant task | installed skills | mandatory rituals after every edit |
| Hooks and settings | bounded event automation; actual runtime permissions | Claude Code settings at every scope, Git hooks, Codex hooks | test runners, workflow engines, publishing steps or product jobs |
| CI (GitHub Actions) | reproducible check evidence on pull requests and `main` | `.github/workflows/` | a deploy or release trigger; a second copy of every local loop |

**Reconciling "do not use MEMORY.md".** The managed Beads block in `CLAUDE.md` says not to use
`MEMORY.md` files. Read it as: do not create a `MEMORY.md` in this repository for project knowledge
(use `bd remember` for workflow knowledge and `000-docs/` for decisions). Claude Code's own auto
memory file lives outside the repository and may hold personal preferences. This task does not
change the auto memory setting or publish its contents.

**Enforcement versus guidance.** Instruction files and rules are context the model reads; they do
not block anything (memory doc, "CLAUDE.md vs auto memory"). Tool allowlists, permission settings,
deterministic hooks, CI and the merge guard enforce. A rule that must hold is placed in an
enforcing layer, not only written down.

## 2. Working agreement

This is the single source for how work is authorized. `CLAUDE.md` and `AGENTS.md` link here.

1. The current authorized task defines scope. Ask before materially expanding it.
2. Preserve other people's and other sessions' work: never discard, overwrite or commit unrelated
   uncommitted changes; use a branch per task.
3. Publication follows the task: commit and push only the change set the task authorizes; open
   pull requests as drafts unless told otherwise; subagents never publish. Authority to commit, push
   or merge comes from the owner's instruction in the current session. The managed Beads blocks'
   default "Conservative" profile applies; this repository has not opted in to the Team-maintainer
   profile.
4. Never force-push, rewrite published history, or bypass the merge guard.
5. No production action, provider write, applicant contact, DNS, proxy or secret change without
   explicit, separate authorization.
6. Approvals are separate acts: approving a commit or PR, approving an architecture decision, and
   approving a production deployment are three different authorizations. A merge does not by itself
   change product policy or authorize publishing private knowledge.
7. Decisions need explicit authority. Reserved decisions (admission, decline, identity disputes,
   legal text, retention) belong to the owner and counsel.
8. Report outcomes as they are: PASS, FAIL, SKIPPED, NOT RUN or BLOCKED, never a summary that hides
   which.

## 3. Beads discipline

- One bead per bounded task, under an epic; plain-English titles; claim, note milestones, close with
  evidence. Runtime verification that has not happened stays open.
- Use the installed CLI only. Never hand-edit `.beads/issues.jsonl`; commit the export the CLI
  writes. Managed `CLAUDE.md`/`AGENTS.md` blocks change only through `bd setup` (supports `--check`,
  `--print`, `--remove`).
- Recovery after a session or compaction: `bd prime` (already run by a session-start hook), then
  `bd ready` or `bd list --status in_progress`.
- Cross-machine history: `bd dolt push` when the task authorizes a push.
- **Public Beads (owner decision, 2026-10-09):** bead history in this repository is public and is
  permitted only for sanitized engineering work. No applicant information, private Intent OS
  knowledge, secrets, confidential documents or internal access details in titles, notes or close
  reasons. Material that cannot safely be public is not tracked here; escalate it to the owner for
  private tracking.

## 4. Brain discipline

- **Retrieve narrowly**: only when a task needs institutional context, through
  `catalyst-intent-knowledge`, one or two keywords, cited results, sanitized summaries.
- **Propose small updates after an approved decision or a verified milestone**, never per session.
  Each candidate carries: project identifier, source (commit, PR or document id), decision or
  evidence status, scope, date, owner, supersession relationship, idempotency key. Drafts and
  experiments are marked as such.
- **Publish only through the governed route** (capture, then governance review) after
  authorization, and record the receipt. Corrections supersede; they never silently rewrite.
- No raw transcripts, no second scheduler or compiler, no brain-write access for specialists.
- Brain unavailable means a visible pending handoff, never a blocked documentation task or a
  re-run of tests.
- Knowledge refresh is not a software upgrade. CLI, skill, Beads and dependency upgrades happen only
  in a bounded maintenance PR with compatibility checks and rollback, never on session start or per
  commit.

## 5. Checks and CI

### 5.1 Canonical commands (one per check group; CI runs the same tools and versions)

| Group | Canonical command | Risk it covers | Measured locally (2026-10-09) |
|---|---|---|---|
| Markdown | `npx --yes markdownlint-cli2@0.24.0 "**/*.md"` | broken formatting that hides content | 2.1-2.7 s warm; in CI (action pinned by commit) |
| Doc index | `bash scripts/check-docs.sh index` (CI step "Every filed doc appears in 000-docs/000-INDEX.md" calls it) | filed documents nobody can find | 0.07 s; in CI |
| Agent definitions | **CI:** the step "Agent definitions stay read-only and well formed" in `ci.yml` (frontmatter parses, 14 fields, name matches file, no Write/Edit/Bash/Agent/Task/NotebookEdit/Skill granted, Agent denied, model allowed, no permission bypass). **Local, when definitions change:** `claude plugin validate .claude/agents` plus the Intent Solutions validator behind `/validate-agent` (maintainer's tooling, not vendored here) | malformed or over-privileged specialists | CI step 0.09 s locally; IS validator 2.4 s for eleven (owner-local) |
| Python lint and dependency audit | **CI:** the step "Python lint and dependency audit (ruff, pip-audit; 009 section 5.1)" in the docs job, on every pull request. **Local:** `ruff check .` (ruff 0.17.3; rules in `pyproject.toml`) and, from a virtual environment with `pip install --require-hashes --no-deps -r requirements/lint.txt`, `python -m pip_audit --disable-pip --no-deps --require-hashes -r requirements/base.txt -r requirements/dev.txt -r requirements/docs.txt -r requirements/lint.txt -r requirements/browser.txt` | undefined and unused names, import and comparison mistakes, syntax errors; a locked dependency with a known vulnerability | ruff 0.45 s over 286 files; pip-audit 4.8 s with a warm cache, 10.3 s with a fresh one, over 57 distinct locked distributions; the hash-locked tool install 21 s (2026-10-23, bead `catalyst-v2-9kg.46`) |
| Runtime tests | `scripts/test.sh` locally (a unique Compose project per run; it provisions the three database roles, then runs the suite; cleanup removes only that run's resources); CI job "Runtime checks (Python 3.14.8, PostgreSQL 16.15)" with the same digest-pinned images, aggregated into the required check | settings, start-up guards, data-model constraints, database roles and append-only protection, migrations; a skip, xfail or xpass fails the run | 130 tests, 61.2 s of tests, 88 s wall locally (2026-10-10, 1B.2 branch) |
| Secrets | **CI:** gitleaks 8.30.1 (checksum-verified download) over full Git history, redacted output | credentials in the public repository | 0.32 s locally over history; 1.1 s over the working tree |
| Sensitive content beyond secrets | `python3 -m config.personal_data_scan --class evidence` over the committed evidence set (run by the suite, so in CI; `026` section 11.2) plus manual diff review for private paths, internal access details and agreement text elsewhere | public exposure | scan 0.1 s locally; the rest manual (gitleaks finds credentials, not personal data) |
| Links and cross-references | manual check that every referenced `000-docs` file exists | dangling references | NOT MEASURED; local only |

`ci.yml` pins the action by commit (`markdownlint-cli2-action` v25.0.0 since the grouped Dependabot
PR #144 of 2026-10-30; v24.2.0 from PR #1 before that), not the tool; v25.0.0 bundles
`markdownlint-cli2 0.24.0 (markdownlint 0.42.0)` (its `package-lock.json` at the pinned commit),
which is why the local command pins 0.24.0. (Before PR #1 the action was v19 and bundled 0.17.2; v24.2.0
bundled 0.23.2.) A `check-docs` script that both CI and contributors call, with the tool version pinned
in one place, is proposal P4. Until then "same version as CI" holds only while the action keeps bundling
0.24.0; a Dependabot bump of the action changes it and must update this line and `scripts/check-docs.sh`.

### 5.2 Skills versus test execution

- `/validate-agent`: when an agent definition changes; schema and declared-tool consistency, plus
  scoped synthetic behaviour checks when behaviour text changes.
- `/audit-tests`: assesses test adequacy for a changed behaviour or risk; not a full-estate audit
  after every commit.
- `/implement-tests`: implements approved missing regression cases; not an architecture rewrite.
- Ordinary test execution is deterministic commands. No LLM reviewer is needed to run tests.

### 5.3 Lanes (proposed)

| Lane | Trigger | Runs | Never |
|---|---|---|---|
| Documentation-only | PR touching only `*.md`, `000-docs/`, `.beads/issues.jsonl` | Markdown, index, link and cross-reference checks, sensitive-content review; agent validator if `.claude/agents/` changed | boot PostgreSQL or run product integration tests for prose |
| Developer feedback | local edit loop during implementation | changed-file lint, format, type checks and the relevant unit and regression tests | rerun unchanged exhaustive suites on every edit |
| Runtime-code PR | any change to code, tests, dependencies, migrations, CI, hooks or test selection (these are **not** docs-only) | the complete hermetic unit and PostgreSQL integration suite while it is small, plus critical safety invariants | substitute SQLite for PostgreSQL locking or schema tests; select a subset before measurement shows the need and the selection map is itself tested |
| High-risk change | schema or data preservation, auth or permissions, signing gate, inbox correlation, retry and reconciliation, provisioning | the specific invariant tests for that area, before merge | defer them to a nightly run |
| Release evidence | explicit, human-authorized release | full journey, recovery, restore, deployment and rollback rehearsal, approved provider canaries in isolated staging | real applicant email, live signing requests or production writes from ordinary CI |

**Python lint and dependency audit (added 2026-10-23, bead `catalyst-v2-9kg.46`).** One step in the documentation job, so
every pull request reports it under the existing required check and no job or check name changed (section 5.5; the
release gate's two names are unchanged). Scope: ruff's default rule set (`E4`, `E7`, `E9`, `F`) over every tracked Python
file, with `F811` ignored under `tests/` because test modules import fixtures from other test modules and then name them as
test parameters; `pip-audit` over the hash-locked requirement files (four then; five since `browser.txt`, bead `catalyst-v2-9kg.68`), reading them without installing anything and
failing on any known vulnerability, fixed or not (a waiver is an explicit `--ignore-vuln` with its reason in the
workflow). Both tools are hash-locked in `requirements/lint.txt`, compiled like `docs.txt`. Measured on the development
host: ruff 0.45 s, pip-audit 4.8 s warm and 10.3 s with a fresh cache, the tool install 21 s; at that measurement the step ran after the
runtime job. It now starts in parallel under the owner-approved 9kg.93 change below. The CI figure is on its
pull request. At `main` `c26e1c0` the default rules found 240 items: 214 `F811` (scoped out as above), 16 unused imports
(removed), one placeholder-less f-string in a migration (the `f` removed; the SQL is byte-identical), two ambiguous
names (`l` to `link`), five lambda assignments and one unused variable in tests, and one undefined name: a provisioning
retry callback read the `except` clause's variable, which Python unbinds when the clause ends; the callback runs inside
the clause today, so no behaviour changed, and the value is now bound before the callback is built. Not adopted, each
needing the owner (proposal P11): `ruff format` (234 of 286 files would change), import sorting (94 files), the `B` and
`UP` rule groups (11 items), a type checker, CodeQL.

**Targeted iteration lane (added 2026-10-23, bead `catalyst-v2-9kg.45`).** Fast feedback on a task without omitting a
test from the merge gate. The pull request's required check "Runtime checks (Python 3.14.8, PostgreSQL 16.15)" stays
the complete suite, and so does the release-candidate gate (`scripts/require_green_ci.py` reads only the two required
names); a targeted run is reported, never gated (`tests/acceptance.py` marks a selected subset "not gated").

- *Selection rule.* `scripts/select_tests.py` maps changed paths to test modules and prints pytest arguments:
  `git diff --name-only origin/main... | xargs python3 scripts/select_tests.py`. The map is derived from the code each
  time (no hand-kept list to drift): every test module's first-party imports, read with `ast` and followed through the
  test modules and helpers it imports (the fixture chains). A change under an application package (outside
  `migrations/`) selects every test module that reaches that package; a change to a test module or helper selects it
  and every module that imports it. Everything else runs the whole suite: `config/` (settings, URLs and guards load in
  every test), migrations, `tests/conftest.py`, the worker child scripts, requirements, the Dockerfile, compose files,
  `deploy/`, `scripts/`, `.github/`, prose. So does a selection above half of the test modules.
  `python3 scripts/select_tests.py --table` prints the whole map.
- *The map is tested* (`tests/test_select_tests.py`, as the "Runtime-code PR" row requires before any subset is
  selected): every test module is reachable through it; a package change selects every module whose source imports
  that package (a regex reading, independent of the `ast` walk); fixture chains are followed; unmapped paths and wide
  selections run the whole suite; the four test modules no package change reaches are pinned by name (seven more reach `applications` and `workflow` through `tests.support` since PR #88), so a new one
  is a decision. Known blind spot, which is why the lane never gates: a view reached only through a URL, a management
  command called by name, or a template.
- *Where it runs.* Locally, `PYTEST_ARGS="$(git diff --name-only origin/main... | xargs python3 scripts/select_tests.py)"
  scripts/test.sh`. In CI, the dispatch-only workflow "Targeted runtime checks" (`targeted.yml`): same digest-pinned
  images, roles and settings as `ci.yml`; a `selection` input that reaches pytest only through an environment
  variable, is validated before any other step and is split by `xargs` (never a script body); the slowest 25 tests
  listed. It adds no required check, no path filter and no change to an existing job; `tests/test_release_gate.py`
  checks that it stays dispatch-only, outside the gate's names and on the same pinned images. A dispatch needs the
  workflow on `main`, so its hosted-runner time is read off the first dispatch after merge.

**Parallel full-suite CI (owner-approved 2026-10-31, bead `catalyst-v2-9kg.93`).** The CI latency audit covered
150 Actions runs (73 CI, 73 Image, four Dependabot). Successful runtime jobs had median test time 1,617 s,
setup 27 s and machine queue 2 s. The owner approved caching scans, parallel fast checks and complete-suite
sharding; paid runners and reduced PR test selection were not adopted.

- Four standard hosted runners each have their own pinned PostgreSQL service and the existing synthetic role
  provisioning. Each collects the full test manifest, then runs every fourth sorted node, including parametrized
  instances. There is no changed-file selection, shared database, new test dependency or maintained partition map.
- The existing required runtime check aggregates the four records with `scripts/ci_shards.py`. It refuses missing
  or duplicate shards, different collections, commit/run/attempt mismatches, nonzero exits, skips, xfail/xpass,
  missing phases, duplicate executions and any acceptance case without all its evidence. Every collected test,
  including tests outside the acceptance map, must have successful setup, call and teardown exactly once.
- Only the verified union writes `register.json`, using the same serializer as a local full run. Local full runs
  and dispatch-only targeted runs keep their existing semantics. Shard artifact transport is mandatory;
  archival upload of the final register remains optional. Use **Re-run all jobs**, not failed jobs only: records
  from an earlier attempt cannot be mixed into a new proof. Artifacts include the attempt in their name.
- The existing required documentation check starts in parallel and retains Markdown, index, agent-definition,
  Ruff, dependency-audit and full-history secret checks. Both existing required check names remain unchanged;
  neither branch protection nor the release gate needs a name change. No new deployment automation is added.
- The image scan restores Grype's database cache and still checks for updates. The audit measured median database
  preparation of 83.34 s versus 1.25 s vulnerability matching; warm-cache savings must be measured after a hit.
  Shards print the slowest 25 tests so balance can be assessed from the first hosted run.

**Phone-width browser check (added 2026-10-24, bead `catalyst-v2-9kg.68`).** One real browser check of the public
applicant pages, which the screen walkthrough (`029` appendix B, GAP 6) could only read as HTML. Decision: **a
documented pre-release step plus a dispatch-only CI job**, not part of the required check. Chose that over a job on
every pull request because the check pulls a browser image of about 1 GB compressed and adds about four minutes for
pages that change rarely, while a skip cannot stand in the full suite (a skip fails the run, section 5.6).

- *What it runs.* `tests/browser_phone_check.py` (not collected by the full suite: the name does not start with
  `test_`) in a headless Chromium at 375 px (a mobile context, so the viewport declaration is honoured only if the page
  declares it) and at 1,280 px: request access in open mode and in invitation mode with the data notice, request
  received, confirm your address and its result, set your own password with its refusal and its result, withdraw and
  its result. On each page it asserts that the layout width equals the device width, that the document is no wider than
  the viewport, and that every form control is visible, inside the viewport, usable by pointer (Playwright's
  actionability checks) and reached by the Tab key; the forms are filled and submitted in the browser. Every page
  request is answered in-process by Django's test client with CSRF checks enforced, inside the test's transaction, on
  synthetic data from the existing helpers; a request for any other origin fails the test, so the browser reaches
  nothing.
- *Pins.* Playwright 1.63.0, hash-locked in `requirements/browser.txt` (compiled like `dev.txt`, constrained to it, and
  in the `pip-audit` step); the browser image `mcr.microsoft.com/playwright/python:v1.63.0-noble` by digest in the
  overlay `compose.browser.yaml`, so `compose.yaml` and the full suite are unchanged. The module refuses a client
  version that differs from the image tag.
- *Where it runs.* Locally, `scripts/browser_check.sh` (isolation and cleanup as `scripts/test.sh`; arguments go to
  pytest). In CI, the dispatch-only workflow "Phone-width browser check" (`browser.yml`) runs the same script; it takes
  no input, adds no required check and changes no existing job, and `tests/test_release_gate.py` checks that it stays
  dispatch-only and outside the gate's names. Run it before a release that touches a public template or its styles, and
  before wider enrollment (`9kg.31.10`).
- *Measured* on the development host, 2026-10-24: 6 tests passed in 118 s of pytest, 4 min 10 s wall including both
  dependency installs and the role provisioning. The check fails as it should: with the viewport declaration removed
  the phone layout was 980 px wide, and with the wrapping rule removed an unbroken 250-character link on the confirm
  page made the document 2,000 px wide; both runs failed and the restored templates passed. The hosted-runner time is
  read off the first dispatch after merge.

The map at `main` `3477231` plus this change (55 test modules), with each row's measured share of the suite from the
2026-10-23 profile (section 5.4; shares from the development-host run of the 1,452-test suite, the hosted-runner
minutes scaled to that suite's hosted run of 1,149 s; module counts are today's, test counts the profiled suite's):

| Changed path | Modules selected | Tests | Share of suite time | About, on a hosted runner | Lane result |
|---|---|---|---|---|---|
| `accounts/` | 8 of 55 | 129 | 10 % | 2 min | targeted |
| `provisioning/` | 9 | 176 | 33 % | 6 min | targeted |
| `agreements/` | 17 | 324 | 55 % | 10.5 min | targeted (module count under half; time over half) |
| `assessments/` | 27 | 622 | 62 % | 12 min | whole suite (over half the modules) |
| `correspondence/` | 39 | 1,104 | 84 % | 16 min | whole suite |
| `workflow/` | 42 | 1,191 | 86 % | 16.5 min | whole suite |
| `applications/` | 43 | 1,266 | 92 % | 17.5 min | whole suite |
| one test module that no other imports (34 of the 55) | 1 | its own | 0 to 8 % | seconds to 1.5 min | targeted |
| `tests/test_provisioning.py` (9 modules borrow its fixtures) | 9 | 176 | 33 % | 6 min | targeted |
| `tests/test_outbound.py`, `tests/smtp_server.py` | 34 | 921 | 80 % | 15 min | whole suite |
| `tests/support.py` | 46 | 1,245 | 99 % | 19 min | whole suite |
| anything unmapped (above) | all | all | 100 % | 19 min | whole suite |

**What this shows:**
the lane pays off for a change to one test module, to `accounts/` or to `provisioning/`; a change to the core packages
(`applications`, `workflow`, `correspondence`) reaches nearly every module through the journey fixtures, so the only
real lever for those is making the full run itself faster (proposals P12 and P13). The half-the-modules threshold
lets `agreements/` through at 55 % of the time; that is acceptable for a lane that never gates, and switching the
threshold to measured time is part of P14.

Measured locally on 2026-10-23: the selection for a change to `accounts/roles.py` (8 modules, 147 tests, including
the new `test_staff_roles`) passed in 721 s pytest, 791 s wall, on the shared development host under a load average
of 16 to 25, where the full suite had taken 4,478 s wall an hour earlier under comparable load: about a sixth.

### 5.4 Targets (proposed, not achieved)

Documentation lane under 2 minutes; focused local tests under 90 seconds; ordinary PR CI under 5
minutes on a named runner, with sustained runs over 10 minutes investigated. Record configured
timeout, queue time, setup time (cold and warm) and test time separately. An overrun prompts
profiling, never removed assertions, weakened thresholds, skipped legal gates or unlimited retries.

**As of 2026-10-09, measured:** one CI job, documentation-only; the last six runs on GitHub-hosted
`ubuntu-latest` took 6 to 9 seconds from creation to completion (`gh run list` created and updated
timestamps, 2026-10-09; queue and setup not separated). Earlier pipeline problems in the
first-generation repository are lessons for later lanes, not a description of this repository.

**Runtime lane, profiled 2026-10-18** (bead `catalyst-v2-egz`; `scripts/test.sh` with
`--durations=0 --durations-min=0.5` on the development host, pinned Python 3.14.8 and PostgreSQL 16.15):

| Measure | Before (main `2e48d9e`) | After |
|---|---|---|
| Tests | 919 passed; 0 failed, skipped or xfailed (the run fails on any skip) | the same |
| pytest time | 1019 s | 759 s |
| Wall time, including container start and dependency install | 1052 s | 790 s |
| Setup phases of 0.5 s or more, summed | 15 s | 13 s |
| Call phases of 0.5 s or more, summed | 472 s | 467 s |
| Teardown phases of 0.5 s or more, summed | 309 s (about 1.4 s each) | none at 0.5 s or more |

**Cause.** The fixture servers (SMTP, IMAP, evidence HTTPS, fake Documenso) ran `serve_forever` with its default
0.5 s shutdown poll. `stop()` waits for that poll, so each test with two or three servers spent about 1.4 s in
teardown. The privileged database reset itself costs about 0.12 s per test: 40 resets took 4.8 s in total. Summed over
those 40 resets, the timed parts were:

- the owner connection, 0.47 s;
- waiting for other sessions to close, 0.20 s;
- the truncate, 2.9 s;
- the protection re-check, 1.1 s;
- releasing the test's own connections and threads, 0.10 s.

These sum to 4.77 s.

**Change.** A 0.02 s poll interval in the four fixture servers. Every assertion and every database and role check
is unchanged.

**Remaining cost.** It is in the tests themselves, kept on purpose:

- migration reverse-and-reapply, 25 s and 16 s;
- the acceptance-gate self-test, 16 s;
- killed-worker and killed-collector subprocess recovery, 6 to 9 s each;
- start-up refusal subprocesses, 47 s in total.

The table counts only phases of 0.5 s or more. Its rows do not sum to the 260 s drop in pytest time.

CI on the last measured head took 15 min 51 s for the runtime job (run 39068959123, before this change). The CI
figure after this change is recorded on its pull request (#40). The 5-minute target remains unmet.

**Runtime lane, profiled again 2026-10-23** (bead `catalyst-v2-9kg.45`). Two sources, because the development host
was shared:

- *Hosted runner, `main`* (`ubuntu-latest`, job "Runtime checks", read from the run logs):

  | Run | Commit | Tests | pytest time | Per test | Job, start to end |
  |---|---|---|---|---|---|
  | 39992632511 | `f4d3eb9` | 1,353 | 1,066 s | 0.79 s | 18 min 20 s |
  | 39994957725 | `a3cf764` | 1,353 | 969 s | 0.72 s | 16 min 46 s |
  | 40008137841 | `b2d9277` | 1,359 | 1,060 s | 0.78 s | 18 min 17 s |
  | 40011063747 | `c4b0f03` | 1,385 | 849 s | 0.61 s | 14 min 40 s |
  | 40022677028 | `c26e1c0` | 1,451 | 1,149 s | 0.79 s | 19 min 41 s |
  | 40033214741 | `3477231` | 1,498 | 1,246 s | 0.83 s | 21 min 23 s |

  Against the 2026-10-18 baseline (919 tests, 759 s after the fixture-server change, 0.83 s per test on the
  development host; 15 min 51 s for the job on CI before it): the suite has grown by 63 % in tests and the time with
  it; the cost per test stays in the same range (0.61 to 0.83 s). The same suite varies by about 10 % between hosted runs (969 s and 1,066 s for
  1,353 tests). Setup before the tests (container, dependency install, roles) is 23 to 32 s per run; the docs job,
  which waits for the runtime job, 8 to 12 s; the image build and scan ("Build and scan the image", a separate
  workflow running alongside) about 2 minutes. No image is built in the runtime lane.
- *Development host*, `scripts/test.sh` with `--durations=0 --durations-min=0`, the `c26e1c0` suite plus the lint
  fixes: 1,452 passed, nothing skipped; 4,408 s pytest, 4,478 s wall. It ran beside nine other sessions' test
  containers (load average 13 rising to 30), 3.8 times its hosted time, so its absolute seconds are void and only its
  shares are used:

  | Phase | Share | Note |
  |---|---|---|
  | Call | 71 % | 3,118 s; the test bodies |
  | Setup | 19 % | 827 s; counting phases of 0.5 s or more, 18 % against 2 % on 2026-10-18 (13 s of 759 s). Led by the journey fixtures: `test_provisioning_screen` 4.9 s per test (its `released` fixture replays the applicant journey to a released address), then `test_provisioning`, `test_reminders`, `test_backup_commands`, `test_inbound` |
  | Teardown | 10 % | 446 s, about half of it in phases under 0.5 s |

  By cost class, as shares of the whole run: start-up refusal subprocesses (`test_startup`) 8 %; backup and restore
  (`test_backup_commands`, `test_restore_rehearsal`, `test_post_restore`) 13 %; database roles with the two
  migration reverse-and-reapply tests (79 s and 43 s under load) 5.5 %; the acceptance-gate self-test about 1 %. The
  slowest single test is the restore rehearsal (2.7 %). The database reset was not instrumented again; 2026-10-18
  measured 0.12 s each, part of the setup share. The log is not committed; the shares above are summed from its
  `--durations` table by phase and by module.

**Cause of the growth and what would help (not done here).** Test count, not slower tests. The setup share is the
one cost that grew faster than the suite: journey fixtures that replay an applicant's path for each test. Caching
that state per module, or building it directly instead of through the journey, is the largest repo-only saving in
reach; it changes test set-up across many modules and is a separate bead for the owner to schedule. The 5-minute
target stays unmet; only sharding (P12) brings the required check near it without dropping a test.

**Focused fixture change, 2026-11-01 (9kg.65).** The provisioning-screen module's eight next-action label cases
replayed intake, assessment, both agreements and release merely to inspect a stage and request fields. They now
construct that application state directly and retain the real database pause lookup. All parameter cases and
assertions remain; rendered-screen, permission and consequential-action tests still use the full journey.
An AST comparison confirmed that only this test's setup/signature changed semantically; other edits in the test
file are the changed-file Ruff formatting required by the owner's acceleration instruction.
Two focused local runs of the same 40 cases passed: **100.75 s before, 72.72 s after** (28.03 s, about 28% less).
This is pytest time, excluding container/dependency preparation, and is not a hosted-CI saving claim. Full-suite
CI and further fixture work remain necessary; no test was removed or made conditional.

**Lanes in CI today:**

- on every pull request, four isolated full-collection test shards feed the required runtime aggregate; the required
  documentation job (Markdown, index, agent definitions, Python lint and dependency audit, secret scan) starts in
  parallel; the image workflow builds and scans the image;
- on dispatch only, "Targeted runtime checks" (`targeted.yml`, section 5.3), never a required check.

Selection by change type exists only as the targeted lane's hint; nothing is skipped on a pull request.

### 5.5 GitHub Actions rules

**2026-11-01 image requirement:** GitHub now requires "Build and scan the image" alongside the existing
documentation and runtime checks, with the same Actions app binding and no bypass. The image workflow reports
on every pull request, including docs-only changes. Scan severity and test coverage are unchanged. The matching
merge-guard installation and real refusal/reporting probes remain pending; see `032` section 1.8 for the current
evidence and outstanding boundaries.

- One stable required check per lane that always reports a result. Workflow-level path filters leave
  required checks pending (GitHub, "Handling skipped but required checks"); use job-level conditions
  with an aggregating job (`needs` plus `always()`) instead. Every PR, docs-only or not, produces the
  same required check name, so the merge guard never waits on a check that will not run. A cancelled,
  missing or failed applicable job is never reported as a pass.
- Cancel superseded PR runs with `concurrency: { group: ${{ github.workflow }}-${{ github.head_ref || github.run_id }}, cancel-in-progress: true }` (in `ci.yml` since 2026-10-09)
  (GitHub, "Control the concurrency of workflows"). Never on deployments.
- Avoid duplicate full runs: feature-branch pushes run through `pull_request`; `push` runs on `main`
  only (already the case).
- Cache dependencies keyed to lockfile and runtime version; never cache test verdicts.
- Public repository safeguards: no production credentials or brain access for untrusted pull
  requests; no untrusted code on a persistent privileged self-hosted runner; no `pull_request_target`
  checkout of untrusted heads; pin actions and tools when CI is implemented.
- Merges go through the estate merge guard, which requires every required check green on the exact
  head. This repository was registered in the guard's configuration (kept outside this repository)
  on 2026-10-09 with one required check, "Markdown lint and doc index check"; that registration is
  not verifiable from the repository itself.
- **Effective GitHub protection, checked read-only on 2026-10-18 (D-40):**
  - `main` has no branch protection: `GET repos/.../branches/main/protection` returns 404 "Branch not
    protected".
  - There are no repository rulesets, and `GET repos/.../rules/branches/main`, which includes any
    organization ruleset that applies, returns none.
  - Organization rulesets could not be listed: that needs the `admin:org` scope.
  - The merge guard is therefore client-side and is the only gate on merges. Anyone with write access can push to
    `main` or merge without checks. The release gates below bind only a release run from `main`; they cannot stop
    someone with write access who edits the workflow.
  - The guard registration recorded above names one required check, while CI now has two and the release gate
    requires both. Updating the registration is the owner's (it lives outside this repository).
  - **Proposed** (needs the owner, not done): a ruleset on `main` requiring a pull request, the two required checks
    and linear history, and blocking force pushes and deletion.
- **Releases** (bead `catalyst-v2-oyu`, 2026-10-18):
  - The version and changelog change is an ordinary pull request. `python3 scripts/prepare_release.py vX.Y.Z`
    writes `version.txt`, the `pyproject.toml` version and the CHANGELOG entry. It never commits, tags or pushes.
  - After that pull request merges through the guard, the Release workflow is dispatched from `main` with `version`
    set. Any other ref is skipped. The version reaches steps only through an environment variable, validated first.
    It runs `scripts/release_check.py`, which checks that the version and changelog match, that the commit is the
    current head of `origin/main` and that the tag does not exist yet. It then runs `scripts/require_green_ci.py`,
    which counts only GitHub Actions' own check runs.
  - Only then, after re-checking the tag on the server, does it call `gh release create --target <that commit>`, so
    GitHub creates the tag on the tested commit. The workflow never commits, tags locally or pushes.
  - **Proposed** (needs the owner): a protected `release` environment limited to `main` with a required reviewer.
    That is the only control that enforces this against someone with write access.
  - `dry_run` defaults to true, and the checkout action is pinned to a commit.
  - `pyproject.toml` said 0.0.0 while `version.txt` said 0.1.0 and `v0.1.0` was tagged; the two were aligned at 0.1.0 on
    2026-10-23 (a LOW finding of the 2026-10-22 audit), without a release, so the gate's two sources agree.

### 5.6 Test integrity

Tests challenge behaviour rather than restating the implementation. Fix flaky tests; a temporary
quarantine records risk, owner, expiry and replacement coverage. Security, legal-gate and
job-ownership failures stay blocking. Reports state PASS, FAIL, SKIPPED, NOT RUN and BLOCKED
separately, with command, revision, environment and actual timing. Read the logs to tell a code
failure from an infrastructure or account limit. No retry-until-green.

## 6. Product jobs are not development hooks

The application's inbox polling, reminders, signing checks and provisioning are durable service jobs
in its single PostgreSQL job system. They never depend on a Claude Code hook, a Git hook, a CI
schedule or a terminal someone leaves open. Development subagents are not the product's
applicant-assessment agents.

## 7. Proposals (each needs separate approval)

| # | Proposal | Status |
|---|---|---|
| P1 | Remove the duplicate `bd prime` session-start and pre-compact hooks from the parent projects-folder settings | **kept** (owner decision 2026-10-09) after verifying the user-scope hook still loads Beads context; rollback copy preserved (`010` section 5) |
| P2 | Remove the mandatory-push text from `AGENTS.md` | applied in this documentation change |
| P3 | Update the parent projects-folder `CLAUDE.md` Beads wording from `bd sync` to the Dolt-remote contract | **reviewed and kept**: `bd sync` is an unknown command in Beads 1.1.x, so the old wording was wrong; uncommitted in that file; rollback copy preserved |
| P4 | One `check-docs` script called by both CI and contributors | when code tooling is introduced |
| P5 | Record the live learn proxy route table after an authorized read-only check | **done** 2026-10-09 (read-only); the detail now lives in the private operations records, `003` keeps a summary (amendment of 2026-10-09) |
| P6 | Add `concurrency` cancellation for PR runs | **done** in `ci.yml` |
| P7 | Path-scoped `.claude/rules/` for Python and migrations | when that code exists; none needed now |
| P8 | Run agent-definition validation in CI | **done**: a scoped check on every PR (0.09 s), keeping one stable required check |
| P9 | Add an automated secret scan to CI | **done**: gitleaks over full history; personal-data and private-path review stays manual |
| P10 | Decide whether bead history should stay public through `refs/dolt/data` | **decided**: public for sanitized engineering work only (section 3) |
| P11 | Widen the Python lint beyond ruff's default rules: `ruff format`, import sorting, the `B` and `UP` groups, a type checker, CodeQL | proposed 2026-10-23 (section 5.3); the default rules and `pip-audit` are in CI |
| P12 | Shard the complete suite with isolated runners and aggregate every test and acceptance case | owner-approved 2026-10-31, 9kg.93 (section 5.3): four runners, deterministic full-collection partition, existing required names retained; no merge-guard change |
| P13 | Skip the runtime job on documentation-only pull requests through a job-level condition, the aggregating docs job then accepting "skipped" for that case only | proposed 2026-10-23; changes what the required check means and what `scripts/require_green_ci.py` accepts (today it refuses `completed/skipped`) |
| P14 | Promote the targeted lane: run it automatically on pull requests (as an extra, non-required signal first, or as a required check with the full run moved to merge or release), and switch its "more than half" threshold from module count to measured time | proposed 2026-10-23 (section 5.3); the full run stays the release-candidate gate in every variant; changing the full run's trigger is the owner's |

## 8. Branches and worktrees

Owner decision, 2026-10-09. The first-generation repository reached more than a hundred worktrees and
a hundred-plus local branches; this section exists so that does not happen again. The same rules are
set for every repository on the maintainer's machine through the user-level instructions.

### 8.1 Rules

1. One logical task, one branch, one pull request by default.
2. Prefer the existing checkout for sequential work. A subagent does not get its own worktree.
3. An additional worktree needs a documented concurrency need (two tasks genuinely running at once),
   recorded in the task's bead before it is created.
4. Never create a branch merely to run tests; run them on the task branch.
5. No hook creates, merges or deletes branches. No automatic merging, deletion or force-pushing.
6. Before creating a branch: list local and remote branches, open pull requests and worktrees, and
   continue related work where it already lives instead of starting a parallel branch.
7. After a pull request merges, retire only branches and worktrees that are verified obsolete
   (procedure below). Never remove dirty, untracked, unpublished or otherwise unique work.
8. Record the relationships for recovery in the task's bead: branch, worktree path (or "main
   checkout"), bead, pull request and head commit.

### 8.2 Before creating a branch

```bash
git fetch --prune origin
git worktree list
git branch -vv                  # local branches, upstream state ([gone] = remote deleted)
gh pr list --state open         # open work you might continue instead
```

### 8.3 Retiring a branch or worktree after its PR merged

Retire only when **every** check passes; any failure means keep it and ask the owner.

```bash
gh pr view <N> --json state,mergeCommit,headRefName    # state MERGED
git -C <worktree> status --porcelain                   # empty: nothing dirty or untracked
git log --oneline <branch> --not --remotes             # empty: nothing unpublished
git diff --stat origin/main <branch> -- <the PR's files>  # nothing the merge left out (squash merges)
```

Then, with the owner's go-ahead or under a task that authorizes cleanup:

```bash
git worktree remove <worktree>   # refuses a dirty worktree; never add --force
git branch -D <branch>           # only after the checks above; squash merges make -d refuse
```

The remote branch is deleted by GitHub on merge (repository setting `delete_branch_on_merge`). Record
the retirement in the bead. A stash, an untracked file or an unpushed commit found during the check
is preserved first (bundle or push) and reported, not deleted.

## 9. Owner decisions recorded 2026-10-09

| # | Decision | Where applied |
|---|---|---|
| 1 | Keep the duplicate SessionStart hook removal if verified safe and reversible; review the Beads wording before accepting; preserve rollback copies; no further global changes without approval | `010` section 5 (verified, kept) |
| 2 | Public Beads history only for sanitized engineering work; escalate anything that cannot be public | section 3 |
| 3 | Lean CI: cancel superseded PR runs, scoped agent validation, secret scanning; measure, no duplicate tests | `ci.yml`, section 5, `010` section 2 |
| 4 | Read-only inspection of the live learn routing; no proxy, DNS, container, service or deployment change | `003` "Learn and Django routing" |
| 5 | Staff interface on a separate authenticated hostname with network restrictions and MFA where supported; final hostname and access method are a design decision requiring verification | `003` "Staff interface access (design)" |
| 6 | Strict branch and worktree policy, here and in every repository | section 8; user-level instructions |

## 10. After-action reports

- **When:** one when the planning phase closes (blueprint, PRD and architecture approved); one per
  epic or implementation phase; one after any incident or significant failure. Not per pull request.
- **Lane:** full nine-section AAR for phase closes and any epic with an incident; the lightweight
  lane (What, Why, Verification, Rollback, Next) for routine epics.
- **Where:** `000-docs/000-aars/NNN-AA-AACR-<slug>.md`, global `NNN` (filing standard v4.5
  §3.1.3).
- **Template:** `000-docs/000-AA-TMPL-after-action-report.md`, a snapshot of the canonical
  `/doc-filing` reference (v1.0.0, SemVer); the skill copy wins on any difference.
- **Evidence:** section 4 is checked against the epic's acceptance test, with links.

## 11. Measured CI acceleration (2026-11-01, 9kg.95)

The owner's acceleration instruction supersedes the earlier proposed-only local formatting lane: install
`python3 scripts/install_fast_checks.py` once per clone. It chains staged-file checks through the existing
Beads hook, preserves earlier hooks, and shares its hash-locked tool installation across worktrees. Each commit
checks staged whitespace, Ruff formatting and the configured Ruff static rules on changed Python files only.
Partially staged files are checked from the index; the working tree is never rewritten. No runtime tests or
network requests run in this checker. Reinstall when the checker or lint lock changes. Ruff is static analysis,
not a dedicated typechecker. This change does not format existing untouched Python files or expand CI lint rules.

The checker rejects missing tools, staged Python symlinks and version drift. Its seven host-side integration tests
passed in 1.50 s locally, including index-versus-working-tree differences, per-file rule resolution from the staged
project root, and preservation of an earlier hook.
They run in the existing docs CI job after its lint dependencies; there is no separate runner or database.

The actual installed Beads pre-commit chain, with all three new Python files staged, took **0.28 s** wall time;
the checker itself reported **0.10 s**. This measures the real hook, not just a direct Ruff command. Larger
changes must be remeasured against the owner's approximately 10 s target.

CI shards and the dispatched targeted lane cache pip downloads with a key containing the runner OS,
architecture, Python minor and the base/dev lock hashes. The docs job has a separate docs/lint lock key. The
restore prefix permits reuse of unchanged downloads across lock updates; `--require-hashes --no-deps` still
verifies every installation. GitHub's ref-scoped cache access lets PRs restore a main cache without publishing
their cache into main. A cache miss uses the normal installation; a restored archive is never a test result or
an installed environment. Each shard retains its fresh virtual environment and isolated PostgreSQL database.

`scripts/test.sh` mounts downloads from `${XDG_CACHE_HOME:-$HOME/.cache}/catalyst-v2/pip`; override with
`CATALYST_TEST_PIP_CACHE`. A direct Compose invocation defaults to the ignored `.cache/pip` directory.
Neither the package cache nor the hook tools enter the application image's allowlisted build context.

Local setup-only comparison used two fresh containers of the pinned Python image, the same base/dev locks,
a new virtual environment each time, and one initially empty download cache: **32.44 s cold, 27.23 s warm**
(5.21 s less, about 16%). Both hash-verified installations succeeded. This includes container start and virtual
environment creation; no database or tests ran in that comparison. A focused Compose run of `tests/test_image.py`
also passed all six tests with the cache mount. These local timings are not hosted-runner timings.

### 11.1 Baseline and remaining scope

The refreshed audit used `gh run list --workflow ci.yml --limit 150` and each run's jobs API with `filter=all`:
150 CI runs, 352 job attempts, from 2026-10-26 13:38:04 UTC through 2026-11-01 04:02:22 UTC. Setup uses job/step
timestamps, refined by available logs for dependency installation embedded in static-tool steps. Queue means
job creation to start, not prerequisite-job waiting; artifact transport, cleanup and gaps are separate overhead.
One cancelled 2,400 s job has unavailable logs and an unfinished task timestamp; its task duration is unknown.

| Measurement | Before the first acceleration pass | Current evidence before the download-cache pass |
|---|---|---|
| Runner wait | Median 2 s in the refreshed 150-run window; p95 3 s, maximum 13 s | Queue is not the dominant cost |
| Runtime job | Median 1,700 s across 102 successful unsharded jobs in that window | [Main run 41271267830](https://github.com/intent-solutions-io/catalyst-onboarding-v2/actions/runs/41271267830): whole CI 653 s; four test steps 545, 566, 585, 588 s |
| Docs prerequisite delay | Median 1,696.5 s before the job was created | Median 1 s after it became independent; its own job remains about 19 s |
| Shard package installation | No download cache | Median 14 s across 43 successful shard attempts; container startup median 13 s, checkout 1 s |
| Ruff execution | Already fast | Median 0.075 s from 109 successful docs-job logs; no dedicated typechecker runs |
| Image scan | Earlier baseline repeatedly downloaded its vulnerability database | [Image run 41271491212](https://github.com/intent-solutions-io/catalyst-onboarding-v2/actions/runs/41271491212): restored database, 54 s job; Docker pip installation still 11.8 s |

These are observations across changing suites and hosted runners, not a controlled identical-commit speedup.
The cache pass still needs cold/warm CI measurements after main populates the cache. Local cache and hook
measurements do not prove hosted performance. The full suite and acceptance aggregate remain required.

Remaining work stays in 9kg.95 and 9kg.65: compatible high-performance runners with an agreed account/isolated
host and cost, fixture replay profiling, duration-aware shard allocation, and fail-closed affected checks with a
scheduled full suite. No additional paid runner, provider secret or service is required by this cache/hook pass.
The existing selection helper explicitly permits under-selection and must not be promoted unchanged to a required
gate. The owner's low-single-digit-minute target and complete acceleration instruction are not yet achieved.
