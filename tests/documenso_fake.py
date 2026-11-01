"""A fake Documenso v2 envelope API for P4 tests (021 section 12, proof A). Loopback only, TLS with the synthetic CA.

Synthetic throughout: the shapes follow the installed version's published OpenAPI schema (021 section 15), never a
real response. Like the real API it returns per-recipient signing tokens and links, so tests prove Catalyst drops
them (TEST-P4-24).

`faults` maps "METHOD /path-prefix" to a list consumed in order; each entry is one of:
- ("drop_after",): process the request, then close the connection without answering (an unknown outcome);
- ("drop_before",): close without processing;
- ("status", code, headers): answer with that status and an empty JSON body, without processing;
- ("redirect", location): answer 302 without processing;
- ("oversize",): answer 200 with a body larger than any cap;
- ("slow", seconds): wait, then answer normally;
- ("encoded",): answer 200 with a compressed-encoding header;
- ("truncated",): declare a longer body than is sent, then close.
"""

import json
import ssl
import threading
import time
from datetime import UTC, datetime, timedelta
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

# serve_forever checks for shutdown every poll_interval (0.5 s by default), and stop() waits for it: a
# short interval keeps each test's teardown from waiting up to half a second per server (bead catalyst-v2-egz).
POLL = 0.02

TOKEN = "synthetic-documenso-api-key"
DEFAULT_EMAIL = {k: True for k in ("recipientSigningRequest", "recipientRemoved", "recipientSigned", "documentPending",
                                   "documentCompleted", "documentDeleted", "ownerDocumentCompleted",
                                   "ownerRecipientExpired", "ownerDocumentCreated")}
BASE = "/api/v2"
TRPC = "/api/trpc/"  # bgl.9: the token-authenticated recipient routes (the provider's own signing page uses them)


