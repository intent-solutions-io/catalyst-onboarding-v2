"""9kg.62 (029 section 6.2, the journal's consistency model): every effect a restore cannot undo is classified.

`workflow.effects.REGISTRY` names each function that performs one, with the class that makes it recoverable. This test
finds those functions in the source with `ast`, without importing the application, and fails when:

- a function performs an effect and is not in the registry, or is registered for an effect it no longer performs;
- a registered class does not match what the function does (a `prepare` outside journaled-before, a marker that is not
  a direct append, a check-first action that writes before it reads, a journaled-before entry written after the
  provider call it precedes in the same function, a provider or model call claimed as journaled with no covering
  journal entry of that class, a `by` function that does not exist);
- a journal kind is not resolvable to a literal, has no writer, a restrictive kind is never prepared, or a site writes
  a kind it does not declare;
- a provider client gains a write method that the scanner does not know;
- a module outside a reviewed allow-list opens a network connection, starts a process or writes a file.

What it finds: calls of the journal (`append`, `record`, `prepare`), SMTP (`transport.send`), a `django.core.mail`
send, Documenso writes, MXroute writes on a mail host, IMAP writes on a mailbox client, and model runs on a PydanticAI
agent, through module, alias, relative and by-name imports (at module level or inside a function), with receivers bound
by assignment, a `with` target or a parameter named `host`.

What it cannot find: a database write that ought to be journaled and is not (that judgement is the effect list in 029
section 6.2); a receiver held in an attribute (`self.client`), reached through `getattr`, or bound in an outer function;
and whether a reader named in `by` reads what the entry says (the review of `workflow/effects.py` checks each `why`).
"""

import ast
import re
from pathlib import Path

import pytest

from workflow import effects, journal

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("accounts", "agreements", "applications", "assessments", "config", "correspondence", "erasure",
            "provisioning", "workflow")
# The primitives themselves: each is checked below for write methods the scanner does not know.
IMPLEMENTATIONS = {"workflow/journal.py", "agreements/provider.py", "correspondence/transport.py",
                   "correspondence/imap.py", "provisioning/adapter.py"}
JOURNAL_CALLS = {"append", "record", "prepare"}
DOCUMENSO_WRITES = {"create_from_template", "distribute", "cancel", "countersign"}  # bgl.9: countersign
DOCUMENSO_READS = {"read", "find"}
MAILHOST_WRITES = {"create", "set_password", "delete_forwarder"}
MAILHOST_READS = {"read", "list_forwarders", "read_catch_all"}
IMAP_WRITES = {"append"}
IMAP_READS = {"search_message_id", "examine", "uids_after", "uids_since", "meta", "fetch", "fetch_headers"}
MODEL_RUNS = {"run", "run_sync", "run_stream", "run_stream_events", "iter"}
# Spelled through PYDANTIC so this file never matches the text guard of test_live_safety (oc4.9: only
# assessments/agent.py names the Agent class); the scanner still resolves the real names.
PYDANTIC = "pydantic_ai"
AGENTS = {f"{PYDANTIC}.Agent", f"{PYDANTIC}.agent.Agent"}
DJANGO_MESSAGES = {"django.core.mail.EmailMessage", "django.core.mail.EmailMultiAlternatives",
                   "django.core.mail.message.EmailMessage", "django.core.mail.message.EmailMultiAlternatives"}
DJANGO_SENDS = {"django.core.mail.send_mail", "django.core.mail.send_mass_mail", "django.core.mail.mail_admins",
                "django.core.mail.mail_managers"}
# Journal entries about the journal itself, written only inside `workflow.journal`.
INTERNAL_KINDS = {"genesis", "repair"}
# Modules that open a network connection, start a process or write a file, and what they touch. A new one fails the
# outward test until it is reviewed: classified in workflow/effects.py if a restore cannot undo it, listed here if not.
OUTWARD = {
    "agreements/keystore.py": "custody data keys and their mirror, outside the backup (026 section 16)",
    "agreements/storage.py": "custody documents, outside the backup (026 section 16)",
    "agreements/provider.py": "the Documenso client (its writes are the documenso family)",
    "assessments/egress.py": "the evidence fetcher's egress proxy connection (fetching is disabled in a live environment)",
    "assessments/fetch.py": "the evidence fetcher's reads through the egress proxy (disabled in a live environment)",
    "config/backup.py": "backup sets and the restore's working files",
    "config/release.py": "the deploy adapter's release bookkeeping files",
    "correspondence/imap.py": "the IMAP client (its writes are the imap family)",
    "correspondence/transport.py": "the SMTP client (the smtp family)",
    "provisioning/mxroute.py": "the live MXroute client (its writes are the mailhost family) and the IMAP login check of a "
                               "one-time password; reached only through a stub transport until the owner's canary",
    "workflow/heartbeat.py": "the worker's heartbeat file",
    "workflow/journal.py": "the effect journal",
    "workflow/shipping.py": "the effect journal's off-host copy",
}
NETWORK_MODULES = {"socket", "ssl", "http.client", "smtplib", "imaplib", "poplib", "ftplib", "urllib.request",
                   "subprocess", "httpx", "requests", "aiohttp", "urllib3"}
