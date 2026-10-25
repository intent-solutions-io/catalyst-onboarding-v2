"""Custody of signed agreements (021 section 7; 4B.3; P4-D-6, P4-D-7).

`StoreAgreement` (`store_agreement`) runs after `signing_complete_verified`:

1. A fresh read binds what is downloaded to this agreement. The envelope must still be complete, ours (id,
   `externalId`, template), with exactly our recipients and every required signature. Its items are the only ones
   downloaded. A `version=signed` download, a PDF header or a provider ETag proves nothing about completion by
   itself (021 section 18).
2. Each item is downloaded with `version=signed` through the hardened adapter (bounded size and time, no redirect,
   `%PDF` check), outside any transaction.
3. The bytes are sealed under a new per-document key (9kg.34, agreements.keystore) and stored under a new
   system-generated name, re-read, opened and re-hashed (`agreements.storage`).
4. One fenced transaction records a `StoredDocument` and its `CustodyEnvelope` per item and moves custody to
   `stored_verified`; then the sequence advances.

Failures:
- A provider or storage failure retries within the attempt bound (custody `failed_retry_pending`), then becomes
  `failed_needs_staff` with a staff item.
- Signing stays verified; nothing is re-signed, reissued or advanced.
- A failure or a decision made meanwhile discards what was written (the new keys and sealed files, 9kg.34). An
  interruption between the file write and the record (a crash) leaves an unreferenced pair that is never served (only
  recorded keys are read); `catalyst_custody_keys --status` reports it and `--reap-orphans` removes it; the retry
  writes a new key. The unique (instance, item) record prevents a second
  authoritative copy.

Custody only reads from the provider, so, like reconciliation (D-44), it is not held by an automation pause.
"""

import logging

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models.functions import Now

from applications.models import Application
from correspondence.staff_items import event, open_item
from workflow import ledger
from workflow.models import PendingAction

from . import provider, storage
from .models import AgreementInstance, CustodyEnvelope, ProviderObservation, StoredDocument

logger = logging.getLogger(__name__)
Status = PendingAction.Status
STORE = "store_agreement"
CUSTODY_FAILED = "agreement_custody_failed"
CUSTODY_CORRUPTED = "agreement_custody_corrupted"


def enqueue_store(instance) -> PendingAction:
    """Inside the caller's transaction. One queued store per instance at a time."""
    pending = PendingAction.objects.filter(kind=STORE, input_ref=str(instance.public_id),
                                           status__in=(Status.QUEUED, Status.RUNNING)).first()
    if pending is not None:
        return pending
    n = PendingAction.objects.filter(kind=STORE, input_ref=str(instance.public_id)).count() + 1
    return PendingAction.objects.create(
        kind=STORE, subject_type="application", subject_id=instance.application.public_ref,
        input_ref=str(instance.public_id), idempotency_key=f"{STORE}:{instance.public_id}:{n}",
        max_attempts=settings.CATALYST_AGREEMENT_ATTEMPTS)


