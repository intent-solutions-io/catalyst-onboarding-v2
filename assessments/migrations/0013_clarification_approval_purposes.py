"""Permit owner approvals for the two existing clarification callers.

Expand-only for image rollback: previous readers filter their own purpose and the
previous owner's assessment/interpretation writes still satisfy this constraint.
No approval record, privilege or immutable-record guard changes.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("assessments", "0012_restore_transaction_time")]

    operations = [
        migrations.RemoveConstraint(
            model_name="modeluseapproval", name="model_use_purpose_valid"
        ),
        migrations.AddConstraint(
            model_name="modeluseapproval",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    purpose__in=[
                        "assessment",
                        "interpretation",
                        "clarification_draft",
                        "clarification_check",
                    ]
                ),
                name="model_use_purpose_valid",
            ),
        ),
    ]
