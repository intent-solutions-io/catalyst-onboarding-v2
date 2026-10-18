# P5 5B.1 (023 sections 4 and 11; ADR-14). Runs as the migration owner.
#
# 1. Grants: the application role inserts and updates only the columns its services change. The retention role
#    reads.
# 2. Evidence is history: the strict append-only and no-truncate triggers. A checklist attestation by the person who
#    recorded the creation is refused for every role (P5-D-5: a different named verifier).
# 3. A request's identity, method, limits and digests are fixed at insert, and its approval is written once; a
#    reservation's identity is fixed and its release written once; an attempt's identity is fixed and its outcome
#    final once settled. No row is ever deleted, and none of these tables can be truncated.
# 4. The new permissions exist and are assigned to no group (named grants only, P5-D-3).
from django.contrib.auth.management import create_permissions
from django.db import migrations

from config.db_roles import apply_grants

RESERVATION = "provisioning_addressreservation"
REQUEST = "provisioning_provisioningrequest"
ATTEMPT = "provisioning_provisioningattempt"
EVIDENCE = "provisioning_provisioningevidence"

grant_forward, grant_reverse = apply_grants({
    RESERVATION: {"app": ["SELECT", "INSERT", "UPDATE (released_at, released_by)"], "retention": ["SELECT"]},
    REQUEST: {"app": ["SELECT", "INSERT",
                      "UPDATE (status, approved_by, approved_at, stop_requested_at, superseded_by_id, updated_at)"],
              "retention": ["SELECT"]},
    ATTEMPT: {"app": ["SELECT", "INSERT", "UPDATE (outcome, code, absent_before, finished_at)"], "retention": ["SELECT"]},
    EVIDENCE: {"app": ["SELECT", "INSERT"], "retention": ["SELECT"]},
})

FUNCTIONS = {
    "catalyst_provisioning_request_fixed": """
        BEGIN
          IF TG_OP = 'DELETE'
             OR (NEW.id, NEW.public_id, NEW.application_id, NEW.reservation_id, NEW.method, NEW.quota_mb, NEW.send_limit,
                 NEW.prerequisite_digest, NEW.approval_digest, NEW.created_at)
                IS DISTINCT FROM
                (OLD.id, OLD.public_id, OLD.application_id, OLD.reservation_id, OLD.method, OLD.quota_mb, OLD.send_limit,
                 OLD.prerequisite_digest, OLD.approval_digest, OLD.created_at)
             OR (OLD.approved_by <> '' AND (NEW.approved_by, NEW.approved_at) IS DISTINCT FROM (OLD.approved_by, OLD.approved_at))
             OR (OLD.stop_requested_at IS NOT NULL AND NEW.stop_requested_at IS DISTINCT FROM OLD.stop_requested_at)
             OR (OLD.superseded_by_id IS NOT NULL AND NEW.superseded_by_id IS DISTINCT FROM OLD.superseded_by_id) THEN
            RAISE EXCEPTION 'provisioning request: % refused (identity, limits and digests are fixed; approval and stop are set once)', TG_OP
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END""",
    "catalyst_provisioning_reservation_fixed": """
        BEGIN
          IF TG_OP = 'DELETE'
             OR (NEW.id, NEW.public_id, NEW.application_id, NEW.local_part, NEW.domain, NEW.basis, NEW.reviewed_by, NEW.created_at)
                IS DISTINCT FROM
                (OLD.id, OLD.public_id, OLD.application_id, OLD.local_part, OLD.domain, OLD.basis, OLD.reviewed_by, OLD.created_at)
             OR (OLD.released_at IS NOT NULL AND (NEW.released_at, NEW.released_by) IS DISTINCT FROM (OLD.released_at, OLD.released_by)) THEN
            RAISE EXCEPTION 'address reservation: % refused (the address is fixed; a release is written once)', TG_OP
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END""",
    "catalyst_provisioning_attempt_fixed": """
        BEGIN
          IF TG_OP = 'DELETE'
             OR (NEW.id, NEW.public_id, NEW.request_id, NEW.step, NEW.series, NEW.started_at)
                IS DISTINCT FROM (OLD.id, OLD.public_id, OLD.request_id, OLD.step, OLD.series, OLD.started_at)
             OR (OLD.outcome NOT IN ('sending', 'unknown') AND NEW.outcome IS DISTINCT FROM OLD.outcome)
             OR (OLD.outcome = 'unknown' AND NEW.outcome NOT IN ('unknown', 'found_by_evidence', 'not_created', 'conflict'))
             OR (OLD.absent_before AND NOT NEW.absent_before) THEN
            RAISE EXCEPTION 'provisioning attempt: % refused (identity is fixed; a settled outcome is final)', TG_OP
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END""",
    "catalyst_provisioning_verifier_differs": """
        BEGIN
          IF NEW.kind = 'checklist_attested' AND EXISTS (
               SELECT 1 FROM public.provisioning_provisioningevidence e
               WHERE e.request_id = NEW.request_id AND e.kind = 'checklist_created' AND e.actor_ref = NEW.actor_ref) THEN
            RAISE EXCEPTION 'provisioning evidence: the verifier must differ from the creator (P5-D-5)'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END""",
}
TRIGGERS = (
    ("catalyst_provisioning_request_fixed", REQUEST, "UPDATE OR DELETE"),
    ("catalyst_provisioning_reservation_fixed", RESERVATION, "UPDATE OR DELETE"),
    ("catalyst_provisioning_attempt_fixed", ATTEMPT, "UPDATE OR DELETE"),
    ("catalyst_provisioning_verifier_differs", EVIDENCE, "INSERT"),
)


