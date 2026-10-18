# Changelog

## [v0.1.0] - 2026-10-09

- feat: initial project setup with governance, filed planning docs and beads (planning phase, no code) (d0f6719)
- bd init: initialize beads issue tracking (e585d2e)
- bd init: initialize beads issue tracking (8dc5045)

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Phases P1 to P4 are implemented and accepted for synthetic work: GATE-S1 (2026-10-11, D-26), GATE-P2 (2026-10-13,
D-33), GATE-P3 (2026-10-17, D-36) and GATE-P4 (2026-10-18, D-45), each recorded in `000-docs/011` section 4. P5 is
specified (`000-docs/023`, proposed) and not built. Nothing is deployed and only synthetic data is used. No release
has been cut since `v0.1.0`, which the templated workflow tagged automatically on the first push to `main`; it was
not a planned release. The release workflow was corrected in PR #41: it is manual, dry-run by default, and publishes
only an already-merged, CI-green commit of `main` without committing or pushing to it.

### Added

- Initial project setup with full governance
- README, LICENSE, CODE_OF_CONDUCT, CONTRIBUTING, SECURITY, SUPPORT
- Docs CI (Markdown lint, index completeness) and an inert release workflow (no release exists)
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

### Fixed

- The release workflow refuses to tag, push or publish unless every required CI check succeeded on the
  release commit (#18)

[Unreleased]: https://github.com/intent-solutions-io/catalyst-onboarding-v2/commits/main
