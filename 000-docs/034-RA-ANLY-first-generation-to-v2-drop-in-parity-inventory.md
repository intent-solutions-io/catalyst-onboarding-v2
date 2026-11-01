# First-generation to v2 drop-in parity inventory

| Field | Value |
|---|---|
| Document | 034-RA-ANLY-first-generation-to-v2-drop-in-parity-inventory |
| Date | 2026-10-30 (read); filed 2026-10-31 |
| Purpose | Row by row, what the live first-generation onboarding service does, what v2 does, whether an applicant or the owner would notice after a silent swap, and the effort to close each gap. Feeds the drop-in replacement epic in Beads. |
| Owner direction | 2026-10-30: v2 must do what the live service does, or better, so the swap is invisible to applicants. |
| Status | Analysis, read-only; nothing was run against any host. Decision rows are recommendations to the owner (section 4 and the decision bundle bead). |
| Boundary | First-generation behaviour is described, never excerpted; citations name files and lines in the two repositories so a reader with access can verify. No applicant data, credentials or host paths. |

Prepared 2026-10-30, read-only. Sources: v1 = the live commit `d519f5c` (PR #180 of the first-generation
repository), read from an export of that commit (cited as `v1:<path>:<line>`, paths relative to `src/catalyst/`
unless they start with `000-docs/`, `deploy/`, `ops/` or `CLAUDE.md`); v2 = this repository at `bd4fe9d`
(cited as `v2:<path>:<line>`). Learn-host routing:
`intent-os/ops/ingress/learn-catalyst/Caddyfile.fragment` (cited as `ingress:`).

**Limits of this read.** Production flag values live in the VPS's SOPS env file and
the host flag-approvals file, which were not read (read-only, no host access). v1's
flag state below is what v1's `CLAUDE.md:69-94` and `000-docs/008` record; v1's `CLAUDE.md` lags the code in
places (it still says decision 16 is "not yet deployed", but `CHANGELOG.md:58` records field set `ua_v24` live
at `9ab3b8f` on 2026-10-18, so the decision-16 flow is the live flow). Anything not visible in code or docs is
marked "not determinable" or "not found".

---

## 1. v1 end to end, as it runs today

### 1.0 Switches that are ON in production (documented, not host-verified)

`v1:CLAUDE.md:71-84`: `SMTP_HOST`, `IMAP_HOST`, `TWENTY_PROJECTION_ENABLED`, `DOCUMENSO_SIGNING_ENABLED`,
`MAILBOX_PROVISIONING_ENABLED`, `WELCOME_EMAIL_ENABLED`, `RESEARCH_GITHUB_ENABLED` (2026-10-06),
`SIGNING_REMINDER_ENABLED` (2026-10-12), `AUTO_RELEASE_ENABLED`, `REVIEW_WORKER_ENABLED` (2026-10-04),
`REVIEW_AUTOMATION_ENABLED` (2026-10-08). OFF: `SETUP_CLICKWRAP_ENABLED` (retired), `RESEARCH_WEB_SEARCH_ENABLED`,
`INTAKE_EMAIL_VERIFICATION_ENABLED`, `CREDENTIAL_VERIFY_ENABLED`, `DEGREE_VERIFY_ENABLED` (`v1:CLAUDE.md:83-84,241-242`).
Settings (not outward flags): `OWNER_NOTICE_MODE=digest` (`v1:CLAUDE.md:164`); `REVIEW_COUNCIL` default on
(`v1:review/policy.py:37-44`); `REVIEW_COUNCIL_ON_INCOMPLETE` and `ADDRESS_POSTAL_CODE_OPTIONAL` default off,
production value not determinable (`v1:000-docs/008:1088-1098`). **Owner mail is currently switched off**:
both kill files `owner-notices.disabled` and `owner-review-notices.disabled` were set on the VPS on 2026-10-24
(`v1:000-docs/008-AT-ADEC-cto-decision-log.md:1102-1105`, decision 30). So today the owner receives
no dossier, no digest, no review/reply/mailbox-issued notice; the approver-link email is not gated by those
files (`v1:signing/handlers.py:176-181`, router classes it immediate).

### 1.1 Public pages on `learn.intentsolutions.io` (Caddy → `127.0.0.1:8095`)

| URL | What the applicant sees / what happens | Cite |
|---|---|---|
| `/user/logon` | NOW-LMS/Caddy 302 → `/request-access` (not v1 code) | `ingress: learn-catalyst/README.md:13,72` |
| `GET /request-access` | Branded form `request-access.v4`: full name, personal email, country of residence (ISO + 3 Ukraine regions), phone (country code + number), work links (1 per line, max 5, http(s)), "What are you building" (30-2000 chars), interest track (`cert_only` / `cert_and_work` / `undecided`, question "What are you looking for?"), optional unticked marketing checkbox, required 18+ box, education (3 rows: level, field, institution, year, ref) or "No post-secondary degree", certifications (4 rows: name, issuer, credential ID/link) or "No certifications", required verification consent. Strict CSP, no JS. | `v1:intake/views.py:96-136`, `v1:intake/validation.py:39-59`, `v1:setup/interest.py:28-37`, `v1:talent/credentials.py:33-65` |
| `POST /request-access` | Order: CSRF → per-IP rate limit (429 page) → signed form timestamp (too fast / too old) → honeypot (silently shows "received") → server validation (422 with field errors) → `submit_request` → 303 to received | `v1:intake/views.py:139-163` |
| `GET /request-access/received` | One-time "received" page, identical for every outcome (no reference shown); reload → back to form | `v1:intake/views.py:166-171` |
| `/request/confirm/<token>` | 404: `INTAKE_EMAIL_VERIFICATION_ENABLED` is off, and Caddy does not route it | `v1:intake/views.py:178-197`, `ingress: Caddyfile.fragment:9` |
| `/signing/return` | Documenso `redirectUrl` landing page: static "thanks" page, reads nothing, changes nothing | `v1:signing/views.py:17-29` |
| `/setup/<token>`, `/renew`, `/agreement.pdf` | Still routed, but nothing in the live path issues a setup link since decision 16 (details are typed on the User Agreement) | `v1:setup/views.py:293,380,400`, `v1:CLAUDE.md:56-66` |
| `/start` | Static study-links page served by Caddy (not v1); linked from the welcome | `ingress: learn-start/Caddyfile.fragment:6` |

### 1.2 Step by step, applicant view and what the system does

1. **Submit.** One transaction creates `onboarding_case` (state `requested`), `intake_request`, a reference
   `CAT-XXXX-XXXX`, the receipt job, and (SMTP on) the owner dossier job (`v1:intake/service.py:318-370`,
   `v1:intake/models.py:135`). Repeat from the same address: while a case is open, or within
   `INTAKE_DUPLICATE_WINDOW_HOURS` (72), it is stored as an `intake_revision`, no second receipt
   (`v1:intake/service.py:9-21`). Global caps 30/hour, 100/day defer (never drop) the receipt and review
   (`v1:intake/service.py:25-29`). Each listed credential queues a `talent.verify` job (runs only if
   `CREDENTIAL_VERIFY_ENABLED`; off) (`v1:intake/service.py:315`).
