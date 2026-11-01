"""P4 agreement records (021 section 3; 4B.1). Synthetic only: a local fake Documenso, placeholder PDFs, no agreement
text in this repository (REQ-019).

The three statuses of an instance are separate facts and never derive from one another (021 section 3, `004` J-11 to
J-13). Database protections (migrations 0002 and 0014): template content and approval metadata are fixed after approval;
only retirement is then allowed. Recipients and the identity of an attempt are insert-only; one live instance per (application, type); and the D-15 backstop refuses a
User Agreement instance unless the NDA is `signing_complete_verified`.

Provider responses never reach these tables raw: only allowlisted fields (`agreements.provider`), never a signing
token or link (021 section 6).
"""

import uuid

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now

ISSUE = [
    "held",
    "create_pending",
    "created",
    "create_uncertain",
    "distribute_pending",
    "distribute_uncertain",
    "issued",
    "failed_needs_staff",
    "cancel_pending",
    "cancel_uncertain",
    "cancelled",
    "superseded",
]
SIGNING = [
    "not_started",
    "partially_signed",
    "signing_complete_observed",
    "signing_complete_verified",
    "declined",
    "expired",
    "cancelled",
]
CUSTODY = [
    "not_due",
    "pending",
    "stored_verified",
    "failed_retry_pending",
    "failed_needs_staff",
]
NOT_LIVE = ["superseded", "cancelled"]
ATTEMPT_OUTCOMES = [
    "sending",
    "succeeded",
    "not_sent",
    "rejected",
    "unknown",
    "found_by_evidence",
    "decided_not_sent",
    "abandoned",
    "orphan_found",
]


class AgreementType(models.Model):
    """The inventory (POL-07; P4-D-1: `nda` then `user_agreement` for synthetic P4). Seeded by migration; a change is a
    new migration, never an edit at run time."""

    class Gate(models.TextChoices):
        SIGNING = "signing"
        SIGNING_AND_CUSTODY = "signing_and_custody"  # P4-D-6: fail closed

    key = models.CharField(max_length=40, unique=True)
    order = models.PositiveSmallIntegerField(unique=True)
    required = models.BooleanField(default=True)
    gate = models.CharField(
        max_length=24, choices=Gate.choices, default=Gate.SIGNING_AND_CUSTODY
    )

    def __str__(self):
        return self.key


class AgreementTemplateVersion(models.Model):
    """A frozen Documenso template version; at most one approved version per type is current.

    Approval columns change while draft. Retirement preserves the approval and content (database trigger).
    """

    class Status(models.TextChoices):
        DRAFT = "draft"
        APPROVED = "approved"
        RETIRED = "retired"

    agreement_type = models.ForeignKey(
        AgreementType, on_delete=models.PROTECT, related_name="template_versions"
    )
    version = models.PositiveIntegerField()
    # The template envelope's id (the `envelopeId` that `envelope/use` takes) and the numeric `templateId` that
    # envelopes created from it carry (the reconciliation listing filters on it). Both synthetic in P4; that the two
    # correspond as described is NOT VERIFIED on the installed version (021 section 15).
    provider_template_ref = models.CharField(max_length=64)
    provider_template_number = models.PositiveIntegerField()
    # The template's recipient slots: {"SIGNER:1": <Documenso template recipient id>}. P4-D-3: the applicant is the
    # only required signer until POL-08 names a countersigner.
    recipient_slots = models.JSONField(default=dict)
    pdf_sha256 = models.CharField(
        max_length=64
    )  # the synthetic placeholder PDF's digest
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    approved_by = models.CharField(max_length=200, blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        permissions = [
            (
                "approve_agreement_template",
                "Approve an agreement template version (owner; POL-07)",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["agreement_type", "version"],
                name="agreement_template_one_per_version",
            ),
            models.UniqueConstraint(
                fields=["agreement_type"],
                condition=Q(status="approved"),
                name="agreement_template_one_current",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["draft", "approved", "retired"]),
                name="agreement_template_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(status="draft") | ~Q(approved_by=""),
                name="agreement_template_approved_has_actor",
            ),
        ]


