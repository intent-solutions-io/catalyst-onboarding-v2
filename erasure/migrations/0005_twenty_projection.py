# bgl.14 (034 rows 42 and 43). Runs as the migration owner.
#
# The Twenty link adds one subject column, `crm_twentylink.field_hashes` (class `application_identity`), and a provider
# handoff (`twenty`: the person and the applicant file note at Twenty, deleted by the owner and recorded with
# `catalyst_erase --handoff twenty`), so the generated erasure functions are reinstalled from erasure.catalog, as 0003
# and 0004 require of every such migration: the checker (`catalyst_erasure_admits`), the erase function (custody part
# included) and its replay variant. CREATE OR REPLACE keeps each function's owner, SECURITY DEFINER, search_path and
# grants. The reverse reinstalls all three as generated for the schema without the Twenty table, which is exactly what
# 0004 left.
#
# Expand-only: the functions only gain the new table, which the previous image never writes.
from django.conf import settings
from django.db import migrations

from erasure import catalog

TWENTY_TABLES = ("crm_twentylink",)


def _existing(schema_editor, without_twenty=False):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'")
        rows = cursor.fetchall()
    out = {}
    for table, column in rows:
        if without_twenty and table in TWENTY_TABLES:
            continue
        out.setdefault(table, set()).add(column)
    return out


def _install(schema_editor, without_twenty):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["retention"]])
        retention = cursor.fetchone()[0]
    existing = _existing(schema_editor, without_twenty)
    schema_editor.execute(catalog.checker_sql(retention, existing), params=None)
    schema_editor.execute(catalog.erase_sql(retention, existing), params=None)
    schema_editor.execute(catalog.erase_sql(retention, existing, replay=True), params=None)


def reinstall(apps, schema_editor):
    _install(schema_editor, without_twenty=False)


def restore(apps, schema_editor):
    _install(schema_editor, without_twenty=True)


class Migration(migrations.Migration):
    dependencies = [("erasure", "0004_erase_replay"), ("crm", "0002_grants")]
    operations = [migrations.RunPython(reinstall, restore)]
