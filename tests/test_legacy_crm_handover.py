"""A paused case's untouched CRM projection must not deadlock its handover."""

from datetime import timedelta
import uuid

import pytest
from django.utils import timezone

from correspondence.common import Refused
from crm import projection
from tests.test_legacy_envelopes import adopt, envelopes, provider_envelope  # noqa: F401
from tests.test_legacy_mailbox_recovery import reconcile, recovery  # noqa: F401
from tests.test_legacy_release import pending, prepare as prepare_release  # noqa: F401
from tests.test_legacy_review import app, legacy, prepare, v1  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from workflow.models import AutomationPause, PendingAction


def queued_projection(application, settings, state):
    settings.CATALYST_TWENTY_PROJECTION = True
    assert projection.enqueue(application, "handover-regression")
    action = PendingAction.objects.get(
        subject_id=application.public_ref, kind=projection.PROJECT
    )
    if state == "running":
        PendingAction.objects.filter(pk=action.pk).update(
            status="running",
            attempts=1,
            lease_token=uuid.uuid4(),
            lease_expires_at=timezone.now() + timedelta(minutes=1),
        )
    elif state == "held":
        PendingAction.objects.filter(pk=action.pk).update(status="held")
    elif state == "retried":
        PendingAction.objects.filter(pk=action.pk).update(attempts=1)
    elif state == "leased":
        PendingAction.objects.filter(pk=action.pk).update(
            lease_token=uuid.uuid4(),
            lease_expires_at=timezone.now() + timedelta(minutes=1),
        )
    action.refresh_from_db()
    assert AutomationPause.objects.filter(subject_id=application.public_ref).exists()
    return action


def check_handover(action, state, error, operation):
    if state != "queued":
        with pytest.raises(Refused, match=error):
            operation()
        return
    result = operation()
    assert result is not None
    action.refresh_from_db()
    assert action.status == "queued" and action.attempts == 0
    assert AutomationPause.objects.filter(subject_id=action.subject_id).exists()


@pytest.mark.parametrize("state", ["queued", "running", "held", "retried", "leased"])
def test_review_preserves_queued_projection_without_blocking_handover(
    legacy, settings, state
):
    application = app()
    action = queued_projection(application, settings, state)
    check_handover(
        action,
        state,
        "native_work_in_flight",
        lambda: prepare(application, legacy.user),
    )


@pytest.mark.parametrize("state", ["queued", "running", "held", "retried", "leased"])
def test_adoption_preserves_queued_projection_without_duplicate_envelope(
    envelopes, settings, state
):
    application = app("CAT-ND00-0007")
    original = provider_envelope(envelopes, application)
    action = queued_projection(application, settings, state)
    check_handover(
        action,
        state,
        "native_work_requires_reconciliation",
        lambda: adopt(envelopes, application),
    )
    if state == "queued":
        assert application.agreements.get().envelope_id == original["id"]
    assert not any(request["method"] == "POST" for request in envelopes.fake.requests)


@pytest.mark.parametrize("state", ["queued", "running", "held", "retried", "leased"])
def test_release_preserves_queued_projection_and_native_approval(
    pending, settings, state
):
    action = queued_projection(pending.application, settings, state)
    check_handover(
        action,
        state,
        "native_work_requires_reconciliation",
        lambda: prepare_release(pending),
    )
    if state == "queued":
        assert (
            PendingAction.objects.get(
                subject_id=pending.application.public_ref, kind="provision"
            ).status
            == "held"
        )


@pytest.mark.parametrize("state", ["queued", "running", "held", "retried", "leased"])
def test_mailbox_reconciliation_preserves_queued_projection(recovery, settings, state):
    action = queued_projection(recovery.application, settings, state)
    check_handover(
        action, state, "native_mailbox_operation_in_flight", lambda: reconcile(recovery)
    )
