"""VersionAdoption is protected history (D-22): it records which version the verified address owner
explicitly adopted, so it is as unchangeable as the versions themselves.

The strict function from 0002 (catalyst_append_only_strict) refuses UPDATE, DELETE and TRUNCATE on
applications_versionadoption to every role, including the migration owner. There is no retention
exception and no new grant: the application role keeps SELECT and INSERT only, and the retention role
gets nothing (POL-10 stays open and must cover adoptions with their versions, challenges and audit).
The same-application foreign keys from 0001 are unchanged. Stated limitations as in 0002: the owner can
disable or drop these triggers and a superuser bypasses them.
"""

from django.db import migrations

TABLE = "applications_versionadoption"


def protect(apps, schema_editor):
    q = schema_editor.quote_name(TABLE)
    schema_editor.execute(
        f"CREATE TRIGGER catalyst_adoption_immutable BEFORE UPDATE OR DELETE ON public.{q} "
        "FOR EACH ROW EXECUTE FUNCTION public.catalyst_append_only_strict()"
    )
    schema_editor.execute(
        f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{q} "
        "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()"
    )


def unprotect(apps, schema_editor):
    q = schema_editor.quote_name(TABLE)
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_adoption_immutable ON public.{q}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{q}")


class Migration(migrations.Migration):
    dependencies = [("applications", "0002_history_protection")]
    operations = [migrations.RunPython(protect, unprotect)]
