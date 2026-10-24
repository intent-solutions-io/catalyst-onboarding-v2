"""P3 evidence records (018 sections 2 and 3; owner decision D-34; task 3B.1). Synthetic only.

Four records stay separate (018 section 1): the **claim** lives in the adopted `SubmissionVersion`
(`submitted_fields["claims"]`); an **observation** is an `EvidenceCapture`; the model assessment (3B.2) and the
authorized decision (3B.4) are later tables. None silently becomes another.

- `EvidenceSource`: the owner-approved allow-list (POL-03). Versioned: an approved row is immutable for the
  application role, and a changed definition is a new version that needs approval. `fixture_only` sources exist
  only for synthetic runs and are refused outside `test` and `staging` (`assessments.fetch`, `config.guards.synthetic`).
- `EvidenceItem`: one slot per claimed URL and approved source for the adopted version; its status is the only
  mutable part (`pending` to `fetched`, `unavailable` or `refused`).
- `EvidenceCapture`: the immutable observation of one successful fetch: what was found, where and when, a bounded
  derivative and digests (never raw bytes), and what it cannot prove. Append-only by trigger (ADR-14).
"""

import uuid

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now

SOURCE_KINDS = ["work_sample_page", "credential_verification"]
ITEM_STATUSES = ["pending", "fetched", "unavailable", "refused"]
CAPTURE_OUTCOMES = ["found", "found_but_inconclusive", "not_found"]

# What an observation of each kind can never establish (018 section 1), stored with every capture.
CANNOT_PROVE = {
    "work_sample_page": "A work page shows that the work exists and what it says; it cannot prove who wrote it or "
                        "what the applicant personally contributed.",
    "credential_verification": "An issuer's page can show that a credential with this identifier exists; it cannot "
                               "prove that the person presenting it is the holder.",
}


