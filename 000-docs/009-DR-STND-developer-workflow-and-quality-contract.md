# Developer Workflow and Quality Contract

**Version:** 0.2.0 (preliminary, subject to owner review)
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
| Markdown | `npx --yes markdownlint-cli2@0.17.2 "**/*.md"` | broken formatting that hides content | 2.1-2.7 s warm; in CI |
| Doc index | the loop in `.github/workflows/ci.yml` step "Every filed doc appears in 000-docs/000-INDEX.md" | filed documents nobody can find | 0.07 s; in CI |
| Agent definitions | `claude plugin validate .claude/agents` (Claude Code's own frontmatter check), plus the Intent Solutions agent validator behind `/validate-agent` (`validate-skills-schema.py --agents-only --fail-on-warn <file>`, from the maintainer's `claude-code-plugins` repository; not vendored here, so outside contributors cannot run it yet) | malformed or over-privileged specialists | 2.4 s for the IS validator on all eleven (owner-local); the plugin check NOT MEASURED; **local only today** (not in CI, proposal P8) |
| Sensitive content | manual diff review for personal data, private paths, credentials, agreement text | public exposure | NOT MEASURED; **intent only today**: no automated scanner in this repository (proposal P9) |
| Links and cross-references | manual check that every referenced `000-docs` file exists | dangling references | NOT MEASURED; local only |

`ci.yml` pins the action (`markdownlint-cli2-action@v19`), not the tool; that action's run log on
2026-10-09 reported `markdownlint-cli2 v0.17.2`, which is why the local command pins 0.17.2. A
`check-docs` script that both CI and contributors call, with the tool version pinned in one place, is
proposal P4. Until then "same version as CI" holds only while the action keeps bundling 0.17.2.

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

### 5.4 Targets (proposed, not achieved)

Documentation lane under 2 minutes; focused local tests under 90 seconds; ordinary PR CI under 5
minutes on a named runner, with sustained runs over 10 minutes investigated. Record configured
timeout, queue time, setup time (cold and warm) and test time separately. An overrun prompts
profiling, never removed assertions, weakened thresholds, skipped legal gates or unlimited retries.

**Current repository, measured:** one CI job, documentation-only; the last six runs on GitHub-hosted
`ubuntu-latest` took 6 to 9 seconds from creation to completion (`gh run list` created and updated
timestamps, 2026-10-09; queue and setup not separated). Earlier pipeline problems in the
first-generation repository are lessons for later lanes, not a description of this repository.
**No lane is enforced in CI today**: the single job runs on every PR, so the lane table is a design
for when code arrives.

### 5.5 GitHub Actions rules

- One stable required check per lane that always reports a result. Workflow-level path filters leave
  required checks pending (GitHub, "Handling skipped but required checks"); use job-level conditions
  with an aggregating job (`needs` plus `always()`) instead. Every PR, docs-only or not, produces the
  same required check name, so the merge guard never waits on a check that will not run. A cancelled,
  missing or failed applicable job is never reported as a pass.
- Cancel superseded PR runs with `concurrency: { group: ${{ github.workflow }}-${{ github.head_ref || github.run_id }}, cancel-in-progress: true }`
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
| P1 | Remove the duplicate `bd prime` session-start and pre-compact hooks from the parent projects-folder settings | **applied 2026-10-09** on the owner's in-chat go-ahead, before this full instruction (which keeps machine settings as proposals) arrived; machine-local, backup kept; the owner decides keep or revert (register section 5) |
| P2 | Remove the mandatory-push text from `AGENTS.md` | applied in this documentation change |
| P3 | Update the parent projects-folder `CLAUDE.md` Beads wording from `bd sync` to the Dolt-remote contract | **applied 2026-10-09** in that file's working tree on the same go-ahead; uncommitted there; owner decides |
| P4 | One `check-docs` script called by both CI and contributors | when code tooling is introduced |
| P5 | Record the live learn proxy route table after an authorized read-only check | pending authorization |
| P6 | Add `concurrency` cancellation for PR runs | with the first CI change |
| P7 | Path-scoped `.claude/rules/` for Python and migrations | when that code exists; none needed now |
| P8 | Run the agent validator in CI when `.claude/agents/` changes | with the first CI change |
| P9 | Add an automated secret and private-path scan to CI | with the first CI change |
| P10 | Decide whether bead history should stay public through `refs/dolt/data` | owner decision |
