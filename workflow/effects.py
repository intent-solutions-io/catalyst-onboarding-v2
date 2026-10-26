"""The effect registry (029 section 6.2, the journal's consistency model; bead 9kg.62): every function that performs an
effect a restore cannot undo, with the class that makes the effect recoverable after a restore to the backup's time.

Nothing imports this at run time. `tests/test_effect_registry.py` finds the effects in the source and fails when one is
missing here, when an entry here is stale, or when a class does not match what the function does, so "the journal
covers every effect" is a checked statement rather than a claim.

The classes:

- `journaled_before`: an entry is written before the effect is a fact (`journal.prepare` before the commit, or a direct
  `journal.append`, fsynced, before the effect); the restrictive effects, and the erasure and custody records;
- `journaled_after`: an entry is written once the effect is a fact (`journal.record`, on commit, or a direct append
  after it), so the journal can miss the effect under a crash, never invent it;
- `provider_read`: no entry; the post-restore step reads the effect at the provider (the Sent folder, the envelope by
  key, the mailbox facts);
- `covered_by_review`: no entry and nothing the restore reads back; the post-restore review closes every open
  credential setup, so staff reissue the link (a password set at the mail host cannot be read back), and queues a
  revocation round for every stopped request whose access removal is not complete, which repeats the password
  rotation and the forwarder removal and reads the host;
- `marker`: an entry about the journal itself (the restore point, the record of a replay), not an effect.

A provider or model call may also be journaled: its entry names, in `via`, the registered function whose journal write
covers it (the same function, or the one that writes the entry).

Families, by what the scanner finds: `journal` (append, record, prepare), `smtp` (`correspondence.transport.send`),
`documenso` (`agreements.provider` writes), `mailhost` (`provisioning.adapter.MailHost` writes), `imap` (a mailbox
client's `append`) and `model` (a PydanticAI agent run).
"""

from dataclasses import dataclass

JOURNALED_BEFORE = "journaled_before"
JOURNALED_AFTER = "journaled_after"
PROVIDER_READ = "provider_read"
COVERED_BY_REVIEW = "covered_by_review"
MARKER = "marker"
CLASSES = (JOURNALED_BEFORE, JOURNALED_AFTER, PROVIDER_READ, COVERED_BY_REVIEW, MARKER)


@dataclass(frozen=True)
class Site:
    cls: str
    why: str
    kinds: tuple = ()  # journal kinds written (the journal family only)
    via: str = ""  # the registered function whose journal entry covers a provider or model call


STAFF_ROLE = ("staff_role_changed",)
PAUSE = ("automation_pause",)

