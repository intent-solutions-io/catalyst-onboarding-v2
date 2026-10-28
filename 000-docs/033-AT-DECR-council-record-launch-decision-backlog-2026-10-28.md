# Council record: the internal-launch decision backlog of 2026-10-28

| Field | Value |
|---|---|
| Document | 033-AT-DECR-council-record-launch-decision-backlog-2026-10-28 |
| Date | 2026-10-28 |
| Acting head of board | Claude Code, designated by the owner on 2026-10-28 ("get with the executive council ... and legal advisors") |
| Council | the seven seats of `030`, plus two non-voting legal advisors (privacy and retention; agreements, notices and the employment boundary) |
| Decisions | ten, adopted provisionally; owner ratification required; recorded as D-52 in `011` section 4 |
| Status | OWNER-RATIFIED 2026-10-28, with the two-wave launch adopted (section 13). Values marked for counsel stay provisional until counsel answers. The legal advisors are not the company's counsel and nothing here is legal advice. |
| Inputs | `031` (the decision package), `030`, `032` sections 1 and 2, `029`, `011` section 4, the open 211.7.x beads, the proposed wording drafts of 2026-10-27 |
| Pattern | ISEDC; the verbatim seat files and advisor memos are in the council session record on the owner's development host (not tracked) |
| Classification | Public repository: roles, never people; no private hosts, paths, addresses or agreement text |

## 1. Purpose

The owner asked on 2026-10-28 where the launch stands and how long it will take, then asked the council and legal advisors to work the decision backlog. The critical path to the internal go/no-go is owner input: nine decision beads (211.7.1 to 211.7.9), counsel, the GitHub protections, the wording and the host and provider goes. This record gives a provisional answer to each, says what the owner must ratify or supply, and corrects the plan where the code disagrees with it. It authorizes no host, provider, real-data, wording or launch act, and it does not upgrade D-49, D-50 or D-51.

## 2. Why a council, with legal advisors

The 030 council settled the architecture. What remained is values, sequencing and a legal boundary: real colleagues' data entering an object-locked backup that can only age out. Two advisors were added on the owner's instruction to separate what counsel must answer from what the owner may adopt; they do not vote.

## 3. The questions

| # | Question |
|---|---|
| Q1 | POL-10 values (211.7.1): adopt 031 section 2 as the provisional POL-10? |
| Q2 | POL-10 sequencing: fill the registry now for the dark deploy, or hold it undecided; and the P6-D-13 crypto-shred gap |
| Q3 | Counsel: send the 031 section 6 questions now, in what form, and which block real intake (E) |
| Q4 | Custody (211.7.9): adopt 031 section 3; fallback without a second device; deputy recovery holder |
| Q5 | Agreements and notices (211.7.4): members on file, countersignature, template control, wording, decline notice |
| Q6 | What the cohort is promised (211.7.6), and how existing members take part |
| Q7 | Coexistence (211.7.3): keep D-51; what makes it final; rollback window |
| Q8 | Staff, devices, authority, fields (211.7.5, 211.7.8); the two human-only selection rules |
| Q9 | Production values (211.7.7, 211.7.2): lifetimes, quiet hours, RPO/RTO, paging, incident ownership |
| Q10 | The owner's shortest path: classification, ordered owner acts, repository work the agent may start |

## 4. What the code says (verified by the main session on `main` at `048d7d3`)

- `config/guards.py:28` admits `production` (9kg.31.11 merged); 031 section 8 item 3 is out of date.
- `deploy/staging/adapters/predeploy.sh:23-26`: no backup, no migration. With the registry undecided, `config/backup.py:109-119` refuses the production backup, so the deploy itself is blocked, not only its proofs; 031 section 8 item 1's second option is not available as built.
- `erasure/registry.py:98-99`: any non-blank retention text counts as decided, and nothing applies a period (lines 30-31).
- `config/backup.py:109-119`: the refusal keys on the environment, not on whether the data is real.
- `assessments/decisions.py:205-225`: an admit records capability, evidence strength and a note for every rubric criterion; 'unknown' with strength 'none' is accepted.
- `assessments/decisions.py:280`: decline is refused only for a member on file (030 Q8); the two 018 section 20 human-only rules are not built.
- `config/settings.py:493`: `CATALYST_AGREEMENT_REQUIRED_DETAILS` is empty (no production POL-18 list).
- `config/settings.py:356-357`: quiet hours 21:00-07:00 UTC, which leaves 02:00-07:00 US Central open for reminders.
- `config/settings.py:210-212`: every wait class's aged threshold defaults to the general pending age; three classes (unprocessed replies, unsigned issued agreements, refused activations) page by default.
- `catalyst_erasure_drill` and `catalyst_custody_drill` refuse to seed in production, so a production restore drill backs up a nearly empty database unless the dark deploy's synthetic journey supplies subjects.
- `applications/management/commands/catalyst_invite.py:7-11`: the invitation is printed for the owner to send by hand, so the owner's own Sent copy and any reply to it sit outside v2's reply collection and erasure handoffs.

