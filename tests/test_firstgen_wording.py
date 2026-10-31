"""bgl.11: the first generation's email wording loaded into v2 as template versions with their HTML part, and v2
sending multipart mail (text plus HTML) when a version has one.

Every file under the synthetic source below is invented placeholder text in the first generation's formats (Jinja
email templates, token assets, Python senders for subjects): no first-generation wording is in this repository.
"""

import dataclasses
import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from psycopg import errors

from correspondence import firstgen_wording as fg
from correspondence import outbound
from correspondence.models import MessageTemplate, MessageTemplateVersion
from correspondence.rendering import (
    TemplateRefused, canonical_digest, check_version, html_placement_problem, render, render_html, version_digest)
from tests.test_intake_notice import template_owner
from tests.test_outbound import ask, p2, question_template, ready, run_worker  # noqa: F401 (fixture chain)
from tests.test_verification_wording import ensure_template as ensure_verification_template

SYNTHETIC = {
    "src/catalyst/templates/email/_partner_badge.txt": "{#- synthetic -#}\nSynthetic Signer\n{{ partner_badge.name }}\n",
    "src/catalyst/templates/email/_partner_badge.html": (
        "<td><p>Synthetic Signer</p><a href=\"{{ partner_badge.url }}\">{{ partner_badge.name }}</a></td>\n"),
    "src/catalyst/branding.py": 'PARTNER_BADGE = Badge(name="Synthetic badge", url="https://badge.example.test/b")\n',
    "src/catalyst/templates/email/intake_receipt.txt": (
        "{#- synthetic header -#}\n"
        "{{ _('Synthetic heading') }}\n\n"
        "{{ _('Hello') }}{% if greeting_name %} {{ greeting_name }}{% endif %},\n\n"
        "{{ _('Synthetic reference line') }}: {{ intake.reference }}\n"
        "{% if ask_to_confirm %}{% if confirm_url %}{{ _('Synthetic confirm') }}: {{ confirm_url }}\n"
        "{% endif %}{% endif %}\n"
        "{{ _('Synthetic price %(amount)s', amount='$5') }}\n\n"
        "{% include \"email/_partner_badge.txt\" %}\n\n"
        "Synthetic Sender\n{{ service_address }}\n"),
    "src/catalyst/templates/email/intake_receipt.html": (
        "<html lang=\"{{ current_locale() }}\">\n"
        "<p>{{ _('Synthetic heading') }}</p>\n"
        "<p>{{ _('Synthetic reference line') }}: {{ intake.reference }}</p>\n"
        "{% if confirm_url %}<p><a href=\"{{ confirm_url }}\">{{ _('Synthetic confirm') }}</a></p>{% endif %}\n"
        "<p>{{ _(\"Synthetic it's\") }}</p>\n"
        "{% include \"email/_partner_badge.html\" %}\n"
        "</html>\n"),
    "src/catalyst/intake/receipt.py": 'def receipt_subject(reference):\n    return f"Synthetic receipt subject [{reference}]"\n',
    "src/catalyst/templates/email/review_clarification.txt": (
        "Hello{% if greeting_name %} {{ greeting_name }}{% endif %},\n\n{{ body_text }}\n\nReference: {{ reference }}\n"),
    "src/catalyst/templates/email/review_clarification.html": (
        "<p>Hello{% if greeting_name %} {{ greeting_name }}{% endif %},</p>\n"
        "{% for paragraph in paragraphs %}<p>{{ paragraph }}</p>{% endfor %}\n<p>Reference: {{ reference }}</p>\n"),
    "src/catalyst/review/correspondence.py": (
        'def build_message(intake):\n    message = {}\n'
        '    message["Subject"] = f"Synthetic question subject [{intake.reference}]"\n'),
    "src/catalyst/signing/assets/ua_cover.txt": "Hi {{FIRST_NAME}},\nSynthetic cover {{SIGN_URL}}\n{{UNKNOWN_TOKEN}}\n",
    "src/catalyst/signing/assets/ua_cover.html": (
        "<p>Hi {{FIRST_NAME}},</p><!--PILOT--><p>Synthetic pilot card</p><!--/PILOT-->\n"
        "<p><a href=\"{{SIGN_URL}}\">Synthetic sign</a></p>\n"),
    "src/catalyst/signing/cover.py": 'SUBJECT = "Synthetic cover subject"\n',
    "src/catalyst/mailbox/assets/welcome.txt": "Hi {{FIRST_NAME}},\nUser {{USERNAME}}@mail.example.test\nPass {{TEMP_PASSWORD}}\n",
    "src/catalyst/mailbox/assets/welcome.html": "<p>Hi {{FIRST_NAME}}</p><p><code>{{TEMP_PASSWORD}}</code></p>\n",
    "src/catalyst/mailbox/assets/welcome.manifest.json": '{"subject": "Synthetic welcome subject"}',
    "src/catalyst/templates/email/review_clarification_reminder.txt": (
        "Hello{% if greeting_name %} {{ greeting_name }}{% endif %},\n\nSynthetic intro {{ sent_on }}\n"
        "{% for item in asked %}\n- {{ item }}{% endfor %}\n\nSynthetic close.{% if final %} Synthetic last.{% endif %}\n"),
    "src/catalyst/templates/email/review_clarification_reminder.html": (
        "<p>Hello{% if greeting_name %} {{ greeting_name }}{% endif %},</p>\n"
        "<ul>{% for item in asked %}<li>{{ item }}</li>{% endfor %}</ul>\n"),
    "src/catalyst/review/reminder.py": (
        'def build_message(intake):\n    message = {}\n'
        '    message["Subject"] = f"Re: Synthetic question subject [{intake.reference}]"\n'),
    "src/catalyst/templates/email/case_lapse_note.txt": (
        "Hello{% if greeting_name %} {{ greeting_name }}{% endif %},\n\n"
        "{% if questions %}Synthetic reply branch.{% else %}Synthetic sign the {{ document }}.{% endif %}\n"),
    "src/catalyst/templates/email/case_lapse_note.html": "<p>{% if questions %}Synthetic reply branch.{% endif %}</p>\n",
    "src/catalyst/lapse.py": (
        'def build_message(intake):\n    message = {}\n'
        '    message["Subject"] = f"Synthetic lapse subject [{intake.reference}]"\n'),
    "src/catalyst/templates/email/signing_link.txt": (
        "{{ _('Synthetic sign: %(title)s', title=document_title) }}\n\n{{ link }}\n"),
    "src/catalyst/templates/email/signing_link.html": "<p><a href=\"{{ link }}\">Synthetic open</a></p>\n",
    "src/catalyst/signing/handlers.py": (
        'def deliver_link(packet):\n    subject = f"Synthetic sign: {packet.envelope_title}"\n'
        '    subject = f"Synthetic approver: {packet.envelope_title}"\n'),
}
SETTINGS = SimpleNamespace(CATALYST_REMINDER_MAX=1)
WORDS = ("Synthetic heading", "Synthetic confirm", "Synthetic receipt subject", "Synthetic question subject",
         "Synthetic Signer")


