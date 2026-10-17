# P4 4B.1 (021 section 3; ADR-14, D-17, D-15, D-37). Runs as the migration owner.
#
# 1. Grants: types are read-only; a template version changes only its approval columns; an instance changes only its
#    key, envelope id and status columns; recipients are insert-only; an attempt changes only its outcome columns.
#    Nothing here is deletable by the application or retention role.
# 2. Triggers, for every role (the 4B.1 security review closed the insert paths):
#    - template versions: born unapproved drafts; changed only while a draft, and then only the approval columns;
#      never deleted;
#    - instances: born in the initial state on an approved version of their own type; identity columns fixed; the
#      envelope id set once; a key never reused; and the D-15 backstop (TEST-P4-26): a User Agreement instance is
#      refused unless the application's live NDA is `signing_complete_verified`;
#    - recipients: added only before the first provider call, then append-only and never truncated.
#    The status columns stay updatable by the application role: that `signing_complete_verified` came from a fresh
#    read is an application control until 4B.2 decides whether to make it database-visible (021 section 15).
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


FUNCTIONS = ("catalyst_agreement_template_frozen", "catalyst_agreement_template_draft", "catalyst_agreement_instance_insert",
             "catalyst_agreement_instance_fixed", "catalyst_agreement_recipient_open")
TRIGGERS = (
    (VERSION, "catalyst_agreement_template_frozen", "BEFORE UPDATE OR DELETE"),
    (VERSION, "catalyst_agreement_template_draft", "BEFORE INSERT"),
    (INSTANCE, "catalyst_agreement_instance_insert", "BEFORE INSERT"),
    (INSTANCE, "catalyst_agreement_instance_fixed", "BEFORE UPDATE"),
    (RECIPIENT, "catalyst_agreement_recipient_open", "BEFORE INSERT"),
)


def _function(schema_editor, name, body):
    schema_editor.execute(f"""
        CREATE FUNCTION public.{name}() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
        {body}
        END $$
    """, params=None)  # params=None: the RAISE format's % signs are not query placeholders
    schema_editor.execute(f"REVOKE ALL ON FUNCTION public.{name}() FROM PUBLIC")


def protect(apps, schema_editor):
    _function(schema_editor, "catalyst_agreement_template_frozen", """
          IF TG_OP = 'DELETE' OR OLD.status <> 'draft'
             OR (NEW.agreement_type_id, NEW.version, NEW.provider_template_ref, NEW.provider_template_number,
                 NEW.recipient_slots::text, NEW.pdf_sha256, NEW.created_at)
                IS DISTINCT FROM
                (OLD.agreement_type_id, OLD.version, OLD.provider_template_ref, OLD.provider_template_number,
                 OLD.recipient_slots::text, OLD.pdf_sha256, OLD.created_at) THEN
            RAISE EXCEPTION 'agreement template version: % refused (approved versions and content are fixed)', TG_OP
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;""")
    # A version is always born a draft: approval is the owner's service, never an insert (4B.1 review).
    _function(schema_editor, "catalyst_agreement_template_draft", """
          IF NEW.status <> 'draft' OR NEW.approved_by <> '' OR NEW.approved_at IS NOT NULL THEN
            RAISE EXCEPTION 'agreement template version: a new version must be an unapproved draft'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;""")
    # An instance is born in its initial state, on an approved version of its own type; and the D-15 backstop: no User
    # Agreement unless the application's live NDA is signing_complete_verified.
    _function(schema_editor, "catalyst_agreement_instance_insert", f"""
          IF NEW.signing_status <> 'not_started' OR NEW.custody_status <> 'not_due' OR NEW.envelope_id <> ''
             OR NEW.issue_status NOT IN ('held', 'create_pending') THEN
            RAISE EXCEPTION 'agreement instance: a new instance starts unsigned, uncreated and not in custody'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF NOT EXISTS (SELECT 1 FROM public.{VERSION} v WHERE v.id = NEW.template_version_id
                         AND v.agreement_type_id = NEW.agreement_type_id AND v.status = 'approved') THEN
            RAISE EXCEPTION 'agreement instance: the template version must be approved and of the same type'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF EXISTS (SELECT 1 FROM public.{TYPE} t WHERE t.id = NEW.agreement_type_id AND t.key = 'user_agreement')
             AND NOT EXISTS (
               SELECT 1 FROM public.{INSTANCE} i JOIN public.{TYPE} t ON t.id = i.agreement_type_id
               WHERE i.application_id = NEW.application_id AND t.key = 'nda'
                 AND i.issue_status NOT IN ('superseded', 'cancelled')
                 AND i.signing_status = 'signing_complete_verified') THEN
            RAISE EXCEPTION 'D-15: no User Agreement before the NDA is signing_complete_verified'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;""")
    # Identity never changes; the envelope id is set once; a key is never reused (P4-D-19).
    _function(schema_editor, "catalyst_agreement_instance_fixed", f"""
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
             AND EXISTS (SELECT 1 FROM public.{ATTEMPT} a WHERE a.external_key = NEW.external_key) THEN
            RAISE EXCEPTION 'agreement instance: a key is never reused'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;""")
    # Recipients are fixed before the create: none may be added once the instance has left create_pending.
    _function(schema_editor, "catalyst_agreement_recipient_open", f"""
          IF NOT EXISTS (SELECT 1 FROM public.{INSTANCE} i WHERE i.id = NEW.instance_id AND i.envelope_id = ''
                         AND i.issue_status IN ('held', 'create_pending')
                         AND NOT EXISTS (SELECT 1 FROM public.{ATTEMPT} a WHERE a.instance_id = i.id)) THEN
            RAISE EXCEPTION 'agreement recipient: recipients are fixed before the first provider call'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;""")
    for table, name, timing in TRIGGERS:
        schema_editor.execute(f"CREATE TRIGGER {name} {timing} ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.{name}()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{RECIPIENT} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_append_only_strict()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{RECIPIENT} "
                          "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect(apps, schema_editor):
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{RECIPIENT}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_append_only ON public.{RECIPIENT}")
    for table, name, _ in TRIGGERS:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {name} ON public.{table}")
    for name in FUNCTIONS:
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
