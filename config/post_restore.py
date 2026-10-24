"""The post-restore step (026 section 6, steps 4 and 5; 6B.7b; P6-D-13; 9kg.33), run as the owner after
`catalyst_restore`, as the code-declared `reconcile` process kind (9kg.49, RD-1).

A restore takes the database back to the backup's time T, but the world did not go back: links issued or used after
T are valid again, staff accounts and passwords are as they were at T, access removed after T looks present again,
and mail, envelopes and mailbox changes made after T are not in the ledger. The step runs in three phases, and work
resumes only after all of them.

**Review run** (no `--lift`), first in one transaction, before any web or worker process starts:

1. closes every outstanding applicant link (unused confirmation links, open password links, open withdrawal links)
   and opens a staff item for each applicant left without one, so nobody is stranded silently; a password set in
   flight becomes "outcome unknown" and its request gets a staff item to send a fresh link;
2. on the first review only, makes every staff password unusable and ends every staff session: staff disabled or
   re-keyed after T must not come back; the owner checks the roster and re-issues passwords
   (`manage.py changepassword`); a second review run leaves the re-issued passwords alone;
3. turns every outward action that was queued, running or held into an uncertain one with a staff item (PR #89
   review): an exchange after T left no mark in the restored record, so running it again could repeat it;
4. queues a revocation round for every stopped request whose access removal is not complete;
5. **replays the effect journal** (`workflow.journal`): every entry after the restored backup's recorded head is
   re-applied to the restored tables through each app's `restore.replay` (closures, revocations, staff pauses and
   resolutions, question withdrawals, reply-link outcomes, decisions on uncertain sends, the reminder series
   position, staff role removals); a grant, a resend or a revision that cannot be re-applied blindly opens a
   `restore_effect_*` staff item;
6. clears every mailbox cursor's completed-collection watermark, so no reminder fires before the first completed
   collection pass after the restore;
7. reports, per kind and status, with action ids, every outward action, so a person can compare them with what each
   provider already did after T;

then, **outside that transaction**, reads each enabled provider and records per-effect staff items: the mail host's
Sent folder since T (`correspondence.restore.read_sent`; in a live environment always required), Documenso by
envelope id or external key (`agreements.restore.read_envelopes`) and the mail host by address
(`provisioning.restore.read_mailboxes`). Model usage needs no replay: the budget reads the journal's high-water mark
for the day as its floor (`assessments.interpret.daily_requests_used`). The hold records the review as *reconciled*
only when the journal was readable and matched the receipt and every provider read that was needed completed; an
unreachable provider or a journal problem leaves it at *reviewed*, and the report says which.

A `restore_effect_*` item is opened once per effect: an item of the same reason and key resolved after the restore
marker is not reopened by a second review (re-run convergence).

**Lift run** (`--lift`) refuses unless the review reached *reconciled*, no `restore_effect_*` staff item is open,
and the operator confirms both limits explicitly: `--outward-checked` (the reported actions were compared with the
providers and any already done were cancelled) and `--no-closures-after-backup` (no application was closed after T,
or its access was removed again by hand). `--resolve <item> --note "..."` is the manual exceptional resolution of one
`restore_effect_*` item, recorded as the owner's; the note passes the staff-message content checks.

Not here: erasure replay (026 option d) needs the erasure path itself (POL-10); its bead must land before any real
personal data is restored.
"""

from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Count
from django.db.models.functions import Now

from config.backup import RESTORE_HOLD
from workflow import journal

OPEN_SETUP_STATES = ("invitation_pending", "invitation_sending", "invited", "presented")
REVIEWED = "post-restore review run done"
RECONCILED = "post-restore review run done; effects reconciled"
# Kinds the ledger may run again safely but that still reach outside: a mail, a billed model call, a fetch.
OUTWARD_REDELIVERABLE = ("send_verification", "run_assessment", "interpret_message", "fetch_evidence")
ITEM_CONFIRMATION = "restore_confirmation_link_closed"
ITEM_WITHDRAWAL = "restore_withdrawal_link_closed"
# The staff items opened for applicants whose link was closed, by cause: a restore, or a leaked link-signing key (027).
ITEMS = {"restore": (ITEM_CONFIRMATION, ITEM_WITHDRAWAL),
         "rotation": ("rotation_confirmation_link_closed", "rotation_withdrawal_link_closed")}
