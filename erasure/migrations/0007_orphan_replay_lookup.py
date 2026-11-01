"""9kg.71: narrow recovery reads, and replay of orphan rows beside tombstoned identities.

Only the normalized sender and hashed counter key become readable to the retention login.
No message body, attachment, mutation privilege or erasure key enters the database.
Existing rows and function signatures are preserved; the previous image remains compatible.
"""

from importlib import import_module

from django.conf import settings
from django.db import migrations

from erasure import catalog


def install(schema_editor, *, reverse):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["retention"])
    for table, column in (
        ("correspondence_inboundmessage", "from_normalized"),
        ("accounts_requestthrottle", "key"),
    ):
        if reverse:
            schema_editor.execute(
                f"REVOKE SELECT ({column}) ON public.{table} FROM {role}"
            )
        else:
            schema_editor.execute(
                f"GRANT SELECT ({column}) ON public.{table} TO {role}"
            )
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["retention"]]
        )
        retention = cursor.fetchone()[0]
    existing = import_module("erasure.migrations.0006_twenty_projection")._existing(
        schema_editor
    )
    statement = catalog.erase_sql(retention, existing, replay=True)
    if reverse:
        statement = statement.replace(catalog.REPLAY_ORPHAN_KEY, "")
    schema_editor.execute(statement, params=None)


def forwards(apps, schema_editor):
    install(schema_editor, reverse=False)


def backwards(apps, schema_editor):
    install(schema_editor, reverse=True)


class Migration(migrations.Migration):
    dependencies = [("erasure", "0006_twenty_projection")]
    operations = [migrations.RunPython(forwards, backwards)]
