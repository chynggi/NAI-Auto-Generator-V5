"""이미지 생성 백엔드의 공통 계약.

``GenerationService``는 이미 클라이언트를 주입받고, 실질 인터페이스가
``generate(req) -> GenerationResult`` 하나뿐이다. 그 자리를 그대로 백엔드
경계로 쓴다 — NovelAI(``api.client.NAIClient``)와 로컬 ComfyUI가 같은 모양이다.

능력 플래그는 **선언하지 않아도 되도록** 설계했다. ``backend_supports_credit``이
``getattr`` 기본값 True를 쓰므로 기존 ``NAIClient``를 고치지 않아도 프로토콜을
만족한다 — 크레딧을 쓰지 않는 쪽(로컬)이 명시적으로 False를 선언한다.

Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from naiauto.core.api.models import GenerationRequest, GenerationResult

__all__ = ["ImageBackend", "backend_supports_credit"]


@runtime_checkable
class ImageBackend(Protocol):
    """이미지 1장을 만드는 백엔드."""

    def generate(self, req: GenerationRequest) -> GenerationResult:
        """요청 1건 → 이미지 바이트. 실패는 예외로 알린다."""
        ...


def backend_supports_credit(backend: object) -> bool:
    """백엔드가 크레딧/Anlas 조회를 지원하는가.

    선언하지 않은 백엔드는 지원하는 것으로 본다 — 기존 ``NAIClient``가
    그 경우이고, 새로 만드는 로컬 백엔드만 False를 명시한다.
    """
    return bool(getattr(backend, "supports_credit", True))
