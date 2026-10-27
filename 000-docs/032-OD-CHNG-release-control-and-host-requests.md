# Internal launch: release-control and host requests

| Field | Value |
|---|---|
| Document | `032-OD-CHNG-release-control-and-host-requests` |
| Version | 0.1.0 (draft, 2026-10-26) |
| Status | **PROPOSED.** Three change requests for the owner. Writing them authorizes nothing. The GitHub protections are executed by the owner's own hand (`030` Q7, Q9); the preflight and host preparation each run only under the owner's recorded host go (`030` Q9). No agent session runs any step marked "owner". |
| Owner | Jeremy Longshore |
| Beads | `9kg.35`, `9kg.36` (release control); `9kg.42` (read-only host preflight); `9kg.28` (host preparation); related: `9kg.25` (PR #103, merged as `e9193db`), `9kg.60` (PR #106, `7aed4ac`), `9kg.69` (PR #104, `0691e02`), `9kg.70` (PR #105, `4fc527a`), `9kg.72` (PR #107, `0211ce9`), `9kg.31.11` (open) |
| Inputs | `009` sections 2, 5.5 and 8; `026` sections 3 to 9 and 16; `027`; `029` sections 6, 7, 12 and 13; `030` Q1, Q7, Q9, Q10; `scripts/apply-github-protections.sh`; `scripts/host-preflight-read.sh`; `.github/workflows/`; `deploy/staging/compose.yaml`; code at `main` `2a19730` |
| Companion | `031` (the owner decision package; its section 8 lists the conflicts these requests depend on) |
| Classification | Public repository. Secrets by name only, never values. No host name, address, private path or named holder: those live in the private operations record. |

## 1. Release control (`9kg.35`, `9kg.36`)

### 1.1 What the protections are for

Nothing reaches `main` without a pull request and the exact required checks, and no deploy credential exists outside
the protected `release` environment. The protections land before any deploy credential is created (D-49, P6-D-5;
`030` Q7).

**The merge guard is not server-side enforcement.** `safe-merge` runs on the owner's machine. It refuses a merge
unless every registered check passed on the exact head, but it binds only someone who uses it. Today anyone with
write access can push to `main` or merge without checks (`009` section 5.5, readback of 2026-10-18; `9kg.35` readback
of 2026-10-23). Only a GitHub ruleset and a protected environment are enforced by GitHub itself.

### 1.2 The intended controls

: The intended GitHub controls, from `9kg.35`, `9kg.36`, `009` section 5.5, `026` section 9 and `030` Q7.

| Control | Intended value | Source |
|---|---|---|
| Ruleset on `refs/heads/main` | name `main-protections`, enforcement active, **empty bypass list** | `9kg.35`; the script |
| Pull request required | yes; 0 approving reviews (one maintainer: a required approval would deadlock); stale reviews dismissed | `9kg.35`; `029` section 16 |
| Required status checks | "Markdown lint and doc index check" and "Runtime checks (Python 3.14.8, PostgreSQL 16.15)", both pinned to the GitHub Actions app; strict (up to date with `main`) | `9kg.35`; the script |
| The image scan in the required contract | "Build and scan the image" added as a third required check (fixable high and critical fail; D-K) | `9kg.36`; the script's `--with-scan` |
| Linear history | yes (merges are squash merges) | `9kg.35` |
| Force-push and deletion of `main` | refused | `9kg.35` |
| `release` environment | deployments from `main` only; the owner as required reviewer, recorded as not independent; self-review allowed; a wait timer; administrators cannot bypass | `9kg.35`; the script |
| Deploy credential trust | bound to the `release` environment claim and the `main` ref; created only after the readback passes | `9kg.35` acceptance; `026` section 9 |
| Merge-guard registration | names every required check (two, then three with the scan) | `9kg.35`; kept outside this repository |
| Agent sessions | a scoped token: contents, pull requests and checks; no administration, environment approval, secrets or Actions variables | `030` Q7 sub-decision 1 |
| Change control | a ruleset change raises an alert and needs a record within a day; an emergency bypass procedure is recorded in `009` section 5.5 | `9kg.35` acceptance |
| Repository move (`9kg.4`) | after the launch's observation period or never; every readback repeated after a move or a visibility change | `030` Q7 sub-decision 2 |

### 1.3 Owner-run actions, in order

Preconditions: the owner's own GitHub credentials in the owner's own terminal; no agent session holds owner
credentials at the time; no deploy credential exists yet. **Not met today:** the token this repository's agent
sessions use on the dev box has administrator permission (readback, section 1.8). Step 4's token swap must therefore
come first, or the owner runs steps 1 to 3 while no agent session is running.

1. **Dry run.** `EXPECTED_LOGIN=<owner login> scripts/apply-github-protections.sh`. It prints the identity, the admin
   right, the current state and the ruleset and environment it would send. Nothing is changed.
2. **Apply.** `EXPECTED_LOGIN=<owner login> scripts/apply-github-protections.sh --apply`. It creates or updates the
   ruleset, upserts the environment and its `main` branch policy, reads back and asserts: bypass actors 0, enforcement
   active, the required checks exactly as intended, the deployment branch policy exactly `main`, and the five rule
   types effective on `main`. A failed assertion exits non-zero: fix before anything else.
3. **The merge-guard registration** (outside this repository): name both required checks. Confirm with
   `safe-merge --dry-run` on the probe pull request of section 1.6.
4. **The scoped agent token.** Issue it with the permission set of section 1.2 and switch every agent session to it.
   From this point no agent session holds owner credentials (`030` Q7).
5. **The probes** of section 1.6.
6. **The image scan (`9kg.36`).** After the probes pass: re-run step 2 with `--with-scan`, then add "Build and scan the
   image" to the merge-guard registration. The image workflow has no path filter, so the job reports on every pull
   request, docs-only included (`009` section 5.5's rule). Run probe P6, then probe P7.
7. **Record.** Paste the readback into section 1.8 and, through a docs pull request, into `009` section 5.5 with the
   emergency-bypass procedure; update the header comment of `.github/workflows/image.yml`, which still says "Not a
   required check".

### 1.4 Effective-rule readback (read-only)

Each line is a read. `REPO` is `intent-solutions-io/catalyst-onboarding-v2`.

: Readback commands and the expected answer.

| # | Read | Expected |
|---|---|---|
| R1 | `gh api repos/$REPO/rulesets` | one ruleset, `main-protections` |
| R2 | `gh api repos/$REPO/rulesets/<id>` (the full object; the list omits `bypass_actors`) | enforcement `active`; `bypass_actors` an empty array; `current_user_can_bypass` not `always`; include `refs/heads/main`; rules deletion, non_fast_forward, required_linear_history, pull_request (0 approvals), required_status_checks (strict, each check with the Actions app's integration id) |
| R3 | `gh api repos/$REPO/rules/branches/main` | the same five rule types in effect, including any organization ruleset that applies |
| R4 | `gh api orgs/intent-solutions-io/rulesets` | the organization's rulesets; needs the `admin:org` scope; if unreadable, record "NOT RUN (scope)" |
| R5 | `gh api repos/$REPO/branches/main/protection` | 404 (classic branch protection is not used; the ruleset is the control) |
| R6 | `gh api repos/$REPO/environments` and `.../environments/release` | `release` present; protection rules include required reviewers (the owner) and the wait timer; administrators cannot bypass; a custom branch policy |
| R7 | `gh api repos/$REPO/environments/release/deployment-branch-policies` | exactly one policy, `main`, of type branch |
| R8 | `gh api repos/$REPO/actions/secrets` and `.../environments/release/secrets` (names only) | no deploy credential yet; any name present is explained in the record |
| R9 | `gh api repos/$REPO/actions/permissions/workflow` | default workflow token read-only; workflows cannot approve pull requests |
| R10 | `gh api repos/$REPO/collaborators --jq '.[].role_name'` | one administrator; everyone else read-only (logins stay in the private record) |
| R11 | Under the agent session's token: `gh api repos/$REPO --jq .permissions` | `admin` false, `maintain` false |
| R12 | The token settings page (the owner, by eye) | the scoped permission set; record the token's expiry, not its value |
| R13 | The merge-guard registration file (the owner) | every required check named |

### 1.5 Bypass review

Answer each with yes or no, and a note, in section 1.8.

1. Is the ruleset's bypass list empty, and does `current_user_can_bypass` read anything other than `always` for the
   owner?
2. Do any organization rulesets or organization-level bypass actors apply to this repository (R3, R4)?
3. Can administrators bypass the `release` environment's reviewer rule (`can_admins_bypass` false)?
4. Are there any other environments, deploy keys, or repository or environment secrets that could deploy?
5. Does any workflow use `pull_request_target`, a self-hosted runner, or a token with write rights on untrusted
   heads (`009` section 5.5)?
6. Who besides the owner holds write, maintain or admin access?
7. Residuals, stated and accepted, not fixed by any setting:
   - The required checks are pinned to the GitHub Actions app, not to a workflow file. A pull request that edits a
     workflow can emit a job with the same name. Accepted with one maintainer, reviewed at merge.
   - The owner, as administrator, can edit or disable the ruleset. Only change control (an alert and a record) can
     catch that. **No ruleset-change alert exists yet** (missing; see section 1.7).
   - The environment reviewer is the same person who merges; the force-command on the host, which takes the commit
     and digest from the owner's recorded go, is the real second key (`9kg.35` notes).
   - Rulesets and environment reviewers lapse if the repository becomes private on the current plan.

### 1.6 Refusal probes (owner-run)

Each probe has an expected refusal and a stop rule. A probe that is not run is reported NOT RUN, never PASS.

| # | Probe | Expected | If not refused |
|---|---|---|---|
| P0 | `safe-merge --dry-run` on a draft probe pull request whose checks are still running | refused (client-side) | the guard registration is wrong: fix it before going on |
| P1 | `gh pr merge <probe> --squash` while its checks are pending | refused by GitHub: required status checks | close the probe, re-read R2 and R3 |
| P2 | `gh pr merge <probe> --squash --admin` | refused: the bypass list is empty | the ruleset is not in force for the owner: stop, re-apply, re-read |
| P3 | An empty commit pushed directly: `git commit --allow-empty -m "probe: direct push must be refused"` then `git push origin HEAD:main` | refused: changes must go through a pull request | the empty commit is harmless; leave it, record the failure, fix the ruleset; no force-push to remove it |
| P4 | A force-push: record `main`'s head first, then push a sibling of it with `--force-with-lease` | refused: non-fast-forward | restore at once by pushing the recorded head, then fix. The owner may skip P4 and rely on R2 and R3; record it as NOT RUN |
| P5 | On a throwaway branch, a push-triggered probe workflow with one no-op job that names `environment: release` | the job is rejected by the environment's branch policy before any step; no secret is read | stop: the environment does not restrict deployments to `main`. (Dispatching `release.yml` from a branch proves nothing here: its own `if` skips the job before the environment is evaluated.) |
| P6 | (`9kg.36`) A draft pull request that adds one package version with a known, fixable high finding to the production image | "Build and scan the image" fails; P1 and `safe-merge` both refuse | the scan is not in the contract: re-run step 6 of section 1.3 |
| P7 | (`9kg.36`) A docs-only pull request | every required check reports, the scan included | a required check that does not report would block every docs pull request: fix the workflow trigger |

Clean-up: close every probe pull request unmerged and delete the probe branches (the owner's own act).

### 1.7 Gaps this request does not close

- **No ruleset-change alert.** `9kg.35`'s acceptance asks for one; nothing builds it. Smallest form: a scheduled,
  read-only workflow that re-runs R2, R3 and R7 and fails, alerting through the existing notification path, on any
  difference from the recorded readback.
- **No deploy workflow and no deploy credential exist yet.** The trust binding in section 1.2 is a readback item for
  host preparation (section 3), after the protections. No bead names the deploy workflow; it belongs with `9kg.28` (the
  force-command) or `9kg.31.4` (release preparation).
- **The emergency-bypass procedure** is not written in `009` section 5.5 yet.

### 1.8 Current readback (2026-10-26)

Read back on 2026-10-26 by the main session with `gh api`, read-only. The token has repository admin permission;
nothing was applied.

| Read | Result |
|---|---|
| Rulesets on the repository | none (`[]`) |
| Branch protection on `main` | none (HTTP 404, "Branch not protected") |
| Rules in effect on `main` | none (`[]`) |
| Environments | none (so no `release` environment and no reviewer rule) |
| `delete_branch_on_merge` | true |
| The merge guard's registration on the dev box | required checks "Markdown lint and doc index check" and "Runtime checks (Python 3.14.8, PostgreSQL 16.15)"; `safe-merge` also requires every check observed on the head, so "Build and scan the image" is enforced only while it posts |

The bypass review and the refusal probes: **NOT RUN.** They need the protections to exist (the owner-run steps
above). Until then, nothing on GitHub refuses a direct push or merge to `main` by anyone with write access.
`safe-merge` is a client-side discipline of this dev box, not server-side enforcement. `9kg.35` and `9kg.36` stay open
at their boundary: `9kg.35` before any deploy credential exists and before host preparation (C; `9kg.28` depends on
it); `9kg.36` before the release preparation (`9kg.31.4` depends on it).

## 2. Host preflight request (`9kg.42`)

### 2.1 The request

- **What.** One bounded, read-only inventory of the production host before anything is written there. Its record
  answers each item or marks it UNKNOWN.
- **Authority.** The owner's recorded host go (`030` Q9). D-50 excluded reading Learn's live proxy configuration
  without one; a council cannot lift an owner's exclusion. The go is one line covering `9kg.42`, `9kg.28`,
  `9kg.31.5`, the production restore drill and `dy7.3`, with the legacy evidence packet `dy7.4` as a separately
  receipted read in the same window.
- **Tool.** `scripts/host-preflight-read.sh <ssh alias>`: fixed read-only commands, addresses masked, the record
  written outside any git work tree with mode 600, only its hash shown.
- **Evidence.** The record stays in the private operations record. The repository gets its hash, cited in `026`
  section 16, and logical identifiers only.
- **Never read.** A secret's value, an environment file, a database row, mailbox contents, log lines (names and sizes
  only), or the first-generation service's data.
- **Abort.** Stop on any prompt for a password, any command that would write, or any output that shows a secret value
  or personal data; record the item as UNKNOWN and say why.

### 2.2 The inventory

: Preflight items, the read-only command class, and whether the script covers each today.

| # | Item | Read-only command class | Answers | Script today |
|---|---|---|---|---|
| H1 | Kernel, load, memory and disk headroom on the data root | system state reads | capacity for a second stack | yes |
| H2 | Ownership and mode of the data root's top level | file metadata | where the v2 stack's directories can go | yes |
| H3 | Containers, images, published ports, compose projects | container listing | isolation; the first-generation service's footprint; the one-writer rule | yes |
| H4 | Listening ports and owning process names | socket listing | free ports for v2 (checked against the estate inventory) | yes (ports); the inventory comparison is manual |
| H5 | Timers and operator cron entries (names and command paths only) | service and timer listing | the first-generation service's timers (U12, partly) | yes |
| H6 | The proxy configuration's hash and size; site block host names | file hash; pattern match | the baseline hash for "byte-untouched" | yes |
| H7 | The learning site's routing directives (allow-listed directive names only) | parse without validation | R1 and R2 collisions with v2's private paths (U2, `029` section 4.6) | yes |
| H8 | The adapted configuration's hash | parse without validation | a second baseline independent of formatting | yes |
| H9 | Installed proxy modules (rate limit, log filters, auth) | module listing | the outer rate-limit layer and the token log filter (U10) | yes |
| H10 | Proxy log files (names, sizes, modes) | file metadata | where the token filter must apply | yes |
| H11 | Certificates on disk (names and dates) | file metadata | certificate state; the new host name's certificate | yes |
| H12 | Secrets directory (names, modes, owners; never contents) | file metadata | the layout the v2 secrets join | yes |
| H13 | PostgreSQL services and role names and attributes | service listing; catalog read | isolation from the first-generation database | yes |
| H14 | Backup fabric paths and exclusions | file metadata; pattern match | whether the archive excludes secrets and must exclude the key volumes (U10) | yes (exclusions only) |
| H15 | Alert floor present | file metadata | the notification path for v2's alerts | yes |
| H16 | Staff private path on the proxy (count of matching lines) | pattern match | whether a staff path pattern already exists | yes |
| H17 | SSH authentication methods; firewall defaults and rule count | configuration readback | the host's access posture | yes |
| H18 | The first-generation service's deployed revision, schema state and flag state | its readiness endpoint (status only); container label and image digest reads | U1, the ownership register `dy7.2` | **no** |
| H19 | The first-generation completion gate's webhook route, secret name and allow-list; the countersign sweep's configuration names (no values) | file metadata and name-only pattern match | U3, U4 (whether either could act on a v2 envelope) | **no** |
| H20 | Whether the archive uses an include list or an exclude list; whether container volume storage is archived wholesale | configuration readback (names only) | whether a key volume could be swept into an archive (`9kg.28` note, item 1) | **no** |
| H21 | Swap state and the core-dump setting | system state reads | the custody processes' host conditions (`9kg.34`) | **no** |
| H22 | Block devices and mounts under the data root (names and sizes) | device listing | whether a second device exists for the key mirror (`031` section 3) | **no** |
| H23 | Provider-side machine snapshots or images | the provider's console or API, read-only, by the owner | whether a point-in-time copy of the host could hold a key | **no** (owner read) |
| H24 | The dedicated v2 host name's DNS state | DNS lookup | whether the name exists and where it points before `9kg.28` adds it | **no** |
| H25 | Any automatic image updater on the host and its scope | container label reads | that it will not manage the v2 stack | **no** |
| H26 | The staff device model (tailnet ACL tags, names only) | the tailnet's admin read, by the owner | the named-device restriction (P6-D-3) | **no** (owner read) |

**Before the go (repo-only, covered by the council's "preparing every later go"):** extend the script with H18 to H22,
H24 and H25 so the host is read once. H23 and H26 stay owner reads at their consoles.

## 3. Host preparation request (`9kg.28`)

### 3.1 Preconditions

Host preparation starts only when all of these hold:

1. The preflight record exists and its hash is cited (`9kg.42`).
2. The coexistence decision is recorded as final on the preflight's evidence (`211.7.3`), and the staff devices and
   holders are recorded privately (`211.7.5`).
3. The protections' readback passed and the scoped agent token is in force (section 1).
4. **Repository work:** a production stack definition and a reviewed release that admits `production` (`031`
   section 8, item 3), bead `9kg.31.11`. Built 2026-10-27 (`026` section 18): production is admitted with every live
   refusal, and `deploy/production/compose.yaml` is the staging definition with reviewed inputs only. Its provider
   settings (Documenso, MXroute) still need a guard amendment before their canaries, and the three Django-mailer
   mails need their live path (`9kg.77`) before real intake.
5. Values the configuration needs before start-up: the challenge lifetime (required at start-up), the custody rows
   (`031` section 3) for the custody mounts, and the erasure registry before the first production backup (`031`
   section 8, item 1).

### 3.2 Services

Each service mounts only what it needs. "Never" is enforced by the guards and repeated here as a host rule.

: Production services, their database login, secrets by name, mounts and networks.

| Service | Kind | Database login | Secret files (by name) | Mounts | Networks | Never |
|---|---|---|---|---|---|---|
| `db` | service | administrator (bootstrap) | `admin_password` | the database data directory, outside every archive source root (P6-D-8 exception record) | backend (internal) | a published port |
| `provision-roles` | one-shot, owner-run | administrator | `admin_password` and every role password | none | backend | running at deploy time |
| `migrate` | one-shot, per deploy | owner | `owner_password`, `secret_key`, `verification_key`, `verification_fallback_keys` | the effect journal (read-write) | backend | the wrapping key |
| `web` | service | application | `app_password`, `secret_key`, `verification_key`, `verification_fallback_keys`, `custody_wrapping_key` (retrieval), the Documenso webhook secrets (after the guard amendment) | the unix socket directory, the effect journal, custody, the key directory and the mirror | backend | the erasure key, the owner, retention, backup or admin passwords, the mail password, the provider tokens |
| `worker` | service | application | `app_password`, `secret_key`, `verification_key`, `verification_fallback_keys`, `mail_password`, `custody_wrapping_key`, the Documenso API token (after the guard amendment) | mail state, the effect journal, custody, the key directory and the mirror | backend; egress to the mail host and Documenso only | the erasure key; the provisioning credential; a model key |
| `fetcher` | service | fetcher | `fetcher_password`, `secret_key` | none (it names a journal path that does not exist) | backend; fetch (to the egress proxy only) | any provider secret, custody, keys or journal |
| `egress` | service | none | none | the deny-list directory, read-only | fetch; egress | anything else |
| `backup` | timer and on demand | backup | `backup_password` (and the keys the staging definition gives it) | the host's logical-dump directory (output), custody read-only, the effect journal read-only | backend | the wrapping key, the erasure key, a key directory (the command refuses all three) |
| `restore` | owner-run | owner and administrator; the post-restore step as the `reconcile` kind | `owner_password`, `admin_password`, `secret_key`, verification keys; `mail_password` for the IMAP Sent read only (RD-1 default, never SMTP); `erasure_key` **for the lift only** (PR #103 brief; see 3.5) | custody (read-write), the effect journal, the key directory and the mirror (the lift's sweep) | backend; IMAP to the mail host only | the wrapping key (the post-restore step refuses it) |
| `erase` (new) | owner-run | retention | `retention_password`, `erasure_key` | the effect journal (read-write), the key directory and the mirror (key destruction), custody read-only (the lingering-plaintext check) | backend only | the wrapping key, the fetch and egress networks, any mail or provider secret |
| `custody` (new one-shot) | owner-run | owner (as the restore drill runs it) | `owner_password`, `custody_wrapping_key`; `erasure_key` for `--recover` only | custody, the key directory and the mirror, the effect journal | backend | running beside the worker for `--migrate` or `--reap-orphans` |
| proxy | the host's existing proxy | none | none | a new site block for the dedicated v2 host name; the staff host site restricted to named devices; the webhook site (POST only) when the Documenso canary needs it | edge | any change to the learning site's block |

Not on the host at all (fixed rules): the mail-host provisioning credential (D-F, `030` Q5); any model provider key
(model advice off).

### 3.3 Volumes and mounts

- **Database data:** under the managed data root, outside every archive source root, with the P6-D-8 exception
  record.
- **Custody:** a volume the restore writes into; sealed files only after `--migrate` (none at first).
- **Key directory and key mirror:** two volumes on different devices where the preflight shows a second device
  (H22); 0700, owned by the process user; provisioned once with `catalyst_custody_keys --provision`; never in any
  archive, snapshot or versioned copy; mounted only into web, worker, `erase`, `restore` and the custody one-shot.
- **Effect journal:** an external volume that `compose down -v` cannot remove; append-only attribute set by the
  operator and lifted only for the owner's repair; mounted read-write by web, worker, migrate, restore and `erase`,
  read-only by backup. The host archive copies it (it is the restore's evidence); it holds no key.
- **Backups output:** the host's logical-dump directory that the estate's nightly archive and off-site legs already
  cover; root-owned 0700.
- **Mail state, the run socket, static files:** as in the staging definition.
- **Egress deny list:** a root-owned directory outside the repository, read-only into `egress` only; an empty list
  refuses every fetch, which is the intended state while fetching is disabled.

### 3.4 Network restrictions

- The backend and fetch networks are internal. Only `egress` and the worker leave the host; the worker only to the mail
  host and Documenso, by the mail-host allow-list (`CATALYST_MAIL_ALLOWED_HOSTS`) and the provider settings. In the production definition (`9kg.79`) the worker's route is the `mail` network,
  which it shares only with the owner-run `post-restore` service (the IMAP Sent read); `restore`, which holds the
  administrator password, has none. The host firewall limits that network to the mail host.
- The web process listens on a unix socket only, mode 0660, the proxy's group. No TCP port is published for web,
  database or the staff site.
- The staff host is reachable only from the named staff devices (tailnet tags, P6-D-3), with two-factor.
- The webhook site accepts POST only, with the body cap and uniform answers (P6-D-4); it is exposed only for the
  Documenso canary, with invitation mode on and every activation held (`9kg.31.5` notes).
- `erase`, `custody`, `backup` and `restore` have no route from any proxy.

### 3.5 Backup and restore wiring

1. **Scheduled backup** before the estate's nightly archive, plus an on-demand pre-deploy backup bound to the deploy
   operation (`9kg.37`). Receipts carry names, digests, versions and timings; a failed receipt step alerts through the
   alert floor. `forward-only.json` is in the set. In production the backup **refuses while the erasure registry is
   undecided**; until POL-10 is recorded, a scheduled run will fail and alert every night (`031` section 8, item 1).
2. **Restore** into an unused, migrated database, with `--expect-manifest-sha256` mandatory (default yes, `9kg.28`).
   The restore writes the hold.
3. **Replay (PR #103, merged as `e9193db`):** the `erase` service runs `catalyst_erasure_replay --expect-head <the last
   off-host head>` as the retention login. It re-erases every recorded person through the hold-only replay function and
   appends the mac'd `erasures_replayed` marker.
4. **Review and lift:** `catalyst_post_restore` (no erasure key) requires the marker for the review; the lift requires
   it again with the erasure key, runs the custody sweep and refuses while any effect item is open. Workflow migration
   0006 (PR #103) refuses application-role inserts of the restore hold. The drill passes the erasure key to the lift
   calls only (`scripts/restore_drill.sh`).
5. **The custody keys are never restored.** A restore brings back rows and sealed files only; a destroyed key stays
   destroyed.
6. **The journal off the host** (`9kg.60`, merged as PR #106): a provisioned destination (`catalyst_journal_ship --provision`,
   once), a timer running `catalyst_journal_ship --to <destination>` every few minutes and immediately before each
   backup, `CATALYST_JOURNAL_SHIP_LAG_SECONDS` set to the owner's RPO (`211.7.2`), and every restore run with
   `--shipped-from <destination>`. The destination, cadence and value are INPUTS. Until the host wires it, the
   owner copies the head and the person's entries to the off-host private store after every erasure, handoff and
   restore.

**Erasure key on the restore service (settled):** the restore service holds the erasure key for the lift only; the
review runs without it (PR #103 as merged; the `9kg.28` bead carries the correction).

### 3.6 Timers and monitoring

- The health timer every five minutes and the liveness sweep, with OnFailure surfacing exit 3; the backup-freshness
  and restore-drill-overdue signals; codes only in alerts.
- The custody health part (`9kg.70`, merged as PR #105) in the existing health timer: every condition pages under its own code,
  a missing mirror copy included (`recovery_incomplete`); verify one custody code through the host timer to Buzz.
  It is merged; until the host timer runs it, nothing pages a custody fault.
- A scheduled proof that the key volumes are absent from the newest host archive, the dev-box replica and the
  off-site listing (`9kg.28` note, item 4). PROVISIONAL (D-51 pattern): a precondition of completing `9kg.28` and of the
  Documenso canary.
- With POL-16: whether `provisioning_revocation_needs_staff` moves to the routine set (moot while provisioning is
  disabled).

### 3.7 What is preserved

- The learning site's proxy block, byte for byte: its hash before the change, after the new site block, and after the
  reload must match the preflight's (H6, H8). Edits follow the estate procedure: validate, then reload, never restart.
- Every first-generation container, timer, port, mailbox poller, webhook target, secret file and database.
- The estate's other stacks, the archive's existing sources and schedule, and the alert floor's configuration.
- No change to DNS other than adding the dedicated v2 host name.

### 3.8 Changes, in order

1. Create the v2 directories and volumes under the data root; provision the key volumes and their markers.
2. Write the secret files from the encrypted secret store into tmpfs (0600, atomic replace); the unit refuses a
   secrets directory that is not 0700 or holds writable secret files.
3. Install the production stack definition and the force-command (`CATALYST_EXPECTED_COMMIT` and the manifest hash
   mandatory; attestation verified; the wrapper serialized).
4. Provision the database roles (administrator from provisioning only; the backup login local-socket only).
5. Add the DNS name and the certificate for the dedicated v2 host; add its site block; validate; reload; re-hash the
   learning block.
6. Install the timers and the dead-man entries; wire receipts and alerts.
7. Set the host conditions: no swap and no core dumps for web, worker and the custody one-shot.
8. Record each step and its induced-fault check (section 3.10) in the private operations record.

The dark deploy (`9kg.31.5`) is a separate step under the same go, after this one completes.

### 3.9 Rollback

All changes are additive. Rollback, in reverse order: remove the timers; remove the site block from the captured copy
of the snippet only (never the whole captured configuration), validate, reload, and confirm the learning block's hash
again; remove the DNS name; stop and remove the v2 compose project; remove the secret files from tmpfs; keep the
volumes until the owner decides (they hold no real data before E). Nothing of the first-generation service is touched,
so nothing there needs rolling back. A rollback is recorded with the same hashes.

### 3.10 Verification (induced faults, not only readbacks)

From `9kg.28`'s acceptance, plus the custody and erasure items added since:

- A secrets directory in the wrong mode refuses start-up; secrets live in tmpfs.
- The staff publish address refuses `0.0.0.0` and `::`.
- Administrator access only from provisioning; the backup login only on the local socket.
- A stale backup raises its alert; a stopped timer is caught by the sweep; `forward-only.json` is in the set; the v2
  dump is inside the archive that feeds the off-site leg.
- An unattested or wrong-digest image is refused by the force-command; the wrapper refuses a second concurrent run.
- The egress environment is parameterized (not `staging`); an entry from the real deny list is refused at deploy.
- Codes only in alerts; the personal-data scan runs in the receipt step.
- No service other than web, worker, `erase`, `restore` and the custody one-shot mounts a key volume; no service
  other than web, worker and the custody one-shot holds the wrapping key; only `erase` and `restore` hold the erasure
  key; the fetcher holds no provider secret (`docker inspect` and `docker exec env` show none).
- The key volumes are absent from the newest archive and the off-site listing.
- The learning block's hash is unchanged.

### 3.11 Missing inputs

: Inputs that must exist before the step that needs them.

| Input | Needed by | Source |
|---|---|---|
| Named staff devices, their holders and the enrolment method; the staff host name; the break-glass holder | the staff site and two-factor at step 5 | `211.7.5` (INPUT) |
| The dedicated v2 host name | step 5 | `211.7.3` (INPUT) |
| The key mirror's device and the custody locations | step 1 | `211.7.9` and H22 (INPUT) |
| The wrapping key's escrow entry and its recipients | step 2 | `211.7.9` (INPUT) |
| The erasure key's source in the encrypted secret store; its rotation row in `027` | step 2 | `211.7.1`; `027` has no row yet |
| The off-host private store for erasure heads and the journal's off-host destination (`9kg.60`) | before the first erasure; before E | INPUT |
| The P6-D-8 exception record for the database data directory | step 1 | the estate's filesystem standard (owner) |
| Port allocations from the estate inventory | step 3 | H4 (owner) |
| The egress deny list's supplier and rotation | step 3 (the list may stay empty while fetching is disabled) | INPUT |
| The production stack definition and the release admitting `production` | step 3 | built (`9kg.31.11`, `026` section 18) |
| The challenge lifetime and the page list | step 3 and step 6 | `211.7.7`, `211.7.2` |
| The erasure registry decision | the first production backup | `211.7.1` |
| The v2 mailbox and its credentials, and the Documenso team, token and webhook secrets | the canaries (D), not this step | `211.7.3`, `211.7.4` |
