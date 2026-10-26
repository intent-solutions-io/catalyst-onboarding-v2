"""Catalyst-wide health signals (026 section 7; 6B.4), read-only, counts and signal names only.

Each part reports counts and an `anomalies` list. The `catalyst_health` command prints them as JSON and exits 1 when
any part has an anomaly, so a host timer can alert through the estate alert floor. The thresholds are placeholders
until POL-16 (P6-D-9). No applicant name, address, token or message text is ever part of a report.
"""

from datetime import timedelta

from django.conf import settings
from django.db.models import Min
from django.db.models.functions import Now
from django.utils import timezone

from workflow import heartbeat
from workflow.models import PendingAction


def worker_health() -> dict:
    path = settings.CATALYST_WORKER_HEARTBEAT_FILE
    if not path:
        return {"configured": False, "age_seconds": None, "anomalies": []}
    age = heartbeat.age_seconds(path)
    stale = age is None or age > settings.CATALYST_HEALTH_HEARTBEAT_STALE_SECONDS
    return {"configured": True, "age_seconds": None if age is None else int(age),
            "anomalies": ["heartbeat_missing" if age is None else "heartbeat_stale"] if stale else []}


def queue_health() -> dict:
    """The oldest action that is due and still queued (moved here from readiness, 6B.3), and running actions whose
    lease ran out long ago (a worker that died mid-action without recovery)."""
    now = timezone.now()
    oldest = PendingAction.objects.filter(status=PendingAction.Status.QUEUED, due_at__lte=Now()).aggregate(m=Min("due_at"))["m"]
    age = int((now - oldest).total_seconds()) if oldest else 0
    expired = PendingAction.objects.filter(
        status=PendingAction.Status.RUNNING,
        lease_expires_at__lt=now - timedelta(seconds=settings.CATALYST_WORKER_LEASE_SECONDS)).count()
    anomalies = []
    if age > settings.CATALYST_HEALTH_PENDING_AGE_SECONDS:
        anomalies.append("backlog")
    if expired:
        anomalies.append("expired_leases")
    return {"oldest_due_seconds": age, "expired_leases": expired, "anomalies": anomalies}


AGREEMENT_UNCERTAIN = ("create_uncertain", "distribute_uncertain", "cancel_uncertain")


def agreement_health() -> dict:
    from agreements.models import AgreementInstance

    live = AgreementInstance.objects.filter(replaced_at__isnull=True)
    uncertain = live.filter(issue_status__in=AGREEMENT_UNCERTAIN).count()
    failed = live.filter(issue_status="failed_needs_staff").count()
    custody_failed = live.filter(custody_status="failed_needs_staff").count()
    anomalies = [name for name, count in (("agreements_uncertain", uncertain), ("agreements_failed", failed),
                                          ("custody_failed", custody_failed)) if count]
    return {"uncertain": uncertain, "failed": failed, "custody_failed": custody_failed, "anomalies": anomalies}


# In-flight states only: an outcome the system is still settling. Terminal states (a conflict, a failure, a mailbox
# recovered after a stop) are not counted here: staff see them as open provisioning items, which close when staff
# resolve them, so the alert clears too (PR #64 review).
PROVISIONING_IN_FLIGHT = ("create_uncertain", "verify_uncertain", "found_by_evidence")


# Items that mean something went wrong alert at once; items that are ordinary waiting for staff (a checklist to carry
# out, a name to review, a prerequisite to fix) alert only once they are older than the backlog target (PR #64 re-check).
PROVISIONING_PROBLEM_ITEMS = ("provisioning_conflict", "provisioning_failed", "provisioning_late_mailbox",
                              "provisioning_confirm_found", "provisioning_revocation_needs_staff",
                              "provisioning_setup_needs_staff", "provisioning_activation_blocked",
                              "provisioning_withdrawal_link_failed")
PROVISIONING_ROUTINE_ITEMS = ("provisioning_checklist", "provisioning_name_needs_review", "provisioning_blocked")


