"""A synthetic first-generation database for the import tests (bgl.16; 035 section 7). Synthetic rows only.

The tables are the first generation's, column for column as its SQLAlchemy models define them at migration 0023
(034 section 1.5), created in a schema of their own inside this run's test database, so the import reads them over a
real libpq connection exactly as it reads the production database. Foreign keys and check constraints are left out:
the import must not rely on them, and a test can then plant an orphan. Every person, address and text is invented
(`.test` addresses, made-up names); nothing comes from the first generation's data.
"""

import json
import os
import uuid
from datetime import datetime, timedelta

from psycopg import sql
from psycopg.types.json import Json

T = "timestamp"
DDL = {
    "onboarding_case": f"id varchar(26) primary key, state varchar(30) not null, cohort varchar(30), version int not null"
                       f" default 1, created_at {T} not null, state_changed_at {T} not null",
    "case_event": f"id bigserial primary key, case_id varchar(26) not null, subject varchar(10) not null, agreement_id"
                  f" varchar(26), from_state varchar(30), to_state varchar(30) not null, event varchar(40) not null, actor"
                  f" varchar(40) not null, policy_version varchar(50), reason varchar(200), version int not null default 1,"
                  f" created_at {T} not null",
    "agreement": f"id varchar(26) primary key, case_id varchar(26) not null, document_type varchar(40) not null,"
                 f" document_version varchar(50) not null, status varchar(20) not null, version int not null default 1,"
                 f" provider_ref varchar(100), external_ref varchar(100) unique, provenance varchar(20) not null default"
                 f" 'native', countersign_claimed_at {T}, countersign_claimed_by varchar(40), created_at {T} not null,"
                 f" status_changed_at {T} not null",
    "job": f"id varchar(26) primary key, action_key varchar(200) not null unique, kind varchar(40) not null, case_id"
           f" varchar(26), agreement_id varchar(26), payload json not null default '{{}}', status varchar(20) not null,"
           f" attempts int not null default 0, max_attempts int not null default 5, reconcile_checks int not null default"
           f" 0, next_run_at {T} not null, lease_owner varchar(100), lease_expires_at {T}, last_error varchar(100),"
           f" outcome_unknown boolean not null default false, created_at {T} not null, updated_at {T} not null,"
           f" completed_at {T}",
    "intake_request": f"id varchar(26) primary key, case_id varchar(26) not null unique, provenance varchar(20) not null"
                      f" default 'native', source varchar(60), source_submitted_at {T}, reference varchar(20) not null"
                      f" unique, full_name varchar(150) not null, personal_email varchar(254) not null, email_key"
                      f" varchar(254) not null, phone_e164 varchar(16), phone_country varchar(2), work_links json not null"
                      f" default '[]', building_text text not null, interest_track varchar(20) not null,"
                      f" interest_wording_version varchar(30) not null, form_version varchar(30) not null,"
                      f" marketing_opt_in boolean, marketing_opt_in_at {T}, marketing_wording_version varchar(40),"
                      f" created_at {T} not null, email_verified_at {T}, email_verified_via varchar(10),"
                      f" email_confirm_token_hash varchar(64), email_confirm_expires_at {T}, holds_email_key boolean"
                      f" not null default true, residence_country varchar(6), age_attested boolean, cap_deferred_until"
                      f" {T}, no_degree_declared boolean, no_certifications_declared boolean, verification_consent_at"
                      f" {T}, verification_wording_version varchar(40)",
    "intake_revision": f"id varchar(26) primary key, case_id varchar(26) not null, intake_request_id varchar(26) not"
                       f" null, full_name varchar(150) not null, personal_email varchar(254) not null, phone_e164"
                       f" varchar(16) not null, phone_country varchar(2) not null, work_links json not null default"
                       f" '[]', building_text text not null, interest_track varchar(20) not null,"
                       f" interest_wording_version varchar(30) not null, form_version varchar(30) not null,"
                       f" marketing_opt_in boolean, marketing_opt_in_at {T}, marketing_wording_version varchar(40),"
                       f" residence_country varchar(6), age_attested boolean, no_degree_declared boolean,"
                       f" no_certifications_declared boolean, verification_consent_at {T}, verification_wording_version"
                       f" varchar(40), changed_fields json not null default '[]', needs_review boolean not null default"
                       f" false, created_at {T} not null",
    "intake_rate_event": f"id bigserial primary key, bucket varchar(64) not null, created_at {T} not null",
    "outbound_message": f"id varchar(26) primary key, case_id varchar(26), action_key varchar(200) not null unique,"
                        f" message_id varchar(250) not null unique, template varchar(40) not null, template_version"
                        f" varchar(30) not null, status varchar(20) not null, service_copy_seen boolean not null default"
                        f" false, created_at {T} not null, updated_at {T} not null, accepted_at {T}",
    "mailbox_cursor": f"folder varchar(100) primary key, uidvalidity bigint not null, last_uid bigint not null, resets"
                      f" int not null default 0, last_checked_at {T} not null",
    "inbound_message": f"id varchar(26) primary key, folder varchar(100) not null, uidvalidity bigint not null, uid"
                       f" bigint not null, message_key varchar(64) not null unique, classification varchar(20) not null,"
                       f" needs_review boolean not null default false, case_id varchar(26), outbound_message_id"
                       f" varchar(26), received_at {T}, created_at {T} not null, reviewed_at {T}, reviewed_by"
                       f" varchar(40)",
    "review_run": f"id varchar(26) primary key, case_id varchar(26) not null, job_id varchar(26), parent_run_id"
                  f" varchar(26), stage varchar(10) not null, repair boolean not null default false, input_case_version"
                  f" int not null, input_fingerprint varchar(64) not null, status varchar(20) not null, outcome"
                  f" varchar(20), action varchar(20), verdict varchar(20), override varchar(60), output json, error_code"
                  f" varchar(100), model_id varchar(100) not null, prompt_pack_version varchar(30) not null,"
                  f" prompt_sha256 varchar(64) not null, skills json not null default '{{}}', input_class varchar(40) not"
                  f" null, policy_version varchar(50) not null, requests int not null default 0, input_tokens int not"
                  f" null default 0, output_tokens int not null default 0, started_at {T} not null, finished_at {T}",
    "review_evidence": f"id varchar(40) primary key, case_id varchar(26) not null, run_id varchar(26), kind varchar(20)"
                       f" not null, url varchar(2048), final_url varchar(2048), fetched_at {T} not null, sha256"
                       f" varchar(64) not null, content_type varchar(100) not null, byte_count int not null, excerpt text"
                       f" not null",
    "review_question": f"id varchar(40) primary key, case_id varchar(26) not null, decide_run_id varchar(26) not null,"
                       f" criterion_id varchar(60) not null, round int not null, status varchar(20) not null, draft_id"
                       f" varchar(26), created_at {T} not null, sent_at {T}, answered_at {T}, answered_by_run_id"
                       f" varchar(26)",
    "review_draft": f"id varchar(26) primary key, case_id varchar(26) not null, decide_run_id varchar(26) not null,"
                    f" write_run_id varchar(26) not null, check_run_id varchar(26), revision int not null default 0,"
                    f" body_text text not null, question_ids json not null default '[]', status varchar(20) not null,"
                    f" created_at {T} not null, updated_at {T} not null",
    "crm_projection": f"case_id varchar(26) primary key, person_id varchar(64), link_method varchar(20), linked_at {T},"
                      f" field_hashes json not null default '{{}}', pending_hashes json not null default '{{}}',"
                      f" projection_version varchar(40), last_projected_at {T}, note_id varchar(64), note_hash"
                      f" varchar(64), note_version varchar(40), note_written_at {T}, created_at {T} not null, updated_at"
                      f" {T} not null",
    "crm_review_item": f"id varchar(26) primary key, case_id varchar(26) not null, kind varchar(30) not null, field"
                       f" varchar(40), detail varchar(300), person_id varchar(64), dedupe_key varchar(200) not null"
                       f" unique, created_at {T} not null, resolved_at {T}, resolved_by varchar(40)",
    "legacy_agreement_import": f"agreement_id varchar(26) primary key, case_id varchar(26) not null, legacy_envelope_id"
                               f" varchar(100) not null unique, document_label varchar(50) not null, completed_at {T},"
                               f" executed_pdf_sha256 varchar(64), verified_status varchar(20) not null,"
                               f" signed_recipients int not null, verified_at {T} not null, imported_by varchar(40) not"
                               f" null, created_at {T} not null",
    "agreement_details": f"id varchar(26) primary key, agreement_id varchar(26) not null unique, case_id varchar(26) not"
                         f" null, legal_full_name varchar(200) not null, residence varchar(200) not null,"
                         f" mailing_address varchar(500) not null, phone varchar(60) not null, source varchar(30) not"
                         f" null default 'documenso_fields', captured_at {T} not null, field_set varchar(10),"
                         f" address_line1 varchar(200), address_line2 varchar(200), locality varchar(100), region"
                         f" varchar(100), postal_code varchar(20), country_code varchar(2)",
    "ua_details_capture": f"envelope_id varchar(64) primary key, case_id varchar(26), agreement_id varchar(26),"
                          f" person_id varchar(64), outcome varchar(20) not null, signer_email_sha256 varchar(64),"
                          f" completed_at {T}, field_hashes json not null default '{{}}', conflict_fields varchar(100),"
                          f" address_incomplete boolean not null default false, incomplete_reasons varchar(100),"
                          f" display_name varchar(200), mailing_address varchar(500), resolved_at {T}, resolved_by"
                          f" varchar(40), first_seen_at {T} not null, updated_at {T} not null",
    "mailbox_account": f"id varchar(26) primary key, case_id varchar(26) not null unique, domain varchar(100) not null,"
                       f" username varchar(64) not null, username_source varchar(10) not null, status varchar(10) not"
                       f" null default 'approved', approved_by varchar(40) not null, approved_at {T} not null,"
                       f" create_requested_at {T}, created_at_provider {T}, welcome_send_started_at {T}, welcome_sent_at"
                       f" {T}, welcome_round int not null default 1, created_at {T} not null, updated_at {T} not null",
    "case_release": f"id varchar(26) primary key, case_id varchar(26) not null unique, released_by varchar(40) not null,"
                    f" policy_version varchar(50) not null, nda_agreement_id varchar(26) not null, ua_agreement_id"
                    f" varchar(26) not null, ua_envelope_id varchar(100) not null, archive_basis varchar(30) not null,"
                    f" attestation_ref varchar(200), verified_at {T} not null, created_at {T} not null",
    "applicant_message": f"id varchar(26) primary key, case_id varchar(26) not null, direction varchar(3) not null,"
                         f" sent_at {T} not null, subject varchar(300), body_text text not null, source_key varchar(64)"
                         f" not null unique, inbound_message_id varchar(26), template varchar(40), created_at {T} not null",
    "applicant_credential": f"id varchar(26) primary key, case_id varchar(26) not null, intake_request_id varchar(26),"
                            f" intake_revision_id varchar(26), kind varchar(20) not null, position int not null,"
                            f" degree_level varchar(20), field_of_study varchar(150), institution varchar(200), year"
                            f" int, name varchar(200), issuer varchar(200), credential_ref varchar(300), ref_kind"
                            f" varchar(10), verification_status varchar(20) not null default 'self_reported',"
                            f" verification_detail varchar(60), evidence_url varchar(500), evidence_title varchar(300),"
                            f" evidence_issuer varchar(200), issued_on varchar(10), expires_on varchar(10), checked_at"
                            f" {T}, created_at {T} not null",
    "agreement_acceptance": f"id varchar(26) primary key, created_at {T} not null",  # a dormant table, empty
}
BASE = datetime(2026, 10, 1, 9, 0, 0)  # naive UTC, as the first generation stores times
MAIL_DOMAIN = "mail.example.test"


