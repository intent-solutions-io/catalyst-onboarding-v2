"""The post-restore step (026 section 6, steps 4 and 5; 6B.7b; P6-D-13), run as the owner after `catalyst_restore`.

A restore takes the database back to the backup's time T, but the world did not go back: links issued after T,
or used after T, are valid again; staff sessions and actions in flight are stale; access removed after T looks
present again; and mail, envelopes and mailbox changes made after T are not in the ledger. This step, before
anything runs:

1. invalidates every outstanding applicant link: unused confirmation links, open password links (a password set
   in flight becomes "outcome unknown", never replayed) and open withdrawal links; and every staff session;
2. lets every action that was running at T expire its lease now, so the ledger recovers it through its existing
   path: a non-repeatable action is reconciled, never blindly repeated (ADR-15);
3. queues a revocation round for every stopped request whose access removal is not complete;
4. reports, as counts per kind, the queued actions that reach the outside world, so a person can check them
   against the providers before work resumes.

Only with `--lift` does it then remove the restore hold. Erasure replay (026 option d) is not here: erasure itself
does not exist yet (POL-10); its bead must land before any real personal data is restored.
"""

from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models.functions import Now

from config.backup import RESTORE_HOLD

OPEN_SETUP_STATES = ("invitation_pending", "invitation_sending", "invited", "presented")


class PostRestoreError(Exception):
    pass


def run(lift: bool) -> dict:
    from applications.models import ContactChallenge
    from provisioning import closure
    from provisioning.models import AccessRevocation, CredentialSetup, ProvisioningRequest, WithdrawalConfirmation
    from workflow import ledger
    from workflow.models import AutomationPause, PendingAction

    hold = AutomationPause.objects.filter(subject_type=RESTORE_HOLD[0], subject_id=RESTORE_HOLD[1])
    with transaction.atomic():
        if not hold.select_for_update().exists():
            raise PostRestoreError("there is no restore hold: this database was not just restored")
        report = {
            "confirmation_links_closed": ContactChallenge.objects.filter(used_at__isnull=True, superseded_at__isnull=True)
            .update(superseded_at=Now()),
            "password_links_closed": CredentialSetup.objects.filter(state__in=OPEN_SETUP_STATES)
            .update(state="superseded", updated_at=Now()),
            "password_sets_now_unknown": CredentialSetup.objects.filter(state="set_pending")
            .update(state="set_uncertain", updated_at=Now()),
            "withdrawal_links_closed": WithdrawalConfirmation.objects.filter(state__in=("pending", "sent", "uncertain"))
            .update(state="superseded", updated_at=Now()),
            "staff_sessions_ended": Session.objects.all().delete()[0],
            "running_actions_recovered": PendingAction.objects.filter(status=PendingAction.Status.RUNNING)
            .update(lease_expires_at=Now(), updated_at=Now()),
        }
        rounds = 0
        for request in ProvisioningRequest.objects.filter(stop_requested_at__isnull=False):
            if AccessRevocation.objects.filter(request=request).exclude(state__in=closure.FINAL).exists():
                closure._queue_round(request)
                rounds += 1
        report["revocation_rounds_queued"] = rounds
        outward = sorted(kind for kind, handler in ledger.handlers().items() if not handler.redeliverable)
        queued = {}
        for kind in outward:
            count = PendingAction.objects.filter(kind=kind, status=PendingAction.Status.QUEUED).count()
            if count:
                queued[kind] = count
        report["queued_outward_actions"] = queued  # check these against the providers before lifting the hold
        if lift:
            hold.delete()
        report["hold"] = "lifted" if lift else "kept"
    return report
