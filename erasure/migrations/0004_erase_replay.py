# 9kg.25 (026 section 6 option d; 029 section 6.2.1). Runs as the migration owner.
#
# public.catalyst_erase_replay(...) is installed from erasure.catalog (`erase_sql(..., replay=True)`): the erase
# function under its own name, without the refusals for an open application, work in flight and an access revocation
# that is not final. Only `catalyst_erasure_replay` calls it, after a restore, to re-apply an erasure the durable record
# names: that erasure passed those refusals when it ran, while the restored rows are as they were before the person
# was closed out. Everything else is the erase function's: the retention-login check, the audit row of the
# transaction, the tombstones each protective trigger admits, the custody part (key references only; nothing is
# destroyed here). SECURITY DEFINER, owned by the owner, EXECUTE for the retention role only.
#
# Expand-only: a new function, nothing the previous image calls. The reverse drops it.
#
# A later migration that adds a subject column reinstalls this function beside catalyst_erase and the checker
# (catalog.erase_sql generates both; the installed-function test compares each with the map).
from django.conf import settings
from django.db import migrations

from erasure import catalog

SIGNATURE = "public.catalyst_erase_replay(uuid, text, text, text[])"


def _existing(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'")
        rows = cursor.fetchall()
    out = {}
    for table, column in rows:
        out.setdefault(table, set()).add(column)
    return out


def install(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["retention"]])
        retention = cursor.fetchone()[0]
    schema_editor.execute(catalog.erase_sql(retention, _existing(schema_editor), replay=True), params=None)
    schema_editor.execute(f"REVOKE ALL ON FUNCTION {SIGNATURE} FROM PUBLIC")
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["retention"])
    schema_editor.execute(f"GRANT EXECUTE ON FUNCTION {SIGNATURE} TO {role}")


def uninstall(apps, schema_editor):
    schema_editor.execute(f"DROP FUNCTION IF EXISTS {SIGNATURE}")


class Migration(migrations.Migration):
    dependencies = [("erasure", "0003_custody_keys")]
    operations = [migrations.RunPython(install, uninstall)]
