"""P4 agreement records (021 section 3; 4B.1). Synthetic only: a local fake Documenso, placeholder PDFs, no agreement
text in this repository (REQ-019).

The three statuses of an instance are separate facts and never derive from one another (021 section 3, `004` J-11 to
J-13). Database protections (migration 0002): template versions change only while draft; recipients and the
identity of an attempt are insert-only; one live instance per (application, type); and the D-15 backstop refuses a
User Agreement instance unless the NDA is `signing_complete_verified`.

Provider responses never reach these tables raw: only allowlisted fields (`agreements.provider`), never a signing
token or link (021 section 6).
"""

import uuid

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now

ISSUE = ["held", "create_pending", "created", "create_uncertain", "distribute_pending", "distribute_uncertain", "issued",
         "failed_needs_staff", "cancel_pending", "cancel_uncertain", "cancelled", "superseded"]
SIGNING = ["not_started", "partially_signed", "signing_complete_observed", "signing_complete_verified", "declined",
           "expired", "cancelled"]
CUSTODY = ["not_due", "pending", "stored_verified", "failed_retry_pending", "failed_needs_staff"]
NOT_LIVE = ["superseded", "cancelled"]
ATTEMPT_OUTCOMES = ["sending", "succeeded", "not_sent", "rejected", "unknown", "found_by_evidence", "decided_not_sent",
                    "abandoned", "orphan_found"]


class AgreementType(models.Model):
    """The inventory (POL-07; P4-D-1: `nda` then `user_agreement` for synthetic P4). Seeded by migration; a change is a
    new migration, never an edit at run time."""

    class Gate(models.TextChoices):
        SIGNING = "signing"
        SIGNING_AND_CUSTODY = "signing_and_custody"  # P4-D-6: fail closed

    key = models.CharField(max_length=40, unique=True)
    order = models.PositiveSmallIntegerField(unique=True)
    required = models.BooleanField(default=True)
    gate = models.CharField(max_length=24, choices=Gate.choices, default=Gate.SIGNING_AND_CUSTODY)

    def __str__(self):
        return self.key


class AgreementTemplateVersion(models.Model):
    """One approved Documenso template per type and version. The provider references are synthetic in P4. Only the
    approval columns change, and only while the version is a draft (database trigger)."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        APPROVED = "approved"

    agreement_type = models.ForeignKey(AgreementType, on_delete=models.PROTECT, related_name="template_versions")
    version = models.PositiveIntegerField()
    # The template envelope's id (the `envelopeId` that `envelope/use` takes) and the numeric `templateId` that
    # envelopes created from it carry (the reconciliation listing filters on it). Both synthetic in P4; that the two
    # correspond as described is NOT VERIFIED on the installed version (021 section 15).
    provider_template_ref = models.CharField(max_length=64)
    provider_template_number = models.PositiveIntegerField()
    # The template's recipient slots: {"SIGNER:1": <Documenso template recipient id>}. P4-D-3: the applicant is the
    # only required signer until POL-08 names a countersigner.
    recipient_slots = models.JSONField(default=dict)
    pdf_sha256 = models.CharField(max_length=64)  # the synthetic placeholder PDF's digest
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.CharField(max_length=200, blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        permissions = [("approve_agreement_template", "Approve an agreement template version (owner; POL-07)")]
        constraints = [
            models.UniqueConstraint(fields=["agreement_type", "version"], name="agreement_template_one_per_version"),
            models.CheckConstraint(condition=Q(status__in=["draft", "approved"]), name="agreement_template_status_valid"),
            models.CheckConstraint(condition=Q(status="draft") | ~Q(approved_by=""), name="agreement_template_approved_has_actor"),
        ]


class AgreementInstance(models.Model):
    """One agreement of one type for one application (J-11). `external_key` is the opaque key sent as Documenso's
    `externalId`; it carries no applicant data. A new create after an unknown outcome mints a new key (P4-D-19); every
    key ever used is kept on its `EnvelopeAttempt`."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="agreements")
    agreement_type = models.ForeignKey(AgreementType, on_delete=models.PROTECT, related_name="instances")
    template_version = models.ForeignKey(AgreementTemplateVersion, on_delete=models.PROTECT, related_name="instances")
    external_key = models.CharField(max_length=64)
    envelope_id = models.CharField(max_length=64, blank=True, default="")
    issue_status = models.CharField(max_length=24, default="held")
    signing_status = models.CharField(max_length=32, default="not_started")
    custody_status = models.CharField(max_length=24, default="not_due")
    # D-42: a stop or cancel requested while a provider exchange was in flight. Set once; the exchange's result then
    # routes to cancellation instead of continuing.
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    # D-43: a controlled new generation replaced this instance for future progression. The verified history stays as
    # it was; only eligibility changes. Set once.
    replaced_at = models.DateTimeField(null=True, blank=True)
    replacement_reason = models.CharField(max_length=40, blank=True, default="", db_default="")
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        permissions = [("resolve_agreement_integrity",
                        "Resolve an agreement-integrity hold: recheck, continue on fresh evidence, or replace (D-43)"),
                       ("decide_uncertain_agreement",
                        "Decide an agreement step whose provider outcome is unknown (decision-maker; P4-D-8)"),
                       ("manage_agreements",
                        "Cancel, reissue or stop an applicant's agreements (decision-maker; P4-D-9, P4-D-18, P4-D-20)")]
        constraints = [
            models.CheckConstraint(condition=Q(issue_status__in=ISSUE), name="agreement_issue_status_valid"),
            models.CheckConstraint(condition=Q(signing_status__in=SIGNING), name="agreement_signing_status_valid"),
            models.CheckConstraint(condition=Q(custody_status__in=CUSTODY), name="agreement_custody_status_valid"),
            models.UniqueConstraint(fields=["application", "agreement_type"],
                                    condition=~Q(issue_status__in=NOT_LIVE) & Q(replaced_at__isnull=True),
                                    name="agreement_one_live_per_type"),
            models.UniqueConstraint(fields=["external_key"], name="agreement_external_key_unique"),
            models.CheckConstraint(  # D-43: set together, with the one known reason code
                condition=(Q(replaced_at__isnull=True, replacement_reason="")
                           | Q(replaced_at__isnull=False, replacement_reason="integrity_replaced")),
                name="agreement_replacement_consistent"),
            models.UniqueConstraint(fields=["envelope_id"], condition=~Q(envelope_id=""), name="agreement_envelope_unique"),
        ]


