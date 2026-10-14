"""Evidence collection jobs (018 section 4 steps 1 to 3; task 3B.1). Synthetic only; no model call.

- `StartEvidenceCollection` (`start_evidence_collection`, the action S1 confirmation creates **held**): released only
  by the owner-run `activate_evidence_collection` command (018 4.1). One transaction: the application is still
  `contact_verified` and its adoption matches the action's input; one `EvidenceItem` per claimed URL with an
  approved source (a URL with none is recorded `refused: no_approved_source`, never a negative finding); stage
  `contact_verified` to `evidence`; one `fetch_evidence` action per pending item.
- `FetchEvidence` (`fetch_evidence:<item>`): a short eligibility transaction, the fetch outside any transaction
  (`assessments.fetch`), then a fenced record transaction writing one immutable `EvidenceCapture`, or the item's
  terminal status. Refusals are never retried; transient failures are retried up to the attempt bound, then the
  item is `unavailable`. When no item of the adopted version is pending, the required-item rule runs (step 3).

Both kinds are automated (a pause holds them) and redeliverable (P3-D-12): their database effects are fenced, and a
redelivered fetch only repeats one GET to a public source.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models.functions import Now

from applications.models import Application, ApplicationEvent, Stage
from applications.stages import StageConflict, transition
from correspondence.staff_items import open_item
from workflow import ledger
from workflow.models import AutomationPause, PendingAction

from . import fetch
from .models import CANNOT_PROVE, EvidenceCapture, EvidenceItem, EvidenceSource

logger = logging.getLogger(__name__)
Status = PendingAction.Status
Item = EvidenceItem.Status
START = "start_evidence_collection"
FETCH = "fetch_evidence"
CLAIM_KINDS = {"work": "work_sample_page", "credential": "credential_verification"}


def event(application, kind, data, actor_ref=""):
    ApplicationEvent.objects.create(application=application, kind=kind, actor_type=ApplicationEvent.ActorType.SYSTEM,
                                    actor_ref=actor_ref, data=data)


def claimed_urls(claims: dict) -> list:
    """(claim_ref, url, credential reference or "") for every URL claim, in a stable order."""
    out = []
    for i, work in enumerate(claims.get("work") or [], start=1):
        if work.get("url"):
            out.append((f"work:{i}", work["url"], ""))
    for i, credential in enumerate(claims.get("credentials") or [], start=1):
        if credential.get("url"):
            out.append((f"credential:{i}", credential["url"], credential.get("identifier") or ""))
    return out


def approved_source(kind: str, url: str):
    """The approved source for this URL: same kind, host and port, with the longest path prefix that matches on a
    path-segment boundary; deterministic when several sources share a host."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        port = parts.port if parts.port is not None else 443
    except (UnicodeError, ValueError):
        return None
    path = parts.path or "/"
    matches = []
    for source in EvidenceSource.objects.filter(kind=kind, host=host, port=port, status=EvidenceSource.Status.APPROVED):
        prefix = source.path_prefix.rstrip("/")
        if path == prefix or path.startswith(prefix + "/") or not prefix:
            matches.append(source)
    matches.sort(key=lambda s: (-len(s.path_prefix.rstrip("/")), s.key))
    return matches[0] if matches else None


def enqueue_fetch(application, item) -> None:
    PendingAction.objects.create(
        kind=FETCH, subject_type="application", subject_id=application.public_ref, input_ref=str(item.public_id),
        idempotency_key=f"{FETCH}:{item.public_id}", max_attempts=settings.CATALYST_EVIDENCE_FETCH_ATTEMPTS)


def finish_item(item, status: str, reason: str = "") -> None:
    EvidenceItem.objects.filter(pk=item.pk, status=Item.PENDING).update(status=status, reason_code=reason,
                                                                        finished_at=Now(), updated_at=Now())


def complete_if_done(application, version) -> None:
    """018 step 3, inside the caller's transaction with the application locked."""
    items = EvidenceItem.objects.filter(application=application, adopted_version=version)
    if items.filter(status=Item.PENDING).exists():
        return
    latest = {}
    for item in items.select_related("source").order_by("claim_ref", "round"):
        latest[item.claim_ref] = item  # a staff re-fetch supersedes the earlier round for the same claim
    def missing(i):  # nothing usable was observed: unavailable, refused, or found nothing at the claimed URL
        return i.status in (Item.UNAVAILABLE, Item.REFUSED) or (
            i.status == Item.FETCHED and not i.captures.exclude(outcome="not_found").exists())
    blocking = [i for i in latest.values() if i.required and missing(i)
                and (i.source is None or i.source.on_unavailable == EvidenceSource.OnUnavailable.STAFF)]
    if blocking:
        open_item("evidence_required_unavailable", f"evidence:{application.public_ref}:{version.public_id}",
                  application=application)
        return
    try:
        transition(application.pk, (Stage.EVIDENCE,), Stage.ASSESSING, event_kind="evidence_collection_complete",
                   data={"version": str(version.public_id), "items": len(latest)})
    except StageConflict:
        pass  # the application moved meanwhile (closed, withdrawn): history only


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str = ""
    refund: bool = False
    due_in: timedelta | None = None
    write: object = None


