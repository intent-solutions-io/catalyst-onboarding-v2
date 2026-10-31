"""The Twenty link (bgl.14; 034 rows 42 and 43): one row per application the projection has looked at.

It holds what the projection must remember between runs, and nothing it can read again:

- `person_id` and `note_id`: the Twenty person and the applicant file note this application writes (Twenty's own
  identifiers; an imported application starts from the ids the first generation recorded, `crm.projection.imported`);
- `link_method`: how the person was found (`created`, `recovered` by the case id, `email_match`, `imported`, `staff`);
- `field_hashes`: a SHA-256 per owned field of the value Twenty held right after the last write, so an edit a person
  made in Twenty is noticed (a staff item) before it is overwritten. Digests of low-entropy values (a name, a state):
  personal data, erasure class `application_identity` (erasure.catalog);
- `note_sha256`: the digest of the last note written, so an unchanged note sends nothing.

An ordinary operational table (ADR-14): the application role inserts and updates it through `crm.projection` only.
"""

from django.db import models
from django.db.models.functions import Now


class TwentyLink(models.Model):
    application = models.OneToOneField("applications.Application", on_delete=models.PROTECT, related_name="twenty_link")
    person_id = models.CharField(max_length=64, blank=True, default="")
    link_method = models.CharField(max_length=16, blank=True, default="")
    note_id = models.CharField(max_length=64, blank=True, default="")
    note_sha256 = models.CharField(max_length=64, blank=True, default="")
    field_hashes = models.JSONField(default=dict)
    projection_version = models.CharField(max_length=40, blank=True, default="")
    projected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(db_default=Now())
    updated_at = models.DateTimeField(db_default=Now())

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(link_method__in=["", "created", "recovered", "email_match", "imported", "staff"]),
                name="twenty_link_method_valid"),
        ]
        indexes = [models.Index(fields=["person_id"], condition=~models.Q(person_id=""), name="twenty_link_person")]
