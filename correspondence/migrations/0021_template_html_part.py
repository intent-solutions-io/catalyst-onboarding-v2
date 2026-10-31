# bgl.11 (owner correction 2026-10-31): the first generation sends multipart mail, plain text plus a designed HTML
# part, so a message template version gains an optional HTML alternative (`body_html`, blank for a text-only version).
#
# - The column is added with a database default (""), so a previous image inserts versions without it and keeps
#   sending text only: expand-safe by the contracting scan (config.release), nothing removed or renamed.
# - The application role already holds table-level SELECT and INSERT on the table (0004) and may still update only
#   status, approved_by and approved_at: the HTML is written once, at insert.
# - `catalyst_template_version_frozen` (0015) is replaced with the HTML in the frozen tuple: once approved, the HTML is
#   as final as the subject and the text (9kg.1). The reverse restores 0015's function exactly.
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
             NEW.created_at{html_new})
            IS DISTINCT FROM
            (OLD.id, OLD.template_id, OLD.version, OLD.subject, OLD.body_text, OLD.variables::text,
             OLD.secret_bearing, OLD.approved_by, OLD.approved_at, OLD.content_sha256, OLD.synthetic,
             OLD.created_at{html_old}) THEN
        RAISE EXCEPTION 'message template version: % refused (an approved version is final; it may only retire)',
          TG_OP USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END $$
"""


def freeze_html(apps, schema_editor):
    schema_editor.execute(FROZEN.format(html_new=", NEW.body_html", html_old=", OLD.body_html"), params=None)


def unfreeze_html(apps, schema_editor):
    schema_editor.execute(FROZEN.format(html_new="", html_old=""), params=None)


class Migration(migrations.Migration):
    dependencies = [("correspondence", "0020_verification_template")]
    operations = [
        migrations.AddField(model_name="messagetemplateversion", name="body_html",
                            field=models.TextField(blank=True, default="", db_default="")),
        migrations.RunPython(freeze_html, unfreeze_html),
    ]
