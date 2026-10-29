"""Add the real wave 1 wording (correspondence.wording) as new draft versions for the owner to approve (D-53).

    manage.py catalyst_seed_wording

For each template (the data notice, the invitation and the verification mail): if a version with the same content
digest already exists, nothing is added; otherwise the next version number is added as a draft, not synthetic, with
the template's own secret-bearing flag. Nothing is approved here: the owner reads and approves each version on the
template screen (D-29), and only then does a live environment serve it. Prints one JSON line of keys, version numbers
and digests, never the wording. Exit 0; 1 when a template is missing (its seed migration has not run).
"""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Max

from correspondence.models import MessageTemplate, MessageTemplateVersion
from correspondence.rendering import canonical_digest
from correspondence.wording import REAL


class Command(BaseCommand):
    help = "Add the real wave 1 wording as draft versions for the owner to approve (never approves)."

    def handle(self, *args, **options):
        out = {}
        with transaction.atomic():
            for key, (subject, body, variables) in REAL.items():
                # No row lock: the app login may not lock templates; (template, version) is unique, so a racing
                # second run fails on insert and adds nothing.
                template = MessageTemplate.objects.filter(key=key).first()
                if template is None:
                    raise CommandError(f"refused ({key}_missing): run the migrations first")
                digest = canonical_digest(subject, body)
                found = MessageTemplateVersion.objects.filter(template=template, content_sha256=digest).first()
                if found is not None:
                    out[key] = {"version": found.version, "sha256": digest, "added": False, "status": str(found.status)}
                    continue
                number = (MessageTemplateVersion.objects.filter(template=template).aggregate(n=Max("version"))["n"] or 0) + 1
                MessageTemplateVersion.objects.create(
                    template=template, version=number, subject=subject, body_text=body, variables=list(variables),
                    secret_bearing=template.secret_bearing, status="draft", content_sha256=digest, synthetic=False)
                out[key] = {"version": number, "sha256": digest, "added": True, "status": "draft"}
        self.stdout.write(json.dumps(out, sort_keys=True))
