"""The details read-back (bgl.8; 034 row 32; 021 section 8 amended by D-46).

The first generation's User Agreement asks the applicant to type their legal name, residence, a structured mailing
address and a phone number next to their signature; when the envelope completes, the service reads those typed values
back and records them, and the case goes on. Here the same happens at the moment a completed envelope is verified
(agreements.completion.apply_read): the typed fields come from one fresh provider read (`provider.read_fields`), the
layout of the template version says which field is which, and the values become a new `AgreementDetailsVersion` with
source `envelope`, confirmed by the applicant's own signature. A staff correction (D-46: record, then confirm, as two
audited acts) is a later version with source `staff`, which then supersedes it; the envelope version is never edited
(agreements migration 0008, the frozen trigger).

Layouts are configuration (`CATALYST_AGREEMENT_FIELD_LAYOUTS`), keyed by agreement type and template version, so a
template change is a new layout and an envelope created from an older version keeps its own. A field is matched by
recipient (the applicant), kind, page and position within a tolerance, as the first generation did: Documenso lets a
prefill replace a label, so labels are never used. The canonical field names, `ua_v24`-compatible by meaning: legal_name,
residence, address_line1, address_line2 (optional), locality, region (optional), postal_code, country, phone.

A layout whose required fields are not all found records nothing: it opens `agreement_details_readback_incomplete` for
staff (identifiers and field names only, never a value) and the sequence continues, because the signed agreement is
the record and the details are read from it, not a condition of it. Address-quality codes (agreements.address_quality)
are computed on the read values and shown on the staff screen; a problem opens `agreement_address_quality`, which never
blocks anything (the first generation's rule).
"""

import hashlib
import json

from django.conf import settings
from django.db.models.functions import Now

from correspondence.staff_items import event, open_item

from . import address_quality
from .models import AgreementDetailsVersion

READBACK_INCOMPLETE = "agreement_details_readback_incomplete"
ADDRESS_QUALITY = "agreement_address_quality"
KINDS = ("TEXT", "DROPDOWN")
DEFAULT_TOLERANCE = 2.0  # percent of the page, either axis
MAX_VALUE = 200  # as a staff-recorded value (services.record_required_details)
CANONICAL = ("legal_name", "residence", "address_line1", "address_line2", "locality", "region", "postal_code", "country",
             "phone")


def layout_key(template_version) -> str:
    return f"{template_version.agreement_type.key}:{template_version.version}"


def layout_for(template_version) -> dict | None:
    return (settings.CATALYST_AGREEMENT_FIELD_LAYOUTS or {}).get(layout_key(template_version))


def layout_problems(layouts) -> list[str]:
    """config.guards: every layout is well formed, so a mistyped layout refuses start-up instead of reading nothing."""
    problems = []
    if not isinstance(layouts, dict):
        return ["CATALYST_AGREEMENT_FIELD_LAYOUTS must be a mapping"]
    for key, layout in layouts.items():
        where = f"CATALYST_AGREEMENT_FIELD_LAYOUTS[{key!r}]"
        if not isinstance(key, str) or key.count(":") != 1 or not key.split(":")[1].isdigit():
            problems.append(f"{where}: the key is '<type key>:<template version>'")
        if not isinstance(layout, dict) or not isinstance(layout.get("name"), str) or not layout["name"]:
            problems.append(f"{where}: a layout has a name")
            continue
        tolerance = layout.get("tolerance", DEFAULT_TOLERANCE)
        if isinstance(tolerance, bool) or not isinstance(tolerance, (int, float)) or not 0 < tolerance <= 10:
            problems.append(f"{where}: tolerance is a page percentage between 0 and 10")
        fields = layout.get("fields")
        if not isinstance(fields, dict) or not fields:
            problems.append(f"{where}: fields is a non-empty mapping")
            continue
        for name, spec in fields.items():
            if not isinstance(name, str) or not name.isidentifier():
                problems.append(f"{where}: field names are identifiers")
                continue
            if (not isinstance(spec, dict) or spec.get("kind") not in KINDS
                    or not isinstance(spec.get("page"), int) or isinstance(spec.get("page"), bool) or spec["page"] < 1
                    or any(isinstance(spec.get(axis), bool) or not isinstance(spec.get(axis), (int, float))
                           or not 0 <= spec[axis] <= 100 for axis in ("x", "y"))
                    or not isinstance(spec.get("optional", False), bool)):
                problems.append(f"{where}.{name}: a field has kind TEXT or DROPDOWN, page >= 1, x and y as page percentages")
    return problems