# 9kg.33: items reconciliation opens, one per unresolved effect; the lift refuses while any is open.
EFFECT_ITEM_PREFIX = "restore_effect_"
ITEM_OUTWARD = "restore_effect_outward_action"
# 9kg.32 (PR #99 reviews): until replay after a restore exists (9kg.25, erasure.registry.REPLAY_BUILT), a journal that
# holds any erasure means the restored tables may hold an erased person again; the review opens this item and the lift
# refuses outright, whether or not the item was resolved by hand.
ITEM_ERASURE = "restore_effect_erasure_unreplayed"


def erasures_unreplayed() -> bool:
    """True while the journal holds an erasure and nothing can replay it (an unreadable journal counts as true)."""
    from erasure import record, registry

    if registry.REPLAY_BUILT:
        return False
    try:
        return record.any_erasure(journal.read())
    except journal.JournalError:
        return True
RESOLVED_BY_OWNER = "owner_resolved_after_restore"
LIVE_STATUSES = ("queued", "running", "held")


class PostRestoreError(Exception):
    pass


def outward_kinds() -> list[str]:
    from workflow import ledger

    return sorted({kind for kind, handler in ledger.handlers().items() if not handler.redeliverable}
                  | {kind for kind in OUTWARD_REDELIVERABLE if kind in ledger.handlers()})


def close_outstanding_links(report: dict, cause: str = "restore", signed_only: bool = False) -> None:
    """Close every outstanding applicant link (unused confirmation links, open password links, open withdrawal links)
    and open a staff item for each applicant left waiting, so nobody is stranded silently; a password set in flight
    becomes "outcome unknown" with a staff item to send a fresh link. Inside the caller's transaction.

    After a restore (review below) every kind is closed. After a leaked link-signing key (`catalyst_close_links`, 027)
    `signed_only` closes the confirmation links alone: they are the only links signed with that key. Password and
    withdrawal links are random tokens stored as hashes, which a key leak does not touch (6B.10a review)."""
    from applications.models import ContactChallenge
    from correspondence.staff_items import open_item
    from provisioning import core, credentials
    from provisioning.models import CredentialSetup, WithdrawalConfirmation

    challenges = ContactChallenge.objects.filter(used_at__isnull=True, superseded_at__isnull=True).select_related("application")
    # A staff item only for an applicant genuinely left waiting: a live link, an unconfirmed contact, still at the
    # first stage. Expired links and settled applications need nothing (PR #68 re-check).
    stranded = {c.application for c in challenges.filter(expires_at__gt=Now(), application__contact_verified_at__isnull=True,
                                                          application__stage="submitted")}
    report["confirmation_links_closed"] = challenges.update(superseded_at=Now())
    for application in stranded:
        open_item(ITEMS[cause][0], f"{cause}:confirmation:{application.public_ref}", application=application)
    if signed_only:
        return
    setups = CredentialSetup.objects.filter(state__in=(*OPEN_SETUP_STATES, "set_pending")).select_related("request")
    affected = {s.request for s in setups}
    report["password_links_closed"] = CredentialSetup.objects.filter(state__in=OPEN_SETUP_STATES).update(
        state="superseded", updated_at=Now())
    report["password_sets_now_unknown"] = CredentialSetup.objects.filter(state="set_pending").update(
        state="set_uncertain", updated_at=Now())
    for request in affected:  # staff send a fresh link through the existing reissue path
        core.item(credentials.ITEM_SETUP, request)
    withdrawals = WithdrawalConfirmation.objects.filter(state__in=("pending", "sent", "uncertain")).select_related("application")
    for application in {w.application for w in withdrawals}:
        open_item(ITEMS[cause][1], f"{cause}:withdrawal:{application.public_ref}", application=application)
    report["withdrawal_links_closed"] = withdrawals.update(state="superseded", updated_at=Now())


