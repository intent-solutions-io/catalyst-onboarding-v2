"""Correspondence records (005 S1.4; 016 sections 3.1 to 3.3 and 3.8, P2 task 2B.1).

S1: `OutboundMessage`, one record per send attempt, written by the send handler inside the lease-fenced
result transaction (`correspondence/verification.py`).

P2 (owner decisions D-27 to D-31; synthetic only):
- `MessageTemplate` and `MessageTemplateVersion`: owner-approved, immutable once approved (A1).
- `ApprovedMessage`: the one canonical, frozen record of a logical send, committed at enqueue and
  separate from its attempts (A-11). A worker rebuilds what to send from it alone.
- `ApprovedMessageQuestion`: which questions a message carried.
- `Question`: the minimal question needed by outbound sends (A-1); reply handling arrives in 2B.3.
- `StaffItem` and `StaffItemResolution`: the staff exception queue with an immutable resolution record
  that exists with or without an application (A-2).

Grants (correspondence migration 0004) make every identity and content column INSERT-only for the
application role; no role may delete these rows.
"""

import uuid

from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Now

# Variable names that carry a link or token. A template using any of them is secret-bearing (016 3.1):
# its rendered body is never stored or shown to staff.
LINK_VARIABLES = ["link", "confirmation_link", "token", "url"]

OUTBOUND_STATUSES = ["rendered", "accepted", "failed", "sending", "accepted_by_server", "rejected_temporary",
                     "rejected_permanent", "transport_blocked", "unknown"]
QUESTION_STATUSES = ["open", "reply_pending", "partially_answered", "satisfied", "withdrawn"]
DISPOSITIONS = ["active", "accepted_by_server", "accepted_by_evidence", "rejected_permanent", "retries_exhausted",
                "transport_blocked", "operator_abandoned", "superseded"]


class OutboundMessage(models.Model):
    """One send attempt. S1 rows use `accepted` and `failed`; P2 rows use the 016 A3 outcome classes and
    belong to an `ApprovedMessage`, numbered per message independently of the ledger's attempt count."""

    class Status(models.TextChoices):
        RENDERED = "rendered"
        ACCEPTED = "accepted"  # S1: accepted by the mail backend; not proof of delivery
        FAILED = "failed"  # S1
        SENDING = "sending"  # P2: recorded before the SMTP exchange; left behind by a crash
        ACCEPTED_BY_SERVER = "accepted_by_server"  # a 250 after the end of data; never "delivered"
        REJECTED_TEMPORARY = "rejected_temporary"
        REJECTED_PERMANENT = "rejected_permanent"
        TRANSPORT_BLOCKED = "transport_blocked"  # a channel fault: not a verdict on the message
        UNKNOWN = "unknown"  # the end-of-data marker was sent and no reply was observed

    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="outbound_messages")
    pending_action = models.ForeignKey("workflow.PendingAction", on_delete=models.PROTECT, related_name="outbound_messages")
    attempt_number = models.PositiveIntegerField()
    template_key = models.CharField(max_length=64)
    template_version = models.CharField(max_length=32)
    recipient = models.CharField(max_length=320)
    message_id = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=24, choices=Status.choices)
    sent_at = models.DateTimeField(null=True, blank=True)
    # P2 (016 3.2)
    approved_message = models.ForeignKey("ApprovedMessage", on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="attempts")
    attempt_series = models.PositiveIntegerField(db_default=0)  # database defaults keep S1 inserts valid
    protocol_phase_reached = models.CharField(max_length=16, blank=True, db_default="")
    smtp_reply_code = models.PositiveIntegerField(null=True, blank=True)  # the code only; reply text is never stored
    rendered_sha256 = models.CharField(max_length=64, blank=True, db_default="")
    server_accepted_at = models.DateTimeField(null=True, blank=True)
    filed_copy_state = models.CharField(max_length=16, blank=True, db_default="none")  # 016 A4 (2B.2)
    created_at = models.DateTimeField(db_default=Now())  # when the attempt row was written (G3 age)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["pending_action", "attempt_number"], name="outbound_unique_per_attempt"),
            models.CheckConstraint(condition=Q(attempt_number__gte=1), name="outbound_attempt_positive"),
            models.CheckConstraint(condition=Q(status__in=OUTBOUND_STATUSES), name="outbound_status_valid"),
            models.UniqueConstraint(fields=["approved_message", "attempt_number"], condition=Q(approved_message__isnull=False),
                                    name="outbound_attempt_number_per_message"),
        ]


