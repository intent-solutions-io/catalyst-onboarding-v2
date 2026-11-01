# bgl.5: add CAT references without breaking an older image that inserts no reference column.
# Existing imported labels are preserved. A BEFORE INSERT trigger fills a missing/empty label for
# older writers; new ORM writers supply their own. The trigger executes without granting the app
# direct EXECUTE on any catalyst_* function and does not elevate the caller's privileges.
import secrets

from django.db import migrations, models

import applications.reference

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # frozen here: a migration never follows later code

CREATE_FUNCTION = f"""
    CREATE FUNCTION public.catalyst_application_reference() RETURNS trigger
    LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
    BEGIN
      IF NEW.reference IS NULL OR NEW.reference = '' THEN
      SELECT 'CAT-' || substr(s, 1, 4) || '-' || substr(s, 5, 4) INTO NEW.reference
      FROM (SELECT string_agg(substr('{ALPHABET}', ((r.n >> (5 * (7 - i))) & 31)::int + 1, 1), '' ORDER BY i) AS s
            FROM (SELECT ('x' || substr(pg_catalog.replace(pg_catalog.gen_random_uuid()::text, '-', ''), 1, 10))::bit(40)::bigint
                         AS n) r,
                 pg_catalog.generate_series(0, 7) i) t;
      END IF;
      RETURN NEW;
    END $$
"""


def _generate():
    chars = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return f"CAT-{chars[:4]}-{chars[4:]}"


def backfill(apps, schema_editor):
    Application = apps.get_model("applications", "Application")
    ImportedCase = apps.get_model("firstgen", "ImportedCase")
    for application_id, reference in ImportedCase.objects.values_list("application_id", "reference"):
        Application.objects.filter(pk=application_id, reference=None).update(reference=reference)
    taken = set(Application.objects.exclude(reference=None).values_list("reference", flat=True))
    for pk in Application.objects.filter(reference=None).order_by("id").values_list("pk", flat=True):
        candidate = _generate()
        while candidate in taken:
            candidate = _generate()
        taken.add(candidate)
        Application.objects.filter(pk=pk).update(reference=candidate)


class Migration(migrations.Migration):

    dependencies = [
        ('applications', '0010_lapsed_stage'),
        ('firstgen', '0002_protection'),
    ]

    operations = [
        migrations.RunSQL(CREATE_FUNCTION, "DROP FUNCTION IF EXISTS public.catalyst_application_reference()"),
        # Called only by its INSERT trigger, not directly by the application role.
        migrations.RunSQL("REVOKE ALL ON FUNCTION public.catalyst_application_reference() FROM PUBLIC", migrations.RunSQL.noop),
        migrations.AddField(
            model_name='application',
            name='reference',
            field=models.CharField(editable=False, max_length=13, null=True),
        ),
        migrations.RunSQL(
            "CREATE TRIGGER catalyst_application_reference BEFORE INSERT ON public.applications_application "
            "FOR EACH ROW EXECUTE FUNCTION public.catalyst_application_reference()",
            "DROP TRIGGER IF EXISTS catalyst_application_reference ON public.applications_application"),
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='application',
            name='reference',
            field=models.CharField(db_default="", default=applications.reference.new_reference, editable=False, max_length=13, unique=True),
        ),
        migrations.AddConstraint(
            model_name='application',
            constraint=models.CheckConstraint(condition=models.Q(('reference__regex', '^CAT-[0-9A-Z]{4}-[0-9A-Z]{4}$')), name='application_reference_format'),
        ),
    ]