def new_id() -> str:
    return uuid.uuid4().hex[:26].upper()


class V1:
    """One synthetic first-generation database: a schema, a writer and the DSN the import reads it with."""

    def __init__(self, owner):
        from django.conf import settings
        from django.db import connection

        self.owner = owner
        self.schema = f"v1fx_{uuid.uuid4().hex[:10]}"
        owner.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(self.schema)))
        for table, columns in DDL.items():
            owner.execute(sql.SQL("CREATE TABLE {}.{} ({})").format(sql.Identifier(self.schema), sql.Identifier(table),
                                                                     sql.SQL(columns)))
        self.counts = {t: 0 for t in DDL}
        s = connection.settings_dict
        self.dsn = (f"host={s['HOST']} port={s['PORT']} dbname={s['NAME']} user={settings.CATALYST_DB_ROLES['owner']}"
                    f" password={os.environ['CATALYST_DB_OWNER_PASSWORD']} options='-c search_path={self.schema}'")

    def drop(self):
        self.owner.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(self.schema)))

    def insert(self, table, **values):
        values = {k: Json(v) if isinstance(v, (dict, list)) else v for k, v in values.items()}
        cols = list(values)
        self.owner.execute(sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
            sql.Identifier(self.schema), sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, cols)),
            sql.SQL(", ").join(sql.Placeholder() * len(cols))), [values[c] for c in cols])
        self.counts[table] += 1

    def at(self, hours) -> datetime:
        return BASE + timedelta(hours=hours)

    # --- building blocks ---------------------------------------------------------------------------------------------

    def case(self, state, name, email, *, reference, verified=True, hours=0, revision=False, credentials=True):
        case_id = new_id()
        self.insert("onboarding_case", id=case_id, state=state, created_at=self.at(hours),
                    state_changed_at=self.at(hours + 5))
        request_id = new_id()
        self.insert("intake_request", id=request_id, case_id=case_id, reference=reference, full_name=name,
                    personal_email=email, email_key=email.lower(), phone_e164="+15555550100", phone_country="US",
                    work_links=["https://example.test/work"], building_text=f"{name} builds synthetic agents",
                    interest_track="cert_and_work", interest_wording_version="interest-track.2026-09-30",
                    form_version="request-access.v4", marketing_opt_in=True, marketing_opt_in_at=self.at(hours),
                    marketing_wording_version="marketing-updates.v1", created_at=self.at(hours),
                    email_verified_at=self.at(hours + 1) if verified else None,
                    email_verified_via="link" if verified else None,
                    email_confirm_token_hash=None if verified else "f" * 64, residence_country="US", age_attested=True,
                    no_degree_declared=False, no_certifications_declared=False, verification_consent_at=self.at(hours),
                    verification_wording_version="credential-verification.v1")
        if credentials:
            self.insert("applicant_credential", id=new_id(), case_id=case_id, intake_request_id=request_id,
                        kind="education", position=1, degree_level="bachelor", field_of_study="Synthetic Studies",
                        institution="Example University", year=2020, created_at=self.at(hours))
            self.insert("applicant_credential", id=new_id(), case_id=case_id, intake_request_id=request_id,
                        kind="certification", position=1, name="Synthetic Cert", issuer="Example Issuer",
                        credential_ref="https://example.test/cert/1", ref_kind="url", verification_status="pending",
                        created_at=self.at(hours))
        if revision:
            self.insert("intake_revision", id=new_id(), case_id=case_id, intake_request_id=request_id, full_name=name,
                        personal_email=email, phone_e164="+15555550101", phone_country="US",
                        work_links=["https://example.test/work2"], building_text=f"{name} builds more agents",
                        interest_track="undecided", interest_wording_version="interest-track.2026-09-30",
                        form_version="request-access.v4", changed_fields=["phone_e164", "work_links"],
                        needs_review=True, created_at=self.at(hours + 2))
        return case_id

    def event(self, case_id, from_state, to_state, event, hours, *, actor="worker", reason=None, agreement_id=None):
        self.insert("case_event", case_id=case_id, subject="agreement" if agreement_id else "case",
                    agreement_id=agreement_id, from_state=from_state, to_state=to_state, event=event, actor=actor,
                    reason=reason, policy_version="synthetic-policy.v1", created_at=self.at(hours))

    def agreement(self, case_id, document_type, status, hours, *, version=None):
        agreement_id = new_id()
        self.insert("agreement", id=agreement_id, case_id=case_id, document_type=document_type,
                    document_version=version or ("v1.1" if document_type == "nda" else "v2.4"), status=status,
                    provider_ref=f"envelope_{agreement_id.lower()}", external_ref=f"onb_{agreement_id.lower()}",
                    created_at=self.at(hours), status_changed_at=self.at(hours + 1))
        return agreement_id

    def outbound(self, case_id, template, hours):
        message_id = f"<{uuid.uuid4().hex}@{MAIL_DOMAIN}>"
        outbound_id = new_id()
        self.insert("outbound_message", id=outbound_id, case_id=case_id, action_key=f"{template}:{outbound_id}",
                    message_id=message_id, template=template, template_version="v1", status="accepted",
                    created_at=self.at(hours), updated_at=self.at(hours), accepted_at=self.at(hours))
        return outbound_id, message_id

    def job(self, kind, status, case_id=None, hours=0):
        job_id = new_id()
        self.insert("job", id=job_id, action_key=f"{kind}:{job_id}", kind=kind, case_id=case_id, payload={"ref": job_id},
                    status=status, next_run_at=self.at(hours), created_at=self.at(hours), updated_at=self.at(hours))


def report(stdout: str) -> dict:
    return json.loads(stdout)
