# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.1.0] - 2026-10-09

- feat: initial project setup with governance, filed planning docs and beads (planning phase, no code) (d0f6719)
- bd init: initialize beads issue tracking (e585d2e)
- bd init: initialize beads issue tracking (8dc5045)

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
(handoff PL-A) with its work graph in Beads; nothing in it is authorized by the plan. On 2026-10-23 the plan was merged (PR #81), its decision brief was adopted provisionally by the council record `000-docs/030` (D-51) and the repo-only batch of `029` section 13.3 and the erasure chain started. Nothing is deployed and only synthetic data is used. No release
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
- PL batch item 4: the effect journal (one hash-chained record outside the backup's rollback domain), the
  reconciliation of effects after the backup point in the post-restore step (journal replay per app, provider reads
  outside the transaction, per-effect staff items, the owner's manual resolution, a lift that refuses on missing
  evidence) and the restore drill extended with an effect after the backup (`9kg.33`)
- PL batch item 4: the read-only Sent-folder evidence source (EXAMINE and BODY.PEEK only, by Message-ID or by
  window, bounded), the reconcile handler's handling of an unreadable source and of a recorded absence, the exact
  production mail-host allow-list for live web and worker processes, and the denied-mailbox rule that keeps the
  first-generation mailbox from ever being a v2 source (`9kg.49`)
- PR #89 review fix-ups: the journal's genesis identity, anchor verification at restore and lift, torn-tail
  detection with the owner-run `catalyst_journal_repair`, loud append failures with a health signal and a readiness
  refusal, a per-kind content allow-list and opaque staff references, `prepare` entries for restrictive effects and
  `send_begun` before SMTP; outward actions made uncertain after a restore, re-run convergence, the cursor watermark
  reset, blocking items for an unverified resend or revision, the question link on an unknown copy; the Sent reader's
  scan limit and incompleteness as blocking errors with a read-only client view; the mail process kind from code
  with a `reconcile` kind for the Sent read only (RD-1), the pinned v2 mailbox digest and the required denied list
  in a live environment; the drill's carried-journal checks as root, the reconcile role and the empty-journal leg
- Internal launch, repo-only batch item 3 (`029` section 13.3): the staff role matrix, the owner-run
  `grant_staff_role` command, the append-only grant record and the P4 and P5 role groups; the qualification
  authority read from configuration (`9kg.30`, `029` section 17.1)
- The staff path back from a hold through the decision service and form, and the staff verification resend on the
  correspondence screen with its limit (`9kg.50`, `018` section 19, `016` section 10.14)
- The `aged_waits` health part: every unbounded wait counted past its own threshold with its oldest age, paging
  per class by the owner's values, codes only (`9kg.51`, `026` section 17)
- The human-only assessment path completed for a launch with model advice disabled: the suspension record, the
  structured human-only reason, the decision digest and record carrying the policy, pack, evidence manifest and
  runs, the policy-to-pack binding guard, "refused by suspension" labels and the selection scorecard command
  (`oc4.12`; `oc4.10` items 1 to 3; `018` section 20, `011` section 4.1)
- Staff screens for the shell-only agreement states: the decisions on an unknown Documenso create, distribute and
  cancel on the agreements screen, and the agreement template approval screen (`9kg.47`, `021` section 20)
- Internal-launch batch 5 (`029` section 13.3): the GATE-STAGING evidence register, read by the per-gate report,
  which prints proof types, completeness, residual beads and the approval boundary per case and counts partial and
  live-only cases apart from PASS (`9kg.44`); the personal-data scan over committed evidence, receipts, alert text and
  the deployment receipt, with positive controls, run by the suite and by the host's receipt step, which withholds a
  receipt on a hit (`9kg.40`, TEST-P6-35); the automation pause row cleared only together with a same-transaction
  staff resume event (`automation_resumed`, with an actor reference, and a ten-character note for a system pause),
  enforced in PostgreSQL for every role by a deferred constraint trigger, with UPDATE and TRUNCATE refused;
  authorization and open-cause checks remain in code (`9kg.6`; applications migration 0006, workflow migration 0005)
- Internal launch, PL batch 2 (`029` section 13.3; beads `9kg.37`, `9kg.38`): the deploy operation (`CATALYST_DEPLOY_ID`)
  binds the pre-deploy backup to the deploy by id, digest and time, and the deployment receipt is a gate, built on
  D-I's recommended default: `deploy.sh` refuses an image other than the approved one, an unapproved commit label and
  a missing, stale, replaced or another deploy's backup before anything changes, so the wrapper reverts and holds; the
  smoke runs `check --deploy`. The deploy drill adds the N+1 expand release reverted to N on the expanded schema with
  the data kept, and a forward-only (contract) release whose revert is refused by name (`026` section 16)
- PL-A batch item 1 (`029` section 13.3): every public endpoint rate-limited in PostgreSQL per client (the proxy's
  forwarded address, trusted by where the web process listens) and per hashed address or token, one uniform refusal,
  fail closed for issuance and open for reading; invitation-only intake by default, enforced inside the intake
  transaction, spent once at confirmation, issued only by the owner-run `catalyst_invite`, shown in the dossier, the
  health report and the release receipt
- Intake notice and first-generation members (`030` Q8 and Q4; `029` section 17.2): the one-paragraph data notice as an
  owner-approved message template rendered on the request-access page in invitation mode and into the invitation
  mail that `catalyst_invite` prints for the owner to send (JSON or `--format text`), with the notice's version and
  digest and the invitation wording's digest recorded on the invitation; a marked draft in the draft environments and,
  anywhere else, a withheld page, no issuance and a health anomaly for unapproved, synthetic or withdrawn wording; the
  owner-run `catalyst_member_on_file` records which first-generation agreements are on file for a known member
  (plain version labels, an attested completion, idempotent, corrections only with `--correct`, fixed by trigger,
  shown on the dossier); a covered agreement type is referenced, never issued; the decision service and form refuse a
  v2 decline for a member on file (`018` section 20)
- Staff and health polish for the internal launch: a recurring sweep opens one `verification_expired` staff item when an
  unverified application's only link expires, resolved by the staff resend (`9kg.66`, `016` section 10.17); plain
  labels on every resolution and decision button, the code kept as the submitted value (`9kg.67`, `016` section
  10.18); the `held_followons` aged-waits class for held `send_decline`, `issue_nda` and `provision` follow-ons, aged
  from the last hold (`9kg.57`, `026` section 17); and the read-only `grant_staff_role --audit` with the `staff_roles`
  health part, reconciling memberships and direct permissions with the grant record (`9kg.56`, `029` section 17.1)
- The decline notice (bead `oc4.11`; `029` section 17.3, `016` section 10.19): a recorded decline queues one
  `send_decline`, which freezes the notice from the `decline_notice` template (correspondence migration 0019, an
  unapproved synthetic placeholder refused in a live environment until the owner approves real wording) and sends it
  through the P2 sender, the only message allowed through to the terminal `declined` stage; uncertain, failed and
  blocked sends reach the usual staff decisions, a permanent bounce opens `decline_not_notified` before the
  closed-application exception, the decision-maker may withhold the notice with a recorded reason, the notice's one
  variable is the display name (no reason, rationale or model output), and `send_decline` actions held by earlier
  releases are cancelled, never released
- Custody encrypted at rest (bead `9kg.34`; `029` section 6.2.2, `026` section 16): every custody document is sealed
  with AES-256-GCM (the reviewed `cryptography` 50.0.2, hash-locked) under its own data key, wrapped under one wrapping
  key; the wrapped keys live in a key directory and its live mirror outside the database, the custody directory and
  every backup set, so once a key is destroyed its document, restored from any older backup, cannot be opened without a surviving copy of the wrapped key and the wrapping key. A
  `CustodyEnvelope` row (agreements migration 0010) records the sealed file's digest; the recorded hash stays the
  plaintext's. The registry's `signed_documents` row takes `destroy_key`, which the erasure command carries out
  through erasure migration 0003's key references, journaling each destruction; `catalyst_custody_keys` reports on,
  migrates (plaintext sealed, then removed) and recovers the keys without ever restoring a destroyed one; start-up
  guards cover the wrapping key and the key directories; the restore drill gains a custody leg. The location, access
  rule and key recovery stay the owner's (`211.7.9`), shipped undecided and refused in a live environment; the claim
  covers v2's custody copy only (the provider's copy is under P4-D-15 until POL-10). Hardened after the PR #102
  security, release-operations and data reviews: the key store fails closed (provisioning markers, `key_lost` apart
  from `key_destroyed`, verified destruction), unrecorded keys and sealed files are discarded or reaped, lingering
  plaintext blocks an erasure, journaled destructions carry a mac and are swept only under the erasure key (at the
  lift; start-up only checks), recovery needs the out-of-band head and the erasure key, a resumed erasure checks the key
  store before it commits, one document that cannot be sealed never stops the migration, the associated data binds the recorded hash, erasure 0003 reverses cleanly, and the drill
  shows both outcomes
- Erasure replay after a restore (bead `9kg.25`, TEST-P6-29; `029` section 6.2.1, `026` section 16): on a restored
  host the order is restore, migrate, replay, review, lift. `catalyst_erasure_replay --expect-head <head>`, run as the
  retention login with the erasure key, verifies the durable record against the head kept out of band and re-erases
  every recorded subject in the restored tables through `catalyst_erase_replay` (erasure migration 0004). That is the
  erase function without its refusals for an open application, work in flight and an unfinished revocation, which
  the restored rows predate. It runs only under the restore hold and keeps the same audit row and tombstones. A
  subject with nothing left in the restored tables counts as satisfied.
  It also finds a person by the recorded subject hash across restored applications, invitations and member records,
  refuses before anything when a restored key does not hash to the record, and withholds its marker while a restored
  plaintext copy of an erased subject's document is on disk under `destroy_key`. The run ends with a mac'd
  `erasures_replayed` marker that the post-restore review and lift both require: written since the hold was placed,
  covering every erasure entry (the lift verifies its mac; the review holds no key), so an erasure made during the
  hold needs another replay. Workflow migration 0006 stops the application role inserting the restore hold. The review
  cancels the work of erased subjects, leaves them out of link, setup and revocation work, and opens one item for a
  subject still open after the journal's replay. `registry.REPLAY_BUILT` and `replay:not_built` are removed, so a
  decided registry is enough for a live backup. The restore drill runs a real erasure after the backup, then the
  restore, the refusals, the replay, its control, a second replay, the review and a later backup
  (`catalyst_erasure_drill`, synthetic only)
- Hardening (internal-launch batch item 6): the database freezes inbound message provenance and the identity
  columns of outbound attempts and reply links for every role, with the audited retention path left open for
  erasure (correspondence migration 0017, `016` section 10.14)
- Test hygiene (internal-launch batch item 6): the administrator database login reaches only the role-provisioning
  step of the test container and the CI job; the superuser-refusal probes and the tests that act as the
  administrator use a probe-only pair read by `tests/support.py` alone (`026` section 16)
- Python lint and dependency audit (bead `9kg.46`): ruff's default rules and `pip-audit` over the hash-locked requirement
  files run as one step of the CI docs job on every pull request, tools hash-locked in `requirements/lint.txt`, with the
  26 findings fixed and the fixture-import redefinitions scoped out (`009` sections 5.1 and 5.3)
- Targeted iteration lane (bead `9kg.45`): `scripts/select_tests.py` maps changed paths to the test modules that import
  them (fixture chains followed, anything unmapped runs the whole suite), tested by `tests/test_select_tests.py`, and the
  dispatch-only workflow "Targeted runtime checks" runs a named selection; neither is a required check, and the full
  run stays the merge and release-candidate gate. The runtime suite was profiled again against the 2026-10-18 baseline,
  with sharding, a docs-only skip and promotion of the lane recorded as proposals P12 to P14 (`009` sections 5.3, 5.4, 7)
- The live-call protections, built and tested before any live model call (bead `oc4.9`; `018` section 21): a lease
  fence before each model request and before the repair, a heartbeat that keeps the lease of a call longer than the
  lease (`workflow.keeper`), a request timeout Catalyst enforces around the call, the guard that one attempt fits in
  half the worker lease, a raising HTTP transport in tests, and the pre-call approval check: no live request without
  the owner's recorded standing, terms-bound approval (`approve_model_use`, append-only, assessments migration 0011, no
  expiry) naming the provider, model id, field list, how the request is built, pack, rubric and schema versions,
  budgets, timeout and repair limit, for the assessment and
  the reply interpreter alike; any changed term or a run frozen under another pack refuses. After review: the fields the
  request builders send are bound to the approved list (`fields_not_approved`), the approval is re-checked before every
  request, a live model needs the fence (`no_lease_fence`), streaming is refused, the keeper is bounded and never
  writes the worker-alive file, the test transport patches the clients' `send`, and the approval reference is a code.
  Security review fix-ups: the approval is relabelled standing, not per-request; the terms bind the builder version, the
  size caps, the model settings and the request limits (a source-hash test forces a version bump); the approval check
  runs after the lease fence, as the last gate; a row whose terms, provider or model id do not match its digest is
  stale; an assessment approval is refused while the rubric is synthetic; the field-absence tests measure the prompt
  text. No live model branch exists
