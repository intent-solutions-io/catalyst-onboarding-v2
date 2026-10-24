# P3 Evidence, Assessment and Qualification Specification (handoff 3A)

| Field | Value |
|---|---|
| Document | `018-AT-DSGN-p3-evidence-assessment-specification` |
| Version | 0.2.5 (2026-10-17: section 18 added for 3C; 0.2.4 added section 17 for 3B.4; 0.2.3 added section 16 for 3B.3; 0.2.2 corrected the status line and added section 15). The owner's approval D-34 covers version 0.2.1, sections 1 to 12; sections 13 and 14 are implementation records; section 15 and the P3-D-10 amendment were approved by D-35 |
| Status | **APPROVED by the owner 2026-10-14 (version 0.2.1; D-34 in `011` section 4), with the recommended defaults `P3-D-1` to `P3-D-16` for synthetic P3.** 3B.1 (PR #30, `d564bfa`) and 3B.2 (PR #32, `8086508`) are merged; 3B.3 was released on 2026-10-16 (section 16), 3B.4 and 3C on 2026-10-17 (sections 17 and 18); GATE-P3 signed off 2026-10-17 (D-36). Selection-quality integration (section 15) and the P3-D-10 amendment were approved by D-35. Approval authorizes no live model call, real fetching, real applicant data, real mail, versioned release or deployment. |
| Owner | Jeremy Longshore |
| Date | 2026-10-13 |
| Epic | P3, "Collect evidence, run the bounded MiniMax assessment, and record the authorized qualification decision" (`catalyst-v2-oc4`); this task is `catalyst-v2-oc4.1` |
| Baseline | main `a2688e3` (P2 accepted, D-33) |
| Builds on | `004` J-04, J-05, J-06, J-07, J-10; `002` REQ-008, REQ-009, REQ-010, REQ-029, REQ-033, REQ-034; `003` ADR-01, ADR-03, ADR-04, ADR-13, ADR-14, ADR-15; `005` S1.4 (ledger rules); `016` (P2 contracts, especially section 1 and 10.12) |
| Classification | Public; synthetic data only; no provider key, real applicant or real source is named |

## 0. How to read this document

A fresh engineer should be able to answer five questions from this document alone:

1. **What is a claim?** Something the applicant says about themselves (section 2).
2. **What was observed?** What a deterministic, approved check actually found, where and when, including
   "unavailable" and "inconclusive" (section 3).
3. **What did the model infer?** MiniMax's advisory reading of one frozen snapshot, with quoted support and
   stated limitations (section 5).
4. **What remains unknown?** Every record carries what it cannot prove (sections 2, 3 and 5).
5. **Who may decide, and how does every failure recover?** Only the authority POL-05 names, as a separate
   audited act (section 7); failures go to staff, never to an adverse outcome (sections 4 and 6).

Tags used for facts: **DOCUMENTED** (an official source says so; URL given), **INSPECTED** (read in this
repository's code or docs), **DEMONSTRATED** (a test or run showed it), **NOT VERIFIED** (unknown; a later
task must establish it).

## 1. Scope and boundaries

**In scope (P3):** structured applicant claims; deterministic evidence collection from an owner-approved
source list against synthetic fixtures; a bounded assessment through PydanticAI with test models; the
clarification loop through the existing P2 correspondence services; reply interpretation through the
existing P2 interface; the audited qualification decision and its held hand-off to P4.

**Out of scope:** any live model call (until a separate authorization, section 9 B); any real source fetch
(until GATE-PILOT conditions, section 9 C); executing submitted code, cloning or running repositories,
opening attachments; Documenso, NDA issue or provisioning (P4, P5); a new applicant portal; a second
workflow engine, vector database, agent framework comparison or model fallback provider.

**Four separate records.** None silently becomes another:

| Record | Meaning | Written by | Can never |
|---|---|---|---|
| **Applicant claim** | What the person says: work, contribution, experience, credentials | the applicant, through an adopted submission version | count as verified |
| **Evidence observation** | What an approved deterministic check found, where and when, including unavailable or inconclusive | the worker, from an approved source | be read as dishonesty or lack of ability when unavailable |
| **Model assessment** | MiniMax's advisory reading of one frozen snapshot, with quotes and limitations | the assessment handler | choose a stage, satisfy a question, send, decide, issue or provision (a run's completion moves the stage to `awaiting_decision` unconditionally; no output field influences any transition) |
| **Authorized decision** | What the permitted human decided, with a reason and exact input references | a decision-maker named by POL-05 | be made by a model, a superuser shortcut or a stale input |

**What each kind of evidence can and cannot establish:**

| Fact | Can be established by | Cannot be established by |
|---|---|---|
| Control of an email address | the S1 confirmation (exists) | anything in P3 |
| Control of a linked account | a challenge the applicant completes on that account (out of P3 scope; NOT designed here) | a link to a profile, which anyone can paste |
| Authorship of, or contribution to, a work | partial support: the applicant's own contribution statement plus an observation that the work exists and names them; never proof | repository stars, commit counts, polished writing, model confidence |
| Possession of a claimed credential | an issuer's public verification page for that credential identifier, from an approved source (future source; fixture only in P3) | a certificate image, a badge, the applicant's statement |
| Suitability under the approved rubric | a human decision informed by claims, observations and the advisory assessment | the model's recommendation alone |

## 2. Applicant claims and how they enter the product

**Today (INSPECTED):** the intake form has three fields (name, email, reason); `SubmissionVersion.submitted_fields`
holds them; a confirmation adopts exactly one version. That is not an evidence application.

**Recommended (smallest adequate extension, PROPOSED for POL-03):** extend the same public form, and therefore
the same versioned, adopted `SubmissionVersion`, with optional structured claim fields. No new portal; the
existing versioning, adoption and repeat-submission rules (J-02, J-03) apply unchanged:

| Claim field | Shape | Bound |
|---|---|---|
| Work samples | up to 3 entries: URL, one-line description | each URL at most 2,048 characters; https only |
| Contribution statement | free text: what the applicant personally did in those works | 2,000 characters |
| Relevant experience | free text | 2,000 characters |
| Credentials | up to 3 entries: name, issuer, credential identifier or verification URL | each field at most 200 characters |
| Confidential-work alternative | a checkbox "my relevant work is private or under confidentiality obligations" plus a description of the kind of work, without client names or secrets | 2,000 characters |

- **Private or confidential work.** The form tells the applicant, in plain words, never to disclose client
  secrets, credentials or confidential material. The alternative path is a description plus a
  staff-arranged conversation; an unavailable or private source is recorded as *unavailable*, never as a
  negative finding.
- **Alternative considered:** collect evidence later through a P2 staff question (the applicant replies with
  links). Rejected as the default because a reply is free text that must be parsed and is not part of the
  adopted version; it stays available for follow-up evidence (section 4, step 7).
- **Earliest blocking task:** 3B.1 builds the fields (synthetic wording); real wording is POL-17 and
  GATE-PILOT.

Claims are stored only inside the adopted submission version; P3 creates no second claim store.

## 3. Evidence observations: deterministic collection

### 3.1 Sources (POL-03)

`EvidenceSource` is the owner-approved allow-list. Each source names: a key, a kind (`work_sample_page`,
`credential_verification`, `profile_page`), an exact host (lower-case punycode, no wildcard), port, path
prefix, allowed redirect hosts (default none), allowed content types, byte cap, deadline, whether it is
required, and what happens when it is unavailable (`continue`, `ask_applicant`, `staff`). Approval needs a new
permission `approve_evidence_source` held by an owner-run group.

**Recommended first source set (PROPOSED):** exactly two kinds, both synthetic in P3:

1. `work_sample_page`: a public HTML or plain-text page at a URL the applicant listed, on an approved host.
2. `credential_verification`: an issuer's public verification page for a listed credential identifier.

Profile pages and code-hosting APIs are deferred: they invite stars and commit counts as proxies, which
section 1 forbids as qualification evidence.

### 3.2 Observation record

`EvidenceItem` is a slot (one per listed source and URL for the adopted version; mutable status
`pending → fetched | unavailable | refused`). `EvidenceCapture` is the immutable observation:

| Field | Content |
|---|---|
| source and request | the source key, the request URL and its digest |
| retrieval | fetched time (database clock), attempt number, final URL, HTTP status, content type, peer address |
| relationship | the claim it answers (work sample n or credential n) and the claimed relationship ("applicant says they contributed") |
| revision | the source's revision marker where one exists (an `ETag`, a last-modified header or a version string in the page); otherwise none |
| content | a bounded derivative (visible text, scripts, styles, comments and hidden elements removed; control, zero-width and bidi characters stripped), its SHA-256, the SHA-256 of the bytes read, the derivation version, a truncation flag |
| outcome | `found`, `found_but_inconclusive`, `not_found`, `unavailable`, `refused`, with a reason code |
| cannot prove | a fixed statement per kind, stored with the observation: a work page cannot prove authorship; a credential page cannot prove the person presenting it is the holder |
| markers | deterministic injection markers found in the content (instruction-like phrases, delimiter look-alikes) |

No raw bytes are stored (as in P2, pending POL-10); the cost is that a derivative cannot be re-verified,
only re-fetched as a new capture.

### 3.3 Safe URL handling (REQ-029; built in 3B.1 against fixtures)

1. **URL:** `https` only; the source's port; no userinfo; at most 2,048 characters; fragment dropped; the host
   must be a DNS name (any IP-literal form, including decimal, octal and hex, is refused); IDNA to punycode;
   exact host match; path normalized (dot segments, encoded dots) before the prefix check.
2. **Resolve** every A and AAAA record under a bounded wait (resolution in a worker thread with a deadline,
   because `getaddrinfo` has none); refuse the host if **any** address fails one pure function
   `classify(ip)` with **no environment branch**. It allows only global unicast after unwrapping IPv4-mapped,
   IPv4-compatible, 6to4 (2002::/16), Teredo (2001::/32) and NAT64 (64:ff9b::/96, 64:ff9b:1::/48) forms, and
   denies explicitly: private, loopback, link-local, CGNAT, multicast, reserved, unspecified, 192.0.0.0/24,
   scoped (`%zone`) forms, 169.254.169.254, fd00:ec2::254, and the host's own interface and public
   addresses (hairpin). It is tested against the pinned Python's behaviour, not assumed. This is a new
   function: P2's `transport.peer_allowed` has the opposite purpose (it admits loopback test hosts).
3. **Connect to the validated IP literal** with TLS SNI and certificate verification for the hostname
   (no re-resolution between check and connect).
4. **Re-check the connected peer** with `classify` before any request bytes (the same check point as P2's
   mail transport, with the opposite rule).
5. **Redirects** off by default; at most 3, each re-passing steps 1 to 4 and listed in the source; never to
   http.
6. **Limits:** connect timeout; the socket timeout set to the remaining deadline before every read (so a
   slow drip cannot outlast it); streamed byte cap; GET only; fixed User-Agent; `Accept-Encoding: identity`
   and any other `Content-Encoding` refused; no connection reuse or HTTP/2 coalescing across hosts; one URL
   parser for validation and the request, sending the normalized path that was checked (trailing-dot hosts,
   backslashes and userinfo differentials handled); no cookies, auth headers, proxy environment or
   credential forwarding; response-header size cap; content types from the source; per-source and per-host
   rate limits.
7. **Allow-list checks at fetch time, not only at start-up.** Sources are database rows approved at runtime,
   so every fetch re-checks the source's status and host, and every capture records the source **version**
   (a source row is immutable once approved; a change is a new version needing approval). A settings-level
   host allow-list, empty outside `test` and refused by a start-up guard elsewhere, bounds every source.
   Synthetic fixtures are admitted only through a source marked `fixture_only` for one exact host and port,
   which the guard refuses outside `test`; the fixture path runs the same `classify` code. Real fetching
   stays unreachable until GATE-PILOT; production also needs a network egress allow-list (P6).
