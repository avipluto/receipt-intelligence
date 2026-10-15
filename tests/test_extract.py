import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from receipt_ai import extract as ex  # noqa: E402


class FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self):
        pass

    def json(self):
        import json

        return json.loads(self.text)


@pytest.mark.parametrize("body", ["not json at all", '{"message": {"content": "{}"', '{"error": "model crashed"}', "[]"])
def test_unusable_ollama_reply_becomes_error_not_crash(monkeypatch, body):
    monkeypatch.setattr(ex.requests, "post", lambda *a, **k: FakeResponse(body))
    result = ex.extract(["TOTAL 10.00"])
    assert result.receipt is None
    assert "not usable JSON" in result.error


def test_request_failure_becomes_error(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(ex.requests, "post", boom)
    result = ex.extract(["TOTAL 10.00"])
    assert result.receipt is None and "request failed" in result.error


def test_model_content_not_json_becomes_error(monkeypatch):
    monkeypatch.setattr(ex.requests, "post", lambda *a, **k: FakeResponse('{"message": {"content": "{\\"total\\": "}}'))
    result = ex.extract(["TOTAL 10.00"])
    assert result.receipt is None and "schema validation failed" in result.error