def provisioning_health() -> dict:
    from correspondence.models import StaffItem
    from provisioning.models import AccessRevocation, ProvisioningRequest

    cutoff = timezone.now() - timedelta(seconds=settings.CATALYST_HEALTH_PENDING_AGE_SECONDS)
    settling = ProvisioningRequest.objects.filter(status__in=PROVISIONING_IN_FLIGHT).count()
    open_items = StaffItem.objects.filter(status=StaffItem.Status.OPEN)
    problems = open_items.filter(reason_code__in=PROVISIONING_PROBLEM_ITEMS).count()
    waiting = open_items.filter(reason_code__in=PROVISIONING_ROUTINE_ITEMS, opened_at__lt=cutoff).count()
    # A revocation round that never ran: an obligation still "requested" long after it was created. ("pending" and
    # "unsupported" rows keep a revocation staff item open, counted above; "applied_unverified" is final, 023 11.6.)
    stalled = AccessRevocation.objects.filter(state="requested", created_at__lt=cutoff).count()
    anomalies = [name for name, count in (("provisioning_settling", settling), ("provisioning_problem", problems),
                                          ("provisioning_waiting_too_long", waiting),
                                          ("revocation_stalled", stalled)) if count]
    return {"requests_settling": settling, "problem_items": problems, "routine_items_overdue": waiting,
            "revocations_stalled": stalled, "anomalies": anomalies}


def bounce_health() -> dict:
    """Hard bounces left unresolved past the target: every send to that applicant is blocked meanwhile (9kg.3)."""
    from correspondence.models import StaffItem

    cutoff = timezone.now() - timedelta(seconds=settings.CATALYST_HEALTH_HARD_BOUNCE_AGE_SECONDS)
    aged = StaffItem.objects.filter(reason_code="hard_bounce", status=StaffItem.Status.OPEN, opened_at__lt=cutoff).count()
    return {"aged_hard_bounces": aged, "anomalies": ["hard_bounce_unresolved"] if aged else []}


def session_health() -> dict:
    """Outside the local environments the hourly removal of expired staff sessions must be scheduled (6B.9)."""
    from accounts.staff_access import CLEAR_SESSIONS

    scheduled = PendingAction.objects.filter(kind=CLEAR_SESSIONS, status__in=(PendingAction.Status.QUEUED,
                                                                              PendingAction.Status.RUNNING)).exists()
    required = settings.CATALYST_STAFF_TWO_FACTOR
    return {"cleanup_scheduled": scheduled, "anomalies": ["session_cleanup_unscheduled"] if required and not scheduled else []}


def staff_role_health() -> dict:
    """9kg.56: memberships and direct permissions that do not match the latest grant record (accounts.grants), counted;
    `grant_staff_role --audit` lists them for the owner. Counts only: no account or group name is in the report."""
    from accounts import grants

    found = grants.differences()
    unrecorded = sum(1 for d in found if d.problem == grants.UNRECORDED)
    not_held = len(found) - unrecorded
    anomalies = [name for name, count in (("role_access_unrecorded", unrecorded), ("role_grant_not_held", not_held)) if count]
    return {"unrecorded": unrecorded, "recorded_not_held": not_held, "anomalies": anomalies}


def verification_health() -> dict:
    """9kg.66: outside the local environments the recurring verification expiry sweep must be scheduled, or an
    expired only link would again prompt nothing (correspondence.verification)."""
    from correspondence.verification import EXPIRY_SWEEP

    scheduled = PendingAction.objects.filter(kind=EXPIRY_SWEEP, status__in=(PendingAction.Status.QUEUED,
                                                                            PendingAction.Status.RUNNING)).exists()
    required = settings.CATALYST_ENV not in settings.LOCAL_ENVIRONMENTS
    return {"expiry_sweep_scheduled": scheduled,
            "anomalies": ["verification_sweep_unscheduled"] if required and not scheduled else []}