class MessageTemplate(models.Model):
    key = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=200)
    secret_bearing = models.BooleanField(default=False)
    created_at = models.DateTimeField(db_default=Now())


class MessageTemplateVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft"
        APPROVED = "approved"
        RETIRED = "retired"

    template = models.ForeignKey(MessageTemplate, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    subject = models.CharField(max_length=200)  # static: no variables in subjects (016 A1)
    body_text = models.TextField()
    variables = models.JSONField(default=list)  # the allow-list of $names the body may use
    # Copied from the template at creation (code keeps them equal) so the database can enforce 3.1's rule.
    secret_bearing = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.CharField(max_length=200, blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    content_sha256 = models.CharField(max_length=64)
    synthetic = models.BooleanField(default=True)  # placeholder wording; real wording needs POL-06 and POL-17
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        permissions = [("approve_template_version", "Approve a message template version (owner only, D-29)")]
        constraints = [
            models.UniqueConstraint(fields=["template", "version"], name="template_version_unique"),
            models.CheckConstraint(condition=Q(version__gte=1), name="template_version_positive"),
            models.CheckConstraint(condition=Q(status__in=["draft", "approved", "retired"]), name="template_version_status_valid"),
            models.CheckConstraint(condition=~Q(status="approved") | (~Q(approved_by="") & Q(approved_at__isnull=False)),
                                   name="template_version_approved_has_approver"),
            models.CheckConstraint(condition=Q(secret_bearing=True) | ~Q(variables__has_any_keys=LINK_VARIABLES),
                                   name="template_version_link_is_secret_bearing"),
        ]


class Question(models.Model):
    """016 3.3 (A-1). In 2B.1 only what outbound sends need: approval and the status column. Withdrawal
    fields exist so later tasks add no column; the withdrawal service arrives in 2B.4."""

    class Status(models.TextChoices):
        OPEN = "open"
        REPLY_PENDING = "reply_pending"
        PARTIALLY_ANSWERED = "partially_answered"
        SATISFIED = "satisfied"
        WITHDRAWN = "withdrawn"

    class Origin(models.TextChoices):
        STAFF = "staff"
        MODEL = "model"

    class Approval(models.TextChoices):
        PROPOSED = "proposed"
        APPROVED = "approved"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="questions")
    text = models.TextField()
    origin = models.CharField(max_length=16, choices=Origin.choices, default=Origin.STAFF)
    approval_state = models.CharField(max_length=16, choices=Approval.choices, default=Approval.PROPOSED)
    approved_by = models.CharField(max_length=200, blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.OPEN)
    withdrawn_by = models.CharField(max_length=200, blank=True, default="")
    withdrawn_reason = models.CharField(max_length=200, blank=True, default="")
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        permissions = [("approve_question", "Approve an applicant-specific question (operators, D-29)")]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=QUESTION_STATUSES), name="question_status_valid"),
            models.CheckConstraint(condition=Q(approval_state__in=["proposed", "approved"]), name="question_approval_valid"),
            models.CheckConstraint(condition=Q(origin__in=["staff", "model"]), name="question_origin_valid"),
            models.CheckConstraint(condition=~Q(approval_state="approved") | (~Q(approved_by="") & Q(approved_at__isnull=False)),
                                   name="question_approved_has_approver"),
        ]


