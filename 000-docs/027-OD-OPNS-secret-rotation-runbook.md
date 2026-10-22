# Secret rotation runbook

| Field | Value |
|---|---|
| Document | 027-OD-OPNS-secret-rotation-runbook |
| Status | Proposed 2026-10-22 (6B.10a); procedures adopted under P6-D-15 (D-49). The owner sets the routine intervals |
| Applies to | Staging now; the pilot and production use the same procedures with SOPS-held values (026 section 5) |
| Evidence | `tests/test_secret_rotation.py`; the webhook overlap in `tests/test_agreement_completion.py` |

Every Catalyst secret is a file, mounted read-only into the processes that need it (026 section 5; the staging
compose file). Rotating a secret means writing the new file and recreating the containers that mount it. No value
is ever typed into a shell history, pasted into chat or written into the repository.

## 1. Before any rotation

1. Record why: routine (an interval came due) or **leak** (the value may be known to someone else). A leak follows
   the leak column below, never the routine one.
2. Have the deploy state at hand: the serving image is recorded, and the stack passes
   `deploy/staging/adapters/smoke.sh`.
3. After the rotation, run the smoke again and keep its result with the rotation's record (date, class, reason,
   who, smoke result). No values in the record.

## 2. Per secret class

| Class | Mounted in | Routine rotation | Leak | What users notice |
|---|---|---|---|---|
| **Link-signing key** (`verification_key`, with `verification_fallback_keys`) | web, worker, migrate | 1. New key as `verification_key`, the old one as the only fallback. 2. Recreate web and worker. 3. After the longest link lifetime has passed (the larger of `CATALYST_CHALLENGE_LIFETIME_SECONDS` for confirmation links and `CATALYST_SETUP_LINK_SECONDS` for password and withdrawal links), remove the fallback and recreate again | 1. New key, **no fallback**; recreate. Every link signed with the leaked key fails at once. 2. Run `manage.py catalyst_close_links --confirm-database <name>` as the owner: it closes every outstanding link record and opens a staff item for each applicant left waiting. 3. Staff send fresh links from those items | Routine: nothing. Leak: applicants holding a link must be sent a new one (the staff items list them) |
| **Django secret key** (`secret_key`) | web, worker, fetcher, migrate | New file; recreate web, worker and fetcher | The same, at once | Every staff session ends; staff sign in again. Applicant links are not signed with it |
| **Database role passwords** (`app_password`, `fetcher_password`, `owner_password`, `backup_password`, `retention_password`, `admin_password`) | each role's own processes (the compose file's secret mounts) | 1. New file. 2. Run the provisioning step (`docker compose --profile provision run --rm provision-roles`), which sets each role's password from its file (hashed before it leaves the container). 3. Recreate the processes that log in as that role | The same, at once; for the admin bootstrap credential, also check the database log for logins you did not make | None after recreation |
| **Documenso webhook secrets** (pilot) | web (the webhook route, not mounted in staging) | Two secrets overlap: 1. add the new one beside the old; 2. switch Documenso to the new one; 3. remove the old | Remove the leaked one at once, add a new one, switch Documenso; deliveries signed with the leaked value are refused meanwhile | None |
| **Provider tokens and mail credentials** (pilot) | worker only | Rotate at the provider, then the file, then recreate the worker | The same, at once, and revoke the old value at the provider first | None after recreation |

## 3. Rules

- **A leaked key is never a fallback.** `catalyst_close_links` refuses while any fallback key is configured, so the
  procedure cannot be finished half-way.
- **One class at a time,** each with its own smoke and record, so a failure is attributable.
- **Intervals:** the owner sets them (P6-D-15). Until then, rotate on a leak, on any staff departure, and before
  the pilot's first real applicant.
- **Not covered here:** the TLS certificates (the proxy's own, internal in staging), the host's SOPS key, and
  two-factor devices (the owner's break-glass reset, 026 section 16, 6B.9).
