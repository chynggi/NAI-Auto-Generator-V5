"""LLM provider 팩토리.

``create_provider``를 통해 provider 이름 문자열로 실제 provider 인스턴스를
생성한다. UI/GUI는 이 함수와 ``LLMProvider`` 프로토콜에만 의존한다.
Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

from typing import Any

from ..errors import CompilerProviderUnavailableError
from ..llm import LLMProvider
from .deepseek import DeepSeekProvider
from .llama_cpp import LlamaCppProvider
from .ollama import OllamaProvider
from .openai_compatible import OpenAICompatibleProvider

__all__ = [
    "API_KEY_CREDENTIAL",
    "create_provider",
    "DeepSeekProvider",
    "LlamaCppProvider",
    "OllamaProvider",
    "OpenAICompatibleProvider",
]

#: 설정 저장소(settings)에서 LLM API 키를 가져올 때 사용할 자격 증명 키.
API_KEY_CREDENTIAL = "llm_api_key"


def create_provider(
    *,
    provider: str,
    base_url: str,
    model: str,
    api_key: str = "",
    **extra: Any,
) -> LLMProvider:
    """provider 이름에 맞는 LLM provider 인스턴스를 생성한다.

    - ``provider == "ollama"`` → ``OllamaProvider``
    - ``provider == "openai_compatible"`` → ``OpenAICompatibleProvider``
    - ``provider == "deepseek"`` → ``DeepSeekProvider`` (thinking/effort는
      ``**extra``로 전달)
    - ``provider == "llama_cpp"`` → ``LlamaCppProvider`` (``**extra``로
      model_path/n_ctx/n_cpu_moe/expert_hot_s 등 전달)
    - 그 외 → ``CompilerProviderUnavailableError``
    """
    if provider == "ollama":
        return OllamaProvider(base_url=base_url, model=model, api_key=api_key)
    if provider == "openai_compatible":
        return OpenAICompatibleProvider(base_url=base_url, model=model, api_key=api_key)
    if provider == "deepseek":
        return DeepSeekProvider(model=model, api_key=api_key, **extra)
    if provider == "llama_cpp":
        return LlamaCppProvider(**extra)
    raise CompilerProviderUnavailableError(f"unknown LLM provider: {provider!r}")
