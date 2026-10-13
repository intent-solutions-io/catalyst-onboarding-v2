"""A scripted IMAP server on loopback for the 2B.2 tests (016 section 4 B; owner decisions D-28, M6). Synthetic and
in-process: implicit TLS with run-time test certificates (tests/tls_certs.py), or plaintext only to prove the
client refuses it. It implements the small IMAP4rev1 subset the collector uses: CAPABILITY, LOGIN, EXAMINE and
SELECT (with UIDVALIDITY and UIDNEXT), UID SEARCH (UID ranges and a Message-ID header search), UID FETCH
(RFC822.SIZE, INTERNALDATE, BODY.PEEK[], BODY.PEEK[HEADER]), APPEND, NOOP, LOGOUT.

Mailbox state is a dict of folders, each with a UIDVALIDITY, a UIDNEXT and its messages, so tests can add
mail, renumber a folder (a UIDVALIDITY change) and count what the client appended. Like RFC 9051 permits, a UID
range `n:*` with no UID at or above n still returns the highest UID, so the client's own `uid > last_uid`
filter is exercised. `login_reply` scripts an authentication refusal. The server never records credentials.
"""

import re
import socketserver
import ssl
import threading


class Folder:
    def __init__(self, uidvalidity=1):
        self.uidvalidity = uidvalidity
        self.uidnext = 1
        self.messages = []  # (uid, bytes, internaldate)

    def add(self, data: bytes, internaldate='"13-Oct-2026 10:00:00 +0000"') -> int:
        uid = self.uidnext
        self.uidnext += 1
        self.messages.append((uid, data, internaldate))
        return uid


