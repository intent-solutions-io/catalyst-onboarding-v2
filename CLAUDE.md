# CLAUDE.md

Entry point for Claude Code in **catalyst-onboarding-v2**, the documentation-first, Django-native
Solution Catalyst onboarding platform for Intent Solutions. Planning phase: there is no application
code yet. Repository: https://github.com/intent-solutions-io/catalyst-onboarding-v2 (public).

## Read first

| Need | Document |
|---|---|
| What we are building, who decides, open policies, phased plan | `000-docs/011-PP-PLAN-master-blueprint.md` (start here; links the PRD `002`, architecture `003`, journey `004`, first slice `005`) |
| How work is authorized, published and checked | `000-docs/009-DR-STND-developer-workflow-and-quality-contract.md` |
| What hooks run, what they cost, where memory lives | `000-docs/010-DR-REFF-hook-and-memory-responsibility-register.md` |
| Rules for the eleven specialist subagents | `000-docs/007-DR-STND-agent-operating-charter.md`, roster in `008` |
| Everything filed | `000-docs/000-INDEX.md` (all planning documents are proposed, not approved) |

## Boundaries

- Django application; PostgreSQL authoritative; one PostgreSQL-backed job system (no Temporal);
  MiniMax through PydanticAI; existing Documenso and MXroute; Django-based staff interface; Twenty
  deferred. **Proposed, not configured:** `learn.intentsolutions.io` stays on the existing LMS and only
  assigned onboarding paths route to Django; today's live routing was verified read-only on 2026-10-09
  (`003`, "Learn and Django routing").
- Public repository: no applicant data, agreement text, credentials, private paths, brain content or
  transcripts.
- Product jobs (inbox polling, reminders, signing checks) are application jobs, never Claude Code
  hooks.

## Working agreement (canonical text: `009` section 2)

The current authorized task sets scope and what may be published. Preserve unrelated work. Commit
and push only the authorized change set; pull requests are drafts unless told otherwise; subagents
never publish. No force-push, no merge-guard bypass, no production, provider, DNS, proxy or secret
change without separate authorization. Commit approval, architecture approval and deployment approval
are separate acts. Report PASS, FAIL, SKIPPED, NOT RUN and BLOCKED separately.

Branches and worktrees (`009` section 8): one task, one branch, one PR; work in this checkout; an
extra worktree only for a recorded concurrency need; check existing branches, worktrees and open PRs
before branching; retire only verified-obsolete branches after merge; never delete unique work.

## Canonical commands

```bash
bd ready                                   # open work (bd prime already ran at session start)
npx --yes markdownlint-cli2@0.23.2 "**/*.md" # Markdown check, same version as CI (009 section 5.1)
claude plugin validate .claude/agents      # agent definitions (plus the IS validator, see 009)
```

Which checks apply: a docs-only change runs the Markdown and index checks (CI) plus, if
`.claude/agents/` changed, the agent validators (local only today). A change to code, tests,
dependencies, migrations, CI, hooks or test selection is **not** docs-only; its lanes are in `009`
section 5.3 (proposed; no code exists yet). Merges go through the estate merge guard (registration
recorded in `009` section 5.5; not verifiable from this repository).

The managed Beads block below says not to use `MEMORY.md` files: that means no `MEMORY.md` in this
repository. Claude Code's own auto memory lives outside the repository and is a personal convenience
only (`009` section 1).

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
