"""이미지 생성 백엔드 (NovelAI / 로컬 ComfyUI).

Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

from naiauto.core.backends.base import ImageBackend, backend_supports_credit

__all__ = ["ImageBackend", "backend_supports_credit"]