class EvidenceSource(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft"
        APPROVED = "approved"
        RETIRED = "retired"

    class OnUnavailable(models.TextChoices):
        CONTINUE = "continue"
        STAFF = "staff"

    key = models.CharField(max_length=64)
    version = models.PositiveIntegerField()
    kind = models.CharField(max_length=32)
    host = models.CharField(max_length=253)  # exact lower-case punycode; no wildcard
    port = models.PositiveIntegerField(default=443)
    path_prefix = models.CharField(max_length=200, default="/")
    redirect_hosts = models.JSONField(default=list)
    content_types = models.JSONField(default=list)
    max_bytes = models.PositiveIntegerField()
    deadline_seconds = models.PositiveIntegerField()
    required = models.BooleanField(default=False)
    on_unavailable = models.CharField(max_length=16, default=OnUnavailable.STAFF)
    fixture_only = models.BooleanField(default=False)
    definition_sha256 = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.CharField(max_length=200, blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        permissions = [("approve_evidence_source", "Approve an evidence source version (owner, POL-03)")]
        constraints = [
            models.UniqueConstraint(fields=["key", "version"], name="evidence_source_version_unique"),
            models.UniqueConstraint(fields=["key"], condition=Q(status="approved"), name="evidence_source_one_approved_version"),
            models.CheckConstraint(condition=Q(version__gte=1), name="evidence_source_version_positive"),
            models.CheckConstraint(condition=Q(kind__in=SOURCE_KINDS), name="evidence_source_kind_valid"),
            models.CheckConstraint(condition=Q(status__in=["draft", "approved", "retired"]), name="evidence_source_status_valid"),
            models.CheckConstraint(condition=Q(on_unavailable__in=["continue", "staff"]), name="evidence_source_on_unavailable_valid"),
            models.CheckConstraint(condition=Q(port__gte=1, port__lte=65535), name="evidence_source_port_valid"),
            models.CheckConstraint(condition=~Q(status="approved") | (~Q(approved_by="") & Q(approved_at__isnull=False)),
                                   name="evidence_source_approved_has_approver"),
        ]


class EvidenceItem(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        FETCHED = "fetched"
        UNAVAILABLE = "unavailable"
        REFUSED = "refused"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="evidence_items")
    adopted_version = models.ForeignKey("applications.SubmissionVersion", on_delete=models.PROTECT, related_name="evidence_items")
    source = models.ForeignKey(EvidenceSource, on_delete=models.PROTECT, null=True, blank=True, related_name="items")
    claim_ref = models.CharField(max_length=32)  # "work:1", "credential:2": which claim this observes
    request_url = models.CharField(max_length=2048)
    request_url_sha256 = models.CharField(max_length=64)
    round = models.PositiveIntegerField(default=1)  # a staff re-fetch is a new slot (round n+1); the old one stays
    required = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    reason_code = models.CharField(max_length=64, blank=True, default="")
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        permissions = [
            ("review_evidence", "Read claims and evidence observations (assessment operators and decision-makers, P3-D-14)"),
            ("operate_evidence", "Re-fetch evidence or proceed without an unavailable item (assessment operators)"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["application", "adopted_version", "claim_ref", "round"], name="evidence_item_one_per_claim_round"),
            models.CheckConstraint(condition=Q(status__in=ITEM_STATUSES), name="evidence_item_status_valid"),
            models.CheckConstraint(condition=Q(round__gte=1), name="evidence_item_round_positive"),
            models.CheckConstraint(condition=Q(status="pending") | Q(finished_at__isnull=False), name="evidence_item_terminal_has_time"),
            models.UniqueConstraint(fields=["id", "application"], name="evidence_item_id_application_unique"),
        ]
        indexes = [models.Index(fields=["application"], condition=Q(status="pending"), name="evidence_item_pending")]


class EvidenceCapture(models.Model):
    item = models.ForeignKey(EvidenceItem, on_delete=models.PROTECT, related_name="captures")
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="evidence_captures")
    source = models.ForeignKey(EvidenceSource, on_delete=models.PROTECT, related_name="captures")  # the exact version
    attempt_number = models.PositiveIntegerField()
    final_url = models.CharField(max_length=2048)
    http_status = models.PositiveIntegerField()
    content_type = models.CharField(max_length=200, blank=True, default="")
    revision_marker = models.CharField(max_length=200, blank=True, default="")  # ETag or Last-Modified, if any
    byte_length = models.PositiveIntegerField()
    truncated = models.BooleanField(default=False)
    response_sha256 = models.CharField(max_length=64)  # of the bytes read
    derived_text = models.TextField(blank=True, default="")
    derived_sha256 = models.CharField(max_length=64)
    derivation_version = models.PositiveIntegerField()
    is_derivative = models.BooleanField(default=True)
    outcome = models.CharField(max_length=32)
    cannot_prove = models.TextField()
    injection_markers = models.JSONField(default=list)
    peer_ip = models.GenericIPAddressField()
    fetched_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["item", "attempt_number"], name="evidence_capture_one_per_attempt"),
            models.CheckConstraint(condition=Q(is_derivative=True), name="evidence_capture_is_derivative"),
            models.CheckConstraint(condition=Q(outcome__in=CAPTURE_OUTCOMES), name="evidence_capture_outcome_valid"),
            models.UniqueConstraint(fields=["id", "application"], name="evidence_capture_id_application_unique"),
        ]


RUN_STATUSES = ["queued", "reserved", "succeeded", "invalid_output", "failed", "capped", "refused", "abandoned"]