def _hold():
    from workflow.models import AutomationPause

    return AutomationPause.objects.select_for_update().filter(subject_type=RESTORE_HOLD[0], subject_id=RESTORE_HOLD[1])


class EffectOpener:
    """Opens `restore_effect_*` items once per effect: an item of the same reason and key already open is returned,
    and one resolved after the restore marker's time is not reopened (PR #89 review: re-run convergence)."""

    def __init__(self, marker_at):
        self.marker_at = marker_at

    def __call__(self, reason: str, key: str, **fields) -> bool:
        from correspondence.models import StaffItem
        from correspondence.staff_items import open_item

        if StaffItem.objects.filter(reason_code=reason, dedupe_key=key, status=StaffItem.Status.OPEN).exists():
            return False
        if self.marker_at is not None and StaffItem.objects.filter(
                reason_code=reason, dedupe_key=key, status=StaffItem.Status.RESOLVED,
                resolution__resolved_at__gte=self.marker_at).exists():
            return False
        open_item(reason, key, audit=False, **fields)
        return True


def replay_journal(report: dict, hold_row) -> tuple[list, "EffectOpener"]:
    """Phase 5: the journal entries after the backup point, re-applied per app inside the review transaction. Returns
    the entries and the opener, for the provider reads. A journal problem is reported (`effects.journal`) and leaves
    nothing replayed: reconciliation without evidence is no reconciliation."""
    from accounts import restore as accounts_restore
    from correspondence import restore as correspondence_restore
    from provisioning import restore as provisioning_restore

    effects = report.setdefault("effects", {})
    opener = EffectOpener(hold_row.created_at)  # re-run convergence: never before the restore itself
    try:
        entries, since, marker = journal.after_restore(journal.parse_anchor(hold_row.actor_ref))
    except journal.JournalError as exc:
        effects["journal"] = exc.code
        return [], opener
    effects["journal"] = "ok"
    effects["entries"] = len(entries)
    effects["restore_marker"] = marker
    if marker is not None:
        opener = EffectOpener(next(e for e in journal.read() if e.seq == marker).when)
    replays = {"correspondence": correspondence_restore, "provisioning": provisioning_restore, "accounts": accounts_restore}
    by_app = {
        "correspondence": [e for e in entries if e.kind in ("automation_pause", "staff_item_resolved", "question_withdrawn",
                                                            "reply_link_outcome", "uncertain_send_decided", "reminder_queued",
                                                            "send_begun")],
        "provisioning": [e for e in entries if e.kind in ("application_closed", "access_revocation")],
        "accounts": [e for e in entries if e.kind == "staff_role_changed"],
    }
    with journal.replaying():  # the replay re-applies facts; it must not journal them again
        for app, module in replays.items():
            effects[app] = module.replay(by_app[app], opener)
    effects["since"] = since.isoformat() if since is not None else None
    return entries, opener


