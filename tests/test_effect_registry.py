"""9kg.62 (029 section 6.2, the journal's consistency model): every effect a restore cannot undo is classified.

`workflow.effects.REGISTRY` names each function that performs one, with the class that makes it recoverable. This test
finds those functions in the source with `ast`, without importing the application, and fails when:

- a function performs an effect and is not in the registry, or is registered for an effect it no longer performs;
- a registered class does not match what the function does (a `prepare` outside journaled-before, a marker that is not
  a direct append, a provider or model call claimed as journaled with no covering journal entry of that class);
- a journal kind has no writer, a restrictive kind is never prepared, or a site writes a kind it does not declare;
- a provider client gains a write method that the scanner does not know, so the list of primitives cannot go stale.

What it finds: calls of the journal (`append`, `record`, `prepare`), SMTP (`transport.send`), Documenso writes, MXroute
writes on a mail host, IMAP writes on a mailbox client, and model runs on a PydanticAI agent, through any import
spelling (module, alias, or the function imported by name, at module level or inside a function). What it cannot find:
a database write that ought to be journaled and is not. Whether a write is an effect is a judgement the registry
records; the effect list in 029 section 6.2 is where that judgement is reviewed.
"""

import ast
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
DOCUMENSO_WRITES = {"create_from_template", "distribute", "cancel"}
MAILHOST_WRITES = {"create", "set_password", "delete_forwarder"}
IMAP_WRITES = {"append"}
MODEL_RUNS = {"run", "run_sync", "run_stream", "run_stream_events", "iter"}
# Journal entries about the journal itself, written only inside `workflow.journal`.
INTERNAL_KINDS = {"genesis", "repair"}


def _sources():
    for package in PACKAGES:
        for path in sorted((ROOT / package).rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            if "migrations" not in path.parts and relative not in IMPLEMENTATIONS:
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


def _dotted(node, names) -> str:
    """The dotted target an expression names (`journal.record` -> `workflow.journal.record`), or ""."""
    if isinstance(node, ast.Name):
        return names.get(node.id, "")
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value, names)
        return f"{base}.{node.attr}" if base else ""
    return ""


class _Function(ast.NodeVisitor):
    """The effects of one function's own body; nested functions and classes are their own sites."""

    def __init__(self, function, names):
        self.names = names
        self.found = {}  # family -> set of call names; journal also maps "kinds" to the literal kinds
        self.kinds, self.unknown_kind = set(), False
        self.hosts = {arg.arg for arg in function.args.args + function.args.kwonlyargs if arg.arg == "host"}
        self.clients, self.agents = set(), set()
        for statement in function.body:
            self.visit(statement)

    def visit_FunctionDef(self, node):
        pass

    visit_AsyncFunctionDef = visit_ClassDef = visit_FunctionDef  # a lambda's calls are the function's own

    def _bind(self, target, value):
        if isinstance(target, ast.Name) and isinstance(value, ast.Call):
            called = _dotted(value.func, self.names)
            if called == "provisioning.adapter.host":
                self.hosts.add(target.id)
            elif called == "correspondence.imap.MailboxClient":
                self.clients.add(target.id)
            elif called == "pydantic_ai.Agent":
                self.agents.add(target.id)

    def visit_Assign(self, node):
        for target in node.targets:
            self._bind(target, node.value)
        self.generic_visit(node)

    def visit_withitem(self, node):
        if node.optional_vars is not None:
            self._bind(node.optional_vars, node.context_expr)
        self.generic_visit(node)

    def _add(self, family, call):
        self.found.setdefault(family, set()).add(call)

    def visit_Call(self, node):
        self.generic_visit(node)
        func = node.func
        called = _dotted(func, self.names)
        module, _, name = called.rpartition(".")
        if module == "workflow.journal" and name in JOURNAL_CALLS:
            self._add("journal", name)
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                self.kinds.add(first.value)
            else:
                self.unknown_kind = True
        elif called == "correspondence.transport.send":
            self._add("smtp", name)
        elif module == "agreements.provider" and name in DOCUMENSO_WRITES:
            self._add("documenso", name)
        elif isinstance(func, ast.Attribute):
            receiver = func.value
            bound = receiver.id if isinstance(receiver, ast.Name) else None
            via_host = isinstance(receiver, ast.Call) and _dotted(receiver.func, self.names) == "provisioning.adapter.host"
            if func.attr in MAILHOST_WRITES and (bound in self.hosts or via_host):
                self._add("mailhost", func.attr)
            elif func.attr in IMAP_WRITES and bound in self.clients:
                self._add("imap", func.attr)
            elif func.attr in MODEL_RUNS and bound in self.agents:
                self._add("model", func.attr)