class AgreementInstance(models.Model):
    """One agreement of one type for one application (J-11). `external_key` is the opaque key sent as Documenso's
    `externalId`; it carries no applicant data. A new create after an unknown outcome mints a new key (P4-D-19); every
    key ever used is kept on its `EnvelopeAttempt`."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    application = models.ForeignKey(
        "applications.Application", on_delete=models.PROTECT, related_name="agreements"
    )
    agreement_type = models.ForeignKey(
        AgreementType, on_delete=models.PROTECT, related_name="instances"
    )
    template_version = models.ForeignKey(
        AgreementTemplateVersion, on_delete=models.PROTECT, related_name="instances"
    )
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
    replacement_reason = models.CharField(
        max_length=40, blank=True, default="", db_default=""
    )
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        permissions = [
            (
                "resolve_agreement_integrity",
                "Resolve an agreement-integrity hold: recheck, continue on fresh evidence, or replace (D-43)",
            ),
            (
                "decide_uncertain_agreement",
                "Decide an agreement step whose provider outcome is unknown (decision-maker; P4-D-8)",
            ),
            (
                "manage_agreements",
                "Cancel, reissue or stop an applicant's agreements (decision-maker; P4-D-9, P4-D-18, P4-D-20)",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(issue_status__in=ISSUE), name="agreement_issue_status_valid"
            ),
            models.CheckConstraint(
                condition=Q(signing_status__in=SIGNING),
                name="agreement_signing_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(custody_status__in=CUSTODY),
                name="agreement_custody_status_valid",
            ),
            models.UniqueConstraint(
                fields=["application", "agreement_type"],
                condition=~Q(issue_status__in=NOT_LIVE) & Q(replaced_at__isnull=True),
                name="agreement_one_live_per_type",
            ),
            models.UniqueConstraint(
                fields=["external_key"], name="agreement_external_key_unique"
            ),
            models.CheckConstraint(  # D-43: set together, with the one known reason code
                condition=(
                    Q(replaced_at__isnull=True, replacement_reason="")
                    | Q(
                        replaced_at__isnull=False,
                        replacement_reason="integrity_replaced",
                    )
                ),
                name="agreement_replacement_consistent",
            ),
            models.UniqueConstraint(
                fields=["envelope_id"],
                condition=~Q(envelope_id=""),
                name="agreement_envelope_unique",
            ),
        ]


class AgreementRecipient(models.Model):
    """Who signs, in what role and order (POL-08). Insert-only: a changed recipient is a new instance."""

    class Role(models.TextChoices):
        SIGNER = "SIGNER"
        APPROVER = "APPROVER"
        VIEWER = "VIEWER"
        CC = "CC"

    instance = models.ForeignKey(
        AgreementInstance, on_delete=models.PROTECT, related_name="recipients"
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    signing_order = models.PositiveSmallIntegerField()
    required = models.BooleanField(default=True)
    who = models.CharField(
        max_length=16
    )  # "applicant", or "staff" once POL-08 names a countersigner
    name = models.CharField(max_length=200)
    email = models.CharField(
        max_length=320
    )  # the applicant's verified address at issue

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["instance", "role", "signing_order"],
                name="agreement_recipient_one_per_slot",
            ),
            models.CheckConstraint(
                condition=Q(who__in=["applicant", "staff"]),
                name="agreement_recipient_who_valid",
            ),
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
    instance = models.ForeignKey(
        AgreementInstance, on_delete=models.PROTECT, related_name="attempts"
    )
    step = models.CharField(max_length=16, choices=Step.choices)
    external_key = models.CharField(max_length=64)
    pending_action_id = models.BigIntegerField(null=True, blank=True)
    outcome = models.CharField(
        max_length=24, choices=Outcome.choices, default=Outcome.SENDING
    )
    outcome_code = models.CharField(
        max_length=64, blank=True, default=""
    )  # a reason code or HTTP status, never a body
    envelope_id = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(db_default=Now())
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(step__in=["create", "distribute", "cancel"]),
                name="envelope_attempt_step_valid",
            ),
            models.CheckConstraint(
                condition=Q(outcome__in=ATTEMPT_OUTCOMES),
                name="envelope_attempt_outcome_valid",
            ),
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

    instance = models.ForeignKey(
        AgreementInstance, on_delete=models.PROTECT, related_name="observations"
    )
    application = models.ForeignKey(
        "applications.Application", on_delete=models.PROTECT, related_name="+"
    )
    source = models.CharField(max_length=16, choices=Source.choices)
    event = models.CharField(
        max_length=40, blank=True, default=""
    )  # the webhook event name, or "" for a read
    envelope_status = models.CharField(max_length=16)
    recipients = models.JSONField(
        default=list
    )  # [{"role", "order", "signing_status", "expired"}]
    identity_match = models.BooleanField(
        default=False
    )  # envelope id, externalId and template are ours
    recipients_match = models.BooleanField(
        default=False
    )  # exactly our recipients' addresses and roles
    all_required_signed = models.BooleanField(default=False)
    content_sha256 = models.CharField(
        max_length=64
    )  # of the allowlisted facts, so an exact replay is a no-op
    observed_at = models.DateTimeField(db_default=Now())
    created_txid = models.BigIntegerField(db_default=CurrentTransactionId())

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(source__in=["webhook", "read"]),
                name="observation_source_valid",
            ),
            models.UniqueConstraint(
                fields=["instance", "source", "event", "content_sha256"],
                condition=Q(source="webhook"),
                name="observation_webhook_once",
            ),
        ]
        indexes = [
            models.Index(
                fields=["instance", "observed_at"], name="observation_instance_time"
            )
        ]


class StoredDocument(models.Model):
    """The signed PDF of one envelope item, held by Catalyst (021 section 7; 4B.3). The bytes live outside the database
    and the repository, under a system-generated key; this row records where, the SHA-256 Catalyst computed itself
    (Documenso documents none, and its ETag is a hash of a storage reference, not of the bytes), and the provenance.
    Insert-only for every role. One row per (instance, envelope item)."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    instance = models.ForeignKey(
        AgreementInstance, on_delete=models.PROTECT, related_name="documents"
    )
    application = models.ForeignKey(
        "applications.Application", on_delete=models.PROTECT, related_name="+"
    )
    envelope_id = models.CharField(max_length=64)
    item_id = models.CharField(max_length=64)
    version = models.CharField(max_length=16, default="signed")
    storage_key = models.CharField(
        max_length=80, unique=True
    )  # system-generated; never from input
    sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    observation = models.ForeignKey(
        "ProviderObservation", on_delete=models.PROTECT, related_name="+"
    )  # the read
    stored_at = models.DateTimeField(db_default=Now())

    class Meta:
        permissions = [
            (
                "retrieve_agreement_document",
                "Retrieve a signed agreement document (decision-maker; P4-D-16)",
            ),
            (
                "operate_agreements",
                "Retry agreement custody and request fresh reads (operator)",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["instance", "item_id"], name="stored_document_one_per_item"
            ),
            models.CheckConstraint(
                condition=Q(version="signed"), name="stored_document_signed_only"
            ),
        ]


