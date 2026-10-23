# Council record: the internal production launch decisions of 2026-10-23

| Field | Value |
|---|---|
| Document | 030-AT-DECR-council-record-internal-launch-decisions-2026-10-23 |
| Date | 2026-10-23 |
| Acting head of board | Claude Code, designated by the owner on 2026-10-23 ("act as council and thinker canon where need be and complete the work; I would like to move to the new system as soon as possible") |
| Council | seven seats, substituted for this domain (section 5) |
| Decisions | ten, adopted provisionally for the internal launch; owner ratification at the go/no-go (`9kg.31.6`) or earlier in session |
| Status | PROVISIONAL (council-adopted, not owner-ratified); recorded as D-51 in `011` section 4 |
| Inputs | `029` sections 5 to 14 (the decision brief is section 14, D-A to D-M); `011` sections 4, 6, 7, 11; `019`; `026`; `028` |
| Pattern | the Intent Solutions Executive Decision Council (ISEDC); the verbatim seat positions are in the council session record on the owner's development host (not tracked) |
| Classification | Public repository: no private hostnames, addresses, paths, people, participant data or agreement text |

## 1. Purpose

The owner asked on 2026-10-23 that the work behind `029` proceed and that the decisions standing in its way be taken by a council acting for the owner. This record is that council's output: for each question, the seven seats' recommended answers verbatim, the vote, the primary tension, the decision and its rationale. Every decision is provisional until the owner ratifies it; nothing here authorizes a host, provider, real-data or launch act. The owner's recorded exclusions (D-49, D-50) are not upgraded by this record.

## 2. Why a council, not a single review