class AssessmentRun(models.Model):
    """One bounded assessment of one frozen snapshot (018 5.1, 6; task 3B.2). Advisory: nothing in the output
    chooses a stage, sends anything or decides. The result columns are written once, when the run ends."""

    class Status(models.TextChoices):
        QUEUED = "queued"
        RESERVED = "reserved"  # an invocation is recorded and the model may have been called
        SUCCEEDED = "succeeded"
        INVALID_OUTPUT = "invalid_output"
        FAILED = "failed"
        CAPPED = "capped"
        REFUSED = "refused"
        ABANDONED = "abandoned"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="assessment_runs")
    adopted_version = models.ForeignKey("applications.SubmissionVersion", on_delete=models.PROTECT, related_name="assessment_runs")
    round = models.PositiveIntegerField(default=1)
    trigger = models.CharField(max_length=32)  # evidence_complete, activation, staff_rerun
    snapshot = models.JSONField()
    snapshot_sha256 = models.CharField(max_length=64)
    prompt_pack = models.CharField(max_length=64)
    prompt_pack_sha256 = models.CharField(max_length=64)
    rubric_version = models.PositiveIntegerField()
    schema_version = models.CharField(max_length=8)
    provider = models.CharField(max_length=32, blank=True, default="")
    model_id = models.CharField(max_length=100, blank=True, default="")
    output_mode = models.CharField(max_length=16, blank=True, default="")
    library_version = models.CharField(max_length=32, blank=True, default="")
    request_sha256 = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    error_code = models.CharField(max_length=64, blank=True, default="")
    output = models.JSONField(null=True, blank=True)
    output_sha256 = models.CharField(max_length=64, blank=True, default="")
    validation_codes = models.JSONField(default=list)
    flags = models.JSONField(default=list)
    requests_used = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(db_default=Now())
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [("rerun_assessment", "Request a new assessment run (assessment operators)")]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=RUN_STATUSES), name="assessment_run_status_valid"),
            models.CheckConstraint(condition=Q(round__gte=1), name="assessment_run_round_positive"),
            # One succeeded run per snapshot; one run in flight per application (018 6).
            models.UniqueConstraint(fields=["application", "snapshot_sha256"], condition=Q(status="succeeded"),
                                    name="assessment_run_one_success_per_snapshot"),
            models.UniqueConstraint(fields=["application"], condition=Q(status__in=["queued", "reserved"]),
                                    name="assessment_run_one_in_flight"),
            models.CheckConstraint(condition=~Q(status="succeeded") | Q(output__isnull=False), name="assessment_run_success_has_output"),
            models.CheckConstraint(condition=Q(status__in=["queued", "reserved"]) | Q(finished_at__isnull=False),
                                   name="assessment_run_terminal_has_time"),
        ]


class AssessmentInvocation(models.Model):
    """Recorded before any model request (018 6): if the worker dies after the provider may have processed or
    billed the call, the reservation still counts. Never refunded once recorded."""

    run = models.ForeignKey(AssessmentRun, on_delete=models.PROTECT, related_name="invocations")
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="assessment_invocations")
    snapshot_sha256 = models.CharField(max_length=64)
    attempt = models.PositiveIntegerField()
    reserved_requests = models.PositiveIntegerField()
    reserved_tokens = models.PositiveIntegerField()
    used_tokens = models.PositiveIntegerField(null=True, blank=True)  # known only when the call returned usage
    status = models.CharField(max_length=16, default="started")  # started, completed, abandoned
    started_at = models.DateTimeField(db_default=Now())
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["run", "attempt"], name="assessment_invocation_one_per_attempt"),
            models.CheckConstraint(condition=Q(status__in=["started", "completed", "abandoned"]), name="assessment_invocation_status_valid"),
        ]


class CurrentTransactionId(models.Func):
    template = "pg_current_xact_id()::text::bigint"
    output_field = models.BigIntegerField()


