"""Cold worker startup and real HTTP connection closure seen in the live canary."""

import sys

import pytest

from crm import twenty
from tests import support
from tests.test_inbound import tls  # noqa: F401
from tests.test_twenty_projection import tw  # noqa: F401


@pytest.mark.parametrize("activated", [False, True])
def test_cold_worker_preserves_model_activation_after_loading_handlers(
    tmp_path, activated
):
    code = f"""
import django,sys
django.setup()
assert 'assessments.agent' not in sys.modules
from django.conf import settings
from django.core.management import call_command
from pydantic_ai import models
from workflow import ledger
settings.CATALYST_ASSESSMENT_MODEL = 'minimax:synthetic-model'
settings.CATALYST_ASSESSMENT_LIVE_BASE_URL = 'https://model.example.test/v1'
settings.CATALYST_ASSESSMENT_API_KEY = 'synthetic-only'
settings.CATALYST_ASSESSMENT_LIVE_ACTIVATION = {int(activated)}
def idle(registry):
    assert 'run_assessment' in registry
    assert models.ALLOW_MODEL_REQUESTS is {activated!r}, 'handler import changed model activation'
    return False
ledger.run_one = idle
call_command('run_worker', exit_when_idle=True, exclude='fetch_evidence')
"""
    result = support.run(
        [sys.executable, "-c", code],
        CATALYST_WORKER_HEARTBEAT_FILE=str(tmp_path / "worker.beat"),
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("truncated", [False, True])
def test_twenty_accepts_complete_close_responses_but_refuses_truncation(
    tw, monkeypatch, truncated
):  # noqa: F811
    handler = tw.server.RequestHandlerClass
    original = handler.end_headers
    header = handler.send_header

    def declared_length(self, name, value):
        if truncated and name == "Content-Length":
            value = str(int(value) + 5)
        header(self, name, value)

    def close_response(self):
        self.send_header("Connection", "close")
        self.close_connection = True
        original(self)

    monkeypatch.setattr(handler, "end_headers", close_response)
    monkeypatch.setattr(handler, "send_header", declared_length)
    expected = tw.add_person("synthetic@example.test")
    if truncated:
        with pytest.raises(twenty.TwentyError, match="response_truncated"):
            twenty.find_people_by_email("synthetic@example.test")
        return
    rows = twenty.find_people_by_email("synthetic@example.test")
    assert [row["id"] for row in rows] == [expected]