2. **Receipt email** (immediately, worker pass ≤30 s). From `SERVICE_MAIL_DISPLAY_NAME <agreements@…>`
   ("Intent Solutions Agreements", `v1:CLAUDE.md:151-152`), Reply-To the same, subject
   **`We received your request [CAT-…]`**, Auto-Submitted header; body: greeting by plain first name or
   "Hello", reference, date, interest answer, "we review every request and reply by email from this
   address… withdraw at any time by replying", partner badge (`v1:intake/receipt.py:89-133`,
   `v1:templates/email/intake_receipt.txt`).
3. **Owner dossier** (immediate in digest mode) to `OWNER_INTAKE_NOTICE_TO` (default `intake@`), subject
   `New applicant: <Full Name>, <country>` (+ " (sent again)") (`v1:intake/owner_notice.py:71-94,324`).
   **Currently suppressed by the kill file (decision 30).**
4. **Background research (Tier 1, ON).** If a work link is a `github.com` user/repo URL, three public GitHub API
   reads (profile, repos, event count) become `review_evidence` kind `github_api` (`v1:research/github.py:1-25`).
   The reviewer can also fetch the applicant's own submitted links through an SSRF-guarded fetcher
   (`v1:research/fetch.py:1-21`, tool `fetch_public_page` `v1:agent/stages.py:411`). Web search (Brave) off.
5. **AI review (MiniMax, ON, acting).** Model `MINIMAX_MODEL`, default `MiniMax-M3`, via Pydantic AI over
   MiniMax's OpenAI-compatible endpoint (`v1:agent/stages.py:63,258-274`), prompt set `cpn-intake-v2`
   (`v1:agent/prompts/cpn-intake-v2/`). Jobs: `review.research` → `review.decide` → (`review.write` →
   `review.check`) (`v1:review/controller.py:4-6`). Input is an allowlist: what they are building, links,
   interest track, credentials as words, research evidence, the question ledger; never name, email or phone,
   contact details scrubbed from free text (`v1:review/inputs.py:1-24`). Policy `cpn-intake-policy.v1`: three
   self-report criteria `work_example`, `personal_contribution`, `practice_goal` (`v1:review/policy.py` lines
   62-80 of the file, the `INTAKE_POLICY` tuple). Decide outputs one of `research_more`, `ask_questions`,
   `wait`, `advance_to_nda`, `human_review`, `stop_contact` (`v1:agent/contracts.py:37-43`).
   - `advance_to_nda` with every criterion evidenced → case `reviewing → nda_pending` and the NDA job, **no human**
     (decision 18, `v1:CLAUDE.md:79-83`).
   - `ask_questions` → model drafts (write), a second model pass checks (check), then the clarification email
     (step 6).
   - `human_review` on judgment → **second-opinion panel**: two more decide runs with `advocate` and `skeptic`
     personas, code takes 2 of 3; only a 3-way split or a reserved category (sanctions, stop contact,
     identity/thread conflict, legal change, applicant asks for a person) holds for the owner
     (`v1:CHANGELOG.md:122-160`, `v1:review/council.py`).
   - Sanctioned residence/phone → never sent to the model, `human_review`/`sanctions_concern`, applicant never
     told (`v1:review/controller.py:26-30`).
   - Self-caused holds (`invalid_output`, `provider_unavailable`) auto-retry after 60 min, twice
     (`v1:review/policy.py:30-35`). Caps: 400 model runs/day, 50 clarification sends/day.
   - **Decline is never automatic**: `decline-applicant` is an owner command (`v1:operator_cli.py:222`,
     `v1:000-docs/008:1108-1109`).
6. **Clarification email** (model-drafted, model-checked, code-validated), subject
   **`A question about your Solutions Catalyst request [CAT-…]`**, body "Hello <first name>, <questions>…
   Please reply… You can withdraw at any time by replying." (`v1:review/correspondence.py:153`,
   `v1:templates/email/review_clarification.txt`). Max 2 rounds × 3 questions (`v1:review/policy.py:10-12`).
7. **Replies.** IMAP poll of the service mailbox every 60 s (`MAILBOX_POLL_SECONDS`, `v1:intake/replies.py:84,373`),
   headers only, UIDVALIDITY+UID cursor; classes `own_message`, `bounce`, `auto_reply`, `suspected_auto`,
   `matched` (In-Reply-To/References + From = applicant), `sender_mismatch`, `ambiguous`, `unmatched`
   (`v1:intake/replies.py:1-48`). A matched reply resumes the review; reply text kept in `applicant_message`
   (`v1:CHANGELOG.md:84-86`). Human mail gets an owner reply notice `"<Name> replied"` /
   `"<Name> wrote to the agreements mailbox"` (`v1:intake/reply_notice.py:404-407`) — suppressed today.
8. **Clarification reminder**: one per round after 5 business days, same thread, subject
   `Re: A question about your Solutions Catalyst request [CAT-…]`, fixed reviewed words restating the questions
   (`v1:review/reminder.py:308`, `v1:templates/email/review_clarification_reminder.txt`).
9. **Lapse**: after the one reminder (questions or signing) and 10 more quiet business days, case → `lapsed` with
   ONE note, subject `Your Solutions Catalyst request [CAT-…]`, "We will keep your request on file"; a reply, new
   submission or signature reopens it to where it was (`v1:lapse.py:21,85-88,341`,
   `v1:templates/email/case_lapse_note.txt`).
10. **NDA** (Documenso template 3, "Mutual NDA v1.1"): envelope created with `distributionMethod: NONE`
    (Documenso sends nothing) and `externalId onb_<code>_<hash>` (`v1:signing/documenso.py:418-432`,
    `v1:signing/lifecycle.py:20-25`, `v1:signing/packets.v1.json`). Applicant SIGNER order 1, company APPROVER
    order 2, sequential. The **service** emails the link: subject **`Please review and sign: Mutual NDA v1.1`**,
    from agreements@ (`v1:signing/handlers.py:170-172`, `v1:templates/email/signing_link.txt`); link is
    `<DOCUMENSO_PUBLIC_URL>/sign/<token>` (sign.intentsolutions.io); `redirectUrl` → `/signing/return`.
11. **Countersignature**: not in the service. The pilot-bridge `cpn-auto-countersign.timer` (every 10 min,
    `v1:ops/pilot-bridge/systemd/cpn-auto-countersign.timer:6`) signs as the company through Documenso's
    recipient-token routes (decision 12, counsel-approved; `v1:ops/pilot-bridge/pilot_bridge/countersign.py:1-40`).
    Fallback: if the approver has not signed 30 min after the applicant (`APPROVER_LINK_DELAY_MINUTES`,
    `v1:signing/lifecycle.py:97`), the owner gets `"<Name> signed the Mutual NDA v1.1; it is waiting for your
    signature"` (`v1:signing/handlers.py:189`).
