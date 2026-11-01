# bgl.14 (034 rows 42 and 43): the Twenty link. Expand-only: one new table, which the previous image never reads.
# Grants are migration 0002; the erasure functions that cover its subject column are reinstalled by erasure 0005.
import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    # After erasure 0004, so the table never exists below it: reversing erasure past 0004 removes it first, and each
    # earlier erasure migration's reverse then regenerates its functions for a schema without it.
    dependencies = [
        ("applications", "0009_tombstone_keys_unique"),
        ("erasure", "0004_erase_replay"),
    ]

    operations = [
        migrations.CreateModel(
            name="TwentyLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("person_id", models.CharField(blank=True, default="", max_length=64)),
                ("link_method", models.CharField(blank=True, default="", max_length=16)),
                ("note_id", models.CharField(blank=True, default="", max_length=64)),
                ("note_sha256", models.CharField(blank=True, default="", max_length=64)),
                ("field_hashes", models.JSONField(default=dict)),
                ("projection_version", models.CharField(blank=True, default="", max_length=40)),
                ("projected_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ("updated_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ("application", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                                                     related_name="twenty_link", to="applications.application")),
            ],
            options={
                "indexes": [models.Index(condition=models.Q(("person_id", ""), _negated=True), fields=["person_id"],
                                         name="twenty_link_person")],
                "constraints": [models.CheckConstraint(
                    condition=models.Q(("link_method__in", ["", "created", "recovered", "email_match", "imported", "staff"])),
                    name="twenty_link_method_valid")],
            },
        ),
    ]
