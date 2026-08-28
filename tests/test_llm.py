import pytest

from naiauto.core.prompt.errors import (
    CompilerAuthError,
    CompilerConnectionError,
    CompilerEmptyResultError,
    CompilerError,
    CompilerParseError,
    CompilerServerError,
    CompilerTimeoutError,
)
from naiauto.core.prompt.llm import FakeLLMProvider, LLMProvider


def test_fake_provider_returns_canned_response():
    provider = FakeLLMProvider(response='{"scene": {"tags": ["cafe"]}}')
    out = provider.chat([], temperature=0.3, max_tokens=100, timeout=5)
    assert '"cafe"' in out


def test_fake_provider_raises_error():
    provider = FakeLLMProvider(error=CompilerConnectionError("offline"))
    with pytest.raises(CompilerError):
        provider.chat([], temperature=0.3, max_tokens=100, timeout=5)


def test_fake_provider_consumes_response_list_in_order():
    provider = FakeLLMProvider(responses=["first", "second", "third"])
    got = [provider.chat([], temperature=0, max_tokens=1, timeout=1) for _ in range(4)]
    assert got[:3] == ["first", "second", "third"]
    assert got[3] == "third"  # 소진 후 마지막 재사용


def test_error_hierarchy_all_subclass_compiler_error():
    for cls in (CompilerConnectionError, CompilerTimeoutError, CompilerAuthError,
                CompilerServerError, CompilerParseError, CompilerEmptyResultError):
        assert issubclass(cls, CompilerError)


def test_server_error_carries_status_and_body():
    err = CompilerServerError(500, "sever debug")
    assert err.status_code == 500
    assert "sever" in str(err)