class CustodyEnvelope(models.Model):
    """9kg.34: how one stored document is sealed at rest (agreements.keystore). The file named `storage_key` holds the
    AES-256-GCM sealed bytes under the data key `key_ref`; `cipher_sha256` and `cipher_size` are those bytes' digest and
    size, so the backup and the restore verify a sealed file without any key. `StoredDocument.sha256` stays the
    plaintext's hash and is checked after opening. For a document sealed when it was stored, `storage_key` is the
    document's own; a migrated one (`migrated`) has a new file and its plaintext file is removed. No key material is
    here: the wrapped key lives outside the database and the backup, so a restore can never bring it back. Insert-only
    for every role, like the document itself. Every column is non-personal (random references, digests, sizes).

    Rules (data review of PR #102, K5): one envelope per document; no repair or re-seal until wrapping-key rotation is
    built (a follow-up); `wrapping_key_id` is the wrapping key's id at seal time; `migrated=False` means the document
    was sealed when stored, so `storage_key` equals the document's own."""

    document = models.OneToOneField(
        StoredDocument, on_delete=models.PROTECT, related_name="envelope"
    )
    storage_key = models.CharField(
        max_length=80, unique=True
    )  # the sealed file; system-generated
    scheme = models.CharField(max_length=32)
    key_ref = models.CharField(max_length=32, unique=True)
    wrapping_key_id = models.CharField(
        max_length=16
    )  # the wrapping key's id at seal time (never updated)
    cipher_sha256 = models.CharField(max_length=64)
    cipher_size = models.PositiveIntegerField()
    migrated = models.BooleanField(default=False)
    sealed_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(scheme="aes-256-gcm/v1"),
                name="custody_envelope_scheme_known",
            ),
            models.CheckConstraint(
                condition=Q(cipher_sha256__regex=r"^[0-9a-f]{64}$"),
                name="custody_envelope_cipher_sha256_hex",
            ),
            models.CheckConstraint(
                condition=Q(key_ref__regex=r"^[0-9a-f]{32}$"),
                name="custody_envelope_key_ref_hex",
            ),
        ]


class DocumentAccess(models.Model):
    """Every retrieval attempt, granted or not (021 section 7). Written and committed before any byte is released;
    a denied attempt records only the reference asked for, so it reveals nothing about whether a document exists.
    Append-only for every role."""

    class Outcome(models.TextChoices):
        GRANTED = "granted"
        DENIED = "denied"
        REFUSED_INTEGRITY = "refused_integrity"  # the stored bytes no longer match

    document = models.ForeignKey(
        StoredDocument,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="accesses",
    )
    requested_ref = models.CharField(max_length=64)
    actor_ref = models.CharField(max_length=200)
    outcome = models.CharField(max_length=24, choices=Outcome.choices)
    reason = models.CharField(
        max_length=300, blank=True, default=""
    )  # the stated purpose, cleaned and capped
    at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(outcome__in=["granted", "denied", "refused_integrity"]),
                name="document_access_outcome_valid",
            )
        ]


