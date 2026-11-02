"""Permit countersign claims only for native or explicitly adopted source envelopes."""

from django.db import migrations, models

SQL = """
CREATE FUNCTION public.catalyst_countersign_identity() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM public.agreements_agreementinstance i
    WHERE i.id = NEW.instance_id AND i.envelope_id = NEW.envelope_id
      AND i.external_key = NEW.external_key
      AND (left(i.external_key, 3) = 'ag_' OR EXISTS (
        SELECT 1 FROM public.firstgen_importedrecord r
        JOIN public.applications_applicationevent e ON e.application_id = r.application_id
        WHERE r.application_id = i.application_id AND r.v1_table = 'agreement'
          AND r.data->>'provider_ref' = i.envelope_id
          AND r.data->>'external_ref' = i.external_key
          AND e.kind = 'legacy_envelope_adopted'
          AND e.data->>'instance' = i.public_id::text
          AND e.data->>'record' = r.id::text
          AND e.data->>'source_stopped_attested' = 'true'
          AND e.data->>'mapping_reviewed' = 'true'
      ))
  ) THEN
    RAISE EXCEPTION 'countersign envelope is not owned' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.catalyst_countersign_identity() FROM PUBLIC;
CREATE TRIGGER catalyst_countersign_identity BEFORE INSERT OR UPDATE OF instance_id, envelope_id, external_key
ON public.agreements_countersignclaim FOR EACH ROW EXECUTE FUNCTION public.catalyst_countersign_identity();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("agreements", "0014_one_current_template"),
        ("firstgen", "0002_protection"),
    ]
    operations = [
        migrations.RemoveConstraint(
            model_name="countersignclaim", name="countersign_claim_v2_envelope_only"
        ),
        migrations.AddConstraint(
            model_name="countersignclaim",
            constraint=models.CheckConstraint(
                condition=~models.Q(external_key="") & ~models.Q(envelope_id=""),
                name="countersign_claim_identity_present",
            ),
        ),
        migrations.RunSQL(
            SQL,
            reverse_sql="""
            DROP TRIGGER catalyst_countersign_identity ON public.agreements_countersignclaim;
            DROP FUNCTION public.catalyst_countersign_identity();
        """,
        ),
    ]
