"""The Twenty projection and the daily User Agreement details fill (bgl.14; 034 rows 42 and 43; owner answer of
2026-10-31, which reverses D-08 once the switch is on). Behind `CATALYST_TWENTY_PROJECTION`, off by default and refused
outside `test` and `staging` until the swap's own code change (config.guards.twenty_problems).

**When it runs.** Every `ApplicationEvent` (a stage change, a decision, an agreement or provisioning step, a staff item)
queues one `twenty_project` action in the event's own transaction, as the first generation queued one per case event,
unless one is already queued for the application (they coalesce: the action reads the current records, not the
event, so a late run never regresses Twenty, and a run with nothing to change writes nothing). A Twenty outage only
delays these actions; nothing in the application's journey waits on them. They run whether or not the application's
automation is paused (they send nothing to the applicant), never under the restore hold.

**Who the person is** (the first generation's order): the stored link; for an imported application, the person and
note the first generation recorded (`imported`); a person already carrying this application's case id in `cpnCaseId`
(a create whose reply was lost); exactly one person whose primary or additional email equals the application's after
trimming and case-folding (`crm.twenty.find_people_by_email`, never fuzzy). None creates a person; several, or a match
already linked to another open application, opens one staff item and writes nothing.

**What it writes.** The owned fields of `crm.mapping` (a person's edit since the last write opens one staff item per
distinct edit, then is overwritten, as the first generation recorded `field_overwritten`), the create-only values, the
User Agreement details where Twenty is blank, and one note `Applicant file — <name>` per person, updated in place: the
note's id is stored, a note whose create reply was lost is found by its title and marker line, and notes people wrote
are never touched.

**Idempotent under retry.** Every write is preceded, in the same function, by the read that would find it done (the
effect registry's `checked_before`, workflow.effects): a repeated run finds the person by link or case id, the note by
id or marker, the attachment by its targets, and writes only what differs. Two runs for one application never overlap:
each holds a session advisory lock for the application while it talks to Twenty (no row lock is held across a call).

**Failures.** Twenty unreachable, timing out or answering 5xx or 429: the action is retried with the worker's bounded
backoff (`CATALYST_TWENTY_ATTEMPTS`); the last failure opens one staff item. A 4xx refusal opens one staff item and is
not retried. The cases the first generation sent to `crm_review_item` open one v2 staff item each (`REVIEW_REASONS`).

**The daily fill** (`twenty_details_fill`): for every application with a confirmed User Agreement details version, the
person's legal name, phone and mailing address are filled where Twenty is blank, never overwritten; a different value
is a conflict, counted and left alone. An application with no linked person yet gets a projection queued instead.

Logs, ledger errors and staff items carry codes, references and digests only, never a value sent to Twenty.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.apps import apps as django_apps
from django.conf import settings
from django.db import connection, transaction
from django.db.models.functions import Now
from django.db.models.signals import post_save
from django.utils import timezone

from applications.models import TERMINAL_STAGES, Application, ApplicationEvent
from workflow import ledger
from workflow.models import PendingAction

from . import mapping, twenty
from .models import TwentyLink

logger = logging.getLogger(__name__)
Status = PendingAction.Status
PROJECT = "twenty_project"
FILL = "twenty_details_fill"
FILL_SUBJECT = ("twenty_details_fill", uuid.UUID("7b3c1e0a-4f52-4d8e-9a11-0c2d5e6f7a81"))
LOCK_NAMESPACE = b"catalyst-twenty-projection\n"
LOCK_RETRY = timedelta(seconds=5)
# The first generation's `crm_review_item` kinds, each now one v2 staff item (their plain words: applications.staff
# REASONS; acknowledged on the staff screen: correspondence.processing.ACKNOWLEDGE_ONLY).
REVIEW_REASONS = ("twenty_ambiguous_match", "twenty_person_linked_elsewhere", "twenty_linked_person_missing",
                  "twenty_field_overwritten", "twenty_request_rejected", "twenty_projection_failed")
SIGNED = ("signing_complete_observed", "signing_complete_verified")


def enabled() -> bool:
    return bool(settings.CATALYST_TWENTY_PROJECTION)


# --- queueing ---------------------------------------------------------------------------------------------------------

def enqueue(application, trigger: str) -> bool:
    """Queue one projection for the application unless one is already queued. Safe inside any transaction: a
    duplicate key is ignored, never raised. True when one was queued."""
    if not enabled():
        return False
    if PendingAction.objects.filter(kind=PROJECT, subject_type="application", subject_id=application.public_ref,
                                    status=Status.QUEUED).exists():
        return False
    created = PendingAction.objects.bulk_create([PendingAction(
        kind=PROJECT, subject_type="application", subject_id=application.public_ref, input_ref="",
        idempotency_key=f"{PROJECT}:{application.public_ref}:{trigger}"[:200],
        max_attempts=settings.CATALYST_TWENTY_ATTEMPTS)], ignore_conflicts=True)
    return bool(created and created[0].pk)


def _on_event(sender, instance, created, raw=False, **kwargs):
    if created and not raw and enabled():
        enqueue(instance.application, f"e{instance.pk}")


def connect() -> None:
    post_save.connect(_on_event, sender=ApplicationEvent, dispatch_uid="catalyst.crm.project_on_event")


def schedule_details_fill(n: int | None = None, delay: float = 0.0) -> bool:
    """Queue the next daily fill unless one is queued or running (or the switch is off). Idempotent."""
    if not enabled():
        return False
    active = PendingAction.objects.filter(kind=FILL, status__in=(Status.QUEUED, Status.RUNNING))
    if n is None and active.exists():
        return False
    n = n if n is not None else PendingAction.objects.filter(kind=FILL).count() + 1
    created = PendingAction.objects.bulk_create([PendingAction(
        kind=FILL, subject_type=FILL_SUBJECT[0], subject_id=FILL_SUBJECT[1], input_ref="",
        idempotency_key=f"{FILL}:{n}", due_at=Now() + timedelta(seconds=delay))], ignore_conflicts=True)
    return bool(created and created[0].pk)


# --- what the records say --------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Imported:
    """What the first-generation import recorded for an application (firstgen.models.ImportedCase)."""

    case_id: str
    reference: str
    person_id: str
    note_id: str
    requested_at: object


def imported(application) -> Imported | None:
    """The first generation's record of this application, when the import app is installed and imported it: the
    projection then keeps the first generation's case id and reference and continues its Twenty person and note."""
    if not django_apps.is_installed("firstgen"):
        return None
    model = django_apps.get_model("firstgen", "ImportedCase")
    row = model.objects.filter(application=application).first()
    if row is None:
        return None
    return Imported(row.v1_case_id, row.reference, row.crm_person_id, row.crm_note_id, row.v1_created_at)