class AgreementRecipient(models.Model):
    """Who signs, in what role and order (POL-08). Insert-only: a changed recipient is a new instance."""

    class Role(models.TextChoices):
        SIGNER = "SIGNER"
        APPROVER = "APPROVER"
        VIEWER = "VIEWER"
        CC = "CC"

    instance = models.ForeignKey(AgreementInstance, on_delete=models.PROTECT, related_name="recipients")
    role = models.CharField(max_length=16, choices=Role.choices)
    signing_order = models.PositiveSmallIntegerField()
    required = models.BooleanField(default=True)
    who = models.CharField(max_length=16)  # "applicant", or "staff" once POL-08 names a countersigner
    name = models.CharField(max_length=200)
    email = models.CharField(max_length=320)  # the applicant's verified address at issue

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["instance", "role", "signing_order"], name="agreement_recipient_one_per_slot"),
            models.CheckConstraint(condition=Q(who__in=["applicant", "staff"]), name="agreement_recipient_who_valid"),
        ]


class EnvelopeAttempt(models.Model):
    """One create or distribute exchange with the provider (ADR-15, D-27; 021 section 5). Written `sending` before the
    request leaves, so a crash after it is never mistaken for "not sent". Its identity (instance, step, key) is
    insert-only; only the outcome columns change."""

    class Step(models.TextChoices):
        CREATE = "create"
        DISTRIBUTE = "distribute"
        CANCEL = "cancel"

    class Outcome(models.TextChoices):
        SENDING = "sending"  # the request may have left: unknown until recorded
        SUCCEEDED = "succeeded"
        NOT_SENT = "not_sent"  # known not processed: refused before sending, a connect failure, 429
        REJECTED = "rejected"  # a definite 4xx from the provider
        UNKNOWN = "unknown"
        FOUND_BY_EVIDENCE = "found_by_evidence"  # reconciliation found the envelope
        DECIDED_NOT_SENT = "decided_not_sent"  # a decision-maker's call; the key stays watched (P4-D-19)
        ABANDONED = "abandoned"
        ORPHAN_FOUND = "orphan_found"  # a late match of an abandoned key: cancelled, never verified

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    instance = models.ForeignKey(AgreementInstance, on_delete=models.PROTECT, related_name="attempts")
    step = models.CharField(max_length=16, choices=Step.choices)
    external_key = models.CharField(max_length=64)
    pending_action_id = models.BigIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=24, choices=Outcome.choices, default=Outcome.SENDING)
    outcome_code = models.CharField(max_length=64, blank=True, default="")  # a reason code or HTTP status, never a body
    envelope_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(db_default=Now())
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(step__in=["create", "distribute", "cancel"]), name="envelope_attempt_step_valid"),
            models.CheckConstraint(condition=Q(outcome__in=ATTEMPT_OUTCOMES), name="envelope_attempt_outcome_valid"),
        ]
        indexes = [models.Index(fields=["external_key"], name="envelope_attempt_key")]


class CurrentTransactionId(models.Func):
    template = "pg_current_xact_id()::text::bigint"
    output_field = models.BigIntegerField()


class ProviderObservation(models.Model):
    """What the provider said about an envelope, from a webhook (a hint) or a fresh read (021 sections 4 and 6;
    4B.2). Protected history: append-only for every role (ADR-14). Only allowlisted facts are kept: statuses, roles,
    orders, and whether the provider's envelope and recipients equal ours; never a name, address, token or link.

    `signing_complete_verified` is only accepted by the database when a read observation in the same transaction shows
    the envelope complete, every required recipient signed, our identity and our recipients (migration 0004)."""

    class Source(models.TextChoices):
        WEBHOOK = "webhook"
        READ = "read"

    instance = models.ForeignKey(AgreementInstance, on_delete=models.PROTECT, related_name="observations")
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="+")
    source = models.CharField(max_length=16, choices=Source.choices)
    event = models.CharField(max_length=40, blank=True, default="")  # the webhook event name, or "" for a read
    envelope_status = models.CharField(max_length=16)
    recipients = models.JSONField(default=list)  # [{"role", "order", "signing_status", "expired"}]
    identity_match = models.BooleanField(default=False)  # envelope id, externalId and template are ours
    recipients_match = models.BooleanField(default=False)  # exactly our recipients' addresses and roles
    all_required_signed = models.BooleanField(default=False)
    content_sha256 = models.CharField(max_length=64)  # of the allowlisted facts, so an exact replay is a no-op
    observed_at = models.DateTimeField(db_default=Now())
    created_txid = models.BigIntegerField(db_default=CurrentTransactionId())

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(source__in=["webhook", "read"]), name="observation_source_valid"),
            models.UniqueConstraint(fields=["instance", "source", "event", "content_sha256"],
                                    condition=Q(source="webhook"), name="observation_webhook_once"),
        ]
        indexes = [models.Index(fields=["instance", "observed_at"], name="observation_instance_time")]

