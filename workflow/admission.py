"""Activate the production signing handoff inside the decision transaction.

The assessment domain records a decision. This workflow boundary reads the
approved template metadata; provider effects remain in the normal worker.
"""

from django.conf import settings

from applications.models import ApplicationEvent
from config.parity import automated_admission_enabled
from agreements.template_versions import approved_version


def activate_nda_handoff(application, decision, *, actor: str, actor_type) -> bool:
    assert decision.outcome == "admit"
    automatic_signing = (
        automated_admission_enabled(settings)
        and bool(settings.CATALYST_AGREEMENT_PROVIDER_URL)
        and approved_version("nda") is not None
    )
    if automatic_signing:
        ApplicationEvent.objects.create(
            application=application,
            kind="agreements_activated",
            actor_type=actor_type,
            actor_ref=actor,
            data={
                "activation_version": 1,
                "approval_ref": decision.policy_ref,
                "decision": str(decision.public_id),
                "mode": "production_workflow",
            },
        )
    return automatic_signing
