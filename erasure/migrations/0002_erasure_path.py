# 9kg.32 (029 section 6.2; council 030 Q3, D-51; ADR-14 pattern). Runs as the migration owner.
#
# The authorized erasure path, in the database:
#
# 1. The erasure audit (0001) is append-only and cannot be truncated, for every role; a BEFORE INSERT trigger sets its
#    transaction id, time and login, so none can be supplied. The retention and backup roles read it; nobody else
#    has any privilege on it.
# 2. public.catalyst_erasure_admits(table, old, new), SECURITY DEFINER, owner-only EXECUTE: true only when the session
#    login is a member of the retention role, an erasure audit row carries the current transaction id (the
#    agreements 0004 pattern), and the change is confined to the table's allow-list of subject columns with every
#    changed column set to its tombstone (the 0015 tuple compare, over the whole row: every column outside the
#    allow-list, `applications_applicationevent.created_txid` included, must be unchanged). Generated from
#    erasure.catalog.
# 3. Each guarded trigger function (erasure.catalog.GUARDED_FUNCTIONS) gains one branch right after its first BEGIN,
#    by CREATE OR REPLACE of its own current definition; the reverse removes exactly that branch. The row triggers that
#    used the strict refusal on a table with subject columns move to catalyst_erasable_append_only (the same refusal
#    with the branch). The strict function itself, the adoption record's trigger and every no-truncate trigger are
#    untouched, and so is the pause-row DELETE guard (catalyst_pause_resume_guard): erasure anonymizes a pause's
#    reason and never deletes the pause, so a restriction is never lifted on this path.
# 4. public.catalyst_erase(subject, authority, reason, classes), SECURITY DEFINER, EXECUTE for the retention role
#    only (never the application, fetcher or backup role, never PUBLIC).
#
# Stated limitations, as for every ADR-14 guard: the owner can replace or disable these functions and triggers, and a
# superuser bypasses them. A later migration that replaces a guarded function must keep the branch (the catalog test
# in tests/test_erasure.py fails otherwise), and one that adds a subject column re-installs the two generated functions.
from django.conf import settings
from django.db import migrations

from config.db_roles import apply_grants
from erasure import catalog

AUDIT = "erasure_erasureaudit"

grant_forward, grant_reverse = apply_grants({AUDIT: {"retention": ["SELECT"], "backup": ["SELECT"]}})


def _retention_literal(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["retention"]])
        return cursor.fetchone()[0]


def _existing(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'")
        rows = cursor.fetchall()
    out = {}
    for table, column in rows:
        out.setdefault(table, set()).add(column)
    return out


def _definition(schema_editor, name):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT pg_get_functiondef(p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
                       " WHERE n.nspname = 'public' AND p.proname = %s AND p.pronargs = 0", [name])
        return cursor.fetchone()[0]


def backup_sequence(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    schema_editor.execute(f"GRANT SELECT ON SEQUENCE public.{AUDIT}_id_seq TO {role}")


def no_backup_sequence(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    schema_editor.execute(f"REVOKE ALL ON SEQUENCE public.{AUDIT}_id_seq FROM {role}")


def protect_audit(apps, schema_editor):
    schema_editor.execute(catalog.AUDIT_TXID_SQL, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_erasure_audit_txid() FROM PUBLIC")
    schema_editor.execute(f"CREATE TRIGGER catalyst_erasure_audit_txid BEFORE INSERT ON public.{AUDIT} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_erasure_audit_txid()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{AUDIT} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_append_only_strict()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{AUDIT} "
                          "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect_audit(apps, schema_editor):
    for trigger in ("catalyst_no_truncate", "catalyst_append_only", "catalyst_erasure_audit_txid"):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {trigger} ON public.{AUDIT}")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_erasure_audit_txid()")


def install(apps, schema_editor):
    retention, existing = _retention_literal(schema_editor), _existing(schema_editor)
    schema_editor.execute(catalog.checker_sql(retention, existing), params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_erasure_admits(text, jsonb, jsonb) FROM PUBLIC")
    schema_editor.execute(catalog.erasable_append_only_sql(retention), params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_erasable_append_only() FROM PUBLIC")
    for table, trigger in catalog.ERASABLE_STRICT:
        schema_editor.execute(f"DROP TRIGGER {trigger} ON public.{table}")
        schema_editor.execute(f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON public.{table} "
                              "FOR EACH ROW EXECUTE FUNCTION public.catalyst_erasable_append_only()")
    for name in catalog.GUARDED_FUNCTIONS:  # CREATE OR REPLACE keeps the owner, the attributes and the grants
        schema_editor.execute(catalog.with_branch(_definition(schema_editor, name), retention), params=None)
    schema_editor.execute(catalog.erase_sql(retention, existing), params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_erase(uuid, text, text, text[]) FROM PUBLIC")
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["retention"])
    schema_editor.execute(f"GRANT EXECUTE ON FUNCTION public.catalyst_erase(uuid, text, text, text[]) TO {role}")


def uninstall(apps, schema_editor):
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_erase(uuid, text, text, text[])")
    for name in catalog.GUARDED_FUNCTIONS:  # by the branch's markers, so the role literal it was written with is moot
        schema_editor.execute(catalog.without_branch(_definition(schema_editor, name)), params=None)
    for table, trigger in catalog.ERASABLE_STRICT:
        schema_editor.execute(f"DROP TRIGGER {trigger} ON public.{table}")
        schema_editor.execute(f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON public.{table} "
                              "FOR EACH ROW EXECUTE FUNCTION public.catalyst_append_only_strict()")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_erasable_append_only()")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_erasure_admits(text, jsonb, jsonb)")


class Migration(migrations.Migration):
    dependencies = [
        ("erasure", "0001_initial"),
        # Every table the erasure map names, at its latest migration, so every guarded function exists.
        ("accounts", "0007_staff_role_grants"),
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("agreements", "0009_staff_groups"),
        ("applications", "0009_tombstone_keys_unique"),
        ("assessments", "0010_decision_inputs_and_human_only_code"),
        ("correspondence", "0019_decline_notice"),
        ("provisioning", "0007_staff_groups"),
        ("workflow", "0005_pause_resume_guard"),
    ]
    operations = [
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(backup_sequence, no_backup_sequence),
        migrations.RunPython(protect_audit, unprotect_audit),
        migrations.RunPython(install, uninstall),
    ]