def _versions(application) -> list:
    return list(application.versions.order_by("version_number"))


def _current_fields(application) -> tuple[dict, object]:
    """The submitted fields Catalyst acts on: the adopted version, else the latest."""
    from applications.models import VersionAdoption

    adopted = VersionAdoption.objects.filter(application=application).order_by("-adopted_at", "-id").first()
    version = adopted.submission_version if adopted else application.versions.order_by("-version_number").first()
    return (version.submitted_fields if version else {}) or {}, version


def _consent(versions) -> mapping.Consent:
    """True from the earliest ticked request-form box, else the form's explicit no; unknown stays unknown."""
    declined = ""
    for version in versions:
        fields = version.submitted_fields or {}
        source = f"request_form:{fields.get('marketing_wording_version') or 'unknown'}"
        if fields.get("marketing_opt_in") is True:
            at = (fields.get("first_generation") or {}).get("marketing_opt_in_at")
            moment = datetime.fromisoformat(at) if isinstance(at, str) and at else version.received_at
            return mapping.Consent(True, moment, source)
        if fields.get("marketing_opt_in") is False and not declined:
            declined = source
    return mapping.Consent(False, None, declined) if declined else mapping.Consent()


def _confirmed_details(application) -> dict:
    from agreements.models import AgreementDetailsVersion

    row = (AgreementDetailsVersion.objects.filter(application=application, agreement_type__key="user_agreement",
                                                  status=AgreementDetailsVersion.Status.CONFIRMED)
           .order_by("-version").first())
    return row.values if row is not None else {}


