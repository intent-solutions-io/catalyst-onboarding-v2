# 000-docs index

Document filing standard: `NNN-CC-ABCD-description.md`, flat by default, chronological by number.
Every document in this directory is **preliminary and subject to review** until the owner accepts it.

| Document | Purpose | Status |
|---|---|---|
| [000-AA-TMPL-after-action-report.md](000-AA-TMPL-after-action-report.md) | After-action report template, snapshot of the `/doc-filing` canonical v1.0.0 (full and lightweight lanes) | Canonical copy lives in the skill; refresh on version change |
| [001-PP-PLAN-business-case.md](001-PP-PLAN-business-case.md) | Business case: problem and decision context; business figures marked unknown | Proposed 2026-10-09 (0.2.0); subject to review |
| [002-PP-PROD-product-requirements.md](002-PP-PROD-product-requirements.md) | PRD: objectives, scope, requirements `REQ-001`-`034`, operating measures, release gates, traceability matrix | Proposed 2026-10-09 (0.2.0); subject to review |
| [003-AT-ARCH-architecture.md](003-AT-ARCH-architecture.md) | Architecture: context, six domain apps plus `accounts`, data flow, security model, verified current Learn routing, proposed v2 routing, staff access design, decision records `ADR-01`-`18` | Proposed 2026-10-09 (0.2.0); subject to review |
| [004-UC-USER-user-journey.md](004-UC-USER-user-journey.md) | Applicant journey, stages `J-01`-`J-16`: trigger, records, transaction, checks, LLM scope, alternates, retries, owner, tests | Proposed 2026-10-09 (0.2.0); subject to review |
| [005-AT-DSGN-technical-spec.md](005-AT-DSGN-technical-spec.md) | Implementation slices; S1 first slice: scope, minimal model, Django capabilities, versions, acceptance plan `TEST-S1-01`-`22` | Proposed 2026-10-09 (0.2.0); not built |
| [006-LS-STAT-status.md](006-LS-STAT-status.md) | Status: current state, verified versus pending, blockers, next approval | Updated 2026-10-11 |
| [007-DR-STND-agent-operating-charter.md](007-DR-STND-agent-operating-charter.md) | Agent Operating Charter: shared rules, boundaries, precedence and result format for the specialist subagents | Proposed 2026-10-09; subject to review |
| [008-RA-REPT-agent-registry-and-validation-report.md](008-RA-REPT-agent-registry-and-validation-report.md) | Agent registry and validation report: roster, models, access boundaries, references, validation and smoke-test results | Proposed 2026-10-09; subject to review |
| [009-DR-STND-developer-workflow-and-quality-contract.md](009-DR-STND-developer-workflow-and-quality-contract.md) | Developer Workflow and Quality Contract: one job per system, working agreement, Beads and brain discipline, checks and CI, branch and worktree policy, owner decisions of 2026-10-09 | Proposed 2026-10-09; subject to review |
| [010-DR-REFF-hook-and-memory-responsibility-register.md](010-DR-REFF-hook-and-memory-responsibility-register.md) | Hook and Memory Responsibility Register: observed hooks, costs, event matrix, memory stores, changes applied outside the repo | Proposed 2026-10-09; subject to review |
| [011-PP-PLAN-master-blueprint.md](011-PP-PLAN-master-blueprint.md) | **Master blueprint (start here):** document map, owner decisions, authority, open policy register, phased work graph with bead references, approval record | Approved in scope 2026-10-09 (section 10) |
| [012-RA-ANLY-s1-t1-compatibility-evidence.md](012-RA-ANLY-s1-t1-compatibility-evidence.md) | Handoff 1A evidence: atomic enqueue, worker-death recovery, append-only enforcement, custom user model, versions; decision table for ADR-03, 14, 17, 18 (recommendations only) | Evidence 2026-10-09; ADRs decided 2026-10-10 (D-16 to D-19) |
| [013-TQ-TEST-first-slice-acceptance-evidence.md](013-TQ-TEST-first-slice-acceptance-evidence.md) | First-slice acceptance evidence (S1-T8): case-to-test map, per-case report and full-run gate, results for TEST-S1-01 to 22, what the evidence does not show | Evidence 2026-10-11; GATE-S1 signed off 2026-10-11 (D-26) |
| [000-aars/014-AA-AACR-first-slice.md](000-aars/014-AA-AACR-first-slice.md) | After-action report for the first working slice (epic `catalyst-v2-6hl`), full lane | Filed 2026-10-11 |
| [015-AA-AUDT-appaudit-devops-playbook.md](015-AA-AUDT-appaudit-devops-playbook.md) | Operator-grade system analysis after GATE-S1: architecture, tradeoffs, operations, sharp edges, security, current state, roadmap; unscored health judgement 68/100 | Audit 2026-10-11 at `ef17aa6`; errata 2026-10-11 |
| [016-AT-DSGN-p2-correspondence-specification.md](016-AT-DSGN-p2-correspondence-specification.md) | Handoff 2A: P2 correspondence specification (outbound, IMAP collection, association and trust, reply processing, reminders, staff intervention, monitoring), GATE-P2 acceptance plan `TEST-P2-01`-`54`, owner decision brief by blocker, bead map | Approved for synthetic P2, version 0.3.2 (D-27 to D-32, 2026-10-12), with implementation notes in section 10; 2B.1 merged, 2B.2 in review |

Next free number: `017`.

**After-action reports** go in `000-aars/` inside this directory (filing standard v4.5 §3.1.3): global
`NNN`, `NNN-AA-AACR-<slug>.md`, from the template above. Filed: `014` (first slice). Cadence: `009` section 10.

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