class ApprovedMessage(models.Model):
    """016 3.2 (A-11): the frozen, authorized logical message. Authorization is set at insert; only the
    disposition changes afterwards."""

    class Kind(models.TextChoices):
        QUESTION = "question"
        REMINDER = "reminder"  # 2B.4
        STAFF_MESSAGE = "staff_message"  # 2B.4

    class Authority(models.TextChoices):
        SYSTEM_POLICY = "system_policy"
        STAFF = "staff"

    class Disposition(models.TextChoices):
        ACTIVE = "active"
        ACCEPTED_BY_SERVER = "accepted_by_server"
        ACCEPTED_BY_EVIDENCE = "accepted_by_evidence"
        REJECTED_PERMANENT = "rejected_permanent"
        RETRIES_EXHAUSTED = "retries_exhausted"
        TRANSPORT_BLOCKED = "transport_blocked"
        OPERATOR_ABANDONED = "operator_abandoned"
        SUPERSEDED = "superseded"

    send_ref = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField(max_length=24, choices=Kind.choices)
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, related_name="approved_messages")
    recipient = models.CharField(max_length=320)  # the verified address, frozen at approval
    template_version = models.ForeignKey(MessageTemplateVersion, on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="approved_messages")
    frozen_subject = models.CharField(max_length=200, blank=True, default="")
    frozen_body = models.TextField(blank=True, default="")
    content_sha256 = models.CharField(max_length=64, blank=True, default="")
    reproducible_inputs = models.JSONField(default=dict)  # secret-bearing kinds: identifiers only, never the secret
    inputs_sha256 = models.CharField(max_length=64, blank=True, default="")
    authorized_by = models.CharField(max_length=200)
    authority = models.CharField(max_length=16, choices=Authority.choices)
    authorized_at = models.DateTimeField(db_default=Now())
    supersedes = models.OneToOneField("self", on_delete=models.PROTECT, null=True, blank=True, related_name="superseded_by")
    disposition = models.CharField(max_length=24, choices=Disposition.choices, default=Disposition.ACTIVE)
    disposition_at = models.DateTimeField(null=True, blank=True)
    disposition_by = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        permissions = [("decide_uncertain_send", "Decide an unknown, exhausted, blocked or rejected send (decision-maker, D-30)")]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=["question", "reminder", "staff_message"]), name="approved_message_kind_valid"),
            models.CheckConstraint(condition=Q(authority__in=["system_policy", "staff"]), name="approved_message_authority_valid"),
            models.CheckConstraint(condition=Q(disposition__in=DISPOSITIONS), name="approved_message_disposition_valid"),
            models.CheckConstraint(condition=Q(kind="staff_message") | Q(template_version__isnull=False),
                                   name="approved_message_template_required"),
            models.CheckConstraint(condition=~Q(content_sha256="") | ~Q(inputs_sha256=""), name="approved_message_has_content"),
            models.CheckConstraint(condition=~Q(authorized_by=""), name="approved_message_authorized"),
            models.CheckConstraint(condition=~Q(supersedes=F("id")), name="approved_message_not_self_superseding"),
        ]


class ApprovedMessageQuestion(models.Model):
    class Purpose(models.TextChoices):
        INITIAL = "initial"
        REMINDER = "reminder"
        REVISION = "revision"  # a revised message superseding the initial one (016 3.2, A6 `revise`)

    approved_message = models.ForeignKey(ApprovedMessage, on_delete=models.PROTECT, related_name="question_links")
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="message_links")
    purpose = models.CharField(max_length=16, choices=Purpose.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["approved_message", "question"], name="message_question_unique"),
            models.UniqueConstraint(fields=["question"], condition=Q(purpose="initial"), name="question_one_initial_message"),
            models.CheckConstraint(condition=Q(purpose__in=["initial", "reminder", "revision"]), name="message_question_purpose_valid"),
        ]