def _agreements(application) -> list:
    from agreements.models import NOT_LIVE, AgreementInstance

    return list(AgreementInstance.objects.filter(application=application).exclude(issue_status__in=NOT_LIVE)
                .select_related("agreement_type", "template_version").order_by("agreement_type__order", "id"))


def _state(application, agreements) -> str:
    state = mapping.STAGE_STATE.get(application.stage, "REVIEWING")
    if application.stage == "agreements" and any(a.agreement_type.key == "nda" and a.signing_status in SIGNED
                                                 for a in agreements):
        return "SETUP_PENDING"
    return state


def _exception(application) -> bool:
    from correspondence.models import StaffItem

    return StaffItem.objects.filter(application=application, status=StaffItem.Status.OPEN).exists()


def facts(application) -> tuple[mapping.Facts, mapping.NoteFacts]:
    origin = imported(application)
    fields, _version = _current_fields(application)
    agreements = _agreements(application)
    details = _confirmed_details(application)
    claims = fields.get("claims") or {}
    links = tuple(str(w.get("url")) for w in claims.get("work") or [] if isinstance(w, dict) and w.get("url"))
    state = _state(application, agreements)
    exception = _exception(application)
    case_id = origin.case_id if origin else str(application.public_ref)
    requested = origin.requested_at if origin else application.created_at
    field_facts = mapping.Facts(
        case_id=case_id, state=state, reference=origin.reference if origin else "",
        interest_track=str(fields.get("interest_track") or ""), exception=exception,
        agreements=tuple((a.agreement_type.key, f"v{a.template_version.version}", a.signing_status) for a in agreements),
        work_links=links, lead_source="" if origin else "CATALYST_REQUEST_ACCESS", requested_at=requested,
        consent=_consent(_versions(application)), contact_email=application.email,
        intake_name=str(fields.get("name") or application.display_name), intake_phone=str(fields.get("phone_e164") or ""),
        details=mapping.details_values(details))
    note_facts = mapping.NoteFacts(
        case_id=case_id, full_name=application.display_name, state=state,
        next_action=mapping.next_action(state, exception), requested_at=requested,
        source="FIRST_GENERATION" if origin else "CATALYST_REQUEST_ACCESS",
        reference=origin.reference if origin else "", track=str(fields.get("interest_track") or ""),
        own_words=str(fields.get("reason") or ""), links=links, decisions=_decisions(application),
        agreements=tuple((a.agreement_type.key, a.template_version.version, a.issue_status, a.signing_status, a.created_at)
                         for a in agreements),
        residence=str(details.get("residence") or details.get("country_code") or ""), access=_access(application))
    return field_facts, note_facts


def _decisions(application) -> tuple:
    from assessments.models import QualificationDecision

    return tuple((d.outcome, d.basis, d.created_at) for d in
                 QualificationDecision.objects.filter(application=application).order_by("created_at", "id"))


def _access(application) -> tuple:
    from provisioning.models import ProvisioningRequest

    request = (ProvisioningRequest.objects.filter(application=application).select_related("reservation")
               .order_by("-id").first())
    if request is None:
        return ()
    r = request.reservation
    return (f"{r.local_part}@{r.domain}", request.status, r.created_at)


# --- the per-application lock ----------------------------------------------------------------------------------------

def _lock_key(application) -> int:
    digest = hashlib.sha256(LOCK_NAMESPACE + str(application.public_ref).encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _try_lock(application) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [_lock_key(application)])
        return bool(cursor.fetchone()[0])


def _unlock(application) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [_lock_key(application)])


# --- outcomes ---------------------------------------------------------------------------------------------------------

class NeedsStaff(Exception):
    """A person must decide; one staff item says why. Nothing more is written to Twenty."""

    def __init__(self, reason: str, observation: str):
        super().__init__(reason)
        self.reason, self.observation = reason, observation


def open_review(application, reason: str, observation: str):
    """One staff item per reason and observation while it is open (the first generation's dedupe rule)."""
    from correspondence.staff_items import open_item

    return open_item(reason, f"{reason}:{application.public_ref}:{observation}"[:200], application=application)


