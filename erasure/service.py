"""The erasure of one person under POL-10 (9kg.32; 029 section 6.2): the owner-run command's logic.

Order of operations, each step refusing before anything changes:

1. the registry (erasure.registry) has no undecided value, the durable record is configured and the erasure key is
   usable (erasure.record);
2. the connection is the retention role's login and nothing else (never the owner, the application role or a
   superuser); the web and worker processes can never hold this login (config.runtime refuses it at connection);
3. a dry run of the database function inside a transaction that is rolled back: a subject that is open, still has
   work in flight, has an unfinished access revocation or is unknown is refused here, before any record is written;
4. the intent is appended to the durable record and fsynced;
5. one database transaction: `public.catalyst_erase(...)` writes the erasure audit row and the tombstones;
6. 9kg.34, when the registry's `signed_documents` row says `destroy_key`: every custody key of the subject's sealed
   documents is destroyed outside the database (agreements.keystore: journaled, then unlinked from the mirror and the
   key directory), so the sealed files in custody and in every backup can no longer be opened. A subject with any
   document still stored in the clear is refused at the dry run, before any record: destruction could not reach it
   (`catalyst_custody_keys --migrate` seals it first);
7. the completion is appended.

Re-running the command after any interruption finishes the erasure: an open intent is resumed with its own hash,
checked against the row's key while the row still holds one, with the classes of the registry in force and this run's
authority and reason, and without the registry gate (an erasure already begun is finished). Re-running it after a
completion changes nothing and writes nothing. A subject whose key is already a tombstone is still run, scoped by its
own references, so a class added later reaches it.
"""

import hmac
from dataclasses import dataclass

from django.conf import settings
from psycopg import errors

from agreements import keystore
from erasure import catalog, record, registry
from workflow import journal


class Refused(Exception):
    def __init__(self, code: str, detail=None):
        super().__init__(code)
        self.code = code
        self.detail = detail or []


@dataclass
class Outcome:
    status: str
    subject_ref: str
    changed: int
    handoffs: list
    journal_head: str
    resumed: bool = False
    retained: list = None
    keys_destroyed: int = 0  # references verified gone from both key directories (9kg.34)
    key_files_removed: int = 0


def _code(exc) -> str:
    return catalog.REFUSALS.get(getattr(exc, "sqlstate", "") or "", "database_error")


def _role_check(conn) -> None:
    roles = settings.CATALYST_DB_ROLES
    row = conn.execute(
        "SELECT r.rolsuper, pg_has_role(current_user, %s, 'MEMBER'), pg_has_role(current_user, %s, 'MEMBER'),"
        " pg_has_role(current_user, %s, 'MEMBER') FROM pg_catalog.pg_roles r WHERE r.rolname = current_user",
        [roles["retention"], roles["owner"], roles["app"]]).fetchone()
    conn.rollback()
    superuser, retention, owner, app = row
    if superuser or not retention or owner or app:
        raise Refused("not_the_retention_role")


def _email_key(conn, subject_ref):
    row = conn.execute("SELECT email_key FROM applications_application WHERE public_ref = %s", [subject_ref]).fetchone()
    if row is None:
        row = conn.execute("SELECT email_key FROM applications_invitation WHERE public_id = %s", [subject_ref]).fetchone()
    conn.rollback()
    return None if row is None else row[0]


def _call(conn, subject_ref, authority, reason, classes, *, commit: bool) -> dict:
    """One transaction around the function: committed for the erasure, rolled back for the dry run."""
    try:
        result = conn.execute("SELECT public.catalyst_erase(%s, %s, %s, %s)",
                              [subject_ref, authority, reason, list(classes)]).fetchone()[0]
    except errors.Error as exc:
        conn.rollback()
        raise Refused(_code(exc)) from None
    if commit:
        conn.commit()
    else:
        conn.rollback()
    return result