def journal_health() -> dict:
    """9kg.33 (PR #89 review): the effect journal is readable and chained, its directory private and writable, and
    no append has failed; a torn tail names the owner's repair."""
    from workflow import journal

    if not journal.configured():
        return {"configured": False, "append_failures": 0, "anomalies": []}
    anomalies = []
    problem = journal.directory_problem(write=True)
    if problem:
        anomalies.append(f"effect_journal_{problem}")
    try:
        journal.read()
    except journal.JournalError as exc:
        anomalies.append(f"effect_journal_{exc.code}")
    failed = journal.failures()
    if failed:
        anomalies.append("effect_journal_append_failed")
    return {"configured": True, "append_failures": failed, "anomalies": anomalies}


def erasure_health() -> dict:
    """9kg.32 (PR #99 reviews): an erasure begun and not finished (`intent_open`), and provider deletions owed after
    an erasure (`handoff_owed`). Counts only. Read without the erasure key (no web or worker process holds it), so
    entries are not mac-verified here; `catalyst_erasure_record --list-open` verifies them."""
    from erasure import record
    from workflow import journal

    if not journal.configured():
        return {"open": 0, "handoffs_owed": 0, "anomalies": []}
    try:
        state = record.fold(journal.read(), None)
    except journal.JournalError:
        return {"open": 0, "handoffs_owed": 0, "anomalies": []}  # the journal part reports the fault
    opened = sum(1 for s in state.values() if s.open)
    owed = sum(len(s.outstanding) for s in state.values())
    return {"open": opened, "handoffs_owed": owed,
            "anomalies": [n for n, c in (("intent_open", opened), ("handoff_owed", owed)) if c]}


# 9kg.70 (release-ops review of PR #105): a key file, a sealed file or a destruction younger than this is left out of
# the orphan, recovery and destruction counts, so a write or a destruction in progress never pages.
CUSTODY_SETTLE_SECONDS = 600


