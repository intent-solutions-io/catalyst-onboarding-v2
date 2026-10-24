"""The erasure audit (9kg.32; 029 section 6.2; ADR-14 pattern).

One row per erasure transaction, written only by the security-definer erase function (`public.catalyst_erase`,
migration 0002; EXECUTE for the retention role only), before any personal column changes. Each protected table's
trigger admits a change to its personal columns only while a row of this table carries the current transaction's id
(the agreements 0004 pattern), the session's login is a member of the retention role, and every changed column is in
the table's allow-list and set to its tombstone (erasure.catalog). The row is append-only for every role.

What it holds is minimal and contains nothing personal: the subject's public reference (a random identifier, not a
numeric id), the authority and reason as codes (never free text, unlike `RetentionAudit.reason`), the classes
anonymized, the login and the time. The keyed hash of the subject's email key is not here: it lives only in the
durable erasure record (erasure.record), outside the backup, under its own key, so a backup never carries it.
"""

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now

from applications.models import CurrentTransactionId

CODE = r"^[a-z0-9_.:-]{3,64}$"


class ErasureAudit(models.Model):
    at = models.DateTimeField(db_default=Now())  # set by the insert trigger
    actor = models.CharField(max_length=128)  # the session login, set by the insert trigger
    subject_ref = models.UUIDField()
    authority = models.CharField(max_length=64)
    reason_code = models.CharField(max_length=64)
    classes = models.JSONField(default=list)
    # The top-level transaction that inserted the row, always the database's own (the insert trigger overwrites a
    # supplied value); the erasure branch of every protected trigger compares it with the current transaction.
    created_txid = models.BigIntegerField(db_default=CurrentTransactionId())

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(authority__regex=CODE), name="erasure_audit_authority_is_a_code"),
            models.CheckConstraint(condition=Q(reason_code__regex=CODE), name="erasure_audit_reason_is_a_code"),
        ]
        indexes = [models.Index(fields=["created_txid"], name="erasure_audit_txid")]