def _short(value: str) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()[:32]


def _save(claim, application, **fields) -> None:
    """Record progress at once (a created person, a note id), fenced, so a later failure never loses it."""
    with transaction.atomic():
        ledger.fence(claim)
        link, _ = TwentyLink.objects.get_or_create(application=application)
        TwentyLink.objects.filter(pk=link.pk).update(**fields, updated_at=Now())


# --- the projection ---------------------------------------------------------------------------------------------------

def _linked_elsewhere(application, person_id: str) -> bool:
    return TwentyLink.objects.filter(person_id=person_id).exclude(application=application).exclude(
        application__stage__in=TERMINAL_STAGES).exists()


def project_person(claim, application, link, f: mapping.Facts) -> tuple[dict, dict, list]:
    """Find or create the person and bring its fields up to date. Returns (person, new field hashes, reviews): the
    reviews are (reason, observation) pairs for staff items. Reads before every write (module docstring)."""
    reviews, person, method, created = [], None, "", False
    if link.person_id:
        person = twenty.get_person(link.person_id)
        if person is None:
            raise NeedsStaff("twenty_linked_person_missing", _short(link.person_id))
        method = link.link_method
    else:
        ours = twenty.find_people_by_field("cpnCaseId", f.case_id)
        if len(ours) > 1:
            raise NeedsStaff("twenty_ambiguous_match", _short(",".join(sorted(str(p["id"]) for p in ours))))
        if ours:
            person, method = ours[0], "recovered"
        else:
            matches = twenty.find_people_by_email(f.contact_email)
            if len(matches) > 1:
                raise NeedsStaff("twenty_ambiguous_match", _short(",".join(sorted(str(p["id"]) for p in matches))))
            if matches:
                if _linked_elsewhere(application, str(matches[0]["id"])):
                    raise NeedsStaff("twenty_person_linked_elsewhere", _short(str(matches[0]["id"])))
                person, method = matches[0], "email_match"
    desired = mapping.desired_owned(f)
    meta = {"cpnProjectedAt": mapping.iso(timezone.now()), "cpnProjectionVersion": mapping.PROJECTION_VERSION}
    if person is None:
        body = {**mapping.create_only(f), **desired, **meta}
        person = twenty.create_person(body)
        method, created = "created", True
        _save(claim, application, person_id=str(person["id"]), link_method=method, field_hashes={})
    elif not link.person_id:
        _save(claim, application, person_id=str(person["id"]), link_method=method)
    person_id = str(person["id"])
    stored = dict(link.field_hashes or {}) if link.person_id == person_id else {}
    # A person someone else wrote first (an email match, a staff link) shows what this write replaces; a person this
    # service created, recovered by its case id or inherited from the first generation (which kept no hashes v2 can
    # read) does not.
    first_link = method in ("email_match", "staff") and not stored
    patch = {}
    for name, want in desired.items():
        current = person.get(name)
        if mapping.normalize(name, current) == mapping.normalize(name, want):
            continue
        observed = mapping.value_hash(name, current)
        if name in stored and observed != stored[name]:
            reviews.append(("twenty_field_overwritten", f"{name}:{observed[:32]}"))
        elif name not in stored and first_link and not mapping.is_blank(name, current):
            reviews.append(("twenty_field_overwritten", f"{name}:{observed[:32]}"))
        patch[name] = want
    if not created:
        patch.update({k: v for k, v in mapping.fill_unowned(f, person).items() if k not in patch})
        details_patch, _conflicts = mapping.blank_fill(f.details, person)
        patch.update(details_patch)
    if patch:
        person = twenty.update_person(person_id, {**patch, **meta}) or person
        fresh = twenty.get_person(person_id)
        if fresh is None:
            raise NeedsStaff("twenty_linked_person_missing", _short(person_id))
        person = fresh
    hashes = {**stored, **{name: mapping.value_hash(name, person.get(name)) for name in desired}}
    return person, hashes, reviews


