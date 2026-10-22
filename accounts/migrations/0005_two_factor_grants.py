"""6B.9 (026 section 8, P6-D-3): least-privilege grants for staff two-factor and login throttling.

django-otp saves a device with a full-row UPDATE when a token is verified (its counters and timestamps), so the
application role needs UPDATE on every column; a trigger then refuses any change by that role to what identifies the
device (its user, name, key, confirmation and parameters). Devices are created and removed only by the owner
(`enroll_staff_two_factor`, `reset_staff_two_factor`); the application role may delete a recovery code, which is how
a used code is spent, and a stale throttle row (the hourly clean-up). The backup role reads the throttle table but none of the two-factor tables: TOTP keys and
recovery codes are credentials, so a restore always means re-enrolling (config.backup.EXCLUDED_TABLES).
"""

from django.conf import settings
from django.db import migrations

from config.db_roles import apply_grants

TOTP_MUTABLE = ["drift", "last_t", "throttling_failure_timestamp", "throttling_failure_count", "last_used_at"]
STATIC_MUTABLE = ["throttling_failure_timestamp", "throttling_failure_count", "last_used_at"]

grant_forward, grant_reverse = apply_grants({
    "otp_totp_totpdevice": {"app": ["SELECT", "UPDATE"]},
    "otp_static_staticdevice": {"app": ["SELECT", "UPDATE"]},
    "otp_static_statictoken": {"app": ["SELECT", "DELETE"]},
    "accounts_loginthrottle": {"app": ["SELECT", "INSERT", "UPDATE (failures, locked_until, updated_at)", "DELETE"],
                               "backup": ["SELECT"]},
})
CREDENTIAL_TABLES = ("otp_totp_totpdevice", "otp_static_staticdevice", "otp_static_statictoken")


def backup_access(apps, schema_editor):
    """Whatever order the apps migrated in, the backup role reads no credential table, but every sequence (pg_dump
    reads each value; 6B.6)."""
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    for table in CREDENTIAL_TABLES:
        schema_editor.execute(f"REVOKE ALL ON TABLE public.{table} FROM {role}")
    for table in (*CREDENTIAL_TABLES, "accounts_loginthrottle"):
        schema_editor.execute(f"GRANT SELECT ON SEQUENCE public.{table}_id_seq TO {role}")


def no_backup_access(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    for table in (*CREDENTIAL_TABLES, "accounts_loginthrottle"):
        schema_editor.execute(f"REVOKE ALL ON SEQUENCE public.{table}_id_seq FROM {role}")


def protect(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["app"]])
        app_literal = cursor.fetchone()[0]
    schema_editor.execute(f"""
        CREATE FUNCTION public.catalyst_otp_device_fixed() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF pg_catalog.pg_has_role(session_user, {app_literal}, 'MEMBER')
             AND (pg_catalog.to_jsonb(NEW) - TG_ARGV::text[]) IS DISTINCT FROM (pg_catalog.to_jsonb(OLD) - TG_ARGV::text[]) THEN
            RAISE EXCEPTION 'two-factor device: only its counters may change for the application role'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_otp_device_fixed() FROM PUBLIC")
    for table, mutable in (("otp_totp_totpdevice", TOTP_MUTABLE), ("otp_static_staticdevice", STATIC_MUTABLE)):
        args = ", ".join(f"'{c}'" for c in mutable)
        schema_editor.execute(f"CREATE TRIGGER catalyst_otp_device_fixed BEFORE UPDATE ON public.{table}"
                              f" FOR EACH ROW EXECUTE FUNCTION public.catalyst_otp_device_fixed({args})")


def unprotect(apps, schema_editor):
    for table in ("otp_totp_totpdevice", "otp_static_staticdevice"):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_otp_device_fixed ON public.{table}")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_otp_device_fixed()")


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0004_login_throttle"),
        ("otp_totp", "0003_add_timestamps"),
        ("otp_static", "0003_add_timestamps"),
        ("workflow", "0003_backup_role_reads"),
    ]
    operations = [migrations.RunPython(grant_forward, grant_reverse), migrations.RunPython(protect, unprotect),
                  migrations.RunPython(backup_access, no_backup_access)]
