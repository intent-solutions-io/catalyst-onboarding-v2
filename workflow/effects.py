"""The effect registry (029 section 6.2, the journal's consistency model; bead 9kg.62): every function that performs an
effect a restore cannot undo, in the families below, with the class that makes the effect recoverable after a restore
to the backup's time.

Nothing imports this at run time. `tests/test_effect_registry.py` finds the effects in the source and fails when one is
missing here, when an entry here is stale, or when a class does not match what the function does. It checks the
calls a function makes and that the function named in `by` or `via` exists; it does not check the order of the calls
or that a reader reads what the entry says, so each `why` is a claim the review of this file checks.

The classes:

- `journaled_before`: an entry is written before the effect is a fact (`journal.prepare` before the commit, or a direct
  `journal.append`, fsynced, before the effect); the restrictive effects, and the erasure and custody records. A
  restrictive `prepare` that fails does not stop its effect: the failure is logged, counted and refused at readiness
  (`workflow/journal.py`); only the erasure and custody records refuse their effect when the entry cannot be written;
- `journaled_after`: an entry is written once the effect is a fact (`journal.record`, on commit, or a direct append
  after it), so the journal can miss the effect under a crash, never invent it;
- `provider_read`: no entry; the post-restore function named in `by` reads the effect at the provider;
- `checked_before`: no entry; the action named in `by` reads the provider before it writes, so a restored run that
  repeats it finds the effect and does not repeat it;
- `covered_by_review`: no entry and nothing the restore reads back; the post-restore function named in `by` closes
  what the effect handed out (every live confirmation, password-setup and withdrawal link) or queues it again (a
  revocation round for every stopped request whose access removal is not final after the journal's replay);
- `marker`: an entry about the journal itself (the restore point, the record of a replay), not an effect.

A provider or model call may instead be journaled: `via` names the registered function whose journal write covers it.
`gap` names the bead for a known part of the effect that nothing covers yet. `after` lists the kinds a
journaled-before site writes after the effect (an outcome recorded once the effect is done).

Families, by what the scanner finds: `journal` (append, record, prepare), `smtp` (`correspondence.transport.send`),
`django_mail` (a `django.core.mail` message sent), `documenso` (`agreements.provider` writes), `mailhost`
(`provisioning.adapter.MailHost` writes), `imap` (a mailbox client's `append`), `model` (a PydanticAI agent run) and
`twenty` (`crm.twenty` writes: a person or a note created or updated, a note attached; bgl.14).
Network, subprocess and file-writing primitives outside these are a separate allow-list in the test, not classified
here.
"""

from dataclasses import dataclass

JOURNALED_BEFORE = "journaled_before"
JOURNALED_AFTER = "journaled_after"
PROVIDER_READ = "provider_read"
CHECKED_BEFORE = "checked_before"
COVERED_BY_REVIEW = "covered_by_review"
MARKER = "marker"
CLASSES = (
    JOURNALED_BEFORE,
    JOURNALED_AFTER,
    PROVIDER_READ,
    CHECKED_BEFORE,
    COVERED_BY_REVIEW,
    MARKER,
)


@dataclass(frozen=True)
class Site:
    cls: str
    why: str
    kinds: tuple = ()  # journal kinds written (the journal family only)
    via: str = ""  # the registered function whose journal entry covers a provider or model call
    by: str = ""  # the function that reads the effect back, checks it first, or closes it in the review
    gap: str = ""  # the bead for a known uncovered part
    after: tuple = ()  # kinds of a journaled-before site written after the effect


STAFF_ROLE = ("staff_role_changed",)
PAUSE = ("automation_pause",)
READ_ENVELOPES = "agreements.restore:read_envelopes"
READ_SENT = "correspondence.restore:read_sent"
READ_MAILBOXES = "provisioning.restore:read_mailboxes"
CLOSE_LINKS = "config.post_restore:close_outstanding_links"
REVIEW = "config.post_restore:review"

