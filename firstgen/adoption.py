"""Attach existing first-generation members to v2 as active member cases (dy7.5; owner decision 211.7.6, 2026-11-21).

The people this is for completed a User Agreement on the first generation's pilot or legacy signing path, outside any
first-generation case. The import (firstgen.importer) kept their completed envelopes only as `ua_details_capture`
records that belong to no case, with the personal columns dropped, so v2 does not know them by address: no
application, no invitation, no member-on-file record. The owner attaches them with the owner-run
`catalyst_member_adopt`, from a private file on the host (one entry per person, `parse`).

**The proof gate.** An entry is refused unless its User Agreement envelope id is in the import snapshot as a
`ua_details_capture` record of no case (the first generation wrote one row per COMPLETED User Agreement envelope;
its migration 0021). An envelope the snapshot holds for a case belongs to that case (`envelope_attached_to_a_case`);
one v2 already issued or adopted (`AgreementInstance`), or one an earlier adoption used, is refused too. The provider
is not read: the v2 credential is not the one the pilot envelopes were made with, and ownership is never inferred
from a provider's answer (agreements.provider.legacy_binding). The owner's verification off-system remains the
completion attestation, as for `catalyst_member_on_file`.

**One person, once.** An address v2 already knows by an application is refused (`address_known_to_v2`): no duplicate
case. A re-run of the same entry for a person this adopted reports `unchanged` and writes nothing; a different entry
for them is refused (`adopted_with_different_input`): corrections of the agreement labels go through
`catalyst_member_on_file --correct`.

**What it creates for a person** (in one transaction): the application at stage `active`, with no contact
verification (v2 holds no proof of it, so no v2 path can mail them until staff verify the address); the member-on-file
record through `applications.members.record`, so nobody is asked to sign again; a system automation pause, so
nothing automatic happens to them (resuming it needs decision-maker review and a reason,
correspondence.staff_actions.resume); for an existing company mailbox, the importer's precedent for a mailbox the
first generation created: a live reservation and an `active` checklist provisioning request, so v2 never reserves or
creates that name again (P5-D-5, P5-D-10: the mailbox itself is never read, created, adopted or changed); and one
`adopted_existing_member` event, inserted without the save signal so not even a Twenty projection is queued. Nothing
is sent, no pending action is queued and the import records stay as they are (append-only).

Refusals are codes, never values. Every row written here is in the erasure map (erasure.catalog): the application and
its event, pause and reservation by the application, the member-on-file record by the email key.
"""

import hashlib
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.utils import timezone

from agreements import provider
from agreements.models import AgreementInstance
from applications import members
from applications.forms import EMAIL_MAX
from applications.identity import email_key
from applications.models import Application, ApplicationEvent, Stage
from provisioning.models import AddressReservation, ProvisioningRequest
from workflow.models import AutomationPause

from .importer import LOCAL_PART
from .models import ImportedRecord

ACTOR = "system:adopt:existing-member"  # a system pause: resuming it needs the decision-maker review and a reason
EVENT = "adopted_existing_member"
PAUSE_REASON = (
    "Existing first-generation member attached by the owner (dy7.5): automation stays off; v2 sends nothing and"
    " changes no mailbox or agreement for them until staff have reviewed the case"
)
REQUIRED = (
    "email",
    "display_name",
    "user_agreement_envelope_id",
    "user_agreement_version",
)
OPTIONAL = ("nda_envelope_id", "nda_version", "mailbox_local_part")
NAME_MAX = Application._meta.get_field("display_name").max_length
# Where a first-generation record names an envelope: an unattached `ua_details_capture` row is the proof; any of
# these in a record of a case means the envelope is that case's.
ENVELOPE_KEYS = ("envelope_id", "provider_ref", "ua_envelope_id", "legacy_envelope_id")


class Refused(Exception):
    """One entry is refused; the message is a code (never a value)."""


@dataclass(frozen=True)
class Entry:
    email: str
    key: str
    display_name: str
    ua_envelope: str
    ua_version: str
    nda_envelope: str
    nda_version: str
    local_part: str

    def covers(self) -> dict:
        return {"nda": self.nda_version or None, "user_agreement": self.ua_version}

    def digest(self, domain: str) -> str:
        """What a re-run compares: everything the entry says except the address as typed (the key stands for it)."""
        values = {k: v for k, v in asdict(self).items() if k != "email"} | {
            "domain": domain if self.local_part else ""
        }
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def _text(raw: dict, name: str) -> str:
    value = raw.get(name)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise Refused(f"{name}_not_text")
    return " ".join(value.split())


