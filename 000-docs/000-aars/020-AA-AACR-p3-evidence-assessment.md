# 020-AA-AACR — P3 evidence, assessment and qualification decision after-action report

> P3 is the stage where Catalyst v2 decides whether an applicant joins the programme. It collects what the
> applicant claims and what approved sources show, asks a model for an advisory reading of exactly that evidence,
> lets staff ask clarifying questions, and records a decision only a named human may make. Everything here ran on
> synthetic data and PydanticAI test models: no live model was called and no real applicant was involved.

- **Status:** built; the full local run passes every case; CI on the closeout head and the 3C review's re-check
  come before the owner's sign-off (proposed statement in section 9).
- **Lane:** full. Every task had review findings and fixes (section 5).
- **Epic:** Collect evidence, run the bounded MiniMax assessment, and record the authorized qualification decision
  (bead `catalyst-v2-oc4`).
- **Acceptance test:** every case TEST-P3-01 to TEST-P3-57 in `018` section 9, plus the D-35 supporting groups,
  PASS at one head on PostgreSQL in a full run, with GATE-S1 and GATE-P2 still PASS.
- **GitHub:**
  - specification: PR #28 (`47f6afd`); the selection-quality contract: PR #33 (`0cc9e6b`);
  - 3B.1: PR #30 (`d564bfa`); 3B.2: PR #32 (`8086508`); 3B.3: PR #34 (`2bb3281`); 3B.4: PR #35 (`25603b0`);
  - 3C: PR #36.
- **Period:** 2026-10-13 to 2026-10-17
- **Author:** Jeremy Longshore. Claude Code implemented the work; the Catalyst specialist subagents reviewed it.
- **Template:** 000-AA-TMPL v1.0.0

## 1. Summary and business value

P3 turns an application into a decision that can be explained afterwards. Staff can now see, for one applicant:

- **Claims and observations** (3B.1). What the person says, beside what an approved, deterministic check found,
  including "unavailable" and "cannot prove", with every outbound fetch behind a request-forgery pipeline. No model
  is involved at this step.
- **An advisory assessment** (3B.2). A bounded model reading of one frozen snapshot of that evidence. Every quote
  must be found verbatim in what was sent; every failure goes to staff, never to an adverse outcome; budgets are
  counted before any call; live models are refused in three layers.
- **Clarification** (3B.3). Questions that name the criterion and the evidence gap they address and offer an
  alternative route, sent only after an operator approves them. Replies get an advisory reading, staff confirm every
  outcome, and confirmed answers feed a bounded reassessment.
- **The decision** (3B.4). Only a person explicitly granted the authority may record admit, decline or hold, and only
  on the inputs they saw. The decision records a per-criterion rationale with capability and strength of evidence
  kept separate, and the selection policy it applied. A database trigger refuses any decided stage without a
  decision row in the same transaction. It guards against code paths and stray writes, not against a compromised
  application role, which could insert a decision row itself.

The owner also approved how selection quality is governed and improved (`019`, D-35), and P3 implements its rules:
evidence gaps and alternative routes on questions, the rationale, the policy reference and a human-only assessment
path.

**What GATE-P3 does not show.** It proves software, permissions, provenance and workflow. It is **not** a validation
of selection quality: whether the assessment helps anyone choose well is the synthetic evaluation 3E and, later,
the pilot (`011` section 11, `019` sections 7 to 9).

## 2. Scope: planned, completed, deferred

**Planned and completed** (`018` section 10): 3A specification; 3B.1 evidence; 3B.2 assessment; 3B.3 clarification;
3B.4 decision; 3C verification (this report and the acceptance map).

**Deferred, each with its home:**

- **Live model use and 3E** (the synthetic evaluation): the live-call protections (`catalyst-v2-oc4.9`) and the
  evaluation set (`catalyst-v2-f1u.3`) come first; 3E itself is `catalyst-v2-oc4.7`.
- **What clears a capped snapshot:** owner decision, `catalyst-v2-oc4.8`.
- **Real sources, notices, retention:** POL-03, POL-17 and POL-10 at GATE-PILOT; the correction beads
  `catalyst-v2-9kg.1` to `.3` before real use.
- **The decision authority itself:** POL-05. Until the owner records it, nobody can decide (by design).
- **Comparable core questions and the first selection policy:** `catalyst-v2-f1u.2` and `.6`.
- **P4 hand-off:** admit and decline create held actions that nothing runs yet.
- Smaller deviations are listed in `018` sections 13, 14, 16 and 17.

## 3. Architecture and tradeoffs

- **Four separate records** (`018` section 1): claim, observation, model assessment, decision. None silently becomes
  another; each names what it cannot prove.
- **Frozen snapshots and digests.** A run is bound to one manifest digest; a decision is bound to the digest of what
  the decision-maker saw (snapshot, question set, run). Any change refuses rather than guesses.
- **Advice never chooses a transition.** A successful run moves the stage to `awaiting_decision` whatever it says;
  a static test bans output fields from control flow. Chose this over "auto-hold on a negative reading" because a
  model must never be able to move a person's case.
- **Layering by seams.** `correspondence` reaches `assessments` only through code-fixed dotted paths pinned by a
  start-up guard (the P2 `CATALYST_ATTENTION_OPENER` pattern), so P2 code never imports the model layer.
- **One question screen** in `correspondence`, shared by model proposals and staff questions.
- **The backstop trigger** compares the decision row's `created_txid` with the current transaction. Chose this over
  `xmin` (a savepoint gives a row its own transaction id) and over a timestamp (Django's `Now()` is the statement
  time): both failed in the first implementation.
- **Fail closed everywhere a policy is open:** daily budget 0, model "none", reply interpretation off, decision
  authority None.

## 4. Verification evidence

