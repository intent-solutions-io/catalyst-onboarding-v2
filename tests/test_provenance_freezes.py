"""9kg.5: the database itself freezes inbound message provenance and the identity of outbound attempts and reply
links, for every role (correspondence migration 0017; 016 section 10.13; ADR-14).

Proved through real connections as each role: the application role is refused by its grants, the owner by the
trigger, and the retention role has no grant at all. The one exception, the audited retention path, is exercised
the way 9kg.32 will use it: a security-definer function owned by the owner, executable by the retention role only,
runs the anonymizing update while the session stays the retention login. Tests commit through their own
connections and rely on the privileged reset (tests/conftest.py).
"""

import uuid

import pytest
from django.conf import settings
from django.db.models.functions import Now
from psycopg import errors

from applications.models import Application
from correspondence.models import InboundMessage, OutboundMessage, Question, QuestionReplyLink
from tests.support import manage_as_owner
from workflow.models import PendingAction

ROLES = settings.CATALYST_DB_ROLES
FROZEN = "frozen"
REASON = "synthetic erasure of a person under POL-10"
ERASE = "catalyst_probe_erase"  # the test's stand-in for 9kg.32's erase function; created and dropped per test


@pytest.fixture
def connect(privileged_reset):
    return privileged_reset.connect


def refused(conn, sql, params=(), match=None):
    with pytest.raises(errors.InsufficientPrivilege, match=match):
        conn.execute(sql, params)
    conn.rollback()


def application(key="frozen@example.test"):
    return Application.objects.create(email=key, email_key=key, display_name="Synthetic")


def inbound(app=None):
    return InboundMessage.objects.create(
        mailbox_ref="synthetic-mailbox", message_id_header="<reply-1@applicant.example.test>",
        in_reply_to="<q@catalyst.example.test>", references="<q@catalyst.example.test>",
        from_address="Ada <ada@applicant.example.test>", from_normalized="ada@applicant.example.test",
        auto_markers={"precedence": "list"}, date_header="Mon, 1 Jan 2026 10:00:00 +0000", internal_date="01-Jan-2026",
        size=1234, original_sha256=uuid.uuid4().hex * 2, derived_text="Thanks, done.",
        attachments=[{"name": "cv.pdf", "size": 10}], application=app)


def outbound(app):
    action = PendingAction.objects.create(kind="send_verification", subject_type="application", subject_id=uuid.uuid4(),
                                          idempotency_key=f"sv:{uuid.uuid4()}")
    return OutboundMessage.objects.create(application=app, pending_action=action, attempt_number=1,
                                          template_key="verification", template_version="1",
                                          recipient="ada@applicant.example.test", message_id="", status="accepted")


def reply_link(app):
    question = Question.objects.create(application=app, text="Which year did you graduate?")
    return QuestionReplyLink.objects.create(question=question, inbound_message=inbound(app))


def erase_function(owner, table, assignment):
    """9kg.32's shape: a security-definer function owned by the owner that the retention role, and only it, may
    execute. The update inside it runs as the owner; the session is still the retention login."""
    owner.execute(f"CREATE FUNCTION public.{ERASE}(target bigint) RETURNS void LANGUAGE sql SECURITY DEFINER"
                  f" SET search_path = public, pg_temp AS $$ UPDATE public.{table} SET {assignment} WHERE id = target $$")
    owner.execute(f"REVOKE ALL ON FUNCTION public.{ERASE}(bigint) FROM PUBLIC")
    owner.execute(f'GRANT EXECUTE ON FUNCTION public.{ERASE}(bigint) TO "{ROLES["retention"]}"')


def drop_erase_function(owner):
    owner.execute(f"DROP FUNCTION IF EXISTS public.{ERASE}(bigint)")


# --- inbound messages --------------------------------------------------------------------------------------

INBOUND_FROZEN = [
    "SET received_at = now() - interval '1 day'", "SET size = size + 1", "SET original_sha256 = repeat('b', 64)",
    "SET public_id = gen_random_uuid()", "SET mailbox_ref = 'other-mailbox'", "SET attachments = '[]'",
    "SET auto_markers = '{}'", "SET date_header = ''", "SET internal_date = ''", "SET message_id_header = '<x@y>'",
    "SET in_reply_to = ''", "SET \"references\" = ''", "SET from_address = ''", "SET from_normalized = ''",
]


