# P3 Evidence, Assessment and Qualification Specification (handoff 3A)

| Field | Value |
|---|---|
| Document | `018-AT-DSGN-p3-evidence-assessment-specification` |
| Version | 0.2.1 (draft for owner review; the independent security and reliability review and its re-check applied, section 12) |
| Status | **APPROVED by the owner 2026-10-14 (version 0.2.1; D-34 in `011` section 4), with the recommended defaults `P3-D-1` to `P3-D-16` for synthetic P3.** 3B.1 is released; 3B.2 to 3C each need their own release. Approval authorizes no live model call, real fetching, real applicant data, real mail, versioned release or deployment. |
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
| 3 | Deterministic checks | the record transaction of the last item | all items of the adopted version | one transaction: required-item policy evaluated; stage `evidence → assessing` | `run_assessment` (step 4), or a staff item `evidence_required_unavailable` | proceed; hold for staff | the application lock serializes the last two fetches; the unique key makes one run | proceed without, or re-fetch | TEST-P3-19, 20 |
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
| the application leaves `assessing` meanwhile (closed or withdrawn; `on_hold` is only ever a recorded `hold` decision from `awaiting_decision`) | the record transaction compare-and-sets the expected stage `assessing`; on a mismatch it records the run and transitions nothing |
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
| Live model | MiniMax through an OpenAI-compatible client with an explicit base URL. Refused in every environment until authorized, by three layers: `models.ALLOW_MODEL_REQUESTS = False` set in the app's `ready()` for every environment; a provider factory that has no live branch reachable without an authorization setting refused by a new start-up guard; and an HTTP transport in tests that raises on any request. Agent instrumentation that exports prompts is forbidden | see 5.6 |
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
| F-4 | `UsageLimits` has `request_limit`, `tool_calls_limit`, `input_tokens_limit`, `output_tokens_limit`, `per_request_input_tokens_limit` and `cost_limit`; exceeding one raises `UsageLimitExceeded`. A total-tokens limit was not found | `https://pydantic.dev/docs/ai/core-concepts/agent/` | DOCUMENTED; total-tokens limit NOT VERIFIED |
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
  `confirm_question_outcome(expected_digest=)` does); the stage is compare-and-set from `awaiting_decision`;
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
result can create either. NDA-before-User-Agreement (D-15 in `011`) and the separate signing and custody facts stay P4.

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
  itself alone); a structured-output probe for P3-D-8. Prerequisites: owner authorization, an API entitlement
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
| TEST-P3-53 | a superuser is refused after POL-05 is recorded; the authority setting is refused from the environment | 3B.4 |
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
| Live-model refusal (request flag, factory guard, raising transport) | INT | ENF in 3B.2 |
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
