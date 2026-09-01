"""프롬프트 엔지니어링 — 프리/포스트 프로세싱, 태그 필터링 통합.

NAIA2.0의 ``prompt_engineering_settings.py``와
``headless_prompt_engineering_service.py``를 통합·이식했다.

프롬프트 처리 파이프라인:
  1. Pre-processing (접두사/접미사 태그 삽입)
  2. 태그 필터링 (FilterDataManager + apply_tag_filters)
  3. 프리셋 토큰 해석 (PresetInputBridge)
  4. Post-processing (최종 포맷팅)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .filter_manager import FilterDataManager, apply_tag_filters
from .preset_bridge import PresetInputBridge

logger = logging.getLogger(__name__)


@dataclass
class PromptEngineeringSettings:
    """프롬프트 엔지니어링 설정."""

    # Pre/post prompt
    pre_prompt: str = ""
    post_prompt: str = ""

    # Auto hide
    auto_hide: list[str] = field(default_factory=list)

    # 필터 체크박스 옵션
    remove_character_features: bool = False
    remove_clothes: bool = True
    remove_clothing_event: bool = False
    remove_color: bool = True
    remove_location_and_background_color: bool = True
    remove_expression: bool = True
    remove_pose_action: bool = False
    remove_meta_tags: bool = True
    remove_object_tags: bool = False
    remove_noise_tags: bool = False

    # 카테고리 오버라이드
    category_overrides: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    def to_checkbox_options(self) -> dict[str, bool]:
        return {
            "remove_character_features": self.remove_character_features,
            "remove_clothes": self.remove_clothes,
            "remove_clothing_event": self.remove_clothing_event,
            "remove_color": self.remove_color,
            "remove_location_and_background_color": self.remove_location_and_background_color,
            "remove_expression": self.remove_expression,
            "remove_pose_action": self.remove_pose_action,
            "remove_meta_tags": self.remove_meta_tags,
            "remove_object_tags": self.remove_object_tags,
            "remove_noise_tags": self.remove_noise_tags,
        }


@dataclass
class ProcessedPrompt:
    """프롬프트 처리 결과."""
    tags: list[str]
    removed: list[str]
    filter_log: list[dict[str, Any]]
    pre_prompt: str
    post_prompt: str
    final_prompt: str
    metadata: dict[str, Any] = field(default_factory=dict)


class PromptEngineeringEngine:
    """프롬프트 엔지니어링 엔진.

    필터링, 프리셋 해석, pre/post-prompt 처리를 통합 제공한다.
    """

    def __init__(
        self,
        filter_manager: FilterDataManager | None = None,
        preset_bridge: PresetInputBridge | None = None,
    ):
        self._filter_manager = filter_manager or FilterDataManager()
        self._preset_bridge = preset_bridge or PresetInputBridge()

    def load(self) -> bool:
        ok_f = self._filter_manager.load()
        ok_p = self._preset_bridge.load()
        return ok_f or ok_p

    def process(
        self,
        tags: list[str],
        settings: PromptEngineeringSettings | None = None,
    ) -> ProcessedPrompt:
        """전체 프롬프트 처리 파이프라인 실행.

        1. 프리셋 토큰 해석 (preset:...)
        2. Pre-prompt 태그 추가
        3. 태그 필터링
        4. Post-prompt 태그 추가
        5. 최종 문자열 조립
        """
        settings = settings or PromptEngineeringSettings()
        main_tags = list(tags)
        removed_tags: list[str] = []

        # 1. 프리셋 토큰 해석
        if self._preset_bridge.is_enabled:
            resolved: list[str] = []
            for tag in main_tags:
                if tag.startswith("preset:"):
                    resolved_tags = self._preset_bridge.resolve_token(tag)
                    resolved.extend(resolved_tags)
                else:
                    resolved.append(tag)
            main_tags = resolved

        # 2. Pre-prompt
        pre_tags = self._parse_pre_prompt(settings.pre_prompt)
        main_tags = pre_tags + main_tags

        # 3. 태그 필터링
        if self._filter_manager.is_enabled:
            opts = settings.to_checkbox_options()
            result = apply_tag_filters(
                main_tags,
                removed_tags,
                opts,
                settings.auto_hide,
                self._filter_manager,
                category_overrides=settings.category_overrides,
            )
        else:
            result = {"filter_log": []}

        # 4. Post-prompt
        post_tags = self._parse_pre_prompt(settings.post_prompt)
        main_tags.extend(post_tags)

        # 5. 최종 조립
        final_prompt = ", ".join(main_tags)

        return ProcessedPrompt(
            tags=main_tags,
            removed=removed_tags,
            filter_log=result.get("filter_log", []),
            pre_prompt=settings.pre_prompt,
            post_prompt=settings.post_prompt,
            final_prompt=final_prompt,
            metadata={
                "removed_clothes_by_region": result.get("removed_clothes_by_region"),
                "removed_clothing_events_by_category": result.get("removed_clothing_events_by_category"),
            },
        )

    @staticmethod
    def _parse_pre_prompt(text: str) -> list[str]:
        """프리/포스트 프롬프트 텍스트 → 태그 리스트."""
        if not text or not text.strip():
            return []
        return [tag.strip() for tag in text.split(",") if tag.strip()]


# ---------------------------------------------------------------------------
# 편의 함수
# ---------------------------------------------------------------------------


def process_prompt_tags(
    tags: list[str],
    *,
    remove_clothes: bool = True,
    remove_color: bool = True,
    remove_location: bool = True,
    remove_expression: bool = True,
    remove_meta: bool = True,
) -> list[str]:
    """단일 호출 태그 필터링 (빠른 사용)."""
    fm = FilterDataManager()
    fm.load()
    main = list(tags)
    removed: list[str] = []
    opts = {
        "remove_character_features": False,
        "remove_clothes": remove_clothes,
        "remove_clothing_event": False,
        "remove_color": remove_color,
        "remove_location_and_background_color": remove_location,
        "remove_expression": remove_expression,
        "remove_pose_action": False,
        "remove_meta_tags": remove_meta,
        "remove_object_tags": False,
        "remove_noise_tags": False,
    }
    apply_tag_filters(main, removed, opts, [], fm)
    return main


__all__ = [
    "PromptEngineeringEngine",
    "PromptEngineeringSettings",
    "ProcessedPrompt",
    "process_prompt_tags",
]
