"""9kg.55: one current template, immutable approval history and bounded legacy adoption."""

from django.db import migrations, models

OLD_GUARD = "IF TG_OP = 'DELETE' OR OLD.status <> 'draft'"
NEW_GUARD = """IF TG_OP = 'DELETE'
             OR (OLD.status <> 'draft' AND NOT (
                 OLD.status = 'approved' AND NEW.status = 'retired'
                 AND (NEW.approved_by, NEW.approved_at)
                     IS NOT DISTINCT FROM (OLD.approved_by, OLD.approved_at)))
             OR (OLD.status = 'draft' AND NEW.status NOT IN ('draft', 'approved'))"""
REVERSE_GUARD = NEW_GUARD.replace(
    "OLD.status = 'approved' AND NEW.status = 'retired'",
    "OLD.status = 'retired' AND NEW.status = 'approved'",
)
OLD_VERSION = "AND v.status = 'approved'"
NEW_VERSION = """AND (v.status = 'approved' OR (v.status = 'retired'
                             AND NEW.issue_status = 'held'
                             AND EXISTS (
                               SELECT 1 FROM public.firstgen_importedrecord r
                               JOIN public.agreements_agreementtype t ON t.id = v.agreement_type_id
                               WHERE r.application_id = NEW.application_id AND r.v1_table = 'agreement'
                                 AND r.data->>'document_type' = t.key
                                 AND r.data->>'external_ref' = NEW.external_key
                                 AND COALESCE(r.data->>'provider_ref', '') <> ''
                             )))"""


def replace_function(schema_editor, name, old, new):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_get_functiondef(%s::regprocedure)", [f"public.{name}()"]
        )
        definition = cursor.fetchone()[0]
    if definition.count(old) != 1:
        raise RuntimeError(f"unexpected template protection definition: {name}")
    schema_editor.execute(definition.replace(old, new), params=None)


def forwards(apps, schema_editor):
    replace_function(
        schema_editor, "catalyst_agreement_template_frozen", OLD_GUARD, NEW_GUARD
    )
    # Preserve the exact version the old highest-approved selector already chose, and every approval tuple.
    schema_editor.execute("""
        UPDATE agreements_agreementtemplateversion old SET status = 'retired'
        WHERE old.status = 'approved' AND EXISTS (
            SELECT 1 FROM agreements_agreementtemplateversion newer
            WHERE newer.agreement_type_id = old.agreement_type_id
              AND newer.status = 'approved' AND newer.version > old.version)
    """)
    # The imported records are owner-written and immutable to the application role. Ordinary issuance has a new
    # external key and cannot use a retired version. Adoption still verifies the real envelope and all recipients
    # before this insert; the SQL exception preserves only an identity already recorded by the legacy importer.
    replace_function(
        schema_editor, "catalyst_agreement_instance_insert", OLD_VERSION, NEW_VERSION
    )


def backwards(apps, schema_editor):
    replace_function(
        schema_editor, "catalyst_agreement_instance_insert", NEW_VERSION, OLD_VERSION
    )
    # The unique index is removed first by reverse operation order. Restore historical approvals before restoring
    # the old status constraint/trigger. Monotonically newer approvals keep the old highest-version selector valid.
    replace_function(
        schema_editor, "catalyst_agreement_template_frozen", NEW_GUARD, REVERSE_GUARD
    )
    schema_editor.execute(
        "UPDATE agreements_agreementtemplateversion SET status = 'approved' WHERE status = 'retired'"
    )
    replace_function(
        schema_editor, "catalyst_agreement_template_frozen", REVERSE_GUARD, OLD_GUARD
    )


class Migration(migrations.Migration):
    dependencies = [
        ("agreements", "0013_restore_transaction_time"),
        ("firstgen", "0002_protection"),
    ]
    operations = [
        migrations.RemoveConstraint(
            model_name="agreementtemplateversion",
            name="agreement_template_status_valid",
        ),
        migrations.AlterField(
            model_name="agreementtemplateversion",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("approved", "Approved"),
                    ("retired", "Retired"),
                ],
                default="draft",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="agreementtemplateversion",
            constraint=models.CheckConstraint(
                condition=models.Q(status__in=["draft", "approved", "retired"]),
                name="agreement_template_status_valid",
            ),
        ),
        migrations.RunPython(forwards, backwards),
        migrations.AddConstraint(
            model_name="agreementtemplateversion",
            constraint=models.UniqueConstraint(
                fields=["agreement_type"],
                condition=models.Q(status="approved"),
                name="agreement_template_one_current",
            ),
        ),
    ]
