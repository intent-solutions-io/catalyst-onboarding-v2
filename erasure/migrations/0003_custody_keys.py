# 9kg.34 (026 section 6 option c; council 030 Q3 and Q4, D-51). Runs as the migration owner.
#
# public.catalyst_erase(...) is re-installed from erasure.catalog so that its result also names the key references of
# the subject's sealed custody documents (`custody_keys`) and the number of the subject's documents still stored in the
# clear (`custody_plaintext`). The erasure command destroys those keys outside the database when the registry's
# `signed_documents` row says `destroy_key` (erasure.service; agreements.keystore). Nothing else changes: the same
# signature, owner, SECURITY DEFINER, search_path and grants (CREATE OR REPLACE keeps them), the same refusals and the
# same tombstones; the map gains the envelope table, whose columns are all non-personal.
#
# Expand-only and compatible with the previous image: the result only gains two members, which the previous command
# ignores. The reverse leaves the function as it is (a superset of 0002's: an older command reads only the members it
# knows); reversing past 0002 drops it as before.
from django.conf import settings
from django.db import migrations

from erasure import catalog


def _existing(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'")
        rows = cursor.fetchall()
    out = {}
    for table, column in rows:
        out.setdefault(table, set()).add(column)
    return out


def reinstall(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["retention"]])
        retention = cursor.fetchone()[0]
    schema_editor.execute(catalog.erase_sql(retention, _existing(schema_editor)), params=None)


class Migration(migrations.Migration):
    dependencies = [
        ("erasure", "0002_erasure_path"),
        ("agreements", "0010_custody_envelope"),
    ]
    operations = [migrations.RunPython(reinstall, migrations.RunPython.noop)]
