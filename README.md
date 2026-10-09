# catalyst-onboarding-v2

> **Status: architecture and planning phase. Preliminary and subject to review.**

A documentation-first, Django-native Solution Catalyst onboarding platform for Intent Solutions.

## What this repository is right now

This repository holds the planning record for a second-generation onboarding platform:
the master blueprint, product requirements, architecture, user journey, technical specification
and phased execution plan. **It contains no application code.** Nothing in it is approved,
implemented or deployed, and every document carries a preliminary banner until the owner
accepts it.

The platform it describes will take a person from a first access request on
`learn.intentsolutions.io` through verification, a bounded AI-assisted review with human
approval, an NDA and a User Agreement signed through Documenso, company mailbox provisioning
and a welcome, with the whole journey auditable from first contact to activation, a single
progressive dossier in PostgreSQL, and a Twenty CRM projection of the relationship.

## Why a new repository

The first-generation Catalyst onboarding service runs in production on a Flask code base and
stays the system of record for live applicants. A Django refactor attempted inside that
repository was parked by the owner on 2026-10-09 (its decision log, decision 22). This
repository starts the replacement cleanly: design first, with the first-generation service's
proven behaviour as the specification to meet, not as code to copy.

## Boundaries

- No application code, features, deployments or data until a plan is approved.
- No code copied from the first-generation repository.
- No secrets, applicant information, agreement contents or private audit material. Everything
  here is public; keep it that way.
- Target shape, to be confirmed by the plan: Django, PostgreSQL, server-rendered applicant UI,
  Django admin as the first operator UI, the existing email provider, Documenso, an LLM provider
  abstraction, Twenty integration, and a simple background worker.

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