class _ApplicationAction:
    automated = True
    redeliverable = True

    def lock_subject(self, claim) -> None:
        Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        if application is not None:
            event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
            if kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final")):
                self.on_final_failure(claim, application)  # a job that cannot finish never ends silently

    def on_final_failure(self, claim, application) -> None:
        open_item("evidence_collection_failed", f"{self.kind}:{claim.input_ref}", application=application,
                  pending_action_id=claim.id)

    def _paused(self, application) -> bool:
        return AutomationPause.objects.filter(subject_type="application", subject_id=application.public_ref).exists()


class StartEvidenceCollection(_ApplicationAction):
    kind = START

    def run(self, claim) -> None:
        with transaction.atomic():
            self.lock_subject(claim)
            decision = self.decide(claim)
            ledger.finish(claim, self, status=decision.status, error=decision.reason, write=decision.write,
                          refund_attempt=decision.refund, due_in=decision.due_in)

    def decide(self, claim) -> Decision:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        if application is None:
            return Decision(Status.FAILED, "application_not_found")
        if self._paused(application):
            return Decision(Status.QUEUED, "automation_paused", refund=True,
                            due_in=timedelta(seconds=settings.CATALYST_WORKER_POLL_SECONDS))
        if application.stage != Stage.CONTACT_VERIFIED:
            return Decision(Status.CANCELLED, "stage_changed")
        adoption = application.adoptions.select_related("submission_version").first()
        if adoption is None or str(adoption.submission_version.public_id) != claim.input_ref:
            return Decision(Status.FAILED, "adoption_changed", write=lambda: open_item(
                "adoption_changed", f"evidence:{application.public_ref}", application=application, pending_action_id=claim.id))
        version = adoption.submission_version
        claims = (version.submitted_fields or {}).get("claims")
        if claims is None:
            return Decision(Status.DONE, "claims_missing", write=lambda: open_item(
                "claims_missing", f"evidence:{application.public_ref}", application=application, pending_action_id=claim.id))

        def write():
            items = []
            for claim_ref, url, _ in claimed_urls(claims):
                kind = CLAIM_KINDS[claim_ref.split(":")[0]]
                source = approved_source(kind, url)
                item = EvidenceItem.objects.create(
                    application=application, adopted_version=version, source=source, claim_ref=claim_ref,
                    request_url=url[:2048], request_url_sha256=fetch.sha256(url), required=bool(source and source.required))
                if source is None:
                    finish_item(item, Item.REFUSED, "no_approved_source")
                else:
                    items.append(item)
            transition(application.pk, (Stage.CONTACT_VERIFIED,), Stage.EVIDENCE, event_kind="evidence_collection_started",
                       data={"version": str(version.public_id), "items": len(items)}, actor_ref=f"pending_action:{claim.id}")
            for item in items:
                enqueue_fetch(application, item)
            complete_if_done(application, version)
        return Decision(Status.DONE, write=write)


