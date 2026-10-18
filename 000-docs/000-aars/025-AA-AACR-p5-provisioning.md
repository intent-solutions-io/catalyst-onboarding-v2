# 025-AA-AACR — P5 provisioning after-action report

> P5 is the stage where an applicant whose agreements are complete gets a company mailbox. The owner releases
> provisioning, an approver approves the exact address and limits, and Catalyst creates and verifies the mailbox.
> The applicant then sets their own password, and Catalyst activates them and sends a welcome. P5 also covers how
> access is removed again: an applicant withdraws through a verified link, or staff close the application, and
> Catalyst revokes access without deleting anything. Everything here ran against a local fake of the documented
> MXroute operations, on synthetic data. No real mailbox, password, provider key or applicant was used.

- **Status:** GATE-P5 signed off by the owner on 2026-10-18 (D-48 in `011`), on CI run 39165187400 at head
  `f3d7503` (1144 passed; GATE-S1 25, GATE-P2 54, GATE-P3 60, GATE-P4 40, GATE-P5 29), accepting the statement in
  section 9 and the partial clauses in section 4.
- **Lane:** full. Every task had review findings and fixes (section 5).
- **Epic:** "Provision the approved mailbox, activate the applicant, and support withdrawal and recovery" (bead
  `catalyst-v2-tuc`).
- **Acceptance test:** at one head, in a full run on PostgreSQL, every case must PASS. That covers TEST-P5-01 to
  TEST-P5-24 in `023` section 9 and the five supporting groups:
  - append-only records;
  - supersession and the bounded watch (11.11);
  - bounded credential recovery (11.5);
  - the removed-gate controls;
  - P5-D-6 (the checklist credential is a separate contingency).

  GATE-S1, GATE-P2, GATE-P3 and GATE-P4 must still PASS.
- **GitHub:**
  - P4 closeout: PR #50 (D-46);
  - decisions: PR #51 (D-47, `023` 0.2.0, with the public MXroute API);
  - backup and restore rehearsal: PR #52 (9kg.7);
  - 5B.1: PR #53; 5B.2: PR #54; 5B.3a: PR #55; 5B.3b: PR #56;
  - 5C: PR #57 (this report).
- **Period:** 2026-10-18
- **Author:** Jeremy Longshore. Claude Code implemented the work; the Catalyst specialist subagents reviewed it.
- **Template:** 000-AA-TMPL v1.0.0

## 1. Summary and business value

For one applicant whose agreements are complete, staff can now see and trust each of these as a separate fact:

- **Release and approval.** Provisioning starts only through the owner's versioned activation command, and only
  after a fresh read of the agreements at Documenso (TEST-P5-01, 02). The approver confirms the exact address,
  quota, sending limit, method and prerequisite digest. A form showing something else is refused (TEST-P5-07).
- **Creation.** The request and its attempt are committed before any call to the mail host. An absent read comes
  first, then one create, then an authoritative read of that mailbox (TEST-P5-08, 12).
  - An unknown outcome is reconciled by reading the mailbox, never by sending again.
  - A mailbox Catalyst did not create is a conflict, never adopted.
  - A mailbox found after an unknown create is ours only when staff confirm it (TEST-P5-09, 10).
- **Credentials.** No password is ever emailed. The applicant sets their own through a one-time link that is
  hash-only, single-use and expiring (TEST-P5-13). The link goes to the verified external address, re-checked when
  it is sent and when it is used (TEST-P5-14).
  - The chosen password is in no record, event, log, error or payload (TEST-P5-15).
  - An unknown set outcome blocks activation and is never replayed (TEST-P5-16).
- **Activation.** Activation needs both a verified mailbox and a completed setup. The welcome is frozen in the same
  transaction and sent later; a bounce of it opens a staff item (TEST-P5-03, 04).
