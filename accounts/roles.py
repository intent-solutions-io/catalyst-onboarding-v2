"""The staff role matrix, one grant path for every permission a staff screen checks (029 sections 5.2, 7 and 14;
9kg.30). The internal launch runs on the recommended default D-D4: the owner is the decision group, and the role
names are the ones the P2 to P5 designs use (016 F, 018 section 7, 021 section 9, 023 sections 8 and 15). The
production holders are the owner's decision (`211.7.8`); changing a holder changes no code.

Two kinds of role, both granted and revoked only by the owner-run `grant_staff_role` command, never by the running
application (D-23: the application role may not write users, memberships or permissions):

- **Group roles.** A group and its permission set are defined by migration (the P2 groups in correspondence 0004,
  0008 and 0012; the P3 groups in assessments 0002, 0005 and 0006; the P4 groups in agreements 0009; the P5 groups in
  provisioning 0007; the S1 read-only group in accounts 0003). The command only adds or removes a membership, and it
  refuses when a group's permissions differ from this matrix, so a role can never quietly carry more than it says.
- **Direct roles.** Two permissions are never carried by a group: the qualification decision (`decisions.can_decide`
  counts only a direct grant, 3B.4 reviews) and the provisioning approval (P5-D-3: delegates need explicit named
  grants). The command grants them per user, and grants the qualification decision only while the authority is
  configured (`CATALYST_QUALIFICATION_AUTHORITY`, POL-05).

Every grant and revocation writes an append-only `StaffRoleGrant` record (accounts migration 0006).
"""

from dataclasses import dataclass

READ_ONLY_STAFF = "Read-only staff"
VIEWABLE = {
    "applications": [
        "view_application",
        "view_submissionversion",
        "view_versionadoption",
        "view_applicationevent",
        "view_contactchallenge",
    ],
    "workflow": ["view_pendingaction", "view_automationpause"],
    "correspondence": ["view_outboundmessage"],
}
P2_CONTROLS = [
    "withdraw_question",
    "send_staff_message",
    "pause_automation",
    "resume_automation",
]


@dataclass(frozen=True)
class GroupRole:
    group: str
    permissions: dict  # {app_label: [codename]}
    design: str

    @property
    def expected(self) -> set:
        return {
            (app, codename)
            for app, codenames in self.permissions.items()
            for codename in codenames
        }


@dataclass(frozen=True)
class DirectRole:
    app_label: str
    codename: str
    design: str
    needs_authority: bool = (
        False  # refused until CATALYST_QUALIFICATION_AUTHORITY is configured (POL-05)
    )

    @property
    def expected(self) -> set:
        return {(self.app_label, self.codename)}


GROUP_ROLES = {
    "read-only-staff": GroupRole(READ_ONLY_STAFF, VIEWABLE, "S1-T7, D-23"),
    # P2 (016 F, D-30)
    "correspondence-operator": GroupRole(
        "Correspondence operator",
        {
            "correspondence": [
                "approve_question",
                "confirm_question_outcome",
                "resolve_exception",
                *P2_CONTROLS,
            ]
        },
        "016 F",
    ),
    "correspondence-decision-maker": GroupRole(
        "Correspondence decision-maker",
        {
            "correspondence": [
                "approve_question",
                "decide_uncertain_send",
                "restart_collector",
                "confirm_question_outcome",
                "resolve_exception",
                "resolve_identity_exception",
                *P2_CONTROLS,
            ]
        },
        "016 F",
    ),
    "template-owner": GroupRole(
        "Template owner",
        {"correspondence": ["approve_template_version"]},
        "016 F, D-29",
    ),
    # P3 (018 sections 3 and 7, P3-D-14)
    "assessment-operator": GroupRole(
        "Assessment operator",
        {
            "assessments": ["review_evidence", "operate_evidence", "rerun_assessment"],
            "correspondence": ["author_question"],
        },
        "018 section 7",
    ),
    "evidence-source-owner": GroupRole(
        "Evidence source owner",
        {"assessments": ["approve_evidence_source"]},
        "018 3.1, POL-03",
    ),
    # P4 (021 section 9; P4-D-8, P4-D-9, P4-D-16, D-43, D-46)
    "agreement-operator": GroupRole(
        "Agreement operator",
        {"agreements": ["view_agreementinstance", "operate_agreements"]},
        "021 section 9",
    ),
    "agreement-decision-maker": GroupRole(
        "Agreement decision-maker",
        {
            "agreements": [
                "view_agreementinstance",
                "decide_uncertain_agreement",
                "manage_agreements",
                "resolve_agreement_integrity",
                "retrieve_agreement_document",
                "confirm_required_details",
            ]
        },
        "021 section 9",
    ),
    "agreement-template-owner": GroupRole(
        "Agreement template owner",
        {"agreements": ["approve_agreement_template"]},
        "021 section 9, POL-07",
    ),
    # P5 (023 sections 8 and 15; P5-D-5, P5-D-11)
    "provisioning-operator": GroupRole(
        "Provisioning operator",
        {"provisioning": ["view_provisioningrequest", "operate_provisioning"]},
        "023 section 15",
    ),
    "provisioning-decision-maker": GroupRole(
        "Provisioning decision-maker",
        {
            "provisioning": [
                "view_provisioningrequest",
                "operate_provisioning",
                "close_application",
            ]
        },
        "023 section 15, POL-12",
    ),
}

DIRECT_ROLES = {
    "qualification-decision-maker": DirectRole(
        "assessments",
        "record_qualification_decision",
        "018 section 7, POL-05",
        needs_authority=True,
    ),
    "provisioning-approver": DirectRole(
        "provisioning", "approve_provisioning", "023 section 8, P5-D-3"
    ),
}

ROLES = {**GROUP_ROLES, **DIRECT_ROLES}


def every_granted_permission() -> set:
    """Every (app_label, codename) some role carries: the supported grant paths."""
    return {pair for role in ROLES.values() for pair in role.expected}
