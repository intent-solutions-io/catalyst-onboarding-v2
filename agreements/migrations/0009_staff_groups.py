"""9kg.30 (029 section 7; 021 section 9): the P4 role groups, created by migration as the owner.

Until now every agreement permission was assigned to no group and granted to named people in a shell (021 sections
9 and 15). The internal launch needs an audited, shell-free grant path, so the three P4 roles the design names get
a group each, holding exactly the matrix in accounts.roles (frozen here as this migration's copy): the operator
(custody retries and fresh reads), the decision-maker (uncertain outcomes, cancel, reissue, stop, integrity holds,
document retrieval, required details; P4-D-8, P4-D-9, P4-D-16, D-43, D-46) and the template owner (POL-07).
Membership is still only the owner's act (`grant_staff_role`); the running application cannot join a group (D-23).
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

GROUPS = {
    "Agreement operator": ["view_agreementinstance", "operate_agreements"],
    "Agreement decision-maker": ["view_agreementinstance", "decide_uncertain_agreement", "manage_agreements",
                                 "resolve_agreement_integrity", "retrieve_agreement_document", "confirm_required_details"],
    "Agreement template owner": ["approve_agreement_template"],
}


def add_groups(apps, schema_editor):
    config = apps.get_app_config("agreements")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for name, codenames in GROUPS.items():
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set([Permission.objects.get(content_type__app_label="agreements", codename=c) for c in codenames])


def remove_groups(apps, schema_editor):
    apps.get_model("auth", "Group").objects.filter(name__in=list(GROUPS)).delete()


class Migration(migrations.Migration):
    dependencies = [("agreements", "0008_custody_and_details_protection")]
    operations = [migrations.RunPython(add_groups, remove_groups)]
