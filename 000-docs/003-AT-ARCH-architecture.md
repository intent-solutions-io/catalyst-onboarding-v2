# Architecture: Catalyst v2 onboarding

| Field | Value |
|---|---|
| Document | `003-AT-ARCH-architecture` (the only architecture description for this repository) |
| Version | 0.2.0 (template sections replaced; the routing sections from PR #5 are unchanged) |
| Status | **PROPOSED**, except where a row says OWNER-DECIDED or VERIFIED |
| Owner | Jeremy Longshore |
| Date | 2026-10-09 |
| Related | `011` (decisions summary, authority, policies), `002` (requirements), `004` (journey), `005` (first slice) |
| Classification | Public; internal addresses, ports and hostnames other than the public learn host are omitted |

> **Status: PRELIMINARY, subject to review.** Nothing here is implemented, configured or deployed.

## System context

```text
Applicant browser ──HTTPS──▶ reverse proxy (learn.intentsolutions.io) ──assigned paths──▶ Django web
Staff browser ──HTTPS, restricted network──▶ staff hostname ─────────────────────────────▶ Django web
Django web ──▶ PostgreSQL ◀── Django worker ──▶ MXroute (SMTP send, IMAP collect, provisioning)
                                           ──▶ Documenso (envelopes; webhooks to Django web if P4 chooses them)
                                           ──▶ MiniMax (through PydanticAI)
LMS (unchanged) keeps every unassigned path on the learn host.
```

Text inventory. **Nodes:** applicant browser, staff browser, reverse proxy, Django web process, Django
worker process, PostgreSQL, MXroute, Documenso, MiniMax, LMS. **Trust boundaries:** (1) public internet
to proxy; (2) proxy to Django web (loopback or private socket only); (3) staff network restriction in
front of the staff hostname; (4) Django processes to external providers (outbound only, credentials only
in production); (5) Documenso webhooks inbound to Django web, authenticated with the installed Documenso version's documented mechanism (the current public documentation describes a shared-secret header, NEEDS VERIFICATION on the installed version). **Flows:** applicant
form and confirmation pages; staff admin and focused views; worker claims pending actions from PostgreSQL
and calls providers; webhooks record observations. **Conclusion:** PostgreSQL is the only system of
record; the worker is the only caller of providers; a webhook receiver, if P4 adopts webhooks, only records.

## Component design

One Django project, two process types (web and worker) from the same code, six cohesive domain apps plus
a small `accounts` app for the custom user model (ADR-18) and a `config` settings package that is not an
app. App names are proposals (ADR-01).

| Component | Responsibility | Depends on |
|---|---|---|
| `workflow` | the one execution mechanism chosen by ADR-03 (the custom ledger, decided by ADR-03: kind, subject type and id, idempotency key, due time, lease token and expiry, attempts, status), automation pauses keyed by subject, the worker loop, the handler registry. Subject-generic: no foreign key to any domain model | Django only |
| `accounts` | the custom user model; nothing else | Django only |
| `applications` | application, submission versions, append-only history events, contact challenges, stage state service, decisions, withdrawal; sets and clears automation pauses through `workflow` services | `workflow`, `accounts` |
| `correspondence` | outbound and inbound messages, templates, mailbox cursor, correlation, reminder and stop rules | `applications`, `workflow` |
| `assessments` | evidence items, assessment runs (PydanticAI with MiniMax), questions | `applications`, `workflow` |
| `agreements` | agreement inventory, instances, recipients, provider observations, stored documents and access records | `applications`, `workflow` |
| `provisioning` | provisioning requests and verification, activation | `applications`, `workflow`, `correspondence` |
| Staff interface | Django admin registrations live in each app; focused staff views (queues, dossier, actions) | all apps, through services |
| `config` (settings package) | environment-driven settings; refuses non-PostgreSQL engines and provider credentials or non-sink mail hosts outside production, both as system checks and in `AppConfig.ready()` | none |

**Layer rules (proposed).** Views, admin actions and job handlers call service functions; service
functions own transactions and stage transitions; models hold fields and database constraints, not
workflow logic. Provider clients sit behind small adapter modules with in-repository fakes used by tests.
Imports run one way: `workflow` and `accounts` import no domain app (so the migration graph has no cycle),
domain apps never import views. No app imports
another app's private models for writing; cross-app writes go through that app's services.

## Data flow (primary path)

1. Applicant POSTs the form → `applications` accept service → one transaction writes application,
   submission version, history event, challenge, pending action (J-01).
2. Worker claims the action (`SELECT ... FOR UPDATE SKIP LOCKED`, new lease token, attempts counted) →
   renders and sends through the mail backend → records the outbound message and completes the action
   with a write fenced by the lease token (J-03; ledger rules in `005` S1.4).
3. Applicant confirms (POST) → one transaction records verification and the next action (J-03).
4. Later phases repeat the same pattern: claim, call the provider outside the transaction, record the
   result with provenance, enqueue the next action only if the stage service allows it (J-04 to J-15).

## Integration points

| Service | Direction | Used for | Status |
|---|---|---|---|
| MXroute SMTP | outbound | applicant correspondence (P2 onward; first slice uses a local sink) | OWNER-DECIDED provider; settings NEEDS VERIFICATION |
| MXroute IMAP | inbound poll | reply collection (P2) | OWNER-DECIDED provider; reply-address support NEEDS VERIFICATION |
| MXroute provisioning | outbound | mailbox creation (P5) | interface NEEDS VERIFICATION; operator fallback designed in `004` J-14 |
| Documenso API and webhooks | both | agreements (P4) | OWNER-DECIDED provider; installed version, API generation and webhook authentication mechanism NEEDS VERIFICATION |
| MiniMax through PydanticAI | outbound | assessments (P3) | OWNER-DECIDED; structured-output support NEEDS VERIFICATION |
| Reverse proxy | inbound | path routing | current table VERIFIED read-only (below); v2 rules PROPOSED |
| Twenty | none | deferred | OWNER-DECIDED out of MVP |

## Security model

- **Authentication:** applicants are anonymous until contact control is verified; afterwards they act
  only through single-use signed links and replies from the verified address. Staff use individual Django
  accounts on the staff hostname with MFA (D-12; package NEEDS VERIFICATION).
- **Authorization:** Django groups and model permissions, deny by default; decision and provisioning
  permissions exist only once POL-05 and POL-11 define them.
- **Data classification:** applicant personal data, correspondence and executed agreements are
  confidential; they live only in PostgreSQL and protected document storage, never in the repository,
  Beads, CI logs or static files (REQ-019).
- **Secrets:** SOPS-encrypted files decrypted at runtime on the production host, per the estate standard;
  no provider credential exists in development, test or CI (REQ-022).
- **Model input:** evidence and applicant text are untrusted data to the model; the model has no tools
  that write or send (D-04).
- **Logging:** identifiers only; tokens and query strings redacted (REQ-020).
- Proxy, cookie, framing and host controls are in "Security implications" below.

## Error handling

| Condition | Behaviour | Recovery |
|---|---|---|
| Database error during acceptance | transaction rolls back; applicant sees a retry page | applicant resubmits; duplicates handled (J-02) |
| Worker crash mid-action | lease expires; action claimed again; attempts were counted at claim | automatic up to the attempt limit, then `failed`. The idempotency key prevents duplicate action rows, not duplicate effects: effects are de-duplicated per kind (unique outbound message per attempt, provider lookups) or declared redeliverable |
| Worker outlives its lease | another worker reclaims the action | the late worker's result write is fenced by the lease token and discarded |
| Provider error | bounded retry with backoff | then `failed` in the staff queue |
| Provider outcome unknown | action `uncertain` | reconcile by provider lookup where possible, else staff |
| Model output invalid | bounded output retries | then `failed`; staff queue; never a decision |
| Prerequisite unmet | transition refused by the stage service | no state change; staff see why |

## Performance

No latency or throughput target is set (POL-16). Measures are defined in `002` section 5. The design
choice that matters at this scale is correctness under concurrency, not speed.

## Infrastructure

- **Hosting:** the estate's production host behind the existing reverse proxy is the expected target;
  the decision and the staging layout are made at P6 (NEEDS OWNER DECISION).
- **CI/CD:** GitHub Actions; documentation lane today; runtime lane with a PostgreSQL service added in the
  first slice (`005` S1.6). No deployment from CI without separate authorization.
- **Monitoring and logging:** pending-action health and the staff queues are the first monitors; estate
  alerting integration is designed at P6.

## Learn and Django routing (current routing checked read-only; v2 routing proposed)

**Status:** the current routing was read from the live proxy configuration on 2026-10-09 in a read-only,
owner-authorized check (no reload, no edit). Everything about **v2** is proposed; nothing for v2 is
configured.

### Current routing (summary only)

The learn host's proxy sends a small set of exact onboarding paths to the **first-generation** Catalyst
onboarding service and every other path to the existing LMS, which is the default route. A v2 cutover
replaces only the first-generation onboarding rules, never the LMS default.

The detailed current route table, header configuration and logging settings are operational detail and
are **not** kept in this public document. The authoritative baseline is the live proxy configuration on
the production host, held in the estate's private operations records; P6 re-reads it read-only before
any cutover and compares against it there. An earlier revision of this document (merged in PR #5)
contained more detail; it remains in Git history, which this change does not rewrite.

### Topology

```text
Browser ──HTTPS──▶ reverse proxy on the authorized host (learn.intentsolutions.io)
                     ├── learning routes ──────────────▶ existing LMS (unchanged)
                     └── assigned onboarding routes ───▶ Django production web service (WSGI/ASGI server)
                                                            │
                                     Django worker ◀────────┤  (not public ingress)
                                                            ▼
                                                        PostgreSQL
```

- The learning site does **not** move into Django and its course content stays where it is.
- A shared hostname does not imply a shared framework or process. The LMS and Catalyst may share a
  host while staying separate processes or containers with separate data.
- Django runs behind a production WSGI or ASGI server, never `runserver`
  ([Django 5.2, "How to deploy Django"](https://docs.djangoproject.com/en/5.2/howto/deployment/),
  checked 2026-10-09). The 5.2 line is a reference, not an approved dependency pin.
- Which application serves a path is decided by the proxy's path routing (for Caddy, `handle` blocks:
  [Caddy, "handle"](https://caddyserver.com/docs/caddyfile/directives/handle), checked 2026-10-09),
  not by the domain.
- Existing routes are preserved until an approved cutover. The live proxy configuration, held in the
  estate's private operations records, is the baseline any cutover is compared against.

### Route-ownership matrix (proposed)

| Path and method | Owning app | Upstream | Authentication | Cookies / CSRF | Static assets | Sensitive files | Failure behaviour | Cutover and rollback |
|---|---|---|---|---|---|---|---|---|
| everything not listed below, all methods | LMS | LMS service | LMS | LMS cookies | LMS | none from Catalyst | LMS error pages | unchanged |
| `/request-access` and its received page, GET and POST | Catalyst v2 | Django web | none (public form) with abuse controls | Django CSRF; cookie name and path scoped to avoid collision with LMS cookies | Django static under a Catalyst-specific prefix | none | Catalyst error page, no LMS fallback | switch the `handle` target; rollback restores the previous target |
| email-confirmation and signing-return paths, GET | Catalyst v2 | Django web | one-time tokens | no state change on GET | as above | none | as above | as above |
| staff interface (Django admin and focused views) | Catalyst v2 | Django web, **not** on the learn host | Django auth, staff groups, MFA | Django session and CSRF on the staff host only | as above | dossier views only through authorized views | deny by default | separate staff hostname (see "Staff interface access (design)") |
| health and readiness | Catalyst v2 | Django web | none | none | none | none | returns status only | **not exposed publicly**; loopback or operator network only |
| Django worker | Catalyst v2 | none | n/a | n/a | n/a | n/a | n/a | never routed |

Check during cutover: trailing slash and prefix behaviour (`/request-access` versus
`/request-access/`), path normalization, and that no LMS path is shadowed by a Catalyst prefix.

### Security implications

Every control below is **intended (proposed)**. None is configured; each becomes "configured" only
when a reviewed change applies it and "enforced" only when a test or the proxy proves it.

- **Path separation is not a security boundary.** Both applications share one origin: a script
  injected into any LMS page can read same-origin responses, submit Catalyst forms and read tokens
  in Catalyst URLs. An LMS login never counts as a Catalyst identity.
- **Cookies:** CSRF and any session cookie use the `__Host-` prefix (no `Domain` attribute, path `/`,
  `Secure`), `HttpOnly` where applicable and `SameSite`; no Catalyst session cookie on public paths
  where avoidable. Scoping cookie names and paths does **not** stop a sibling subdomain setting a
  parent-domain cookie ("cookie tossing"); the `__Host-` prefix does.
- **Framing and content:** `Content-Security-Policy` with `frame-ancestors 'none'` (and
  `X-Frame-Options: DENY`) on Catalyst pages; `Referrer-Policy: no-referrer` on token-bearing pages;
  query strings redacted from proxy and application access logs.
- **Upstream exposure:** the Django web service listens on loopback or a private socket only, so the
  proxy cannot be bypassed. The proxy strips client-supplied `X-Forwarded-*` headers before setting
  its own; Django trusts exactly one proxy hop and uses `SECURE_PROXY_SSL_HEADER` accordingly.
- **Fail closed:** on the public host the proxy forwards only the listed Catalyst paths; `/admin` and
  every unlisted path never reach Django there. Path normalization and encoded slashes are tested so
  `/request-access/../admin` and `%2F` variants cannot reach an unlisted route.
- **Hosts:** `ALLOWED_HOSTS` contains the public host, plus the staff hostname if that proposal is
  adopted.
- **Staff surface:** a separate staff hostname **and** network restriction (operator network or VPN)
  is proposed; a hostname alone does not isolate staff sessions from an LMS compromise on a sibling
  subdomain. Not configured.
- **Abuse controls:** rate limiting and request body-size limits at the proxy and in Django; client
  address taken only from the trusted proxy hop; `Host` validated at the proxy.
- **Documents:** executed or confidential agreements are never served as static or public media;
  access goes through authorized views with audit.
- **Health routes** are not routed publicly and never return version, configuration or dependency
  detail.
- Review by `catalyst-security-privacy` is required before any cutover.

### Staff interface access (design; owner decision 2026-10-09, hostname and method to be verified)

The staff interface is served on its own authenticated hostname, never on `learn.intentsolutions.io`.
The final hostname and access method are a design decision that needs verification; this section is
the design, not a configuration.

| Concern | Design | Status |
|---|---|---|
| Hostname | a dedicated staff hostname under the company domain, distinct from the learn host; exact name to be chosen | design decision, unverified |
| Network restriction | reachable only from the operator network (VPN or equivalent); the proxy refuses other sources before Django sees the request | design decision, unverified |
| Authentication | Django's authentication system with staff accounts and groups; no shared accounts | proposed |
| MFA | required for every staff account where the chosen package supports it. Django has no built-in MFA; candidates to evaluate are `django-otp` (TOTP) and the MFA module of `django-allauth` (TOTP, WebAuthn). Choice requires verification of maintenance, Django-version support and admin integration | design decision, unverified |
| Sessions and cookies | `__Host-` prefixed session and CSRF cookies on the staff host; short idle timeout; no cookie shared with the learn host | proposed |
| Admin URL | Django admin mounted only on the staff host; the public host never forwards `/admin` | proposed |
| Audit | every staff action through a business service with an audit row (`007`, operator specialist) | proposed |

References: [Django 5.2, "The Django admin site"](https://docs.djangoproject.com/en/5.2/ref/contrib/admin/) and
[Django 5.2, "User authentication in Django"](https://docs.djangoproject.com/en/5.2/topics/auth/),
checked 2026-10-09. Package documentation for the MFA candidates is checked when one is chosen.

## Architecture decisions

The decision records for this repository. Status uses `011` section 1. An ADR with status PROPOSED
binds only after the owner approves it in a merged PR; an OWNER-DECIDED one cites its source in `011`
section 4.

| ID | Decision | Status | Rationale and alternatives |
|---|---|---|---|
| ADR-01 | One Django project, web and worker processes from one codebase, six domain apps (`workflow`, `applications`, `correspondence`, `assessments`, `agreements`, `provisioning`) | direction OWNER-DECIDED (D-01); app split PROPOSED | apps follow the journey's ownership boundaries; fewer apps would mix provider adapters with the dossier; more would split one transaction across apps |
| ADR-02 | PostgreSQL only, in tests, staging and production; settings refuse other engines | OWNER-DECIDED (D-02) | locking (`SKIP LOCKED`, `select_for_update`), partial unique constraints and concurrency tests must run on the real engine |
| ADR-03 | One PostgreSQL-backed execution mechanism: a **custom pending-action ledger** in `workflow`, claimed with `select_for_update(skip_locked=True)` and a lease token, run by a Django management-command worker, meeting the behavioural rules in `005` S1.4. Scope: the bounded Catalyst MVP only; not a reusable queue framework, distributed scheduler, plugin architecture or second execution engine | **OWNER-DECIDED 2026-10-10** (D-16), from the `012` evidence at PR #8 head `62a4a9d` | Comparison as recorded by the owner: Procrastinate passed every behaviour tested and remains a viable option; the custom proof demonstrated claiming and fenced completion, **not** a complete automatic worker loop; package and table counts do not prove maintenance superiority; neither candidate demonstrated exactly-once external effects. **Not demonstrated by `012`:** automatic recovery by a polling worker, pause handling, bounded attempts with the poison rule's history event, `uncertain` outcomes, reconciliation, operational visibility. The first four and staff visibility of pending actions are S1 acceptance (S1-T5, S1-T7, S1-T8: TEST-S1-07, 12, 17, 18, 19); Recovery policy (owner clarification 2026-10-10, D-20): S1 still proves attempts, bounded recovery, lease fencing, interruption handling and no duplicate challenge, adoption or next-stage action; only the identical verification invitation may be redelivered to the local sink after an interrupted attempt. Provider-specific reconciliation of `uncertain` outcomes is deferred to P2 or the relevant integration phase, before any real external action is enabled; it is not implemented and not unnecessary. Temporal stays out of scope (D-03) |
| ADR-04 | MiniMax through PydanticAI, typed output with evidence references, advisory only | OWNER-DECIDED (D-04) | model output cannot authorize transitions; PydanticAI gives typed validation, retries and test models without network |
| ADR-05 | Existing Documenso installation. Signing completion and custody are separate facts with separate statuses (`004` "Agreement facts"); signing completion requires a fresh provider read showing every required participant complete; webhook requests are authenticated with the installed version's documented mechanism; webhook versus polling is a P4 design choice | provider OWNER-DECIDED (D-05); the rest PROPOSED; installed version NEEDS VERIFICATION | one webhook is not proof of completion; an archive failure must not erase signing evidence; the current public docs describe a plain shared secret in `X-Documenso-Secret` compared in constant time, not an HMAC signature (Documenso "Webhook Verification", read 2026-10-09) |
| ADR-06 | Existing MXroute for SMTP, IMAP and provisioning | OWNER-DECIDED (D-06) | inbox handling is deterministic code; provisioning interface NEEDS VERIFICATION |
| ADR-07 | Django admin plus focused Django views for staff | OWNER-DECIDED (D-07) | admin covers read and simple edits; workflow actions use focused views that call services |
| ADR-08 | Twenty deferred | OWNER-DECIDED (D-08) | |
| ADR-09 | LMS unchanged; proxy routes only assigned paths to Django; reversible cutover | OWNER-DECIDED (D-09) | see the routing sections above |
| ADR-10 | Staff interface on a separate hostname, network-restricted, MFA | OWNER-DECIDED design (D-12); hostname, method and package NEEDS VERIFICATION | see "Staff interface access (design)" above |
| ADR-11 | Development tooling never operates the live workflow; product jobs are application jobs | OWNER-DECIDED (D-10) | `009` section 6 |
| ADR-12 | Legacy behaviour enters only as sanitized evidence packets through `catalyst-legacy-analyst` | OWNER-DECIDED (D-11) | |
| ADR-13 | Stages change only through service functions that lock the application, check prerequisites inside the transaction and write a history event; no view, admin form or handler sets the stage field directly | PROPOSED | one place enforces REQ-008; admin stage fields are read-only |
| ADR-14 | Append-only protection for the **protected history tables** (submission versions, history events and any table the data design names as protected): privileges plus triggers, with three roles: migration owner, application, retention. Ordinary operational tables may still be updated through approved services; the database as a whole is **not** append-only. The application role neither inherits nor can assume owner or retention privileges; web and worker processes never use owner or superuser credentials. Privileged functions use a trusted `search_path` (`public, pg_temp`), schema-qualified objects and restricted permissions | **OWNER-DECIDED 2026-10-10** (D-17), from `012` proof 3. Least privilege is implemented when the schema task arrives (S1-T3) | **Retention:** the capability for a separately authorized, audited retention operation is approved; a default permission to delete real records is **not**. POL-10 stays open; no real retention or deletion is enabled until the policy and an operating authorization are approved. **Stated limitations kept:** the migration owner can disable the trigger; a superuser bypasses everything; migrations need review for trigger changes. If POL-10 requires redaction instead of deletion, that needs a second, separately audited operation. TEST-S1-21 covers privilege and trigger refusals; role non-inheritance, no owner or superuser credentials in web and worker, and the privileged-function `search_path` are checked when S1-T3 builds the roles. The decided form fixes TEST-S1-21 (trigger variant). **Implemented (S1-T3, PR #11):** trigger inventory of 8: `catalyst_append_only` on versions and events, `catalyst_no_truncate` on versions, events, the retention audit and adoptions, `catalyst_audit_immutable` on the audit and `catalyst_adoption_immutable` on adoptions (D-22: adoptions have no retention exception). **Runtime enforcement:** `config/runtime.py` holds the one role contract; the WSGI entry point declares itself `web` unconditionally and a `connection_created` receiver refuses an owner, retention or superuser connection before use, and closes the connection if the check itself fails (the worker will declare `worker`; any new entry point, such as an ASGI module, must declare its kind, because an undeclared process counts as `management` and is not enforced); `catalyst.E002` is the diagnostic form of the same contract. Tests run as the application role and reset with a test-only owner path (D-21) |
| ADR-15 | Every external effect is a pending action with an idempotency key; the provider is called outside any row-locking transaction; an unknown outcome becomes `uncertain` and is reconciled before retry, unless the action kind is declared redeliverable | PROPOSED overall. **Owner decision 2026-10-10 (D-20), S1 only:** the identical verification invitation may be redelivered to the local test sink after an interrupted attempt; this exception is not generalized to any other message or provider action kind | Redelivery being allowed does **not** mean an outcome can never be uncertain: S1 still represents and tests attempts, bounded recovery, lease fencing and interruption, and never duplicates the challenge, adoption or next-stage action. The generic pending-action design keeps the `uncertain` status and reconciliation hooks; provider-specific reconciliation (SMTP, Documenso, provisioning) is P2 or later, before real external actions are enabled |
| ADR-16 | Verification links carry the challenge's random public id signed with Django's `Signer` (dedicated salt and a dedicated key setting with fallback keys, independent of `SECRET_KEY`); expiry, use and supersession live only in the database; links are built from a `PUBLIC_BASE_URL` setting; GET shows a confirm button, POST confirms | PROPOSED; token contract **OWNER-DECIDED 2026-10-10** (D-24) | the same link can be resent after a crash (`004` J-03) without storing a raw token; one expiry authority; rotating the token key does not touch sessions or CSRF, and a retired key stays as a fallback for the longest challenge lifetime; POST defeats link prefetching **Token contract (D-24):** the raw challenge `public_id` alone never authorizes confirmation; a valid signature plus the database checks (expiry, use, supersession) are required. The signed value, the signature and the link are never shown or exported by staff views, logged, or stored in `ApplicationEvent`; staff see challenge status, issue time, expiry and completion only, and no staff action can mint a link. Implemented in S1-T6 |
| ADR-17 | Initial application baseline: **Python 3.14.8, Django 5.2.18 LTS, PostgreSQL 16.15, psycopg 3.3.6**, in an isolated project environment with reproducible, hash-locked dependencies and container images pinned by digest (a floating tag such as `postgres:16` is not a pin). No change to the system interpreter, existing applications or the production database | **OWNER-DECIDED 2026-10-10** (D-18), from `012` (all proofs passed on 3.14.8) | **Unverified at decision time:** pytest 9.1.1 and pytest-django 4.14.0 were reported, not run; 1B.1 must first show they install, load, collect and run a minimal PostgreSQL-backed check, and a material incompatibility is a blocker to resolve, not permission to change the Python line. The production host's PostgreSQL version is still unchecked (P6) |
| ADR-18 | A minimal custom user model, `accounts.User` subclassing `AbstractUser`, set as `AUTH_USER_MODEL` before the first migration. Applicants remain dossier records, not automatically created accounts; staff actor and reviewer references to users are permitted where the approved data design needs them. No custom authentication | **OWNER-DECIDED 2026-10-10** (D-19), from `012` proof 4 and the Django 5.2 documentation | established in S1-T2 before any migration is generated or run |
