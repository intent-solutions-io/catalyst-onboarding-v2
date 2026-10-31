# bgl.16 (035): the first-generation import's provenance tables. Expand-only: three new tables, nothing else changes, so
# the previous image runs on this schema unchanged (it never reads them). Grants and protection are migration 0002.
import uuid

import django.db.models.deletion
import django.db.models.functions.datetime
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("applications", "0009_tombstone_keys_unique"),
    ]

    operations = [
        migrations.CreateModel(
            name="ImportRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ("actor_ref", models.CharField(max_length=200)),
                ("source_ref", models.CharField(max_length=64)),
                ("report", models.JSONField(default=dict)),
                ("recorded_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
            ],
            options={
                "constraints": [models.CheckConstraint(condition=models.Q(("actor_ref", ""), _negated=True),
                                                       name="firstgen_run_has_actor")],
            },
        ),
        migrations.CreateModel(
            name="ImportedCase",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("v1_case_id", models.CharField(max_length=26, unique=True)),
                ("reference", models.CharField(max_length=20, unique=True)),
                ("v1_state", models.CharField(max_length=30)),
                ("v1_resume_state", models.CharField(blank=True, default="", max_length=30)),
                ("v1_cohort", models.CharField(blank=True, default="", max_length=30)),
                ("v1_created_at", models.DateTimeField()),
                ("v1_state_changed_at", models.DateTimeField()),
                ("mapped_stage", models.CharField(max_length=32)),
                ("crm_person_id", models.CharField(blank=True, default="", max_length=64)),
                ("crm_note_id", models.CharField(blank=True, default="", max_length=64)),
                ("findings", models.JSONField(default=list)),
                ("run_ref", models.UUIDField()),
                ("imported_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ("application", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                                                     related_name="first_generation", to="applications.application")),
            ],
        ),
        migrations.CreateModel(
            name="ImportedRecord",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("v1_table", models.CharField(max_length=40)),
                ("v1_id", models.CharField(max_length=100)),
                ("kind", models.CharField(max_length=40)),
                ("occurred_at", models.DateTimeField(blank=True, null=True)),
                ("message_id", models.CharField(blank=True, default="", max_length=255)),
                ("target", models.CharField(blank=True, default="", max_length=120)),
                ("data", models.JSONField(default=dict)),
                ("run_ref", models.UUIDField()),
                ("imported_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ("application", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                                  related_name="first_generation_records",
                                                  to="applications.application")),
            ],
            options={
                "indexes": [
                    models.Index(condition=models.Q(("message_id", ""), _negated=True), fields=["message_id"],
                                 name="firstgen_record_message_id"),
                    models.Index(fields=["application", "occurred_at"], name="firstgen_record_timeline"),
                ],
                "constraints": [models.UniqueConstraint(fields=("v1_table", "v1_id"), name="firstgen_record_once")],
            },
        ),
    ]
