"""The erasure map (9kg.32; 029 section 6.1): every table and every column of the schema, classified, and the SQL the
erasure migration installs from it.

Each column is one of:

- a **subject** column (`Subject(class, tombstone)`): personal data of an applicant, in one of the registry's subject
  classes (erasure.registry); the erase function sets it to its tombstone for the subject's rows when the class is
  anonymized, and the table's protective trigger admits exactly that change on the audited path;
- **staff**: personal data of staff (accounts, staff references such as `user:<pk>`, approvals), governed by POL-13,
  never part of an applicant's erasure;
- **secret**: credential material (password hashes, token digests, device keys): never applicant content;
- **non-personal**: identifiers, codes, states, times, counts, digests of high-entropy content and configuration.

`tests/test_erasure.py` keeps this map complete: every table and column in the database must appear here, and
nothing here may name a column that does not exist. A new table or column therefore fails the suite until it is
classified, and a new subject column on a protected table also needs the table's trigger to carry the erasure branch.

Tombstones (each idempotent: a tombstone of a tombstone is the same value):

- `text`: `[erased]`, keeping an empty string or a null as it is;
- `empty`: the empty string (a digest of a low-entropy value, a deduplication key);
- `object`, `array`: an empty JSON object or array;
- `object_or_null`: an empty object, keeping a null as it is;
- `key`: `erased:<the row's public uuid>`, a unique key that can never equal a real email key (no `@`), for the email
  keys partial unique constraints and lookups use (unique indexes on the tombstones, applications migration 0009);
- `local_part`: `erased-<the row's public uuid without dashes>`, unique and valid for the mailbox-name check;
- `notes`: a JSON object of criteria whose `note` members become `[erased]`; ratings and codes are kept;
- `delete`: the row is deleted (only the intake throttle bucket, a rate counter keyed on an unkeyed digest of the
  email key, which has no protective trigger and no history value).

The rows of a subject: every application with the subject's email key (`v_apps`, their `v_refs`), and the rows keyed
on the email key itself (`v_key`): invitations, the member-on-file record, inbound mail from that address and the throttle
bucket. Each table names its selector over those three values.
"""

import re
from dataclasses import dataclass

TEXT, EMPTY, OBJECT, ARRAY, OBJECT_OR_NULL, KEY, LOCAL_PART, NOTES, DELETE = (
    "text", "empty", "object", "array", "object_or_null", "key", "local_part", "notes", "delete")
ERASED = "[erased]"
CODE = re.compile(r"[a-z0-9_.:-]{3,64}")  # authority and reason: codes, never free text (the audit table checks it too)
TERMINAL_STAGES = ("declined", "withdrawn", "closed")
FINAL_REVOCATION_STATES = ("verified", "applied_unverified", "not_applicable", "exception")  # provisioning.closure.FINAL
OPEN_ACTION_STATUSES = ("queued", "running", "held", "uncertain")


@dataclass(frozen=True)
class Subject:
    cls: str
    tombstone: str
    source: str = ""  # the uuid column a `key` or `local_part` tombstone is built from


@dataclass(frozen=True)
class Table:
    selector: str = ""  # SQL over v_apps (bigint[]), v_refs (uuid[]) and v_key (text): the subject's rows
    subject: dict = None  # {column: Subject}
    staff: str = ""
    secret: str = ""
    other: str = ""  # non-personal columns, space-separated

    def columns(self) -> dict:
        out = {c: "staff" for c in self.staff.split()}
        out.update({c: "secret" for c in self.secret.split()})
        out.update({c: "non_personal" for c in self.other.split()})
        out.update({c: s for c, s in (self.subject or {}).items()})
        return out


def S(cls, tombstone=TEXT, source=""):
    return Subject(cls, tombstone, source)


APP = "application_id = ANY(v_apps)"
REQUEST = "request_id IN (SELECT q.id FROM public.provisioning_provisioningrequest q WHERE q.application_id = ANY(v_apps))"

