# catalyst-onboarding-v2

<!-- intent-select-partner:start -->
[![Intent Solutions: Claude Partner Network Select Services Partner](https://raw.githubusercontent.com/intent-solutions-io/.github/b82af5d3e7951d85e39ea9e65cc24ee8278722a7/assets/brand/claude-select-partner.svg)](https://intentsolutions.io/)

Intent Solutions is a Claude Partner Network Select Services Partner.
<!-- intent-select-partner:end -->

> **Status (2026-10-14): the first slice (GATE-S1) and the correspondence loop (GATE-P2) are accepted for synthetic
> work; P3 (evidence and a bounded, advisory assessment with test models only) is in progress. Nothing is deployed
> and no real applicant data or live model is used.**

A documentation-first, Django-native Solution Catalyst onboarding platform for Intent Solutions.

## What this repository is right now

This repository holds the planning record for a second-generation onboarding platform (the master
blueprint, product requirements, architecture, user journey, technical specification and phased
execution plan, approved in scope by the owner in `000-docs/011` section 10) and the code of its
**first working slice** (phase P1), which passed its acceptance gate, GATE-S1, on 2026-10-11 (owner
decision D-26; evidence `000-docs/013`). The slice covers:

- a public access-request form that records the application, its first submission version, a
  verification challenge and a queued send in one database transaction;
- a PostgreSQL-backed worker that sends the verification message to a **local mail sink** (never real
  email) and recovers after interruption;
- an explicit, expiring, single-use confirmation link that adopts only the submission the applicant was
  shown;
- a read-only staff dossier in Django Admin.

Since then, P2, the applicant correspondence loop against local test mail servers, passed GATE-P2 on 2026-10-13
(D-33; `000-docs/016`), and P3 is in progress (`000-docs/018`, approved D-34): versioned applicant claims,
fixture-backed evidence observations, and a bounded assessment that runs only on PydanticAI test models and is
advice to a human, never a decision. How the selection standard itself is governed and improved is set out (approved D-35) in
`000-docs/011` section 11 and `000-docs/019`.

Only synthetic data is used and nothing is deployed. Real email, live model calls, the qualification decision,
agreements, provisioning and deployment are not built or not authorized. The release workflow
has an open release-blocking defect (it pushes its version-bump commit straight to `main`; tracked in
Beads as "Make the release workflow publish through a reviewed pull request"), so no release is cut
until it is fixed.

Run the tests (Docker required; digest-pinned Python 3.14.8 and PostgreSQL 16.15 containers, isolated
per run):

```bash
scripts/test.sh        # full runtime suite; a full run fails unless every acceptance case is PASS
scripts/check-docs.sh  # Markdown lint and document index check
```

The platform it describes will take a person from a first access request on
`learn.intentsolutions.io` through verification, a bounded AI-assisted review with human
approval, an NDA whose verified completion comes before the User Agreement is shown or issued,
then the User Agreement and any other required agreements, signed through Documenso, company mailbox provisioning
and a welcome, with the whole journey auditable from first contact to activation, a single
progressive dossier in PostgreSQL. A Twenty CRM projection is deferred beyond the MVP.

## Why a new repository

The first-generation Catalyst onboarding service runs in production on a Flask code base and
stays the system of record for live applicants. A Django refactor attempted inside that
repository was parked by the owner on 2026-10-09 (its decision log, decision 22). This
repository starts the replacement cleanly: design first, with the first-generation service's
proven behaviour as the specification to meet, not as code to copy.

## Boundaries

- Application code only within an authorized handoff; no deployments, no real data.
- No code copied from the first-generation repository.
- No secrets, applicant information, agreement contents or private audit material. Everything
  here is public; keep it that way.
- Shape: Django, PostgreSQL, server-rendered applicant UI, Django admin as the first operator UI,
  one PostgreSQL-backed background worker (all in use in the first slice); later phases add the
  existing MXroute email services, Documenso, and MiniMax through PydanticAI; Twenty deferred. The build
  contract is `000-docs/011-PP-PLAN-master-blueprint.md`.

## Layout

| Path | Purpose |
|---|---|
| `000-docs/` | Filed planning documents (`NNN-CC-ABCD-description.md`); `000-INDEX.md` is the index |
| `accounts/`, `applications/`, `correspondence/`, `assessments/`, `workflow/`, `config/` | Django apps and settings (P1 intake and verification, P2 correspondence, P3 evidence and assessment) |
| `tests/` | Runtime test suite; `tests/acceptance.py` maps each acceptance case to its tests |
| `scripts/` | `test.sh`, `check-docs.sh`, database role provisioning and the release CI gate |
| `.beads/` | Task tracking (beads); `bd ready` lists open work |
| `CLAUDE.md`, `AGENTS.md` | Working rules for agent sessions in this repository |

## Working here

Read `CLAUDE.md` first. Documents follow the Intent Solutions document filing standard; every new
document gets the next number and an index row. Pull requests only; `main` is protected by
convention until branch protection is configured.

## License

Apache-2.0. See `LICENSE`.
