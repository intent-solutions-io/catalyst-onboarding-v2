# Hardening 9kg.5 (016 section 10.13; ADR-14; the security review of PR #44, MEDIUM 3). Runs as the migration owner.
#
# Until now the provenance of an inbound message and the identity of an outbound attempt and a reply link were fixed
# only by the application role's column grants: the owner, or any role granted UPDATE later, could rewrite them.
# These triggers make the database itself refuse the change, for every role, in the 0015 pattern (a tuple compare of
# the frozen columns; DELETE refused; TRUNCATE refused by the strict function):
#
# 1. InboundMessage: the headers (message_id_header, in_reply_to, references, from_address, from_normalized,
#    auto_markers, date_header, internal_date), received_at, size, original_sha256, attachments, is_derivative,
#    public_id and mailbox_ref are frozen at insert. The status, classification, association, trust and derivative
#    columns (the 0006 grant, including from_matches_verified_address) stay updatable.
# 2. OutboundMessage: application, pending action, attempt number, template key and version, recipient, approved
#    message, attempt series and rendered digest are frozen; message_id is set once (an empty value may be filled,
#    a value never changes); status, phase, reply code, timestamps and the filed-copy state stay updatable.
# 3. QuestionReplyLink: the question and the inbound message are frozen; state, outcome, actor and updated_at change.
#
# The audited retention path (ADR-14, migration applications.0002), carried forward so the freeze never blocks the
# erasure 9kg.32 builds under POL-10: a member of the retention role that has set `catalyst.retention_reason` may
# change the personal columns only (inbound: from_address, from_normalized, message_id_header, in_reply_to,
# references, attachments; outbound: recipient), and the trigger records the change in applications_retentionaudit
# with a digest of the row before the change (application 0 when the message was never associated). Nothing is
# granted to the retention role here: 9kg.32's security-definer erase function (EXECUTE for the retention role only)
# runs the update as the owner while the session stays the retention login, which is what the branch checks. 9kg.32
# may replace the reason-and-audit condition with its erasure-audit row; the frozen tuples stay as they are.
#
# Stated limitations as in 0015: the owner can disable or drop a trigger it owns, and a superuser bypasses them.
from django.conf import settings
from django.db import migrations

INBOUND = "correspondence_inboundmessage"
OUTBOUND = "correspondence_outboundmessage"
LINK = "correspondence_questionreplylink"
AUDIT = "applications_retentionaudit"
MIN_REASON = 10  # as applications.0002

INBOUND_FIXED = ("id", "public_id", "mailbox_ref", "auto_markers::text", "date_header", "internal_date", "received_at",
                 "size", "original_sha256", "is_derivative")  # never changed, by any path
INBOUND_PERSONAL = ("message_id_header", "in_reply_to", '"references"', "from_address", "from_normalized",
                    "attachments::text")  # frozen, except for the audited retention path
OUTBOUND_FIXED = ("id", "application_id", "pending_action_id", "attempt_number", "template_key", "template_version",
                  "approved_message_id", "attempt_series", "rendered_sha256")
OUTBOUND_PERSONAL = ("recipient",)
LINK_FIXED = ("id", "question_id", "inbound_message_id")


def tuple_of(prefix, columns):
    return "(" + ", ".join(f"{prefix}.{c}" for c in columns) + ")"


def retention_path(retention_literal, application_expr):
    """The one exception: a retention member with a stated reason, recorded in the audit table."""
    return f"""
          IF pg_catalog.pg_has_role(session_user, {retention_literal}, 'MEMBER')
             AND pg_catalog.length(pg_catalog.btrim(coalesce(
                   pg_catalog.current_setting('catalyst.retention_reason', true), ''))) >= {MIN_REASON} THEN
            INSERT INTO public.{AUDIT} (at, actor, table_name, row_id, application_id, row_sha256, reason)
              VALUES (pg_catalog.statement_timestamp(), session_user, TG_TABLE_NAME, OLD.id, {application_expr},
                      pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(OLD::text, 'UTF8')), 'hex'),
                      pg_catalog.btrim(pg_catalog.current_setting('catalyst.retention_reason')));
            RETURN NEW;
          END IF;"""


def frozen_function(name, label, fixed, personal, retention_literal, application_expr, extra=""):
    """A BEFORE UPDATE OR DELETE function: DELETE refused; a change to a fixed column refused; a change to a
    personal column allowed only on the audited retention path; anything else (the updatable columns) passes."""
    return f"""
        CREATE FUNCTION public.{name}() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION '{label}: DELETE refused (the record is frozen; erasure anonymizes, it never deletes)'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          IF {tuple_of("NEW", fixed)} IS DISTINCT FROM {tuple_of("OLD", fixed)} THEN
            RAISE EXCEPTION '{label}: UPDATE refused (the provenance and identity columns are frozen)'
              USING ERRCODE = 'insufficient_privilege';
          END IF;{extra}
          IF {tuple_of("NEW", personal)} IS DISTINCT FROM {tuple_of("OLD", personal)} THEN{retention_path(retention_literal, application_expr)}
            RAISE EXCEPTION '{label}: UPDATE refused (the personal columns are frozen; only the audited retention path changes them)'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """


MESSAGE_ID_SET_ONCE = """
          IF NEW.message_id IS DISTINCT FROM OLD.message_id AND OLD.message_id <> '' THEN
            RAISE EXCEPTION 'outbound attempt: UPDATE refused (message_id is set once)'
              USING ERRCODE = 'insufficient_privilege';
          END IF;"""

FUNCTIONS = (("catalyst_inbound_provenance_frozen", INBOUND), ("catalyst_outbound_identity_frozen", OUTBOUND),
             ("catalyst_reply_link_identity_frozen", LINK))


def protect(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["retention"]])
        retention = cursor.fetchone()[0]
    schema_editor.execute(frozen_function(
        "catalyst_inbound_provenance_frozen", "inbound message", INBOUND_FIXED, INBOUND_PERSONAL, retention,
        "coalesce(OLD.application_id, 0)"), params=None)
    schema_editor.execute(frozen_function(
        "catalyst_outbound_identity_frozen", "outbound attempt", OUTBOUND_FIXED, OUTBOUND_PERSONAL, retention,
        "OLD.application_id", extra=MESSAGE_ID_SET_ONCE), params=None)
    schema_editor.execute(f"""
        CREATE FUNCTION public.catalyst_reply_link_identity_frozen() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'DELETE' OR {tuple_of("NEW", LINK_FIXED)} IS DISTINCT FROM {tuple_of("OLD", LINK_FIXED)} THEN
            RAISE EXCEPTION 'reply link: % refused (the question and the message are frozen)', TG_OP
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """, params=None)
    for function, table in FUNCTIONS:
        schema_editor.execute(f"REVOKE ALL ON FUNCTION public.{function}() FROM PUBLIC")
        schema_editor.execute(f"CREATE TRIGGER {function} BEFORE UPDATE OR DELETE ON public.{table} "
                              f"FOR EACH ROW EXECUTE FUNCTION public.{function}()")
        schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{table} "
                              "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect(apps, schema_editor):
    for function, table in FUNCTIONS:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{table}")
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {function} ON public.{table}")
        schema_editor.execute(f"DROP FUNCTION IF EXISTS public.{function}()")


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0016_welcome_kind"), ("applications", "0002_history_protection")]
    operations = [migrations.RunPython(protect, unprotect)]
