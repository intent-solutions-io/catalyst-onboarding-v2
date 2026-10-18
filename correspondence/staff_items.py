"""The staff exception queue (016 3.8; owner decision D-28, A-2).

`open_item` is idempotent per (reason, dedupe key) while an item is open: a retrying worker never opens a
duplicate. `resolve_item` writes the immutable `StaffItemResolution` (INSERT-only for the application
role) whether or not an application is known, and an append-only event when one is. Items, resolutions
and events carry identifiers and reason codes only: never an address, subject or body.
"""

import re

from django.db import IntegrityError, transaction

from applications.links import CONFIRM_PATH
from applications.models import ApplicationEvent

from .common import Refused
from .models import StaffItem, StaffItemResolution

OPEN_KEY = "staff_item_one_open_per_key"
NOTE_LIMIT = 500
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f؜​-‏‪-‮⁦-⁩﻿]")  # controls, bidi, zero-width


class NoteRefused(Refused):
    """A refused note; a `Refused`, so every service surfaces one refusal type."""


def clean_note(note: str) -> str:
    """016 3.8: length-capped, control and bidirectional-override characters removed, and a confirmation
    link refused (D-24)."""
    note = _CONTROL.sub("", note or "").strip()
    if CONFIRM_PATH in note:
        raise NoteRefused("note_contains_confirmation_link")
    return note[:NOTE_LIMIT]


def event(application, kind, data, actor_type=ApplicationEvent.ActorType.SYSTEM, actor_ref=""):
    if application is not None:
        ApplicationEvent.objects.create(application=application, kind=kind, actor_type=actor_type,
                                        actor_ref=actor_ref, data=data)


def hard_bounce_open(application) -> bool:
    """9kg.3: an unresolved hard bounce blocks every send to the applicant (P2 mail, staff messages, resends and
    Documenso distribution) until a decision-maker resolves it."""
    return StaffItem.objects.filter(application=application, reason_code="hard_bounce", status=StaffItem.Status.OPEN).exists()


def open_item(reason_code: str, dedupe_key: str, *, application=None, approved_message=None, pending_action_id=None,
              question_id=None, audit: bool = True) -> StaffItem:
    existing = StaffItem.objects.filter(reason_code=reason_code, dedupe_key=dedupe_key, status=StaffItem.Status.OPEN).first()
    if existing is not None:
        return existing
    try:
        with transaction.atomic():
            item = StaffItem.objects.create(
                reason_code=reason_code, dedupe_key=dedupe_key, application=application, approved_message=approved_message,
                pending_action_id=pending_action_id, question_id=question_id,
            )
    except IntegrityError as exc:
        diag = getattr(exc.__cause__, "diag", None)
        if getattr(diag, "constraint_name", None) != OPEN_KEY:
            raise
        return StaffItem.objects.get(reason_code=reason_code, dedupe_key=dedupe_key, status=StaffItem.Status.OPEN)
    if audit:
        event(application, "staff_item_opened", {"item": str(item.public_id), "reason": reason_code})
    return item


def open_attention(application, reason: str, attention_event) -> StaffItem:
    """CATALYST_ATTENTION_OPENER (016 3.8): one open item per S1 `needs_staff_attention` event. The event is
    the audit record, so no second event is written and S1 histories are unchanged."""
    return open_item(reason, f"event:{attention_event.pk}", application=application, audit=False)


def resolve_item(item: StaffItem, *, code: str, actor_ref: str, note: str = "", effects: dict | None = None,
                 actor_type=ApplicationEvent.ActorType.STAFF) -> bool:
    """Compare-and-set the item from open to resolved and record the resolution. Returns False (no change)
    if the item was already resolved."""
    note = clean_note(note)
    if StaffItem.objects.filter(pk=item.pk, status=StaffItem.Status.OPEN).update(status=StaffItem.Status.RESOLVED) != 1:
        return False
    StaffItemResolution.objects.create(item=item, resolution_code=code, resolved_by=actor_ref, note=note,
                                       effects=effects or {})
    event(item.application, "staff_item_resolved", {"item": str(item.public_id), "reason": item.reason_code,
                                                    "resolution": code},
          actor_type=actor_type, actor_ref=actor_ref)
    return True