def _clean(text: str) -> str:
    return " ".join(text.split())[:MAX_VALUE]


def extract(layout: dict, fields, recipient_id) -> tuple[dict, list[str]]:
    """(values, missing): each layout field matched to the nearest inserted field of the applicant with the same kind, on
    the same page, within the tolerance. A required field with no match or an empty text is `missing`; an optional one
    reads as ""."""
    tolerance = float(layout.get("tolerance", DEFAULT_TOLERANCE))
    values, missing = {}, []
    for name, spec in layout["fields"].items():
        candidates = [f for f in fields
                      if f.recipient_id == recipient_id and f.kind == spec["kind"] and f.page == spec["page"]
                      and abs(f.x - spec["x"]) <= tolerance and abs(f.y - spec["y"]) <= tolerance]
        text = ""
        if candidates:
            nearest = min(candidates, key=lambda f: (f.x - spec["x"]) ** 2 + (f.y - spec["y"]) ** 2)
            text = _clean(nearest.text)
        if not text and not spec.get("optional", False):
            missing.append(name)
        values[name] = text
    return values, missing


def _digest(values: dict) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def captured(instance) -> AgreementDetailsVersion | None:
    return AgreementDetailsVersion.objects.filter(instance=instance, source=AgreementDetailsVersion.Source.ENVELOPE).first()


def capture(instance, env, fields, claim_id=None, actor: str = "") -> AgreementDetailsVersion | None:
    """Inside the fenced result transaction that verifies `instance`, with the application locked. Records the typed
    details as a confirmed envelope version (once per instance), or opens the incomplete item. Returns the version."""
    layout = layout_for(instance.template_version)
    if layout is None:
        return None
    existing = captured(instance)
    if existing is not None:
        return existing  # a repeated verifying read never records a second envelope version
    application = instance.application
    applicant = instance.recipients.filter(who="applicant").first()
    recipient_id = next((r.id for r in env.recipients
                         if applicant is not None and r.role == "SIGNER" and r.email.casefold() == applicant.email.casefold()), None)
    values, missing = extract(layout, fields, recipient_id) if recipient_id is not None else ({}, list(layout["fields"]))
    ref = str(instance.public_id)
    if missing:
        open_item(READBACK_INCOMPLETE, f"readback:{ref}", application=application, pending_action_id=claim_id)
        event(application, "agreement_details_readback_incomplete",
              {"instance": ref, "layout": layout["name"], "missing": sorted(missing),
               "recipient_identified": recipient_id is not None}, actor_ref=actor)
        return None
    agreement_type = instance.agreement_type
    number = AgreementDetailsVersion.objects.filter(application=application, agreement_type=agreement_type).count() + 1
    row = AgreementDetailsVersion.objects.create(  # a draft first (migration 0008), then confirmed by the signature
        application=application, agreement_type=agreement_type, version=number, values=values, values_sha256=_digest(values),
        recorded_by=f"envelope:{ref}", source=AgreementDetailsVersion.Source.ENVELOPE, instance=instance)
    AgreementDetailsVersion.objects.filter(pk=row.pk).update(status=AgreementDetailsVersion.Status.CONFIRMED,
                                                             confirmed_by=f"signature:{ref}", confirmed_at=Now())
    codes = address_quality.flags(values)
    event(application, "agreement_details_captured",
          {"instance": ref, "type": agreement_type.key, "version": number, "layout": layout["name"], "flags": list(codes)},
          actor_ref=actor)
    if address_quality.problems(values):
        open_item(ADDRESS_QUALITY, f"address:{ref}", application=application, pending_action_id=claim_id)
    row.refresh_from_db()
    return row