def discover(sources) -> dict:
    """`module:qualified.name` -> (family -> call names, literal journal kinds, whether a kind was not a literal)."""
    sites = {}
    for module, text in sources:
        tree = ast.parse(text)
        names = _imports(tree, module)

        def walk(node, prefix):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    walk(child, (*prefix, child.name))
                elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = (*prefix, child.name)
                    body = _Function(child, names)
                    if body.found:
                        sites[f"{module}:{'.'.join(qualified)}"] = (body.found, body.kinds, body.unknown_kind)
                    walk(child, qualified)
                else:
                    walk(child, prefix)

        walk(tree, ())
    return sites


@pytest.fixture(scope="module")
def sites():
    return discover(_sources())


def test_9kg62_every_function_with_an_effect_is_registered_and_no_registration_is_stale(sites):
    unregistered = sorted(f"{site} ({', '.join(sorted(found))})" for site, (found, _, _) in sites.items()
                          if site not in effects.REGISTRY)
    stale = sorted(set(effects.REGISTRY) - set(sites))
    assert not unregistered, f"effects with no class in workflow.effects.REGISTRY: {unregistered}"
    assert not stale, f"registered functions that no longer perform an effect (or were renamed): {stale}"
    for site, (found, _, _) in sites.items():
        assert set(effects.REGISTRY[site]) == set(found), (
            f"{site}: performs {sorted(found)}, registered for {sorted(effects.REGISTRY[site])}")


def test_9kg62_each_class_matches_what_the_function_does(sites):
    for site, (found, kinds, unknown_kind) in sites.items():
        for family, entry in effects.REGISTRY.get(site, {}).items():  # an unregistered site fails the first test
            assert entry.cls in effects.CLASSES, f"{site} {family}: unknown class {entry.cls!r}"
            assert entry.why, f"{site} {family}: no reason recorded"
            calls = found.get(family, set())
            if family == "journal":
                assert entry.cls in (effects.JOURNALED_BEFORE, effects.JOURNALED_AFTER, effects.MARKER), (site, entry)
                assert not entry.via, f"{site}: a journal write is its own evidence"
                if "prepare" in calls:
                    assert entry.cls == effects.JOURNALED_BEFORE, f"{site}: prepares an entry, so it is journaled before"
                if entry.cls == effects.JOURNALED_BEFORE:
                    assert calls & {"prepare", "append"}, f"{site}: journaled before needs a prepare or a direct append"
                elif entry.cls == effects.JOURNALED_AFTER:
                    assert calls <= {"record", "append"}, f"{site}: journaled after is a record or an append, found {sorted(calls)}"
                else:
                    assert calls == {"append"}, f"{site}: a marker is a direct append, found {sorted(calls)}"
                assert entry.kinds, f"{site}: declare the journal kinds it writes"
                assert set(entry.kinds) <= set(journal.KINDS), f"{site}: unknown kinds {set(entry.kinds) - set(journal.KINDS)}"
                assert kinds <= set(entry.kinds), f"{site}: writes {sorted(kinds - set(entry.kinds))}, not declared"
                if not unknown_kind:
                    assert kinds == set(entry.kinds), f"{site}: declares {sorted(set(entry.kinds) - kinds)}, never writes it"
            else:
                assert entry.cls != effects.MARKER and not entry.kinds, f"{site} {family}: only a journal write is a marker"
                if entry.cls in (effects.JOURNALED_BEFORE, effects.JOURNALED_AFTER):
                    assert entry.via, f"{site} {family}: name the registered function whose journal entry covers it"
                    covering = effects.REGISTRY.get(entry.via, {}).get("journal")
                    assert covering and covering.cls == entry.cls, (
                        f"{site} {family}: {entry.via} has no {entry.cls} journal entry to cover it")
                else:
                    assert not entry.via, f"{site} {family}: `via` is only for a journaled class"


