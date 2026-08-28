"""구조화 프롬프트 → NovelAI V5 프롬프트 문자열 포맷터.

``schema.ScenePrompt``/``CharacterPrompt``/``RelationshipPrompt``/``TagRef``로부터
NovelAI V5 생성 요청에 직접 넣을 수 있는 문자열 (base_prompt, negative_prompt)을
조립한다.

모드 (스펙 §14):
  tag     — 검증된 태그만, 쉼표 결합
  hybrid  — 태그 + 자연어 문장 (기본값)
  natural — 자연어 중심 (scene/char의 description·natural_language)

정렬 규칙 (스펙 §53): base = [count 태그] + scene 태그 + [관계 태그형] + camera + style + NL 단락
캐릭터 prompt: appearance/clothing/pose/expression 태그 + NL.
count 태그는 base에만 (스펙 §21, §55). scene 태그에 이미 count 태그가 있으면 중복 제거.
Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

import re

from naiauto.core.prompt.schema import CharacterPrompt, RelationshipPrompt, ScenePrompt, TagRef

#: 단수 주제어 → 복수형 (count 태그·상호 관계 문장의 명사에 사용).
SUBJECT_PLURALS: dict[str, str] = {
    "girl": "girls", "boy": "boys", "man": "men", "woman": "women",
    "child": "children", "cat": "cats", "dog": "dogs",
}

#: count 태그 정규식 ("2girls", "1girl" 등) — scene 태그 중복 제거에 사용.
COUNT_TAG_RE = re.compile(r"^\d+(girls|girl|boys|boy|men|man|women|woman|children|child|cats|cat|dogs|dog)$")

#: 정규화 액션(snake_case) → 자연어 구절 (관계 문장용).
ACTION_PHRASES: dict[str, str] = {
    "looking_at": "looking at", "talking_to": "talking to", "facing": "facing",
    "holding_hands": "holding hands", "hugging": "hugging",
    "standing_next_to": "standing next to", "sitting_opposite": "sitting opposite",
    "chasing": "chasing", "following": "following", "pointing_at": "pointing at",
    "touching": "touching", "waving_to": "waving to", "leaning_on": "leaning on",
}

#: 최종 조립 후 남는 중복 쉼표/공백 정리 ("tag ,, tag" → "tag, tag").
_SANITIZE_RE = re.compile(r"\s*,\s*")


class PromptFormatter:
    """구조화 프롬프트 → NovelAI V5 문자열.

    모드 (스펙 §14):
      tag     — 검증된 태그만, 쉼표 결합
      hybrid  — 태그 + 자연어 문장 (기본값)
      natural — 자연어 중심 (scene/char의 description·natural_language)

    정렬 규칙 (스펙 §53): base = [count 태그] + scene 태그 + [관계 태그형] + camera + style + NL 단락
    캐릭터 prompt: appearance/clothing/pose/expression 태그 + NL.
    count 태그는 base에만 (스펙 §21, §55). scene 태그에 이미 count 태그가 있으면 중복 제거.
    """

    def __init__(self, *, preserve_natural_language: bool = True,
                 relationship_style: str = "natural") -> None:
        self.preserve_natural_language = preserve_natural_language
        # relationship_style: "natural" | "tag"
        self.relationship_style = relationship_style

    def format(self, *, scene: ScenePrompt, characters: tuple[CharacterPrompt, ...],
               relationships: tuple[RelationshipPrompt, ...],
               negative_tags: tuple[TagRef, ...], mode: str) -> tuple[str, str]:
        """(base_prompt, negative_prompt) 반환."""
        base = self._base_prompt(scene, characters, relationships, mode)
        negative = ", ".join(t.tag for t in negative_tags if t.status == "verified")
        return self._sanitize(base), self._sanitize(negative)

    def count_tag(self, subjects: tuple[str, ...]) -> str:
        """subjects가 모두 같고 단수형 SUBJECT_PLURALS에 있으면 "{n}{plural}" (n>=2) /
        "1girl" 등 (n==1). 그 외엔 ""."""
        if not subjects:
            return ""
        first = subjects[0]
        if first not in SUBJECT_PLURALS:
            return ""
        if any(s != first for s in subjects):
            return ""
        if len(subjects) >= 2:
            return f"{len(subjects)}{SUBJECT_PLURALS[first]}"
        return f"{len(subjects)}{first}"

    def relationship_sentences(self, relationships: tuple[RelationshipPrompt, ...],
                               characters: tuple[CharacterPrompt, ...]) -> list[str]:
        """관계 → 자연어 문장 목록.

        상호 쌍: "The two characters are {phrase} each other." (주제어 없으면 characters)
        단방향 + 위치 힌트: "The character on the {left} is {phrase} the character on the {right}."
        단방향 + 힌트 없음: "Character {src} is {phrase} Character {dst}."
        """
        return self._relationship_sentences(relationships, characters, "characters")

    def relationship_tag_segment(self, relationships: tuple[RelationshipPrompt, ...]) -> str:
        """관계 태그형 세그먼트 (relationship_style="tag"용).

        상호 쌍: "{src}#{action} {dst}#{action}", 단방향: "{src}#{action}".
        복수 관계는 ", " 결합. 상호 쌍은 중복 제거.
        """
        segments: list[str] = []
        used: set[int] = set()
        for i, r in enumerate(relationships):
            if i in used:
                continue
            partner = self._mutual_partner_index(relationships, i, used)
            used.add(i)
            if partner is not None or r.mutual:
                if partner is not None:
                    used.add(partner)
                segments.append(f"{r.source}#{r.action} {r.target}#{r.action}")
            else:
                segments.append(f"{r.source}#{r.action}")
        return ", ".join(segments)

    def character_prompt_text(self, character: CharacterPrompt, mode: str) -> str:
        """캐릭터용 문자열 — base와 독립적으로 조립 (컴파일러가 사용).

        모든 모드: tags를 ", " 결합. hybrid/natural + preserve_nl이면
        "\n\n" + natural_language 추가 (tags가 비면 NL만).
        """
        tag_text = ", ".join(t.tag for t in character.tags)
        if mode in ("hybrid", "natural") and self.preserve_natural_language:
            if character.natural_language:
                if tag_text:
                    return f"{tag_text}\n\n{character.natural_language}"
                return character.natural_language
        return tag_text

    # -- 내부 헬퍼 ----------------------------------------------------------

    def _base_prompt(self, scene: ScenePrompt, characters: tuple[CharacterPrompt, ...],
                     relationships: tuple[RelationshipPrompt, ...], mode: str) -> str:
        """모드별 base prompt 조립."""
        if mode == "natural":
            return "\n".join(self._natural_parts(scene, characters, relationships))
        count = self.count_tag(scene.subjects)
        scene_tags = [t.tag for t in scene.tags if not COUNT_TAG_RE.match(t.tag)]
        base_tags = ([count] if count else []) + scene_tags
        if mode != "natural" and self.relationship_style == "tag":
            segment = self.relationship_tag_segment(relationships)
            if segment:
                base_tags.append(segment)
        tag_line = ", ".join(t for t in base_tags if t)
        if mode == "hybrid" and self.preserve_natural_language:
            segments = self._hybrid_segments(scene, characters, relationships)
            if segments:
                return f"{tag_line}\n\n" + "\n".join(segments)
        return tag_line

    def _hybrid_segments(self, scene: ScenePrompt, characters: tuple[CharacterPrompt, ...],
                         relationships: tuple[RelationshipPrompt, ...]) -> list[str]:
        """hybrid 모드 NL 세그먼트: NL(또는 description) → camera → style → 관계 문장."""
        segments: list[str] = []
        nl = scene.natural_language or scene.description
        if nl:
            segments.append(nl)
        if scene.camera:
            segments.append(scene.camera)
        if scene.style:
            segments.append(scene.style)
        segments.extend(
            self._relationship_sentences(
                relationships, characters, self._subject_noun(scene)
            )
        )
        return segments

    def _natural_parts(self, scene: ScenePrompt, characters: tuple[CharacterPrompt, ...],
                       relationships: tuple[RelationshipPrompt, ...]) -> list[str]:
        """natural 모드 문장 목록: NL → description → 관계 문장 → camera → style."""
        parts: list[str] = []
        if scene.natural_language:
            parts.append(scene.natural_language)
        if scene.description:
            parts.append(scene.description)
        if not parts:
            parts.append(", ".join(t.tag for t in scene.tags))
        parts.extend(
            self._relationship_sentences(
                relationships, characters, self._subject_noun(scene)
            )
        )
        if scene.camera:
            parts.append(scene.camera)
        if scene.style:
            parts.append(scene.style)
        return parts

    def _subject_noun(self, scene: ScenePrompt) -> str:
        """scene.subjects가 모두 같고 복수형이 있으면 복수 명사, 아니면 "characters"."""
        subjects = scene.subjects
        if subjects and all(s == subjects[0] for s in subjects) and subjects[0] in SUBJECT_PLURALS:
            return SUBJECT_PLURALS[subjects[0]]
        return "characters"

    def _relationship_sentences(self, relationships: tuple[RelationshipPrompt, ...],
                                characters: tuple[CharacterPrompt, ...],
                                subject_noun: str) -> list[str]:
        """관계 → 자연어 문장 (subject_noun은 상호 쌍 문장의 명사)."""
        sentences: list[str] = []
        used: set[int] = set()
        by_id = {c.id: c for c in characters}
        for i, r in enumerate(relationships):
            if i in used:
                continue
            partner = self._mutual_partner_index(relationships, i, used)
            used.add(i)
            phrase = self._action_phrase(r.action)
            if partner is not None or r.mutual:
                if partner is not None:
                    used.add(partner)
                sentences.append(f"The two {subject_noun} are {phrase} each other.")
                continue
            src = by_id.get(r.source)
            dst = by_id.get(r.target)
            pos_src = src.position_hint if src else ""
            pos_dst = dst.position_hint if dst else ""
            if pos_src and pos_dst:
                sentences.append(
                    f"The character on the {pos_src} is {phrase} "
                    f"the character on the {pos_dst}."
                )
            else:
                sentences.append(f"Character {r.source} is {phrase} Character {r.target}.")
        return sentences

    def _mutual_partner_index(self, relationships: tuple[RelationshipPrompt, ...],
                              i: int, used: set[int]) -> int | None:
        """양방향 + 같은 액션의 상호 쌍 파트너 인덱스 (이미 사용된 항목 제외). 없으면 None."""
        r = relationships[i]
        for j, r2 in enumerate(relationships):
            if j == i or j in used:
                continue
            if r2.source == r.target and r2.target == r.source and r2.action == r.action:
                return j
        return None

    def _action_phrase(self, action: str) -> str:
        """정규화 액션 → 자연어 구절 (ACTION_PHRASES 없으면 언더스코어→공백)."""
        return ACTION_PHRASES.get(action, action.replace("_", " "))

    def _sanitize(self, text: str) -> str:
        """앞뒤 공백/중복 쉼표 정리 ("tag ,, tag" → "tag, tag")."""
        return _SANITIZE_RE.sub(", ", text).strip()


__all__ = ["SUBJECT_PLURALS", "COUNT_TAG_RE", "ACTION_PHRASES", "PromptFormatter"]
