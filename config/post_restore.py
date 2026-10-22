"""The post-restore step (026 section 6, steps 4 and 5; 6B.7b; P6-D-13), run as the owner after `catalyst_restore`.

A restore takes the database back to the backup's time T, but the world did not go back: links issued or used after
T are valid again, staff accounts and passwords are as they were at T, access removed after T looks present again,
and mail, envelopes and mailbox changes made after T are not in the ledger. The step runs in two phases, and work
resumes only after both.

**Review run** (no `--lift`), in one transaction, before any web or worker process starts:

1. closes every outstanding applicant link (unused confirmation links, open password links, open withdrawal links)
   and opens a staff item for each applicant left without one, so nobody is stranded silently; a password set in
   flight becomes "outcome unknown" and its request gets a staff item to send a fresh link;
2. makes every staff password unusable and ends every staff session: staff disabled or re-keyed after T must not
   come back; the owner checks the roster and re-issues passwords (`manage.py changepassword`);
3. lets every action that was running expire its lease. The ledger then runs it again; a handler reconciles instead
   of repeating only where the restored record shows its exchange began (for example a "sending" attempt). An
   exchange after T leaves no such mark, so this alone does not stop a repeat;
4. queues a revocation round for every stopped request whose access removal is not complete. A closure that
   happened after T is not in the restored database at all, so it cannot be found here;
5. reports, per kind and status, with action ids, every queued or running action that reaches the outside world, so
   a person can compare them with what each provider already did after T;

and records on the hold that the review run happened.

**Lift run** (`--lift`) refuses unless a review run happened and the operator confirms both limits explicitly:
`--outward-checked` (the reported actions were compared with the providers and any already done were cancelled)
and `--no-closures-after-backup` (no application was closed after T, or its access was removed again by hand).

Not here: erasure replay (026 option d) needs the erasure path itself (POL-10); its bead must land before any real
personal data is restored.
"""

from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Count
from django.db.models.functions import Now

from config.backup import RESTORE_HOLD

OPEN_SETUP_STATES = ("invitation_pending", "invitation_sending", "invited", "presented")
REVIEWED = "post-restore review run done"
# Kinds the ledger may run again safely but that still reach outside: a mail, a billed model call, a fetch.
OUTWARD_REDELIVERABLE = ("send_verification", "run_assessment", "interpret_message", "fetch_evidence")
ITEM_CONFIRMATION = "restore_confirmation_link_closed"
ITEM_WITHDRAWAL = "restore_withdrawal_link_closed"
# The staff items opened for applicants whose link was closed, by cause: a restore, or a leaked link-signing key (027).
ITEMS = {"restore": (ITEM_CONFIRMATION, ITEM_WITHDRAWAL),
         "rotation": ("rotation_confirmation_link_closed", "rotation_withdrawal_link_closed")}


class PostRestoreError(Exception):
    pass


def outward_kinds() -> list[str]:
    from workflow import ledger

    return sorted({kind for kind, handler in ledger.handlers().items() if not handler.redeliverable}
                  | {kind for kind in OUTWARD_REDELIVERABLE if kind in ledger.handlers()})


def close_outstanding_links(report: dict, cause: str = "restore") -> None:
    """Close every outstanding applicant link (unused confirmation links, open password links, open withdrawal links)
    and open a staff item for each applicant left waiting, so nobody is stranded silently; a password set in flight
    becomes "outcome unknown" with a staff item to send a fresh link. Inside the caller's transaction. Used after a
    restore (review below) and after a leaked link-signing key (`manage.py catalyst_close_links`, 027)."""
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


def review() -> dict:
    from accounts.models import User
    from provisioning import closure
    from provisioning.models import AccessRevocation, ProvisioningRequest
    from workflow.models import AutomationPause, PendingAction

    hold = AutomationPause.objects.select_for_update().filter(subject_type=RESTORE_HOLD[0], subject_id=RESTORE_HOLD[1])
    if not hold.exists():
        raise PostRestoreError("there is no restore hold: this database was not just restored")
    report = {}
    close_outstanding_links(report)
    report["staff_sessions_ended"] = Session.objects.all().delete()[0]
    staff = User.objects.filter(is_staff=True)
    report["staff_passwords_disabled"] = staff.count()
    for user in staff:  # one at a time: the unusable value is random per user, as Django makes it
        user.set_unusable_password()
        User.objects.filter(pk=user.pk).update(password=user.password)
    report["running_actions_recovered"] = PendingAction.objects.filter(status=PendingAction.Status.RUNNING).update(
        lease_expires_at=Now(), updated_at=Now())
    rounds = 0
    for request in ProvisioningRequest.objects.filter(stop_requested_at__isnull=False):
        if AccessRevocation.objects.filter(request=request).exclude(state__in=closure.FINAL).exists():
            rounds += int(closure._queue_round(request))
    report["revocation_rounds_queued"] = rounds
    outward = (PendingAction.objects.filter(kind__in=outward_kinds(),
                                            status__in=(PendingAction.Status.QUEUED, PendingAction.Status.RUNNING))
               .values("kind", "status").annotate(n=Count("id")).order_by("kind", "status"))
    report["outward_actions"] = [{"kind": r["kind"], "status": r["status"], "count": r["n"],
                                  "ids": list(PendingAction.objects.filter(kind=r["kind"], status=r["status"])
                                              .order_by("id").values_list("id", flat=True))} for r in outward]
    hold.update(reason=REVIEWED)
    return report


def run(lift: bool, outward_checked: bool = False, no_closures_after_backup: bool = False) -> dict:
    from workflow.models import AutomationPause

    with transaction.atomic():
        if not lift:
            report = review()
            report["hold"] = "kept: review the outward actions, then run again with --lift"
            return report
        hold = AutomationPause.objects.select_for_update().filter(subject_type=RESTORE_HOLD[0], subject_id=RESTORE_HOLD[1])
        row = hold.first()
        if row is None:
            raise PostRestoreError("there is no restore hold: this database was not just restored")
        if row.reason != REVIEWED:
            raise PostRestoreError("run the review first (without --lift), then lift")
        if not (outward_checked and no_closures_after_backup):
            raise PostRestoreError("lifting needs --outward-checked and --no-closures-after-backup (see the review report)")
        hold.delete()
        return {"hold": "lifted"}
