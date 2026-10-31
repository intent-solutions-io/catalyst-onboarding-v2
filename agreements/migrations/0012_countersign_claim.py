# bgl.9 (034 row 30; first-generation decision 12, owner YES 2026-10-31). Runs as the migration owner.
#
# The countersign claim: one row per envelope the automated company countersignature works on (agreements.countersign),
# unique on the envelope, so two workers or a second consumer cannot both sign it. A check constraint refuses a claim on
# an envelope Catalyst v2 did not create (its external key carries the `ag_` prefix). The row is working state, not
# history: the application role inserts it and moves its state columns; the retention and backup roles read it. It
# holds no token, link, name or address. Expand-only: a new table, so the previous image runs on it unchanged.
import django.db.models.deletion
import django.db.models.functions.datetime
from django.conf import settings
from django.db import migrations, models

from config.db_roles import apply_grants

TABLE = "agreements_countersignclaim"

grant_forward, grant_reverse = apply_grants({TABLE: {
    "app": ["SELECT", "INSERT", "UPDATE (action_id, state, attempts, last_code, first_failure_at, updated_at, finished_at)"],
    "retention": ["SELECT"], "backup": ["SELECT"]}})


def backup_sequence(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    schema_editor.execute(f"GRANT SELECT ON SEQUENCE public.{TABLE}_id_seq TO {role}")


def no_backup_sequence(apps, schema_editor):
    role = schema_editor.quote_name(settings.CATALYST_DB_ROLES["backup"])
    schema_editor.execute(f"REVOKE ALL ON SEQUENCE public.{TABLE}_id_seq FROM {role}")


class Migration(migrations.Migration):

    dependencies = [
        ("agreements", "0011_details_from_envelope"),  # renumbered from 0011 at the parity integration (after bgl.8's 0011)
    ]

    operations = [
        migrations.CreateModel(
            name="CountersignClaim",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("envelope_id", models.CharField(max_length=64, unique=True)),
                ("external_key", models.CharField(max_length=64)),
                ("holder", models.CharField(max_length=40)),
                ("action_id", models.BigIntegerField(blank=True, null=True)),
                ("state", models.CharField(choices=[("signing", "Signing"), ("signed", "Signed"),
                                                    ("failed", "Failed"), ("handed_off", "Handed Off")],
                                           default="signing", max_length=16)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("last_code", models.CharField(blank=True, default="", max_length=64)),
                ("first_failure_at", models.DateTimeField(blank=True, null=True)),
                ("claimed_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ("updated_at", models.DateTimeField(db_default=django.db.models.functions.datetime.Now())),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("instance", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                               related_name="countersign_claims", to="agreements.agreementinstance")),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("state__in", ["signing", "signed", "failed", "handed_off"])),
                        name="countersign_claim_state_valid"),
                    models.CheckConstraint(
                        condition=models.Q(("external_key__startswith", "ag_"), models.Q(("envelope_id", ""), _negated=True)),
                        name="countersign_claim_v2_envelope_only"),
                ],
            },
        ),
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(backup_sequence, no_backup_sequence),
    ]
