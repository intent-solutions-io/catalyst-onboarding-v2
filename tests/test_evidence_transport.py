"""Actual TLS response closure at the public evidence boundary."""

from types import SimpleNamespace

import pytest

from assessments import fetch
from tests.http_fixture import ScriptedHTTPS
from tests.test_inbound import tls  # noqa: F401


@pytest.mark.parametrize(
    "mode", ["complete", "empty", "truncated", "truncated_whitespace", "capped"]
)
def test_evidence_close_response_preserves_completion_and_limits(tls, settings, mode):
    server = ScriptedHTTPS(tls.evidence).start()
    try:
        settings.CATALYST_EVIDENCE_ALLOWED_HOSTS = ["evidence.example.test"]
        settings.CATALYST_EVIDENCE_FIXTURE_ADDRESS = "127.0.0.1"
        settings.CATALYST_EVIDENCE_CA_FILE = tls.ca
        settings.CATALYST_EVIDENCE_PROXY = ""
        source = SimpleNamespace(
            fixture_only=True,
            host="evidence.example.test",
            port=server.port,
            path_prefix="/",
            redirect_hosts=[],
            content_types=["text/plain"],
            max_bytes=5 if mode == "capped" else 65536,
            deadline_seconds=5,
        )
        body = b"" if mode == "empty" else b"Synthetic public evidence."

        def respond(handler):
            handler.send_response(200)
            handler.send_header("Content-Type", "text/plain")
            handler.send_header("Connection", "close")
            declared = str(len(body) + (5 if mode.startswith("truncated") else 0))
            if mode == "truncated_whitespace":
                declared += " \t"
            handler.send_header("Content-Length", declared)
            handler.end_headers()
            handler.wfile.write(body)
            handler.close_connection = True

        server.routes["/work"] = respond
        url = f"https://{source.host}:{source.port}/work"
        if mode.startswith("truncated"):
            with pytest.raises(fetch.Transient, match="response_truncated"):
                fetch.fetch(url, source)
        else:
            result = fetch.fetch(url, source)
            assert result.body == body[: source.max_bytes]
            assert result.truncated is (mode == "capped")
    finally:
        server.stop()