def erase(conn, subject_ref: str, authority: str, reason: str, rows=None) -> Outcome:
    """Erase the person behind `subject_ref` (an application's public_ref, or an invitation's public_id). `conn` is a
    psycopg connection as the retention role, not in a transaction. `rows` replaces the registry (tests).

    A new erasure needs a registry with no problem. Finishing an open intent does not (the erasure already began and
    stopping halfway helps nobody), but it takes nothing from the journal on trust: the classes come from the registry
    in force, the authority and reason from this command, and while the row still holds a real key the intent's hash
    must be that key's hash under the erasure key (an intent is also verified by its mac when folded)."""
    rows = registry.current() if rows is None else rows
    if not catalog.CODE.fullmatch(authority or "") or not catalog.CODE.fullmatch(reason or ""):
        raise Refused("malformed_request")
    try:
        secret = record.key()
        entries = journal.read()
    except record.RecordError as exc:
        raise Refused(f"record_{exc.code}") from None
    except journal.JournalError as exc:
        raise Refused(f"record_{exc.code}") from None
    _role_check(conn)
    forged = []
    state = record.fold(entries, secret, forged).get(str(subject_ref))
    if str(subject_ref) in forged:
        raise Refused("record_forged_entry")
    resumed = state is not None and state.open
    if not resumed:
        problems = registry.problems(rows)
        if problems:
            raise Refused("registry_undecided", problems)
    classes = [c for c in registry.SUBJECT_CLASSES if (rows.get(c) or {}).get("treatment") == registry.ANONYMIZE]
    destroy = (rows.get("signed_documents") or {}).get("treatment") == registry.DESTROY_KEY
    if not classes:
        raise Refused("registry_undecided", ["no_class_anonymized"])
    kid = record.key_id(secret)
    email_key = _email_key(conn, subject_ref)
    real_key = email_key is not None and not (email_key.startswith("erased:") and "@" not in email_key)
    if resumed:
        subject = state.intent.data["subject"]
        if real_key and not hmac.compare_digest(subject, record.subject_hash(email_key, secret)):
            raise Refused("record_subject_mismatch")
        if state.intent.data.get("key_id") != kid:
            raise Refused("record_key_mismatch")
        if destroy:
            _refuse_lingering_plaintext(conn, None, subject_ref=subject_ref)
    elif email_key is None:
        raise Refused("unknown_subject")
    else:
        dry = _call(conn, subject_ref, authority, reason, classes, commit=False)  # refusals surface before the intent
        if destroy and int(dry.get("custody_plaintext") or 0):
            raise Refused("custody_plaintext_unmigrated")  # a plaintext copy is beyond any key: seal it first
        if destroy:
            _refuse_lingering_plaintext(conn, dry.get("custody_keys") or [])
        keys_left = destroy and bool(_pending(dry.get("custody_keys") or []))
        if dry["status"] == "nothing_to_erase" and not keys_left:
            return Outcome("nothing_to_erase", str(subject_ref), 0, [], record.head_string(),
                           retained=_retained(dry, destroy and _all_destroyed(dry.get("custody_keys") or [])))
        if real_key:
            subject = record.subject_hash(email_key, secret)
        elif state is not None and state.intent is not None:
            subject = state.intent.data["subject"]  # the key is already a tombstone: the earlier record names the person
        else:
            raise Refused("record_subject_unknown")
        try:
            record.append_intent(subject_ref, subject, kid, authority, reason, classes, dry.get("handoffs") or [],
                                 _retained(dry, False), secret)
        except record.RecordError as exc:
            raise Refused(f"record_{exc.code}") from None
    try:
        result = _call(conn, subject_ref, authority, reason, classes, commit=True)
    except Refused as refusal:
        _complete(subject_ref, subject, kid, f"refused_{refusal.code}", 0, secret)
        raise
    refs = sorted(set(result.get("custody_keys") or []))
    performed = destroy and bool(_pending(refs))
    files = 0
    if destroy and refs:
        try:  # after the commit: an interruption leaves the intent open, and the next run destroys what is left
            files = keystore.destroy(str(subject_ref), refs)  # verifies every reference is gone, or raises
        except keystore.KeyStoreError as exc:
            raise Refused(f"custody_{exc.code}_after_commit") from None
    status = result["status"]
    if resumed and status == "nothing_to_erase":
        status = "already_erased"  # the interrupted run's transaction had committed
    elif status == "nothing_to_erase" and performed:
        status = "erased"  # the tables were already tombstoned; the custody keys were not (9kg.34)
    keys = len(refs) if destroy else 0
    _complete(subject_ref, subject, kid, status, result.get("changed", 0), secret, keys, files,
              custody_destroyed=destroy and bool(refs))
    folded = record.fold(journal.read(), secret).get(str(subject_ref))
    return Outcome(status, str(subject_ref), int(result.get("changed", 0)), sorted(folded.handoffs_owed),
                   record.head_string(), resumed, sorted(folded.retained), keys, files)


