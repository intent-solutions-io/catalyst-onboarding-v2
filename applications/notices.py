"""The data notice and the invitation mail (9kg.52; 030 Q8, D-51; 029 section 7).

The council decided the internal cohort is not candidate-impacting selection but its members are people with rights,
so a plain one-paragraph data notice is not deferred: what is collected, who sees it, that no model reads it and no
link is fetched, how to withdraw and how to request erasure. It is one message template (`data_notice`, seeded by
correspondence migration 0018) rendered in two places from the same approved version: the request-access page in
invitation mode and the invitation mail the owner sends (the `invitation` template, which carries the notice as its
one variable). The wording is never a constant in code: the owner approves it on the template screen like every
other template (211.7.7, D-29), and the version and content digest of what was rendered are recorded (on the
invitation row, in the command's output, and in the health report).

Unapproved wording: a local or synthetic environment (config.guards.DRAFT_WORDING_ENVIRONMENTS) renders the newest
draft with a visible draft marker so the page and the mail can be exercised before approval; a live environment
refuses (`Unavailable`), so the page is withheld and no invitation is issued until the owner approves. A live
environment also refuses an approved version still marked synthetic (`<key>_synthetic`: a placeholder approved for a
drill never reaches a real person) and a withdrawn one (`<key>_retired`, from the source). Real wording arrives as a
new draft version by a correspondence data migration, as every template version does, and the owner approves it.

The templates belong to the correspondence app and are reached only through the fixed path in
`CATALYST_NOTICE_SOURCE` (003 ADR-01: this app never imports a later app; the same seam pattern as
`CATALYST_ATTENTION_OPENER`). The source renders an approved version through its strict renderer and hands a draft
back as fields; the draft is substituted here with the standard library alone, never the template engine.
"""

from dataclasses import dataclass
from string import Template

from django.conf import settings
from django.utils.module_loading import import_string

from config import guards

from .reference import with_reference

DATA_NOTICE = "data_notice"
INVITATION = "invitation"
VERIFICATION = "verification_invitation"  # 9kg.80: the verification mail (correspondence migration 0020)
# bgl.5: the receipt at the first submission (correspondence migration 0026): alone, or as the verification mail.
RECEIPT = "intake_receipt"
RECEIPT_CONFIRM = "intake_receipt_confirm"
RECEIPT_VARIABLES = ("greeting", "reference", "submitted_on", "interest")
_TRIAL_RECEIPT = {"greeting": "Hello", "reference": "CAT-0000-0000", "submitted_on": "1 January 2026", "interest": ""}
_TRIAL_LINK = "https://link.invalid/"
DRAFT_MARKER = "DRAFT: placeholder wording the owner has not approved; shown only outside a live environment."


class Unavailable(Exception):
    """No approved version of the template, in an environment that may not show a draft. The message is a reason
    code; it never carries wording."""


@dataclass(frozen=True)
class Rendered:
    """What the source returns for an approved version: rendered, with the version's number, content digest and
    whether its wording is still a synthetic placeholder."""
    version: int
    sha256: str
    subject: str
    text: str
    synthetic: bool = True
    html: str = ""  # bgl.11: the HTML alternative, or "" for a text-only version
    subject_reference: bool = False  # bgl.5: the sender appends the application's reference to the subject


@dataclass(frozen=True)
class Draft:
    """What the source returns for a draft: its fields, unrendered."""
    version: int
    sha256: str
    subject: str
    body_text: str
    variables: tuple
    subject_reference: bool = False


@dataclass(frozen=True)
class Wording:
    key: str
    version: int
    sha256: str  # the version's content digest (subject, line feed, body), as recorded on the version
    subject: str
    text: str
    approved: bool
    html: str = ""  # bgl.11: the rendered HTML alternative of an approved version, or ""; a draft is sent as text only
    subject_reference: bool = False

    @property
    def draft(self) -> bool:
        return not self.approved

    @property
    def display(self) -> str:
        """The text as a person may see it: a draft always carries its marker."""
        return self.text if self.approved else f"{DRAFT_MARKER}\n{self.text}"

    def subject_for(self, reference: str) -> str:
        """bgl.5: the subject as sent to the applicant this reference belongs to: the static subject, with the reference
        appended when the version asks for it (amending 016 A1 for the reference alone)."""
        return with_reference(self.subject, reference) if self.subject_reference else self.subject


def _source(name: str):
    return import_string(f"{settings.CATALYST_NOTICE_SOURCE}.{name}")