def _label(value: str, prefix: str) -> str:
    try:
        return members.check_label(value)
    except members.Refused as why:
        raise Refused(f"{prefix}_{why}") from None


def parse(raw) -> Entry:
    """One entry of the input file, checked without the database. Raises Refused."""
    if not isinstance(raw, dict):
        raise Refused("entry_not_an_object")
    if set(raw) - set(REQUIRED) - set(OPTIONAL):
        raise Refused("unknown_field")
    for name in REQUIRED:
        if not _text(raw, name):
            raise Refused(f"missing_{name}")
    email = _text(raw, "email")
    try:
        key = email_key(email)
    except ValueError:
        raise Refused("not_an_email_address") from None
    if len(key) > EMAIL_MAX:
        raise Refused("address_too_long")
    name = _text(raw, "display_name")
    if len(name) > NAME_MAX:
        raise Refused("display_name_too_long")
    ua_envelope = _text(raw, "user_agreement_envelope_id")
    if not provider.ENVELOPE_ID.fullmatch(ua_envelope):
        raise Refused("user_agreement_envelope_id_malformed")
    nda_envelope, nda_version = _text(raw, "nda_envelope_id"), _text(raw, "nda_version")
    if nda_envelope and not provider.ENVELOPE_ID.fullmatch(nda_envelope):
        raise Refused("nda_envelope_id_malformed")
    if nda_envelope and not nda_version:
        raise Refused("missing_nda_version")
    if nda_envelope and nda_envelope == ua_envelope:
        raise Refused("nda_envelope_is_the_user_agreement")
    local_part = _text(raw, "mailbox_local_part").lower()
    if local_part and (not re.match(LOCAL_PART, local_part) or ".." in local_part):
        raise Refused("mailbox_name_not_reservable")
    return Entry(
        email=email,
        key=key,
        display_name=name,
        ua_envelope=ua_envelope,
        ua_version=_label(
            _text(raw, "user_agreement_version"), "user_agreement_version"
        ),
        nda_envelope=nda_envelope,
        nda_version=_label(nda_version, "nda_version") if nda_version else "",
        local_part=local_part,
    )


def _records(envelope: str):
    query = Q(v1_table="ua_details_capture", v1_id=envelope)
    for name in ENVELOPE_KEYS:
        query |= Q(**{f"data__{name}": envelope})
    return ImportedRecord.objects.filter(query)


def proof(envelope: str) -> ImportedRecord:
    """The import record that proves a completed User Agreement envelope outside any case. Raises Refused."""
    records = list(_records(envelope).order_by("pk"))
    if any(r.application_id is not None for r in records):
        raise Refused("envelope_attached_to_a_case")
    found = next(
        (
            r
            for r in records
            if r.v1_table == "ua_details_capture"
            and r.data.get("envelope_id") == envelope
        ),
        None,
    )
    if found is None:
        raise Refused("envelope_not_in_first_generation_snapshot")
    if AgreementInstance.objects.filter(envelope_id=envelope).exists():
        raise Refused("envelope_owned_by_a_v2_case")
    if ApplicationEvent.objects.filter(kind=EVENT, data__ua_record=found.pk).exists():
        raise Refused("envelope_already_adopted")
    return found


def nda_record(envelope: str):
    """The import record of the NDA envelope, if the snapshot has one outside any case (None when it has none)."""
    if not envelope:
        return None
    records = list(_records(envelope).order_by("pk"))
    if any(r.application_id is not None for r in records):
        raise Refused("nda_envelope_attached_to_a_case")
    if AgreementInstance.objects.filter(envelope_id=envelope).exists():
        raise Refused("nda_envelope_owned_by_a_v2_case")
    if ApplicationEvent.objects.filter(
        kind=EVENT, data__nda_envelope_id=envelope
    ).exists():
        raise Refused("nda_envelope_already_adopted")
    return records[0] if records else None