@pytest.mark.parametrize("change", INBOUND_FROZEN, ids=[c.split()[1] for c in INBOUND_FROZEN])
@pytest.mark.parametrize("role", ["app", "owner"])
def test_9kg5_a_frozen_inbound_column_refuses_an_update_for_every_role(connect, role, change):
    message = inbound()
    # The application role is stopped by its grants, the owner by the trigger itself.
    refused(connect(role), f"UPDATE correspondence_inboundmessage {change} WHERE id = %s", [message.pk],
            match="permission denied" if role == "app" else FROZEN)


def test_9kg5_the_updatable_inbound_columns_still_update_through_the_application_role_and_the_owner(connect):
    app = application()
    message = inbound()
    InboundMessage.objects.filter(pk=message.pk).update(  # the application role, through the ORM
        status="awaiting_processing", classification="human", application=app, from_matches_verified_address=True,
        auth_evidence="pass", trust_decision="trusted", identity_state="established", processed_at=Now(),
        derived_text="re-derived", derived_text_sha256="c" * 64, derivation_version=2, redaction_version=2,
        truncated=True, truncated_at_chars=9, omitted_parts=[{"part": "x"}], redactions={"confirmation_link": 1})
    message.refresh_from_db()
    assert (message.status, message.application_id, message.derived_text) == ("awaiting_processing", app.pk, "re-derived")
    assert message.from_matches_verified_address and message.derivation_version == 2
    owner = connect("owner", autocommit=True)
    assert owner.execute("UPDATE correspondence_inboundmessage SET status = 'exception', exception_reason = 'synthetic'"
                         " WHERE id = %s", [message.pk]).rowcount == 1
    assert owner.execute("SELECT from_address, original_sha256, received_at = %s FROM correspondence_inboundmessage WHERE id = %s",
                         [message.received_at, message.pk]).fetchone() == (message.from_address, message.original_sha256, True)


@pytest.mark.parametrize("role", ["app", "owner", "retention"])
def test_9kg5_no_role_deletes_or_truncates_inbound_messages(connect, role):
    message = inbound()
    conn = connect(role)
    if role == "retention":  # the audited retention path is anonymization, never deletion
        conn.execute("SELECT set_config('catalyst.retention_reason', %s, true)", [REASON])
    refused(conn, "DELETE FROM correspondence_inboundmessage WHERE id = %s", [message.pk])
    refused(conn, "TRUNCATE correspondence_inboundmessage CASCADE")
    assert InboundMessage.objects.filter(pk=message.pk).exists()


def test_9kg5_the_audited_retention_path_anonymizes_the_personal_inbound_columns_and_nothing_else(connect):
    app = application()
    linked, orphan = inbound(app), inbound()  # with and without an application: both are erasable
    owner = connect("owner", autocommit=True)
    erase_function(owner, "correspondence_inboundmessage",
                   "from_address = 'erased', from_normalized = 'erased:' || id, message_id_header = '', in_reply_to = '',"
                   " \"references\" = '', attachments = '[]'")
    try:
        retention = connect("retention")
        # Without a stated reason the branch does not open, even for the retention login through the function.
        refused(retention, f"SELECT {ERASE}(%s)", [linked.pk], match="personal columns are frozen")
        # The owner calling the same function is not a retention member: refused.
        refused(owner, f"SELECT {ERASE}(%s)", [linked.pk], match="personal columns are frozen")
        for message in (linked, orphan):
            retention.execute("SELECT set_config('catalyst.retention_reason', %s, true)", [REASON])
            retention.execute(f"SELECT {ERASE}(%s)", [message.pk])
            retention.commit()
            message.refresh_from_db()
            assert (message.from_address, message.from_normalized, message.attachments) == ("erased", f"erased:{message.pk}", [])
            assert message.message_id_header == "" and message.references == ""
            assert len(message.original_sha256) == 64 and message.size == 1234  # the fixed provenance is untouched
        audited = retention.execute(
            "SELECT actor, row_id, application_id, reason, length(row_sha256) FROM applications_retentionaudit"
            " WHERE table_name = 'correspondence_inboundmessage' ORDER BY row_id").fetchall()
        assert audited == [(ROLES["retention"], linked.pk, app.pk, REASON, 64), (ROLES["retention"], orphan.pk, 0, REASON, 64)]
        retention.commit()
        # The path reaches the personal columns only: a fixed provenance column stays frozen even with a reason.
        drop_erase_function(owner)
        erase_function(owner, "correspondence_inboundmessage", "original_sha256 = repeat('d', 64), from_address = ''")
        retention.execute("SELECT set_config('catalyst.retention_reason', %s, true)", [REASON])
        refused(retention, f"SELECT {ERASE}(%s)", [linked.pk], match="provenance and identity columns are frozen")
    finally:
        drop_erase_function(owner)


