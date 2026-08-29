"""LLM provider (OpenAI 호환 + Ollama + 내장 llama.cpp) 테스트."""
import json
import sys
import types

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
from naiauto.core.prompt.providers.deepseek import DeepSeekProvider
from naiauto.core.prompt.providers.llama_cpp import LlamaCppProvider
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


def test_ollama_provider_non_dict_json_raises_parse_error(monkeypatch):
    # [review #4] JSON 배열 응답은 dict 계약 위반 — AttributeError가 아니라
    # provider 계약(모든 오류는 CompilerError)을 지키는 ParseError로 변환한다
    resp = _FakeResponse(json_data=[])
    _monkeypatch_post(monkeypatch, resp)
    provider = OllamaProvider(base_url="http://localhost:11434", model="gemma3")
    with pytest.raises(CompilerParseError):
        provider.chat([], temperature=0.4, max_tokens=32, timeout=10)


def test_create_provider_factory():
    p = create_provider(provider="openai_compatible", base_url="http://x/v1", model="m")
    assert isinstance(p, OpenAICompatibleProvider)
    p2 = create_provider(provider="ollama", base_url="http://localhost:11434", model="m")
    assert isinstance(p2, OllamaProvider)
    with pytest.raises(CompilerProviderUnavailableError):
        create_provider(provider="wat", base_url="", model="")


# ── LlamaCppProvider (내장 추론) ─────────────────────────────────────────


class _FakeLlama:
    """llama_cpp.Llama 대역 — 생성 인자와 close 호출을 기록한다."""

    instances: list = []
    closed: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        _FakeLlama.instances.append(self)

    def create_chat_completion(self, *, messages, temperature, max_tokens):
        return {"choices": [{"message": {"content": "fake response"}}]}

    def close(self):
        _FakeLlama.closed.append(self)


def _install_fake_llama_cpp(monkeypatch):
    """sys.modules['llama_cpp']를 가짜 모듈로 교체 (Llama만 구현)."""
    fake = types.ModuleType("llama_cpp")
    fake.Llama = _FakeLlama
    monkeypatch.setitem(sys.modules, "llama_cpp", fake)
    _FakeLlama.instances.clear()
    _FakeLlama.closed.clear()


def test_llama_cpp_provider_chat_lazy_loads_and_returns_content(monkeypatch, tmp_path):
    _install_fake_llama_cpp(monkeypatch)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"x")

    provider = LlamaCppProvider(model_path=str(model), n_cpu_moe=22, expert_hot_s=-1)
    assert provider._llm is None  # lazy — 아직 로드 안 됨

    out = provider.chat([{"role": "user", "content": "hi"}], temperature=0.3, max_tokens=64, timeout=10)
    assert out == "fake response"
    assert len(_FakeLlama.instances) == 1
    llm = _FakeLlama.instances[0]
    assert llm.kwargs["model_path"] == str(model)
    assert llm.kwargs["n_cpu_moe"] == 22
    assert llm.kwargs["expert_hot_s"] == -1


def test_llama_cpp_provider_missing_model_file(monkeypatch, tmp_path):
    _install_fake_llama_cpp(monkeypatch)
    provider = LlamaCppProvider(model_path=str(tmp_path / "nope.gguf"))
    with pytest.raises(CompilerProviderUnavailableError, match="model file not found"):
        provider.chat([], temperature=0, max_tokens=1, timeout=1)


def test_llama_cpp_provider_close_releases_model(monkeypatch, tmp_path):
    _install_fake_llama_cpp(monkeypatch)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"x")

    provider = LlamaCppProvider(model_path=str(model))
    provider.chat([], temperature=0, max_tokens=1, timeout=1)
    provider.close()
    assert len(_FakeLlama.closed) == 1
    # close 후 재호출은 새로 로드하지 않고 같은 인스턴스 사용(이미 닫힘 상태)
    assert len(_FakeLlama.instances) == 1


def test_create_provider_factory_llama_cpp(monkeypatch, tmp_path):
    _install_fake_llama_cpp(monkeypatch)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"x")
    p = create_provider(provider="llama_cpp", base_url="", model="", model_path=str(model))
    assert isinstance(p, LlamaCppProvider)


# ── DeepSeekProvider (OpenAI 호환 + thinking 모드) ───────────────────────

def test_deepseek_provider_sends_thinking_payload(monkeypatch):
    captured = _capture_post(monkeypatch)
    provider = DeepSeekProvider(model="deepseek-v4-flash", api_key="sk-test")
    provider.chat([{"role": "user", "content": "hi"}], temperature=0.3, max_tokens=64, timeout=10)

    assert captured["url"] == "https://api.deepseek.com/chat/completions"  # v1 불필요
    payload = captured["kwargs"]["json"]
    assert payload["model"] == "deepseek-v4-flash"
    assert payload["thinking"] == {"type": "enabled"}  # 기본 켬
    assert payload["reasoning_effort"] == "medium"


