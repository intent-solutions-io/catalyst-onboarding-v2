# 017-AA-AACR — P2 correspondence loop after-action report

> Catalyst v2 is Intent Solutions' onboarding platform for Solution Catalyst applicants, built on Django and
> PostgreSQL. This report closes phase P2: the applicant correspondence loop.
>
> - Staff approve a question, and the system sends it by email as a frozen, exact message.
> - The system collects replies from a mailbox, links each reply to the question it answers, and decides
>   whether the reply can be trusted.
> - Staff confirm what a reply settled. Reminders and escalation follow unanswered questions.
> - Staff can pause, resume, withdraw and write directly, through permissioned screens.
>
> Everything ran against synthetic SMTP and IMAP servers. No real email, AI model, applicant data or
> deployment was involved.

- **Status:** GATE-P2 signed off by the owner on 2026-10-13 (D-33 in `011`), after one bounded closeout
  (`016` 10.12). The epic closes.
- **Lane:** full. There were review findings and fixes in every task (section 5).
- **Epic:** Run the applicant correspondence loop (bead `catalyst-v2-7hu`).
- **Acceptance test:** every case TEST-P2-01 to TEST-P2-54 in `016` section 7 is PASS at one head on
  PostgreSQL in CI, GATE-S1 still passes, QA has reviewed the work, and this report is filed (GATE-P2,
  `002` line 121).
- **GitHub:**
  - specification: PR #20 (`1a6a25f`);
  - implementation:
    - #21 (2B.1, `349f54e`);
    - #22 (2B.2, `2aea347`);
    - #23 (2B.3, `ea67f07`);
    - #24 (2B.4, `cb0bd2a`);
  - gate: the 2C pull request that adds this report.
- **Period:** 2026-10-11 to 2026-10-13
- **Author:** Jeremy Longshore. Claude Code implemented the work; the Catalyst specialist subagents
  reviewed it.
- **Template:** 000-AA-TMPL v1.0.0

## 1. Summary and business value

P2 turns the first slice's single verification email into a complete, recoverable conversation:

- **Outbound** (2B.1). Each send is an owner-approved, frozen `ApprovedMessage`. Every SMTP outcome is
  classified by the protocol phase it reached. An outcome that is not known is reconciled, never resent
  blindly.
- **Inbound collection** (2B.2):
  - a durable cursor with a completed-collection watermark;
  - message identity by digest;
  - redacted text derivatives (no original bytes are stored);
  - association by our own Message-IDs;
  - the DMARC trust table;
  - verified TLS;
  - recovery from a `UIDVALIDITY` change.
- **Processing** (2B.3):
  - deterministic classification of bounces, autoresponders and mail loops;
  - a reply never satisfies a question by itself;
  - staff confirm outcomes;
  - a held, typed interface for the later AI step (P3);
  - immutable staff resolutions;
  - S1's staff attention now reads open staff items.
- **Reminders and staff intervention** (2B.4):
  - reminders held while a reply is pending, with quiet hours, a minimum gap and the watermark rule;
  - escalation after the last reminder;
  - pause and resume with no burst;
  - question withdrawal;
  - staff messages, previewed and then confirmed against the exact content;
  - permissioned staff screens, so staff never need a shell.

The organization can now show working evidence that the hard communication failures are handled before any
real mailbox is connected:

- duplicate, malformed, oversize, spoofed and looping mail;
- a crash at any point;
- an outcome that is not known;
- a reminder racing a reply;
- staff takeover.

## 2. Scope: planned, completed, deferred

**Planned (`016` section 9):** 2A specification, then 2B.1 to 2B.4, then 2C verification.

**Completed:**

