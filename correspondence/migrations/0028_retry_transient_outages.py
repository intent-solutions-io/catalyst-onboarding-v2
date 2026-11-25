"""Carry a saved network-outage checkpoint into the normal worker retry policy."""

from django.conf import settings
from django.db import migrations


def queue_transient_outages(apps, schema_editor):
    db = schema_editor.connection.alias
    cursors = apps.get_model("correspondence", "MailboxCursor").objects.using(db)
    actions = apps.get_model("workflow", "PendingAction").objects.using(db)
    for cursor in cursors.select_for_update().filter(
        state="blocked",
        blocked_reason="unreachable",
        last_error_code="unreachable",
        uidvalidity__isnull=False,
        mailbox_ref=settings.CATALYST_MAIL_MAILBOX_REF,
        folder=settings.CATALYST_MAIL_COLLECT_FOLDER,
    ):
        number = cursor.pass_number + 1
        actions.create(
            kind="collect",
            subject_type="mailbox_cursor",
            subject_id=cursor.public_id,
            idempotency_key=f"collect:{cursor.public_id}:{number}",
            max_attempts=settings.CATALYST_MAIL_SEND_ATTEMPTS,
        )
        # Keep the old reason until a complete pass can resolve the incident.
        cursors.filter(pk=cursor.pk).update(state="recovery", pass_number=number)


class Migration(migrations.Migration):
    dependencies = [
        ("correspondence", "0027_hold_notice"),
        ("workflow", "0001_initial"),
    ]
    operations = [
        migrations.RunPython(queue_transient_outages, migrations.RunPython.noop)
    ]
