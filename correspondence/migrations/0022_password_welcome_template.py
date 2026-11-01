# First-generation parity (034 row 39; bead catalyst-v2-bgl.10): the template key of the welcome that carries a
# one-time mailbox password, used only when CATALYST_PROVISIONING_CREDENTIAL_MODE is "one_time_password" (P5-D-6's
# set-your-own-password flow stays the default and keeps `provisioning_welcome`). The template is secret-bearing
# (016 3.1), so it can never be frozen into an ApprovedMessage: the worker renders it in memory at send time and stores
# identifiers only. No version is seeded here: the wording is a separate task (bead catalyst-v2-bgl.11), and the
# one-time-password flow refuses to run until a version declaring `$password` is approved (D-29).
from django.db import migrations

KEY = "provisioning_welcome_password"
PURPOSE = "Welcome an activated applicant with their mailbox and its one-time password (first-generation parity)"


def seed_template(apps, schema_editor):
    Template = apps.get_model("correspondence", "MessageTemplate")
    Template.objects.get_or_create(key=KEY, defaults={"purpose": PURPOSE, "secret_bearing": True})


def unseed_template(apps, schema_editor):
    apps.get_model("correspondence", "MessageTemplate").objects.filter(key=KEY, versions__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0021_agreement_link_templates")]  # renumbered from 0021 at the parity integration
    operations = [migrations.RunPython(seed_template, unseed_template)]