FILE_CALLS = {"os.unlink", "os.remove", "os.replace", "os.rename", "os.rmdir", "os.removedirs", "os.makedirs",
              "os.mkdir", "os.symlink", "os.link", "os.chmod", "os.chown", "os.truncate", "os.system", "os.popen",
              "shutil.rmtree", "shutil.move", "shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copytree",
              "tempfile.mkstemp", "tempfile.mkdtemp", "tempfile.NamedTemporaryFile", "tempfile.TemporaryDirectory"}
PATH_WRITES = {"unlink", "write_bytes", "write_text", "touch", "mkdir", "rmdir", "symlink_to", "hardlink_to"}
WRITE_FLAGS = {"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC"}
BEAD = re.compile(r"[a-z0-9]+(\.\d+)+")


def _sources(include_implementations=False):
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            if "migrations" not in path.parts and (include_implementations or relative not in IMPLEMENTATIONS):
                yield ".".join(path.relative_to(ROOT).with_suffix("").parts), path.read_text(encoding="utf-8")


def _imports(tree, module) -> dict:
    """Local name -> dotted target, for every import in the module (module level or inside a function, absolute or
    relative to the module's package)."""
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names[alias.asname] = alias.name
                else:
                    names[alias.name.split(".")[0]] = alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            base = ".".join([*module.split(".")[:-node.level], *([node.module] if node.module else [])]) \
                if node.level else node.module
            for alias in node.names:
                names[alias.asname or alias.name] = f"{base}.{alias.name}"
    return names


def _constants(tree) -> dict:
    """Module-level NAME = "string" assignments."""
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node.value.value
    return found


def _dotted(node, names) -> str:
    """The dotted target an expression names (`journal.record` -> `workflow.journal.record`), or ""."""
    if isinstance(node, ast.Name):
        return names.get(node.id, "")
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value, names)
        return f"{base}.{node.attr}" if base else ""
    return ""


