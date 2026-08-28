"""Ollama 네이티브 /api/chat LLM provider.

로컬 Ollama 서버(기본 http://localhost:11434)와 통신한다.
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

__all__ = ["OllamaProvider"]


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


class OllamaProvider:
    """Ollama 네이티브 /api/chat."""

    name = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "",
        api_key: str = "",
    ) -> None:
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
        """메시지를 /api/chat로 보내고 응답 텍스트를 돌려준다."""
        payload = {
            "model": self.model or "llama3",
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        url = self.base_url.rstrip("/") + "/api/chat"
        resp = _post_json(url, payload, {}, timeout)
        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise CompilerParseError(f"LLM response is not valid JSON: {e}") from e
        content = data.get("message", {}).get("content")
        if not content:
            raise CompilerEmptyResultError("LLM response has no content")
        return content
