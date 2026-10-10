"""Database and schema facts against the real PostgreSQL test database (TEST-S1-13; ADR-17, ADR-18)."""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.core.management import call_command
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder

pytestmark = pytest.mark.django_db

# The complete, approved migration set. Updated deliberately per task: S1-T2 added the skeleton baseline
# (contrib + accounts.0001); S1-T3 added the slice data model, the role grants and history protection, and
# adoption protection (D-22).
# Anything else appearing here means unapproved schema was pulled in.
APPROVED_MIGRATIONS = {
    ("contenttypes", "0001_initial"), ("contenttypes", "0002_remove_content_type_name"),
    ("auth", "0001_initial"), ("auth", "0002_alter_permission_name_max_length"),
    ("auth", "0003_alter_user_email_max_length"), ("auth", "0004_alter_user_username_opts"),
    ("auth", "0005_alter_user_last_login_null"), ("auth", "0006_require_contenttypes_0002"),
    ("auth", "0007_alter_validators_add_error_messages"), ("auth", "0008_alter_user_username_max_length"),
    ("auth", "0009_alter_user_last_name_max_length"), ("auth", "0010_alter_group_name_max_length"),
    ("auth", "0011_update_proxy_permissions"), ("auth", "0012_alter_user_first_name_max_length"),
    ("accounts", "0001_initial"), ("accounts", "0002_role_grants"),
    ("workflow", "0001_initial"), ("workflow", "0002_role_grants"),
    ("applications", "0001_initial"), ("applications", "0002_history_protection"),
    ("applications", "0003_protect_version_adoption"),
    ("correspondence", "0001_initial"), ("correspondence", "0002_role_grants"),
}


def test_connection_is_postgresql_16_15():
    assert connection.vendor == "postgresql"
    with connection.cursor() as cursor:
        cursor.execute("select current_setting('server_version')")
        assert cursor.fetchone()[0].startswith("16.15")


def test_settings_invariants():
    assert settings.USE_TZ is True
    assert settings.TIME_ZONE == "UTC"
    assert settings.DATABASES["default"]["ATOMIC_REQUESTS"] is False
    assert settings.AUTH_USER_MODEL == "accounts.User"
    # EMAIL_BACKEND is not asserted here: pytest-django forces locmem during tests, so the configured
    # default is checked from a fresh process in test_startup.py.


def test_custom_user_model_is_in_place_and_auth_user_was_never_created():
    user_model = get_user_model()
    assert user_model._meta.label == "accounts.User"
    assert issubclass(user_model, AbstractUser)
    tables = set(connection.introspection.table_names())
    assert "accounts_user" in tables
    assert "auth_user" not in tables


def test_applied_migrations_are_exactly_the_approved_set():
    applied = set(MigrationRecorder(connection).applied_migrations())
    assert applied == APPROVED_MIGRATIONS


def test_custom_user_migration_precedes_any_dependent_migration():
    from django.db.migrations.loader import MigrationLoader

    plan = MigrationLoader(connection).graph.forwards_plan(("accounts", "0001_initial"))
    assert ("auth", "0012_alter_user_first_name_max_length") in plan
    assert plan[-1] == ("accounts", "0001_initial")


def test_models_and_migrations_are_in_sync():
    # Raises SystemExit(1) if a model change has no migration.
    call_command("makemigrations", "--check", "--dry-run", verbosity=0)


def test_no_sqlite_database_is_configured_anywhere():
    assert {c["ENGINE"] for c in settings.DATABASES.values()} == {"django.db.backends.postgresql"}