Three of the ten questions are irreversible if wrong (the Documenso team, retention and erasure, the deploy credential's identity binding); the others pit speed against evidence with one maintainer and a live first-generation service on the shared host. Single-reviewer reasoning had already produced the plan's recommendations; the council's job was to find where they fail, who must act, and what can run now.

## 3. Synthesis lenses

1. Speed with a reversible footprint. 2. One writer per case, mailbox, envelope, callback and timer. 3. Real people's data, judged as if for external applicants. 4. A single maintainer: a control that deadlocks is not a control.

## 4. The questions

| Question | Subject | Why it is costly if wrong |
|---|---|---|
| Q1 | D-A: host for the internal cohort | a changed matcher on the live host breaks links in real applicants' hands |
| Q2 | D-B: the Documenso team and webhook | a sealed document archived into the wrong custody store cannot be erased |
| Q3 | D-C and the critical path: build the erasure chain now, or wait for counsel | real data in an object-locked backup with no erasure path ages out, never purges |
| Q4 | D-D, D-D2, D-E: the cohort's legal posture | a re-sign double-processes an existing member; plaintext custody of real documents |
| Q5 | D-D3, D-D4, D-D5, D-F, D-G, D-H: provisional production values | a value that reaches a real person or a host before the go/no-go |
| Q6 | D-I, D-K: the receipt and scan gates | an undrilled digest on a shared production host |
| Q7 | D-J: GitHub protections, the agent token and the repository move | a deploy credential born before the protections, or in an agent session |
| Q8 | D-M: is the internal cohort candidate-impacting selection | selection obligations applied or skipped for real people |
| Q9 | The authority scope of the owner's instruction of 2026-10-23 | an act taken without the authority it needs, or a go asked for that buys nothing |
| Q10 | The shortest safe path to a dark deploy | a serialization that spends the owner's attention or shares host state |

## 5. Council composition

The default seven-seat roster was substituted for this domain; the owner was not available to confirm the substitution, so it is recorded here. Seats: CTO / Chief Architect (durability, schema integrity, Django idioms, reversibility); General Counsel (data-protection law, retention, consent, agreement validity, the counsel boundary); CISO (threat model, least privilege, custody, deploy credentials, repository controls); COO / Head of Release Operations (cadence, environment separation, deployment evidence, restore, the single-ingress procedure); CFO / Strategic Operator (a single maintainer's bandwidth, opportunity cost, launch-blocking versus gold-plating); Head of Product and Applicant Experience (what the cohort and the operator experience, feature parity, no dead ends); Chief Legacy and Coexistence Officer (the live first-generation service and its applicants, one writer, nothing excerpted). Each seat argued from its value system and named the seats it expected to clash with.

## 6. Per-question record

### Q1. D-A: host for the internal cohort

Recommended answers, verbatim:

- **CTO / Chief Architect.** Dedicated v2 host name; learning host untouched; record the P6-D-11 amendment as cohort-only.
- **General Counsel.** Dedicated v2 host name; learning host untouched; D-09 kept for the public cutover.
- **CISO.** Dedicated v2 host name; the learning host untouched; D-09 kept for the public cutover.
- **COO / Head of Release Operations.** Dedicated host name; the learning host's configuration byte-untouched at launch; D-09 kept for GATE-CUTOVER.
- **CFO / Strategic Operator.** Dedicated v2 host name; the learning host untouched; D-09 kept for the public cutover.
- **Head of Product and Applicant Experience.** Dedicated host name, learning host untouched, D-09 kept for GATE-CUTOVER.
- **Chief Legacy and Coexistence Officer.** Dedicated host name; record the P6-D-11 amendment for the cohort only; D-09 kept for GATE-CUTOVER.

**Vote and tension.** 7 of 7 for a dedicated v2 host name. No dissent. Conditions raised: the preflight hashes the live proxy configuration before and after the new name is added (COO, Legacy); the P6-D-11 amendment is recorded as cohort-only (all).

**Decision.** A dedicated v2 host name for the internal cohort. The learning host's proxy configuration is byte-untouched at launch; the preflight records its hash before and after the new site block is added. P6-D-11 is amended for the cohort only; D-09 stays the rule for the public cutover under GATE-CUTOVER.

**Rationale and dissent.** Unanimous. The rollback is a site block and a reload; a changed matcher on the live host is a cutover done early, against links already in real applicants' hands.

### Q2. D-B: the Documenso team and webhook

Recommended answers, verbatim:

- **CTO / Chief Architect.** Separate Documenso team with v2's own webhook target; the canary proves it.
- **General Counsel.** Separate v2 team with its own webhook; the canary proves no cross-delivery either way.
- **CISO.** A separate Documenso team with its own webhook target and secret; if the installed instance cannot create one, agreements stay disabled rather than shared.
- **COO / Head of Release Operations.** Separate team; the canary proves the installed instance supports it (U3) and that the countersign sweep cannot match v2 envelopes (U4).
- **CFO / Strategic Operator.** Separate Documenso team with its own webhook.
- **Head of Product and Applicant Experience.** Separate team, own webhook, own templates; the canary's negative control proves the legacy countersign step ignores v2 envelopes.
- **Chief Legacy and Coexistence Officer.** Separate team, with v2's own templates and its own external-key prefix; the canary's negative control proves the legacy sweep never acts on a v2 envelope.

**Vote and tension.** 7 of 7 for a separate Documenso team with v2's own webhook, templates and external-key prefix. The split is on the fallback if the installed instance cannot create a second team (U3): agreements stay disabled rather than shared (GC, CISO), stop and reconvene (Legacy), or the shared team only with a v2 ownership filter plus a canary negative control with the legacy gate unmodified (CTO, COO, CFO, Product). Six of seven seats named D-B the decision most costly to get wrong.

**Decision.** A separate Documenso team for v2, with v2's own webhook target and secret, its own templates and its own external-key prefix. If the installed instance cannot create a second team, agreements stay DISABLED at the internal launch and the council reconvenes; the shared team is never used as a fallback by default. The canary's negative control proves the first-generation sweep never acts on a v2 envelope, with the first-generation gate unmodified. The separate team lands before the first new participant signs, which may be after the dark deploy.

**Rationale and dissent.** Unanimous on the team; the fallback takes the GC, CISO and Legacy minority as binding because six of seven seats named this the decision most costly to get wrong: a sealed document archived into the wrong custody store and swept into object-locked backups has no rollback.

### Q3. D-C and the critical path: build the erasure chain now, or wait for counsel

Recommended answers, verbatim:

- **CTO / Chief Architect.** Build 9kg.32, 9kg.34 and 9kg.25 now against section 6.1 with the proposed values labelled PROVISIONAL; POL-10 gates the first real backup only.
- **General Counsel.** Build 9kg.33, 9kg.32, 9kg.34, 9kg.25 now with PROPOSED values; POL-10 and POL-09 recorded before any real submission; the counsel question leaves today.
- **CISO.** Build now; the counsel decision moves from gating code to gating the first non-owner real backup.
- **COO / Head of Release Operations.** Build against 029 6.1 with the proposed values recorded as provisional; counsel's decision gates the first real backup and the go/no-go, not the code.
- **CFO / Strategic Operator.** Build 9kg.32, 9kg.34, 9kg.25 now; POL-10 gates the first real backup, not the code.
- **Head of Product and Applicant Experience.** Build 9kg.32, 9kg.34, 9kg.25 against section 6.1 with proposed values; counsel's decision gates the first real backup.
- **Chief Legacy and Coexistence Officer.** Build 9kg.32, 9kg.34, 9kg.25 now against 6.1, retention values as settings; POL-10 gates the first real backup, not the build.

**Vote and tension.** 7 of 7 to build the erasure chain now. Novel tightening from GC: the gate is the first real submission, not the first real backup, because the nightly dump and the object-locked off-site leg fire automatically the night a real row exists; CISO and COO add that the go/no-go also waits. CTO and Product: every retention value ships as 'undecided: refuse'. COO: 9kg.33 first. GC: the counsel question leaves today.

**Decision.** Build the erasure chain now, as repo-only work: 9kg.33 (the effect journal), then 9kg.32 (the erasure path and record), 9kg.34 (custody encryption with keys outside the application backup's rollback domain), 9kg.25 (replay after restore). Every retention value and per-class treatment lives in a registry that ships as 'undecided: refuse'; the erasure command and any real backup refuse to run while a value is undecided. POL-10 and POL-09 are recorded with counsel before the first real submission (not merely the first real backup) and before the go/no-go; the dark deploy and its drills run on synthetic subjects without them. The data-class table of 029 section 6.1 goes to counsel now with its values marked PROPOSED. A shape change from counsel (not a value change) reopens the bead before launch.

**Rationale and dissent.** Unanimous. Counsel decides values; the mechanism does not change shape with the answer. The GC's tightening (first real submission) is adopted because the nightly dump and the off-site leg fire automatically.

### Q4. D-D, D-D2, D-E: the cohort's legal posture

Recommended answers, verbatim:

- **CTO / Chief Architect.** Adopt all three as recommended.
- **General Counsel.** Adopt, with per-member verified completion recorded in v2, manual countersign, key destruction in the map, and the provider copy named in POL-10.
- **CISO.** Adopt with the three sharpenings above (encryption before the Documenso canary; keys outside the application backup's rollback domain; a reference, never a copy).
- **COO / Head of Release Operations.** Adopt as recommended.
- **CFO / Strategic Operator.** Adopt all four parts unchanged.
- **Head of Product and Applicant Experience.** Adopt all three as recommended, plus one full real signing journey in the cohort.
- **Chief Legacy and Coexistence Officer.** Adopt all three; add that the owner's countersignature is performed only in v2's team.

**Vote and tension.** 7 of 7 adopt. Sharpenings: 'referenced, not re-signed' is a per-member fact the owner records by hand from the private roster, naming the agreement version and a verified completion, with no legacy identifier and no document copy (GC, CTO, CISO, Legacy); a member without a verified completion is a new participant (GC); the countersignature is performed only in v2's team and its wait gets a page threshold (Legacy, COO); custody keys live outside the application backup's rollback domain and encryption precedes the Documenso canary (CISO); key destruction belongs in the erasure map and the provider's retained copy is named in POL-10 (GC); one full real signing journey, the owner's, exercises the agreement screens (Product).

**Decision.** Adopted. Existing members are referenced, not re-signed: for each member the owner records by hand, from the private roster, that an agreement is on file, naming the agreement version and that completion was verified; no legacy identifier and no document copy enters v2; a member without a verified completion is a new participant. New participants sign the current versions on v2's own templates. The owner countersigns by hand, only in v2's team; the countersignature wait gets a page threshold in 211.7.2. Custody is under the managed data root, encrypted with recoverable keys held outside the application backup's rollback domain, and the encryption is in place before the Documenso canary; key destruction is part of the erasure map and the provider's retained copy is named in POL-10 as a manual handoff. Model advice is off and verified from inside the running containers; oc4.12 is a real decision form. One full real signing journey, the owner's own, exercises the agreement screens before wider enrollment.

**Rationale and dissent.** Unanimous with sharpenings from GC, CISO, Legacy and Product, all adopted.

### Q5. D-D3, D-D4, D-D5, D-F, D-G, D-H: provisional production values

Recommended answers, verbatim:

- **CTO / Chief Architect.** Adopt all as provisional; hold only the named devices and holders for the owner now, because host preparation consumes them.
- **General Counsel.** Adopt D-D3, D-D5, D-F, D-G, D-H as provisional; hold POL-05, template approval and the field list for an explicit owner record before first use.
- **CISO.** Adopt as provisional, with staff restriction and credential absence enforced at host preparation and the security abort threshold adopted now.
- **COO / Head of Release Operations.** Adopt all; nothing held for the owner now (RPO and RTO ratified from the production restore drill's measurement).
- **CFO / Strategic Operator.** Adopt all as provisional production values ratified at the go/no-go; one owner sitting, not seven.
- **Head of Product and Applicant Experience.** Adopt all as provisional; templates and the challenge lifetime approved now.
- **Chief Legacy and Coexistence Officer.** Adopt all as provisional; D-F held as a fixed rule, not provisional.

**Vote and tension.** 7 of 7 adopt as provisional values ratified at the go/no-go, with named holds that differ by seat: named devices and holders before host preparation (CTO, CISO); POL-05 decision group, template approval with hashes and the form-field list before first use (GC); templates and the challenge lifetime before the mail canary (Product); D-F a fixed rule (Legacy); RPO and RTO ratified from the production restore drill's measurement (COO); the security-event abort threshold adopted now (CISO); nothing held (CFO).

**Decision.** Adopted as provisional production values, ratified in one owner sitting at the go/no-go, with these exceptions. Before host preparation: the named staff devices and their holders (host preparation consumes them). Before the mail canary: the verification, question, reminder and decline templates approved one version each with their hashes, and the challenge lifetime. Before the first real use: the decision group (POL-05) and the form-field list (POL-18), recorded in one owner decision row the day the package is drafted. Fixed rules, not provisional: provisioning disabled and no drill touches an existing mailbox (D-F); the security-event abort threshold of 029 section 10 applies from the dark deploy; the absence of the provisioning credential on the host is enforced at host preparation. RPO and RTO are ratified from the production restore drill's measurement, with section 10's proposals as the targets the drill is measured against.

**Rationale and dissent.** Unanimous on the principle; each seat's named hold is adopted where the value reaches a real person or a host before the go/no-go.

### Q6. D-I, D-K: the receipt and scan gates

Recommended answers, verbatim:

- **CTO / Chief Architect.** Mismatch refuses; fixable high and critical fail.
- **General Counsel.** Refuse on mismatch; fail on fixable high and critical.
- **CISO.** Receipt mismatch refuses and holds; fixable high and critical fail the required contract, with an expiring waiver mechanism.
- **COO / Head of Release Operations.** Mismatch refuses; fixable high and critical fail the required check.
- **CFO / Strategic Operator.** Adopt both.
- **Head of Product and Applicant Experience.** Receipt mismatch refuses; fixable high and critical fail.
- **Chief Legacy and Coexistence Officer.** Refuse on mismatch; fixable high and critical fail the contract.

**Vote and tension.** 7 of 7 adopt both gates. Compromise shared by all: an expiring, owner-granted exception only for an unfixable finding; the receipt gate has no exception.

**Decision.** Both are gates. A deployment-receipt mismatch refuses the deploy and holds; there is no exception path. Fixable high and critical image findings fail the required check contract; an unfixable finding may be excepted only by an owner-granted, dated, expiring record with a bead, never a standing advisory.

**Rationale and dissent.** Unanimous.

### Q7. D-J: GitHub protections, the agent token and the repository move

Recommended answers, verbatim:

- **CTO / Chief Architect.** Protections now; scoped agent token; 9kg.4 before 9kg.35, or after launch, never between.
- **General Counsel.** Protections now; scoped agent token; move before 9kg.35 or after launch.
- **CISO.** Protections now; scoped token for every agent session; the repository move before the protections or never.
- **COO / Head of Release Operations.** Protections now; scoped agent token; the move after launch.
- **CFO / Strategic Operator.** Execute 9kg.35 now; scoped agent token; 9kg.4 after the launch.
- **Head of Product and Applicant Experience.** Protections now; scoped token; move after launch.
- **Chief Legacy and Coexistence Officer.** Protections now; scoped token; move after launch.

**Vote and tension.** 7 of 7 for the protections now and 7 of 7 for a scoped agent token without administration, environment-approval, secrets or Actions-variable rights. The repository move: after the launch or never (COO, CFO, Product, Legacy); before 9kg.35 or after launch (CTO, GC); before the protections or never (CISO). Nobody accepts a move between a credential's creation and its first use.

**Decision.** The GitHub protections are applied now, before any deploy credential: a main ruleset requiring a pull request and the two required checks pinned to the Actions app, linear history, no force-push or deletion, an empty bypass list; a release environment limited to main with the owner as reviewer, recorded as not independent; the merge-guard registration names both checks. The act is executed by the owner's own hand from a prepared, idempotent script with a readback, never by an agent session. Sub-decision 1: agent sessions get a scoped token with no administration, environment-approval, secrets or Actions-variable rights, mandatory from the moment the protections land and before any deploy credential exists. Sub-decision 2: the repository move 9kg.4 happens after the launch's observation period or never; never between a credential's creation and its first use; if it ever happens, every readback and trust subject is repeated.

**Rationale and dissent.** Unanimous on protections and the token. The move: the majority (after launch) is adopted; the CTO and GC alternative (before 9kg.35) is not taken because it would put an identity change in front of the launch for no launch value.

### Q8. D-M: is the internal cohort candidate-impacting selection

Recommended answers, verbatim:

- **CTO / Chief Architect.** No; defer each named item to external applicants, listed in the record.
- **General Counsel.** No, each deferred item named, plus a cohort notice and POL-10 as go/no-go items.
- **CISO.** No, with each deferred item named and the data controls unchanged.
- **COO / Head of Release Operations.** No; each deferred item named and attached to the wider-enrollment decision.
- **CFO / Strategic Operator.** No; deferred to external applicants, each item named.
- **Head of Product and Applicant Experience.** No, with the deferred list named, the plain data notice and the scorecard not deferred, and the four flip conditions recorded.
- **Chief Legacy and Coexistence Officer.** No, with every deferred item named; add a rule that no decline is recorded in v2 for an existing member (hold or withdraw instead).

**Vote and tension.** 7 of 7: not candidate-impacting selection. Binding conditions: the four flip conditions recorded (Product); every deferred item named and attached to the wider-enrollment decision (all, COO); not deferred: a plain data notice on the intake form and in the invitation, an approved decline notice if a decline is possible, and POL-10 (GC, Product); the human-only form follows 019 section 5 and records the policy identifier as 'none: internal cohort, D-M' (CTO, Product); the scorecard runs from day one (Product); no v2 decline is recorded for an existing member (Legacy); the 'no' lapses if model advice is enabled or anyone off the roster enters (GC).

**Decision.** No: the internal cohort is not candidate-impacting selection under 011 section 7, on four recorded conditions, any failure of which flips the answer to yes: participants are already team members; the admission changes nothing about their work or standing; the decision group is the owner alone; model advice and evidence fetching are off. Deferred to external applicants, each named: the automated-assessment notices (POL-17), the alternative-evidence routes and the correction path, reviewer preparation (f1u.5), SP-L2-1 (f1u.2, f1u.6), the scorecard as a gate (f1u.7), outcome validation (f1u.8) and the evaluation oc4.7; they attach to the wider-enrollment decision 9kg.31.10 as blockers for anyone not pre-selected. Not deferred: a one-paragraph data notice on the intake form and in the invitation (what is collected, who sees it, that no model reads it and no link is fetched, how to withdraw and request erasure); an approved decline notice if a decline is possible; POL-10; the 019 section 5 rules in the human-only form; the policy identifier recorded as 'none: internal cohort, D-M' on every cohort decision; the 019 section 9 scorecard run from day one, including the count of shell or database edits; and no v2 decline is ever recorded for an existing member (hold or withdraw instead). The 'no' lapses the moment model advice is enabled or anyone outside the roster enters.

**Rationale and dissent.** Unanimous on the answer; the GC, Product, CTO and Legacy conditions are adopted in full.

### Q9. The authority scope of the owner's instruction of 2026-10-23

Recommended answers, verbatim:

- **CTO / Chief Architect.** Repo-only and the erasure chain proceed; everything from 9kg.35 outward waits for its own recorded go, with each go pre-drafted.
- **General Counsel.** Covered: the repo-only batch and the read-only preflight; everything else a named go.
- **CISO.** Covered: repo-only and the read-only preflight; GitHub-admin by the human's own hand; everything else awaits its recorded go.
- **COO / Head of Release Operations.** Line at 9kg.28. Request one bundled host go and one bundled provider go. Three goes, not seven.
- **CFO / Strategic Operator.** Covered: repo-only, erasure chain, GitHub-admin, host read, legacy read. Two batched goes for host write and canaries; the go/no-go stays the owner's.
- **Head of Product and Applicant Experience.** Repo-only, GitHub-admin, host read and the packet read proceed; host write, canaries and launch each wait for a go.
- **Chief Legacy and Coexistence Officer.** Covered: repo-only and owner-run GitHub-admin. Needs a recorded go: host read, host write, the packet, canaries, launch.

**Vote and tension.** Repo-only batch: 7 of 7 covered. Erasure chain: 7 of 7 covered as repo-only. GitHub-admin: covered when executed by the owner's own hand (CFO, COO, Product, Legacy, CISO) versus its own go (GC, CTO). Host read 9kg.42: covered (CFO, COO, Product, CISO, GC if names and counts only) versus a recorded go (CTO, Legacy). Legacy packet dy7.4: its own go (CTO, GC, CISO, COO, Legacy) versus covered as a read (CFO, Product). Host write, provider canaries and the launch: 7 of 7 not covered. Bundling the remaining goes by blast radius: COO, CFO (three goes, not seven); GC (several goes may be given in one recorded line).

**Decision.** Covered by the owner's instruction without a further go: the repo-only batch of 029 section 13.3; the erasure chain under Q3; preparing every later go (the ruleset script and readback, the preflight command list, the packet's question list, each go request drafted as one line with rollback and abort conditions). Executed by the owner's own hand from the prepared script, not by an agent session: the GitHub protections and the scoped token. Each of the following needs its own recorded go, bundled by blast radius into three: (1) the host go, covering the read-only preflight 9kg.42, host preparation 9kg.28, the dark deploy 9kg.31.5 of the current attested digest, the production restore drill and the rehearsal dy7.3, with the legacy evidence packet dy7.4 as a separately receipted read in the same window; (2) the provider go, covering the three canaries one at a time; (3) the launch, GATE-PILOT, which is a signature. The preflight is held behind the host go rather than treated as covered because D-50 recorded 'reading or changing Learn's live proxy configuration' as not authorized, and a council cannot upgrade an owner's recorded exclusion; the go is prepared so it is a one-line act.

**Rationale and dissent.** The line is the first action whose undo is not a revert in this repository and whose subject is a shared live surface. The CTO and Legacy minority on the preflight is binding because of D-50's wording; the COO and CFO bundling is adopted so the owner is asked three times, not seven.

### Q10. The shortest safe path to a dark deploy

Recommended answers, verbatim:

- **CTO / Chief Architect.** Six serial steps, three parallel lanes, migration-graph work serialized per app.
- **General Counsel.** The chain above; the dark deploy may precede POL-10, the go/no-go may not.
- **CISO.** Protections and scoped token, then attested digest, then host preparation, then dark deploy; repo-only and read-only work in parallel beside it.
- **COO / Head of Release Operations.** Preflight, protections beside it, host preparation, dark-deploy the current attested main digest, the production restore drill, the rehearsal, then the launch-candidate redeploy; the go/no-go waits for the erasure chain, the batch and the policy decisions.
- **CFO / Strategic Operator.** Three owner touches to the go/no-go: one decision sitting, one host go, one canary go.
- **Head of Product and Applicant Experience.** Batch plus erasure chain, walkthrough, release prep, preflight-then-host-prep, dark deploy.
- **Chief Legacy and Coexistence Officer.** Preflight first, decide D-A and D-B on its evidence, then host preparation; nothing on the shared host runs concurrently with anything else that writes there.

**Vote and tension.** Agreement on the lanes: the repo-only batch and the erasure chain run now; the policy decisions run beside; the preflight precedes any host write; protections precede any deploy credential; the go/no-go waits on the erasure chain, the batch and POL-10/POL-09. Novel option (COO): dark-deploy the current attested main digest first to prove the host, the force-command, attestation verification on the target and the production restore drill, then redeploy the launch candidate through the drilled wrapper; CTO's rule that release preparation of the launch candidate waits for the batch's last migration is compatible. Product puts the screen walkthrough 9kg.41 on the critical path before release preparation. Legacy requires the preflight's evidence before 211.7.3 is recorded as final.

**Decision.** Three lanes. Lane A, repository, now and in parallel: the section 13.3 batch (migrations to the same app merged serially); the screen and exceptional-state walkthrough 9kg.41 once items 3's beads land; the erasure chain 9kg.33, 9kg.32, 9kg.34, 9kg.25, serial within itself. Lane B, owner, minutes: this record; the protections and the scoped token from the prepared script; the counsel question for POL-10 and POL-09; one sitting for the remaining 211.7.x values. Lane C, host, under the host go, serial: the preflight read; 211.7.3 recorded as final on its evidence; host preparation (after the protections readback, never overlapping it); the dark deploy of the current attested main digest with every activation held; the production restore drill with RPO and RTO measured; the rehearsal against the live baseline; then, once lane A's last migration is on main, release preparation 9kg.31.4 of the launch candidate and its redeploy through the drilled wrapper. Then the provider go and the canaries one at a time, then the go/no-go, which waits on lane A complete, POL-10 and POL-09 recorded, and the remaining decisions. Never parallelized: two edits to the shared ingress configuration; host preparation and the dark deploy; any migration and any deploy; the restore drill and any other write to the production database; the three canaries with each other; the Documenso canary before the ownership register and the rehearsal; any canary against the shared mail host while the first-generation mailbox's other readers are unknown; credential creation while an agent session holds owner credentials; the repository move with anything credential-bearing; any routing change on the learning host with anything at all.

**Rationale and dissent.** The COO's host-proof-first ordering is adopted because a dark deploy carries no real data and proves what the dev-box staging never could; the CTO, CISO, Legacy and Product sequencing constraints are stacked onto it.

## 7. Council memos: the decision most costly to get wrong

- **CTO / Chief Architect:** Q3 (D-C)
- **General Counsel:** D-C, runner-up D-B
- **CISO:** Q2 (D-B)
- **COO / Head of Release Operations:** D-B
- **CFO / Strategic Operator:** D-B
- **Head of Product and Applicant Experience:** D-B
- **Chief Legacy and Coexistence Officer:** D-B

Tally: D-B (the Documenso team): CISO, COO, CFO, Product, Legacy, and GC's runner-up (6 of 7). D-C (retention and erasure): CTO and GC (2 of 7).

## 8. Cross-cutting themes

- Reversibility is the test (CTO, COO, CFO): every adopted option keeps the undo inside the system that made the change, and speed comes from parallel repo-only work and bundled goes, not from skipping goes.
- Mechanism versus policy (GC): build the mechanism now with values held at 'refuse'; a named human records the policy; the audit trail is the product.
- Identity binding (CISO): bind the name, then create the credential, then let it act; an agent session holding owner credentials is the largest open risk and is closed by the scoped token.
- The cheapest read first (Legacy): the plan's unknowns settle with one read-only preflight; nothing beside the live service is touched before it.
- Honest dogfooding (Product): the go/no-go package lists the screens the cohort did not exercise beside those it did; every control that resolves to 'the owner, by shell' is a product defect counted by the scorecard.

**Adversarial integrity.** Seven seats, ten questions: unanimous recommended answers on nine, a three-way split on the repository move and a split on the authority line for the preflight, the GitHub-admin actor and the legacy packet. The novel options (host-proof dark deploy first; the first-real-submission gate; the 'undecided: refuse' registry; the four flip conditions) each came from one seat and were adopted. Consensus on the answers reflects that the plan's recommendations were already the reversible ones; the dissent concentrated on who acts and when, which is where the value systems differ.

## 9. Decision tree

```text
Q1 host ─────────── 7/7 dedicated name ──────────────────────────────── DECIDED
Q2 Documenso ────── 7/7 separate team ── fallback split ── minority (disable) BINDING
Q3 erasure ──────── 7/7 build now ──── GC tightening (first real submission) ADOPTED
Q4 legal posture ── 7/7 adopt ──────── 4 sharpenings ─────────────────── ADOPTED
Q5 values ───────── 7/7 provisional ── 6 named holds ──────────────────── ADOPTED
Q6 gates ────────── 7/7 both gates ─────────────────────────────────────── DECIDED
Q7 protections ──── 7/7 now + token ── move: 4 after / 2 before-or-after / 1 before-or-never
Q8 selection ────── 7/7 no ──────────── 7 conditions not deferred ──────── ADOPTED
Q9 authority ────── split on preflight (5 covered / 2 go) ── D-50 wording ── minority BINDING
                    split on GitHub actor (5 owner hand / 2 go) ──────────── owner's hand
                    split on legacy packet (5 go / 2 read) ────────────────── its own go
Q10 path ────────── lanes agreed ──── COO host-proof-first NOVEL ─────────── ADOPTED
most costly: D-B x6 (incl. GC runner-up), D-C x2
```

## 10. Implementation directives

| Where | Directive |
|---|---|
| 011 and 029 | Record this council's decisions as D-51 in 011 section 4 (provisional for the internal launch; owner ratification at the go/no-go or earlier in session) and point 029 section 14 at this record. Main-session, this PR. |
| Beads: erasure chain | Remove the POL-10 and POL-09 code blockers from 9kg.32 and 9kg.34 (they gate the first real submission and the go/no-go, which already wait on 211.7.1 and 211.7.9); add 9kg.32 after 9kg.33; add the 'undecided: refuse' registry to 9kg.32's acceptance; add the keys-outside-backup rule to 9kg.34. Build in a worktree after batch item 4 lands. |
| Beads: walkthrough | 9kg.41 stays on the critical path before 9kg.31.4; its scope is 029 section 5.2's states plus the three disabled capabilities' refusals. |
| Beads: protections | 9kg.35 gains the prepared script and readback as its first step and the scoped-token sub-decision as a recorded condition; executed by the owner. |
| Beads: host lane | 9kg.42, 9kg.28, 9kg.31.5, dy7.3 and dy7.4 are requested under one host go; 9kg.31.5's scope records the host-proof deploy of the current attested digest before the launch-candidate redeploy; the production restore drill is named in 9kg.31.5's acceptance. |
| Beads: policy | Notes on 211.7.1 to 211.7.9 and oc4.8 carry the council's provisional answer, the named holds and the counsel packet; 9kg.31.10 lists f1u.5, f1u.2, f1u.6, f1u.7, f1u.8 and oc4.7 as blockers for anyone not pre-selected. |
| Beads: intake notice | A new task under 9kg.43's parent adds the one-paragraph data notice on the intake form and in the invitation, and the policy identifier 'none: internal cohort, D-M' on cohort decisions. |
| Outputs for the owner | outputs/owner-go-requests.md (three one-line goes with rollback and abort conditions), outputs/counsel-question-pol-10-pol-09.md (the data-class table with PROPOSED values), and the prepared ruleset script in the repository. |

## 11. Acting head of board declaration

Signed as acting head of board, designated by the owner on 2026-10-23. The minority positions on the Documenso fallback, the preflight's go and the GitHub-admin actor are absorbed as binding constraints rather than dismissed. Every decision above is provisional until the owner ratifies it, in session or at the go/no-go; the owner may override any row, and an override is recorded in `011` section 4 as a later decision.

## 12. Provenance

Derived from the council session's structured record (session header, seven seat positions, ten vote tallies, cross-cutting themes, ten decisions, the synthesis) kept with the council pattern on the owner's development host and backed up nightly. The seat files are kept there in full; this document carries each seat's recommended answers verbatim and the decisions.
