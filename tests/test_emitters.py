"""emitter 3종 테스트 — 파일시스템 없이 CompiledPrompt만으로 검증한다."""

from naiauto.core.prompt.emitters import (
    MUTUAL_RELATION_TAGS,
    POSITION_TAGS,
    character_regions,
    lora_tags,
    negative_prompt,
    relationship_tags,
    split_phrase,
)
from naiauto.core.prompt.schema import (
    CharacterPrompt,
    CompiledPrompt,
    RelationshipPrompt,
    ScenePrompt,
    TagRef,
)
from naiauto.core.prompt.targets import LoraEntry, TargetPreset

PRESET = TargetPreset(
    id="demo",
    name="Demo",
    quality_prefix=("masterpiece", "best quality"),
    default_negative=("lowres", "worst quality"),
)


def char(cid, tags, *, hint="", cx=None, cy=None, negative=(), nl=""):
    return CharacterPrompt(
        id=cid,
        tags=tuple(TagRef(t) for t in tags),
        position_hint=hint,
        center_x=cx,
        center_y=cy,
        negative_tags=tuple(negative),
        natural_language=nl,
    )


def compiled(*, scene_tags=("rain", "night"), subjects=(), characters=(), relationships=(),
             negative="", camera="", composition="", style="", nl="", target="demo"):
    return CompiledPrompt(
        base_prompt="",
        negative_prompt=negative,
        scene=ScenePrompt(
            tags=tuple(TagRef(t) for t in scene_tags),
            subjects=tuple(subjects),
            natural_language=nl,
            camera=camera,
            composition=composition,
            style=style,
        ),
        characters=tuple(characters),
        relationships=tuple(relationships),
        mode="hybrid",
        warnings=(),
        unresolved=(),
        target=target,
    )


# --- split_phrase ----------------------------------------------------------


def test_split_phrase_splits_on_commas_and_strips():
    assert split_phrase("low angle shot,  from below ,") == ["low angle shot", "from below"]


def test_split_phrase_empty_is_empty_list():
    assert split_phrase("") == []
    assert split_phrase("  ,  , ") == []


# --- 위치 태그 -------------------------------------------------------------


def test_position_tags_cover_all_hints_except_center():
    assert POSITION_TAGS["left"] == "on the left"
    assert POSITION_TAGS["far_right"] == "on the far right"
    assert "center" not in POSITION_TAGS


# --- 관계 태그 -------------------------------------------------------------


def test_relationship_tags_maps_mutual_only():
    rels = (RelationshipPrompt(source="c1", target="c2", action="hugging", mutual=True),)
    tags, warnings = relationship_tags(rels)
    assert tags == ["hug"]
    assert warnings == []


def test_relationship_tags_drops_one_way_with_warning():
    rels = (RelationshipPrompt(source="c1", target="c2", action="hugging", mutual=False),)
    tags, warnings = relationship_tags(rels)
    assert tags == []
    assert len(warnings) == 1
    assert "hugging" in warnings[0]


def test_relationship_tags_drops_unmapped_mutual_with_warning():
    rels = (RelationshipPrompt(source="c1", target="c2", action="chasing", mutual=True),)
    tags, warnings = relationship_tags(rels)
    assert tags == []
    assert len(warnings) == 1
    assert "chasing" in warnings[0]


def test_relationship_tags_deduplicates():
    rels = (
        RelationshipPrompt(source="c1", target="c2", action="looking_at", mutual=True),
        RelationshipPrompt(source="c2", target="c1", action="looking_at", mutual=True),
    )
    tags, _ = relationship_tags(rels)
    assert tags == [MUTUAL_RELATION_TAGS["looking_at"]]


# --- 영역 좌표 -------------------------------------------------------------


def test_character_regions_splits_evenly_for_two():
    chars = (char("c1", ["a"], cx=0.30), char("c2", ["b"], cx=0.70))
    regions = character_regions(chars)
    assert [(r.character.id, r.x, r.width) for r in regions] == [
        ("c1", 0.0, 0.5),
        ("c2", 0.5, 0.5),
    ]
    assert all(r.y == 0.0 and r.height == 1.0 for r in regions)


def test_character_regions_sorts_by_center_x():
    chars = (char("c1", ["a"], cx=0.85), char("c2", ["b"], cx=0.15))
    assert [r.character.id for r in character_regions(chars)] == ["c2", "c1"]


def test_character_regions_missing_center_defaults_to_half_and_keeps_order():
    chars = (char("c1", ["a"]), char("c2", ["b"]))
    assert [r.character.id for r in character_regions(chars)] == ["c1", "c2"]


def test_character_regions_three_way_split():
    chars = (char("c1", ["a"], cx=0.15), char("c2", ["b"], cx=0.5), char("c3", ["c"], cx=0.85))
    widths = [round(r.width, 4) for r in character_regions(chars)]
    assert widths == [0.3333, 0.3333, 0.3333]


def test_character_regions_empty():
    assert character_regions(()) == []


# --- LoRA 태그 -------------------------------------------------------------


def test_lora_tags_strips_extension_and_uses_weight():
    entry = LoraEntry(id="kafka", file="kafka_illustrious.safetensors", weight=0.8)
    assert lora_tags({"c1": entry}) == ["<lora:kafka_illustrious:0.8>"]


def test_lora_tags_deduplicates_same_file():
    entry = LoraEntry(id="kafka", file="kafka.safetensors", weight=0.8)
    assert lora_tags({"c1": entry, "c2": entry}) == ["<lora:kafka:0.8>"]


def test_lora_tags_empty_when_no_assignment():
    assert lora_tags({}) == []


# --- 네거티브 --------------------------------------------------------------


def test_negative_prompt_merges_preset_scene_and_characters():
    result = negative_prompt(
        compiled(negative="bad hands", characters=(char("c1", ["a"], negative=("blurry",)),)),
        PRESET,
    )
    assert result == "lowres, worst quality, bad hands, blurry"


def test_negative_prompt_deduplicates_keeping_order():
    result = negative_prompt(
        compiled(negative="lowres", characters=(char("c1", ["a"], negative=("lowres",)),)),
        PRESET,
    )
    assert result == "lowres, worst quality"