def uncertain_outward(report: dict, opener) -> None:
    """Phase 3 (PR #89 review): an outward action queued, running or held at T may have run after T. It becomes
    uncertain, with one item per action; a send gets its decidable `send_outcome_unknown` item, which the Sent read
    settles when it finds the copy."""
    from applications.models import Application
    from correspondence.models import ApprovedMessage
    from correspondence.outbound import SEND_KINDS, SEND_OUTCOME_UNKNOWN
    from correspondence.staff_items import open_item
    from workflow.models import PendingAction

    actions = list(PendingAction.objects.filter(kind__in=outward_kinds(), status__in=LIVE_STATUSES).order_by("id"))
    for action in actions:
        application = Application.objects.filter(public_ref=action.subject_id).first()
        if action.kind in SEND_KINDS:
            message = ApprovedMessage.objects.filter(send_ref=action.input_ref).first() if action.input_ref else None
            open_item(SEND_OUTCOME_UNKNOWN, str(action.input_ref or action.pk), application=application,
                      approved_message=message, pending_action_id=action.pk)
        else:
            opener(ITEM_OUTWARD, f"action:{action.kind}:{action.pk}", application=application, pending_action_id=action.pk)
    PendingAction.objects.filter(pk__in=[a.pk for a in actions]).update(
        status=PendingAction.Status.UNCERTAIN, last_error="restore_outward_uncertain", lease_token=None,
        lease_expires_at=None, completed_at=Now(), updated_at=Now())
    report["outward_actions_made_uncertain"] = len(actions)


def review() -> dict:
    from accounts.models import User
    from correspondence.models import MailboxCursor
    from provisioning import closure
    from provisioning.models import AccessRevocation, ProvisioningRequest
    from workflow.models import PendingAction

    hold = _hold()
    row = hold.first()
    if row is None:
        raise PostRestoreError("there is no restore hold: this database was not just restored")
    report = {}
    close_outstanding_links(report)
    report["staff_sessions_ended"] = Session.objects.all().delete()[0]
    staff = User.objects.filter(is_staff=True)
    if row.reason not in (REVIEWED, RECONCILED):  # the first review only: a second run leaves re-issued passwords alone
        report["staff_passwords_disabled"] = staff.count()
        for user in staff:  # one at a time: the unusable value is random per user, as Django makes it
            user.set_unusable_password()
            User.objects.filter(pk=user.pk).update(password=user.password)
    else:
        report["staff_passwords_disabled"] = 0
    entries, opener = replay_journal(report, row)
    if journal.configured() and erasures_unreplayed():
        opener(ITEM_ERASURE, "erasure:unreplayed")
        report.setdefault("effects", {})["erasure"] = "unreplayed"
    uncertain_outward(report, opener)
    rounds = 0
    for request in ProvisioningRequest.objects.filter(stop_requested_at__isnull=False):
        if AccessRevocation.objects.filter(request=request).exclude(state__in=closure.FINAL).exists():
            rounds += int(closure._queue_round(request))
    report["revocation_rounds_queued"] = rounds
    report["cursors_reset"] = MailboxCursor.objects.filter(complete_through_at__isnull=False).update(complete_through_at=None)
    outward = (PendingAction.objects.filter(kind__in=outward_kinds(),
                                            status__in=(*LIVE_STATUSES, PendingAction.Status.UNCERTAIN))
               .values("kind", "status").annotate(n=Count("id")).order_by("kind", "status"))
    report["outward_actions"] = [{"kind": r["kind"], "status": r["status"], "count": r["n"],
                                  "ids": list(PendingAction.objects.filter(kind=r["kind"], status=r["status"])
                                              .order_by("id").values_list("id", flat=True))} for r in outward]
    hold.update(reason=REVIEWED)
    report["_entries"], report["_opener"] = entries, opener
    return report


def read_providers(report: dict, entries, opener) -> None:
    """The provider reads, each outside any transaction (the design review of 2026-10-23), feeding per-effect items.
    The hold moves to RECONCILED only when the journal was readable and every needed read completed."""
    from agreements import restore as agreements_restore
    from correspondence import restore as correspondence_restore
    from provisioning import restore as provisioning_restore
    from workflow.models import AutomationPause

    effects = report.setdefault("effects", {})
    row = AutomationPause.objects.filter(subject_type=RESTORE_HOLD[0], subject_id=RESTORE_HOLD[1]).first()  # no lock: outside a transaction
    since = journal.after_restore(journal.parse_anchor(row.actor_ref if row else ""))[1] if effects.get("journal") == "ok" else None
    effects["sends"] = correspondence_restore.read_sent(since, entries, opener)
    effects["envelopes"] = agreements_restore.read_envelopes(since, opener)
    effects["mailboxes"] = provisioning_restore.read_mailboxes(opener)
    blocked = [name for name in ("sends", "envelopes", "mailboxes") if effects[name]["status"] != "ok"]
    if effects.get("journal") != "ok":
        blocked.insert(0, "journal")
    effects["blocked"] = blocked
    if not blocked:
        with transaction.atomic():
            AutomationPause.objects.filter(subject_type=RESTORE_HOLD[0], subject_id=RESTORE_HOLD[1],
                                           reason=REVIEWED).update(reason=RECONCILED)