TABLES = {
    # --- accounts (staff; POL-13) and the public-endpoint throttle -------------------------------------------------
    "accounts_loginthrottle": Table(staff="key", other="id failures locked_until updated_at"),
    "accounts_requestthrottle": Table(
        selector="key = pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to('intake-address:' || v_key, 'UTF8')), 'hex')",
        subject={"key": S("throttle_keys", DELETE)}, other="id count window_start updated_at"),
    "accounts_staffrolegrant": Table(staff="actor_ref", other="id role kind target action approval_ref recorded_at user_id"),
    "accounts_user": Table(staff="username first_name last_name email last_login date_joined", secret="password",
                           other="id is_superuser is_staff is_active"),
    "accounts_user_groups": Table(other="id user_id group_id"),
    "accounts_user_user_permissions": Table(other="id user_id permission_id"),
    # --- agreements --------------------------------------------------------------------------------------------------
    "agreements_agreementdetailsversion": Table(
        selector=APP, subject={"values": S("agreement_records", OBJECT), "values_sha256": S("agreement_records", EMPTY)},
        staff="recorded_by confirmed_by",
        other="id public_id version status confirmed_at created_at agreement_type_id application_id"),
    "agreements_agreementinstance": Table(other=(
        "id public_id external_key envelope_id issue_status signing_status custody_status created_at updated_at"
        " application_id template_version_id agreement_type_id cancel_requested_at replaced_at replacement_reason")),
    "agreements_agreementrecipient": Table(
        # Staff recipients (the countersigner) are staff data: only the applicant's rows are the subject's.
        selector="who = 'applicant' AND instance_id IN (SELECT i.id FROM public.agreements_agreementinstance i"
                 " WHERE i.application_id = ANY(v_apps))",
        subject={"name": S("agreement_records"), "email": S("agreement_records")},
        other="id role signing_order required who instance_id"),
    "agreements_agreementtemplateversion": Table(staff="approved_by", other=(
        "id version provider_template_ref provider_template_number recipient_slots pdf_sha256 status approved_at"
        " created_at agreement_type_id")),
    "agreements_agreementtype": Table(other="id key order required gate"),
    "agreements_documentaccess": Table(
        selector="document_id IN (SELECT d.id FROM public.agreements_storeddocument d WHERE d.application_id = ANY(v_apps))",
        subject={"reason": S("staff_notes")}, staff="actor_ref", other="id requested_ref outcome at document_id"),
    "agreements_envelopeattempt": Table(other=(
        "id public_id step external_key pending_action_id outcome outcome_code envelope_id created_at finished_at"
        " instance_id")),
    "agreements_providerobservation": Table(other=(  # recipients: role, order and signing state only
        "id source event envelope_status recipients identity_match recipients_match all_required_signed content_sha256"
        " observed_at created_txid application_id instance_id")),
    "agreements_storeddocument": Table(other=(  # the PDF itself is in custody: registry row signed_documents (9kg.34)
        "id public_id envelope_id item_id version storage_key sha256 size stored_at application_id instance_id"
        " observation_id")),
    "agreements_custodyenvelope": Table(other=(  # 9kg.34: random references, digests and sizes; no key material
        "id storage_key scheme key_ref wrapping_key_id cipher_sha256 cipher_size migrated sealed_at document_id")),
    # --- applications --------------------------------------------------------------------------------------------
    "applications_application": Table(
        selector="id = ANY(v_apps)",
        subject={"email": S("application_identity"), "email_key": S("application_identity", KEY, "public_ref"),
                 "display_name": S("application_identity")},
        other="id public_ref stage contact_verified_at next_version_number created_at updated_at"),
    "applications_applicationevent": Table(
        selector=APP, subject={"data": S("history_events", OBJECT)}, staff="actor_ref",
        other="id kind actor_type occurred_at application_id created_txid"),  # created_txid: the guard's marker
    "applications_contactchallenge": Table(
        selector=APP, subject={"email_at_issue": S("application_identity")},
        other="id public_id created_at expires_at used_at superseded_at application_id"),
    "applications_invitation": Table(
        selector="email_key = v_key OR application_id = ANY(v_apps)",
        subject={"email_key": S("invitations", KEY, "public_id"), "note": S("invitations")}, staff="issued_by",
        other=("id public_id issued_at expires_at used_at superseded_at updated_at application_id"
               " notice_template_version notice_sha256 mail_template_sha256")),
    "applications_memberagreementonfile": Table(
        selector="email_key = v_key", subject={"email_key": S("member_on_file", KEY, "public_id")}, staff="recorded_by",
        other="id public_id covers completion_verified recorded_at superseded_at"),  # covers: owner-typed labels
    "applications_retentionaudit": Table(
        selector=APP, subject={"reason": S("audit_residue"), "row_sha256": S("audit_residue", EMPTY)},
        other="id at actor table_name row_id application_id"),  # actor: a database role name
    "applications_submissionversion": Table(
        selector=APP, subject={"submitted_fields": S("submissions", OBJECT)},
        other="id public_id version_number origin received_at application_id"),
    "applications_versionadoption": Table(other="id adopted_at application_id submission_version_id via_challenge_id"),
    # --- assessments ---------------------------------------------------------------------------------------------
    "assessments_assessmentinvocation": Table(other=(
        "id snapshot_sha256 attempt reserved_requests reserved_tokens used_tokens status started_at finished_at"
        " application_id run_id")),
    "assessments_assessmentrun": Table(
        selector=APP, subject={"snapshot": S("evidence", OBJECT), "output": S("evidence", OBJECT_OR_NULL)},
        other=("id public_id round trigger snapshot_sha256 prompt_pack prompt_pack_sha256 rubric_version schema_version"
               " provider model_id output_mode library_version request_sha256 status error_code output_sha256"
               " validation_codes flags requests_used input_tokens output_tokens created_at finished_at"
               " adopted_version_id application_id")),
    "assessments_evidencecapture": Table(
        selector=APP, subject={"final_url": S("evidence"), "derived_text": S("evidence")},
        other=("id attempt_number http_status content_type revision_marker byte_length truncated response_sha256"
               " derived_sha256 derivation_version is_derivative outcome cannot_prove injection_markers peer_ip"
               " fetched_at application_id item_id source_id")),  # cannot_prove: fixed text per source kind
    "assessments_evidenceitem": Table(
        selector=APP, subject={"request_url": S("evidence"), "request_url_sha256": S("evidence", EMPTY)},
        other=("id public_id claim_ref round required status reason_code finished_at created_at updated_at"
               " adopted_version_id application_id source_id")),
    "assessments_evidencesource": Table(staff="approved_by", other=(
        "id key version kind host port path_prefix redirect_hosts content_types max_bytes deadline_seconds required"
        " on_unavailable fixture_only definition_sha256 status approved_at created_at")),
    "assessments_modeluseapproval": Table(staff="actor_ref", other=(  # oc4.9: owner configuration, no applicant data
        "id purpose action provider model_id terms terms_sha256 approval_ref recorded_at")),
    "assessments_qualificationdecision": Table(
        selector=APP,
        subject={"human_only_reason": S("decisions"), "reason_text": S("decisions"), "rationale": S("decisions", NOTES)},
        staff="actor_ref second_actor_ref",
        other=("id public_id outcome basis reason_code snapshot_sha256 decision_digest policy_ref created_at created_txid"
               " adopted_version_id application_id run_id human_only_code prompt_pack prompt_pack_sha256"
               " rubric_version decision_inputs")),  # decision_inputs: references, states, codes and digests
    # --- Django's own tables -------------------------------------------------------------------------------------
    "auth_group": Table(other="id name"),
    "auth_group_permissions": Table(other="id group_id permission_id"),
    "auth_permission": Table(other="id name content_type_id codename"),
    "django_admin_log": Table(
        selector=("content_type_id = (SELECT c.id FROM public.django_content_type c WHERE c.app_label = 'applications'"
                  " AND c.model = 'application') AND object_id = ANY(v_apps::text[])"),
        subject={"object_repr": S("admin_log"), "change_message": S("admin_log")},
        other="id action_time object_id action_flag content_type_id user_id"),
    "django_content_type": Table(other="id app_label model"),
    "django_migrations": Table(other="id app name applied"),
    "django_session": Table(staff="session_data", secret="session_key", other="expire_date"),
    # --- correspondence ------------------------------------------------------------------------------------------
    "correspondence_approvedmessage": Table(
        selector=APP,
        subject={"recipient": S("mail_derivatives"), "frozen_subject": S("mail_derivatives"),
                 "frozen_body": S("mail_derivatives"), "reproducible_inputs": S("mail_derivatives", OBJECT)},
        staff="authorized_by disposition_by",
        other=("id send_ref kind content_sha256 inputs_sha256 authority authorized_at disposition disposition_at"
               " application_id supersedes_id template_version_id staff_draft_id")),
    "correspondence_approvedmessagequestion": Table(other="id purpose approved_message_id question_id"),
    "correspondence_inboundmessage": Table(
        # Mail from the subject's address that was never associated with an application is the subject's too.
        selector="application_id = ANY(v_apps) OR from_normalized = v_key",
        subject={"message_id_header": S("mail_derivatives"), "in_reply_to": S("mail_derivatives"),
                 "references": S("mail_derivatives"), "from_address": S("mail_derivatives"),
                 "from_normalized": S("mail_derivatives"), "derived_text": S("mail_derivatives"),
                 "attachments": S("mail_derivatives", ARRAY)},
        other=("id public_id mailbox_ref auto_markers date_header internal_date received_at size original_sha256"
               " derivation_version redaction_version truncated truncated_at_chars omitted_parts redactions"
               " is_derivative auth_evidence trust_decision from_matches_verified_address classification status"
               " exception_reason processed_at identity_state application_id approved_message_id"
               " derived_text_sha256")),  # redactions: counts per code; omitted_parts: content types
    "correspondence_inboundmessagelocation": Table(other="id mailbox_ref folder uidvalidity uid observed_at matched_by message_id"),
    "correspondence_mailboxcursor": Table(other=(
        "id public_id mailbox_ref folder uidvalidity last_uid complete_through_uid complete_through_at state"
        " blocked_reason epoch pass_number start_mode last_batch_at last_error_code consecutive_failures"
        " duplicates_seen created_at")),
    "correspondence_messagetemplate": Table(other="id key purpose secret_bearing created_at"),
    "correspondence_messagetemplateversion": Table(staff="approved_by", other=(
        "id version subject body_text variables secret_bearing status approved_at content_sha256 synthetic created_at"
        " template_id")),
    "correspondence_outboundmessage": Table(
        selector=APP, subject={"recipient": S("mail_derivatives")},
        other=("id attempt_number template_key template_version message_id status sent_at application_id"
               " pending_action_id attempt_series created_at protocol_phase_reached rendered_sha256 server_accepted_at"
               " smtp_reply_code approved_message_id filed_copy_state")),
    "correspondence_question": Table(
        selector=APP,
        subject={"text": S("mail_derivatives"), "text_key": S("mail_derivatives", EMPTY),
                 "alternative_route": S("mail_derivatives"), "evidence_gap": S("mail_derivatives"),
                 "withdrawn_reason": S("mail_derivatives")},
        staff="approved_by withdrawn_by raised_by",
        other=("id public_id origin approval_state approved_at status withdrawn_at created_at updated_at application_id"
               " criterion_id requires_evidence round")),
    "correspondence_questionreplylink": Table(staff="actor_ref", other=(
        "id state outcome created_at updated_at inbound_message_id question_id")),
    "correspondence_replyinterpretation": Table(
        selector=APP, subject={"proposals": S("mail_derivatives", ARRAY)},
        other=("id public_id attempt text_sha256 status code reserved_requests problems flags provenance started_at"
               " finished_at application_id message_id")),
    "correspondence_staffitem": Table(other=(  # dedupe_key: references such as inbound:<uuid>
        "id public_id reason_code dedupe_key question_id pending_action_id status opened_at application_id"
        " approved_message_id")),
    "correspondence_staffitemresolution": Table(
        selector="item_id IN (SELECT s.id FROM public.correspondence_staffitem s WHERE s.application_id = ANY(v_apps))",
        subject={"note": S("staff_notes")}, staff="resolved_by", other="id resolution_code resolved_at effects item_id"),
    "correspondence_staffmessagedraft": Table(
        selector=APP,
        subject={"subject": S("mail_derivatives"), "body": S("mail_derivatives"), "recipient": S("mail_derivatives")},
        staff="author", other="id public_id content_sha256 created_at application_id"),
    # --- erasure (this app) ----------------------------------------------------------------------------------------
    "erasure_erasureaudit": Table(other="id at actor subject_ref authority reason_code classes created_txid"),
    # --- two-factor devices (staff credentials) -------------------------------------------------------------------
    "otp_static_staticdevice": Table(other=(
        "id name confirmed user_id throttling_failure_count throttling_failure_timestamp created_at last_used_at")),
    "otp_static_statictoken": Table(secret="token", other="id device_id"),
    "otp_totp_totpdevice": Table(secret="key", other=(
        "id name confirmed step t0 digits tolerance drift last_t user_id throttling_failure_count"
        " throttling_failure_timestamp created_at last_used_at")),
    # --- provisioning --------------------------------------------------------------------------------------------
    "provisioning_accessrevocation": Table(
        selector=REQUEST, subject={"note": S("staff_notes")}, staff="decided_by",
        other="id public_id kind state created_at updated_at request_id"),
    "provisioning_addressreservation": Table(
        selector=APP, subject={"local_part": S("provisioning_records", LOCAL_PART, "public_id")},
        staff="reviewed_by released_by", other="id public_id domain basis released_at created_at application_id"),
    "provisioning_credentialsetup": Table(
        selector=REQUEST, subject={"recipient": S("provisioning_records")}, secret="token_sha256",
        other="id public_id series state expires_at set_attempts set_started_at completed_at created_at updated_at request_id"),
    "provisioning_provisioningattempt": Table(other=(
        "id public_id step series outcome code absent_before started_at finished_at request_id")),
    "provisioning_provisioningevidence": Table(
        selector=REQUEST, subject={"facts": S("provisioning_records", OBJECT), "note": S("staff_notes")},
        staff="actor_ref", other="id kind created_at request_id"),
    "provisioning_provisioningrequest": Table(staff="approved_by", other=(
        "id public_id method quota_mb send_limit prerequisite_digest approval_digest status approved_at"
        " stop_requested_at created_at updated_at application_id reservation_id superseded_by_id")),
    "provisioning_withdrawalconfirmation": Table(
        selector=APP, subject={"recipient": S("provisioning_records")}, secret="token_sha256", staff="requested_by",
        other="id public_id state expires_at created_at updated_at application_id"),
    # --- workflow ------------------------------------------------------------------------------------------------
    "workflow_automationpause": Table(
        # Erasure anonymizes a pause and never deletes it: a restriction kept is safe, one lifted is not.
        selector="subject_type = 'application' AND subject_id = ANY(v_refs)",
        subject={"reason": S("pauses")}, staff="actor_ref", other="id subject_type subject_id created_at"),
    "workflow_pendingaction": Table(
        selector="subject_type = 'application' AND subject_id = ANY(v_refs)",
        subject={"last_error": S("jobs")},
        other=("id kind subject_type subject_id input_ref idempotency_key status due_at attempts max_attempts lease_token"
               " lease_expires_at created_at updated_at completed_at")),
}

