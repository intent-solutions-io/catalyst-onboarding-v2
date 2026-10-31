# bgl.7 (034 row 21): the `lapsed` stage. An application the applicant has quietly left after the last reminder rests
# here instead of waiting out loud; it is open, not terminal (it keeps its email key and counts as open for erasure and
# retention), and a reply or a signature reopens it to the stage it lapsed from (correspondence.lapse). The two
# constraints that enumerate the stages are rebuilt with the new member. Written by hand in the shape Django 5.2.18
# generates; tests/test_database.py proves it matches the models (makemigrations --check).

from django.db import migrations, models

# Tuples, as the model declares them: the autodetector compares the deconstructed conditions, where a list is not a tuple.
OPEN = ("submitted", "contact_verified", "evidence", "assessing", "awaiting_answers", "awaiting_decision", "on_hold",
        "admitted", "agreements", "agreements_complete", "provisioning", "active", "lapsed")
ALL = OPEN + ("declined", "withdrawn", "closed")
CHOICES = [("submitted", "Submitted"), ("contact_verified", "Contact Verified"), ("evidence", "Evidence"),
           ("assessing", "Assessing"), ("awaiting_answers", "Awaiting Answers"), ("awaiting_decision", "Awaiting Decision"),
           ("on_hold", "On Hold"), ("admitted", "Admitted"), ("agreements", "Agreements"),
           ("agreements_complete", "Agreements Complete"), ("provisioning", "Provisioning"), ("active", "Active"),
           ("lapsed", "Lapsed"), ("declined", "Declined"), ("withdrawn", "Withdrawn"), ("closed", "Closed")]


class Migration(migrations.Migration):

    dependencies = [
        ("applications", "0009_tombstone_keys_unique"),
    ]

    operations = [
        migrations.RemoveConstraint(model_name="application", name="application_one_open_per_email_key"),
        migrations.RemoveConstraint(model_name="application", name="application_stage_valid"),
        migrations.AlterField(
            model_name="application", name="stage",
            field=models.CharField(choices=CHOICES, default="submitted", max_length=32),
        ),
        migrations.AddConstraint(
            model_name="application",
            constraint=models.UniqueConstraint(condition=models.Q(("stage__in", OPEN)), fields=("email_key",),
                                               name="application_one_open_per_email_key"),
        ),
        migrations.AddConstraint(
            model_name="application",
            constraint=models.CheckConstraint(condition=models.Q(("stage__in", ALL)), name="application_stage_valid"),
        ),
    ]
