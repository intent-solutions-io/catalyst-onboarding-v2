# Least-privilege grants for the P2 inbound tables (016 sections 3.3, 3.5, 3.6; ADR-14, D-17; owner decision
# D-28) and the decision-maker's restart_collector permission (016 F, D-30). Runs as the migration owner.
#
# No role may delete any of these rows. Locations are INSERT-only. Identity and provenance columns of inbound
# messages are fixed; only status columns and the derivative (written only by re-derivation, 016 3.5) change.
# The outbound grant gains filed_copy_state (016 A4).
from django.contrib.auth.management import create_permissions
from django.db import migrations

from config.db_roles import apply_grants, grant, revoke_all

OUTBOUND_2B1 = ["SELECT", "INSERT",
                "UPDATE (status, message_id, sent_at, protocol_phase_reached, smtp_reply_code, server_accepted_at)"]
OUTBOUND_2B2 = ["SELECT", "INSERT", "UPDATE (status, message_id, sent_at, protocol_phase_reached, smtp_reply_code,"
                " server_accepted_at, filed_copy_state)"]

forward_grants, reverse_grants = apply_grants({
    "correspondence_mailboxcursor": {"app": [
        "SELECT", "INSERT",
        "UPDATE (uidvalidity, last_uid, complete_through_uid, complete_through_at, state, blocked_reason, epoch,"
        " pass_number, start_mode, last_batch_at, last_error_code, consecutive_failures, duplicates_seen)",
    ]},
    "correspondence_inboundmessage": {"app": [
        "SELECT", "INSERT",
        "UPDATE (status, classification, exception_reason, processed_at, application_id, approved_message_id,"
        " trust_decision, auth_evidence, from_matches_verified_address, identity_state, derived_text,"
        " derivation_version, redaction_version, truncated, truncated_at_chars, omitted_parts, redactions)",
    ]},
    "correspondence_inboundmessagelocation": {"app": ["SELECT", "INSERT"]},
    "correspondence_questionreplylink": {"app": ["SELECT", "INSERT", "UPDATE (state, outcome, actor_ref, updated_at)"]},
})


def outbound_forward(apps, schema_editor):
    revoke_all(schema_editor, "correspondence_outboundmessage", "app")
    grant(schema_editor, "correspondence_outboundmessage", "app", OUTBOUND_2B2)


def outbound_reverse(apps, schema_editor):
    revoke_all(schema_editor, "correspondence_outboundmessage", "app")
    grant(schema_editor, "correspondence_outboundmessage", "app", OUTBOUND_2B1)


def add_permission(apps, schema_editor):
    config = apps.get_app_config("correspondence")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    group = Group.objects.get(name="Correspondence decision-maker")
    group.permissions.add(Permission.objects.get(content_type__app_label="correspondence", codename="restart_collector"))


def remove_permission(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    group = Group.objects.filter(name="Correspondence decision-maker").first()
    if group is not None:
        group.permissions.remove(*Permission.objects.filter(content_type__app_label="correspondence", codename="restart_collector"))


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0005_inbound_collection"), ("correspondence", "0004_role_grants_and_groups")]
    operations = [
        migrations.RunPython(forward_grants, reverse_grants),
        migrations.RunPython(outbound_forward, outbound_reverse),
        migrations.RunPython(add_permission, remove_permission),
    ]
