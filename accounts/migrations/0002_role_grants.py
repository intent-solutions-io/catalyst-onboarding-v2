# Least-privilege grants for the application role on authentication tables (ADR-14, D-17).
# The application reads staff accounts and permissions and records last_login (and a rehashed password on
# login); it never creates users or changes is_staff/is_superuser (that is `createsuperuser`, run as the owner).
from django.db import migrations

from config.db_roles import apply_grants

forward, reverse = apply_grants({
    "accounts_user": {"app": ["SELECT", "UPDATE (last_login, password)"]},
    "accounts_user_groups": {"app": ["SELECT"]},
    "accounts_user_user_permissions": {"app": ["SELECT"]},
    "auth_group": {"app": ["SELECT"]},
    "auth_group_permissions": {"app": ["SELECT"]},
    "auth_permission": {"app": ["SELECT"]},
    "django_content_type": {"app": ["SELECT"]},
    "django_migrations": {"app": ["SELECT"]},
})


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]
    operations = [migrations.RunPython(forward, reverse)]
