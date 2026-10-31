"""First-generation wording as v2 template versions (bead bgl.11; parity inventory 034): the conversion half of
`manage.py catalyst_load_firstgen_wording`. Pure functions over files: no database, no network.

The first generation's wording is never part of this repository (it is public). The operator points the command at a
private checkout of the first generation at its live commit; this module reads the files named in `MAPPINGS` from
there at run time, converts them and hands back subject, text and HTML for the command to store as new versions.
`MAPPINGS` names only file paths, function or constant names, variable names and v2 keys: no wording.

Two first-generation formats are read:

- `jinja`: the Flask email templates (`templates/email/*.txt` and `*.html`). A small, closed subset of Jinja is
  interpreted, the subset those templates use: comments, `{{ expression }}`, `if`/`elif`/`else`, `for x in y`,
  `include` (resolved at load time, so a stored version is self-contained), attribute access, `not`, string literals,
  and the calls `_()` (the first generation's identity gettext: `text % params`) and the names in `calls`. Anything
  else is refused. As in the first generation, the HTML part is autoescaped (markupsafe's escaping) and the text part
  is not; whitespace control (`-`) and the dropped final newline behave as Jinja's do.
- `tokens`: the asset files (the welcome and the User Agreement cover) with `{{UPPER_NAME}}` placeholders.

How each first-generation variable becomes v2 text, per mapping:

- `bind`: a v2 variable: becomes `$name` (the version's allow-list must hold it);
- `lists`: iterated by a `for`, as one item that is the v2 variable;
- `flags`: a fixed value that decides a branch (a callable is evaluated with Django settings when the command runs);
- `sourced`: a constant read from the first-generation source (a literal, or a call with literal keyword arguments,
  such as the partner badge), inserted as static text;
- `constants`: deployment values the operator may give with `--constant name=value` (the service address, the help
  address, a document title); not given, they are unmapped;
- anything else is unmapped: it has no v2 equivalent and no data is invented for it. It is false in a condition (the
  first generation's own fallback branch), and a line that would print it is dropped (an HTML line only when its tags
  are balanced, otherwise the template is refused). Every unmapped name and every dropped line is reported.

Literal `$` becomes `$$`, so only the converted variables are placeholders. Subjects are static in v2 (016 A1): a
first-generation subject is read from its sender (a function's return, an assignment in a function, a module
constant or a JSON field), and a variable in it is filled from `--constant` when the mapping allows it or dropped with
its brackets and reported as a known difference.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

MAX_FILE_BYTES = 512 * 1024
_V2_OPEN, _V2_CLOSE, _UN_OPEN, _UN_CLOSE = "", "", "", ""
_MARKERS = (_V2_OPEN, _V2_CLOSE, _UN_OPEN, _UN_CLOSE)
_TOKEN = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
_IDENTIFIER_CHAR = re.compile(r"[A-Za-z0-9_]")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Refused(Exception):
    """A reason code; never carries wording."""


# ---- the mapping table (paths and names only) -----------------------------------------------------------------------

@dataclass(frozen=True)
class Part:
    path: str
    fmt: str  # "jinja" or "tokens"
    strip_between: tuple = ()  # (start, end) markers whose span is removed first (the cover's pilot card)


@dataclass(frozen=True)
class SubjectSource:
    kind: str  # "return", "assign", "constant" or "json"
    path: str
    name: str  # the function, constant or JSON field
    index: int = 0  # for "assign": which subject assignment in the function, in source order


@dataclass(frozen=True)
class Mapping:
    key: str
    moment: str  # the sending moment, for the report
    text: Part
    html: Part | None
    subject: SubjectSource
    variables: tuple  # the version's allow-list: exactly what the v2 sender supplies
    required: tuple = ()  # v2 variables the converted text must use (a link mail without its link is refused)
    bind: dict = field(default_factory=dict)
    lists: dict = field(default_factory=dict)
    flags: dict = field(default_factory=dict)
    sourced: dict = field(default_factory=dict)
    constants: tuple = ()
    calls: dict = field(default_factory=dict)
    subject_exprs: dict = field(default_factory=dict)  # subject expression -> constant name
    notes: tuple = ()  # known differences, as codes


SRC = "src/catalyst"
EMAIL = f"{SRC}/templates/email"
TEMPLATE_ROOT = f"{SRC}/templates"
BADGE = {"partner_badge": (f"{SRC}/branding.py", "PARTNER_BADGE")}
LOCALE = {"current_locale": "en"}  # the first generation's `current_locale` global is a constant (English only)
SIGNATURE = ("service_address",)


def _single_reminder(settings) -> bool:
    return int(getattr(settings, "CATALYST_REMINDER_MAX", 1)) <= 1


MAPPINGS: tuple[Mapping, ...] = (
    Mapping(
        key="verification_invitation", moment="after the request form is sent: the mail that carries the link",
        text=Part(f"{EMAIL}/intake_receipt.txt", "jinja"), html=Part(f"{EMAIL}/intake_receipt.html", "jinja"),
        subject=SubjectSource("return", f"{SRC}/intake/receipt.py", "receipt_subject"),
        variables=("link",), required=("link",), bind={"confirm_url": "link"}, flags={"ask_to_confirm": True},
        sourced=BADGE, constants=SIGNATURE, calls=LOCALE,
        notes=("no_name_variable_in_v2_greets_without_a_name", "first_generation_offers_confirmation_by_reply",
               "first_generation_states_its_own_link_lifetime", "subject_reference_dropped")),
    Mapping(
        key="question_request", moment="staff approve a clarifying question",
        text=Part(f"{EMAIL}/review_clarification.txt", "jinja"), html=Part(f"{EMAIL}/review_clarification.html", "jinja"),
        subject=SubjectSource("assign", f"{SRC}/review/correspondence.py", "build_message"),
        variables=("display_name", "question_text"), required=("question_text",),
        bind={"greeting_name": "display_name", "body_text": "question_text"}, lists={"paragraphs": "question_text"},
        sourced=BADGE, constants=SIGNATURE, calls=LOCALE,
        notes=("greets_with_the_display_name_not_the_first_word", "subject_reference_dropped")),
    Mapping(
        key="question_reminder", moment="an approved question stays unanswered",
        text=Part(f"{EMAIL}/review_clarification_reminder.txt", "jinja"),
        html=Part(f"{EMAIL}/review_clarification_reminder.html", "jinja"),
        subject=SubjectSource("assign", f"{SRC}/review/reminder.py", "build_message"),
        variables=("display_name", "question_text"), required=("question_text",),
        bind={"greeting_name": "display_name"}, lists={"asked": "question_text"}, flags={"final": _single_reminder},
        sourced=BADGE, constants=SIGNATURE, calls=LOCALE,
        notes=("greets_with_the_display_name_not_the_first_word", "lists_the_question_text_not_plain_words",
               "final_sentence_kept_only_while_one_reminder_is_configured", "subject_reference_dropped")),
    Mapping(
        key="lapse_note", moment="an application lapses after the last follow-up",
        text=Part(f"{EMAIL}/case_lapse_note.txt", "jinja"), html=Part(f"{EMAIL}/case_lapse_note.html", "jinja"),
        subject=SubjectSource("assign", f"{SRC}/lapse.py", "build_message"),
        variables=("display_name",), bind={"greeting_name": "display_name"}, flags={"questions": True},
        sourced=BADGE, constants=SIGNATURE, calls=LOCALE,
        notes=("greets_with_the_display_name_not_the_first_word",
               "one_v2_template_for_both_lapses_the_question_variant_is_used", "subject_reference_dropped")),
    Mapping(
        key="agreement_link_nda", moment="the NDA signing link, sent by the service",
        text=Part(f"{EMAIL}/signing_link.txt", "jinja"), html=Part(f"{EMAIL}/signing_link.html", "jinja"),
        subject=SubjectSource("assign", f"{SRC}/signing/handlers.py", "deliver_link"),
        variables=("display_name", "link"), required=("link",), bind={"link": "link"},
        sourced=BADGE, constants=("document_title", "help_email"), calls=LOCALE,
        subject_exprs={"packet.envelope_title": "document_title"},
        notes=("document_title_is_a_constant_per_v2_key",)),
    Mapping(
        key="agreement_link_user_agreement", moment="the User Agreement signing link in the branded cover",
        text=Part(f"{SRC}/signing/assets/ua_cover.txt", "tokens"),
        html=Part(f"{SRC}/signing/assets/ua_cover.html", "tokens", strip_between=("<!--PILOT-->", "<!--/PILOT-->")),
        subject=SubjectSource("constant", f"{SRC}/signing/cover.py", "SUBJECT"),
        variables=("display_name", "link"), required=("link",), bind={"FIRST_NAME": "display_name", "SIGN_URL": "link"},
        notes=("greets_with_the_display_name_not_the_first_word", "pilot_card_removed_v2_has_no_pilot_cohort")),
    Mapping(
        key="provisioning_welcome_password", moment="the mailbox is ready (one-time password mode)",
        text=Part(f"{SRC}/mailbox/assets/welcome.txt", "tokens"), html=Part(f"{SRC}/mailbox/assets/welcome.html", "tokens"),
        subject=SubjectSource("json", f"{SRC}/mailbox/assets/welcome.manifest.json", "subject"),
        variables=("display_name", "mailbox_address", "mailbox_username", "password"), required=("password",),
        bind={"FIRST_NAME": "display_name", "USERNAME": "mailbox_username", "TEMP_PASSWORD": "password"},
        notes=("greets_with_the_display_name_not_the_first_word",)),
)

# v2 templates with no first-generation email at the same moment (reported, never converted).
V2_ONLY = {
    "data_notice": "v2 invitation-only intake: the data notice shown with the invitation and the form",
    "invitation": "v2 invitation-only intake: the first generation sent no invitation mail",
    "decline_notice": "v2 decline: the first generation declined without a templated mail",
    "provisioning_welcome": "v2 set-your-own-password welcome: the first generation always sent a one-time password",
}
# First-generation files with no v2 sending moment (reported, never converted).
NO_V2_MOMENT = {
    f"{EMAIL}/intake_receipt.txt (without confirmation)": "the receipt sent when verification was off: v2 always verifies",
    f"{EMAIL}/setup_link.txt": "the first-generation setup page link: v2 has no setup page (the User Agreement is signed)",
    f"{EMAIL}/setup_receipt.txt": "the setup page acceptance receipt: v2 has no setup page",
    f"{EMAIL}/approval_link.txt": "the countersigner's fallback link: not applicant-facing",
    f"{EMAIL}/owner_*.txt": "owner notices: not applicant-facing",
}


# ---- reading the source ---------------------------------------------------------------------------------------------

def read_source(root: Path, relative: str) -> str:
    path = (root / relative).resolve()
    if root not in path.parents:
        raise Refused("source_path_outside_root")
    if not path.is_file():
        raise Refused("source_file_missing")
    data = path.read_bytes()
    if len(data) > MAX_FILE_BYTES:
        raise Refused("source_file_too_large")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("source_file_not_utf8") from None
    if any(marker in text for marker in _MARKERS):
        raise Refused("source_holds_reserved_characters")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def sourced_constant(root: Path, relative: str, name: str):
    """A module constant: a literal, or a call with literal keyword arguments (as a namespace)."""
    for node in ast.parse(read_source(root, relative)).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            value = node.value
            if isinstance(value, ast.Call) and not value.args:
                try:
                    return SimpleNamespace(**{k.arg: ast.literal_eval(k.value) for k in value.keywords})
                except (ValueError, TypeError):
                    raise Refused("sourced_constant_unreadable") from None
            try:
                return ast.literal_eval(value)
            except ValueError:
                raise Refused("sourced_constant_unreadable") from None
    raise Refused("sourced_constant_missing")


# ---- subjects -------------------------------------------------------------------------------------------------------

def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise Refused("subject_function_missing")


def _is_subject_target(target) -> bool:
    if isinstance(target, ast.Name):
        return target.id == "subject"
    return (isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
            and target.slice.value == "Subject")


def _subject_node(root: Path, source: SubjectSource):
    if source.kind == "json":
        try:
            value = json.loads(read_source(root, source.path))[source.name]
        except (ValueError, KeyError, TypeError):
            raise Refused("subject_unreadable") from None
        if not isinstance(value, str):
            raise Refused("subject_unreadable")
        return ast.Constant(value)
    tree = ast.parse(read_source(root, source.path))
    if source.kind == "constant":
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == source.name for t in node.targets):
                return node.value
        raise Refused("subject_constant_missing")
    function = _function(tree, source.name)
    if source.kind == "return":
        found = [n.value for n in ast.walk(function) if isinstance(n, ast.Return) and n.value is not None]
    elif source.kind == "assign":
        found = [n.value for n in ast.walk(function)
                 if isinstance(n, ast.Assign) and any(_is_subject_target(t) for t in n.targets)]
        found.sort(key=lambda n: (n.lineno, n.col_offset))
    else:
        raise Refused("subject_kind_unknown")
    if len(found) <= source.index:
        raise Refused("subject_missing")
    return found[source.index]


def convert_subject(root: Path, mapping: Mapping, constants: dict) -> tuple[str, list[str]]:
    """(static subject, known differences). A variable is filled from a given constant the mapping allows, else
    dropped with the brackets around it."""
    node = _subject_node(root, mapping.subject)
    differences: list[str] = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        subject = node.value
    elif isinstance(node, ast.JoinedStr):
        pieces = []
        for part in node.values:
            if isinstance(part, ast.Constant):
                pieces.append(str(part.value))
                continue
            expression = ast.unparse(part.value)
            name = mapping.subject_exprs.get(expression)
            if name and constants.get(name):
                pieces.append(constants[name])
            else:
                pieces.append(_UN_OPEN + _UN_CLOSE)
                differences.append(f"subject_variable_dropped:{expression}")
        subject = "".join(pieces)
        subject = re.sub(r"\s*[\[(]\s*" + _UN_OPEN + _UN_CLOSE + r"\s*[\])]", "", subject)
        subject = subject.replace(_UN_OPEN + _UN_CLOSE, "")
        subject = re.sub(r"\s+", " ", subject).strip().rstrip(":-–—").strip()
    else:
        raise Refused("subject_unreadable")
    if not subject or "\n" in subject or len(subject) > 200 or any(m in subject for m in _MARKERS):
        raise Refused("subject_invalid")
    return subject, differences


# ---- the Jinja subset -----------------------------------------------------------------------------------------------

class Unmapped:
    """A first-generation value with no v2 equivalent: false, empty, and printed as a marker (its line is dropped)."""

    def __init__(self, name: str, seen: set):
        self.name, self.seen = name, seen
        seen.add(name)

    def __bool__(self):
        return False

    def __iter__(self):
        return iter(())

    def __str__(self):
        return f"{_UN_OPEN}{self.name}{_UN_CLOSE}"


class V2Variable:
    def __init__(self, name: str):
        self.name = name

    def __bool__(self):
        return True

    def __str__(self):
        return f"{_V2_OPEN}{self.name}{_V2_CLOSE}"


class V2List:
    def __init__(self, name: str):
        self.name = name

    def __bool__(self):
        return True

    def __iter__(self):
        return iter((V2Variable(self.name),))


def markup_escape(text: str) -> str:
    """markupsafe's escaping, which the first generation's autoescaped HTML used."""
    return (text.replace("&", "&amp;").replace(">", "&gt;").replace("<", "&lt;").replace("'", "&#39;")
            .replace('"', "&#34;"))


_TAG = re.compile(r"(\{\{-?|\{%-?|\{#-?)")
_CLOSE = {"{{": "}}", "{%": "%}", "{#": "#}"}


def _tokenize(source: str) -> list[tuple[str, str]]:
    """[(kind, content)] with kind "text", "out" or "stmt"; comments and whitespace control applied."""
    tokens: list[list] = []
    position, strip_next = 0, False
    while True:
        match = _TAG.search(source, position)
        text = source[position:match.start() if match else len(source)]
        if strip_next:
            text = text.lstrip()
        if match and match.group(1).endswith("-"):
            text = text.rstrip()
        tokens.append(["text", text])
        if not match:
            break
        opener = match.group(1)[:2]
        end = source.find(_CLOSE[opener], match.end())
        if end < 0:
            raise Refused("template_tag_unclosed")
        inner = source[match.end():end]
        strip_next = inner.endswith("-")
        if strip_next:
            inner = inner[:-1]
        position = end + 2
        if opener == "{#":
            continue
        tokens.append(["out" if opener == "{{" else "stmt", inner.strip()])
    return [(k, c) for k, c in tokens if not (k == "text" and c == "")]


_EXPR_TOKEN = re.compile(r"\s*(?:(?P<string>'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")|(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
                         r"|(?P<op>[.(),=]))")


def _expression_tokens(text: str) -> list[tuple[str, str]]:
    out, position = [], 0
    while position < len(text):
        if text[position:].strip() == "":
            break
        match = _EXPR_TOKEN.match(text, position)
        if not match:
            raise Refused("template_expression_unsupported")
        kind = match.lastgroup
        out.append((kind, match.group(kind)))
        position = match.end()
    return out


class _Expr:
    def __init__(self, tokens):
        self.tokens, self.i = tokens, 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def take(self, value=None):
        token = self.peek()
        if token[0] is None or (value is not None and token[1] != value):
            raise Refused("template_expression_unsupported")
        self.i += 1
        return token

    def parse(self):
        node = self.expression()
        if self.i != len(self.tokens):
            raise Refused("template_expression_unsupported")
        return node

    def expression(self):
        kind, value = self.peek()
        if kind == "name" and value == "not":
            self.take()
            return ("not", self.expression())
        if kind == "name" and value in ("and", "or", "in", "is"):
            raise Refused("template_expression_unsupported")
        return self.primary()

    def primary(self):
        kind, value = self.take()
        if kind == "string":
            return ("str", ast.literal_eval(value))
        if kind != "name":
            raise Refused("template_expression_unsupported")
        path = [value]
        while self.peek() == ("op", "."):
            self.take()
            path.append(self.take()[1])
        if self.peek() == ("op", "("):
            self.take()
            args, kwargs = [], {}
            while self.peek() != ("op", ")"):
                if self.peek()[0] == "name" and self.i + 1 < len(self.tokens) and self.tokens[self.i + 1] == ("op", "="):
                    keyword = self.take()[1]
                    self.take("=")
                    kwargs[keyword] = self.expression()
                else:
                    args.append(self.expression())
                if self.peek() == ("op", ","):
                    self.take()
                elif self.peek() != ("op", ")"):
                    raise Refused("template_expression_unsupported")
            self.take(")")
            return ("call", ".".join(path), args, kwargs)
        return ("name", path)


def _parse(tokens) -> list:
    """A tree of ("text", s), ("out", expr), ("if", [(cond, body)], else_body), ("for", var, expr, body),
    ("include", path)."""
    position = 0

    def block(stops: tuple) -> tuple[list, str]:
        nonlocal position
        body = []
        while position < len(tokens):
            kind, content = tokens[position]
            position += 1
            if kind == "text":
                body.append(("text", content))
            elif kind == "out":
                body.append(("out", _Expr(_expression_tokens(content)).parse()))
            else:
                word, _, rest = content.partition(" ")
                if word in stops:
                    return body, content
                if word == "if":
                    branches, otherwise = [], []
                    condition = _Expr(_expression_tokens(rest)).parse()
                    while True:
                        inner, ender = block(("elif", "else", "endif"))
                        branches.append((condition, inner))
                        head, _, tail = ender.partition(" ")
                        if head == "elif":
                            condition = _Expr(_expression_tokens(tail)).parse()
                            continue
                        if head == "else":
                            otherwise, ender = block(("endif",))
                        break
                    body.append(("if", branches, otherwise))
                elif word == "for":
                    match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(.+)", rest.strip())
                    if not match:
                        raise Refused("template_statement_unsupported")
                    inner, _ = block(("endfor",))
                    body.append(("for", match.group(1), _Expr(_expression_tokens(match.group(2))).parse(), inner))
                elif word == "include":
                    target = rest.strip()
                    if not re.fullmatch(r"\"[A-Za-z0-9_./-]+\"|'[A-Za-z0-9_./-]+'", target):
                        raise Refused("template_statement_unsupported")
                    body.append(("include", target[1:-1]))
                else:
                    raise Refused("template_statement_unsupported")
        if stops:
            raise Refused("template_block_unclosed")
        return body, ""

    tree, _ = block(())
    return tree


@dataclass
class _Context:
    mapping: Mapping
    root: Path
    html: bool
    flags: dict
    sourced: dict
    constants: dict
    unmapped: set
    used: set
    depth: int = 0


def _resolve(path: list[str], scope: dict, ctx: _Context):
    dotted = ".".join(path)
    if path[0] in scope:
        value = scope[path[0]]
        rest = path[1:]
    else:
        for prefix_length in range(len(path), 0, -1):
            prefix = ".".join(path[:prefix_length])
            mapping = ctx.mapping
            if prefix in mapping.bind:
                if prefix_length != len(path):
                    raise Refused("template_attribute_of_a_v2_variable")
                ctx.used.add(mapping.bind[prefix])
                return V2Variable(mapping.bind[prefix])
            if prefix in mapping.lists:
                ctx.used.add(mapping.lists[prefix])
                return V2List(mapping.lists[prefix])
            if prefix in ctx.flags:
                value, rest = ctx.flags[prefix], path[prefix_length:]
                break
            if prefix in ctx.sourced:
                value, rest = ctx.sourced[prefix], path[prefix_length:]
                break
            if prefix in mapping.constants:
                given = ctx.constants.get(prefix)
                if given is None:
                    return Unmapped(dotted, ctx.unmapped)
                value, rest = given, path[prefix_length:]
                break
        else:
            return Unmapped(dotted, ctx.unmapped)
    for attribute in rest:
        if isinstance(value, Unmapped):
            return Unmapped(dotted, ctx.unmapped)
        if not isinstance(value, SimpleNamespace) or not hasattr(value, attribute):
            raise Refused("template_attribute_unsupported")
        value = getattr(value, attribute)
    return value


def _evaluate(node, scope: dict, ctx: _Context):
    kind = node[0]
    if kind == "str":
        return node[1]
    if kind == "not":
        return not _evaluate(node[1], scope, ctx)
    if kind == "name":
        return _resolve(node[1], scope, ctx)
    if kind == "call":
        name, args, kwargs = node[1], node[2], node[3]
        if name == "_":
            if len(args) != 1:
                raise Refused("template_expression_unsupported")
            text = _evaluate(args[0], scope, ctx)
            if not isinstance(text, str):
                raise Refused("template_gettext_needs_a_literal")
            params = {k: _text(_evaluate(v, scope, ctx)) for k, v in kwargs.items()}
            try:
                return text % params if params else text
            except (KeyError, ValueError, TypeError):
                raise Refused("template_gettext_parameters") from None
        if name in ctx.mapping.calls and not args and not kwargs:
            return ctx.mapping.calls[name]
        raise Refused("template_call_unsupported")
    raise Refused("template_expression_unsupported")


def _text(value) -> str:
    if isinstance(value, (Unmapped, V2Variable)):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    raise Refused("template_value_unprintable")


def _render(tree, scope: dict, ctx: _Context) -> str:
    out = []
    for node in tree:
        kind = node[0]
        if kind == "text":
            out.append(node[1])
        elif kind == "out":
            value = _text(_evaluate(node[1], scope, ctx))
            out.append(markup_escape(value) if ctx.html else value)
        elif kind == "if":
            for condition, body in node[1]:
                if _evaluate(condition, scope, ctx):
                    out.append(_render(body, scope, ctx))
                    break
            else:
                out.append(_render(node[2], scope, ctx))
        elif kind == "for":
            iterable = _evaluate(node[2], scope, ctx)
            if not isinstance(iterable, (V2List, Unmapped, list, tuple)):
                raise Refused("template_loop_unsupported")
            for item in iterable:
                out.append(_render(node[3], {**scope, node[1]: item}, ctx))
        elif kind == "include":
            if ctx.depth >= 4:
                raise Refused("template_include_too_deep")
            ctx.depth += 1
            out.append(_render_jinja(read_source(ctx.root, f"{TEMPLATE_ROOT}/{node[1]}"), scope, ctx))
            ctx.depth -= 1
    return "".join(out)


def _render_jinja(source: str, scope: dict, ctx: _Context) -> str:
    if source.endswith("\n"):
        source = source[:-1]  # Jinja drops one final newline (keep_trailing_newline is off)
    return _render(_parse(_tokenize(source)), scope, ctx)


def _render_tokens(source: str, ctx: _Context) -> str:
    def replace(match):
        name = match.group(1)
        if name in ctx.mapping.bind:
            ctx.used.add(ctx.mapping.bind[name])
            return str(V2Variable(ctx.mapping.bind[name]))
        return str(Unmapped(name, ctx.unmapped))

    return _TOKEN.sub(replace, source)


# ---- assembling one part --------------------------------------------------------------------------------------------

def _balanced(line: str) -> bool:
    depth = 0
    for closing, name in re.findall(r"<(/?)([A-Za-z][A-Za-z0-9]*)[^>]*?>", line):
        if name.lower() in _VOID:
            continue
        depth += -1 if closing else 1
    return depth == 0 and line.count("<") == line.count(">")


def _drop_unmapped_lines(text: str, html: bool) -> tuple[str, int]:
    kept: list[str] = []
    dropped, after_drop = 0, False
    for line in text.split("\n"):
        if _UN_OPEN in line:
            if html and not _balanced(line):
                raise Refused("unmapped_value_inside_html_structure")
            dropped += 1
            after_drop = True
            continue
        if after_drop and line.strip() == "" and (not kept or kept[-1].strip() == ""):
            continue  # the drop would leave two blank lines where the first generation had one
        after_drop = False
        kept.append(line)
    return "\n".join(kept), dropped


def _placeholders(text: str) -> str:
    """Literal `$` doubled, then each v2 marker made a `$name` (braced when a name character follows)."""
    text = text.replace("$", "$$")

    def replace(match):
        name, following = match.group(1), text[match.end():match.end() + 1]
        return "${" + name + "}" if _IDENTIFIER_CHAR.match(following) else "$" + name

    out = re.sub(re.escape(_V2_OPEN) + r"([a-z_][a-z0-9_]*)" + re.escape(_V2_CLOSE), replace, text)
    if any(marker in out for marker in _MARKERS):
        raise Refused("unconverted_marker")
    return out


def convert_part(root: Path, mapping: Mapping, part: Part, *, html: bool, flags: dict, sourced: dict,
                 constants: dict, unmapped: set, used: set) -> tuple[str, int]:
    source = read_source(root, part.path)
    if part.strip_between:
        start, end = part.strip_between
        if source.count(start) != 1 or source.count(end) != 1 or source.index(end) < source.index(start):
            raise Refused("strip_markers_changed")
        source = source[:source.index(start)] + source[source.index(end) + len(end):]
    ctx = _Context(mapping, root, html, flags, sourced, constants, unmapped, used)
    if part.fmt == "jinja":
        rendered = _render_jinja(source, {}, ctx)
    elif part.fmt == "tokens":
        rendered = _render_tokens(source, ctx)
    else:
        raise Refused("source_format_unknown")
    rendered, dropped = _drop_unmapped_lines(rendered, html)
    body = _placeholders(rendered)
    if not body.endswith("\n"):
        body += "\n"  # the wire form ends every part with a line end (email set_content)
    return body, dropped


@dataclass
class Converted:
    key: str
    subject: str
    body_text: str
    body_html: str
    used: set
    unmapped: set
    dropped_text_lines: int
    dropped_html_lines: int
    subject_differences: list
    source_files: list


def convert(root: Path, mapping: Mapping, constants: dict, settings=None) -> Converted:
    root = root.resolve()
    flags = {name: (value(settings) if isinstance(value, Callable) else value) for name, value in mapping.flags.items()}
    sourced = {name: sourced_constant(root, path, constant) for name, (path, constant) in mapping.sourced.items()}
    unknown = set(constants) - set(mapping.constants) - set(mapping.subject_exprs.values())
    allowed_constants = {k: v for k, v in constants.items() if k not in unknown}
    unmapped: set = set()
    used: set = set()
    text, dropped_text = convert_part(root, mapping, mapping.text, html=False, flags=flags, sourced=sourced,
                                      constants=allowed_constants, unmapped=unmapped, used=used)
    page, dropped_html = "", 0
    if mapping.html is not None:
        page, dropped_html = convert_part(root, mapping, mapping.html, html=True, flags=flags, sourced=sourced,
                                          constants=allowed_constants, unmapped=unmapped, used=used)
    subject, differences = convert_subject(root, mapping, allowed_constants)
    files = [mapping.text.path] + ([mapping.html.path] if mapping.html else []) + [mapping.subject.path]
    return Converted(mapping.key, subject, text, page, used, unmapped, dropped_text, dropped_html, differences, files)
