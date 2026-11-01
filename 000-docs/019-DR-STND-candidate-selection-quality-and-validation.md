# Candidate Selection Quality and Validation

| Field | Value |
|---|---|
| Document | `019-DR-STND-candidate-selection-quality-and-validation` |
| Version | 1.0.0 (approved; 0.1.0 was the review draft) |
| Status | **APPROVED by the owner 2026-10-14 (D-35 in `011` section 4: "approve 019 and merge 33").** This is the governing contract for selection quality. The role profile (section 4) and `SP-L2-1` remain drafts until completed and activated; the items in section 13 marked open remain open. The approval authorizes no code, release, live model call, real applicant data, deployment or policy activation. |
| Owner | Jeremy Longshore (approver) |
| Date | 2026-10-14 |
| Baseline | main `8086508` (3B.2 merged) |
| Authority hub | `011` section 11 (who owns selection quality, how it changes, how it maps to the phases); decision D-35 |
| Classification | Public. Policies and synthetic examples only. Real case reviews, evaluation answers and restricted material never enter this repository (section 12). |

## 0. How to read this document

This document answers one question: **how do we know the standard we select people by is the right one, and what
do we do when it is not?** It defines selection methods and the validation protocol. It does not decide anything.

Each fact has one home:

| Fact | Home |
|---|---|
| Who owns selection quality, who may change the standard, which milestone needs what | `011` section 11 |
| What a person is assessed for, the criteria, the evidence rules, the policy record, the evaluation and the scorecard | this document |
| How the software carries a policy version, the P3 boundaries, what 3B.3, 3B.4, 3C and 3E build or prove | `018` section 15 |
| Requirements, measures and their acceptance references | `002` (REQ-035 to REQ-039, MET-11) |
| Task status, dependencies and delivery evidence | Beads (epic "Improve candidate selection through a versioned standard, a small evaluation and operational feedback") |

Status labels used here, so approved direction is never confused with a suggestion:

| Label | Meaning |
|---|---|
| **APPROVED DIRECTION** | an owner decision recorded in `011` section 4 (named) |
| **PROPOSED** | this document's recommendation; binding only after owner approval |
| **IMPLEMENTED** | present in code on `main` (named) |
| **DEMONSTRATED** | shown by a test or a run (named) |
| **UNRESOLVED** | a question only the owner, a domain expert or counsel can answer |

## 1. Where we stand

