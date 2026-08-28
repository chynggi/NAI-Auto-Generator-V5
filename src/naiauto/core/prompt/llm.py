"""LLM 백엔드 인터페이스.

UI/GUI는 ``LLMProvider`` 프로토콜에만 의존한다. 실제 provider
(NovelAI/AI21 등)와 테스트용 ``FakeLLMProvider``가 이 프로토콜을 구현한다.
오류는 전부 ``CompilerError`` 계층(``errors`` 모듈)으로 변환해 던진다.
Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

from typing import Protocol

__all__ = ["LLMProvider", "FakeLLMProvider"]


class LLMProvider(Protocol):
    """LLM 백엔드 인터페이스 — UI/GUI는 이 프로토콜에만 의존한다."""

    name: str

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> str:
        """메시지 목록을 보내고 응답 텍스트를 돌려준다. 오류는 CompilerError 계층으로."""
        ...


class FakeLLMProvider:
    """테스트용 결정적 provider. response 반환 또는 error raise.

    - ``response``: 항상 반환할 단일 응답 텍스트.
    - ``responses``: 순서대로 소비할 응답 목록 (소진 시 마지막 재사용).
    - ``error``: 설정되면 모든 chat 호출에서 raise.
    """

    name = "fake"

    def __init__(
        self,
        response: str = "",
        responses: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.responses = list(responses) if responses is not None else None
        self.error = error
        self._index = 0

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> str:
        if self.error is not None:
            raise self.error
        if self.responses:
            out = self.responses[min(self._index, len(self.responses) - 1)]
            self._index += 1
            return out
        return self.response