12. **Completion detection**: poll, never webhook: `agreement_sync` re-reads each open envelope every
    `DOCUMENSO_POLL_SECONDS` (300) (`v1:signing/lifecycle.py:8-18,95,707`). NDA completed → case
    `nda_pending → setup_pending` and the User Agreement job in the same transaction
    (`v1:signing/lifecycle.py:28-35,101-104`).
13. **User Agreement** (template 4, "User Agreement v2.4"): same mechanics; the service sends a branded cover
    from agreements@, subject **`Your Intent Solutions User Agreement`**, signed "Jeremy", listing what to type on
    the last page (`v1:signing/cover.py:21`, `v1:signing/assets/ua_cover.txt:1-28`,
    `v1:signing/handlers.py:200-218`). Applicant types legal name, residence, structured mailing address (street,
    line 2, city, region, postal code, country dropdown of 243, phone) — field set `ua_v24`
    (`v1:CHANGELOG.md:23-50`). On COMPLETED the typed details are read back into `agreement_details`, then the
    case → `release_pending` (`v1:signing/lifecycle.py:103`). Address quality check flags short/no-country/bad
    postal code to the owner digest, never blocks release (`v1:signing/address_quality.py`).
14. **Signing reminder** (ON): one more copy of the same link email after 5 business days unsigned
    (`v1:signing/handlers.py:120-125`, `v1:signing/reminder.py:25,260`).
15. **Archive gate** (separate service, Documenso team webhook): archives the sealed PDF; v1 reads only a
    metadata status file from `ARCHIVE_STATUS_DIR` (`v1:000-docs/008:144`, `v1:release/policy.py:24-29`).
16. **Automatic release** (ON): `case_auto_release` when NDA executed, UA COMPLETED by applicant then
    `DOCUMENSO_APPROVER_EMAIL`, re-read live, details captured, agreement archived per the gate
    (`v1:release/auto.py:1-30`, `v1:release/policy.py:1-31`).
17. **Mailbox** (ON): username = first name, else `first.last`, `first.last2…9`, reserved list and prefixes,
    checked against MXroute mailboxes and forwarders (`v1:mailbox/usernames.py:1-37`); create with an unseen
    random password, read back, never adopt an account it did not request; case → `active`
    (`v1:mailbox/service.py:1-30,448`). Quota 1024 MB.
18. **Welcome** (ON): sets a fresh 20-char password at MXroute, verifies an IMAP login, sends to the
    **personal** address only (no owner copy), subject **`Welcome to Intent Solutions`**, template
    `cpn-welcome-v1.14`: username + one-time password, MXroute webmail/IMAP/SMTP settings, certification
    paths, exam registration steps, `/start` link, LinkedIn wording, **"Join our Discord" →
    `the community invite link`**, calendar link, support@, signed by Jeremy with the company footer
    (`v1:mailbox/service.py:16-22,519-540`, `v1:mailbox/assets/welcome.manifest.json`,
    `v1:mailbox/assets/welcome.txt:62-63`). Then the owner's "Mailbox issued" notice
    `"<Name> is in the club: <address> is ready"` (`v1:mailbox/issued_notice.py:91-99`) — suppressed today.
19. **Twenty CRM** (ON): every case event queues a projection (`cpn-projection.v2`: name split, links,
    lead source, consent, case state, next action, mailing address parts) and one `Applicant file — <name>`
    note per person, updated in place (`v1:crm/projection.py`, `v1:crm/applicant_file.py`,
    `v1:CLAUDE.md:204-219`). Daily UA-details backfill also fills blank Twenty fields for pilot/existing
    members (`v1:signing/backfill.py`, `v1:worker.py:25-28`).

### 1.3 Timers and pollers

Worker pass every 30 s (`WORKER_POLL_SECONDS`) runs, in order: mailbox poll scheduling, unverified expiry (off),
lapse reopens, review scheduling, clarification reminders, signing sweep + signing reminders, lapses, auto
release, once-a-day UA details backfill, once-a-day digest, then the job queue (`v1:worker.py:63-100`). Host
timers: monitor every 5 min, reconcile hourly at :17, restore drill monthly on the 3rd
(`v1:deploy/systemd/*.timer`); nightly `pg_dump` via borg drop-in
(`v1:deploy/systemd/borg-backup.service.d/30-catalyst-pg-dump.conf`). Pilot bridge: watch, deadman and
auto-countersign every 10 min (`v1:ops/pilot-bridge/systemd/`).

### 1.4 What the owner/staff does by hand today

