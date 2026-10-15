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


class ErrorResponse(FakeResponse):
    def __init__(self, status: int):
        super().__init__("boom")
        self.status_code = status

    def raise_for_status(self):
        raise requests.HTTPError(f"{self.status_code} Server Error", response=self)


GOOD = '{"message": {"content": "{\\"total\\": \\"10.00\\"}"}}'


def fake_post(*replies):
    calls = []

    def post(*a, **k):
        calls.append(1)
        return replies[len(calls) - 1]

    return post, calls


def test_transient_500_is_retried_once(monkeypatch):
    post, calls = fake_post(ErrorResponse(500), FakeResponse(GOOD))
    monkeypatch.setattr(ex.requests, "post", post)
    result = ex.extract(["TOTAL 10.00"])
    assert result.error is None and str(result.receipt.total) == "10.00"
    assert len(calls) == 2


def test_client_error_is_not_retried(monkeypatch):
    post, calls = fake_post(ErrorResponse(400), FakeResponse(GOOD))
    monkeypatch.setattr(ex.requests, "post", post)
    result = ex.extract(["TOTAL 10.00"])
    assert result.receipt is None and "400" in result.error
    assert len(calls) == 1


def test_gives_up_after_second_failure(monkeypatch):
    post, calls = fake_post(ErrorResponse(500), ErrorResponse(500))
    monkeypatch.setattr(ex.requests, "post", post)
    assert ex.extract(["TOTAL 10.00"]).receipt is None
    assert len(calls) == 2
