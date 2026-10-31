# bgl.5 (034 rows 6, 7 and 9): every application carries the first generation's `CAT-XXXX-XXXX` reference
# (applications.reference). Added nullable, backfilled for every existing application with a fresh random reference,
# then made required and unique with its format check. The ORM sets it from Python (`reference.new_reference`); a row
# inserted outside the ORM gets the database default, `public.catalyst_new_reference()`: the same alphabet and length,
# from the first 40 bits of a `gen_random_uuid()` (random in version 4, from PostgreSQL's strong random source). The
# application role keeps its column-level UPDATE grant (migration 0002), which does not name the column, so once set the
# reference is never changed by the application; the table-level INSERT lets the application and the owner-run importer
# set it at creation. Like every catalyst_* function, the default is not executable by the application role (the ORM
# always supplies the value); the owner-run paths may rely on it.
import secrets

import django.db.models.expressions
from django.db import migrations, models

import applications.reference

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # frozen here: a migration never follows later code

CREATE_FUNCTION = f"""
    CREATE FUNCTION public.catalyst_new_reference() RETURNS text
    LANGUAGE sql VOLATILE SET search_path = public, pg_temp AS $$
      SELECT 'CAT-' || substr(s, 1, 4) || '-' || substr(s, 5, 4)
      FROM (SELECT string_agg(substr('{ALPHABET}', ((r.n >> (5 * (7 - i))) & 31)::int + 1, 1), '' ORDER BY i) AS s
            FROM (SELECT ('x' || substr(pg_catalog.replace(pg_catalog.gen_random_uuid()::text, '-', ''), 1, 10))::bit(40)::bigint
                         AS n) r,
                 pg_catalog.generate_series(0, 7) i) t
    $$
"""


def _generate():
    chars = "".join(secrets.choice(ALPHABET) for _ in range(8))
    return f"CAT-{chars[:4]}-{chars[4:]}"


def backfill(apps, schema_editor):
    Application = apps.get_model("applications", "Application")
    taken = set(Application.objects.exclude(reference=None).values_list("reference", flat=True))
    for pk in Application.objects.filter(reference=None).order_by("id").values_list("pk", flat=True):
        candidate = _generate()
        while candidate in taken:
            candidate = _generate()
        taken.add(candidate)
        Application.objects.filter(pk=pk).update(reference=candidate)


class Migration(migrations.Migration):

    dependencies = [
        ('applications', '0009_tombstone_keys_unique'),
    ]

    operations = [
        migrations.RunSQL(CREATE_FUNCTION, "DROP FUNCTION IF EXISTS public.catalyst_new_reference()"),
        # Like every catalyst_* function, not executable by the application role: the ORM always supplies the value.
        migrations.RunSQL("REVOKE ALL ON FUNCTION public.catalyst_new_reference() FROM PUBLIC", migrations.RunSQL.noop),
        migrations.AddField(
            model_name='application',
            name='reference',
            field=models.CharField(editable=False, max_length=13, null=True),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='application',
            name='reference',
            field=models.CharField(db_default=django.db.models.expressions.Func(function='public.catalyst_new_reference', output_field=models.CharField()), default=applications.reference.new_reference, editable=False, max_length=13, unique=True),
        ),
        migrations.AddConstraint(
            model_name='application',
            constraint=models.CheckConstraint(condition=models.Q(('reference__regex', '^CAT-[0-9A-Z]{4}-[0-9A-Z]{4}$')), name='application_reference_format'),
        ),
    ]
