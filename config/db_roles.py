"""Least-privilege grants for the three database roles (ADR-14, D-17).

Used by each app's grant migration, which runs as the migration owner. Role names come from settings
(CATALYST_DB_ROLES); roles themselves are provisioned outside the application (scripts/provision_db_roles.py).
Grants are explicit per table: no default privileges, so a new table gets nothing until a migration says so.
UPDATE is column-level where possible ("UPDATE (col, col)"), so identity and audit columns stay fixed; code
that writes these tables must use update_fields or QuerySet.update, never a full-row save.
"""

from django.conf import settings


def _q(schema_editor, name):
    return schema_editor.quote_name(name)


def _id_sequence(cursor, table):
    """The sequence behind the table's `id` column, or None (django_session, for one, has no `id`)."""
    cursor.execute(
        "SELECT pg_get_serial_sequence(%s, 'id') FROM information_schema.columns"
        " WHERE table_schema = current_schema() AND table_name = %s AND column_name = 'id'", [table, table])
    return cursor.fetchone()


def grant(schema_editor, table, role_key, privileges):
    role = settings.CATALYST_DB_ROLES[role_key]
    schema_editor.execute(f"GRANT {', '.join(privileges)} ON TABLE {_q(schema_editor, table)} TO {_q(schema_editor, role)}")
    # Identity columns draw from a sequence; INSERT needs USAGE on it.
    if any(p.startswith("INSERT") for p in privileges):
        with schema_editor.connection.cursor() as cursor:
            row = _id_sequence(cursor, table)
        if row and row[0]:
            schema_editor.execute(f"GRANT USAGE ON SEQUENCE {row[0]} TO {_q(schema_editor, role)}")


def revoke_all(schema_editor, table, role_key):
    role = settings.CATALYST_DB_ROLES[role_key]
    schema_editor.execute(f"REVOKE ALL ON TABLE {_q(schema_editor, table)} FROM {_q(schema_editor, role)}")
    with schema_editor.connection.cursor() as cursor:
        row = _id_sequence(cursor, table)
    if row and row[0]:
        schema_editor.execute(f"REVOKE ALL ON SEQUENCE {row[0]} FROM {_q(schema_editor, role)}")


def apply_grants(grants):
    """Build forward and reverse RunPython functions from {table: {role_key: [privileges]}}."""

    def forward(apps, schema_editor):
        for table, by_role in grants.items():
            for role_key, privileges in by_role.items():
                grant(schema_editor, table, role_key, privileges)

    def reverse(apps, schema_editor):
        for table, by_role in grants.items():
            for role_key in by_role:
                revoke_all(schema_editor, table, role_key)

    return forward, reverse
