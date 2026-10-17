"""Staff services for P4 agreements (021 sections 5 and 9; 4B.1). One transaction each, the application locked first.

- `approve_template_version`: the owner approves one template version (POL-07; P4-D-1). Approving twice does nothing
  more; an approved version is never edited (database trigger).
- `decide_uncertain_create`: a decision-maker decides an unknown create that reconciliation could not settle
  (P4-D-8): mark it not sent and allow one new create under a **new** key, or abandon the agreement. The old key stays
  watched, so a late envelope is caught as an orphan and never verified (P4-D-19). A decision never rewrites the
  unknown outcome into a known one: the attempt records `decided_not_sent` or `abandoned`.

The permissions are assigned to no group by migration (021 section 9): they are granted to named people.
"""

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models.functions import Now

from applications.models import Application, ApplicationEvent, Stage
from correspondence.models import StaffItem
from correspondence.staff_items import event, resolve_item
from workflow.models import PendingAction

from . import handlers
from .models import AgreementInstance, AgreementTemplateVersion, EnvelopeAttempt

CHOICES = ("not_sent", "abandon")


class Refused(Exception):
    """A service refused; the message is a reason code."""


def can(user, permission: str) -> bool:
    return (user is not None and user.is_authenticated and user.is_active and user.is_staff and not user.is_superuser
            and user.has_perm(f"agreements.{permission}"))


def require(user, permission: str) -> None:
    if not can(user, permission):
        raise PermissionDenied(permission)


def approve_template_version(version_id: int, user, expected_sha256: str) -> AgreementTemplateVersion:
    require(user, "approve_agreement_template")
    with transaction.atomic():
        version = AgreementTemplateVersion.objects.select_for_update(of=("self",)).get(pk=version_id)
        if expected_sha256 != version.pdf_sha256:
            raise Refused("template_changed_since_shown")
        if version.status == AgreementTemplateVersion.Status.APPROVED:
            return version
        AgreementTemplateVersion.objects.filter(pk=version.pk, status=AgreementTemplateVersion.Status.DRAFT).update(
            status=AgreementTemplateVersion.Status.APPROVED, approved_by=f"user:{user.pk}", approved_at=Now())
    version.refresh_from_db()
    return version


def decide_uncertain_create(instance_id: int, user, choice: str) -> AgreementInstance:
    require(user, "decide_uncertain_agreement")
    if choice not in CHOICES:
        raise Refused("unknown_choice")
    actor = f"user:{user.pk}"
    instance = AgreementInstance.objects.get(pk=instance_id)
    with transaction.atomic():
        application = Application.objects.select_for_update(of=("self",)).get(pk=instance.application_id)
        instance = AgreementInstance.objects.select_for_update(of=("self",)).get(pk=instance_id)
        if instance.issue_status != "create_uncertain":
            raise Refused("not_uncertain")
        attempt = EnvelopeAttempt.objects.filter(instance=instance, step=EnvelopeAttempt.Step.CREATE,
                                                 external_key=instance.external_key,
                                                 outcome=EnvelopeAttempt.Outcome.UNKNOWN).order_by("-id").first()
        if attempt is None:
            raise Refused("no_unknown_attempt")
        if PendingAction.objects.filter(kind=handlers.RECONCILE, input_ref=str(attempt.public_id),
                                        status__in=(PendingAction.Status.QUEUED, PendingAction.Status.RUNNING)).exists():
            raise Refused("reconciliation_in_progress")  # decide only once the evidence checks have ended
        outcome = EnvelopeAttempt.Outcome.DECIDED_NOT_SENT if choice == "not_sent" else EnvelopeAttempt.Outcome.ABANDONED
        EnvelopeAttempt.objects.filter(pk=attempt.pk).update(outcome=outcome, finished_at=Now())
        PendingAction.objects.filter(kind=handlers.CREATE, input_ref=str(instance.public_id),
                                     status=PendingAction.Status.UNCERTAIN).update(
            status=PendingAction.Status.DONE, last_error=f"decided_{choice}", completed_at=Now(), updated_at=Now())
        if choice == "not_sent" and application.stage == Stage.AGREEMENTS:
            instance.external_key = handlers.new_key()  # P4-D-19: never the same key twice
            AgreementInstance.objects.filter(pk=instance.pk).update(external_key=instance.external_key,
                                                                    issue_status="create_pending", updated_at=Now())
            handlers.enqueue_create(instance)
        else:
            AgreementInstance.objects.filter(pk=instance.pk).update(issue_status="cancelled", updated_at=Now())
        handlers.enqueue_reconcile(attempt, 1, watch=True)
        for item in StaffItem.objects.filter(reason_code=handlers.CREATE_UNKNOWN, dedupe_key=f"create:{attempt.public_id}",
                                             status=StaffItem.Status.OPEN):
            resolve_item(item, code=f"decided_{choice}", actor_ref=actor, effects={"instance": str(instance.public_id)})
        event(application, "agreement_create_decided", {"instance": str(instance.public_id), "choice": choice,
                                                        "attempt": str(attempt.public_id)},
              actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor)
    instance.refresh_from_db()
    return instance