## 5. Per-question record

### Q1. POL-10 values (211.7.1): adopt 031 section 2 as the provisional POL-10?

| Seat | Recommended answer |
|---|---|
| CTO / Chief Architect | Adopt provisionally, R3 to counsel; a structured CLOCKS table 9kg.75 reads; R3 starts at an owner-recorded engagement-ended event, never case closure. |
| General Counsel | Adopt with four changes: R1 6 months; an erasure request outranks a pause; provider copies deleted within 30 days of the request; an agreement_obligations hold stops key destruction until R3 has run. |
| CISO | Adopt unchanged; the erasure key is generated on the host or an owner device, never in an agent session; real receipts scanned against a host-local deny-list. |
| COO / Head of Release Operations | Adopt; the monthly procedure runs on a fixed calendar day and the go/no-go defines 'enforced' as that owner-run procedure. |
| CFO / Strategic Operator | Adopt; the monthly review starts when the first clock can expire (about 3 months in); requests handled within 5 working days. |
| Head of Product and Applicant Experience | Adopt with R3 from end of engagement, referenced members under R1 from trial closure, and the owner's own mailbox copies added to the handoffs. |
| Chief Legacy and Coexistence Officer | Adopt, plus: v2 erasure and every provider handoff reach only v2's own stores, never a first-generation record, mailbox or signing team. |

**Vote:** 7/7 adopt provisionally. **Tension:** GC alone on R1 6 months; the rest keep 12 (strength: mild).

**Decision (provisional):**

- Adopt 031 section 2 as the provisional POL-10, with these amendments stacked in:
- R4 runs from receipt of the request: erase, or send a reasoned delay or refusal, within 30 days; an open case or hold does not silently pause it (privacy advisor; GC: an erasure request outranks a pause).
- R3 starts at an owner-recorded 'engagement ended' event, never at case closure (CTO, Product); members whose agreements are only referenced fall under R1 from trial closure (Product).
- A recorded agreement-obligations hold stops key destruction of signed documents until the R3 period has run (GC); every provider-copy deletion for a request finishes within 30 days of the request (GC).
- The owner's own mailbox copies (the hand-sent invitation and replies to it) join the provider handoffs (Product); erasure and handoffs reach only v2's stores, never a first-generation record (Legacy).
- Records and notices say 'content erased; a pseudonymous record kept', never 'anonymized' (privacy advisor). The keyed hash's lifetime goes to counsel, not 'deployment life' (privacy advisor).
- The erasure key is generated on the production host or an owner device, never in an agent session (CISO). The monthly procedure runs on a fixed calendar day and each run is recorded (COO, privacy advisor).
- R1 stays at 12 months provisionally; GC's 6 months goes to counsel as the alternative.

### Q2. POL-10 sequencing: fill the registry now for the dark deploy, or hold it undecided; and the P6-D-13 crypto-shred gap

| Seat | Recommended answer |
|---|---|
| CTO / Chief Architect | (a) Fill now in a release that adds a 'provisional' state refusing invitations and intake in production; a second release after counsel flips it. (b) Keep the required-details list empty and refuse a non-empty list in production until field encryption exists. |
| General Counsel | (a) Fill now; real intake mechanically blocked by the notice gate plus a COUNSEL_CONFIRMED refusal. (b) Accept only as an explicit owner amendment of P6-D-13; build crypto-shredding before wider enrollment. |
| CISO | (a) Fill now; intake gated by the owner withholding notice approval until counsel answers. (b) Accept only if POL-18 holds no ID, date of birth, postal, tax or bank data. |
| COO / Head of Release Operations | (a) Fill now, flagged provisional in health and cleared before the go/no-go; dark-deploy synthetic subjects erased with catalyst_erase before real intake. (b) Accept; bead before F only if counsel rejects anonymization. |
| CFO / Strategic Operator | (a) Fill now labelled 'provisional, counsel pending'; no invitations before counsel. (b) Accept: POL-18 is empty in production, nothing to shred. |
| Head of Product and Applicant Experience | (a) Fill now; refuse live intake until counsel's launch-blocking answers. (b) Accept while POL-18 stays empty for the cohort. |
| Chief Legacy and Coexistence Officer | (a) Fill now; one complete host visit is safer for the live service than two. (b) Accept for the internal cohort. |