- **Removing access.** A withdrawal through the verified link (GET shows, POST commits), or a staff close, stops
  provisioning wherever it is (TEST-P5-05, 17, 21, 22).
  - Revocation acts only on a mailbox proven ours, and only once nothing is still in flight.
  - Each obligation is tracked separately: setup links, password rotation, owned and inbound forwarders, the
    catch-all, sessions and app credentials.
  - What has no documented mechanism stays open until the owner accepts an exception. A rotation can never be
    waived (TEST-P5-18).
  - No mailbox or record is deleted; only forwarders the mailbox itself owns are removed. The adapter has no
    delete-mailbox, suspend or domain operation at all, so these hold by construction; a test pins its public
    operations.
- **The staff screen.** One page per application shows approval, creation, verification, setup, activation and
  revocation as separate sections, with each request's blocker and items, and the next action with its owner (TEST-P5-19).
  Managing access never grants reading applicant mail or documents (TEST-P5-20).
- **Refusals outside a test environment.** A real adapter, domain or provider key is refused outside an
  authorized environment (TEST-P5-23).

## 2. Scope: planned, completed, deferred

| Item | Status |
|---|---|
| P4 closeout (TEST-P4-09, 21 evidence, AAR reconciliation, D-46) | done, PR #50 |
| MXroute research correction (the public API at `api.mxroute.com/docs`) | done, `023` section 3 |
| P5 decisions P5-D-1 to D-11 | recorded as D-47 |
| 5B.1 release, approval, creation, verification against the fake | done, PR #53 |
| 5B.2 set-your-own-password and activation | done, PR #54 |
| 5B.3a withdrawal, closure, revocation | done, PR #55 |
| 5B.3b staff screen | done, PR #56 |
| Local backup and restore rehearsal | done, PR #52 (`024`) |
| 5C case map, journey, negative controls, this report | this PR, draft |
| GATE-P5 sign-off | **not done; the owner's decision** |
| Live MXroute adapter, real domain, real limits | **deferred**: separate activation decisions (P5-D-1, D-2, D-4) |
| Other access (LMS, GitHub, Slack) | out of scope (P5-D-7) |

## 3. Architecture and tradeoffs

- **One narrow adapter.** `provisioning.adapter.MailHost` exposes only `read`, `create`, `set_password`,
  `list_forwarders`, `delete_forwarder` and `read_catch_all`. It has no delete-mailbox, no suspend, and no domain or
  reseller operation. The only implementation is the test fake; settings refuse any adapter outside `tests.` and
  any domain outside `.test`.
  - Chose a narrow interface over a general client because a missing operation cannot be called by mistake.
- **Durable intent before every effect.** Every external call is a ledger action with its attempt committed first.
  Unknown is a first-class outcome. Reconciliation reads; it never re-sends.
- **Proof of ownership.** "Ours" means our create succeeded, the checklist creator recorded it, or staff confirmed a
  found mailbox. Revocation depends on that proof.
  - Chose staff confirmation over automatic adoption because a wrong adoption hands someone else's mailbox to an
    applicant, or rotates it.
- **Stop intent is orthogonal to status** (`stop_requested_at`). A stop survives an in-flight create or password
  set and settles when that work ends.
- **The screen only offers; the services decide.** Every action is a CSRF-protected POST to one service that checks
  its own permission. A removed-gate control shows the services still refuse when the screen gate is widened.

## 4. Verification evidence

- **The acceptance map.**
  - `tests/acceptance.py` `P5_CASES` maps all 24 cases.
  - `P5_SUPPORTING` maps the five supporting groups.
  - `conftest.py` reports and gates GATE-P5 like the earlier gates.
  - `test_acceptance` requires the map to equal `023`'s case list, every mapped test to exist, and every test in the
    five P5 files to be mapped (none sits outside the gate).
- **The journey** (`tests/test_p5_journey.py`, TEST-P5-24) runs over real Django HTTP:
  - intake and confirmation run over HTTP, and the P3 decision at the service level;
  - agreements are signed with their webhooks posted over HTTP;
  - the owner's release command runs;
  - staff log in through the admin form, and every staff and applicant POST carries the page's CSRF token through a
    client that enforces CSRF (a POST without it is refused);
  - an unknown create is reconciled and confirmed from the screen;
  - the applicant sets their password through the emailed link;
  - activation sends the welcome;
  - the applicant withdraws through the emailed link;
  - revocation rotates the password, records sessions as unsupported, deletes nothing, and completes only after the
    owner accepts the two exceptions.
