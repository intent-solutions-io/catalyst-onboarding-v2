# Business Case: Catalyst v2 onboarding

| Field | Value |
|---|---|
| Document | `001-PP-PLAN-business-case` |
| Version | 0.2.0 (replaces the seeded template) |
| Status | **PROPOSED**; business figures **unknown** |
| Owner | Jeremy Longshore |
| Date | 2026-10-09 |
| Related | `011-PP-PLAN-master-blueprint.md` (the build contract hub) |

> **Status: PRELIMINARY, subject to review.** The seeded template asked for market size, ROI and
> competitor figures. None has been researched or provided, so none is stated. This document records
> only the problem and the decision context.

## Problem

Intent Solutions onboards people who request access through `learn.intentsolutions.io`. The
first-generation onboarding service handles this in production and remains the system of record for live
applicants. A Django refactor inside that repository was parked on 2026-10-09 (its decision 22). The
owner chose to build a second-generation, Django-native service in a clean repository, designed first,
that treats the first generation's proven behaviour as a specification to meet, not as code to copy
(`README.md`; `011` D-01, D-11).

## What v2 must deliver

The objectives are `OBJ-01` to `OBJ-05` in `002` section 1: one auditable path per applicant, routine work
without manual pushing, staff resolution without SSH or coding agents, no progress past unmet legal or
approval prerequisites, and no protected information in public places.

## Figures not established

| Item | Status |
|---|---|
| Applicant volume, staff time per applicant, cost of the current process | unknown; not researched in this handoff |
| Market size, ROI, competitor comparison | not applicable to an internal onboarding service unless the owner says otherwise |
| Operating cost of v2 (hosting, model usage) | unknown; model usage becomes measurable through `MET-10` |

## Main risks

| Risk | Response |
|---|---|
| v2 drifts from the first generation's proven behaviour | sanitized evidence packets through `catalyst-legacy-analyst` at each phase's handoff A |
| Live records lost at cutover | epic PL and GATE-CUTOVER (`002` section 6); D-14 |
| Open policies stall later phases | each policy names the earliest milestone it blocks (`011` section 6) |
| Planning grows without working software | phases ship working slices; the first slice is deliberately small (`005` S1) |

## Decision

Pending: owner approval of the build contract (`011`).
