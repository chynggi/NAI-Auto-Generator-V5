"""LLM 시스템 프롬프트 템플릿 + LLM 응답 파서.

자연어 → NovelAI V5 프롬프트 컴파일 파이프라인의 LLM 단계:
- ``load_system_prompt``: 템플릿 파일(templates/system_prompt.md) 로드.
- ``extract_json``/``parse_structured``: LLM 응답 텍스트에서 JSON 추출 및
  ``LLMStructuredPrompt`` 스키마 검증.
- ``build_messages``: 생성/수정 모드에 맞는 system/user 메시지 구성.
- ``SceneParser``: LLM 호출 + 구조화 파싱을 묶은 Scene Understanding Layer.

Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import ValidationError

from naiauto.core.prompt.errors import (
    CompilerEmptyResultError,
    CompilerParseError,
    CompilerProviderUnavailableError,
)
from naiauto.core.prompt.llm import LLMProvider
from naiauto.core.prompt.schema import LLMStructuredPrompt

__all__ = [
    "PRESERVED_TOKEN_RE",
    "load_system_prompt",
    "extract_json",
    "parse_structured",
    "build_messages",
    "SceneParser",
]

_TEMPLATE_PATH = Path(__file__).parent / "templates" / "system_prompt.md"

#: 보존 대상 토큰 — `__dynamic__` 형태의 플레이스홀더 또는 `{artist:grp}` 형태의
#: 단일 중괄호 토큰. 수정 모드에서 제거되면 안 되는 원본 프롬프트 조각.
PRESERVED_TOKEN_RE = re.compile(r"(__[\w=\-]+__|\{[^{}]*\})")


def load_system_prompt() -> str:
    """templates/system_prompt.md 내용을 읽는다.

    파일 누락/읽기 실패 → ``CompilerProviderUnavailableError``
    ("system prompt template missing").
    """
    try:
        return _TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise CompilerProviderUnavailableError("system prompt template missing") from exc


def extract_json(text: str) -> dict:
    """LLM 응답 텍스트에서 JSON 객체 1개를 추출한다.

    코드펜스(```json``` 펜스 라인) 제거 후, 첫 ``{``부터 균형 잡힌 ``}``까지
    잘라 ``json.loads``를 수행한다. 프로즈로 둘러싸인 JSON도 추출 가능.
    실패 시 원문 앞 200자를 포함한 ``CompilerParseError``를 던진다.
    """
    original = text.strip()
    text = re.sub(r"^```(?:json)?\s*$", "", original, flags=re.MULTILINE).strip()

    start = text.find("{")
    if start == -1:
        raise CompilerParseError(
            f"no JSON object found in LLM response: {original[:200]}"
        )

    depth = 0
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break

    if end == -1:
        raise CompilerParseError(
            f"unbalanced braces in LLM response: {original[:200]}"
        )

    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise CompilerParseError(
            f"invalid JSON in LLM response ({exc}): {original[:200]}"
        ) from exc

    if not isinstance(data, dict):
        raise CompilerParseError(
            f"LLM response is not a JSON object: {original[:200]}"
        )
    return data


def parse_structured(text: str) -> LLMStructuredPrompt:
    """LLM 응답 텍스트를 추출·검증해 ``LLMStructuredPrompt``로 만든다.

    스키마 검증 실패(ValidationError) → ``CompilerParseError``.
    """
    data = extract_json(text)
    try:
        return LLMStructuredPrompt.model_validate(data)
    except ValidationError as exc:
        raise CompilerParseError(f"invalid LLM output schema: {exc}") from exc


def build_messages(
    text: str,
    *,
    existing_prompt: str = "",
    preserved: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    """LLM 호출용 system/user 메시지 목록을 구성한다.

    - 생성 모드(``existing_prompt`` 비어있음): user = 원문 그대로.
    - 수정 모드: 기존 프롬프트·보존 토큰·수정 요청을 한 user 메시지로 조립.
    """
    system = load_system_prompt()
    if existing_prompt:
        user = (
            "EXISTING PROMPT:\n"
            f"{existing_prompt}\n\n"
            "PRESERVED TOKENS (must not be removed from the final prompt):\n"
            f"{', '.join(preserved) or '(none)'}\n\n"
            "MODIFICATION REQUEST:\n"
            f"{text}"
        )
    else:
        user = text
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


class SceneParser:
    """LLM 호출 + 구조화 파싱을 묶은 Scene Understanding Layer.

    ``LLMProvider`` 프로토콜(``llm.LLMProvider``)에만 의존한다.
    """

    def __init__(
        self,
        provider: LLMProvider,
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float = 120.0,
    ) -> None:
        self.provider = provider
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def parse(
        self,
        text: str,
        *,
        existing_prompt: str = "",
        preserved: tuple[str, ...] = (),
    ) -> LLMStructuredPrompt:
        """자연어를 LLM에 보내 구조화 프롬프트로 파싱한다.

        빈 응답 → ``CompilerEmptyResultError``.
        """
        messages = build_messages(
            text, existing_prompt=existing_prompt, preserved=preserved
        )
        response = self.provider.chat(
            messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
        )
        if not response.strip():
            raise CompilerEmptyResultError("LLM returned an empty response")
        return parse_structured(response)
