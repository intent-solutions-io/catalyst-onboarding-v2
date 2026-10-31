# bgl.5 (the owner's parity direction of 2026-10-31; 034 row 9): a message template version may ask the sender to
# append the application's `CAT-` reference to its static subject (`subject_reference`). This amends 016 A1 for the
# reference alone: no other variable ever reaches a subject. The flag is part of the version's content digest
# (correspondence.rendering.version_digest) and, like the rest of an approved version, final: the protection function of
# migration 0015 is replaced with one that also compares it. Every existing version keeps `false` and its digest. The
# application role's column grants (migration 0004: SELECT, INSERT, UPDATE of the approval columns only) already let it
# set the flag on insert and never change it.
from django.db import migrations, models

FROZEN = """
        CREATE OR REPLACE FUNCTION public.catalyst_template_version_frozen() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.status IS DISTINCT FROM 'draft' OR NEW.approved_by <> '' OR NEW.approved_at IS NOT NULL THEN
              RAISE EXCEPTION 'message template version: a version is inserted as a draft and approved by the owner'
                USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
          END IF;
          IF OLD.status = 'draft' THEN
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
          END IF;
          IF TG_OP = 'DELETE'
             OR (NEW.status IS DISTINCT FROM OLD.status AND NOT (OLD.status = 'approved' AND NEW.status = 'retired'))
             OR (NEW.id, NEW.template_id, NEW.version, NEW.subject, NEW.body_text, NEW.variables::text,
                 NEW.secret_bearing, NEW.approved_by, NEW.approved_at, NEW.content_sha256, NEW.synthetic,
                 NEW.created_at, NEW.subject_reference)
                IS DISTINCT FROM
                (OLD.id, OLD.template_id, OLD.version, OLD.subject, OLD.body_text, OLD.variables::text,
                 OLD.secret_bearing, OLD.approved_by, OLD.approved_at, OLD.content_sha256, OLD.synthetic,
                 OLD.created_at, OLD.subject_reference) THEN
            RAISE EXCEPTION 'message template version: % refused (an approved version is final; it may only retire)',
              TG_OP USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """

FROZEN_BEFORE = """
        CREATE OR REPLACE FUNCTION public.catalyst_template_version_frozen() RETURNS trigger
        LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
        BEGIN
          IF TG_OP = 'INSERT' THEN
            IF NEW.status IS DISTINCT FROM 'draft' OR NEW.approved_by <> '' OR NEW.approved_at IS NOT NULL THEN
              RAISE EXCEPTION 'message template version: a version is inserted as a draft and approved by the owner'
                USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
          END IF;
          IF OLD.status = 'draft' THEN
            RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
          END IF;
          IF TG_OP = 'DELETE'
             OR (NEW.status IS DISTINCT FROM OLD.status AND NOT (OLD.status = 'approved' AND NEW.status = 'retired'))
             OR (NEW.id, NEW.template_id, NEW.version, NEW.subject, NEW.body_text, NEW.variables::text,
                 NEW.secret_bearing, NEW.approved_by, NEW.approved_at, NEW.content_sha256, NEW.synthetic,
                 NEW.created_at)
                IS DISTINCT FROM
                (OLD.id, OLD.template_id, OLD.version, OLD.subject, OLD.body_text, OLD.variables::text,
                 OLD.secret_bearing, OLD.approved_by, OLD.approved_at, OLD.content_sha256, OLD.synthetic,
                 OLD.created_at) THEN
            RAISE EXCEPTION 'message template version: % refused (an approved version is final; it may only retire)',
              TG_OP USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END $$
    """


def protect(apps, schema_editor):
    schema_editor.execute(FROZEN, params=None)  # params=None: the RAISE format's % signs are not query placeholders


def unprotect(apps, schema_editor):
    schema_editor.execute(FROZEN_BEFORE, params=None)


class Migration(migrations.Migration):

    dependencies = [
        ('correspondence', '0020_verification_template'),
    ]

    operations = [
        migrations.AddField(
            model_name='messagetemplateversion',
            name='subject_reference',
            field=models.BooleanField(db_default=False, default=False),
        ),
        migrations.RunPython(protect, unprotect),
    ]
