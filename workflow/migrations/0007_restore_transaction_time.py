"""9kg.58: a restored resume event cannot authorize a new transaction with a reused ID."""

from django.db import migrations

from workflow.migrations._transaction_time import refine


def forwards(apps, schema_editor):
    refine(schema_editor, "catalyst_pause_resume_guard", "e", "occurred_at")


def backwards(apps, schema_editor):
    refine(
        schema_editor, "catalyst_pause_resume_guard", "e", "occurred_at", reverse=True
    )


class Migration(migrations.Migration):
    dependencies = [("workflow", "0006_restore_hold_insert_guard")]
    operations = [migrations.RunPython(forwards, backwards)]
