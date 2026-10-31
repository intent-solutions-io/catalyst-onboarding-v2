"""A stub transport for the live MXroute adapter (`provisioning.mxroute.MXrouteHost`), answering like the documented
API over the adapter's own HTTP seam, so the tests run the real request building, authentication headers, routing,
error taxonomy and body parsing with no socket ever opened. Synthetic only; nothing is contacted.

`StubTransport.mailboxes` maps (domain, local part) to the facts a read returns; `forwarders` maps (domain, alias) to
destinations; `catch_all` maps a domain to an address. `calls` records (method, path) in order; `headers_seen` every
header set (so a test can prove the key travelled and the key file was read); `passwords_seen` every password a write
carried (only to prove none reaches a record). `faults` queues behaviours for the next matching call, as
(method-and-route, fault) pairs:

- ("POST", "connect_refused"): no request leaves (a definite, not-sent failure);
- ("POST", "timeout_after_send"): the create lands, the answer is lost; ("PATCH", "timeout_after_send"): likewise;
- ("GET", "500"): MXroute's failed or ambiguous lookup; ("POST", "429"): the create lands, the answer is throttled;
- ("POST", "400") and ("PATCH", "400"): the server refuses the password (a definite rejection).

`StubbedMXrouteHost` is the adapter class the tests configure (`CATALYST_PROVISIONING_ADAPTER`; it keeps the guards'
"a test fake" rule): the live class with this module's transport injected.
"""

import re
from urllib.parse import unquote, urlsplit

from provisioning.mxroute import MXrouteHost, Response, TransportFailure

ACCOUNT = re.compile(r"^/domains/([^/]+)/email-accounts(?:/([^/]+))?$")
FORWARDER = re.compile(r"^/domains/([^/]+)/forwarders(?:/([^/]+))?$")
CATCH_ALL = re.compile(r"^/domains/([^/]+)/catch-all$")


def _error(status, code, field=None):
    return Response(status, {"success": False, "error": {"code": code, "message": "synthetic", "field": field}})


class StubTransport:
    def __init__(self):
        self.reset()

    def reset(self):
        self.mailboxes, self.forwarders, self.catch_all = {}, {}, {}
        self.calls, self.headers_seen, self.passwords_seen, self.faults, self.bodies = [], [], [], [], []

    def _fault(self, method):
        for pair in self.faults:
            if pair[0] == method:
                self.faults.remove(pair)
                return pair[1]
        return None

    def __call__(self, method, url, headers, body, timeout):
        path = urlsplit(url).path
        self.calls.append((method, path))
        self.headers_seen.append(dict(headers))
        self.bodies.append(dict(body) if isinstance(body, dict) else body)
        if isinstance(body, dict) and "password" in body:
            self.passwords_seen.append(body["password"])
        fault = self._fault(method)
        if fault == "connect_refused":
            raise TransportFailure("ConnectError", sent=False)
        if fault == "500":
            return _error(500, "SERVER_ERROR")
        if fault == "400":
            return _error(400, "VALIDATION_ERROR", "password")
        answer = self._route(method, path, body)
        if fault == "timeout_after_send":
            raise TransportFailure("ReadTimeout", sent=True)
        if fault == "429":
            return Response(429, {"success": False, "error": {"code": "RATE_LIMITED", "message": "synthetic"}}, retry_after=1.0)
        return answer

    def _route(self, method, path, body):
        if match := ACCOUNT.match(path):
            domain, local = unquote(match.group(1)).lower(), match.group(2)
            local = unquote(local).lower() if local else None
            if method == "GET" and local:
                box = self.mailboxes.get((domain, local))
                return _error(404, "NOT_FOUND") if box is None else Response(200, {"success": True, "data": {
                    "username": local, "quota": box["quota"], "limit": box["limit"], "suspended": box.get("suspended", False)}})
            if method == "POST" and local is None:
                key = (domain, str(body.get("username", "")).lower())
                if key in self.mailboxes:
                    return _error(409, "CONFLICT")
                self.mailboxes[key] = {"quota": body["quota"], "limit": body["limit"], "suspended": False}
                return Response(201, {"success": True, "data": {"username": key[1]}})
            if method == "PATCH" and local:
                if (domain, local) not in self.mailboxes:
                    return _error(404, "NOT_FOUND")
                self.mailboxes[(domain, local)]["current_password"] = body["password"]
                return Response(200, {"success": True, "data": {"username": local}})
        elif match := FORWARDER.match(path):
            domain, alias = unquote(match.group(1)).lower(), match.group(2)
            if method == "GET" and alias is None:
                return Response(200, {"success": True, "data": [
                    {"alias": f"{a}@{domain}", "destinations": list(d)} for (dom, a), d in sorted(self.forwarders.items())
                    if dom == domain]})
            if method == "DELETE" and alias:
                return Response(204, None) if self.forwarders.pop((domain, unquote(alias).lower()), None) is not None \
                    else _error(404, "NOT_FOUND")
        elif (match := CATCH_ALL.match(path)) and method == "GET":
            domain = unquote(match.group(1)).lower()
            address = self.catch_all.get(domain)
            return _error(404, "NOT_FOUND") if not address else Response(200, {"success": True, "data": {"address": address}})
        return _error(404, "NOT_FOUND")


class StubbedMXrouteHost(MXrouteHost):
    transport = StubTransport()

    def __init__(self):
        super().__init__(transport=type(self).transport)
