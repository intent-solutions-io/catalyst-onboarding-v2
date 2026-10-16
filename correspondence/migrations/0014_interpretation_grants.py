# P3 3B.3 (018 5.4; 3B.3). Runs as the migration owner.
#
# Reply interpretations are inserted before the model call and finished once: the application role may update
# only the result columns. The new question columns (criterion, gap, route, source, round, text key) need no
# grant change: they are written at insert and the existing UPDATE grant does not include them, so they never
# change afterwards.
from django.db import migrations

from config.db_roles import apply_grants

forward_grants, reverse_grants = apply_grants({
    "correspondence_replyinterpretation": {
        "app": ["SELECT", "INSERT", "UPDATE (status, code, proposals, problems, flags, provenance, finished_at)"],
        "retention": ["SELECT"],
    },
})


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0013_clarification_and_interpretation")]
    operations = [migrations.RunPython(forward_grants, reverse_grants)]
