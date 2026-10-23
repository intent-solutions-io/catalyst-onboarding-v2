# 9kg.43 (029 sections 4.1 and 7): the invitation record for invitation-only intake. Expand-only: a new table, so
# the previous image runs unchanged (config.release). Grants and protection follow in 0005.

import django.db.models.deletion
import django.db.models.functions.datetime
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0003_protect_version_adoption"),
    ]

    operations = [
        migrations.CreateModel(
            name="Invitation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("email_key", models.CharField(max_length=320)),
                ("issued_by", models.CharField(max_length=200)),
                ("note", models.CharField(blank=True, default="", max_length=500)),
                ("issued_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("superseded_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ("application", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                                  related_name="invitations", to="applications.application")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(condition=models.Q(("superseded_at__isnull", True), ("used_at__isnull", True)),
                                            fields=("email_key",), name="invitation_one_live_per_email_key"),
                    models.CheckConstraint(condition=models.Q(("expires_at__gt", models.F("issued_at"))),
                                           name="invitation_expires_after_issue"),
                    models.CheckConstraint(condition=models.Q(("issued_by", ""), _negated=True), name="invitation_has_issuer"),
                ],
            },
        ),
    ]
