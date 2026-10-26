# Secret rotation runbook

| Field | Value |
|---|---|
| Document | 027-OD-OPNS-secret-rotation-runbook |
| Status | Proposed 2026-10-22 (6B.10a); procedures adopted under P6-D-15 (D-49). The owner sets the routine intervals |
| Applies to | Staging now; the pilot and production use the same procedures with SOPS-held values (026 section 5) |
| Evidence | `tests/test_secret_rotation.py`; the webhook overlap in `tests/test_agreement_completion.py`. Each row below says whether its procedure is tested |

Every Catalyst secret is a file, mounted read-only into the processes that need it (026 section 5; the staging
compose file, `deploy/staging/compose.yaml`). Rotating a secret means writing the new file and recreating the
containers that mount it. No value is ever typed into a shell history, pasted into chat or written into the
repository.

## 1. Before any rotation

1. Record why: routine (an interval came due) or **leak** (the value may be known to someone else). A leak follows
   the leak column below, never the routine one.
2. Have the deploy state at hand: the serving image is recorded, and the stack passes
   `deploy/staging/adapters/smoke.sh`.
3. After the rotation, run the smoke again and keep its result with the rotation's record (date, class, reason,
   who, smoke result). No values in the record.

## 2. Per secret class

**Link-signing key** (`verification_key`, with `verification_fallback_keys`; mounted in web, worker and migrate).
Only confirmation links are signed with it. Password-setup and withdrawal links are random tokens the database
stores as hashes, so this key does not affect them.

