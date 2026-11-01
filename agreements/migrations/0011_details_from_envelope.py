# bgl.8 (034 section 2.3 row 32; 021 section 8, D-46): a details version may be read back from the signed envelope.
#
# 1. `source` ("staff", the default for every existing row, or "envelope") and `instance` (the agreement the values were
#    read from; required for an envelope version, absent for a staff one); one envelope read per instance.
# 2. The frozen trigger of 0008 is left as it is, on purpose: erasure 0002 injected the erasure branch into it, and
#    replacing the function here would drop that branch (or, reversed with erasure, leave a body that is not 0008's).
#    The new columns are write-once anyway: the application role's UPDATE grant is limited to the confirmation columns,
#    an envelope version is confirmed in the transaction that inserts it, and the trigger refuses every change to a
#    confirmed version for every role. The check constraints below tie a source to its origin.
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("agreements", "0010_custody_envelope")]
    operations = [
        migrations.AddField(
            model_name="agreementdetailsversion", name="source",
            field=models.CharField(choices=[("staff", "Staff"), ("envelope", "Envelope")], db_default="staff",
                                   default="staff", max_length=16),
        ),
        migrations.AddField(
            model_name="agreementdetailsversion", name="instance",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="details_versions", to="agreements.agreementinstance"),
        ),
        migrations.AddConstraint(
            model_name="agreementdetailsversion",
            constraint=models.CheckConstraint(condition=models.Q(("source__in", ["staff", "envelope"])), name="details_source_valid"),
        ),
        migrations.AddConstraint(
            model_name="agreementdetailsversion",
            constraint=models.CheckConstraint(
                condition=(models.Q(("instance__isnull", True), ("source", "staff"))
                           | models.Q(("instance__isnull", False), ("source", "envelope"))),
                name="details_envelope_names_its_instance"),
        ),
        migrations.AddConstraint(
            model_name="agreementdetailsversion",
            constraint=models.UniqueConstraint(condition=models.Q(("source", "envelope")), fields=("instance",),
                                               name="details_one_envelope_read_per_instance"),
        ),
    ]
