"""9kg.33: envelopes after a restore (config.post_restore; 029 section 6.2), by provider read, outside the
post-restore transaction.

Every restored instance that is live is checked against Documenso:

- an instance with an envelope id is read by that id; an envelope whose status moved past what the restored record
  shows (completed, rejected, cancelled, or one the provider no longer has) opens one `restore_effect_envelope`
  item for the decision-maker, who settles it on the agreements screen before the hold lifts;
- an instance without an envelope id, whose create had not finished at the backup, is searched by its external
  key (the bounded listing the ordinary reconciliation uses); an envelope found there is one the restored system
  would create again, so it opens the same item.

Then every envelope Catalyst may have created after the backup is listed (9kg.76): the team's documents from every
template, newest first, back to an hour before the backup's start, so a template the restored tables do not know is
covered too. An envelope with Catalyst's key shape that no restored instance or attempt names, by envelope id or
external key, was created for an agreement the restore dropped; the restored system would create and distribute a
second one to the same signer, so it opens one `restore_effect_envelope` item keyed by the envelope id, which the
report also lists (the application is attached when exactly one verified applicant is a signer). The owner looks the
envelope up at Documenso and cancels or keeps it before the restored system issues its own, then resolves the item.

The listing fails closed (review of PR #119): it ends only on a short page or on an envelope older than the floor,
never on a page count the provider may omit; creation times must not increase down the listing, or the order is not
the one asked for; and the page limit is a limit, not an end. Each of those reports `incomplete:*`, and the lift
refuses.

A provider error leaves the evidence unreachable: reported, and the lift refuses. Nothing here writes to the
provider (029 section 6.2: no automatic repair of provider state).
"""

import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from correspondence.staff_items import event

from . import handlers, provider
from .models import NOT_LIVE, AgreementInstance, AgreementTemplateVersion, EnvelopeAttempt

ACTOR = "catalyst_post_restore"
ITEM_ENVELOPE = "restore_effect_envelope"
# A provider status that is an effect, and the restored signing states that already reflect it.
MOVED = {"COMPLETED": ("signing_complete_observed", "signing_complete_verified"), "REJECTED": ("declined",),
         "CANCELLED": ("cancelled",)}


KEY = re.compile(r"ag_[0-9a-f]{32}")  # handlers.new_key: an envelope without it is not Catalyst's (one writer per team)


def read_envelopes(since, opener) -> dict:
    instances = list(AgreementInstance.objects.select_related("application", "template_version")
                     .exclude(issue_status__in=NOT_LIVE).filter(replaced_at__isnull=True))
    if not provider.configured():
        # Nothing can be read here: fine only where agreements were never in use (no template, no instance).
        used = bool(instances) or AgreementTemplateVersion.objects.exists() or AgreementInstance.objects.exists()
        return {"status": "not_configured" if used else "ok", "checked": 0, "items": 0, "unknown": 0,
                "unknown_envelopes": []}
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
            return {"status": f"unreachable:{exc.code}", "checked": 0, "items": items, "unknown": 0, "unknown_envelopes": []}
        if moved:
            with transaction.atomic():
                if opener(ITEM_ENVELOPE, f"agreement:{instance.public_id}", application=instance.application):
                    event(instance.application, "restore_effect_envelope",
                          {"instance": str(instance.public_id), "had_envelope": bool(instance.envelope_id)}, actor_ref=ACTOR)
                    items += 1
    try:
        unknown, status = _unknown_envelopes(since)
    except provider.ProviderError as exc:
        return {"status": f"unreachable:{exc.code}", "checked": len(instances), "items": items, "unknown": 0,
                "unknown_envelopes": []}
    for env in unknown:
        application = _signer_application(env)
        with transaction.atomic():
            if opener(ITEM_ENVELOPE, f"unknown_envelope:{env.id}", application=application):
                if application is not None:
                    event(application, "restore_effect_unknown_envelope", {"envelope_id": env.id}, actor_ref=ACTOR)
                items += 1
    return {"status": status, "checked": len(instances), "items": items, "unknown": len(unknown),
            "unknown_envelopes": sorted(env.id for env in unknown)}


def _unknown_envelopes(since) -> tuple[list, str]:
    """Catalyst-keyed envelopes created since an hour before the backup's start that no restored row names, and the
    listing's status: "ok" only when it provably reached the floor or its end."""
    floor = (since or (timezone.now() - timedelta(days=30))) - timedelta(hours=1)
    ids = set(AgreementInstance.objects.exclude(envelope_id="").values_list("envelope_id", flat=True)) | set(
        EnvelopeAttempt.objects.exclude(envelope_id="").values_list("envelope_id", flat=True))
    keys = set(AgreementInstance.objects.values_list("external_key", flat=True)) | set(
        EnvelopeAttempt.objects.values_list("external_key", flat=True))
    unknown, last = [], None
    for page in range(1, settings.CATALYST_AGREEMENT_LIST_PAGES + 1):
        batch, reached = provider.find_recent(page), False
        for env in batch:
            created = handlers._created_at(env.created_at)
            if created is not None:
                if last is not None and created > last:
                    return unknown, "incomplete:listing_order"  # not newest first: the floor proves nothing
                last = created
                if created < floor:
                    reached = True
                    continue
            # An unreadable creation time counts as recent: an envelope is never dismissed for want of a date.
            if (env.type == "DOCUMENT" and KEY.fullmatch(env.external_id or "")
                    and env.id not in ids and env.external_id not in keys):
                unknown.append(env)
        if reached or len(batch) < settings.CATALYST_AGREEMENT_LIST_PAGE_SIZE:
            return unknown, "ok"  # past the floor (the order held), or a short page: the listing has ended
    return unknown, "incomplete:listing_limit"


def _signer_application(env):
    """The application whose verified address is one of the envelope's recipients, when exactly one matches."""
    from applications.models import Application
    from correspondence.messages import verified_address

    emails = {r.email.lower() for r in env.recipients if r.email}
    if not emails:
        return None
    found = [a for a in Application.objects.filter(contact_verified_at__isnull=False).order_by("id")
             if (verified_address(a) or "").lower() in emails]
    return found[0] if len(found) == 1 else None