# --- outbound attempts -------------------------------------------------------------------------------------

OUTBOUND_FROZEN = [
    "SET attempt_number = 2", "SET template_key = 'x'", "SET template_version = '9'", "SET recipient = 'x@example.test'",
    "SET approved_message_id = 1", "SET attempt_series = 1", "SET rendered_sha256 = repeat('e', 64)",
    "SET pending_action_id = pending_action_id + 1", "SET application_id = application_id + 1",
]


@pytest.mark.parametrize("change", OUTBOUND_FROZEN, ids=[c.split()[1] for c in OUTBOUND_FROZEN])
@pytest.mark.parametrize("role", ["app", "owner"])
def test_9kg5_a_frozen_outbound_identity_column_refuses_an_update_for_every_role(connect, role, change):
    attempt = outbound(application())
    refused(connect(role), f"UPDATE correspondence_outboundmessage {change} WHERE id = %s", [attempt.pk],
            match="permission denied" if role == "app" else FROZEN)


@pytest.mark.parametrize("role", ["app", "owner"])
def test_9kg5_an_outbound_message_id_is_set_once(connect, role):
    attempt = outbound(application())
    conn = connect(role, autocommit=True)
    assert conn.execute("UPDATE correspondence_outboundmessage SET message_id = '<a1@catalyst.example.test>' WHERE id = %s",
                        [attempt.pk]).rowcount == 1  # empty at insert (the S1 path): filled once
    refused(conn, "UPDATE correspondence_outboundmessage SET message_id = '<a2@catalyst.example.test>' WHERE id = %s",
            [attempt.pk], match="set once")
    refused(conn, "UPDATE correspondence_outboundmessage SET message_id = '' WHERE id = %s", [attempt.pk], match="set once")
    assert OutboundMessage.objects.get(pk=attempt.pk).message_id == "<a1@catalyst.example.test>"


def test_9kg5_the_outbound_delivery_columns_still_update_and_the_owner_still_ages_an_attempt(connect):
    attempt = outbound(application())
    app = connect("app", autocommit=True)
    assert app.execute("UPDATE correspondence_outboundmessage SET status = 'accepted_by_server', sent_at = now(),"
                       " protocol_phase_reached = 'data', smtp_reply_code = 250, server_accepted_at = now(),"
                       " filed_copy_state = 'pending' WHERE id = %s", [attempt.pk]).rowcount == 1
    owner = connect("owner", autocommit=True)  # how tests age an attempt (G3): created_at is not identity
    assert owner.execute("UPDATE correspondence_outboundmessage SET created_at = now() - interval '1 day' WHERE id = %s",
                         [attempt.pk]).rowcount == 1
    assert OutboundMessage.objects.get(pk=attempt.pk).status == "accepted_by_server"


@pytest.mark.parametrize("role", ["app", "owner", "retention"])
def test_9kg5_no_role_deletes_or_truncates_outbound_attempts(connect, role):
    attempt = outbound(application())
    conn = connect(role)
    if role == "retention":
        conn.execute("SELECT set_config('catalyst.retention_reason', %s, true)", [REASON])
    refused(conn, "DELETE FROM correspondence_outboundmessage WHERE id = %s", [attempt.pk])
    refused(conn, "TRUNCATE correspondence_outboundmessage CASCADE")


