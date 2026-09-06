import pytest

from naiauto.core.prompt.errors import CompilerEmptyResultError, CompilerParseError
from naiauto.core.prompt.llm import FakeLLMProvider
from naiauto.core.prompt.parser import (
    PRESERVED_TOKEN_RE,
    SceneParser,
    build_messages,
    extract_json,
    load_system_prompt,
    parse_structured,
)

GOOD_JSON = """{
  "scene": {"tags": ["cafe", "window", "rain"], "subjects": ["girl", "girl"]},
  "characters": [
    {"id": "c1", "description": "silver-haired schoolgirl",
     "tags": ["silver_hair", "short_hair", "school_uniform"], "position_hint": "left"},
    {"id": "c2", "description": "black-haired girl in casual clothes",
     "tags": ["black_hair", "long_hair", "casual_clothes"], "position_hint": "right"}
  ],
  "relationships": [{"source": "c1", "target": "c2", "action": "talking_to", "mutual": true}],
  "camera": "", "composition": "", "style": "", "negative": [], "unresolved": []
}"""


def test_load_system_prompt():
    text = load_system_prompt()
    assert "image prompt analysis assistant" in text
    assert "talking_to" in text


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_code_fence():
    text = "Sure!\n```json\n{\"a\": 1}\n```"
    assert extract_json(text) == {"a": 1}


def test_extract_json_with_prose_around():
    text = 'Here is the result: {"scene": {"tags": ["rain"]}} hope it helps'
    assert extract_json(text)["scene"]["tags"] == ["rain"]


def test_extract_json_malformed_raises():
    with pytest.raises(CompilerParseError):
        extract_json("no json here at all")


def test_parse_structured_valid():
    parsed = parse_structured(GOOD_JSON)
    assert parsed.scene.tags == ["cafe", "window", "rain"]
    assert len(parsed.characters) == 2


def test_parse_structured_invalid_schema_raises():
    with pytest.raises(CompilerParseError):
        parse_structured('{"scene": {"tags": "not-a-list"}, "characters": []}')


def test_build_messages_create_mode():
    msgs = build_messages("a girl in a cafe")
    assert msgs[0]["role"] == "system"
    assert "image prompt analysis" in msgs[0]["content"]
    assert msgs[1] == {"role": "user", "content": "a girl in a cafe"}


def test_build_messages_modify_mode_includes_existing_and_tokens():
    msgs = build_messages(
        "배경을 밤으로 바꿔줘",
        existing_prompt="1girl, __hairstyle__, {artist:grp}, silver_hair, classroom",
        preserved=("__hairstyle__", "{artist:grp}"),
    )
    user = msgs[1]["content"]
    assert "EXISTING PROMPT:" in user
    assert "__hairstyle__" in user
    assert "{artist:grp}" in user
    assert "MODIFICATION REQUEST:" in user


def test_build_messages_injects_candidate_tags():
    msgs = build_messages("rainy alley", candidate_tags=("rain", "alley", "night"))
    assert "AVAILABLE TAGS" in msgs[0]["content"]
    assert "rain, alley, night" in msgs[0]["content"]


def test_build_messages_injects_translated_query():
    msgs = build_messages(
        "비 오는 골목",
        translated_text="rainy alley",
        candidate_tags=("rain", "alley"),
    )
    user = msgs[1]["content"]
    assert "TRANSLATED QUERY" in user
    assert "rainy alley" in user


def test_build_messages_without_translation_unchanged():
    msgs = build_messages("비 오는 골목")
    assert "TRANSLATED QUERY" not in msgs[1]["content"]


def test_build_messages_modify_mode_injects_translated_instruction():
    msgs = build_messages(
        "배경을 밤으로 바꿔줘",
        existing_prompt="1girl, classroom",
        preserved=(),
        translated_text="change the background to night",
    )
    user = msgs[1]["content"]
    assert "TRANSLATED QUERY" in user
    assert "change the background to night" in user


def test_scene_parser_translate_returns_english():
    parser = SceneParser(FakeLLMProvider(response="rainy alley at night"))
    assert parser.translate("비 오는 밤의 골목") == "rainy alley at night"


def test_scene_parser_translate_empty_response():
    parser = SceneParser(FakeLLMProvider(response="   "))
    assert parser.translate("비 오는 골목") == ""


def test_build_messages_without_candidates_unchanged():
    # 후보가 없으면 섹션 헤더(주입 전용 문구)가 추가되지 않는다 —
    # 지시문 자체에 "AVAILABLE TAGS"가 포함되므로 주입 헤더로 구분한다.
    msgs = build_messages("rainy alley")
    assert "(use these exact tag names" not in msgs[0]["content"]


def test_scene_parser_passes_candidate_tags_to_provider():
    seen = {}

    class CapturingProvider(FakeLLMProvider):
        def chat(self, messages, **kwargs):
            seen["system"] = messages[0]["content"]
            return super().chat(messages, **kwargs)

    parser = SceneParser(CapturingProvider(response=GOOD_JSON))
    parser.parse("rainy alley", candidate_tags=("rain", "alley"))
    assert "AVAILABLE TAGS" in seen["system"]
    assert "rain, alley" in seen["system"]


def test_scene_parser_end_to_end():
    parser = SceneParser(FakeLLMProvider(response=GOOD_JSON))
    parsed = parser.parse("은발 소녀와 흑발 소녀가 카페에서 이야기한다")
    assert parsed.characters[0].id == "c1"
    assert parsed.relationships[0].mutual is True


def test_scene_parser_empty_response_raises():
    parser = SceneParser(FakeLLMProvider(response="   "))
    with pytest.raises(CompilerEmptyResultError):
        parser.parse("anything")


def test_preserved_token_regex():
    text = "1girl, __hairstyle__, {artist:grp}, silver_hair"
    # Python sorted()는 ASCII 기준: "_"(0x5F) < "{"(0x7B) — [Pre-flight ruling #2]
    assert sorted(PRESERVED_TOKEN_RE.findall(text)) == ["__hairstyle__", "{artist:grp}"]