def write_note(claim, application, link, person_id: str, note: mapping.NoteFacts) -> tuple[str, str]:
    """Create or update the one applicant file note and attach it to the person. Returns (note id, digest). No request
    at all when the note is unchanged since the last write."""
    title, body = mapping.render(note)
    digest = mapping.note_sha256(title, body)
    note_id = link.note_id
    if note_id and link.note_sha256 == digest:
        return note_id, digest
    existing = twenty.get_note(note_id) if note_id else None
    if note_id and existing is None:
        note_id = ""  # our note was deleted in Twenty: start a new one, never borrow somebody else's
    if not note_id:
        found = [n for n in twenty.find_notes(title) if mapping.is_marked(n, note.case_id)]
        note_id = str(found[0]["id"]) if found else ""
        existing = found[0] if found else None
    if note_id:
        if existing.get("title") != title or ((existing.get("bodyV2") or {}).get("markdown") or "") != body:
            twenty.update_note(note_id, title, body)
    else:
        note_id = twenty.create_note(title, body)
    _save(claim, application, note_id=note_id, note_sha256="")
    if person_id not in twenty.note_targets(note_id):
        twenty.attach_note(note_id, person_id)
    return note_id, digest


class ProjectApplication:
    """`twenty_project`: one application's person, fields and note (module docstring)."""

    kind = PROJECT
    automated = False  # back-office only: runs while the application's correspondence is paused
    redeliverable = True  # every write is checked first, so a redelivery cannot duplicate one

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        """Never an ApplicationEvent (each would queue another projection): the last failure opens one staff item."""
        if kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final")):
            application = Application.objects.filter(public_ref=claim.subject_id).first()
            if application is not None:
                open_review(application, "twenty_projection_failed", "attempts")

    def run(self, claim) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        if not enabled() or application is None or application.email_key.startswith("erased:"):
            code = "projection_off" if not enabled() else "nothing_to_project"
            ledger.finish(claim, self, status=Status.DONE, error=code)
            return
        if not twenty.configured():
            ledger.fail_or_retry(claim, self, "twenty_not_configured", write=lambda: self.record(
                claim, "action_failed", {"final": claim.final}))
            return
        if not _try_lock(application):
            ledger.finish(claim, self, status=Status.QUEUED, error="another_run_holds_the_application",
                          refund_attempt=True, due_in=LOCK_RETRY)
            return
        try:
            self._project(claim, application)
        except ledger.LeaseLost:
            return
        finally:
            _unlock(application)

    def _project(self, claim, application) -> None:
        link, _ = TwentyLink.objects.get_or_create(application=application)
        origin = imported(application)
        if origin and not link.person_id and origin.person_id:
            _save(claim, application, person_id=origin.person_id, link_method="imported", note_id=origin.note_id)
            link.refresh_from_db()
        field_facts, note_facts = facts(application)
        try:
            person, hashes, reviews = project_person(claim, application, link, field_facts)
            link.refresh_from_db()
            note_id, digest = write_note(claim, application, link, str(person["id"]), note_facts)
        except NeedsStaff as exc:
            reason, observation = exc.reason, exc.observation
            ledger.finish(claim, self, status=Status.DONE, error=reason,
                          write=lambda: open_review(application, reason, observation))
            return
        except twenty.TwentyError as exc:
            code = exc.code
            if exc.rejected:
                ledger.finish(claim, self, status=Status.FAILED, error=code,
                              write=lambda: open_review(application, "twenty_request_rejected", code))
                return
            logger.warning("twenty projection %s attempt %s: %s", claim.id, claim.attempt, code)
            ledger.fail_or_retry(claim, self, code, write=lambda: self.record(
                claim, "action_failed", {"final": claim.final}))
            return

        def done():
            TwentyLink.objects.filter(application=application).update(
                field_hashes=hashes, note_id=note_id, note_sha256=digest, projection_version=mapping.PROJECTION_VERSION,
                projected_at=Now(), updated_at=Now())
            for reason, observation in reviews:
                open_review(application, reason, observation)
        ledger.finish(claim, self, status=Status.DONE, write=done)


# --- the daily details fill ------------------------------------------------------------------------------------------

