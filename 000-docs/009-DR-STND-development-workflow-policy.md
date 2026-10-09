# Development workflow policy: instructions, hooks, Beads, memory, CI and Learn routing

**Version:** 0.1.0 (preliminary, subject to owner review)
**Date:** 2026-10-09
**Scope:** how development work on this repository is instructed, tracked, remembered, checked and
routed. Documentation maintenance only: it changes no hook, setting, workflow, service or route.
Every configuration change below is a **proposal** for separate approval.

> **Status: PRELIMINARY, subject to review.** Written from what was visible of the owner's
> 2026-10-08 instruction; the remainder of that instruction was not available. Sections that depend
> on the missing part are marked **pending**.

## 1. The principle

Six mechanisms, six jobs, one source of truth each. None of them restates or re-runs another.

| Mechanism | Its one job | It is not |
|---|---|---|
| Instruction files (`CLAUDE.md`, `AGENTS.md`) | explain the rules for working here, and point to the documents that hold them | a decision record or a task list |
| Beads (`bd`) | track work: what is open, claimed, blocked, done, with evidence on close | a design document or a memory store for project decisions |
| Approved repository documents (`000-docs/`) | record project decisions, requirements and designs once approved | a scratchpad; a seeded template is not approved |
| Bob's Big Brain / Intent OS | supply scoped institutional knowledge on request, as sanitized summaries | a place to copy into this public repository |
| Hooks (Claude Code, Git, Codex) | perform small, bounded, fast actions at session or Git events | a test runner, a workflow engine, or the product's background jobs |
| CI (GitHub Actions) | produce reproducible check evidence on every pull request | a second copy of every local check, or a deployment trigger |

**Precedence when they disagree:** a current owner instruction in the session (for that task), then
an approved `000-docs/` decision, then the Agent Operating Charter
(`007-DR-STND-agent-operating-charter.md`) for subagents, then this policy, then instruction-file
prose, then generated or templated text (including the managed Beads blocks).

## 2. Observed state (2026-10-09, read-only inspection)

Recorded so changes can be argued from evidence. Values and personal paths are omitted.

| Surface | What is in force for a session in this repository |
|---|---|
| Claude Code | 2.1.x |
| Beads | 1.1.x, embedded Dolt, prefix `catalyst-v2`, auto-commit on, five Git hooks via `core.hooksPath=.beads/hooks` (each runs `bd hooks run`), merge driver for `issues.jsonl`, sync branch `beads-sync`, Dolt remote on this repository (`refs/dolt/data`) |
| Instruction files loaded | the user's global file, two parent-directory files (home and the projects umbrella), and this repository's `CLAUDE.md`; `AGENTS.md` at the same three levels for agents that read it |
| SessionStart hooks | `bd prime` from the user's global settings, `bd prime` from the parent umbrella's project settings, and `bd prime --hook-json` from this repository's `.claude/settings.json`: **three Beads context loads per session start** |
| PreCompact hooks | `bd prime` from global settings and again from the parent umbrella: **two** |
| Other global hooks | notification, edit tracking, token counting, prompt counting and a commit/PR-standard reminder; none runs tests or touches this repository's files |
| Codex | `.codex/` enables Beads pre/post-compact hooks for Codex sessions only; no Claude Code effect |
| Plugins enabled globally | two (one CLAUDE.md maintenance plugin, one vendor automation plugin); neither adds hooks observed here |
| Native auto memory | no project memory directory exists for this repository |
| CI | one workflow, `ci.yml`: Markdown lint plus an index-completeness check on push to `main` and on pull requests; `release.yml` is manual-only (`workflow_dispatch`) |
| Installed project skills | `/audit-tests` 7.2.0, `/implement-tests` 1.2.0, `/agent-creator` 1.1.0, `/validate-agent` 1.0.0, `/doc-filing` 4.4.0, `/beads` 4.5.0 |
| Managed (enterprise) settings | none readable on this machine |

**Duplications and conflicts found:**

1. Beads context loads three times at session start and twice at compaction (global, umbrella, project).
2. `AGENTS.md` (repo-dress template) says work is not complete until `git push` succeeds and to
   never stop before pushing; the managed Beads block and the current owner rules say pushes need
   explicit authority. Two instructions, opposite answers.
3. The parent umbrella's `CLAUDE.md` still tells agents to run `bd sync`, which the managed Beads
   block in this repository describes differently (Dolt remote push, JSONL as a passive export).
4. Doc numbers 009 to 011 were reported as used by earlier drafts; none landed on `main` or in an
   open pull request, so `009` is allocated here and `010`, `011` remain free.

## 3. Rules

### 3.1 Instructions

