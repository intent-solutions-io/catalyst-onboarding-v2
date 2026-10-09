# Agent Registry and Validation Report: Catalyst v2 specialist team

**Version:** 0.1.0 (preliminary, subject to owner review)
**Date:** 2026-10-09
**Scope:** the eleven subagent definitions under `.claude/agents/`, their shared charter
(`007-DR-STND-agent-operating-charter.md`), how they were built and validated, and what was not verified.
**Authorization:** this setup creates definitions and documentation only. It does not authorize application development, deployment, provider access or any production change.

> **Status: PRELIMINARY, subject to review.** Nothing here is an approved specification. Every
> specialist is read-only and advisory at this stage.

## 1. How the definitions were built

| Item | Value |
|---|---|
| Creator skill | installed `/agent-creator` v1.1.0 (author Jeremy Longshore; standalone-project mode, target `.claude/agents/`), structure per its Step 3 and Step 5 (role, responsibilities, process, quality standards, output format, edge cases). The private source skill was not copied into this repository. |
| Validator skill | installed `/validate-agent` v1.0.0, wrapping the Intent Solutions validator `validate-skills-schema.py` v7.0, schema 4.1.0, kernel-strict agent gate (`@intentsolutions/core` schemas vendored 2026-06-12) |
| Runtime | Claude Code 2.1.x on the setup machine; `claude plugin validate .claude/agents` |
| Official docs consulted | code.claude.com `sub-agents` (frontmatter reference, project subagents, nested subagents) and `model-config` (model aliases, subagent model), read 2026-10-09 |
| Doc filing | `/doc-filing` v4.4 numbering; `007` and `008` were the next free numbers in `000-INDEX.md` |
| Tracking | one bead, "Create and validate the eleven Catalyst v2 specialist subagents with their operating charter and registry", child of the planning epic |

### 1.1 Field discrepancies between runtime, creator and validator (recorded, not resolved by weakening anything)

| Field | Claude Code 2.1.295 runtime (official docs) | Intent Solutions validator (14 required, standalone) | What the definitions do |
|---|---|---|---|
| `name`, `description` | required | required | present |
| `tools`, `disallowedTools`, `model`, `permissionMode`, `skills`, `background`, `hooks`, `mcpServers` | optional, interpreted | required (`disallowedTools` must be an array) | present on every agent |
| `version`, `author`, `tags`, `color` | `color` interpreted; `version`, `author`, `tags` **not interpreted** by the runtime ("silently ignores unrecognized fields") | required | present; treated as metadata for the validator and registry only |
| `omitClaudeMd`, `experimental` | interpreted (new) | not in validator or creator | not used |
| `permissionMode` values | `default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions`, `plan`, `manual` | same list | `default` |
| `model` values | `sonnet`, `opus`, `haiku`, `fable`, full id, `inherit` | same | `sonnet` |
| Nested spawning | allowed by default up to three layers; disable by omitting `Agent` from `tools` or listing it in `disallowedTools`; the creator's reference snapshot still says "subagents cannot spawn other subagents" (stale) | not checked | `Agent` and `Task` excluded from every allowlist and listed in `disallowedTools` |
| `effort`, `maxTurns`, `memory`, `isolation`, `initialPrompt` | optional | "upgrade levers", carried as a commented block | commented block present, none set |

No installed skill was modified. The creator skill's spec snapshot predates the runtime's nested-spawning change; that is reported here for the skill maintainer.

## 2. Roster

All eleven: `model: sonnet`, `permissionMode: default`, `background: false`, `skills: []`, `hooks: {}`, `mcpServers: {}`, `disallowedTools: [Agent, Task, Write, Edit, NotebookEdit, Bash, Skill]`, version `0.1.0`. No agent inherits the parent's tool set; every definition pins `model: sonnet` (resolved model id unverified, section 3). No agent may spawn another. Only the main session writes.

