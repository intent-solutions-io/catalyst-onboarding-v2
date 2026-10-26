"""Replay of the durable erasure record after a restore (9kg.25; 026 section 6 option d; 029 section 6.2.1).

A restore takes the tables back to the backup's time T; every erasure made after T is undone in them, while the
durable record in the effect journal (erasure.record), outside the backup's rollback domain, still names it. The
order on a restored host is: restore, migrate, **replay**, review, lift (`catalyst_post_restore`).

The replay, run by the owner with the retention role's login (`catalyst_erasure_replay --expect-head <head>`):

1. verifies the record: the erasure key, the journal's chain, every entry's mac, and the head the owner kept out of
   band from the last erasure (`erasure.record.verify`). An emptied, replaced, truncated or rolled-back journal, a
   missing key or a forged entry refuses, and the restore stays held: missing, corrupt, stale or unavailable evidence
   never releases restored records;
2. folds the record and, for every subject with an erasure (completed or still open), calls
   `public.catalyst_erase_replay` (erasure 0004) in its own transaction, with the classes of the registry in force and
   the intent's authority and reason. The function is the erase function without its refusals for an open
   application, work in flight and an unfinished access revocation (the erasure passed them when it ran; the restored
   rows predate the closure), and it runs only while the restore hold is present. A subject the backup does not hold
   (created after T) is satisfied (`absent`); one the backup already held erased changes nothing (`already`); one
   whose restored key does not hash to the recorded subject is erased all the same, by its public reference, a random
   identifier that never recurs for another person, and reported (`mismatched`);
3. appends one `erasures_replayed` marker, with its mac, keyed by the restore it answers (the seq of the journal's
   last `restore` entry, 0 for a hold placed by hand) and naming the seq of the last erasure entry it covered.

The post-restore review and lift re-read the marker (`state`): both refuse until a verified marker for the current
restore covers every erasure entry in the journal, so an erasure made during the hold (a later entry) needs another
replay. A second replay is harmless (every subject is `already`) and writes another marker; an interrupted replay
wrote no marker and is simply run again.

What the refusals guarded is settled by the review, as the owner, before anything runs (config.post_restore
`settle_erased`): the work of erased subjects is cancelled, and a subject still open or with an access revocation that
is not final after the journal's replay gets a `restore_effect_*` item the lift waits for. Custody needs nothing here:
a destroyed key is outside the rollback domain, and the lift's key sweep removes any key file journaled destroyed.
"""

import hmac

from psycopg import errors

from erasure import record, registry
from erasure.service import Refused, _code, _email_key, _role_check
from workflow import journal

MARKER = "erasures_replayed"


def restore_seq(entries) -> int:
    """The seq of the journal's last `restore` entry (written by catalyst_restore), 0 when there is none."""
    return max((e.seq for e in entries if e.kind == "restore"), default=0)


def marker_key(seq: int) -> str:
    return f"erasure_replay:{seq}"


def last_erasure_seq(entries) -> int:
    return max((e.seq for e in entries if e.kind.startswith("erasure_")), default=0)


def state(entries, secret: bytes | None, since=None) -> str:
    """`replayed` when a marker for the current restore, written at or after `since` (the restore hold's creation:
    security review of PR #103, finding 2), covers every erasure entry; otherwise `unreplayed` (no such marker),
    `forged_marker` (none verifies) or `stale` (an erasure after the marker). With `secret` the marker's mac is
    verified (the lift); without it (the review, which holds no key: finding 4) only its presence and coverage are."""
    seq = restore_seq(entries)
    markers = [e for e in entries if e.kind == MARKER and e.key == marker_key(seq) and e.seq > seq
               and (since is None or e.when >= since)]
    verified = [e for e in markers if secret is None
                or hmac.compare_digest(str(e.data.get("mac", "")), record.entry_mac(MARKER, e.key, e.data, secret))]
    if not verified:
        return "forged_marker" if markers else "unreplayed"
    through = verified[-1].data.get("through")
    if not isinstance(through, int) or isinstance(through, bool) or through < last_erasure_seq(entries):
        return "stale"
    return "replayed"


def mark(entries, secret: bytes, subjects=0, erased=0, already=0, absent=0) -> int:
    """Append the `erasures_replayed` marker for the journal `entries` were read from; returns the restore's seq."""
    seq = restore_seq(entries)
    data = {"restore": seq, "through": last_erasure_seq(entries), "subjects": subjects, "erased": erased,
            "already": already, "absent": absent, "key_id": record.key_id(secret), "phase": "done"}
    data["mac"] = record.entry_mac(MARKER, marker_key(seq), data, secret)
    if journal.append(MARKER, marker_key(seq), data) is None:
        raise Refused("record_unwritable")  # the failure is logged and counted by the journal; run the replay again
    return seq


def current_state(since=None, verify: bool = True) -> str:
    """`state` of the journal as it is (with the erasure key when `verify`); a code when either cannot be read."""
    try:
        return state(journal.read(), record.key() if verify else None, since)
    except record.RecordError as exc:
        return exc.code
    except journal.JournalError as exc:
        return exc.code


def _real(key) -> bool:
    return bool(key) and not (key.startswith("erased:") and "@" not in key)


