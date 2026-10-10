"""Slice data model constraints (005 S1.4; S1-T3), exercised against PostgreSQL through the ORM."""

import uuid
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection, transaction
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


def refused(fn, constraint, immediate=False):
    """The operation fails on exactly the named constraint (not merely on some IntegrityError)."""
    with pytest.raises(IntegrityError) as excinfo:
        with transaction.atomic():
            if immediate:  # deferred foreign keys are otherwise only checked at commit
                with connection.cursor() as cursor:
                    cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            fn()
    assert excinfo.value.__cause__.diag.constraint_name == constraint


def challenge(app, **kw):
    return ContactChallenge.objects.create(
        application=app, email_at_issue=app.email, expires_at=timezone.now() + timedelta(hours=1), **kw
    )


def version(app, number=1):
    return SubmissionVersion.objects.create(application=app, version_number=number, origin="form", submitted_fields={})


def test_one_open_application_per_email_key_but_terminal_ones_do_not_count():
    application("dup@example.test")
    refused(lambda: application("dup@example.test"), "application_one_open_per_email_key")
    refused(lambda: application("dup@example.test", stage="active"), "application_one_open_per_email_key")  # `active` is open
    first = Application.objects.get(email_key="dup@example.test")
    Application.objects.filter(pk=first.pk).update(stage="withdrawn")
    assert application("dup@example.test").stage == "submitted"


def test_open_stage_set_matches_the_journey():
    assert len(OPEN_STAGES) == 12 and "active" in OPEN_STAGES and "declined" not in OPEN_STAGES


def test_unknown_stage_and_non_positive_counter_are_refused():
    refused(lambda: application("s@example.test", stage="limbo"), "application_stage_valid")
    refused(lambda: application("n@example.test", next_version_number=0), "application_next_version_positive")


def test_version_numbers_are_unique_per_application_and_positive():
    app = application()
    version(app, 1)
    refused(lambda: version(app, 1), "version_number_unique_per_application")
    refused(lambda: version(app, 0), "version_number_positive")
    assert version(application("b@example.test"), 1).version_number == 1


def test_version_origin_is_restricted():
    app = application()
    refused(lambda: SubmissionVersion.objects.create(application=app, version_number=1, origin="import", submitted_fields={}), "version_origin_valid")


def test_at_most_one_active_challenge_per_application():
    app = application()
    first = challenge(app)
    refused(lambda: challenge(app), "challenge_one_active_per_application")
    ContactChallenge.objects.filter(pk=first.pk).update(superseded_at=timezone.now())
    second = challenge(app)
    ContactChallenge.objects.filter(pk=second.pk).update(used_at=timezone.now())
    assert challenge(app).used_at is None


def test_challenge_must_expire_after_creation():
    app = application()
    refused(lambda: ContactChallenge.objects.create(
        application=app, email_at_issue=app.email, expires_at=timezone.now() - timedelta(days=1)
    ), "challenge_expires_after_creation")


def test_one_adoption_per_version_and_per_application():
    app = application()
    v1, v2 = version(app, 1), version(app, 2)
    ch = challenge(app)
    VersionAdoption.objects.create(application=app, submission_version=v1, via_challenge=ch)
    refused(lambda: VersionAdoption.objects.create(application=app, submission_version=v2, via_challenge=ch),
            "adoption_one_per_application")


def test_an_adoption_cannot_use_another_applications_version_or_challenge():
    mine, theirs = application("mine@example.test"), application("theirs@example.test")
    my_version, my_challenge = version(mine, 1), challenge(mine)
    their_version, their_challenge = version(theirs, 1), challenge(theirs)
    refused(lambda: VersionAdoption.objects.create(application=mine, submission_version=their_version, via_challenge=my_challenge),
            "adoption_version_same_application", immediate=True)
    refused(lambda: VersionAdoption.objects.create(application=mine, submission_version=my_version, via_challenge=their_challenge),
            "adoption_challenge_same_application", immediate=True)


def test_event_actor_type_is_restricted():
    app = application()
    ApplicationEvent.objects.create(application=app, kind="submission_received", actor_type="applicant")
    refused(lambda: ApplicationEvent.objects.create(application=app, kind="x", actor_type="robot"), "event_actor_type_valid")


def action(key="sv:1", **kw):
    return PendingAction.objects.create(
        kind="send_verification", subject_type="application", subject_id=uuid.uuid4(), idempotency_key=key, **kw
    )


def test_pending_action_idempotency_key_is_unique():
    action("sv:dup")
    with pytest.raises(IntegrityError) as excinfo:
        with transaction.atomic():
            action("sv:dup")
    assert "idempotency_key" in excinfo.value.__cause__.diag.constraint_name


def test_pending_action_attempts_are_bounded_and_statuses_restricted():
    refused(lambda: action("a", attempts=4, max_attempts=3), "pending_action_attempts_bounded")
    refused(lambda: action("b", max_attempts=0), "pending_action_max_attempts_positive")
    refused(lambda: action("c", status="lost"), "pending_action_status_valid")
    assert action("d", attempts=3, max_attempts=3).attempts == 3


def test_running_requires_a_lease():
    refused(lambda: action("r1", status="running"), "pending_action_running_has_lease")
    leased = action("r2", status="running", lease_token=uuid.uuid4(), lease_expires_at=timezone.now())
    assert leased.status == "running"


@pytest.mark.parametrize(
    ("table", "column"),
    [("workflow_pendingaction", "due_at"), ("workflow_pendingaction", "created_at"),
     ("applications_submissionversion", "received_at"), ("applications_applicationevent", "occurred_at")],
)
def test_timestamps_default_to_the_database_clock(table, column):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT column_default FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
            [table, column],
        )
        (default,) = cursor.fetchone()
    assert default is not None and "statement_timestamp()" in default


def test_workflow_models_have_no_foreign_key_to_domain_models():
    for model in (PendingAction, AutomationPause):
        assert not [f for f in model._meta.get_fields() if isinstance(f, ForeignKey)]


def test_one_pause_per_subject():
    subject = uuid.uuid4()
    AutomationPause.objects.create(subject_type="application", subject_id=subject, reason="synthetic", actor_ref="staff:1")
    refused(lambda: AutomationPause.objects.create(subject_type="application", subject_id=subject, reason="again", actor_ref="staff:1"), "pause_one_per_subject")


def test_outbound_message_is_unique_per_action_attempt():
    app = application()
    act = action("sv:out")
    fields = dict(application=app, pending_action=act, template_key="verification", template_version="1",
                  recipient=app.email, status="accepted")
    OutboundMessage.objects.create(attempt_number=1, **fields)
    refused(lambda: OutboundMessage.objects.create(attempt_number=1, **fields), "outbound_unique_per_attempt")
    assert OutboundMessage.objects.create(attempt_number=2, **fields).attempt_number == 2
    refused(lambda: OutboundMessage.objects.create(attempt_number=3, **{**fields, "status": "lost"}), "outbound_status_valid")
