"""태그별 Danbooru rating 분포 — tag_rating.json 로드 및 조회.

데이터 출처: HuggingFace ``baqu2213/PoemForSmallFThings`` (NAIA2.0 동일).

형식:
    {"tags": {"1girl": {"n": 912496, "g": 42.3, "s": 37.8, "q": 8.5, "e": 11.4}, ...}}

rating 값:
    g=general  s=sensitive  q=questionable  e=explicit  n=게시물 수
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from ..resources.tag_data_downloader import bundled_tags_dir

logger = logging.getLogger(__name__)

#: tag_rating.json 파일명.
TAG_RATING_FILENAME = "tag_rating.json"


@dataclass(frozen=True)
class TagRating:
    """태그 하나의 rating 분포."""

    post_count: int  # 전체 게시물 수
    general: float  # general 비율 (%)
    sensitive: float  # sensitive 비율 (%)
    questionable: float  # questionable 비율 (%)
    explicit: float  # explicit 비율 (%)


class TagRatingDb:
    """태그별 rating 분포를 조회한다.

    사용 예:
        db = TagRatingDb()
        db.load()
        rating = db.get_tag_rating("1girl")
        if rating:
            print(f"explicit={rating.explicit}%")
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or bundled_tags_dir() / TAG_RATING_FILENAME
        self._tags: dict[str, TagRating] = {}
        self._enabled = False

    def load(self) -> bool:
        if not self._path.is_file():
            logger.warning("Tag rating file not found: %s", self._path)
            return False
        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            tags_raw = data.get("tags", {})
            for name, r in tags_raw.items():
                self._tags[name] = TagRating(
                    post_count=int(r.get("n", 0)),
                    general=float(r.get("g", 0)),
                    sensitive=float(r.get("s", 0)),
                    questionable=float(r.get("q", 0)),
                    explicit=float(r.get("e", 0)),
                )
            self._enabled = True
            logger.info("Loaded %d tag ratings from %s", len(self._tags), self._path.name)
            return True
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Failed to load tag ratings: %s", exc)
            return False

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    @property
    def tag_count(self) -> int:
        return len(self._tags)

    def get_tag_rating(self, tag: str) -> TagRating | None:
        return self._tags.get(tag.lower())

    def is_explicit_likely(self, tag: str, threshold: float = 30.0) -> bool:
        """해당 태그가 explicit 성향이 강한지 판단한다 (explicit 비율 > threshold)."""
        r = self.get_tag_rating(tag)
        return r is not None and r.explicit > threshold

    def is_adult_likely(self, tag: str, threshold: float = 40.0) -> bool:
        """해당 태그가 성인(questionable + explicit) 성향이 강한지 판단한다."""
        r = self.get_tag_rating(tag)
        return r is not None and (r.questionable + r.explicit) > threshold


__all__ = ["TagRating", "TagRatingDb", "TAG_RATING_FILENAME"]