def test_deepseek_provider_thinking_disabled(monkeypatch):
    captured = _capture_post(monkeypatch)
    provider = DeepSeekProvider(
        model="deepseek-v4-flash", api_key="sk-test",
        thinking_enabled=False, reasoning_effort="low",
    )
    provider.chat([], temperature=0, max_tokens=1, timeout=1)
    payload = captured["kwargs"]["json"]
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["reasoning_effort"] == "low"


def test_deepseek_provider_thinking_drops_max_tokens(monkeypatch):
    # thinking 모드에서는 max_tokens가 reasoning + content 합계로 계산되어
    # reasoning이 예산을 다 쓰면 content가 비어버린다 ("결과가 비어 있습니다").
    # 길이 제한을 아예 보내지 않아 서버 기본값을 쓰게 한다.
    captured = _capture_post(monkeypatch)
    provider = DeepSeekProvider(model="deepseek-v4-flash", api_key="sk-test")
    provider.chat([], temperature=0, max_tokens=100, timeout=1)
    assert "max_tokens" not in captured["kwargs"]["json"]

    # thinking을 끄면 사용자 설정 그대로 전달
    captured2 = _capture_post(monkeypatch)
    p2 = DeepSeekProvider(model="deepseek-v4-flash", api_key="sk-test", thinking_enabled=False)
    p2.chat([], temperature=0, max_tokens=100, timeout=1)
    assert captured2["kwargs"]["json"]["max_tokens"] == 100


def test_create_provider_deepseek_ignores_llama_cpp_extra():
    # build_compiler가 모든 provider에 같은 extra를 넘겨도 DeepSeek는 무시한다
    p = create_provider(
        provider="deepseek", base_url="", model="deepseek-v4-flash",
        api_key="sk-test",
        model_path="/tmp/x.gguf", n_ctx=16384, n_gpu_layers=99,
        n_cpu_moe=0, expert_hot_s=0,
    )
    assert isinstance(p, DeepSeekProvider)


def test_create_provider_factory_deepseek():
    p = create_provider(
        provider="deepseek", base_url="", model="deepseek-v4-pro",
        api_key="sk-test",
    )
    assert isinstance(p, DeepSeekProvider)
    assert p.base_url == "https://api.deepseek.com"
    assert p.model == "deepseek-v4-pro"


# ── 요청 내용 검증 (Minor #4 해소 — Bearer 생략 규칙 포함) ──────────────

def _capture_post(monkeypatch):
    """requests.post를 가로채 (url, kwargs)를 기록하고 200 응답을 돌려준다."""
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        # OpenAI(choices)와 Ollama(message) 파서를 모두 만족시키는 응답
        return _FakeResponse(
            json_data={
                "choices": [{"message": {"content": "ok"}}],
                "message": {"content": "ok"},
            }
        )

    monkeypatch.setattr(requests, "post", fake_post)
    return captured


def test_openai_request_url_and_payload(monkeypatch):
    captured = _capture_post(monkeypatch)
    provider = OpenAICompatibleProvider(base_url="http://127.0.0.1:7112/v1", model="qwen")
    provider.chat([{"role": "user", "content": "hi"}], temperature=0.5, max_tokens=64, timeout=10)

    assert captured["url"] == "http://127.0.0.1:7112/v1/chat/completions"
    payload = captured["kwargs"]["json"]
    assert payload["model"] == "qwen"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    assert payload["temperature"] == 0.5
    assert payload["max_tokens"] == 64
    assert payload["stream"] is False
    headers = captured["kwargs"]["headers"]
    assert "Authorization" not in headers  # api_key 없으면 Bearer 생략 (§28)


def test_openai_bearer_sent_only_with_api_key(monkeypatch):
    captured = _capture_post(monkeypatch)
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m", api_key="secret")
    provider.chat([], temperature=0, max_tokens=1, timeout=1)
    headers = captured["kwargs"]["headers"]
    assert headers["Authorization"] == "Bearer secret"
    assert captured["kwargs"]["timeout"] == 1


def test_ollama_request_url_and_payload(monkeypatch):
    captured = _capture_post(monkeypatch)
    provider = OllamaProvider(base_url="http://localhost:11434", model="gemma3")
    provider.chat([{"role": "user", "content": "hi"}], temperature=0.4, max_tokens=32, timeout=10)

    assert captured["url"] == "http://localhost:11434/api/chat"
    payload = captured["kwargs"]["json"]
    assert payload["model"] == "gemma3"
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0.4, "num_predict": 32}
