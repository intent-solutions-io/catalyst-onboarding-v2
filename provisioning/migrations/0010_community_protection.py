"""Community access grants, append-only receipts and erasure integration (9kg.81)."""

from django.conf import settings
from django.contrib.auth.management import create_permissions
from django.db import migrations

from config.db_roles import apply_grants
from erasure import catalog

ACCESS, RECEIPT = "provisioning_communityaccess", "provisioning_communityreceipt"
grant_forward, grant_reverse = apply_grants(
    {
        ACCESS: {
            "app": [
                "SELECT",
                "INSERT",
                "UPDATE (sealed_identity, revision, desired_roles, identity_evidence, "
                "decision_evidence, certified_evidence, leaders_evidence, reviewed_by, revoked, requires_review, "
                "verified_roles, removal_verified, updated_at)",
            ],
            "retention": ["SELECT"],
            "backup": ["SELECT"],
        },
        RECEIPT: {
            "app": ["SELECT", "INSERT"],
            "retention": ["SELECT"],
            "backup": ["SELECT"],
        },
    }
)


def rebuild(schema_editor, remove=False):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public'"
        )
        existing = {}
        for table, column in cursor.fetchall():
            if not remove or table not in (ACCESS, RECEIPT):
                existing.setdefault(table, set()).add(column)
        cursor.execute(
            "SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["retention"]]
        )
        retention = cursor.fetchone()[0]
    schema_editor.execute(catalog.checker_sql(retention, existing), params=None)
    schema_editor.execute(catalog.erase_sql(retention, existing), params=None)
    schema_editor.execute(
        catalog.erase_sql(retention, existing, replay=True), params=None
    )


def protect(apps, schema_editor):
    for table in (ACCESS, RECEIPT):
        schema_editor.execute(
            f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()"
        )
        role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
        schema_editor.execute(
            f"GRANT SELECT ON SEQUENCE public.{table}_id_seq TO {role}"
        )
    schema_editor.execute(
        f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{RECEIPT} "
        "FOR EACH ROW EXECUTE FUNCTION public.catalyst_append_only_strict()"
    )
    rebuild(schema_editor)
    config = apps.get_app_config("provisioning")
    config.models_module = True
    create_permissions(config, verbosity=0, apps=apps)  # assigned to no group


def unprotect(apps, schema_editor):
    schema_editor.execute(f"DROP TRIGGER catalyst_append_only ON public.{RECEIPT}")
    for table in (ACCESS, RECEIPT):
        schema_editor.execute(f"DROP TRIGGER catalyst_no_truncate ON public.{table}")
    rebuild(schema_editor, remove=True)


class Migration(migrations.Migration):
    dependencies = [
        ("provisioning", "0009_communityaccess_communityreceipt_and_more"),
        ("erasure", "0008_model_handoff_evidence"),
    ]
    operations = [
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(protect, unprotect),
    ]
