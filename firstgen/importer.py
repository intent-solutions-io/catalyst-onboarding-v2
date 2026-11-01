"""Write a first-generation snapshot into this database (bgl.16; 035). Owner path only.

Unit of work: one person (every case of one email key) per transaction. A malformed case fails alone, is reported
with a code, and leaves the others imported; a re-run imports exactly what is missing, because every first-generation
row is recorded once under (table, id) and every case once under its id (firstgen.models). Within the transaction the
deferred decision backstop (assessments 0008) is checked before the person commits (`SET CONSTRAINTS ALL IMMEDIATE`),
so a dry run sees the same refusals a real run would. Rows that belong to no case (owner notices, unmatched mail, the
mailbox cursor, details captured for people outside the service) are imported last, in their own transaction, with
their personal columns dropped and the drop reported.

What it creates for a case: the application at its mapped stage (no mail, no pending action); its submission versions;
the contact challenge and adoption that stand for the first generation's address verification, when there was one; a
decline decision for a declined case; one `imported_first_generation` event; an automation pause on every open
application, so nothing automatic happens to an imported person until staff review the case; the import record; the
agreement details of a completed User Agreement (confirmed, recorded by the import); the mailbox the first generation
created, as a live reservation and an `active` provisioning request, so v2 never reserves or creates it again; and,
per person, the member-on-file record of the agreements the first generation completed (applications.members), so
nobody is asked to sign twice. It never queues an action and never sends anything.
"""

import re
import uuid
from collections import Counter, defaultdict
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from agreements.models import AgreementDetailsVersion, AgreementType
from applications import members
from applications.identity import email_key
from applications.models import Application, ApplicationEvent, ContactChallenge, SubmissionVersion, VersionAdoption
from assessments.models import QualificationDecision
from provisioning.models import AddressReservation, ProvisioningRequest
from workflow.models import AutomationPause

from . import mapping, source
from .models import ImportedCase, ImportedRecord, ImportRun

ACTOR = "import:first-generation"
RECORDER = "first-generation import"  # a plain label (applications.members.check_recorder)
PAUSE_REASON = ("Imported from the first-generation service (bgl.16): automation stays off until staff have reviewed"
                " the case")
LOCAL_PART = r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$"
# Tables whose rows hold personal data: an unaccounted row of one fails the run (exit 2).
PERSONAL = ("intake_request", "intake_revision", "applicant_credential", "applicant_message", "agreement_details",
            "ua_details_capture", "mailbox_account", "review_evidence", "review_draft", "review_run")
# Columns never carried into a record: a secret, and the personal columns of rows that belong to no case.
SECRET_COLUMNS = {"intake_request": ("email_confirm_token_hash",)}
UNATTACHED_PERSONAL = {"ua_details_capture": ("display_name", "mailing_address", "signer_email_sha256")}
# The personal columns of rows whose content became a v2 record (kept there, not twice).
NATIVE_PERSONAL = {
    "intake_request": ("full_name", "personal_email", "email_key", "phone_e164", "phone_country", "work_links",
                       "building_text", "residence_country"),
    "intake_revision": ("full_name", "personal_email", "phone_e164", "phone_country", "work_links", "building_text",
                        "residence_country"),
    "agreement_details": ("legal_full_name", "residence", "mailing_address", "phone", "address_line1", "address_line2",
                          "locality", "region", "postal_code", "country_code"),
    "mailbox_account": ("username",),
}
# Per-case tables imported as records, with the record kind.
CASE_TABLES = {
    "case_event": "case_event", "agreement": "agreement", "legacy_agreement_import": "legacy_agreement_import",
    "outbound_message": "outbound_message", "inbound_message": "inbound_message", "applicant_message": "message",
    "review_run": "review_run", "review_evidence": "review_evidence", "review_question": "review_question",
    "review_draft": "review_draft", "crm_projection": "crm_projection", "crm_review_item": "crm_review_item",
    "case_release": "case_release", "ua_details_capture": "ua_details_capture",
}
OCCURRED = {"case_event": "created_at", "agreement": "created_at", "legacy_agreement_import": "completed_at",
            "outbound_message": "created_at", "inbound_message": "received_at", "applicant_message": "sent_at",
            "review_run": "started_at", "review_evidence": "fetched_at", "review_question": "created_at",
            "review_draft": "created_at", "crm_projection": "linked_at", "crm_review_item": "created_at",
            "case_release": "verified_at", "ua_details_capture": "completed_at", "intake_request": "created_at",
            "intake_revision": "created_at", "applicant_credential": "created_at", "agreement_details": "captured_at",
            "mailbox_account": "approved_at", "mailbox_cursor": "last_checked_at"}


