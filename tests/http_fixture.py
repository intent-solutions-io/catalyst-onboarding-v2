"""A scripted HTTPS server for synthetic evidence sources (P3 3B.1). Loopback only, TLS with the synthetic CA.

`routes` maps a request path to a (status, headers, body) tuple or a callable(handler) for special cases (slow
drip, redirects). Every request's path and headers are recorded so a test can prove what was (and was not) sent.
"""

import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# serve_forever checks for shutdown every poll_interval (0.5 s by default), and stop() waits for it: a
# short interval keeps each test's teardown from waiting up to half a second per server (bead catalyst-v2-egz).
POLL = 0.02


class ScriptedHTTPS:
    def __init__(self, tls_pair):
        self.routes, self.requests, self._lock = {}, [], threading.Lock()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def do_GET(self):
                with outer._lock:
                    outer.requests.append({"path": self.path, "headers": dict(self.headers.items())})
                route = outer.routes.get(self.path.split("?")[0])
                if route is None:
                    route = (404, {"Content-Type": "text/html"}, b"<p>not here</p>")
                if callable(route):
                    route(self)
                    return
                status, headers, body = route
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

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

    def page(self, path, body, status=200, content_type="text/html; charset=utf-8", **headers):
        self.routes[path] = (status, {"Content-Type": content_type, **headers},
                             body.encode() if isinstance(body, str) else body)


def slow_drip(seconds_per_byte: float, total: int):
    def route(handler):
        handler.send_response(200)
        handler.send_header("Content-Type", "text/plain")
        handler.send_header("Content-Length", str(total))
        handler.end_headers()
        for _ in range(total):
            time.sleep(seconds_per_byte)
            try:
                handler.wfile.write(b"x")
                handler.wfile.flush()
            except OSError:
                return
    return route
