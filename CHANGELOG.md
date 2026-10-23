# Changelog

## [v0.1.0] - 2026-10-09

- feat: initial project setup with governance, filed planning docs and beads (planning phase, no code) (d0f6719)
- bd init: initialize beads issue tracking (e585d2e)
- bd init: initialize beads issue tracking (8dc5045)

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Phases P1 to P5 are implemented and accepted for synthetic work: GATE-S1 (2026-10-11, D-26), GATE-P2 (2026-10-13,
D-33), GATE-P3 (2026-10-17, D-36) and GATE-P4 (2026-10-18, D-45), each recorded in `000-docs/011` section 4. P5 is
built against a local fake of the documented MXroute operations (PRs #53 to #56). GATE-P5 was signed off for synthetic
work on 2026-10-18 (D-48), with the after-action report `000-docs/000-aars/025`. P6 staging (PRs #58 to #80: the
`staging` environment and guards, secure cookies and sessions, health endpoints, a worker heartbeat and health
command, the image and per-secret files, role provisioning, backup and restore with a restore hold and a post-restore
step, the generated Caddyfile, staff two-factor, the deploy adapters and attested image, the rotation runbook `027`,
the live staging cases, the egress proxy, alerts to Buzz, the measured restore drill, the dark deploy and cutover
rehearsal, and the GATE-STAGING evidence map with the after-action report `028`) is built and drilled on the dev
box; GATE-STAGING was signed off on 2026-10-22 (D-50). The internal production launch is planned in `000-docs/029`
(handoff PL-A) with its work graph in Beads; nothing in it is authorized by the plan. Nothing is deployed and only synthetic data is used. No release
has been cut since `v0.1.0`, which the templated workflow tagged automatically on the first push to `main`; it was
not a planned release. The release workflow was corrected in PR #41: it is manual, dry-run by default, and publishes
only an already-merged, CI-green commit of `main` without committing or pushing to it.

### Added

- Initial project setup with full governance
- README, LICENSE, CODE_OF_CONDUCT, CONTRIBUTING, SECURITY, SUPPORT
- Docs CI (Markdown lint, index completeness) and a release workflow, inert at the time (since replaced; see above)
- Six-document planning set under `000-docs/` with `000-INDEX.md`, each marked preliminary
- Beads task tracking (prefix `catalyst-v2`) with one planning epic
- GitHub issue templates and PR template
- Dependabot configuration
- EditorConfig and gitattributes
- Eleven read-only specialist subagents with their operating charter and registry (#3); developer
  workflow and quality contract, hook and memory register, branch and worktree policy (#5); AAR template
  and cadence (#6); the build contract, readiness checkpoint and first-slice specification (#7); handoff 1A
  compatibility evidence for ADR-03, 14, 17 and 18 (#8)
- Handoff 1B.1: Django skeleton, PostgreSQL-only start-up guards, custom user model and the CI runtime
  lane in digest-pinned containers (#9)
- Handoff 1B.2: first-slice data model, three separated database roles (ADR-14) and append-only history
  (#11)
- Handoff 1B.3: public access-request form with one-transaction intake and race-safe duplicate handling
  (#12)
- Handoff 1B.4: PostgreSQL-backed worker with lease-fenced recovery and the verification send to a local
  mail sink (#13)
- Handoff 1B.5: explicit, single-use contact confirmation that adopts only the named submission version
  (#14)
- Handoff 1B.6: read-only staff dossier in Django Admin with owner-created accounts and a view-only group
  (#15)
- S1-T8: every first-slice acceptance case mapped to its tests, reported per case, and full runs gated on
  all PASS; acceptance evidence `013` and after-action report `014` (#16)
- Owner's GATE-S1 sign-off (D-26) and POL-01 confirmation for the slice (D-25) recorded (#17)
- Operator-grade system analysis `015` (#19)
- P2, the correspondence loop: handoff 2A specification (#20); outbound foundations (#21); inbound collection
  (#22); reply processing (#23); reminders and staff intervention (#24); GATE-P2 evidence, closeout and
  after-action report `017` (#25, #27)
- P3, evidence and assessment: handoff 3A specification (#28); claims and fixture-backed evidence (#30); bounded
  assessment on test models (#32); the selection-quality contract `019` (#33); clarification (#34); the authorized
  qualification decision (#35); GATE-P3 map and after-action report `020` (#36)
- P4, agreements: handoff 4A specification (#37); create and distribute against a fake Documenso (#38);
  verification by fresh read and sequencing (#39); recovery corrections and D-41 to D-44 (#42); custody,
  retrieval, required details and the staff screen (#43); GATE-P4 map, HTTP journey and after-action report `022`
  (#47)
- Hardening: correspondence evidence append-only (#44); hard bounces block every send (#45); system pauses need a
  decision-maker (#46); a quarter-faster test suite (#40)
- Preparation: P5 specification, P6 readiness matrix and PL cutover plan, `023` and `024` (#48)
- Internal launch, repo-only batch item 3 (`029` section 13.3): the staff role matrix, the owner-run
  `grant_staff_role` command, the append-only grant record and the P4 and P5 role groups; the qualification
  authority read from configuration (`9kg.30`, `029` section 17.1)
- The staff path back from a hold through the decision service and form, and the staff verification resend on the
  correspondence screen with its limit (`9kg.50`, `018` section 19, `016` section 10.13)
- The `aged_waits` health part: every unbounded wait counted past its own threshold with its oldest age, paging
  per class by the owner's values, codes only (`9kg.51`, `026` section 17)
- The human-only assessment path completed for a launch with model advice disabled: the suspension record, the
  structured human-only reason, the decision digest and record carrying the policy, pack, evidence manifest and
  runs, the policy-to-pack binding guard, "refused by suspension" labels and the selection scorecard command
  (`oc4.12`; `oc4.10` items 1 to 3; `018` section 20, `011` section 4.1)
- Staff screens for the shell-only agreement states: the decisions on an unknown Documenso create, distribute and
  cancel on the agreements screen, and the agreement template approval screen (`9kg.47`, `021` section 20)

### Changed

- Dependabot no longer proposes Django major-version bumps (#29)
- The release workflow publishes only an already-merged, CI-green commit of `main` and never commits or pushes to it
  (#41)
- The Intent Solutions Select partner badge is shown (#31)

### Fixed

- The release workflow refuses to tag, push or publish unless every required CI check succeeded on the
  release commit (#18)

[Unreleased]: https://github.com/intent-solutions-io/catalyst-onboarding-v2/commits/main
