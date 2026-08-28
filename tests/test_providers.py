"""LLM provider (OpenAI 호환 + Ollama) 테스트 — requests.post를 monkeypatch한다."""
import json

import pytest
import requests

from naiauto.core.prompt.errors import (
    CompilerAuthError,
    CompilerConnectionError,
    CompilerEmptyResultError,
    CompilerParseError,
    CompilerProviderUnavailableError,
    CompilerServerError,
    CompilerTimeoutError,
)
from naiauto.core.prompt.providers import create_provider
from naiauto.core.prompt.providers.ollama import OllamaProvider
from naiauto.core.prompt.providers.openai_compatible import OpenAICompatibleProvider


class _FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None, raise_for_body=False):
        self.status_code = status_code
        self.text = text
        self._json = json_data
        self.raise_for_body = raise_for_body
        self.headers = {}

    def json(self):
        if self.raise_for_body:
            raise json.JSONDecodeError("bad", "doc", 0)
        return self._json


def _monkeypatch_post(monkeypatch, response, error=None):
    def fake_post(*args, **kwargs):
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(requests, "post", fake_post)


def test_openai_provider_parses_chat_completion(monkeypatch):
    resp = _FakeResponse(json_data={"choices": [{"message": {"content": "hello"}}]})
    _monkeypatch_post(monkeypatch, resp)
    provider = OpenAICompatibleProvider(base_url="http://127.0.0.1:7112/v1", model="qwen")
    out = provider.chat([{"role": "user", "content": "hi"}], temperature=0.5, max_tokens=64, timeout=10)
    assert out == "hello"


def test_openai_provider_timeout_maps_to_timeout_error(monkeypatch):
    _monkeypatch_post(monkeypatch, None, error=requests.exceptions.Timeout())
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with pytest.raises(CompilerTimeoutError):
        provider.chat([], temperature=0, max_tokens=1, timeout=1)


def test_openai_provider_connection_error(monkeypatch):
    _monkeypatch_post(monkeypatch, None, error=requests.exceptions.ConnectionError("refused"))
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with pytest.raises(CompilerConnectionError):
        provider.chat([], temperature=0, max_tokens=1, timeout=1)


def test_openai_provider_auth_error(monkeypatch):
    _monkeypatch_post(monkeypatch, _FakeResponse(status_code=401, text="no"))
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m", api_key="bad")
    with pytest.raises(CompilerAuthError):
        provider.chat([], temperature=0, max_tokens=1, timeout=1)


def test_openai_provider_server_error(monkeypatch):
    _monkeypatch_post(monkeypatch, _FakeResponse(status_code=500, text="boom"))
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with pytest.raises(CompilerServerError) as ei:
        provider.chat([], temperature=0, max_tokens=1, timeout=1)
    assert ei.value.status_code == 500


def test_openai_provider_empty_content(monkeypatch):
    _monkeypatch_post(monkeypatch, _FakeResponse(json_data={"choices": []}))
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with pytest.raises(CompilerEmptyResultError):
        provider.chat([], temperature=0, max_tokens=1, timeout=1)


def test_openai_provider_malformed_json_body(monkeypatch):
    _monkeypatch_post(monkeypatch, _FakeResponse(json_data=None, raise_for_body=True))
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with pytest.raises(CompilerParseError):
        provider.chat([], temperature=0, max_tokens=1, timeout=1)


def test_ollama_provider_parses_response(monkeypatch):
    resp = _FakeResponse(json_data={"message": {"content": "bye"}, "done": True})
    _monkeypatch_post(monkeypatch, resp)
    provider = OllamaProvider(base_url="http://localhost:11434", model="gemma3")
    out = provider.chat([{"role": "user", "content": "hi"}], temperature=0.4, max_tokens=32, timeout=10)
    assert out == "bye"


def test_ollama_provider_empty_content(monkeypatch):
    resp = _FakeResponse(json_data={"done": True})
    _monkeypatch_post(monkeypatch, resp)
    provider = OllamaProvider(base_url="http://localhost:11434", model="gemma3")
    with pytest.raises(CompilerEmptyResultError):
        provider.chat([], temperature=0.4, max_tokens=32, timeout=10)


def test_create_provider_factory():
    p = create_provider(provider="openai_compatible", base_url="http://x/v1", model="m")
    assert isinstance(p, OpenAICompatibleProvider)
    p2 = create_provider(provider="ollama", base_url="http://localhost:11434", model="m")
    assert isinstance(p2, OllamaProvider)
    with pytest.raises(CompilerProviderUnavailableError):
        create_provider(provider="wat", base_url="", model="")
