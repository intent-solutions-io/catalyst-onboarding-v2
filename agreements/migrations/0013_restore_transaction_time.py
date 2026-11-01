"""9kg.58: a restored provider read cannot verify signing in a new transaction with a reused ID."""

from django.db import migrations

from workflow.migrations._transaction_time import refine


def forwards(apps, schema_editor):
    refine(schema_editor, "catalyst_agreement_verified_needs_read", "o", "observed_at")


def backwards(apps, schema_editor):
    refine(
        schema_editor,
        "catalyst_agreement_verified_needs_read",
        "o",
        "observed_at",
        reverse=True,
    )


class Migration(migrations.Migration):
    dependencies = [("agreements", "0012_countersign_claim")]
    operations = [migrations.RunPython(forwards, backwards)]