Owner commands, run in the worker container on the VPS (`v1:operator_cli.py:52-367`, `v1:CLAUDE.md:180-200`):
`approve-applicant` (queues NDA), `decline-applicant` (sends nothing), `withdraw-applicant` (sends nothing; the
closing email is the operator's own), `release-case` / `approve-mailbox` / `resend-welcome` (manual overrides),
`review requeue`, `review council`, `clear-inbound-review`, `reconcile-job`, `signing address-ok`,
`signing request-user-agreement`, `bridge sync`, `talent search|erase`, `notify digest`, `case-status`
(dev-box wrapper `catalyst-status`). With owner mail off (decision 30) the owner learns of escalations only via
`catalyst-status` (`v1:000-docs/008:1112-1114`). Countersigning by hand only when the auto-countersign refuses.

### 1.5 Where v1 data lives

PostgreSQL 16 container on the VPS, its compose directory (`v1:CLAUDE.md:46-48`). Tables:
`onboarding_case`, `case_event`, `agreement`, `job`, `intake_request`, `intake_revision`, `intake_rate_event`,
`outbound_message`, `inbound_message`, `mailbox_cursor`, `review_run`, `review_evidence`, `review_question`,
`review_draft`, `crm_projection`, `crm_review_item`, `legacy_agreement_import`, `agreement_details`,
`ua_details_capture`, `mailbox_account`, `case_release`, `applicant_message`, `applicant_credential`, plus the
dormant setup tables (`setup_case`, `setup_token`, …) (`__tablename__` in each `models.py`); migrations to
`0023_ua_structured_address`. Signature facts: Documenso; sealed PDFs: archive gate; mailboxes: MXroute;
people: Twenty; pilot cohorts: bridge state files on dev box and VPS `/root/pilot-bridge`.

---

## 2. Parity table

Status key: **SAME**; **DIFFERENT** (how); **MISSING**; **BUILT BUT DISABLED** (which switch). "Notice?" =
would an applicant (A) or the owner (O) notice after a silent swap. Effort to match v1: S (days, config or
template), M (a task with tests), L (a new integration or a reversed decision plus live canary). v2 state is the
checkout at `bd4fe9d`; per `v2:000-docs/006-LS-STAT-status.md:10-12` nothing is deployed yet, and D-53
(`v2:000-docs/011-PP-PLAN-master-blueprint.md:420`) authorizes wave 1 only: owner plus members with both
agreements on file, nothing signed, rated or declined, no model.

### 2.1 Entry and intake

| # | v1 behaviour | v2 status | Notice? | Effort | v2 file:line |
|---|---|---|---|---|---|
| 1 | Public entry `learn.intentsolutions.io/request-access` (exact path); `/user/logon` → 302 there | DIFFERENT: own host `catalyst-v2.intentsolutions.io`, path `/request-access/` (trailing slash); learn routing deliberately unchanged at launch (D-51, `211.7.3`) | A: yes (URL, any bookmarked/linked URL) | S code + Caddy, but a reversed decision | `config/urls.py:12-29`; `deploy/production/Caddyfile:63-69`; `correspondence/wording.py:45`; `029:172-174` |
| 2 | Open public intake: anyone may apply | BUILT BUT DISABLED as open intake: `CATALYST_INTAKE_MODE = "invitation"` is fixed in code; uninvited submissions are rolled back silently; invitations are printed by `catalyst_invite` and mailed by the owner by hand | A: yes (an uninvited applicant never hears back) | S (code) + owner decision | `config/settings.py:577-578`; `applications/invitations.py:1-43`; `applications/management/commands/catalyst_invite.py:1-85` |
| 3 | Form v4: name, personal email, country of residence, phone, ≤5 work links, "What are you building" 30-2000, interest track (3 options), marketing opt-in, 18+ box, education ×3 or "none", certifications ×4 with ID/link or "none", verification consent | DIFFERENT: `name`, `email`, `reason`, optional `contribution`, `experience`, `confidential` + description, 3 https work samples with notes, 3 credentials. **Missing:** residence country, phone, interest track, marketing consent, 18+ attestation, education rows, the "none" ticks, verification consent | A: yes (different form) | M | `applications/forms.py:21-46` |
| 4 | CSRF, per-IP rate limit, signed form timestamp, honeypot | DIFFERENT: CSRF and PostgreSQL rate limits (10/client, 3/address per 600 s); **honeypot not found** (029:186 says built; the code has none); signed timestamp not found | no | S | `config/settings.py:562-567` |
| 5 | Global caps 30/h, 100/day defer receipts and review | MISSING (per-client/per-address limits only) | no | S | none |
| 6 | One "received" page for every outcome, shown once | SAME | no | — | `applications/views.py:117-119` |
| 7 | Duplicate from same address → stored revision, no second receipt | SAME in substance (one open application per address; repeat becomes a version; after verification flagged for staff) | no | — | `applications/services.py:7-19` |
| 8 | Sanctions screen on residence/phone → owner hold, applicant never told | MISSING (no residence or phone collected) | O: yes | M | none |
| 9 | Receipt email at once: `We received your request [CAT-XXXX-XXXX]`, reference, interest answer, "reply to withdraw" | DIFFERENT: `Confirm your email address`, an explicit confirm-by-POST link valid 24 h; the application does not proceed until clicked; no `CAT-` reference in the subject. v1 has the same idea behind `INTAKE_EMAIL_VERIFICATION_ENABLED`, which is OFF | A: yes (extra click, different words, no reference) | S to M (wording, or add a v1-style receipt) | `correspondence/wording.py:53-60`; `applications/views.py:129-160` |
| 10 | Applicant mail From "Intent Solutions Agreements" at the agreements address, Reply-To the same, partner badge | DIFFERENT: From `CATALYST_FROM_EMAIL` (v2's own mailbox by decision), **no Reply-To**, no partner badge found | A: yes (sender address/name) | S config + reversed decision (`211.7.3`) | `config/settings.py:603`; `correspondence/messages.py:6` |
| 11 | Owner dossier email per request (`New applicant: <Name>, <country>`) | MISSING by decision (staff queue instead). Note: v1 has had it **switched off** since 2026-10-24 (decision 30 kill file) | O: no today | S-M | `029:113,158` |
| 12 | Talent capture: credentials stored, `talent.verify` queued (verification flag OFF in v1) | DIFFERENT: credentials collected as claims; verification and full-text talent search not found | O: yes (no `talent search`) | M | `applications/forms.py:41-45` |

### 2.2 Review, questions, replies

| # | v1 behaviour | v2 status | Notice? | Effort | v2 file:line |
|---|---|---|---|---|---|
| 13 | Tier 1 GitHub research from a supplied github.com link (public API, 3 reads) | MISSING (no GitHub-specific research) | O: yes (dossier/applicant file) | M | none |
| 14 | Reviewer fetches supplied links through an SSRF guard | BUILT BUT DISABLED: `CATALYST_EVIDENCE_ALLOWED_HOSTS = []` fixed in code, refused outside test/staging | no | M | `config/settings.py:371`; `config/guards.py:264-273`; `assessments/collection.py:301` |
| 15 | MiniMax (`MiniMax-M3`) four-stage review that **acts**: routine applicants advance to the NDA with no human, questions sent automatically, holds applied | BUILT BUT DISABLED and DIFFERENT: one typed `assessment` run (plus reply `interpretation`) that only advises a human; `ALLOW_MODEL_REQUESTS = False`, `build_model` has no live branch, `CATALYST_ASSESSMENT_MODEL = "none"`, no provider client installed, daily requests 0; D-53 "no model" | A: yes (time to NDA goes from minutes to whenever a person decides) | L | `assessments/agent.py:5-6,53,91-107`; `config/settings.py:387,402,419` |
| 16 | Second-opinion panel (advocate/skeptic, 2 of 3) | MISSING | O: indirectly (more decisions land on a person) | L (moot while a human decides) | none |
| 17 | Self-caused hold auto-retry, daily run/send caps | MISSING (no live model) | no | M | none |
| 18 | Decision: routine advance automatic; approve/decline by owner command; decline sends nothing | DIFFERENT: every admit/decline/hold is a person on the decision screen; `CATALYST_QUALIFICATION_AUTHORITY` must be set; decline sends a notice, but a live decline is refused while `COHORT_BOUNDARY = True` | A: yes (decline notice; slower admits). O: yes (decides every case) | M | `assessments/decisions.py:72,241,253-254`; `assessments/staff_urls.py:9-19` |
| 19 | Clarification email (model-drafted, model-checked): `A question about your Solutions Catalyst request [CAT-…]`; ≤2 rounds × 3 questions | DIFFERENT: staff-authored (or model-proposed then approved) question, template `question_request`, placeholder subject `A question about your application` | A: yes (subject, voice) | S (wording) / L (to be automatic) | `correspondence/migrations/0004_role_grants_and_groups.py:64-70` |
| 20 | One clarification reminder after 5 business days, same thread: `Re: A question about your Solutions Catalyst request [CAT-…]` | DIFFERENT: up to 2 reminders every 3 days, quiet hours 02:00-13:00 UTC, then `escalate_unanswered`; placeholder subject `A reminder about your application` | A: yes (count, timing, words) | S (settings + wording) | `config/settings.py:354-361`; `correspondence/migrations/0012_reminder_and_staff_message_grants.py:22-24` |
| 21 | Lapse after 10 quiet business days with one note `Your Solutions Catalyst request [CAT-…]`; reopens on reply/signature | MISSING (an unanswered staff item instead; no closing note, no reopen) | A: yes (no "we'll keep your request on file") | M | none |
| 22 | IMAP poll of agreements@ every 60 s, header-only, durable cursor, reply matched by In-Reply-To/References + From | SAME mechanism (60 s, cursor, exact association, DMARC result), on **v2's own mailbox**; v1's mailbox login is refused by digest | no (if same address) | S config, reversed decision | `correspondence/inbound.py:1-16`; `correspondence/association.py:1-12`; `config/settings.py:343,456-463` |
| 23 | Bounces/autoreplies classified; nothing suppresses on a bounce | IMPROVED: hard bounce pauses and opens an item; autoresponder loop pause | no | — | `correspondence/processing.py:4-10` |
| 24 | Owner reply notice for human mail | MISSING by decision (staff queue). Off in v1 since 2026-10-24 | O: no today | S | `029:126` |
| 25 | Withdraw by replying; `withdraw-applicant` operator command, sends nothing | DIFFERENT: `/withdraw/<token>` link mailed by staff (`Confirm that you want to withdraw`), staff closure path | A: minor (a link instead of a reply) | — | `provisioning/views.py:67-83`; `provisioning/closure.py:54-56,337-358` |

### 2.3 Agreements

| # | v1 behaviour | v2 status | Notice? | Effort | v2 file:line |
|---|---|---|---|---|---|
| 26 | NDA v1.1 (Documenso template 3), then User Agreement v2.4 (template 4); applicant SIGNER then company APPROVER, sequential | BUILT BUT DISABLED: `activate_agreements --activation-version 1 --approval-ref`; templates are DB rows approved on `/staff/p4/templates/`; provider settings code-fixed empty and refused outside test/staging; own Documenso team by decision; signing off for wave 1 (D-53) | A: yes (nothing to sign) | M-L (canary, templates, team) | `agreements/management/commands/activate_agreements.py:1-45`; `agreements/models.py:30,46-77`; `config/guards.py:349-359` |
| 27 | Service emails the link: `Please review and sign: Mutual NDA v1.1` from agreements@; Documenso distribution NONE | DIFFERENT: Documenso sends its own signing email (P4-D-4/P4-D-14) | A: yes (sender, wording, branding) | M | `agreements/handlers.py:11-13`; `021:245` |
| 28 | Branded UA cover `Your Intent Solutions User Agreement`, signed Jeremy, what to type, Schedule A links | MISSING | A: yes | S-M | none |
| 29 | `/signing/return` landing page after signing | MISSING (no route) | A: yes (redirect target 404 or Documenso default) | S | none |
| 30 | Automated company countersign every 10 min (bridge timer, counsel-approved decision 12); owner link after 30 min only on failure | MISSING: the owner countersigns every envelope by hand (manual handoff) | A: yes (wait for owner). O: yes (signs every UA/NDA) | M + owner/counsel decision | `029:138`; `033:156` |
| 31 | Completion by poll every 300 s; NDA completion queues the UA in the same transaction | DIFFERENT: fresh-read sweep every 3600 s (webhook hint only in test/dev); NDA-first enforced, UA advance automatic | A: yes (UA up to an hour after NDA instead of ~5 min) | S (setting) | `config/settings.py:507-508`; `agreements/completion.py:3-10` |
| 32 | Applicant types details on the UA (`ua_v24`: legal name, residence, structured address, 243-country dropdown, phone); read back into `agreement_details` | DIFFERENT: `CATALYST_AGREEMENT_REQUIRED_DETAILS = {}`; details recorded by staff (`AgreementDetailsVersion`, D-46), not read from the envelope | O: yes (manual typing) | M | `config/settings.py:495`; `agreements/completion.py:349` |
| 33 | Address quality flags (short, no country, bad postal code) to the owner | MISSING | O: yes | S-M | none |
| 34 | One signing reminder after 5 business days unsigned (same link email) | MISSING | A: yes | M | none |
| 35 | Separate archive gate (team webhook) archives sealed PDFs; service reads status files | DIFFERENT (IMPROVED): v2 downloads, hash-verifies and stores encrypted copies itself | no | — | `config/settings.py:479-492` |

### 2.4 Release, mailbox, welcome, back office

| # | v1 behaviour | v2 status | Notice? | Effort | v2 file:line |
|---|---|---|---|---|---|
| 36 | Automatic release once NDA + UA complete, details captured, archived | DIFFERENT: an owner-run activation (P4-D-13) | A: yes (delay). O: yes | S-M | `029:201` |
| 37 | MXroute mailbox create, read-before-create, never adopt | BUILT BUT DISABLED: adapter interface only, "a live adapter does not exist"; `CATALYST_PROVISIONING_ADAPTER=""`, `_DOMAIN=""`, `activate_provisioning` | A: yes (no mailbox) | L | `provisioning/adapter.py:1-12`; `config/settings.py:286-287`; `config/guards.py:385-393` |
| 38 | Username = first name, then `first.last`, `first.last2…9` | DIFFERENT: `firstname.lastname` with numeric suffix | A: yes (address format) | S | `provisioning/naming.py:1-30` |
| 39 | Welcome `Welcome to Intent Solutions` with username + one-time password, verified by IMAP login, personal address only | DIFFERENT by decision (P5-D-6): `Set the password for your new mailbox` link (24 h, `/setup/<token>`), then `Your mailbox is ready` (placeholder) | A: yes | M (or reverse P5-D-6) | `provisioning/credentials.py:53-58,397-408`; `provisioning/views.py:36-64` |
| 40 | Welcome body v1.14: webmail/IMAP/SMTP settings, 4 certifications, exam registration steps, `/start`, LinkedIn titles, **Discord invite the community invite link**, calendar link, support@, Jeremy's signature | MISSING: placeholder welcome; no Discord, community, certification or LinkedIn text in code | A: yes | S (approve a template version with that text) | none |
| 41 | "Mailbox issued" owner notice | MISSING by decision. Off in v1 since 2026-10-24 | O: no today | S | none |
| 42 | Twenty projection of every case event + one `Applicant file — <name>` note; marketing consent fields | MISSING by decision (D-08); guards refuse `TWENTY_*` | O: yes (CRM stops updating) | M-L | `config/guards.py:63`; `011:395` |
| 43 | Daily UA-details run fills blank Twenty fields for every completed UA (incl. pilot/existing members) | MISSING | O: yes | M | none |
| 44 | Daily owner digest | MISSING (post-launch option). Off in v1 since 2026-10-24 | O: no today | M | `029:762` |
| 45 | Operator CLI in the worker container + `catalyst-status` board | DIFFERENT (IMPROVED): staff web screens `/staff/p2..p5/`, read-only admin, 2FA, `grant_staff_role` | O: yes (different tools) | — | `correspondence/staff_urls.py:8-29`; `accounts/roles.py:56-94` |
| 46 | Monitor 5 min, reconcile hourly, monthly restore drill, nightly `pg_dump`; alerts to Buzz | DIFFERENT: `catalyst_health`, heartbeat, sweep, backup/restore commands; host timers not installed yet; hourly provider reconcile a later task | no | M | `config/management/commands/catalyst_health.py`; `029:162` |
| 47 | Host kill files per notice family | DIFFERENT (IMPROVED): audited `AutomationPause` | no | — | `workflow/models.py:57` |
| 48 | Pilot-bridge hooks: `bridge sync`, single-writer `claim-countersign`, legacy import commands | MISSING (only `catalyst_member_on_file`, a version-label coverage record) | O: yes | M | `applications/members.py:1-30` |
| 49 | Erasure: none (`talent erase` only) | IMPROVED: erasure path built | no | — | `029:312-379` |

---

## 3. The swap: what must change so applicants see no difference

### 3.1 Public URLs on learn

- Re-point the `@catalyst` matcher in `intent-os/ops/ingress/learn-catalyst/Caddyfile.fragment:9-13` from
  `127.0.0.1:8095` (v1) to v2, for `/request-access`, `/request-access/received`, the two partner-badge asset
  paths, `/signing/return` and `/setup/*`. Keep NOW-LMS's `/user/logon` → `/request-access` redirect and the
  static `/start` page (`learn-start/Caddyfile.fragment:6`) as they are; the welcome links `/start`.
- v2 serves `request-access/` with a trailing slash (`config/urls.py:12-29`); v1 and every link in the wild use
  `/request-access` exactly. Either add exact-path routes in v2 or a Caddy rewrite; the fragment uses exact CEL
  matches, so a rewrite is the smaller change.
- `/setup/*` collides: v1 still serves `/setup/<token>` for any old setup link (none issued since decision 16,
  but tokens issued before 2026-10-04 may be within `SETUP_TOKEN_TTL_DAYS`; production value not determinable)
  and v2 uses `/setup/<token>/` for mailbox passwords. v2 `/confirm/*` and `/withdraw/*` are new paths; v1's
  `/request/confirm/*` is unrouted. `/signing/return` has no v2 route (row 29).
- v2 refuses all of this today by decision: D-51 / `211.7.3` keep the learning host unchanged at launch and
  put the cohort on `catalyst-v2.intentsolutions.io` (`v2:029:172-174,695,708`); changing it is GATE-CUTOVER.
  Also `CATALYST_INTAKE_MODE = "invitation"` is fixed in code (`v2:config/settings.py:577`) and the
  provisional wording lock holds the form shut until the owner approves the `data_notice` and
  `verification_invitation` wordings (`v2:applications/views.py:77-87`).

### 3.2 Sender address and mailbox

- v1: SMTP From the agreements address, display name "Intent Solutions Agreements", Reply-To the
  same, and the same mailbox is polled by IMAP (`v1:CLAUDE.md:151-158`, `v1:intake/receipt.py:122-124`). The
  same mailbox also carries the pilot bridge's sends and every existing member's replies.
- v2: From `CATALYST_FROM_EMAIL`, no Reply-To, its own mailbox, and the v1 login is actively refused by digest
  (`CATALYST_MAIL_DENIED_USER_SHA256`, `v2:config/settings.py:456-463`). Decision `211.7.3`/P6-D-10/M8:
  "a second poller of the first-generation mailbox would duplicate and race" (`v2:029:126`).
- For an invisible swap: v2 must send from agreements@ with the same display name and set Reply-To, and own
  the IMAP poll of agreements@. That needs (a) the v1 worker's IMAP poll stopped first (unset `IMAP_HOST` on
  v1), (b) the denied-digest guard reversed, (c) v2's association to tolerate replies to v1 Message-IDs: it
  matches only its own Message-IDs (`v2:correspondence/association.py:5`), so a reply to an old v1 receipt or
  question would be an unassociated item for staff, not a resumed review.

### 3.3 Documenso team, templates, webhook, countersign

- v1: one team; NDA = template 3, UA v2.4 = template 4, envelopes `onb_<code>_<hash>`, distribution NONE,
  `redirectUrl` `/signing/return`; the team webhook feeds the separate archive gate; the bridge's
  auto-countersign matches template allowlist `1,3,4` and `onb_` ids and takes the ledger's single-writer
  claim in the v1 database (`v1:CLAUDE.md:106-110,135-147`, `v1:ops/pilot-bridge/pilot_bridge/countersign.py:30-40`).
- v2: its own templates as DB rows, `ag_` external keys, the provider sends the signing email, its own
  POST-only webhook site, a separate Documenso team recommended (D-B/D-51, `v2:030:66-78`, `v2:029:161`),
  owner countersigns by hand.
- For an invisible swap: the same PDFs and the same `sign.intentsolutions.io` host (applicants do not see team
  ids), but distribution NONE plus a v2-sent link email and cover, the `/signing/return` page, and the
  `ua_v24` field layout read back into v2. If v2 shares v1's team, every v2 envelope reaches the archive gate
  and v1 auto-countersign must be proven not to touch `ag_` envelopes (the canary's negative control,
  `v2:029:162`); if v2 gets its own team, the countersign automation and the archive gate need a v2 path or
  stay manual (owner signs every envelope).

### 3.4 In-flight v1 cases and how they finish

v2 has **no import path** for v1 cases (only `catalyst_member_on_file`, a version-label coverage record,
`v2:applications/members.py:1-30`). v1 cases sit in `requested`, `reviewing`, `needs_information`,
`nda_pending`, `setup_pending`, `release_pending`, `provisioning`, `held`, `lapsed`; open envelopes are v1's,
reminders and lapses are v1 timers. The only safe pattern with today's code is a **drain**:

1. Route only new intake (`/request-access`, `/received`) to v2; leave v1's web container serving
   `/signing/return` and `/setup/*` until its last case closes.
2. Keep the v1 worker running for existing cases: signing sweeps, reminders, lapse, auto-release, mailbox and
   welcome, Twenty, the bridge's auto-countersign. It needs agreements@ SMTP and IMAP to keep working, which
   collides with 3.2: either v2 sends from another address during the drain (applicants notice), or v2 sends
   from agreements@ by SMTP only while v1 keeps the IMAP poll (v2 then gets no replies), or replies are split
   by a mailbox rule (MXroute blocks Sieve redirect, `v1:CLAUDE.md:154`). No option is invisible.
3. A v1 applicant who re-applies at the new form gets a fresh v2 application: v2 cannot see the v1 case
   (the cross-system duplicate gap, `v2:029:114`, `dy7.2`). Mitigation today: a manual check by the owner.
4. Lapsed v1 cases reopen on a reply or signature only while v1 polls; after v1 stops they are dead.

### 3.5 v1-only data v2 would need for "nothing changes"

- Who is already a member: completed NDA/UA per person (v1 ledger + bridge state + the 36 existing-member
  UAs), so nobody is asked to sign twice (v2 records this only as `catalyst_member_on_file`, typed by hand).
- Existing mailbox usernames (81+ at MXroute, first-name style) for collision checks — v2 would read MXroute
  directly if a live adapter existed (none does).
- Open v1 references (`CAT-XXXX-XXXX`) and Message-IDs, so replies to old threads associate.
- Twenty person ids and the `Applicant file` note ids, if v2 is to keep the CRM current.
- Typed agreement details (`agreement_details`) for anyone whose UA completed on v1.
- Review evidence, questions asked and reply text, if v2's staff screens are to show history.

### 3.6 What v1 does that v2 deliberately refuses (with the decision)

| v1 behaviour | v2 refusal | Decision / cite |
|---|---|---|
| Email a one-time mailbox password in the welcome (v1 decision 11) | Applicant sets their own password via `/setup/` | P5-D-6, `v2:000-docs/023:162`; `v2:029:149,203` |
| Model reviews and **acts** (advance to NDA, send questions) | No model requests; human-only assessment; model output never sent unapproved | `oc4.9`, P3-D-5, P3-D-10; D-53 "no model" (`v2:011:420`); `v2:029:124-125`; `v2:assessments/agent.py:91-107` |
| Fetch applicant links / GitHub research | Allow-list empty until `9kg.39` | `v2:029:123,700` |
| Owner notices by email (dossier, reply, review, mailbox issued, digest) | Staff queue and health report | `v2:029:113,126,158,188` |
| Share agreements@ mailbox and poller | Own mailbox; v1 login refused | M8, P6-D-10, `211.7.3`; `v2:029:126,160` |
| Automated company countersignature | Owner signs by hand | `211.7.4`, `dy7.2`; `v2:029:138,199`; `v2:033:156` |
| Shared Documenso team and webhook | Own team or agreements disabled | D-B in D-51; `v2:030:66-78`; `v2:029:161` |
| Service-sent signing email (distribution NONE) | Provider sends it | P4-D-4, P4-D-14; `v2:021:245` |
| Twenty CRM projection and applicant file | Not built | D-08, `v2:011:395`; `v2:029:159,204` |
| Learn host routing at launch | Dedicated v2 host | D-51, `211.7.3`; `v2:029:172-174` |
| Automatic release | Owner-run activation | P4-D-13; `v2:029:201` |
| Access promises beyond the mailbox (Discord/LMS) | Mailbox only | P5-D-7, `v2:023:163`; `v2:029:763` |
| Decline anyone in the cohort; rate colleagues | Refused while `COHORT_BOUNDARY` | D-52 Q5/Q6, `v2:033:159,178`; `v2:assessments/decisions.py:253,302` |
| v2 sends invitations | Owner sends by hand | `v2:catalyst_invite.py:6-7`; `v2:033:50` |

P5-D-7 is the one that bears directly on the Discord invite: v2's welcome promises the mailbox only, so the
v1.14 welcome's Discord button is a deliberate exclusion today, not an oversight.

---

## 4. Top 10 gaps, ranked by "an applicant or the owner would notice"

1. **Nobody outside an invitation can apply, and the URL is different.** Work: route learn's exact v1 paths
   to v2 (3.1) with a `/request-access` (no slash) route; make intake mode a setting and turn open intake on;
   owner approves the data notice and verification wordings; reverse D-51/`211.7.3` through GATE-CUTOVER.
2. **Every applicant waits for a person to decide.** v1 advances routine applicants to the NDA within minutes
   with no human (MiniMax, decision 18). Work, either: (a) owner commits to deciding every case on the v2
   decision screen with a same-day SLA and a way to learn a case is waiting (v2 sends no owner mail); or
   (b) build the live MiniMax client, the routine-advance policy and the approvals (`oc4.7`, `oc4.9`, data-use
   decision `211.7.4`) — L.
3. **Agreements are off, and when on they look different.** Work: Documenso canary; load NDA v1.1 and UA
   v2.4 as v2 templates with the `ua_v24` field layout; switch to distribution NONE and send the v1 link email
   and branded UA cover from agreements@; add `/signing/return`; set the completion sweep to 300 s; read the
   typed details back from the envelope instead of staff typing them.
4. **The welcome and mailbox are not there.** No live MXroute adapter, `firstname.lastname` instead of first
   name, set-your-own-password instead of the one-time password, and a placeholder welcome with no Discord,
   certification, `/start`, LinkedIn or calendar content. Work: build the MXroute adapter and canary; adopt
   v1's username rule; either reverse P5-D-6 or accept the visible change; approve a welcome template with
   the v1.14 text (and the Discord invite, reversing P5-D-7 for that link).
5. **The form is a different form.** Work: add residence country, phone with calling code, interest track,
   marketing consent (wording `marketing-updates.v1`), 18+ attestation, education/certification rows with
   "none" ticks and the verification consent; keep the v1 limits; add the honeypot and signed timestamp.
6. **The first email is a confirm-click, not a receipt with a reference.** Work: either send a v1-style
   `We received your request [CAT-…]` receipt (and keep confirmation as a later, separate step) or accept the
   extra click; carry a `CAT-`-style reference in subjects so threads look the same.
7. **Sender and replies.** Work: From agreements@ with display name "Intent Solutions Agreements" and
   Reply-To; move the IMAP poll from v1 to v2 at a planned cut (3.2); association of replies to v1
   Message-IDs, or a drain period.
8. **Countersign and release are manual.** The owner would sign every NDA and UA and activate every release.
   Work: an owner/counsel decision to carry v1 decision 12 to v2 envelopes (or extend the bridge's
   auto-countersign to v2 with a claim in the v2 database) and an automatic release under the same
   deterministic conditions.
9. **Follow-up cadence differs.** No signing reminder; clarification reminders are twice every 3 days
   instead of once after 5 business days; no lapse note or reopen. Work: settings to 1 reminder after 5
   business days; add the signing reminder job; add the lapse state, note and reopen-on-reply.
10. **Back office goes quiet: Twenty and talent search stop.** No projection, no `Applicant file` note, no
    daily UA-details fill, no GitHub research, no `talent search`, no address-quality flags. Work: a Twenty
    adapter (reverse D-08), the details backfill, GitHub Tier 1 research behind the evidence allow-list, and a
    search view. (Owner dossier/digest/reply notices are not on this list because v1 has had them switched off
    since 2026-10-24; if the owner wants them back, they are a further M.)

**Bottom line.** v2 today is not a drop-in replacement and cannot become one by configuration: roughly a
third of the rows are deliberate design refusals recorded as owner or council decisions (password mail,
acting model, shared mailbox and Documenso team, automatic countersign, CRM, learn routing), and the rest
need building (MXroute adapter, Documenso canary and cover mail, form v4, reminders/lapse, Twenty, research).
A silent swap requires the owner to reverse at least D-51, P5-D-6, P5-D-7, P4-D-4/14, P6-D-10/`211.7.3`,
D-08 and the D-53 "no model" condition, plus a drain plan for open v1 cases. Overall effort: L.

---

## 5. v1 work in flight that is NOT live

Read from the first-generation checkout with git and `gh pr view` only (origin/main = `d519f5c`
= production). Nothing below runs in production.

### 5.1 PR #120 "Port onboarding lifecycle to Django and preserve migration safety"

- **State:** draft, open; head `feat/django-agreement-lifecycle` at `92936a6` (last code 2026-10-08; the
  2026-10-17 update is only the owner's "parked draft" comment). Base is `feat/gatekeeper-v2`, not `main`.
  Parked by v1 decision 24 (`v1:000-docs/008:747`).
- **Size/age:** forked from `main` at `e005545` (2026-10-06); 49 commits behind `origin/main`, 317 ahead
  (286 its own); 589 files, +92,578/−5,094. All 21 hosted CI checks failed before any step (GitHub billing
  hold); the PR body claims ~4,659 tests passed locally at `92936a6` (not re-run). No human review.
- **Architecture:** Django on top of the **Alembic-owned** schema (`managed = False` models, no Django
  migrations) plus **Temporal** (`src/catalyst/temporal/`: case-operations workflow, 5-minute agreement
  observer, CRM workflow; `deploy/temporal/` self-hosted stack). "Retained" execution keeps live ids, job keys
  and provider identities.
- **What it ports:** intake views, the four MiniMax review stages and clarification/reply rounds, Documenso NDA
  → User Agreement with typed-details capture, the service-sent cover email, countersign client, Documenso
  webhook ingestion, archive, MXroute mailbox and welcome (one-time password), release, Twenty projection and
  applicant-file note, GitHub research, monitor/reconcile, operator commands; ~100 files in
  `src/catalyst/django_app/`, 40 in `src/catalyst/domain/`, 18 `native_*` commands, 211 test files.
- **How far it got:** components only; the Temporal worker has "no production entrypoint"; the PR body lists
  the full native journey, installed handoff, rollback and restore as unproven.
- **Cannot apply to the live database as is:** its `0019_one_outbound_conversation` and main's
  `0019_review_council` both descend from `0018` (two Alembic heads; production is at `0023`); its frozen
  `0002` state list lacks `lapsed`; it edits `0002`/`0004` history.
- **Missing everything since the fork:** council (#145), dossier + digest (#142), signing reminder (#127),
  reminder-then-lapse (#156), `ua_v24` address form (#165), talent profile/search (#162),
  `withdraw-applicant` (#172), routine-hold settlement (#174), Discord welcome (#180). Its welcome still has
  the WhatsApp invite.
- **Overlap with v2 / where it is ahead of v2:** #120 has these live-v1 behaviours that v2 lacks: Twenty
  projection + applicant-file note; the multi-stage MiniMax review; GitHub-specific research; details read back
  from the signed User Agreement (v2 has staff type them); the service-sent signing cover email; automated
  countersign; the one-time-password welcome. **v2 is ahead of #120** on withdrawal paths, bounce blocking,
  audited pause, erasure, custody with hash verification, invitation mode and staff UI; and neither has the
  post-fork features. **Use:** reference material only for the Twenty lane, the typed-details capture and the
  cover-email/countersign flow; its Temporal layer contradicts v2's single PostgreSQL job system and its
  migrations contradict live Alembic. It is not a faster route to parity.

### 5.2 PR #179 "feat(ops): add default-off worker process observations"

Draft, open; head `feat/discord-container-activity` at `dafeeb6` (2026-10-27), 1 commit, 1 behind `main`,
required checks green. Adds an optional hook to `deploy/ops/catalyst-ops-run.sh` (+46/−1) that reports only
"worker container running/stopped" (from `docker inspect`) to a shared **Discord activity outbox**. Off unless
`INTENT_ACTIVITY_ENABLED=1` and `INTENT_ACTIVITY_SPOOL_DIR` (mode 700) are set; `INTENT_ACTIVITY_BRIDGE`
overrides the helper path; non-blocking `flock`, 5 s timeout, no private data. Tests
`tests/unit/test_worker_activity.py`, fixture, runbook `023` (+43). Held as draft because a `deploy/**` merge
auto-deploys; depends on intent-os `7287307` and solution-catalyst-discord `60b2f74`. **Applicant-invisible.**
v2 equivalent: none (v2 alerts go to Buzz); parity impact nil unless the owner wants the Discord activity feed
from v2 too.

### 5.3 Branch `origin/feat/discord-container-activity`

The head branch of #179 and nothing else (identical 4-file diff, +298/−1; `gh pr list --head` returns only #179).

## Receipt and reference integration contract (bgl.5)

Every application receives a unique `CAT-XXXX-XXXX` label. It is never an authentication credential.
Application migration `0011_application_reference` preserves references from already-imported cases
before assigning labels to other existing applications. Subsequent first-generation imports set the
original reference at creation; duplicate references fail instead of silently renaming a case.

Correspondence migrations `0025_subject_reference` and `0026_intake_receipt_templates` add the
approved-version subject flag and two synthetic draft templates. The subject flag and HTML are both
covered by the content digest and database freeze. Verification, questions, reminders, decline,
signing and password-welcome senders honor the flag. Existing approved templates remain unchanged;
new wording needs an explicit template approval.

`CATALYST_INTAKE_RECEIPT=on` enables a separate receipt queued once for a new application. It shares
any intake-cap deferral with verification. Also setting `CATALYST_RECEIPT_IS_VERIFICATION=on` combines
the receipt and verification link into one mail instead. Both switches default off and must match on
web and worker. Enabling a mode in production requires approved, non-synthetic wording; intake is
withheld when that wording cannot be rendered. A repeat submission never queues another separate
receipt. Ambiguous deliveries after a restore require review under the existing restore policy.

These are repository behaviors, not evidence of production activation or approved real wording.
The confirmation page also displays the new form answers before the applicant adopts that version.
