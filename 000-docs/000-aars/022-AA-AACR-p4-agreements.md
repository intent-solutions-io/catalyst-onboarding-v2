# 022-AA-AACR — P4 agreements after-action report

> P4 is the stage where an admitted applicant signs the agreements Catalyst needs before access is provisioned:
> first the NDA, then the User Agreement. Catalyst issues each one through Documenso and verifies that it is
> complete. It keeps its own verified copy, and only then hands the applicant to provisioning. Everything here ran
> against a local fake of the installed Documenso version, on synthetic data. No real envelope, agreement text,
> applicant or provider credential was used.

- **Status:** GATE-P4 signed off by the owner on 2026-10-18 (D-45 in `011`), on CI run 39103156421 at head
  `f11ca36` (1000 passed; GATE-S1 25, GATE-P2 54, GATE-P3 60, GATE-P4 40), accepting the statement in section 9 and
  its limits.
- **Lane:** full. Every task had review findings and fixes (section 5).
- **Epic:** "Issue and verify the NDA, User Agreement and other required agreements through Documenso with protected
  custody" (bead `catalyst-v2-hdg`).
- **Acceptance test:** at one head, in a full run on PostgreSQL, every case PASS. That covers TEST-P4-01 to
  TEST-P4-32 in `021` section 12, and the supporting groups (D-41 to D-44, the hardening 9kg.1 to 9kg.3, and the
  removed-gate controls). GATE-S1, GATE-P2 and GATE-P3 must still PASS.
- **GitHub:**
  - specification: PR #37;
  - 4B.1: PR #38; 4B.2: PR #39; recovery corrections and D-41 to D-44: PR #42; 4B.3: PR #43;
  - hardening: #44 (9kg.1), #45 (9kg.3), #46 (9kg.2);
  - suite profiling #40 and release correction #41;
  - 4C: PR #47 (this report; a draft until the owner signs off).
- **Period:** 2026-10-17 to 2026-10-18
- **Author:** Jeremy Longshore. Claude Code implemented the work; the Catalyst specialist subagents reviewed it.
- **Template:** 000-AA-TMPL v1.0.0

## 1. Summary and business value

For one admitted applicant, staff can now see and trust:

- **Issue.** An NDA instance and its key are committed before any provider call. Create and distribute are never
  sent twice. An uncertain outcome is reconciled on admissible evidence or goes to a decision-maker, never to a
  blind retry (4B.1).
- **Signing.** Signing counts as verified only after a fresh provider read. A webhook is a hint that brings that
  read forward. The database refuses `signing_complete_verified` without a read recorded in the same transaction.
  The User Agreement cannot exist before the NDA is verified: that rule is enforced in services and in a database
  backstop (D-15). Decline, expiry, cancellation, withdrawal and holds each have a defined, tested outcome (4B.2,
  D-41 to D-44).
- **Custody.** Catalyst stores its own copy of the signed PDF and verifies it, as a fact separate from signing. A
  custody failure leaves signing verified and blocks only progression. Retrieval is permissioned and audited
  before any byte is released (4B.3).
- **Hand-off.** After the last gate, the stage is `agreements_complete`. Exactly one held `provision` action exists,
  bound to the exact prerequisites. Nothing runs it until P5.

The hardening batch closed three correspondence gaps that P4 relies on:

- correspondence evidence is append-only for every role (9kg.1);
- an unresolved hard bounce blocks every send, the S1 verification email included (9kg.3);
- a system safety pause needs decision-maker review and an addressed cause (9kg.2).

**What GATE-P4 does not show:** section 4, "Cannot yet be demonstrated".

## 2. Scope: planned, completed, deferred

**Planned and completed** (`021` section 13):

- the 4A specification;
- 4B.1, 4B.2, the recovery corrections, 4B.3;
- 4C (this report, the acceptance map, the HTTP journey and the negative controls).

**Deferred, each with its home:**

- **Live provider.** A credentialed Documenso check and canary need their own authorization (D-41, `021`
  section 17).
- **Real templates, the agreement inventory and countersigning:** POL-07 and POL-08, with counsel.
- **Custody, retention and details policy:**
  - POL-09: location, encryption, backup, replacing a corrupt copy;
  - POL-10: retention and erasure for every append-only table;
  - POL-18: the production field list, and whether the recorder may also confirm.
- **Provisioning:** P5 (`023`, prepared, not approved). P5 must re-check every prerequisite when it releases the
  held action.
- **Follow-up hardening beads:** freezing inbound provenance and identity columns; a database guard on the pause
  row.

## 3. Architecture and tradeoffs

- **Three statuses, never merged:** issue, signing and custody. Chose this over one lifecycle field because "signed
  at the provider" and "we hold a verified copy" fail independently and are recovered differently.
