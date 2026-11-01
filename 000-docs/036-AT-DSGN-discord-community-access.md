# Optional Discord community access

**Status:** In development, default off; synthetic verification only. Bead `9kg.81`.
This integration does not approve or deploy the internal launch, change existing
intake policies, or authorize a real role grant. Production admission in code and
the owner-recorded launch decision remain separate (`026` section 18, `029`, `032`).

## Authority and stored information

The staff reviewer needs the named `approve_community_access` permission, which the
migration assigns to nobody. The reviewer independently verifies the person's
Discord account and current membership epoch, and records digests identifying the
identity and access evidence. Separate evidence is required for Certified and
Leaders; being active never implies either grant. A digest is a reference to
reviewed evidence, not proof that verification occurred.

The existing owner-run `grant_staff_role` command exposes the direct
`community-access-reviewer` role. No group inherits that permission; granting or
revoking it requires the same explicit approval reference and append-only audit as
the other named staff decision roles.

`CommunityAccess` holds the opaque application link, immutable guild and keyed
identity lookup, AES-GCM encrypted Discord account and membership epoch, desired
roles, monotonic decision revision and review evidence. Its encryption key is
separate from other application keys. `CommunityReceipt` contains append-only
operation codes, role labels and action references; it contains no user ID or
provider response. Applicant answers, agreement bodies, email addresses and
conversation content never form Discord payloads.

## Execution and recovery

The existing PostgreSQL `PendingAction` worker executes exact-member reconciliation
and protective revocation. It reads current authority and agreement prerequisites
before granting, journals request intent before an external mutation, and uses the
existing lease fence for results. Calls occur outside database row-lock transactions.
Provider uncertainty is retried with a fresh exact-member read and bounded attempts;
an exhausted outcome is visible for staff review. A change in authority during an
accepted grant queues protective revocation. Database fencing alone cannot undo a
remote effect.

Only HTTP 404 with Discord's JSON error code `10007` proves that the member is
absent. A generic 404, unknown guild (`10004`), or access failure remains an
unverified provider outcome, never evidence of completed removal. These codes are
defined in Discord's [official error reference](https://docs.discord.com/developers/topics/opcodes-and-status-codes#json).

`provisioning.credentials.Activate` reconsiders an existing approved entitlement;
it does not create one. `provisioning.closure.close_locked` records restrictive intent
and queues removal before closure commits. A reviewed downgrade also queues a
protective job and journals a restrictive role ceiling; replay cannot turn that
ceiling into a new positive approval. Grant-disable and subject pause controls
do not suppress full or partial protective removal. The global restore hold still protects the
worker until the existing post-restore review has completed.

The application's closed stage and the community binding's revoked flag record
business closure and restrictive intent. They do not prove Discord removal. Until
`removal_verified` and the separate residual-access review are complete, community
offboarding remains pending and erasure is refused.

Only the three configured role IDs are managed, using individual role PUT/DELETE
requests. The integration neither joins absent people nor replaces their entire
role lists. A changed membership epoch or observed manual removal requires a new
review. Removing managed roles leaves an explicit residual-access review for other
roles and member-specific overwrites. Staff must confirm that review before the
identity becomes erasable.

The existing effect journal carries restrictive revisions and request references,
never Discord identities. Restore replay preserves newer revocation decisions;
provider readback and unresolved effect items participate in the existing hold.
A binding lost with a database snapshot opens a missing-binding review item: the
journal does not pretend it can reconstruct personal data it never contained.
Restore reconciliation performs reads only. Protective changes needed while the
restore hold is active remain an explicit operator recovery obligation.

## Staff operation

`catalyst_community_access` accepts `approve`, `revoke`, and `confirm-offboarding`.
It identifies the application by opaque public reference and the reviewer by staff
ID. The process operator authenticates that reviewer separately; this command is
not a public account-binding endpoint. Approval input is an owner-readable private
JSON file with `guild_id`, `user_id`, `joined_at`, `identity_evidence`, and
`decision_evidence`; optional `certified_evidence`, `leaders_evidence`, and boolean
`reapprove` carry independent decisions. Offboarding confirmation accepts only an
`evidence` digest. Unknown fields are refused.

The command previews by default. `--apply --expected-digest` binds the operation to
the fresh preview, and revision checks refuse an intervening decision. It enqueues
jobs and prints only safe counts and the digest; it makes no provider call. The
operator does not put identity files in this public repository. OAuth self-service
binding is outside this first implementation.

## Configuration and release boundary

Defaults contain no adapter, access credential, identity key, guild or roles, and
`CATALYST_COMMUNITY_GRANTS_ENABLED=false`. Tests inject a synthetic adapter.

The real factory is `provisioning.community_adapter.LiveDiscord`. A reviewed
production configuration needs the separate access credential and identity key
from per-secret files, exact guild and Member/Certified/Leaders IDs, and
`CATALYST_COMMUNITY_LIVE_AUTHORITY`, the digest of its reviewed release/policy record.
That reference does not independently prove approval. Only worker and restore-reader
processes may receive the access credential. Grants can remain disabled while a
configured provider removes revoked access.

The HTTP boundary uses fixed `discord.com` HTTPS, certificate and hostname
verification, bounded reads, explicit timeouts, no redirect following or environment
proxy discovery, and exact API routes. Before writes it verifies a non-administrator
bot with Manage Roles, refuses broader management powers, and checks that the three
unmanaged, permission-free target roles are below its highest role.

Those scope checks also apply before removal. If the bot's permissions or any
configured target role's hierarchy or guild permissions drift, automatic writes
are refused and removal remains unverified. Staff must restore the reviewed scope
or complete removal manually and obtain fresh provider readback; disabling grants
alone does not resolve a provider-scope failure.

The production compose definition and host firewall are unchanged. Deployment must
explicitly mount the new credentials into the authorized processes and permit the
reviewed Discord HTTPS route. Existing v2 launch prerequisites, approved eligibility
and data-handling policy, a narrowly scoped access identity, controlled provider
canary, and actual member-account permission tests remain required release evidence.
Synthetic tests do not satisfy those steps or authorize broader enrollment. The
separate release and live-evidence work remains tracked in bead `9kg.82`.