class FakeDocumenso:
    def __init__(self, tls_pair):
        self.templates = {}  # template envelope id -> {"number": int, "slots": {recipient id: role}}
        self.envelopes = {}  # id -> envelope dict (newest last)
        self.requests, self.faults, self.download = [], {}, (200, "application/pdf", b"%PDF-1.7 synthetic placeholder")
        # Provider-sent email (D-41), modelled on the installed version's handlers: the signing request on distribute,
        # the cancellation email on cancel unless `documentDeleted` is off, the completed copy on completion.
        self.emails = []
        self._lock, self._n, self._f, self.clock = threading.Lock(), 0, 0, 0
        # 9kg.76 review: a provider that ignores the requested order, or omits the page count, must not read as complete.
        self.list_ascending, self.list_omit_total_pages = False, False
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                outer._handle(self, "GET")

            def do_POST(self):
                outer._handle(self, "POST")

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

    # --- test controls ------------------------------------------------------------------------------------------

    def template(self, ref="envelope_template_nda", number=101, slot=7001):
        self.templates[ref] = {"number": number, "slots": {slot: "SIGNER"}}
        return ref, number, {"SIGNER:1": slot}

    def fault(self, key, *entries):
        self.faults.setdefault(key, []).extend(entries)

    def calls(self, method, path):
        return [r for r in self.requests if r["method"] == method and r["path"].split("?")[0] == BASE + path]

    def sign(self, envelope_id, index=0, complete=True):
        """A recipient signs; with `complete`, the envelope completes once every recipient has signed."""
        with self._lock:
            env = self.envelopes[envelope_id]
            env["recipients"][index]["signingStatus"] = "SIGNED"
            if complete and all(r["signingStatus"] == "SIGNED" for r in env["recipients"]):
                env["status"] = "COMPLETED"
                self._mail(env, "documentCompleted", "completed_copy", lambda r: True)

    def _mail(self, env, setting, kind, who):
        if env["_email"].get(setting, True):
            self.emails += [{"kind": kind, "to": r["email"], "envelope": env["id"]} for r in env["recipients"] if who(r)]

    def reject(self, envelope_id, index=0):
        with self._lock:
            env = self.envelopes[envelope_id]
            env["recipients"][index]["signingStatus"] = "REJECTED"
            env["status"] = "REJECTED"

    def expire(self, envelope_id, index=0):
        with self._lock:
            self.envelopes[envelope_id]["recipients"][index]["expired"] = datetime.now(UTC).isoformat()

    def webhook(self, envelope_id, event="DOCUMENT_COMPLETED"):
        """The installed version's webhook body (021 section 15): the document with its legacy numeric id, tokens
        included, wrapped in {event, payload, createdAt, webhookEndpoint}."""
        env = self.envelopes[envelope_id]
        return {"event": event, "createdAt": datetime.now(UTC).isoformat(),
                "webhookEndpoint": "https://catalyst.example.test/hooks/documenso/",
                "payload": {"id": int(envelope_id.split("_")[1]), "externalId": env["externalId"], "status": env["status"],
                            "templateId": env["templateId"], "title": env["title"],
                            "recipients": [dict(r) for r in env["recipients"]]}}

    def add_envelope(self, **fields):
        """An envelope created outside Catalyst's view (for example a late one)."""
        with self._lock:
            return self._create(fields.pop("template_ref"), fields.pop("external_id"), fields.pop("recipients"), **fields)

    # --- the API ------------------------------------------------------------------------------------------------

    def type_fields(self, envelope_id, index, entries):
        """bgl.8: the recipient at `index` typed or chose these values: entries of (kind, page, x, y, text), kind TEXT
        or DROPDOWN, positions as page percentages, as the installed version's envelope read reports inserted fields."""
        with self._lock:
            env = self.envelopes[envelope_id]
            recipient = env["recipients"][index]["id"]
            for kind, page, x, y, text in entries:
                self._f += 1
                env["fields"].append({"id": self._f, "envelopeId": envelope_id, "recipientId": recipient, "type": kind,
                                      "page": page, "positionX": x, "positionY": y, "width": 20, "height": 3,
                                      "customText": text, "inserted": True, "fieldMeta": {"type": kind.lower()}})

    def _create(self, template_ref, external_id, recipients, status="DRAFT", email=None, override=None):
        override = override or {}
        self._n += 1
        self.clock += 1
        envelope_id = f"envelope_{self._n:04d}"
        template = self.templates[template_ref]
        self.envelopes[envelope_id] = {
            "id": envelope_id, "externalId": external_id, "status": status, "type": "DOCUMENT",
            "templateId": template["number"], "title": "Synthetic agreement", "secondaryId": f"document_{self._n}",
            "createdAt": (datetime.now(UTC) + timedelta(milliseconds=self.clock)).isoformat(timespec="milliseconds"),
            "envelopeItems": [{"id": f"item_{self._n}", "envelopeId": envelope_id, "documentDataId": "d", "title": "x", "order": 1}],
            # bgl.8: the distribution method and redirect the create asked for, and the fields (a signature field is
            # never inserted TEXT, so a reader that filters correctly drops it)
            "documentMeta": {"distributionMethod": override.get("distributionMethod", "EMAIL"),
                             "redirectUrl": override.get("redirectUrl")},
            "fields": [{"id": 10_000 + self._n, "envelopeId": envelope_id, "recipientId": 9000 + self._n * 10, "type": "SIGNATURE",
                        "page": 1, "positionX": 10, "positionY": 80, "width": 30, "height": 5, "customText": "", "inserted": False}],
            "recipients": [{"id": 9000 + self._n * 10 + i, "email": r["email"], "name": r.get("name", ""),
                            "role": template["slots"].get(r["id"], "SIGNER"), "signingOrder": r.get("signingOrder"),
                            "signingStatus": "NOT_SIGNED", "sendStatus": "NOT_SENT", "readStatus": "NOT_OPENED",
                            "token": f"secret-signing-token-{self._n}-{i}",
                            "signingUrl": f"https://documenso.example.test/sign/secret-signing-token-{self._n}-{i}"}
                           for i, r in enumerate(recipients)],
            "_email": dict(DEFAULT_EMAIL, **(email or {})),
        }
        return self.envelopes[envelope_id]

    def _handle(self, handler, method):
        path = handler.path
        length = int(handler.headers.get("Content-Length") or 0)
        body = handler.rfile.read(length) if length else b""
        with self._lock:
            self.requests.append({"method": method, "path": path, "headers": dict(handler.headers.items()), "body": body})
            route = path.split("?")[0]
            fault = None
            for key, entries in self.faults.items():
                m, _, prefix = key.partition(" ")
                if m == method and route.startswith(BASE + prefix) and entries:
                    fault = entries.pop(0)
                    break
        if route.startswith(TRPC):  # bgl.9: the recipient-token routes the company countersignature uses
            return self._trpc(handler, method, route, body)
        if fault and fault[0] == "drop_before":
            handler.close_connection = True
            return
        if fault and fault[0] == "status":
            return self._send(handler, fault[1], {}, extra=fault[2] if len(fault) > 2 else {})
        if fault and fault[0] == "redirect":
            handler.send_response(302)
            handler.send_header("Location", fault[1])
            handler.send_header("Content-Length", "0")
            handler.end_headers()
            return
        if fault and fault[0] == "oversize":
            return self._send(handler, 200, {"id": "x" * 3_000_000})
        if fault and fault[0] == "slow":
            time.sleep(fault[1])
        if fault and fault[0] in ("encoded", "truncated"):
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            if fault[0] == "encoded":
                handler.send_header("Content-Encoding", "gzip")
            handler.send_header("Content-Length", "100" if fault[0] == "truncated" else "2")
            handler.end_headers()
            handler.wfile.write(b"{}")
            handler.close_connection = True
            return
        if handler.headers.get("Authorization") != TOKEN:
            return self._send(handler, 401, {"message": "Unauthorized"})
        with self._lock:
            status, payload, content_type = self._route(method, route, path, handler.headers, body)
        if fault and fault[0] == "drop_after":
            handler.close_connection = True
            return
        if content_type == "application/json":
            return self._send(handler, status, payload)
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)

    def _route(self, method, route, path, headers, body):
        json_ = "application/json"
        if method == "POST" and route == BASE + "/envelope/use":
            message = BytesParser(policy=HTTP).parsebytes(
                f"Content-Type: {headers.get('Content-Type')}\r\n\r\n".encode() + body)
            part = next(p for p in message.iter_parts() if p.get_param("name", header="content-disposition") == "payload")
            payload = json.loads(part.get_content())
            if payload["envelopeId"] not in self.templates or payload.get("distributeDocument") is not False:
                return 400, {"message": "Bad request"}, json_
            env = self._create(payload["envelopeId"], payload.get("externalId"), payload["recipients"],
                               email=(payload.get("override") or {}).get("emailSettings"), override=payload.get("override") or {})
            return 200, {"id": env["id"], "recipients": [{k: r[k] for k in ("id", "name", "email", "token", "role",
                                                                              "signingOrder", "signingUrl")}
                                                         for r in env["recipients"]]}, json_
        if method == "POST" and route == BASE + "/envelope/distribute":
            payload = json.loads(body)
            env = self.envelopes.get(payload.get("envelopeId"))
            if env is None or env["status"] != "DRAFT":
                return 400, {"message": "Bad request"}, json_
            env["status"] = "PENDING"
            meta = payload.get("meta") or {}
            # A distribute whose meta omits emailSettings falls back to the all-on default, as the schema does.
            env["_email"] = dict(DEFAULT_EMAIL, **(meta.get("emailSettings") or {})) if meta else env["_email"]
            if meta.get("distributionMethod"):
                env["documentMeta"]["distributionMethod"] = meta["distributionMethod"]
            for r in env["recipients"]:
                r["sendStatus"] = "SENT"
            if env["documentMeta"]["distributionMethod"] != "NONE":  # bgl.8: with NONE the provider mails nobody
                self._mail(env, "recipientSigningRequest", "signing_request", lambda r: True)
            return 200, {"success": True, "id": env["id"], "recipients": env["recipients"]}, json_
        if method == "POST" and route == BASE + "/envelope/cancel":
            request = json.loads(body)
            env = self.envelopes.get(request.get("envelopeId"))
            if env is None or env["status"] != "PENDING":
                return 400, {"message": "Bad request"}, json_
            env["status"] = "CANCELLED"
            env["_cancel_reason"] = request.get("reason", "")
            self._mail(env, "documentDeleted", "cancellation",
                       lambda r: r["sendStatus"] == "SENT" and r["signingStatus"] != "REJECTED" and r["role"] != "CC")
            return 200, {"success": True}, json_
        if method == "GET" and route == BASE + "/envelope":
            query = {k: v[0] for k, v in parse_qs(urlsplit(path).query).items()}
            rows = [e for e in reversed(list(self.envelopes.values()))  # newest first; templateId filters when given
                    if ("templateId" not in query or str(e["templateId"]) == query["templateId"])
                    and e["type"] == query.get("type", "DOCUMENT")]
            if self.list_ascending:
                rows.reverse()
            per, page = int(query.get("perPage", 10)), int(query.get("page", 1))
            pages = max(1, -(-len(rows) // per))
            body = {"data": rows[(page - 1) * per:page * per], "count": len(rows), "currentPage": page, "perPage": per,
                    "totalPages": pages}
            if self.list_omit_total_pages:
                del body["totalPages"]
            return 200, body, json_
        if method == "GET" and route.startswith(BASE + "/envelope/item/") and route.endswith("/download"):
            status, content_type, data = self.download
            return status, data, content_type
        if method == "GET" and route.startswith(BASE + "/envelope/"):
            env = self.envelopes.get(route[len(BASE + "/envelope/"):])
            return (200, env, json_) if env else (404, {"message": "Not found"}, json_)
        return 404, {"message": "Not found"}, json_

    # --- bgl.9: the company countersignature through the recipient-token routes ------------------------------------

    def add_field(self, envelope_id, index, kind="SIGNATURE", inserted=False):
        """A field the recipient at `index` owns (the installed version reports them in the envelope read's `fields`)."""
        with self._lock:
            env = self.envelopes[envelope_id]
            self._fields = getattr(self, "_fields", 50_000) + 1
            env.setdefault("fields", []).append({"id": self._fields, "envelopeId": envelope_id, "type": kind,
                                                 "recipientId": env["recipients"][index]["id"], "page": 1,
                                                 "customText": "", "inserted": inserted})
            return self._fields

    def trpc_fault(self, route, *entries):
        """Faults for a recipient route ("envelope.field.sign" or "recipient.completeDocumentWithToken"): ("status",
        code) answers without processing, ("drop_after",) processes and answers nothing, ("slow", seconds) waits."""
        self.__dict__.setdefault("trpc_faults", {}).setdefault(route, []).extend(entries)

    def _trpc(self, handler, method, route, body):
        name = route[len(TRPC):]
        with self._lock:
            entries = self.__dict__.setdefault("trpc_faults", {}).get(name) or []
            fault = entries.pop(0) if entries else None
        if fault and fault[0] == "slow":
            time.sleep(fault[1])
        if fault and fault[0] == "status":
            return self._send(handler, fault[1], {"error": {"json": {"data": {"code": "SYNTHETIC"}}}})
        # The installed version's CSRF check: a token-authenticated mutation carries the instance's own Origin and, here,
        # never the API key (the API key must not reach a recipient route).
        if (method != "POST" or handler.headers.get("Authorization")
                or handler.headers.get("Origin") != f"https://documenso.example.test:{self.port}"):
            return self._send(handler, 403, {"error": {"json": {"data": {"code": "FORBIDDEN"}}}})
        payload = (json.loads(body or b"{}").get("json") or {})
        with self._lock:
            status, answer = self._recipient_route(name, payload)
        if fault and fault[0] == "drop_after":
            handler.close_connection = True
            return
        return self._send(handler, status, answer)

    def _recipient_route(self, name, payload):
        found = [(env, r) for env in self.envelopes.values() for r in env["recipients"] if r["token"] == payload.get("token")]
        if not found:
            return 404, {"error": {"json": {"data": {"code": "NOT_FOUND"}}}}
        env, recipient = found[0]
        earlier = [r for r in env["recipients"] if (r.get("signingOrder") or 0) < (recipient.get("signingOrder") or 0)]
        if env["status"] != "PENDING" or any(r["signingStatus"] != "SIGNED" for r in earlier):
            return 400, {"error": {"json": {"data": {"code": "INVALID_REQUEST"}}}}
        own = [f for f in env.get("fields", []) if f["recipientId"] == recipient["id"]]
        if name == "envelope.field.sign":
            field = next((f for f in own if f["id"] == payload.get("fieldId")), None)
            value = payload.get("fieldValue") or {}
            if field is None or value.get("type") != field["type"] or not value.get("value"):
                return 400, {"error": {"json": {"data": {"code": "INVALID_REQUEST"}}}}
            field["inserted"], field["customText"] = True, value["value"]
            return 200, {"result": {"data": {"json": {}}}}
        if name == "recipient.completeDocumentWithToken":
            if f"document_{payload.get('documentId')}" != env["secondaryId"]:
                return 400, {"error": {"json": {"data": {"code": "INVALID_REQUEST"}}}}
            if recipient["signingStatus"] == "SIGNED":
                return 200, {"result": {"data": {"json": {"status": "ALREADY_SIGNED"}}}}
            if any(f["type"] == "SIGNATURE" and not f["inserted"] for f in own):
                return 400, {"error": {"json": {"data": {"code": "FIELDS_MISSING"}}}}
            recipient["signingStatus"] = "SIGNED"
            env.setdefault("_countersigned", []).append(recipient["email"])
            if all(r["signingStatus"] == "SIGNED" for r in env["recipients"]):
                env["status"] = "COMPLETED"
                self._mail(env, "documentCompleted", "completed_copy", lambda r: True)
            return 200, {"result": {"data": {"json": {"status": "SIGNED"}}}}
        return 404, {"error": {"json": {"data": {"code": "NOT_FOUND"}}}}

    def _send(self, handler, status, payload, extra=None):
        data = json.dumps(payload).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        for name, value in (extra or {}).items():
            handler.send_header(name, value)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
