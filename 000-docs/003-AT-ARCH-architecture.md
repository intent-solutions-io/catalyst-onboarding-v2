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

## Learn and Django routing (proposed; current routing unverified)

**Status:** proposed topology. Nothing here is configured. The live proxy configuration was **not**
inspected for this document; the current route table must come from an approved record or a
separately authorized read-only operator check (proposal P5 in `009`).

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
- Existing routes are preserved until an approved cutover. The available records about today's
  routing are inconsistent, so the current route table is treated as unverified.

### Route-ownership matrix (proposed)

| Path and method | Owning app | Upstream | Authentication | Cookies / CSRF | Static assets | Sensitive files | Failure behaviour | Cutover and rollback |
|---|---|---|---|---|---|---|---|---|
| everything not listed below, all methods | LMS | LMS service | LMS | LMS cookies | LMS | none from Catalyst | LMS error pages | unchanged |
| `/request-access` and its received page, GET and POST | Catalyst v2 | Django web | none (public form) with abuse controls | Django CSRF; cookie name and path scoped to avoid collision with LMS cookies | Django static under a Catalyst-specific prefix | none | Catalyst error page, no LMS fallback | switch the `handle` target; rollback restores the previous target |
| email-confirmation and signing-return paths, GET | Catalyst v2 | Django web | one-time tokens | no state change on GET | as above | none | as above | as above |
| staff interface (Django admin and focused views) | Catalyst v2 | Django web | Django auth, staff groups | Django session and CSRF | as above | dossier views only through authorized views | deny by default | **separate restricted staff hostname proposed** (see below) |
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
