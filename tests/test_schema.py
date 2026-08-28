"""프롬프트 구조 스키마 (naiauto.core.prompt.schema) 테스트."""

import pytest
from pydantic import ValidationError

from naiauto.core.prompt.schema import (
    DEFAULT_MODE,
    MODE_TAGS,
    CharacterPrompt,
    CompiledPrompt,
    LLMCharacterModel,
    LLMSceneModel,
    LLMStructuredPrompt,
    RelationshipPrompt,
    ScenePrompt,
    TagRef,
)


def test_llm_structured_prompt_valid_json():
    data = {
        "scene": {"tags": ["cafe", "window"], "subjects": ["girl", "girl"]},
        "characters": [
            {"id": "c1", "description": "silver-haired schoolgirl",
             "tags": ["silver_hair", "short_hair"], "position_hint": "left"},
            {"id": "c2", "description": "black-haired girl",
             "tags": ["black_hair", "long_hair"], "position_hint": "right"},
        ],
        "relationships": [{"source": "c1", "target": "c2", "action": "talking_to", "mutual": True}],
    }
    parsed = LLMStructuredPrompt.model_validate(data)
    assert parsed.scene.tags == ["cafe", "window"]
    assert len(parsed.characters) == 2
    assert parsed.characters[0].position_hint == "left"
    assert parsed.relationships[0].mutual is True


def test_llm_structured_prompt_missing_required_fields():
    with pytest.raises(ValidationError):
        LLMStructuredPrompt.model_validate({"scene": {}, "characters": []})


def test_llm_structured_prompt_extra_fields_rejected():
    data = {
        "scene": {"tags": ["cafe"]},
        "characters": [],
        "surprise_field": "nope",
    }
    with pytest.raises(ValidationError):
        LLMStructuredPrompt.model_validate(data)


def test_llm_character_extra_fields_rejected():
    with pytest.raises(ValidationError):
        LLMCharacterModel.model_validate({"id": "c1", "tags": [], "weird": 1})


def test_llm_scene_defaults():
    scene = LLMSceneModel(tags=["rain"])
    assert scene.subjects == []
    assert scene.description == ""


def test_modes_are_frozen_and_hybrid_default():
    assert DEFAULT_MODE == "hybrid"
    assert set(MODE_TAGS) == {"tag", "hybrid", "natural"}


def test_compiled_prompt_holds_structured_sections():
    compiled = CompiledPrompt(
        base_prompt="2girls, cafe",
        negative_prompt="",
        scene=ScenePrompt(tags=(TagRef("cafe"),)),
        characters=(CharacterPrompt(id="c1", tags=(TagRef("silver_hair"),)),),
        relationships=(RelationshipPrompt("c1", "c2", "looking_at"),),
        mode="hybrid",
        warnings=(),
        unresolved=(),
    )
    assert compiled.scene.tags[0].tag == "cafe"
    assert compiled.characters[0].id == "c1"