@pytest.fixture
def source(tmp_path) -> Path:
    for relative, text in SYNTHETIC.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def mapping(key):
    return next(m for m in fg.MAPPINGS if m.key == key)


def load(*args) -> tuple[list, dict, str]:
    out = StringIO()
    call_command("catalyst_load_firstgen_wording", *args, stdout=out)
    lines = [json.loads(line) for line in out.getvalue().splitlines() if line.startswith("{")]
    return [line for line in lines if not line.get("summary")], next(line for line in lines if line.get("summary")), out.getvalue()


# --- conversion (no database) -----------------------------------------------------------------------------------

def test_bgl11_conversion_maps_variables_drops_unmapped_lines_and_resolves_includes(source):
    converted = fg.convert(source, mapping("verification_invitation"), {}, SETTINGS)
    assert converted.subject == "Synthetic receipt subject"
    assert converted.subject_differences == ["subject_variable_dropped:reference"]
    text = converted.body_text
    assert "Synthetic confirm: $link\n" in text and "Hello $first_name,\n" in text  # greets by first name (parity)
    assert "Synthetic reference line" not in text and "Synthetic Sender\n" in text  # unmapped lines dropped
    assert "Synthetic price $$5" in text  # a literal dollar is escaped, so only $link is a placeholder
    assert "Synthetic badge" in text and "{{" not in text and "{%" not in text  # the include resolved at load time
    page = converted.body_html
    assert '<a href="$link">Synthetic confirm</a>' in page and 'lang="en"' in page
    assert "Synthetic it&#39;s" in page  # autoescaped as the first generation's HTML was
    assert "https://badge.example.test/b" in page and "Synthetic reference line" not in page
    assert converted.used == {"first_name", "link"}
    assert converted.unmapped == {"intake.reference", "service_address"}
    assert (converted.dropped_text_lines, converted.dropped_html_lines) == (2, 1)
    with_address = fg.convert(source, mapping("verification_invitation"), {"service_address": "desk@example.test"}, SETTINGS)
    assert "Synthetic Sender\ndesk@example.test\n" in with_address.body_text