def protect(apps, schema_editor):
    for name, body in FUNCTIONS.items():
        schema_editor.execute(f"CREATE FUNCTION public.{name}() RETURNS trigger LANGUAGE plpgsql "
                              f"SET search_path = public, pg_temp AS $$ {body} $$", params=None)
        schema_editor.execute(f"REVOKE ALL ON FUNCTION public.{name}() FROM PUBLIC")
    for name, table, events in TRIGGERS:
        schema_editor.execute(f"CREATE TRIGGER {name} BEFORE {events} ON public.{table} "
                              f"FOR EACH ROW EXECUTE FUNCTION public.{name}()")
    schema_editor.execute(f"CREATE TRIGGER catalyst_append_only BEFORE UPDATE OR DELETE ON public.{EVIDENCE} "
                          "FOR EACH ROW EXECUTE FUNCTION public.catalyst_append_only_strict()")
    for table in (RESERVATION, REQUEST, ATTEMPT, EVIDENCE):
        schema_editor.execute(f"CREATE TRIGGER catalyst_no_truncate BEFORE TRUNCATE ON public.{table} "
                              "FOR EACH STATEMENT EXECUTE FUNCTION public.catalyst_append_only_strict()")


def unprotect(apps, schema_editor):
    for table in (RESERVATION, REQUEST, ATTEMPT, EVIDENCE):
        schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_no_truncate ON public.{table}")
    schema_editor.execute(f"DROP TRIGGER IF EXISTS catalyst_append_only ON public.{EVIDENCE}")
    for name, table, _ in TRIGGERS:
        schema_editor.execute(f"DROP TRIGGER IF EXISTS {name} ON public.{table}")
    for name in FUNCTIONS:
        schema_editor.execute(f"DROP FUNCTION IF EXISTS public.{name}()")


def permissions(apps, schema_editor):
    config = apps.get_app_config("provisioning")
    config.models_module = True
    create_permissions(config, apps=apps, verbosity=0)  # assigned to no group


class Migration(migrations.Migration):
    dependencies = [("provisioning", "0001_provisioning_records")]
    operations = [migrations.RunPython(grant_forward, grant_reverse), migrations.RunPython(protect, unprotect),
                  migrations.RunPython(permissions, migrations.RunPython.noop)]
