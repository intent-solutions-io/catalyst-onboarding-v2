"""P5 provisioning records (023 sections 4 and 11; D-47). Synthetic only: the adapter is a local fake, no provider key
exists, and every address is in a configured `.test` domain.

- `AddressReservation`: one live reservation per normalized address. System and role addresses are refused by the
  naming rules before a row is written.
- `ProvisioningRequest`: one live request per application. Its identity, method, limits and the prerequisite digest
  are fixed at insert; approval is written once, against the digest of what the approver saw. A changed prerequisite
  supersedes the request; it never mutates it.
- `ProvisioningAttempt`: each exchange with the mail host, committed `sending` before the call (a "never twice"
  record, as P4's envelope attempts).
- `ProvisioningEvidence`: what established a mailbox: the adapter's allowlisted read, or the checklist creator's
  record and a different named verifier's attestation. Append-only.
"""

import uuid

from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower, Now

LIVE_REQUEST = ("awaiting_approval", "approved", "create_pending", "create_uncertain", "found_by_evidence", "created",
                "verify_uncertain", "verified", "setup_pending", "setup_complete", "stopping")
REQUEST_STATUSES = (*LIVE_REQUEST, "active", "conflict", "failed_needs_staff", "superseded", "stopped",
                    "recovered_after_stop")


class AddressReservation(models.Model):
    class Basis(models.TextChoices):
        NAMING_RULE = "naming_rule"
        REVIEWED_EXCEPTION = "reviewed_exception"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="reservations")
    local_part = models.CharField(max_length=64)
    domain = models.CharField(max_length=253)
    basis = models.CharField(max_length=24, choices=Basis.choices)
    reviewed_by = models.CharField(max_length=200, blank=True, default="")
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("local_part"), Lower("domain"), condition=Q(released_at__isnull=True),
                                    name="reservation_live_address_unique"),
            models.CheckConstraint(condition=Q(basis__in=["naming_rule", "reviewed_exception"]),
                                   name="reservation_basis_valid"),
            models.CheckConstraint(condition=Q(basis="naming_rule") | ~Q(reviewed_by=""),
                                   name="reservation_exception_reviewed"),
            models.CheckConstraint(condition=Q(local_part__regex=r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$")
                                   & ~Q(local_part__contains=".."), name="reservation_local_part_safe"),
        ]

    @property
    def address(self) -> str:
        return f"{self.local_part}@{self.domain}"


class ProvisioningRequest(models.Model):
    class Method(models.TextChoices):
        API = "api"
        CHECKLIST = "checklist"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT,
                                    related_name="provisioning_requests")
    reservation = models.ForeignKey(AddressReservation, on_delete=models.PROTECT, related_name="requests")
    method = models.CharField(max_length=16, choices=Method.choices)
    quota_mb = models.PositiveIntegerField()
    send_limit = models.PositiveIntegerField()
    prerequisite_digest = models.CharField(max_length=64)
    approval_digest = models.CharField(max_length=64)  # what the approver must confirm: address, limits, method, digest
    status = models.CharField(max_length=24, default="awaiting_approval")
    approved_by = models.CharField(max_length=200, blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    stop_requested_at = models.DateTimeField(null=True, blank=True)  # 023 11.5: orthogonal to the status
    superseded_by = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="supersedes")
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        permissions = [
            ("approve_provisioning", "Approve the exact mailbox for an applicant (P5-D-3; named grant only)"),
            ("operate_provisioning", "Record checklist provisioning, attest verification and decide conflicts"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["application"], condition=Q(status__in=LIVE_REQUEST),
                                    name="provisioning_one_live_request"),
            models.CheckConstraint(condition=Q(status__in=REQUEST_STATUSES), name="provisioning_status_valid"),
            models.CheckConstraint(condition=Q(method__in=["api", "checklist"]), name="provisioning_method_valid"),
            models.CheckConstraint(condition=Q(quota_mb__gte=1), name="provisioning_quota_positive"),  # never unlimited
            models.CheckConstraint(condition=Q(send_limit__gte=1) & Q(send_limit__lte=9600),
                                   name="provisioning_send_limit_range"),
            models.CheckConstraint(
                condition=(Q(approved_by="") & Q(approved_at__isnull=True)) | (~Q(approved_by="") & Q(approved_at__isnull=False)),
                name="provisioning_approval_consistent"),
            models.CheckConstraint(condition=Q(status__in=["awaiting_approval", "superseded", "stopped"])
                                   | ~Q(approved_by=""), name="provisioning_progress_needs_approval"),
            models.CheckConstraint(condition=~Q(superseded_by=F("id")), name="provisioning_not_self_superseding"),
        ]


