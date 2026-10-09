# AGENTS.md — AI Agent Operations for catalyst-onboarding-v2

## Beads (bd) Issue Tracking

This project uses [beads](https://github.com/steveyegge/beads) for AI-friendly task tracking.
Tasks are stored in `.beads/` and tracked via the `bd` CLI.

## Quick Reference

```bash
bd ready                              # Find available work
bd show <id>                          # View issue details
bd update <id> --status in_progress   # Claim work
bd close <id> -r "Evidence"           # Complete work (or: bd done)
bd note <id> "Progress update"        # Append a note
bd prime                              # LLM-optimized context
bd doctor                             # Health check
```

## Core Workflow

### Session Start

1. Run `/beads` or `bd prime` to recover context
2. Run `bd ready` to see available tasks
3. Pick a task and claim it: `bd update <id> --status in_progress`

### During Work

- Keep notes: `bd note <id> "what I did"`
- Create subtasks: `bd create "Subtask" --parent <id> -p 2`
- Check blockers: `bd blocked`

### Session End (Landing the Plane)

1. Close finished tasks: `bd close <id> -r "Evidence of completion"`
2. Update in-progress tasks with status notes
3. Run quality gates (tests, linters, builds)
4. **PUSH TO REMOTE** (mandatory):

   ```bash
   git push
   git status  # MUST show "up to date with origin"
   ```

5. Hand off context for next session

## Priority Levels

| Priority | Label | Meaning |
|----------|-------|---------|
| P0 | Critical | Blocks everything, fix immediately |
| P1 | High | Important, address this session |
| P2 | Normal | Standard priority |
| P3 | Low | Nice-to-have, address when convenient |

## Critical Rules

- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing — leaves work stranded locally
- NEVER say "ready to push when you are" — YOU must push
- Always close beads when work is done
- Always start sessions with `bd prime` or `/beads`

## Creating Tasks

```bash
# Simple task
bd create "Implement user auth" -t task -p 1 -d "Add JWT-based authentication"

# Bug report
bd create "Login fails on mobile" -t bug -p 0 -d "Steps to reproduce..."

# Feature request
bd create "Add export to CSV" -t feature -p 2

# With dependencies
bd create "Write tests" --parent <epic-id> -p 2
```

## Advanced Commands

```bash
bd list --status in_progress    # What am I working on?
bd statuses                     # List valid statuses
bd search "auth"                # Search by text
bd stale                        # Find stale issues
bd dep add <child> <parent>     # Add dependency
bd graph <id>                   # View dependency graph
```

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
