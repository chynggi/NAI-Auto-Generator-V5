"""태그 관계 추천 엔진 — 유사 태그, 상세 태그, 배타 쌍 검증.

NAIA2.0의 ``tag_relation_ranker.py``를 V5 환경에 맞게 이식했다.
``tag_exclusive_pairs.json``과 ``tag_cooccurrence.json``을 사용해
비슷한 태그, 더 구체적인 태그, 배타적 관계를 추천/검증한다.

사용 예:
    ranker = TagRelationRanker()
    ranker.load()
    similar = ranker.rank_related("swimsuit")
    specific = ranker.rank_specific("swimsuit")
    exclusive = ranker.is_exclusive_pair("muscular", "loli")
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..resources.tag_data_downloader import bundled_tags_dir

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

_STOP_TOKENS: frozenset = frozenset({
    "a", "an", "and", "at", "by", "for", "from",
    "first", "high", "in", "into", "low", "of", "on",
    "open", "or", "over", "the", "to", "under", "with", "without",
})

_COLOR_TOKENS: frozenset = frozenset({
    "aqua", "black", "blonde", "blue", "brown", "dark",
    "gold", "green", "grey", "gray", "light", "orange",
    "pink", "purple", "red", "silver", "white", "yellow",
})

_GENERIC_TOKENS: frozenset = frozenset({
    "boy", "boys", "cosplay", "everyone", "female", "focus",
    "girl", "girls", "human", "humans", "male", "many",
    "multiple", "other", "others", "person", "solo", "too",
    "view", "views",
})

_BROAD_SIBLING_SUBGROUPS: frozenset = frozenset({
    "accessories", "activity", "attire", "clothing_action",
    "effects", "etc", "gesture", "image_composition",
    "instruments", "metatags", "patterns", "pose", "posture",
    "sex_acts", "sexual_positions", "symbols", "text",
    "tools", "verbs_and_gerunds", "weapons",
})

_NEG_RE = re.compile(r"^(?:no|without|missing)\s+|\s+(?:gone|removed)$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def normalize_tag(tag: str) -> str:
    """태그 정규화: 소문자 + underscore → 공백."""
    return tag.lower().replace("_", " ").strip()


def _core_tokens(tag: str) -> set[str]:
    return {
        t for t in normalize_tag(tag).split()
        if t and t not in _STOP_TOKENS and t not in _COLOR_TOKENS
    }


def _relation_tokens(tag: str) -> set[str]:
    return set(_TOKEN_RE.findall(normalize_tag(tag)))


def _is_negation_pair(a: str, b: str) -> bool:
    na, nb = bool(_NEG_RE.search(a)), bool(_NEG_RE.search(b))
    if na == nb:
        return False
    ta = _relation_tokens(_NEG_RE.sub(" ", a))
    tb = _relation_tokens(_NEG_RE.sub(" ", b))
    if not ta or not tb:
        return False
    return ta <= tb or tb <= ta


# ---------------------------------------------------------------------------
# 배타 태그쌍
# ---------------------------------------------------------------------------

_exclusive_pairs: frozenset[tuple[str, str]] | None = None


def _load_exclusive_pairs_from(path: Path | None = None) -> frozenset[tuple[str, str]]:
    global _exclusive_pairs
    if _exclusive_pairs is not None:
        return _exclusive_pairs
    filepath = path or bundled_tags_dir() / "tag_exclusive_pairs.json"
    pairs: set[tuple[str, str]] = set()
    try:
        if filepath.is_file():
            payload = json.loads(filepath.read_text(encoding="utf-8"))
            for row in payload.get("pairs") or []:
                a, _, b = str(row).partition("\t")
                if a and b:
                    pairs.add((a, b) if a < b else (b, a))
        _exclusive_pairs = frozenset(pairs)
    except Exception as exc:
        logger.warning("Failed to load exclusive pairs: %s", exc)
        _exclusive_pairs = frozenset()
    return _exclusive_pairs


def is_exclusive_pair(a: str, b: str) -> bool:
    """두 태그가 배타적(같이 쓰면 안 되는) 관계인지 확인."""
    key = (a, b) if a < b else (b, a)
    return key in _load_exclusive_pairs_from()


# ---------------------------------------------------------------------------
# RankedRelation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RankedRelation:
    tag: str
    score: float
    source: str


# ---------------------------------------------------------------------------
# TagRelationRanker
# ---------------------------------------------------------------------------


class TagRelationRanker:
    """태그 관계 순위 엔진.

    ``tag_records`` 는 {tag: {relations: {children, siblings, word_match, parent}, group, subgroup}} 형태.
    NAIA2.0의 이벤트 프리셋 데이터에서 생성되며, V5에서는 동반/배타 데이터로 대체한다.
    """

    def __init__(self, tag_records: Mapping[str, Mapping[str, Any]] | None = None):
        self._records: dict[str, dict[str, Any]] = {}
        if tag_records:
            self._records.update(tag_records)
        self._cooccurrence: dict[str, list[str]] = {}

    def load_cooccurrence(self, path: Path | None = None) -> bool:
        """tag_cooccurrence.json 로드."""
        filepath = path or bundled_tags_dir() / "tag_cooccurrence.json"
        if not filepath.is_file():
            logger.warning("Cooccurrence file not found: %s", filepath)
            return False
        try:
            payload = json.loads(filepath.read_text(encoding="utf-8"))
            companions = payload.get("companions", {})
            self._cooccurrence = {
                tag: list(vals) for tag, vals in companions.items()
            }
            logger.info("Loaded %d cooccurrence entries", len(self._cooccurrence))
            return True
        except Exception as exc:
            logger.warning("Failed to load cooccurrence: %s", exc)
            return False

    def add_tag_records(self, records: Mapping[str, Mapping[str, Any]]) -> None:
        """태그 레코드(relations, group, subgroup 등) 추가."""
        for tag, info in records.items():
            self._records[normalize_tag(tag)] = dict(info)

    # -- 공개 조회 메서드 ---------------------------------------------------

    def rank_related(
        self,
        tag: str,
        *,
        limit: int = 8,
    ) -> list[str]:
        """비슷한 태그 추천 (siblings + word_match + cooccurrence)."""
        return [item.tag for item in self._rank(tag, limit=limit)]

    def rank_specific(
        self,
        tag: str,
        *,
        limit: int = 8,
    ) -> list[str]:
        """더 구체적인 태그 추천 (children)."""
        return [item.tag for item in self._rank(tag, sources=("children",), limit=limit)]

    def get_cooccurrence(self, tag: str, limit: int = 8) -> list[str]:
        """자주 함께 쓰이는 태그 반환."""
        normed = normalize_tag(tag)
        companions = self._cooccurrence.get(normed, [])
        return companions[:limit]

    def valid_implications(
        self,
        tag: str,
        limit: int = 8,
    ) -> list[str]:
        """상위(부모) 태그 반환 (더 일반적인 개념)."""
        normed = normalize_tag(tag)
        info = self._records.get(normed, {})
        relations = info.get("relations", {}) or {}
        valid: list[str] = []
        seen: set[str] = set()
        for raw_parent in relations.get("parent", []):
            parent = normalize_tag(raw_parent)
            if parent in seen:
                continue
            if self._is_valid_parent(normed, parent):
                seen.add(parent)
                valid.append(parent)
            if len(valid) >= limit:
                break
        return valid

    # -- 순위 계산 ----------------------------------------------------------

    def _rank(
        self,
        tag: str,
        *,
        sources: tuple[str, ...] | None = None,
        limit: int = 8,
    ) -> list[RankedRelation]:
        normed = normalize_tag(tag)
        info = self._records.get(normed, {})
        relations = info.get("relations", {}) or {}
        parents = set(self.valid_implications(tag))

        source_group = str(info.get("group", "") or "")
        source_subgroup = str(info.get("subgroup", "") or "")
        source_tokens = _core_tokens(normed)

        wanted = sources or ("siblings", "word_match")
        own_children = {normalize_tag(t) for t in self._as_list(relations.get("children"))}
        drop_children = "children" not in wanted

        candidates: list[tuple[str, str]] = []
        for key in ("children", "siblings", "word_match"):
            if key in wanted:
                candidates.extend((key, t) for t in self._as_list(relations.get(key)))

        # Also add cooccurrence candidates if doing "related" search
        if "siblings" in wanted:
            for companion in self.get_cooccurrence(tag, limit=limit * 2):
                candidates.append(("cooccurrence", companion))

        ranked: dict[str, RankedRelation] = {}
        for source, raw_candidate in candidates:
            candidate = normalize_tag(raw_candidate)
            if not candidate or candidate == normed or candidate in parents:
                continue
            if _is_negation_pair(normed, candidate):
                continue
            if source != "children" and is_exclusive_pair(normed, candidate):
                continue
            if drop_children and candidate in own_children:
                continue

            candidate_info = self._records.get(candidate, {})
            score = self._score_candidate(
                candidate, candidate_info,
                source=source,
                source_group=source_group,
                source_subgroup=source_subgroup,
                source_tokens=source_tokens,
            )
            if score <= 0:
                continue

            previous = ranked.get(candidate)
            if previous is None or score > previous.score:
                ranked[candidate] = RankedRelation(candidate, score, source)

        results = list(ranked.values())
        results.sort(key=lambda r: (-r.score, r.tag))
        return results[:limit]

    def _score_candidate(
        self,
        candidate: str,
        candidate_info: dict[str, Any],
        *,
        source: str,
        source_group: str,
        source_subgroup: str,
        source_tokens: set[str],
    ) -> float:
        candidate_group = str(candidate_info.get("group", "") or "")
        candidate_subgroup = str(candidate_info.get("subgroup", "") or "")
        candidate_tokens = _core_tokens(candidate)
        overlap = source_tokens & candidate_tokens
        same_group = bool(source_group and candidate_group and source_group == candidate_group)
        same_subgroup = bool(same_group and source_subgroup and candidate_subgroup and source_subgroup == candidate_subgroup)

        if source == "word_match" and not overlap:
            return 0.0
        if source == "word_match" and self._has_only_generic_overlap(overlap):
            return 0.0
        if source == "word_match" and not same_subgroup and len(overlap) < 2:
            return 0.0

        score = {"children": 320.0, "siblings": 190.0, "word_match": 40.0, "cooccurrence": 100.0}.get(source, 0.0)

        if same_subgroup:
            score += 150
        elif same_group:
            score += 75
        if overlap:
            score += 70 * len(overlap)
            if len(overlap) >= 2:
                score += 30

        if source == "word_match" and score < 100:
            return 0.0

        return score

    def _is_valid_parent(self, child: str, parent: str) -> bool:
        if not parent or parent == child:
            return False
        if parent not in self._records:
            return False
        if len(parent) == 1 and parent.isalpha():
            return False
        parent_tokens = _relation_tokens(parent)
        child_tokens = _relation_tokens(child)
        if not parent_tokens:
            return parent in child
        return parent_tokens.issubset(child_tokens)

    def _has_only_generic_overlap(self, overlap: set[str]) -> bool:
        if not overlap:
            return False
        if any(len(t) <= 1 for t in overlap):
            return True
        return overlap <= _GENERIC_TOKENS

    @staticmethod
    def _as_list(value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value if item]
        return []


# ---------------------------------------------------------------------------
# 편의 함수
# ---------------------------------------------------------------------------


def build_ranked_related_tags(
    tag: str,
    tag_records: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    limit: int = 8,
) -> list[str]:
    """단일 호출로 유사 태그 추천."""
    ranker = TagRelationRanker(tag_records)
    ranker.load_cooccurrence()
    return ranker.rank_related(tag, limit=limit)


__all__ = [
    "RankedRelation",
    "TagRelationRanker",
    "build_ranked_related_tags",
    "is_exclusive_pair",
    "normalize_tag",
]