# The trigger functions that refuse an update of a subject column and so carry the erasure branch (injected after
# their first BEGIN by migration erasure.0002 and removed on reverse). catalyst_append_only_strict is deliberately
# absent: it stays a plain refusal for the adoption record and every no-truncate trigger.
GUARDED_FUNCTIONS = (
    "catalyst_history_append_only",  # versions, events, evidence captures, decisions, provider observations
    "catalyst_approved_message_frozen", "catalyst_inbound_provenance_frozen", "catalyst_outbound_identity_frozen",
    "catalyst_invitation_fixed", "catalyst_member_on_file_fixed", "catalyst_agreement_details_frozen",
    "catalyst_credential_setup_fixed", "catalyst_withdrawal_confirmation_fixed", "catalyst_access_revocation_fixed",
    "catalyst_provisioning_reservation_fixed", "catalyst_run_result_once", "catalyst_interpretation_result_once",
    "catalyst_pause_fixed",
    # Every other UPDATE trigger on a table with subject columns carries the branch too (PR #99 review: the coverage
    # test is derived from pg_trigger, not this list), so no trigger added there can refuse the audited path unseen.
    "catalyst_fetcher_applications_application_update", "catalyst_fetcher_assessments_evidenceitem_update",
    "catalyst_fetcher_workflow_pendingaction_update", "catalyst_decided_stage_needs_decision", "catalyst_restore_hold_fixed",
)
# Row triggers that used the strict refusal on a table with subject columns: they move to
# catalyst_erasable_append_only (the same refusal, with the branch). The adoption record keeps the strict function.
ERASABLE_STRICT = (
    ("applications_retentionaudit", "catalyst_audit_immutable"),
    ("agreements_agreementrecipient", "catalyst_append_only"),
    ("agreements_documentaccess", "catalyst_append_only"),
    ("correspondence_staffitemresolution", "catalyst_append_only"),
    ("provisioning_provisioningevidence", "catalyst_append_only"),
)
BRANCH_BEGIN = "-- catalyst-erasure-branch begin (9kg.32)"
BRANCH_END = "-- catalyst-erasure-branch end"


