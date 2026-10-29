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

DATA_NOTICE = "data_notice"
INVITATION = "invitation"
VERIFICATION = "verification_invitation"  # 9kg.80: the verification mail (correspondence migration 0020)
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


@dataclass(frozen=True)
class Draft:
    """What the source returns for a draft: its fields, unrendered."""
    version: int
    sha256: str
    subject: str
    body_text: str
    variables: tuple


@dataclass(frozen=True)
class Wording:
    key: str
    version: int
    sha256: str  # the version's content digest (subject, line feed, body), as recorded on the version
    subject: str
    text: str
    approved: bool

    @property
    def draft(self) -> bool:
        return not self.approved

    @property
    def display(self) -> str:
        """The text as a person may see it: a draft always carries its marker."""
        return self.text if self.approved else f"{DRAFT_MARKER}\n{self.text}"


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


def verification_withheld() -> bool:
    """9kg.80: a live environment has no approved, non-synthetic verification mail, so an accepted applicant could not
    be sent one: intake is withheld and health reports `verification_template_unapproved`. Where a draft may be shown,
    the seeded draft is sent, marked (correspondence.verification), so nothing is withheld there."""
    if guards.draft_wording_allowed(settings.CATALYST_ENV):
        return False
    return not servable(status(VERIFICATION), settings.CATALYST_ENV)


def wording(key: str, values: dict | None = None) -> Wording:
    values = values or {}
    drafts_allowed = guards.draft_wording_allowed(settings.CATALYST_ENV)
    rendered = _source("approved")(key, values)
    if rendered is not None:
        if rendered.synthetic and not drafts_allowed:
            raise Unavailable(f"{key}_synthetic")
        return Wording(key, rendered.version, rendered.sha256, rendered.subject, rendered.text, approved=True)
    if not drafts_allowed:
        raise Unavailable(f"{key}_not_approved")
    draft = _source("draft")(key)
    if draft is None:
        raise Unavailable(f"{key}_missing")
    if set(values) != set(draft.variables):
        raise Unavailable(f"{key}_values_do_not_match_allow_list")
    try:
        text = Template(draft.body_text).substitute(values)  # the standard library; values are not re-expanded
    except (KeyError, ValueError):  # a stray or unknown `$`: a refusal, never an error page
        raise Unavailable(f"{key}_invalid_placeholder") from None
    return Wording(key, draft.version, draft.sha256, draft.subject, text, approved=False)


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