REGISTRY = {
    # Staff accounts (accounts.journal_hooks): a deactivation or a group removal is prepared before its commit.
    "accounts.journal_hooks:_remember_active": {
        "journal": Site(
            JOURNALED_BEFORE, "a deactivation, prepared in pre_save", STAFF_ROLE
        )
    },
    "accounts.journal_hooks:_account_saved": {
        "journal": Site(
            JOURNALED_AFTER,
            "a staff account created, deactivated or reactivated, on commit",
            STAFF_ROLE,
        )
    },
    "accounts.journal_hooks:_groups_changed": {
        "journal": Site(
            JOURNALED_BEFORE,
            "a group removal prepared before it, every change recorded on commit",
            STAFF_ROLE,
        )
    },
    # Agreements at Documenso.
    "agreements.completion:_pause": {
        "journal": Site(
            JOURNALED_BEFORE,
            "the pause an agreement fault places, prepared then recorded",
            PAUSE,
        )
    },
    "agreements.completion:CancelAgreement.call": {
        "documenso": Site(
            PROVIDER_READ,
            "a restored instance's envelope is read by id; a cancel shows",
            by=READ_ENVELOPES,
        )
    },
    "agreements.handlers:CreateAgreement.call": {
        "documenso": Site(
            PROVIDER_READ,
            "read by id or key; one for a dropped instance is found by the template listing",
            by=READ_ENVELOPES,
        )
    },  # 9kg.76: Catalyst-keyed envelopes no restored row names open an item
    "agreements.handlers:DistributeAgreement.call": {
        "documenso": Site(
            CHECKED_BEFORE,
            "re-reads the envelope and skips one already PENDING",
            by="agreements.handlers:DistributeAgreement.call",
        )
    },
    # bgl.9: the automated countersignature reads the envelope first and signs only for a company recipient that has not
    # signed (a restored run finds a signature already there); `begun` is appended before the call, `done` on commit.
    "agreements.countersign:CountersignAgreement.run": {
        "journal": Site(
            JOURNALED_BEFORE,
            "a countersignature begun, appended before the provider call",
            ("agreement_countersign",),
        ),
        "documenso": Site(
            CHECKED_BEFORE,
            "reads the envelope first; signs only a company recipient not yet signed",
            by="agreements.countersign:CountersignAgreement.run",
        ),
    },
    "agreements.countersign:CountersignAgreement._signed": {
        "journal": Site(
            JOURNALED_AFTER,
            "a countersignature verified by a fresh read, on commit",
            ("agreement_countersign",),
        )
    },
    "agreements.handlers:CancelEnvelope.call": {
        "documenso": Site(
            PROVIDER_READ,
            "a restored instance's envelope is read by id; a cancel shows",
            by=READ_ENVELOPES,
        )
    },
    # Custody keys (agreements.keystore, catalyst_custody_keys): appended and fsynced before any file is unlinked or
    # rewrapped, and the run refuses when the entry cannot be written; recovery never restores a key recorded as
    # destroyed.
    "agreements.keystore:destroy": {
        "journal": Site(
            JOURNALED_BEFORE,
            "custody key destruction, appended before the unlink",
            ("custody_key_destroyed",),
        )
    },
    "agreements.keystore:_rotate": {
        "journal": Site(
            JOURNALED_BEFORE,
            "rotation prepare, appended before any key is rewrapped",
            ("custody_rotation",),
        )
    },
    "agreements.keystore:retire": {
        "journal": Site(
            JOURNALED_AFTER,
            "retirement, appended once no key file is under the old key",
            ("custody_rotation",),
        )
    },
    "agreements.management.commands.catalyst_custody_keys:reap": {
        "journal": Site(
            JOURNALED_BEFORE,
            "each orphan, appended before its file is removed",
            ("custody_orphan_reaped",),
        )
    },
    "agreements.management.commands.catalyst_custody_keys:rotate_keys": {
        "journal": Site(
            JOURNALED_AFTER,
            "rotation done, appended once every live document opens under the new key",
            ("custody_rotation",),
        )
    },
    # The model, for the assessment and the reply interpreter: the reservation journals the day's running total on its
    # commit, before the call.
    "assessments.agent:run_checked": {
        "model": Site(
            JOURNALED_AFTER,
            "usage reserved and journaled before the run",
            via="assessments.interpret:record_usage",
        )
    },
    "assessments.interpret:record_usage": {
        "journal": Site(
            JOURNALED_AFTER,
            "the day's usage total, on the reservation's commit",
            ("model_usage",),
        )
    },
    # The restore point the restore writes into the journal.
    "config.backup:restore": {
        "journal": Site(
            MARKER, "the restore entry the post-restore step answers", ("restore",)
        )
    },
    # 9kg.77: production's Django mailer sends the three link mails through the transport; the review supersedes every
    # live link they carry, as for the django_mail sends above.
    "config.mail:TransportEmailBackend.send_messages": {
        "smtp": Site(
            COVERED_BY_REVIEW,
            "the review supersedes every live link these mails carry",
            by=CLOSE_LINKS,
        )
    },
    # Mail: send_begun before SMTP, then the Sent folder is read after a restore. A filed copy is never evidence of a
    # send; the filing action searches the Sent folder for the message first.
    "correspondence.inbound:FileCopy.run": {
        "imap": Site(
            CHECKED_BEFORE,
            "searches the Sent folder for the message id before it files a copy",
            by="correspondence.inbound:FileCopy.run",
        )
    },
    "correspondence.outbound:approve_question": {
        "journal": Site(
            JOURNALED_AFTER, "an approved question, on commit", ("question_approved",)
        )
    },
    "correspondence.outbound:approve_questions_by_policy": {  # bgl.12, registered at the parity integration
        "journal": Site(
            JOURNALED_AFTER,
            "a question the routine-advance policy approved, on commit",
            ("question_approved",),
        )
    },
    "correspondence.outbound:SendMessage.run": {
        "journal": Site(
            JOURNALED_BEFORE,
            "send_begun, appended after the claim and before SMTP",
            ("send_begun",),
        ),
        "smtp": Site(
            PROVIDER_READ,
            "the Sent folder is read; an unknown copy opens an item",
            by=READ_SENT,
        ),
    },
    "correspondence.processing:_pause": {
        "journal": Site(
            JOURNALED_BEFORE, "the pause a reply places, prepared then recorded", PAUSE
        )
    },
    "correspondence.processing:confirm_question_outcome": {
        "journal": Site(
            JOURNALED_AFTER,
            "a confirmed reply outcome, on commit",
            ("reply_link_outcome",),
        )
    },
    "correspondence.reminders:SendReminder.decide.write": {
        "journal": Site(
            JOURNALED_AFTER, "a queued reminder, on commit", ("reminder_queued",)
        )
    },
    "correspondence.staff_actions:decide_uncertain_send": {
        "journal": Site(
            JOURNALED_AFTER,
            "staff decision on an uncertain send, on commit",
            ("uncertain_send_decided",),
        )
    },
    "correspondence.staff_actions:pause": {
        "journal": Site(
            JOURNALED_BEFORE, "a staff pause, prepared then recorded", PAUSE
        )
    },
    "correspondence.staff_actions:resume": {
        "journal": Site(
            JOURNALED_AFTER,
            "a resume lifts a restriction, so it is recorded on commit",
            PAUSE,
        )
    },
    "correspondence.staff_actions:withdraw_question_as": {
        "journal": Site(
            JOURNALED_BEFORE,
            "a withdrawal, prepared then recorded",
            ("question_withdrawn",),
        )
    },
    "correspondence.staff_actions:confirm_staff_message": {
        "journal": Site(
            JOURNALED_AFTER,
            "a confirmed staff message, on commit",
            ("staff_message_confirmed",),
        )
    },
    "correspondence.staff_items:resolve_item": {
        "journal": Site(
            JOURNALED_AFTER,
            "a resolved staff item, on commit",
            ("staff_item_resolved",),
        )
    },
    # The contact-confirmation link: the review supersedes every unused challenge and opens an item for an applicant
    # left waiting.
    # bgl.8, registered at the parity integration: the service-sent signing link carries the applicant's own provider
    # token. After a restore the envelope is read by id; a signed applicant gets no further link, and a repeated mail
    # to an unsigned one carries the identical link (at least once, as the verification mail, D-20), disclosing nothing new.
    "agreements.signing_mail:SendSigningLink.run": {
        "django_mail": Site(
            PROVIDER_READ,
            "the envelope is read by id after a restore; a repeat is the identical link",
            by=READ_ENVELOPES,
        )
    },
    "correspondence.verification:SendVerification.run": {
        "django_mail": Site(
            COVERED_BY_REVIEW,
            "the review supersedes every unused confirmation link",
            by=CLOSE_LINKS,
        )
    },
    # bgl.5: the receipt carries no link; a receipt action live at the restore point becomes uncertain with a staff item
    # (send_receipt is an outward redeliverable kind), so a restored queue never sends a second receipt unseen.
    "correspondence.receipt:SendReceipt.run": {
        "django_mail": Site(
            COVERED_BY_REVIEW,
            "a live receipt action is made uncertain with a staff item",
            by=REVIEW,
        )
    },
    # Erasure (9kg.32, 9kg.25): the durable erasure record; the intent is fsynced before the erasure runs, and an
    # unwritable record refuses the erasure. The replay marker records a replay, not a new effect.
    "erasure.record:_append": {
        "journal": Site(
            JOURNALED_BEFORE,
            "the intent before the erasure, its completion and handoffs after, fsynced",
            ("erasure_intent", "erasure_complete", "erasure_handoff"),
            after=("erasure_complete", "erasure_handoff"),
        )
    },
    "erasure.replay:mark": {
        "journal": Site(
            MARKER, "erasures re-applied after a restore", ("erasures_replayed",)
        )
    },
    # Closure, revocation and mailboxes (provisioning): the outcomes are restrictive, prepared before the commit. The
    # revocation's host calls come before that commit, so the journal entry does not cover them: a round whose outcome
    # the journal lacks is queued again by the post-restore review. The mailbox facts are read at the host.
    "provisioning.closure:close_locked": {
        "journal": Site(
            JOURNALED_BEFORE,
            "an application closure, prepared then recorded",
            ("application_closed",),
        )
    },
    "provisioning.closure:accept_revocation_exception": {
        "journal": Site(
            JOURNALED_BEFORE,
            "a revocation outcome accepted by staff, prepared then recorded",
            ("access_revocation",),
        )
    },
    "provisioning.closure:_rotate": {
        "mailhost": Site(
            COVERED_BY_REVIEW,
            "the revocation's password rotation, repeated by a queued round",
            by=REVIEW,
        )
    },
    "provisioning.closure:RevokeAccess.run": {
        "mailhost": Site(
            COVERED_BY_REVIEW,
            "the revocation's forwarder removal, read and repeated by a queued round",
            by=REVIEW,
        )
    },
    "provisioning.closure:RevokeAccess.run.write": {
        "journal": Site(
            JOURNALED_BEFORE,
            "the revocation outcome, prepared then recorded",
            ("access_revocation",),
        )
    },
    "provisioning.closure:SendWithdrawalLink.run": {
        "django_mail": Site(
            COVERED_BY_REVIEW,
            "the review supersedes every live withdrawal link",
            by=CLOSE_LINKS,
        )
    },
    "provisioning.credentials:SendSetupInvitation.run": {
        "django_mail": Site(
            COVERED_BY_REVIEW,
            "the review supersedes every open password-setup link",
            by=CLOSE_LINKS,
        )
    },
    "provisioning.credentials:set_password": {
        "mailhost": Site(
            COVERED_BY_REVIEW,
            "a password cannot be read back; the review closes every open setup",
            by=CLOSE_LINKS,
        )
    },
    # The Twenty projection (bgl.14): every write is preceded in its own function by the read that finds it done, so a
    # restored run that repeats it finds the person by its link or the case id it carries, the note by id or marker and
    # the attachment by its targets, and writes only what differs (the restored link rows lose nothing that matters).
    "crm.projection:project_person": {
        "twenty": Site(
            CHECKED_BEFORE,
            "reads the person by link, case id or email before any create or update",
            by="crm.projection:project_person",
        )
    },
    "crm.projection:write_note": {
        "twenty": Site(
            CHECKED_BEFORE,
            "reads the note by id or title and marker, and its targets, before writing",
            by="crm.projection:write_note",
        )
    },
    "crm.projection:fill_person": {
        "twenty": Site(
            CHECKED_BEFORE,
            "reads the person and fills only the blanks it shows",
            by="crm.projection:fill_person",
        )
    },
    "provisioning.handlers:CreateMailbox.run": {
        "mailhost": Site(
            PROVIDER_READ,
            "restored requests are read by address; every create reads absence first",
            by=READ_MAILBOXES,
        )
    },
    # The one-time-password welcome (034 row 39): the set cannot be read back and the welcome carries the credential;
    # the review supersedes every open round, marks a set in flight unknown and tells staff, and the reissued round
    # sets a new password, so a credential the restored record does not account for stops working.
    "provisioning.password_welcome:SendPasswordWelcome._exchange": {
        "mailhost": Site(
            COVERED_BY_REVIEW,
            "the one-time password set; the review closes every open round and a new round "
            "sets a new one",
            by=CLOSE_LINKS,
        ),
        "django_mail": Site(
            COVERED_BY_REVIEW,
            "the welcome carrying that password; the review closes the round and staff "
            "reissue",
            by=CLOSE_LINKS,
        ),
    },
}