def branch(retention_literal: str) -> str:
    """The one branch each guarded trigger function gains, right after its first BEGIN. The membership test comes
    first, in its own IF, so a session of any other role (the application role updating a disposition, a status or a
    use) never calls the checker, which only the owner may execute."""
    return (f"\n          {BRANCH_BEGIN}\n"
            f"          IF TG_OP = 'UPDATE' AND pg_catalog.pg_has_role(session_user, {retention_literal}, 'MEMBER') THEN\n"
            "            IF public.catalyst_erasure_admits(TG_TABLE_NAME, pg_catalog.to_jsonb(OLD), pg_catalog.to_jsonb(NEW)) THEN\n"
            "              RETURN NEW;\n"
            "            END IF;\n"
            "          END IF;\n"
            f"          {BRANCH_END}")


# Refusals the erase function raises, by SQLSTATE (class CE, Catalyst erasure), mapped to codes by erasure.service.
REFUSALS = {"CE001": "nothing_to_erase", "CE002": "unknown_subject", "CE003": "subject_open",
            "CE004": "subject_has_open_work", "CE005": "revocation_not_final", "CE006": "malformed_request",
            "CE007": "not_the_retention_role", "CE008": "no_restore_hold"}
# config.backup.RESTORE_HOLD, the row a restore writes (tests pin that the two agree): the replay variant of the erase
# function (9kg.25) runs only while it is present, so it can never skip the refusals on a database in service.
RESTORE_HOLD_ROW = ("system", "00000000-0000-0000-0000-00000000aaaa")


