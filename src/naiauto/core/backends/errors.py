"""ComfyUI 백엔드 오류 계층.

UI는 ``ComfyError`` 하나만 잡으면 되지만, 원인별로 다른 안내를 하려면 구분이
필요하다. 특히 ``ComfyPromptRejectedError``의 ``node_errors``는 서버가 주는
가장 정확한 진단(어느 노드의 어느 입력이 틀렸는지)이므로 뭉뚱그리지 않는다.

Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

__all__ = [
    "ComfyError",
    "ComfyConnectionError",
    "ComfyPromptRejectedError",
    "ComfyExecutionError",
    "ComfyTimeoutError",
    "ComfyTemplateError",
]


class ComfyError(Exception):
    """모든 ComfyUI 백엔드 오류의 베이스."""


class ComfyConnectionError(ComfyError):
    """서버에 붙지 못했다 (미실행이 가장 흔하다)."""


class ComfyPromptRejectedError(ComfyError):
    """``POST /prompt``가 400으로 거부했다.

    ``node_errors``는 서버가 알려준 노드별 문제다 — 모델 파일이 없거나 샘플러
    이름이 틀린 경우가 여기로 온다.
    """

    def __init__(self, message: str, node_errors: dict | None = None) -> None:
        super().__init__(message)
        self.node_errors = node_errors or {}


class ComfyExecutionError(ComfyError):
    """실행 중 노드가 예외를 냈다 (WS ``execution_error``)."""

    def __init__(
        self, message: str, node_id: str = "", node_type: str = ""
    ) -> None:
        super().__init__(f"{node_type or 'node'}: {message}" if node_type else message)
        self.node_id = node_id
        self.node_type = node_type


class ComfyTimeoutError(ComfyError):
    """정해진 시간 안에 결과가 오지 않았다."""


class ComfyTemplateError(ComfyError):
    """워크플로 템플릿이 잘못됐다 (슬롯 경로 없음, JSON 파손 등)."""
