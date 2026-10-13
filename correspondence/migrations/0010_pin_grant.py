# The application role may also update `derived_text_sha256`, written with the derivative at store time and by
# re-derivation (016 section 1, P3 span pin; P2 2B.3). Runs as the migration owner; additive and reversible.
from django.conf import settings
from django.db import migrations


def forward(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["app"])
    schema_editor.execute(f"GRANT UPDATE (derived_text_sha256) ON TABLE correspondence_inboundmessage TO {role}")


def reverse(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["app"])
    schema_editor.execute(f"REVOKE UPDATE (derived_text_sha256) ON TABLE correspondence_inboundmessage FROM {role}")


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0009_reply_processing_indexes_and_pin"),
                    ("correspondence", "0008_reply_processing_groups_and_s1_items")]
    operations = [migrations.RunPython(forward, reverse)]
