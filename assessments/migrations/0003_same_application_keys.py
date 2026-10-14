# P3 3B.1 (QA review): an item's adopted version, and a capture's item, must belong to the same application.
# Django has no composite foreign key, so these are SQL constraints against the (id, application) unique
# constraints, deferred like Django's own foreign keys (the applications 0001 pattern).
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("assessments", "0002_grants_protection_and_groups")]
    operations = [
        migrations.RunSQL(
            sql=[
                "ALTER TABLE assessments_evidenceitem ADD CONSTRAINT evidence_item_version_same_application"
                " FOREIGN KEY (adopted_version_id, application_id)"
                " REFERENCES applications_submissionversion (id, application_id) DEFERRABLE INITIALLY DEFERRED",
                "ALTER TABLE assessments_evidencecapture ADD CONSTRAINT evidence_capture_item_same_application"
                " FOREIGN KEY (item_id, application_id)"
                " REFERENCES assessments_evidenceitem (id, application_id) DEFERRABLE INITIALLY DEFERRED",
            ],
            reverse_sql=[
                "ALTER TABLE assessments_evidencecapture DROP CONSTRAINT evidence_capture_item_same_application",
                "ALTER TABLE assessments_evidenceitem DROP CONSTRAINT evidence_item_version_same_application",
            ],
        ),
    ]
