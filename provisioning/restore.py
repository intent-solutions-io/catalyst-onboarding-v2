"""9kg.33: closures, revocations and mailbox facts after a restore (config.post_restore; 029 section 6.2).

From the effect journal, inside the post-restore transaction:

- `application_closed`: a restored application that is not closed is closed again through `closure.close_locked`
  (the same stop intents, cancellations and revocation obligations as the original closure), as the system actor.
- `access_revocation`: a restored obligation whose state is not final takes the journaled final state, so a
  removal that happened is not reported as outstanding; the revocation round the review queues still runs and
  reads the provider, which is harmless and confirms it.

From the mail host, outside the transaction (`read_mailboxes`): every restored request under which a mailbox may
exist is read by address. A mailbox the restored record does not account for, or a mailbox the restored record
relies on that is gone, opens one `restore_effect_mailbox` item per request. An adapter error means the evidence
is unreachable: reported, and the lift refuses. Credentials are not readable at the host (the adapter's set is
write-only), so a password set after the backup is not reconciled here: the review has already closed every
open setup and marked an in-flight set uncertain, and staff reissue the link.
"""

import uuid

from django.db import transaction
from django.db.models import Q

from applications.models import TERMINAL_STAGES, Application, ApplicationEvent
from correspondence.staff_items import event

from . import adapter, closure
from .models import LIVE_REQUEST, AccessRevocation, ProvisioningRequest

ACTOR = "catalyst_post_restore"


def _uuid(text: str):
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


ITEM_MAILBOX = "restore_effect_mailbox"
MAY_HOLD = (*LIVE_REQUEST, "active", "stopping", "stopped", "recovered_after_stop")


def replay(entries, opener) -> dict:
    report = {"replayed": 0, "reflected": 0, "items": 0, "target_missing": 0}
    for entry in entries:
        if entry.kind == "application_closed":
            application = Application.objects.select_for_update(of=("self",)).filter(
                public_ref=_uuid(entry.key.removeprefix("application:"))).first()
            if application is None:
                report["target_missing"] += 1
                continue
            if application.stage in TERMINAL_STAGES:
                report["reflected"] += 1
                continue
            outcome = entry.data.get("outcome") if entry.data.get("outcome") in closure.OUTCOMES else "closed"
            closure.close_locked(application, outcome, "replayed from the effect journal after a restore", ACTOR,
                                 ApplicationEvent.ActorType.SYSTEM)
            event(application, "restore_effect_replayed", {"kind": entry.kind, "seq": entry.seq}, actor_ref=ACTOR)
            report["replayed"] += 1
        elif entry.kind == "access_revocation":
            _, request_ref, kind = entry.key.split(":", 2)
            state = entry.data.get("state")
            if state not in closure.FINAL:
                report["reflected"] += 1
                continue
            if not AccessRevocation.objects.filter(request__public_id=_uuid(request_ref), kind=kind).exists():
                report["target_missing"] += 1
                continue
            rows = AccessRevocation.objects.filter(request__public_id=_uuid(request_ref), kind=kind).exclude(state__in=closure.FINAL)
            row = rows.select_related("request__application").first()
            if row is None:
                report["reflected"] += 1
                continue
            fields = {"state": state}
            if state == "exception":
                fields.update(decided_by=ACTOR, note="replayed from the effect journal after a restore")
            rows.update(**fields)
            event(row.request.application, "restore_effect_replayed", {"kind": entry.kind, "seq": entry.seq}, actor_ref=ACTOR)
            report["replayed"] += 1
    return report


def read_mailboxes(opener) -> dict:
    """The provider read, outside any transaction. Returns {"status": "ok" | "not_configured" | "unreachable:<code>",
    "checked": n, "items": n}."""
    # 9kg.25: an erased subject's reserved name is a tombstone, so a read by it says nothing (the mailbox is a handoff).
    requests = list(ProvisioningRequest.objects.select_related("reservation", "application").filter(status__in=MAY_HOLD)
                    .exclude(Q(application__email_key__startswith="erased:") & ~Q(application__email_key__contains="@")))
    if not requests:
        return {"status": "ok", "checked": 0, "items": 0}
    try:
        host = adapter.host()
    except adapter.AdapterError as exc:
        return {"status": "not_configured" if exc.code == "no_adapter_configured" else f"unreachable:{exc.code}",
                "checked": 0, "items": 0}
    items = 0
    for request in requests:
        domain, local = request.reservation.domain, request.reservation.local_part
        try:
            mailbox = host.read(domain, local)
        except adapter.AdapterError as exc:
            return {"status": f"unreachable:{exc.code}", "checked": 0, "items": items}
        except Exception as exc:  # an adapter defect reads as unreachable, never as "absent"
            return {"status": f"unreachable:{type(exc).__name__.lower()}", "checked": 0, "items": items}
        present = mailbox is not None
        expected = closure.proven_ours(request) or request.status in ("found_by_evidence", "created", "verify_uncertain",
                                                                      "verified", "active")
        if present != expected:
            with transaction.atomic():
                if opener(ITEM_MAILBOX, f"provisioning:{request.public_id}", application=request.application):
                    event(request.application, "restore_effect_mailbox",
                          {"request": str(request.public_id), "present": present, "expected": expected}, actor_ref=ACTOR)
                    items += 1
    return {"status": "ok", "checked": len(requests), "items": items}
