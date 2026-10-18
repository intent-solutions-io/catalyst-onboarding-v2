# D-42 and D-43 (2026-10-18; bead catalyst-v2-hdg.6). Runs as the migration owner.
#
# 1. The application role may set the new columns: a cancel request recorded while an exchange is in flight (D-42),
#    and the replacement of an instance by a controlled new generation (D-43).
# 2. Both are set once, for every role, and a replacement needs its reason (catalyst_agreement_instance_fixed).
#    Verified signing columns stay immutable (0004): replacement changes eligibility only.
# 3. The D-15 backstop counts only an NDA that has not been replaced (catalyst_agreement_instance_insert).
# 4. The `resolve_agreement_integrity` permission exists and is assigned to no group.
from django.contrib.auth.management import create_permissions
from django.db import migrations

INSTANCE = "agreements_agreementinstance"
COLUMNS = ("external_key, envelope_id, issue_status, signing_status, custody_status, updated_at, cancel_requested_at, "
           "replaced_at, replacement_reason")
OLD_COLUMNS = "external_key, envelope_id, issue_status, signing_status, custody_status, updated_at"

NEW_INSERT = """
          IF NEW.signing_status <> 'not_started' OR NEW.custody_status <> 'not_due' OR NEW.envelope_id <> ''
             OR NEW.issue_status NOT IN ('held', 'create_pending') THEN
            RAISE EXCEPTION 'agreement instance: a new instance starts unsigned, uncreated and not in custody'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM public.agreements_agreementtemplateversion v WHERE v.id = NEW.template_version_id
                         AND v.agreement_type_id = NEW.agreement_type_id AND v.status = 'approved') THEN
            RAISE EXCEPTION 'agreement instance: the template version must be approved and of the same type'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF EXISTS (SELECT 1 FROM public.agreements_agreementtype t WHERE t.id = NEW.agreement_type_id AND t.key = 'user_agreement')
             AND NOT EXISTS (
               SELECT 1 FROM public.agreements_agreementinstance i JOIN public.agreements_agreementtype t ON t.id = i.agreement_type_id
               WHERE i.application_id = NEW.application_id AND t.key = 'nda'
                 AND i.issue_status NOT IN ('superseded', 'cancelled') AND i.replaced_at IS NULL
                 AND i.signing_status = 'signing_complete_verified') THEN
            RAISE EXCEPTION 'D-15: no User Agreement before the NDA is signing_complete_verified'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;"""
OLD_INSERT = """
          IF NEW.signing_status <> 'not_started' OR NEW.custody_status <> 'not_due' OR NEW.envelope_id <> ''
             OR NEW.issue_status NOT IN ('held', 'create_pending') THEN
            RAISE EXCEPTION 'agreement instance: a new instance starts unsigned, uncreated and not in custody'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM public.agreements_agreementtemplateversion v WHERE v.id = NEW.template_version_id
                         AND v.agreement_type_id = NEW.agreement_type_id AND v.status = 'approved') THEN
            RAISE EXCEPTION 'agreement instance: the template version must be approved and of the same type'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF EXISTS (SELECT 1 FROM public.agreements_agreementtype t WHERE t.id = NEW.agreement_type_id AND t.key = 'user_agreement')
             AND NOT EXISTS (
               SELECT 1 FROM public.agreements_agreementinstance i JOIN public.agreements_agreementtype t ON t.id = i.agreement_type_id
               WHERE i.application_id = NEW.application_id AND t.key = 'nda'
                 AND i.issue_status NOT IN ('superseded', 'cancelled')
                 AND i.signing_status = 'signing_complete_verified') THEN
            RAISE EXCEPTION 'D-15: no User Agreement before the NDA is signing_complete_verified'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;"""