def subject_columns(table=None):
    """{table: {column: Subject}} for every table with subject columns (or one table's)."""
    out = {t: {c: s for c, s in spec.columns().items() if isinstance(s, Subject)} for t, spec in TABLES.items()}
    out = {t: cols for t, cols in out.items() if cols}
    return out if table is None else out.get(table, {})


def classes_in_map() -> set:
    return {s.cls for cols in subject_columns().values() for s in cols.values()}


# --- SQL generation ------------------------------------------------------------------------------------------------

def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _notes(expr: str) -> str:
    """The `notes` tombstone over a jsonb expression."""
    return (f"(CASE WHEN pg_catalog.jsonb_typeof({expr}) = 'object' THEN (SELECT coalesce(pg_catalog.jsonb_object_agg("
            f"e.key, CASE WHEN pg_catalog.jsonb_typeof(e.value) = 'object' AND e.value ? 'note'"
            f" THEN e.value || '{{\"note\": \"{ERASED}\"}}'::jsonb ELSE e.value END), '{{}}'::jsonb)"
            f" FROM pg_catalog.jsonb_each({expr}) e) ELSE '{{}}'::jsonb END)")


def set_expression(column: str, subject: Subject) -> str:
    """The tombstone as a column value, for the UPDATE's SET list."""
    c = _q(column)
    return {
        TEXT: f"CASE WHEN {c} IS NULL OR {c} = '' THEN {c} ELSE {_lit(ERASED)} END",
        EMPTY: "''",
        OBJECT: "'{}'::jsonb",
        ARRAY: "'[]'::jsonb",
        OBJECT_OR_NULL: f"CASE WHEN {c} IS NULL THEN NULL ELSE '{{}}'::jsonb END",
        KEY: f"'erased:' || {_q(subject.source)}::text",
        LOCAL_PART: f"'erased-' || pg_catalog.replace({_q(subject.source)}::text, '-', '')",
        NOTES: _notes(c),
    }[subject.tombstone]


def check_expression(column: str, subject: Subject) -> str:
    """The tombstone as a jsonb value computed from the old row (p_old), for the trigger's check."""
    old = f"p_old -> {_lit(column)}"
    return {
        TEXT: f"(CASE WHEN {old} IN ('null'::jsonb, '\"\"'::jsonb) THEN {old} ELSE '\"{ERASED}\"'::jsonb END)",
        EMPTY: "'\"\"'::jsonb",
        OBJECT: "'{}'::jsonb",
        ARRAY: "'[]'::jsonb",
        OBJECT_OR_NULL: f"(CASE WHEN {old} = 'null'::jsonb THEN 'null'::jsonb ELSE '{{}}'::jsonb END)",
        KEY: f"pg_catalog.to_jsonb('erased:' || (p_old ->> {_lit(subject.source)}))",
        LOCAL_PART: f"pg_catalog.to_jsonb('erased-' || pg_catalog.replace(p_old ->> {_lit(subject.source)}, '-', ''))",
        NOTES: _notes(old),
    }[subject.tombstone]


def _present(existing, table, columns):
    """The columns of `columns` that exist now (a migration installs only what the schema holds at that point; a later
    migration that adds a subject column reinstalls the functions, and the catalog test checks they match)."""
    have = existing.get(table, set())
    return {c: s for c, s in columns.items() if c in have}


def checker_body(existing: dict) -> str:
    """The body of public.catalyst_erasure_admits(p_table text, p_old jsonb, p_new jsonb): true only on the audited
    path (the session login is a member of the retention role and an erasure audit row carries the current
    transaction id; both are checked by the caller's wrapper) for a change confined to the table's allow-list with
    every changed column set to its tombstone."""
    whens = []
    for table, columns in subject_columns().items():
        columns = {c: s for c, s in _present(existing, table, columns).items() if s.tombstone != DELETE}
        if not columns:
            continue
        names = "ARRAY[" + ", ".join(_lit(c) for c in sorted(columns)) + "]::text[]"
        parts = [f"(p_old - {names}) = (p_new - {names})"]
        for column, subject in sorted(columns.items()):
            parts.append(f"(p_new -> {_lit(column)} = p_old -> {_lit(column)}"
                         f" OR p_new -> {_lit(column)} = {check_expression(column, subject)})")
        whens.append(f"    WHEN {_lit(table)} THEN\n      RETURN " + "\n         AND ".join(parts) + ";")
    return "\n".join(whens)