class StaffItem(models.Model):
    """016 3.8 (A-2). Carries identifiers and reason codes only: no address, subject or body."""

    class Status(models.TextChoices):
        OPEN = "open"
        RESOLVED = "resolved"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    reason_code = models.CharField(max_length=64)
    dedupe_key = models.CharField(max_length=200)  # identifiers or digests only, never an address
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="staff_items")
    approved_message = models.ForeignKey(ApprovedMessage, on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="staff_items")
    question_id = models.BigIntegerField(null=True, blank=True)
    pending_action_id = models.BigIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["reason_code", "dedupe_key"], condition=Q(status="open"), name="staff_item_one_open_per_key"),
            models.CheckConstraint(condition=Q(status__in=["open", "resolved"]), name="staff_item_status_valid"),
        ]


class StaffItemResolution(models.Model):
    """Immutable: INSERT-only for the application role, one per item, with or without an application."""

    item = models.OneToOneField(StaffItem, on_delete=models.PROTECT, related_name="resolution")
    resolution_code = models.CharField(max_length=64)
    resolved_by = models.CharField(max_length=200)
    resolved_at = models.DateTimeField(db_default=Now())
    note = models.CharField(max_length=500, blank=True, default="")
    effects = models.JSONField(default=dict)  # the identifiers changed

    class Meta:
        constraints = [models.CheckConstraint(condition=~Q(resolved_by=""), name="staff_item_resolution_has_actor")]


# --- P2 inbound (016 sections 3.3, 3.5, 3.6; task 2B.2) ---------------------------------------------------

INBOUND_STATUSES = ["received", "awaiting_processing", "processed", "automated_reply", "exception"]
CURSOR_STATES = ["ok", "resync", "recovery", "blocked"]
LINK_STATES = ["pending", "applied", "ignored_automated", "stale", "void_withdrawn"]


class MailboxCursor(models.Model):
    """016 3.6: one collected mailbox folder, its position and the completed-collection watermark."""

    class State(models.TextChoices):
        OK = "ok"
        RESYNC = "resync"
        RECOVERY = "recovery"
        BLOCKED = "blocked"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    mailbox_ref = models.CharField(max_length=64)
    folder = models.CharField(max_length=200)
    uidvalidity = models.BigIntegerField(null=True, blank=True)
    last_uid = models.BigIntegerField(default=0)
    complete_through_uid = models.BigIntegerField(null=True, blank=True)
    complete_through_at = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=16, choices=State.choices, default=State.OK)
    blocked_reason = models.CharField(max_length=64, blank=True, default="")
    epoch = models.PositiveIntegerField(default=0)
    pass_number = models.PositiveIntegerField(default=0)
    start_mode = models.CharField(max_length=16, blank=True, default="")  # from_now | from_uid | recovery
    last_batch_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True, default="")
    consecutive_failures = models.PositiveIntegerField(default=0)
    duplicates_seen = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(db_default=Now())

    class Meta:
        permissions = [("restart_collector", "Restart a blocked mailbox collector (decision-maker, D-30)")]
        constraints = [
            models.UniqueConstraint(fields=["mailbox_ref", "folder"], name="cursor_one_per_folder"),
            models.CheckConstraint(condition=Q(state__in=CURSOR_STATES), name="cursor_state_valid"),
            models.CheckConstraint(condition=Q(last_uid__gte=0), name="cursor_last_uid_nonnegative"),
        ]


