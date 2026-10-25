# 9kg.34 (026 section 6 option c; council 030 Q3 and Q4, D-51). Runs as the migration owner.
#
# public.catalyst_erase(...) is re-installed from erasure.catalog so that its result also names the key references of
# the subject's sealed custody documents (`custody_keys`) and the number of the subject's documents still stored in the
# clear (`custody_plaintext`). The erasure command destroys those keys outside the database when the registry's
# `signed_documents` row says `destroy_key` (erasure.service; agreements.keystore). Nothing else changes: the same
# signature, owner, SECURITY DEFINER, search_path and grants (CREATE OR REPLACE keeps them), the same refusals and the
# same tombstones; the map gains the envelope table, whose columns are all non-personal.
#
# The custody part sits between inline markers (erasure.catalog.CUSTODY_BEGIN and CUSTODY_END). The reverse reinstalls
# the function with that part stripped, which is byte for byte what 0002 installs, so a rollback of agreements 0010
# (which reverses this migration first) never leaves a function that reads a dropped table (data review of PR #102, K1;
# tests/test_custody_encryption.py compares the definitions).
#
# Expand-only and compatible with the previous image: the result only gains two members, which the previous command
# ignores.
#
# A later migration that adds a subject column must reinstall this function (and the checker), as PR #99 requires of
# every such migration: catalog.erase_sql generates both from the map, and the installed-function test fails until the
# reinstall is there. It reinstalls the full function, custody part included.
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


def _install(schema_editor, custody: bool):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["retention"]])
        retention = cursor.fetchone()[0]
    sql = catalog.erase_sql(retention, _existing(schema_editor))
    schema_editor.execute(sql if custody else catalog.without_custody(sql), params=None)


def reinstall(apps, schema_editor):
    _install(schema_editor, custody=True)


def strip(apps, schema_editor):
    _install(schema_editor, custody=False)


class Migration(migrations.Migration):
    dependencies = [
        ("erasure", "0002_erasure_path"),
        ("agreements", "0010_custody_envelope"),
    ]
    operations = [migrations.RunPython(reinstall, strip)]
