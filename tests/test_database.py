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
    ("workflow", "0001_initial"), ("workflow", "0002_role_grants"), ("workflow", "0003_backup_role_reads"),  # 6B.6
    ("workflow", "0004_restore_hold_protection"),  # 6B.7a
    ("applications", "0001_initial"), ("applications", "0002_history_protection"),
    ("applications", "0003_protect_version_adoption"),
    ("correspondence", "0001_initial"), ("correspondence", "0002_role_grants"),
    # S1-T7: Django Admin's log, database sessions, and the staff grants and read-only group.
    ("admin", "0001_initial"), ("admin", "0002_logentry_remove_auto_add"), ("admin", "0003_logentry_add_action_flag_choices"),
    ("sessions", "0001_initial"), ("accounts", "0003_staff_view"),
    # P2 2B.1 (owner decisions D-27 to D-30): outbound foundations, their grants, the P2 role groups.
    ("correspondence", "0003_outbound_foundations"), ("correspondence", "0004_role_grants_and_groups"),
    # P2 2B.2: inbound collection, its grants and the decision-maker's restart_collector permission.
    ("correspondence", "0005_inbound_collection"), ("correspondence", "0006_inbound_grants"),
    # P2 2B.3: reply-processing permissions, and open staff items for earlier S1 attention events.
    ("correspondence", "0007_reply_processing_permissions"), ("correspondence", "0008_reply_processing_groups_and_s1_items"),
    ("correspondence", "0009_reply_processing_indexes_and_pin"), ("correspondence", "0010_pin_grant"),
    ("correspondence", "0011_reminders_and_staff_messages"), ("correspondence", "0012_reminder_and_staff_message_grants"),
    ("assessments", "0001_initial"), ("assessments", "0002_grants_protection_and_groups"),
    ("assessments", "0003_same_application_keys"), ("assessments", "0004_assessment_runs"),
    ("assessments", "0005_assessment_grants_and_protection"),
    ("correspondence", "0013_clarification_and_interpretation"), ("correspondence", "0014_interpretation_grants"),
    ("assessments", "0006_author_question_permission"), ("assessments", "0007_qualification_decision"),
    ("assessments", "0008_decision_protection"),
    ("agreements", "0001_initial"), ("agreements", "0002_protection_and_types"),  # P4 4B.1
    ("agreements", "0003_provider_observations"), ("agreements", "0004_observation_protection_and_verification"),  # 4B.2
    ("agreements", "0005_stop_intent_and_replacement"), ("agreements", "0006_stop_intent_and_replacement_protection"),  # D-42, D-43
    ("agreements", "0007_custody_and_details"), ("agreements", "0008_custody_and_details_protection"),  # 4B.3
    ("correspondence", "0015_evidence_protection"),  # 9kg.1
    ("provisioning", "0001_provisioning_records"), ("provisioning", "0002_provisioning_protection"),  # P5 5B.1
    ("correspondence", "0016_welcome_kind"),  # 5B.2
    ("correspondence", "0017_provenance_freezes"),  # 9kg.5 (internal-launch batch item 6)
    ("provisioning", "0003_credential_setup"), ("provisioning", "0004_credential_setup_protection"),
    ("provisioning", "0005_revocation_and_withdrawal"), ("provisioning", "0006_revocation_and_withdrawal_protection"),  # 5B.3
    # 6B.9: django-otp's TOTP and recovery-code tables, the login throttle, their grants and device protection.
    ("otp_totp", "0001_initial"), ("otp_totp", "0002_auto_20190420_0723"), ("otp_totp", "0003_add_timestamps"),
    ("otp_static", "0001_initial"), ("otp_static", "0002_throttling"), ("otp_static", "0003_add_timestamps"),
    ("accounts", "0004_login_throttle"), ("accounts", "0005_two_factor_grants"),
    ("assessments", "0009_fetcher_role_grants"),  # 9kg.24: the evidence fetcher's own narrower role
    ("accounts", "0006_request_throttle"),  # 9kg.29: the public-endpoint throttle buckets
    ("applications", "0004_invitation"), ("applications", "0005_invitation_protection"),  # 9kg.43: invitation-only intake
    ("applications", "0006_event_txid"), ("workflow", "0005_pause_resume_guard"),  # 9kg.6: the pause-row guard
    # 9kg.30: the append-only staff role grant record and the P4 and P5 role groups (accounts.roles)
    ("accounts", "0007_staff_role_grants"), ("agreements", "0009_staff_groups"), ("provisioning", "0007_staff_groups"),
    ("assessments", "0010_decision_inputs_and_human_only_code"),  # oc4.12: what a decision records, completed
    ("applications", "0007_notice_record_and_member_on_file"), ("applications", "0008_member_on_file_protection"),  # 9kg.52
    ("correspondence", "0018_intake_notice_templates"),  # 9kg.52: the data notice and invitation templates
    # 9kg.32: the tombstone keys held unique, the erasure audit, and the erasure functions and trigger branches
    ("applications", "0009_tombstone_keys_unique"), ("erasure", "0001_initial"), ("erasure", "0002_erasure_path"),
    ("correspondence", "0019_decline_notice"),  # oc4.11: the decline kind and template; held send_decline cancelled
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