def update_statements(existing: dict) -> list[tuple[str, str, str]]:
    """[(class, table, statement)]: one statement per class and table, in the map's order. A statement updates the
    subject's rows whose class columns are not yet tombstones (so a repeat changes nothing), or deletes the rows of a
    `delete` class."""
    out = []
    for table, spec in TABLES.items():
        columns = _present(existing, table, subject_columns(table))
        by_class = {}
        for column, subject in columns.items():
            by_class.setdefault(subject.cls, {})[column] = subject
        for cls, cols in by_class.items():
            if any(s.tombstone == DELETE for s in cols.values()):
                out.append((cls, table, f"DELETE FROM public.{_q(table)} WHERE {spec.selector}"))
                continue
            names = sorted(cols)
            targets = ", ".join(_q(c) for c in names)
            values = ", ".join(set_expression(c, cols[c]) for c in names)
            sets = ", ".join(f"{_q(c)} = {set_expression(c, cols[c])}" for c in names)
            out.append((cls, table, f"UPDATE public.{_q(table)} SET {sets} WHERE ({spec.selector})"
                                    f" AND ROW({targets}) IS DISTINCT FROM ROW({values})"))
    return out


# --- the functions migration erasure.0002 installs -------------------------------------------------------------------

def checker_sql(retention_literal: str, existing: dict) -> str:
    return f"""CREATE OR REPLACE FUNCTION public.catalyst_erasure_admits(p_table text, p_old jsonb, p_new jsonb)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
BEGIN
  IF NOT pg_catalog.pg_has_role(session_user, {retention_literal}, 'MEMBER') OR NOT EXISTS (
       SELECT 1 FROM public.erasure_erasureaudit a
       WHERE a.created_txid = pg_catalog.pg_current_xact_id()::text::bigint) THEN
    RETURN false;
  END IF;
  CASE p_table
{checker_body(existing)}
    ELSE
      RETURN false;
  END CASE;
END $fn$"""


def erasable_append_only_sql(retention_literal: str) -> str:
    return f"""CREATE OR REPLACE FUNCTION public.catalyst_erasable_append_only() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $fn$
        BEGIN{branch(retention_literal)}
          RAISE EXCEPTION 'append-only: % on % refused', TG_OP, TG_TABLE_NAME
            USING ERRCODE = 'insufficient_privilege';
        END $fn$"""


def _tally(table: str) -> str:
    return (f"      GET DIAGNOSTICS v_n = ROW_COUNT;\n"
            f"      IF v_n > 0 THEN\n"
            f"        v_total := v_total + v_n;\n"
            f"        v_tables := v_tables || pg_catalog.jsonb_build_object({_lit(table)},"
            f" coalesce((v_tables ->> {_lit(table)})::bigint, 0) + v_n);\n"
            f"      END IF;")