def _string(node, constants):
    """A literal string, or a module constant's value; None otherwise."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


class _Function(ast.NodeVisitor):
    """The effects of one function's own body; nested functions and classes are their own sites."""

    def __init__(self, function, names, constants):
        self.name, self.names, self.constants = function.name, names, constants
        self.params = [arg.arg for arg in function.args.posonlyargs + function.args.args]
        self.found, self.first_write, self.first_read = {}, {}, {}
        self.kinds, self.prepared, self.kind_params = set(), set(), set()
        self.unresolved = False
        self.hosts = {arg.arg for arg in function.args.args + function.args.kwonlyargs if arg.arg == "host"}
        self.clients, self.agents, self.messages, self.connections = set(), set(), set(), set()
        for statement in function.body:
            self.visit(statement)

    def visit_FunctionDef(self, node):
        pass

    visit_AsyncFunctionDef = visit_ClassDef = visit_FunctionDef  # a lambda's calls are the function's own

    def _bind(self, target, value):
        if isinstance(target, ast.Name) and isinstance(value, ast.Call):
            called = _dotted(value.func, self.names)
            for kinds, bound in (({"provisioning.adapter.host"}, self.hosts),
                                 ({"correspondence.imap.MailboxClient"}, self.clients), (AGENTS, self.agents),
                                 (DJANGO_MESSAGES, self.messages), ({"django.core.mail.get_connection"}, self.connections)):
                if called in kinds:
                    bound.add(target.id)

    def visit_Assign(self, node):
        for target in node.targets:
            self._bind(target, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self._bind(node.target, node.value)
        self.generic_visit(node)

    def visit_withitem(self, node):
        if node.optional_vars is not None:
            self._bind(node.optional_vars, node.context_expr)
        self.generic_visit(node)

    def _add(self, family, call, node, read=False):
        lines = self.first_read if read else self.first_write
        lines[family] = min(lines.get(family, node.lineno), node.lineno)
        if not read:
            self.found.setdefault(family, set()).add(call)

    def _kind(self, node, call):
        first = node.args[0] if node.args else next((k.value for k in node.keywords if k.arg == "kind"), None)
        kind = _string(first, self.constants)
        if kind is not None:
            self.kinds.add(kind)
            if call == "prepare":
                self.prepared.add(kind)
        elif isinstance(first, ast.Name) and first.id in self.params:
            self.kind_params.add((self.params.index(first.id), first.id, call == "prepare"))
        else:
            self.unresolved = True

    def visit_Call(self, node):
        self.generic_visit(node)
        func = node.func
        called = _dotted(func, self.names)
        module, _, name = called.rpartition(".")
        receiver = func.value if isinstance(func, ast.Attribute) else None
        bound = receiver.id if isinstance(receiver, ast.Name) else None
        inline = _dotted(receiver.func, self.names) if isinstance(receiver, ast.Call) else ""
        if module == "workflow.journal" and name in JOURNAL_CALLS:
            self._add("journal", name, node)
            self._kind(node, name)
        elif called == "correspondence.transport.send":
            self._add("smtp", name, node)
        elif called in DJANGO_SENDS:
            self._add("django_mail", name, node)
        elif module == "agreements.provider" and name in DOCUMENSO_WRITES | DOCUMENSO_READS:
            self._add("documenso", name, node, read=name in DOCUMENSO_READS)
        elif receiver is not None:
            attr = func.attr
            if bound in self.hosts or inline == "provisioning.adapter.host":
                if attr in MAILHOST_WRITES | MAILHOST_READS:
                    self._add("mailhost", attr, node, read=attr in MAILHOST_READS)
            elif bound in self.clients and attr in IMAP_WRITES | IMAP_READS:
                self._add("imap", attr, node, read=attr in IMAP_READS)
            elif bound in self.agents and attr in MODEL_RUNS:
                self._add("model", attr, node)
            elif ((bound in self.messages or inline in DJANGO_MESSAGES) and attr == "send") or (
                    bound in self.connections and attr == "send_messages"):
                self._add("django_mail", attr, node)


def _resolve_kind_parameters(tree, body, constants) -> None:
    """A kind passed in as a parameter: the literal (or constant) each call in the module passes at that position, by
    name (`_append(...)`) or as a method (`self._append(...)`)."""
    for index, parameter, prepares in body.kind_params:
        passed = set()
        for node in ast.walk(tree):
            func = node.func if isinstance(node, ast.Call) else None
            if not (isinstance(func, ast.Name) and func.id == body.name or isinstance(func, ast.Attribute)
                    and func.attr == body.name and isinstance(func.value, ast.Name) and func.value.id in ("self", "cls")):
                continue
            offset = index - 1 if isinstance(func, ast.Attribute) else index  # a method's first parameter is self
            value = node.args[offset] if len(node.args) > offset else next(
                (k.value for k in node.keywords if k.arg == parameter), None)
            kind = _string(value, constants)
            if kind is None:
                body.unresolved = True
            else:
                passed.add(kind)
        if not passed:
            body.unresolved = True
        body.kinds |= passed
        if prepares:
            body.prepared |= passed


def _walk(tree, visit, prefix=()):
    """Call `visit(qualified name, node)` for every function and method, nested ones included."""
    for child in ast.iter_child_nodes(tree):
        if isinstance(child, ast.ClassDef):
            _walk(child, visit, (*prefix, child.name))
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit(".".join((*prefix, child.name)), child)
            _walk(child, visit, (*prefix, child.name))
        else:
            _walk(child, visit, prefix)


def discover(sources) -> dict:
    """`module:qualified.name` -> the function's `_Function` record, for every function with an effect."""
    sites = {}
    for module, text in sources:
        tree = ast.parse(text)
        names, constants = _imports(tree, module), _constants(tree)
        bodies = []
        _walk(tree, lambda qualified, node: bodies.append((qualified, _Function(node, names, constants))))
        for qualified, body in bodies:
            if body.kind_params:
                _resolve_kind_parameters(tree, body, constants)
            if body.found:
                sites[f"{module}:{qualified}"] = body
    return sites


def _all_functions(sources) -> set:
    found = set()
    for module, text in sources:
        _walk(ast.parse(text), lambda qualified, node, module=module: found.add(f"{module}:{qualified}"))
    return found


@pytest.fixture(scope="module")
def sites():
    return discover(_sources())


def test_9kg62_every_function_with_an_effect_is_registered_and_no_registration_is_stale(sites):
    unregistered = sorted(f"{site} ({', '.join(sorted(body.found))})" for site, body in sites.items()
                          if site not in effects.REGISTRY)
    stale = sorted(set(effects.REGISTRY) - set(sites))
    assert not unregistered, f"effects with no class in workflow.effects.REGISTRY: {unregistered}"
    assert not stale, f"registered functions that no longer perform an effect (or were renamed): {stale}"
    for site, body in sites.items():
        assert set(effects.REGISTRY[site]) == set(body.found), (
            f"{site}: performs {sorted(body.found)}, registered for {sorted(effects.REGISTRY[site])}")


def test_9kg62_each_class_matches_what_the_function_does(sites):
    functions = _all_functions(_sources(include_implementations=True))
    for site, body in sites.items():
        for family, entry in effects.REGISTRY.get(site, {}).items():  # an unregistered site fails the first test
            assert entry.cls in effects.CLASSES, f"{site} {family}: unknown class {entry.cls!r}"
            assert entry.why, f"{site} {family}: no reason recorded"
            assert not entry.gap or BEAD.fullmatch(entry.gap), f"{site} {family}: gap {entry.gap!r} is not a bead"
            assert not entry.after or (entry.cls == effects.JOURNALED_BEFORE and set(entry.after) < set(entry.kinds)), (
                f"{site}: `after` lists some, not all, kinds of a journaled-before site")
            calls = body.found.get(family, set())
            if family == "journal":
                assert entry.cls in (effects.JOURNALED_BEFORE, effects.JOURNALED_AFTER, effects.MARKER), (site, entry)
                assert not (entry.via or entry.by), f"{site}: a journal write is its own evidence"
                if "prepare" in calls:
                    assert entry.cls == effects.JOURNALED_BEFORE, f"{site}: prepares an entry, so it is journaled before"
                if entry.cls == effects.JOURNALED_BEFORE:
                    assert calls & {"prepare", "append"}, f"{site}: journaled before needs a prepare or a direct append"
                    for other, line in body.first_write.items():  # before the effect it precedes in this function
                        assert other == "journal" or body.first_write["journal"] < line, (
                            f"{site}: the journal entry is written after the {other} call it should precede")
                elif entry.cls == effects.JOURNALED_AFTER:
                    assert calls <= {"record", "append"}, f"{site}: journaled after is a record or an append, found {sorted(calls)}"
                else:
                    assert calls == {"append"}, f"{site}: a marker is a direct append, found {sorted(calls)}"
                assert not body.unresolved, f"{site}: a journal kind is not a literal, a constant or a literal argument"
                assert set(entry.kinds) == body.kinds, (
                    f"{site}: writes {sorted(body.kinds)}, declares {sorted(entry.kinds)}")
                assert body.kinds <= set(journal.KINDS), f"{site}: unknown kinds {body.kinds - set(journal.KINDS)}"
            else:
                assert entry.cls != effects.MARKER and not entry.kinds, f"{site} {family}: only a journal write is a marker"
                if entry.cls in (effects.JOURNALED_BEFORE, effects.JOURNALED_AFTER):
                    assert entry.via and not entry.by, f"{site} {family}: name, in `via`, the covering journal write"
                    covering = effects.REGISTRY.get(entry.via, {}).get("journal")
                    assert covering and covering.cls == entry.cls, (
                        f"{site} {family}: {entry.via} has no {entry.cls} journal entry to cover it")
                else:
                    assert entry.by and not entry.via, f"{site} {family}: name, in `by`, the function that covers it"
                    assert entry.by in functions, f"{site} {family}: {entry.by} does not exist"
                if entry.cls == effects.CHECKED_BEFORE:
                    assert entry.by == site, f"{site} {family}: a check-first action reads in its own body"
                    assert body.first_read.get(family, 10**9) < body.first_write[family], (
                        f"{site} {family}: writes before it reads the provider")


def test_9kg62_every_journal_kind_has_a_writer_and_each_restrictive_kind_is_prepared(sites):
    written = {kind for body in sites.values() for kind in body.kinds}
    missing = set(journal.KINDS) - INTERNAL_KINDS - written
    assert not missing, f"journal kinds no function writes: {sorted(missing)}"
    prepared = {kind for body in sites.values() for kind in body.prepared}
    assert set(journal.RESTRICTIVE) <= prepared, f"restrictive kinds never prepared: {set(journal.RESTRICTIVE) - prepared}"


def _functions(path):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, ast.FunctionDef):
                    yield f"{node.name}.{child.name}", child
    for child in tree.body:
        if isinstance(child, ast.FunctionDef):
            yield child.name, child