- **A webhook is a hint; the read is the authority.** It costs one read per completion. That buys immunity to
  forged, duplicated, reordered or lost webhooks.
- **Database backstops beside the services:**
  - the verification-needs-a-read trigger;
  - D-15;
  - append-only observations, documents, accesses and details;
  - frozen approved templates.

  These guard against code paths and stray writes. They do not guard against a compromised owner role.
- **Protective work runs while paused.** Reads, reconciliation, custody and cancellations are not automated kinds.
  Issue and progression are.
- **No silent repair:**
  - a corrupt stored copy goes to staff;
  - a changed recipient set after verification holds reliance until a reasoned resolution (D-43);
  - a retry never replaces a stored copy.

## 4. Verification evidence

- **The acceptance map.**
  - `tests/acceptance.py` `P4_CASES` maps all 32 cases to their tests.
  - `P4_SUPPORTING` maps D-41 to D-44, 9kg.1 to 9kg.3 and the three removed-gate controls.
  - `conftest.py` reports and gates GATE-P4 like the earlier gates.
  - `test_acceptance` requires the map to equal `021`'s case list and every mapped test to exist.
- **The journey** (`tests/test_p4_journey.py`) runs over real Django HTTP:
  - intake and confirmation run over HTTP; the P3 decision runs at the service level (scripted model);
  - staff log in through the admin form, with CSRF enforced on every staff POST;
  - each webhook is posted over HTTP with the secret and is asserted to be only a hint;
  - the default signing-and-custody gate is used for both agreements, with no signing-only override, and custody
    is verified before the User Agreement is created;
  - an audited download is refused without CSRF, then served as a private PDF attachment;
  - a forged webhook gets 401 and changes nothing;
  - a duplicate callback adds no second hand-off.
- **Negative controls (removed gates):**
  1. With no service involved, the database refuses a verified status without a fresh read. The test asserts the
     trigger's own message.
  2. With every service gate bypassed, a User Agreement is refused by D-15 while the NDA is complete at the provider
     but unverified.
  3. With custody unavailable, nothing advances. With the custody half of the gate removed, the same state
     advances: the gate is load-bearing.
- **CI full run.** The "Runtime checks" job of run 39101605672, at head `ced9d16`, took 10 min 7 s for the job and
  576 s for pytest. Results:
  - **1000 passed**; nothing failed, skipped or deselected;
  - GATE-S1 PASS 25, GATE-P2 PASS 54, GATE-P3 PASS 60;
  - **GATE-P4 PASS 40** (the 32 cases and the 8 supporting groups);
  - FAIL 0, INCOMPLETE 0, NOT RUN 0.

  This report's commit changes documentation only. Its own CI run is linked on the pull request.
- **Local full run.** `scripts/test.sh` at `fb8c202` (before the QA fixes; pinned Python 3.14.8 and PostgreSQL
  16.15) took 888 s: 999 passed, with the same gates all PASS.
- **Reviews.**
  - Each 4B task and each hardening PR had one independent QA or security review, then fixes and a re-check. Their
    dispositions are in `021` sections 15 to 18 and on each pull request.
  - **4C final QA review:** 25 cases rated proven and 7 partial, none weak. It found that control 2 tripped the
    fresh-read check instead of D-15, that the journey's webhook was not causal, and that the default gate was not
    pinned. All three were fixed, and TEST-P4-05, 06 and 24 gained visibility and rendering evidence.
  - **Final security review:** no blocker for a synthetic sign-off. Four production limits are carried (below).

**What the passing cases still do not show.** The final QA review rated seven cases partial: 04, 05, 06, 09, 22, 24
and 25. Their dispositions (reconciled after sign-off, in the P4 closeout follow-up):

| Case | Partial clause | Disposition |
|---|---|---|
| TEST-P4-04 | the checksum re-verified on retrieval | closed in 4C: the tamper test is mapped |
| TEST-P4-05 | visibility limited to named roles | closed in 4C: `test_p4_details_are_visible_only_to_those_who_confirm_them` |
| TEST-P4-06 | the User Agreement not shown or linked before the NDA's gate | closed in 4C: the journey asserts it |
| TEST-P4-09 | a non-admitted application, and held actions of other kinds | closed in the follow-up: `test_p4_09_activation_refuses_a_non_admitted_application_and_never_releases_other_held_kinds` |
| TEST-P4-22 | "no burst" for creates across many paused applications | **open, a pre-live limit**: only coalesced reads are shown; cross-application create and send rates are not claimed |
| TEST-P4-24 | tokens and links never rendered on the screen or in the PDF response | closed in 4C: the journey asserts it |
| TEST-P4-25 | the "application is paused" clause | closed in 4C: the pause test is mapped |

