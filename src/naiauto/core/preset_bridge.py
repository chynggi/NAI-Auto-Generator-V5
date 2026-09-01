"""``preset:`` 프롬프트 토큰 해석 브릿지.

NAIA2.0의 ``preset_input_bridge.py`` 이식. 프롬프트 내 ``preset:``
토큰을 의상/표정/이벤트 프리셋으로 확장한다.

문법:
    preset:clothes/UPPER_BODY/shirt
    preset:expressions/tears
    preset:events/s/g/1girl_solo/...

사용 예:
    bridge = PresetInputBridge()
    bridge.load()
    result = bridge.resolve_token("preset:clothes/UPPER_BODY/shirt")
"""

from __future__ import annotations

import logging
import re
from typing import Any

from .clothes_preset import ClothesPreset
from .expression_preset import ExpressionPreset

logger = logging.getLogger(__name__)

PRESET_PREFIX = "preset:"

PRESET_AXES: tuple[dict[str, str], ...] = (
    {"id": "events", "label": "Events", "desc": "Event Preset taxonomy"},
    {"id": "clothes", "label": "Clothes", "desc": "Clothes Preset combos"},
    {"id": "expressions", "label": "Expressions", "desc": "Expression Preset catalog"},
)

CLOTHES_SLOT_IDS: frozenset = frozenset({
    "HEAD_NECK_FACE", "UPPER_BODY", "WAIST_HIP",
    "ARMS_HANDS", "LEGS_FEET", "STYLE",
})

_PRESET_PATH_RE = re.compile(
    rf"^{PRESET_PREFIX}(?P<axis>[A-Za-z_]+)(?:/(?P<path>.+))?$"
)


class PresetInputBridge:
    """프리셋 토큰 해석기.

    ``preset:clothes/UPPER_BODY`` 등의 토큰을 실제 태그로 변환한다.
    """

    def __init__(
        self,
        clothes_preset: ClothesPreset | None = None,
        expression_preset: ExpressionPreset | None = None,
    ):
        self._clothes = clothes_preset or ClothesPreset()
        self._expression = expression_preset or ExpressionPreset()
        self._enabled = False

    def load(self) -> bool:
        ok_c = self._clothes.load()
        ok_e = self._expression.load()
        self._enabled = ok_c or ok_e
        return self._enabled

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def resolve_token(self, token: str) -> list[str]:
        """프리셋 토큰을 태그 목록으로 변환.

        Args:
            token: ``preset:...`` 형식 토큰

        Returns:
            변환된 태그 목록. 인식 불가면 빈 리스트.
        """
        if not token.startswith(PRESET_PREFIX):
            return []

        match = _PRESET_PATH_RE.match(token)
        if not match:
            return []

        axis = match.group("axis")
        path = match.group("path") or ""

        if axis == "clothes":
            return self._resolve_clothes(path)
        elif axis == "expressions":
            return self._resolve_expression(path)
        else:
            logger.debug("Unknown preset axis: %s", axis)
            return []

    def resolve_prompt(self, prompt: str) -> str:
        """프롬프트 내 모든 ``preset:`` 토큰을 치환."""
        if PRESET_PREFIX not in prompt:
            return prompt

        def _replace(m: re.Match) -> str:
            token = m.group(0).strip().rstrip(",")
            tags = self.resolve_token(token)
            return ", ".join(tags) if tags else token

        pattern = re.compile(rf"{PRESET_PREFIX}[A-Za-z_/]+")
        return pattern.sub(_replace, prompt)

    def suggest_completions(self, prefix: str) -> list[dict[str, Any]]:
        """부분 입력에 대한 자동완성 제안."""
        if not prefix.startswith(PRESET_PREFIX):
            return []

        parts = prefix[len(PRESET_PREFIX):].split("/")
        suggestions: list[dict[str, Any]] = []

        if len(parts) == 1 and parts[0]:
            # 축 자동완성
            axis_part = parts[0].lower()
            for axis in PRESET_AXES:
                if axis["id"].startswith(axis_part):
                    suggestions.append({
                        "text": f"{PRESET_PREFIX}{axis['id']}/",
                        "label": axis["label"],
                        "desc": axis["desc"],
                    })

        elif len(parts) == 2:
            axis, sub = parts[0], parts[1]
            if axis == "clothes":
                for slot in CLOTHES_SLOT_IDS:
                    if slot.startswith(sub.upper()):
                        suggestions.append({
                            "text": f"{PRESET_PREFIX}{axis}/{slot}/",
                            "label": slot,
                        })
            elif axis == "expressions":
                if self._expression.is_enabled:
                    for group in self._expression.available_groups():
                        if group.key.startswith(sub):
                            suggestions.append({
                                "text": f"{PRESET_PREFIX}{axis}/{group.key}/",
                                "label": group.label,
                            })

        elif len(parts) == 3:
            axis, sub2, query = parts[0], parts[1], parts[2]
            if axis == "clothes" and sub2.upper() in CLOTHES_SLOT_IDS:
                if self._clothes.is_enabled:
                    for item in self._clothes.get_slot_items(sub2.upper()):
                        tag = item["tag"] if isinstance(item, dict) else str(item)
                        if query.lower() in tag.lower():
                            suggestions.append({
                                "text": f"{PRESET_PREFIX}{axis}/{sub2}/{tag}",
                                "label": tag,
                            })

        return suggestions

    # -- 내부 해석 ----------------------------------------------------------

    def _resolve_clothes(self, path: str) -> list[str]:
        parts = path.split("/")
        if len(parts) < 2:
            return []
        slot = parts[0].upper()
        if slot not in CLOTHES_SLOT_IDS:
            return []
        tag_name = parts[1]
        # 슬롯에서 태그 찾기
        if self._clothes.is_enabled:
            for item in self._clothes.get_slot_items(slot):
                item_tag = item["tag"] if isinstance(item, dict) else str(item)
                if item_tag == tag_name:
                    return [item_tag]
            # 부분 매칭
            for item in self._clothes.get_slot_items(slot):
                item_tag = item["tag"] if isinstance(item, dict) else str(item)
                if tag_name.lower() in item_tag.lower():
                    return [item_tag]
        return [tag_name]  # fallback: 토큰 그대로

    def _resolve_expression(self, path: str) -> list[str]:
        parts = path.split("/")
        group_key = parts[0] if parts else ""
        if self._expression.is_enabled and group_key:
            tags = self._expression.get_group_tags(group_key)
            if tags:
                return tags
        return []


__all__ = ["PresetInputBridge", "PRESET_PREFIX", "CLOTHES_SLOT_IDS"]