def test_9kg5_the_audited_retention_path_anonymizes_an_outbound_recipient(connect):
    app = application()
    attempt = outbound(app)
    owner = connect("owner", autocommit=True)
    erase_function(owner, "correspondence_outboundmessage", "recipient = 'erased'")
    try:
        retention = connect("retention")
        refused(retention, f"SELECT {ERASE}(%s)", [attempt.pk], match="personal columns are frozen")  # no reason
        retention.execute("SELECT set_config('catalyst.retention_reason', %s, true)", [REASON])
        retention.execute(f"SELECT {ERASE}(%s)", [attempt.pk])
        retention.commit()
        assert OutboundMessage.objects.get(pk=attempt.pk).recipient == "erased"
        assert retention.execute("SELECT actor, row_id, application_id, reason FROM applications_retentionaudit"
                                 " WHERE table_name = 'correspondence_outboundmessage'").fetchall() == [
            (ROLES["retention"], attempt.pk, app.pk, REASON)]
        retention.commit()
        drop_erase_function(owner)
        erase_function(owner, "correspondence_outboundmessage", "recipient = 'erased', attempt_number = 7")
        retention.execute("SELECT set_config('catalyst.retention_reason', %s, true)", [REASON])
        refused(retention, f"SELECT {ERASE}(%s)", [attempt.pk], match="provenance and identity columns are frozen")
    finally:
        drop_erase_function(owner)


# --- reply links --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("role", ["app", "owner"])
def test_9kg5_a_reply_link_keeps_its_question_and_message_and_is_never_deleted(connect, role):
    app = application()
    link = reply_link(app)
    other = Question.objects.create(application=app, text="And the other thing?")
    conn = connect(role)
    kind = "permission denied" if role == "app" else "frozen"
    refused(conn, "UPDATE correspondence_questionreplylink SET question_id = %s WHERE id = %s", [other.pk, link.pk], match=kind)
    refused(conn, "UPDATE correspondence_questionreplylink SET inbound_message_id = %s WHERE id = %s",
            [inbound(app).pk, link.pk], match=kind)
    refused(conn, "DELETE FROM correspondence_questionreplylink WHERE id = %s", [link.pk])
    refused(conn, "TRUNCATE correspondence_questionreplylink")
    conn.autocommit = True
    assert conn.execute("UPDATE correspondence_questionreplylink SET state = 'applied', outcome = 'satisfied',"
                        " actor_ref = 'staff:1', updated_at = now() WHERE id = %s", [link.pk]).rowcount == 1
    assert QuestionReplyLink.objects.get(pk=link.pk).state == "applied"


# --- the functions and the migration ----------------------------------------------------------------------

@pytest.mark.parametrize(("function", "definer"), [
    ("catalyst_inbound_provenance_frozen", True), ("catalyst_outbound_identity_frozen", True),
    ("catalyst_reply_link_identity_frozen", False),
])
@pytest.mark.django_db
def test_9kg5_the_freeze_functions_are_owned_fixed_and_not_executable_by_the_application_role(function, definer):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner), has_function_privilege(%s, p.oid, 'EXECUTE')"
                       " FROM pg_proc p WHERE p.oid = %s::regprocedure", [ROLES["app"], f"public.{function}()"])
        security_definer, config, owner, app_can_execute = cursor.fetchone()
    assert security_definer is definer  # only the two that write the audit row run as the owner
    assert "search_path=public, pg_temp" in config and owner == ROLES["owner"] and app_can_execute is False


def test_9kg5_the_freeze_migration_reverses_and_reapplies_and_keeps_the_rows(connect):
    message, attempt = inbound(), outbound(application())
    owner = connect("owner", autocommit=True)

    def triggers():
        return owner.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgname IN ('catalyst_inbound_provenance_frozen',"
            " 'catalyst_outbound_identity_frozen', 'catalyst_reply_link_identity_frozen') OR (tgname = 'catalyst_no_truncate'"
            " AND tgrelid IN ('correspondence_inboundmessage'::regclass, 'correspondence_outboundmessage'::regclass,"
            " 'correspondence_questionreplylink'::regclass))").fetchone()[0]

    assert triggers() == 6
    manage_as_owner("migrate", "correspondence", "0016", "--verbosity", "0")
    assert triggers() == 0
    manage_as_owner("migrate", "--verbosity", "0")
    assert triggers() == 6
    assert InboundMessage.objects.filter(pk=message.pk).exists() and OutboundMessage.objects.filter(pk=attempt.pk).exists()
    refused(owner, "UPDATE correspondence_inboundmessage SET received_at = now() WHERE id = %s", [message.pk], match=FROZEN)