- **The acceptance map.** `tests/acceptance.py` `P3_CASES` maps all 57 cases to 120 test references; `P3_SUPPORTING`
  maps the three D-35 groups to 9 more. `conftest.py` reports and gates them like GATE-S1 and GATE-P2.
- **Local full run** (`scripts/test.sh`, pinned Python 3.14.8 and PostgreSQL 16.15, 2026-10-17): **846 passed** in 946 s; GATE-S1 PASS 25, GATE-P2 PASS 54, **GATE-P3 PASS 60** (the 57
  cases and the 3 D-35 groups); FAIL 0, INCOMPLETE 0, NOT RUN 0; nothing skipped.
- **CI:** the "Runtime checks" job on this closeout's head, linked from the pull request.
- **Reviews per task.** Every 3B task had one primary independent QA review plus one scoped specialist review
  (model boundary for 3B.2 and 3B.3, security for 3B.4), a fix-up, and a re-check of both. Dispositions are in
  `018` sections 14, 16 and 17 and on each pull request.
- **3C review.** One independent QA review of this closeout. It rated 39 cases proven, 17 partial and 1 weak on
  the first map. TEST-P3-08 and the TEST-P3-51 re-fetch clause gained tests; 19, 20, 27, 49 and 50 were tightened.
  What the remaining partial cases do not show is below.

**What the passing cases do not show** (a passing case means its mapped tests passed, not that every clause is
proven):

| Case | Not shown by the mapped tests |
| --- | --- |
| TEST-P3-06 | a staff item for a transient failure that later succeeds |
| TEST-P3-12, 16 | that the connection goes to the validated address and that no proxy is used, beyond the pinned fixture |
| TEST-P3-15 | one unicode-query instance passes whether the fetch refuses or not |
| TEST-P3-21 | a foreign capture injected into a manifest (the manifest only reads the application's own rows) |
| TEST-P3-24 | the role-marker half of the injection flags |
| TEST-P3-29 | canaries in notes, headers and non-application identifiers |
| TEST-P3-30 | that no key is read (none exists in the settings) |
| TEST-P3-33 | old runs kept intact across a pack change, beyond the result-once trigger |
| TEST-P3-43 | a stale run on an older adopted version (only one adoption is reachable) |
| TEST-P3-45 | a forced overlap of the two concurrent decisions |
| Logs (018 3.3 step 9) | "logs hold host and code only": fetch code logs nothing today, so the clause is untested |

## 5. Issues and root causes

The most serious findings, by task, and their root causes:

- **3B.1:** the request-forgery pipeline needed a deadline over the whole fetch and refusal of every private,
  link-local or reserved address after each redirect (`018` section 13). Root cause: per-step checks alone. Fix: one
  pipeline that validates every hop and pins the connected address.
- **3B.2:** unfenced applicant claims could forge prompt structure; name scrubbing could invent "the page names the
  applicant"; a one-character quote passed. Root cause: free text was treated as structured. Fix: fence, normalize
  and scrub every untrusted text; minimum-substance quotes.
- **3B.3:** a reply repeating our own question unquoted could make our words the applicant's answer. Root cause:
  only quoted text was excluded. Fix: one own-text helper used everywhere text leaves or is cited.
- **3B.4:** once a live model is configured, a confirmed answer in the last round or the run cap could leave an
  applicant with no possible decision. Root cause: the human-only path was gated on the model setting rather than on
  "no valid run is coming". Fix: widened, with tests for each path.
- **Test infrastructure:** PydanticAI runs a scripted model in another thread, so test hooks using the ORM there
  leaked connections; the runtime CI job outgrew its 10-minute limit (raised to 20, profiling filed as
  `catalyst-v2-egz`).

## 6. Lessons learned

- **Review on a stable tree.** One review read a file changing under it; afterwards reviews waited for a stable
  tree, which removed the confusion.
- **A test must prove its clause.** The backstop's first test would have passed with the key clause deleted; the
  negative-case tests fixed that.
- **Fail closed, then record the owner decision.** Several findings were policy, not code (repeat-submission
  stalls, erasure of decision text); recording them with the default kept avoided silent policy-making.

## 7. Operational impact, including cost

- **No model cost:** test models only; the daily budget defaults to 0.
- **New tables:** evidence sources, items and captures; assessment runs and invocations; reply interpretations;
  qualification decisions. All synthetic. Captures and decisions are append-only history; runs and
  interpretations are frozen once finished (result written once).
- **Test time:** the full run takes about 13 to 16 minutes locally; the CI runtime job's time is cited on the
  closeout pull request (its limit is 20 minutes).
- **Nothing deployed.**

## 8. Rollback procedure and validation

Revert the P3 pull requests in reverse order and reverse the `assessments` and `correspondence` migrations added in
P3, on synthetic data only. Reversal of the protection migrations is exercised by the existing migration tests
(`tests/test_db_roles.py`); a full P3 rollback was not rehearsed (no real data exists).

## 9. Next steps

**Proposed GATE-P3 sign-off statement for the owner:**

> "I accept GATE-P3 for synthetic P3 at main after PR #36, on the CI run of PR #36's final head (run id on the PR) with GATE-S1 25/25,
> GATE-P2 54/54 and GATE-P3 60/60 (the 57 cases and the 3 D-35 groups; a passing case means its mapped tests
> passed, with the limits in section 4), and the deviations and owner decisions in `018` sections 13 to 18.
> This is not a validation of selection quality and does not authorize live model use, real fetching, real applicant
> data, release or deployment. POL-05 must be recorded before anyone can decide; the correction beads, POL-10 and
> the live-call protections come before real use."

Then: the owner decisions listed in `018` section 18; the live-call protections and the evaluation set before 3E;
P4 specification when released.
