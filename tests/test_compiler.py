import pytest

from naiauto.core.prompt.compiler import PromptCompiler
from naiauto.core.prompt.errors import CompilerEmptyResultError
from naiauto.core.prompt.formatter import PromptFormatter
from naiauto.core.prompt.llm import FakeLLMProvider
from naiauto.core.prompt.resolver import TagResolver

GOLDEN_JSON = """{
  "scene": {
    "tags": ["city", "night", "rain", "wet_road", "neon_lights"],
    "subjects": ["girl", "girl"],
    "description": "A rainy night city scene",
    "natural_language": ""
  },
  "characters": [
    {"id": "c1", "description": "silver-haired girl in a black dress",
     "tags": ["long_hair", "silver_hair", "black_dress", "standing"], "position_hint": "left"},
    {"id": "c2", "description": "red short-haired girl with an umbrella",
     "tags": ["short_hair", "red_hair", "umbrella", "standing"], "position_hint": "right"}
  ],
  "relationships": [
    {"source": "c1", "target": "c2", "action": "looking_at", "mutual": true},
    {"source": "c2", "target": "c1", "action": "looking_at", "mutual": true}
  ],
  "camera": "low_angle", "composition": "", "style": "",
  "negative": [], "unresolved": []
}"""


@pytest.fixture()
def golden_input() -> str:
    return (
        "밤의 비 내리는 도시에서 왼쪽에는 긴 은발의 소녀가 검은 드레스를 입고 서 있고, "
        "오른쪽에는 붉은 단발머리의 소녀가 우산을 들고 서 있다. "
        "두 사람은 서로를 바라보고 있으며 젖은 도로에 네온사인이 반사되고 있다. "
        "카메라는 두 사람을 낮은 앵글에서 바라본다."
    )


def _compiler(response=GOLDEN_JSON):
    resolver = TagResolver()
    assert resolver.load()
    return PromptCompiler(
        provider=FakeLLMProvider(response=response),
        resolver=resolver,
        formatter=PromptFormatter(preserve_natural_language=True, relationship_style="natural"),
    )


def test_golden_example_hybrid(golden_input):
    compiled = _compiler().compile(golden_input, mode="hybrid")
    # base에 scene + count
    assert compiled.base_prompt.startswith("2girls")
    # [Ruling #5] "wet_road"는 토큰 분해로 wet + road (둘 다 DB 존재), "silver_hair"는 grey_hair로 정규화
    for tag in ("city", "night", "rain", "wet", "road", "neon_lights"):
        assert tag in compiled.base_prompt
    # 캐릭터 분리
    assert len(compiled.characters) == 2
    c1, c2 = compiled.characters
    assert any(t.tag == "grey_hair" for t in c1.tags)
    assert any(t.tag == "black_dress" for t in c1.tags)
    assert any(t.tag == "red_hair" for t in c2.tags)
    assert any(t.tag == "umbrella" for t in c2.tags)
    # 캐릭터 태그가 base에 없고, scene 태그가 캐릭터에 없음 (스펙 §74 핵심)
    assert "grey_hair" not in compiled.base_prompt
    assert "rain" not in "".join(t.tag for t in c1.tags)
    # 관계는 별도 구조로 보존
    assert len(compiled.relationships) == 2
    assert {r.action for r in compiled.relationships} == {"looking_at"}
    # 위치
    assert c1.center_x == pytest.approx(0.30) and c1.center_y == pytest.approx(0.50)
    assert c2.center_x == pytest.approx(0.70)
    # 관계 자연어 문장이 base에 있음
    assert "looking at each other" in compiled.base_prompt
    assert compiled.unresolved == ()


def test_golden_example_tag_mode_no_nl(golden_input):
    compiled = _compiler().compile(golden_input, mode="tag")
    assert "each other" not in compiled.base_prompt


def test_golden_example_relationships_rendered(golden_input):
    # 태그형 관계 옵션
    resolver = TagResolver()
    assert resolver.load()
    compiler = PromptCompiler(
        provider=FakeLLMProvider(response=GOLDEN_JSON),
        resolver=resolver,
        formatter=PromptFormatter(preserve_natural_language=True, relationship_style="tag"),
    )
    compiled = compiler.compile(golden_input, mode="hybrid")
    assert "c1#looking_at c2#looking_at" in compiled.base_prompt


def test_compile_empty_input():
    with pytest.raises(CompilerEmptyResultError):
        _compiler().compile("   ")


