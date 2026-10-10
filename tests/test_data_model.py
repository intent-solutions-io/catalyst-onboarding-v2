"""Slice data model constraints (005 S1.4; S1-T3), exercised against PostgreSQL through the ORM."""

import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ForeignKey
from django.utils import timezone

from applications.models import (
    OPEN_STAGES,
    Application,
    ApplicationEvent,
    ContactChallenge,
    SubmissionVersion,
    VersionAdoption,
)
from correspondence.models import OutboundMessage
from workflow.models import AutomationPause, PendingAction

pytestmark = pytest.mark.django_db


def application(email_key="a@example.test", **kw):
    return Application.objects.create(email=email_key, email_key=email_key, display_name="Synthetic Applicant", **kw)


def refused(fn):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            fn()


def challenge(app, **kw):
    return ContactChallenge.objects.create(
        application=app, email_at_issue=app.email, expires_at=timezone.now() + timedelta(hours=1), **kw
    )


def version(app, number=1):
    return SubmissionVersion.objects.create(application=app, version_number=number, origin="form", submitted_fields={})


def test_one_open_application_per_email_key_but_terminal_ones_do_not_count():
    application("dup@example.test")
    refused(lambda: application("dup@example.test"))
    refused(lambda: application("dup@example.test", stage="active"))  # `active` is open
    first = Application.objects.get(email_key="dup@example.test")
    Application.objects.filter(pk=first.pk).update(stage="withdrawn")
    assert application("dup@example.test").stage == "submitted"


def test_open_stage_set_matches_the_journey():
    assert len(OPEN_STAGES) == 12 and "active" in OPEN_STAGES and "declined" not in OPEN_STAGES


def test_unknown_stage_and_non_positive_counter_are_refused():
    refused(lambda: application("s@example.test", stage="limbo"))
    refused(lambda: application("n@example.test", next_version_number=0))


def test_version_numbers_are_unique_per_application_and_positive():
    app = application()
    version(app, 1)
    refused(lambda: version(app, 1))
    refused(lambda: version(app, 0))
    assert version(application("b@example.test"), 1).version_number == 1


def test_version_origin_is_restricted():
    app = application()
    refused(lambda: SubmissionVersion.objects.create(application=app, version_number=1, origin="import", submitted_fields={}))


def test_at_most_one_active_challenge_per_application():
    app = application()
    first = challenge(app)
    refused(lambda: challenge(app))
    ContactChallenge.objects.filter(pk=first.pk).update(superseded_at=timezone.now())
    second = challenge(app)
    ContactChallenge.objects.filter(pk=second.pk).update(used_at=timezone.now())
    assert challenge(app).used_at is None


def test_challenge_must_expire_after_creation():
    app = application()
    refused(lambda: ContactChallenge.objects.create(
        application=app, email_at_issue=app.email, expires_at=timezone.now() - timedelta(days=1)
    ))


def test_one_adoption_per_version_and_per_application():
    app = application()
    v1, v2 = version(app, 1), version(app, 2)
    ch = challenge(app)
    VersionAdoption.objects.create(application=app, submission_version=v1, via_challenge=ch)
    refused(lambda: VersionAdoption.objects.create(application=app, submission_version=v2, via_challenge=ch))
    other = application("o@example.test")
    refused(lambda: VersionAdoption.objects.create(application=other, submission_version=v1, via_challenge=ch))


def test_event_actor_type_is_restricted():
    app = application()
    ApplicationEvent.objects.create(application=app, kind="submission_received", actor_type="applicant")
    refused(lambda: ApplicationEvent.objects.create(application=app, kind="x", actor_type="robot"))


def action(key="sv:1", **kw):
    return PendingAction.objects.create(
        kind="send_verification", subject_type="application", subject_id=uuid.uuid4(), idempotency_key=key, **kw
    )


def test_pending_action_idempotency_key_is_unique():
    action("sv:dup")
    refused(lambda: action("sv:dup"))


def test_pending_action_attempts_are_bounded_and_statuses_restricted():
    refused(lambda: action("a", attempts=4, max_attempts=3))
    refused(lambda: action("b", max_attempts=0))
    refused(lambda: action("c", status="lost"))
    assert action("d", attempts=3, max_attempts=3).attempts == 3


def test_running_requires_a_lease():
    refused(lambda: action("r1", status="running"))
    leased = action("r2", status="running", lease_token=uuid.uuid4(), lease_expires_at=timezone.now())
    assert leased.status == "running"


def test_due_at_comes_from_the_database_clock():
    created = action("clock")
    created.refresh_from_db()
    assert created.due_at is not None and created.created_at is not None


def test_workflow_models_have_no_foreign_key_to_domain_models():
    for model in (PendingAction, AutomationPause):
        assert not [f for f in model._meta.get_fields() if isinstance(f, ForeignKey)]


def test_one_pause_per_subject():
    subject = uuid.uuid4()
    AutomationPause.objects.create(subject_type="application", subject_id=subject, reason="synthetic", actor_ref="staff:1")
    refused(lambda: AutomationPause.objects.create(subject_type="application", subject_id=subject, reason="again", actor_ref="staff:1"))


def test_outbound_message_is_unique_per_action_attempt():
    app = application()
    act = action("sv:out")
    fields = dict(application=app, pending_action=act, template_key="verification", template_version="1",
                  recipient=app.email, status="accepted")
    OutboundMessage.objects.create(attempt_number=1, **fields)
    refused(lambda: OutboundMessage.objects.create(attempt_number=1, **fields))
    assert OutboundMessage.objects.create(attempt_number=2, **fields).attempt_number == 2
    refused(lambda: OutboundMessage.objects.create(attempt_number=3, **{**fields, "status": "lost"}))
