"""OpenAI 호환 /chat/completions LLM provider.

llama.cpp, LM Studio, 원격 API 등 OpenAI 호환 엔드포인트용.
``base_url``은 "/v1"을 포함한다 (예: http://127.0.0.1:7112/v1).
``api_key``가 빈 문자열이면 Authorization 헤더를 생략한다.
오류는 전부 ``CompilerError`` 계층(``errors`` 모듈)으로 변환해 던진다.
Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

import json

import requests

from ..errors import (
    CompilerAuthError,
    CompilerConnectionError,
    CompilerEmptyResultError,
    CompilerParseError,
    CompilerServerError,
    CompilerTimeoutError,
)

__all__ = ["OpenAICompatibleProvider"]


def _post_json(
    url: str,
    payload: dict,
    headers: dict,
    timeout_seconds: float,
) -> requests.Response:
    """POST 후 공통 오류 변환 (타임아웃/연결/인증/HTTP 상태)."""
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout_seconds)
    except requests.exceptions.Timeout:
        raise CompilerTimeoutError(f"LLM request timed out after {timeout_seconds}s") from None
    except requests.exceptions.RequestException as e:
        raise CompilerConnectionError(f"cannot reach LLM server at {url}: {e}") from e
    if resp.status_code in (401, 403):
        raise CompilerAuthError(f"LLM auth failed ({resp.status_code})")
    if resp.status_code != 200:
        raise CompilerServerError(resp.status_code, resp.text[:300])
    return resp


class OpenAICompatibleProvider:
    """OpenAI 호환 /chat/completions (llama.cpp, LM Studio, 원격 API)."""

    name = "openai_compatible"

    def __init__(self, base_url: str, model: str = "", api_key: str = "") -> None:
        # base_url은 "/v1" 포함 (예: http://127.0.0.1:7112/v1)
        # api_key 빈 문자열이면 Authorization 헤더 생략
        self.base_url = base_url
        self.model = model
        self.api_key = api_key

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> str:
        """메시지를 /chat/completions로 보내고 응답 텍스트를 돌려준다."""
        payload = {
            "model": self.model or "local-model",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
        }
        url = self.base_url.rstrip("/") + "/chat/completions"
        resp = _post_json(url, payload, headers, timeout)
        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise CompilerParseError(f"LLM response is not valid JSON: {e}") from e
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise CompilerEmptyResultError(
                "LLM response has no message content"
            ) from None
        if not content:
            raise CompilerEmptyResultError("LLM response has empty content")
        return content