| Agent | Purpose (one line) | Tools (allowlist) | Trigger phrases | Depends on / hands to | Primary official references |
|---|---|---|---|---|---|
| `catalyst-intent-knowledge` | authorized Intent Solutions context; current decisions versus history | Read, Glob, Grep, `mcp__governed-brain__brain_search` | "what did we decide about", "is there an estate standard for", "knowledge check" | hands to the specialist for the area | charter sections 3 and 4 |
| `catalyst-legacy-analyst` | narrow questions on first-generation behaviour and contracts, only when assigned | Read, Glob, Grep | "legacy question", "how did v1 handle" | supplies compatibility facts to `catalyst-django-data` | charter section 3 (Legacy) |
| `catalyst-django-architect` | coherent Django-native application design | Read, Glob, Grep, WebFetch | "Django design review", "is this idiomatic Django" | reviews proposals from data, operator, workflow | Django 5.2 applications, transactions, forms, middleware, auth, settings, security |
| `catalyst-django-data` | progressive dossier, constraints, migrations, adoption evidence | Read, Glob, Grep, WebFetch | "data model review", "migration plan", "is this schema equivalent" | consumes legacy facts; supplies schema to workflow and operator | Django 5.2 constraints, indexes, migrations, `RunSQL`, `select_for_update`; PostgreSQL 16 locking clause, triggers |
| `catalyst-django-operator` | staff experience on admin and focused views | Read, Glob, Grep, WebFetch | "operator UI", "admin design" | consumes data design; reviewed by security | Django 5.2 admin, actions, `LogEntry`, permissions, class-based views |
| `catalyst-workflow-correspondence` | durable jobs and the full communication loop | Read, Glob, Grep, WebFetch | "job design", "reply handling", "reminder race" | schema from data; carries documents' and evaluation's messages; monitored by release | PostgreSQL 16 locking clause, advisory locks; Django `on_commit`; RFC 9051, RFC 5322; Python `email`, `imaplib` |
| `catalyst-minimax-evaluation` | PydanticAI/MiniMax assessment layer | Read, Glob, Grep, WebFetch | "assessment design", "rubric", "prompt injection case" | delivery via workflow; reviewed by security | PydanticAI OpenAI model and compatible APIs, retries; MiniMax "Model Invocation" |
| `catalyst-documenso-documents` | agreement lifecycle on the existing Documenso | Read, Glob, Grep, WebFetch | "agreement lifecycle", "is this envelope complete" | mail via workflow; custody reviewed by security | Documenso developers index, API v2, envelopes migration, webhooks, self-hosting |
| `catalyst-security-privacy` | independent security and privacy review | Read, Glob, Grep, WebFetch | "security review", "privacy review", "is this safe to publish" | reviews every other specialist | Django 5.2 security, CSRF, passwords, logging; OWASP Top 10, ASVS, LLM Top 10 |
| `catalyst-release-operations` | environments, deployment evidence, monitoring, restore, cutover | Read, Glob, Grep, WebFetch | "release plan", "cutover", "restore drill" | monitors workflow; reviewed by security | PostgreSQL 16 backup, `pg_dump`; Django deployment checklist, `check --deploy`; Compose spec |
| `catalyst-independent-qa` | challenge specifications, verify traceability and claims | Read, Glob, Grep | "QA challenge", "verify this claim", "is this traceable" | reviews everyone; never certifies own work | charter sections 5 and 6; pytest skip/xfail; Django testing |

**Deliberately excluded tools:** Write, Edit, NotebookEdit, Bash, Agent, Task, Skill, every provider or deployment tool, and every MCP tool except the governed-brain search on the knowledge agent.

**Reference caveats recorded in the definitions:** Django links are to the 5.2 documentation line pending the approved runtime version; Documenso links must be checked against the installed version (the public API today is v2, with envelopes replacing documents and templates); PydanticAI structured-output, usage-limit and testing pages are to be pinned when the library version is approved; MiniMax structured output and tool calling were not documented on the page read; no official MXroute URL was confirmed, so the workflow agent marks it "to be verified".

## 3. Model policy and observed resolution

- Definitions: `model: sonnet` on all eleven. Haiku is permitted only for bounded mechanical sub-tasks when the main session passes it explicitly; Opus is reserved for one independent final review; Fable is not used for generation or validation.
- Official alias table (model-config, read 2026-10-09): on the Anthropic API `sonnet` resolves to Sonnet 5.5, `opus` to Opus 5.5, `haiku` to Haiku 5.5. `CLAUDE_CODE_SUBAGENT_MODEL` and `availableModels` can override or fall back; neither is set in this repository.
- **Observed resolution: unverified.** The Agent tool accepted `model: sonnet` for the smoke tests but did not expose the resolved model id in its results. Record as unverified until a run surfaces it.
- Concurrency during setup: at most two specialists at once (observed: two smoke tests in parallel, then one, then one reviewer).

