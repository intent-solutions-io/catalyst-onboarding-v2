# Hook and Memory Responsibility Register

**Version:** 0.1.0 (preliminary, subject to owner review)
**Date:** 2026-10-09 (inspection and measurements taken the same day)
**Status:** proposed. Recommendations are not applied unless section 5 says so.
**Governs with:** `009-DR-STND-developer-workflow-and-quality-contract.md`.

> **Status: PRELIMINARY, subject to review.** Observed on the setup machine for a Claude Code session
> started in this repository. Only project-owned mechanisms are itemised; a user's personal hooks and
> machine layout are summarized, not mapped, because this repository is public. Runtime behaviour in a fresh session (hook loading, denial, memory) is **pending
> verification under separate authorization**.

## 1. Versions and sources

| Item | Value | Checked |
|---|---|---|
| Claude Code | 2.1.x | `claude --version`, 2026-10-09 |
| Beads | 1.1.x, embedded Dolt | `bd version`, 2026-10-09 |
| Installed skills | `/audit-tests`, `/implement-tests`, `/agent-creator`, `/validate-agent`, `/doc-filing`, `/beads` present and read for scope; none run in this task except as recorded in `008` | skill frontmatter, read only |
| Official docs read 2026-10-09 | memory ("How Claude remembers your project": AGENTS.md, auto memory, rules, imports); settings ("Settings files and precedence"); hooks (event list, SessionStart, Stop, SessionEnd, merging and deduplication); sub-agents; GitHub "Handling skipped but required checks"; GitHub "Control the concurrency of workflows" | code.claude.com, docs.github.com |

**Facts from the docs that this register relies on:**

- Settings precedence, highest first: managed, command line, project local, shared project, user.
  Hook entries **merge** across scopes; a project file does not cancel inherited hooks. The same
  handler defined in more than one settings file runs once; a plugin's or skill's copy stays separate.
- Instruction files load from the working directory and every directory above it, concatenated
  root-first. With any `CLAUDE.md` present, `AGENTS.md` is not read by Claude Code.
- Auto memory lives per repository at `~/.claude/projects/<project>/memory/`; the first 200 lines or
  25 KB of `MEMORY.md` load each session; `autoMemoryEnabled` or `CLAUDE_CODE_DISABLE_AUTO_MEMORY`
  turn it off.
- SessionStart matchers: `startup`, `resume`, `clear`, `compact`, `fork`; its stdout becomes context.
  SessionEnd cannot block and shares a 1.5-second budget. Default command-hook timeout is 600 s.
  Stop can block with exit code 2.

## 2. Inventory

KEEP, NARROW, RETIRE PROPOSED, NO HOOK NEEDED. "Cost" is wall time measured on the setup machine,
three runs, unless marked NOT MEASURED.