def test_compile_with_missing_positions():
    data = GOLDEN_JSON.replace('"position_hint": "left"', '"position_hint": ""').replace(
        '"position_hint": "right"', '"position_hint": "somewhere"'
    )
    compiled = _compiler(response=data).compile("테스트", mode="hybrid")
    assert compiled.characters[0].center_x is None
    assert compiled.characters[1].center_x is None


def test_modify_preserves_wildcard_tokens():
    existing = "1girl, silver_hair, school_uniform, __hairstyle__, classroom"
    response = GOLDEN_JSON.replace('"city", "night", "rain", "wet_road", "neon_lights"', '"rooftop", "night"')
    compiled = _compiler(response=response).modify(
        existing_prompt=existing,
        instruction="교실을 밤의 옥상으로 바꾸고 우산을 추가해줘.",
        mode="hybrid",
    )
    assert "__hairstyle__" in compiled.base_prompt


def test_modify_keeps_character_when_llm_returns_them():
    # LLM이 캐릭터를 반환하면 그대로 사용
    compiled = _compiler().modify(
        existing_prompt="1girl, silver_hair, classroom",
        instruction="배경을 밤으로 바꿔줘",
        mode="hybrid",
    )
    assert len(compiled.characters) == 2


def test_resolver_disabled_passes_raw_tags():
    resolver = TagResolver(database_path="/nonexistent/path.csv")
    resolver.load()  # False
    compiler = PromptCompiler(
        provider=FakeLLMProvider(response=GOLDEN_JSON),
        resolver=resolver,
        formatter=PromptFormatter(),
        use_resolver=False,
    )
    compiled = compiler.compile("test", mode="tag")
    assert any(t.tag == "silver_hair" for t in compiled.characters[0].tags)


def test_unresolved_and_relationship_warnings_collected():
    # 미해결 태그(quantum_road) + 알 수 없는 관계 액션(teleporting) → warnings 수집
    data = GOLDEN_JSON.replace('"wet_road"', '"quantum_road"').replace(
        '"action": "looking_at"', '"action": "teleporting"'
    )
    compiled = _compiler(response=data).compile("테스트", mode="hybrid")
    assert compiled.unresolved == ("quantum_road",)
    assert any("quantum_road" in w for w in compiled.warnings)
    assert any("unresolved concept" in w for w in compiled.warnings)
    # 관계 경고: 액션 2건 모두 할루시네이션으로 제외
    assert compiled.relationships == ()
    assert len([w for w in compiled.warnings if "teleporting" in w]) == 2


def test_duplicate_scene_tags_deduplicated():
    # [Minor #1] LLM이 같은 태그를 반복 출력해도 base에 한 번만 나온다
    data = GOLDEN_JSON.replace('"city", "night", "rain"', '"city", "night", "rain", "rain", "city"')
    compiled = _compiler(response=data).compile("테스트", mode="tag")
    assert compiled.base_prompt.count("city") == 1
    assert compiled.base_prompt.count("rain") == 1
    assert len(compiled.scene.tags) == len({t.tag for t in compiled.scene.tags})


def test_negative_unresolved_collected():
    # [Minor #3] negative 후보 중 태그 DB에 없는 개념도 unresolved로 취합된다
    data = GOLDEN_JSON.replace('"negative": []', '"negative": ["bad_hands", "quantum_glow"]')
    compiled = _compiler(response=data).compile("테스트", mode="hybrid")
    assert "quantum_glow" in compiled.unresolved
    assert any("quantum_glow" in w for w in compiled.warnings)
    assert "bad_hands" in compiled.negative_prompt  # 검증된 negative는 유지


def test_modify_preserved_token_exact_segment_match():
    # [Minor #5] 보존 토큰 판정은 세그먼트 단위 — "girl"이 "1girl"에 묻히면 보존 처리된다
    existing = "girl, __hairstyle__, classroom"
    data = GOLDEN_JSON.replace('"city", "night", "rain", "wet_road", "neon_lights"', '"rooftop", "night"')
    compiled = _compiler(response=data).modify(
        existing_prompt=existing,
        instruction="교실을 밤의 옥상으로 바꿔줘",
        mode="tag",
    )
    # base가 "2girls, rooftop, night" 형태여도 "girl" 세그먼트는 없음 → "__hairstyle__"만 보존
    assert "__hairstyle__" in compiled.base_prompt
    segments = {s.strip() for s in compiled.base_prompt.split(",")}
    assert "girl" not in segments
