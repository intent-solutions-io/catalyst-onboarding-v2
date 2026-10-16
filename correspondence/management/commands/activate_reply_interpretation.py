"""Release message-level reply interpretation for replies received before it was activated (018 5.4; P3 3B.3).
Owner-run, versioned and tied to an approval reference, like the other activation commands. It refuses unless
the version given is the one in force (`CATALYST_REPLY_INTERPRETATION_ACTIVATION`). Only replies still awaiting
processing, `trusted`, eligible and with a pending question get one `interpret_message` action. Prints counts
only."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from applications.models import Application, ApplicationEvent
from correspondence.models import InboundMessage
from correspondence.processing import create_interpretation


class Command(BaseCommand):
    help = "Queue reply interpretation for replies awaiting processing (018 5.4); --approval-ref is required."

    def add_arguments(self, parser):
        parser.add_argument("--activation-version", type=int, required=True)
        parser.add_argument("--approval-ref", required=True)

    def handle(self, *args, activation_version, approval_ref, **options):
        if activation_version < 1 or activation_version != settings.CATALYST_REPLY_INTERPRETATION_ACTIVATION:
            raise CommandError("that activation version is not in force")
        if not approval_ref.strip():
            raise CommandError("an approval reference is required")
        report = {"queued": 0, "skipped": 0}
        pending = (InboundMessage.objects.filter(status=InboundMessage.Status.AWAITING_PROCESSING, application__isnull=False)
                   .values_list("pk", "application_id").order_by("pk"))
        for message_pk, application_pk in pending:
            with transaction.atomic():
                application = Application.objects.select_for_update(of=("self",)).get(pk=application_pk)
                message = InboundMessage.objects.select_for_update(of=("self",)).get(pk=message_pk)
                if not create_interpretation(application, message):
                    report["skipped"] += 1
                    continue
                report["queued"] += 1
                ApplicationEvent.objects.create(application=application, kind="reply_interpretation_activated",
                                                actor_type=ApplicationEvent.ActorType.SYSTEM, actor_ref="owner_command",
                                                data={"activation_version": activation_version, "approval_ref": approval_ref,
                                                      "message": str(message.public_id)})
        self.stdout.write(json.dumps(report, sort_keys=True))
