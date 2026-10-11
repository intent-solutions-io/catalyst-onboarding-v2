# The read-only staff view (S1-T7; D-23, POL-13 PROPOSED default). Runs as the migration owner.
#
# Grants: only what Django authentication, database sessions and the admin need for read-only staff.
# Sessions are created, refreshed and deleted at login and logout. The admin log is only read: read-only
# staff never add, change or delete, so the admin never writes a log entry, and refusing INSERT keeps it
# that way. Users, groups, memberships and permissions stay SELECT-only for the application role (0002),
# so the running application can never make anyone staff, a superuser or a group member.
#
# The group: exactly the view permissions on the slice models staff may read. RetentionAudit is left
# out (audit detail; the application role cannot read it either).
from django.contrib.auth.management import create_permissions
from django.db import migrations

from config.db_roles import apply_grants

READ_ONLY_STAFF = "Read-only staff"
VIEWABLE = {
    "applications": ["application", "submissionversion", "versionadoption", "applicationevent", "contactchallenge"],
    "workflow": ["pendingaction", "automationpause"],
    "correspondence": ["outboundmessage"],
}

grant_forward, grant_reverse = apply_grants({
    "django_session": {"app": ["SELECT", "INSERT", "UPDATE", "DELETE"]},
    "django_admin_log": {"app": ["SELECT"]},
})


def create_group(apps, schema_editor):
    for label in VIEWABLE:  # permissions are normally created after migrate; the group needs them now
        config = apps.get_app_config(label)
        config.models_module = True
        create_permissions(config, apps=apps, verbosity=0)
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    group, _ = Group.objects.get_or_create(name=READ_ONLY_STAFF)
    wanted = [(label, f"view_{model}") for label, models in VIEWABLE.items() for model in models]
    permissions = [Permission.objects.get(content_type__app_label=label, codename=codename) for label, codename in wanted]
    group.permissions.set(permissions)


def delete_group(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name=READ_ONLY_STAFF).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_role_grants"),
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("sessions", "0001_initial"),
        ("applications", "0003_protect_version_adoption"),
        ("workflow", "0002_role_grants"),
        ("correspondence", "0002_role_grants"),
    ]
    operations = [
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(create_group, delete_group),
    ]