def fill_person(person_id: str, desired: dict) -> tuple[list, list]:
    """Fill one person's blank User Agreement details. Returns (fields written, conflicts)."""
    person = twenty.get_person(person_id)
    if person is None:
        return [], ["person_missing"]
    patch, conflicts = mapping.blank_fill(desired, person)
    if patch:
        twenty.update_person(person_id, patch)
    return sorted(patch), conflicts


class FillDetails:
    """`twenty_details_fill`: once a day, the confirmed User Agreement details into blank Twenty fields."""

    kind = FILL
    automated = False
    redeliverable = True  # fills blanks only, after reading them

    def lock_subject(self, claim) -> None:
        pass

    def record(self, claim, kind, data) -> None:
        """The chain survives a final failure: the next day's fill is queued anyway."""
        if kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final")):
            schedule_details_fill(_number(claim) + 1, settings.CATALYST_TWENTY_FILL_SECONDS)

    def run(self, claim) -> None:
        if not enabled():
            ledger.finish(claim, self, status=Status.DONE, error="projection_off")
            return
        from agreements.models import AgreementDetailsVersion

        report = {"unchanged": 0, "filled": 0, "conflicts": 0, "queued": 0, "skipped": 0, "errors": 0}
        ids = (AgreementDetailsVersion.objects.filter(agreement_type__key="user_agreement",
                                                      status=AgreementDetailsVersion.Status.CONFIRMED)
               .values_list("application_id", flat=True).distinct())
        for application in Application.objects.filter(pk__in=ids).exclude(email_key__startswith="erased:").order_by("id"):
            try:
                with transaction.atomic():
                    ledger.fence(claim)  # keeps the lease across a long run, and stops when it is lost
            except ledger.LeaseLost:
                return
            outcome = self._one(application)
            report[outcome] = report.get(outcome, 0) + 1
            if outcome == "stop":
                break
        logger.info("twenty details fill %s: %s", claim.id, " ".join(f"{k}={v}" for k, v in sorted(report.items())))
        n = _number(claim)
        ledger.finish(claim, self, status=Status.DONE,
                      error="" if not report["errors"] else f"errors:{report['errors']}",
                      write=lambda: schedule_details_fill(n + 1, settings.CATALYST_TWENTY_FILL_SECONDS))

    def _one(self, application) -> str:
        link = TwentyLink.objects.filter(application=application).first()
        if link is None or not link.person_id:
            return "queued" if enqueue(application, f"fill-{timezone.now():%Y%m%d}") else "skipped"
        desired = mapping.details_values(_confirmed_details(application))
        if not desired:
            return "skipped"
        if not _try_lock(application):
            return "skipped"  # a projection is writing this person now, and fills the same blanks
        try:
            written, conflicts = fill_person(link.person_id, desired)
        except twenty.TwentyError as exc:
            return "stop" if exc.code == "twenty_not_configured" else "errors"
        finally:
            _unlock(application)
        if conflicts:
            return "conflicts"
        return "filled" if written else "unchanged"


def _number(claim) -> int:
    key = PendingAction.objects.filter(pk=claim.id).values_list("idempotency_key", flat=True).first() or ""
    try:
        return int(key.rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return 0


# --- staff: link a person by hand ------------------------------------------------------------------------------------

def link_person(application, person_id: str) -> None:
    """Pin the application to the Twenty person staff confirmed (after an ambiguous or missing match) and queue a
    projection. The note is rewritten and attached to the newly linked person at the next run."""
    person_id = person_id.strip()
    if not twenty.RECORD_ID.fullmatch(person_id):
        raise ValueError("person_id_invalid")
    with transaction.atomic():
        Application.objects.select_for_update(of=("self",)).get(pk=application.pk)
        link, _ = TwentyLink.objects.get_or_create(application=application)
        fields = {"person_id": person_id, "link_method": "staff", "updated_at": Now()}
        if link.person_id != person_id:
            fields.update(field_hashes={}, note_sha256="")
        TwentyLink.objects.filter(pk=link.pk).update(**fields)
        enqueue(application, f"staff-link-{uuid.uuid4().hex[:12]}")