def test_bgl11_token_assets_map_to_v2_variables_and_the_pilot_card_is_removed(source):
    cover = fg.convert(source, mapping("agreement_link_user_agreement"), {}, SETTINGS)
    assert cover.subject == "Synthetic cover subject" and cover.unmapped == {"UNKNOWN_TOKEN"}
    assert cover.body_text == "Hi $first_name,\nSynthetic cover $link\n"
    assert "pilot" not in cover.body_html and '<a href="$link">' in cover.body_html
    welcome = fg.convert(source, mapping("provisioning_welcome_password"), {}, SETTINGS)
    assert "User $mailbox_username@mail.example.test\nPass $password\n" in welcome.body_text
    assert welcome.used == {"first_name", "mailbox_username", "password"}


def test_bgl11_subjects_fill_an_allowed_constant_and_branches_follow_the_flags(source):
    nda = fg.convert(source, mapping("agreement_link_nda"), {}, SETTINGS)
    assert nda.subject == "Synthetic sign" and nda.subject_differences == ["subject_variable_dropped:packet.envelope_title"]
    assert nda.body_text == "$link\n" and nda.unmapped == {"document_title"}  # the title line had no value: dropped
    titled = fg.convert(source, mapping("agreement_link_nda"), {"document_title": "Synthetic NDA"}, SETTINGS)
    assert titled.subject == "Synthetic sign: Synthetic NDA" and titled.body_text.startswith("Synthetic sign: Synthetic NDA\n")
    reminder = fg.convert(source, mapping("question_reminder"), {}, SETTINGS)
    assert "- $question_text\n" in reminder.body_text and "Synthetic last." in reminder.body_text
    assert "Synthetic intro" not in reminder.body_text and reminder.unmapped == {"sent_on"}
    assert "Synthetic last." not in fg.convert(source, mapping("question_reminder"), {},
                                               SimpleNamespace(CATALYST_REMINDER_MAX=2)).body_text
    assert "Synthetic reply branch." in fg.convert(source, mapping("lapse_note"), {}, SETTINGS).body_text


def test_bgl11_unsupported_template_constructs_are_refused(source):
    path = source / "src/catalyst/templates/email/review_clarification.txt"
    for construct in ("{{ body_text|upper }}", "{% set x = 1 %}", "{{ a and b }}", "{% include '../../x' %}"):
        path.write_text(construct)
        with pytest.raises(fg.Refused):
            fg.convert(source, mapping("question_request"), {}, SETTINGS)


# --- the HTML part (rendering) -----------------------------------------------------------------------------------

def _version(body_html, variables=("display_name", "question_text"), secret=False, status="approved", body_text=None):
    template = MessageTemplate(key="synthetic", secret_bearing=secret)
    body_text = body_text or "Hello $display_name: $question_text\n"
    return MessageTemplateVersion(template=template, subject="Synthetic", body_text=body_text, body_html=body_html,
                                  variables=list(variables), secret_bearing=secret, status=status,
                                  content_sha256=version_digest("Synthetic", body_text, body_html))