| Mechanism | Owner | Location / scope | Trigger | Purpose | Reads / writes / network | Failure effect | Cost | Duplication | Recommendation |
|---|---|---|---|---|---|---|---|---|---|
| `bd prime --hook-json` | this repo | `.claude/settings.json` (shared project) | SessionStart (all matchers) | task recovery context | reads Beads DB; no writes; no network | session starts without task context | 0.27-0.30 s | overlaps the user-scope `bd prime` (different command text, so not deduplicated) | **KEEP** (travels with every clone) |
| `bd prime` | user | user-scope settings | SessionStart, PreCompact | task recovery in every repository | same | same | 0.29-0.31 s | overlaps the project hook here (different command text, so not deduplicated) | KEEP at user scope; NARROW here by proposal (see 3) |
| A duplicate `bd prime` from a parent-directory settings file | user | outside this repository | SessionStart, PreCompact | same | same | same | 0.29 s | exact duplicate of the user-scope hook | **RETIRED 2026-10-09** (section 5) |
| A user's personal hooks (notifications, metrics, reminders, local guards) | user | user-scope settings | various | personal | not enumerated here | none is a project dependency | NOT MEASURED | none with this repository | out of scope; nothing in this repository may rely on them |
| Enabled plugins | user | user-scope settings | none observed | none for this repository | n/a | n/a | n/a | n/a | NO HOOK NEEDED (no plugin hooks found) |
| Git hooks via `core.hooksPath=.beads/hooks` (5) | this repo, Beads | local Git config, per clone | pre-commit, pre-push, post-merge, post-checkout, prepare-commit-msg | keep the JSONL export and Dolt in step with Git | each runs `bd hooks run`; writes the export; warns when no Dolt remote | a commit or checkout warns; does not run tests | NOT MEASURED | none | KEEP; must stay tiny (no test suites) |
| Codex hooks | this repo | `.codex/` | Codex PreCompact, PostCompact | Beads refresh for Codex sessions | Beads only | Codex only | n/a | none with Claude Code | KEEP (affects Codex only) |
| CI job "Markdown lint and doc index check" | this repo | `.github/workflows/ci.yml` | `pull_request`, `push` to `main`; superseded PR runs cancelled | Markdown, index, agent-definition and secret-scan evidence | checkout (full history); downloads PyYAML and a checksum-verified gitleaks; no secrets | PR shows a failure | before this change 6-9 s per run; after: see the CI timing row below | none | KEEP |
| CI timing after the 2026-10-09 change | this repo | GitHub-hosted `ubuntu-latest` | PR | measurement | n/a | n/a | run 37884524977 on 2026-10-09: about 2 s queue, 11 s from creation to completion; job 8 s (setup 1 s, checkout with full history 1 s, Markdown under 1 s, index under 1 s, agent check 2 s of which most is installing PyYAML, gitleaks download, verify and scan 1 s); cold runner, no cache | n/a | re-measure when steps change |
| Release workflow | this repo | `.github/workflows/release.yml` | `workflow_dispatch` only | manual release | writes tags and releases | none unless run | n/a | none | KEEP manual-only |
| Auto memory | each user | user machine | session start | personal preferences | local file | none | NOT MEASURED | none (no directory exists yet for this repository) | optional; never project policy |
| Governed brain search | estate | MCP connector in the invoking session | on request by `catalyst-intent-knowledge` | institutional retrieval | read only, network | visible UNKNOWN | NOT MEASURED | none | KEEP read-only; no write access for specialists |

## 3. Event matrix (proposed defaults)

| Event | Proposed default | Rationale |
|---|---|---|
| Session start, resume | **today:** two loads (user-scope `bd prime` and the project `bd prime --hook-json`), about 0.6 s together. **Proposed:** one bounded recovery path | no installs, network sync, brain crawl, tests or model calls |
| Compaction | **today:** user-scope `bd prime` runs on PreCompact and the project hook runs again on SessionStart `compact` (empty matcher), so two recovery loads (about 0.6 s together). **Proposed:** keep the project hook on every matcher, including `compact`, because nothing in this repository may rely on a user's personal hooks; accept the duplicate load | do not depend only on a final hook to save work |
| Prompt submission | **no hook** | no automatic retrieval or audit on every message |
| PreToolUse | only small guards not already enforced by permissions | a regex is not a full security boundary; a safety guard's failure blocks the guarded action; optional knowledge lookups never block unrelated work |
| PostToolUse (edits) | **no hook** | no whole-suite runs per edit; changed-file formatting is a later opt-in with recursion and scope guards |
| Subagent completion | **no hook** | specialists return results to the parent; nothing to automate |
| Stop | **no hook** | Stop is not proof of task completion; no auto-audit, commit, push, release or brain update; any future blocking hook needs a re-entry guard (`stop_hook_active`) and a bounded stop rule |
| Session exit | **no project hook** | best-effort local bookkeeping at most; authoritative state is already in Beads and Git |
| Git commit, push | Beads sync hooks only | tiny and fast; bypassing a hook never bypasses the merge guard |
| Release | **no hook** | explicit human-authorized workflow only |

