"""이미지 생성 백엔드 (NovelAI / 로컬 ComfyUI).

Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

from naiauto.core.backends.base import ImageBackend, backend_supports_credit
from naiauto.core.backends.comfy_objects import ObjectInfo, parse_object_info
from naiauto.core.backends.comfy_workflow import (
    LoraAssignment,
    WorkflowTemplate,
    build_graph,
    find_workflow,
    load_workflows,
)
from naiauto.core.backends.comfyui import ComfyUIBackend
from naiauto.core.backends.errors import ComfyError

__all__ = [
    "ImageBackend",
    "backend_supports_credit",
    "ComfyUIBackend",
    "ComfyError",
    "ObjectInfo",
    "parse_object_info",
    "WorkflowTemplate",
    "LoraAssignment",
    "load_workflows",
    "find_workflow",
    "build_graph",
]
