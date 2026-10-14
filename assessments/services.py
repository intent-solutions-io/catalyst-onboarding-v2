"""Staff services for evidence (018 sections 3.1, 4 steps 2 and 3, 7; task 3B.1).

Every service checks a named `assessments.*` permission with the P2 rule (`can`): an active, authenticated,
non-superuser account (D-23). Each runs in one transaction, application first, and writes an event.

- `approve_evidence_source`: the owner approves exactly the source version shown (its definition digest); the
  previously approved version of the same key is retired in the same transaction.
- `refetch_item`: a new slot (round n+1) for the same claim, source and URL, and a new fetch; the old slot stays.
- `proceed_without`: continue to assessment although a required item is unavailable.
"""

import json

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.db.models.functions import Now

from applications.models import Application, ApplicationEvent, Stage
from applications.stages import StageConflict, transition
from correspondence.models import StaffItem
from correspondence.staff_items import clean_note, resolve_item

from . import collection, fetch
from .models import EvidenceItem, EvidenceSource


class Refused(Exception):
    """A service refused; the message is a reason code."""


def can(user, permission: str) -> bool:
    return (user is not None and user.is_authenticated and user.is_active and not user.is_superuser
            and user.has_perm(f"assessments.{permission}"))


def require(user, permission: str) -> None:
    if not can(user, permission):
        raise PermissionDenied(permission)


def actor_ref(user) -> str:
    return f"user:{user.pk}"


DEFINITION_FIELDS = ("key", "version", "kind", "host", "port", "path_prefix", "redirect_hosts", "content_types",
                     "max_bytes", "deadline_seconds", "required", "on_unavailable", "fixture_only")


def definition_digest(values: dict) -> str:
    return fetch.sha256(json.dumps({k: values[k] for k in DEFINITION_FIELDS}, sort_keys=True, separators=(",", ":")))


def define_evidence_source(**values) -> EvidenceSource:
    """A new draft version (owner-run command; nothing is approved here)."""
    values["host"] = values["host"].rstrip(".").encode("idna").decode("ascii").lower()
    values["redirect_hosts"] = sorted(h.lower() for h in values.get("redirect_hosts") or [])
    values["content_types"] = sorted(values.get("content_types") or ["text/html", "text/plain"])
    if values["kind"] not in ("work_sample_page", "credential_verification"):
        raise Refused("unknown_kind")
    if fetch._is_ip_literal(values["host"]):
        raise Refused("host_not_a_name")
    if not str(values.get("path_prefix", "/")).startswith("/"):
        raise Refused("path_prefix_invalid")
    with transaction.atomic():
        latest = EvidenceSource.objects.select_for_update().filter(key=values["key"]).aggregate(v=Max("version"))["v"]
        values["version"] = (latest or 0) + 1
        values.setdefault("port", 443)
        values.setdefault("path_prefix", "/")
        values.setdefault("required", False)
        values.setdefault("on_unavailable", "staff")
        values.setdefault("fixture_only", False)
        return EvidenceSource.objects.create(definition_sha256=definition_digest(values), **values)


def approve_evidence_source(source_id: int, user, expected_digest: str) -> EvidenceSource:
    require(user, "approve_evidence_source")
    with transaction.atomic():
        source = EvidenceSource.objects.select_for_update().get(pk=source_id)
        if source.definition_sha256 != expected_digest:
            raise Refused("source_changed_since_shown")
        if source.status == EvidenceSource.Status.APPROVED:
            return source
        if source.status != EvidenceSource.Status.DRAFT:
            raise Refused("source_not_draft")
        EvidenceSource.objects.filter(key=source.key, status=EvidenceSource.Status.APPROVED).update(
            status=EvidenceSource.Status.RETIRED)
        EvidenceSource.objects.filter(pk=source.pk).update(status=EvidenceSource.Status.APPROVED,
                                                          approved_by=actor_ref(user), approved_at=Now())
    source.refresh_from_db()
    return source


def _lock(application_id) -> Application:
    return Application.objects.select_for_update(of=("self",)).get(pk=application_id)


def _evidence_items(application):
    return StaffItem.objects.select_for_update(of=("self",)).filter(
        status=StaffItem.Status.OPEN, reason_code="evidence_required_unavailable", application=application)


