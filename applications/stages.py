"""The one place application stages change outside S1 confirmation (003 ADR-13; 018 section 4).

`transition` runs inside the caller's transaction with the application already locked: it re-reads the stage,
refuses unless it is one of the expected stages (a compare-and-set), updates it and writes the history event.
"""

from django.db import transaction
from django.db.models.functions import Now

from .models import Application, ApplicationEvent


class StageConflict(Exception):
    """The application is not in an expected stage; nothing was changed."""


def transition(application_pk, from_stages, to: str, *, event_kind: str, data=None,
               actor_type=ApplicationEvent.ActorType.SYSTEM, actor_ref: str = "") -> Application:
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("transition() must run inside the caller's transaction")
    application = Application.objects.select_for_update(of=("self",)).get(pk=application_pk)
    if application.stage not in from_stages:
        raise StageConflict(application.stage)
    Application.objects.filter(pk=application.pk).update(stage=to, updated_at=Now())
    ApplicationEvent.objects.create(application=application, kind=event_kind, actor_type=actor_type, actor_ref=actor_ref,
                                    data={"from": application.stage, "to": to, **(data or {})})
    application.stage = to
    return application