class ScriptedIMAP:
    def __init__(self, tls=None, login_reply="OK", folders=("INBOX", "Sent")):
        self.tls = tls  # a tests.tls_certs.Pair; None serves plaintext (the client must refuse it)
        self.login_reply = login_reply
        self.folders = {name: Folder(uidvalidity=1000 + i) for i, name in enumerate(folders)}
        self.commands = []
        self.logins = 0
        self._lock = threading.Lock()
        outer = self

        class Handler(socketserver.StreamRequestHandler):
            timeout = 10

            def setup(self):
                if outer.tls is not None:
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    context.load_cert_chain(outer.tls.cert, outer.tls.key)
                    try:
                        self.request = context.wrap_socket(self.request, server_side=True)
                    except (ssl.SSLError, OSError):
                        self.request = None
                        return
                super().setup()

            def handle(self):
                if self.request is None:
                    return
                self.selected = None
                self.send(b"* OK [CAPABILITY IMAP4rev1] synthetic IMAP ready")
                while True:
                    line = self.rfile.readline()
                    if not line:
                        return
                    text = line.decode(errors="replace").rstrip("\r\n")
                    tag, _, rest = text.partition(" ")
                    verb, _, args = rest.partition(" ")
                    verb = verb.upper()
                    if verb == "UID":
                        sub, _, args = args.partition(" ")
                        verb = "UID " + sub.upper()
                    with outer._lock:
                        outer.commands.append(verb)
                    if not self.dispatch(tag, verb, args):
                        return

            def send(self, data: bytes):
                self.wfile.write(data + b"\r\n")

            def ok(self, tag, text="completed"):
                self.send(f"{tag} OK {text}".encode())

            def dispatch(self, tag, verb, args):
                if verb == "CAPABILITY":
                    self.send(b"* CAPABILITY IMAP4rev1 AUTH=PLAIN")
                    self.ok(tag)
                elif verb == "LOGIN":
                    with outer._lock:
                        outer.logins += 1
                    if outer.login_reply != "OK":
                        self.send(f"{tag} NO [AUTHENTICATIONFAILED] synthetic refusal".encode())
                    else:
                        self.ok(tag, "LOGIN completed")
                elif verb in ("SELECT", "EXAMINE"):
                    name = args.strip().strip('"')
                    folder = outer.folders.get(name)
                    if folder is None:
                        self.send(f"{tag} NO no such folder".encode())
                        return True
                    self.selected = name
                    self.send(f"* {len(folder.messages)} EXISTS".encode())
                    self.send(f"* OK [UIDVALIDITY {folder.uidvalidity}] UIDs valid".encode())
                    self.send(f"* OK [UIDNEXT {folder.uidnext}] predicted next UID".encode())
                    self.ok(tag, f"[{'READ-ONLY' if verb == 'EXAMINE' else 'READ-WRITE'}] {verb} completed")
                elif verb == "UID SEARCH":
                    folder = outer.folders[self.selected]
                    match = re.fullmatch(r"UID (\d+):\*", args.strip(), re.I)
                    if match:
                        start = int(match.group(1))
                        uids = [u for u, _, _ in folder.messages if u >= start]
                        if not uids and folder.messages:
                            uids = [folder.messages[-1][0]]  # the n:* quirk: the highest UID even when below n
                    else:
                        header = re.fullmatch(r'HEADER (\S+) "?([^"]*)"?', args.strip(), re.I)
                        needle = header.group(2).lower().encode() if header else b"\x00"
                        uids = [u for u, data, _ in folder.messages if needle in data.lower()]
                    self.send(("* SEARCH " + " ".join(str(u) for u in uids)).strip().encode())
                    self.ok(tag)
                elif verb == "UID FETCH":
                    folder = outer.folders[self.selected]
                    uid_text, _, items = args.partition(" ")
                    found = [(i + 1, u, d, date) for i, (u, d, date) in enumerate(folder.messages) if str(u) == uid_text]
                    for seq, uid, data, date in found:
                        upper = items.upper()
                        if "BODY.PEEK[]" in upper:
                            self.wfile.write(f"* {seq} FETCH (UID {uid} BODY[] {{{len(data)}}}\r\n".encode() + data + b")\r\n")
                        elif "BODY.PEEK[HEADER]" in upper:
                            head = data.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
                            self.wfile.write(f"* {seq} FETCH (UID {uid} BODY[HEADER] {{{len(head)}}}\r\n".encode() + head + b")\r\n")
                        else:
                            self.send(f"* {seq} FETCH (UID {uid} RFC822.SIZE {len(data)} INTERNALDATE {date})".encode())
                    self.ok(tag)
                elif verb == "APPEND":
                    match = re.match(r'"?([^"\s]+)"?.*\{(\d+)\}$', args)
                    if not match or match.group(1) not in outer.folders:
                        self.send(f"{tag} NO [TRYCREATE] no such folder".encode())
                        return True
                    self.send(b"+ Ready for literal data")
                    data = self.rfile.read(int(match.group(2)))
                    self.rfile.readline()
                    with outer._lock:
                        uid = outer.folders[match.group(1)].add(data)
                    self.ok(tag, f"[APPENDUID {outer.folders[match.group(1)].uidvalidity} {uid}] APPEND completed")
                elif verb == "NOOP":
                    self.ok(tag)
                elif verb == "LOGOUT":
                    self.send(b"* BYE synthetic logout")
                    self.ok(tag)
                    return False
                else:
                    self.send(f"{tag} BAD unsupported".encode())
                return True

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self._server = Server(("127.0.0.1", 0), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()

    def deliver(self, data: bytes, folder="INBOX") -> int:
        with self._lock:
            return self.folders[folder].add(data)

    def renumber(self, folder="INBOX"):
        """A UIDVALIDITY change (RFC 9051 2.3.1.1): same messages, new UIDs, a higher validity."""
        with self._lock:
            old = self.folders[folder]
            fresh = Folder(uidvalidity=old.uidvalidity + 100)
            fresh.uidnext = 1
            for _, data, date in old.messages:
                fresh.add(data, date)
            self.folders[folder] = fresh
