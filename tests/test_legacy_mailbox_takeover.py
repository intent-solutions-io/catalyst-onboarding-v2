"""Rehearse imported-thread collection across the cutover boundary and a later IMAP epoch change."""

from correspondence import inbound
from correspondence.models import InboundMessage, InboundMessageLocation, StaffItem
from firstgen.models import ImportedRecord
from tests.test_inbound import collect, reply, tls  # noqa: F401
from tests.test_legacy_review import app, legacy, v1  # noqa: F401
from tests.test_mailbox_takeover import start, the_cursor, unset  # noqa: F401
from tests.test_outbound import p2, ready  # noqa: F401
from workflow.models import AutomationPause


def test_imported_thread_takeover_never_replays_v1_mail_after_a_completed_pass(
    legacy, unset
):
    application = app()
    prior = ImportedRecord.objects.get(
        application=application, v1_table="outbound_message"
    )
    assert prior.message_id
    old = reply(
        None,
        sender=application.email_key,
        in_reply_to=prior.message_id,
        body="Historical reply already processed by v1.",
    )
    unset.imap.deliver(old)
    new = reply(
        None,
        sender=application.email_key,
        in_reply_to=prior.message_id,
        body="New reply after the frozen source cursor.",
    )
    first_new = unset.imap.deliver(new)
    validity = unset.imap.folders["INBOX"].uidvalidity
    start("--from-uid", str(first_new), "--uidvalidity", str(validity))
    collect()
    [message] = InboundMessage.objects.all()
    assert message.application_id == application.pk
    assert message.trust_decision == "trusted"
    assert message.approved_message_id is None
    assert AutomationPause.objects.filter(subject_id=application.public_ref).exists()
    assert the_cursor().complete_through_at is not None
    assert list(InboundMessageLocation.objects.values_list("uid", flat=True)) == [
        first_new
    ]
    assert not unset.server.messages

    # A later mailbox rebuild is not evidence that v1 history became unprocessed.
    # v2 has no MIME digest for old, so its normal resync deduplication cannot protect it.
    fetches = len(unset.imap.fetches)
    unset.imap.renumber()
    late = unset.imap.deliver(
        reply(
            None,
            sender=application.email_key,
            in_reply_to=prior.message_id,
            body="Reply during epoch review.",
        )
    )
    collect()
    cursor = the_cursor()
    assert (cursor.state, cursor.blocked_reason) == (
        "blocked",
        inbound.TAKEOVER_VALIDITY,
    )
    assert (cursor.uidvalidity, cursor.last_uid) == (validity, first_new)
    assert len(unset.imap.fetches) == fetches
    assert InboundMessage.objects.count() == 1
    assert StaffItem.objects.filter(
        reason_code="collector_blocked", status="open"
    ).exists()

    # A reviewed boundary in the NEW epoch may replay v2's own known message;
    # deduplication retains it once and collection reaches mail that arrived during the hold.
    start(
        "--from-uid",
        str(first_new),
        "--uidvalidity",
        str(unset.imap.folders["INBOX"].uidvalidity),
        "--override",
    )
    collect()
    assert InboundMessage.objects.count() == 2
    assert InboundMessageLocation.objects.count() == 3
    assert the_cursor().last_uid == late and the_cursor().state == "ok"
    assert the_cursor().duplicates_seen == 1
    assert not InboundMessage.objects.filter(
        derived_text__contains="Historical reply"
    ).exists()
    assert not unset.server.messages