def test_bgl11_html_values_are_escaped_and_text_values_are_plain():
    version = _version("<p>Hello $display_name</p><p>$question_text</p>\n")
    values = {"display_name": "Ada", "question_text": "<script>alert(1)</script> & more"}
    assert render(version, values)[1] == "Hello Ada: <script>alert(1)</script> & more\n"
    assert render_html(version, values) == "<p>Hello Ada</p><p>&lt;script&gt;alert(1)&lt;/script&gt; &amp; more</p>\n"
    assert render_html(_version(""), values) == ""  # a text-only version has no HTML part


def test_bgl11_links_only_in_an_authored_href_and_nothing_inside_tags_scripts_or_styles():
    assert html_placement_problem('<a href="$link">go</a>') == ""
    assert html_placement_problem("<p>$link</p>") == "html_link_outside_href"
    assert html_placement_problem('<a href="https://x.test/?u=$link">') == "html_link_outside_href"
    assert html_placement_problem('<a title="$display_name">x</a>') == "html_placeholder_inside_tag"
    assert html_placement_problem("<style>p { content: '$display_name' }</style>") == "html_placeholder_in_comment_or_style"
    assert html_placement_problem("<p>x</p><SCRIPT>1</SCRIPT>") == "html_script_refused"
    linked = _version('<a href="$link">go</a>\n', variables=("link",), secret=True, body_text="Open $link\n")
    assert render_html(linked, {"link": "https://catalyst.example.test/confirm/a/"}) == (
        '<a href="https://catalyst.example.test/confirm/a/">go</a>\n')
    with pytest.raises(TemplateRefused, match="link_value_refused"):
        render_html(linked, {"link": "javascript:alert(1)"})
    with pytest.raises(TemplateRefused, match="html_placeholder_inside_tag"):
        check_version(_version('<p title="$display_name">x</p>\n'))


def test_bgl11_the_content_digest_covers_the_html_and_is_unchanged_without_it():
    assert version_digest("S", "B\n") == canonical_digest("S", "B\n")
    assert version_digest("S", "B\n", "<p>B</p>\n") != version_digest("S", "B\n", "<p>C</p>\n") != canonical_digest("S", "B\n")
    version = _version("<p>$display_name</p>\n")
    version.body_html = "<p>changed $display_name</p>\n"
    with pytest.raises(TemplateRefused, match="content_digest_mismatch"):
        check_version(version)


# --- the command and the database ------------------------------------------------------------------------------

def test_bgl11_dry_run_writes_nothing_prints_no_wording_and_skips_missing_keys(privileged_reset, source):
    ensure_verification_template()
    before = MessageTemplateVersion.objects.count()
    reports, summary, printed = load("--source", str(source), "--dry-run")
    assert MessageTemplateVersion.objects.count() == before and summary["dry_run"]
    by_key = {r["key"]: r for r in reports}
    assert by_key["verification_invitation"]["action"] == "create"
    assert by_key["verification_invitation"]["unmapped"] == ["intake.reference", "service_address"]
    assert by_key["agreement_link_nda"] == {**by_key["agreement_link_nda"], "action": "skip", "reason": "template_missing"}
    assert not any(word in printed for word in WORDS)  # lengths and names only, never the wording
    _, _, shown = load("--source", str(source), "--dry-run", "--only", "verification_invitation", "--show")
    assert "Synthetic heading" in shown and MessageTemplateVersion.objects.count() == before


def test_bgl11_loads_new_drafts_with_both_parts_and_a_rerun_skips_identical_content(privileged_reset, source):
    ensure_verification_template()
    reports, summary, _ = load("--source", str(source), "--only", "verification_invitation")
    [report] = reports
    version = MessageTemplateVersion.objects.get(template__key="verification_invitation", version=report["version"])
    assert (report["action"], version.version, version.status, version.synthetic) == ("create", 2, "draft", False)
    assert version.secret_bearing and version.variables == ["first_name", "link"] and '<a href="$link">' in version.body_html
    assert version.content_sha256 == version_digest(version.subject, version.body_text, version.body_html) == report["sha256"]
    assert summary["create"] == 1 and summary["approved_by"] == ""
    again, _, _ = load("--source", str(source), "--only", "verification_invitation")
    assert (again[0]["action"], again[0]["reason"]) == ("skip", "identical_draft")
    assert MessageTemplateVersion.objects.filter(template__key="verification_invitation").count() == 2


