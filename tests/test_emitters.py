"""emitter 3종 테스트 — 파일시스템 없이 CompiledPrompt만으로 검증한다."""

from naiauto.core.prompt.emitters import (
    MUTUAL_RELATION_TAGS,
    POSITION_TAGS,
    _finalize,
    character_regions,
    emit_sequential,
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


def test_relationship_tags_deduplicates_identical_warnings():
    rels = (
        RelationshipPrompt(source="c1", target="c2", action="chasing", mutual=True),
        RelationshipPrompt(source="c1", target="c2", action="chasing", mutual=True),
    )
    _, warnings = relationship_tags(rels)
    assert len(warnings) == 1


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
    regions = character_regions(chars)
    assert [round(r.width, 4) for r in regions] == [0.3333, 0.3333, 0.3333]
    # 영역이 빈틈·겹침 없이 이어지고 오른쪽 끝에 닿는다.
    assert [round(r.x, 4) for r in regions] == [0.0, 0.3333, 0.6667]
    assert round(regions[-1].x + regions[-1].width, 4) == 1.0


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


def test_lora_tags_deduplicates_same_stem_from_different_paths():
    """A1111/ComfyUI는 <lora:name:w>를 이름으로 찾으므로 stem이 같으면 같은 태그다."""
    a = LoraEntry(id="a", file="characters/kafka.safetensors", weight=0.8)
    b = LoraEntry(id="b", file="outfits/kafka.safetensors", weight=0.5)
    assert lora_tags({"c1": a, "c2": b}) == ["<lora:kafka:0.8>"]


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


# --- _finalize ---------------------------------------------------------------


def test_finalize_replaces_underscores_but_spares_lora_tags():
    tags = ["<lora:kafka_illustrious:0.8>", "silver_hair", "school_uniform"]
    assert _finalize(tags, PRESET) == "<lora:kafka_illustrious:0.8>, silver hair, school uniform"


def test_finalize_keeps_underscores_when_preset_disables_replacement():
    preset = TargetPreset(id="p", name="P", underscore_to_space=False)
    assert _finalize(["silver_hair"], preset) == "silver_hair"


def test_finalize_drops_empty_tags():
    assert _finalize(["a", "", "b"], PRESET) == "a, b"


def test_finalize_normalises_whitespace_around_commas():
    assert _finalize(["a ,  b"], PRESET) == "a, b"


# --- emit_sequential -------------------------------------------------------


def test_sequential_assembly_order():
    result, _ = emit_sequential(
        compiled(
            scene_tags=("rain", "night", "alley"),
            subjects=("girl", "girl"),
            characters=(
                char("c1", ["silver_hair"], hint="left", cx=0.30),
                char("c2", ["black_hair"], hint="right", cx=0.70),
            ),
            relationships=(
                RelationshipPrompt(source="c1", target="c2", action="hugging", mutual=True),
            ),
            camera="low angle shot, from below",
        ),
        PRESET,
        {},
    )
    assert result == (
        "masterpiece, best quality, 2girls, "
        "on the left, silver hair, on the right, black hair, "
        "rain, night, alley, hug, low angle shot, from below"
    )


def test_sequential_single_character_has_no_position_tag():
    result, _ = emit_sequential(
        compiled(
            scene_tags=("alley",),
            subjects=("girl",),
            characters=(char("c1", ["silver_hair"], hint="left", cx=0.30),),
        ),
        PRESET,
        {},
    )
    assert "on the left" not in result
    assert "1girl" in result


def test_sequential_no_characters_is_background_prompt():
    result, _ = emit_sequential(compiled(scene_tags=("alley", "night")), PRESET, {})
    assert result == "masterpiece, best quality, alley, night"


def test_sequential_drops_duplicate_count_tag_from_scene():
    result, _ = emit_sequential(
        compiled(scene_tags=("2girls", "rain"), subjects=("girl", "girl")), PRESET, {}
    )
    assert result.count("2girls") == 1


def test_sequential_position_tags_disabled_by_preset():
    preset = TargetPreset(id="p", name="P", position_tags=False)
    result, _ = emit_sequential(
        compiled(
            characters=(
                char("c1", ["a"], hint="left", cx=0.3),
                char("c2", ["b"], hint="right", cx=0.7),
            )
        ),
        preset,
        {},
    )
    assert "on the left" not in result


def test_sequential_underscore_to_space_can_be_off():
    preset = TargetPreset(id="p", name="P", underscore_to_space=False)
    result, _ = emit_sequential(
        compiled(scene_tags=(), characters=(char("c1", ["silver_hair"]),)), preset, {}
    )
    assert "silver_hair" in result


def test_sequential_natural_language_drop_and_append():
    drop = TargetPreset(id="d", name="D", natural_language="drop")
    append = TargetPreset(id="a", name="A", natural_language="append")
    data = compiled(scene_tags=("alley",), nl="A quiet rainy night.")
    assert "quiet rainy night" not in emit_sequential(data, drop, {})[0]
    assert emit_sequential(data, append, {})[0].endswith("A quiet rainy night.")


def test_sequential_quality_suffix_goes_last():
    preset = TargetPreset(id="p", name="P", quality_suffix=("hires",))
    result, _ = emit_sequential(compiled(scene_tags=("alley",)), preset, {})
    assert result.endswith("hires")


def test_sequential_lora_tag_first_trigger_in_block():
    entry = LoraEntry(id="kafka", file="kafka.safetensors", weight=0.8, triggers=("kafka",))
    result, _ = emit_sequential(
        compiled(
            scene_tags=("alley",),
            characters=(char("c1", ["purple_hair"]), char("c2", ["black_hair"])),
        ),
        PRESET,
        {"c1": entry},
    )
    assert result.startswith("<lora:kafka:0.8>, masterpiece")
    assert "kafka, purple hair" in result


def test_sequential_lora_filename_underscores_survive():
    """<lora:...> 태그는 언더스코어 치환에서 제외된다 — 안 그러면 파일을 못 찾는다."""
    entry = LoraEntry(id="k", file="kafka_illustrious.safetensors", weight=0.8)
    result, _ = emit_sequential(
        compiled(scene_tags=(), characters=(char("c1", ["purple_hair"]),)),
        PRESET,
        {"c1": entry},
    )
    assert "<lora:kafka_illustrious:0.8>" in result
    assert "purple hair" in result


def test_sequential_returns_negative_too():
    _, negative = emit_sequential(compiled(negative="bad hands"), PRESET, {})
    assert negative == "lowres, worst quality, bad hands"
