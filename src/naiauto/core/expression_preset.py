"""표현(표정) 프리셋 — NAIA2.0의 expression_preset_service.py 이식.

`expression_tags.json`의 그룹/수식어 데이터를 사용해 표정 조합을 제공한다.

사용 예:
    preset = ExpressionPreset()
    preset.load()
    groups = preset.available_groups()
    tags = preset.get_group_tags("smile")
"""

from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path

from ..resources.tag_data_downloader import bundled_taglist_dir

logger = logging.getLogger(__name__)

# NovelAI 표정 수식어 (NAIA2.0과 동일)
EXPR_MODIFIERS: set[str] = {
    "blush", "light blush", "blush stickers", "nose blush",
    "open mouth", "closed mouth", "closed eyes",
    "one eye closed", "half-closed eyes", "raised eyebrows",
}


@dataclass(frozen=True)
class ExpressionGroup:
    key: str
    label: str
    tags: frozenset[str]


class ExpressionPreset:
    """expression_tags.json 기반 표정 프리셋."""

    def __init__(self, taglist_dir: Path | None = None):
        self._dir = taglist_dir or bundled_taglist_dir()
        self._groups: dict[str, ExpressionGroup] = {}
        self._modifiers: list[str] = []
        self._enabled = False

    def load(self) -> bool:
        path = self._dir / "expression_tags.json"
        if not path.is_file():
            logger.warning("Expression tags file not found: %s", path)
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._modifiers = data.get("modifiers", [])

            builtin_groups = {
                "tears": "눈물", "angry": "분노", "shy": "수줄음",
                "surprise": "놀람", "displeased": "불쾌", "grin": "비웃음",
                "smile": "미소", "stoic": "무표정", "physical": "신체",
                "special": "특수",
            }
            for group_key, group_tags in data.get("groups", {}).items():
                label = builtin_groups.get(group_key, group_key)
                self._groups[group_key] = ExpressionGroup(
                    key=group_key, label=label, tags=frozenset(group_tags),
                )
            self._enabled = True
            logger.info("Loaded %d expression groups", len(self._groups))
            return True
        except Exception as exc:
            logger.warning("Failed to load expression tags: %s", exc)
            return False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def available_groups(self) -> list[ExpressionGroup]:
        return list(self._groups.values())

    def get_group_tags(self, group_key: str) -> list[str]:
        group = self._groups.get(group_key)
        return list(group.tags) if group else []

    def get_modifiers(self) -> list[str]:
        return list(self._modifiers)

    def classify_combo(self, combo: str) -> str:
        """표정 조합 문자열 → 분류 키 반환 ('base' / group_key / 'other')."""
        tags = {t.strip() for t in combo.split(",") if t.strip()}
        core = tags - EXPR_MODIFIERS
        if not core:
            return "base"
        for group in self._groups.values():
            if core & group.tags:
                return group.key
        return "other"

    def random_combo(self) -> list[str]:
        """랜덤 표정 조합 생성."""
        tags: list[str] = []
        # 수식어 0~2개
        if self._modifiers and random.random() < 0.6:
            tags.extend(random.sample(self._modifiers, min(random.randint(1, 2), len(self._modifiers))))
        # 그룹 태그 1개
        if self._groups:
            group = random.choice(list(self._groups.values()))
            if group.tags:
                tags.append(random.choice(list(group.tags)))
        return tags


__all__ = ["ExpressionPreset", "ExpressionGroup", "EXPR_MODIFIERS"]