def test_bgl11_approve_as_uses_the_staff_approval_service_and_the_new_version_becomes_current(privileged_reset, source):
    ensure_verification_template()
    owner = template_owner(privileged_reset, "firstgen-owner")
    seeded = MessageTemplateVersion.objects.get(template__key="verification_invitation", version=1)
    outbound.approve_template_version(seeded.pk, owner)  # an earlier approved version, as on a live host
    reports, summary, _ = load("--source", str(source), "--only", "verification_invitation",
                               "--approve-as", "firstgen-owner", "--approval-ref", "d-60.wording")
    version = MessageTemplateVersion.objects.get(template__key="verification_invitation", version=reports[0]["version"])
    assert (version.status, version.approved_by) == ("approved", f"user:{owner.pk}") and version.approved_at
    assert (summary["approval_ref"], summary["approved_by"], summary["approve"]) == ("d-60.wording", f"user:{owner.pk}", 1)
    seeded.refresh_from_db()
    assert seeded.status == "approved"  # as on the staff screen: the newer approved version supersedes, nothing retires
    assert outbound.current_template_version("verification_invitation").pk == version.pk
    reader = staff_like_reader(privileged_reset)
    with pytest.raises(CommandError, match="approve_template_version"):
        load("--source", str(source), "--approve-as", reader.username, "--approval-ref", "d-60.wording")
    with pytest.raises(CommandError, match="decision code"):
        load("--source", str(source), "--approve-as", "firstgen-owner", "--approval-ref", "Free text")


def staff_like_reader(privileged_reset):
    from tests.test_staff import make_user

    return make_user(privileged_reset, "firstgen-reader")


def test_bgl11_a_variable_outside_the_allow_list_is_refused_and_nothing_is_written(privileged_reset, source, monkeypatch):
    ensure_verification_template()
    widened = dataclasses.replace(mapping("verification_invitation"),
                                  bind={"confirm_url": "link", "greeting_name": "display_name"})
    monkeypatch.setattr(fg, "MAPPINGS", (widened, mapping("question_request")))
    MessageTemplateVersion.objects.filter(template__key="question_request").exists() or question_template()
    before = MessageTemplateVersion.objects.count()
    out = StringIO()
    with pytest.raises(CommandError, match="refused, nothing written: verification_invitation"):
        call_command("catalyst_load_firstgen_wording", "--source", str(source), stdout=out)
    report = json.loads(out.getvalue().splitlines()[0])
    assert (report["reason"], report["outside"]) == ("variable_outside_allow_list", ["display_name"])
    assert MessageTemplateVersion.objects.count() == before  # the valid question_request was not written either


def test_bgl11_a_source_inside_the_repository_is_refused(privileged_reset):
    with pytest.raises(CommandError, match="inside this repository"):
        load("--source", str(Path(__file__).resolve().parent), "--dry-run")


def html_version(number: int, page: str, body: str = "Hello $display_name: $question_text\n",
                 variables=("display_name", "question_text")):
    """A question_request version with an HTML part, inserted as a draft (the HTML is written once, at insert)."""
    template, _ = MessageTemplate.objects.get_or_create(key="question_request", defaults={
        "purpose": "Ask an applicant an approved question", "secret_bearing": False})
    return MessageTemplateVersion.objects.create(
        template=template, version=number, subject="Synthetic question", body_text=body, body_html=page,
        variables=list(variables), content_sha256=version_digest("Synthetic question", body, page))


def test_bgl11_an_approved_html_part_is_final_for_every_role(privileged_reset):
    owner = template_owner(privileged_reset, "html-owner")
    version = html_version(1, "<p>$question_text</p>\n")
    outbound.approve_template_version(version.pk, owner)
    for role, error in (("app", errors.InsufficientPrivilege), ("owner", errors.InsufficientPrivilege)):
        connection = privileged_reset.connect(role)
        with pytest.raises(error):
            connection.execute("UPDATE correspondence_messagetemplateversion SET body_html = 'x' WHERE id = %s", [version.pk])
        connection.rollback()