- The egress deny list (bead `9kg.39`, TEST-P6-28; `026` section 16, `018` section 3.3): the fetcher's egress proxy
  refuses the estate's own production hosts by name (and every name under one) before any lookup, by every address
  those names resolve to, and at the connected peer, re-resolving the names at each check and keeping every address
  they ever had, so redirects and DNS changes cannot reach them; the list is an operator-supplied, secret-free file
  of logical host names read by the proxy alone, and a missing, empty or wholly unresolvable one refuses everything
  as a transient refusal with a start-up code and a failing healthcheck. The repository and
  staging carry synthetic names only (`tests/egress-deny.example`, `deploy/staging/egress-deny`, mounted into the
  proxy alone); the real list is a host-preparation item of `9kg.28`

### Changed

- Dependabot no longer proposes Django major-version bumps (#29)
- The release workflow publishes only an already-merged, CI-green commit of `main` and never commits or pushes to it
  (#41)
- The Intent Solutions Select partner badge is shown (#31)

### Fixed

- The P3 real-use defects 4 to 7 (bead `oc4.10`; `018` section 21): a dead reserved run (for example on a paused
  application) no longer holds a global concurrency slot; a handler defect with attempts left returns the run to queued
  for its retry; a run that ends leaves no invocation `started`; the lease-versus-timeout guard (item 7) is the `oc4.9`
  guard. Items 1 to 3 were fixed by `oc4.12`
- The release workflow refuses to tag, push or publish unless every required CI check succeeded on the
  release commit (#18)
- Two LOW findings of the 2026-10-22 audit (bead `9kg.48`): `pyproject.toml` declares the tagged version 0.1.0 (it said
  0.0.0 while `version.txt` said 0.1.0), the CI docs job installs its one dependency hash-locked from
  `requirements/docs.txt` instead of by version alone, and this file's preamble sits above the first release entry
- The screen walkthrough (bead `9kg.41`, `029` appendix B): the staff verification resend acts once on a double
  submit; the decision, clarification and agreement-details forms keep what was typed after a refusal (never the
  decision's outcome); the dossier labels actions held on policy; the staff item page states each reason in plain
  words and links the decision and evidence screens; the agreements screen names the countersignature wait and shows
  each agreement's age; a suspended or capped assessment item closes only through the human-only decision; a decision
  refused because the case changed clears every judgment; the provisioning screen shows an activation waiting on an unavailable provider; the staff
  index lists the screens a role can open; the public pages wrap at phone width; stale help text and docstrings
  corrected (the worker's help line, "in this slice", test-only where staging is allowed, "outside production", the
  `016` line on a paused staff-send reconcile)

[Unreleased]: https://github.com/intent-solutions-io/catalyst-onboarding-v2/commits/main
