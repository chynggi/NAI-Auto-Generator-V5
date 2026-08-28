"""캐릭터 위치 힌트 → 정규화 좌표 추정.

LLM 파서가 내놓은 ``position_hint`` 문자열("left", "right bottom", "center")을
샷 구도 좌표 (center_x, center_y)로 결정적으로 변환한다. 핵심 포인트:
- 알 수 없는 토큰이 하나라도 있으면 추정을 포기하고 None (할루시네이션 방지)
- 절대 좌표는 스펙 §7의 X_HINTS/Y_HINTS 상수만 사용한다
- 미지정 축은 0.5 (중앙)로 기본 처리한다

좌표 추정만 담당하며, 최종 프롬프트 반영(center_x=None → 0.5 강제 등)은
하위 단계(merge)의 책임이다. core/ 모듈이므로 Qt 의존성이 없다.
"""

from __future__ import annotations

from dataclasses import replace

from naiauto.core.prompt.schema import CharacterPrompt

#: 수평 위치 힌트 토큰 → x 좌표 (0.0=왼쪽 끝, 1.0=오른쪽 끝).
X_HINTS: dict[str, float] = {
    "far_left": 0.15,
    "left": 0.30,
    "center": 0.50,
    "right": 0.70,
    "far_right": 0.85,
}

#: 수직 위치 힌트 토큰 → y 좌표 (0.0=위, 1.0=아래).
Y_HINTS: dict[str, float] = {
    "top": 0.30,
    "center": 0.50,
    "bottom": 0.70,
}

#: 미지정 축 기본값 — 구도상 수평/수직 모두 중앙.
_DEFAULT_XY: float = 0.5


def estimate_position(hint: str) -> tuple[float, float] | None:
    """힌트 문자열("left", "right bottom", "center") → (x, y).

    명확한 힌트만 좌표로: 알 수 없는 토큰이 있거나 힌트가 비면 None.
    y 미지정 시 0.5.

    예:
        "left" → (0.30, 0.50)
        "left bottom" → (0.30, 0.70)
        "left somewhere" → None (미지 토큰 "somewhere")
    """
    tokens = hint.split()
    if not tokens:
        return None
    x: float | None = None
    y: float | None = None
    for token in tokens:
        if token in X_HINTS:
            x = X_HINTS[token]
        elif token in Y_HINTS:
            y = Y_HINTS[token]
        else:
            return None
    return (x if x is not None else _DEFAULT_XY, y if y is not None else _DEFAULT_XY)


def estimate_positions(characters: tuple[CharacterPrompt, ...]) -> tuple[CharacterPrompt, ...]:
    """각 캐릭터의 center_x/center_y를 position_hint에서 계산해 새 튜플 반환.

    None이면 해당 캐릭터 좌표는 None 유지 (변이 없이 그대로 재사용).
    """
    out: list[CharacterPrompt] = []
    for char in characters:
        pos = estimate_position(char.position_hint)
        if pos is None:
            out.append(char)
        else:
            out.append(replace(char, center_x=pos[0], center_y=pos[1]))
    return tuple(out)


__all__ = ["X_HINTS", "Y_HINTS", "estimate_position", "estimate_positions"]
