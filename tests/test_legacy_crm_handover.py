"""CRM retries and worker claims must not block or be changed by legacy handover."""

from datetime import timedelta
import uuid

import pytest
from django.utils import timezone

from agreements import provider
from correspondence.common import Refused
from crm import projection
from tests.test_legacy_envelopes import adopt, envelopes, provider_envelope  # noqa: F401
from tests.test_legacy_mailbox_recovery import reconcile, recovery  # noqa: F401
from tests.test_legacy_release import pending, prepare as prepare_release  # noqa: F401
from tests.test_legacy_review import app, legacy, prepare, v1  # noqa: F401
from tests.test_inbound import tls  # noqa: F401
from workflow import ledger
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


def check_handover(action, operation):
    before = (
        action.status,
        action.attempts,
        action.lease_token,
        action.lease_expires_at,
    )
    result = operation()
    assert result is not None
    action.refresh_from_db()
    assert (
        action.status,
        action.attempts,
        action.lease_token,
        action.lease_expires_at,
    ) == before
    assert AutomationPause.objects.filter(subject_id=action.subject_id).exists()


@pytest.mark.parametrize("state", ["queued", "running", "held", "retried", "leased"])
def test_review_preserves_crm_projection_without_blocking_handover(
    legacy, settings, state
):
    application = app()
    action = queued_projection(application, settings, state)
    check_handover(
        action,
        lambda: prepare(application, legacy.user),
    )


@pytest.mark.parametrize("state", ["queued", "running", "held", "retried", "leased"])
def test_adoption_preserves_crm_projection_without_duplicate_envelope(
    envelopes, settings, state
):
    application = app("CAT-ND00-0007")
    original = provider_envelope(envelopes, application)
    action = queued_projection(application, settings, state)
    check_handover(
        action,
        lambda: adopt(envelopes, application),
    )
    assert application.agreements.get().envelope_id == original["id"]
    assert not any(request["method"] == "POST" for request in envelopes.fake.requests)


@pytest.mark.parametrize("state", ["queued", "running", "held", "retried", "leased"])
def test_release_preserves_crm_projection_and_native_approval(pending, settings, state):
    action = queued_projection(pending.application, settings, state)
    check_handover(
        action,
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
def test_mailbox_reconciliation_preserves_crm_projection(recovery, settings, state):
    action = queued_projection(recovery.application, settings, state)
    check_handover(action, lambda: reconcile(recovery))


@pytest.mark.parametrize("state", ["queued", "running", "held", "retried", "leased"])
def test_applicant_work_still_blocks_handover(legacy, settings, state):
    application = app()
    action = queued_projection(application, settings, state)
    PendingAction.objects.create(
        kind="send_verification",
        subject_type="application",
        subject_id=application.public_ref,
        idempotency_key="handover-conflicting-applicant-work",
        status=action.status,
        attempts=action.attempts,
        lease_token=action.lease_token,
        lease_expires_at=action.lease_expires_at,
    )
    with pytest.raises(Refused, match="native_work_in_flight"):
        prepare(application, legacy.user)
    assert not application.events.filter(kind="legacy_review_prepared").exists()


def test_adoption_survives_real_crm_claim_during_provider_read(
    envelopes, settings, monkeypatch
):
    application = app("CAT-ND00-0007")
    original = provider_envelope(envelopes, application)
    action = queued_projection(application, settings, "queued")
    read = provider.read
    claims = []

    def claim_during_read(envelope_id):
        claim = ledger.claim_next({projection.PROJECT: projection.ProjectApplication()})
        assert claim is not None and claim.id == action.pk
        claims.append(claim)
        return read(envelope_id)

    monkeypatch.setattr(provider, "read", claim_during_read)
    instance = adopt(envelopes, application)
    assert instance.envelope_id == original["id"]
    action.refresh_from_db()
    assert action.status == "running" and action.attempts == 1
    assert action.lease_token == claims[0].lease_token
    assert AutomationPause.objects.filter(subject_id=application.public_ref).exists()
    assert not any(request["method"] == "POST" for request in envelopes.fake.requests)
