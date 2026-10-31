"""A local stub of the Twenty REST API for the projection's tests (bgl.14). Loopback only, TLS with the synthetic CA.

It keeps people, notes and note targets in memory and answers the calls `crm.twenty` makes, in the response shapes the
first generation reads (`data.people`, `data.createPerson`, ...), with the filters it sends: `field[eq]:"v"`,
`emails.primaryEmail[ilike]:"v"`, `emails.additionalEmails[like]:"%v%"` and `or(...)` of them. Every request is recorded
(method, path, query, body and the Authorization header) so a test can prove what was and was not sent.

Faults: `fault("POST /rest/people", "lost")` performs the request and then closes the connection without an answer (a
reply lost after Twenty acted); an integer answers that HTTP status without acting. Faults are consumed in order.
Everything here is synthetic; no real Twenty instance, identifier or token appears.
"""

import json
import re
import ssl
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

TOKEN = "synthetic-twenty-token-for-tests-only"  # gitleaks:allow (synthetic; never a real token)
POLL = 0.02
CLAUSE = re.compile(r'([A-Za-z.]+)\[(eq|ilike|like)\]:"([^"]*)"')


def _get(record: dict, dotted: str):
    value = record
    for part in dotted.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _like(pattern: str, value: str) -> bool:
    regex = "^" + "".join(".*" if c == "%" else "." if c == "_" else re.escape(c) for c in pattern) + "$"
    return re.match(regex, value, flags=re.S) is not None


def _matches(record: dict, expression: str) -> bool:
    clauses = CLAUSE.findall(expression)
    if not clauses:
        return False

    def one(field, op, value):
        found = _get(record, field)
        if op == "eq":
            return str(found if found is not None else "") == value
        if op == "ilike":
            return isinstance(found, str) and _like(value.lower(), found.lower())
        values = found if isinstance(found, list) else [found]
        return any(isinstance(v, str) and _like(value, v) for v in values)  # `like` on a JSON array: any element

    results = [one(*c) for c in clauses]
    return any(results) if expression.startswith("or(") else all(results)


class TwentyStub:
    def __init__(self, tls_pair):
        self.people, self.notes, self.targets = {}, {}, {}
        self.requests, self.faults, self._lock = [], [], threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                outer._handle(self, "GET")

            def do_POST(self):
                outer._handle(self, "POST")

            def do_PATCH(self):
                outer._handle(self, "PATCH")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(tls_pair.cert, tls_pair.key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]

    def start(self):
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": POLL}, daemon=True).start()
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()

    # --- test helpers -------------------------------------------------------------------------------------------------

    def fault(self, route: str, *outcomes):
        with self._lock:
            self.faults += [(route, o) for o in outcomes]

    def add_person(self, email="", additional=(), **fields) -> str:
        pid = str(uuid.uuid4())
        self.people[pid] = {"id": pid, "emails": {"primaryEmail": email, "additionalEmails": list(additional)},
                            "deletedAt": None, **fields}
        return pid

    def add_note(self, title, markdown, person_id="") -> str:
        nid = str(uuid.uuid4())
        self.notes[nid] = {"id": nid, "title": title, "bodyV2": {"markdown": markdown, "blocknote": None}, "deletedAt": None}
        if person_id:
            tid = str(uuid.uuid4())
            self.targets[tid] = {"id": tid, "noteId": nid, "targetPersonId": person_id, "deletedAt": None}
        return nid

    def calls(self, method: str, path_prefix: str = "") -> list:
        return [r for r in self.requests if r["method"] == method and r["path"].startswith(path_prefix)]

    def writes(self) -> list:
        return [r for r in self.requests if r["method"] != "GET"]

    def notes_of(self, person_id: str) -> list:
        return [self.notes[t["noteId"]] for t in self.targets.values() if t["targetPersonId"] == person_id]

    # --- the API ------------------------------------------------------------------------------------------------------

    def _handle(self, handler, method):
        parts = urlsplit(handler.path)
        length = int(handler.headers.get("Content-Length") or 0)
        raw = handler.rfile.read(length) if length else b""
        body = json.loads(raw) if raw else None
        query = {k: v[0] for k, v in parse_qs(parts.query).items()}
        with self._lock:
            self.requests.append({"method": method, "path": parts.path, "query": query, "body": body,
                                  "authorization": handler.headers.get("Authorization", "")})
            route = f"{method} {parts.path}"
            fault = next((f for f in self.faults if route.startswith(f[0])), None)
            if fault is not None:
                self.faults.remove(fault)
        if fault is not None and isinstance(fault[1], int):
            return self._send(handler, fault[1], {"error": "synthetic fault"})
        if handler.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._send(handler, 401, {"error": "unauthorized"})
        status, payload = self._route(method, parts.path, query, body)
        if fault is not None and fault[1] == "lost":
            handler.close_connection = True
            handler.connection.shutdown(2)  # acted, but the reply never arrives
            return None
        return self._send(handler, status, payload)

    def _route(self, method, path, query, body):
        segments = [s for s in path.split("/") if s][1:]  # drop "rest"
        collection = segments[0] if segments else ""
        record_id = segments[1] if len(segments) > 1 else ""
        stores = {"people": (self.people, "person", "people", "Person"), "notes": (self.notes, "note", "notes", "Note"),
                  "noteTargets": (self.targets, "noteTarget", "noteTargets", "NoteTarget")}
        if collection not in stores:
            return 404, {"error": "not found"}
        store, one, many, title = stores[collection]
        with self._lock:
            if method == "GET" and not record_id:
                expression = query.get("filter", "")
                rows = [r for r in store.values() if not expression or _matches(r, expression)]
                return 200, {"data": {many: rows[: int(query.get("limit", 60))]}}
            if method == "GET":
                row = store.get(record_id)
                return (200, {"data": {one: row}}) if row else (404, {"error": "not found"})
            if method == "POST" and not record_id:
                rid = str(uuid.uuid4())
                store[rid] = {"id": rid, "deletedAt": None, **(body or {})}
                if collection == "people":
                    store[rid].setdefault("emails", {"primaryEmail": "", "additionalEmails": []})
                return 201, {"data": {f"create{title}": store[rid]}}
            if method == "PATCH" and record_id:
                if record_id not in store:
                    return 404, {"error": "not found"}
                store[record_id].update(body or {})
                return 200, {"data": {f"update{title}": store[record_id]}}
        return 405, {"error": "method"}

    @staticmethod
    def _send(handler, status, payload):
        data = json.dumps(payload).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