def erase_sql(retention_literal: str, existing: dict, replay: bool = False) -> str:
    """public.catalyst_erase(p_subject uuid, p_authority text, p_reason text, p_classes text[]) RETURNS jsonb: the one
    erasure function, SECURITY DEFINER (it runs as the owner while the session stays the retention login), EXECUTE for
    the retention role only. One transaction: it locks the subject's applications, refuses unless every one is terminal
    and nothing of the subject is still in flight, writes the erasure audit row, then sets each anonymized class to its
    tombstones. A subject with nothing left to change returns `nothing_to_erase` without writing anything (the audit
    row is rolled back with its sub-block), so a second erasure is harmless; a subject whose key is already a tombstone
    is scoped by its own references, so a class added later still reaches it. It also reports the provider handoffs
    owed, what it retains (`custody_documents` when the subject has stored documents) and, for 9kg.34, the key
    references of the subject's sealed custody documents (`custody_keys`) and the number still in the clear
    (`custody_plaintext`), so the command can destroy those keys outside the database (agreements.keystore).

    `replay=True` generates public.catalyst_erase_replay (9kg.25, erasure 0004): the same function under its own name,
    without the three refusals for an open application, work in flight and an access revocation that is not final,
    and refusing instead unless the restore hold is present (CE008). It re-applies, to a restored older backup, an erasure that passed those refusals when it ran: the restored rows are as
    they were before the person was closed out, so the refusals would keep the restore held for good. The post-restore
    review settles what they guarded (config.post_restore.settle_erased) before anything runs."""
    terminal = ", ".join(_lit(s) for s in TERMINAL_STAGES)
    open_statuses = ", ".join(_lit(s) for s in OPEN_ACTION_STATUSES)
    final = ", ".join(_lit(s) for s in FINAL_REVOCATION_STATES)
    known = ", ".join(_lit(c) for c in sorted(classes_in_map()))
    blocks = []
    for cls, table, statement in update_statements(existing):
        blocks.append(f"    IF {_lit(cls)} = ANY(p_classes) THEN\n      {statement};\n{_tally(table)}\n    END IF;")
    updates = "\n".join(blocks)
    held = f"""  IF NOT EXISTS (SELECT 1 FROM public.workflow_automationpause h WHERE h.subject_type = {_lit(RESTORE_HOLD_ROW[0])}
                 AND h.subject_id = {_lit(RESTORE_HOLD_ROW[1])}::uuid) THEN
    RAISE EXCEPTION 'erasure: replay runs only on a database under the restore hold' USING ERRCODE = 'CE008';
  END IF;
"""
    gates = "" if replay else f"""  IF EXISTS (SELECT 1 FROM public.applications_application a WHERE a.id = ANY(v_apps) AND a.stage NOT IN ({terminal})) THEN
    RAISE EXCEPTION 'erasure: the subject has an open application' USING ERRCODE = 'CE003';
  END IF;
  IF EXISTS (SELECT 1 FROM public.workflow_pendingaction p WHERE p.subject_type = 'application'
             AND p.subject_id = ANY(v_refs) AND p.status IN ({open_statuses})) THEN
    RAISE EXCEPTION 'erasure: work for the subject is still queued, running, held or uncertain' USING ERRCODE = 'CE004';
  END IF;
  IF EXISTS (SELECT 1 FROM public.provisioning_accessrevocation r
             JOIN public.provisioning_provisioningrequest q ON q.id = r.request_id
             WHERE q.application_id = ANY(v_apps) AND r.state NOT IN ({final})) THEN
    RAISE EXCEPTION 'erasure: an access revocation is not final' USING ERRCODE = 'CE005';
  END IF;
"""
    return f"""CREATE OR REPLACE FUNCTION public.{"catalyst_erase_replay" if replay else "catalyst_erase"}(p_subject uuid, p_authority text, p_reason text,
                                                 p_classes text[])
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $fn$
DECLARE
  v_key text;
  v_apps bigint[];
  v_refs uuid[];
  v_n bigint;
  v_total bigint := 0;
  v_tables jsonb := '{{}}'::jsonb;
  v_handoffs text[] := ARRAY[]::text[];
  v_retained text[] := ARRAY[]::text[];
{CUSTODY_BEGIN}  v_custody_keys text[] := ARRAY[]::text[];
  v_custody_plaintext bigint := 0;
{CUSTODY_END}  v_tombstoned boolean;
BEGIN
  IF NOT pg_catalog.pg_has_role(session_user, {retention_literal}, 'MEMBER') THEN
    RAISE EXCEPTION 'erasure: refused for this login' USING ERRCODE = 'CE007';
  END IF;
  IF p_subject IS NULL OR p_authority IS NULL OR p_authority !~ '^[a-z0-9_.:-]{{3,64}}$'
     OR p_reason IS NULL OR p_reason !~ '^[a-z0-9_.:-]{{3,64}}$' OR p_classes IS NULL
     OR pg_catalog.cardinality(p_classes) = 0 OR NOT (p_classes <@ ARRAY[{known}{CUSTODY_BEGIN}, 'custody_keys_destroyed'{CUSTODY_END}]::text[]) THEN
    RAISE EXCEPTION 'erasure: malformed request' USING ERRCODE = 'CE006';
  END IF;
{held if replay else ""}  SELECT a.email_key INTO v_key FROM public.applications_application a WHERE a.public_ref = p_subject;
  IF NOT FOUND THEN
    SELECT i.email_key INTO v_key FROM public.applications_invitation i WHERE i.public_id = p_subject;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'erasure: unknown subject' USING ERRCODE = 'CE002';
    END IF;
  END IF;
  -- A tombstone (never a real key: no @) means an earlier erasure ran. The key can no longer find anything, so the
  -- subject is scoped by its own references and the key-selected rows are skipped (v_key NULL matches nothing); the
  -- other classes still run, so a class or a step added later (9kg.34) reaches an already-erased subject.
  v_tombstoned := v_key LIKE 'erased:%' AND pg_catalog.strpos(v_key, '@') = 0;
  IF v_tombstoned THEN
    v_key := NULL;
    SELECT coalesce(pg_catalog.array_agg(s.id ORDER BY s.id), ARRAY[]::bigint[]),
           coalesce(pg_catalog.array_agg(s.public_ref ORDER BY s.id), ARRAY[]::uuid[])
      INTO v_apps, v_refs
      FROM (SELECT a.id, a.public_ref FROM public.applications_application a
            WHERE a.public_ref = p_subject
               OR a.id IN (SELECT i.application_id FROM public.applications_invitation i WHERE i.public_id = p_subject)
            ORDER BY a.id FOR UPDATE) s;
  ELSE
    SELECT coalesce(pg_catalog.array_agg(s.id ORDER BY s.id), ARRAY[]::bigint[]),
           coalesce(pg_catalog.array_agg(s.public_ref ORDER BY s.id), ARRAY[]::uuid[])
      INTO v_apps, v_refs
      FROM (SELECT a.id, a.public_ref FROM public.applications_application a WHERE a.email_key = v_key
            ORDER BY a.id FOR UPDATE) s;
  END IF;
{gates}  -- Provider-held copies (211.7.1, QA finding 12): a manual handoff each, recorded in the durable erasure record.
  IF EXISTS (SELECT 1 FROM public.agreements_agreementinstance i WHERE i.application_id = ANY(v_apps)
             AND i.envelope_id <> '') THEN
    v_handoffs := v_handoffs || 'documenso'::text;
  END IF;
  IF EXISTS (SELECT 1 FROM public.applications_contactchallenge c WHERE c.application_id = ANY(v_apps))
     OR EXISTS (SELECT 1 FROM public.correspondence_outboundmessage o WHERE o.application_id = ANY(v_apps)) THEN
    v_handoffs := v_handoffs || 'mail_sent'::text;
  END IF;
  IF EXISTS (SELECT 1 FROM public.correspondence_inboundmessage m WHERE m.application_id = ANY(v_apps)
             OR m.from_normalized = v_key) THEN
    v_handoffs := v_handoffs || 'mail_inbox'::text;
  END IF;
  IF EXISTS (SELECT 1 FROM public.provisioning_addressreservation r WHERE r.application_id = ANY(v_apps)
             AND EXISTS (SELECT 1 FROM public.provisioning_provisioningrequest q WHERE q.reservation_id = r.id
                         AND q.status NOT IN ('awaiting_approval', 'superseded'))) THEN
    v_handoffs := v_handoffs || 'mail_host_mailbox'::text;
  END IF;
  IF EXISTS (SELECT 1 FROM public.assessments_assessmentrun r WHERE r.application_id = ANY(v_apps)) THEN
    v_handoffs := v_handoffs || 'model_provider'::text;  -- what the model provider kept of a request, if anything
  END IF;
  -- Not erased by this function: the custody PDFs (registry row signed_documents; 9kg.34 destroys their keys).
  IF EXISTS (SELECT 1 FROM public.agreements_storeddocument d WHERE d.application_id = ANY(v_apps)) THEN
    v_retained := v_retained || 'custody_documents'::text;
  END IF;
{CUSTODY_BEGIN}  -- 9kg.34: the key references of the subject's sealed documents, so the command destroys the keys outside the
  -- database under `destroy_key`; reachable for a tombstoned subject too (erasure 0003; its reverse strips this block).
  -- One statement, one snapshot: the sealed documents' keys and the documents still in the clear can never disagree
  -- about a document a concurrent migration seals in between (data review of PR #102, K2).
  SELECT coalesce(pg_catalog.array_agg(e.key_ref ORDER BY e.id) FILTER (WHERE e.id IS NOT NULL), ARRAY[]::text[]),
         pg_catalog.count(*) FILTER (WHERE e.id IS NULL)
    INTO v_custody_keys, v_custody_plaintext
    FROM public.agreements_storeddocument d LEFT JOIN public.agreements_custodyenvelope e ON e.document_id = d.id
    WHERE d.application_id = ANY(v_apps);
{CUSTODY_END}  BEGIN
    INSERT INTO public.erasure_erasureaudit (subject_ref, authority, reason_code, classes)
      VALUES (p_subject, p_authority, p_reason, pg_catalog.to_jsonb(p_classes));
{updates}
    IF v_total = 0 THEN
      RAISE EXCEPTION 'erasure: nothing to erase' USING ERRCODE = 'CE001';
    END IF;
  EXCEPTION WHEN SQLSTATE 'CE001' THEN
    RETURN pg_catalog.jsonb_build_object('status', 'nothing_to_erase', 'changed', 0, 'tables', '{{}}'::jsonb,
                                         'handoffs', pg_catalog.to_jsonb(v_handoffs),
                                         'retained', pg_catalog.to_jsonb(v_retained){CUSTODY_BEGIN},
                                         'custody_keys', pg_catalog.to_jsonb(v_custody_keys),
                                         'custody_plaintext', v_custody_plaintext{CUSTODY_END});
  END;
  RETURN pg_catalog.jsonb_build_object('status', 'erased', 'changed', v_total, 'tables', v_tables,
                                       'handoffs', pg_catalog.to_jsonb(v_handoffs),
                                       'retained', pg_catalog.to_jsonb(v_retained){CUSTODY_BEGIN},
                                       'custody_keys', pg_catalog.to_jsonb(v_custody_keys),
                                       'custody_plaintext', v_custody_plaintext{CUSTODY_END});
END $fn$"""