def test_bgl11_a_version_with_html_is_sent_multipart_and_one_without_as_text_only(ready):
    _, plain = ask(ready, "Which synthetic project shows your work?")
    run_worker()
    first = ready.server.parsed()
    assert first.get_content_type() == "text/plain" and not first.is_multipart()
    newer = html_version(2, "<p>Hello $display_name</p><p>$question_text</p>\n")
    outbound.approve_template_version(newer.pk, ready.owner)
    _, message = ask(ready, "Does <b>bold</b> & more appear?")
    assert set(message.reproducible_inputs["html_values"]) == {"display_name", "question_text"}
    run_worker()
    sent = ready.server.parsed()
    assert sent.get_content_type() == "multipart/alternative"
    text, html = (part.get_content().replace("\r\n", "\n") for part in sent.iter_parts())
    assert [p.get_content_type() for p in sent.iter_parts()] == ["text/plain", "text/html"]
    assert "Does <b>bold</b> & more appear?" in text and text == message.frozen_body
    assert "<p>Does &lt;b&gt;bold&lt;/b&gt; &amp; more appear?</p>" in html
    assert message.content_sha256 == canonical_digest(message.frozen_subject, message.frozen_body)  # A5 unchanged



# --- the first-name greeting (parity integration) ---------------------------------------------------------------

def test_bgl11_the_greeting_takes_the_first_word_of_the_name_and_falls_back_to_the_display_name():
    from correspondence.rendering import first_name, fit_greeting

    assert first_name("  Ada   Example Lovelace ") == "Ada" and first_name("Grace") == "Grace"
    assert first_name("") == "" and first_name("   ") == "   "  # no first word: the display name as it stands
    version = _version("<p>Hello $first_name</p><p>$question_text</p>\n", variables=("first_name", "question_text"),
                       body_text="Hello $first_name: $question_text\n")
    values = {"display_name": "Ada Example Lovelace", "question_text": "Which project?"}  # what every sender offers
    assert fit_greeting(version.variables, values) == {"first_name": "Ada", "question_text": "Which project?"}
    assert render(version, values)[1] == "Hello Ada: Which project?\n"
    assert render_html(version, values) == "<p>Hello Ada</p><p>Which project?</p>\n"
    blank = {"display_name": "   ", "question_text": "Which project?"}
    assert render(version, blank)[1] == "Hello    : Which project?\n"  # never a KeyError: the fallback stands in
    both = _version("", variables=("display_name", "first_name"), body_text="$first_name ($display_name)\n")
    assert render(both, {"display_name": "Ada Lovelace"})[1] == "Ada (Ada Lovelace)\n"
    assert render(_version(""), {"display_name": "Ada Lovelace", "question_text": "q"})[1] == "Hello Ada Lovelace: q\n"
    with pytest.raises(TemplateRefused, match="values_do_not_match_allow_list"):  # every other value stays exact
        render(version, {"display_name": "Ada", "question_text": "q", "extra": "x"})


def test_bgl11_a_question_frozen_from_a_first_name_version_greets_by_the_first_word(ready):
    newer = html_version(2, "<p>Hello $first_name</p><p>$question_text</p>\n", body="Hello $first_name: $question_text\n",
                         variables=["first_name", "question_text"])
    outbound.approve_template_version(newer.pk, ready.owner)
    _, message = ask(ready, "Which synthetic project shows your work?")
    first = ready.app.display_name.split()[0]
    assert message.frozen_body == f"Hello {first}: Which synthetic project shows your work?\n"
    assert message.reproducible_inputs["html_values"] == {"first_name": first,
                                                          "question_text": "Which synthetic project shows your work?"}
    run_worker()
    sent = ready.server.parsed()
    assert [p.get_content_type() for p in sent.iter_parts()] == ["text/plain", "text/html"]
    assert f"<p>Hello {first}</p>" in [p.get_content() for p in sent.iter_parts()][1]
