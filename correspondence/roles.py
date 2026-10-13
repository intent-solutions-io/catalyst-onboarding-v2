"""The P2 role matrix for synthetic operation (016 section F; owner decision D-30). Groups and their
permissions are created by migration (correspondence 0004), run as the owner; the running application
can never create groups or grant itself permissions (D-23). Accounts join a group only through the
owner-run `add_correspondence_staff` command.

2B.1 holds the permissions its services need; later tasks add theirs to the same groups by migration.
"""

OPERATOR = "Correspondence operator"
DECISION_MAKER = "Correspondence decision-maker"
TEMPLATE_OWNER = "Template owner"

GROUP_PERMISSIONS = {
    OPERATOR: ["approve_question"],
    DECISION_MAKER: ["approve_question", "decide_uncertain_send"],
    TEMPLATE_OWNER: ["approve_template_version"],
}
