"""컴파일 결과 → 기존 생성 파이프라인 연동 (Merge 레이어).

``CompiledPrompt``(컴파일러 내부 표현)을 UI/``GenerationRequest``가 바로 쓸 수
있는 형태로 변환한다: 최종 프롬프트 문자열 + 기존 ``CharacterCaption`` 목록.
캐릭터 프롬프트 스키마(``core.api.models.CharacterCaption``)를 재사용하므로
API 계층은 수정하지 않는다 — 의존 방향은 prompt → api.models 단방향이다.

- prompt = compiled.base_prompt (이미 최종 문자열, 스펙 §22)
- negative = 기존 사용자 negative와 컴파일 negative의 중복 없는 병합
- characters = CharacterCaption(prompt_text, negative_tags, 좌표 or 0.5) —
  좌표 미지정은 0.5로 강제 (V4 이래 client의 use_coords=False 규칙과 동일)

Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from naiauto.core.api.models import CharacterCaption
from naiauto.core.prompt.schema import CompiledPrompt
from naiauto.core.prompt.targets import NOVELAI_TARGET_ID

__all__ = ["MergeResult", "to_generation_data", "merge_negatives"]


@dataclass(frozen=True)
class MergeResult:
    """편집기/GenerationRequest와 호환되는 최종 병합 데이터."""

    prompt: str
    negative_prompt: str
    characters: tuple[CharacterCaption, ...]


def merge_negatives(existing: str, compiled: str) -> str:
    """기존 사용자 negative와 컴파일 negative를 중복 없이 병합한다 (스펙 §22).

    쉼표 단위로 분할 → strip → 빈값 제거 → 등장 순서 유지 중복 제거.
    """
    parts: list[str] = []
    for chunk in (existing, compiled):
        for item in chunk.split(","):
            item = item.strip()
            if item and item not in parts:
                parts.append(item)
    return ", ".join(parts)


def to_generation_data(compiled: CompiledPrompt, *, existing_negative: str = "") -> MergeResult:
    """CompiledPrompt → MergeResult (기존 편집기/GenerationRequest 호환).

    - ``prompt`` = compiled.base_prompt (이미 최종 문자열)
    - ``negative_prompt`` = 기존 negative + 컴파일 negative (스펙 §22)
    - ``characters`` = CharacterCaption(prompt=char.prompt_text, uc=negative_tags join,
      center_x/center_y=좌표 or 0.5).
      좌표 미지정은 client가 0.5로 강제하는 기존 규칙을 그대로 따른다.
      ``prompt_text``가 비어 있으면(수동 구성 등) verified/inferred 태그를
      ", "로 이어붙인 것으로 대체한다.

    ``compiled.target``이 "novelai"가 아니면 ``characters``는 항상 빈 튜플이다.
    """
    # 로컬 타깃은 캐릭터별 프롬프트 개념이 없다 — 캐릭터 태그는 이미 본문에
    # 합쳐져 있으므로 CharacterCaption을 만들지 않는다.
    if compiled.target != NOVELAI_TARGET_ID:
        return MergeResult(
            prompt=compiled.base_prompt,
            negative_prompt=merge_negatives(existing_negative, compiled.negative_prompt),
            characters=(),
        )

    characters = tuple(
        CharacterCaption(
            prompt=char.prompt_text
            or ", ".join(t.tag for t in char.tags if t.status in ("verified", "inferred")),
            uc=", ".join(char.negative_tags),
            center_x=char.center_x if char.center_x is not None else 0.5,
            center_y=char.center_y if char.center_y is not None else 0.5,
        )
        for char in compiled.characters
    )
    return MergeResult(
        prompt=compiled.base_prompt,
        negative_prompt=merge_negatives(existing_negative, compiled.negative_prompt),
        characters=characters,
    )
