"""자연어 키워드 → 태그 DB 후보 검색 리트리버 (RAG).

LLM 호출 전에 사용자 자연어에서 영문 키워드를 뽑아 내장 Danbooru 태그 DB에서
인기 태그(post_count 기준) 후보를 검색한다. 검색 결과는 시스템 프롬프트에
"AVAILABLE TAGS"로 주입되어 LLM이 실존 태그를 고르도록 돕는다.

매칭 규칙 (토큰별, 강도 내림차순):
- 정확 일치: 태그명 == 토큰
- 접두사: 태그명이 토큰으로 시작
- 부분 문자열: 토큰이 태그명에 포함 ("rainy" → rain은 부분이 아님, 반대 방향)
- 4글자 근사: 토큰의 앞 4글자가 태그명의 접두사 (복합어 "schoolgirl" → school_uniform)

결정적(deterministic) 검색 — 임베딩/벡터 없음. DB 비활성 시 빈 결과(폴백).
Qt 의존성 없음.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from naiauto.core.tag_completer import parse_tag_line, resolve_database_path

logger = logging.getLogger(__name__)

#: 검색 대상 토큰에서 제외할 불용어 (영문 태그 키워드에만 의미가 있음).
_STOPWORDS = frozenset(
    {
        "a", "an", "the", "in", "on", "at", "with", "of", "and", "or", "to",
        "from", "is", "are", "was", "were", "be", "being", "been", "this",
        "that", "it", "for", "as", "by", "into", "under", "over", "between",
    }
)

#: 4글자 근사 접두사 규칙 파라미터.
_APPROX_MIN_TOKEN = 4
_APPROX_PREFIX_LEN = 4

#: 토큰 하나가 후보 목록에 기여할 수 있는 최대 태그 수 (균형 배분).
_TOKEN_CAP = 15

#: 강한 일치 기준 — exact(3)/prefix(2)는 우선 그룹, substring(1)/근사(0)는 보충.
_STRONG_MIN = 2

#: 매칭 강도 상수.
_EXACT = 3
_PREFIX = 2
_SUBSTRING = 1
_APPROX = 0

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


class TagRetriever:
    """자연어 텍스트 → 태그 DB 후보 태그명 목록 (강도·post_count 내림차순)."""

    def __init__(self, database_path: Path | None = None, limit: int = 120) -> None:
        # None → bundled_database_path()
        self._database_path = database_path
        self._default_limit = limit
        self._db: dict[str, int] = {}  # 태그명 → post_count
        self._enabled = False

    def load(self) -> bool:
        """태그 DB를 읽어 메모리에 적재한다. 실패 시 False (검색 비활성)."""
        self._db = {}
        self._enabled = False

        path = resolve_database_path(str(self._database_path) if self._database_path is not None else None)
        if not path.exists():
            logger.warning("Tag database file not found: %s; tag retriever disabled", path)
            return False

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Cannot read tag database file: %s; tag retriever disabled", e)
            return False

        entries: dict[str, int] = {}
        for line in raw.splitlines():
            entry = parse_tag_line(line)
            if entry is not None:
                entries[entry.name.lower()] = entry.post_count

        if not entries:
            logger.warning("Tag database file is empty or malformed: %s; tag retriever disabled", path)
            return False

        self._db = entries
        self._enabled = True
        logger.info("Loaded %d tags for retrieval from %s", len(entries), path)
        return True

    @property
    def is_enabled(self) -> bool:
        """DB 로드 성공 여부."""
        return self._enabled

    def search(self, text: str, limit: int | None = None) -> tuple[str, ...]:
        """텍스트에서 키워드를 뽑아 후보 태그명을 (강도, post_count) 순으로 반환.

        DB 비활성 또는 키워드 없음 → 빈 튜플.
        """
        if not self._enabled:
            return ()
        tokens = self._tokens(text)
        if not tokens:
            return ()

        # 토큰별 상위 _TOKEN_CAP개를 (태그 → 최대 강도)로 누적한 뒤,
        # 강한 일치(exact/prefix) 그룹 → 약한 일치(substring/근사) 그룹 순으로,
        # 각 그룹 안에서 인기도(post_count) 내림차순으로 정렬한다.
        scored: dict[str, int] = {}
        for token in tokens:
            candidates = self._token_matches(token)
            candidates.sort(key=lambda item: -self._db[item[0]])
            for tag, strength in candidates[:_TOKEN_CAP]:
                scored[tag] = max(scored.get(tag, -1), strength)

        strong = sorted(
            (tag for tag, s in scored.items() if s >= _STRONG_MIN),
            key=lambda tag: -self._db[tag],
        )
        weak = sorted(
            (tag for tag, s in scored.items() if s < _STRONG_MIN),
            key=lambda tag: -self._db[tag],
        )
        n = limit if limit is not None else self._default_limit
        return tuple((strong + weak)[:n])

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tokens(text: str) -> tuple[str, ...]:
        """소문자 영문/숫자/언더스코어 토큰 추출 — 불용어 제외."""
        return tuple(t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS)

    def _token_matches(self, token: str) -> list[tuple[str, int]]:
        """토큰 하나를 각 매칭 규칙에 적용해 (태그명, 최대 강도) 목록을 만든다."""
        scored: dict[str, int] = {}
        # 규칙 1: 정확 일치
        if token in self._db:
            scored[token] = _EXACT
        # 규칙 2: 접두사 (태그명이 토큰으로 시작)
        for tag in self._db:
            if tag.startswith(token):
                scored[tag] = max(scored.get(tag, -1), _PREFIX)
        # 규칙 3: 부분 문자열 (토큰이 태그명에 포함)
        for tag in self._db:
            if token in tag:
                scored[tag] = max(scored.get(tag, -1), _SUBSTRING)
        # 규칙 4: 4글자 근사 접두사 (복합어용)
        if len(token) >= _APPROX_MIN_TOKEN:
            prefix = token[:_APPROX_PREFIX_LEN]
            for tag in self._db:
                if tag.startswith(prefix):
                    scored[tag] = max(scored.get(tag, -1), _APPROX)
        return list(scored.items())


__all__ = ["TagRetriever"]