def status(key: str = DATA_NOTICE) -> dict:
    """For the health report and the release receipt: the state of the wording, never the wording."""
    return _source("status")(key)


def servable(state: dict, environment: str) -> bool:
    """Whether wording in this state may be shown to a person here: approved and real, or any version where a
    draft may be shown (it is then marked). The health report's `data_notice_unapproved` is "not servable"."""
    if guards.draft_wording_allowed(environment):
        return state["status"] != "missing"
    return state["status"] == "approved" and not state["synthetic"]


def receipt_mode() -> str:
    """bgl.5: "off" (no receipt), "separate" (the receipt is its own mail, before the verification mail) or
    "verification" (the receipt is the verification mail, with the link)."""
    if not settings.CATALYST_INTAKE_RECEIPT:
        return "off"
    return "verification" if settings.CATALYST_RECEIPT_IS_VERIFICATION else "separate"


def verification_template() -> str:
    """The template the verification mail is rendered from: the receipt with the link in "verification" mode."""
    return RECEIPT_CONFIRM if receipt_mode() == "verification" else VERIFICATION


def _withheld(key: str, values: dict) -> bool:
    """Whether a trial render of `key` is refused here. Where a draft may be shown and the template row is absent, the
    seeded draft is sent (correspondence.verification, correspondence.receipt): not withheld."""
    try:
        wording(key, values)
    except Unavailable as refused:
        return not (guards.draft_wording_allowed(settings.CATALYST_ENV) and str(refused) == f"{key}_missing")
    return False


def verification_withheld() -> bool:
    """9kg.80: whether the verification mail could not be rendered here, so an accepted applicant could not be sent one:
    intake is withheld and health reports `verification_template_unapproved`. A trial render with a placeholder link
    decides (CodeRabbit on PR #132: a retired version or an invalid draft refuses the send in staging too). bgl.5: in
    "verification" receipt mode the verification mail is the receipt with the link, so that template decides."""
    if verification_template() == RECEIPT_CONFIRM:
        return _withheld(RECEIPT_CONFIRM, {**_TRIAL_RECEIPT, "link": _TRIAL_LINK})
    return _withheld(VERIFICATION, {"link": _TRIAL_LINK, "display_name": "Applicant"})


def receipt_withheld() -> bool:
    """bgl.5: in "separate" receipt mode, whether the receipt could not be rendered here, so an accepted applicant would
    get no receipt: intake is withheld like 9kg.80 and health reports `receipt_template_unapproved`. In the other modes
    there is no separate receipt to withhold for."""
    return receipt_mode() == "separate" and _withheld(RECEIPT, dict(_TRIAL_RECEIPT))


def wording(key: str, values: dict | None = None) -> Wording:
    values = values or {}
    drafts_allowed = guards.draft_wording_allowed(settings.CATALYST_ENV)
    rendered = _source("approved")(key, values)
    if rendered is not None:
        if rendered.synthetic and not drafts_allowed:
            raise Unavailable(f"{key}_synthetic")
        return Wording(key, rendered.version, rendered.sha256, rendered.subject, rendered.text, approved=True,
                       html=rendered.html, subject_reference=rendered.subject_reference)
    if not drafts_allowed:
        raise Unavailable(f"{key}_not_approved")
    draft = _source("draft")(key)
    if draft is None:
        raise Unavailable(f"{key}_missing")
    values = _source("fit_greeting")(draft.variables, values)
    if set(values) != set(draft.variables):
        raise Unavailable(f"{key}_values_do_not_match_allow_list")
    try:
        text = Template(draft.body_text).substitute(values)  # the standard library; values are not re-expanded
    except (KeyError, ValueError):  # a stray or unknown `$`: a refusal, never an error page
        raise Unavailable(f"{key}_invalid_placeholder") from None
    return Wording(key, draft.version, draft.sha256, draft.subject, text, approved=False,
                   subject_reference=draft.subject_reference)


def data_notice() -> Wording:
    return wording(DATA_NOTICE)


@dataclass(frozen=True)
class InvitationMail:
    subject: str
    body: str
    notice: Wording
    template: Wording  # the invitation template's own version and digest (body is the rendered mail)

    @property
    def draft(self) -> bool:
        return self.notice.draft or self.template.draft


def invitation_mail() -> InvitationMail:
    """The invitation mail body with the notice rendered in, for the owner to send by hand (029 section 5.1: v2
    contacts nobody on an invitation; the mail confirmation is the first automated message)."""
    notice = data_notice()
    mail = wording(INVITATION, {"notice": notice.display})
    return InvitationMail(mail.subject, mail.display, notice, mail)
