"""Append-only protection for the protected history tables and the audited retention path (ADR-14, D-17).

Protected: applications_submissionversion and applications_applicationevent. The application role may
only SELECT and INSERT them (privileges); a trigger refuses UPDATE, DELETE and TRUNCATE to every role,
including the migration owner, except one path: a DELETE by a member of the retention role that has set
`catalyst.retention_reason`, which the trigger records in applications_retentionaudit. That audit table
is itself unchangeable. The capability exists; no real retention or deletion is enabled (POL-10 open).

The trigger functions are owned by the migration owner, run with a fixed search_path (public, pg_temp)
and schema-qualified names, and EXECUTE is revoked from PUBLIC. Stated limitations (ADR-14): the owner
can disable the triggers, and a superuser bypasses everything; migrations need review for trigger changes.
"""

from django.conf import settings
from django.db import migrations

from config.db_roles import apply_grants

PROTECTED = ("applications_submissionversion", "applications_applicationevent")
AUDIT = "applications_retentionaudit"

grant_forward, grant_reverse = apply_grants({
    "applications_application": {"app": ["SELECT", "INSERT", "UPDATE"], "retention": ["SELECT"]},
    "applications_submissionversion": {"app": ["SELECT", "INSERT"], "retention": ["SELECT", "DELETE"]},
    "applications_applicationevent": {"app": ["SELECT", "INSERT"], "retention": ["SELECT", "DELETE"]},
    "applications_versionadoption": {"app": ["SELECT", "INSERT"]},
    "applications_contactchallenge": {"app": ["SELECT", "INSERT", "UPDATE"]},
    AUDIT: {"retention": ["SELECT"]},
})


def protect(apps, schema_editor):
    q = schema_editor.quote_name
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["retention"]])
        retention_literal = cursor.fetchone()[0]
    schema_editor.execute(f"""
        CREATE FUNCTION public.catalyst_history_append_only() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'DELETE'
             AND pg_catalog.pg_has_role(session_user, {retention_literal}, 'MEMBER')
             AND coalesce(pg_catalog.current_setting('catalyst.retention_reason', true), '') <> '' THEN
            INSERT INTO public.{AUDIT} (at, actor, table_name, row_id, reason)
              VALUES (pg_catalog.now(), session_user, TG_TABLE_NAME, OLD.id,
                      pg_catalog.current_setting('catalyst.retention_reason'));
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'append-only: % on % refused for %', TG_OP, TG_TABLE_NAME, session_user
            USING ERRCODE = 'insufficient_privilege';
        END $$
    """, params=None)  # params=None: the RAISE format's % signs are not query placeholders
    schema_editor.execute(f"""
        CREATE FUNCTION public.catalyst_append_only_strict() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          RAISE EXCEPTION 'append-only: % on % refused', TG_OP, TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
        END $$
    """, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_history_append_only() FROM PUBLIC")
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_append_only_strict() FROM PUBLIC")
    for table in PROTECTED:
        schema_editor.execute(
            f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{q(table)} "
            "FOR EACH ROW EXECUTE FUNCTION public.catalyst_history_append_only()"
        )
    for table in (*PROTECTED, AUDIT):
        schema_editor.execute(
            f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{q(table)} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()"
        )
    schema_editor.execute(
        f"CREATE TRIGGER catalyst_audit_immutable BEFORE UPDATE OR DELETE ON public.{q(AUDIT)} "
        "FOR EACH ROW EXECUTE FUNCTION public.catalyst_append_only_strict()"
    )


def unprotect(apps, schema_editor):
    q = schema_editor.quote_name
    for table in PROTECTED:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_append_only ON public.{q(table)}")
    for table in (*PROTECTED, AUDIT):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{q(table)}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_audit_immutable ON public.{q(AUDIT)}")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_history_append_only()")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_append_only_strict()")


class Migration(migrations.Migration):
    dependencies = [("applications", "0001_initial")]
    operations = [
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(protect, unprotect),
    ]