class StoreAgreement:
    kind = STORE
    redeliverable = True  # idempotent: the unique (instance, item) record and fresh keys
    automated = False  # it only reads from the provider (D-44 classification)

    def lock_subject(self, claim) -> None:
        application = Application.objects.select_for_update(of=("self",)).filter(public_ref=claim.subject_id).first()
        if application is not None:
            AgreementInstance.objects.select_for_update(of=("self",)).filter(public_id=claim.input_ref,
                                                                             application=application).first()

    def record(self, claim, kind, data) -> None:
        application = Application.objects.filter(public_ref=claim.subject_id).first()
        event(application, kind, data, actor_ref=f"pending_action:{claim.id}")
        if application is not None and (kind == "action_attempts_exhausted" or (kind == "action_failed" and data.get("final"))):
            self._staff(claim, "handler_error")

    def _staff(self, claim, code) -> None:
        instance = AgreementInstance.objects.select_related("application").filter(public_id=claim.input_ref).first()
        if instance is None:
            return
        AgreementInstance.objects.filter(pk=instance.pk, custody_status__in=("pending", "failed_retry_pending")).update(
            custody_status="failed_needs_staff", updated_at=Now())
        open_item(CUSTODY_FAILED, f"custody:{instance.public_id}", application=instance.application,
                  pending_action_id=claim.id)
        event(instance.application, "agreement_custody_failed", {"instance": str(instance.public_id), "code": code},
              actor_ref=f"pending_action:{claim.id}")

    def run(self, claim) -> None:
        from .completion import facts, read_identity

        instance = (AgreementInstance.objects.select_related("application", "template_version", "agreement_type")
                    .filter(public_id=claim.input_ref).first())
        if (instance is None or str(instance.application.public_ref) != str(claim.subject_id)
                or instance.signing_status != "signing_complete_verified" or instance.replaced_at
                or instance.custody_status not in ("pending", "failed_retry_pending")):
            ledger.finish(claim, self, status=Status.DONE, error="nothing_to_store")
            return
        stored = []
        try:
            env = provider.read(instance.envelope_id)
            data = facts(instance, env.status, env.recipients, identity=read_identity(instance, env))
            if not (env.status == "COMPLETED" and data["identity_match"] and data["all_required_signed"]):
                self._mismatch(claim, instance, env, data)
                return
            if not env.items or len(env.items) > settings.CATALYST_AGREEMENT_MAX_ITEMS:
                raise provider.ProviderError("items_unexpected", sent=True, status=200)
            for item in env.items:  # outside any transaction
                pdf = provider.download(item)
                key, digest, sealed = storage.write(pdf)
                stored.append((item, key, digest, len(pdf), sealed))
            # A second fresh read: the envelope did not change while its items were downloaded (security review).
            after = provider.read(instance.envelope_id)
            again = facts(instance, after.status, after.recipients, identity=read_identity(instance, after))
            if (after.items != env.items or after.status != "COMPLETED" or not again["identity_match"]
                    or not again["all_required_signed"]):  # recipients included (QA review)
                raise provider.ProviderError("envelope_changed_during_download", sent=True, status=200)
        except (provider.ProviderError, storage.StorageError) as exc:
            for *_, sealed in stored:  # nothing will be recorded: no orphan key or sealed file (review of PR #102, F2)
                storage.discard(sealed)
            code = exc.code if isinstance(exc, provider.ProviderError) else str(exc)
            if claim.final:
                ledger.finish(claim, self, status=Status.FAILED, error=code, write=lambda: self._staff(claim, code))
            else:
                due = None
                if isinstance(exc, provider.ProviderError) and exc.retry_after is not None:
                    from datetime import timedelta
                    due = timedelta(seconds=exc.retry_after)
                ledger.finish(claim, self, status=Status.QUEUED, error=code, due_in=due, write=lambda: (
                    AgreementInstance.objects.filter(pk=instance.pk, custody_status="pending").update(
                        custody_status="failed_retry_pending", updated_at=Now())))
            return
        ledger.finish(claim, self, status=Status.DONE, write=lambda: self._record(claim, instance.pk, env, data, stored))

    def _mismatch(self, claim, instance, env, data) -> None:
        from .completion import observe, open_integrity_hold

        def write():
            observe(AgreementInstance.objects.get(pk=instance.pk), ProviderObservation.Source.READ, data)
            open_integrity_hold(instance, "custody_read_mismatch", claim.id, f"pending_action:{claim.id}")
        ledger.finish(claim, self, status=Status.DONE, error="custody_read_mismatch", write=write)

    def _record(self, claim, instance_id, env, data, stored) -> None:
        from .completion import enqueue_advance, observe

        instance = AgreementInstance.objects.select_related("application").get(pk=instance_id)
        if instance.signing_status != "signing_complete_verified" or instance.replaced_at or instance.custody_status not in (
                "pending", "failed_retry_pending"):
            for *_, sealed in stored:  # decided meanwhile: nothing is recorded, so nothing is kept (PR #102, F2)
                storage.discard(sealed)
            return
        observation = observe(instance, ProviderObservation.Source.READ, data)
        try:
            with transaction.atomic():
                for item, key, digest, size, sealed in stored:
                    document = StoredDocument.objects.create(
                        instance=instance, application=instance.application, envelope_id=instance.envelope_id,
                        item_id=item, storage_key=key, sha256=digest, size=size, observation=observation)
                    CustodyEnvelope.objects.create(document=document, **sealed.fields())
        except IntegrityError:
            # A record for this item already exists (insert-only). Never a silent "pending": staff decide.
            for *_, sealed in stored:
                storage.discard(sealed)
            AgreementInstance.objects.filter(pk=instance.pk).update(custody_status="failed_needs_staff", updated_at=Now())
            open_item(CUSTODY_FAILED, f"custody:{instance.public_id}", application=instance.application,
                      pending_action_id=claim.id)
            return
        AgreementInstance.objects.filter(pk=instance.pk).update(custody_status="stored_verified", updated_at=Now())
        event(instance.application, "agreement_custody_verified",
              {"instance": str(instance.public_id), "documents": len(stored)}, actor_ref=f"pending_action:{claim.id}")
        enqueue_advance(instance.application)