class InboundMessage(models.Model):
    """016 3.5 (A-9): metadata, the digest of the original bytes, and a sanitized derivative of the content,
    labelled as a derivative. Original MIME bytes are never stored in synthetic P2."""

    class Status(models.TextChoices):
        RECEIVED = "received"
        AWAITING_PROCESSING = "awaiting_processing"
        PROCESSED = "processed"
        AUTOMATED_REPLY = "automated_reply"
        EXCEPTION = "exception"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    mailbox_ref = models.CharField(max_length=64)
    message_id_header = models.CharField(max_length=998, blank=True, default="")
    in_reply_to = models.TextField(blank=True, default="")
    references = models.TextField(blank=True, default="")
    from_address = models.CharField(max_length=320, blank=True, default="")
    from_normalized = models.CharField(max_length=320, blank=True, default="")
    auto_markers = models.JSONField(default=dict)
    date_header = models.CharField(max_length=200, blank=True, default="")  # untrusted text, never used for ordering
    internal_date = models.CharField(max_length=64, blank=True, default="")
    received_at = models.DateTimeField(db_default=Now())
    size = models.BigIntegerField(default=0)
    original_sha256 = models.CharField(max_length=64, blank=True, default="")  # empty when identity is unestablished
    derived_text = models.TextField(blank=True, default="")
    derivation_version = models.PositiveIntegerField(default=1)
    redaction_version = models.PositiveIntegerField(default=1)
    truncated = models.BooleanField(default=False)
    truncated_at_chars = models.PositiveIntegerField(null=True, blank=True)
    omitted_parts = models.JSONField(default=list)
    redactions = models.JSONField(default=dict)
    attachments = models.JSONField(default=list)  # metadata only: sanitized name, type, size, digest
    is_derivative = models.BooleanField(default=True)
    auth_evidence = models.CharField(max_length=24, blank=True, default="missing")
    trust_decision = models.CharField(max_length=24, blank=True, default="")
    from_matches_verified_address = models.BooleanField(default=False)
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="inbound_messages")
    approved_message = models.ForeignKey(ApprovedMessage, on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="replies")
    classification = models.CharField(max_length=16, blank=True, default="")  # human | automatic | bounce | own_copy
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.RECEIVED)
    exception_reason = models.CharField(max_length=64, blank=True, default="")
    processed_at = models.DateTimeField(null=True, blank=True)
    identity_state = models.CharField(max_length=16, default="established")  # established | unestablished

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(status__in=INBOUND_STATUSES), name="inbound_status_valid"),
            models.CheckConstraint(condition=Q(is_derivative=True), name="inbound_is_derivative"),
            models.CheckConstraint(condition=Q(identity_state__in=["established", "unestablished"]), name="inbound_identity_state_valid"),
            models.UniqueConstraint(fields=["mailbox_ref", "original_sha256"], condition=~Q(original_sha256=""),
                                    name="inbound_one_per_digest"),
        ]


class InboundMessageLocation(models.Model):
    """Every place a message was observed (016 3.5). INSERT-only."""

    message = models.ForeignKey(InboundMessage, on_delete=models.PROTECT, related_name="locations")
    mailbox_ref = models.CharField(max_length=64)
    folder = models.CharField(max_length=200)
    uidvalidity = models.BigIntegerField()
    uid = models.BigIntegerField()
    observed_at = models.DateTimeField(db_default=Now())
    matched_by = models.CharField(max_length=16)  # new | digest | metadata

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["mailbox_ref", "folder", "uidvalidity", "uid"], name="inbound_location_unique"),
            models.CheckConstraint(condition=Q(matched_by__in=["new", "digest", "metadata"]), name="inbound_location_matched_by_valid"),
        ]


class QuestionReplyLink(models.Model):
    """016 3.3: a reply's relation to one question. `pending` makes the question `reply_pending`."""

    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="reply_links")
    inbound_message = models.ForeignKey(InboundMessage, on_delete=models.PROTECT, related_name="question_links")
    state = models.CharField(max_length=24, default="pending")
    outcome = models.CharField(max_length=24, blank=True, default="")
    actor_ref = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["question", "inbound_message"], name="reply_link_unique"),
            models.CheckConstraint(condition=Q(state__in=LINK_STATES), name="reply_link_state_valid"),
            models.CheckConstraint(condition=Q(outcome__in=["", "satisfied", "partial", "not_addressed"]), name="reply_link_outcome_valid"),
        ]