- **Negative controls (removed gates):**
  1. With only the proof-of-ownership check (`proven_ours`) removed, the same close rotates someone else's mailbox.
     With it present, that mailbox is never touched (`test_closure`). This control shows the outcome, not a refusal
     reason, and the removed function is used at two places in revocation.
  2. With only the screen gate (`admitted`) removed, a dossier reader reaches the page, and all 13 of the screen's
     actions are refused: 12 by their own service (`not_permitted`), and one because its form names no revocation
     (`invalid_request`). Nothing changes.
- **Full runs.** The pass, fail, skipped and not-run counts and the GATE-S1 to GATE-P5 counts, with the CI run and
  its head, are recorded on the pull request. GATE-P5 has 29 entries: the 24 cases and 5 supporting groups. A
  report filed before its own CI run cannot hold that run's numbers. The owner signs against the run linked there.
- **Reviews.** Each 5B task had one independent QA review and one security review, then fixes and re-checks. The
  merge followed the reviewers' MERGEABLE verdicts and green required checks on the exact head (`safe-merge`). The
  finding counts and dispositions are in `023` sections 12 to 15, and the verdicts are on each pull request.
- **Independent traceability review (5C).** It rated the cases against their "Must show" text and found TEST-P5-22
  weak, with ten other cases partial. The gaps that tests could close were closed (`023` section 16). What stays
  partial is listed below.