REGISTRY = {
    # Staff accounts (accounts.journal_hooks): a deactivation or a group removal is prepared before its commit.
    "accounts.journal_hooks:_remember_active": {
        "journal": Site(JOURNALED_BEFORE, "a deactivation, prepared in pre_save", STAFF_ROLE)},
    "accounts.journal_hooks:_account_saved": {
        "journal": Site(JOURNALED_AFTER, "a staff account created, deactivated or reactivated, on commit", STAFF_ROLE)},
    "accounts.journal_hooks:_groups_changed": {
        "journal": Site(JOURNALED_BEFORE, "a group removal prepared before it, every change recorded on commit",
                        STAFF_ROLE)},
    # Agreements: the envelope is read back at Documenso by its key after a restore.
    "agreements.completion:_pause": {
        "journal": Site(JOURNALED_BEFORE, "the pause an agreement fault places, prepared then recorded", PAUSE)},
    "agreements.completion:CancelAgreement.call": {"documenso": Site(PROVIDER_READ, "envelope read by key")},
    "agreements.handlers:CreateAgreement.call": {"documenso": Site(PROVIDER_READ, "envelope found by its external key")},
    "agreements.handlers:DistributeAgreement.call": {"documenso": Site(PROVIDER_READ, "envelope read by key")},
    "agreements.handlers:CancelEnvelope.call": {"documenso": Site(PROVIDER_READ, "envelope read by key")},
    # Custody keys (agreements.keystore, catalyst_custody_keys): appended and fsynced before any file is unlinked or
    # rewrapped; recovery never restores a key recorded as destroyed.
    "agreements.keystore:destroy": {
        "journal": Site(JOURNALED_BEFORE, "custody key destruction, appended before the unlink",
                        ("custody_key_destroyed",))},
    "agreements.keystore:_rotate": {
        "journal": Site(JOURNALED_BEFORE, "rotation prepare, appended before any key is rewrapped",
                        ("custody_rotation",))},
    "agreements.keystore:retire": {
        "journal": Site(JOURNALED_AFTER, "retirement, appended once no key file is under the old key",
                        ("custody_rotation",))},
    "agreements.management.commands.catalyst_custody_keys:reap": {
        "journal": Site(JOURNALED_BEFORE, "each orphan, appended before its file is removed", ("custody_orphan_reaped",))},
    "agreements.management.commands.catalyst_custody_keys:rotate_keys": {
        "journal": Site(JOURNALED_AFTER, "rotation done, appended once every live document opens under the new key",
                        ("custody_rotation",))},
    # The model: spent budget is journaled as the day's running total when the reservation commits, before the call.
    "assessments.agent:run_checked": {
        "model": Site(JOURNALED_AFTER, "usage reserved and journaled before the run", via="assessments.interpret:record_usage")},
    "assessments.interpret:record_usage": {
        "journal": Site(JOURNALED_AFTER, "the day's usage total, on the reservation's commit", ("model_usage",))},
    # The restore point the backup and restore write into the journal.
    "config.backup:restore": {"journal": Site(MARKER, "the restore entry the post-restore step answers", ("restore",))},
    # Mail: send_begun before SMTP, then the Sent folder is read after a restore; a filed copy is in that folder.
    "correspondence.inbound:FileCopy.run": {"imap": Site(PROVIDER_READ, "the filed copy is in the Sent folder read")},
    "correspondence.outbound:approve_question": {
        "journal": Site(JOURNALED_AFTER, "an approved question, on commit", ("question_approved",))},
    "correspondence.outbound:SendMessage.run": {
        "journal": Site(JOURNALED_BEFORE, "send_begun, appended after the claim and before SMTP", ("send_begun",)),
        "smtp": Site(PROVIDER_READ, "the Sent folder is read after a restore")},
    "correspondence.processing:_pause": {
        "journal": Site(JOURNALED_BEFORE, "the pause a reply places, prepared then recorded", PAUSE)},
    "correspondence.processing:confirm_question_outcome": {
        "journal": Site(JOURNALED_AFTER, "a confirmed reply outcome, on commit", ("reply_link_outcome",))},
    "correspondence.reminders:SendReminder.decide.write": {
        "journal": Site(JOURNALED_AFTER, "a queued reminder, on commit", ("reminder_queued",))},
    "correspondence.staff_actions:decide_uncertain_send": {
        "journal": Site(JOURNALED_AFTER, "staff decision on an uncertain send, on commit", ("uncertain_send_decided",))},
    "correspondence.staff_actions:pause": {
        "journal": Site(JOURNALED_BEFORE, "a staff pause, prepared then recorded", PAUSE)},
    "correspondence.staff_actions:resume": {
        "journal": Site(JOURNALED_AFTER, "a resume lifts a restriction, so it is recorded on commit", PAUSE)},
    "correspondence.staff_actions:withdraw_question_as": {
        "journal": Site(JOURNALED_BEFORE, "a withdrawal, prepared then recorded", ("question_withdrawn",))},
    "correspondence.staff_actions:confirm_staff_message": {
        "journal": Site(JOURNALED_AFTER, "a confirmed staff message, on commit", ("staff_message_confirmed",))},
    "correspondence.staff_items:resolve_item": {
        "journal": Site(JOURNALED_AFTER, "a resolved staff item, on commit", ("staff_item_resolved",))},
    # Erasure (9kg.32, 9kg.25): the durable erasure record; the intent is fsynced before the erasure runs, and an
    # unwritable record refuses the erasure. The replay marker records a replay, not a new effect.
    "erasure.record:_append": {
        "journal": Site(JOURNALED_BEFORE, "intent before the erasure, completion and handoffs after, each fsynced",
                        ("erasure_intent", "erasure_complete", "erasure_handoff"))},
    "erasure.replay:mark": {"journal": Site(MARKER, "erasures re-applied after a restore", ("erasures_replayed",))},
    # Closure, revocation and mailboxes (provisioning): the outcomes are restrictive, prepared before the commit. The
    # revocation's host calls come before that commit, so the journal entry does not cover them: a round whose outcome
    # the journal lacks is queued again by the post-restore review. The mailbox facts are read at the host.
    "provisioning.closure:close_locked": {
        "journal": Site(JOURNALED_BEFORE, "an application closure, prepared then recorded", ("application_closed",))},
    "provisioning.closure:accept_revocation_exception": {
        "journal": Site(JOURNALED_BEFORE, "a revocation outcome accepted by staff, prepared then recorded",
                        ("access_revocation",))},
    "provisioning.closure:_rotate": {
        "mailhost": Site(COVERED_BY_REVIEW, "the revocation's password rotation, repeated by a queued round")},
    "provisioning.closure:RevokeAccess.run": {
        "mailhost": Site(COVERED_BY_REVIEW, "the revocation's forwarder removal, read and repeated by a queued round")},
    "provisioning.closure:RevokeAccess.run.write": {
        "journal": Site(JOURNALED_BEFORE, "the revocation outcome, prepared then recorded", ("access_revocation",))},
    "provisioning.credentials:set_password": {
        "mailhost": Site(COVERED_BY_REVIEW, "a password cannot be read back; the review closes every open setup")},
    "provisioning.handlers:CreateMailbox.run": {"mailhost": Site(PROVIDER_READ, "the mailbox facts are read at the host")},
}