**Vote:** 7/7 fill the registry now; 7/7 accept anonymize-and-replay for the cohort. **Tension:** mechanism for the intake gate: coded lock (CTO, GC, COO) vs owner withholding approval (CISO, CFO, Product, Legacy) (strength: strong (CTO)).

**Decision (provisional):**

- (a) A reviewed release fills the registry now with the provisional values AND adds a coded 'provisional' state: while set, production refuses invitations and intake, and health reports it (CTO, GC, COO; adopted because CTO's most-costly finding is that the fill otherwise removes the only coded refusal). A second release, after counsel's answers, clears it; that release merges only after the 032 section 1 protections are applied (CISO).
- The dark deploy's synthetic subjects are erased with catalyst_erase before real intake, which is also the first production erasure proof (COO).
- (b) Accept anonymize-and-replay for the internal cohort, recorded as an owner amendment of P6-D-13 (GC), on three conditions: production refuses a non-empty required-details list until field encryption exists (CTO); POL-18 holds no ID, date of birth, postal, tax or bank data (CISO); the notice states the backup window (privacy advisor). Crypto-shredding is a bead before wider enrollment (F).

### Q3. Counsel: send the 031 section 6 questions now, in what form, and which block real intake (E)

| Seat | Recommended answer |
|---|---|
| CTO / Chief Architect | Send all twelve now; 1-5, 7, 8, 12 before the first real submission; 6, 9, 10, 11 before F. |
| General Counsel | Authorize today, two parts, as a privileged request; E: 1, 2, 3, 5, 7, 8 plus new 13 (which law) and 14 (free volunteering); counsel discloses the conflict and joins after part one. |
| CISO | Send all twelve with blockers marked: E: 2, 3, 5, 7, 8 and the R3 period, plus 4 and 12 if anyone signs, 11 if a decline is possible; record that counsel is a cohort member. |
| COO / Head of Release Operations | Send the whole packet now, blockers marked: 1, 2, 3, 5, 7, 8 (+11, 12 if a v2 decline or agreement can happen); 4, 6, 9, 10 wait. |
| CFO / Strategic Operator | Authorize today; before wave 1: 2, 7, 8, 1(c); before wave 2: 4, 12; the rest to F. |
| Head of Product and Applicant Experience | Send today as one packet with the wording drafts; E: 1, 2, 3, 5, 7, 8, 11, 12 (+4 if anyone signs); record counsel as a cohort member. |
| Chief Legacy and Coexistence Officer | Send all twelve now; E: 1, 2, 3, 5, 7, 8, 9 (+12 if anyone new signs); counsel's own record out of the first wave. |

**Vote:** 7/7 send now. **Tension:** form: one marked packet (5) vs two parts (GC) vs wave subsets (CFO); E-blocking sets differ at the edges (strength: mild).

**Decision (provisional):**

- Recommend the owner authorize sending today, as one privileged request to the company's counsel: the whole packet, launch-blocking items marked, the wording drafts attached, and a facts sheet by role and country (never names) (majority; privacy advisor).
- Before real intake (E): 031 questions 1 (R3 at least), 2, 3, 5, 7, 8, plus 4 and 12 once anyone signs in v2, and 11 only if a decline can happen; add 'which law applies to each member' and 'can a colleague volunteer freely' (GC; privacy advisor Group A items 1-3, 13-17). Before F: 6, 9, 10, 11 and the privacy advisor's Group B.
- Counsel is a cohort member: counsel discloses it, is not in the first wave, holds no staff role, never resolves a hold on their own record, and is not the sole reviewer of the member-rights points; whether to engage an outside attorney for those points is the owner's call (GC, Legacy, agreements advisor).
- The public record carries only 'decided on counsel's advice', never the advice.

### Q4. Custody (211.7.9): adopt 031 section 3; fallback without a second device; deputy recovery holder

| Seat | Recommended answer |
|---|---|
| CTO / Chief Architect | Adopt; the escrow copy must not be decryptable by the production host's key; without a second device, a separate mount with the provider copy as the stated recovery source; no deputy. |
| General Counsel | Adopt; owner sole holder, no deputy; without a second device a same-device mirror recorded as a limit, or agreements stay disabled; the key directory never in a versioned backup. |
| CISO | Adopt, but escrow the wrapping key only to owner-held keys no agent or backup can read, two copies, one offline; same-device mirror outside every archive if needed; deputy named before F. |
| COO / Head of Release Operations | Adopt; without a second device a separate filesystem, Documenso copy kept as recovery source until erasure, tabletop the re-fetch before the go/no-go; no deputy. |
| CFO / Strategic Operator | Adopt; without a second device the mirror on the same disk and the provider copy as recovery source, provider-copy deletion paused for those documents; no deputy. |
| Head of Product and Applicant Experience | Adopt; no deputy; without a second device only new-participant signing waits and each affected member is told why. |
| Chief Legacy and Coexistence Officer | Adopt; no key directory on any device the first-generation service uses; without a second device agreements stay off and only members with both agreements enter. |

**Vote:** 7/7 adopt, no deputy for the trial. **Tension:** escrow target: CISO and CTO require keys no agent or host can decrypt (strength: binding (CISO)).

**Decision (provisional):**

- Adopt 031 section 3 with the owner as sole recovery holder and no deputy for the trial; a deputy is named before F (CISO).
- Binding (CISO, CTO): the wrapping-key escrow must not be decryptable by any key on the development host or the production host; owner-held keys only, two copies, one offline. This replaces 'the estate's encrypted secret store' if that store's key sits on the development host.
- No second device (H22): the key mirror on a separate filesystem or directory outside every archive, never on a device the first-generation service uses or a backed-up machine; the provider copy is the recorded recovery source and its deletion is paused for those documents until erasure; tabletop the re-fetch before the go/no-go (COO, CFO, CTO, Legacy).

### Q5. Agreements and notices (211.7.4): members on file, countersignature, template control, wording, decline notice

| Seat | Recommended answer |
|---|---|
| CTO / Chief Architect | Adopt the agreement mechanics; fix the drafts: lifetimes as variables, narrower 'no model' claim, a person may open links, backups on company machines, a defined order for the erasure confirmation. |
| General Counsel | Adopt option (a) conditional on counsel's Q7; add voluntariness, 'role or engagement', staff notes and logs, fix correction and erasure-confirmation promises and the invitation's 'nothing happens'; no cohort member is declined. |
| CISO | Adopt; narrow the 'no model' sentence, name company-run backup machines, hold the named-devices clause until verified, drop the clickable link from the invitation. |
| COO / Head of Release Operations | Adopt; remove every placeholder before approval; the erasure confirmation cannot be sent after the address is erased; a time for reading replies; the decline notice gives no reason unless counsel agrees. |
| CFO / Strategic Operator | Adopt; five wording fixes (retention incl. backups, honest erasure confirmation, owner-only viewer, collected fields only, model-off tied to the notice version); no decline wording before F. |
| Head of Product and Applicant Experience | Adopt option (a); send the drafts back with line edits; the notice depends on the model being verified off; never withhold a decline notice from a cohort member. |
| Chief Legacy and Coexistence Officer | Adopt option (a) with both agreements on file; name v2's own reply mailbox, an unmistakable sender, and that the trial changes nothing the first-generation service holds; no declines in the cohort. |

**Vote:** 7/7 adopt the agreement mechanics; 7/7 send the wording back. **Tension:** option (a) conditional on counsel's Q7 (GC) and both agreements on file (Legacy) (strength: mild).

**Decision (provisional):**

- Adopt the agreement mechanics: v2's own Documenso team, provider sends, owner countersigns by hand after a digest check, in-place template edits forbidden and checked by digest before every send (agreements advisor).
- Members on file: option (a) only where both first-generation agreements are verified and counsel clears the reference in writing (counsel Q7); otherwise the member signs the full current v2 set; no mixing; no signature, no activation (agreements advisor, GC, Legacy).
- The three drafts go back for rework, not approval: the line edits in seats/product.md and both advisors' memos. They must name the contact (owner input), narrow the 'not an assessment' and 'no model' sentences, list staff notes and ratings, drop 'nothing happens', fix the erasure confirmation (it cannot go to an erased address), render lifetimes as variables, name v2's own reply mailbox and sender, and state the backup window. The agent does not approve or publish them.
- Decline: production refuses every decline of a cohort member while D-M applies (CTO); the decline notice is drafted with slots now and settled before F.

### Q6. What the cohort is promised (211.7.6), and how existing members take part

| Seat | Recommended answer |
|---|---|
| CTO / Chief Architect | A member is promised only a recorded completion; the invitation table is the roster with a stated upper bound; results owner-only, never for work decisions. |
| General Counsel | Trial access only, nothing else changes; owner-only results used to evaluate the system; no cohort data exported anywhere, the brain included; recorded in 011. |
| CISO | Owner-only results, never used for employment or standing, never exported per person; existing members referenced, not re-signed. |
| COO / Head of Release Operations | No new mailbox or access; owner-only results never used for employment, pay, assignment or performance, never copied to CRM, tracker or a per-person scorecard. |
| CFO / Strategic Operator | Promise nothing new; members take part through their on-file record, never a second mailbox; owner-only results; every criterion recorded 'unknown / none - not assessed'. |
| Head of Product and Applicant Experience | Every rubric criterion recorded unknown/none/not assessed; no cohort member declined; the owner sends a closing message before closing the case. |
| Chief Legacy and Coexistence Officer | Nothing new promised; the first-generation record stays authoritative and v2's on-file row is a pointer; invite only members whose first-generation case is closed. |

**Vote:** 7/7 owner-only results, no new access, never used for employment. **Tension:** rating colleagues: CFO and Product require every criterion recorded 'unknown / none' (strength: binding (Product)).

**Decision (provisional):**

- The promise: trial access only; no new mailbox or access; nothing held by the first-generation service changes; the first-generation record stays authoritative and v2's on-file row is a pointer (Legacy).
- Binding (Product, CFO): for a cohort member, every rubric criterion is recorded capability 'unknown', strength 'none', note 'not assessed: internal trial (D-M)'; a coded refusal enforces it while D-M applies.
- Results are seen by the owner only, used to evaluate the system, never for pay, role, assignment, promotion, discipline or continued work, and never exported per person (CRM, tracker, brain or scorecard). Any such use is a breach reported to counsel (agreements advisor).
- Invite only members whose first-generation case is closed (Legacy). The owner sends a closing message before closing each case (Product). The go/no-go states a count or upper bound.

### Q7. Coexistence (211.7.3): keep D-51; what makes it final; rollback window

| Seat | Recommended answer |
|---|---|
| CTO / Chief Architect | Keep D-51, final on preflight items H18, H19, H24, H25; rollback window the observation period, owner executes, no case moves back. |
| General Counsel | Keep D-51; a rollback leaves retention and erasure duties in force; decommissioning means erasing every cohort member. |
| CISO | Keep D-51; final after the preflight proves isolation; rollback window the whole observation period. |
| COO / Head of Release Operations | Keep D-51; rollback open for the observation period, 30-minute target, owner executes; any first-generation regression means rollback first. |
| CFO / Strategic Operator | Keep D-51, final on the preflight's evidence; rollback window the observation period, owner executes. |
| Head of Product and Applicant Experience | Keep D-51, final on the preflight; a rollback serves the existing 'unavailable' page and the owner emails each member. |
| Chief Legacy and Coexistence Officer | Keep D-51, final in three parts: host on the preflight (and a second read after the dark deploy); mailbox and timers on the legacy packet before the mail canary; Documenso on the canary's negative control; rollback within one hour; any first-generation effect pauses v2. |

**Vote:** 7/7 keep D-51, final on evidence. **Tension:** Legacy's three-part finality; rollback target 30 min (COO) vs one hour (Legacy) (strength: mild).

**Decision (provisional):**

- Keep D-51. Record it final in three parts (Legacy): host isolation on the preflight's evidence and a second read after the dark deploy; mailbox and timers on the legacy packet (dy7.4) before the mail canary; Documenso on the canary's negative control.
- Rollback stays available for the whole observation period, executed by the owner within one hour; any first-generation effect traced to v2 pauses v2 at once; a rollback leaves retention and erasure duties in force (GC).

### Q8. Staff, devices, authority, fields (211.7.5, 211.7.8); the two human-only selection rules

| Seat | Recommended answer |
|---|---|
| CTO / Chief Architect | Owner only staff with the only grant; form as built; required details empty; production refuses every decline while D-M applies, so both rules wait for F. |
| General Counsel | Owner only staff with the grant; name, email, reason; both rules wait for F. |
| CISO | Owner only staff; staff site excludes the development host; agents lose shell access to the production host, or the owner accepts that in writing, before real intake; minimal fields; rules deferred. |
| COO / Head of Release Operations | Owner alone on two named devices with two-factor; grant to the owner; minimal fields; both rules deferred to F. |
| CFO / Strategic Operator | Owner alone, two named devices, private network; grant to the owner; name, email, reason; build both rules now (about 15 lines) and refuse 'decline' in the cohort. |
| Head of Product and Applicant Experience | Owner only staff with the grant; name, invited email and optional note, claim fields hidden; POL-18 empty; build both rules before real intake. |
| Chief Legacy and Coexistence Officer | Owner only staff; minimal fields; both rules deferred to F. |

**Vote:** 7/7 owner alone as staff with the grant; minimal fields. **Tension:** selection rules: defer (5) vs build (CFO, Product); CISO's agent-shell condition (strength: strong (CISO)).

**Decision (provisional):**

- The owner is the only staff member and holds the only qualification grant (explicit_permission); two named devices with two-factor; the staff site on the private network, excluding the development host.
- Form: name, the invited email and a reason or optional note; claim fields hidden while intake is invitation-only; POL-18 empty.
- The two human-only selection rules wait for F, because production refuses every cohort decline (decision 5) (majority 5-2; CFO and Product dissent recorded).
- Binding (CISO): before real intake, agent sessions lose shell access to the production host, or the owner accepts that access in writing in the go/no-go record.

### Q9. Production values (211.7.7, 211.7.2): lifetimes, quiet hours, RPO/RTO, paging, incident ownership

| Seat | Recommended answer |
|---|---|
| CTO / Chief Architect | Defaults; challenge 24 hours; RPO one day plus a 15-minute journal-lag alert; RTO 4 hours; page issued_agreements at 72 hours; Buzz; owner owns incidents. |
| General Counsel | Defaults, reminders stop on withdrawal; owner owns incidents; counsel told the same day of any personal-data event; any deputy can only pause. |
| CISO | Defaults; challenge 3,600 seconds; RPO one day, RTO four hours; pages for journal lag, lockouts and ruleset changes; a deputy only receives pages. |
| COO / Head of Release Operations | Challenge 24 hours; quiet hours 02:00-13:00 UTC (the built 21:00-07:00 UTC sends overnight in US Central); DB RPO 24 h, journal RPO 15 min; RTO 4 h; custody 24 h; host rebuild 2 working days; owner plus a no-access second reader. |
| CFO / Strategic Operator | Built values; challenge 24 hours; RPO nightly plus pre-deploy dump; RTO 4 hours; owner, no deputy, one working day; stack stays paused if the owner is unreachable. |
| Head of Product and Applicant Experience | Defaults; challenge 24 hours; quiet hours in UTC covering the cohort's night (02:00-14:00 UTC); RPO/RTO from the restore drill; deputy paging-only. |
| Chief Legacy and Coexistence Officer | Defaults; challenge one hour; RPO one day, RTO four hours; drills and dumps clear of the first-generation backup window; owner owns incidents, stop-only deputy. |

**Vote:** 7/7 built defaults as starting values. **Tension:** challenge lifetime 24 h (CTO, COO, CFO, Product) vs 1 h (CISO, Legacy); deputy: none (CTO, CFO) vs paging/stop-only (5) (strength: mild).

**Decision (provisional):**

- Keep the built defaults as starting values. Challenge lifetime 24 hours (4-2; CISO and Legacy's one hour recorded; the link is single-use and address-bound).
- Quiet hours 02:00-13:00 UTC (COO), fixing the built window that lets reminders out overnight in US Central.
- Database RPO 24 hours; journal-lag page at 15 minutes; restore RTO 4 hours from acknowledgement, confirmed by the drill; custody recovery 24 hours; host rebuild 2 working days.
- Pages through the estate's Buzz alert floor, adding journal lag, lockouts, ruleset changes and issued_agreements at 72 hours; the aged-wait thresholds and the default page list are set per class.
- The owner owns incidents. A deputy is optional and stop-only; if the owner is unreachable the stack stays paused. Counsel is told the same day of any personal-data event (GC).

### Q10. The owner's shortest path: classification, ordered owner acts, repository work the agent may start

| Seat | Recommended answer |
|---|---|
| CTO / Chief Architect | Nine ordered owner acts; the agent may start 9kg.80, H18-H25, the TOTP test, 9kg.75, template variables and the provisional lock. |
| General Counsel | Seven owner acts starting with authorizing counsel; repository-only work starts now. |
| CISO | Protections need not precede the ratifications; they precede the deploy credential and merging decided registry and custody values; agent starts 9kg.80, 9kg.75, TOTP, H18-H25. |
| COO / Head of Release Operations | One sitting (ratify, counsel, private inputs); template approval; GitHub protections; one host go; one provider go; counsel's answers then final values and notices; go/no-go. About 7 to 11 working days of agent-side work, excluding counsel's turnaround. |
| CFO / Strategic Operator | Two waves (wave 1: owner plus members with both agreements, signing off; wave 2 adds signing). Ratify, counsel email, protections, private inputs, host go, templates after counsel, mail canary only, go/no-go. |
| Head of Product and Applicant Experience | Nine acts, the first two in one sitting; the agent starts 9kg.80, 9kg.75, H18-H25, TOTP, and draft PRs unmerged until ratification. |
| Chief Legacy and Coexistence Officer | One ratification sitting plus counsel, then protections, host go, wording, provider go, go/no-go; agent starts 9kg.80, 9kg.75, H18-H25, the draft registry release, the dy7.2 skeleton and an abort threshold. |

**Vote:** 7/7 one ratification sitting first; repository work starts now. **Tension:** two waves (CFO, echoed by GC and Legacy); protections before the final values merge (CISO) (strength: mild).

**Decision (provisional):**

- Recommended to the owner, not adopted on the owner's behalf: a two-wave internal launch (CFO, with GC and Legacy). Wave 1: the owner plus members with both agreements on file, signing off, so custody and the Documenso canary leave wave 1's critical path. Wave 2 adds signing. Both precede wider enrollment. Owner ratification needed because it changes what the go/no-go covers.
- Owner acts in order: (1) one sitting: ratify this record, authorize the counsel send, record the private inputs; (2) the 032 section 1 GitHub protections; (3) one host go (preflight, host preparation, dark deploy, restore drill); (4) counsel's answers, then final values and the wording approvals; (5) one provider go, the mail canary first; (6) the go/no-go for wave 1; (7) wave 2.
- The agent may start now: 9kg.80; 9kg.75; preflight items H18-H25; the TOTP test (PR #126); the registry release with the provisional lock; the cohort guards (decline refusal, unrated criteria, empty POL-18 in production); lifetimes as template variables; the quiet-hours and wait-class defaults; 9kg.73; the dy7.2 skeleton. Agent-side work between owner acts is about 7 to 11 working days (COO), excluding counsel's turnaround.

## 6. Legal advisors (non-voting)

- **Privacy, retention and erasure.** The per-class structure is defensible as a provisional setting. Three items are not fit for real data as drafted: R4's conditional start, the keyed hash kept for the deployment's life, and the blank R3. The residue after erasure is pseudonymous, not anonymous, in a small group of colleagues. Leaving required details anonymized-and-replayed differs legally from crypto-shredding by the backup exposure window; acceptable for the cohort only with no sensitive fields, the window disclosed and a fixed cleanup date. The counsel packet is regrouped into questions before real intake (jurisdiction, HR-data status, legal basis and voluntariness, retention periods, the erasure clock and outcome, the keyed hash, backups, holds, agreements, providers, the not-appraisal control, monitoring rules, notice sufficiency, sensitive fields, risk assessment and breach duties) and questions before wider enrollment.
- **Agreements, notices and the employment boundary.** Referencing first-generation agreements depends on their wording, not on their existence: counsel must clear it in writing per member, otherwise the member signs the full v2 set, never a mix. A hand countersignature is adequate in principle if the owner's signing authority, electronic-record consent and a digest check are in place. The 'not an assessment' promise must be narrowed and backed by a written use rule, no HR export and an access log; the colleagues' status and location change the analysis. The company's counsel being a cohort member is a conflict to manage: disclosure, not the sole reviewer of member-rights points. Both advisors marked every contact, period and promise in the drafts as a slot to be filled, and drafted a minimal decline notice and a cohort promise with slots.

## 7. Council memos: the decision most costly to get wrong

- **CTO / Chief Architect:** Q2(a): filling the registry removes the only coded refusal between real rows and the object-locked off-site backup.
- **General Counsel:** Signed documents set to key destruction at every erasure: irreversible, the provider copy goes too, and NDA obligations outlive the engagement.
- **CISO:** Escrowing the wrapping key to a key the development host can decrypt; with agent shell access to production, one session could open every signed document in unrecallable backups.
- **COO / Head of Release Operations:** Approving the data notice before counsel's launch-blocking answers: it opens intake, and real data enters an object-locked backup that only ages out.
- **CFO / Strategic Operator:** Counsel's answer on whether anonymization counts as erasure; the whole chain is built on it, and a 'no' after real data is backed up means a rebuild under deadline.
- **Head of Product and Applicant Experience:** Q6: as built, admitting a member records a rating per rubric criterion that survives erasure: a permanent appraisal of a colleague.
- **Chief Legacy and Coexistence Officer:** The mailbox and timer boundary (Q7 part two): mail the first-generation service has acted on cannot be unsent or reconciled.

Tally: real data reaching the object-locked backup before the registry, counsel or the notice is right (CTO, COO, CFO, and GC through key destruction): 4 of 7. Escrow reachable by an agent (CISO), appraisal of colleagues (Product), the first-generation mailbox boundary (Legacy): 1 each.

## 8. Cross-cutting themes

- Counsel before content: no real data enters the object-locked backup before counsel's launch-blocking answers and a coded refusal holds until then. (Q1, Q2, Q3, Q5)
- Mechanism over memory: every 'the owner withholds approval' gate gets a coded refusal behind it. (Q2, Q5, Q6, Q8)
- The agent session is the attack surface: keys, escrow and production shell access sit where no agent can reach. (Q1, Q4, Q8)
- Dogfooding must not become appraisal: unrated criteria, owner-only results, no export. (Q5, Q6)
- Spend the owner's attention once: one ratification sitting, one host go, one provider go, two waves. (Q10)

**Adversarial integrity.** All seven seats agreed on the substance of nine questions; dissent was on mechanisms: how intake stays shut (coded lock or withheld approval), where the escrow key may live, whether colleagues are rated, the challenge lifetime, the selection rules, and how many waves. Each dissent with a strength of 'strong' or 'binding' is absorbed as a constraint. The novel options (the provisional lock, owner-only escrow, unrated criteria, the two waves, three-part coexistence finality, erasing the dark deploy's subjects as the first production erasure proof) each came from one seat.

## 9. Decision tree

```text
Q1 POL-10 values ──── 7/7 adopt ── 7 amendments stacked ───────────── ADOPTED
Q2 registry now ───── 7/7 fill ─── lock: coded (3) vs withheld (4) ── coded lock BINDING
   crypto-shred gap ─ 7/7 accept ─ POL-18 empty, refused if not ────── ADOPTED
Q3 counsel ────────── 7/7 send now ── owner authorizes ────────────── RECOMMENDED
Q4 custody ────────── 7/7 adopt ── escrow off every agent key ─────── CISO BINDING
Q5 agreements ─────── 7/7 adopt ── (a) only if counsel clears ─────── ADOPTED
   wording ────────── 7/7 rework ─ not approved ──────────────────── RETURNED
Q6 promise ────────── 7/7 owner-only ── criteria unrated ─────────── PRODUCT BINDING
Q7 coexistence ────── 7/7 keep D-51 ── three-part finality ───────── ADOPTED
Q8 staff ──────────── 7/7 owner only ── rules: defer 5 / build 2 ─── defer; CISO shell BINDING
Q9 values ─────────── 7/7 defaults ── challenge 24h 4 / 1h 2 ─────── 24h; quiet hours fixed
Q10 path ──────────── one sitting ── two waves (CFO) ─────────────── RECOMMENDED to owner
most costly: real data in the locked backup too early x4; escrow, appraisal, mailbox x1 each
```

## 10. Implementation directives

| Where | Directive |
|---|---|
| `011` section 4 | Record these decisions as D-52, provisional, owner ratification required. |
| `031` | Section 8 item 3 is superseded (production is admitted); item 1's second option is not available as built (no backup, no migration). |
| Beads 211.7.1 to 211.7.9 | A note on each with this record's provisional answer and what the owner must ratify or supply. |
| New repository work (agent, reviewed PRs) | The registry release with the provisional lock; cohort guards (decline refusal, unrated criteria, no non-empty POL-18 in production); lifetimes as template variables; quiet hours and wait-class defaults; R3 start event and a structured clocks table for 9kg.75. |
| Held for the owner | Ratification; the counsel send; private inputs (holders, devices, member facts by role and country, escrow recipients); the two-wave split; the wording approvals; every host and provider go. |

## 11. Acting head of board declaration

Signed as acting head of board, designated by the owner on 2026-10-28. The binding minority positions (the coded lock, escrow outside every agent-reachable key, unrated criteria, the agent-shell condition, protections before the final values) are absorbed rather than dismissed. Every decision is provisional until the owner ratifies it; the owner may override any row, and an override is recorded in `011` section 4 as a later decision. Not made: no wording approved, no counsel contacted, no legal conclusion presented as settled, no host, provider, real-data or launch act.

## 12. Provenance

Derived from the council session's structured record (session header, ten questions, seven seat positions, two advisor memos, ten vote tallies, seven memos, five themes, the synthesis, the decision and the owner's ratification), kept with the council pattern on the owner's development host and backed up nightly.

## 13. Owner ratification

On 2026-10-28 the owner ratified this record ("ratified, two waves, send counsel the packet"):

- Decisions 1 to 9 stand as recorded. Values the record sends to counsel (the R1 to R4 periods, the keyed hash, option (a) per member, the wording) stay provisional until counsel answers; the coded provisional lock keeps intake refused until then.
- The two-wave launch (decision 10) is adopted. Wave 1: the owner plus members with both first-generation agreements on file, counsel clearing the reference, signing off; its go/no-go is `9kg.31.6`. Wave 2 adds signing after POL-09, the Documenso canary and counsel's Part B answers (`9kg.31.12`).
- The counsel packet was authorized and sent the same day to the company's counsel, grouped as Part A (before wave 1), Part B (before wave 2) and Part C (before wider enrollment). The members' facts sheet by role and country follows from the owner.
- Still held: wording approval, every host and provider go, and the go/no-go for each wave.