NEW_FIXED = """
          IF (NEW.public_id, NEW.application_id, NEW.agreement_type_id, NEW.template_version_id, NEW.created_at)
             IS DISTINCT FROM (OLD.public_id, OLD.application_id, OLD.agreement_type_id, OLD.template_version_id,
                               OLD.created_at) THEN
            RAISE EXCEPTION 'agreement instance: identity columns are fixed'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF OLD.envelope_id <> '' AND NEW.envelope_id IS DISTINCT FROM OLD.envelope_id THEN
            RAISE EXCEPTION 'agreement instance: the envelope id is set once'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF NEW.external_key IS DISTINCT FROM OLD.external_key
             AND EXISTS (SELECT 1 FROM public.agreements_envelopeattempt a WHERE a.external_key = NEW.external_key) THEN
            RAISE EXCEPTION 'agreement instance: a key is never reused'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF OLD.cancel_requested_at IS NOT NULL AND NEW.cancel_requested_at IS DISTINCT FROM OLD.cancel_requested_at THEN
            RAISE EXCEPTION 'agreement instance: a cancel request is recorded once'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF OLD.replaced_at IS NOT NULL AND (NEW.replaced_at, NEW.replacement_reason)
                                             IS DISTINCT FROM (OLD.replaced_at, OLD.replacement_reason) THEN
            RAISE EXCEPTION 'agreement instance: a replacement is recorded once'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF NEW.replaced_at IS NOT NULL AND OLD.replaced_at IS NULL AND NEW.replacement_reason = '' THEN
            RAISE EXCEPTION 'agreement instance: a replacement needs its reason'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;"""
OLD_FIXED = """
          IF (NEW.public_id, NEW.application_id, NEW.agreement_type_id, NEW.template_version_id, NEW.created_at)
             IS DISTINCT FROM (OLD.public_id, OLD.application_id, OLD.agreement_type_id, OLD.template_version_id,
                               OLD.created_at) THEN
            RAISE EXCEPTION 'agreement instance: identity columns are fixed'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF OLD.envelope_id <> '' AND NEW.envelope_id IS DISTINCT FROM OLD.envelope_id THEN
            RAISE EXCEPTION 'agreement instance: the envelope id is set once'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF NEW.external_key IS DISTINCT FROM OLD.external_key
             AND EXISTS (SELECT 1 FROM public.agreements_envelopeattempt a WHERE a.external_key = NEW.external_key) THEN
            RAISE EXCEPTION 'agreement instance: a key is never reused'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;"""


def _replace(schema_editor, name, body):
    schema_editor.execute(f"""
        CREATE OR REPLACE FUNCTION public.{name}() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
        {body}
        END $$
    """, params=None)


def _grant(schema_editor, columns):
    from django.conf import settings

    app = schema_editor.quote_name(settings.CATALYST_DB_ROLES["app"])
    schema_editor.execute(f"REVOKE UPDATE ON TABLE public.{INSTANCE} FROM {app}")
    schema_editor.execute(f"GRANT UPDATE ({columns}) ON TABLE public.{INSTANCE} TO {app}")


def forward(apps, schema_editor):
    _grant(schema_editor, COLUMNS)
    _replace(schema_editor, "catalyst_agreement_instance_insert", NEW_INSERT)
    _replace(schema_editor, "catalyst_agreement_instance_fixed", NEW_FIXED)


def reverse(apps, schema_editor):
    Instance = apps.get_model("agreements", "AgreementInstance")
    if Instance.objects.exclude(replaced_at=None).exists() or Instance.objects.exclude(cancel_requested_at=None).exists():
        raise RuntimeError("agreements 0006 cannot be reversed: stop requests or replacements are recorded")
    _replace(schema_editor, "catalyst_agreement_instance_fixed", OLD_FIXED)
    _replace(schema_editor, "catalyst_agreement_instance_insert", OLD_INSERT)
    _grant(schema_editor, OLD_COLUMNS)


def permissions(apps, schema_editor):
    config = apps.get_app_config("agreements")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)  # assigned to no group


class Migration(migrations.Migration):
    dependencies = [("agreements", "0005_stop_intent_and_replacement")]
    operations = [
        migrations.RunPython(permissions, migrations.RunPython.noop),
        migrations.RunPython(forward, reverse),
    ]