def test_9kg62_every_journal_kind_has_a_writer_and_each_restrictive_kind_is_prepared(sites):
    declared = {kind for entries in effects.REGISTRY.values() if "journal" in entries
                for kind in entries["journal"].kinds}
    assert set(journal.KINDS) - INTERNAL_KINDS - declared == set(), "journal kinds no registered site writes"
    prepared = {kind for site, (found, kinds, _) in sites.items() if "prepare" in found.get("journal", ())
                for kind in effects.REGISTRY.get(site, {}).get("journal", effects.Site("", "")).kinds}
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
    writes = set()
    for name, function in _functions("agreements/provider.py"):
        for call in _calls(function):
            if isinstance(call.func, ast.Name) and call.func.id == "exchange":
                method = call.args[0]
                assert isinstance(method, ast.Constant), f"provider.{name}: the exchange method is not a literal"
                if method.value != "GET":
                    writes.add(name)
    assert writes == DOCUMENSO_WRITES
    # MXroute: the interface's methods other than reads and lists are writes.
    interface = {name.split(".", 1)[1] for name, _ in _functions("provisioning/adapter.py") if name.startswith("MailHost.")}
    assert {name for name in interface if not name.startswith(("read", "list"))} == MAILHOST_WRITES
    # IMAP: a client method calling a state-changing IMAP command, directly or through UID, is a write.
    changing = {"append", "store", "copy", "move", "expunge", "delete", "create", "rename"}
    writes = set()
    for name, function in _functions("correspondence/imap.py"):
        if not name.startswith("MailboxClient."):
            continue
        for call in _calls(function):
            command = call.func.attr.lower() if isinstance(call.func, ast.Attribute) else ""
            if command == "uid":
                assert isinstance(call.args[0], ast.Constant), f"{name}: the UID command is not a literal"
                command = call.args[0].value.lower()
            if command in changing and _dotted(call.func.value, {"self": "self"}) == "self.imap":
                writes.add(name.split(".", 1)[1])
    assert writes == IMAP_WRITES
    # SMTP: only `send` (and its body helper) speaks the mail transaction.
    speaking = {name for name, function in _functions("correspondence/transport.py") for call in _calls(function)
                if isinstance(call.func, ast.Attribute) and call.func.attr in {"mail", "rcpt", "data", "sendmail",
                                                                             "send_message"}}
    assert speaking <= {"send", "_send_body"}, speaking
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


@pytest.mark.parametrize("source, family", [
    ("from correspondence import transport\ndef f():\n    transport.send(b'', 'a', 'b')\n", "smtp"),
    ("from correspondence.transport import send as deliver\ndef f():\n    deliver(b'', 'a', 'b')\n", "smtp"),
    ("def f():\n    from agreements import provider\n    provider.cancel('x')\n", "documenso"),
    ("import agreements.provider as p\ndef f():\n    p.distribute('x')\n", "documenso"),
    ("from provisioning import adapter\ndef f():\n    adapter.host().delete_forwarder('d', 'a')\n", "mailhost"),
    ("from provisioning.adapter import host\ndef f():\n    h = host()\n    h.create('d', 'l', 'p', 1, 1)\n", "mailhost"),
    ("from correspondence.imap import MailboxClient\ndef f():\n    with MailboxClient(1) as c:\n        c.append('S', b'')\n",
     "imap"),
    ("from pydantic_ai import Agent\ndef f():\n    a = Agent('m')\n    a.run_sync('p')\n", "model"),
    ("from workflow.journal import record\ndef f():\n    record('model_usage', 'k')\n", "journal"),
])
def test_9kg62_an_unclassified_effect_in_any_spelling_is_found(source, family):
    found = discover([("synthetic.module", source)])
    assert list(found) == ["synthetic.module:f"] and set(found["synthetic.module:f"][0]) == {family}
    assert "synthetic.module:f" not in effects.REGISTRY  # so the first test would name it


def test_9kg62_lookalike_calls_are_not_effects():
    source = ("def f(user, items):\n    user.set_password('x')\n    items.append(1)\n"
              "    Model.objects.create(a=1)\n    handler.run(1)\n")
    assert discover([("synthetic.module", source)]) == {}
