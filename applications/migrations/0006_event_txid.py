"""9kg.6 (ADR-14 pattern; 016 section 10.13): every history event carries the top-level transaction id that inserted
it, so a database guard can require an event "in the same transaction" (the pause guard, workflow 0005). The value is
always the database's own: a BEFORE INSERT trigger overwrites whatever was supplied, as assessments 0008 does for
qualification decisions. Existing rows take the migration's transaction id, which no later transaction can match."""

from django.db import migrations, models

import applications.models


def protect(apps, schema_editor):
    schema_editor.execute("""
        CREATE FUNCTION public.catalyst_event_txid() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          NEW.created_txid := pg_current_xact_id()::text::bigint;
          RETURN NEW;
        END $$
    """, params=None)
    schema_editor.execute("REVOKE ALL ON FUNCTION public.catalyst_event_txid() FROM PUBLIC")
    schema_editor.execute("CREATE TRIGGER catalyst_event_txid BEFORE INSERT ON public.applications_applicationevent "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_event_txid()")


def unprotect(apps, schema_editor):
    schema_editor.execute("DROP TRIGGER IF EXISTS catalyst_event_txid ON public.applications_applicationevent")
    schema_editor.execute("DROP FUNCTION IF EXISTS public.catalyst_event_txid()")


class Migration(migrations.Migration):
    dependencies = [("applications", "0005_invitation_protection")]
    operations = [
        migrations.AddField(
            model_name="applicationevent",
            name="created_txid",
            field=models.BigIntegerField(db_default=applications.models.CurrentTransactionId()),
        ),
        migrations.RunPython(protect, unprotect),
    ]
