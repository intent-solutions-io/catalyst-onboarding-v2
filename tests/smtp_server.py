"""A scripted SMTP server on loopback for the 2B.1 tests (016 A3, TEST-P2-48). Synthetic and in-process: no
dependency, no network beyond 127.0.0.1, no real mail.

`script` maps a phase to the reply the server gives there. Phases: greeting, ehlo, mail, rcpt, data
(the reply to the DATA command), end (the reply after the end-of-data marker). A value is a reply code,
"drop" (close the connection without replying) or "silent" (never reply; the client's deadline decides).
A value may also be a list, consumed one per connection, so a phase can fail and then recover.

The server records each command verb in order, and each message it fully received with its envelope.
`ServerEvidence` is the declared synthetic evidence source for reconciliation tests (016 A5): it reports
received messages with an origin the test chooses, so admissibility rules are tested without any provider.
"""

import email
import socketserver
import threading
import time
from email.policy import default as DEFAULT_POLICY

from correspondence.outbound import Evidence
from correspondence.rendering import canonical_digest

DEFAULTS = {"greeting": 220, "ehlo": 250, "mail": 250, "rcpt": 250, "data": 354, "end": 250}


class ScriptedSMTP:
    def __init__(self, script=None, advertise_starttls=False):
        self.script = {**DEFAULTS, **(script or {})}
        self.advertise_starttls = advertise_starttls
        self.commands = []
        self.messages = []  # dicts: mail_from, rcpts, data (bytes)
        self.connections = 0
        self._lock = threading.Lock()
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            timeout = 10

            def handle(self):
                with outer._lock:
                    outer.connections += 1
                state = {"from": None, "rcpts": []}
                if not self.reply("greeting", "220 synthetic.example.test ESMTP"):
                    return
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    verb = line.split(b" ", 1)[0].split(b":", 1)[0].strip().upper().decode(errors="replace")
                    with outer._lock:
                        outer.commands.append(verb)
                    if verb in ("EHLO", "HELO"):
                        lines = ["250-synthetic.example.test"] + (["250-STARTTLS"] if outer.advertise_starttls else []) + ["250 OK"]
                        if not self.reply("ehlo", "\r\n".join(lines)):
                            return
                    elif verb == "MAIL":
                        state["from"] = line.decode(errors="replace")
                        if not self.reply("mail", "250 OK"):
                            return
                    elif verb == "RCPT":
                        state["rcpts"].append(line.decode(errors="replace").split(":", 1)[1].strip().strip("<>"))
                        if not self.reply("rcpt", "250 OK"):
                            return
                    elif verb == "DATA":
                        if not self.reply("data", "354 End data with <CR><LF>.<CR><LF>"):
                            return
                        body = []
                        while True:
                            chunk = self.rfile.readline()
                            if not chunk:
                                return
                            if chunk == b".\r\n":
                                break
                            body.append(chunk[1:] if chunk.startswith(b"..") else chunk)
                        with outer._lock:
                            outer.messages.append({"from": state["from"], "rcpts": list(state["rcpts"]), "data": b"".join(body)})
                        if not self.reply("end", "250 OK queued"):
                            return
                    elif verb == "QUIT":
                        self.wfile.write(b"221 Bye\r\n")
                        return
                    else:
                        self.wfile.write(b"250 OK\r\n")

            def reply(self, phase, ok_text):
                value = outer.next_value(phase)
                if value == "drop":
                    return False
                if value == "silent":
                    time.sleep(5)
                    return False
                code = int(value)
                text = ok_text if code == DEFAULTS[phase] else f"{code} synthetic {phase} reply"
                if code != DEFAULTS[phase] and phase == "ehlo":
                    text = f"{code} synthetic ehlo reply"
                self.wfile.write(text.encode() + b"\r\n")
                return code < 400

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def next_value(self, phase):
        with self._lock:
            value = self.script[phase]
            if isinstance(value, list):
                value = value.pop(0) if len(value) > 1 else value[0]
            return value

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def parsed(self, index=-1):
        return email.message_from_bytes(self.messages[index]["data"], policy=DEFAULT_POLICY)


class ServerEvidence:
    """Declared synthetic evidence (016 A5): what a verified provider source would report. `origin`,
    `recipient` and `digest` overrides let tests present inadmissible records."""

    server = None
    origin = "provider"
    recipient = None
    digest = None

    def find(self, message_id):
        for item in self.server.messages if self.server else []:
            parsed = email.message_from_bytes(item["data"], policy=DEFAULT_POLICY)
            if parsed["Message-ID"] != message_id:
                continue
            digest = self.digest or canonical_digest(str(parsed["Subject"]), parsed.get_content())
            yield Evidence(origin=self.origin, message_id=message_id,
                           recipient=self.recipient or item["rcpts"][0], content_sha256=digest)
