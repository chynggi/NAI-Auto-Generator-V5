"""CompiledPrompt → 출력 대상별 프롬프트 방출기(emitter).

NovelAI는 캐릭터별 프롬프트가 분리되지만 로컬 SDXL은 단일 프롬프트다.
같은 ``CompiledPrompt``에서 세 가지 출력을 만든다:

- ``emit_sequential``   — 단일 Positive/Negative. 어디서나 동작한다
- ``emit_couple_mask``  — ``COUPLE MASK(...)`` (asagi4/comfyui-prompt-control)
- ``emit_regional_json``— 구조화 JSON (좌표 0..1 정규화)

모두 ``CompiledPrompt``만 읽는 순수 함수다 — I/O도, Qt 의존성도 없다.
프리셋 로딩은 ``targets``가 맡는다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from naiauto.core.prompt.formatter import COUNT_TAG_RE, count_tag
from naiauto.core.prompt.merge import merge_negatives
from naiauto.core.prompt.schema import CharacterPrompt, CompiledPrompt, RelationshipPrompt
from naiauto.core.prompt.targets import LoraEntry, TargetPreset

__all__ = [
    "POSITION_TAGS",
    "MUTUAL_RELATION_TAGS",
    "CharacterRegion",
    "split_phrase",
    "relationship_tags",
    "character_regions",
    "lora_tags",
    "negative_prompt",
    "emit_sequential",
    "emit_couple_mask",
    "emit_regional_json",
]

#: position_hint의 수평 토큰 → 태그. "center"는 노이즈라 태그를 만들지 않는다.
POSITION_TAGS: dict[str, str] = {
    "far_left": "on the far left",
    "left": "on the left",
    "right": "on the right",
    "far_right": "on the far right",
}

#: 상호(mutual) 관계 → Danbooru 실존 태그. 단방향 관계는 단일 프롬프트로
#: 표현할 수단이 없어 드롭한다 (경고를 남긴다).
MUTUAL_RELATION_TAGS: dict[str, str] = {
    "holding_hands": "holding hands",
    "hugging": "hug",
    "looking_at": "eye contact",
    "facing": "facing another",
}

#: 쉼표 앞뒤 공백을 ", "로 통일한다 (쉼표 연속 자체는 합치지 않는다).
#: formatter._sanitize와 같은 규칙이지만 그쪽은 비공개 메서드라 여기 따로 둔다.
_SANITIZE_RE = re.compile(r"\s*,\s*")

#: position_hint 토큰 중 수평 태그를 만들지 않는 것들. "top"/"bottom"은 세로축이라
#: POSITION_TAGS에 없고, "center"는 POSITION_TAGS에 없는 게 의도(노이즈라 태그 없음)라
#: 실수로 빠뜨린 게 아님을 명시하려고 여기 그대로 나열해 둔다.
_NON_HORIZONTAL_TOKENS = ("top", "bottom", "center")


@dataclass(frozen=True)
class CharacterRegion:
    """캐릭터 1명이 차지하는 정규화 영역 (0..1)."""

    character: CharacterPrompt
    x: float
    y: float
    width: float
    height: float


def split_phrase(text: str) -> list[str]:
    """쉼표로 쪼개 공백을 다듬고 빈 조각을 버린다.

    LLM이 camera를 "low angle shot, from below"처럼 문장으로 줄 때 태그화한다.
    """
    return [part.strip() for part in text.split(",") if part.strip()]


def relationship_tags(
    relationships: tuple[RelationshipPrompt, ...],
) -> tuple[list[str], list[str]]:
    """(태그 목록, 경고 목록). 상호 관계 중 매핑된 것만 태그가 된다."""
    tags: list[str] = []
    warnings: list[str] = []
    seen_tags: set[str] = set()
    seen_warnings: set[str] = set()
    for rel in relationships:
        tag = MUTUAL_RELATION_TAGS.get(rel.action) if rel.mutual else None
        if tag is None:
            warning = (
                f"The relationship between {rel.source} and {rel.target} ({rel.action}) "
                "has no equivalent tag for this target and was left out of the prompt."
            )
            if warning not in seen_warnings:
                seen_warnings.add(warning)
                warnings.append(warning)
            continue
        if tag not in seen_tags:
            seen_tags.add(tag)
            tags.append(tag)
    return tags, warnings


def character_regions(characters: tuple[CharacterPrompt, ...]) -> list[CharacterRegion]:
    """캐릭터를 center_x 순으로 정렬해 가로 균등 분할 영역을 만든다.

    center_x가 없으면 0.5로 보고, 같은 값끼리는 원래 순서를 유지한다.
    """
    if not characters:
        return []
    ordered = sorted(
        enumerate(characters),
        key=lambda pair: (0.5 if pair[1].center_x is None else pair[1].center_x, pair[0]),
    )
    total = len(ordered)
    width = 1.0 / total
    return [
        CharacterRegion(character=char, x=index * width, y=0.0, width=width, height=1.0)
        for index, (_, char) in enumerate(ordered)
    ]


def lora_tags(loras: Mapping[str, LoraEntry]) -> list[str]:
    """캐릭터별 LoRA 배정 → ``<lora:stem:weight>`` 목록 (stem 기준 중복 제거).

    ``file``이 아니라 ``stem``으로 중복을 없앤다 — A1111/ComfyUI는
    ``<lora:name:w>``를 이름으로 찾으므로, 경로만 다르고 stem이 같은 두 파일도
    태그로는 결국 하나로 뭉개진다. 두 번 넣어봐야 한 번보다 나을 게 없다.
    """
    tags: list[str] = []
    seen: set[str] = set()
    for entry in loras.values():
        if entry.stem in seen:
            continue
        seen.add(entry.stem)
        tags.append(f"<lora:{entry.stem}:{entry.weight:g}>")
    return tags


def negative_prompt(compiled: CompiledPrompt, preset: TargetPreset) -> str:
    """프리셋 기본 네거티브 + 씬 네거티브 + 전 캐릭터 네거티브 (순서 유지 중복 제거)."""
    parts = [", ".join(preset.default_negative), compiled.negative_prompt]
    parts.extend(", ".join(char.negative_tags) for char in compiled.characters)
    merged = ""
    for part in parts:
        merged = merge_negatives(merged, part)
    return merged


def _position_tag(char: CharacterPrompt, total: int, preset: TargetPreset) -> str:
    """캐릭터의 위치 태그. 1인이거나 프리셋이 끄면 "" (혼자인데 위치 태그는 구도만 망친다)."""
    if total < 2 or not preset.position_tags:
        return ""
    for token in char.position_hint.split():
        if token in _NON_HORIZONTAL_TOKENS:
            continue
        tag = POSITION_TAGS.get(token)
        if tag:
            return tag
    return ""


def _character_block(
    char: CharacterPrompt,
    total: int,
    preset: TargetPreset,
    loras: Mapping[str, LoraEntry],
    *,
    with_position: bool,
) -> list[str]:
    """캐릭터 1명의 태그 조각: [위치 태그] + [LoRA 트리거] + 캐릭터 태그."""
    block: list[str] = []
    if with_position:
        position = _position_tag(char, total, preset)
        if position:
            block.append(position)
    entry = loras.get(char.id)
    if entry is not None:
        block.extend(entry.triggers)
    block.extend(ref.tag for ref in char.tags)
    return block


def _scene_tags(compiled: CompiledPrompt) -> list[str]:
    """씬 태그 — count 태그는 따로 넣으므로 여기서 제외한다."""
    return [ref.tag for ref in compiled.scene.tags if not COUNT_TAG_RE.match(ref.tag)]


def _style_tags(compiled: CompiledPrompt) -> list[str]:
    """camera/composition/style을 태그화한 목록."""
    scene = compiled.scene
    tags: list[str] = []
    for text in (scene.camera, scene.composition, scene.style):
        tags.extend(split_phrase(text))
    return tags


def _finalize(tags: list[str], preset: TargetPreset) -> str:
    """태그 목록 → 최종 문자열 (언더스코어 치환 + 빈 태그 제거 + 쉼표 공백 정리).

    빈 문자열은 버리고, 쉼표 앞뒤 공백을 ", "로 통일하고, 맨 앞뒤 쉼표/공백을
    자른다. 쉼표가 연속된 경우("a ,, b")를 하나로 합치지는 않는다 — 자연어
    문장(natural_language: "append")도 이 함수를 거치므로, 문장 속 쉼표 연속을
    임의로 뭉개지 않기 위해서다.

    ``<lora:...>`` 태그는 치환에서 제외한다 — 파일명의 언더스코어를 공백으로
    바꾸면 LoRA를 못 찾는다 (``kafka_illustrious`` → ``kafka illustrious``).
    """
    parts: list[str] = []
    for tag in tags:
        if not tag:
            continue
        if preset.underscore_to_space and not tag.startswith("<lora:"):
            tag = tag.replace("_", " ")
        parts.append(tag)
    text = ", ".join(parts)
    return _SANITIZE_RE.sub(", ", text).strip().strip(",").strip()


def _global_tags(
    compiled: CompiledPrompt,
    preset: TargetPreset,
    loras: Mapping[str, LoraEntry],
) -> list[str]:
    """캐릭터 블록을 뺀 전역 태그: LoRA 태그 + 품질 프리픽스 + count 태그."""
    tags = lora_tags(loras)
    tags.extend(preset.quality_prefix)
    count = count_tag(compiled.scene.subjects)
    if count:
        tags.append(count)
    return tags


def _trailing_tags(compiled: CompiledPrompt, preset: TargetPreset) -> list[str]:
    """캐릭터 블록 뒤에 오는 것: 씬 태그 + 관계 태그 + camera/style + NL + 품질 서픽스."""
    tags = _scene_tags(compiled)
    rel_tags, _ = relationship_tags(compiled.relationships)
    tags.extend(rel_tags)
    tags.extend(_style_tags(compiled))
    if preset.natural_language == "append" and compiled.scene.natural_language:
        tags.append(compiled.scene.natural_language)
    tags.extend(preset.quality_suffix)
    return tags


def emit_sequential(
    compiled: CompiledPrompt,
    preset: TargetPreset,
    loras: Mapping[str, LoraEntry] | None = None,
) -> tuple[str, str]:
    """단일 Positive/Negative 문자열. 어떤 UI에서도 그대로 붙여넣을 수 있다.

    순서: [LoRA] [품질 프리픽스] [count] [캐릭터 블록…] [씬] [관계] [camera/style]
    [NL?] [품질 서픽스].
    """
    loras = loras or {}
    tags = _global_tags(compiled, preset, loras)
    total = len(compiled.characters)
    for char in compiled.characters:
        tags.extend(_character_block(char, total, preset, loras, with_position=True))
    tags.extend(_trailing_tags(compiled, preset))
    return _finalize(tags, preset), negative_prompt(compiled, preset)


def _coord(value: float) -> str:
    """좌표를 프롬프트에 넣을 짧은 문자열로 (0.3333333 → "0.333", 1.0 → "1")."""
    return f"{round(value, 3):g}"


def emit_couple_mask(
    compiled: CompiledPrompt,
    preset: TargetPreset,
    loras: Mapping[str, LoraEntry] | None = None,
    *,
    resolution: tuple[int, int] | None = None,
) -> tuple[str, str]:
    """``COUPLE MASK(...)`` 형식 (asagi4/comfyui-prompt-control).

    글로벌 라인 + 캐릭터별 ``COUPLE`` 라인. 캐릭터가 2명 미만이면 영역 분할의
    의미가 없으므로 ``COUPLE`` 라인도 ``MASK_SIZE``도 만들지 않고 캐릭터 태그를
    글로벌 라인에 합친다.

    위치 태그는 넣지 않는다 — 좌표가 이미 그 일을 하며 중복은 구도를 왜곡한다.
    negative는 확장이 영역별 분할을 지원하지 않으므로 단일 문자열이다.
    """
    loras = loras or {}
    negative = negative_prompt(compiled, preset)
    regions = character_regions(compiled.characters)
    total = len(compiled.characters)

    global_tags = _global_tags(compiled, preset, loras)
    if total < 2:
        for char in compiled.characters:
            global_tags.extend(
                _character_block(char, total, preset, loras, with_position=False)
            )
    global_tags.extend(_trailing_tags(compiled, preset))
    global_line = _finalize(global_tags, preset)

    if total < 2:
        return global_line, negative

    size = preset.mask_size or resolution
    if size is not None:
        global_line = f"MASK_SIZE({size[0]}, {size[1]}) {global_line}"

    lines = [global_line]
    for region in regions:
        block = _character_block(
            region.character, total, preset, loras, with_position=False
        )
        mask = (
            f"MASK({_coord(region.x)} {_coord(region.x + region.width)}, "
            f"{_coord(region.y)} {_coord(region.y + region.height)})"
        )
        lines.append(f"COUPLE {mask} {_finalize(block, preset)}")
    return "\n".join(lines), negative


def emit_regional_json(
    compiled: CompiledPrompt,
    preset: TargetPreset,
    loras: Mapping[str, LoraEntry] | None = None,
) -> dict:
    """구조화 영역 출력 — 좌표는 0..1 정규화 (해상도 곱셈은 소비자 몫).

    LoRA는 ``positive``에 합치지 않고 ``lora`` 키로 분리해 둔다 — 소비하는
    쪽이 LoraLoader 노드로 결선할지 텍스트 태그로 넘길지 고를 수 있어야 한다.
    전역 프롬프트에도 ``<lora:...>`` 태그를 넣지 않는 이유가 같다.
    """
    loras = loras or {}
    global_tags = _global_tags(compiled, preset, {})  # LoRA 태그 제외
    global_tags.extend(_trailing_tags(compiled, preset))
    regions: list[dict] = []
    for region in character_regions(compiled.characters):
        char = region.character
        entry = loras.get(char.id)
        item: dict = {
            "id": char.id,
            "positive": _finalize([ref.tag for ref in char.tags], preset),
            "negative": _finalize(list(char.negative_tags), preset),
            "x": round(region.x, 4),
            "y": round(region.y, 4),
            "width": round(region.width, 4),
            "height": round(region.height, 4),
            "center_x": char.center_x,
            "center_y": char.center_y,
        }
        if entry is not None:
            item["lora"] = {
                "file": entry.file,
                "weight": entry.weight,
                "triggers": list(entry.triggers),
            }
        regions.append(item)
    return {
        "target": compiled.target,
        "global": {
            "positive": _finalize(global_tags, preset),
            "negative": negative_prompt(compiled, preset),
        },
        "regions": regions,
    }