class AgreementDetailsVersion(models.Model):
    """POL-18 required details for one agreement type, as staff recorded them from what the applicant provided (an
    email is never adopted as an answer by itself) and then explicitly confirmed (021 section 8; 4B.3). Versioned:
    a change is a new version; a confirmed version is frozen. The production field list is undecided (POL-18): only
    synthetic fields exist.

    bgl.8 (034 row 32): a version may instead come from the signed envelope itself (`source` envelope, `instance` the
    agreement it was read from; agreements.details), confirmed by the applicant's signature. A staff correction (D-46)
    is a later `staff` version; the envelope version stays as read."""

    class Status(models.TextChoices):
        DRAFT = "draft"
        CONFIRMED = "confirmed"

    class Source(models.TextChoices):
        STAFF = "staff"
        ENVELOPE = "envelope"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    application = models.ForeignKey(
        "applications.Application",
        on_delete=models.PROTECT,
        related_name="agreement_details",
    )
    agreement_type = models.ForeignKey(
        AgreementType, on_delete=models.PROTECT, related_name="+"
    )
    version = models.PositiveIntegerField()
    values = models.JSONField(default=dict)
    values_sha256 = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.DRAFT
    )
    recorded_by = models.CharField(max_length=200)
    confirmed_by = models.CharField(max_length=200, blank=True, default="")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(
        max_length=16, choices=Source.choices, default=Source.STAFF, db_default="staff"
    )
    instance = models.ForeignKey(
        AgreementInstance,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="details_versions",
    )  # the envelope the values were read from
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        permissions = [
            (
                "confirm_required_details",
                "Record and confirm the details an agreement needs (POL-18)",
            )
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["application", "agreement_type", "version"],
                name="details_one_per_version",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["draft", "confirmed"]),
                name="details_status_valid",
            ),
            models.CheckConstraint(
                condition=Q(status="draft") | ~Q(confirmed_by=""),
                name="details_confirmed_has_actor",
            ),
            models.CheckConstraint(
                condition=Q(source__in=["staff", "envelope"]),
                name="details_source_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(source="staff", instance__isnull=True)
                    | Q(source="envelope", instance__isnull=False)
                ),
                name="details_envelope_names_its_instance",
            ),
            models.UniqueConstraint(
                fields=["instance"],
                condition=Q(source="envelope"),
                name="details_one_envelope_read_per_instance",
            ),
        ]


class CountersignClaim(models.Model):
    """bgl.9 (034 row 30; first-generation decision 12, owner YES 2026-10-31): the single-writer claim on one envelope
    for the automated company countersignature (agreements.countersign). One row per envelope, unique, so two workers or
    a second consumer cannot both sign it. The database refuses a claim on an envelope Catalyst v2 did not create: the
    external key must carry v2's `ag_` prefix (the first generation's `onb_` envelopes are never v2's to sign).

    `state`: `signing` (taken; the exchange may have started, so the next attempt reads first and never signs blindly), `signed` (a fresh read showed the company recipient signed), `failed` (the last attempt failed;
    a retry is due), `handed_off` (retries ran for the hand-off window: the owner countersigns by hand). No token, link,
    name or address is kept."""

    class State(models.TextChoices):
        SIGNING = "signing"
        SIGNED = "signed"
        FAILED = "failed"
        HANDED_OFF = "handed_off"

    instance = models.ForeignKey(
        AgreementInstance, on_delete=models.PROTECT, related_name="countersign_claims"
    )
    envelope_id = models.CharField(max_length=64, unique=True)
    external_key = models.CharField(max_length=64)
    holder = models.CharField(max_length=40)  # a code: the writer that holds the claim
    action_id = models.BigIntegerField(
        null=True, blank=True
    )  # the pending action now working under the claim
    state = models.CharField(
        max_length=16, choices=State.choices, default=State.SIGNING
    )
    attempts = models.PositiveIntegerField(default=0)
    last_code = models.CharField(
        max_length=64, blank=True, default=""
    )  # a reason code, never a provider body
    first_failure_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(state__in=["signing", "signed", "failed", "handed_off"]),
                name="countersign_claim_state_valid",
            ),
            models.CheckConstraint(
                condition=Q(external_key__startswith="ag_") & ~Q(envelope_id=""),
                name="countersign_claim_v2_envelope_only",
            ),
        ]
