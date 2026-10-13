"""The P2 role matrix for synthetic operation (016 section F; owner decision D-30). Groups and their
permissions are created by migration (correspondence 0004), run as the owner; the running application
can never create groups or grant itself permissions (D-23). Accounts join a group only through the
owner-run `add_correspondence_staff` command.

2B.1 holds the permissions its services need; later tasks add theirs to the same groups by migration.
"""

OPERATOR = "Correspondence operator"
DECISION_MAKER = "Correspondence decision-maker"
TEMPLATE_OWNER = "Template owner"

STAFF_CONTROLS = ["withdraw_question", "send_staff_message", "pause_automation", "resume_automation"]  # 2B.4

GROUP_PERMISSIONS = {
    OPERATOR: ["approve_question", "confirm_question_outcome", "resolve_exception", *STAFF_CONTROLS],
    DECISION_MAKER: ["approve_question", "decide_uncertain_send", "restart_collector", "confirm_question_outcome",
                     "resolve_exception", "resolve_identity_exception", *STAFF_CONTROLS],
    TEMPLATE_OWNER: ["approve_template_version"],
}
