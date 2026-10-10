# catalyst-onboarding-v2

> **Status: architecture and planning phase. Preliminary and subject to review.**

A documentation-first, Django-native Solution Catalyst onboarding platform for Intent Solutions.

## What this repository is right now

This repository holds the planning record for a second-generation onboarding platform:
the master blueprint, product requirements, architecture, user journey, technical specification
and phased execution plan, approved in scope by the owner (`000-docs/011` section 10). The only
application code is the handoff 1B.1 skeleton: Django settings, start-up guards, a custom user model
and its tests. No applicant feature is implemented and nothing is deployed.

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
- Target shape, to be confirmed by the plan: Django, PostgreSQL, server-rendered applicant UI,
  Django admin as the first operator UI, the existing MXroute email services, Documenso, MiniMax
  through PydanticAI, and one PostgreSQL-backed background worker; Twenty deferred. The build
  contract is `000-docs/011-PP-PLAN-master-blueprint.md`.

## Layout

| Path | Purpose |
|---|---|
| `000-docs/` | Filed planning documents (`NNN-CC-ABCD-description.md`); `000-INDEX.md` is the index |
| `.beads/` | Task tracking (beads); `bd ready` lists open work |
| `CLAUDE.md`, `AGENTS.md` | Working rules for agent sessions in this repository |

## Working here

Read `CLAUDE.md` first. Documents follow the Intent Solutions document filing standard; every new
document gets the next number and an index row. Pull requests only; `main` is protected by
convention until branch protection is configured.

## License

Apache-2.0. See `LICENSE`.