| Task | Bead | Merged as |
|---|---|---|
| 2A specification and owner brief | 7hu.1 | `1a6a25f` (#20) |
| 2B.1 outbound foundations | 7hu.2 | `349f54e` (#21) |
| 2B.2 inbound collection | 7hu.3 | `2aea347` (#22) |
| 2B.3 reply processing | 7hu.4 | `ea67f07` (#23) |
| 2B.4 reminders and staff intervention | 7hu.5 | `cb0bd2a` (#24) |
| 2C gate, QA and this report | 7hu.6 | this PR |

**Deferred (recorded in `016` sections 8 and 10):**

- **Real mail.** Real MXroute access, provider evidence for reconciliation, and real production values for
  cadence, quiet hours and thresholds (POL-06). These are separately gated (`016` 8.3).
- **P3 interpretation.** The interface and the `interpret_reply` hold are in place; no model is called.
- **Alerting.** P6 wires `correspondence_health`'s exit status to the alert floor. The thresholds are owner
  numbers.
- **Admin link.** A link from the admin dossier to the staff screens.

## 3. Architecture and tradeoffs

- **One ledger.** Every effect (send, reconcile, collect, process, remind, escalate, file a copy) is a
  `PendingAction`. Each claim is lease-fenced and each result is one transaction. There is no second job
  system.
- **Frozen messages instead of templates rendered at send time.** A worker rebuilds the exact approved bytes
  after any crash. Chose this over rendering at send time because the alternative cannot prove what was
  sent.
- **Derivatives, not originals.** Inbound mail is reduced to redacted text plus metadata at collection time.
  Re-derivation needs the mailbox. Chose this over storing bytes because of POL-10 (retention) and the
  public repository.
- **Staff decide; the system classifies.** Only deterministic rules act automatically. Everything that
  needs judgement opens a staff item with an immutable resolution record.
- **A focused staff screen module instead of admin actions.** Chose this because of the 2B.4 spike: admin
  actions cannot collect the inputs and would weaken the read-only admin of S1.
- **Layering (ADR-01).** `applications` never imports `correspondence`. The S1 code opens staff items through
  one code-loading setting (`CATALYST_ATTENTION_OPENER`), pinned by a start-up guard. Import-direction
  tests enforce this.

## 4. Verification evidence

- **The acceptance map.** `tests/acceptance.py` `P2_CASES` maps all 54 cases to 196 test references (181 at 2C, 196 after the closeout).
  `tests/conftest.py` fails a full run unless every GATE-S1 and GATE-P2 case is PASS. `tests/test_acceptance.py`
  checks that the map names exactly the cases in `016` section 7 and that every mapped test exists.
- **Local full run** (`scripts/test.sh`, pinned Python 3.14.8 and PostgreSQL 16.15, 2026-10-13): **614 passed**
  in 690.51 s at 2C; **623 passed** in 703.23 s after the GATE-P2 closeout (`016` 10.12). GATE-S1 PASS 25, FAIL 0, INCOMPLETE 0, NOT RUN 0. GATE-P2 PASS 54, FAIL 0, INCOMPLETE 0,
  NOT RUN 0.
- **CI:** the "Runtime checks" job on the 2C head, linked from the pull request.
- **Reviews per task** (`016` 10.3 to 10.11):
  - 2B.1 and 2B.2: independent QA.
  - 2B.3: QA, Django architecture, data, MiniMax evaluation, and security and privacy.
  - 2B.4: QA, security and privacy, workflow and correspondence, Django operator, and release operations.
  - No review left a blocker unresolved.
- **2C traceability audit.** An independent QA audit of the map judged 28 cases fully proven and the rest
  partial. It found no case wrong as a whole. 2C closed the ranked gaps with new tests:
  - no table stores original message bytes (schema scan, TEST-P2-39 and 47);
  - a crash during resync (46);
  - a derivation golden case (44);
  - a reply to a closed application when a newer one exists (18);
  - a negative permission test for every remaining screen action (42 and 52);
  - staff messages and Reply-To change no identity or recipient (54 and 36);
  - withdrawal cancels held reminders and the escalation (50).

  It also added the mappings the audit named, and renamed two tests whose names overstated them.

**Partial coverage at filing (dispositions accepted by the owner in D-33).** The GATE-P2 closeout (`016` 10.12) closed or set a
scope boundary for each item below. Owner acceptance of those dispositions is still pending. The items as
filed:

- **TEST-P2-08.** "The rest stays open" is shown with one question per message. In P2 every message carries
  one question.
- **TEST-P2-15.** The scripted server does not count body bytes fetched.
- **TEST-P2-41.** G5 ages and G7 growth are reported without thresholds; the thresholds are P6 numbers.
- **TEST-P2-45.** "Cannot reach a non-test host" is proven by the guards and the transport peer check, not by
  a staff send to a real host.
- **Concurrency.** Reminder races are proven through the projection and handler re-checks under locks. A true
  two-thread race is tested only for staff confirmation against `process_reply` (TEST-P2-32).

## 5. Issues and root causes

- **Silent stuck replies** (2B.3 QA). A reply whose processing failed finally stayed `awaiting_processing`.
  - Cause: the ledger's final failure had no domain hook.
  - Fix: a final failure now opens a `processing_error` item. A follow-up re-check found that this item was
    itself unresolvable (a dedupe key with a suffix), and that was fixed too.
- **A two-way dependency** (2B.3 architecture). `applications` wrote `correspondence` rows.
  - Fix: the attention-opener seam plus an import-direction test.
- **Reminder bursts** (2B.4 correspondence review). The minimum gap counted only mail the server had
  accepted, so reminders that fell due together could all go out.
  - Fix: the gap now counts frozen messages.
- **Frozen reminders ignoring their question** (2B.4 QA). A reminder already frozen and waiting to send
  ignored a later "satisfied".
  - Fix: the send check follows the question.
- **Read access too broad** (2B.4 security). Any single permission could read applicant mail.
  - Fix: each page now names the permissions whose holders need it.
- **No template approval screen** (2B.4 operator, blocker). The owner would have needed a shell to approve
  the first template.
  - Fix: template pages, with a digest-checked approval.
- **Status lines drifted** in `000-INDEX`, `016` and `011`. Fixed in 2B.4.

## 6. Lessons learned

- **Specialist reviewers find different classes of defect.** In P2, several specialists found issues no
  single review did. Examples: the operator blocker, the burst, and read access. This is not a standing rule.
  Later tasks use one primary independent reviewer, plus a narrowly scoped specialist when a change crosses a
  security, data or integration boundary (`016` 10.12).
- **Every "final failure" path needs a domain owner.** The ledger is generic, so each handler's `record` must
  turn exhaustion into a staff item.
- **A gate proves only what is mapped.** The 2C audit showed that generating the map from test names
  overstates coverage. An independent traceability read before sign-off is worth its cost.

## 7. Operational impact, including cost

- **Schema.** Migrations `correspondence` 0003 to 0012, run as the owner.
- **New settings.** All of them are synthetic defaults. There are no new dependencies, secrets or provider
  credentials.
- **Mail hosts.** The guards still refuse any real mail host outside the named test service.
- **Cost.** No hosting, provider or model cost.

## 8. Rollback procedure and validation

- **Code.** Revert the 2B squash commits in reverse order (#24, #23, #22, #21). Each is self-contained.
- **Schema.** The migrations are reversible down to `correspondence` 0002. Reversing 0005 drops the inbound
  tables and their data, and reversing 0008 keeps the backfilled staff items. Both are documented in the
  2B.3 data review.
- **Validation.** `scripts/test.sh` must report GATE-S1 PASS 25 after any rollback.

## 9. Next steps

1. **Owner GATE-P2 sign-off** (owner only). Includes the accepted partial coverage in section 4.
2. **Owner decisions carried forward** (`016` 10.9 and 10.11):
   - ADR-14 protection triggers for the correspondence audit tables (POL-10);
   - read access to derivative text;
   - whether an operator may resume after an automatic pause;
   - staff mail to an address that hard-bounced;
   - retention of drafts and notes;
   - one person both associating and confirming a reply;
   - model use of applicant mail (P3);
   - alert thresholds (P6).
3. **P3.** Design the bounded MiniMax interpretation against the typed interface (`catalyst-minimax-evaluation`).
4. **Before real mail.** Run the separately authorized provider check (`016` 8.3).