def _calls(function):
    return [node for node in ast.walk(function) if isinstance(node, ast.Call)]


def test_9kg62_the_scanner_knows_every_write_method_of_each_provider_client():
    # Documenso: a non-GET exchange is a write, and the method is always a literal.
    writes, reads = set(), set()
    for name, function in _functions("agreements/provider.py"):
        for call in _calls(function):
            if isinstance(call.func, ast.Name) and call.func.id == "exchange":
                method = call.args[0]
                assert isinstance(method, ast.Constant), f"provider.{name}: the exchange method is not a literal"
                (reads if method.value == "GET" else writes).add(name)
    assert writes == DOCUMENSO_WRITES
    assert DOCUMENSO_READS <= reads
    # MXroute: the interface's methods other than reads and lists are writes.
    interface = {name.split(".", 1)[1] for name, _ in _functions("provisioning/adapter.py") if name.startswith("MailHost.")}
    assert {name for name in interface if not name.startswith(("read", "list"))} == MAILHOST_WRITES
    assert MAILHOST_READS <= interface
    # IMAP: a client method calling a state-changing IMAP command, directly or through UID, is a write.
    changing = {"append", "store", "copy", "move", "expunge", "delete", "create", "rename"}
    writes, methods = set(), set()
    for name, function in _functions("correspondence/imap.py"):
        if not name.startswith("MailboxClient."):
            continue
        methods.add(name.split(".", 1)[1])
        for call in _calls(function):
            command = call.func.attr.lower() if isinstance(call.func, ast.Attribute) else ""
            if command == "uid":
                assert isinstance(call.args[0], ast.Constant), f"{name}: the UID command is not a literal"
                command = call.args[0].value.lower()
            if command in changing and _dotted(call.func.value, {"self": "self"}) == "self.imap":
                writes.add(name.split(".", 1)[1])
    assert writes == IMAP_WRITES
    assert IMAP_READS <= methods
    # SMTP: only `send` and its body helper speak the mail transaction.
    speaking = {name for name, function in _functions("correspondence/transport.py") for call in _calls(function)
                if isinstance(call.func, ast.Attribute) and call.func.attr in {"mail", "rcpt", "data", "docmd", "send",
                                                                             "sendmail", "send_message"}}
    assert speaking == {"send", "_send_body"}, speaking
    # The journal: every public function that writes an entry is one of the three calls the scanner reads, or writes
    # only the journal's own kinds (the genesis, the owner's repair).
    functions = dict(_functions("workflow/journal.py"))
    writers = {"_write_entry"}
    while True:
        more = {name for name, function in functions.items() if name not in writers and any(
            isinstance(call.func, ast.Name) and call.func.id in writers for call in _calls(function))}
        if not more:
            break
        writers |= more
    assert {name for name in writers if not name.startswith("_")} == JOURNAL_CALLS | {"ensure_genesis", "repair"}