def adopt(
    entry: Entry, recorder: str, domain: str, created: Counter
) -> tuple[str, Application]:
    """Attach one person, inside the caller's transaction. Returns ("adopted" | "unchanged", application)."""
    digest = entry.digest(domain)
    known = (
        Application.objects.select_for_update()
        .filter(email_key=entry.key)
        .order_by("pk")
    )
    if known.exists():
        event = (
            ApplicationEvent.objects.filter(application__in=known, kind=EVENT)
            .select_related("application")
            .order_by("pk")
            .first()
        )
        if event is None:
            raise Refused("address_known_to_v2")
        if event.data.get("input_sha256") != digest:
            raise Refused("adopted_with_different_input")
        return "unchanged", event.application
    if entry.local_part and not domain:
        raise Refused("mailbox_domain_not_configured")
    ua = proof(entry.ua_envelope)
    nda = nda_record(entry.nda_envelope)
    if (
        entry.local_part
        and AddressReservation.objects.filter(
            local_part__iexact=entry.local_part,
            domain__iexact=domain,
            released_at__isnull=True,
        ).exists()
    ):
        raise Refused("mailbox_already_reserved")
    app = Application.objects.create(
        email=entry.email,
        email_key=entry.key,
        display_name=entry.display_name,
        stage=Stage.ACTIVE,
    )
    created["applications.Application"] += 1
    try:
        row, outcome = members.record(entry.email, entry.covers(), recorder)
    except members.Refused as why:
        raise Refused(f"member_on_file_{why}") from None
    if outcome == "recorded":
        created["applications.MemberAgreementOnFile"] += 1
    AutomationPause.objects.create(
        subject_type="application",
        subject_id=app.public_ref,
        reason=PAUSE_REASON,
        actor_ref=ACTOR,
    )
    created["workflow.AutomationPause"] += 1
    reservation = None
    if entry.local_part:
        reservation = AddressReservation.objects.create(
            application=app,
            local_part=entry.local_part,
            domain=domain,
            basis="reviewed_exception",
            reviewed_by=ACTOR,
        )
        facts = {"source": "existing_member", "ua_record": ua.pk}
        ProvisioningRequest.objects.create(
            application=app,
            reservation=reservation,
            method="checklist",
            quota_mb=settings.CATALYST_PROVISIONING_QUOTA_MB,
            send_limit=settings.CATALYST_PROVISIONING_SEND_LIMIT,
            prerequisite_digest=_digest(facts),
            approval_digest=_digest({**facts, "approval": True}),
            status="active",
            approved_by=f"owner:{recorder}",
            approved_at=timezone.now(),
        )
        created["provisioning.AddressReservation"] += 1
        created["provisioning.ProvisioningRequest"] += 1
    # bulk_create sends no post_save: crm.projection queues a Twenty projection on every saved event, and an
    # adoption queues nothing at all.
    ApplicationEvent.objects.bulk_create(
        [
            ApplicationEvent(
                application=app,
                kind=EVENT,
                actor_type="system",
                actor_ref=ACTOR,
                data={
                    "recorded_by": recorder,
                    "ua_record": ua.pk,
                    "ua_envelope_id": entry.ua_envelope,
                    "ua_version": entry.ua_version,
                    "nda_envelope_id": entry.nda_envelope,
                    "nda_record": nda.pk if nda is not None else None,
                    "nda_version": entry.nda_version,
                    "member_on_file": str(row.public_id),
                    "reservation": str(reservation.public_id)
                    if reservation is not None
                    else "",
                    "contact_verified": False,
                    "input_sha256": digest,
                },
            )
        ]
    )
    created["applications.ApplicationEvent"] += 1
    with connection.cursor() as cursor:
        cursor.execute(
            "SET CONSTRAINTS ALL IMMEDIATE"
        )  # every deferred guard, before the entry commits
    return "adopted", app


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()


def _error_code(exc) -> str:
    diag = getattr(getattr(exc, "__cause__", None), "diag", None)
    name = getattr(diag, "constraint_name", None) if diag else None
    return f"write_refused:{name}" if name else "write_refused"


def run(entries: list, recorder: str, domain: str) -> dict:
    """Every entry in its own transaction (a savepoint when the caller holds one, as the dry run does). The report
    names entries by their index in the file and applications by public reference only."""
    created, results = Counter(), []
    for index, raw in enumerate(entries):
        mine = Counter()
        try:
            entry = parse(raw)
            with transaction.atomic():
                outcome, app = adopt(entry, recorder, domain, mine)
        except Refused as why:
            results.append({"index": index, "outcome": "refused", "code": str(why)})
            continue
        except IntegrityError as exc:  # a concurrent run or a constraint this did not foresee: the entry wrote nothing
            results.append(
                {"index": index, "outcome": "refused", "code": _error_code(exc)}
            )
            continue
        created.update(mine)
        results.append(
            {
                "index": index,
                "outcome": outcome,
                "public_ref": str(app.public_ref),
                "reference": app.reference,
            }
        )
    counts = Counter(r["outcome"] for r in results)
    return {
        "entries": results,
        "counts": {name: counts[name] for name in ("adopted", "unchanged", "refused")},
        "refusals": dict(
            sorted(
                Counter(r["code"] for r in results if r["outcome"] == "refused").items()
            )
        ),
        "created": dict(sorted(created.items())),
        "queued": 0,
        "sent": 0,
    }