# 9kg.34 (erasure 0003; data review of PR #102, K1): the custody part of catalyst_erase, between these inline markers,
# so 0003's reverse reinstalls the function exactly as 0002 installed it (and 0002 installs it without the part): a
# rollback of agreements 0010 never leaves a function that reads a dropped table.
CUSTODY_BEGIN, CUSTODY_END = "/*catalyst-custody{*/", "/*}catalyst-custody*/"
# Data review of PR #102, K4: a class the command adds to the call (never anonymized, no column) so the erasure audit row
# written on a first erasure under `destroy_key` says the subject's custody keys are destroyed outside the database.
CUSTODY_AUDIT_CLASS = "custody_keys_destroyed"
CUSTODY_PATTERN = re.compile(re.escape(CUSTODY_BEGIN) + r".*?" + re.escape(CUSTODY_END), re.DOTALL)


def without_custody(definition: str) -> str:
    """The erase function's SQL without its marked custody part (what erasure 0002 installs and 0003's reverse
    restores)."""
    return CUSTODY_PATTERN.sub("", definition)


AUDIT_TXID_SQL = """CREATE OR REPLACE FUNCTION public.catalyst_erasure_audit_txid() RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp AS $fn$
BEGIN
  NEW.created_txid := pg_catalog.pg_current_xact_id()::text::bigint;
  NEW.at := pg_catalog.now();
  NEW.actor := session_user;
  RETURN NEW;
END $fn$"""


def with_branch(definition: str, retention_literal: str) -> str:
    """A function definition (pg_get_functiondef's CREATE OR REPLACE text) with the branch right after the first
    BEGIN of its body. Raises when the body has no BEGIN or already carries a branch."""
    start = definition.index("AS $function$")
    found = re.compile(r"\bBEGIN\b", re.IGNORECASE).search(definition, start)
    if found is None or BRANCH_BEGIN in definition:
        raise ValueError("the function cannot take the erasure branch")
    return definition[:found.end()] + branch(retention_literal) + definition[found.end():]


BRANCH_PATTERN = re.compile(r"\n[ \t]*" + re.escape(BRANCH_BEGIN) + r".*?" + re.escape(BRANCH_END), re.DOTALL)


def without_branch(definition: str) -> str:
    """The inverse of with_branch, by the begin and end markers (whatever role literal the branch was written with):
    the definition exactly as it was before."""
    if len(BRANCH_PATTERN.findall(definition)) != 1:
        raise ValueError("the function does not carry exactly one erasure branch")
    return BRANCH_PATTERN.sub("", definition, count=1)
