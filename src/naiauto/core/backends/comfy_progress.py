"""ComfyUI WebSocket 메시지 해석.

메시지 파싱과 소켓 입출력을 나눈다 — 파싱은 순수 함수라 실제 서버 없이
테스트할 수 있고, 실제로 버전차가 드러나는 곳이 여기다.

v0.34는 노드별 ``progress_state``를 보내고, 구버전은 ``progress``를 보낸다.
둘 다 받는다. ``executed``는 출력(이미지 목록)을 직접 실어 오므로 ``/history``
폴링이 필요 없다.

Qt 의존성 없음.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = ["Progress", "Executed", "ExecutionFailed", "parse_message"]


@dataclass(frozen=True)
class Progress:
    """샘플링 진행률."""

    value: int
    max_value: int


@dataclass(frozen=True)
class Executed:
    """노드가 출력을 냈다."""

    node: str
    images: tuple[dict, ...]


@dataclass(frozen=True)
class ExecutionFailed:
    """실행 중 노드가 예외를 냈다."""

    message: str
    node_id: str = ""
    node_type: str = ""


def parse_message(raw: object, prompt_id: str) -> Progress | Executed | ExecutionFailed | None:
    """WS 프레임 하나 → 이벤트. 관심 없거나 남의 작업이면 None.

    바이너리 프레임(미리보기 이미지)과 모양이 어긋난 JSON은 조용히 무시한다 —
    서버 버전이 달라도 앱이 죽으면 안 된다.
    """
    if isinstance(raw, (bytes, bytearray)):
        return None  # 바이너리 프리뷰 프레임 — 이번 범위에서는 쓰지 않는다
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    # prompt_id가 있으면 우리 작업인지 확인한다. 없는 메시지는 통과시킨다
    # (일부 메시지는 id를 싣지 않는다).
    incoming = data.get("prompt_id")
    if incoming is not None and str(incoming) != prompt_id:
        return None

    kind = payload.get("type")
    if kind == "progress_state":
        nodes = data.get("nodes")
        if not isinstance(nodes, dict):
            return None
        for state in nodes.values():
            if not isinstance(state, dict):
                continue
            value, maximum = state.get("value"), state.get("max")
            if isinstance(value, (int, float)) and isinstance(maximum, (int, float)) and maximum:
                return Progress(value=int(value), max_value=int(maximum))
        return None
    if kind == "progress":
        value, maximum = data.get("value"), data.get("max")
        if isinstance(value, (int, float)) and isinstance(maximum, (int, float)) and maximum:
            return Progress(value=int(value), max_value=int(maximum))
        return None
    if kind == "executed":
        output = data.get("output")
        images = output.get("images") if isinstance(output, dict) else None
        if not isinstance(images, list) or not images:
            return None
        return Executed(
            node=str(data.get("node", "")),
            images=tuple(i for i in images if isinstance(i, dict)),
        )
    if kind == "execution_error":
        return ExecutionFailed(
            message=str(data.get("exception_message", "execution failed")),
            node_id=str(data.get("node_id", "")),
            node_type=str(data.get("node_type", "")),
        )
    return None
