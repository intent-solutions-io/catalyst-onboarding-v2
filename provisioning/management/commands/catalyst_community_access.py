"""Privileged staff decision import; preview only unless exact digest is supplied.

The process operator authenticates the named staff reviewer out of band. This is
not a public identity-verification endpoint, and a JSON digest is not evidence of
approval. It enqueues ordinary jobs; it never calls Discord or grants permissions.
"""

import hashlib
import json
import os
import stat
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from applications.models import Application
from provisioning import community, services
from provisioning.models import CommunityAccess


class Command(BaseCommand):
    help = (
        "Preview a reviewed community decision from a private file; no provider call."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "operation", choices=("approve", "revoke", "confirm-offboarding")
        )
        parser.add_argument("--application", required=True)
        parser.add_argument("--reviewer", type=int, required=True)
        parser.add_argument("--decision-file")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expected-digest")

    def handle(self, *args, **options):
        try:
            user = get_user_model().objects.get(pk=options["reviewer"])
            services.require(user, "approve_community_access")
            app = Application.objects.get(public_ref=options["application"])
            decision = {}
            if options["operation"] in ("approve", "confirm-offboarding"):
                path = Path(options["decision_file"] or "")
                info = path.lstat()
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o077
                    or info.st_size > 4096
                ):
                    raise ValueError("private_file_required")
                with os.fdopen(
                    os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "r"
                ) as handle:
                    decision = json.load(handle)
                allowed = (
                    {
                        "guild_id",
                        "user_id",
                        "joined_at",
                        "identity_evidence",
                        "decision_evidence",
                        "certified_evidence",
                        "leaders_evidence",
                        "reapprove",
                    }
                    if options["operation"] == "approve"
                    else {"evidence"}
                )
                if not isinstance(decision, dict) or set(decision) - allowed:
                    raise ValueError("decision_fields_refused")
            elif options["decision_file"]:
                raise ValueError("revocation_file_not_used")
            prior = (
                CommunityAccess.objects.filter(application=app)
                .values("revision", "revoked", "requires_review")
                .first()
            )
            value = {
                "operation": options["operation"],
                "application": str(app.public_ref),
                "stage": app.stage,
                "reviewer": user.pk,
                "decision": decision,
                "prior": prior,
            }
            digest = hashlib.sha256(
                json.dumps(value, sort_keys=True).encode()
            ).hexdigest()
            if options["apply"]:
                if options["expected_digest"] != digest:
                    raise ValueError("fresh_digest_required")
                if options["operation"] == "approve":
                    community.approve(
                        app.pk,
                        user,
                        expected_revision=prior["revision"] if prior else 0,
                        **decision,
                    )
                elif options["operation"] == "confirm-offboarding":
                    community.confirm_offboarding(
                        app.pk,
                        user,
                        expected_revision=prior["revision"] if prior else 0,
                        **decision,
                    )
                else:
                    community.revoke(
                        app.pk,
                        user,
                        expected_revision=prior["revision"] if prior else 0,
                    )
            self.stdout.write(
                json.dumps(
                    {
                        "applied": options["apply"],
                        "sha256": digest,
                        "provider_calls": 0,
                        "roles_granted": 0,
                    }
                )
            )
        except Exception as exc:
            raise CommandError(
                f"community decision refused ({type(exc).__name__})"
            ) from None