def refetch_item(item_id: int, user, note: str = "") -> EvidenceItem:
    require(user, "operate_evidence")
    note = clean_note(note)
    item = EvidenceItem.objects.get(pk=item_id)
    with transaction.atomic():
        application = _lock(item.application_id)
        item = EvidenceItem.objects.select_for_update(of=("self",)).select_related("source").get(pk=item_id)
        if application.stage != Stage.EVIDENCE:
            raise Refused("stage_not_evidence")
        nothing_found = item.status == EvidenceItem.Status.FETCHED and not item.captures.exclude(outcome="not_found").exists()
        if item.status not in (EvidenceItem.Status.UNAVAILABLE, EvidenceItem.Status.REFUSED) and not nothing_found:
            raise Refused("item_not_refetchable")
        source = collection.approved_source(item.source.kind if item.source else
                                            collection.CLAIM_KINDS[item.claim_ref.split(":")[0]], item.request_url)
        latest = EvidenceItem.objects.filter(application=application, adopted_version=item.adopted_version,
                                             claim_ref=item.claim_ref).aggregate(r=Max("round"))["r"]
        if latest != item.round:
            raise Refused("a_newer_round_exists")
        new = EvidenceItem.objects.create(
            application=application, adopted_version=item.adopted_version, source=source, claim_ref=item.claim_ref,
            request_url=item.request_url, request_url_sha256=item.request_url_sha256, round=item.round + 1,
            required=item.required or bool(source and source.required))  # a required claim never becomes optional
        if source is None:
            collection.finish_item(new, EvidenceItem.Status.REFUSED, "no_approved_source")
        else:
            collection.enqueue_fetch(application, new)
        for staff_item in _evidence_items(application):
            resolve_item(staff_item, code="refetch", actor_ref=actor_ref(user), note=note,
                         effects={"item": str(new.public_id)})
        ApplicationEvent.objects.create(application=application, kind="evidence_refetch_requested",
                                        actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor_ref(user),
                                        data={"item": str(new.public_id), "replaces": str(item.public_id)})
        if source is None:
            collection.complete_if_done(application, item.adopted_version)
    new.refresh_from_db()
    return new


def proceed_without(application_id: int, user, note: str = "") -> Application:
    require(user, "operate_evidence")
    note = clean_note(note)
    with transaction.atomic():
        application = _lock(application_id)
        adoption = application.adoptions.select_related("submission_version").first()
        if adoption is None:
            raise Refused("no_adopted_version")
        if EvidenceItem.objects.filter(application=application, adopted_version=adoption.submission_version,
                                       status=EvidenceItem.Status.PENDING).exists():
            raise Refused("items_still_pending")
        try:
            transition(application.pk, (Stage.EVIDENCE,), Stage.ASSESSING, event_kind="evidence_collection_complete",
                       data={"version": str(adoption.submission_version.public_id), "proceeded_without": True},
                       actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor_ref(user))
        except StageConflict:
            raise Refused("stage_not_evidence") from None
        for staff_item in _evidence_items(application):
            resolve_item(staff_item, code="proceed_without", actor_ref=actor_ref(user), note=note, effects={})
        from .runs import enqueue_assessment

        enqueue_assessment(Application.objects.get(pk=application.pk), "evidence_complete")
    application.refresh_from_db()
    return application


def rerun_assessment(application_id: int, user, note: str = ""):
    """A staff request for a new run (018 4 step 4): a new snapshot only; the same snapshot never runs twice."""
    require(user, "rerun_assessment")
    note = clean_note(note)
    from .runs import enqueue_assessment

    with transaction.atomic():
        application = _lock(application_id)
        if application.stage != Stage.ASSESSING:
            raise Refused("stage_not_assessing")
        run = enqueue_assessment(application, "staff_rerun")
        if run is None:
            raise Refused("nothing_to_rerun")
        ApplicationEvent.objects.create(application=application, kind="assessment_rerun_requested",
                                        actor_type=ApplicationEvent.ActorType.STAFF, actor_ref=actor_ref(user),
                                        data={"run": str(run.public_id)})
    return run
