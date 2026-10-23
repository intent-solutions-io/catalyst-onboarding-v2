"""9kg.33: envelopes after a restore (config.post_restore; 029 section 6.2), by provider read, outside the
post-restore transaction.

Every restored instance that is live is checked against Documenso:

- an instance with an envelope id is read by that id; an envelope whose status moved past what the restored record
  shows (completed, rejected, cancelled, or one the provider no longer has) opens one `restore_effect_envelope`
  item for the decision-maker, who settles it on the agreements screen before the hold lifts;
- an instance without an envelope id, whose create had not finished at the backup, is searched by its external
  key (the bounded listing the ordinary reconciliation uses); an envelope found there is one the restored system
  would create again, so it opens the same item.

A provider error leaves the evidence unreachable: reported, and the lift refuses. Nothing here writes to the
provider (029 section 6.2: no automatic repair of provider state).
"""

from django.db import transaction
from django.utils import timezone

from correspondence.staff_items import event, open_item

from . import handlers, provider
from .models import NOT_LIVE, AgreementInstance

ACTOR = "catalyst_post_restore"
ITEM_ENVELOPE = "restore_effect_envelope"
# A provider status that is an effect, and the restored signing states that already reflect it.
MOVED = {"COMPLETED": ("signing_complete_observed", "signing_complete_verified"), "REJECTED": ("declined",),
         "CANCELLED": ("cancelled",)}


def read_envelopes(since) -> dict:
    instances = list(AgreementInstance.objects.select_related("application", "template_version")
                     .exclude(issue_status__in=NOT_LIVE).filter(replaced_at__isnull=True))
    if not instances:
        return {"status": "ok", "checked": 0, "items": 0}
    if not provider.configured():
        return {"status": "not_configured", "checked": 0, "items": 0}
    items = 0
    for instance in instances:
        try:
            if instance.envelope_id:
                try:
                    env = provider.read(instance.envelope_id)
                except provider.ProviderError as exc:
                    if exc.status != 404:
                        raise
                    env = None
                moved = env is None or (env.status in MOVED and instance.signing_status not in MOVED[env.status]
                                        and not (env.status == "CANCELLED" and instance.issue_status.startswith("cancel")))
            else:
                floor = since or (timezone.now() - timezone.timedelta(days=30))
                moved = bool(handlers.search(instance, instance.external_key, floor))
        except provider.ProviderError as exc:
            return {"status": f"unreachable:{exc.code}", "checked": 0, "items": items}
        if moved:
            with transaction.atomic():
                open_item(ITEM_ENVELOPE, f"agreement:{instance.public_id}", application=instance.application, audit=False)
                event(instance.application, "restore_effect_envelope",
                      {"instance": str(instance.public_id), "had_envelope": bool(instance.envelope_id)}, actor_ref=ACTOR)
            items += 1
    return {"status": "ok", "checked": len(instances), "items": items}