8. **Nothing in the public web request** fetches, previews or dereferences an applicant URL; staff screens
   show applicant URLs as text.
9. **Logging:** host and reason code only; never the path, query, headers or body.

**Never:** execute submitted code, clone or run a repository, open an attachment, or fetch a URL the model
produced. An attachment's metadata (from P2) is not its content and not proof of a claim; attachment
ingestion needs its own explicit boundary.

## 4. The P3 journey, step by step

Lock order everywhere: application, then the item, run or question, then the pending action (the ledger's
fenced write). External calls (fetch, model) run between a claim transaction and a fenced record
transaction, never under a domain lock.

| # | Step | Trigger and owner | Exact inputs | Records and transaction | Next durable action | Outcomes | Retry, interruption, staleness | Staff see and may | Acceptance |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Activate evidence collection | the held `start_evidence_collection` action (exists, INSPECTED); released by the activation rule (4.1) | the adopted version in `input_ref` | one transaction: stage `contact_verified → evidence`, one `EvidenceItem` per claim and approved source, one `fetch_evidence` action each, an event | `fetch_evidence` per item, or straight to step 4 if none | stage moved; no slots | redeliverable; a changed adoption refuses with a staff item | item list; pause | TEST-P3-09, 10 |
| 2 | Fetch one item | `fetch_evidence:<item>` (automated) | the item and its source | eligibility transaction; fetch outside; fenced record: capture, item status, event | the next item; when none is pending, step 3 | found, inconclusive, not found, unavailable, refused | bounded retry for transient errors; refused is not retried; a stale lease discards the result; pause refunds the attempt | each observation and its "cannot prove"; request a re-fetch | TEST-P3-05, 06, 11 to 18 |
| 3 | Deterministic checks | the record transaction of the last item | all items of the adopted version | one transaction: required-item policy evaluated; stage `evidence → assessing` | `run_assessment` (step 4; enqueued from 3B.2, see 13), or a staff item `evidence_required_unavailable` | proceed; hold for staff | the application lock serializes the last two fetches; the unique key makes one run | proceed without, or re-fetch | TEST-P3-19, 20 |
| 4 | Assess | `run_assessment:<app>:<snapshot digest>` (automated) | the frozen snapshot (section 5.1) | freeze transaction writes `AssessmentRun` + inputs; pre-call check records the **invocation** (budget reserved) before the call; call outside; fenced record writes the result once and, **whatever the output says**, compare-and-sets the stage `assessing → awaiting_decision` (staff now own the next step) | the decision queue (step 9), with any proposals visible (step 5) | succeeded, invalid output, provider error, timeout, budget stop, refused (input changed) | section 6; a result whose lease was lost is **discarded** (the reservation is the only accounting); a run that fails leaves the stage at `assessing` with a staff item | run, inputs, output, usage, failures; rerun | TEST-P3-01, 02, 03, 08, 21 to 33 |
| 5 | Propose clarification | the run's record transaction | the run's `proposed_questions` | `Question(origin=model, approval_state=proposed)` through a `correspondence` service plus a link to the run; **no stage change** | staff approval (P2 `approve_question`); approving the first question of a round moves `awaiting_decision → awaiting_answers` (a staff act) | proposed; deduplicated; round cap reached | never sent until staff approve; dedup by normalized text per application; at most 3 per round | approve, edit by withdrawing and authoring, withdraw | TEST-P3-34, 35 |
| 6 | Staff author a question | a staff screen (new, 3B.3) | staff text | `Question(origin=staff)`; then P2 approval and send | P2 sending | sent | P2 rules | author, approve, withdraw | TEST-P3-36 |
| 7 | Reply and additional evidence | P2 collection and processing (exists) | an eligible reply (P2 `eligible()`) | P2 records; P3 coalesced interpretation (5.4) | staff confirmation (P2 D3) | P2 outcomes; links in a reply become new claims only through a new submission version or a staff-entered claim | P2 rules | P2 screens plus the proposal | TEST-P3-37 to 41 |
| 8 | Reassess | a staff-confirmed answer, or staff "reassess" | a new snapshot including confirmed answer spans | as step 4, round n+1 | as step 4 | as step 4 | at most 3 rounds; the same snapshot runs once (TEST-P3-07) | rerun | TEST-P3-07, 42 |
| 9 | Decide | a decision-maker on the decision screen | the latest valid run, **the snapshot digest the decision-maker saw**, and the adopted version | one transaction: recompute the current manifest digest and refuse any difference; compare-and-set the stage from `awaiting_decision`; `QualificationDecision`; event; held follow-on (`issue_nda` or `send_decline`) | P4 hand-off (held) | admit, decline, hold | no retry (a human act); a stale snapshot, a pending evidence item or a run in flight refuses | section 7 | TEST-P3-04, 43 to 49, 51 to 53 |

### 4.1 Activation and backfill of held work

Held rows are never claimed by the ledger (`claim_next` takes only queued and expired-running rows;
INSPECTED), so registering a handler cannot run them. The activation command is therefore a **release gate**:

- `start_evidence_collection` rows stay `held`. An owner-run command `activate_evidence_collection
  --activation-version 1 --approval-ref <011 decision id>` releases (to `queued`) only rows whose application
  is still `contact_verified`, not terminal, not paused, with an adoption matching `input_ref`. It refuses
  without an approval reference (the POL-03 and POL-04 records) and logs it on each release event.
- A row whose adopted version has no claim fields (created before the form extension) is not released: it gets
  a staff item `claims_missing`, so an empty snapshot never reaches a model.
- `interpret_reply` rows (per question, held, INSPECTED) are never released individually (5.4).

### 4.2 Stale input and concurrent change

| While a run or fetch is in flight | Result |
|---|---|
| a newer submission version arrives, unadopted | ignored; the run uses the adopted version (TEST-P3-08); the existing `newer_unverified_version` staff item opens (S1 rule) |
| the application leaves `assessing` meanwhile (closed or withdrawn; `on_hold` is only ever a recorded `hold` decision, from `awaiting_decision` or, for a human-only assessment, from `assessing`; section 17) | the record transaction compare-and-sets the expected stage `assessing`; on a mismatch it records the run and transitions nothing |
| the adoption changes | the pre-call or record check finds a different snapshot digest: the run ends `refused: input_changed`, no transition, a staff item |
| evidence changes (re-fetch) | a new capture; the frozen snapshot still names the old one; the result is valid history for that snapshot only |
| a reply is re-derived | the derivative digest pin (P2 10.9) no longer matches: interpretation ends `text_changed` |
| a question is answered or withdrawn | the run's proposals for it are dropped at record; P2 withdrawal cancels held work (exists) |
| staff decide | the decision is final; a later run result is kept as history and transitions nothing |
| automation pauses | claims stop (automated kinds only); an in-flight call still records its result **and** its `assessing → awaiting_decision` move, because a stage move has no external effect (it only puts the application in the staff decision queue); no proposal is sent and no further automated action runs until resume |
| the application closes | the result is recorded as history; no transition, no question |

## 5. The model contracts

### 5.1 The frozen snapshot

A run is bound to a manifest, written in its freeze transaction and digested (`snapshot_sha256`):
the adopted version id and the SHA-256 of its canonical fields; each eligible capture id and derivative
SHA-256; each confirmed answer span (message id, derivative SHA-256, offsets); the open question set; the
rubric version and SHA-256; the prompt-pack version and SHA-256; the output-schema version. Later
unverified submissions keep their own provenance and are never inputs. The idempotency key includes the
snapshot digest, so one snapshot is assessed at most once.

### 5.2 What may leave Catalyst (the data-use boundary, PROPOSED)

| Allowed (minimized, sanitized) | Never |
|---|---|
| run-local aliases ("applicant", E1..En, Q1..Qn) | name, email, phone, address, IP, identifiers, UUIDs |
| the adopted claim fields (work-sample descriptions, contribution, experience, credential names and issuers) | the verification link, any token or credential, raw email, headers |
| capture derivatives, each at most 8,000 characters, at most 12, total at most 40,000 | unrelated correspondence, staff notes, resolution notes |
| confirmed answer spans only, each at most 2,000 characters | quoted text, our own sent text, unadopted versions |
| the rubric criteria from the approved pack | other applicants, agreements, Intent OS or brain content, coding-agent memory |
| for reply interpretation: the reply derivative outside quoted ranges, its versions, and the exact question texts | the full reply, quoted text and our sent body (`sent_body` stays local, used only by `validate_proposals`) |
| deterministic observation booleans such as `names_applicant` (computed locally: does a page name the applicant, by exact and normalized name match) | the applicant's name itself |

