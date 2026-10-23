# 9kg.52 (030 Q4 and Q8, D-51): the data notice an invitation mail carried, recorded on the invitation (a nullable
# column and a database-defaulted one), and the member-on-file record. Expand-only: the previous image runs unchanged
# (config.release). Grants and protection follow in 0008.

import django.db.models.functions.datetime
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0006_event_txid"),
    ]

    operations = [
        migrations.AddField(
            model_name="invitation",
            name="notice_template_version",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="invitation",
            name="notice_sha256",
            field=models.CharField(blank=True, db_default="", max_length=64),
        ),
        migrations.CreateModel(
            name="MemberAgreementOnFile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("email_key", models.CharField(max_length=320)),
                ("agreement_version", models.CharField(max_length=100)),
                ("completion_verified", models.BooleanField()),
                ("recorded_by", models.CharField(max_length=200)),
                ("note", models.CharField(blank=True, default="", max_length=500)),
                ("recorded_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ("superseded_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(condition=models.Q(("superseded_at__isnull", True)), fields=("email_key",),
                                            name="member_on_file_one_live_per_email_key"),
                    models.CheckConstraint(condition=models.Q(("completion_verified", True)),
                                           name="member_on_file_completion_verified"),
                    models.CheckConstraint(condition=models.Q(("agreement_version", ""), _negated=True),
                                           name="member_on_file_has_agreement_version"),
                    models.CheckConstraint(condition=models.Q(("recorded_by", ""), _negated=True),
                                           name="member_on_file_has_recorder"),
                ],
            },
        ),
    ]
