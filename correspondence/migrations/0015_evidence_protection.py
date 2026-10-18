# Hardening 9kg.1 (016 section 3; ADR-14). Runs as the migration owner.
#
# Correspondence evidence is protected for every role, not only by the application role's column grants:
#
# 1. Staff item resolutions, inbound message locations and the links from an approved message to its questions are
#    history: the strict append-only and no-truncate
#    triggers (a retention path is a POL-10 decision, not built).
# 2. An approved message's authorization is frozen at insert: only the disposition columns ever change, and a row is
#    never deleted (catalyst_approved_message_frozen). Delivery state lives in the disposition and in
#    OutboundMessage, which stay updatable.
# 3. A message template version is free while it is a draft. Once approved, its content and approval are final; the
#    only change left is approved to retired, and an approved or retired version is never deleted. A version is
#    always inserted as a draft, so an approval exists only through the owner's approval step
#    (catalyst_template_version_frozen).
#
# These rows cannot be erased by any ordinary role, the retention role included: a retention or erasure path for
# them is a POL-10 decision for the owner (a later audited migration), not built here.
from django.db import migrations

RESOLUTION = "correspondence_staffitemresolution"
LOCATION = "correspondence_inboundmessagelocation"
LINK = "correspondence_approvedmessagequestion"
APPROVED = "correspondence_approvedmessage"
TEMPLATE = "correspondence_messagetemplateversion"


def protect(apps, schema_editor):
    for table in (RESOLUTION, LOCATION, LINK):
        schema_editor.execute(f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{table} "
                              "FOR EACH ROW EXECUTE FUNCTION public.catalyst_append_only_strict()")
    for table in (RESOLUTION, LOCATION, LINK, APPROVED, TEMPLATE):
        schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{table} "
                              "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")
    schema_editor.execute("""
        CREATE FUNCTION public.catalyst_approved_message_frozen() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'DELETE'
             OR (NEW.id, NEW.send_ref, NEW.kind, NEW.application_id, NEW.recipient, NEW.template_version_id,
                 NEW.frozen_subject, NEW.frozen_body, NEW.content_sha256, NEW.reproducible_inputs::text,
                 NEW.inputs_sha256, NEW.authorized_by, NEW.authority, NEW.authorized_at, NEW.supersedes_id,
                 NEW.staff_draft_id)
                IS DISTINCT FROM
                (OLD.id, OLD.send_ref, OLD.kind, OLD.application_id, OLD.recipient, OLD.template_version_id,
                 OLD.frozen_subject, OLD.frozen_body, OLD.content_sha256, OLD.reproducible_inputs::text,
                 OLD.inputs_sha256, OLD.authorized_by, OLD.authority, OLD.authorized_at, OLD.supersedes_id,
                 OLD.staff_draft_id) THEN
            RAISE EXCEPTION 'approved message: % refused (the authorization is frozen; only the disposition changes)',
              TG_OP USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    schema_editor.execute("""
        CREATE FUNCTION public.catalyst_template_version_frozen() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.status IS DISTINCT FROM 'draft' OR NEW.approved_by <> '' OR NEW.approved_at IS NOT NULL THEN
              RAISE EXCEPTION 'message template version: a version is inserted as a draft and approved by the owner'
                USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
          END IF;
          IF OLD.status = 'draft' THEN
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
          END IF;
          IF TG_OP = 'DELETE'
             OR (NEW.status IS DISTINCT FROM OLD.status AND NOT (OLD.status = 'approved' AND NEW.status = 'retired'))
             OR (NEW.id, NEW.template_id, NEW.version, NEW.subject, NEW.body_text, NEW.variables::text,
                 NEW.secret_bearing, NEW.approved_by, NEW.approved_at, NEW.content_sha256, NEW.synthetic,
                 NEW.created_at)
                IS DISTINCT FROM
                (OLD.id, OLD.template_id, OLD.version, OLD.subject, OLD.body_text, OLD.variables::text,
                 OLD.secret_bearing, OLD.approved_by, OLD.approved_at, OLD.content_sha256, OLD.synthetic,
                 OLD.created_at) THEN
            RAISE EXCEPTION 'message template version: % refused (an approved version is final; it may only retire)',
              TG_OP USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    for function, table, events in (("catalyst_approved_message_frozen", APPROVED, "UPDATE OR DELETE"),
                                    ("catalyst_template_version_frozen", TEMPLATE, "INSERT OR UPDATE OR DELETE")):
        schema_editor.execute(f"REVOKE ALL ON FUNCTION public.{function}() FROM PUBLIC")
        schema_editor.execute(f"CREATE TRIGGER {function} BEFORE {events} ON public.{table} "
                              f"FOR EACH ROW EXECUTE FUNCTION public.{function}()")


def unprotect(apps, schema_editor):
    for function, table in (("catalyst_approved_message_frozen", APPROVED),
                            ("catalyst_template_version_frozen", TEMPLATE)):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {function} ON public.{table}")
        schema_editor.execute(f"DROP FUNCTION IF EXISTS public.{function}()")
    for table in (RESOLUTION, LOCATION, LINK, APPROVED, TEMPLATE):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{table}")
    for table in (RESOLUTION, LOCATION, LINK):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_append_only ON public.{table}")


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0014_interpretation_grants"), ("applications", "0002_history_protection")]
    operations = [migrations.RunPython(protect, unprotect)]