def open_effect_items() -> list[str]:
    from correspondence.models import StaffItem

    return [f"{i.reason_code}:{i.public_id}" for i in StaffItem.objects.filter(
        reason_code__startswith=EFFECT_ITEM_PREFIX, status=StaffItem.Status.OPEN).order_by("id")]


def resolve_effect(public_id: str, note: str) -> dict:
    """The manual exceptional resolution of one `restore_effect_*` item, as the owner, with a reason that passes the
    staff-message content checks (no link, no credential-like text, no control characters)."""
    from correspondence.common import Refused
    from correspondence.models import StaffItem
    from correspondence.staff_actions import _check_staff_content
    from correspondence.staff_items import clean_note, resolve_item

    note = clean_note(note)
    if len(note) < 10:
        raise PostRestoreError("--resolve needs --note with a reason of at least 10 characters")
    try:
        _check_staff_content("restore", note)
    except Refused as exc:
        raise PostRestoreError(f"--note refused: {exc}") from None
    with transaction.atomic():
        item = StaffItem.objects.select_for_update(of=("self",)).filter(public_id=public_id).first()
        if item is None or not item.reason_code.startswith(EFFECT_ITEM_PREFIX):
            raise PostRestoreError("--resolve must name an open restore_effect_* staff item by its public id")
        if item.status != StaffItem.Status.OPEN:
            return {"resolved": str(item.public_id), "already": True}
        resolve_item(item, code=RESOLVED_BY_OWNER, actor_ref="owner:catalyst_post_restore", note=note,
                     effects={"reason": item.reason_code})
    return {"resolved": str(item.public_id), "already": False}


def run(lift: bool, outward_checked: bool = False, no_closures_after_backup: bool = False) -> dict:
    if not lift:
        with transaction.atomic():
            report = review()
        entries, opener = report.pop("_entries"), report.pop("_opener")
        read_providers(report, entries, opener)
        report["effect_items_open"] = open_effect_items()
        blocked = report["effects"]["blocked"]
        report["hold"] = ("kept: review the outward actions, then run again with --lift" if not blocked
                          else "kept: evidence missing or unreachable (" + ", ".join(blocked) + "); fix and run the review again")
        return report
    with transaction.atomic():
        hold = _hold()
        row = hold.first()
        if row is None:
            raise PostRestoreError("there is no restore hold: this database was not just restored")
        if row.reason == REVIEWED:
            raise PostRestoreError("the review found evidence missing or unreachable; run the review again until it reports reconciled")
        if row.reason != RECONCILED:
            raise PostRestoreError("run the review first (without --lift), then lift")
        if journal.configured() and erasures_unreplayed():
            raise PostRestoreError(f"{ITEM_ERASURE}: the effect journal holds erasures and replay (9kg.25) is not built; "
                                   "the restored tables may hold an erased person, so the hold stays")
        items = open_effect_items()
        if items:
            raise PostRestoreError("effects are unresolved: resolve each restore_effect_* item (--resolve <id> --note ...): "
                                   + ", ".join(items))
        if not (outward_checked and no_closures_after_backup):
            raise PostRestoreError("lifting needs --outward-checked and --no-closures-after-backup (see the review report)")
        hold.delete()
        return {"hold": "lifted"}
