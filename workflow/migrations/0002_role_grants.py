# Least-privilege grants for the application role on the pending-action ledger (ADR-14, D-17).
# Operational tables: updatable through approved services. Pending actions are never deleted; pauses are
# removed when staff resume automation.
from django.db import migrations

from config.db_roles import apply_grants

forward, reverse = apply_grants({
    "workflow_pendingaction": {"app": [
        "SELECT", "INSERT",
        "UPDATE (status, due_at, attempts, lease_token, lease_expires_at, last_error, updated_at, completed_at)",
    ]},
    "workflow_automationpause": {"app": ["SELECT", "INSERT", "DELETE"]},
})


class Migration(migrations.Migration):
    dependencies = [("workflow", "0001_initial")]
    operations = [migrations.RunPython(forward, reverse)]