**Free text is the weak point.** Claim text, page derivatives and replies can carry names, addresses, phone
numbers and URLs. Every outgoing free-text field is scrubbed first (email addresses, phone numbers and URLs
replaced by placeholders; the applicant's name and its normalized variants replaced by the alias), and the
canary tests cover free text, not only structured fields. Residual risk, stated: third parties' names and
details in fetched pages are not reliably detectable and would leave with the page text; this is why real
content needs the provider review (F-16) and an explicit authorization.

Every untrusted item is fenced as data (`<<DATA alias nonce>> … <</DATA nonce>>` with a per-run nonce; any
delimiter look-alike in content neutralized), Unicode-normalized and stripped of control, zero-width and
bidi characters. The model has no tools and no network. **No real applicant content may be sent under this
specification;** the boundary above is what an owner authorization would approve.

### 5.3 Assessment output (`AssessmentOutput`, schema version 1)

| Field | Type and bound | Rule enforced by code after parsing |
|---|---|---|
| `criteria` | 1 to 8 findings | exactly one per rubric criterion, no extras |
| finding `rating` | `supported`, `partly_supported`, `not_supported`, `insufficient_evidence` | any rating but `insufficient_evidence` needs a citation |
| finding `summary` | at most 300 characters | cleaned; no URL or HTML |
| `citations` | at most 3 per finding: an alias and a verbatim quote (1 to 300 characters) | the alias exists in this request; the quote occurs verbatim in exactly the sanitized text that was sent for that item; code computes offsets (the model never gives offsets); a citation overlapping a deterministic injection marker is flagged |
| `recommendation` | `admit`, `decline`, `hold` | advisory only |
| `recommendation_basis` | at most 600 characters; 1 to 8 criterion ids | ids exist in the rubric |
| `confidence` | `low`, `medium`, `high` | no numeric score |
| `proposed_questions` | 0 to 3: text (at most 400), criterion id, why needed (at most 200) | no URL, address or credential request |
| `injection_suspected` | boolean, with 1 to 4 citations when true | informative only |
| `limitations` | at most 5, each at most 200 characters | e.g. truncated items, unavailable sources |

The bounds keep the largest valid output near 10,000 characters (about 2,500 tokens). Injection markers are
computed on the sanitized derivative (after hidden elements are stripped), so markers and quotes refer to the
same text; any `<think>` block inline in `content` (F-13) is removed before parsing and never stored.

Cross-checks stored, never silently corrected: `admit` with a required criterion `not_supported` is flagged
`inconsistent_recommendation`; a truncated item cannot support `not_supported`; an unavailable source can only
yield `insufficient_evidence`. No hidden reasoning is requested or stored (any reasoning part the provider
returns is discarded).

**A valid schema is not a true assessment, and a citation that exists is not necessarily support.** The
mechanical checks above prove shape and provenance only; quality is section 9 B.

### 5.4 Reply interpretation: extend the existing interface

The contract already exists in `correspondence/processing.py` (INSPECTED): `ReplyInterpreter`,
`InterpretRequest`, `QuestionRef`, `QuestionProposal`, `Span`, `Provenance`, `InterpretResult`,
`InterpretUnavailable`, `eligible()`, `validate_proposals()` and `quoted_ranges()`. P3 **implements** that
protocol in `assessments`; it creates no second interface (the `016` mention of `correspondence/interpreter.py`
is superseded by the actual module).

- **Coalescing.** P2 holds one `interpret_reply:<message>:<question>` row per pending question. P3 adds one
  message-level action `interpret_message:<message>:<derivative digest>`; the per-question held rows stay as
  staff-visible shadows. One reply therefore causes at most one model call per derivative.
- **Layering.** The `interpret_message` handler is a thin class in `correspondence/processing.py` (so
  `correspondence` never imports `assessments`, and the existing `dispatch_problems` prefix rule holds). It
  resolves the implementation through a code-fixed setting `CATALYST_REPLY_INTERPRETER` (the
  `CATALYST_ATTENTION_OPENER` pattern), pinned by `dispatch_problems` to `assessments.` and refused from the
  environment. The P3 assessment handlers (`fetch_evidence`, `run_assessment`) need `dispatch_problems` to
  admit the `assessments.` prefix: an explicit, tested amendment.
- **Cancellation.** `_cancel_interpretation` is extended to cancel `interpret_message` rows, so a staff
  confirmation, closure or withdrawal cancels queued work; the pre-call transaction also re-checks that the
  message is still `awaiting_processing` and undecided, so nothing is disclosed after staff decided.
- **Creation.** `ProcessReply` creates the message-level row when the reply is eligible and the activation
  version is in force (a setting checked in `correspondence`); earlier replies are released only by the
  versioned activation command.
- **Inputs:** `eligible()` checked before the request, at pre-call and at record; exact question ids;
  `derived_text_sha256`, derivation and redaction versions; `quoted_ranges`; the sent body.
- **Output:** per question an outcome and up to 10 verbatim quotes; the adapter locates each quote uniquely
  outside quoted ranges, builds `Span`s and calls `validate_proposals(request, proposals, stored_sha256,
  provenance)`. Add the missing rule: a question requiring evidence with no attachment or link present yields
  `evidence_required_but_absent`.
- **Authority:** proposals are stored on the run, never in `QuestionReplyLink`; staff still confirm through
  `confirm_question_outcome`, which requires a user and cannot be called by the handler. Turning on automatic
  application would need a new owner decision and new code, not a setting.
- **Eligibility default:** only `trusted` replies (not `staff_associated`, which `eligible()` admits) go to a
  model; the adapter adds this rule and a test proves it (pending the owner's decision P3-D-6).

### 5.5 Provider and framework

| Item | Proposal | Status |
|---|---|---|
| Framework | PydanticAI agent per contract; no tools | per ADR-04 |
| Test model | `TestModel` and scripted `FunctionModel`; real requests disabled for all tests | see 5.6 |
| Live model | MiniMax through an OpenAI-compatible client with an explicit base URL. Refused in every environment until authorized, by three layers: `models.ALLOW_MODEL_REQUESTS = False` set in the app's `ready()` for every environment; a provider factory that has no live branch reachable without an authorization setting refused by a new start-up guard; and an HTTP transport in tests that raises on any request. Agent instrumentation that exports prompts is forbidden. As built in 3B.2 (see 14): the flag is set when `assessments/agent.py` is imported, not in `ready()`, and the raising transport is deferred to live enablement | see 5.6, 14 |
| Output mode | PydanticAI tool output as the candidate (MiniMax documents function tools), prompted output as the fallback, never native JSON-schema output (undocumented); our strict validation always; the authorized synthetic probe decides | F-2, F-11, F-12 |
| Pins | one PydanticAI version, one model identifier, recorded on every run | owner decision P3-D-8 |

### 5.6 Official documentation findings

Official documentation only, read 2026-10-13. The pages were read through a summarizing fetch, so quotes are
extracts: **re-verify each one verbatim before 3B.2 pins versions** (that check is part of 3B.2).

| # | Fact | Source | Tag |
|---|---|---|---|
| F-1 | PydanticAI's latest published version is 2.55.0 | `https://pypi.org/pypi/pydantic-ai/json` | DOCUMENTED |
| F-2 | Output modes: tool output is the default ("supported by virtually all models"); native output uses the model's structured-outputs (JSON schema) feature and is "not supported by all models"; prompted output works with any model but "is often the least reliable approach" | `https://pydantic.dev/docs/ai/core-concepts/output/` | DOCUMENTED |
| F-3 | Testing: `TestModel`, `FunctionModel` and `Agent.override`; `models.ALLOW_MODEL_REQUESTS = False` blocks requests to non-test models (default `True`) | `https://pydantic.dev/docs/ai/guides/testing/`, `https://pydantic.dev/docs/ai/api/models/base/` | DOCUMENTED |
| F-4 | `UsageLimits` has `request_limit`, `tool_calls_limit`, `input_tokens_limit`, `output_tokens_limit`, `per_request_input_tokens_limit` and `cost_limit`; exceeding one raises `UsageLimitExceeded`. **Corrected in 3B.2:** version 2.55.0 also has `total_tokens_limit` (DEMONSTRATED by inspecting the installed signature) | `https://pydantic.dev/docs/ai/core-concepts/agent/` | DOCUMENTED; total-tokens limit DEMONSTRATED |
| F-5 | Output retries: `retries={'output': N}` (default 1); each `ModelRetry` from a validator consumes one unit; exhaustion raises `UnexpectedModelBehavior` | `https://pydantic.dev/docs/ai/core-concepts/retries/` | DOCUMENTED |
| F-6 | Provider SDK and transport retries are not counted toward `request_limit` | `https://pydantic.dev/docs/ai/core-concepts/retries/` | DOCUMENTED; hence section 6 sets SDK retries to 0 |
| F-7 | An OpenAI-compatible endpoint is used through `OpenAIProvider` with a custom `AsyncOpenAI` client (`base_url`); `openai-chat:` pins Chat Completions | `https://pydantic.dev/docs/ai/models/openai/` | DOCUMENTED |
| F-8 | Model-profile flags declaring tool or JSON-schema support; handling of thinking parts | the profile and thinking pages | NOT VERIFIED (not found; the thinking page returned 404) |
| F-9 | MiniMax OpenAI-compatible base URL `https://api.minimax.io/v1`; an Anthropic-compatible URL also exists | `https://platform.minimax.io/docs/api-reference/text-openai-api` | DOCUMENTED |
| F-10 | Current text models include MiniMax-M3, MiniMax-M2.7 and MiniMax-M2.7-highspeed; MiniMax-M3.1-Flash-Preview is "available only through M Plan and MiniMax Code for now" | `https://platform.minimax.io/docs/api-reference/api-overview` | DOCUMENTED |
| F-11 | The OpenAI-compatible endpoint documents `tools` (function tools); the deprecated `function_call` is not supported | `https://platform.minimax.io/docs/api-reference/text-openai-api` | DOCUMENTED |
| F-12 | `response_format` (JSON object or JSON schema) is not mentioned | same | NOT VERIFIED (absent from the docs) |
| F-13 | Reasoning: with a split flag, thinking goes to `reasoning_content`; otherwise `content` carries `<think>` content; M2.x thinking cannot be disabled; M3 can skip thinking | same and the Anthropic-compatible page | DOCUMENTED |
| F-14 | Billing: pay-as-you-go uses Open Platform API keys against an account balance; subscription credits use a separate subscription key | `https://platform.minimax.io/docs/guides/pricing-paygo` | DOCUMENTED |
| F-15 | Rate limits by model (for example M3 200 requests per minute) | `https://platform.minimax.io/docs/guides/rate-limits` | DOCUMENTED |
| F-16 | API data retention, training use of API content, storage region, zero-retention terms | the privacy and paid-agreement pages did not render | NOT VERIFIED: an open provider-review item before any real content |

**Consequences for the contract:**

- The output mode is not "OpenAI-compatible therefore JSON schema": `response_format` is undocumented (F-12).
  The candidate is PydanticAI tool output (F-2, F-11), with prompted output as the fallback; native output is
  not used. Either way the strict validation of 5.3 runs, and the probe in section 9 B decides.
- Reasoning content is discarded and never stored (F-13); the model choice must account for thinking that
  cannot be disabled (M2.x) when sizing token budgets.
- Tests set `ALLOW_MODEL_REQUESTS = False` and use `TestModel` and `FunctionModel` (F-3).
- An existing key or a subscription is not authorization or proof of API entitlement (F-14); the provider's
  data handling (F-16) must be reviewed before any real content leaves Catalyst.

## 6. Budgets, failure and recovery

**Limits (PROPOSED, synthetic; every number needs the owner's cost decision).** All are per **snapshot**
(one manifest digest), not per run row, so a re-created run cannot reset them:

| Limit | Value | Rationale |
|---|---|---|
| Model requests per snapshot | at most 4: 2 per attempt (one call plus one output repair) × 2 ledger attempts | every layer counted (below) |
| Function tools | none registered; the output tool of PydanticAI's tool-output mode is the only tool | `tool_calls_limit` is not set to 0, because tool output is itself a tool call (verify in 3B.2) |
| Input tokens per request | 16,000 (`per_request_input_tokens_limit`) | the largest snapshot (40,000 characters) is about 10,000 tokens |
| Output tokens per attempt | 8,000, including any reasoning the model cannot disable (F-13) | the largest valid output is about 2,500 tokens |
| Total tokens per snapshot | 50,000, enforced by Catalyst's own accounting (UsageLimits has no total limit, F-4) | |
| Wall time per request | 60 s (connect 10 s); the whole attempt at most half the worker lease, enforced by a settings check like the mail transport's | no reclaim while a call is in flight |
| Ledger attempts | `max_attempts=2` set explicitly on the row (the ledger default is 3) | crashes and provider errors share this counter |
| Concurrent runs | 1 per application (a partial unique constraint on runs in flight); 2 globally through a counter row taken under its lock | the ledger has no concurrency cap |
| Rounds per application | 3 | bounded clarification |
| Runs per application, all purposes | 6 | |
| Tokens per application, lifetime | 150,000 | |
| Daily global requests and cost | a counter row that **defaults to 0** (fail-closed): no run proceeds until the owner sets a value | no price is verified yet |

Lock order for budgets: application, then the budget or counter row, then the action (through the ledger).

**Retry layers do not multiply:** the SDK's own retries are 0; PydanticAI's output retries are 1; the ledger
retries provider errors with `max_attempts=2`; transport retries are disabled. Catalyst counts every request
itself, because SDK and transport retries are invisible to `request_limit` (F-6).

**Invocation before the call, and the lease.** The pre-call transaction records an invocation (run, attempt,
reserved budget, time) before any request, and `ledger.fence()` runs before each request and each repair. Once
an invocation is recorded, the attempt is **never refunded** (a pause after that point does not return the
attempt, so a pause cannot let a duplicate call through). If the worker dies after the provider may have
processed or billed a call, the lease expires: a reclaim finds the recorded invocation and either continues
under the remaining budget or, when the poison rule exhausts the row, `record()` marks the invocation
`abandoned`, counts its reservation as spent and opens a staff item, so the application never sits in
`assessing` with no action. A result whose lease was lost is discarded with its transaction; the reservation
is the only accounting. At most one **succeeded** run exists per snapshot (a partial unique constraint);
abandoned and failed runs are history. Catalyst does not claim exactly-once inference or zero duplicate
charges.

**Failure is never adverse:** an unavailable model, malformed output after the repair, an exhausted budget, an
unsupported feature or a refused input ends the run with a code, opens a staff item, and leaves the stage
where it was. No failure produces a recommendation or a decision.

## 7. Human authority and the staff experience

**Decision service (J-10).** One transaction with the application locked: a `QualificationDecision` (outcome,
actor, reason code and text, the run it relied on, the snapshot digest, the adopted version, time), the stage
transition, an event and one held follow-on action. Prerequisites checked inside the transaction:

- the authority is decided: a code-fixed setting `CATALYST_QUALIFICATION_AUTHORITY` is `None` until POL-05 is
  recorded, and while `None` everyone is refused, superusers included;
- the actor passes the P2 `can()` rule permanently (authenticated, active, never a superuser, a human `user:`
  actor) and holds `assessments.record_qualification_decision` by explicit grant (assigned to no group by
  migration; the existing correspondence decision-maker group is not extended); `CATALYST_QUALIFICATION_AUTHORITY`
  is fixed in code and refused from the environment by `dispatch_problems`;
- the snapshot digest the decision-maker saw equals the digest recomputed now from the current manifest (any
  re-fetch, newly confirmed answer, changed question set or rubric bump refuses, as P2's
  `confirm_question_outcome(expected_digest=)` does); the stage is compare-and-set from `awaiting_decision`
  (or from `assessing` for a recorded human-only assessment after a failed run, the D-35 amendment; section 17);
  no evidence item is pending;
- the run is this application's latest succeeded, valid run on the current adopted version, and no run is in
  flight; no open identity-affecting staff item exists;
- `admit` is refused while automation is paused; `decline` and `hold` are allowed.

**Database backstop.** Because web and worker share the application role, which may update `stage`, a
deferred constraint trigger (the ADR-14 pattern) refuses any transition into `admitted`, `declined` or
`on_hold` unless a `QualificationDecision` row for that application is inserted in the same transaction. The
decision table is insert-only for the application role, and at most one `admit` or `decline` decision exists
per application (a partial unique constraint). Staff decisions should also require MFA and recent
re-authentication (POL-13, GATE-STAGING).

**P4 hand-off.** `admit` creates a held `issue_nda:<application>` action and nothing else; `decline` creates a
held `send_decline:<application>` action (no applicant message until a POL-06 template is approved). No model
result can create either. *(Superseded for decline by `oc4.11`, 2026-10-24: a decline queues `send_decline`, which
sends the decline notice through the P2 sender unless the decision-maker withheld it; `016` section 10.17.)* NDA-before-User-Agreement (D-15 in `011`) and the separate signing and custody facts stay P4.

**Re-application after decline.** P3 makes `declined` reachable for the first time; the fail-closed repeat rule
of J-02 (planned TEST-P5-06) is pulled into 3B.4.

**The decision screen** (focused view, permission-gated like the P2 screens) shows, for one application:
the adopted version and any newer unverified versions (labelled); each claim beside its observations and
their "cannot prove" statements; unsupported assertions (claims with no observation); the latest run's
findings with highlighted quotes, its limitations, flags and advisory recommendation (never pre-selected);
outstanding questions; the snapshot digest the decision will cite; and only the outcomes the viewer may
record. A missing authority shows "no decision authority is configured (POL-05)".

**Staff never need a shell for:** requesting evidence (re-fetch, or author a question), repairing a routine
assessment exception (rerun, proceed without an unavailable item), approving model-proposed questions, or
releasing work under the activation rule (an owner-run command is the one exception, by design).

## 8. Owner decisions brief (recommendations, not decisions)

These are numbered `P3-D-n` to avoid confusion with the recorded decisions `D-01` to `D-33` in `011`.

| # | Decision | Recommended | Alternative | Rationale | Earliest blocking task |
|---|---|---|---|---|---|
| P3-D-1 | POL-03 claims intake | extend the public form with the optional structured claim fields of section 2 | collect by P2 question only | versioning and adoption already exist | 3B.1 |
| P3-D-2 | POL-03 first sources | two kinds (work-sample page, credential verification page), synthetic fixtures only; none required; `on_unavailable=staff` | also profile pages | proxies such as stars are excluded | 3B.1 |
| P3-D-3 | Real fetching | synthetic only through GATE-P3; real fetching at GATE-PILOT with a network egress allow-list | real public fetch in development | the guards already require it | GATE-PILOT |
| P3-D-4 | POL-04 rubric shape | fixed criteria per rubric version, a rating per criterion, an advisory overall recommendation, no numeric score | criteria plus a score | a score invites thresholds and false precision | 3B.2 |
| P3-D-5 | POL-04 model-proposed questions | never sent until staff approve each one | an approved question bank | fail-closed, matches J-06 and the existing constraints | 3B.3 |
| P3-D-6 | Data-use boundary | synthetic only now; later, the minimized fields of 5.2, alias instead of name, only `trusted` replies, no stored raw outputs | wider content | minimum needed; staff-associated unverified mail is less trustworthy | 3B.2 (contract), live use (separate) |
| P3-D-7 | Budgets | the table of section 6 for synthetic work; no live budget until prices are verified | other numbers | conservative, restart-proof | 3B.2 |
| P3-D-8 | Model and SDK pin, output mode | pin one PydanticAI version and one MiniMax model (a generally available one, not the preview of F-10); tool output as the candidate, prompted as the fallback, both validated; the probe decides | native JSON-schema output | `response_format` is undocumented (F-12); "OpenAI-compatible" does not prove each feature | 3B.2 (pin), probe (B) |
| P3-D-9 | POL-05 authority | one named decision group with the owner as its only member; one person may decide | two people for admit and decline | a one-person team; the schema keeps a nullable second actor | 3B.4 |
| P3-D-10 | POL-05 decision without an assessment | not allowed: a failed assessment is rerun or waits | a recorded waiver | fail-closed | 3B.4 |
| P3-D-11 | POL-05 reconsideration | none in P3; decline is terminal; reopening is POL-12 | reconsideration by another decision-maker | keeps P3 small | 3B.4 |
| P3-D-12 | Redelivery of `start_evidence_collection`, `fetch_evidence` and `run_assessment` | allowed (redeliverable) within the per-snapshot budget. Accepted cost: a redelivered `run_assessment` repeats the disclosure of the same minimized snapshot to the provider and may be billed again; a redelivered fetch repeats a request to a public source | treat as uncertain and reconcile | ADR-15 and D-20 did not generalize redelivery, so this needs an explicit statement | 3B.1 |
| P3-D-13 | POL-10 for P3 records | no raw bytes; derivatives, digests and runs kept; no deletion until POL-10 | encrypted raw custody | public repository; retention undecided | real-data use |
| P3-D-14 | POL-13 for P3 screens | observation and assessment text readable by assessment operators and decision-makers only; a template owner or pause-only role sees none | broader read | least privilege, as in P2 | 3B.1 |
| P3-D-15 | POL-17 applicant notice | the form states what evidence is checked, that a model assists staff, and that a person decides | no notice in synthetic P3 | needed before real applicants | GATE-PILOT |
| P3-D-16 | Re-application after decline | enforce the J-02 rule in 3B.4 | defer to P5 | P3 makes `declined` reachable | 3B.4 |

## 9. Acceptance plan

**Inventory (INSPECTED):** `002` and `004` name TEST-P3-01 to TEST-P3-08. They keep their meaning; new cases
continue from TEST-P3-09. The P3 cases will join `tests/acceptance.py` as a third map in 3C, gated like
GATE-S1 and GATE-P2.

**Three kinds of proof, never mixed:**

- **A. Deterministic application tests (every PR, in CI):** no live model, no public network. PydanticAI test
  models (TestModel, scripted FunctionModel), real requests disabled, synthetic source fixtures behind the
  existing network guard. They prove orchestration, validation, safety and recovery, not assessment quality.
- **B. Synthetic MiniMax compatibility and quality evaluation (later, separately authorized):** a stated
  budget; the pinned model and endpoint; a small owner-reviewed evaluation set of synthetic applications
  with expected findings written by the owner; quality criteria scored by people (the model never grades
  itself alone); a structured-output probe for P3-D-8. The evaluation protocol (set composition, development
  versus held-out cases, a human baseline without the model, a non-model baseline, what is measured and what is
  not claimed) is proposed in `019` section 8. Prerequisites: owner authorization, an API entitlement
  confirmed from the provider (an existing key or subscription is not authorization), provider data-handling
  review (5.6), and the P3-D-6 boundary. Not part of GATE-P3.
- **C. Real-data and pilot acceptance:** only after POL-03, POL-04, POL-05, POL-10, POL-13, POL-17, the
  correction beads `catalyst-v2-9kg.1` to `.3` and GATE-STAGING and GATE-PILOT.

**Case list (A):**

| Case | Proves | Built in |
|---|---|---|
| TEST-P3-01 | typed output stored with provenance; citations resolve | 3B.2 |
| TEST-P3-02 | model failure (error, timeout, malformed after repair, budget) goes to staff; no stage change | 3B.2 |
| TEST-P3-03 | prompt-injection evidence is data; output still schema-bound; flags shown; no side effect | 3B.2 |
| TEST-P3-04 | no decision without authority (POL-05 undecided refuses everyone, superusers included) | 3B.4 |
| TEST-P3-05 | disallowed and private hosts refused; nothing stored | 3B.1 |
| TEST-P3-06 | unavailable source path: bounded retry, then `unavailable`, the policy staff item | 3B.1 |
| TEST-P3-07 | an answer re-enters assessment once; a duplicate trigger is a no-op | 3B.3 |
| TEST-P3-08 | the run records its explicit input version and ignores a newer unadopted one | 3B.2 |
| TEST-P3-09 | activation releases only eligible held rows, versioned, with events | 3B.1 |
| TEST-P3-10 | slot creation per claim and approved source; changed adoption refused | 3B.1 |
| TEST-P3-11 | address classification table (mapped, metadata, CGNAT, loopback, ULA, unspecified, decimal, octal, hex) | 3B.1 |
| TEST-P3-12 | mixed DNS answers refuse; connection to the validated IP; peer mismatch refused before bytes | 3B.1 |
| TEST-P3-13 | redirects: unlisted refused, listed followed, https to http refused, more than 3 refused | 3B.1 |
| TEST-P3-14 | byte cap gives truncation with the digest over bytes read; the deadline stops a slow drip | 3B.1 |
| TEST-P3-15 | content type, userinfo and IP-literal URLs refused; refused is never retried | 3B.1 |
| TEST-P3-16 | no cookies, auth headers or proxy use; logs hold host and code only | 3B.1 |
| TEST-P3-17 | captures are immutable; no raw-bytes column; derivative flag enforced | 3B.1 |
| TEST-P3-18 | an unavailable or private source is recorded as unavailable, never as a negative finding | 3B.1 |
| TEST-P3-19 | exactly one run is enqueued when the last two fetches commit concurrently | 3B.1 |
| TEST-P3-20 | a required unavailable item holds for staff; "proceed without" enqueues the run | 3B.1 |
| TEST-P3-21 | the snapshot manifest and digest; foreign captures refused | 3B.2 |
| TEST-P3-22 | a fabricated alias or a quote not found verbatim fails validation, repairs once, then staff | 3B.2 |
| TEST-P3-23 | `admit` with an unsupported required criterion is flagged, not altered | 3B.2 |
| TEST-P3-24 | delimiter and role-marker injection is neutralized; the rendered request keeps its fencing | 3B.2 |
| TEST-P3-25 | malformed output: one repair, never a third request; nothing partial stored | 3B.2 |
| TEST-P3-26 | budgets per run and per application, including a race for the last unit on separate connections | 3B.2 |
| TEST-P3-27 | provider timeout and server error: at most the stated attempts, then `failed` | 3B.2 |
| TEST-P3-28 | input changed between freeze and call: `refused: input_changed`, no call | 3B.2 |
| TEST-P3-29 | minimization: canary values (name, email, identifiers, notes, headers) never appear in the request | 3B.2 |
| TEST-P3-30 | the live-model guard refuses every environment; no key is read; real requests are disabled in tests | 3B.2 |
| TEST-P3-31 | crash after the call: the recorded invocation is counted; at most one result per snapshot | 3B.2 |
| TEST-P3-32 | a provider reasoning part is never persisted | 3B.2 |
| TEST-P3-33 | a tampered prompt pack is refused; a new version keeps old runs intact | 3B.2 |
| TEST-P3-34 | a model-proposed question is stored proposed and unsendable until approved; URLs and credential requests refused | 3B.3 |
| TEST-P3-35 | question deduplication and the round cap | 3B.3 |
| TEST-P3-36 | staff author a question through a screen and it is sent through P2 | 3B.3 |
| TEST-P3-37 | one reply causes at most one interpretation call (coalescing) | 3B.3 |
| TEST-P3-38 | ineligible replies (staff-associated, truncated, degraded, automatic, empty) make no call | 3B.3 |
| TEST-P3-39 | a reply telling the model to mark questions satisfied changes nothing; staff still confirm | 3B.3 |
| TEST-P3-40 | evidence required but absent is reported | 3B.3 |
| TEST-P3-41 | interpretation racing staff confirmation or a re-derivation ends superseded or text changed | 3B.3 |
| TEST-P3-42 | reassessment uses a new snapshot including confirmed answers; rounds bounded | 3B.3 |
| TEST-P3-43 | a decision needs the latest valid run on the current adopted version; a stale run is refused | 3B.4 |
| TEST-P3-44 | decision atomicity and the held P4 follow-on; no model result creates one | 3B.4 |
| TEST-P3-45 | two concurrent decisions: one wins | 3B.4 |
| TEST-P3-46 | decisions are append-only for every role | 3B.4 |
| TEST-P3-47 | an identity staff item blocks a decision; `admit` refused while paused | 3B.4 |
| TEST-P3-48 | the decision screen shows claims, observations, "cannot prove", assessment, limitations and only permitted outcomes; hostile text escaped | 3B.4 |
| TEST-P3-49 | repeat submission after decline follows the fail-closed J-02 rule | 3B.4 |
| TEST-P3-50 | static checks: `assessments` imports nothing from agreements or provisioning; no transition or code branch reads **any** model-output field (recommendation, proposals, ratings); no assessment code calls `confirm_question_outcome` | 3B.2 |
| TEST-P3-51 | a decision is refused after a re-fetch, a newly confirmed answer or a changed question set since the snapshot shown | 3B.4 |
| TEST-P3-52 | the stage cannot enter a decided state without a decision row in the same transaction (trigger) | 3B.4 |
| TEST-P3-53 | a superuser is refused after POL-05 is recorded; the authority setting takes only the one rule the code implements (amended 2026-10-23 by `9kg.30`: it is read from the environment, accepted only as `explicit_permission` or unset; the selection policy stays refused from the environment) | 3B.4 |
| TEST-P3-54 | `classify(ip)` has no environment branch; fixtures pass only through a `fixture_only` source refused outside `test` | 3B.1 |
| TEST-P3-55 | `interpret_message` is cancelled by a staff decision; a staff decision before the call stops the disclosure | 3B.3 |
| TEST-P3-56 | a crash inside the lease with a recorded invocation yields at most the stated requests per snapshot; no refund after invocation; the poison path opens a staff item | 3B.2 |
| TEST-P3-57 | canary values in free text (claim text, page text, reply text) are scrubbed from the request; `names_applicant` is computed locally | 3B.2 |

## 10. Build slices (3B) and verification (3C)

| Key | Bead | Scope | Depends on |
|---|---|---|---|
| 3B.1 | `catalyst-v2-oc4.2` | versioned claim fields on the adopted submission; `EvidenceSource`, `EvidenceItem`, `EvidenceCapture` with grants and triggers; the fixture-backed fetch adapter with the full SSRF pipeline; the activation rule; the staff observation screen; TEST-P3-05, 06, 09 to 20, 54. **No model call.** | 3A approval; P3-D-1, P3-D-2, P3-D-12, P3-D-14 |
| 3B.2 | `catalyst-v2-oc4.3` | the assessment run: snapshot, prompt pack, output schema and validation, budgets and invocation record, failure routing, stage transitions, the live-model guard; test models only; TEST-P3-01 to 03, 08, 21 to 33, 50, 56, 57 | 3B.1; P3-D-4, P3-D-6, P3-D-7, P3-D-8 |
| 3B.3 | `catalyst-v2-oc4.4` | clarification: model-proposed questions through P2 approval, the staff question-authoring screen, dedup and rounds, the reply interpreter implementing the existing protocol with coalescing and activation, reassessment; TEST-P3-07, 34 to 42, 55 | 3B.2; P3-D-5, P3-D-6 |
| 3B.4 | `catalyst-v2-oc4.5` | the decision service and screen, the authority gate, the database backstop trigger, the held P4 hand-off, the re-application rule; TEST-P3-04, 43 to 49, 51 to 53 | 3B.2; P3-D-9, P3-D-10, P3-D-11, P3-D-16 |
| 3C | `catalyst-v2-oc4.6` | the GATE-P3 run (the P3 acceptance map), one independent QA review, the after-action report | 3B.1 to 3B.4 |
| 3E | `catalyst-v2-oc4.7` | the synthetic MiniMax compatibility and quality evaluation (proof B); not part of GATE-P3 | owner authorization, entitlement, provider review, P3-D-6, P3-D-8 |

**Proposed 3B.1:** exactly the first row: versioned evidence inputs, deterministic fixture-backed collection
and staff-visible observations, without any model call. No concrete dependency requires adjusting it.

**Open at their own gates (not blockers for 3A):** `catalyst-v2-9kg.1` to `.3` (before real use), POL-10
(through `catalyst-v2-211.7`), and the release-path defect `catalyst-v2-oyu`.

## 11. Security and privacy summary

Untrusted inputs: claim text, fetched pages, replies. Controls: the SSRF pipeline (3.3); derivatives only;
fenced, minimized model inputs with no tools or network (5.2); verbatim-quote citations checked by code;
escaped rendering with the `visible` filter; no model path to stage, sending, questions or decisions;
start-up guards for fetch hosts and the live model; budgets that survive restarts; no secrets or bodies in
logs. Residual risks: a hijacked model flags nothing (the controls are structural, and a person reads
everything); a derivative cannot be re-verified; application-level SSRF needs a network egress allow-list in
production (P6); third parties' details in fetched pages are not reliably scrubbed; captures and runs are kept
until POL-10.

**Control enforcement** (ENF: enforced by code, database or infrastructure; CFG: configured; INT: intended until
the named task builds and tests it):

| Control | Today | After |
|---|---|---|
| Held rows are never claimed | ENF (`ledger.claim_next`) | unchanged |
| Fenced result writes; lost lease discards the result | ENF (`ledger.finish`, `fence`) | unchanged |
| Provider credential variables refused | ENF (`config/guards.py`) | unchanged |
| Live-model refusal (request flag, factory guard; the raising transport is deferred, see 14) | INT | ENF in 3B.2 (flag and factory guard) |
| Fetch host allow-list at fetch time; `classify(ip)`; `fixture_only` guard | INT | ENF in 3B.1 |
| No model path to a stage or decision | INT | ENF in 3B.2 (static test) and 3B.4 (database trigger) |
| Decision bound to the viewed snapshot; superusers refused; authority setting pinned | INT | ENF in 3B.4 |
| Budgets per snapshot, no refund after invocation, global counter defaulting to 0 | INT | ENF in 3B.2 |
| Free-text scrubbing and `names_applicant` | INT | ENF in 3B.2 (canary tests) |
| `interpret_message` cancellation and the pre-call staff re-check | INT | ENF in 3B.3 |
| Correctness of the model's assessment | not enforceable by code | human reading; proof B evaluation |

## 12. Review record

Design input: `catalyst-minimax-evaluation` (assessment contracts) and `catalyst-django-data` (data, fetch job,
stages). Official documentation research: section 5.6.

**Independent security and reliability review** (`catalyst-security-privacy`, one reviewer, of 0.1.0). All
findings applied in 0.2.0; the reviewer's re-check of 0.2.0 confirmed every BLOCKER and HIGH resolved and
raised two MEDIUM items, applied in 0.2.1: `on_hold` is entered only as a recorded `hold` decision (so the
trigger covering it is consistent), and a paused in-flight run still records its stage move (no resume hook is
needed).

| Severity | Finding | Resolution |
|---|---|---|
| BLOCKER | a model run changed the stage by proposing questions | a run's completion always moves to `awaiting_decision`; only a staff approval moves to `awaiting_answers`; TEST-P3-50 covers every output field (section 4) |
| BLOCKER | the decision was not bound to the snapshot shown | the decision takes the viewed digest, recomputes it and refuses any difference; compare-and-set stage; no pending item (section 7, TEST-P3-51) |
| HIGH | stage authority rested on convention | `can()` semantics, a pinned authority setting, a deferred trigger requiring a decision row, insert-only decisions, MFA noted (section 7, TEST-P3-52, 53) |
| HIGH | `interpret_message` conflicted with P2 guards and cancellation | a thin handler in `correspondence` behind a pinned seam, the guard amendment stated, cancellation and a pre-call staff check (5.4, TEST-P3-55) |
| HIGH | the fetch guard was start-up only; fixtures conflicted with the address rules | fetch-time checks, versioned sources, `fixture_only` sources, one `classify` with no environment branch, more address classes (3.3, TEST-P3-54) |
| HIGH | retry arithmetic and lost-result recovery were inconsistent with the ledger | per-snapshot budgets, explicit `max_attempts`, no refund after invocation, fencing, the poison path, discard on lost lease, one succeeded run per snapshot, a fail-closed global counter (section 6, TEST-P3-56) |
| HIGH | free text bypassed the data boundary | scrubbing, local `names_applicant`, a reply-interpretation row, residual risk stated (5.2, TEST-P3-57) |
| MEDIUM | activation, redelivery rationale, record compare-and-set, fetch details, token arithmetic, live-model guard, injection handling | 4.1, P3-D-12, 4.2, 3.3, 5.3, 5.5 and section 6 |
| LOW | decision numbering collided with `011` | renamed `P3-D-n` |
| LOW | `staff_associated` replies are admitted by `eligible()` | the adapter adds the trusted-only rule, with a test |

## 13. Implementation notes from 3B.1 (2026-10-14)

Built in `assessments` (models, `fetch.py`, `collection.py`, `services.py`, staff screens at `/staff/p3/`), with
`applications/stages.py` as the one transition primitive outside S1 confirmation. Choices and deviations:

- **Claims.** The P3 fields are stored under `submitted_fields["claims"]` only when at least one is given, so
  S1-shaped submissions are unchanged. A version without claims is never released: it gets a `claims_missing`
  staff item. The request limits rose to 32 fields and 128 KiB for the extended form.
- **Sources.** An owner-run command (`define_evidence_source`) creates a draft version; the owner approves the
  exact version on the screen by its definition digest. Approving a version retires the earlier approved version
  of the same key in the same transaction.
- **Fixtures.** A `fixture_only` source replaces DNS with the one pinned address
  (`CATALYST_EVIDENCE_FIXTURE_ADDRESS`), which `classify` admits only because the source names it; the
  allow-list, fixture address and CA settings are refused outside `test`.
- **Outcomes.** A work page is `found` when it has visible text, `found_but_inconclusive` when empty, and
  `not_found` on 404 or 410. A credential page is `found` only when it shows the claimed identifier, otherwise
  `found_but_inconclusive`. Other 4xx responses refuse the item; 408, 425, 429 and 5xx are transient.
- **Completion.** When nothing is pending, the stage moves `evidence → assessing`. **Deviation:** 3B.1 enqueues
  no `run_assessment` action; 3B.2 adds that enqueue together with its handler, so until then an application
  waits in `assessing`.
- **Staff actions.** Re-fetch is allowed only while the stage is `evidence`; it creates round n+1 and resolves the
  open `evidence_required_unavailable` item. "Proceed without" moves the stage on and resolves the item.
- **Permissions.** New groups: "Assessment operator" (`review_evidence`, `operate_evidence`) and "Evidence source
  owner" (`approve_evidence_source`). No decision permission exists yet (3B.4).
- **Protection.** Captures carry the ADR-14 append-only and no-truncate triggers (the trigger inventory is now
  10); sources and items are protected by column grants.

**3B.1 reviews** (one primary QA review and one scoped security review of the fetch boundary, of `41e2820`; no
blocker). Applied:

- **Deadline.** It is a true total bound: a watchdog shuts the live (TLS) socket down at the deadline, covering
  the handshake, a dripping header block and a dripping body. Reads take one receive at a time, and a cut
  exchange is never parsed.
- **Malformed URLs** are refused (`url_invalid`), never left pending. The query is percent-encoded. Port 0 is
  refused.
- **Charsets.** Only a short allow-list of server-declared charsets is used; any other codec falls back to UTF-8.
- **Path prefixes** match on path-segment boundaries. A URL selects the approved source with the same host and
  port and the longest matching prefix.
- **Host lists.** `fetch()` itself requires every host, source or redirect, to be in the settings allow-list, and
  refuses a fixture source outside `test`. Redirects are off unless the source lists the target host, its own host
  included.
- **Addresses.** The host's own addresses are denied (hairpin), and explicit ranges are added.
- **Private and missing pages.** 401 and 403 make the item `unavailable` (private, not retried). 404 and 410 are a
  `not_found` observation with no stored body, re-fetchable by staff. A required item with nothing usable blocks
  for staff. 3B.2 must map `unavailable`, `refused` and `not_found` to `insufficient_evidence`, never to a negative
  rating.
- **Final failures.** A final handler failure or exhausted attempts marks the item `unavailable: handler_error`,
  opens `evidence_collection_failed` and lets collection complete, so no application is left in `evidence`
  without a staff item. Lease loss at the fence fetches nothing; a result whose lease was lost during the fetch is
  discarded.
- **Re-fetch.** A required claim stays required on re-fetch.
- **Composite keys.** Foreign keys keep an item's version and a capture's item within one application.
- **Tests.** New tests cover lease loss, a handler-defect retry, the final-failure path, the pause refund, a real
  two-connection completion race, 401, 403, 404 and 410, the redirect-host bound and source selection.
- **Staff text.** The next-step text names the P3 stages. `claims_missing`, `adoption_changed` and
  `evidence_collection_failed` are acknowledge-only staff items.

**Interpretations recorded, for the owner to change if wanted:**

- `on_unavailable=staff` opens a staff item only for a **required** source; a non-required unavailable item
  continues and stays visible on the evidence screen.
- `ask_applicant` is not built; staff ask through the P2 screens.

**Deferred:** per-source and per-host rate limits to P6. The response header block is bounded by Python's own
caps (100 headers, 65,536 bytes per line) and by the deadline.

**3B.2 backfill:** applications already waiting in `assessing` when 3B.2 is released get their `run_assessment`
through the same kind of versioned activation command, never automatically.

**Re-check round.** The QA re-check found no blocker or HIGH. The security re-check found the TLS handshake was
still outside the watchdog, and that the stray-end-tag fix made the HTML extractor quadratic on hostile input.
Both are fixed:

- **Handshake.** It runs after the watchdog holds the TLS socket, so it is inside the deadline.
- **HTML extractor.** Tracked nesting is capped at 64, an unmatched end tag is ignored in constant time, and the
  number of parser events is capped (the page is then marked truncated).

Tests cover a server that never completes the handshake and a hostile tag soup.

## 14. Implementation notes from 3B.2 (2026-10-14)

Released by the owner ("release 3B.2"). Built:

- `assessments/pack.py`: prompt pack `assessment_v2`, a system prompt and a synthetic five-criterion rubric,
  pinned by digest. `assessment_v1` stays pinned and loadable.
- `snapshot.py`: the manifest, its digest, and the minimized, scrubbed, fenced request.
- `schema.py`: output schema version 2 and its deterministic checks.
- `agent.py`: PydanticAI, test models only.
- `runs.py`: the run handler, budgets, invocation records and the backfill command `activate_assessment`.

Two reviews ran on the first candidate: the primary independent QA review and a scoped review of the model
boundary. Their findings were applied before merge; the dispositions are below.

- **Dependency.** `pydantic-ai-slim==2.55.0`, with no provider extra, so no live provider client is installed. It
  is hash-locked in `requirements/`. DEMONSTRATED on the pinned Python 3.14.8:
  - `result.usage` is a property;
  - `UsageLimits` has `total_tokens_limit` (F-4 corrected);
  - `retries=1` gives exactly one repair.
- **Live models.** They are refused in three layers:
  1. `ALLOW_MODEL_REQUESTS = False` is set when `assessments/agent.py` is imported, which is the only path to a
     model. **Deviation from 5.5:** it is not set in `ready()`, because importing PydanticAI costs about 2 s in
     every process. `build_model` refuses if anything has set it back to True.
  2. `build_model` has no live branch and accepts only a `TestModel` or `FunctionModel`.
  3. `config.guards.assessment_problems` allows only "none", plus "test" in the `test` environment.

  Model availability is checked before any reservation, so "none" never spends budget. **Not built:** the raising
  HTTP transport described in 5.5 and 11. No provider client exists to carry it; it belongs to live enablement.
- **What the model sees (5.2).**
  - Every untrusted text is normalized before scrubbing: NFKC; control, zero-width, bidi and private-use
    characters stripped.
  - Claims become fenced C blocks on one line, so a claim cannot forge prompt structure.
  - Scrubbing removes email addresses (including obfuscated forms), links, bare domains and phone numbers; ISO
    dates are kept.
  - The applicant's full name, matched on word boundaries with diacritics optional, becomes "the applicant". Its
    "Surname, Given" and initial-plus-surname forms are matched too. A lone part of the name becomes
    "[name removed]".
  - `names_applicant` needs a full-name match in the text actually sent. Truncation happens before scrubbing.
  - An item past the size limits is listed as missing ("not sent (size limit)") rather than sent empty.
  - The request digest masks the per-run nonce.
  - All scrub patterns are bounded, so they run in linear time.
  - A lone name part is scrubbed only as a capitalized word outside a short list of common words and particles.
    A one-token name counts only when capitalized.
  - **Accepted:** placeholders can be longer than the text they replace, so an item can slightly exceed its
    8,000-character cap. The total counts the scrubbed length.
- **Output checks (5.3).**
  - A quote must be verbatim and must carry at least 20 letters or digits once redaction placeholders are removed
    (or the whole item, if shorter).
  - Duplicate citations are refused.
  - Every model-written string is checked for links, contact details, markup and control characters.
  - `limitations` items are capped at 200 characters.
  - `basis_criteria` must be unique.
  - Proposed questions are refused when they ask for credentials, personal data or confidential material
    (including plurals), contain an obfuscated address, or are not in English.
  - New soft flags: `decline_without_a_negative_finding`, `not_supported_while_evidence_is_missing`,
    `rating_rests_on_claims_only`.
  - Marker overlap now uses character offsets in the text that was sent.
- **Owner-decision default (POL-04, rubric): claims are citable.** Applicant statements are C aliases. A rating
  that rests only on claims is capped at `partly_supported` (a hard check) and flagged. This replaces "cite any
  page to satisfy the checker". If the owner decides otherwise, a new pack and schema version will follow.
- **Budgets.** All budgets are synthetic. The daily global budget defaults to 0 (fail-closed), so outside tests no
  run proceeds until the owner sets a value.
  - One attempt is at most 2 requests and the ledger allows 2 attempts, so a snapshot gets at most 4 requests.
  - Each invocation reserves one attempt's tokens: 2 requests of input plus the attempt's output. When usage is
    unknown (failed, invalid or abandoned), the full reservation counts against the application's token budget.
  - An invocation is recorded and committed before any call and is never refunded. A reclaim marks an unfinished
    invocation abandoned, and it still counts.
  - Global concurrency and the daily budget are serialized by one PostgreSQL advisory lock, taken after the
    application lock. A run waiting out a retry backoff returns to queued, so it holds no concurrency slot.
- **Transitions.** Success moves `assessing → awaiting_decision` whatever the output says. Any failure (refused,
  invalid output, capped, failed, abandoned) leaves the stage alone and opens a staff item. A finished run is
  frozen by the `catalyst_run_result_once` trigger.
- **Staff items.** The four codes `assessment_failed`, `assessment_capped`, `assessment_input_changed` and
  `assessment_pack_refused` can be acknowledged by staff. The system also resolves them when staff queue a rerun
  or a later run succeeds.
- **Enqueueing and its deviations.**
  - Runs are queued by evidence completion, "proceed without", a staff rerun and the backfill command.
  - **Deviation:** the action key is `run_assessment:<run id>`, not `<application>:<snapshot>`, so a failed
    snapshot can be rerun. Staff may rerun the same snapshot after a failure. A succeeded snapshot never runs
    twice, and every run spends from the same per-snapshot budget.
  - **Rule for 3B.3:** no model-proposed question is sent without staff approval. The question screen fails closed
    and can block legitimate technical wording ("token", "wallet"); staff can rephrase.
  - **Deviation:** model-proposed questions are stored in the output and shown on the screen. Creating proposed
    `Question` rows and sending them is 3B.3.
- **Open owner decision.** Once a snapshot's request budget is spent, a rerun ends `capped` again, and re-fetching
  is possible only in the `evidence` stage. The open question is whether staff get a budget top-up or a "close
  the assessment" path. Until then, staff can still use the existing application-level actions.
- **Deferred to live enablement (harmless with test models; must be built before any live call):**
  - a fence check before each request and before the repair (today the lease is fenced before the call and at
    the record);
  - a provider-side 60 s timeout, which is set in `MODEL_SETTINGS` but not enforced by a test model;
  - a settings check that an attempt fits within half the lease;
  - a heartbeat for calls longer than the lease;
  - removal of `<think>` text (F-13), which does not apply in tool-output mode.
- **Screen.** The evidence screen shows the latest run as advice: findings, quotes, limitations and flags. The
  recommendation is labelled advisory and is never pre-selected.
- **Scope of proof.** The tests prove orchestration, validation, safety and recovery with a scripted
  `FunctionModel`. They prove nothing about a real model's assessment quality (018 9 B, `catalyst-v2-oc4.7`).

## 15. Selection-quality integration (approved 2026-10-14, D-35)

Authority and lifecycle for the selection standard live in `011` section 11; methods, criteria, the evaluation
protocol and the scorecard live in `019`. This section states only what the P3 software carries and where its
boundaries stay. Nothing here changes D-34, a release, or GATE-P3.

**What the software already records (IMPLEMENTED, 3B.2):** per run, the snapshot digest and manifest, the adopted
version, the prompt pack and its digest, the rubric version, the output schema version, the model identifier, the
library version and the request digest; per capture, the derivation version. These are the "linked versions" of a
selection-policy record (`019` section 6). **Not recorded yet:** a selection-policy identifier (`SP-<role>-<n>`);
until a policy is approved, the rubric version stands in for it, and it is synthetic.

**Proposed additions, each at its existing handoff (none changes a handoff's release):**

| Handoff | Addition | Boundary |
|---|---|---|
| 3B.3 | each model-proposed or staff-authored question names the criterion and the evidence gap it addresses; questions offer an alternative evidence route where one exists (`019` section 5); the 3B.2 question screen applies to staff-authored questions too; the staff screen shows why each question exists | staff approval before sending stays (P3-D-5) |
| 3B.4 | the `QualificationDecision` records per-criterion human rationale and the selection-policy identifier alongside the snapshot digest; the decision screen shows capability and strength of evidence separately | the authority gate stands; P3-D-10 as amended below |
| 3C | GATE-P3 proves software, permissions, provenance and workflow | it is **not** a validation of selection quality and its report must say so |
| 3E | runs the `019` section 8 protocol on synthetic cases | evidence, not proof of predictive validity |

**P3-D-10 as amended (D-35, 2026-10-14; the original rule was: no decision without a valid assessment).** A decision-maker may decide on a **recorded human-only assessment** (the same criteria, written
rationale, the same snapshot) when model advice is unavailable for a case or suspended under `019` section 10. It
is never a shortcut past a working assessment; every use is visible on the scorecard (`019` section 9, area B).
Rationale: suspending model advice must not strand or silently reject applicants.

**Not changed by this section:** the advisory-only rule (D-04), the unconditional stage move on a successful run
(section 14), the rule that no output field influences a transition, and the synthetic-only scope.

## 16. Implementation notes from 3B.3 (2026-10-16)

Released by the owner ("release 3B.3"). Test models only; no live model call, no real data.

**Built:**

- **Questions** (`correspondence/questions.py`, `correspondence/question_screen.py`):
  - one creation path for model-proposed and staff-authored questions;
  - every question passes the one screen (moved from `assessments/schema.py`, so both origins face the same
    rules);
  - every question names its criterion and the evidence gap, may give an alternative evidence route, and may
    require a link or document;
  - questions are deduplicated by normalized text per application (a partial unique constraint while live) and
    stored `proposed`;
  - the new question columns are insert-only for the application role.
- **Proposals** (`assessments/clarification.py`): inside a successful run's record transaction, at most 3 per
  round and none after the last round. No stage change and nothing sent. Approving the first question
  (`approve_question`, a staff act) moves `awaiting_decision → awaiting_answers`.
- **Staff authoring:** on the P3 evidence screen, with the new permission `correspondence.author_question`, granted
  to "Assessment operator". Approval and sending stay with the correspondence operators (D-29).
- **Reassessment** (step 8): `answers_settled`, reached through the code-fixed seam
  `CATALYST_ANSWERS_CONFIRMED_HOOK`, runs after staff confirm an outcome or withdraw a question.
  - When no approved question is open, the case returns to `assessing` and a run is queued (round n+1) on a new
    snapshot. The manifest gains `answers`; the request sends each confirmed reply as an A block: the reply's own
    text, with quoted material and our sent text removed, cleaned, scrubbed, fenced, at most 2,000 characters.
  - A duplicate trigger is a no-op. The same snapshot never runs twice.
  - After the last round (3) the case returns to `awaiting_decision`. If nothing new was confirmed, it also returns
    there, with an event.
- **Prompt pack `assessment_v3`, output schema 3:** A aliases, which count as the applicant's own statements for the
  claims-only cap; `alternative_route` and `requires_evidence` on proposals; a proposal without an evidence gap is
  refused.
- **Reply interpretation (5.4):**
  - `correspondence.processing.InterpretMessage` makes one `interpret_message:<message>:<digest>` call per reply
    derivative (coalesced). It covers `trusted` replies only (P3-D-6) and runs only when
    `CATALYST_REPLY_INTERPRETATION_ACTIVATION` (code-fixed, **0 by default**) is in force; earlier replies are
    released by the owner-run `activate_reply_interpretation`.
  - **Pre-call:** the message must still be undecided and eligible; the derivative digest must match; the
    interpreter's `admit` checks that the model is available and the shared daily budget allows an attempt; a
    `ReplyInterpretation` is recorded before the call.
  - **Record:** superseded if staff decided meanwhile, text changed if re-derived, otherwise `validate_proposals`
    runs, plus the `evidence_required_but_absent` flag.
  - Proposals are advice on the `ReplyInterpretation`, never in `QuestionReplyLink`. Staff decisions cancel queued
    work.
  - The implementation is `assessments.interpret.Interpreter` (P2's protocol, no second interface), with prompt
    pack `interpret_v1`. Each quote must occur exactly once in the stored derivative outside quoted text (one
    repair otherwise).
  - Assessments and interpretations share the daily request budget.
- **Reply screen:** shows the model's reading as advice; no outcome is pre-selected.

**Changes from the two reviews of `cdb2f5c`** (the primary QA review and a scoped review of the interpretation
boundary):

- **Our own words.** `own_text_ranges` finds our sent body, its lines and the question texts (each at least 15
  characters) in a reply, even unquoted, re-wrapped, re-cased or numbered. They are removed before anything leaves (interpretation and A
  blocks). A span or quote inside them is refused, so our own question can never become the applicant's answer.
- **Scrubbing and caps.**
  - Question texts are scrubbed and fenced on the interpretation path (the applicant's name could appear in one).
  - Handles and IPv4 addresses are scrubbed everywhere.
  - A reply over 8,000 characters is refused before any call.
  - Quotes are 1 to 300 characters with at least 20 letters or digits.
  - The free-text note was removed from the interpretation output (a channel from the reply to staff).
  - Confirmed answers are one A block per reply (at most 6 blocks, 6,000 characters in total); an answer past
    the cap is listed under missing evidence as "not sent (size limit)", never dropped silently. A manifest answer
    that no longer resolves ends the run `refused: answer_changed` with a staff item, before any reservation.
  - The `assessment_v3` and `interpret_v1` wording now matches what is actually redacted; both were re-pinned.
- **Lifecycle.**
  - Pre-call re-checks activation (the suspension lever of `019` section 10), the terminal stage and the pause (a
    pause returns the attempt).
  - Earlier unfinished attempts are marked abandoned and stay counted.
  - The record step re-checks eligibility and the pending question set.
  - Withdrawal cancels queued interpretation of a reply that no longer answers any pending question, and its
    event precedes the hook.
  - A per-application daily cap on interpretation requests (10, counting interpretations only) keeps one
    applicant from starving others.
  - A finished `ReplyInterpretation` is frozen by the `catalyst_interpretation_result_once` trigger.
  - The reply screen shows only advice computed on the current derivative.
- **Rounds.** No proposals in the last round. A rerun keeps the round of the latest run. Proposals are stored only
  after the stage move succeeds. The authoring stage is checked under the application lock.
- **Evidence flag.** It counts only links in the applicant's own text, not quoted text or our message.
- **Owner-decision default: the alternative route reaches the applicant.** The screened route is appended to the
  sent question text ("If you cannot share that, you could instead: ..."). This uses the approved template's
  existing `question_text` variable, so no template change is needed (`019` section 5, D-35). Replace it with a
  template variable if the owner prefers.

**Deviations and limits:**

- **Comparable core questions** (`019` section 5) are not built: they need the approved criteria of `SP-L2-1`
  (bead "Complete the supervised-delivery role profile").
- **Staff "reassess"** (step 8) is not built as its own button. Reassessment starts when staff confirm answers or
  withdraw the last open question; a rerun is possible only in `assessing`.
- **A question approved outside the clarification stages** (for example a P2-style question in `assessing`) has
  no reassessment trigger when answered.
- **The manifest has no open-question set and no answer offsets** (5.1). 3B.4's TEST-P3-51 needs them; they belong
  to the 3B.4 brief.
- **Caps on interpretation.** It does not count toward "runs per application, all purposes" or the global
  concurrency cap (section 6). It is bounded by its own per-message attempts (2), the per-application daily cap
  and the shared daily budget.
- **Interpretation is not retried** after a provider error: the reply goes to staff without a proposal (the
  attempt is still counted).
- **Quotes containing redaction placeholders** cannot be located in the stored reply, so such quotes are refused.
- **Answer text.** Confirmed answers send the reply's own text (quoted material and our words removed), not
  staff-selected spans: staff confirmation records no spans.
- **Proposals for answered questions** are not dropped at record (4.2): dedup by text covers re-asking the same
  question; a reworded one is caught only by staff review.
- **Daily boundary.** The daily budget uses the database's UTC date (`TIME_ZONE` is UTC).

**Tests:** `tests/test_clarification.py` covers TEST-P3-07, 34 to 42 and 55, the activation command, the seams, the
shared budget and both screens. The 3B.2 tests move to schema 3.

## 17. Implementation notes from 3B.4 (2026-10-17)

Released by the owner ("release 3B.4"). No live model call, no real data, no P4 action runs.

**Built:**

- **Decision record.** `QualificationDecision`, insert-only for the application role and append-only for every role
  (the ADR-14 triggers). It records:
  - the outcome, actor and reason code and text;
  - the adopted version;
  - the run relied on, or none for a recorded human-only assessment;
  - the snapshot digest and the **decision digest** (what the decision-maker saw: the snapshot, the clarification
    question set and the run);
  - the **selection-policy reference** (D-35; until a policy is activated, `none-approved:<pack>:rubric-<n>`);
  - the **per-criterion rationale**, with capability and strength of evidence kept separate (`019` section 5).

  At most one admit or decline per application. The permission `assessments.record_qualification_decision` is
  assigned to no group.
- **The service** (`assessments/decisions.py`).
  - `CATALYST_QUALIFICATION_AUTHORITY` is fixed in code and is **None until POL-05 is recorded**, so everyone is
    refused, superusers included. The guard allows only None or `explicit_permission`, and never from the
    environment.
  - One locked transaction checks: the digest shown equals the one recomputed; no run is in flight; no evidence
    item is pending; a valid succeeded run exists on the current snapshot; the stage is compare-and-set; no
    identity item is open; admit is refused while paused; every criterion has a rationale.
  - It then records the decision, moves the stage, writes an event and creates the held follow-on (`issue_nda` or
    `send_decline`; nothing for hold).
- **Human-only assessment (the D-35 amendment of P3-D-10).** It is allowed only when there is no succeeded run for
  the current snapshot and no run is in flight, **and** one of these holds:
  - model advice is suspended (the model setting "none");
  - the latest run for this snapshot failed;
  - staff got the case back without a reassessment (`awaiting_decision`);
  - no run can be queued any more (`assessing` at the run cap).

  It is allowed from `awaiting_decision` or `assessing`, with a recorded reason, and is never a shortcut past a
  working assessment (as amended after review; see below).
- **Open questions.** A decision is refused while an approved question is still open or awaiting processing:
  staff withdraw it first, so its reminders stop. Unsent proposed questions are withdrawn by the decision, with
  an event.
- **Database backstop** (TEST-P3-52). A deferred constraint trigger on applications refuses, for every role, any
  move into `admitted`, `declined` or `on_hold` without a matching decision inserted in the same transaction. The
  row's `created_txid` (a database default of the top-level transaction id) is compared, because `xmin` differs
  inside a savepoint and Django's `Now()` is the statement time.
- **Decision screen** (`/staff/p3/applications/<ref>/decision/`). It shows:
  - claims beside observations and what they cannot prove;
  - the advisory run, with its limitations and flags;
  - the clarification questions;
  - the snapshot the decision will cite;
  - the selection-policy reference;
  - per-criterion capability and evidence-strength inputs, never pre-selected;
  - only the outcomes the viewer may record;
  - "no decision authority is configured (POL-05)" while the authority is None.

  The evidence page and this page share their claims and run partials.
- **Re-application after decline** (J-02, P3-D-16). A repeat submission after a decline is recorded as a version
  on the declined application with the staff item `repeat_after_decline` (resolved by acknowledgement under the
  identity permission). No new application is created. Withdrawn and closed stay with P5.

**Changes from the two reviews of `c4fa72f`** (the primary QA review and a scoped security review):

- **Human-only reachability.** It is now also allowed when staff get the case back without a reassessment (the
  round cap, or a reassessment that could not be queued) and no run is in flight. Previously a confirmed answer
  in the last round could strand the applicant once a live model is configured. The screen labels a run that is
  not for the current snapshot.
- **Authority.** `can_decide` counts only a permission granted to the user directly (a group grant never counts)
  and requires a staff user.
- **The transaction marker.** `catalyst_decision_txid` (BEFORE INSERT) overwrites `created_txid` and `created_at`,
  so a supplied value never counts. A column-level grant cannot do this, because Django names `db_default`
  columns in its INSERT. The backstop now has negative tests for each of these cases, run through committed
  connections:
  - a decision from an earlier transaction;
  - the wrong outcome;
  - another application's decision;
  - a decided INSERT;
  - a rolled-back savepoint;
  - the positive savepoint case.
- **Questions end with the decision.** Unsent proposed questions are withdrawn ("decided", with an event naming
  them), `approve_question` refuses an admitted or held application, and a sent question still open refuses the
  decision (`open_question_pending`).
- **Migration 0008 was edited in place** during review. No database ran the earlier version (synthetic, no
  deployment).
- **Rationale.** With strength of evidence `none`, capability must be `unknown` (`019` section 5: absence of
  evidence is never lack of ability). Over-length notes are refused, not cut. A non-dict entry is refused.
- **Screen and other fixes.**
  - A confidential description is shown whenever it exists (it is sent whether or not the box was ticked).
  - Admit is not offered while paused, and no form is shown at a non-decidable stage.
  - `repeat_after_decline` has a staff label.
  - The selection-policy setting is validated (`SP-<role>-<n>` or empty).
  - Integrity errors are mapped by constraint name.

**Owner decisions surfaced by the reviews (fail-closed defaults kept):**

- **Repeat submissions can stall a decision.** Anyone who knows a verified applicant's address can open a
  `repeat_after_verification` or `repeat_after_decline` item, and an open identity item blocks the decision until
  staff acknowledge it. Kept fail-closed. POL-01 and POL-12 decide whether such items should block, and P6 adds
  the intake rate limit; repeat items are not coalesced yet.
- **Decision text cannot be erased.** The retention role has SELECT only on decisions (append-only, protected
  history), so a deletion request cannot be met for the rationale or reason text. This is POL-10. Staff guidance
  is "facts about the evidence only".
- **A tampered or unknown prompt pack** leaves no snapshot and therefore no decision, even human-only. This is
  fail-closed and accepted until the owner says otherwise.
- **`reason_code`** is a free slug, not a controlled list (POL-05).

**Deviations and limits:**

- **The backstop guards code paths, not a compromised application role.** That role may insert a decision row
  itself; the trigger then only requires one.
- **Entry only.** No database guard covers leaving a decided stage; the terminal rule is code-only (P4 and P5).
- **No reconsideration** (P3-D-11). A decline is terminal, and the held follow-ons do nothing until P4 and POL-06.
- **Hold.** `on_hold` has no exit in P3; what follows a hold is POL-05 or POL-12.
- **The decision digest covers the question set, not the answer offsets.** A newly confirmed answer changes the
  snapshot (and so the run's validity), which covers TEST-P3-51 without storing offsets.
- **Second person.** The optional second actor (P3-D-9) has a column but no screen.

**Tests:** `tests/test_decision.py` covers TEST-P3-04, 43 to 49 and 51 to 53, the human-only path and the
rationale. TEST-P3-50's static check now includes `decisions.py`.

## 18. Verification and closeout (3C, 2026-10-17)

Released by the owner ("release 3C"). Verification only; no feature was added.

- **The acceptance map.** `tests/acceptance.py` maps all 57 cases (`P3_CASES`, 120 test references, from the case
  numbers in test names plus the review tests that prove the same case). The D-35 rules form `P3_SUPPORTING`
  (question gap and route, decision rationale and policy reference, human-only assessment).
- **The gate.** `tests/conftest.py` reports and gates P3 like GATE-S1 and GATE-P2: a full run fails unless every case
  is PASS. `tests/test_acceptance.py` checks that the map names exactly the cases of section 9 and that every mapped
  test exists.
- **What it proves and what it does not.** GATE-P3 proves software, permissions, provenance and workflow on
  synthetic data with test models. It is not a validation of selection quality (`011` section 11; `019` sections 7
  to 9).
- **After-action report:** `000-docs/000-aars/020-AA-AACR-p3-evidence-assessment.md`, with the proposed sign-off
  statement.

**Owner decisions carried out of P3** (consolidated from sections 14, 16 and 17; each keeps a fail-closed default):

1. POL-05: who may decide. Until recorded, nobody can (the authority setting is None).
2. What clears a capped assessment snapshot (bead `catalyst-v2-oc4.8`).
3. Whether repeat form submissions may block a decision through an identity item (POL-01 and POL-12; rate limit in
   P6).
4. POL-10: decision text cannot be erased today.
5. Whether a tampered prompt pack should still allow a human-only decision.
6. Whether `reason_code` becomes a controlled list.
7. How the alternative route reaches the applicant (today: appended to the question text).
8. When to turn on reply interpretation (activation setting 0) and authorize live use (after `catalyst-v2-oc4.9`).
9. The daily request budget, which is 0 until the owner sets it: no run happens outside tests until then.
10. Claims are citable by default (C aliases, capped at `partly_supported`; section 14); a different POL-04 choice
    means a new prompt pack.
11. `on_unavailable=staff` applies to required sources only, and `ask_applicant` is not built (section 13).
12. Confirmed answers send the reply's own text, not staff-selected spans (section 16): a departure from 5.2's
    "confirmed answer spans only" until staff confirmation records spans.
13. `on_hold` has no exit in P3 (section 17): what follows a hold is POL-05 or POL-12.
14. The open inputs of `019` section 13 (domain expert, operational delegate, private evaluation location,
    scorecard minimums).

## 19. The staff path back from a hold (9kg.50, 2026-10-23)

Section 17 recorded that `on_hold` had no exit in P3. The internal launch (`029` section 5.2) needs one that is a
decision, not a closure, so the decision service now accepts `on_hold` as a source stage:

- `record_decision` moves a held application to `admitted` or `declined` under exactly the rules of any decision:
  the configured authority and the direct grant (`can_decide`), the digest shown, no run in flight, no pending
  evidence, no open identity item, admit refused while paused, a rationale per criterion. A model-assisted decision
  needs a succeeded run on the current snapshot; otherwise the recorded human-only assessment applies, which is
  allowed from `on_hold` as it is from `awaiting_decision`. A second hold is refused (`already_on_hold`): the way
  off a hold is a decision.
- The transition is the ordinary compare-and-set with its event (`qualification_admit` or `qualification_decline`,
  `from: on_hold`, the staff actor), the same-transaction database backstop applies, and the held follow-on
  (`issue_nda` or `send_decline`) is created as for any admit or decline. The hold decision stays as history (one
  admit or decline per application; holds are not limited).
- The decision screen offers the form on a held case with `hold` removed from the outcomes; a viewer without the
  permission sees no form and a POST is refused (403), as before.

Tests: `tests/test_hold_and_resend.py` (the service, the form, the refused user, the human-only hold). The default
built on: the route is the existing authority-gated decision form, never a free close action (`029` section 13.3;
`oc4.12` records the same for a capped snapshot).

## 20. The human-only path completed for the internal launch (oc4.12, 2026-10-23)

Built on the recorded default that model advice is suspended for the whole internal launch (`011` section 4.1,
suspension record of 2026-10-23; `019` decision 4 and section 10) and on `oc4.8`'s recommended default (a capped or
refused snapshot leaves `assessing` through the authority-gated human-only decision form, never a free
close-assessment action; the owner's `oc4.8` decision can change the value without redesign).

**What a decision now records** (`QualificationDecision`, migration 0010; `decisions.decision_state`):

- the **decision digest** binds, and `decision_inputs` keeps: the policy reference (the synthetic rubric's
  `none-approved:<pack>:rubric-<n>` stated openly until a policy is bound), the pack name and digest and the rubric
  version, the snapshot digest with an **evidence manifest** (one state per claim: `present`, `size_limited`,
  `unavailable`, `refused`, `pending`, `claims_only`), every run with its status, error code and requests spent, and
  the question set. A change to any of them between the screen and the submit is refused (`changed_since_shown`):
  `oc4.10` item 2 fixed.
- the **pack, its digest and the rubric version** in their own columns, whatever the policy reference says:
  `oc4.10` item 3 fixed.
- a **structured human-only reason** (`human_only_code`: `advice_suspended`, `run_capped`, `run_failed`,
  `run_cap_reached`, `returned_without_reassessment`), derived from the state and shown on the screen before the
  submit; a database constraint refuses a human-only row without one, so a free-text reason never stands alone.
  Under the suspension the code is `advice_suspended` and the record cites `CATALYST_MODEL_ADVICE_SUSPENSION_REF`.

**A policy labels only its own decisions** (`oc4.10` item 1 fixed): `CATALYST_SELECTION_POLICY_PACKS` binds a
policy to the pack it was approved with (written by the activation, code-fixed like the policy). The start-up guard
refuses a policy that is unbound, bound to an unusable pack, or bound to a pack whose rubric is synthetic (POL-04);
the decision service refuses a decision whose pack is not the bound one (`policy_not_bound_to_pack`).

**Refused by suspension.** A run refused because the model is `none` opens `assessment_suspended` (acknowledge-only,
settled by a later success or rerun like the other assessment items), not `assessment_failed`; the dossier and the
run partial say "refused by suspension: not an assessment failure" (TEST-P3-02 amended accordingly). Model output,
where it exists, is labelled nonbinding advice.

**Counted.** `manage.py selection_scorecard` emits every `019` section 9 row explicitly: a measurable row as a value
(the decision-time rows with every human-only code and an explicit zero, overrides against the advisory
recommendation by reason code, open and resolved assessment items with the runs that ended capped or failed, days
from adoption to decision, insufficient-evidence ratings per succeeded run, outcomes by policy, pack and rubric),
and a row this code cannot compute as `null` with its reason (`shell_or_database_edits`: its source is an incident
log that does not exist in the database; reviewer annotations, abandonment and delivery records likewise). Counts
only, for the weekly summary (`f1u.7`).

**The cohort's policy identifier.** While no policy is active and model advice is off, every decision records the
literal `none: internal cohort, D-M` (`CATALYST_NO_POLICY_LABEL`; council record `030` Q8), not the synthetic
rubric's reference, which applies again the moment advice is on; the pack, its digest and the rubric version stay in
their own columns either way.

**One source for the human-only rule.** `decisions.human_only_code` computes the structured reason once;
`human_only_allowed` is "a code applies". `CATALYST_CAPPED_EXIT` (`human_only`, the recommended default from
`oc4.8`; or `none`) decides whether a capped snapshot is an exit, so the owner's `oc4.8` decision changes one setting.
A paused application under the suspension is refused at once (the model check runs before the pause check), so a
requeued run never blocks the human-only path. A human-only decision resolves the case's `assessment_suspended`
or `assessment_capped` item (`human_only_decision`), so it does not page forever.

**The form and comparability at launch.** The decision form shows each criterion's definition and the `019`
section 5 rules (missing or private evidence is never evidence of low ability; equivalent evidence routes are
offered and recorded). Comparability at the internal launch means the same criteria and the same form for everyone;
a fixed core question set per criterion is a later owner decision.

**No v2 decline for an existing member** (`030` Q8, `9kg.52`). While the address has a live first-generation
agreement-on-file record (`applications.MemberAgreementOnFile`, recorded by the owner, `029` section 17.2), the
decision service refuses a decline under the application lock (`decline_refused_member_on_file`) and the decision
form does not offer one, with a line saying why; hold, or withdraw through the withdrawal path, instead. Admit and
hold are unchanged. Like the other human-only rules, it binds the form and the service alike.

**Open owner decisions (policy, not implemented):** (1) whether `not_shown` should need observed contrary evidence
rather than absence; (2) whether a decline should need at least one `not_shown` criterion at moderate or strong
evidence strength; (3) a fixed core question set per criterion; (4) `oc4.8`'s value (`CATALYST_CAPPED_EXIT`).

**Not built, by design:** no close-assessment action, no budget top-up, no change to the applicant-facing pages, no
model call (a tripwire in `tests/test_human_only.py` fails any test on this path that builds or calls a model, and a
static check keeps `decisions.py` and `staff_views.py` free of the model layer). Tests: `tests/test_human_only.py`;
the hold exit of section 19 is the same form.