## 4. Validation results (observed)

| Check | Result (self-reported by the setup session; re-run the command to confirm) |
|---|---|
| IS validator `validate-skills-schema.py --agents-only`, each of 11 files | exit 0, 0 errors, 0 warnings on all eleven after one fix (the knowledge agent's body now names `mcp__governed-brain__brain_search` in full; before the fix the validator warned "declares MCP tool ... but the body never references it") |
| IS validator `--fail-on-warn` (strict) | all eleven pass |
| Pre-flight shape check (14 required fields present, no banned field, `disallowedTools` is an array, `color` in enum) | all eleven pass |
| Body-versus-allowlist consistency (validate-agent Step 5) | ten agents declare no MCP tool and reference none; the knowledge agent declares one and references it in full. No BLOCK. |
| `claude plugin validate .claude/agents` (Claude Code 2.1.295) | "Validation passed" |
| `markdownlint-cli2@0.17.2` (the CI action's version) over all Markdown | 0 errors, 30 files |

### 4.1 How to reproduce

```bash
for f in .claude/agents/*.md; do python3 <path-to>/validate-skills-schema.py --agents-only --fail-on-warn "$f"; done
claude plugin validate .claude/agents
npx --yes markdownlint-cli2@0.17.2 "**/*.md"
```

## 5. Discovery

Project subagents are discovered by Claude Code walking up from the working directory and scanning `.claude/agents/`. **Not verified from this setup session**, which was started in a different repository: the Agent tool reported "Agent type 'catalyst-workflow-correspondence' not found" when asked for the new type, which is the expected result for a session rooted elsewhere, not a defect in the files. Per the official docs, a session started in this repository picks the files up within seconds, except that **the first file in a new `agents` directory requires a restart**; since this commit creates that directory, the first session after checkout must be restarted (or started fresh) before the eleven appear. User action required; loading is therefore reported as **not yet verified**.

## 6. Smoke tests (read-only, synthetic, Sonnet; contract-text simulation, not runtime enforcement)

Because discovery could not be exercised from this session, each test ran a general-purpose Sonnet agent instructed to read the definition file and the charter and follow them, restricted by instruction to Read, Glob and Grep inside this repository. This exercises the contract text, not the runtime's tool enforcement. Each agent reported reading exactly three files: its definition, the charter and `000-INDEX.md` (the index read is required by every definition).

| Test | Scenario (synthetic) | Observed |
|---|---|---|
| Workflow: reply arrives while a reminder is pending | reply at 08:59:50, reminder claim at 09:00:00 | Returned the result format in order. Proposed one collector transaction (insert inbound with unique folder/UIDVALIDITY/UID key, associate by In-Reply-To, lock the question row `FOR UPDATE`, mark answered, cancel the reminder by its action key, write the event, enqueue processing, advance the cursor last) and a reminder claim that locks the question row in the same lock order and re-checks state before any outbound row. Named the collector-lag race and proposed a freshness check. Marked the communications policy, schema and MXroute behaviour UNKNOWN; listed three reserved decisions. Stated it fetched no reference pages. No write, no provider contact. |
| Documenso: applicant signed, approver not started | envelope with two required participants, request to issue the next agreement | Refused issuance: "every required participant complete" gate not met. Distinguished invitation, link opened and one signature from completion. Proposed recording the observation with provenance, a unique (envelope, recipient, status) constraint making duplicate observations no-ops, an operator "waiting on approver" view with no timer-based release, and a fresh provider re-read at the moment of action. Marked the installed version, inventory, roles and order UNKNOWN; sent inventory and ordering to owner and counsel as required decisions. No write, no provider contact. |
| Security: request to publish private source, a real applicant record and an NDA clause | contributor argues it is needed to explain the data model | Rejected as proposed. Rated the source excerpt with private path, the real applicant record and the agreement clause as blocking under charter section 3, the legacy excerpt as "code to copy", the path as reconnaissance help. Offered a sanitized alternative: behaviour description via the legacy analyst, a clearly synthetic record on `example.test`, a one-sentence description of the clause instead of its text, and a structural data-model summary. Marked whether anything had already been pushed as UNKNOWN; sent agreement wording to owner and counsel. No write, no provider contact. |

### 6.1 Security smoke test result

Observed as recorded in the table above. The agent read exactly the definition, the charter and the index, returned every heading in order, and separated enforced controls (the charter rule) from the contributor's stated intent.

## 7. Independent review

One Opus review (reviewer-shaped agent, read-only, not the author) ran over the eleven definitions, the charter and this report on 2026-10-09. Verdict: **accept with named fixes.** Findings and disposition:

| # | Finding | Disposition |
|---|---|---|
| 1 | Ten definitions handled missing inputs but not conflicting inputs | fixed: every Inputs section now applies charter section 4 and records the conflict |
| 2 | No per-agent governing-documents and precedence section | fixed: section added to all eleven |
| 3 | Knowledge and legacy agents had no external reference | fixed: each states that no vendor documentation applies and links the Claude Code subagent reference |
| 4 | Registry filed before the review it reports | fixed by this section |
| 5 | Inconsistent statement of which files the smoke tests read | fixed: three files, including the index |
| 6 | Haiku clause did not say how a Haiku run happens | fixed in the charter: explicit model override by the main session |
| 7 | Precedence row 1 versus charter change control | fixed: an in-session owner instruction governs one task and does not amend the charter |
| 8 | Knowledge agent depends on an MCP server the repository does not configure | accepted as designed: the tool name is a real connector, not an invention; the agent reports UNKNOWN when it is absent; `mcpServers: {}` is deliberate (no credentials in a public repo) |
| 9 | Legacy analyst could be pointed at the private repository | fixed: packets only; all output must be publishable |
| 10 | WebFetch unrestricted | fixed: a "Fetching references" rule in every WebFetch agent |
| 11 | Evidence tags defined per agent, ambiguously | fixed: defined once in charter section 6 |
| 12 | Internal toolchain detail in this report | generalised (runtime build and machine) |
| 13 | Bead identifiers quoted | fixed: title only |
| 14 | Author email in frontmatter | intended: the organisation's public contact address, required by the validator |
| 15 | "No agent inherits model" overstated | fixed wording |
| 16 | Smoke tests simulate the contract text, not runtime enforcement | fixed heading and caveat |
| 17 | Validator passes self-reported | marked as such with the reproduction commands |

After the fixes every definition was re-validated (section 4). The reviewer did not see the fixed files; a second pass is left to the owner's PR review.

## 8. Unavailable capabilities and unresolved conflicts

1. Discovery and runtime tool enforcement not verified from this session (section 5). Needs a session started in this repository after restart.
2. Resolved model ids not observable from the Agent tool result (section 3).
3. The creator skill's reference snapshot is stale on nested spawning; the definitions follow the live docs (exclude `Agent`).
4. The validator requires `version`, `author`, `tags`, which the runtime ignores; kept for the validator, harmless at runtime.
5. Official MXroute documentation URL not confirmed; MiniMax structured-output and tool-calling pages not confirmed; PydanticAI output, usage-limit and testing pages not pinned pending version approval.
6. Private access for the knowledge agent exists only through the governed-brain MCP tool when the invoking session has that server; otherwise the agent reports UNKNOWN. The legacy analyst has no connector and works only from evidence packets or an assigned read-only location.
7. Write policy resolved: the current authorized task controls writes; subagents cannot publish; the parent publishes only the explicitly authorized change set (this setup's files and pointer edits). The managed Beads blocks in `CLAUDE.md` and `AGENTS.md` are preserved unchanged; the `AGENTS.md` template's "always push" rule is subordinate to this policy and is noted, not rewritten.

## 9. Documents created by this setup

- `000-docs/007-DR-STND-agent-operating-charter.md`
- `000-docs/008-RA-REPT-agent-registry-and-validation-report.md` (this file)
- `.claude/agents/catalyst-*.md` (eleven files)
- pointer edits: `000-docs/000-INDEX.md`, `CLAUDE.md`, `AGENTS.md`

No application code, database migration, runtime agent, deployment script or integration was created. No applicant, provider or production system was contacted.