class FetchEvidence(_ApplicationAction):
    kind = FETCH

    def on_final_failure(self, claim, application) -> None:
        """The item becomes unavailable (a handler defect, never a negative finding), so collection can complete."""
        item = EvidenceItem.objects.select_related("adopted_version").filter(public_id=claim.input_ref).first()
        if item is not None and item.status == Item.PENDING:
            finish_item(item, Item.UNAVAILABLE, "handler_error")
            if Application.objects.filter(pk=application.pk, stage=Stage.EVIDENCE).exists():
                complete_if_done(application, item.adopted_version)
        super().on_final_failure(claim, application)

    def lock_subject(self, claim) -> None:
        """Application, then the item (018 section 4)."""
        application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
        if application is not None:
            EvidenceItem.objects.select_for_update(of=("self",)).filter(public_id=claim.input_ref, application=application).first()

    def run(self, claim) -> None:
        try:
            with transaction.atomic():
                self.lock_subject(claim)
                ledger.fence(claim)  # another claim owns the action: nothing is fetched or written
                early, item = self.check(claim)
                if early is not None:
                    ledger.finish(claim, self, status=early.status, error=early.reason, write=early.write,
                                  refund_attempt=early.refund, due_in=early.due_in)
                    return
        except ledger.LeaseLost:
            logger.warning("action %s (%s): lease lost before fetching; nothing fetched", claim.id, claim.kind)
            return
        try:
            result = fetch.fetch(item.request_url, item.source)  # outside any transaction
        except fetch.Refused as exc:
            self._terminal(claim, Item.REFUSED, str(exc))
            return
        except fetch.Private as exc:
            self._terminal(claim, Item.UNAVAILABLE, str(exc))  # private: not retried, never negative
            return
        except fetch.Transient as exc:
            if claim.final:
                self._terminal(claim, Item.UNAVAILABLE, str(exc), ledger_status=Status.FAILED)
            else:
                ledger.finish(claim, self, status=Status.QUEUED, error=str(exc))
            return
        self._record(claim, result)

    def check(self, claim):
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        item = (EvidenceItem.objects.select_related("source", "adopted_version").filter(public_id=claim.input_ref)
                .first() if application else None)
        if application is None or item is None or item.application_id != application.pk:
            return Decision(Status.FAILED, "item_not_found"), None
        if item.status != Item.PENDING:
            return Decision(Status.DONE, "item_already_finished"), None
        if application.stage != Stage.EVIDENCE:
            return Decision(Status.CANCELLED, "stage_changed"), None
        if self._paused(application):
            return Decision(Status.QUEUED, "automation_paused", refund=True,
                            due_in=timedelta(seconds=settings.CATALYST_WORKER_POLL_SECONDS)), None
        source = item.source
        if (source is None or source.status != EvidenceSource.Status.APPROVED
                or source.host not in settings.CATALYST_EVIDENCE_ALLOWED_HOSTS
                or (source.fixture_only and settings.CATALYST_ENV != "test")):
            reason = "source_not_allowed"
            return Decision(Status.DONE, reason, write=lambda: self._terminal_write(application, item, Item.REFUSED, reason)), None
        return None, item

    def _terminal_write(self, application, item, status, reason) -> None:
        finish_item(item, status, reason)
        event(application, "evidence_item_" + status, {"item": str(item.public_id), "claim": item.claim_ref, "reason": reason})
        complete_if_done(application, item.adopted_version)

    def _terminal(self, claim, status, reason, ledger_status=Status.DONE) -> None:
        def write():
            application = Application.objects.get(public_ref=claim.subject_id)
            item = EvidenceItem.objects.select_related("adopted_version").get(public_id=claim.input_ref)
            if item.status == Item.PENDING and application.stage == Stage.EVIDENCE:
                self._terminal_write(application, item, status, reason)
        ledger.finish(claim, self, status=ledger_status, error=reason, write=write)

    def _record(self, claim, result) -> None:
        def write():
            application = Application.objects.get(public_ref=claim.subject_id)
            item = EvidenceItem.objects.select_related("source", "adopted_version").get(public_id=claim.input_ref)
            if item.status != Item.PENDING or application.stage != Stage.EVIDENCE:
                return  # decided meanwhile: the observation is not recorded against a finished slot
            derived = fetch.derive(result)
            outcome = _outcome(item, result, derived)
            try:
                with transaction.atomic():
                    EvidenceCapture.objects.create(
                        item=item, application=application, source=item.source, attempt_number=claim.attempt,
                        final_url=result.final_url[:2048], http_status=result.status,
                        content_type=result.content_type.split(";")[0][:200], revision_marker=result.revision_marker,
                        byte_length=len(result.body), truncated=result.truncated or derived.truncated,
                        response_sha256=fetch.sha256(result.body), derived_text=derived.text,
                        derived_sha256=fetch.sha256(derived.text), derivation_version=fetch.DERIVATION_VERSION,
                        outcome=outcome, cannot_prove=CANNOT_PROVE[item.source.kind], injection_markers=derived.markers,
                        peer_ip=result.peer_ip)
            except IntegrityError:
                return  # this attempt was already recorded (a redelivery after the commit)
            finish_item(item, Item.FETCHED)
            event(application, "evidence_observed", {"item": str(item.public_id), "claim": item.claim_ref,
                                                     "outcome": outcome, "markers": derived.markers})
            complete_if_done(application, item.adopted_version)
        ledger.finish(claim, self, status=Status.DONE, write=write)


def _outcome(item, result, derived) -> str:
    if result.status in (404, 410):
        return "not_found"
    if not derived.text:
        return "found_but_inconclusive"
    if item.source.kind == "credential_verification":
        claims = (item.adopted_version.submitted_fields or {}).get("claims") or {}
        credentials = claims.get("credentials") or []
        index = int(item.claim_ref.split(":")[1]) - 1
        identifier = (credentials[index].get("identifier") or "") if index < len(credentials) else ""
        if not identifier or identifier not in derived.text:
            return "found_but_inconclusive"  # the page exists but does not show the claimed identifier
    return "found"