class QualificationDecision(models.Model):
    """The authorized human decision (018 section 7, J-10; P3 3B.4; D-34 P3-D-9 to P3-D-11, D-35). Insert-only and
    append-only for every role (ADR-14). It names exactly what it relied on: the adopted version, the run (none for
    a recorded human-only assessment, the D-35 amendment of P3-D-10), the snapshot digest, the digest of what the
    decision-maker saw, and the selection policy. Capability and strength of evidence are recorded separately per
    criterion (019 section 5). A model never writes one."""

    class Outcome(models.TextChoices):
        ADMIT = "admit"
        DECLINE = "decline"
        HOLD = "hold"

    class Basis(models.TextChoices):
        MODEL_ASSISTED = "model_assisted"  # a valid succeeded run informed the decision
        HUMAN_ONLY = "human_only"  # model advice unavailable or suspended (D-35)

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="qualification_decisions")
    adopted_version = models.ForeignKey("applications.SubmissionVersion", on_delete=models.PROTECT, related_name="+")
    run = models.ForeignKey(AssessmentRun, on_delete=models.PROTECT, null=True, blank=True, related_name="decisions")
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    basis = models.CharField(max_length=16, choices=Basis.choices)
    human_only_reason = models.CharField(max_length=300, blank=True, default="")
    # oc4.12: the structured reason for a human-only assessment (decisions.HUMAN_ONLY_CODES), never free text alone;
    # `advice_suspended` cites the suspension record in `decision_inputs`.
    human_only_code = models.CharField(max_length=40, blank=True, default="", db_default="")
    reason_code = models.CharField(max_length=40)
    reason_text = models.TextField(blank=True, default="")
    rationale = models.JSONField(default=dict)  # {criterion: {capability, evidence_strength, note}}
    snapshot_sha256 = models.CharField(max_length=64)
    decision_digest = models.CharField(max_length=64)  # what the decision-maker saw (snapshot, questions, run)
    policy_ref = models.CharField(max_length=100)  # the selection policy, or the synthetic rubric until one exists
    # oc4.12 (oc4.10 item 3): the pack and rubric relied on, recorded whatever the policy reference says.
    prompt_pack = models.CharField(max_length=64, blank=True, default="", db_default="")
    prompt_pack_sha256 = models.CharField(max_length=64, blank=True, default="", db_default="")
    rubric_version = models.PositiveIntegerField(default=0, db_default=0)
    # oc4.12 (oc4.10 item 2): everything the decision digest binds, kept with the decision (decisions.decision_state).
    decision_inputs = models.JSONField(default=dict, db_default="{}")
    actor_ref = models.CharField(max_length=200)
    second_actor_ref = models.CharField(max_length=200, blank=True, default="")  # P3-D-9: optional, not required
    created_at = models.DateTimeField(db_default=Now())
    # The top-level transaction that inserted the row (the same inside a savepoint); the database backstop
    # compares it with the current transaction (migration 0008, TEST-P3-52).
    created_txid = models.BigIntegerField(db_default=CurrentTransactionId())

    class Meta:
        permissions = [("record_qualification_decision", "Record an admit, decline or hold decision (POL-05; granted explicitly)")]
        constraints = [
            models.CheckConstraint(condition=Q(outcome__in=["admit", "decline", "hold"]), name="decision_outcome_valid"),
            models.CheckConstraint(condition=Q(basis__in=["model_assisted", "human_only"]), name="decision_basis_valid"),
            models.CheckConstraint(condition=(Q(basis="model_assisted") & Q(run__isnull=False)) |
                                   (Q(basis="human_only") & Q(run__isnull=True) & ~Q(human_only_reason="")),
                                   name="decision_basis_matches_run"),
            models.UniqueConstraint(fields=["application"], condition=Q(outcome__in=["admit", "decline"]),
                                    name="decision_one_final_per_application"),
            models.CheckConstraint(condition=Q(basis="model_assisted") | ~Q(human_only_code=""),
                                   name="decision_human_only_has_code"),  # oc4.12: a structured reason, never text alone
        ]


APPROVAL_REF_PATTERN = r"^[a-z0-9_.:-]{3,64}$"


class ModelUseApproval(models.Model):
    """oc4.9: the owner's recorded approval of live model use for one purpose (the assessment, or the reply
    interpreter; both share the checked-run path and the daily budget). Written only by the owner-run
    `approve_model_use` command (the migration owner role); the application role reads it and nothing else, and no
    web path creates one. Append-only for every role (migration 0011): a revocation, or a changed term, is a new row.

    `terms` is everything the approval names, as the command computed it from the code and settings in force: the
    provider and model id, the exact field list that may leave Catalyst, the prompt pack, its digest, the rubric and
    output schema versions, every budget, the request timeout and the repair limit. `terms_sha256` is its digest.
    Before any live request, `assessments.approval.require` recomputes the terms for the call at hand and refuses
    unless the latest row for the purpose is an approval with the same digest: a changed version, budget or field
    list (a stale approval) refuses, and so does a run frozen under another pack (a stale snapshot)."""

    class Action(models.TextChoices):
        APPROVE = "approve"
        REVOKE = "revoke"

    purpose = models.CharField(max_length=20)
    action = models.CharField(max_length=8, choices=Action.choices)
    provider = models.CharField(max_length=40)
    model_id = models.CharField(max_length=100)
    terms = models.JSONField(default=dict)
    terms_sha256 = models.CharField(max_length=64)
    approval_ref = models.CharField(max_length=200)
    actor_ref = models.CharField(max_length=200)
    recorded_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(purpose__in=["assessment", "interpretation"]), name="model_use_purpose_valid"),
            models.CheckConstraint(condition=Q(action__in=["approve", "revoke"]), name="model_use_action_valid"),
            # A decision code, never free text: lowercase letters, digits and _ . : - (3 to 64 characters).
            models.CheckConstraint(condition=Q(approval_ref__regex=APPROVAL_REF_PATTERN), name="model_use_approval_ref_is_a_code"),
        ]