def _keys_by_subject(conn, secret: bytes) -> dict:
    """{subject hash: {real email key: an application's or invitation's public reference, or None}} over the restored
    rows the retention role reads: applications, invitations and first-generation member records (data review of
    PR #103, finding 1: a person invited before the backup and erased under an application made after it)."""
    found = {}
    for query in ("SELECT email_key, public_ref FROM applications_application",
                  "SELECT email_key, public_id FROM applications_invitation",
                  "SELECT email_key, NULL::uuid FROM applications_memberagreementonfile"):
        for key, ref in conn.execute(query).fetchall():
            if _real(key):
                entry = found.setdefault(record.subject_hash(key, secret), {})
                if entry.get(key) is None:
                    entry[key] = str(ref) if ref is not None else None
    conn.rollback()
    return found


def _plaintext_restored(conn) -> list:
    """Storage keys of erased subjects' documents restored with no envelope (stored in the clear before 9kg.34) whose
    file is back on disk: a copy no key destruction reaches (data review of PR #103, finding 2)."""
    from agreements import storage

    rows = conn.execute("SELECT d.storage_key FROM agreements_storeddocument d JOIN applications_application a"
                        " ON a.id = d.application_id LEFT JOIN agreements_custodyenvelope e ON e.document_id = d.id"
                        " WHERE e.id IS NULL AND a.email_key LIKE 'erased:%%' AND strpos(a.email_key, '@') = 0").fetchall()
    conn.rollback()
    if not rows:
        return []
    try:
        return [key for (key,) in rows if storage.exists(key)]
    except storage.StorageError:
        raise Refused("custody_storage_unavailable") from None


def replay(conn, expected_head: str, rows=None) -> dict:
    """Re-apply every recorded erasure to the restored database. `conn` is a psycopg connection as the retention role,
    not in a transaction; `expected_head` is the head printed by the last erasure or handoff (`none` before the first
    erasure); `rows` replaces the registry (tests). Raises Refused; returns counts and public references only."""
    try:
        record.verify(expected_head)  # the key, the chain, every mac, and the out-of-band head
        secret = record.key()
        entries = journal.read()
    except record.RecordError as exc:
        raise Refused(f"record_{exc.code}") from None
    except journal.JournalError as exc:
        raise Refused(f"record_{exc.code}") from None
    _role_check(conn)
    subjects = {ref: s for ref, s in record.fold(entries, secret).items() if s.erased or s.open}
    current, destroy = [], False
    if subjects:
        rows = registry.current() if rows is None else rows
        problems = registry.problems(rows)
        if problems:
            raise Refused("registry_undecided", problems)
        current = registry.anonymized_classes(rows)
        destroy = (rows.get("signed_documents") or {}).get("treatment") == registry.DESTROY_KEY
    own = {ref: _email_key(conn, ref) for ref in subjects}
    # Data review of PR #103, finding 3: nothing changes an application's key, so a restored key that does not hash to
    # the recorded subject is not a moved address but an altered row or record. Refuse before anything is erased.
    mismatched = sorted(ref for ref, key in own.items() if _real(key) and not hmac.compare_digest(
        subjects[ref].intent.data["subject"], record.subject_hash(key, secret)))
    if mismatched:
        raise Refused("replay_subject_mismatch", mismatched)
    by_subject = _keys_by_subject(conn, secret) if subjects else {}
    counts = {"erased": 0, "already": 0, "absent": 0}
    matched = 0
    for ref, subject in sorted(subjects.items(), key=lambda item: item[1].intent.seq):
        intent = subject.intent.data
        # Finding 6: the classes the erasure anonymized when it ran, with those the registry anonymizes now.
        classes = [c for c in registry.SUBJECT_CLASSES if c in current or c in (intent.get("classes") or [])]
        targets, covered = [], set()
        if own[ref] is not None:
            targets.append((ref, None))
            covered.add(own[ref])
        for key, entry in by_subject.get(intent["subject"], {}).items():
            if key not in covered:
                targets.append((entry, None) if entry else (ref, key))  # an entry point, or the key itself
                covered.add(key)
        matched += max(0, len(targets) - (own[ref] is not None))
        statuses = []
        for target, key in targets:
            try:
                result = conn.execute("SELECT public.catalyst_erase_replay(%s, %s, %s, %s, %s)",
                                      [target, intent["authority"], intent["reason"], classes, key]).fetchone()[0]
            except errors.Error as exc:
                conn.rollback()
                code = _code(exc)
                if code == "unknown_subject":
                    continue
                raise Refused(f"replay_{code}", [ref]) from None
            conn.commit()
            statuses.append(result["status"])
        if not statuses:
            counts["absent"] += 1  # nothing of the person is in the restored tables
        else:
            counts["erased" if "erased" in statuses else "already"] += 1
    if destroy and _plaintext_restored(conn):
        # The older set predates sealing: its plaintext copy of an erased subject's document is back. No marker until
        # the owner removes those files (catalyst_custody_keys --status lists lingering plaintext) and replays again.
        raise Refused("replay_custody_plaintext_restored")
    seq = mark(entries, secret, subjects=len(subjects), **counts)
    return {"status": "replayed", "restore": seq, "subjects": len(subjects), **counts, "matched_by_key": matched,
            "open": sorted(ref for ref, s in subjects.items() if s.open), "journal_head": record.head_string()}
