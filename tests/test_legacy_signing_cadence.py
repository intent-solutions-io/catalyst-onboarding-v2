"""An imported envelope keeps its delivery allowance and quiet-period clock."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db.models.functions import Now
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from psycopg import sql

from agreements import signing_mail, signing_reminder
from correspondence import association, lapse, staff_actions
from correspondence.common import Refused
from correspondence.models import (
    InboundMessage,
    MessageTemplate,
    MessageTemplateVersion,
)
from firstgen import review, signing_cadence
from tests.test_first_generation_import import import_v1
from tests.test_legacy_envelopes import (  # noqa: F401 (fixture chain)
    adopt,
    app,
    envelopes,
    legacy,
    provider_envelope,
    source_record,
    tls,
    v1,
)
from tests.test_legacy_signing_history import signing_job
from tests.test_staff import logged_in, make_user
from workflow import business_days, ledger
from workflow.models import AutomationPause, PendingAction


@pytest.fixture
def timers(envelopes, settings):
    settings.CATALYST_SIGNING_REMINDER_MAX = 1
    settings.CATALYST_SIGNING_REMINDER_BUSINESS_DAYS = 5
    settings.CATALYST_LAPSE_AFTER_BUSINESS_DAYS = 10
    settings.CATALYST_REMINDER_QUIET_START_HOUR = (
        settings.CATALYST_REMINDER_QUIET_END_HOUR
    ) = 0
    settings.CATALYST_AGREEMENT_DISTRIBUTION = "service"
    settings.CATALYST_AGREEMENT_SIGNING_BASE_URL = "https://sign.example.test"
    signing_mail.SEED.create_templates(MessageTemplate, MessageTemplateVersion)
    envelopes.application = app("CAT-ND00-0007")
    envelopes.envelope = provider_envelope(envelopes, envelopes.application)
    envelopes.instance = adopt(envelopes, envelopes.application)
    return envelopes


def prepare(env, **overrides):
    args = dict(
        expected_digest=review.review_state(env.application)["digest"],
        source_stopped=True,
        timers_reviewed=True,
        note="Reviewed frozen source jobs and delivery history",
    )
    args.update(overrides)
    return signing_cadence.prepare(
        env.application.pk, env.instance.pk, env.user, **args
    )


def resume(env):
    staff_actions.resume(
        env.application.pk,
        env.user,
        "Verified the transfer of envelope and timer ownership",
    )


def record_reminder(env):
    env.source.event(
        env.ids["CAT-ND00-0007"],
        "sent",
        "sent",
        "signing_reminder_sent",
        80,
        agreement_id=source_record(env.application).v1_id,
    )
    import_v1(env.source)


def test_remaining_reminder_uses_original_clock_and_sends_same_envelope_once(
    timers, settings
):
    receipt = prepare(timers)
    action = PendingAction.objects.get(pk=receipt.data["action"])
    assert action.kind == "remind_signing" and action.input_ref.endswith(":1")
    assert action.due_at == business_days.after(
        signing_cadence.instant(receipt.data["quiet_since"]), 5
    )
    assert (
        ledger.claim_next({"remind_signing": signing_reminder.RemindSigning()}) is None
    )
    assert prepare(timers).pk == receipt.pk
    resume(timers)
    action.refresh_from_db()
    assert (
        action.due_at > timezone.now()
    )  # overdue import gets grace, never catch-up mail
    PendingAction.objects.filter(pk=action.pk).update(due_at=Now())
    call_command(
        "run_worker",
        only="remind_signing,send_signing_link",
        exit_when_idle=True,
        stdout=StringIO(),
    )
    action.refresh_from_db()
    assert action.status == "done"
    [message] = mail.outbox
    assert message.to == [timers.application.email] and "/sign/" in message.body
    assert (
        PendingAction.objects.filter(
            kind="lapse", subject_id=timers.application.public_ref
        ).count()
        == 1
    )
    call_command(
        "run_worker",
        only="remind_signing,send_signing_link",
        exit_when_idle=True,
        stdout=StringIO(),
    )
    assert len(mail.outbox) == 1
    assert not any(method == "POST" for method, *_ in timers.fake.requests)


@pytest.mark.parametrize("delivered_by", ["reminder", "operator_resend"])
def test_spent_allowance_does_not_repeat_and_lapse_checks_replies_before_handover(
    timers, delivered_by
):
    if delivered_by == "reminder":
        record_reminder(timers)
    else:
        signing_job(
            timers.source,
            timers.ids["CAT-ND00-0007"],
            source_record(timers.application).v1_id,
        )
        import_v1(timers.source)
    message = InboundMessage.objects.create(
        application=timers.application,
        mailbox_ref="synthetic-legacy",
        original_sha256="a" * 64,
        derived_text_sha256="b" * 64,
        status="processed",
        classification="human",
        trust_decision=association.TRUSTED,
        received_at=timezone.now() - timedelta(days=1),
    )
    receipt = prepare(timers)
    action = PendingAction.objects.get(pk=receipt.data["action"])
    assert receipt.data["delivered_followups"] == 1 and action.kind == "lapse"
    assert action.due_at == business_days.after(
        signing_cadence.instant(receipt.data["quiet_since"]), 10
    )
    assert message.received_at < action.created_at
    assert not PendingAction.objects.filter(kind="remind_signing").exists()
    resume(timers)
    PendingAction.objects.filter(pk=action.pk).update(due_at=Now())
    handler = lapse.Lapse()
    claim = ledger.claim_next({"lapse": handler})
    assert claim is not None
    handler.run(claim)
    action.refresh_from_db()
    assert action.status == "cancelled" and action.last_error == "applicant_replied"
    assert not getattr(mail, "outbox", [])


def test_uncertain_source_delivery_blocks_timer_transfer_but_unattempted_queue_can_transfer(
    timers,
):
    job = signing_job(
        timers.source,
        timers.ids["CAT-ND00-0007"],
        source_record(timers.application).v1_id,
        kind="signing_reminder",
        status="running",
    )
    for status, attempts, unknown in (
        ("running", 1, False),
        ("queued", 1, False),
        ("failed", 1, True),
    ):
        timers.source.owner.execute(
            sql.SQL(
                "UPDATE {}.job SET status=%s, attempts=%s, outcome_unknown=%s WHERE id=%s"
            ).format(sql.Identifier(timers.source.schema)),
            [status, attempts, unknown, job],
        )
        import_v1(timers.source)
        with pytest.raises(Refused, match="delivery_requires_reconciliation"):
            prepare(timers)
    assert not PendingAction.objects.filter(
        kind__in=("remind_signing", "lapse")
    ).exists()
    timers.source.owner.execute(
        sql.SQL("UPDATE {}.job SET case_id=%s WHERE id=%s").format(
            sql.Identifier(timers.source.schema)
        ),
        [timers.ids["CAT-SP00-0008"], job],
    )
    import_v1(timers.source)
    with pytest.raises(Refused, match="job_case_mismatch"):
        prepare(timers)
    timers.source.owner.execute(
        sql.SQL("UPDATE {}.job SET case_id=%s WHERE id=%s").format(
            sql.Identifier(timers.source.schema)
        ),
        [timers.ids["CAT-ND00-0007"], job],
    )
    timers.source.owner.execute(
        sql.SQL(
            "UPDATE {}.job SET status='queued', attempts=0, outcome_unknown=false, completed_at=NULL WHERE id=%s"
        ).format(sql.Identifier(timers.source.schema)),
        [job],
    )
    import_v1(timers.source)
    receipt = prepare(timers)
    assert receipt.data["delivered_followups"] == 0
    assert PendingAction.objects.get(pk=receipt.data["action"]).kind == "remind_signing"


def test_timer_handover_requires_current_review_authority_and_pause(timers):
    for change in (
        {"source_stopped": False},
        {"timers_reviewed": False},
        {"note": "short"},
        {"expected_digest": "stale"},
    ):
        with pytest.raises(Refused):
            prepare(timers, **change)
    reader = make_user(timers.committed, "legacy-timer-reader")
    with pytest.raises(PermissionDenied):
        signing_cadence.prepare(
            timers.application.pk,
            timers.instance.pk,
            reader,
            expected_digest="",
            source_stopped=True,
            timers_reviewed=True,
            note="Reviewed history",
        )
    resume(timers)
    with pytest.raises(Refused, match="paused_signing_case_required"):
        prepare(timers)
    assert not PendingAction.objects.filter(
        kind__in=("remind_signing", "lapse")
    ).exists()


def test_signed_applicant_does_not_get_another_followup(timers):
    record_reminder(timers)
    timers.envelope["recipients"][0]["signingStatus"] = "SIGNED"
    receipt = prepare(timers)
    assert (
        receipt.data["reason"] == "applicant_already_signed"
        and receipt.data["action"] is None
    )
    assert AutomationPause.objects.filter(
        subject_id=timers.application.public_ref
    ).exists()


def test_timer_form_requires_post_csrf_and_scoped_envelope(timers):
    url = reverse(
        "firstgen_staff:prepare_signing_timers", args=[timers.application.public_ref]
    )
    client = logged_in(timers.user)
    assert client.get(url).status_code == 405
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(timers.user)
    assert strict.post(url, {}).status_code == 403
    response = client.post(
        url,
        {
            "instance": "999999",
            "digest": review.review_state(timers.application)["digest"],
            "source_stopped": "yes",
            "timers_reviewed": "yes",
            "note": "<script>synthetic()</script>",
        },
    )
    assert response.status_code == 409 and "&lt;script&gt;" in response.content.decode()
    assert not PendingAction.objects.filter(
        kind__in=("remind_signing", "lapse")
    ).exists()
    response = client.post(
        url,
        {
            "instance": str(timers.instance.pk),
            "digest": review.review_state(timers.application)["digest"],
            "source_stopped": "yes",
            "timers_reviewed": "yes",
            "note": "Reviewed frozen delivery history and timer ownership",
        },
    )
    assert response.status_code == 302
    shown = client.get(response.url).content.decode()
    assert "Follow-up handover recorded" in shown and "Original due time" in shown
    assert AutomationPause.objects.filter(
        subject_id=timers.application.public_ref
    ).exists()


def test_late_source_reply_prevents_a_new_closing_note(timers):
    from tests.firstgen_v1 import new_id

    record_reminder(timers)
    timers.source.insert(
        "applicant_message",
        id=new_id(),
        case_id=timers.ids["CAT-ND00-0007"],
        direction="in",
        sent_at=timers.source.at(90),
        subject="Re: Signing",
        body_text="Synthetic reply after the reminder",
        source_key=new_id() * 2,
        created_at=timers.source.at(90),
    )
    import_v1(timers.source)
    receipt = prepare(timers)
    assert receipt.data["reason"] == "applicant_returned_after_reminder"
    assert receipt.data["action"] is None
    assert not PendingAction.objects.filter(
        kind__in=("lapse", "remind_signing")
    ).exists()


def test_timer_handover_rechecks_history_after_provider_read(timers, monkeypatch):
    from agreements import provider

    original = provider.read

    def read_and_change(envelope_id):
        result = original(envelope_id)
        record_reminder(timers)
        return result

    monkeypatch.setattr(provider, "read", read_and_change)
    with pytest.raises(Refused, match="changed_since_shown"):
        prepare(timers)
    assert not timers.application.events.filter(kind=signing_cadence.PREPARED).exists()
    assert not PendingAction.objects.filter(
        kind__in=("lapse", "remind_signing")
    ).exists()
