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
6. the completion is appended.

Re-running the command after any interruption finishes the erasure (an open intent is resumed with its own hash);
re-running it after a completion changes nothing and writes nothing.
"""

from dataclasses import dataclass

from django.conf import settings
from psycopg import errors

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
    psycopg connection as the retention role, not in a transaction. `rows` replaces the registry (tests)."""
    rows = registry.current() if rows is None else rows
    problems = registry.problems(rows)
    if problems:
        raise Refused("registry_undecided", problems)
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
    classes = registry.anonymized_classes(rows)
    kid = record.key_id(secret)
    state = record.fold(entries).get(str(subject_ref))
    resumed = state is not None and state.open
    email_key = _email_key(conn, subject_ref)
    if resumed:
        intent = state.intent.data
        subject, classes, authority, reason = intent["subject"], intent["classes"], intent["authority"], intent["reason"]
        kid = intent["key_id"]
    elif email_key is None:
        raise Refused("unknown_subject")
    elif email_key.startswith("erased:"):
        # Already erased (by this reference or another of the same person): nothing to do and nothing to record.
        return Outcome("already_erased", str(subject_ref), 0, [], record.head_string())
    else:
        subject = record.subject_hash(email_key, secret)
        dry = _call(conn, subject_ref, authority, reason, classes, commit=False)  # refusals surface before the intent
        try:
            record.append_intent(subject_ref, subject, kid, authority, reason, classes, dry.get("handoffs") or [])
        except record.RecordError as exc:
            raise Refused(f"record_{exc.code}") from None
    try:
        result = _call(conn, subject_ref, authority, reason, classes, commit=True)
    except Refused as refusal:
        _complete(subject_ref, subject, kid, f"refused_{refusal.code}", 0)
        raise
    _complete(subject_ref, subject, kid, result["status"], result.get("changed", 0))
    owed = state.intent.data.get("handoffs", []) if resumed else (result.get("handoffs") or [])
    return Outcome(result["status"], str(subject_ref), int(result.get("changed", 0)), sorted(owed),
                   record.head_string(), resumed)


def _complete(subject_ref, subject, kid, status, changed):
    try:
        record.append_complete(subject_ref, subject, kid, status, changed)
    except record.RecordError as exc:
        # The database transaction has committed; the intent stays open and the next run completes it.
        raise Refused(f"record_{exc.code}_after_commit") from None


def handoff(subject_ref: str, provider: str, completed_on: str) -> str:
    """Record the owner's completion of one manual provider deletion for an erased subject."""
    try:
        state = record.fold(journal.read()).get(str(subject_ref))
    except journal.JournalError as exc:
        raise Refused(f"record_{exc.code}") from None
    if state is None or not state.erased:
        raise Refused("not_erased")
    if provider not in state.handoffs_owed:
        raise Refused("handoff_not_owed")
    try:
        record.append_handoff(subject_ref, provider, completed_on)
    except record.RecordError as exc:
        raise Refused(f"record_{exc.code}") from None
    return record.head_string()