- **Routine** (tested):
  1. Put the current key into `verification_fallback_keys` and the new key into `verification_key`.
  2. Recreate web and worker. New links are signed with the new key; links already sent still open.
  3. After `CATALYST_CHALLENGE_LIFETIME_SECONDS` has passed (the confirmation link's lifetime), empty
     `verification_fallback_keys` and recreate again.
- **Leak** (tested):
  1. Put the new key into `verification_key`, leave `verification_fallback_keys` **empty**, and recreate web, worker
     and migrate. Every confirmation link signed with the leaked key now fails.
  2. Close the records behind those links, naming the leaked key by its digest, never its value:

     ```bash
     digest="$(tr -d '\n' < <old key file> | sha256sum | cut -d' ' -f1)"
     docker compose run --rm --no-deps migrate python manage.py catalyst_close_links \
       --confirm-database catalyst --leaked-key-sha256 "$digest"
     ```

     The command refuses while the leaked key is still the link key or any fallback key, so step 1 must come
     first. It closes every outstanding confirmation link and opens a staff item for each applicant left waiting.
  3. Staff send fresh links from those items (`rotation_confirmation_link_closed`).
- **What users notice:** routine, nothing. After a leak, applicants who had not yet confirmed must use the fresh link
  staff send them.

**Django secret key** (`secret_key`; mounted in web, worker, fetcher and migrate). It signs staff sessions only.

- **Routine and leak** (tested): write the new file and recreate web, worker and fetcher.
- **What users notice:** every staff session ends; staff sign in again (and, outside test and development, use their
  second factor again). Applicant links are not signed with it.

**Database role passwords** for the application, fetcher, owner, backup and retention roles (each mounted only in its
role's processes, as `db_password` or by its own name).

- **Routine and leak** (tested for one role, the same code path for all five):
  1. Write the new file.
  2. Run the provisioning step: `docker compose --profile provision run --rm provision-roles`. It sets each role's
     password from its file, hashed before it leaves the container.
  3. Recreate the processes that log in as that role.
- **What users notice:** between steps 2 and 3, new connections from those processes fail. Run steps 2 and 3
  together. Existing connections continue.

**The bootstrap administrator's password** (`admin_password`; mounted in the database and the provisioning step).
The provisioning step logs in with this password, so it cannot change it.

- **Routine and leak** (a procedure, not yet tested):
  1. Open a session on the database container's local socket:
     `docker compose exec db psql -U catalyst_admin -d catalyst`.
  2. Set the new value with `\password catalyst_admin`, which prompts and keeps it out of the shell history.
  3. Write the same value to `admin_password`.
  4. Run the provisioning step once to prove the new password works.
- **On a leak:** also read the database's connection log for administrator logins you did not make.

**Documenso webhook secrets** (pilot; web only, on a route not mounted in staging). The settings accept two secrets.

- **Routine:** add the new secret beside the old one; switch Documenso to the new one; remove the old one.
- **Leak:** remove the leaked secret at once, add a new one, and switch Documenso. Deliveries signed with the leaked
  secret are refused meanwhile.
- **Status:** that both secrets authenticate is tested (`test_agreement_completion.py`). Removing the old one is a
  settings change, not yet tested. The file path for these secrets is part of the pilot's guard amendment (P6-D-6).

**Provider tokens and mail credentials** (pilot; worker only). They are not configured in staging: the guards refuse
provider variables until P6-D-6.

- **Routine:** rotate at the provider, then the file, then recreate the worker.
- **Leak:** revoke the old value at the provider first.
- **Status:** a procedure, not tested until the pilot.

**Custody wrapping key** (`custody_wrapping_key`, 9kg.34; mounted in web and worker and the owner-run custody
commands; its escrow copy in the operator's encrypted secret store). It wraps every per-document data key. A rotation
is also the only way to retire a remnant of an erased document's wrapped key (a snapshot, unlinked blocks, an archive
or an off-site copy): after the old wrapping key is destroyed, no key opens the remnant.

- **Routine and leak** (tested, `tests/test_custody_rotation.py`, 9kg.69):
  1. Stop web and worker. Retrieval and sealing pause for the run.
  2. Generate the next key (32 random bytes, 64 lower-case hex). Mount it for this run only as
     `custody_next_wrapping_key`, beside the current `custody_wrapping_key`. Every other process refuses to start
     holding it.
  3. Run `catalyst_custody_keys --rotate --expect-head <the last head from the private operations record>`. It
     finishes every journaled destruction, rewraps every live key in both directories, and opens every live document
     under the next key. Only then does it journal `custody_rotation` `done`. It prints `from_key` and `to_key` (key ids,
     never keys). If it is interrupted, run the same command again: every copy is under one of the two keys, and both
     are still held. If it refuses with `key_needs_recovery`, run `--recover` first.
  4. Make the next key the current one: write it to `custody_wrapping_key` and to the escrow, then remove
     `custody_next_wrapping_key`. Start web and worker, and check one retrieval.
  5. Destroy the old key everywhere: its secret file and its escrow copy.
  6. Run `catalyst_custody_keys --retire-old-key <from_key> --expect-head <head>`. It refuses unless that rotation
     was journaled done, and while any key file is still under the old key, a destroyed key's file remains, or a
     stray file is in a key directory. Then it journals the retirement, which is your attestation that the old key
     is destroyed.
- **A key directory lost during a rotation:** `--recover` holds one wrapping key, so it copies only the copies that
  key opens and reports the rest as unrecoverable. Run `--recover` once with the old key current, then once with the
  next key as the current key, and then run the rotation again.
- **Interval:** the owner's (211.7.9), and immediately after a suspected leak of the wrapping key or of a key
  directory.
- **What users notice:** document retrieval is unavailable while web is stopped (step 1 to step 4). A rotation that
  finds a key being created or destroyed refuses (`custody_operation_in_progress`); run it again.
- **Not covered by code:** destroying the old key's escrow copy and any copy outside the host. That is the owner's
  act, recorded by step 6.

## 3. Rules

- **A leaked key is never a fallback.** `catalyst_close_links` refuses while the leaked key is the link key or any
  fallback key, so the leak procedure cannot be finished half-way or in the wrong order.
- **One class at a time,** each with its own smoke and record, so a failure is attributable.
- **Intervals:** the owner sets them (P6-D-15). Until then, rotate on a leak, on any staff departure, and before
  the pilot's first real applicant.
- **Not covered here:** the TLS certificates (the proxy's own, internal in staging), the host's SOPS key, two-factor
  devices (the owner's break-glass reset, 026 section 16, 6B.9), and a leak of the database itself. A database leak
  exposes the password-setup and withdrawal link hashes, and is an incident, not a rotation.
