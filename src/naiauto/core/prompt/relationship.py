"""캐릭터 간 관계(relationship) 정규화.

LLM 파서 출력(``LLMRelationshipModel``)을 프롬프트 컴파일러 내부 표현
(``RelationshipPrompt``)으로 변환한다.

- 액션은 화이트리스트(RELATION_ACTIONS) + 유사어(ACTION_SYNONYMS)로 결정적으로
  정규화한다 — 목록에 없는 액션은 LLM 할루시네이션으로 보고 경고 + 제외 (§7)
- source/target id가 알려진 캐릭터(character_ids)에 없으면 경고 + 제외
- mutual=True면 양방향 2개 엔트리로 확장한다

core/ 모듈이므로 Qt 의존성이 없다.
"""

from __future__ import annotations

from naiauto.core.prompt.schema import LLMRelationshipModel, RelationshipPrompt

#: 허용 액션 화이트리스트 (snake_case 정규화명).
RELATION_ACTIONS: frozenset[str] = frozenset({
    "looking_at", "talking_to", "facing", "holding_hands", "hugging",
    "standing_next_to", "sitting_opposite", "chasing", "following",
    "pointing_at", "touching", "waving_to", "leaning_on"})

#: LLM이 자연어로 쓸 가능성이 높은 표현 → 정규화 액션 (공백 포함 원문 키).
ACTION_SYNONYMS: dict[str, str] = {
    "staring at": "looking_at", "staring": "looking_at", "watching": "looking_at",
    "gazing at": "looking_at", "gazing": "looking_at", "look at": "looking_at",
    "conversing with": "talking_to", "chatting with": "talking_to",
    "talking with": "talking_to", "speaking to": "talking_to", "talking": "talking_to",
    "embracing": "hugging", "hug": "hugging", "hand in hand": "holding_hands",
    "hands held": "holding_hands", "next to": "standing_next_to",
    "standing beside": "standing_next_to", "waving at": "waving_to",
    "face to face": "facing", "facing each other": "facing",
    "opposite": "sitting_opposite", "leaning against": "leaning_on",
}


def normalize_action(action: str) -> str | None:
    """소문자/공백→언더스코어 후, RELATION_ACTIONS 존재 또는 SYNONYMS 매핑.
    없으면 None.

    예:
        "Looking At" → "looking_at" (화이트리스트 직접 매칭)
        "staring at" → "looking_at" (유사어 매핑)
        "quantum entangling" → None (할루시네이션 방지)
    """
    norm = action.strip().lower()
    if norm in ACTION_SYNONYMS:
        return ACTION_SYNONYMS[norm]
    underscored = norm.replace(" ", "_")
    if underscored in RELATION_ACTIONS:
        return underscored
    return None


def normalize_relationships(
    raw: list[LLMRelationshipModel],
    character_ids: set[str],
) -> tuple[list[RelationshipPrompt], list[str]]:
    """(정규화된 관계 목록, 경고 목록).

    - source/target id가 character_ids에 없으면 경고 + 제외
    - normalize_action이 None이면 경고 + 제외 (hallucinated action 방지)
    - mutual=True면 양방향 2개 엔트리 (source→target, target→source, mutual=True)
    - mutual=False면 단방향 1개
    """
    rels: list[RelationshipPrompt] = []
    warns: list[str] = []
    for rel in raw:
        if rel.source not in character_ids or rel.target not in character_ids:
            warns.append(
                f"관계에서 알 수 없는 캐릭터 id 제외: '{rel.source}'→'{rel.target}' "
                f"(action='{rel.action}')"
            )
            continue
        action = normalize_action(rel.action)
        if action is None:
            warns.append(
                f"관계에서 알 수 없는 액션 제외: '{rel.source}'→'{rel.target}' "
                f"(action='{rel.action}')"
            )
            continue
        rels.append(
            RelationshipPrompt(source=rel.source, target=rel.target, action=action, mutual=rel.mutual)
        )
        if rel.mutual:
            rels.append(
                RelationshipPrompt(source=rel.target, target=rel.source, action=action, mutual=True)
            )
    return rels, warns


__all__ = ["RELATION_ACTIONS", "ACTION_SYNONYMS", "normalize_action", "normalize_relationships"]
