"""슬롯 기반 의상 프리셋 — NAIA2.0의 clothes_preset_service.py 이식.

`clothing_regions.json`과 `taglist/clothing_event.json`을 사용하여
슬롯별(HEAD_NECK_FACE/UPPER_BODY/WAIST_HIP/ARMS_HANDS/LEGS_FEET/STYLE)
의상 조합을 제공한다.

사용 예:
    preset = ClothesPreset()
    preset.load()
    slots = preset.available_slots()
    items = preset.get_slot_items("UPPER_BODY")
    combo = preset.build_combo({"UPPER_BODY": "shirt", "LEGS_FEET": "skirt"})
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

from ..resources.tag_data_downloader import bundled_taglist_dir, bundled_tags_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

SLOT_IDS = (
    "HEAD_NECK_FACE",
    "UPPER_BODY",
    "WAIST_HIP",
    "ARMS_HANDS",
    "LEGS_FEET",
    "STYLE",
)

SLOT_LABELS = {
    "HEAD_NECK_FACE": "Head / Neck / Face",
    "UPPER_BODY": "Upper Body",
    "WAIST_HIP": "Waist / Hip",
    "ARMS_HANDS": "Arms / Hands",
    "LEGS_FEET": "Legs / Feet",
    "STYLE": "Style / Overlay",
}

DEFAULT_SLOT = "UPPER_BODY"


# ---------------------------------------------------------------------------
# ClothesPreset
# ---------------------------------------------------------------------------


class ClothesPreset:
    """슬롯 기반 의상 조합 프리셋 데이터.

    ``clothing_regions.json``의 region 분류와 ``clothes_list.txt``의
    의류 태그를 결합해 슬롯별 의류 아이템을 제공한다.
    """

    def __init__(self, taglist_dir: Path | None = None):
        self._taglist_dir = taglist_dir or bundled_taglist_dir()
        self._tags_dir = bundled_tags_dir()

        self._slot_items: dict[str, list[dict[str, Any]]] = {}
        self._tag_to_slot: dict[str, str] = {}
        self._clothes_list: list[str] = []
        self._enabled = False

    def load(self) -> bool:
        """모든 의상 프리셋 데이터 로드."""
        self._load_clothes_list()
        self._build_slot_index()
        self._enabled = bool(self._slot_items)
        return self._enabled

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def available_slots(self) -> list[str]:
        """사용 가능한 슬롯 ID 목록."""
        return [s for s in SLOT_IDS if self._slot_items.get(s)]

    def get_slot_items(self, slot: str) -> list[dict[str, Any]]:
        """특정 슬롯의 의류 아이템 목록."""
        return list(self._slot_items.get(slot, []))

    def get_slot_for_tag(self, tag: str) -> str | None:
        """태그가 속한 슬롯 반환."""
        return self._tag_to_slot.get(tag)

    def build_combo(self, selections: dict[str, str]) -> list[str]:
        """슬롯별 선택 → 태그 목록."""
        tags: list[str] = []
        for _slot, tag in selections.items():
            if tag and tag not in tags:
                tags.append(tag)
        return tags

    def random_combo(
        self,
        slots: list[str] | None = None,
        count: int = 1,
    ) -> list[list[str]]:
        """랜덤 의상 조합 생성."""
        target_slots = slots or self.available_slots()
        results: list[list[str]] = []
        for _ in range(count):
            combo: list[str] = []
            for slot in target_slots:
                items = self._slot_items.get(slot, [])
                if items:
                    chosen = random.choice(items)
                    tag = chosen.get("tag", "") if isinstance(chosen, dict) else str(chosen)
                    if tag and tag not in combo:
                        combo.append(tag)
            results.append(combo)
        return results

    def suggest_combos(
        self,
        anchor_tag: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """특정 태그와 어울리는 의상 조합 추천."""
        slot = self._tag_to_slot.get(anchor_tag)
        if not slot:
            return []
        SLOT_IDS.index(slot) if slot in SLOT_IDS else -1
        suggestions: list[dict[str, Any]] = []

        # 같은 슬롯의 다른 아이템
        same_slot = [item for item in self._slot_items.get(slot, [])
                     if (isinstance(item, dict) and item.get("tag") != anchor_tag)
                     or (isinstance(item, str) and item != anchor_tag)]
        for item in same_slot[:limit]:
            tag = item["tag"] if isinstance(item, dict) else str(item)
            suggestions.append({"tag": tag, "slot": slot, "relation": "alternative"})

        # 다른 슬롯의 아이템과 조합
        for other_slot in SLOT_IDS:
            if other_slot == slot or other_slot not in self._slot_items:
                continue
            for item in self._slot_items[other_slot][:3]:
                tag = item["tag"] if isinstance(item, dict) else str(item)
                suggestions.append({"tag": tag, "slot": other_slot, "relation": "complement"})
                if len(suggestions) >= limit * 2:
                    break
            if len(suggestions) >= limit * 2:
                break

        return suggestions[:limit]

    # -- 내부 로드 ----------------------------------------------------------

    def _load_clothes_list(self):
        path = self._tags_dir / "clothes_list.txt"
        if not path.is_file():
            path = self._taglist_dir.parent / "clothes_list.txt"
        if path.is_file():
            self._clothes_list = [
                line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
            ]
            logger.info("Loaded %d clothes tags", len(self._clothes_list))

    def _build_slot_index(self):
        # clothing_regions.json 로드
        region_path = self._taglist_dir / "clothing_regions.json"
        if region_path.is_file():
            try:
                data = json.loads(region_path.read_text(encoding="utf-8"))
                regions = data.get("regions", {})
                for slot, tags in regions.items():
                    items: list[dict[str, Any]] = []
                    for tag in tags:
                        items.append({"tag": tag, "slot": slot})
                        self._tag_to_slot[tag] = slot
                    # 먼저 region 태그를 slot에 채운다
                    existing = self._slot_items.get(slot, [])
                    existing_tags = {isinstance(e, dict) and e["tag"] or e for e in existing}
                    for item in items:
                        if item["tag"] not in existing_tags:
                            existing.append(item)
                            existing_tags.add(item["tag"])
                    self._slot_items[slot] = existing
                logger.info("Built slot index from %d regions", len(regions))
            except Exception as exc:
                logger.warning("Failed to build slot index: %s", exc)

        # clothes_list.txt 태그도 slot 찾아서 추가
        for tag in self._clothes_list:
            if tag in self._tag_to_slot:
                continue
            # 추정: 단어 기반 region 매칭
            assigned = False
            for slot, items in self._slot_items.items():
                for item in items:
                    known_tag = item["tag"] if isinstance(item, dict) else str(item)
                    if known_tag and known_tag in tag or tag in known_tag:
                        self._tag_to_slot[tag] = slot
                        self._slot_items[slot].append({"tag": tag, "slot": slot, "inferred": True})
                        assigned = True
                        break
                if assigned:
                    break
            if not assigned:
                self._slot_items.setdefault("STYLE", []).append({"tag": tag, "slot": "STYLE", "inferred": True})
                self._tag_to_slot[tag] = "STYLE"


__all__ = [
    "ClothesPreset",
    "SLOT_IDS",
    "SLOT_LABELS",
]