**Specification for the one active project hook** (SessionStart, `bd prime --hook-json`):
event and matcher SessionStart, all; owner this repository; source `.claude/settings.json`; supported
Claude Code 2.1.x and Beads 1.1.x; permission scope read-only on the Beads database; timeout default
600 s, proposed explicit 10 s; output: Beads context JSON, bounded by Beads; side effects none;
failure policy non-blocking (session continues without task context); observability visible as
session-start context; rollback delete the entry from `.claude/settings.json`.

**Latency budgets (proposed targets, pending measurement in a fresh session):** session bootstrap
hooks under 5 s in aggregate (measured: about 0.6 s for the two `bd prime` loads that run today, each timed separately three times); a synchronous guard
under 1 s; pre-commit fast checks under 15 s. Overruns are investigated, not hidden behind longer
timeouts or more hooks.

## 4. Memory and knowledge responsibilities

| Store | Writes allowed | Never |
|---|---|---|
| `000-docs/` | the parent session, in an authorized PR | unapproved text presented as approved |
| Beads | the parent session via the CLI | hand-edited exports; a parallel Markdown task list |
| Auto memory | the user's own sessions, locally | project decisions, backlog mirrors, publication, cross-repository sharing |
| Governed brain | the governed capture and review route, after authorization, with a receipt | raw transcripts; specialist writes; per-session dumps |
| `bd remember` | the parent session, for durable workflow facts about this repository | decisions that belong in `000-docs/` |

## 5. Changes applied outside this repository (2026-10-09)

Both were made on the owner's in-chat instruction to fix the issues found, before the full
documentation instruction arrived. The owner then decided (2026-10-09): keep the hook removal if it
is verified safe and reversible; review the Beads wording before accepting it; keep rollback copies;
no further global changes without approval. Rollback copies are held privately on the maintainer's
machine, not in this repository.

**5.1 Parent-directory settings file (the maintainer's projects folder, `.claude/settings.json`)**

| | Value |
|---|---|
| Original | `{"hooks": {"PreCompact": [{"matcher": "", "hooks": [{"type": "command", "command": "bd prime"}]}], "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "bd prime"}]}]}}` |
| Modified | `{}` |
| Safety check | the user-scope settings still run `bd prime` on SessionStart and PreCompact (verified 2026-10-09), so every repository below that folder still gets Beads context; this repository also has its own SessionStart hook |
| Reversible | yes: restore the private copy; one file, no other references |
| Status | **kept** |

**5.2 Parent-directory instructions file (the same folder's `CLAUDE.md`), two lines**

| | Value |
|---|---|
| Original line 1 | ``Workflow: `bd update <id> --status in_progress` → work → `bd close <id> --reason "evidence"` → `bd sync` `` |
| Modified line 1 | ``Workflow: `bd update <id> --status in_progress` → work → `bd close <id> --reason "evidence"` → `bd export -o .beads/issues.jsonl` (commit the export) and, where a Dolt remote is configured, `bd dolt push`. `bd sync` is the pre-Dolt command; do not use it.`` |
| Original line 2 | `Rules: Never code without marking a task first. Never finish without closing. Always sync.` |
| Modified line 2 | `Rules: Never code without marking a task first. Never finish without closing. Push the Dolt history and the commit only when the current task authorizes a push.` |
| Review | `bd sync` returns "unknown command" in Beads 1.1.x (checked 2026-10-09), so the original instruction could not be followed; the modified text matches the managed Beads block's sync contract |
| Reversible | yes: restore those two lines from the private copy (restore only those lines; the file holds unrelated pending edits) |
| Status | **kept**; uncommitted in that folder's repository |

**5.3 User-level instructions (`~/.claude/CLAUDE.md`), added section "Git branches and worktrees (all repos)"**

| | Value |
|---|---|
| Original | section absent |
| Modified | a short section stating the rules in `009` section 8 for every repository |
| Authority | owner instruction 2026-10-09 to apply the worktree rules "everywhere" |
| Reversible | yes: delete the section; a private copy of the file before the change is kept |
| Status | applied |

## 6. Pending verification (not claimed)

- Hook loading, deduplication and denial behaviour in a fresh session started in this repository.
- Auto memory behaviour in a fresh session.
- Git-hook timings.
- CI timings beyond the documentation job.
