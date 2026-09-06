from naiauto.core.prompt.merge import merge_negatives, to_generation_data
from naiauto.core.prompt.schema import (
    CharacterPrompt,
    CompiledPrompt,
    ScenePrompt,
    TagRef,
)


def _compiled(characters=()):
    return CompiledPrompt(
        base_prompt="2girls, cafe, rain",
        negative_prompt="bad_hands",
        scene=ScenePrompt(tags=(TagRef("cafe"),)),
        characters=characters,
        relationships=(),
        mode="hybrid",
        warnings=(),
        unresolved=(),
    )


def test_merge_negatives_dedupes_and_orders():
    assert merge_negatives("bad_hands, text", "bad_hands, lowres") == "bad_hands, text, lowres"
    assert merge_negatives("", "bad_hands") == "bad_hands"
    assert merge_negatives("existing", "") == "existing"


def test_to_generation_data_base_and_negative():
    out = to_generation_data(_compiled(), existing_negative="text")
    assert out.prompt == "2girls, cafe, rain"
    assert out.negative_prompt == "text, bad_hands"


def test_to_generation_data_characters_mapped():
    chars = (
        CharacterPrompt(id="c1", tags=(TagRef("silver_hair"), TagRef("school_uniform")),
                        negative_tags=("bad_hands",), center_x=0.3, center_y=0.5),
        CharacterPrompt(id="c2", tags=(TagRef("black_hair"),)),
    )
    out = to_generation_data(_compiled(characters=chars))
    assert len(out.characters) == 2
    c1 = out.characters[0]
    assert c1.prompt == "silver_hair, school_uniform"
    assert c1.uc == "bad_hands"
    assert c1.center_x == 0.3 and c1.center_y == 0.5
    # 좌표 미지정 캐릭터는 0.5/0.5 (기존 CharacterCaption 기본)
    assert out.characters[1].center_x == 0.5 and out.characters[1].center_y == 0.5


def test_generation_request_accepts_merge_output():
    from naiauto.core.api.models import GenerationRequest

    out = to_generation_data(_compiled(
        characters=(CharacterPrompt(id="c1", tags=(TagRef("silver_hair"),)),)
    ))
    req = GenerationRequest(prompt=out.prompt, negative_prompt=out.negative_prompt,
                            characters=out.characters)
    assert req.characters[0].prompt == "silver_hair"


def _compiled_with_target(target: str):
    return CompiledPrompt(
        base_prompt="2girls, rain",
        negative_prompt="lowres",
        scene=ScenePrompt(tags=(TagRef("rain"),)),
        characters=(
            CharacterPrompt(id="c1", tags=(TagRef("silver_hair"),), prompt_text="silver_hair"),
        ),
        relationships=(),
        mode="hybrid",
        warnings=(),
        unresolved=(),
        target=target,
    )


def test_novelai_target_keeps_character_captions():
    result = to_generation_data(_compiled_with_target("novelai"))
    assert len(result.characters) == 1
    assert result.characters[0].prompt == "silver_hair"


def test_local_target_drops_character_captions():
    result = to_generation_data(_compiled_with_target("illustrious"))
    assert result.characters == ()
    assert result.prompt == "2girls, rain"
    assert result.negative_prompt == "lowres"


def test_local_target_still_merges_existing_negative():
    """캐릭터만 비울 뿐, 기존 사용자 네거티브 병합은 그대로 동작해야 한다."""
    result = to_generation_data(_compiled_with_target("illustrious"), existing_negative="bad hands")
    assert result.negative_prompt == "bad hands, lowres"
