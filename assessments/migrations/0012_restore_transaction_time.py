"""9kg.58: a restored decision cannot authorize a new transaction with a reused ID."""

from django.db import migrations

from workflow.migrations._transaction_time import refine


def forwards(apps, schema_editor):
    refine(schema_editor, "catalyst_decided_stage_needs_decision", "d", "created_at")


def backwards(apps, schema_editor):
    refine(
        schema_editor,
        "catalyst_decided_stage_needs_decision",
        "d",
        "created_at",
        reverse=True,
    )


class Migration(migrations.Migration):
    dependencies = [("assessments", "0011_model_use_approval")]
    operations = [migrations.RunPython(forwards, backwards)]
