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

TOKEN = "synthetic-documenso-api-key"
DEFAULT_EMAIL = {k: True for k in ("recipientSigningRequest", "recipientRemoved", "recipientSigned", "documentPending",
                                   "documentCompleted", "documentDeleted", "ownerDocumentCompleted",
                                   "ownerRecipientExpired", "ownerDocumentCreated")}
BASE = "/api/v2"


class FakeDocumenso:
    def __init__(self, tls_pair):
        self.templates = {}  # template envelope id -> {"number": int, "slots": {recipient id: role}}
        self.envelopes = {}  # id -> envelope dict (newest last)
        self.requests, self.faults, self.download = [], {}, (200, "application/pdf", b"%PDF-1.7 synthetic placeholder")
        # Provider-sent email (D-41), modelled on the installed version's handlers: the signing request on distribute,
        # the cancellation email on cancel unless `documentDeleted` is off, the completed copy on completion.
        self.emails = []
        self._lock, self._n, self.clock = threading.Lock(), 0, 0
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
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
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

    def _create(self, template_ref, external_id, recipients, status="DRAFT", email=None):
        self._n += 1
        self.clock += 1
        envelope_id = f"envelope_{self._n:04d}"
        template = self.templates[template_ref]
        self.envelopes[envelope_id] = {
            "id": envelope_id, "externalId": external_id, "status": status, "type": "DOCUMENT",
            "templateId": template["number"], "title": "Synthetic agreement", "secondaryId": f"document_{self._n}",
            "createdAt": (datetime.now(UTC) + timedelta(milliseconds=self.clock)).isoformat(timespec="milliseconds"),
            "envelopeItems": [{"id": f"item_{self._n}", "envelopeId": envelope_id, "documentDataId": "d", "title": "x", "order": 1}],
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
                               email=(payload.get("override") or {}).get("emailSettings"))
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
            for r in env["recipients"]:
                r["sendStatus"] = "SENT"
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
            rows = [e for e in reversed(list(self.envelopes.values()))
                    if str(e["templateId"]) == query.get("templateId") and e["type"] == query.get("type", "DOCUMENT")]
            per, page = int(query.get("perPage", 10)), int(query.get("page", 1))
            pages = max(1, -(-len(rows) // per))
            return 200, {"data": rows[(page - 1) * per:page * per], "count": len(rows), "currentPage": page,
                         "perPage": per, "totalPages": pages}, json_
        if method == "GET" and route.startswith(BASE + "/envelope/item/") and route.endswith("/download"):
            status, content_type, data = self.download
            return status, data, content_type
        if method == "GET" and route.startswith(BASE + "/envelope/"):
            env = self.envelopes.get(route[len(BASE + "/envelope/"):])
            return (200, env, json_) if env else (404, {"message": "Not found"}, json_)
        return 404, {"message": "Not found"}, json_

    def _send(self, handler, status, payload, extra=None):
        data = json.dumps(payload).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        for name, value in (extra or {}).items():
            handler.send_header(name, value)
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)
