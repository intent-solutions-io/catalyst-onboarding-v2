"""The real wording for wave 1 of the internal trial (D-53, 2026-10-29): the data notice, the invitation and the
verification mail, written from decisions already recorded (033 Q1, Q5, Q6, Q8, Q9; D-53), never from invented
promises. `manage.py catalyst_seed_wording` adds each as a new draft, non-synthetic version of its template; the owner
reads and approves it on the template screen (D-29), which is what lets a live environment serve it.

What each sentence rests on:
- who sees it: the owner is the only staff member (033 Q8); the staff site is reachable only from the owner's two
  devices (211.7.5);
- services: MXroute carries the mail; the host and its backups are run by the hosting and backup-storage providers;
  signing is off in wave 1, so no signing service is named;
- no model and no fetch: model advice and evidence fetching stay disabled (D-52);
- not an appraisal: no criterion is rated and nobody is declined in a live environment (033 Q5, Q6; 9kg.85);
- how long: R1 12 months, R2 3 months, erasure within 30 days of a request (033 Q1); the backup window as the
  estate's backup record states it (borg prune keeps up to six monthly archives; the home-server snapshots are kept
  until pruned), and a restore re-applies every erasure (the replay, PR #103);
- what remains after erasure: "a pseudonymous record" (033 Q1, never "anonymized").
"""

DATA_NOTICE_SUBJECT = "How your information is handled"
DATA_NOTICE_BODY = (
    "This onboarding service is run by intentsolutions.io LLC as an internal trial. Only team members invited by the "
    "company's owner can use it. Taking part is not used for any employment or pay decision, and nothing you send is "
    "rated.\n\n"
    "What we collect: the name and email address you enter, your reason for asking, and anything you choose to add "
    "about your work and credentials (links, short descriptions, credential details). We also keep the record of your "
    "email confirmation, the messages between you and us, and what happened to your request.\n\n"
    "Who can see it: only the company's owner, through a staff site with two-step sign-in that only the owner's own "
    "devices can reach.\n\n"
    "Services involved: our email provider carries this service's messages, and the server and its backups are run by "
    "our hosting and backup-storage providers. No automated model reads your information, and the service does not "
    "open or fetch any link you give: a person reads your request and a person makes every decision.\n\n"
    "How long we keep it: if your request ends without going further, 12 months after it ends; if you are invited and "
    "never send the form, 3 months after the invitation expires. Our backups keep older copies for up to six months, "
    "and some archived copies until they are removed; they are used only to recover the service, and if one is ever "
    "restored, every erasure is applied again.\n\n"
    "To correct your details, withdraw your request or have your information erased, reply to any message from this "
    "service. We erase it within 30 days and confirm by email. What remains is a pseudonymous record that an erasure "
    "took place, with no name, address or content.\n"
)

INVITATION_SUBJECT = "You are invited to the onboarding trial"
INVITATION_BODY = (
    "Hello,\n\n"
    "You are invited to try our new onboarding service, an internal trial for team members. To take part, open "
    "https://catalyst-v2.intentsolutions.io/request-access/ and send the form from this email address. A request from "
    "any other address gets no reply. This invitation is valid for 14 days and is used up once you confirm your email "
    "address.\n\n"
    "$notice\n\n"
    "If you did not expect this invitation, ignore it. Nothing happens unless you send the form.\n\n"
    "Jeremy Longshore, intentsolutions.io LLC\n"
)

VERIFICATION_SUBJECT = "Confirm your email address"
VERIFICATION_BODY = (
    "Hello,\n\n"
    "A request to join the intentsolutions.io onboarding trial was sent with this email address. If it was you, open "
    "this link to check the answers we received and confirm them:\n\n"
    "$link\n\n"
    "The link works once and expires after 24 hours. If it was not you, ignore this message or reply to tell us.\n"
)

# key -> (subject, body, variables)
REAL = {
    "data_notice": (DATA_NOTICE_SUBJECT, DATA_NOTICE_BODY, []),
    "invitation": (INVITATION_SUBJECT, INVITATION_BODY, ["notice"]),
    "verification_invitation": (VERIFICATION_SUBJECT, VERIFICATION_BODY, ["link"]),
}
