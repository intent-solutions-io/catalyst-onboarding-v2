"""9kg.24 (026 P6-D-14): the fetcher role's grants, only what `fetch_evidence` itself does, each write pinned.

The fetcher handles untrusted pages, so a compromise must reach nothing but its own fetch (PR #71 security review).
It reads the application, the item and its source, and pauses; it records the item's result, a capture, evidence
history events, the evidence staff item and its own action's progress; and it asks the worker to check completion.
Completion itself (the stage, the assessment run, the snapshot) is the worker's (`complete_evidence_collection`).

Stated residual: the fetcher is the process that produces fetch results, so a compromised fetcher can record a
forged result for any item still pending (it can always claim that item's fetch first). It cannot touch a finished
item, another kind of action, an application, or anything outside the evidence path; captures keep the peer address
and digests, and staff review every assessment.

Grants alone cannot say *which* rows or values, so a trigger refuses, for a session in the fetcher role:
- a pending action insert other than a completion request exactly as the fetch makes it (naming a real item of
  that application), and an update to any action but a live `fetch_evidence` (no other kind, no revived row);
- any change to an application (it may only lock the row: a row lock needs an UPDATE grant);
- a change to an evidence item that is no longer pending;
- a history event or staff item of a kind the fetch never writes.
"""

from django.conf import settings
from django.db import migrations

from config.db_roles import apply_grants

ACTION_UPDATE = "UPDATE (status, due_at, attempts, lease_token, lease_expires_at, last_error, updated_at, completed_at)"
EVENT_KINDS = ("evidence_observed", "evidence_item_refused", "evidence_item_unavailable", "action_failed",
               "action_attempts_exhausted")
STAFF_ITEM_KINDS = ("evidence_collection_failed",)

forward, reverse = apply_grants({
    # Three columns, never contact details; UPDATE only so the row can be locked (the trigger refuses any change).
    "applications_application": {"fetcher": ["SELECT (id, public_ref, stage)", "UPDATE (updated_at)"]},
    "applications_applicationevent": {"fetcher": ["SELECT", "INSERT"]},
    "assessments_evidencecapture": {"fetcher": ["SELECT", "INSERT"]},
    "assessments_evidenceitem": {"fetcher": ["SELECT", "UPDATE (status, reason_code, finished_at, updated_at)"]},
    "assessments_evidencesource": {"fetcher": ["SELECT"]},
    "correspondence_staffitem": {"fetcher": ["SELECT", "INSERT"]},
    "workflow_automationpause": {"fetcher": ["SELECT"]},
    "workflow_pendingaction": {"fetcher": ["SELECT", "INSERT", ACTION_UPDATE]},
    "django_migrations": {"fetcher": ["SELECT"]},
    "django_content_type": {"fetcher": ["SELECT"]},
})

TRIGGERS = (  # (table, events, condition under which a fetcher session is refused)
    # A completion request exactly as request_completion makes it: due now, default attempts, and its key and version
    # naming a real evidence item of that application, so a squatted request is identical to the real one.
    ("workflow_pendingaction", "INSERT", "NOT (NEW.kind = 'complete_evidence_collection' AND NEW.status = 'queued'"
     " AND NEW.attempts = 0 AND NEW.max_attempts = 3 AND NEW.lease_token IS NULL AND NEW.due_at <= statement_timestamp()"
     " AND NEW.subject_type = 'application' AND NEW.input_ref ~ '^[0-9]+$' AND EXISTS (SELECT 1 FROM"
     " public.assessments_evidenceitem i JOIN public.applications_application a ON a.id = i.application_id"
     " WHERE a.public_ref = NEW.subject_id AND i.adopted_version_id = NEW.input_ref::bigint"
     " AND NEW.idempotency_key = 'complete_evidence_collection:' || i.public_id::text))"),
    ("workflow_pendingaction", "UPDATE", "NOT (OLD.kind = 'fetch_evidence' AND OLD.status IN ('queued', 'running'))"),
    ("applications_application", "UPDATE", "true"),
    ("assessments_evidenceitem", "UPDATE", "OLD.status <> 'pending'"),
    ("applications_applicationevent", "INSERT",
     "NOT (NEW.kind = ANY (ARRAY[" + ", ".join(f"'{k}'" for k in EVENT_KINDS) + "]) AND NEW.actor_type = 'system')"),
    ("correspondence_staffitem", "INSERT",
     "NOT (NEW.reason_code = ANY (ARRAY[" + ", ".join(f"'{k}'" for k in STAFF_ITEM_KINDS) + "]))"),
)


def _name(table, events):
    return f"catalyst_fetcher_{table}_{events.lower()}"[:63]


def protect(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT quote_literal(%s)", [settings.CATALYST_DB_ROLES["fetcher"]])
        fetcher = cursor.fetchone()[0]
    for table, events, refused in TRIGGERS:
        name = _name(table, events)
        schema_editor.execute(f"""
            CREATE FUNCTION public.{name}() RETURNS trigger
            LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
            BEGIN
              IF pg_catalog.pg_has_role(session_user, {fetcher}, 'MEMBER') AND ({refused}) THEN
                RAISE EXCEPTION 'fetcher: % on % refused', TG_OP, TG_TABLE_NAME USING ERRCODE = 'insufficient_privilege';
              END IF;
              RETURN NEW;
            END $$
        """, params=None)
        schema_editor.execute(f"REVOKE ALL ON FUNCTION public.{name}() FROM PUBLIC")
        schema_editor.execute(f"CREATE TRIGGER {name} BEFORE {events} ON public.{table}"
                              f" FOR EACH ROW EXECUTE FUNCTION public.{name}()")


def unprotect(apps, schema_editor):
    for table, events, _ in TRIGGERS:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {_name(table, events)} ON public.{table}")
        schema_editor.execute(f"DROP FUNCTION IF EXISTS public.{_name(table, events)}()")


class Migration(migrations.Migration):
    # Only what the granted tables need, so reversing and reapplying one app never drags in unrelated ones.
    dependencies = [("assessments", "0008_decision_protection"), ("workflow", "0002_role_grants"),
                    ("contenttypes", "0002_remove_content_type_name")]
    operations = [migrations.RunPython(forward, reverse), migrations.RunPython(protect, unprotect)]
