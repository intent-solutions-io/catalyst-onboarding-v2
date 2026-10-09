# 000-docs index

Document filing standard: `NNN-CC-ABCD-description.md`, flat by default, chronological by number.
Every document in this directory is **preliminary and subject to review** until the owner accepts it.

| Document | Purpose | Status |
|---|---|---|
| [000-AA-TMPL-after-action-report.md](000-AA-TMPL-after-action-report.md) | After-action report template, snapshot of the `/doc-filing` canonical v1.0.0 (full and lightweight lanes) | Canonical copy lives in the skill; refresh on version change |
| [001-PP-PLAN-business-case.md](001-PP-PLAN-business-case.md) | Business case (template, preliminary) | Seeded 2026-10-09; subject to review |
| [002-PP-PROD-product-requirements.md](002-PP-PROD-product-requirements.md) | Product requirements (template, preliminary) | Seeded 2026-10-09; subject to review |
| [003-AT-ARCH-architecture.md](003-AT-ARCH-architecture.md) | Architecture (template, preliminary; adds verified current Learn routing, proposed v2 routing and the staff-interface access design) | Seeded 2026-10-09; subject to review |
| [004-UC-USER-user-journey.md](004-UC-USER-user-journey.md) | User journey (template, preliminary) | Seeded 2026-10-09; subject to review |
| [005-AT-DSGN-technical-spec.md](005-AT-DSGN-technical-spec.md) | Technical spec (template, preliminary) | Seeded 2026-10-09; subject to review |
| [006-LS-STAT-status.md](006-LS-STAT-status.md) | Status (template, preliminary) | Seeded 2026-10-09; subject to review |
| [007-DR-STND-agent-operating-charter.md](007-DR-STND-agent-operating-charter.md) | Agent Operating Charter: shared rules, boundaries, precedence and result format for the specialist subagents | Proposed 2026-10-09; subject to review |
| [008-RA-REPT-agent-registry-and-validation-report.md](008-RA-REPT-agent-registry-and-validation-report.md) | Agent registry and validation report: roster, models, access boundaries, references, validation and smoke-test results | Proposed 2026-10-09; subject to review |
| [009-DR-STND-developer-workflow-and-quality-contract.md](009-DR-STND-developer-workflow-and-quality-contract.md) | Developer Workflow and Quality Contract: one job per system, working agreement, Beads and brain discipline, checks and CI, branch and worktree policy, owner decisions of 2026-10-09 | Proposed 2026-10-09; subject to review |
| [010-DR-REFF-hook-and-memory-responsibility-register.md](010-DR-REFF-hook-and-memory-responsibility-register.md) | Hook and Memory Responsibility Register: observed hooks, costs, event matrix, memory stores, changes applied outside the repo | Proposed 2026-10-09; subject to review |

Next free number: `011`.

**After-action reports** go in `000-aars/` inside this directory (filing standard v4.5 §3.1.3): global
`NNN`, `NNN-AA-AACR-<slug>.md`, from the template above. None filed yet. Cadence: `009` section 10.

**Renamed 2026-10-09** to valid codes (doc-filing audit): `001` BCASE to PLAN, `002` PRD to PROD,
`004` PP-UJRN to UC-USER, `005` SPEC to DSGN, `006` OD-STAT to LS-STAT.

## Code quick reference

| Category (CC) | Types (ABCD) used or likely here |
|---|---|
| PP Product and Planning | PROD, PLAN, RMAP, BREQ, FREQ |
| AT Architecture and Technical | ARCH, ADEC, DSGN, APIS, INTG |
| TQ Testing and Quality | TEST, CASE, QAPL, SECU |
| OD Operations and Deployment | OPNS, DEPL, INFR, CONF, RELS, INCD |
| LS Logs and Status | STAT, PROG, CHKP |
| RA Reports and Analysis | REPT, ANLY, AUDT, REVW |
| DR Documentation and Reference | STND, REFF, GUID, SOPS, TMPL, CHKL |
| UC User and Customer | USER, ONBD, PERS |
| AA After Action and Review | AACR, LESN, PMRT, REPT, TMPL |

Full tables: `/doc-filing` reference standard v4.5.
