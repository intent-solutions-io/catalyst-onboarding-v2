"""Import provenance for the first-generation service (bead catalyst-v2-bgl.16; 035; 034 sections 1.5, 3.4 and 3.5).

`catalyst_import_v1` converts every record of the first-generation database into this database. Where a v2 model fits,
the record becomes that model (an application with its submission versions, agreement details, a mailbox reservation,
a member-on-file record, a decline decision); everything else, and the provenance of everything, is kept here:

- `ImportedCase`: one row per first-generation case, the key that makes the import idempotent. It names the v2
  application, the `CAT-` reference applicants quote, the first-generation state verbatim and the stage it mapped to,
  the CRM (Twenty) references and finding codes for anything lossy. Non-personal: identifiers, states, codes, times.
- `ImportedRecord`: one row per first-generation row (any table), keyed (table, id): the case timeline with its
  original timestamps, review runs, questions, drafts and evidence, messages and their Message-IDs (so a reply to an
  old thread can be associated, `firstgen.threads`), agreements, releases, CRM items. `data` holds the row; when the
  row's personal content became a v2 record (`target`), `data` keeps only its non-personal columns. `data` is personal
  history: erasure class `history_events` (erasure.catalog), selected through `application`; a row without an
  application never holds personal data (the importer drops those columns and says so in the report).
- `ImportRun`: the report of each committed run (counts and codes only).

All three are written only by the owner-run command (the application role may read them) and are append-only for every
role; `ImportedRecord.data` admits only the audited erasure tombstone (migration 0002).
"""

import uuid

from django.db import models
from django.db.models import Q
from django.db.models.functions import Now


class ImportRun(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    actor_ref = models.CharField(max_length=200)
    source_ref = models.CharField(max_length=64)  # sha256 of the source database's identity, never the DSN
    report = models.JSONField(default=dict)  # counts and codes only
    recorded_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [models.CheckConstraint(condition=~Q(actor_ref=""), name="firstgen_run_has_actor")]


class ImportedCase(models.Model):
    application = models.OneToOneField("applications.Application", on_delete=models.PROTECT,
                                       related_name="first_generation")
    v1_case_id = models.CharField(max_length=26, unique=True)
    reference = models.CharField(max_length=20, unique=True)  # the applicant-facing CAT- reference
    v1_state = models.CharField(max_length=30)  # verbatim
    v1_resume_state = models.CharField(max_length=30, blank=True, default="")  # lapsed: the state it lapsed from
    v1_cohort = models.CharField(max_length=30, blank=True, default="")
    v1_created_at = models.DateTimeField()
    v1_state_changed_at = models.DateTimeField()
    mapped_stage = models.CharField(max_length=32)
    crm_person_id = models.CharField(max_length=64, blank=True, default="")  # Twenty person id
    crm_note_id = models.CharField(max_length=64, blank=True, default="")  # Twenty "Applicant file" note id
    findings = models.JSONField(default=list)  # codes only: lossy mappings and follow-ups
    run_ref = models.UUIDField()
    imported_at = models.DateTimeField(db_default=Now())


class ImportedRecord(models.Model):
    v1_table = models.CharField(max_length=40)
    v1_id = models.CharField(max_length=100)
    application = models.ForeignKey("applications.Application", on_delete=models.PROTECT, null=True, blank=True,
                                    related_name="first_generation_records")
    kind = models.CharField(max_length=40)
    occurred_at = models.DateTimeField(null=True, blank=True)  # the first-generation time, as recorded there
    message_id = models.CharField(max_length=255, blank=True, default="")  # an outbound RFC 5322 Message-ID
    target = models.CharField(max_length=120, blank=True, default="")  # the v2 record it became: "app.Model:<id>"
    data = models.JSONField(default=dict)
    run_ref = models.UUIDField()
    imported_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [models.UniqueConstraint(fields=["v1_table", "v1_id"], name="firstgen_record_once")]
        indexes = [
            models.Index(fields=["message_id"], condition=~Q(message_id=""), name="firstgen_record_message_id"),
            models.Index(fields=["application", "occurred_at"], name="firstgen_record_timeline"),
        ]
