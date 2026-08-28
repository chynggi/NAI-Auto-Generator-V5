"""후보 태그 문구 → 검증된 Danbooru 태그 리졸버.

자연어 → 태그 파이프라인에서 LLM이 후보 문구만 내놓으면, 이 모듈이 실제
Danbooru 태그 DB에 존재하는지 결정적(deterministic)으로 확인한다.
유사어/의미 기반 추측은 하지 않는다 — 규칙에 없는 형태는 전부 unresolved로
처리해 final prompt에서 제외한다 (스펙 §10, §41).

DB(CSV/JSON) 로딩은 core.tag_completer 의 ``parse_tag_line`` /
``bundled_database_path`` / ``resolve_database_path`` 를 재사용한다.
메인 DB(동봉 또는 사용자 지정) 로드가 성공하면 [Ruling #5]에 따라 내장 보조
파일 ``danbooru_tags_extra.csv``(NAI UC 어휘)를 병합한다.
core/ 모듈이므로 Qt 의존성이 없다.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from naiauto.core.prompt.schema import TagRef
from naiauto.core.tag_completer import (
    TagEntry,
    parse_tag_line,
    resolve_database_path,
)

logger = logging.getLogger(__name__)

#: norm 정규화에서 끝단어가 아닌 문장부호 — 끝에 붙은 구두점만 자른다.
_TRAILING_PUNCT_RE = re.compile(r"[^A-Za-z0-9_]+$")

#: [Ruling #5] Danbooru 태그 병합/철자 정규화 (2026-08-28 확인).
ALIASES: dict[str, str] = {
    "silver_hair": "grey_hair",    # Danbooru에서 deprecated → grey_hair로 통합
    "blond_hair": "blonde_hair",   # canonical 철자는 blonde_hair
}

#: 내장 보조 태그 파일 이름 (NAI UC 어휘).
BUNDLED_EXTRA_NAME = "danbooru_tags_extra.csv"

#: "{stem}_haired" → "{stem}_hair", "{stem}_eyed" → "{stem}_eyes" 변형 규칙.
_SUFFIX_RULES = (
    ("_haired", "_hair"),
    ("_eyed", "_eyes"),
)


def bundled_extra_path() -> Path:
    """내장 보조 태그 파일 (NAI UC 어휘) — danbooru_tags_extra.csv"""
    return Path(__file__).resolve().parent.parent.parent / "resources" / "tags" / BUNDLED_EXTRA_NAME


def _norm(phrase: str, keep_hyphens: bool = False) -> str:
    """후보 문구 → 조회용 정규화명.

    [Ruling #5] 소문자 + 하이픈→언더스코어 + 공백→언더스코어 +
    끝단어가 아닌 문장부호 제거. ("silver-haired" → silver_haired)

    ``keep_hyphens=True`` 면 하이픈을 보존한다 (공백만 언더스코어로):
    DB에 하이픈을 포함한 실제 태그("two-tone_hair", "straight-on")를
    규칙 1에서 그대로 조회하기 위한 variant다.
    """
    text = phrase.strip().lower().strip(".,;:!?\"'()[]{}")
    text = _TRAILING_PUNCT_RE.sub("", text)
    if keep_hyphens:
        return re.sub(r"\s+", "_", text)
    return re.sub(r"[\s-]+", "_", text)


class TagResolver:
    """후보 태그 문구 → 검증된 Danbooru 태그.

    결정적(deterministic) 검증만 한다 — LLM은 후보만 내고, 여기서 실제 tag인지
    판정한다. DB에 없는 태그는 status="unresolved" TagRef 하나로 돌려주며
    final prompt에 넣지 않는다 (스펙 §10, §41).

    [Ruling #5 적용] 메인 DB(동봉 또는 사용자 지정)와 별도로 내장 보조 파일
    `danbooru_tags_extra.csv`를 로드한다 — Danbooru 추출본에 없지만 NovelAI
    UC/quality 어휘에 속하는 소수 단어(text, worst_quality, bad_quality,
    blank_page)만 담겨 있다. 보조 파일은 메인 DB 로드가 성공했을 때만 병합된다.

    [Ruling #5 적용] 알려진 Danbooru 병합/철자 변형은 alias 사전으로 정규화한다:
    silver_hair→grey_hair (Danbooru에서 deprecated·병합됨),
    blond_hair→blonde_hair (canonical 철자). alias는 토큰 분해보다 먼저 적용된다.
    """

    def __init__(self, database_path: Path | None = None) -> None:
        # None → bundled_database_path()
        self._database_path = database_path
        self._db: dict[str, TagEntry] = {}
        self._enabled = False

    def load(self) -> bool:
        """태그 DB를 읽어 메모리에 적재한다. 실패(없음/손상) 시 False.

        성공하면 ``{정규화 태그명: TagEntry}`` dict를 채운다 — 사전 검증(resolve)
        용이므로 자동완성이 쓰는 정렬 목록은 만들지 않는다. 메인 DB 로드가
        성공했을 때만 보조 파일(danbooru_tags_extra.csv)을 병합한다.
        """
        self._db = {}
        self._enabled = False

        path = resolve_database_path(str(self._database_path) if self._database_path is not None else None)
        if not path.exists():
            logger.warning("Tag database file not found: %s; tag resolver disabled", path)
            return False

        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Cannot read tag database file: %s; tag resolver disabled", e)
            return False

        entries: dict[str, TagEntry] = {}
        for line in raw.splitlines():
            entry = parse_tag_line(line)
            if entry is not None:
                entries[entry.name.lower()] = entry

        if not entries:
            logger.warning("Tag database file is empty or malformed: %s; tag resolver disabled", path)
            return False

        # [Ruling #5] 메인 로드 성공 시에만 보조 파일 병합 (# 주석 줄은 parse_tag_line이 건너뜀)
        try:
            extra_raw = bundled_extra_path().read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("Cannot read extra tag file (ignored): %s", e)
            extra_raw = ""
        for line in extra_raw.splitlines():
            entry = parse_tag_line(line)
            if entry is not None:
                entries[entry.name.lower()] = entry

        self._db = entries
        self._enabled = True
        logger.info("Loaded %d tags from %s (+ extra)", len(entries), path)
        return True

    @property
    def is_enabled(self) -> bool:
        """DB(메인+보조) 로드 성공 여부."""
        return self._enabled

    @property
    def tag_count(self) -> int:
        """로드된 태그 수 (메인+보조); 비활성이면 0."""
        return len(self._db)

    def resolve_phrase(self, phrase: str) -> tuple[TagRef, ...]:
        """하나의 후보 문구 → 1..n개의 검증된 TagRef.

        규칙 (순서대로):
        1. 정규화(norm): 소문자, 공백/하이픈→언더스코어, 끝단어가 아닌 문장부호
           제거. DB 존재 → TagRef(norm, "verified", post_count=DB값). 하이픈
           보존 variant(keep_hyphens)도 함께 조회한다 — DB의 "two-tone_hair",
           "straight-on" 같은 실존 하이픈 태그가 rule 1에서 잡혀야 한다.
        1.5 alias 확인: norm(또는 변형 규칙 2/3의 후보)이 ALIASES에 있으면
            canonical 태그로 대체해 DB 존재 확인 (silver_hair → grey_hair)
        2. "{stem}_haired" → DB에 "{stem}_hair" 존재하면 verified (alias 경유 포함)
           "{stem}_eyed"  → DB에 "{stem}_eyes" 존재하면 verified
        3. "{a}_{b}_hair" / "_eyes" 복합 신체 속성: 접두어를 '_'로 분리해 각 단어에
           접미사를 붙여 DB 존재 확인 (alias 경유 포함) — 하나 이상 존재하면 그 refs
           반환 ("long black hair" → long_hair, black_hair). 단어 "bob" → "bob_cut".
        4. 일반 다중 토큰: norm을 공백 또는 '_'로 분리한 각 토큰을 개별 DB 조회
           ("wet_road" → wet, road). 전부 verified면 목록 반환 (source="inferred")
           하나라도 실패하면 전체를 unresolved(전체 정규화명) 하나로 반환
        5. 어느 것도 못 찾으면 TagRef(norm, "unresolved", post_count=0) 하나 반환
        """
        norm = _norm(phrase)

        # 비활성(메인 DB 로드 실패) 상태면 전부 unresolved 폴백
        if not self._enabled:
            return (TagRef(tag=norm, status="unresolved", post_count=0),)

        # 규칙 1 + 1.5: 정규화 후보(하이픈 언더스코어화/보존) 순회해 DB 조회 (alias 경유 포함)
        candidates = [norm]
        hyphens_kept = _norm(phrase, keep_hyphens=True)
        if hyphens_kept != norm:
            candidates.append(hyphens_kept)
        for candidate in candidates:
            entry = self._lookup(candidate)
            if entry is not None:
                return (self._verified_ref(entry),)

        # 규칙 2: _haired/_eyed 변형
        refs = self._resolve_suffix_variant(norm)
        if refs is not None:
            return refs

        # 규칙 3: 복합 신체 속성 "{a}_{b}_hair" / "{a}_{b}_eyes"
        refs = self._resolve_compound(norm)
        if refs is not None:
            return refs

        # 규칙 4: 일반 다중 토큰(공백/언더스코어 분리) — 전부 verified일 때만 refs로 승격
        refs = self._resolve_tokens(norm)
        if refs is not None:
            return refs

        # 규칙 5: unresolved
        return (TagRef(tag=norm, status="unresolved", post_count=0),)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _lookup(self, name: str) -> TagEntry | None:
        """DB 조회 — [Ruling #5] alias(canonical 변환) 경유 포함.

        규칙 1·2·3의 후보에만 적용된다. 규칙 4(토큰 분해)에는 alias를
        적용하지 않는다 (토큰 분해보다 alias가 먼저이기 때문).
        """
        entry = self._db.get(name)
        if entry is not None:
            return entry
        canonical = ALIASES.get(name)
        return self._db.get(canonical) if canonical else None

    def _verified_ref(self, entry: TagEntry, source: str = "explicit") -> TagRef:
        """DB 엔트리 → 검증된 TagRef (post_count는 DB 값)."""
        return TagRef(
            tag=entry.name.lower(),
            status="verified",
            source=source,
            post_count=entry.post_count,
        )

    def _resolve_suffix_variant(self, norm: str) -> tuple[TagRef, ...] | None:
        """규칙 2: "{stem}_haired"→"{stem}_hair", "{stem}_eyed"→"{stem}_eyes".

        alias 경유도 허용한다 ("silver-haired" → silver_haired → silver_hair →
        ALIASES → grey_hair). 일치하는 DB 태그가 없으면 None (다음 규칙으로 진행).
        """
        for stem_suffix, db_suffix in _SUFFIX_RULES:
            if norm.endswith(stem_suffix):
                stem = norm[: -len(stem_suffix)]
                if stem:
                    entry = self._lookup(stem + db_suffix)
                    if entry is not None:
                        return (self._verified_ref(entry),)
        return None

    def _resolve_compound(self, norm: str) -> tuple[TagRef, ...] | None:
        """규칙 3: "{a}_{b}_hair"/"_eyes" 복합 속성을 단어별로 분해해 검증한다.

        하나 이상 단어가 DB(alias 경유 포함)에 있으면 그 refs만 반환한다.
        단어 "bob"은 "bob_cut"으로 매핑을 시도한다. 하나도 없으면 None.
        """
        for suffix in ("_hair", "_eyes"):
            if not norm.endswith(suffix):
                continue
            found: list[TagRef] = []
            for word in norm[: -len(suffix)].split("_"):
                if not word:
                    continue
                entry = self._lookup(word + suffix)
                if entry is None and word == "bob":
                    entry = self._lookup("bob_cut")
                if entry is not None:
                    found.append(self._verified_ref(entry))
            return tuple(found) if found else None
        return None

    def _resolve_tokens(self, norm: str) -> tuple[TagRef, ...] | None:
        """규칙 4: norm을 '_'로 분리한 토큰 전부가 개별 태그로 존재해야 목록 반환.

        [Ruling #5] "wet_road" → wet + road. 하나라도 없으면 전체를
        unresolved 처리하기 위해 None (규칙 5로 진행).
        """
        tokens = [t for t in norm.split("_") if t]
        if not tokens:
            return None
        refs: list[TagRef] = []
        for token in tokens:
            entry = self._db.get(token)  # 규칙 4에는 alias를 적용하지 않는다
            if entry is None:
                return None
            refs.append(self._verified_ref(entry, source="inferred"))
        return tuple(refs)


__all__ = ["ALIASES", "TagResolver", "bundled_extra_path"]
