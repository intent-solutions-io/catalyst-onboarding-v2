"""9kg.30 (029 section 7; 023 sections 8 and 15): the P5 role groups, created by migration as the owner.

The provisioning permissions were assigned to no group (023 section 8, P5-D-3: named grants only). The two P5 staff
roles the design names get a group each, holding exactly the matrix in accounts.roles (frozen here): the operator
(the checklist, attestation, reissue, supersede, address release) and the decision-maker (the same, plus closing or
withdrawing an application on the applicant's behalf, POL-12, P5-D-8, P5-D-11). The approval itself
(`approve_provisioning`) stays a direct, named grant (P5-D-3) and is never in a group: `grant_staff_role` grants it
per person. Membership is still only the owner's act (D-23).
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

GROUPS = {
    "Provisioning operator": ["view_provisioningrequest", "operate_provisioning"],
    "Provisioning decision-maker": ["view_provisioningrequest", "operate_provisioning", "close_application"],
}


def add_groups(apps, schema_editor):
    config = apps.get_app_config("provisioning")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for name, codenames in GROUPS.items():
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set([Permission.objects.get(content_type__app_label="provisioning", codename=c) for c in codenames])


def remove_groups(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=list(GROUPS)).delete()


class Migration(migrations.Migration):
    # The last of the 9kg.30 migrations: a database at this head always carries the whole role matrix and the grant
    # record (accounts 0006), so the command finds both or neither.
    dependencies = [("provisioning", "0006_revocation_and_withdrawal_protection"), ("accounts", "0006_staff_role_grants")]
    operations = [migrations.RunPython(add_groups, remove_groups)]