def custody_health() -> dict:
    """9kg.70: the custody key store's state, read-only, counts only (agreements.keystore; `catalyst_custody_keys
    --status` gives the operator the same view). Each condition pages under its own code; the operator action is in
    026 section 16:

    - `key_store_unavailable` / `key_store_unsafe`: a key directory (`store` says which) is missing or unmarked, or has
      the wrong owner or mode;
    - `wrapping_key_mismatch`: key files under a wrapping key other than the one this process holds (a replaced
      secret file, or an older key directory put back), so the documents cannot be opened;
    - `key_lost`: a sealed document's key is in neither directory and was never journaled destroyed;
    - `recovery_incomplete`: a live key in one directory only; `copies_differ`: the two copies of a key differ;
    - `destroyed_still_present`: a key journaled destroyed still has a file;
    - `destroyed_without_erasure`: a destruction whose subject has no erasure in the record (a mistaken or forged
      entry would hide a real loss as an erasure);
    - `in_the_clear`, `orphans`, `key_invalid` (unreadable, does not unwrap, or a stray file), `rotation_incomplete`;
    - `journal_unavailable`: destructions cannot be told apart from losses, so `key_lost` and `orphans` are withheld.

    A document whose key an erasure destroyed is the intended outcome: counted (`erased_documents`), never paged. A
    planned rotation or migration pages by design while it runs (`rotation_incomplete`, `key_invalid` for its
    temporary copy, `wrapping_key_mismatch`)."""
    import time

    from agreements import keystore, storage
    from agreements.management.commands.catalyst_custody_keys import orphan_files, state
    from agreements.models import CustodyEnvelope
    from erasure import record
    from workflow import journal

    if not keystore.configured():
        return {"configured": False, "anomalies": []}
    try:
        primary, mirror = keystore.directories()
    except keystore.KeyStoreError as exc:
        return {"configured": True, "store": "configuration", "anomalies": [exc.code]}
    listed = {}
    for name, path in (("primary", primary), ("mirror", mirror)):
        try:
            listed[name] = keystore._listing(path)
        except keystore.KeyStoreError as exc:
            code = "key_store_unsafe" if exc.code == "key_store_unsafe" else "key_store_unavailable"
            return {"configured": True, "store": name, "anomalies": [code]}
    try:
        found = state()
        blobs = {(name, ref): keystore._read(path, ref) or b"" for name, path in (("primary", primary), ("mirror", mirror))
                 for ref in listed[name]}
        stray = keystore.strays()
        refs = set(CustodyEnvelope.objects.values_list("key_ref", flat=True))
        sealed_orphans = orphan_files(list(CustodyEnvelope.objects.all()))
    except keystore.KeyStoreError as exc:
        code = "key_store_unsafe" if exc.code == "key_store_unsafe" else "key_store_unavailable"
        return {"configured": True, "store": "either", "anomalies": [code]}
    except (storage.StorageError, OSError):
        return {"configured": True, "store": "custody", "anomalies": ["key_store_unavailable"]}
    now = time.time()

    def settled(path) -> bool:
        try:
            return path.stat().st_mtime <= now - CUSTODY_SETTLE_SECONDS
        except OSError:
            return True
    journal_ok, destroyed, recent, begun, done, unmatched = found["journal"] == "ok", set(), set(), set(), set(), 0
    if journal_ok:
        try:
            entries = journal.read()
        except journal.JournalError:
            journal_ok = False
        else:
            destroyed = keystore.destroyed_refs(entries)
            recent = {e.key.partition(":")[2] for e in entries if e.kind == keystore.DESTROYED
                      and e.when.timestamp() > now - CUSTODY_SETTLE_SECONDS}
            erased = set(record.fold(entries, None))
            unmatched = sum(1 for e in entries if e.kind == keystore.DESTROYED and str(e.data.get("subject")) not in erased)
            rotations = [e for e in entries if e.kind == "custody_rotation" and e.key.startswith("custody_rotation:")]
            begun = {e.key for e in rotations if e.data.get("phase") == "prepare"}
            done = {e.key for e in rotations if e.data.get("phase") == "done"}
    in_primary, in_mirror = listed["primary"], listed["mirror"]
    wrapped = {key: keystore.wrapped_by(blob) for key, blob in blobs.items()}
    held = None
    if getattr(settings, "CATALYST_CUSTODY_WRAPPING_KEY", ""):  # the worker and web hold it; the check needs no decryption
        try:
            held = keystore.wrapping_key()
        except keystore.KeyStoreError:
            held = None
    unwrap_failed = 0
    if held is not None:
        held_id = keystore.wrapping_key_id(held)
        for (name, ref), by in wrapped.items():
            if by == held_id:
                try:
                    keystore._unwrap(held, ref, blobs[(name, ref)])
                except keystore.KeyStoreError:
                    unwrap_failed += 1
    counts = {
        "documents": found["documents"], "sealed": found["sealed"], "erased_documents": found["sealed_after_destruction"],
        "keys_primary": len(in_primary), "keys_mirror": len(in_mirror),
        "wrapping_key_mismatch": sum(1 for by in wrapped.values() if by and held is not None
                                     and by != keystore.wrapping_key_id(held)),
        "key_lost": found["lost"] if journal_ok else 0,
        "recovery_incomplete": sum(1 for ref in (in_primary ^ in_mirror) - destroyed
                                   if settled((primary if ref in in_primary else mirror) / f"{ref}.key")),
        "copies_differ": sum(1 for ref in in_primary & in_mirror if blobs[("primary", ref)] != blobs[("mirror", ref)]),
        "destroyed_still_present": len(((in_primary | in_mirror) & destroyed) - recent),
        "destroyed_without_erasure": unmatched,
        "in_the_clear": found["in_the_clear"] + found["plaintext_lingering"],
        "orphans": (sum(1 for ref in (in_primary | in_mirror) - refs - destroyed
                        if settled(primary / f"{ref}.key") and settled(mirror / f"{ref}.key"))
                    + sum(1 for n in sealed_orphans if settled(storage.root() / n))) if journal_ok else 0,
        "key_invalid": sum(1 for by in wrapped.values() if by is None) + unwrap_failed + stray,
        "rotation_incomplete": len(begun - done) + int(len({by for by in wrapped.values() if by}) > 1),
        "journal_unavailable": int(not journal_ok and found["journal"] != "not_configured"),
    }
    paging = ("wrapping_key_mismatch", "key_lost", "recovery_incomplete", "copies_differ", "destroyed_still_present",
              "destroyed_without_erasure", "in_the_clear", "orphans", "key_invalid", "rotation_incomplete",
              "journal_unavailable")
    return {"configured": True, **counts, "anomalies": [name for name in paging if counts[name]]}