Three cases QA rated proven carry accepted notes:

- **TEST-P4-08:** constant time is shown as "every secret is compared with `compare_digest`". Whole-request timing
  is not measured or claimed.
- **TEST-P4-20:** only the refusals are tested, because no authorized live environment exists.
- **TEST-P4-21:** escaping was first tested on the display name only. The follow-up adds hostile required-details
  values and a hostile typed reason on a refusal screen.

**Cannot yet be demonstrated:**

- **Live Documenso.** Payload shapes and the download contract were INSPECTED from the public source at the
  installed version. The download's binary behaviour, provider email suppression (D-41), real TLS, rate limits and
  webhook delivery are NOT VERIFIED.
- **Real documents.** Templates are placeholder PDFs, there is one item per template, and there is no countersigning.
- **Production ingress.** The webhook route is mounted only in test and development. There is no proxy, real
  listener, MFA or network restriction.
- **Scale.** There is no load or multi-worker soak. Floods are sequential.
- **Operations.** No backup or restore of the custody directory has been run, and no browser or accessibility check.
- **P5.** The held action has no handler.

## 5. Issues and root causes

- **4B.1:** a crash after the exchange could have resent. Root cause: "unknown" was not a first-class outcome. Fix:
  an attempt record committed before the call, then reconciliation before any retry.
- **4B.2:** a webhook could have verified signing on its own. Root cause: trusting the push. Fix: a fresh read, plus
  the database trigger.
- **Recovery (PR #42):**
  - replace-after-stop could issue again;
  - a withdrawal could be downgraded to a resumable hold;
  - a completion after a cancel could reissue.

  Root cause: stop intent was not durable. Fix: `cancel_requested_at`, final stops, and the D-42 to D-44 rules.
- **4B.3:**
  - a corrupt copy wedged custody at `pending`;
  - an NDA that needed details deadlocked.

  Root causes: an insert-only record met a retry, and the stage check came before the details. Fix: no silent
  replacement; details are allowed at `admitted`.
- **9kg.2:** the first rule would have locked declined, expired and cancelled agreements in a permanent pause.
  Root cause: those causes had no resolution path. Fix: a reasoned decision-maker resolution, and a coverage test
  that ties every pause reason to a cause and a resolution.
- **4C:** the first negative control named the wrong gate. Root cause: the outcome was asserted, not the reason. Fix:
  each control now asserts the refusal that proves its gate.

## 6. Lessons learned

- **Assert the reason, not only the outcome.** Two controls passed for a reason other than the one they named.
- **Every new block needs its unblock path in the same change** (the 9kg.2 blocker).
- **A hint is not evidence.** Treating provider pushes as hints removed a whole class of ordering and forgery cases.

## 7. Operational impact, including cost

- **No provider cost.** Only the local fake was used; no credential was read.
- **New tables:** agreement types and template versions; instances, recipients, attempts and observations; stored
  documents and accesses; details versions. Every record of what happened is protected history.
- **New settings,** all test-only or empty by default: the agreement provider and timings, custody storage, required
  details, and `CATALYST_HARD_BOUNCE_RECHECK_SECONDS`.
- **Test time:** see the CI run above. The suite was profiled and shortened by a quarter in PR #40.
- **Nothing deployed.**

## 8. Rollback procedure and validation

On synthetic data only: revert the P4 pull requests in reverse order, then reverse the `agreements` migrations and
correspondence 0015. Migrations 0005 and 0006 refuse to reverse once their columns are used, by design. The
migration tests exercise reversal of the protection migrations. A full P4 rollback was not rehearsed (no real data
exists).

## 9. Next steps

**Proposed GATE-P4 sign-off statement for the owner:**

> "I accept GATE-P4 for synthetic P4 at the final head of PR #47, on its CI run (run 39101605672 at `ced9d16` showed
> 1000 passed with GATE-S1 25/25, GATE-P2 54/54, GATE-P3 60/60 and GATE-P4 40/40; the final head is linked on the
> pull request; a passing case
> means its mapped tests passed, with the limits in section 4), and the deviations and owner decisions in `021`
> sections 15 to 18. This is not a live-provider proof. It does not authorize real templates, real signing, real
> applicant data, provider credentials, provisioning, a release or a deployment. POL-07, POL-08, POL-09, POL-10 and
> POL-18 come before any real agreement. The four production limits are carried and are not accepted for real use:
> the pause row has no database guard; custody is plaintext on local disk; records cannot be erased; and the webhook
> has a shared secret with no production secret path."

Then:

- the P5 decisions in `023` section 8;
- the production blockers in `024`;
- the follow-up hardening beads.
