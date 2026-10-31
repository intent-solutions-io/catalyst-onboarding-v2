# bgl.16 (035). Runs as the migration owner.
#
# The first-generation import adds one subject column, `firstgen_importedrecord.data` (class `history_events`), so the
# generated erasure functions are reinstalled from erasure.catalog, as 0003 and 0004 require of every such migration:
# the checker (`catalyst_erasure_admits`), the erase function (custody part included) and its replay variant. CREATE OR
# REPLACE keeps each function's owner, SECURITY DEFINER, search_path and grants. The reverse reinstalls all three as
# generated for the schema without the import tables, which is exactly what 0004 left.
#
# Expand-only: the functions only gain the import table, which the previous image never writes.
from django.conf import settings
from django.db import migrations

from erasure import catalog

IMPORT_TABLES = ("firstgen_importedcase", "firstgen_importedrecord", "firstgen_importrun")
# Tables whose coverage a later erasure migration adds (0006, the Twenty link, bgl.14). Its table exists while this
# migration is reversed (crm depends on erasure 0004 only), so the reverse leaves it out too: what 0004 left covers
# neither the import nor the Twenty link.
LATER_TABLES = ("crm_twentylink",)


def _existing(schema_editor, without_import=False):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'")
        rows = cursor.fetchall()
    out = {}
    for table, column in rows:
        if without_import and table in (*IMPORT_TABLES, *LATER_TABLES):
            continue
        out.setdefault(table, set()).add(column)
    return out


def _install(schema_editor, without_import):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["retention"]])
        retention = cursor.fetchone()[0]
    existing = _existing(schema_editor, without_import)
    schema_editor.execute(catalog.checker_sql(retention, existing), params=None)
    schema_editor.execute(catalog.erase_sql(retention, existing), params=None)
    schema_editor.execute(catalog.erase_sql(retention, existing, replay=True), params=None)


def reinstall(apps, schema_editor):
    _install(schema_editor, without_import=False)


def restore(apps, schema_editor):
    _install(schema_editor, without_import=True)


class Migration(migrations.Migration):
    dependencies = [("erasure", "0004_erase_replay"), ("firstgen", "0002_protection")]
    operations = [migrations.RunPython(reinstall, restore)]
