# Least-privilege grants for the application role on outbound messages (ADR-14, D-17).
from django.db import migrations

from config.db_roles import apply_grants

forward, reverse = apply_grants({
    "correspondence_outboundmessage": {"app": ["SELECT", "INSERT", "UPDATE"]},
})


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0001_initial")]
    operations = [migrations.RunPython(forward, reverse)]