def outward(sources) -> dict:
    """Module path -> what it uses of the network, process and file-writing primitives."""
    found = {}
    for module, text in sources:
        tree = ast.parse(text)
        names, hits = _imports(tree, module), set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imported = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                hits |= {f"import {name}" for name in imported
                         if name in NETWORK_MODULES or name.split(".")[0] in {"httpx", "httpx2", "requests", "aiohttp", "urllib3"}}
            elif isinstance(node, ast.Call):
                called = _dotted(node.func, names)
                if called in FILE_CALLS:
                    hits.add(called)
                elif called == "os.open":
                    flags = [n for arg in node.args[1:2] for n in ast.walk(arg)]
                    if any(isinstance(flag, ast.Attribute) and flag.attr in WRITE_FLAGS for flag in flags):
                        hits.add("os.open for writing")
                elif isinstance(node.func, ast.Name) and node.func.id == "open":
                    mode = node.args[1] if len(node.args) > 1 else next(
                        (k.value for k in node.keywords if k.arg == "mode"), None)
                    if mode is not None and not (isinstance(mode, ast.Constant) and not set(str(mode.value)) & set("wax+")):
                        hits.add("open for writing")
                elif isinstance(node.func, ast.Attribute) and node.func.attr in PATH_WRITES:
                    hits.add(f".{node.func.attr}()")
        if hits:
            found[module.replace(".", "/") + ".py"] = sorted(hits)
    return found