class PersonFailed(Exception):
    """One person's cases are refused; the message is a code (never a value)."""


def _error_code(exc) -> str:
    diag = getattr(getattr(exc, "__cause__", None), "diag", None)
    name = getattr(diag, "constraint_name", None) if diag else None
    return f"{type(exc).__name__}:{name}" if name else type(exc).__name__


class Importer:
    def __init__(self, snap: source.Snapshot, actor_ref: str):
        self.snap, self.actor_ref = snap, actor_ref
        self.run_ref = uuid.uuid4()
        self.outcomes = defaultdict(dict)  # {table: {v1 id: ("mapped" | "already" | "skipped", detail)}}
        self.created = Counter()
        self.failures, self.followups, self.findings = [], [], Counter()
        self.states = defaultdict(Counter)
        self.by_case = defaultdict(lambda: defaultdict(list))  # {case id: {table: [rows]}}
        self.unattached = defaultdict(list)
        cases = {c["id"] for c in snap.rows["onboarding_case"]}
        for table, rows in snap.rows.items():
            if table == "onboarding_case":
                continue
            key = source.TABLES[table]
            for row in rows:
                case_id = row.get("case_id")
                if case_id is None and table in ("outbound_message", "inbound_message", "ua_details_capture",
                                                 "mailbox_cursor"):
                    self.unattached[table].append(row)
                elif case_id in cases:
                    self.by_case[case_id][table].append(row)
                else:
                    self.outcomes[table][str(row[key])] = ("skipped", "orphan_case")
        self.existing = set(ImportedRecord.objects.values_list("v1_table", "v1_id"))
        self.imported_cases = dict(ImportedCase.objects.values_list("v1_case_id", "application_id"))
        self.jobs_by_case = defaultdict(list)
        for job in snap.open_jobs:
            self.jobs_by_case[job.get("case_id")].append(job)

    # --- accounting ----------------------------------------------------------------------------------------------

    def mark(self, table, v1_id, outcome, detail=""):
        self.outcomes[table][str(v1_id)] = (outcome, detail)

    def record(self, table, row, application, kind, *, drop=(), target="", message_id=""):
        key = str(row[source.TABLES[table]])
        if (table, key) in self.existing:
            self.mark(table, key, "already")
            return
        ImportedRecord.objects.create(
            v1_table=table, v1_id=key, application=application, kind=kind,
            occurred_at=row.get(OCCURRED.get(table, "created_at")), message_id=message_id or "", target=target,
            data=mapping.jsonable(row, drop=(*drop, *SECRET_COLUMNS.get(table, ()))), run_ref=self.run_ref)
        self.existing.add((table, key))
        self.created["firstgen.ImportedRecord"] += 1
        self.mark(table, key, "mapped", target or "firstgen.ImportedRecord")

    # --- the run ----------------------------------------------------------------------------------------------------

    def run(self):
        people = defaultdict(list)
        for case in self.snap.rows["onboarding_case"]:
            request = next(iter(self.by_case[case["id"]]["intake_request"]), None)
            if request is None:
                self.fail_case(case, "case_without_intake_request")
                continue
            try:
                people[email_key(request["personal_email"])].append((case, request))
            except ValueError:
                self.fail_case(case, "intake_email_not_an_address")
        for key, cases in people.items():
            cases.sort(key=lambda pair: pair[0]["created_at"])
            saved = self._save()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET CONSTRAINTS ALL DEFERRED")
                    done = [self.import_case(key, case, request) for case, request in cases]
                    self.member_on_file(cases, done)
                    with connection.cursor() as cursor:
                        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")  # the decision backstop, before the commit
            except Exception as exc:  # any failure of one person is reported with a code; the others go on
                self._restore(saved)  # nothing of this person committed: neither do its counts
                code = str(exc) if isinstance(exc, PersonFailed) else _error_code(exc)
                for case, _ in cases:
                    if case["id"] not in self.imported_cases:
                        self.fail_case(case, code)
        with transaction.atomic():
            self.import_unattached()

    def _save(self):
        return (Counter(self.created), {t: dict(o) for t, o in self.outcomes.items()}, Counter(self.findings),
                list(self.followups), {k: Counter(v) for k, v in self.states.items()}, set(self.existing),
                dict(self.imported_cases))

    def _restore(self, saved):
        created, outcomes, findings, followups, states, existing, imported = saved
        self.created, self.findings, self.followups = Counter(created), Counter(findings), list(followups)
        self.outcomes = defaultdict(dict, {t: dict(o) for t, o in outcomes.items()})
        self.states = defaultdict(Counter, {k: Counter(v) for k, v in states.items()})
        self.existing, self.imported_cases = set(existing), dict(imported)

    def fail_case(self, case, code):
        reference = next((r["reference"] for r in self.by_case[case["id"]]["intake_request"]), "")
        self.failures.append({"v1_case": case["id"], "reference": reference, "error": code})
        self.mark("onboarding_case", case["id"], "skipped", f"case_failed:{code}")
        for table, rows in self.by_case[case["id"]].items():
            for row in rows:
                self.mark(table, row[source.TABLES[table]], "skipped", f"case_failed:{code}")

    # --- one case -----------------------------------------------------------------------------------------------

    def import_case(self, key, case, request):
        rows = self.by_case[case["id"]]
        if case["id"] in self.imported_cases:
            return self.top_up(case, rows)
        state = case["state"]
        events = sorted(rows["case_event"], key=lambda e: (e["created_at"], e["id"]))
        resume = next((e.get("from_state") or "" for e in reversed(events)
                       if e.get("subject") == "case" and e.get("to_state") == "lapsed"), "") if state == "lapsed" else ""
        verified_at = request.get("email_verified_at")
        try:
            stage = mapping.stage_for(state, resume, verified_at is not None)
        except mapping.Unmappable as why:
            raise PersonFailed(str(why)) from None
        if stage in mapping.OPEN_STAGES and Application.objects.filter(
                email_key=key, stage__in=mapping.OPEN_STAGES).exclude(first_generation__isnull=False).exists():
            raise PersonFailed("open_v2_application_exists")
        findings = list(mapping.STATE_FINDINGS.get(state, []))
        email = request["personal_email"]
        revisions = sorted(rows["intake_revision"], key=lambda r: r["created_at"])
        app = Application.objects.create(
            reference=request["reference"], email=email, email_key=key, display_name=(request.get("full_name") or "")[:200], stage=stage,
            contact_verified_at=verified_at, next_version_number=2 + len(revisions), created_at=case["created_at"],
            updated_at=timezone.now())
        self.created["applications.Application"] += 1
        self.states[state][stage] += 1
        credentials = rows["applicant_credential"]
        version = SubmissionVersion.objects.create(
            application=app, version_number=1, origin="form", received_at=request["created_at"],
            submitted_fields=mapping.submitted_fields(
                request, request["reference"], [c for c in credentials if c.get("intake_request_id") == request["id"]],
                "intake_request"))
        self.created["applications.SubmissionVersion"] += 1
        self.record("intake_request", request, app, "intake_request", drop=NATIVE_PERSONAL["intake_request"],
                    target=f"applications.SubmissionVersion:{version.public_id}")
        for n, revision in enumerate(revisions, start=2):
            after = verified_at is not None and revision["created_at"] > verified_at
            later = SubmissionVersion.objects.create(
                application=app, version_number=n, origin="repeat_after_verification" if after else "form",
                received_at=revision["created_at"], submitted_fields=mapping.submitted_fields(
                    revision, request["reference"],
                    [c for c in credentials if c.get("intake_revision_id") == revision["id"]], "intake_revision"))
            self.created["applications.SubmissionVersion"] += 1
            self.record("intake_revision", revision, app, "intake_revision", drop=NATIVE_PERSONAL["intake_revision"],
                        target=f"applications.SubmissionVersion:{later.public_id}")
        for credential in credentials:  # their answers are in the versions; the verification detail is kept here
            self.record("applicant_credential", credential, app, "applicant_credential")
        if verified_at is not None:
            challenge = ContactChallenge.objects.create(
                application=app, email_at_issue=email, created_at=request["created_at"],
                expires_at=max(verified_at, request["created_at"]) + timedelta(seconds=1), used_at=verified_at)
            VersionAdoption.objects.create(application=app, submission_version=version, via_challenge=challenge,
                                           adopted_at=verified_at)
            self.created["applications.ContactChallenge"] += 1
            self.created["applications.VersionAdoption"] += 1
            findings.append(f"contact_verified_in_v1_by:{request.get('email_verified_via') or 'unknown'}")
        elif stage not in ("submitted", "withdrawn", "declined", "closed"):
            findings.append("contact_not_verified_in_v1")
        if stage == "declined":
            self.decline(app, version, events)
        if stage in mapping.OPEN_STAGES:
            AutomationPause.objects.create(subject_type="application", subject_id=app.public_ref, reason=PAUSE_REASON,
                                           actor_ref=ACTOR)
            self.created["workflow.AutomationPause"] += 1
        crm = next(iter(rows["crm_projection"]), {})
        findings += self.agreements(app, rows)
        findings += self.mailbox(app, rows, stage)
        for table, kind in CASE_TABLES.items():
            for row in rows[table]:
                self.record(table, row, app, kind,
                            message_id=row.get("message_id") or "" if table == "outbound_message" else "")
        ApplicationEvent.objects.create(
            application=app, kind="imported_first_generation", actor_type="system", actor_ref=ACTOR,
            data={"reference": request["reference"], "v1_state": state, "v1_resume_state": resume, "stage": stage,
                  "run": str(self.run_ref)})
        self.created["applications.ApplicationEvent"] += 1
        followups = self.followups_for(case, stage, state, rows, findings)
        ImportedCase.objects.create(
            application=app, v1_case_id=case["id"], reference=request["reference"], v1_state=state,
            v1_resume_state=resume, v1_cohort=case.get("cohort") or "", v1_created_at=case["created_at"],
            v1_state_changed_at=case.get("state_changed_at") or case["created_at"], mapped_stage=stage,
            crm_person_id=crm.get("person_id") or "", crm_note_id=crm.get("note_id") or "",
            findings=sorted(set(findings)), run_ref=self.run_ref)
        self.created["firstgen.ImportedCase"] += 1
        self.mark("onboarding_case", case["id"], "mapped", "firstgen.ImportedCase")
        self.findings.update(set(findings))
        if followups:
            self.followups.append({"reference": request["reference"], "v1_state": state, "stage": stage,
                                   "needs": followups})
        self.imported_cases[case["id"]] = app.pk
        return app

    def top_up(self, case, rows):
        """A case imported by an earlier run: only rows added since become records. A late row of a table that maps to
        a v2 record (a revision, a credential, details, a mailbox) is kept as a record and reported, never applied."""
        app = Application.objects.get(pk=self.imported_cases[case["id"]])
        self.mark("onboarding_case", case["id"], "already")
        imported = ImportedCase.objects.get(v1_case_id=case["id"])
        if imported.v1_state != case["state"]:
            self.findings[f"v1_state_changed_since_import:{imported.v1_state}->{case['state']}"[:64]] += 1
        for table, table_rows in rows.items():
            for row in table_rows:
                late = (table, str(row[source.TABLES[table]])) not in self.existing
                if late and table in ("intake_revision", "applicant_credential", "agreement_details", "mailbox_account",
                                      "intake_request"):
                    self.findings[f"late_row_not_applied:{table}"] += 1
                self.record(table, row, app, CASE_TABLES.get(table, table),
                            message_id=row.get("message_id") or "" if table == "outbound_message" else "")
        return app

    def decline(self, app, version, events):
        event = next((e for e in reversed(events) if e.get("subject") == "case" and e.get("to_state") == "declined"), {})
        fields = version.submitted_fields
        QualificationDecision.objects.create(
            application=app, adopted_version=version, run=None, outcome="decline", basis="human_only",
            human_only_reason="Declined on the first-generation service; imported (bgl.16)",
            human_only_code="first_generation", reason_code=mapping.reason_code(event.get("reason"), "first_generation"),
            rationale={}, snapshot_sha256=mapping.digest(fields),
            decision_digest=mapping.digest({"v1_event": event.get("id"), "reason": event.get("reason")}),
            policy_ref=(event.get("policy_version") or "first-generation")[:100],
            decision_inputs={"source": "first_generation", "v1_event": event.get("id"),
                             "decided_at": mapping.iso(event.get("created_at")), "v1_actor": event.get("actor")},
            actor_ref=f"first-generation:{event.get('actor') or 'unknown'}"[:200])
        self.created["assessments.QualificationDecision"] += 1

    # --- agreements and details --------------------------------------------------------------------------------------

    def agreements(self, app, rows) -> list:
        findings = []
        by_id = {a["id"]: a for a in rows["agreement"]}
        for agreement in rows["agreement"]:
            if agreement["status"] in mapping.OPEN_AGREEMENT and agreement.get("provider_ref"):
                findings.append(f"open_v1_envelope:{agreement['document_type']}")
        types = {t.key: t for t in AgreementType.objects.all()}
        for details in sorted(rows["agreement_details"], key=lambda d: d["captured_at"]):
            agreement = by_id.get(details["agreement_id"], {})
            agreement_type = types.get(agreement.get("document_type", "user_agreement"))
            if agreement_type is None:
                self.record("agreement_details", details, app, "agreement_details")
                findings.append("details_type_unknown_in_v2")
                continue
            values = mapping.details_values(details)
            number = AgreementDetailsVersion.objects.filter(application=app, agreement_type=agreement_type).count() + 1
            row = AgreementDetailsVersion.objects.create(
                application=app, agreement_type=agreement_type, version=number, values=values,
                values_sha256=mapping.digest(values), recorded_by=ACTOR)
            AgreementDetailsVersion.objects.filter(pk=row.pk).update(
                status="confirmed", confirmed_by=f"{ACTOR}:documenso-readback", confirmed_at=details["captured_at"])
            self.created["agreements.AgreementDetailsVersion"] += 1
            self.record("agreement_details", details, app, "agreement_details", drop=NATIVE_PERSONAL["agreement_details"],
                        target=f"agreements.AgreementDetailsVersion:{row.public_id}")
        return findings

    def member_on_file(self, cases, apps):
        """The agreements the first generation completed for this person, as one member-on-file record (the latest
        completed version of each type). An owner-recorded record that differs is kept, never superseded."""
        covers = {}
        for case, _ in cases:
            for agreement in sorted(self.by_case[case["id"]]["agreement"], key=lambda a: a["created_at"]):
                if agreement["status"] in mapping.COMPLETED_AGREEMENT and agreement["document_type"] in members.COVERABLE:
                    covers[agreement["document_type"]] = mapping.agreement_label(agreement)
        if not covers:
            return
        try:
            _, outcome = members.record(apps[-1].email, covers, RECORDER)
        except members.Refused as why:
            self.findings[f"member_on_file_not_recorded:{why}"[:64]] += 1
            return
        if outcome == "recorded":
            self.created["applications.MemberAgreementOnFile"] += 1

    # --- the mailbox -----------------------------------------------------------------------------------------------

    def mailbox(self, app, rows, stage) -> list:
        findings = []
        for account in rows["mailbox_account"]:
            local, domain = (account.get("username") or "").lower(), (account.get("domain") or "").lower()
            if not re.match(LOCAL_PART, local) or ".." in local or not domain:
                self.record("mailbox_account", account, app, "mailbox_account")
                findings.append("mailbox_name_not_reservable")
                continue
            if AddressReservation.objects.filter(local_part__iexact=local, domain__iexact=domain,
                                                 released_at__isnull=True).exists():
                self.record("mailbox_account", account, app, "mailbox_account")
                findings.append("mailbox_already_reserved_in_v2")
                continue
            reservation = AddressReservation.objects.create(
                application=app, local_part=local, domain=domain, basis="reviewed_exception", reviewed_by=ACTOR,
                created_at=account.get("approved_at") or timezone.now())
            created = account.get("status") == "created"
            facts = {"source": "first_generation", "v1_mailbox": account["id"], "v1_status": account.get("status")}
            ProvisioningRequest.objects.create(
                application=app, reservation=reservation, method="checklist",
                quota_mb=settings.CATALYST_PROVISIONING_QUOTA_MB, send_limit=settings.CATALYST_PROVISIONING_SEND_LIMIT,
                prerequisite_digest=mapping.digest(facts), approval_digest=mapping.digest({**facts, "approval": True}),
                status="active" if created else "failed_needs_staff",
                approved_by=f"first-generation:{account.get('approved_by') or 'unknown'}"[:200],
                approved_at=account.get("approved_at") or timezone.now())
            self.created["provisioning.AddressReservation"] += 1
            self.created["provisioning.ProvisioningRequest"] += 1
            if not created:
                findings.append("v1_mailbox_approved_not_created_check_mxroute")
            elif account.get("welcome_sent_at") is None:
                findings.append("v1_welcome_not_recorded_as_sent")
            if created and stage in ("withdrawn", "declined", "closed"):
                findings.append("v1_mailbox_exists_for_closed_case_revoke_by_hand")
            self.record("mailbox_account", account, app, "mailbox_account", drop=NATIVE_PERSONAL["mailbox_account"],
                        target=f"provisioning.AddressReservation:{reservation.public_id}")
        return findings

    # --- rows of no case -------------------------------------------------------------------------------------------

    def import_unattached(self):
        for table, rows in self.unattached.items():
            for row in rows:
                drop = UNATTACHED_PERSONAL.get(table, ())
                self.record(table, row, None, CASE_TABLES.get(table, table), drop=drop,
                            message_id=row.get("message_id") or "" if table == "outbound_message" else "")
                if drop:
                    self.findings[f"personal_columns_dropped_no_case:{table}"] += 1

    # --- after the import ---------------------------------------------------------------------------------------------

    def followups_for(self, case, stage, state, rows, findings) -> list:
        """What v2 must do to continue this case, as codes (035 section 5). The import queues none of it."""
        needs = []
        if stage == "submitted":
            needs.append("verify_contact: the first-generation confirm link is not honoured by v2; staff re-send the"
                         " verification")
        elif stage in ("contact_verified", "assessing", "awaiting_decision"):
            needs.append("decide: a staff decision on the decision screen (the first-generation review is history)")
        elif stage == "awaiting_answers":
            needs.append("answers: staff read replies to the first-generation questions (threads associate through"
                         " firstgen.threads once wired) and decide")
        elif stage == "agreements":
            needs.append("agreements: an open first-generation envelope cannot be watched by v2; the owner checks"
                         " Documenso and records completion (catalyst_member_on_file) or cancels and reissues")
        elif stage == "agreements_complete":
            needs.append("provision: staff approve the mailbox on the provisioning screen")
        elif stage == "provisioning":
            needs.append("provision: check MXroute for the mailbox the first generation was creating")
        if "v1_offboarding_incomplete_revoke_by_hand" in findings:
            needs.append("revoke: finish the first-generation offboarding by hand")
        jobs = Counter(f"{j['kind']}/{j['status']}" for j in self.jobs_by_case.get(case["id"], []))
        if jobs:
            needs.append("v1_jobs_not_carried: " + ", ".join(f"{k} x{n}" for k, n in sorted(jobs.items())))
        if stage in mapping.OPEN_STAGES:
            needs.append("resume_automation: staff resume the import's automation pause when the case is reviewed")
        return needs

    def report(self, dry_run: bool) -> dict:
        tables = {}
        unaccounted_personal = 0
        all_tables = ("onboarding_case", *[t for t in source.TABLES if t != "onboarding_case"])
        for table in all_tables:
            rows = self.snap.rows.get(table, [])
            outcomes = self.outcomes.get(table, {})
            ids = {str(r[source.TABLES[table]]) for r in rows}
            counts = Counter(o for o, _ in outcomes.values())
            skipped = Counter(d for o, d in outcomes.values() if o == "skipped")
            unaccounted = len(ids - set(outcomes))
            if table in PERSONAL:
                unaccounted_personal += unaccounted
            tables[table] = {"read": len(rows), "mapped": counts["mapped"], "already_imported": counts["already"],
                             "skipped": dict(skipped), "unaccounted": unaccounted}
        for table, n in self.snap.counted.items():
            tables[table] = {"read": n, "mapped": 0, "already_imported": 0,
                             "skipped": {"operational_not_imported": n}, "unaccounted": 0}
        open_jobs = Counter(f"{j['kind']}/{j['status']}" for j in self.snap.open_jobs)
        return {
            "run": str(self.run_ref), "dry_run": dry_run, "source_fingerprint": self.snap.fingerprint,
            "tables": tables, "missing_tables": sorted(self.snap.missing),
            "dormant_rows": {t: n for t, n in self.snap.dormant.items() if n},
            "created": dict(sorted(self.created.items())),
            "states": {s: dict(m) for s, m in sorted(self.states.items())},
            "failures": self.failures, "findings": dict(sorted(self.findings.items())),
            "followups": self.followups,
            "jobs": {"by_kind_status": self.snap.job_counts, "open_or_failed_for_cases": dict(sorted(open_jobs.items())),
                     "queued_in_v2": 0},
            "personal_rows_dropped_without_reason": unaccounted_personal,
        }

    def save_run(self, report):
        ImportRun.objects.create(public_id=self.run_ref, actor_ref=self.actor_ref, source_ref=self.snap.fingerprint,
                                 report={k: report[k] for k in ("tables", "created", "states", "findings", "jobs",
                                                                "personal_rows_dropped_without_reason")}
                                 | {"failures": len(report["failures"]), "followups": len(report["followups"])})
