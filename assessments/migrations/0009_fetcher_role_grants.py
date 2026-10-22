"""9kg.24 (026 P6-D-14): the fetcher role's grants, exactly what `fetch_evidence` touches.

Traced from every statement FetchEvidence issued across the evidence and assessment suites (138 tests), and proven
by tests/test_fetcher_role.py, which runs the fetch as this role. The fetch itself reads the application, its
adopted submission, the sources and the item, and writes the item, its capture, history events and staff items. When
the last fetch completes collection it also moves the application's stage and queues the assessment run (freezing
the snapshot reads the confirmed answers, hence the question and inbound-message reads). Nothing else: no staff,
agreement, provisioning, mail or session table, and no grant to change history.
"""

from django.db import migrations

from config.db_roles import apply_grants

ACTION_UPDATE = "UPDATE (status, due_at, attempts, lease_token, lease_expires_at, last_error, updated_at, completed_at)"

forward, reverse = apply_grants({
    "applications_application": {"fetcher": ["SELECT", "UPDATE (stage, updated_at)"]},
    "applications_applicationevent": {"fetcher": ["SELECT", "INSERT"]},
    "applications_submissionversion": {"fetcher": ["SELECT"]},
    "applications_versionadoption": {"fetcher": ["SELECT"]},
    "assessments_assessmentrun": {"fetcher": ["SELECT", "INSERT"]},
    "assessments_evidencecapture": {"fetcher": ["SELECT", "INSERT"]},
    "assessments_evidenceitem": {"fetcher": ["SELECT", "UPDATE (status, reason_code, finished_at, updated_at)"]},
    "assessments_evidencesource": {"fetcher": ["SELECT"]},
    "correspondence_inboundmessage": {"fetcher": ["SELECT"]},
    "correspondence_question": {"fetcher": ["SELECT"]},
    "correspondence_questionreplylink": {"fetcher": ["SELECT"]},
    "correspondence_staffitem": {"fetcher": ["SELECT", "INSERT"]},
    "workflow_automationpause": {"fetcher": ["SELECT"]},
    "workflow_pendingaction": {"fetcher": ["SELECT", "INSERT", ACTION_UPDATE]},
    "django_migrations": {"fetcher": ["SELECT"]},
    "django_content_type": {"fetcher": ["SELECT"]},
})


class Migration(migrations.Migration):
    # Only what the granted tables need, so reversing and reapplying one app never drags in unrelated ones.
    dependencies = [("assessments", "0008_decision_protection"), ("workflow", "0002_role_grants"),
                    ("contenttypes", "0002_remove_content_type_name")]
    operations = [migrations.RunPython(forward, reverse)]