| Item | Status |
|---|---|
| Model output is advisory and never authorizes a transition | APPROVED DIRECTION (D-04) |
| Fixed criteria per rubric version, a rating per criterion, an advisory recommendation, no numeric score | APPROVED DIRECTION for synthetic P3 (D-34, `018` P3-D-4) |
| Model-proposed questions are never sent until staff approve each one | APPROVED DIRECTION for synthetic P3 (D-34, P3-D-5) |
| No qualification decision without a valid assessment | APPROVED DIRECTION for synthetic P3 (D-34, P3-D-10), **amended by D-35**: a recorded human-only assessment is allowed when model advice is unavailable or suspended (section 7) |
| A five-criterion synthetic rubric (`work_quality`, `contribution`, `credential_support`, `purpose_fit`, `consistency`), prompt pack `assessment_v2`, output schema 2 | IMPLEMENTED (3B.2, PR #32); **synthetic, not a production standard** |
| Each run records its snapshot digest, adopted version, prompt pack and digest, rubric version, schema version, model identifier and library version; each evidence capture records its derivation version | IMPLEMENTED; run provenance DEMONSTRATED by TEST-P3-01 and TEST-P3-08 (`tests/test_assessment.py`), the derivation version by `tests/test_evidence.py` (TEST-P3-17) |
| Claims are citable, and a rating resting on claims alone is capped at `partly_supported` | IMPLEMENTED as a default awaiting the owner's POL-04 decision (`018` section 14) |
| What role a person is selected for; the production rubric; the evidence rules for real candidates; notices, alternatives and correction | UNRESOLVED (POL-03, POL-04, POL-05, POL-17) |
| Whether any assessment predicts later delivery quality | UNRESOLVED; unknowable until after a pilot (section 7) |

## 2. Source basis and our adaptations

Sources read on 2026-10-14. The left column paraphrases what each page states; the right column says what this
document adapts from it. **Nothing here claims compliance with these sources, certification, predictive
validity or a universally best rubric.** OPM pages describe United States federal hiring practice; they are used
as method guidance, not as procedures we follow.

| Source (accessed 2026-10-14) | What it states (paraphrased) | Our adaptation |
|---|---|---|
| OPM, Job Analysis (`https://www.opm.gov/policy-data-oversight/assessment-and-selection/job-analysis/`) | Job analysis is the foundation of assessment: it identifies the tasks of a job and the competencies those tasks need, and documents their link, which supports job-relatedness | Section 4: define the first delivery role's tasks and outcomes before criteria; each criterion names the work outcome it matters to (section 5) |
| OPM, Structured Interviews (`…/other-assessment-methods/structured-interviews/`) | Structure means rules for asking, observing and rating; the most structured form asks every applicant the same questions and rates answers against proficiency benchmarks; behavioural (past behaviour) and situational (what would you do) questions; panel members rate individually before discussing discrepancies | Comparable core questions within a role, behavioural anchors per criterion (section 5), independent human ratings before discussion in the evaluation (section 8) |
| OPM, Work Samples and Simulations (`…/other-assessment-methods/work-samples-and-simulations/`) | Tasks representative of the job give strong content validity and are seen as fair; trained assessors rate them; they cost time to build and maintain; the return is lower when the skill can be taught after entry | Bounded work samples only for skills needed at entry; skills learnable after entry are not screened for (section 4); no unpaid client work |
| SIOP, recommendations for AI-based assessments (`https://www.siop.org/post/siop-releases-recommendations-for-ai-based-assessments/`; a summary post, not the full document) | AI-based assessments used for selection deserve the same scrutiny as traditional tests: evidence that results relate to job performance, consistency, fairness, and documentation of development and scoring for audit | Versioned policy record with validation evidence (section 6), repeatability checks (section 8), documented changes; we do not claim predictive validity |
| NIST AI RMF Playbook, MEASURE (`https://airc.nist.gov/airmf-resources/playbook/measure/`; read in part) | Establish ways to detect and track risks, errors and incidents; reassess metrics and controls over the lifecycle; document test sets and metrics so testing can be repeated; seek feedback from affected people | The scorecard (section 9), a versioned evaluation set (section 8), candidate-experience measures |
| NIST AI RMF Playbook, MANAGE (`https://airc.nist.gov/airmf-resources/playbook/manage/`) | Plan responses to risks (mitigate, transfer, avoid, accept); document residual risk; be able to respond to unknown risks and deactivate systems; preserve material for review; record and respond to reported incidents and near misses | Suspension, rollback and investigation rules (section 10), an incident log of affected cases |

Not done: no vendor survey, no framework comparison, no reproduction of licensed assessment material.

## 3. What a person is selected for (assessment purposes, approved D-35)

Three purposes, ordered by the responsibility they lead to. They are **assessment purposes, not implemented
tracks**, automatic entitlements, certifications or legal statuses. Admission under one purpose never implies
another.

| Purpose | Responsibility that follows | What the assessment must establish | What it must not demand |
|---|---|---|---|
| L1. Participation | joins learning and community activities; no client work | interest, good faith, the ability to follow the programme's rules | prior delivery experience, a public portfolio, credentials |
| L2. Supervised delivery | works on client delivery under a named supervisor who reviews work before it reaches the client | enough evidence on the section 5 criteria at L2 to be trusted with reviewed work | independent client responsibility; skills the supervisor can teach |
| L3. Independent delivery | delivers to a client with no pre-delivery review | L3 evidence on every required criterion, including verification and safety | anything not tied to section 5 |

The first delivery role (section 4) is L2. L3 is not designed here; it needs its own role profile and approval.

## 4. The first delivery role: supervised delivery (L2), draft skeleton

**UNRESOLVED until the owner and a domain expert fill it in.** The rows are the structure the job analysis must
complete; the examples are synthetic placeholders.

| Element | Draft (synthetic placeholder) | Who completes it |
|---|---|---|
| Actual tasks | e.g. implement a scoped change in a client's AI workflow; diagnose a failing integration; write the verification evidence for a change | owner with a domain expert |
| Outcomes the tasks serve | the change works, is verified, is handed off so another person can operate it, and creates no safety or privacy incident | owner |
| Entry requirements (needed on day one) | only what a supervisor cannot reasonably teach within the supervision period; candidates: reading and changing code in at least one language, using version control, explaining what was verified | owner with a domain expert |
| Learnable after entry (never screened for) | the programme's tools and conventions, a specific framework, the client's domain | owner |
| Supervision | a named supervisor reviews every client-facing change before release during an initial period | owner (length and form) |
| Consequences of unsafe performance | **placeholder only, not a proposed consequence:** for example, an unsafe action (exposing client data, bypassing a review) pauses client work pending review; it is recorded as a delivery outcome, not retroactively as an assessment result | owner, with counsel where contracts apply |

## 5. Behavioural criteria (approved D-35 as the draft of `SP-L2-1`)

Six criteria for L2. Each rating is **two separate facts**: the capability shown (what the evidence indicates)
and the strength of evidence (how much there is to go on). An `insufficient_evidence` rating is about the
evidence, never about the person.

| Criterion | Work outcome it matters to | Observable behaviour at L2 (L3 adds) | Acceptable evidence (equivalent alternatives) | Missing versus contrary evidence | Cannot establish |
|---|---|---|---|---|---|
| C1 Problem framing | the right change is made | restates the problem, separates assumptions from facts, asks before guessing (L3: scopes and negotiates trade-offs with a client) | a work sample's issue or design note; a written account of a past problem; a structured follow-up question; a short framing exercise | missing: no sample shows framing. Contrary: work that solved a different problem with no sign of checking | whether the person frames well under client pressure |
| C2 Implementation and diagnosis | the change works | makes a scoped change, reads errors, narrows causes (L3: does so unaided on unfamiliar systems) | a public or private work sample described with the applicant's own contribution; a bounded work sample; a walkthrough of a past diagnosis | missing: only private work, not shown. Contrary: the applicant's own account contradicts the sample, or the work sample fails in a way the applicant does not notice | authorship of a public page; speed on real client systems |
| C3 Verification and safety | no defect or incident reaches the client | states what was tested and what was not; does not ship unverified changes; protects secrets and data (L3: designs the verification) | test evidence in a sample; a described verification habit; a scenario question on handling a secret | missing: no sample shows testing. Contrary: shared credentials or client data in submitted material; claims of testing that the material refutes | behaviour when unobserved |
| C4 Learning from feedback | the person improves under supervision | changes course after review; asks for help early | a described review and what changed; references to code review in a sample; a follow-up question | missing: no example offered. Contrary: none should be inferred from tone or confidence | long-term growth |
| C5 Collaboration and handoff | another person can operate the work | writes handoff notes, explains decisions plainly | a README or handoff note in a sample; a written explanation; the clarity of answers to questions | missing: none supplied. Contrary: a handoff that misstates what the work does | team dynamics |
| C6 Ownership and reliability | commitments are kept | finishes or hands back explicitly; reports problems | the applicant's account of a past commitment; a reference to a delivered project in a sample | missing: none supplied. Contrary: a described pattern of abandoned commitments in the applicant's own account. **Never evidence either way:** how quickly or whether the applicant answers clarification questions | reliability in paid work |

Rules that apply to every criterion:

- **Not evidence of low ability:** no public portfolio; confidential or private work; a missing certification; a
  non-traditional career; a different communication style or English fluency beyond what the role needs.
- **Equivalent evidence paths:** every criterion lists more than one route; an applicant who cannot use one route
  (for example because the work is confidential) is offered another, and the alternative is recorded.
- **Comparable core questions:** within one role, every applicant gets the same core clarification questions per
  criterion; follow-ups may differ but are recorded.
- **Not used, ever:** a universal numerical talent score, personality inferences, prestige weighting (employer or
  school names as proxies), "culture fit" as an undefined rejection reason, source or referral as a proxy for
  ability or trust.

**Mapping to the implemented synthetic rubric** (`assessment_v2`): `work_quality` ≈ C2, `contribution` ≈ C2 and
C5 (authorship), `credential_support` is evidence for C2 or C3 only where a credential is job-related,
`purpose_fit` ≈ L1 participation, `consistency` is an evidence-quality check, not a criterion. C1, C3, C4 and C6
are not in the synthetic rubric. A production rubric is a new pack and schema version under section 6.

## 6. The selection-policy record (documentation contract, approved D-35)

A **selection policy** is the versioned standard a decision is made under. Initially it is a documentation
record, not a software registry. Its identifier is `SP-<role>-<n>` (for example `SP-L2-1`).

**Required fields:**

| Field | Content |
|---|---|
| Identifier and status | `SP-L2-1`; draft, approved, active, suspended or retired; effective date |
| Intended role and use | the purpose (section 3) and what admission under it leads to |
| Criteria and behavioural anchors | the section 5 table as approved, with its version |
| Evidence rules | what counts as evidence, missing versus contrary, equivalent routes, what is never evidence |
| Assessment exercises | core questions, bounded work samples (if any), their time limits |
| Allowed AI and tool use | for the assessed person (for example, AI tools allowed in a work sample if disclosed) and for the assessment itself (advisory model, never deciding) |
| Decision authority | the POL-05 holder; whether a second person is required |
| Candidate alternatives and correction | how to use another evidence route; how to correct a claim; how to ask for review |
| Notices | the POL-17 notice versions that applied |
| Linked versions | prompt pack and digest, rubric version, output schema version, model identifier, evidence source and derivation versions, evaluation set version |
| Validation evidence | the evaluation report this version was approved on (section 8) |
| Change record | reason, affected uses, evaluation comparison, reviewer, owner approval, rollback or suspension procedure |

**Versions stay distinguishable.** The policy version links to, but is not the same as, the prompt pack, rubric,
schema, model, source and derivation, and evaluation versions. A prompt edit is a new prompt pack; it is a
material policy change only if the change rules below say so.

**Material change** (needs a new policy version): any change to role, criteria or anchors, evidence rules,
exercises, decision authority, the model or its provider, the prompt pack or rubric, an evidence source or its
derivation, or the notices. Each material change records a stated reason, affected uses, an evaluation
comparison against the current version (section 8), a reviewer, owner approval, an effective date, and a
rollback or suspension procedure. **Merging a change does not make it active**; activation is a separate,
recorded owner act.

**History is never rewritten.** Every assessment and decision keeps the inputs and versions it used (already true
for runs: `018` section 14). No silent rescoring, no overwritten decisions, no budget reset by a new version.

**Pending cases across a change:**

| Case state when a new version activates | Handling |
|---|---|
| Not yet assessed | assessed under the new version |
| Assessed, no decision yet | stays under the version it was assessed with; staff may offer reassessment under the new version, with notice to the applicant |
| Clarification in progress | finishes under its original version; the applicant is not asked new questions mid-round without notice |
| Decided | unchanged; a reconsideration, if POL-05 or POL-12 allows one, states which version it applies |

## 7. Maturity mapped onto the existing phases

No new P-phase. Each addition sits at its earliest relevant milestone. Synthetic results are necessary evidence,
**not proof of real-world predictive validity**, and that limitation stays visible during any pilot. Longitudinal
delivery outcomes are not prerequisites for finishing synthetic P3. Production policy is never inferred from
synthetic defaults.

| Milestone | Addition | Kind of proof |
|---|---|---|
| 3B.3 | clarification tied to a named evidence gap per criterion; questions that offer alternative evidence routes; candidate-safe wording (the 3B.2 question screen); comparable core questions; staff can see why each question exists | application tests (proof A) |
| 3B.4 | a decision records the human's rationale per criterion, the snapshot digest and the policy identifier; **P3-D-10 as amended (D-35)**: a decision-maker may decide on a recorded human-only assessment when the model assessment is unavailable or suspended (section 10), never as a shortcut | application tests (proof A) |
| 3C | proves software, permissions, provenance and workflow; **not** a validation of selection quality | GATE-P3 |
| 3E | the synthetic evaluation of section 8: model output against human-reviewed examples and a non-model baseline | evaluation report (proof B) |
| Before real candidate-impacting use | an approved role profile and `SP-L2-1`; the data-use boundary (P3-D-6); notices, alternatives and correction path (POL-17); reviewer preparation; legal review where counsel names it; the live-call protections (`018` section 14); the three pre-real-use corrections (append-only correspondence evidence, automatic-pause review, hard-bounce send block); POL-10 | owner approvals, GATE-PILOT |
| Pilot (P6) | the scorecard (section 9) and the review cadence (section 10) | operating records |
| After pilot | outcome validation (area D), reviewed improvements as new policy versions | outcome review |

## 8. A small, credible evaluation process

**Set.** Start with a small set of synthetic cases written and reviewed by the owner and a domain expert, not a
benchmark platform. It must include: strong candidates whose work is private; non-traditional backgrounds;
polished but unsupported claims; missing and conflicting evidence; different communication styles; relevant
work demonstrations; genuinely unsafe conduct. Each case uses the same core questions for its role and equivalent
evidence routes. Work samples are bounded exercises, never unpaid client work.

**Separation.** Development cases (used to write prompts and rubrics) are kept apart from a held-out evaluation set.
Expected findings and evaluation answers never enter the assessed model's inputs. The set is versioned; reviewer
disagreements are recorded, not averaged away. Real cases are never added to the public set (section 12).

**Human baseline first.** Qualified reviewers rate each case without seeing the model's output. Then:

- **non-model baseline:** the human ratings alone, and a simple deterministic checklist over the same evidence;
- **model assistance:** the same reviewers rate again with the model's output, recording whether it helped them find
  evidence or merely moved their rating toward the model's.

**What is measured:**

- citation relevance and conclusion support (does the quote support the finding), not only whether a quote exists;
- missed relevant evidence and unsupported conclusions;
- repeatability (the same case, several runs) and sensitivity to irrelevant presentation changes (formatting, a
  name, tone);
- treatment of missing evidence (never adverse) and of the "not evidence of low ability" cases (section 5).

**Limits stated with every report:** a small set is not statistical proof; a human decision is not unquestionable
ground truth; model agreement with humans is not correctness.

## 9. Watching quality: a small scorecard (structure approved D-35)

Computed from existing PostgreSQL records and shown in staff views; no warehouse, analytics service or evaluation
platform by default. **No thresholds are set** (POL-16): with small numbers, review triggers are case reviews and
counts, not rates. "Minimum to interpret" is the smallest count at which a rate would mean anything; the owner sets
it, and until then every case is reviewed individually. Owner: the operational delegate (section 10) prepares; the owner reviews.

**Staff report (`f1u.7`).** The read-only “Selection quality and owner report” screen is linked from
the staff index for active staff holding `assessments.record_qualification_decision`; superusers and
other roles are refused. It uses the same queries as `manage.py selection_scorecard`, shows all 15
measures, and keeps unavailable measurements distinct from zero. The screen covers all recorded
cases, without a date or cohort filter, and does not claim a change since the previous review.
Printing includes the owner summary, while detailed measures remain on screen. It excludes case
identifiers, narrative decision reasons and unrelated staff notices. It assigns no delegate, changes
no decision and schedules no review. Owner review of the sample and the operational appointment
remain acceptance work; rendering the report does not ratify either.

| Area | Measure | Definition and denominator | Source | Minimum to interpret | Review trigger | Response | Privacy boundary |
|---|---|---|---|---|---|---|---|
| A. Candidate | time waiting | days from adoption to decision, per decided case | stage events | any case | any case over the owner's stated window | review the stalled step | counts and durations only |
| A | clarification burden | questions per application; repeated questions on the same criterion | `Question` records | any case | any repeat question | check the question set | no answer text in reports |
| A | abandoned cases | applications that stop responding, per started clarification | stage and question records | owner to set | any abandonment | case review: was the burden reasonable | no inference about the person |
| A | corrections, alternatives, complaints | correction requests, alternative-route use, unresolved complaints | staff items, events | any | any unresolved complaint | owner review | complaint text stays private |
| B. Staff | review time | staff minutes from `awaiting_decision` to decision | events | any | outliers by case review | adjust the screen or rubric | none |
| B | exceptions and futile reruns | open assessment staff items; reruns that end capped or failed | staff items, runs | any | any rerun loop | budget-policy amendment bead | none |
| B | override reasons | decisions that differ from the advisory recommendation, by reason code | decisions, runs | any | every override is read | recalibrate or record | reason text private |
| B | reviewer disagreement | cases where two reviewers differ, when two review | decisions | any | any | discuss and record | private |
| B | shell or database edits | cases that needed a coding agent or a database edit | incident log | any | any | treat as a product defect | none |
| C. Assessment | unsupported conclusions, missed evidence | findings a reviewer marks unsupported or incomplete, per reviewed run | reviewer annotations | any | any | case review; evaluation comparison | private |
| C | citation relevance | quotes judged irrelevant to their finding, per citation reviewed | reviewer annotations | owner to set | any irrelevant citation | prompt or rubric review | private |
| C | instability | reruns of an unchanged snapshot that disagree | runs | any | any disagreement | suspend criterion use if repeated | none |
| C | insufficient-evidence outcomes | criteria rated `insufficient_evidence`, per run | runs | any | rising share by case review | improve evidence routes, not ratings | none |
| C | version differences | outcomes by policy and model version | runs, decisions | per version | any version change | evaluation comparison | none |
| D. Delivery (after pilot) | quality, rework, handoff, reliability, safety | per assigned person, at the responsibility actually assigned | delivery records (not yet designed) | after enough assignments for case review | any safety incident | separate assessment error from poor assignment, inadequate support or unequal opportunity | restricted; never public |

**False negatives.** They cannot be estimated from accepted candidates alone. Offer a voluntary second
look to a sample of uncertain cases (held or declined on thin evidence), through a comparable evidence route. What
remains unobservable: how declined people would have performed.

**Protected characteristics.** Never inferred from names, photographs or text. Any demographic fairness analysis
needs a separately approved lawful basis, access separation and a privacy review; none is proposed here.

## 10. Ownership, cadence and corrective action (operating plan, approved D-35)

These are recommendations, not scheduled automations: no cron job, alert or task is created by this document.

- **Policy approver:** Jeremy Longshore. **Operational delegate:** a named staff role (to be named by the owner)
  who prepares reviews and carries out responses. The decision to suspend model advice or roll back a version is the
  owner's; the delegate may act alone only under a standing authorization the owner has recorded in advance in `011`
  section 4 (naming the triggers it covers), and reports to the owner the same day (`011` section 11).
- **Cadence:** a brief weekly exception review during an authorized pilot; a monthly aggregate review after
  stabilization; revalidation (section 8) after any material change (section 6); immediate triage of a privacy or
  safety incident or an unauthorized decision.
- **One-page owner report:** what changed; evidence; candidate and staff impact; exceptions; decisions needed;
  the safest next action. Every alert or trigger has a named owner and a stated response.

**Corrective actions:**

| Trigger | Action |
|---|---|
| Repeated instability, unsupported conclusions or a harmful pattern in model output | **suspend model advice**: new cases go to human-only review under the amended P3-D-10 (D-35). Until 3B.4 builds that path, suspended cases wait in `assessing` with an open staff item and a notice to the applicant. Suspension never rejects or declines anyone automatically |
| A defect in a policy version | **roll back** to the previous approved version; cases assessed under the defective version are listed and offered reassessment |
| A privacy or safety incident, or a decision made without authority | **investigate affected cases**: preserve records, notify the owner, record the root cause and the remedy per case |

**Never:** automatic rubric tuning, automatic threshold changes, increasing the model's authority, or training any
model on accepted-candidate history.

## 11. Ethical attraction is separate from scoring

Useful public technical work, voluntary clinics and explicit invitations are **future acquisition hypotheses**,
not hidden assessments. No covert scoring of participants, no social scraping, no requirement to do unpaid public
work; an equivalent private route always exists. Source or referral information may help evaluate outreach if it
is collected with notice; it never becomes a proxy for ability or trust. No outreach automation, community
platform or CRM integration is part of this work.

## 12. Private material boundary

Real case reviews, evaluation answers for real people, reviewer notes on real candidates and any restricted
evaluation material need an **approved private location with an access and retention policy** (POL-10) before they
exist. Until then only synthetic cases are written, and only into the repository's public test fixtures or this
document's examples.

## 13. Owner decisions

Decided 2026-10-14 (D-35):

1. The three assessment purposes (section 3) are the frame.
2. The six criteria and the evidence rules (section 5) are the draft for `SP-L2-1`.
3. The selection-policy record and change rules (section 6), including that merging never activates.
4. The P3-D-10 amendment: a recorded human-only assessment when model advice is unavailable or suspended. It differs
   from the "recorded waiver" rejected for P3-D-10: a waiver skips assessment, while the amendment substitutes a
   written human assessment against the same criteria and snapshot. It applies when 3B.4 is built.
5. The cadence and corrective actions (section 10), the evaluation process (section 8) and the scorecard structure
   (section 9).

Still open (each needs a name or an input the approval did not give):

1. The domain expert who completes the L2 role profile (section 4) with the owner.
2. The operational delegate role and any standing authorization for it (section 10).
3. The private location, access and retention rules for real evaluation material (section 12).
4. The scorecard's minimum counts (section 9).
5. What clears a capped assessment snapshot (`018` section 14).
