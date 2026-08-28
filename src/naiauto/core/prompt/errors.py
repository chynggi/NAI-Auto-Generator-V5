"""컴파일러 오류 계층.

자연어 → NovelAI V5 프롬프트 컴파일 파이프라인에서 발생하는 모든
오류의 베이스 클래스. LLM 백엔드 오류(연결/타임아웃/인증/HTTP)와
파싱 오류(JSON 추출/스키마 검증/빈 결과)를 계층으로 표현한다.
UI/GUI는 ``CompilerError`` 기준으로만 예외를 처리하면 된다.
Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations


class CompilerError(Exception):
    """모든 컴파일러 오류의 베이스."""


class CompilerConnectionError(CompilerError):
    """서버 오프라인/연결 실패."""


class CompilerTimeoutError(CompilerError):
    """timeout."""


class CompilerAuthError(CompilerError):
    """401/403."""


class CompilerServerError(CompilerError):
    """기타 HTTP 오류 (status_code, body 스니펫 보관)."""

    def __init__(self, status_code: int, body: str = "") -> None:
        super().__init__(f"server error (status {status_code})")
        self.status_code = status_code
        self.body = body

    def __str__(self) -> str:
        if self.body:
            return f"server error (status {self.status_code}): {self.body}"
        return f"server error (status {self.status_code})"


class CompilerParseError(CompilerError):
    """JSON 추출/스키마 검증 실패."""


class CompilerEmptyResultError(CompilerError):
    """빈 응답/의미 없는 결과."""


class CompilerProviderUnavailableError(CompilerError):
    """provider 설정 누락 등."""


__all__ = [
    "CompilerError",
    "CompilerConnectionError",
    "CompilerTimeoutError",
    "CompilerAuthError",
    "CompilerServerError",
    "CompilerParseError",
    "CompilerEmptyResultError",
    "CompilerProviderUnavailableError",
]