def _retained(result: dict, destroyed: bool) -> list:
    """What the erasure leaves in place. `custody_documents` leaves the list only once every key of the subject is
    verified gone (security review of PR #102, F1): the intent always names it, and the completion clears it."""
    retained = set(result.get("retained") or [])
    if destroyed:
        retained.discard("custody_documents")
    return sorted(retained)


def _pending(refs) -> list:
    """The subject's custody keys not yet destroyed: not journaled as destroyed, or still present in a key directory
    (an earlier erasure under `retain`, an interrupted destruction, a restored file). A reference absent but never
    journaled is pending too: it is journaled and verified, never assumed. A key store that cannot be read refuses."""
    try:
        destroyed = keystore.journaled_destroyed()
        return [ref for ref in refs if ref not in destroyed or any(keystore.present(ref))]
    except keystore.KeyStoreError as exc:
        raise Refused(f"custody_{exc.code}") from None


def _refuse_lingering_plaintext(conn, refs, subject_ref=None) -> None:
    """Review of PR #102, F3: a migrated document whose plaintext file is still on disk (a migration interrupted after
    its commit) is a copy no key destruction reaches. Refused, before any record, until `--migrate --confirm` removes
    it. Scoped by the subject's key references (or, on a resumed run, by its documents)."""
    from agreements import storage

    if refs is None:
        rows = conn.execute("SELECT d.storage_key FROM agreements_storeddocument d JOIN agreements_custodyenvelope e"
                            " ON e.document_id = d.id JOIN applications_application a ON a.id = d.application_id"
                            " WHERE e.migrated AND a.public_ref = %s", [subject_ref]).fetchall()
    elif refs:
        rows = conn.execute("SELECT d.storage_key FROM agreements_storeddocument d JOIN agreements_custodyenvelope e"
                            " ON e.document_id = d.id WHERE e.migrated AND e.key_ref = ANY(%s)", [list(refs)]).fetchall()
    else:
        rows = []
    conn.rollback()
    try:
        lingering = [key for (key,) in rows if storage.exists(key)]
    except storage.StorageError:
        raise Refused("custody_storage_unavailable") from None
    if lingering:
        raise Refused("custody_plaintext_lingering")


def _all_destroyed(refs) -> bool:
    return bool(refs) and not _pending(refs)


def _complete(subject_ref, subject, kid, status, changed, secret, keys_destroyed=0, key_files_removed=0,
              custody_destroyed=False):
    try:
        record.append_complete(subject_ref, subject, kid, status, changed, secret, keys_destroyed, key_files_removed,
                               custody_destroyed)
    except record.RecordError as exc:
        # The database transaction has committed; the intent stays open and the next run completes it.
        raise Refused(f"record_{exc.code}_after_commit") from None


def handoff(subject_ref: str, provider: str, completed_on: str) -> str:
    """Record the owner's completion of one manual provider deletion for an erased subject."""
    try:
        secret = record.key()
        state = record.fold(journal.read(), secret).get(str(subject_ref))
    except record.RecordError as exc:
        raise Refused(f"record_{exc.code}") from None
    except journal.JournalError as exc:
        raise Refused(f"record_{exc.code}") from None
    if state is None or not state.erased:
        raise Refused("not_erased")
    if provider not in state.handoffs_owed:
        raise Refused("handoff_not_owed")
    try:
        record.append_handoff(subject_ref, provider, completed_on, secret)
    except record.RecordError as exc:
        raise Refused(f"record_{exc.code}") from None
    return record.head_string()
