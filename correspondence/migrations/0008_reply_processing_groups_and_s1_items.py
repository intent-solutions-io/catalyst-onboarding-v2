# P2 2B.3 (016 F and 3.8; owner decisions D-28 A-2, D-30, D-31). Runs as the migration owner.
#
# 1. The role matrix gains the 2B.3 permissions: operators confirm question outcomes and resolve non-identity
#    items; the decision-maker also resolves identity-affecting items. Frozen literal map (later tasks add theirs).
# 2. Every earlier S1 `needs_staff_attention` event gets one open staff item (dedupe `event:<id>`), so staff
#    attention now reads open items and resolving an item clears the mark. The events stay as history.
from django.contrib.auth.management import create_permissions
from django.db import migrations

ADDED = {
    "Correspondence operator": ["confirm_question_outcome", "resolve_exception"],
    "Correspondence decision-maker": ["confirm_question_outcome", "resolve_exception", "resolve_identity_exception"],
}


def add_permissions(apps, schema_editor):
    config = apps.get_app_config("correspondence")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for name, codenames in ADDED.items():
        group, _ = Group.objects.get_or_create(name=name)  # tolerate a group an operator removed
        group.permissions.add(
            *Permission.objects.filter(content_type__app_label="correspondence", codename__in=codenames))


def remove_permissions(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for name, codenames in ADDED.items():
        group = Group.objects.filter(name=name).first()
        if group is not None:
            group.permissions.remove(*Permission.objects.filter(content_type__app_label="correspondence", codename__in=codenames))


def open_items_for_s1_events(apps, schema_editor):
    Event = apps.get_model("applications", "ApplicationEvent")
    StaffItem = apps.get_model("correspondence", "StaffItem")
    for event in Event.objects.filter(kind="needs_staff_attention").order_by("id"):
        data = event.data if isinstance(event.data, dict) else {}
        key = f"event:{event.pk}"
        reason = data.get("reason")
        if reason not in ("repeat_after_verification", "newer_unverified_version"):
            reason = "processing_error"  # an unknown S1 reason stays resolvable (acknowledge), never stuck open
        if not StaffItem.objects.filter(dedupe_key=key).exists():
            StaffItem.objects.create(reason_code=reason, dedupe_key=key, application_id=event.application_id,
                                     opened_at=event.occurred_at)  # the mark keeps its real age


def keep_items(apps, schema_editor):
    pass  # reversing leaves the items: staff items are never deleted


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0007_reply_processing_permissions"), ("applications", "0003_protect_version_adoption")]
    operations = [
        migrations.RunPython(add_permissions, remove_permissions),
        migrations.RunPython(open_items_for_s1_events, keep_items),
    ]