class ProvisioningAttempt(models.Model):
    class Step(models.TextChoices):
        CREATE = "create"
        READ = "read"

    class Outcome(models.TextChoices):
        SENDING = "sending"
        SUCCEEDED = "succeeded"
        ABSENT = "absent"  # an authoritative read found no such mailbox
        CONFLICT = "conflict"
        REJECTED = "rejected"
        UNKNOWN = "unknown"
        FOUND_BY_EVIDENCE = "found_by_evidence"
        NOT_CREATED = "not_created"  # an unknown create later read as absent

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    request = models.ForeignKey(ProvisioningRequest, on_delete=models.PROTECT, related_name="attempts")
    step = models.CharField(max_length=16, choices=Step.choices)
    series = models.PositiveIntegerField(default=0)
    outcome = models.CharField(max_length=24, choices=Outcome.choices, default=Outcome.SENDING)
    code = models.CharField(max_length=64, blank=True, default="")
    absent_before = models.BooleanField(default=False)  # 023 11.3: an authoritative absent read in the same claim
    started_at = models.DateTimeField(db_default=Now())
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(step__in=["create", "read"]), name="provisioning_attempt_step_valid"),
            models.CheckConstraint(condition=Q(outcome__in=["sending", "succeeded", "absent", "conflict", "rejected",
                                                             "unknown", "found_by_evidence", "not_created"]),
                                   name="provisioning_attempt_outcome_valid"),
            models.UniqueConstraint(fields=["request"], condition=Q(step="create", outcome__in=["sending", "unknown"]),
                                    name="provisioning_one_open_create"),
        ]


class ProvisioningEvidence(models.Model):
    class Kind(models.TextChoices):
        ADAPTER_READ = "adapter_read"
        CHECKLIST_CREATED = "checklist_created"
        CHECKLIST_ATTESTED = "checklist_attested"
        STAFF_CONFIRMED = "staff_confirmed"  # a found_by_evidence outcome confirmed by staff (023 11.3)

    request = models.ForeignKey(ProvisioningRequest, on_delete=models.PROTECT, related_name="evidence")
    kind = models.CharField(max_length=24, choices=Kind.choices)
    actor_ref = models.CharField(max_length=200)
    facts = models.JSONField(default=dict)  # allowlisted: name, quota, limit, suspended; never a credential
    note = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["adapter_read", "checklist_created", "checklist_attested",
                                                         "staff_confirmed"]), name="provisioning_evidence_kind_valid"),
            models.CheckConstraint(condition=~Q(actor_ref=""), name="provisioning_evidence_has_actor"),
        ]


SETUP_STATES = ("invitation_pending", "invitation_sending", "invited", "invitation_uncertain", "invitation_failed",
                "presented", "set_pending", "completed", "set_uncertain", "expired", "cancelled", "superseded")
LIVE_SETUP = ("invitation_pending", "invitation_sending", "invited", "presented", "set_pending")


class CredentialSetup(models.Model):
    """023 sections 11.2, 11.5 and 11.7 (5B.2): one set-your-own-password invitation series for a verified mailbox.

    The token is minted by the worker at send time and only its SHA-256 is stored, once. The recipient is the
    verified external address at the moment the series was opened, and is fixed. The chosen password is never stored
    anywhere: it travels only in the POST and the in-process call to the credential operation.
    """

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    request = models.ForeignKey(ProvisioningRequest, on_delete=models.PROTECT, related_name="setups")
    series = models.PositiveIntegerField()
    recipient = models.CharField(max_length=320)
    token_sha256 = models.CharField(max_length=64, blank=True, default="")
    state = models.CharField(max_length=24, default="invitation_pending")
    expires_at = models.DateTimeField(null=True, blank=True)
    set_attempts = models.PositiveIntegerField(default=0)
    set_started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["request", "series"], name="setup_series_unique"),
            models.UniqueConstraint(fields=["request"], condition=Q(state__in=LIVE_SETUP), name="setup_one_live_per_request"),
            models.UniqueConstraint(fields=["token_sha256"], condition=~Q(token_sha256=""), name="setup_token_unique"),
            models.CheckConstraint(condition=Q(state__in=SETUP_STATES), name="setup_state_valid"),
            models.CheckConstraint(condition=~Q(state__in=["invited", "presented", "set_pending", "completed"])
                                   | (~Q(token_sha256="") & Q(expires_at__isnull=False)), name="setup_invited_has_token"),
            models.CheckConstraint(condition=Q(state="completed") | Q(completed_at__isnull=True),
                                   name="setup_completed_consistent"),
        ]

