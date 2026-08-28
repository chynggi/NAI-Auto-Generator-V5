from naiauto.core.prompt.formatter import PromptFormatter
from naiauto.core.prompt.schema import (
    CharacterPrompt,
    RelationshipPrompt,
    ScenePrompt,
    TagRef,
)


def _scene(**kw):
    defaults = dict(tags=(TagRef("rain"), TagRef("night"), TagRef("alley")))
    defaults.update(kw)
    return ScenePrompt(**defaults)


def _char(cid, tags, **kw):
    return CharacterPrompt(
        id=cid,
        tags=tuple(TagRef(t) for t in tags),
        **kw,
    )


def test_tag_mode_base_has_count_and_scene():
    fmt = PromptFormatter(preserve_natural_language=True)
    scene = _scene(subjects=("girl", "girl"))
    chars = (_char("c1", ["silver_hair", "school_uniform"]), _char("c2", ["black_hair"]))
    base, neg = fmt.format(scene=scene, characters=chars, relationships=(),
                           negative_tags=(), mode="tag")
    assert base.startswith("2girls")
    assert "rain" in base and "night" in base and "alley" in base
    assert "silver_hair" not in base  # 캐릭터 태그는 base에 없음


def test_tag_mode_character_prompts_no_count_tag():
    fmt = PromptFormatter()
    chars = (_char("c1", ["silver_hair"]),)
    # format은 base만 반환하므로, 캐릭터 문자열은 compiler가 조립 — 여기서는
    # 캐릭터용 문자열 도우미가 필요하다: format은 (base, negative)뿐이므로
    # 아래처럼 정적 메서드로 캐릭터 prompt 문자열을 검증.
    char_text = fmt.character_prompt_text(chars[0], mode="tag")
    assert char_text == "silver_hair"
    assert "2girls" not in char_text and "girl" != char_text.split(",")[0]


def test_hybrid_mode_appends_nl_segments():
    fmt = PromptFormatter(preserve_natural_language=True)
    scene = _scene(
        subjects=("girl", "girl"),
        natural_language="She is standing in a narrow alley at night.",
    )
    chars = (_char("c1", ["silver_hair"]), _char("c2", ["black_hair"]))
    base, _ = fmt.format(scene=scene, characters=chars, relationships=(), negative_tags=(), mode="hybrid")
    assert "silver_hair" not in base
    assert base.startswith("2girls")
    assert "narrow alley" in base


def test_hybrid_mode_no_nl_when_preserve_off():
    fmt = PromptFormatter(preserve_natural_language=False)
    scene = _scene(subjects=("girl",), natural_language="Should not appear.")
    base, _ = fmt.format(scene=scene, characters=(), relationships=(), negative_tags=(), mode="hybrid")
    assert "Should not appear" not in base


def test_natural_mode_prose_only():
    fmt = PromptFormatter()
    scene = _scene(
        subjects=("girl", "girl"),
        description="Two girls sit facing each other in a warm cafe.",
        natural_language="Rain falls outside the window.",
    )
    base, _ = fmt.format(scene=scene, characters=(), relationships=(), negative_tags=(), mode="natural")
    assert "rain" in base.lower() or "Rain" in base
    assert "cafe" in base.lower()
    assert "silver_hair" not in base


def test_count_tag_rules():
    fmt = PromptFormatter()
    assert fmt.count_tag(("girl", "girl")) == "2girls"
    assert fmt.count_tag(("girl",)) == "1girl"
    assert fmt.count_tag(("boy", "boy", "boy")) == "3boys"
    assert fmt.count_tag(("cat", "cat")) == "2cats"
    assert fmt.count_tag(("girl", "boy")) == ""
    assert fmt.count_tag(()) == ""


def test_scene_count_tag_deduplicated():
    fmt = PromptFormatter()
    scene = _scene(subjects=("girl", "girl"), tags=(TagRef("2girls"), TagRef("rain")))
    base, _ = fmt.format(scene=scene, characters=(), relationships=(), negative_tags=(), mode="tag")
    assert base.count("2girls") == 1


def test_relationship_sentences_one_way_with_positions():
    fmt = PromptFormatter()
    chars = (
        _char("c1", ["silver_hair"], position_hint="left"),
        _char("c2", ["black_hair"], position_hint="right"),
    )
    sentences = fmt.relationship_sentences(
        (RelationshipPrompt("c1", "c2", "looking_at"),), chars
    )
    assert sentences == ["The character on the left is looking at the character on the right."]


def test_relationship_sentences_mutual():
    fmt = PromptFormatter()
    sentences = fmt.relationship_sentences(
        (RelationshipPrompt("c1", "c2", "facing", mutual=True),
         RelationshipPrompt("c2", "c1", "facing", mutual=True)),
        (),
    )
    assert sentences == ["The two characters are facing each other."]


def test_relationship_sentences_fallback_ids():
    fmt = PromptFormatter()
    sentences = fmt.relationship_sentences(
        (RelationshipPrompt("c1", "c2", "looking_at"),), ()
    )
    assert sentences == ["Character c1 is looking at Character c2."]


def test_relationship_tag_style():
    fmt = PromptFormatter(relationship_style="tag")
    seg = fmt.relationship_tag_segment(
        (RelationshipPrompt("c1", "c2", "talking_to", mutual=True),
         RelationshipPrompt("c2", "c1", "talking_to", mutual=True)),
    )
    assert seg == "c1#talking_to c2#talking_to"
    seg2 = fmt.relationship_tag_segment((RelationshipPrompt("c1", "c2", "looking_at"),))
    assert seg2 == "c1#looking_at"


def test_negative_prompt_uses_verified_tags_only():
    fmt = PromptFormatter()
    _, neg = fmt.format(
        scene=_scene(), characters=(), relationships=(),
        negative_tags=(TagRef("bad_hands", "verified"), TagRef("text", "verified"),
                       TagRef("made_up_thing", "unresolved")),
        mode="hybrid",
    )
    assert neg == "bad_hands, text"
