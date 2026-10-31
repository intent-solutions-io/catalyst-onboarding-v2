# First-generation parity (034 row 39; bead catalyst-v2-bgl.10): a credential series has a mode. `set_your_own` is the
# P5-D-6 link flow every existing row used; `one_time_password` is the alternative the worker runs (set, IMAP login
# check, welcome). The token constraint exempts the new mode (it never has a token), and the row-fixing trigger of
# 0004 now holds the mode fixed with the rest of the series' identity. Runs as the migration owner.
from django.db import migrations, models

SETUP = "provisioning_credentialsetup"

BODY_WITH_MODE = """
    BEGIN
      IF TG_OP = 'DELETE'
         OR (NEW.id, NEW.public_id, NEW.request_id, NEW.series, NEW.recipient, NEW.mode, NEW.created_at)
            IS DISTINCT FROM (OLD.id, OLD.public_id, OLD.request_id, OLD.series, OLD.recipient, OLD.mode, OLD.created_at)
         OR (OLD.token_sha256 <> '' AND NEW.token_sha256 IS DISTINCT FROM OLD.token_sha256)
         OR (OLD.completed_at IS NOT NULL AND NEW.completed_at IS DISTINCT FROM OLD.completed_at)
         OR (OLD.state IN ('completed', 'expired', 'cancelled', 'superseded', 'invitation_failed')
             AND NEW.state IS DISTINCT FROM OLD.state)
         OR (OLD.state IN ('invitation_uncertain', 'set_uncertain') AND NEW.state NOT IN (OLD.state, 'superseded')) THEN
        RAISE EXCEPTION 'credential setup: % refused (identity and token are fixed; a settled series is final)', TG_OP
          USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END"""

BODY_WITHOUT_MODE = BODY_WITH_MODE.replace(", NEW.mode", "").replace(", OLD.mode", "")


def _replace(body):
    def run(apps, schema_editor):
        schema_editor.execute("CREATE OR REPLACE FUNCTION public.catalyst_credential_setup_fixed() RETURNS trigger "
                              f"LANGUAGE plpgsql SET search_path = public, pg_temp AS $$ {body} $$", params=None)
    return run


class Migration(migrations.Migration):
    dependencies = [("provisioning", "0007_staff_groups")]

    operations = [
        migrations.AddField(
            model_name="credentialsetup",
            name="mode",
            field=models.CharField(choices=[("set_your_own", "Set Your Own"), ("one_time_password", "One Time Password")],
                                   default="set_your_own", max_length=24),
        ),
        migrations.RemoveConstraint(model_name="credentialsetup", name="setup_invited_has_token"),
        migrations.AddConstraint(
            model_name="credentialsetup",
            constraint=models.CheckConstraint(condition=models.Q(("mode__in", ["set_your_own", "one_time_password"])),
                                              name="setup_mode_valid"),
        ),
        migrations.AddConstraint(
            model_name="credentialsetup",
            constraint=models.CheckConstraint(
                condition=models.Q(("mode", "one_time_password"))
                | ~models.Q(("state__in", ["invited", "presented", "set_pending", "completed"]))
                | (~models.Q(("token_sha256", "")) & models.Q(("expires_at__isnull", False))),
                name="setup_invited_has_token"),
        ),
        migrations.RunPython(_replace(BODY_WITH_MODE), _replace(BODY_WITHOUT_MODE)),
    ]