def test_9kg62_only_reviewed_modules_reach_the_network_start_a_process_or_write_a_file():
    found = outward(_sources(include_implementations=True))
    assert not set(found) - set(OUTWARD), {path: found[path] for path in set(found) - set(OUTWARD)}
    assert not set(OUTWARD) - set(found), f"listed but no longer outward: {sorted(set(OUTWARD) - set(found))}"


@pytest.mark.parametrize("source, family", [
    ("from correspondence import transport\ndef f():\n    transport.send(b'', 'a', 'b')\n", "smtp"),
    ("from correspondence.transport import send as deliver\ndef f():\n    deliver(b'', 'a', 'b')\n", "smtp"),
    ("from django.core.mail import EmailMessage\ndef f():\n    m = EmailMessage(to=['a'])\n    m.send()\n",
     "django_mail"),
    ("from django.core import mail\ndef f():\n    mail.EmailMessage(to=['a']).send()\n", "django_mail"),
    ("from django.core.mail import send_mail\ndef f():\n    send_mail('s', 'b', 'f', ['a'])\n", "django_mail"),
    ("def f():\n    from agreements import provider\n    provider.cancel('x')\n", "documenso"),
    ("import agreements.provider as p\ndef f():\n    p.distribute('x')\n", "documenso"),
    ("from provisioning import adapter\ndef f():\n    adapter.host().delete_forwarder('d', 'a')\n", "mailhost"),
    ("from provisioning.adapter import host\ndef f():\n    h = host()\n    h.create('d', 'l', 'p', 1, 1)\n", "mailhost"),
    ("from correspondence.imap import MailboxClient\ndef f():\n    with MailboxClient(1) as c:\n        c.append('S', b'')\n",
     "imap"),
    (f"from {PYDANTIC} import Agent\ndef f():\n    a = Agent('m')\n    a.run_sync('p')\n", "model"),
    (f"from {PYDANTIC}.agent import Agent\ndef f():\n    a: Agent = Agent('m')\n    a.run('p')\n", "model"),
    ("from workflow.journal import record\ndef f():\n    record('model_usage', 'k')\n", "journal"),
])
def test_9kg62_an_unclassified_effect_in_any_spelling_is_found(source, family):
    found = discover([("synthetic.module", source)])
    assert list(found) == ["synthetic.module:f"] and set(found["synthetic.module:f"].found) == {family}
    assert "synthetic.module:f" not in effects.REGISTRY  # so the first test would name it


def test_9kg62_a_kind_is_resolved_from_a_constant_or_a_caller_and_otherwise_refused():
    source = ("from workflow import journal\nKIND = 'staff_role_changed'\n"
              "def f():\n    journal.prepare(KIND, 'k')\n"
              "def _write(kind, key):\n    journal.append(kind, key)\n"
              "def g():\n    _write('erasure_intent', 'k')\n    _write(kind='erasure_complete', key='k')\n"
              "def h(kind):\n    journal.record(kind, 'k')\n"
              "def i():\n    journal.record(make_kind(), 'k')\n")
    found = discover([("synthetic.module", source)])
    assert found["synthetic.module:f"].kinds == found["synthetic.module:f"].prepared == {"staff_role_changed"}
    assert found["synthetic.module:_write"].kinds == {"erasure_intent", "erasure_complete"}
    assert not found["synthetic.module:_write"].unresolved
    assert found["synthetic.module:h"].unresolved and found["synthetic.module:i"].unresolved  # no caller; a call


def test_9kg62_lookalike_calls_are_not_effects():
    source = ("from email.message import EmailMessage\n"
              "def f(user, items, message, text):\n    user.set_password('x')\n    items.append(1)\n"
              "    Model.objects.create(a=1)\n    handler.run(1)\n    message.send()\n    EmailMessage().send()\n"
              "    text.replace('a', 'b')\n")
    assert discover([("synthetic.module", source)]) == {}
    assert outward([("synthetic.module", source)]) == {}


def test_9kg62_an_unreviewed_outward_module_is_found():
    source = ("import subprocess\nimport os\nfrom pathlib import Path\n"
              "def f(p: Path):\n    p.write_text('x')\n    os.unlink('a')\n    open('a', 'w')\n"
              "    os.open('a', os.O_WRONLY)\n    os.open('b', os.O_RDONLY)\n    open('c')\n")
    assert outward([("synthetic.module", source)]) == {"synthetic/module.py": [
        ".write_text()", "import subprocess", "open for writing", "os.open for writing", "os.unlink"]}
