"""카테고리별 태그 필터 관리자.

NAIA2.0의 ``filter_data_manager.py``와 ``tag_filter_helpers.py``를 V5 환경에
맞게 통합·이식했다. taglist/*.json 및 텍스트 필터 파일을 로드해 10라운드
태그 필터링 파이프라인을 제공한다.

처리 순서:
  1. Auto Hide (패턴 매칭 + 보호 키워드)
  2. 캐릭터 특징 제거
  3. 의류 제거 (+ region 추적)
  4. 의상 이벤트 제거 (+ category 추적)
  5. 색상 제거 (+ 예외 처리)
  6. 위치/배경 제거
  7. 표정 제거
  8. 포즈/동작 제거
  9. 메타 태그 제거
  10. 사물 태그 제거
  11. 노이즈 태그 제거 (저빈도)
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..resources.tag_data_downloader import bundled_taglist_dir, bundled_tags_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 색상 필터링 예외 패턴
# ---------------------------------------------------------------------------

COLOR_EXCEPTION_PREFIXES = [
    "covered", "shared", "armored", "layered", "feathered",
    "colored", "multicolored", "checkered", "mirrored", "captured",
    "scared", "striped",
]

COLOR_EXCEPTION_CONTAINS = [
    "palette", "impaled", "blueberry", "blueprint",
    "goldfish", "marigold", "strawberry", "pinky out", "footprints",
    "darkness", "dark aura", "rainbow", " fire", " theme",
    " border", " outline", " gradient", "scooping",
]

COLOR_EXCEPTION_EXACT = [
    "turn pale", "checkered", "striped", "rainbow", "darkness",
]

# ---------------------------------------------------------------------------
# Auto Hide 태그 변환 맵
# ---------------------------------------------------------------------------

_TAG_CONVERSION_MAP = {
    "v": "peace sign",
    "double v": "double peace",
    "|_|": "bar eyes",
    "\\||/": "open \\m/",
    ":|": "neutral face",
    ";|": "neutral face",
    "eyepatch bikini": "square bikini",
    "tachi-e": "character image",
}
_REVERSED_CONVERSION_MAP = {v: k for k, v in _TAG_CONVERSION_MAP.items()}

# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _norm_tag(tag: Any) -> str:
    return str(tag or "").strip().lower()


def _pattern_norm(value: Any) -> str:
    return str(value or "").lower()


def compile_hide_pattern(item: str) -> tuple[bool, str] | None:
    """Auto-Hide 패턴 문법을 (is_prefix_match: bool, needle: str)로 컴파일.

    반환 None = 일반 문자열(정확 일치). 아니면 predicate로 사용.
    - ``_text`` 또는 ``__text``: 앞에 공백이 오는 단어 경계 매치 (접두사)
    - ``text_`` 또는 ``text__`` 또는 ``_text_``: 포함 매치
    - 밑줄 없음: None
    - 중간 밑줄은 공백으로 치환
    """
    if not isinstance(item, str) or not item:
        return None
    stripped_lead = item.lstrip("_")
    lead = len(item) - len(stripped_lead)
    core = stripped_lead.rstrip("_")
    trail = len(stripped_lead) - len(core)
    if lead == 0 and trail == 0:
        return None
    if not core.strip():
        return None
    needle = core.replace("_", " ")
    is_prefix = lead > 0 and trail == 0
    if is_prefix:
        needle = " " + needle
    return (is_prefix, needle)


def _is_color_exception(tag: str) -> bool:
    tag_lower = tag.lower()
    if tag_lower in COLOR_EXCEPTION_EXACT:
        return True
    for prefix in COLOR_EXCEPTION_PREFIXES:
        if tag_lower.startswith(prefix):
            return True
    for pattern in COLOR_EXCEPTION_CONTAINS:
        if pattern in tag_lower:
            return True
    return False


def _parse_override_terms(items: list[str]) -> tuple[set[str], list[tuple[bool, str]]]:
    """오버라이드 항목을 (exact_set, pattern_predicates)로 분리."""
    exact: set[str] = set()
    preds: list[tuple[bool, str]] = []
    for raw in items or []:
        text = str(raw or "").strip()
        if not text:
            continue
        pred = compile_hide_pattern(text)
        if pred is not None:
            preds.append(pred)
        else:
            exact.add(_norm_tag(text))
    return exact, preds


def _matches_terms(keyword: str, terms: tuple[set[str], list[tuple[bool, str]]]) -> bool:
    exact, preds = terms
    if _norm_tag(keyword) in exact:
        return True
    for is_prefix, needle in preds:
        if is_prefix:
            if needle in (" " + keyword):
                return True
        else:
            if needle in keyword:
                return True
    return False


def _terms_empty(terms: tuple[set[str], list[tuple[bool, str]]]) -> bool:
    exact, preds = terms
    return not exact and not preds


def _override_sets(category_overrides: dict | None, option_key: str):
    entry = (category_overrides or {}).get(option_key) if isinstance(category_overrides, dict) else None
    if not isinstance(entry, dict):
        return (set(), []), (set(), [])
    exclude = _parse_override_terms(entry.get("exclude"))
    include = _parse_override_terms(entry.get("include"))
    return exclude, include


def _apply_round_overrides(
    temp: list[str],
    main_tags: list[str],
    exclude: tuple[set[str], list[tuple[bool, str]]],
    include: tuple[set[str], list[tuple[bool, str]]],
) -> list[str]:
    if _terms_empty(exclude) and _terms_empty(include):
        return temp
    result = [k for k in temp if not _matches_terms(k, exclude)]
    if not _terms_empty(include):
        scheduled = {_norm_tag(k) for k in result}
        for keyword in main_tags:
            nk = _norm_tag(keyword)
            if nk in scheduled:
                continue
            if _matches_terms(keyword, exclude):
                continue
            if _matches_terms(keyword, include):
                result.append(keyword)
                scheduled.add(nk)
    return result


# ---------------------------------------------------------------------------
# FilterDataManager
# ---------------------------------------------------------------------------


class FilterDataManager:
    """태그 필터 데이터 로더 및 관리자.

    ``data/`` 디렉터리의 텍스트 파일 + taglist/*.json 을 로드하여
    카테고리별 태그 세트를 제공한다.
    """

    def __init__(
        self,
        data_dir: str | Path = "",
        taglist_dir: Path | None = None,
    ):
        self._data_dir = Path(data_dir) if data_dir else bundled_tags_dir()
        self._taglist_dir = taglist_dir or bundled_taglist_dir()

        self.clothes_list: list[str] = []
        self.color_list: list[str] = []
        self.characteristic_list: list[str] = []

        self._location_set: set[str] = set()
        self._expression_set: set[str] = set()
        self._pose_action_set: set[str] = set()
        self._meta_set: set[str] = set()
        self._object_set: set[str] = set()
        self._clothing_region_map: dict[str, list[str]] = {}
        self._clothing_tag_to_region: dict[str, str] = {}
        self._unassigned_region: str = "UNASSIGNED"

        self._clothing_event_set: set[str] = set()
        self._clothing_event_categories: dict[str, list[str]] = {}
        self._clothing_event_tag_to_category: dict[str, str] = {}
        self._clothing_event_meta: dict[str, dict[str, Any]] = {}

        self._valid_tag_whitelist: frozenset = frozenset()
        self._NOISE_THRESHOLD = 24

        self._enabled = False

    def load(self) -> bool:
        """모든 필터 데이터 로드."""
        self._load_text_filters()
        self._load_json_filters()
        self._load_tag_whitelist()
        self._enabled = True
        return True

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # -- 텍스트 파일 로드 ---------------------------------------------------

    def _resolve_file(self, filename: str) -> Path | None:
        if self._data_dir and (self._data_dir / filename).is_file():
            return self._data_dir / filename
        if (self._taglist_dir.parent / filename).is_file():
            return self._taglist_dir.parent / filename
        return None

    def _load_list_from_file(self, filename: str) -> list[str]:
        path = self._resolve_file(filename)
        if not path:
            logger.debug("Filter file not found: %s", filename)
            return []
        try:
            text = path.read_text(encoding="utf-8")
            tags = [line.strip() for line in text.splitlines() if line.strip()]
            logger.info("Loaded filter file: %s (%d tags)", filename, len(tags))
            return tags
        except OSError as exc:
            logger.warning("Failed to load filter file %s: %s", filename, exc)
            return []

    def _load_text_filters(self):
        self.clothes_list = self._load_list_from_file("clothes_list.txt")
        self.color_list = self._load_list_from_file("color.txt")
        self.characteristic_list = self._load_list_from_file("characteristic_list.txt")

    # -- JSON 태그 필터 로드 ------------------------------------------------

    def _load_json_file(self, filename: str) -> dict:
        path = self._taglist_dir / filename
        if not path.is_file():
            logger.debug("JSON filter file not found: %s", path)
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load JSON filter %s: %s", filename, exc)
            return {}

    def _load_json_filters(self):
        # expression_tags.json
        expr_data = self._load_json_file("expression_tags.json")
        if expr_data:
            tags: set[str] = set(expr_data.get("tags", []))
            tags.update(expr_data.get("modifiers", []))
            for group_tags in expr_data.get("groups", {}).values():
                tags.update(group_tags)
            self._expression_set = tags
            logger.info("  → 표정 태그: %d개", len(self._expression_set))

        # pose_action_tags.json
        pose_data = self._load_json_file("pose_action_tags.json")
        if pose_data:
            tags = set()
            for cat_tags in pose_data.get("categories", {}).values():
                tags.update(cat_tags)
            self._pose_action_set = tags
            logger.info("  → 포즈/행동 태그: %d개", len(self._pose_action_set))

        # location_tags.json
        loc_data = self._load_json_file("location_tags.json")
        if loc_data:
            self._location_set = set(loc_data.get("tags", []))
            logger.info("  → 장소 태그: %d개", len(self._location_set))

        # meta_tags.json
        meta_data = self._load_json_file("meta_tags.json")
        if meta_data:
            self._meta_set = set(meta_data.get("tags", []))
            logger.info("  → 메타 태그: %d개", len(self._meta_set))

        # object_tags.json
        obj_data = self._load_json_file("object_tags.json")
        if obj_data:
            self._object_set = set(obj_data.get("tags", []))
            logger.info("  → 사물 태그: %d개", len(self._object_set))

        # clothing_event.json
        event_data = self._load_json_file("clothing_event.json")
        if event_data:
            version = int(event_data.get("version", 1))
            raw_categories = event_data.get("categories", {})
            tags = set()
            cat_map: dict[str, list[str]] = {}
            tag_to_cat: dict[str, str] = {}
            meta_map: dict[str, dict[str, Any]] = {}
            for cat, entries in raw_categories.items():
                cat_tags: list[str] = []
                for entry in entries:
                    if isinstance(entry, dict):
                        tag = entry.get("tag", "")
                        if not tag:
                            continue
                        meta_map[tag] = {
                            "category": cat,
                            "garment_noun": entry.get("garment_noun"),
                            "region": entry.get("region"),
                            "garment_bound": bool(entry.get("garment_noun")),
                        }
                    else:
                        tag = str(entry)
                        if not tag:
                            continue
                        meta_map[tag] = {"category": cat, "garment_noun": None, "region": None, "garment_bound": False}
                    cat_tags.append(tag)
                    tags.add(tag)
                    tag_to_cat[tag] = cat
                cat_map[cat] = cat_tags
            self._clothing_event_categories = cat_map
            self._clothing_event_set = tags
            self._clothing_event_tag_to_category = tag_to_cat
            self._clothing_event_meta = meta_map
            logger.info("  → 의상 이벤트 태그: %d개 (v%s)", len(tags), version)

        # clothing_regions.json
        region_data = self._load_json_file("clothing_regions.json")
        if region_data:
            self._clothing_region_map = region_data.get("regions", {})
            self._unassigned_region = region_data.get("unassigned_region", "UNASSIGNED")
            self._clothing_tag_to_region = {}
            for region, rtags in self._clothing_region_map.items():
                for tag in rtags:
                    self._clothing_tag_to_region[tag] = region
            logger.info("  → 의류 Region: %d개, %d개 태그 매핑",
                        len(self._clothing_region_map), len(self._clothing_tag_to_region))

    # -- Whitelist (노이즈 필터링) ------------------------------------------

    def _load_tag_whitelist(self):
        path = self._taglist_dir / "unique_tags.json"
        if not path.is_file():
            logger.warning("Whitelist source not found: %s", path)
            return
        try:
            freq_data = json.loads(path.read_text(encoding="utf-8"))
            freq_whitelist = {tag for tag, freq in freq_data.items() if freq > self._NOISE_THRESHOLD}

            classified: set[str] = set()
            classified.update(self.clothes_list)
            classified.update(self.characteristic_list)
            classified.update(self._location_set)
            classified.update(self._expression_set)
            classified.update(self._pose_action_set)
            classified.update(self._meta_set)
            classified.update(self._object_set)
            classified.update(self._clothing_event_set)
            for region_tags in self._clothing_region_map.values():
                classified.update(region_tags)

            self._valid_tag_whitelist = frozenset(freq_whitelist | classified)
            logger.info("태그 Whitelist: %d개", len(self._valid_tag_whitelist))
        except Exception as exc:
            logger.warning("Whitelist load error: %s", exc)

    # -- 공개 조회 메서드 ---------------------------------------------------

    def filter_noise_tags(self, tags: list[str]) -> list[str]:
        if not self._valid_tag_whitelist:
            return tags
        return [tag for tag in tags if tag in self._valid_tag_whitelist]

    def get_clothing_region(self, tag: str) -> str:
        return self._clothing_tag_to_region.get(tag, self._unassigned_region)

    def get_clothing_event_category(self, tag: str) -> str | None:
        return self._clothing_event_tag_to_category.get(tag)

    def get_clothing_event_meta(self, tag: str) -> dict[str, Any] | None:
        return self._clothing_event_meta.get(tag)

    def get_garment_region(self, garment_tag: str) -> str | None:
        if not garment_tag:
            return None
        t = garment_tag.lower().strip()
        direct = self._clothing_tag_to_region.get(t)
        if direct:
            return direct
        best_region: str | None = None
        best_len = 0
        padded = f" {t} "
        for known, region in self._clothing_tag_to_region.items():
            if not known:
                continue
            kp = f" {known} "
            if kp in padded and len(known) > best_len:
                best_region = region
                best_len = len(known)
        return best_region


# ---------------------------------------------------------------------------
# 태그 필터 파이프라인
# ---------------------------------------------------------------------------


def apply_tag_filters(
    main_tags: list[str],
    removed_tags: list[str],
    checkbox_options: dict[str, bool],
    auto_hide: list[str],
    filter_manager: FilterDataManager,
    *,
    track_clothing_regions: bool = False,
    category_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """공통 태그 필터링 파이프라인. main_tags/removed_tags를 in-place 수정.

    Returns:
        dict with optional keys:
        - ``removed_clothes_by_region`` (track_clothing_regions=True 시)
        - ``removed_clothing_events_by_category`` (track_clothing_regions=True 시)
        - ``filter_log`` (각 라운드 처리 기록)
    """
    result: dict[str, Any] = {}
    filter_log: list[dict[str, Any]] = []

    def _remove_matched(matched: list[str]) -> None:
        for keyword in matched:
            if keyword in main_tags:
                main_tags.remove(keyword)
                removed_tags.append(keyword)

    # 1. Auto Hide
    before_len = len(removed_tags)
    _process_auto_hide(main_tags, removed_tags, auto_hide)
    filter_log.append({"name": "Auto Hide", "key": "auto_hide", "enabled": True,
                        "removed": removed_tags[before_len:]})

    if not filter_manager:
        result["filter_log"] = filter_log
        return result

    # 라운드 정의: (체크박스 키, 표시 이름, 태그 목록 획득 함수)
    rounds: list[tuple[str, str, Any]] = [
        ("remove_character_features", "캐릭터 특징", lambda: filter_manager.characteristic_list),
        ("remove_clothes", "의류", lambda: filter_manager.clothes_list),
        ("remove_clothing_event", "의상 이벤트", lambda: list(filter_manager._clothing_event_set)),
        ("remove_color", "색상", None),  # 특수 처리
        ("remove_location_and_background_color", "위치/배경", lambda: list(filter_manager._location_set)),
        ("remove_expression", "표정", lambda: list(filter_manager._expression_set)),
        ("remove_pose_action", "포즈/동작", lambda: list(filter_manager._pose_action_set)),
        ("remove_meta_tags", "메타", lambda: list(filter_manager._meta_set)),
        ("remove_object_tags", "사물", lambda: list(filter_manager._object_set)),
        ("remove_noise_tags", "노이즈 태그", None),  # 특수 처리
    ]

    for key, name, get_tags_fn in rounds:
        enabled = checkbox_options.get(key, key == "remove_meta_tags")
        before_len = len(removed_tags)
        if not enabled:
            filter_log.append({"name": name, "key": key, "enabled": False, "removed": []})
            continue

        exclude, include = _override_sets(category_overrides, key)

        if key == "remove_color":
            # 색상: partial match + 예외 처리
            colors = filter_manager.color_list
            if not _terms_empty(exclude):
                colors = [c for c in colors if not _matches_terms(c, exclude)]
            temp = [kw for kw in main_tags
                    if not _is_color_exception(kw) and any(c in kw for c in colors)]
            temp = _apply_round_overrides(temp, main_tags, exclude, include)
            _remove_matched(temp)

        elif key == "remove_noise_tags":
            filtered_set = set(filter_manager.filter_noise_tags(main_tags))
            new_main: list[str] = []
            removed_here: list[str] = []
            for keyword in main_tags:
                protected = _matches_terms(keyword, exclude)
                forced = _matches_terms(keyword, include)
                should_remove = (keyword not in filtered_set or forced) and not protected
                if should_remove:
                    removed_here.append(keyword)
                else:
                    new_main.append(keyword)
            main_tags[:] = new_main
            removed_tags.extend(removed_here)

        else:
            tag_set = get_tags_fn()
            temp = [kw for kw in main_tags if kw in tag_set]
            temp = _apply_round_overrides(temp, main_tags, exclude, include)

            # 의류/의상이벤트 region/category 추적
            if key == "remove_clothes" and track_clothing_regions and temp:
                by_region: dict[str, list[str]] = defaultdict(list)
                for kw in temp:
                    by_region[filter_manager.get_clothing_region(kw)].append(kw)
                result["removed_clothes_by_region"] = dict(by_region)

            if key == "remove_clothing_event" and track_clothing_regions and temp:
                by_cat: dict[str, list[str]] = defaultdict(list)
                for kw in temp:
                    cat = filter_manager.get_clothing_event_category(kw) or "unknown"
                    by_cat[cat].append(kw)
                result["removed_clothing_events_by_category"] = dict(by_cat)

            _remove_matched(temp)

        filter_log.append({"name": name, "key": key, "enabled": True,
                           "removed": removed_tags[before_len:]})

    result["filter_log"] = filter_log
    return result


def _process_auto_hide(
    main_tags: list[str],
    removed_tags: list[str],
    auto_hide: list[str],
) -> None:
    """Auto Hide 처리: 직접 매칭 + 패턴 매칭."""
    protected: list[str] = []
    for item in auto_hide:
        if item.startswith("~"):
            protected.append(item[1:].strip())

    hide_items = [item for item in auto_hide if not item.startswith("~")]

    # 변환 맵 확장
    additional: list[str] = []
    for item in hide_items:
        if item in _REVERSED_CONVERSION_MAP:
            additional.append(_REVERSED_CONVERSION_MAP[item])
    hide_items = list(set(hide_items + additional))

    # 직접 매칭
    to_remove: list[str] = []
    for keyword in main_tags[:]:
        if keyword in hide_items:
            if not any(p in keyword or keyword == p for p in protected):
                to_remove.append(keyword)

    # 패턴 매칭
    for item in hide_items:
        pred = compile_hide_pattern(item)
        if pred is None:
            continue
        is_prefix, needle = pred
        for keyword in main_tags[:]:
            if is_prefix:
                if needle == (" " + keyword):
                    to_remove.append(keyword)
            else:
                if needle in keyword:
                    to_remove.append(keyword)

    # protected 제외
    to_remove = list(set(to_remove))
    if protected:
        to_remove = [kw for kw in to_remove
                     if not any(p in kw or kw == p for p in protected)]

    for keyword in to_remove:
        if keyword in main_tags:
            main_tags.remove(keyword)
            removed_tags.append(keyword)


__all__ = [
    "FilterDataManager",
    "apply_tag_filters",
    "compile_hide_pattern",
    "_is_color_exception",
]