def backup_health() -> dict:
    """9kg.32: in a live environment a backup refuses while the erasure registry is not decided (or replay is not
    built), so the nightly set is not being written: `registry_blocked`."""
    from config.guards import LIVE_ENVIRONMENTS
    from erasure import registry

    blocked = settings.CATALYST_ENV in LIVE_ENVIRONMENTS and bool(registry.problems())
    return {"registry_blocked": blocked, "anomalies": ["registry_blocked"] if blocked else []}


# 9kg.51 (029 section 5.2): the waits that had no bound once the first-generation owner notices retired. Each class is
# counted past its own threshold and its oldest age is printed; a class in CATALYST_HEALTH_AGED_WAITS_PAGE raises the
# anomaly `aged_waits.<class>` (delivered by the alert floor as high), the others are audit only. Counts and ages
# only: no identifier of any application, item, message or agreement is part of the report.
STAGE_WAITS = {"assessing": "assessing", "awaiting_decision": "awaiting_decision", "on_hold": "on_hold"}
# A sent agreement still awaiting the applicant's signature, or the countersignature once the applicant signed.
AWAITING_SIGNATURE = ("not_started", "partially_signed", "signing_complete_observed")
# 9kg.57: the follow-ons a decision or the agreements hand-off leave held for the owner's release or a policy: the decline
# notice (`send_decline`, oc4.11), the NDA (`issue_nda`, activate_agreements) and the provisioning hand-off (`provision`,
# activate_provisioning), which is also how an application waits in `agreements_complete` (021 step 8, 023 11.11), so
# that stage is counted once, through its hand-off. Counted by kind and status only, whether or not a handler exists.
HELD_FOLLOWONS = ("send_decline", "issue_nda", "provision")


def _stage_wait(stage: str):
    """Applications in `stage`, with when they entered it: the latest transition event into the stage (every stage
    move writes one, applications.stages), else the row's last update."""
    from django.db.models import OuterRef, Subquery
    from django.db.models.functions import Coalesce

    from applications.models import Application, ApplicationEvent

    entered = ApplicationEvent.objects.filter(application=OuterRef("pk"), data__to=stage).order_by("-occurred_at", "-id")
    return (Application.objects.filter(stage=stage)
            .annotate(started_at=Coalesce(Subquery(entered.values("occurred_at")[:1]), "updated_at")))


def _waits() -> dict:
    """Each wait class as (queryset, the name of its start-time column)."""
    from agreements.models import AgreementInstance
    from correspondence.models import InboundMessage, StaffItem
    from workflow.models import AutomationPause

    waits = {name: (_stage_wait(stage), "started_at") for name, stage in STAGE_WAITS.items()}
    waits.update({
        "open_staff_items": (StaffItem.objects.filter(status=StaffItem.Status.OPEN), "opened_at"),
        "pauses": (AutomationPause.objects.filter(subject_type="application"), "created_at"),
        "replies_awaiting_processing": (InboundMessage.objects.filter(status=InboundMessage.Status.AWAITING_PROCESSING),
                                        "received_at"),
        "issued_agreements": (AgreementInstance.objects.filter(replaced_at__isnull=True, issue_status="issued",
                                                               signing_status__in=AWAITING_SIGNATURE), "updated_at"),
        "provisioning_activation": (PendingAction.objects.filter(kind="provision_activate", status=PendingAction.Status.QUEUED),
                                    "created_at"),
        # From `updated_at`: when the action was created held or last returned to held (a refused `issue_nda` goes back
        # to held); nothing else updates a held row.
        "held_followons": (PendingAction.objects.filter(kind__in=HELD_FOLLOWONS, status=PendingAction.Status.HELD),
                           "updated_at"),
    })
    return waits


