# catalyst-onboarding-v2

<!-- intent-select-partner:start -->
[![Intent Solutions: Claude Partner Network Select Services Partner](https://raw.githubusercontent.com/intent-solutions-io/.github/b82af5d3e7951d85e39ea9e65cc24ee8278722a7/assets/brand/claude-select-partner.svg)](https://intentsolutions.io/)

Intent Solutions is a Claude Partner Network Select Services Partner.
<!-- intent-select-partner:end -->

> **Status (2026-10-23):** phases P1 to P5 are built and their acceptance gates are signed off **for synthetic work
> only** (GATE-S1, GATE-P2, GATE-P3, GATE-P4, GATE-P5). P6 staging (a deployable image, a staging stack, a deploy
> that reverts itself, alerts, a measured restore and a cutover rehearsal) is built and drilled on the dev box, and
> GATE-STAGING is signed off for that scope (D-50). The first production deployment, an invited internal cohort on
> the production host, is **planned** in `000-docs/029` and not authorized. Nothing is deployed. No real applicant
> data, live model, live Documenso, real mailbox or live provider key is used.

A documentation-first, Django-native Solution Catalyst onboarding platform for Intent Solutions.

## What it does today

The platform takes a person from a first access request through to signed agreements. Each step is auditable
from first contact, in one progressive dossier in PostgreSQL.

| Phase | What works (synthetic) | Gate |
|---|---|---|
| P1 | Public access-request form, an email verification sent by a PostgreSQL-backed worker, a single-use confirmation link, a read-only staff dossier | GATE-S1 (D-26; `000-docs/013`) |
| P2 | Applicant correspondence: approved questions and reminders, mail collection, reply association and trust, staff confirmation, pause and resume, hard-bounce blocking | GATE-P2 (D-33; `000-docs/016`) |
| P3 | Applicant claims, fixture-backed evidence, a bounded advisory assessment on PydanticAI **test models**, clarification, and a qualification decision that only an authorized person records | GATE-P3 (D-36; `000-docs/018`) |
| P4 | NDA, then User Agreement, through a **local fake of Documenso**: no duplicate envelopes, signing verified only by a fresh provider read, Catalyst's own verified copy kept separately, audited retrieval, a staff agreement screen, and one held provisioning hand-off | GATE-P4 (D-45; `000-docs/021`, AAR `000-docs/000-aars/022`) |
| P5 | Mailbox provisioning, credential setup, activation and withdrawal | built and accepted for synthetic work: GATE-P5 signed off 2026-10-18 (D-48, `000-docs/000-aars/025`) |
| P6 | An attested image, a staging stack with its own roles and secrets read from files, staff two-factor, an egress-controlled evidence fetcher, a deploy that reverts itself, health checks that alert to Buzz, a backup restored and measured, the Learn cutover rehearsed on a stand-in | built and drilled on the dev box; GATE-STAGING signed off 2026-10-22 (D-50; `000-docs/000-aars/028`, 17 of 38 cases partly proven) |
| PL and the internal launch | Coexistence with the live first-generation service; the first production deployment for an invited internal cohort | planned (`000-docs/029`, proposed; GATE-PILOT is the owner's go/no-go) |

**Not built or not authorized:** real email delivery, live model calls, live Documenso, real agreement templates, a
live mailbox adapter, erasure and retention, production-host configuration, deployment and releases. Before any real applicant data, the owner's open policies must be
decided: custody (POL-09), retention and erasure (POL-10), required details (POL-18), staff MFA and network access
(POL-13, POL-14), and the others in `000-docs/011` section 6. The carried production limits are listed in
`000-docs/000-aars/022` section 9 and `000-docs/024`.

How the selection standard itself is governed and improved is set out in `000-docs/011` section 11 and
`000-docs/019` (approved D-35). Software gates passing is not evidence of selection quality.

## Run it

Docker is required. Every run uses its own digest-pinned Python 3.14.8 and PostgreSQL 16.15 containers and removes
them afterwards. No credentials are needed and nothing external is contacted.

```bash
scripts/test.sh                                            # full suite; fails unless every acceptance case of every gate passes
PYTEST_ARGS="-v tests/test_p4_journey.py" scripts/test.sh  # one area (a selected run is reported, not gated)
scripts/check-docs.sh                                      # Markdown lint and document index check
```

`tests/acceptance.py` maps every acceptance case of GATE-S1 to GATE-P5 and GATE-STAGING to the tests that prove
it (one staging case, the dark deploy, is proven only by a live drill). A full run prints the per-gate report; read
it beside the after-action report's per-case table, because a PASS on a few staging cases pins the code's shape and
the drills carry the behaviour. The local demonstration of the P4 journey is described in `000-docs/021` section 19.

## Why a new repository

The first-generation Catalyst onboarding service runs in production on a Flask code base and stays the system of
record for live applicants. A Django refactor attempted inside that repository was parked by the owner on
2026-10-09. This repository starts the replacement cleanly: design first, with the first-generation service's proven
behaviour as the specification to meet, not as code to copy. How live records will move is planned in
`000-docs/024` (PL, proposed).

## Boundaries

- Application code only within an authorized handoff; no deployments, no real data.
- No code copied from the first-generation repository.
- No secrets, applicant information, agreement contents or private audit material. Everything here is public; keep
  it that way.
- Shape:
  - Django, PostgreSQL, a server-rendered applicant UI, Django admin plus focused staff screens;
  - one PostgreSQL-backed background worker, with no Temporal and no second queue;
  - MXroute email, Documenso and MiniMax through PydanticAI, each behind a local fake or test model until the
    owner authorizes live use;
  - Twenty CRM deferred.
- The build contract is `000-docs/011-PP-PLAN-master-blueprint.md`.

## Layout

| Path | Purpose |
|---|---|
| `000-docs/` | Filed documents (`NNN-CC-ABCD-description.md`); `000-INDEX.md` is the index; after-action reports in `000-aars/` |
| `accounts/`, `applications/`, `workflow/`, `config/` | Users, intake and verification, the pending-action ledger and worker, settings and start-up guards |
| `correspondence/` | P2: outbound and inbound mail, reply processing, reminders, staff actions |
| `assessments/` | P3: evidence, the bounded assessment, the qualification decision |
| `agreements/` | P4: agreement records, the Documenso client, completion, custody, the staff agreement screen |
| `provisioning/` | P5: the mail-host interface, mailbox creation, credential setup, activation, withdrawal and closure |
| `deploy/` | P6: the generated staging compose stack and Caddyfile, the estate deploy adapters, the cutover route snippets |
| `Dockerfile` | One image for every process kind; the staging target adds two local fakes |
| `tests/` | Runtime suite; `tests/acceptance.py` is the acceptance map; local fakes for SMTP, IMAP, Documenso and the mail host |
| `scripts/` | `test.sh`, `check-docs.sh`, database role provisioning, the release checks, the live staging drills |
| `.beads/` | Task tracking (beads); `bd ready` lists open work |
| `CLAUDE.md`, `AGENTS.md` | Working rules for agent sessions in this repository |

## Working here

Read `CLAUDE.md` first, then `000-docs/011` (start here) and `000-docs/009` (workflow and quality contract).

- Documents follow the Intent Solutions filing standard: each new document gets the next number and an index row.
- Work goes through pull requests only, and merges go through the estate merge guard after the required checks pass.
- GitHub branch protection is not configured on `main` (checked 2026-10-22). A ruleset and a protected release
  environment are proposed in `000-docs/009` section 5.5 and are a precondition for any deploy credential (bead
  `catalyst-v2-9kg.35`).
- Releases are manual and dry-run by default, and publish only an already-merged, CI-green commit of `main`.
  No release has been cut since the automatic `v0.1.0`.

## License

Apache-2.0. See `LICENSE`.
