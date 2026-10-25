"""The erasure and retention decision registry (council record 030 Q3, D-51; POL-10, decision 211.7.1).

Every retention value and every per-class treatment lives here, as one row per data class, and every row ships as
`undecided`. While any value is undecided the erasure command refuses (`erasure.service`) and so does a backup in a
live environment (`config.backup`): there is nothing to erase against, and no real personal data may be backed up
under rules nobody has decided. Counsel's POL-10 decision changes rows of this table (a reviewed change, like every
policy constant in this repository), never the schema: the database mechanism (`erasure.catalog`, migration
`erasure.0002`) already supports every treatment a row may name.

Treatments a subject class may take:

- `anonymize`: the class's personal columns are set to their tombstones by the audited erasure function. This is
  the superset: an anonymized append-only row with a tombstone key satisfies a "delete" answer as well as an
  "anonymize" one, so counsel choosing deletion changes nothing here.
- `retain`: the class is kept as it is (a legal hold or a retention obligation); the erasure function leaves it.

Rows that are not database classes:

- `signed_documents`: v2's custody copy of the signed PDFs. `retain` keeps them; `destroy_key` (9kg.34) destroys
  each of the subject's per-document keys (agreements.keystore), in the key directory and its mirror, so the sealed
  files in custody and in every backup, old or new, cannot be opened without a surviving copy of the wrapped key and the wrapping key. The rows and sealed files stay; nothing
  in the database changes. The provider's copy is not reached (`provider_copies`, P4-D-15 until POL-10).
- `provider_copies`: the Documenso copy, the mail host's Sent and inbox folders and a provisioned mailbox. Deleting
  them is a manual handoff owned by the owner (211.7.1, QA finding 12); the only supported treatment is
  `manual_handoff`, recorded as an erasure-record entry with its completion date (`catalyst_erase --handoff`).
- `erasure_record` and `effect_journal`: how long the durable record is kept. The floor is fixed by design (at least
  as long as the oldest restorable backup, since a restore of an older set must still find every later erasure);
  the value above the floor is counsel's.

Each row's `retention` is the period after which the class is deleted or anonymized without a request (POL-10).
Nothing applies a retention period yet; the values are recorded here so that the same decision fills them.
"""

UNDECIDED = "undecided"
ANONYMIZE = "anonymize"
RETAIN = "retain"
DESTROY_KEY = "destroy_key"  # 9kg.34: signed_documents only
MANUAL_HANDOFF = "manual_handoff"

# The subject data classes the erasure function can anonymize (erasure.catalog names each class's columns).
SUBJECT_CLASSES = (
    "application_identity",  # the application's address, key and name; the contact challenge's address
    "submissions",  # submitted answers (the versions; the adoption record itself is kept)
    "history_events",  # the data of history events
    "mail_derivatives",  # inbound and outbound mail records, approved and draft messages, questions, interpretations
    "staff_notes",  # free text staff wrote about the person: resolutions, revocations, evidence, document access
    "agreement_records",  # applicant recipients and agreement details (POL-18, the most sensitive)
    "decisions",  # qualification decision texts and rationale notes (POL-10 says erase or anonymize, 029 6.1)
    "evidence",  # evidence URLs, captured text, assessment snapshots and outputs
    "provisioning_records",  # the reserved mailbox name, setup and withdrawal recipients, evidence facts
    "invitations",  # the invitation's address key and note
    "member_on_file",  # the first-generation agreement-on-file record's address key
    "pauses",  # the free-text reason of an automation pause
    "jobs",  # the error text of the subject's pending actions
    "audit_residue",  # earlier retention audits: their free-text reason and unkeyed row digest
    "throttle_keys",  # the intake throttle bucket keyed on the address (an unkeyed digest of the email key)
    "admin_log",  # the admin log's text for the subject's application
)
OTHER_CLASSES = ("signed_documents", "provider_copies", "erasure_record", "effect_journal")

# What each row may say once decided, besides UNDECIDED.
ALLOWED = {
    **{name: (ANONYMIZE, RETAIN) for name in SUBJECT_CLASSES},
    "signed_documents": (RETAIN, DESTROY_KEY),  # 9kg.34: per-document key destruction
    "provider_copies": (MANUAL_HANDOFF,),
    "erasure_record": (RETAIN,),
    "effect_journal": (RETAIN,),
}

REGISTRY = {name: {"treatment": UNDECIDED, "retention": UNDECIDED} for name in (*SUBJECT_CLASSES, *OTHER_CLASSES)}

# Replay after a restore (9kg.25) does not exist yet. Until it does, an erasure could be undone by restoring an older
# backup, so the registry reports `replay:not_built`: neither an erasure nor a live backup proceeds, however decided the
# rows are. 9kg.25 flips this constant in the same change that builds the replay (PR #99 reviews).
REPLAY_BUILT = False
# The classes whose rows are found only through the subject's real email key. Once `application_identity` replaces the
# key with a tombstone, these rows can never be found again, so anonymizing the identity while retaining any of them
# would strand them (PR #99 data review).
KEY_SELECTED_CLASSES = ("invitations", "member_on_file", "mail_derivatives", "throttle_keys")


def current() -> dict:
    """The registry in force: this module's REGISTRY (tests replace it with a decided synthetic copy)."""
    return REGISTRY


def problems(registry: dict | None = None) -> list[str]:
    """Every row and value that blocks an erasure or a real backup: an undecided value, a missing or unknown row, or
    a treatment the mechanism does not support. Codes only."""
    registry = current() if registry is None else registry
    found = []
    for name in (*SUBJECT_CLASSES, *OTHER_CLASSES):
        row = registry.get(name)
        if not isinstance(row, dict):
            found.append(f"{name}:missing")
            continue
        treatment, retention = row.get("treatment", UNDECIDED), row.get("retention", UNDECIDED)
        if treatment == UNDECIDED:
            found.append(f"{name}.treatment:undecided")
        elif treatment not in ALLOWED[name]:
            found.append(f"{name}.treatment:unsupported")
        if retention == UNDECIDED or not isinstance(retention, str) or not retention.strip():
            found.append(f"{name}.retention:undecided")
    found += [f"{name}:unknown" for name in sorted(set(registry) - set(ALLOWED))]
    identity = (registry.get("application_identity") or {}).get("treatment")
    if identity == ANONYMIZE and any((registry.get(n) or {}).get("treatment") == RETAIN for n in KEY_SELECTED_CLASSES):
        found.append("application_identity:retains_key_selected_classes")
    if not REPLAY_BUILT:
        found.append("replay:not_built")
    return found


def anonymized_classes(registry: dict | None = None) -> list[str]:
    """The subject classes a decided registry anonymizes, in the catalog's order."""
    registry = current() if registry is None else registry
    return [name for name in SUBJECT_CLASSES if registry[name]["treatment"] == ANONYMIZE]
