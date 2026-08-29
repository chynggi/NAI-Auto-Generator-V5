"""DeepSeek API provider — OpenAI 호환 + thinking 모드.

공식 문서(https://api-docs.deepseek.com) 기준:
- base_url: ``https://api.deepseek.com`` (v1 경로 불필요 — /chat/completions 직행)
- 모델: ``deepseek-v4-flash`` (가성비), ``deepseek-v4-pro`` (컨텍스트 1M)
- thinking 모드: ``"thinking": {"type": "enabled"|"disabled"}`` +
  ``"reasoning_effort": "low"|"medium"|"high"`` (기본 enabled)

``OpenAICompatibleProvider``를 상속해 ``extra_payload()``만 확장한다.
Qt 의존성 없음.
"""

from __future__ import annotations

from .openai_compatible import OpenAICompatibleProvider

__all__ = ["DeepSeekProvider"]

#: 공식 OpenAI 호환 base URL (문서: https://api-docs.deepseek.com)
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

#: 기본 모델 — 가성비 최강 (v4-flash, 컨텍스트 1M)
DEFAULT_MODEL = "deepseek-v4-flash"


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek API — OpenAI 호환 + thinking 모드 파라미터."""

    name = "deepseek"

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str = "",
        *,
        thinking_enabled: bool = True,
        reasoning_effort: str = "medium",
        **_extra,
    ) -> None:
        super().__init__(base_url=DEEPSEEK_BASE_URL, model=model, api_key=api_key)
        self.thinking_enabled = thinking_enabled
        self.reasoning_effort = reasoning_effort

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> str:
        """thinking 모드에서는 max_tokens가 reasoning + content 합계로 계산된다.

        reasoning이 예산을 다 쓰면 content가 비어 "결과가 비어 있습니다"가
        된다 — thinking 중에는 길이 제한을 아예 보내지 않아 서버 기본값을
        쓰게 한다. thinking을 끄면 사용자 설정 그대로 전달.
        """
        if self.thinking_enabled:
            max_tokens = None  # 길이 제한 제거 (서버 기본 max_tokens 사용)
        return super().chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    def extra_payload(self) -> dict:
        """DeepSeek 전용 필드 — thinking 모드 + 추론 강도."""
        return {
            "thinking": {"type": "enabled" if self.thinking_enabled else "disabled"},
            "reasoning_effort": self.reasoning_effort,
        }
