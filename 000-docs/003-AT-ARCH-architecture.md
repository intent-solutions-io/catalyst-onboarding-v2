# Architecture: catalyst-onboarding-v2

> **Status: PRELIMINARY, subject to review.** This repository is in the architecture and planning
> phase. Nothing here is approved, implemented or deployed. The master blueprint, PRD, architecture
> and phased execution plan are being developed before any code is written.
>
> Documentation-first, Django-native Solution Catalyst onboarding platform for Intent Solutions

**Author:** Jeremy Longshore
**Date:** 2026-10-09
**Status:** Draft

## System Context

<!-- Where does this system fit in the broader ecosystem? -->

## Component Design

| Component | Responsibility |
|-----------|---------------|
| <!-- component --> | <!-- what it does --> |

## Data Flow

```text
[Input] → [Processing] → [Output]
```

<!-- Describe the primary data flow through the system -->

## Integration Points

| Endpoint/Service | Method | Purpose |
|-----------------|--------|---------|
| <!-- endpoint --> | <!-- GET/POST/etc --> | <!-- purpose --> |

## Security Model

- **Authentication:** <!-- method -->
- **Authorization:** <!-- method -->
- **Data Classification:** <!-- PII, confidential, public -->
- **Secrets Management:** <!-- env vars, vault, etc -->

## Error Handling

| Error | Code | Message | Recovery |
|-------|------|---------|----------|
| <!-- error --> | <!-- code --> | <!-- message --> | <!-- recovery --> |

## Performance

| Operation | Target | Max |
|-----------|--------|-----|
| <!-- operation --> | <!-- target latency --> | <!-- max latency --> |

## Infrastructure

- **Hosting:** <!-- cloud provider, service -->
- **CI/CD:** GitHub Actions
- **Monitoring:** <!-- tool -->
- **Logging:** <!-- tool -->

## Learn and Django routing (current routing verified read-only; v2 routing proposed)

**Status:** the **current** route table below was read from the live proxy configuration on
2026-10-09 in a read-only, owner-authorized check (no reload, no edit; internal addresses and ports
are deliberately omitted). Everything about **v2** is proposed; nothing for v2 is configured.

### Current live routing (verified 2026-10-09, read-only)

| Path | Served by | Notes |
|---|---|---|
| `/user/logon`, `/user/logon/` | proxy redirect (302) to `/request-access` | LMS self-registration is closed at the edge |
| `/start`, `/start/` (exact, case-sensitive) | static page from the proxy host | its own strict CSP and headers |
| `/request-access`, `/request-access/received`, `/signing/return` (exact, case-sensitive), and everything under `/setup/` | **first-generation** Catalyst onboarding service | exact-match rules, so `/request-access/` and `/setup` still reach the LMS; `/setup/...` requests are excluded from the access log because the path carries a token |
| `/u.js`, `/u/api/send` | the estate analytics service, same-origin | first-party analytics |
| everything else | the existing LMS | default route |

Access logs for the learn host are kept 30 days. The learn site block does **not** import the shared
security-headers snippet that the other hosts use; any HSTS, framing or referrer headers on LMS and
onboarding pages therefore come from the upstream applications (not verified here). Any v2 cutover
replaces the first-generation onboarding rules, not the LMS default.

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
- Existing routes are preserved until an approved cutover. The table above is the baseline any
  cutover is compared against.

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