- **Restore rehearsal.** The local backup and restore of the database with the custody files was rehearsed and
  verified (`024`, PR #52).

**What the passing cases still do not show** (partial clauses after the traceability review):

| Case | Clause not shown |
|---|---|
| TEST-P5-02 | Boundaries are driven for pause and hard bounce. A custody, details or contact change is shown only at release and create. |
| TEST-P5-04 | That the welcome is queued in the activation transaction is shown by design and by "no activation without an approved template", not by a direct assertion. |
| TEST-P5-06 | A collision is checked against reservations and the reserved list. **The host's mailboxes and forwarders are not checked before the create's absent read** (P5-D-1 names them). OWNER: build the check, or accept the absent read for synthetic work. |
| TEST-P5-07 | A prerequisite change between the page and the POST is caught as `prerequisites_changed`, not as `changed_since_shown`. |
| TEST-P5-10 | Concurrency is shown by database constraints and duplicate actions, not by two workers racing. |
| TEST-P5-12 | An accepted SMTP message is never used as evidence by design. No test makes SMTP succeed while the read says absent. |
| TEST-P5-15 | The full database scan runs after the successful path. Rejected and unknown paths are checked in logs and pages only. |
| TEST-P5-17 | The in-flight password set is simulated by inserting its state directly. |
| TEST-P5-23 | The refusals are tested in `guards` directly, not through Django's start-up check. |

**Also not shown:**

- **Live MXroute.** The operations follow the public OpenAPI document read on 2026-10-18 (schema digest recorded in
  `023` section 3). Real behaviour is NOT VERIFIED:
  - status codes;
  - whether forwarder listing is complete (pagination);
  - what happens when a forwarder and a mailbox share a name;
  - rate limits;
  - whether a password can be read back.
- **Sessions and app credentials.** No documented revocation exists, so these stay `unsupported` until the owner
  accepts an exception. Rotation is "applied, cannot be read back".
- **A verified shared forwarder or catch-all** is a point-in-time read.
- **Production access.** There is no MFA, network restriction or throttle on the staff screen or on `/withdraw/`
  (POL-13 at the staging gate). There is no browser or accessibility check.
- **Scale.** There is no load or multi-worker soak.
- **The withdrawal link's lifetime** and any notice after a withdrawal are open owner questions (`023` section 14).

## 5. Issues and root causes

- **5B.1:** reviews found three QA HIGH and one security HIGH (`023` section 12).
  - A 429 after the create was sent could have freed an address while a mailbox might exist.
  - A prerequisite change since the P4 hand-off was not bound into the new approval.
  - A pause was missing from some effect boundaries.

  Root cause: "the create was rejected" and "the outcome is unknown" were not told apart, and the boundary checks
  were not uniform. Fix:
  - a 429 or 5xx after sending is unknown and reconciled by reading;
  - release binds today's snapshot;
  - every boundary includes the pause.
- **5B.2:** one security HIGH and four QA HIGH (`023` section 13). The setup link's recipient was not re-checked at
  redemption, an unused link could end silently, and a refused activation could not be retried. Root cause: the
  link was trusted from the moment it was sent. Fix:
  - the recipient is re-checked at GET and POST;
  - expiry opens a bounded new series or a staff reissue;
  - activation re-checks everything and can be retried with a reason.
- **5B.3a:** one QA BLOCKER and four HIGH, plus one security HIGH.
  - "Not applicable" could be written before a late mailbox landed and then frozen, so the rollup reported a false
    "complete".
  - Revocation could act on a mailbox not proven ours.

  Root cause: revocation read a point-in-time state, not a settled one. Fix: act only on a proven-ours mailbox on a
  settled request, where settled means no open create, reconcile or watch. The re-check found the watch was queued
  but not yet counted as unsettled, and that was fixed too.
- **5B.3b:** three QA HIGH issues (PR #56 review; `023` section 15). Release after a close, and the decision on a late mailbox, were unreachable from
  the screen, and the checklist path named the wrong owner. Root cause: the screen's offers were written separately
  from the service guards. Fix: the offers mirror the guards, and a status-by-method table test pins them.

## 6. Lessons learned

- **A rollup is only as honest as its settle rule.** "Every row is final" is not "complete" while work is in flight.
- **Write the screen's offers from the services' guards, not from memory.** The first version drifted in five
  places.
- **Unknown is an outcome.** Every external effect needs its own unknown path with a read-based reconciliation.

## 7. Operational impact, including cost

- **No provider cost.** Only the local fake was used; no credential was read.
- **New tables:**
  - address reservations;
  - provisioning requests, attempts and evidence;
  - credential setups;
  - access revocations;
  - withdrawal confirmations.

  Every record of what happened is protected history (append-only triggers).
- **New settings,** all test-only or empty by default:
  - `CATALYST_PROVISIONING_*`, with the adapter and domain refused outside test;
  - `CATALYST_SETUP_*`.
- **Nothing deployed.**

## 8. Rollback procedure and validation

On synthetic data only:

1. Revert PRs #56, #55, #54 and #53 in that order.
2. Reverse the `provisioning` migrations 0006 to 0001.
3. Reverse correspondence 0016 (the welcome kind and its draft template).

The P4 hand-off stays held, as it was before P5. A full P5 rollback was not rehearsed, because no real data exists.

## 9. Next steps

**GATE-P5 sign-off statement (proposed here; accepted by the owner on 2026-10-18, D-48):**

> "I accept GATE-P5 for synthetic P5 at the final head of the 5C pull request, on its CI run (the run, head and gate
> counts are linked on the pull request; a passing case means its mapped tests passed, with the limits in section
> 4), and the owner decisions in `023` section 8 (D-47). This is not a live-provider proof. It does not authorize a
> live MXroute adapter or key, a real domain, real limits, real mailboxes or passwords, real applicant data, real
> role grants, a release or a deployment. Sessions and app credentials have no documented revocation and stay
> unsupported until an exception is accepted case by case."

**Before any live use** (each a separate owner decision):

- the production domain and limits, after the account's capacity is verified (P5-D-1, D-2);
- the live adapter's privilege separation and key custody (P5-D-4, D-6);
- the live checks listed in section 4;
- the withdrawal link's lifetime and any notice after withdrawal (`023` section 14);
- POL-10 (retention and deletion) and POL-13 (staff MFA and network restriction);
- the production blockers in `024`.