def aged_waits_health() -> dict:
    now = timezone.now()
    report = {}
    for name, (queryset, column) in _waits().items():
        threshold = settings.CATALYST_HEALTH_AGED_WAIT_SECONDS[name]
        oldest = queryset.aggregate(m=Min(column))["m"]
        age = (now - oldest).total_seconds() if oldest else 0.0
        aged = queryset.filter(**{f"{column}__lt": now - timedelta(seconds=threshold)}).count() if oldest else 0
        report[name] = {"waiting": queryset.count(), "aged": aged, "oldest_seconds": int(age),
                        "threshold_seconds": int(threshold), "pages": name in settings.CATALYST_HEALTH_AGED_WAITS_PAGE}
        if name == "held_followons":  # which follow-on is waiting: kind names and counts, never an identifier
            past = queryset.filter(**{f"{column}__lt": now - timedelta(seconds=threshold)})
            report[name]["aged_by_kind"] = {kind: past.filter(kind=kind).count() for kind in HELD_FOLLOWONS}
    report["anomalies"] = sorted(name for name, values in report.items() if values["aged"] and values["pages"])
    return report


def decision_health() -> dict:
    """9kg.30 review: whether the qualification authority is configured (POL-05), visible without a shell. Not an
    anomaly either way: unset is the intended state until 211.7.8 is recorded.

    oc4.11: the decline notice's wording state (as for the data notice: status, version, digest and synthetic flag,
    never the wording). Once decisions can be recorded, wording that may not be sent here is an anomaly
    (`decline_notice_unapproved`): a decline is recorded but its notice waits, with a staff item, until the owner
    approves real wording."""
    from applications import notices

    configured = settings.CATALYST_QUALIFICATION_AUTHORITY == "explicit_permission"
    notice = notices.status("decline_notice")
    unusable = configured and not notices.servable(notice, settings.CATALYST_ENV)
    return {"qualification_authority_configured": configured, "decline_notice": notice,
            "anomalies": ["decline_notice_unapproved"] if unusable else []}


def intake_health() -> dict:
    """9kg.43 and 9kg.29: the launch mode and the client-identity source the limits key on, as configured in code, and
    the number of live invitations (a count, never an address). No anomaly: the mode is the owner's recorded act."""
    from applications import notices
    from applications.invitations import LIVE
    from applications.models import Invitation

    # 9kg.52: the data notice's state (approved, draft, retired or missing, with the version, digest and synthetic
    # flag; never the wording). In invitation mode, wording that may not be served here (unapproved, retired, or an
    # approved synthetic placeholder outside the draft environments) is an anomaly: the page is withheld and no
    # invitation can be issued until the owner approves real wording. Where a draft may be shown the page works, marked.
    notice = notices.status(notices.DATA_NOTICE)
    withheld = settings.CATALYST_INTAKE_MODE == "invitation" and not notices.servable(notice, settings.CATALYST_ENV)
    anomalies = ["data_notice_unapproved"] if withheld else []
    return {"mode": settings.CATALYST_INTAKE_MODE, "client_identity": settings.CATALYST_CLIENT_IDENTITY,
            "live_invitations": Invitation.objects.filter(LIVE).count(), "data_notice": notice, "anomalies": anomalies}


def report() -> dict:
    from correspondence.health import collector_health, mail_behaviour_health, reminder_health, reply_health, send_health

    return {"worker": worker_health(), "queue": queue_health(), "agreements": agreement_health(),
            "provisioning": provisioning_health(), "bounces": bounce_health(), "sends": send_health(),
            "collector": collector_health(), "replies": reply_health(), "reminders": reminder_health(),
            "mail": mail_behaviour_health(), "sessions": session_health(), "staff_roles": staff_role_health(),
            "verification": verification_health(),
            "journal": journal_health(),
            "aged_waits": aged_waits_health(), "decision": decision_health(), "intake": intake_health(),
            "erasure": erasure_health(), "backup": backup_health(), "custody": custody_health()}
