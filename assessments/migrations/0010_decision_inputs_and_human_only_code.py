"""oc4.12 (018 section 20; 019 decision 4): what a decision records, completed for the human-only path.

Adds, to the append-only decision row: the prompt pack, its digest and the rubric version (recorded whatever the
policy reference says: oc4.10 item 3), the structured human-only reason code (a database constraint refuses a
human-only decision without one), and `decision_inputs`, the material the decision digest binds (the policy, the
pack digest, the snapshot digest, the evidence manifest and every run: oc4.10 item 2). Columns only, with
defaults; the ADR-14 triggers and grants of migration 0008 are unchanged (the application role inserts whole rows).
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("assessments", "0009_fetcher_role_grants")]
    operations = [
        migrations.AddField(model_name="qualificationdecision", name="human_only_code",
                            field=models.CharField(blank=True, db_default="", default="", max_length=40)),
        migrations.AddField(model_name="qualificationdecision", name="prompt_pack",
                            field=models.CharField(blank=True, db_default="", default="", max_length=64)),
        migrations.AddField(model_name="qualificationdecision", name="prompt_pack_sha256",
                            field=models.CharField(blank=True, db_default="", default="", max_length=64)),
        migrations.AddField(model_name="qualificationdecision", name="rubric_version",
                            field=models.PositiveIntegerField(db_default=0, default=0)),
        migrations.AddField(model_name="qualificationdecision", name="decision_inputs",
                            field=models.JSONField(db_default="{}", default=dict)),
        migrations.AddConstraint(
            model_name="qualificationdecision",
            constraint=models.CheckConstraint(
                condition=models.Q(("basis", "model_assisted")) | models.Q(("human_only_code", ""), _negated=True),
                name="decision_human_only_has_code"),
        ),
    ]
