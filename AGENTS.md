# AGENTS.md

Entry point for Codex and other coding agents. Claude Code uses `CLAUDE.md`.

Catalyst v2 is the Django-native Solution Catalyst onboarding platform. This repository is public.
`AGENTS.md` and `CLAUDE.md` are separate entry points; keep their shared guidance aligned and use the
canonical documents below for detailed requirements and decisions.

## Read first

| Need | Document |
|---|---|
| Build contract, authority, policies and phases | `000-docs/011-PP-PLAN-master-blueprint.md` (links the PRD, architecture, journey and first-slice specification) |
| Working agreement, publication policy and checks | `000-docs/009-DR-STND-developer-workflow-and-quality-contract.md` (section 2 is canonical) |
| Hooks and memory responsibilities | `000-docs/010-DR-REFF-hook-and-memory-responsibility-register.md` |
| Release and host evidence | `000-docs/032-OD-CHNG-release-control-and-host-requests.md` |
| Launch decisions and their scope | `000-docs/033-AT-DECR-council-record-launch-decision-backlog-2026-10-28.md` |
| First-generation parity work | `000-docs/034-RA-ANLY-first-generation-to-v2-drop-in-parity-inventory.md` |
| Specialist rules and roster | `000-docs/007-DR-STND-agent-operating-charter.md`, `000-docs/008-RA-REPT-agent-registry-and-validation-report.md` |
| Filed documents | `000-docs/000-INDEX.md` |

Read dates and evidence status: older planning banners are snapshots, and later recorded owner
decisions may supersede them. Do not infer current deployment state, enabled providers or permission
from an entry-point summary. Task state lives in Beads; inspect the relevant bead and current code.
A proposal is not an approval, and a synthetic gate pass is not authorization for live use.

## Boundaries

- Django with PostgreSQL as the authoritative database; no SQLite substitute for database tests.
  Background work uses one PostgreSQL-backed job system. Staff use Django admin and focused views.
- MXroute, Documenso and MiniMax through PydanticAI are external integrations. Use local fakes or
  test models for ordinary development; live provider actions need separate authorization.
- The first-generation service remains live. Preserve one writer per case, mailbox, envelope,
  callback and timer. Describe legacy behaviour from sanitized evidence; do not copy legacy code
  or read the private implementation without its separately authorized task.
- No applicant data, agreement text, credentials, private paths, brain content or transcripts in
  this public repository, PRs or Beads history.
- Product jobs (inbox polling, reminders, signing checks) are application jobs, never agent hooks.
  Preserve guards, feature switches and human decision boundaries unless the task authorizes a change.

## Working agreement (canonical: `009` section 2)

The current authorized task sets scope and what may be published. Preserve unrelated work. Commit
and push only the authorized change set; pull requests are drafts unless told otherwise; subagents
never publish. Apply an explicit active Git authority profile before the managed Beads default.
No force-push, history rewrite, merge-guard bypass, production, provider, DNS, proxy or secret change
without separate authorization. Commit approval, architecture approval and deployment approval are
separate acts. Report PASS, FAIL, SKIPPED, NOT RUN and BLOCKED separately.

Branches and worktrees (`009` section 8): one task, one branch, one PR; inspect existing branches,
worktrees and open PRs before branching. Work in this checkout; an extra worktree needs a recorded
concurrency need. Do not create a worktree per agent or delete unique work.

## Repository map

| Path | Purpose |
|---|---|
| `accounts/`, `applications/` | Users, intake, invitations, verification and application dossier |
| `workflow/` | Pending-action ledger and background worker |
| `correspondence/` | Inbound/outbound mail, replies and reminders |
| `assessments/` | Evidence, bounded assessment and qualification decisions |
| `agreements/` | Documenso integration, signing, custody and staff screens |
| `provisioning/` | Mailbox provisioning, credential setup, activation and closure |
| `config/` | Settings, guards, database roles, health and recovery |
| `tests/` | Synthetic runtime suite; `acceptance.py` maps acceptance cases to tests |
| `scripts/`, `deploy/` | Check scripts, release tooling and deployment definitions; live operations require authorization |
| `requirements/`, `pyproject.toml`, `compose.yaml` | Hash-locked dependencies, Python tooling and isolated test containers |
| `000-docs/` | Indexed specifications, decisions, evidence and after-action reports |

## Canonical commands

Run from the repository root:

```bash
bd ready                              # available work; inspect the relevant bead before claiming
scripts/check-docs.sh                 # Markdown lint and document index check
scripts/test.sh                       # full suite in digest-pinned Python and PostgreSQL containers
PYTEST_ARGS="-v tests/test_intake.py" scripts/test.sh  # targeted feedback, not a gate
ruff check .                          # use the version locked in requirements/lint.txt
```

Docker is required for runtime checks. `scripts/test.sh` creates an isolated Compose project and
cleans up its own resources. Do not substitute a production database or real provider credentials.
For branch-based test selection, use `scripts/select_tests.py` as described in `009` section 5.3;
it is a selection hint, never a replacement for the full merge gate.

For documentation-only edits, run Markdown and index checks, verify referenced paths and review the
diff for sensitive content. Code, tests, dependencies, migrations, CI, hooks and test-selection
changes use the runtime lanes in `009` section 5.3. CI also runs Python lint and the dependency audit;
the audit command is in `009` section 5.1. If `.claude/agents/` changes, run
`claude plugin validate .claude/agents` and the Intent Solutions agent validator described there.

## Task tracking and memory

Use the Beads CLI (`bd`) and the project skill `.agents/skills/beads/SKILL.md`. Inspect existing
work, create or claim a bounded bead before implementation, and record validation and handoff evidence.
Run `bd prime` when context is missing or stale. Never hand-edit `.beads/issues.jsonl`.

Use `bd remember` for persistent project knowledge; do not create Markdown task lists or repository
`MEMORY.md` files. Personal auto memory outside the repository is a convenience, not project policy
(`009` section 1). Managed Beads guidance below remains subordinate to active user and repository
authority.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:970c3bf2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:

   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   bd dolt push
   git push
   git status
   ```

5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**

- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->
