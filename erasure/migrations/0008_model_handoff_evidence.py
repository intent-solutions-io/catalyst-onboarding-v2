"""9kg.73: queued or refused model work alone creates no provider cleanup obligation.

Reservations remain conservative evidence of possible disclosure, including abandoned calls
and reply interpretation without an assessment run. Reinstall both erasure functions without
rewriting rows, signed records, function ownership or grants.
"""

from importlib import import_module

from django.conf import settings
from django.db import migrations

from erasure import catalog

LEGACY = "EXISTS (SELECT 1 FROM public.assessments_assessmentrun r WHERE r.application_id = ANY(v_apps))"


def install(schema_editor, *, reverse):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["retention"]]
        )
        retention = cursor.fetchone()[0]
    existing = import_module("erasure.migrations.0006_twenty_projection")._existing(
        schema_editor
    )
    for replay in (False, True):
        statement = catalog.erase_sql(retention, existing, replay=replay)
        if statement.count(catalog.MODEL_PROVIDER_HANDOFF) != 1:
            raise RuntimeError("unexpected model handoff definition")
        if reverse:
            statement = statement.replace(catalog.MODEL_PROVIDER_HANDOFF, LEGACY, 1)
        schema_editor.execute(statement, params=None)


def forwards(apps, schema_editor):
    install(schema_editor, reverse=False)


def backwards(apps, schema_editor):
    install(schema_editor, reverse=True)


class Migration(migrations.Migration):
    dependencies = [("erasure", "0007_orphan_replay_lookup")]
    operations = [migrations.RunPython(forwards, backwards)]
