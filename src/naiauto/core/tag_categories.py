"""분류된 태그 목록 — NAIA2.0 taglist/*.json 을 로드하여 카테고리별로 제공한다.

V5는 이 데이터를 프롬프트 편집기의 태그 제안/카테고리 브라우징에 활용한다.
데이터는 NAIA2.0 저장소에서 가져온 것으로, HuggingFace에서도 동일한 데이터를
배포한다:

    https://huggingface.co/baqu2213/PoemForSmallFThings

지원하는 태그 분류:
  - clothing_event  — 의류 관련 이벤트(조정/착용/탈의 등)
  - clothing_regions — 의류 태그를 신체 부위(region)별로 분류
  - expression       — 표정/감정 태그
  - location         — 장소/배경 태그
  - meta             — 메타/스타일 태그 (아트 스타일, 매체 등)
  - object           — 사물 태그 (무기, 음식, 동물 등)
  - pose_action     — 포즈/행동 태그
  - style_meta      — 이미지 생성에 유의미한 메타/스타일/효과 태그
  - unique_tags     — 태그-게시물수 Dict (``{tag: post_count}``)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..resources.tag_data_downloader import bundled_taglist_dir

logger = logging.getLogger(__name__)


class TagCategories:
    """taglist/*.JSON 으로부터 분류된 태그 목록을 제공한다.

    사용 예:
        cats = TagCategories()
        cats.load()
        expressions = cats.get_category("expression_tags")
        print(f"{len(expressions)}개 표정 태그 로드됨")
    """

    def __init__(self, taglist_dir: Path | None = None) -> None:
        self._dir = taglist_dir or bundled_taglist_dir()
        self._data: dict[str, Any] = {}
        self._enabled = False

    def load(self) -> bool:
        """디렉터리 내 모든 *.json을 읽어들인다."""
        self._data = {}
        self._enabled = False

        if not self._dir.is_dir():
            logger.warning("Taglist directory not found: %s", self._dir)
            return False

        seen = 0
        for path in sorted(self._dir.glob("*.json")):
            try:
                raw = path.read_text(encoding="utf-8")
                self._data[path.stem] = json.loads(raw)
                seen += 1
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to load taglist %s: %s", path.name, exc)

        self._enabled = seen > 0
        logger.info("Loaded %d taglist files from %s", seen, self._dir)
        return self._enabled

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def category_names(self) -> list[str]:
        """로드된 카테고리 이름 목록."""
        return sorted(self._data.keys())

    def get_raw(self, name: str) -> Any:
        """원본 JSON 데이터를 반환한다 (카테고리 구조에 따라 다름)."""
        return self._data.get(name)

    def get_category(self, name: str) -> list[str]:
        """카테고리에서 모든 태그 목록을 추출해 반환한다.

        각 JSON 파일의 구조에 따라 다른 키에서 태그를 수집한다:
        - unique_tags → dict 키
        - expression_tags → groups 아래 모든 태그 + modifiers
        - clothing_event → categories 아래 각 항목의 tag 필드
        - clothing_regions → regions 아래 모든 값
        - pose_action_tags → categories 아래 모든 값
        - location_tags, meta_tags, object_tags → tags 배열
        - style_meta_tags → categories 아래 각 그룹의 tags 배열
        """
        data = self._data.get(name)
        if data is None:
            return []

        # 간단한 배열 → 그대로 반환
        if isinstance(data, list):
            return [str(t) for t in data]

        # {tag: count, ...} → 키 목록
        if isinstance(data, dict):
            collected: list[str] = []

            # 여러 키에서 태그를 수집한다 (expression_tags는 tags + modifiers + groups)
            if "tags" in data and isinstance(data["tags"], list):
                collected.extend(str(t) for t in data["tags"])
            if "modifiers" in data and isinstance(data["modifiers"], list):
                collected.extend(str(t) for t in data["modifiers"])
            if "groups" in data:
                collected.extend(self._extract_from_groups(data["groups"]))
            if "categories" in data:
                collected.extend(self._extract_from_categories(data["categories"]))
            if "regions" in data:
                collected.extend(self._extract_from_regions(data["regions"]))

            if collected:
                return collected

            # 평탄한 {tag: count} 객체
            keys = [k for k in data if k not in ("version", "description", "sources",
                                                  "note", "modifiers", "groups")]
            if keys and all(isinstance(data[k], (int, float)) for k in keys[:5]):
                return keys

        return []

    def get_tags_with_metadata(self, name: str) -> list[dict[str, Any]]:
        """의류 이벤트처럼 메타데이터가 있는 태그를 반환한다."""
        data = self._data.get(name)
        if not isinstance(data, dict):
            return []
        if "categories" in data:
            return self._extract_items_with_meta(data["categories"])
        return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_from_categories(categories: dict[str, Any]) -> list[str]:
        tags: list[str] = []
        for items in categories.values():
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        tag = item.get("tag")
                        if tag:
                            tags.append(str(tag))
                    elif isinstance(item, str):
                        tags.append(item)
            elif isinstance(items, dict):
                # style_meta_tags: 각 카테고리가 {"name": ..., "tags": [...]} 형태
                sub = items.get("tags")
                if isinstance(sub, list):
                    tags.extend(str(t) for t in sub)
        return tags

    @staticmethod
    def _extract_from_regions(regions: dict[str, Any]) -> list[str]:
        tags: list[str] = []
        for items in regions.values():
            if isinstance(items, list):
                tags.extend(str(t) for t in items)
        return tags

    @staticmethod
    def _extract_from_groups(groups: dict[str, Any]) -> list[str]:
        tags: list[str] = []
        for items in groups.values():
            if isinstance(items, list):
                tags.extend(str(t) for t in items)
        return tags

    @staticmethod
    def _extract_items_with_meta(categories: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for cat_name, entries in categories.items():
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        items.append({**entry, "category": cat_name})
        return items


__all__ = ["TagCategories"]
