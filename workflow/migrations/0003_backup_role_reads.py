"""6B.6 (026 section 6, P6-D-7): the backup role may read every table except the session table.

The backup job (6B.7) connects as this role and takes one consistent snapshot. It never writes, and it never reads
`django_session` (staff session keys) - a restore makes staff sign in again anyway (026 section 6, step 5). Grants are
explicit per table, like every other role's (config.db_roles): a table created later gets nothing until its own
migration grants it, and tests/test_db_roles.py fails until it does.
"""

from django.conf import settings
from django.db import migrations

EXCLUDED = ("django_session",)


def tables(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname = current_schema() ORDER BY 1")
        return [name for (name,) in cursor.fetchall() if name not in EXCLUDED]


def grant(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    for table in tables(schema_editor):
        schema_editor.execute(f"GRANT SELECT ON TABLE {schema_editor.quote_name(table)} TO {role}")


def revoke(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    for table in tables(schema_editor):
        schema_editor.execute(f"REVOKE ALL ON TABLE {schema_editor.quote_name(table)} FROM {role}")


class Migration(migrations.Migration):
    # After every table that exists today, so the grant covers them all.
    dependencies = [
        ("workflow", "0002_role_grants"),
        ("accounts", "0003_staff_view"),
        ("applications", "0003_protect_version_adoption"),
        ("correspondence", "0016_welcome_kind"),
        ("assessments", "0008_decision_protection"),
        ("agreements", "0008_custody_and_details_protection"),
        ("provisioning", "0006_revocation_and_withdrawal_protection"),
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("sessions", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]
    operations = [migrations.RunPython(grant, revoke)]
