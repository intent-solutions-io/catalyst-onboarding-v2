# P4 4B.1 (021 section 3; ADR-14, D-17, D-15, D-37). Runs as the migration owner.
#
# 1. Grants: types are read-only; a template version changes only its approval columns; an instance changes only its
#    key, envelope id and status columns; recipients are insert-only; an attempt changes only its outcome columns.
#    Nothing here is deletable by the application or retention role.
# 2. Triggers, for every role:
#    - `catalyst_agreement_template_frozen`: a template version changes only while it is a draft, and then only its
#      approval columns; it is never deleted;
#    - `catalyst_agreement_envelope_once`: an instance's envelope id is set once and never changed;
#    - `catalyst_agreement_nda_first` (the D-15 backstop, TEST-P4-26): a User Agreement instance is refused unless the
#      application's NDA is `signing_complete_verified`;
#    - recipients: the strict append-only and no-truncate triggers (a changed recipient is a new instance).
#    The live-instance rule is the partial unique index `agreement_one_live_per_type` (0001).
# 3. The P4-D-1 inventory: `nda`, then `user_agreement`, both gated on signing and custody (P4-D-6).
# 4. The two permissions exist and are assigned to no group (021 section 9): granted to named people only.
# A compromised migration owner can still drop these triggers; that limit is ADR-14's, stated in 021 section 15.
from django.contrib.auth.management import create_permissions
from django.db import migrations

from config.db_roles import apply_grants

TYPE = "agreements_agreementtype"
VERSION = "agreements_agreementtemplateversion"
INSTANCE = "agreements_agreementinstance"
RECIPIENT = "agreements_agreementrecipient"
ATTEMPT = "agreements_envelopeattempt"

grant_forward, grant_reverse = apply_grants({
    TYPE: {"app": ["SELECT"], "retention": ["SELECT"]},
    VERSION: {"app": ["SELECT", "INSERT", "UPDATE (status, approved_by, approved_at)"], "retention": ["SELECT"]},
    INSTANCE: {"app": ["SELECT", "INSERT",
                       "UPDATE (external_key, envelope_id, issue_status, signing_status, custody_status, updated_at)"],
               "retention": ["SELECT"]},
    RECIPIENT: {"app": ["SELECT", "INSERT"], "retention": ["SELECT"]},
    ATTEMPT: {"app": ["SELECT", "INSERT", "UPDATE (outcome, outcome_code, envelope_id, finished_at)"],
              "retention": ["SELECT"]},
})


def protect(apps, schema_editor):
    schema_editor.execute(f"""
        CREATE FUNCTION public.catalyst_agreement_template_frozen() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR OLD.status <> 'draft'
             OR (NEW.agreement_type_id, NEW.version, NEW.provider_template_ref, NEW.provider_template_number,
                 NEW.recipient_slots::text, NEW.pdf_sha256, NEW.created_at)
                IS DISTINCT FROM
                (OLD.agreement_type_id, OLD.version, OLD.provider_template_ref, OLD.provider_template_number,
                 OLD.recipient_slots::text, OLD.pdf_sha256, OLD.created_at) THEN
            RAISE EXCEPTION 'agreement template version: % refused (approved versions and content are fixed)', TG_OP
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    schema_editor.execute(f"""
        CREATE FUNCTION public.catalyst_agreement_envelope_once() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF OLD.envelope_id <> '' AND NEW.envelope_id IS DISTINCT FROM OLD.envelope_id THEN
            RAISE EXCEPTION 'agreement instance: the envelope id is set once'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    schema_editor.execute(f"""
        CREATE FUNCTION public.catalyst_agreement_nda_first() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF EXISTS (SELECT 1 FROM public.{TYPE} t WHERE t.id = NEW.agreement_type_id AND t.key = 'user_agreement')
             AND NOT EXISTS (
               SELECT 1 FROM public.{INSTANCE} i JOIN public.{TYPE} t ON t.id = i.agreement_type_id
               WHERE i.application_id = NEW.application_id AND t.key = 'nda'
                 AND i.signing_status = 'signing_complete_verified') THEN
            RAISE EXCEPTION 'D-15: no User Agreement before the NDA is signing_complete_verified'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    for name in ("catalyst_agreement_template_frozen", "catalyst_agreement_envelope_once", "catalyst_agreement_nda_first"):
        schema_editor.execute(f"REVOKE ALL ON FUNCTION public.{name}() FROM PUBLIC")
    schema_editor.execute(f"CREATE TRIGGER catalyst_agreement_template_frozen BEFORE UPDATE OR DELETE ON public.{VERSION} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_agreement_template_frozen()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_agreement_envelope_once BEFORE UPDATE ON public.{INSTANCE} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_agreement_envelope_once()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_agreement_nda_first BEFORE INSERT ON public.{INSTANCE} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_agreement_nda_first()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{RECIPIENT} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_append_only_strict()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{RECIPIENT} "
                          "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect(apps, schema_editor):
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{RECIPIENT}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_append_only ON public.{RECIPIENT}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_agreement_nda_first ON public.{INSTANCE}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_agreement_envelope_once ON public.{INSTANCE}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_agreement_template_frozen ON public.{VERSION}")
    for name in ("catalyst_agreement_template_frozen", "catalyst_agreement_envelope_once", "catalyst_agreement_nda_first"):
        schema_editor.execute(f"DROP FUNCTION IF EXISTS public.{name}()")


def seed(apps, schema_editor):
    AgreementType = apps.get_model("agreements", "AgreementType")
    for key, order in (("nda", 1), ("user_agreement", 2)):
        AgreementType.objects.get_or_create(key=key, defaults={"order": order, "required": True,
                                                               "gate": "signing_and_custody"})
    config = apps.get_app_config("agreements")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)  # assigned to no group


def unseed(apps, schema_editor):
    apps.get_model("agreements", "AgreementType").objects.filter(key__in=("nda", "user_agreement")).delete()


class Migration(migrations.Migration):
    dependencies = [("agreements", "0001_initial")]
    operations = [
        migrations.RunPython(seed, unseed),
        migrations.RunPython(grant_forward, grant_reverse),
        migrations.RunPython(protect, unprotect),
    ]