- `CLAUDE.md` and `AGENTS.md` in this repository carry **rules and pointers only**. Decisions live in
  `000-docs/`; tasks live in Beads.
- The **write and push policy** is the one in `AGENTS.md` "Specialist subagents and write policy":
  the current authorized task controls writes; subagents cannot publish; the parent session publishes
  only the explicitly authorized change set. Any generic "always push" text is subordinate.
- Managed blocks (`<!-- BEGIN BEADS ... -->`) are changed only by the tool that owns them
  (`bd setup`), never by hand.

### 3.2 Beads

- One bead per bounded task, under an epic; plain-English titles; close with evidence.
- `.beads/issues.jsonl` is an export: commit it, never hand-edit it.
- Persistent workflow knowledge for this repository uses `bd remember`, not ad hoc memory files.
- Bead identifiers are command handles; documents and pull requests cite bead titles.

### 3.3 Memory

- Native Claude Code auto memory may hold **personal working preferences** only. Project decisions
  never live there.
- Institutional knowledge comes from Bob's Big Brain through the `catalyst-intent-knowledge`
  specialist, as cited, sanitized summaries. Brain content, private paths and transcripts are never
  copied into this public repository.

### 3.4 Hooks

- A hook does one small thing in seconds and never blocks on the network for long.
- **Product behaviour is never a development hook.** The application's inbox polling, reminders,
  signing checks and provisioning are durable service jobs in the application's single PostgreSQL
  job system. They never depend on a Claude Code hook or on a terminal session someone leaves open.
- Hooks do not run test suites; local checks and CI do.

### 3.5 Local checks and CI

- **One check set, two places.** The command a contributor runs before pushing is the same one CI
  runs. Today that is:

  ```bash
  npx --yes markdownlint-cli2@0.17.2 "**/*.md"
  for f in $(find 000-docs -name '*.md' ! -name '000-INDEX.md'); do grep -q "$(basename "$f")" 000-docs/000-INDEX.md || echo "missing from index: $f"; done
  ```

- CI stays one job until there is code. When code arrives, each new check is added once, as a named
  CI job with a local equivalent, and its gate status is recorded in the merge guard.
- CI never deploys and never releases. The release workflow runs only by hand.
- A pull request merges only through the estate merge guard (`safe-merge`), which requires every
  required check green on the exact head.

### 3.6 Learn and Django routing

- `learn.intentsolutions.io` does **not** move into Django. The existing learning application keeps
  serving its pages. The reverse proxy routes only designated onboarding paths to the Catalyst v2
  Django service, which runs under a production WSGI/ASGI server, never Django's development server.
  The learning application and Catalyst may share a host while staying separate processes and
  containers with separate data.
- A domain or subdomain does not decide which application serves a path; the proxy's path routing
  does (Caddy `handle` blocks).
- **Current routing is not verified.** Estate documents disagree: one describes the whole learn
  host proxied to the learning application, another describes an onboarding route set
  (`/request-access`, `/setup/*`, `/signing/return`) carved out for the first-generation onboarding
  service. Before any v2 route change, the route ownership must be read from the live proxy
  configuration by someone authorized, recorded here, and reviewed by `catalyst-security-privacy`
  (cookie scope across applications on one host, CSRF origin, which app sees which paths,
  admin exposure).
- References: Caddy `handle` directive, https://caddyserver.com/docs/caddyfile/directives/handle ;
  Django 5.2 deployment, https://docs.djangoproject.com/en/5.2/howto/deployment/ .

## 4. Proposals (not applied; each needs separate approval)

| # | Proposal | Why | Owner action |
|---|---|---|---|
| P1 | Keep this repository's `SessionStart: bd prime --hook-json` and stop the duplicate loads by removing `bd prime` from the parent umbrella's `.claude/settings.json` (SessionStart and PreCompact) | the project hook travels with the repository for every clone; the umbrella one only duplicates the global hook | edit outside this repository |
| P2 | Replace the repo-dress "Critical Rules" push text in `AGENTS.md` with a pointer to the write policy | removes the contradiction in section 2, item 2 | **applied in this documentation change** (repository text only) |
| P3 | Update the umbrella `CLAUDE.md` Beads paragraph (`bd sync`) to the current Dolt-remote wording | removes conflict 3 | edit outside this repository |
| P4 | Add a `Makefile` or script target `check-docs` that wraps the two commands in 3.5, and make CI call it | one command, one place | approve when code tooling is introduced |
| P5 | Record the verified learn proxy route table in this document | closes the routing unknown | read-only read of the live proxy by an authorized person |

## 5. Pending

The rest of the owner's instruction (phases after Phase A) was not available when this was written.
Any deliverables it names beyond this document are **not done** and are not claimed.
