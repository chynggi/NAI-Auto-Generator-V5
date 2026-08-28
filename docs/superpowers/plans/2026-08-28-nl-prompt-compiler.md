# Natural Language → NovelAI V5 Prompt Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자연어 설명을 Scene/Character/Relationship 구조로 분해해 NovelAI V5에 최적화된 prompt로 컴파일하는 독립 하위 시스템(Prompt Intelligence)을 NAI-Auto-Generator-V5에 추가한다.

**Architecture:** 기존 API 계층(`GenerationRequest` → `NAIClient.generate()`)은 변경하지 않는다. 새 `src/naiauto/core/prompt/` 패키지가 LLM Scene Parser → Deterministic Tag Resolver → NovelAI V5 Formatter 파이프라인을 제공하고, UI(전용 다이얼로그 + 메인 패널 요약 섹션)가 산출물을 기존 프롬프트 편집기/캐릭터 슬롯/위치 캔버스에 반영한다. LLM은 semantic extraction만 담당하고, 태그 검증은 내장 Danbooru DB 재사용 resolver가, 최종 문법은 formatter가 결정한다.

**Tech Stack:** Python 3.10+, PySide6(UI), pydantic v2(schema·설정), requests(LLM HTTP), pytest(신규 테스트), keyring(LLM API key 보관), 기존 내장 Danbooru 태그 DB(22,351개).

**Spec:** `/home/chynggi/NAI-Auto-Generator-V5/NAI-Auto-Generator-V5.md` (75개 섹션 전체 구현 지시서). 이 플랜은 스펙을 저장소 구조에 매핑한 실행 계획이다. 추가 확정 사항(사용자 승인):
- 관계 렌더링: 자연어 기본 + 태그형(`source#action`) 옵션 토글
- LLM 실서버: llama.cpp `http://127.0.0.1:7112/v1` (OpenAI 호환)
- System prompt: 영어 코어 + 한/영 예시 (템플릿 파일)
- 테스트: pytest + GitHub Actions job 추가

## Global Constraints

(스펙에서 복사한 절대 규칙 — 모든 태스크의 요구사항에 암묵적으로 포함됨)

1. ComfyUI / ComfyUI custom node / NeuralBooru를 dependency로 추가하지 않는다 (§2.1).
2. `NAIClient` / `payload_v5` / `GenerationRequest`를 재작성하지 않는다. API 계층이 prompt 계층을 import하지 않는다 (§2.2). 방향: GUI → Compiler → CompiledPrompt → GenerationRequest → NAIClient.
3. LLM에게 NovelAI payload/GenerationRequest/API parameter를 직접 만들게 하지 않는다 (§9). LLM은 semantic extraction과 후보 태그 생성까지만.
4. 존재하지 않는 태그를 final prompt에 넣지 않는다 (§10) — resolver가 검증, `unresolved`는 final tag에서 제외 (§13, §41).
5. LLM inference를 GUI thread에서 실행하지 않는다 (§29). Worker 스레드 패턴(`MainWindow._run_in_background` + Qt 시그널) 사용.
6. 사용자 승인 없이 기존 prompt를 덮어쓰지 않는다 (§24) — Generate → Preview → Review → Apply 구조.
7. Hybrid가 기본 모드다 (§15, §74).
8. 캐릭터 count 태그(`2girls`)는 base prompt에서만 관리, character prompt에 중복하지 않는다 (§21, §55).
9. Wildcards(`__x__`), artist combo placeholder(`{artist:...}`)를 파괴하지 않는다 (§51, §52).
10. LLM API key는 keyring(`core/settings/credentials.py`)에만 저장, 평문 설정 저장 금지, 로그에서 제거 (§28, §64).
11. 기존 기능(수동 prompt 입력, negative, tag autocomplete, batch, i2i, inpainting, gallery, WD14 등)은 그대로 동작해야 한다 (§65).
12. 새 GUI 문자열은 i18n 4개 언어(ko/en/ja/zh) JSON에 추가, 하드코딩 금지 (§45).
13. Unit 테스트에서 실제 NovelAI API·실제 LLM 서버 호출 금지 — provider는 mock/Fake (§60).
14. 과도한 abstraction 금지. 필요해진 뒤에만 추가 (§66).

---

## File Structure

**새 파일 (core — Qt 의존성 없음):**
- `src/naiauto/core/prompt/__init__.py` — public exports (`PromptCompiler`, `build_compiler`, `CompiledPrompt`, ...)
- `src/naiauto/core/prompt/schema.py` — 구조 스키마 (TagRef/ScenePrompt/CharacterPrompt/RelationshipPrompt/CompiledPrompt + pydantic LLM 모델)
- `src/naiauto/core/prompt/errors.py` — CompilerError 계층
- `src/naiauto/core/prompt/llm.py` — LLMProvider Protocol + FakeLLMProvider
- `src/naiauto/core/prompt/providers/__init__.py` — `create_provider()` 팩토리
- `src/naiauto/core/prompt/providers/openai_compatible.py` — OpenAI 호환 (llama.cpp/LM Studio/원격)
- `src/naiauto/core/prompt/providers/ollama.py` — Ollama 네이티브
- `src/naiauto/core/prompt/parser.py` — LLM 호출 + JSON 추출 + pydantic 검증
- `src/naiauto/core/prompt/templates/system_prompt.md` — LLM 지시문 (영어 코어 + 한/영 예시)
- `src/naiauto/core/prompt/resolver.py` — Danbooru tag 검증
- `src/naiauto/core/prompt/positions.py` — 위치 힌트 → 좌표
- `src/naiauto/core/prompt/relationship.py` — 관계 정규화
- `src/naiauto/core/prompt/formatter.py` — NovelAI V5 prompt 조립
- `src/naiauto/core/prompt/merge.py` — CompiledPrompt → UI/GenerationRequest 호환 데이터
- `src/naiauto/core/prompt/compiler.py` — 파이프라인 오케스트레이션 + `build_compiler()` 팩토리

**새 파일 (UI):**
- `src/naiauto/ui/prompt_compiler_dialog.py` — 자연어 입력/미리보기/Apply 다이얼로그
- `src/naiauto/ui/options_pages/prompt_ai_page.py` — 설정 페이지

**새 파일 (테스트):**
- `tests/conftest.py`, `tests/test_schema.py`, `tests/test_resolver.py`, `tests/test_positions.py`, `tests/test_relationship.py`, `tests/test_formatter.py`, `tests/test_parser.py`, `tests/test_providers.py`, `tests/test_compiler.py`, `tests/test_merge.py`
- `.github/workflows/tests.yml`

**수정 파일:**
- `pyproject.toml` — pytest dev extra, package-data에 templates/*.md, pytest 설정
- `src/naiauto/core/settings/schema.py` — `PromptAISettings`, `CompilerSettings` + `AppSettings` 필드
- `src/naiauto/ui/options_dialog.py` — `NAV_ORDER`, `OWNED_FIELDS`
- `src/naiauto/ui/options_pages/__init__.py` — static import 목록
- `src/naiauto/ui/main_window.py` — 메뉴 액션, Apply 핸들러, 요약 섹션
- `src/naiauto/resources/languages/{ko,en,ja,zh}.json` — `compiler.*`, `options_nav.prompt_ai*`, `menu.prompt_compiler` 키
- `packaging/nai-auto-v5.spec` — templates 데이터 포함
- `README.md` — 자연어 컴파일러 섹션 (한국어 + English)

---

## Task 1: 테스트 인프라 (pytest + CI)

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/conftest.py`
- Create: `.github/workflows/tests.yml`
- Test: `tests/test_infra.py`

**Interfaces:**
- Consumes: 없음
- Produces: `pytest` 실행 가능한 `tests/` 디렉터리, `conftest.py`의 fixture `bundled_db_path`(Path), `fake_provider_factory`(下 Task 3)

- [ ] **Step 1: pyproject.toml에 pytest 추가**

`[project.optional-dependencies] dev`를 `["ruff>=0.5", "pytest>=8.0"]`로 바꾸고, 파일 끝에 추가:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 2: tests/conftest.py 생성**

```python
"""공용 테스트 픽스처."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def bundled_db_path() -> Path:
    """앱 내장 Danbooru 태그 DB 경로."""
    import naiauto.core.tag_completer as tc

    return tc.bundled_database_path()
```

- [ ] **Step 3: test_infra.py 생성 (pytest가 sys.path를 잡는지 확인)**

```python
def test_import_naiauto():
    import naiauto  # noqa: F401

    assert True
```

- [ ] **Step 4: 로컬 실행 확인**

```bash
cd /home/chynggi/NAI-Auto-Generator-V5
python -m pip install -e ".[dev]" 2>&1 | tail -1
python -m pytest tests/ -q
```

Expected: `1 passed`.

- [ ] **Step 5: CI 워크플로 생성**

`.github/workflows/tests.yml`:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  pytest:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install Qt runtime libs (PySide6 offscreen)
        run: sudo apt-get update && sudo apt-get install -y libegl1 libgl1
      - name: Install
        run: pip install -e ".[dev]"
      - name: Run tests
        env:
          QT_QPA_PLATFORM: offscreen
        run: pytest tests/ -q
```

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml tests/ .github/workflows/tests.yml
git commit -m "test: add pytest infrastructure and CI job"
```

---

## Task 2: 구조 스키마 (schema.py)

**Files:**
- Create: `src/naiauto/core/prompt/schema.py`
- Test: `tests/test_schema.py`

**Interfaces:**
- Consumes: 없음
- Produces (후속 태스크가 의존하는 정확한 이름/시그니처):

```python
TagStatus = Literal["verified", "inferred", "unresolved"]

@dataclass(frozen=True)
class TagRef:
    tag: str                         # 정규화된 태그명 (underscore)
    status: TagStatus = "verified"
    source: str = "explicit"         # "explicit" | "inferred"
    post_count: int = 0              # DB 미존재(unresolved)면 0

@dataclass(frozen=True)
class ScenePrompt:
    tags: tuple[TagRef, ...] = ()            # verified/inferred만 (final에 포함)
    raw_tags: tuple[str, ...] = ()           # LLM 원문 후보
    subjects: tuple[str, ...] = ()           # ["girl", "girl"] — count 태그용
    description: str = ""
    natural_language: str = ""
    camera: str = ""
    composition: str = ""
    style: str = ""
    lighting: str = ""
    environment: str = ""

@dataclass(frozen=True)
class CharacterPrompt:
    id: str                          # "c1", "c2", ...
    description: str = ""
    tags: tuple[TagRef, ...] = ()
    raw_tags: tuple[str, ...] = ()
    negative_tags: tuple[str, ...] = ()
    pose: str = ""
    expression: str = ""
    position_hint: str = ""          # "left" | "right" | "center" | "far_left" | ...
    center_x: float | None = None
    center_y: float | None = None
    natural_language: str = ""
    prompt_text: str = ""            # formatter가 만든 최종 캐릭터 prompt 문자열 (merge가 사용)

# [Pre-flight ruling #1] Task 2↔9 인터페이스 갭: to_generation_data()가 캐릭터별 최종
# 문자열이 필요한데 schema에 없었다. CharacterPrompt.prompt_text 필드를 추가하고,
# compiler._assemble이 formatter.character_prompt_text() 결과로 채운다.

@dataclass(frozen=True)
class RelationshipPrompt:
    source: str                      # character id
    target: str
    action: str                      # 정규화된 action (snake_case)
    mutual: bool = False             # True = 양방향 (서로)

@dataclass(frozen=True)
class CompiledPrompt:
    base_prompt: str
    negative_prompt: str
    scene: ScenePrompt
    characters: tuple[CharacterPrompt, ...]
    relationships: tuple[RelationshipPrompt, ...]
    mode: str                        # "tag" | "hybrid" | "natural"
    warnings: tuple[str, ...]
    unresolved: tuple[str, ...]

MODE_TAGS = ("tag", "hybrid", "natural")
DEFAULT_MODE = "hybrid"
```

**LLM pydantic 모델** (parser 출력 검증용, `model_config = ConfigDict(extra="forbid")`):

```python
class LLMSceneModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str]
    subjects: list[str] = []
    description: str = ""
    natural_language: str = ""

class LLMCharacterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str = ""
    tags: list[str]
    position_hint: str = ""
    negative_tags: list[str] = []
    pose: str = ""
    expression: str = ""
    natural_language: str = ""

class LLMRelationshipModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    action: str
    mutual: bool = False

class LLMStructuredPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene: LLMSceneModel
    characters: list[LLMCharacterModel]
    relationships: list[LLMRelationshipModel] = []
    camera: str = ""
    composition: str = ""
    style: str = ""
    negative: list[str] = []
    unresolved: list[str] = []
```

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_schema.py`

```python
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
```

- [ ] **Step 2: 실패 확인**

```bash
python -m pytest tests/test_schema.py -q
```

Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: schema.py 구현** — 위 인터페이스 블록의 dataclass/pydantic 모델을 그대로 작성. `__all__`에 공개 이름 나열.

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_schema.py -q` → `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/naiauto/core/prompt/schema.py tests/test_schema.py
git commit -m "feat(prompt): add structured prompt schema"
```

---

## Task 3: 오류 계층 + LLM 인터페이스 + FakeLLMProvider

**Files:**
- Create: `src/naiauto/core/prompt/errors.py`
- Create: `src/naiauto/core/prompt/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: 없음
- Produces:

```python
# errors.py
class CompilerError(Exception): ...            # 모든 컴파일러 오류의 베이스
class CompilerConnectionError(CompilerError): ...   # 서버 오프라인/연결 실패
class CompilerTimeoutError(CompilerError): ...      # timeout
class CompilerAuthError(CompilerError): ...         # 401/403
class CompilerServerError(CompilerError):           # 기타 HTTP 오류 (status_code, body 스니펫 보관)
    def __init__(self, status_code: int, body: str = ""): ...
class CompilerParseError(CompilerError): ...        # JSON 추출/스키마 검증 실패
class CompilerEmptyResultError(CompilerError): ...  # 빈 응답/의미 없는 결과
class CompilerProviderUnavailableError(CompilerError): ...  # provider 설정 누락 등

# llm.py
class LLMProvider(Protocol):
    """LLM 백엔드 인터페이스 — UI/GUI는 이 프로토콜에만 의존한다."""
    name: str
    def chat(self, messages: list[dict[str, str]], *,
             temperature: float, max_tokens: int, timeout: float) -> str:
        """메시지 목록을 보내고 응답 텍스트를 돌려준다. 오류는 CompilerError 계층으로."""
        ...

class FakeLLMProvider:
    """테스트용 결정적 provider. response 반환 또는 error raise."""
    name = "fake"
    def __init__(self, response: str = "", responses: list[str] | None = None,
                 error: Exception | None = None) -> None: ...
    def chat(self, messages, *, temperature, max_tokens, timeout) -> str:
        # responses 리스트가 있으면 순서대로 소비(소진 시 마지막 재사용), error가 있으면 raise.
```

- [ ] **Step 1: 실패 테스트** — `tests/test_llm.py`

```python
import pytest

from naiauto.core.prompt.errors import (
    CompilerAuthError,
    CompilerConnectionError,
    CompilerEmptyResultError,
    CompilerError,
    CompilerParseError,
    CompilerServerError,
    CompilerTimeoutError,
)
from naiauto.core.prompt.llm import FakeLLMProvider, LLMProvider


def test_fake_provider_returns_canned_response():
    provider = FakeLLMProvider(response='{"scene": {"tags": ["cafe"]}}')
    out = provider.chat([], temperature=0.3, max_tokens=100, timeout=5)
    assert '"cafe"' in out


def test_fake_provider_raises_error():
    provider = FakeLLMProvider(error=CompilerConnectionError("offline"))
    with pytest.raises(CompilerError):
        provider.chat([], temperature=0.3, max_tokens=100, timeout=5)


def test_fake_provider_consumes_response_list_in_order():
    provider = FakeLLMProvider(responses=["first", "second", "third"])
    got = [provider.chat([], temperature=0, max_tokens=1, timeout=1) for _ in range(4)]
    assert got[:3] == ["first", "second", "third"]
    assert got[3] == "third"  # 소진 후 마지막 재사용


def test_error_hierarchy_all_subclass_compiler_error():
    for cls in (CompilerConnectionError, CompilerTimeoutError, CompilerAuthError,
                CompilerServerError, CompilerParseError, CompilerEmptyResultError):
        assert issubclass(cls, CompilerError)


def test_server_error_carries_status_and_body():
    err = CompilerServerError(500, "sever debug")
    assert err.status_code == 500
    assert "sever" in str(err)
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_llm.py -q` → FAIL

- [ ] **Step 3: 구현** — errors.py와 llm.py를 위 인터페이스 그대로 작성. `CompilerServerError.status_code`/`body` 속성, `__str__`은 상태 코드를 포함.

- [ ] **Step 4: 통과 확인**

- [ ] **Step 5: Commit**

```bash
git add src/naiauto/core/prompt/errors.py src/naiauto/core/prompt/llm.py tests/test_llm.py
git commit -m "feat(prompt): add error hierarchy and LLM provider interface"
```

---

## Task 4: LLM Provider 구현 (OpenAI 호환 + Ollama)

**Files:**
- Create: `src/naiauto/core/prompt/providers/__init__.py`
- Create: `src/naiauto/core/prompt/providers/openai_compatible.py`
- Create: `src/naiauto/core/prompt/providers/ollama.py`
- Test: `tests/test_providers.py`

**Interfaces:**
- Consumes: `llm.LLMProvider`, `errors.*`, `settings.schema.PromptAISettings`(Task 10에 정의되지만 순환 방지를 위해 providers는 `base_url: str`, `model: str`, `api_key: str` 인자만 받는다 — Task 10에서 `create_provider`를 통해 연결)

```python
# providers/openai_compatible.py
class OpenAICompatibleProvider:
    """OpenAI 호환 /chat/completions (llama.cpp, LM Studio, 원격 API)."""
    name = "openai_compatible"
    def __init__(self, base_url: str, model: str = "", api_key: str = "") -> None:
        # base_url은 "/v1" 포함 (예: http://127.0.0.1:7112/v1)
        # api_key 빈 문자열이면 Authorization 헤더 생략
    def chat(self, messages, *, temperature, max_tokens, timeout) -> str: ...

# providers/ollama.py
class OllamaProvider:
    """Ollama 네이티브 /api/chat."""
    name = "ollama"
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "", api_key: str = "") -> None:
    def chat(self, messages, *, temperature, max_tokens, timeout) -> str: ...

# providers/__init__.py
API_KEY_CREDENTIAL = "llm_api_key"
def create_provider(*, provider: str, base_url: str, model: str, api_key: str = "") -> LLMProvider:
    """provider == "ollama" → OllamaProvider / "openai_compatible" → OpenAICompatibleProvider.
    알 수 없는 provider → CompilerProviderUnavailableError."""
```

**HTTP 처리 규칙 (두 provider 공통, `requests` 재사용):**

```python
import requests

def _post_json(url, payload, headers, timeout_seconds) -> requests.Response:
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout_seconds)
    except requests.exceptions.Timeout:
        raise CompilerTimeoutError(f"LLM request timed out after {timeout_seconds}s")
    except requests.exceptions.RequestException as e:
        raise CompilerConnectionError(f"cannot reach LLM server at {url}: {e}")
    if resp.status_code in (401, 403):
        raise CompilerAuthError(f"LLM auth failed ({resp.status_code})")
    if resp.status_code != 200:
        raise CompilerServerError(resp.status_code, resp.text[:300])
    return resp
```

**OpenAI 호환 요청/응답:**

```python
# 요청
{
    "model": model or "local-model",
    "messages": messages,
    "temperature": temperature,
    "max_tokens": max_tokens,
    "stream": False,
}
# headers: {"Content-Type": "application/json", **({"Authorization": f"Bearer {api_key}"} if api_key else {})}
# url = base_url.rstrip("/") + "/chat/completions"
# 응답 파싱:
#   data = resp.json(); choices[0]["message"]["content"] — 없으면 CompilerEmptyResultError
#   resp.json() 실패 (json.JSONDecodeError) → CompilerParseError
```

**Ollama 요청/응답:**

```python
# 요청 (base_url에 /api/chat 직접 이어붙임)
{
    "model": model or "llama3",
    "messages": messages,
    "stream": False,
    "options": {"temperature": temperature, "num_predict": max_tokens},
}
# 응답: data["message"]["content"] — 없으면 CompilerEmptyResultError
```

**사용 시나리오:** llama.cpp 서버 예 — `base_url="http://127.0.0.1:7112/v1"`, model은 llama.cpp 서버가 등록한 모델명(`/v1/models`로 확인 가능, 보통 파일명).

- [ ] **Step 1: 실패 테스트** — `tests/test_providers.py` (requests.post를 monkeypatch)

```python
import json

import pytest
import requests

from naiauto.core.prompt.errors import (
    CompilerAuthError,
    CompilerConnectionError,
    CompilerEmptyResultError,
    CompilerParseError,
    CompilerProviderUnavailableError,
    CompilerServerError,
    CompilerTimeoutError,
)
from naiauto.core.prompt.providers import create_provider
from naiauto.core.prompt.providers.ollama import OllamaProvider
from naiauto.core.prompt.providers.openai_compatible import OpenAICompatibleProvider


class _FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None, raise_for_body=False):
        self.status_code = status_code
        self.text = text
        self._json = json_data
        self.raise_for_body = raise_for_body
        self.headers = {}

    def json(self):
        if self.raise_for_body:
            raise json.JSONDecodeError("bad", "doc", 0)
        return self._json


def _monkeypatch_post(monkeypatch, response, error=None):
    def fake_post(*args, **kwargs):
        if error is not None:
            raise error
        return response

    monkeypatch.setattr(requests, "post", fake_post)


def test_openai_provider_parses_chat_completion(monkeypatch):
    resp = _FakeResponse(json_data={"choices": [{"message": {"content": "hello"}}]})
    _monkeypatch_post(monkeypatch, resp)
    provider = OpenAICompatibleProvider(base_url="http://127.0.0.1:7112/v1", model="qwen")
    out = provider.chat([{"role": "user", "content": "hi"}], temperature=0.5, max_tokens=64, timeout=10)
    assert out == "hello"


def test_openai_provider_timeout_maps_to_timeout_error(monkeypatch):
    _monkeypatch_post(monkeypatch, None, error=requests.exceptions.Timeout())
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with pytest.raises(CompilerTimeoutError):
        provider.chat([], temperature=0, max_tokens=1, timeout=1)


def test_openai_provider_connection_error(monkeypatch):
    _monkeypatch_post(monkeypatch, None, error=requests.exceptions.ConnectionError("refused"))
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with pytest.raises(CompilerConnectionError):
        provider.chat([], temperature=0, max_tokens=1, timeout=1)


def test_openai_provider_auth_error(monkeypatch):
    _monkeypatch_post(monkeypatch, _FakeResponse(status_code=401, text="no"))
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m", api_key="bad")
    with pytest.raises(CompilerAuthError):
        provider.chat([], temperature=0, max_tokens=1, timeout=1)


def test_openai_provider_server_error(monkeypatch):
    _monkeypatch_post(monkeypatch, _FakeResponse(status_code=500, text="boom"))
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with pytest.raises(CompilerServerError) as ei:
        provider.chat([], temperature=0, max_tokens=1, timeout=1)
    assert ei.value.status_code == 500


def test_openai_provider_empty_content(monkeypatch):
    _monkeypatch_post(monkeypatch, _FakeResponse(json_data={"choices": []}))
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with pytest.raises(CompilerEmptyResultError):
        provider.chat([], temperature=0, max_tokens=1, timeout=1)


def test_openai_provider_malformed_json_body(monkeypatch):
    _monkeypatch_post(monkeypatch, _FakeResponse(json_data=None, raise_for_body=True))
    provider = OpenAICompatibleProvider(base_url="http://x/v1", model="m")
    with pytest.raises(CompilerParseError):
        provider.chat([], temperature=0, max_tokens=1, timeout=1)


def test_ollama_provider_parses_response(monkeypatch):
    resp = _FakeResponse(json_data={"message": {"content": "bye"}, "done": True})
    _monkeypatch_post(monkeypatch, resp)
    provider = OllamaProvider(base_url="http://localhost:11434", model="gemma3")
    out = provider.chat([{"role": "user", "content": "hi"}], temperature=0.4, max_tokens=32, timeout=10)
    assert out == "bye"


def test_create_provider_factory():
    p = create_provider(provider="openai_compatible", base_url="http://x/v1", model="m")
    assert isinstance(p, OpenAICompatibleProvider)
    p2 = create_provider(provider="ollama", base_url="http://localhost:11434", model="m")
    assert isinstance(p2, OllamaProvider)
    with pytest.raises(CompilerProviderUnavailableError):
        create_provider(provider="wat", base_url="", model="")
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: 구현** — 위 규칙대로 3개 파일 작성. 핵심 주의: `CompilerParseError`는 JSONDecodeError를 감싸고, `CompilerEmptyResultError`는 content 누락 시.

- [ ] **Step 4: 통과 확인** — `10 passed`

- [ ] **Step 5: Commit**

```bash
git add src/naiauto/core/prompt/providers/ tests/test_providers.py
git commit -m "feat(prompt): add OpenAI-compatible and Ollama providers"
```

---

## Task 5: System Prompt 템플릿 + Parser (LLM → Structured Prompt)

**Files:**
- Create: `src/naiauto/core/prompt/templates/system_prompt.md`
- Create: `src/naiauto/core/prompt/parser.py`
- Test: `tests/test_parser.py`

**Interfaces:**
- Consumes: `llm.LLMProvider`, `errors.*`, `schema.LLMStructuredPrompt`
- Produces:

```python
def load_system_prompt() -> str
    # templates/system_prompt.md를 읽는다. 파일 누락 → CompilerProviderUnavailableError("system prompt template missing")

def extract_json(text: str) -> dict
    # 코드펜스(```json ... ```) 제거 후 첫 "{"부터 균형 잡힌 마지막 "}"까지 json.loads.
    # 실패 시 CompilerParseError(원문 200자 포함).

def parse_structured(text: str) -> LLMStructuredPrompt
    # extract_json + LLMStructuredPrompt.model_validate.
    # ValidationError → CompilerParseError(str(e) 요약).

PRESERVED_TOKEN_RE = re.compile(r"(__[\w=\-]+__|\{[^{}]*\})")

def build_messages(text: str, *, existing_prompt: str = "", preserved: tuple[str, ...] = ()) -> list[dict[str, str]]
    # system: load_system_prompt() (+ modify 문단 필요시)
    # user는 다음 중 하나:
    #   수정 모드 (existing_prompt 비어있지 않음):
    #     "EXISTING PROMPT:\n{existing_prompt}\n\nPRESERVED TOKENS (must not be removed from the final prompt):\n{', '.join(preserved) or '(none)'}\n\nMODIFICATION REQUEST:\n{text}"
    #   생성 모드:
    #     "{text}"

class SceneParser:
    """LLM 호출 + 구조화 파싱을 묶은 Scene Understanding Layer."""
    def __init__(self, provider: LLMProvider, *, temperature: float = 0.3,
                 max_tokens: int = 2048, timeout: float = 120.0) -> None: ...
    def parse(self, text: str, *, existing_prompt: str = "",
              preserved: tuple[str, ...] = ()) -> LLMStructuredPrompt:
        # provider.chat(build_messages(...)) → parse_structured
        # 응답이 비면 CompilerEmptyResultError
```

**system_prompt.md 전체 내용** (이 파일 그대로 작성):

```markdown
You are a NovelAI V5 prompt analysis assistant.

Your job is to transform the user's image description into structured
scene, character and relationship information.

RULES:
- Output ONLY valid JSON. No markdown, no commentary, no code fences.
- Do not generate NovelAI API requests, API payloads, or parameter values.
- Do not invent nonexistent Danbooru tags. Use common, well-known Danbooru
  style tags (single words or underscore_joined). When a concept cannot be
  expressed by a reliable tag, leave it out of "tags" and describe it in
  natural_language fields instead.
- Preserve user intent. Never invert or replace explicit details.
- Separate:
  - global scene / environment / lighting / weather / camera -> scene, camera, composition, style
  - individual characters (appearance, clothing, pose, expression) -> characters
  - character relationships / interactions -> relationships
- Character-specific visual traits (hair, eyes, clothing, accessories) belong
  to the character's tags, never to the scene.
- Global scene properties (rain, night, location, lighting, camera angle)
  belong to scene.tags / camera / composition / style, never to a character.
- "subjects" lists the subject kind per character, e.g. ["girl", "girl"],
  ["girl"], ["boy"]. Use only: girl, boy, man, woman, child, cat, dog,
  bird, rabbit, fox, wolf, dragon, robot, or "" when unknown.
- "position_hint" per character: one of "", "far_left", "left", "center",
  "right", "far_right". Optionally append vertical: "left top", "right bottom".
  Only set when the user explicitly states a position.
- "negative" lists explicitly requested negative requirements, e.g. "bad_hands"
  when the user says hands should not be broken. Do not add generic negative
  tags unless the user asked.
- Return this exact JSON shape:
  {
    "scene": {
      "tags": ["string"],
      "subjects": ["string"],
      "description": "one sentence, English",
      "natural_language": "non-tag global details, English"
    },
    "characters": [
      {
        "id": "c1",
        "description": "short English description",
        "tags": ["silver_hair", "school_uniform", "sitting"],
        "position_hint": "left",
        "negative_tags": [],
        "pose": "",
        "expression": "",
        "natural_language": "character-specific details tags cannot express"
      }
    ],
    "relationships": [
      {"source": "c1", "target": "c2", "action": "talking_to", "mutual": false}
    ],
    "camera": "low angle shot from below",
    "composition": "",
    "style": "",
    "negative": [],
    "unresolved": ["concepts you could not map to reliable tags"]
  }

Relationships actions must come from this list only:
looking_at, talking_to, facing, holding_hands, hugging, standing_next_to,
sitting_opposite, chasing, following, pointing_at, touching, waving_to,
leaning_on

- "mutual": true when both characters do the action to each other
  (e.g. looking at each other, holding hands, facing each other).
- When modifying an existing prompt, apply the user's modification with
  MINIMAL semantic change: keep all character identities and details that
  the user did not ask to change. Never rewrite the background unless asked.
- Do not add decorative filler sentences. Only include what the user implied
  or explicitly stated.

Examples:
  1girl, silver_hair, short_hair, school_uniform, rain, night, alley →
  scene.tags: ["rain", "night", "alley"], characters: [{id: "c1",
  tags: ["silver_hair", "short_hair", "school_uniform"]}], subjects: ["girl"]
```

(영어 코어에 한/영 예시를 추가 — 위 Example 블록 아래에 한국어 입력 예시 1개를 덧붙인다: "비 오는 밤의 골목에 서 있는 은발 소녀" → 같은 구조.)

- [ ] **Step 1: 실패 테스트** — `tests/test_parser.py`

```python
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
    assert "NovelAI V5 prompt analysis assistant" in text
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
    assert "NovelAI" in msgs[0]["content"]
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
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: 구현** — 템플릿 파일 + parser.py. `extract_json`은 문자열에서 `{`..`}` 균형 매칭으로 잘라낸 뒤 `json.loads`. 실패 시 원문 앞 200자 포함해 CompilerParseError.

- [ ] **Step 4: 통과 확인** — `11 passed`

- [ ] **Step 5: Commit**

```bash
git add src/naiauto/core/prompt/templates/system_prompt.md src/naiauto/core/prompt/parser.py tests/test_parser.py
git commit -m "feat(prompt): add LLM system prompt template and scene parser"
```

---

## Task 6: Danbooru Tag Resolver

**Files:**
- Create: `src/naiauto/core/prompt/resolver.py`
- Create: `src/naiauto/resources/tags/danbooru_tags_extra.csv` — [Ruling #5] NAI UC 어휘 보조 파일
- Modify: `src/naiauto/core/prompt/templates/system_prompt.md` — [Ruling #5] deprecation 1줄 추가
- Test: `tests/test_resolver.py`

**Interfaces:**
- Consumes: `core.tag_completer.parse_tag_line / bundled_database_path / resolve_database_path` (DB 로드 재사용), `schema.TagRef`
- Produces:

```python
class TagResolver:
    """후보 태그 문구 → 검증된 Danbooru 태그.

    결정적(deterministic) 검증만 한다 — LLM은 후보만 내고, 여기서 실제 tag인지
    판정한다. DB에 없는 태그는 status="unresolved" TagRef 하나로 돌려주며
    final prompt에 넣지 않는다 (스펙 §10, §41).

    [Ruling #5 적용] 메인 DB(동봉 또는 사용자 지정)와 별도로 내장 보조 파일
    `danbooru_tags_extra.csv`를 로드한다 — Danbooru 추출본에 없지만 NovelAI
    UC/quality 어휘에 속하는 소수 단어(text, worst_quality, bad_quality,
    blank_page)만 담겨 있다. 보조 파일은 메인 DB 로드가 성공했을 때만 병합된다.

    [Ruling #5 적용] 알려진 Danbooru 병합/철자 변형은 alias 사전으로 정규화한다:
    silver_hair→grey_hair (Danbooru에서 deprecated·병합됨),
    blond_hair→blonde_hair (canonical 철자). alias는 토큰 분해보다 먼저 적용된다.
    """
    def __init__(self, database_path: Path | None = None) -> None:
        # None → bundled_database_path()
    def load(self) -> bool: ...
    @property
    def is_enabled(self) -> bool: ...
    @property
    def tag_count(self) -> int: ...
    def resolve_phrase(self, phrase: str) -> tuple[TagRef, ...]:
        """하나의 후보 문구 → 1..n개의 검증된 TagRef.

        규칙 (순서대로):
        1. 정규화(norm): 소문자, 공백→언더스코어, 하이픈→언더스코어,
           끝단어가 아닌 문장부호 제거. DB 존재 → TagRef(norm, "verified", post_count=DB값)
        1.5 alias 확인: norm(또는 변형 규칙 2/3의 후보)이 ALIASES에 있으면
            canonical 태그로 대체해 DB 존재 확인 (silver_hair → grey_hair)
        2. "{stem}_haired" → DB에 "{stem}_hair" 존재하면 verified (alias 경유 포함)
           "{stem}_eyed"  → DB에 "{stem}_eyes" 존재하면 verified
        3. "{a}_{b}_hair" / "_eyes" 복합 신체 속성: 접두어를 '_'로 분리해 각 단어에
           접미사를 붙여 DB 존재 확인 (alias 경유 포함) — 하나 이상 존재하면 그 refs
           반환 ("long black hair" → long_hair, black_hair). 단어 "bob" → "bob_cut".
        4. 일반 다중 토큰: norm을 공백 또는 '_'로 분리한 각 토큰을 개별 DB 조회
           ("wet_road" → wet, road). 전부 verified면 목록 반환 (source="inferred")
           하나라도 실패하면 전체를 unresolved(전체 정규화명) 하나로 반환
        5. 어느 것도 못 찾으면 TagRef(norm, "unresolved", post_count=0) 하나 반환
        """

ALIASES: dict[str, str] = {
    # [Ruling #5] Danbooru 태그 병합/철자 정규화 (2026-08-28 확인)
    "silver_hair": "grey_hair",    # Danbooru에서 deprecated → grey_hair로 통합
    "blond_hair": "blonde_hair",   # canonical 철자는 blonde_hair
}

def bundled_extra_path() -> Path:
    """내장 보조 태그 파일 (NAI UC 어휘) — danbooru_tags_extra.csv"""
```

**마스킹 규칙:** norm 정규화 정확한 정의:

```python
_TRAILING_PUNCT_RE = re.compile(r"[^A-Za-z0-9_]+$")

def _norm(phrase: str) -> str:
    text = phrase.strip().lower().strip(".,;:!?\"'()[]{}")
    text = _TRAILING_PUNCT_RE.sub("", text)
    return re.sub(r"\s+", "_", text)
```

DB 구조: `dict[str, TagEntry]` — `{entry.name.lower(): entry}` + 원본 이름 목록은 `suggest` 용이 아니므로 생략. `parse_tag_line`로 파일을 읽어 채운다. (별도 alias DB 없음 — 규칙 2가 `_haired`/`_eyed` 변형을 흡수한다.)

- [ ] **Step 1: 실패 테스트** — `tests/test_resolver.py`

```python
import pytest

from naiauto.core.prompt.resolver import TagResolver


@pytest.fixture()
def resolver(bundled_db_path):
    r = TagResolver(database_path=bundled_db_path)
    assert r.load()
    return r


def test_silver_hair_aliases_to_grey_hair(resolver):
    # [Ruling #5] Danbooru에서 silver_hair는 deprecated — grey_hair가 canonical
    refs = resolver.resolve_phrase("silver hair")
    assert len(refs) == 1
    assert refs[0].tag == "grey_hair"
    assert refs[0].status == "verified"
    assert refs[0].post_count > 0


def test_underscore_input_ok(resolver):
    refs = resolver.resolve_phrase("silver_hair")
    assert refs[0].tag == "grey_hair"


def test_capitalized_and_punctuated(resolver):
    refs = resolver.resolve_phrase("Silver Hair,")
    assert refs[0].tag == "grey_hair"


def test_blond_hair_aliases_to_blonde_hair(resolver):
    # [Ruling #5] canonical 철자는 blonde_hair
    refs = resolver.resolve_phrase("blond hair")
    assert refs[0].tag == "blonde_hair"
    assert refs[0].status == "verified"


def test_long_black_hair_splits_into_parts(resolver):
    refs = resolver.resolve_phrase("long black hair")
    tags = {r.tag for r in refs}
    assert {"long_hair", "black_hair"} <= tags
    assert all(r.status == "verified" for r in refs)


def test_haired_variant_rule(resolver):
    refs = resolver.resolve_phrase("silver-haired")
    assert refs[0].tag == "grey_hair"
    assert refs[0].status == "verified"


def test_eyed_variant_rule(resolver):
    refs = resolver.resolve_phrase("red-eyed")
    assert any(r.tag == "red_eyes" and r.status == "verified" for r in refs)


def test_underscore_compound_splits_into_tokens(resolver):
    # [Ruling #5] "wet_road" → wet + road (둘 다 DB에 존재)
    refs = resolver.resolve_phrase("wet_road")
    tags = {r.tag for r in refs}
    assert {"wet", "road"} <= tags
    assert all(r.status == "verified" for r in refs)


def test_nai_negative_vocabulary_verified(resolver):
    # [Ruling #5] 보조 파일(danbooru_tags_extra.csv)의 NAI UC 어휘
    refs = resolver.resolve_phrase("text")
    assert refs[0].tag == "text"
    assert refs[0].status == "verified"


def test_nonexistent_tag_is_unresolved(resolver):
    refs = resolver.resolve_phrase("cinematic melancholic atmosphere")
    assert len(refs) == 1
    assert refs[0].status == "unresolved"
    assert refs[0].tag == "cinematic_melancholic_atmosphere"
    assert refs[0].post_count == 0


def test_empty_phrase_unresolved(resolver):
    refs = resolver.resolve_phrase("")
    assert refs[0].status == "unresolved"


def test_unknown_single_token_not_splittable(resolver):
    # DB에 없는 조합인데 토큰 분해도 불가하면 unresolved
    refs = resolver.resolve_phrase("zzzqqq")
    assert refs[0].status == "unresolved"


def test_resolver_disabled_when_db_missing(tmp_path):
    # 메인 DB 로드 실패 시 보조 파일도 적용하지 않는다 (Ruling #5)
    r = TagResolver(database_path=tmp_path / "nope.csv")
    assert r.load() is False
    assert r.is_enabled is False
    assert r.resolve_phrase("silver hair")[0].status == "unresolved"  # 폴백 동작
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 2.5: [Ruling #5] 보조 태그 파일 + 시스템 프롬프트 보강**

`src/naiauto/resources/tags/danbooru_tags_extra.csv` (정확히 이 내용 — `#` 주석 줄은 두 로더 모두 안전하게 건너뛴다):

```csv
# NovelAI UC/quality vocabulary absent from danbooru_tags_post_count.csv.
# These words appear in the app's own NovelAI UC presets / quality tags
# (core/api/model_specs.py: _UC_45F 등, quality_tags "no text").
# Captured 2026-08-28. Count is a presence marker, not a post count.
text[1]
worst_quality[1]
bad_quality[1]
blank_page[1]
```

`system_prompt.md`의 RULES 블록에 한 줄 추가 (영어, 기존 문체 유지):

```markdown
- Known Danbooru merges to avoid: use grey_hair (silver_hair is deprecated
  and merged into grey_hair), use blonde_hair (not blond_hair).
```

- [ ] **Step 3: 구현** — 위 인터페이스/규칙 블록 그대로. `load()`는 `parse_tag_line`/`bundled_database_path`/`resolve_database_path`를 재사용해 메인 파일을 읽고, **메인 로드 성공 시에만** `bundled_extra_path()`의 보조 파일을 병합한다. 정규화는 소문자 + 하이픈→언더스코어 + 공백→언더스코어 + 끝단어가 아닌 문장부호 제거. alias(`ALIASES`)는 규칙 1·2·3의 DB 존재 확인 시 canonical 변환 경로로 적용 (규칙 4 토큰 분해보다 먼저).

- [ ] **Step 4: 통과 확인** — `12 passed`

- [ ] **Step 5: Commit**

```bash
git add src/naiauto/core/prompt/resolver.py src/naiauto/resources/tags/danbooru_tags_extra.csv src/naiauto/core/prompt/templates/system_prompt.md tests/test_resolver.py
git commit -m "feat(prompt): add deterministic Danbooru tag resolver"
```

---

## Task 7: 위치 추정 + 관계 정규화

**Files:**
- Create: `src/naiauto/core/prompt/positions.py`
- Create: `src/naiauto/core/prompt/relationship.py`
- Test: `tests/test_positions.py`, `tests/test_relationship.py`

**Interfaces:**
- Consumes: `schema.CharacterPrompt`/`RelationshipPrompt`/`LLMRelationshipModel`
- Produces:

```python
# positions.py
X_HINTS = {"far_left": 0.15, "left": 0.30, "center": 0.50, "right": 0.70, "far_right": 0.85}
Y_HINTS = {"top": 0.30, "center": 0.50, "bottom": 0.70}

def estimate_position(hint: str) -> tuple[float, float] | None:
    """힌트 문자열("left", "right bottom", "center") → (x, y).

    명확한 힌트만 좌표로: 알 수 없는 토큰이 있거나 힌트가 비면 None.
    y 미지정 시 0.5."""

def estimate_positions(characters: tuple[CharacterPrompt, ...]) -> tuple[CharacterPrompt, ...]:
    """각 캐릭터의 center_x/center_y를 position_hint에서 계산해 새 튜플 반환.
    None이면 해당 캐릭터 좌표는 None 유지."""
```

관계 정규화:

```python
# relationship.py
RELATION_ACTIONS: frozenset[str] = frozenset({
    "looking_at", "talking_to", "facing", "holding_hands", "hugging",
    "standing_next_to", "sitting_opposite", "chasing", "following",
    "pointing_at", "touching", "waving_to", "leaning_on"})

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
    없으면 None."""

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
```

- [ ] **Step 1: 실패 테스트** — `tests/test_positions.py`

```python
import pytest

from naiauto.core.prompt.positions import (
    X_HINTS,
    Y_HINTS,
    estimate_position,
    estimate_positions,
)
from naiauto.core.prompt.schema import CharacterPrompt


def test_left_right_center():
    assert estimate_position("left") == (X_HINTS["left"], 0.5)
    assert estimate_position("right") == (X_HINTS["right"], 0.5)
    assert estimate_position("center") == (X_HINTS["center"], 0.5)


def test_spec_example_coordinates():
    assert estimate_position("left") == (0.30, 0.50)
    assert estimate_position("right") == (0.70, 0.50)


def test_far_left_far_right():
    assert estimate_position("far_left") == (0.15, 0.50)
    assert estimate_position("far_right") == (0.85, 0.50)


def test_vertical_combined():
    assert estimate_position("left bottom") == (0.30, 0.70)
    assert estimate_position("center top") == (0.50, 0.30)


def test_unknown_hint_returns_none():
    assert estimate_position("") is None
    assert estimate_position("somewhere") is None
    assert estimate_position("left somewhere") is None


def test_estimate_positions_assigns_only_known():
    chars = (
        CharacterPrompt(id="c1", position_hint="left", center_x=None, center_y=None),
        CharacterPrompt(id="c2", position_hint="right", center_x=None, center_y=None),
        CharacterPrompt(id="c3", position_hint="", center_x=None, center_y=None),
    )
    out = estimate_positions(chars)
    assert out[0].center_x == 0.30 and out[0].center_y == 0.50
    assert out[1].center_x == 0.70 and out[1].center_y == 0.50
    assert out[2].center_x is None and out[2].center_y is None
```

`tests/test_relationship.py`:

```python
import pytest

from naiauto.core.prompt.relationship import (
    RELATION_ACTIONS,
    normalize_action,
    normalize_relationships,
)
from naiauto.core.prompt.schema import LLMRelationshipModel


def test_synonyms_normalize():
    assert normalize_action("staring at") == "looking_at"
    assert normalize_action("chatting with") == "talking_to"
    assert normalize_action("conversing with") == "talking_to"
    assert normalize_action("face to face") == "facing"
    assert normalize_action("embracing") == "hugging"


def test_unknown_action_none():
    assert normalize_action("quantum entangling") is None


def test_whitespace_and_case_normalized():
    assert normalize_action("  Looking At  ") == "looking_at"


def test_mutual_expands_to_both_directions():
    rels, warns = normalize_relationships(
        [LLMRelationshipModel(source="c1", target="c2", action="facing", mutual=True)],
        {"c1", "c2"},
    )
    assert len(rels) == 2
    assert (rels[0].source, rels[0].target, rels[0].mutual) == ("c1", "c2", True)
    assert (rels[1].source, rels[1].target, rels[1].mutual) == ("c2", "c1", True)
    assert warns == []


def test_one_way_single_entry():
    rels, warns = normalize_relationships(
        [LLMRelationshipModel(source="c1", target="c2", action="looking_at")],
        {"c1", "c2"},
    )
    assert len(rels) == 1
    assert not rels[0].mutual


def test_unknown_character_id_warns_and_drops():
    rels, warns = normalize_relationships(
        [LLMRelationshipModel(source="c9", target="c2", action="looking_at")],
        {"c1", "c2"},
    )
    assert rels == []
    assert len(warns) == 1


def test_unknown_action_warns_and_drops():
    rels, warns = normalize_relationships(
        [LLMRelationshipModel(source="c1", target="c2", action="teleporting")],
        {"c1", "c2"},
    )
    assert rels == []
    assert len(warns) == 1


def test_all_actions_are_snake_case():
    assert all(" " not in a for a in RELATION_ACTIONS)
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: 구현** — 위 인터페이스 그대로. `estimate_position`은 hint를 공백 분리해 X/Y 토큰을 찾고, 미지 토큰이 있으면 None.

- [ ] **Step 4: 통과 확인** — `test_positions 6 + test_relationship 8 passed`

- [ ] **Step 5: Commit**

```bash
git add src/naiauto/core/prompt/positions.py src/naiauto/core/prompt/relationship.py tests/test_positions.py tests/test_relationship.py
git commit -m "feat(prompt): add position estimation and relationship normalization"
```

---

## Task 8: NovelAI V5 Formatter

**Files:**
- Create: `src/naiauto/core/prompt/formatter.py`
- Test: `tests/test_formatter.py`

**Interfaces:**
- Consumes: `schema.*` (ScenePrompt/CharacterPrompt/RelationshipPrompt/TagRef)
- Produces:

```python
SUBJECT_PLURALS: dict[str, str] = {
    "girl": "girls", "boy": "boys", "man": "men", "woman": "women",
    "child": "children", "cat": "cats", "dog": "dogs",
}

COUNT_TAG_RE = re.compile(r"^\d+(girls|girl|boys|boy|men|man|women|woman|children|child|cats|cat|dogs|dog)$")

ACTION_PHRASES: dict[str, str] = {
    "looking_at": "looking at", "talking_to": "talking to", "facing": "facing",
    "holding_hands": "holding hands", "hugging": "hugging",
    "standing_next_to": "standing next to", "sitting_opposite": "sitting opposite",
    "chasing": "chasing", "following": "following", "pointing_at": "pointing at",
    "touching": "touching", "waving_to": "waving to", "leaning_on": "leaning on",
}

class PromptFormatter:
    """구조화 프롬프트 → NovelAI V5 문자열.

    모드 (스펙 §14):
      tag     — 검증된 태그만, 쉼표 결합
      hybrid  — 태그 + 자연어 문장 (기본값)
      natural — 자연어 중심 (scene/char의 description·natural_language)

    정렬 규칙 (스펙 §53): base = [count 태그] + scene 태그 + [관계 태그형] + camera + style + NL 단락
    캐릭터 prompt: appearance/clothing/pose/expression 태그 + NL.
    count 태그는 base에만 (스펙 §21, §55). scene 태그에 이미 count 태그가 있으면 중복 제거.
    """
    def __init__(self, *, preserve_natural_language: bool = True,
                 relationship_style: str = "natural") -> None:
        # relationship_style: "natural" | "tag"
    def format(self, *, scene: ScenePrompt, characters: tuple[CharacterPrompt, ...],
               relationships: tuple[RelationshipPrompt, ...],
               negative_tags: tuple[TagRef, ...], mode: str) -> tuple[str, str]:
        """(base_prompt, negative_prompt) 반환."""
    def count_tag(self, subjects: tuple[str, ...]) -> str:
        """subjects가 모두 같고 단수형 SUBJECT_PLURALS에 있으면 "{n}{plural}" (n>=2) /
        "1girl" 등 (n==1). 그 외엔 ""."""
    def relationship_sentences(self, relationships, characters) -> list[str]: ...
    def relationship_tag_segment(self, relationships) -> str: ...
```

**포맷 규칙 상세 (구현 시 이대로):**

- `count_tag`: `subjects=("girl","girl")` → `"2girls"`; `("girl",)` → `"1girl"`; `("girl","boy")` → `""`; `()` → `""`.
- base 태그 목록: `[count] + [scene.tags 중 COUNT_TAG_RE 아닌 것들의 tag 문자열] + ([관계 태그형] if relationship_style=="tag") + [camera 태그? no — camera는 문장]`. camera/composition/style은 자연어로만 (태그가 있으면 scene.tags에 이미 있음 — camera는 LLM의 camera 필드 문자열).
- base 문자열 (tag/hybrid): `", ".join(base_tags)` + (preserve_nl and mode != "tag"이면) `"\n\n" + "\n".join(nl_segments)`. NL 세그먼트 순서: scene.natural_language(또는 description) → camera 문장(`"Camera: {camera}"` 대신 그대로 문장) → relationship_sentences.
- tag 모드: 태그만, NL 제외. camera/composition/style 필드는 tag 모드에서도 태그가 아니므로 생략 (scene.tags가 이미 담당).
- natural 모드: base = 문장만 — scene.description이 있으면 그것, 없으면 scene.natural_language, 그것도 없으면 검증된 scene 태그를 `", ".join`으로 폴백. + relationship 문장. camera/style 문장 덧붙임. count 없음 (또는 "Two girls" 자연어 — subjects 기반: `f"{n} {plural}"` 문장 시작에).

  NATURAL 구체 규칙:
  ```
  parts = []
  if scene.natural_language: parts.append(scene.natural_language)
  elif scene.description: parts.append(scene.description)
  for r in relationships: parts.append(sentence)
  if scene.camera: parts.append(f"{sentence case}")  # camera를 그대로 문장으로
  if scene.style: parts.append(scene.style)
  base = "\n".join(parts)
  ```
  NAI는 자연어 프롬프트를 그대로 받으므로 쉼표 결합 대신 줄바꿈/마침표 문장.

- 캐릭터 prompt (모든 모드): `", ".join(char.tags의 tag 문자열)` + (hybrid/natural이고 preserve_nl이면) `"\n\n" + char.natural_language`. natural 모드에서 char.tags가 비고 natural_language 있으면 그것만.
- negative: `", ".join(negative_tags의 tag)` — verified만.
- relationship_sentences:
  - mutual 쌍 (c1→c2, c2→c1 같은 action): `"The two girls are {phrase} each other."` 여기서 "girls"는 subjects 기반(("girl","girl") → "girls") — 정확한 대상 명사: 첫 문장부. `subjects_phrase = f"{len} {plural}"` 또는 "characters". 구현: scene.subjects에서 동일한 plural 가능 시 `f"The two {plural} are ..."`, 아니면 `"The two characters are ..."`.
  - 단방향: 위치 힌트 있으면 `"The character on the {left} is {phrase} the character on the {right}."`, 없으면 `"Character {src} is {phrase} Character {dst}."`
- relationship_tag_segment (tag 스타일 옵션): 각 관계에 대해 mutual → `"{src}#{action} {dst}#{action}"`, 단방향 → `"{src}#{action}"`. 복수 관계는 ", " 결합.

- **문자열 sanitation**: base_prompt 최종 조립 후 앞뒤 공백/중복 쉼표 정리 (`re.sub(r"\s*,\s*", ", ", ...)` 등).

- [ ] **Step 1: 실패 테스트** — `tests/test_formatter.py`

```python
import pytest

from naiauto.core.prompt.formatter import (
    COUNT_TAG_RE,
    PromptFormatter,
    SUBJECT_PLURALS,
)
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
    scene = _scene(subjects=("girl", "girl"))
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
```

`character_prompt_text`는 위 인터페이스 블록에 추가된 공개 메서드:

```python
def character_prompt_text(self, character: CharacterPrompt, mode: str) -> str: ...
    # 캐릭터용 문자열 — base와 독립적으로 조립 (컴파일러가 사용)
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: 구현** — 규칙 상세 블록 그대로. 추가 공개 메서드 `character_prompt_text(character, mode)`.

- [ ] **Step 4: 통과 확인** — `12 passed`

- [ ] **Step 5: Commit**

```bash
git add src/naiauto/core/prompt/formatter.py tests/test_formatter.py
git commit -m "feat(prompt): add NovelAI V5 prompt formatter (tag/hybrid/natural)"
```

---

## Task 9: Merge + Compiler 오케스트레이션

**Files:**
- Create: `src/naiauto/core/prompt/merge.py`
- Create: `src/naiauto/core/prompt/compiler.py`
- Create: `src/naiauto/core/prompt/__init__.py`
- Test: `tests/test_merge.py`, `tests/test_compiler.py` (골든 예제 통합)

**Interfaces:**
- Consumes: 모든 이전 태스크 (schema/parser/resolver/positions/relationship/formatter/llm/errors)
- Produces:

```python
# merge.py
from ..api.models import CharacterCaption  # 기존 스키마 재사용 — API 계층은 수정하지 않는다

@dataclass(frozen=True)
class MergeResult:
    prompt: str
    negative_prompt: str
    characters: tuple[CharacterCaption, ...]

def to_generation_data(compiled: CompiledPrompt, *, existing_negative: str = "") -> MergeResult:
    """CompiledPrompt → 기존 편집기/GenerationRequest 호환 데이터.

    - prompt = compiled.base_prompt (이미 최종 문자열)
    - negative = 기존 사용자 negative와 컴파일 negative를 중복 없이 병합
      (스펙 §22: "기존 negative prompt는 보존한다. 사용자 negative와 compiler negative를
      명확하게 병합한다.")
    - characters = CharacterCaption(prompt=char_prompt_text, uc=negative_tags join,
                                    center_x=center_x or 0.5, center_y=center_y or 0.5)
      (use_coords=False면 client가 0.5로 강제하는 기존 규칙을 그대로 따른다)

def merge_negatives(existing: str, compiled: str) -> str: ...
    # ", ".join(dict.fromkeys((existing, compiled) 분할 → strip → 빈값 제거))

# compiler.py
class PromptCompiler:
    """전체 파이프라인 오케스트레이션 (스펙 §34 인터페이스)."""
    def __init__(
        self,
        provider: LLMProvider,
        resolver: TagResolver,
        formatter: PromptFormatter,
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float = 120.0,
        use_resolver: bool = True,
    ) -> None: ...

    def compile(self, text: str, *, mode: str = "hybrid") -> CompiledPrompt: ...
        # 1. text.strip() 빈값 → CompilerEmptyResultError("empty input")
        # 2. parser.parse(text) → raw (LLMStructuredPrompt)
        # 3. _assemble(raw, mode)

    def modify(self, existing_prompt: str, instruction: str, *, mode: str = "hybrid") -> CompiledPrompt: ...
        # 1. preserved = PRESERVED_TOKEN_RE.findall(existing_prompt)
        # 2. parser.parse(instruction, existing_prompt=existing_prompt, preserved=preserved)
        # 3. result = _assemble(raw, mode)
        # 4. 보존 토큰이 base_prompt에 없으면 base_prompt 끝에 ", " + join(빠진 토큰) 추가
        #    (스펙 §51: wildcards는 컴파일러가 제거하지 않는다)

    def _assemble(self, raw: LLMStructuredPrompt, mode: str) -> CompiledPrompt: ...
        # 1. scene 태그 해석: resolver.resolve_phrase 각각 → verified/inferred만 scene.tags,
        #    unresolved는 취합
        # 2. 캐릭터 태그 해석: 동일. position_hint → estimate_positions 적용
        # 3. use_resolver=False면 raw 태그를 전부 verified로 처리 (태그 검증 끄기)
        # 4. relationships = normalize_relationships(raw.relationships, char_ids)
        # 5. negative 해석: raw.negative → resolver → verified만 negative_tags
        # 6. scene.subjects = raw.scene.subjects (count 태그용)
        # 7. formatter.format(...) → (base, neg)
        # 8. 캐릭터별 character_prompt_text → 차후 merge가 사용하도록 CharacterPrompt에
        #    natural_language 유지 + compiled.characters는 CharacterPrompt 그대로
        # 9. 빈 결과 체크: scene.tags 없음 + characters 없음 → CompilerEmptyResultError
        # 10. CompiledPrompt(...) — warnings에 관계 경고 + unresolved 태그 포함

# __init__.py
__all__ = ["PromptCompiler", "CompiledPrompt", "build_compiler", "to_generation_data",
           "MergeResult", "TagResolver", "PromptFormatter", "API_KEY_CREDENTIAL"]

def build_compiler(settings) -> PromptCompiler: ...
    # settings(AppSettings) → provider=create_provider(...), resolver=TagResolver(경로),
    # formatter=PromptFormatter(preserve_natural_language=settings.compiler.preserve_natural_language,
    #                           relationship_style=settings.compiler.relationship_style)
    # 온전성을 위해 provider 설정 미완료(예: ollama인데 model 비어있음)는 여기서 기본값 보정
    # (Task 10의 PromptAISettings 필드명에 의존 — Task 10에서 완성)
```

**세부 규칙:**
- `_assemble`의 unresolved 취합: 모든 unresolved TagRef의 tag 문자열을 `compiled.unresolved`로.
- warnings는 `normalize_relationships` 경고 + (unresolved 태그 수 > 0이면) "N unresolved concept(s) were not added to the final prompt: ..." 1줄.
- `compile()`에서 `raw.characters` id 충돌 시 LLM이 재사용해도 무방 — resolver/positions가 id로만 참조.
- 캐릭터가 0명이면 scene만 있는 프롬프트도 유효 (배경만). `scene.tags`가 비고 characters도 비면 → CompilerEmptyResultError.

- [ ] **Step 1: 실패 테스트** — `tests/test_merge.py`

```python
from naiauto.core.prompt.merge import merge_negatives, to_generation_data
from naiauto.core.prompt.schema import (
    CharacterPrompt,
    CompiledPrompt,
    RelationshipPrompt,
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
```

`tests/test_compiler.py` (골든 예제 — 스펙 §70):

```python
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
    return ("밤의 비 내리는 도시에서 왼쪽에는 긴 은발의 소녀가 검은 드레스를 입고 서 있고, "
            "오른쪽에는 붉은 단발머리의 소녀가 우산을 들고 서 있다. "
            "두 사람은 서로를 바라보고 있으며 젖은 도로에 네온사인이 반사되고 있다. "
            "카메라는 두 사람을 낮은 앵글에서 바라본다.")


def _compiler(response=GOLDEN_JSON, resolver_kwargs=None):
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
        '"position_hint": "right"', '"position_hint": "somewhere"')
    compiled = _compiler(response=data).compile("테스트", mode="hybrid")
    assert compiled.characters[0].center_x is None
    assert compiled.characters[1].center_x is None


def test_modify_preserves_wildcard_tokens():
    existing = "1girl, silver_hair, school_uniform, __hairstyle__, classroom"
    response = GOLDEN_JSON.replace('"city", "night", "rain", "wet_road", "neon_lights"',
                                   '"rooftop", "night"')
    compiled = _compiler(response=response).modify(
        existing_prompt=existing, instruction="교실을 밤의 옥상으로 바꾸고 우산을 추가해줘.",
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
```

- [ ] **Step 2: 실패 확인**

- [ ] **Step 3: 구현** — merge.py → compiler.py → `__init__.py`. `build_compiler(settings)`는 Task 10의 `PromptAISettings`/`CompilerSettings` 필드명(`provider`, `base_url`, `model`, `timeout_seconds`, `temperature`, `max_tokens`, `compiler.default_mode`, `compiler.use_danbooru_resolver`, `compiler.preserve_natural_language`, `compiler.relationship_style`)을 사용하며, 이 태스크에서는 `settings`를 간단한 namespace 객체로 흉내 낼 수 있게 duck-typed로 작성(존재하지 않으면 기본값). Task 10에서 실제 설정 연결.

- [ ] **Step 4: 통과 확인** — `tests/test_merge.py 4 + tests/test_compiler.py 9 passed`

- [ ] **Step 5: Commit**

```bash
git add src/naiauto/core/prompt/merge.py src/naiauto/core/prompt/compiler.py src/naiauto/core/prompt/__init__.py tests/test_merge.py tests/test_compiler.py
git commit -m "feat(prompt): add compiler pipeline orchestration and merge layer"
```

---

## Task 10: 설정 + 옵션 페이지 + i18n

**Files:**
- Modify: `src/naiauto/core/settings/schema.py`
- Modify: `src/naiauto/ui/options_dialog.py`
- Modify: `src/naiauto/ui/options_pages/__init__.py`
- Create: `src/naiauto/ui/options_pages/prompt_ai_page.py`
- Modify: `src/naiauto/resources/languages/{ko,en,ja,zh}.json`
- Test: `tests/test_settings_compiler.py`

**Interfaces:**
- Consumes: `core/settings/schema.AppSettings`, `core/settings/credentials`, `options_dialog.OWNED_FIELDS`, `options_pages` 레지스트리, `core/prompt/providers.API_KEY_CREDENTIAL`
- Produces:

```python
# settings/schema.py 에 추가
class PromptAISettings(BaseModel):
    """LLM provider 설정 (스펙 §46). api_key는 설정 파일에 저장하지 않는다 — keyring."""

    provider: str = "openai_compatible"          # "openai_compatible" | "ollama"
    base_url: str = "http://127.0.0.1:7112/v1"   # llama.cpp 로컬 서버 (OpenAI 호환)
    model: str = ""
    timeout_seconds: float = 120.0
    temperature: float = 0.3
    max_tokens: int = 2048
    api_key_available: bool = False              # keyring에 key가 저장되어 있는가 (표시용)


class CompilerSettings(BaseModel):
    """Prompt Compiler 기본값 (스펙 §46)."""

    default_mode: str = "hybrid"                 # "tag" | "hybrid" | "natural"
    use_danbooru_resolver: bool = True
    preserve_natural_language: bool = True
    relationship_style: str = "natural"          # "natural" | "tag"


# AppSettings 에 추가
    prompt_ai: PromptAISettings = Field(default_factory=PromptAISettings)
    compiler: CompilerSettings = Field(default_factory=CompilerSettings)
```

**options_dialog.py 수정:**
- `NAV_ORDER`에 `"prompt_ai"` 추가 ("interface" 다음, "tags" 앞)
- `OWNED_FIELDS`에 `"prompt_ai"`, `"compiler"` 추가

**options_pages/__init__.py 수정:** static import 목록에 `prompt_ai_page` 추가.

**prompt_ai_page.py** (`@register_page`, `KEY = "prompt_ai"`):

```python
@register_page
class PromptAiPage(OptionsPage):
    """Prompt AI + Prompt Compiler 설정 (스펙 §46의 두 그룹을 한 페이지에)."""

    KEY = "prompt_ai"

    def __init__(self, i18n, parent=None, **_extra): ...
    def load(self, draft: AppSettings) -> None: ...
        # draft.prompt_ai.* → 위젯 / compiler.* → 위젯
        # api_key_available = credentials.load_credential(API_KEY_CREDENTIAL) 존재와 keyring.is_available()
        #   (load_credential은 keyring 미사용 시 빈 문자열 반환)
    def commit(self, draft: AppSettings) -> None: ...
        # 위젯 → draft.prompt_ai / draft.compiler
        # API key 입력란이 비어 있지 않으면 credentials.save_credential(API_KEY_CREDENTIAL, value)
        #   로 저장하고 입력란 비움, draft.prompt_ai.api_key_available=True
        # "API key 삭제" 체크박스가 켜져 있으면 delete_credential
        # keyring 불가(is_available() False)면 저장하지 않고 입력란을 비우며
        #   경고 노트(notices) "compiler.warn_keyring"
    def retranslate(self) -> None: ...
```

위젯 구성: provider 콤보(openai_compatible/ollama), base_url QLineEdit, model QLineEdit, temperature QDoubleSpinBox(0~2, step 0.05), max_tokens QSpinBox(64~4096, step 64), timeout QDoubleSpinBox(5~600), API key QLineEdit(password echo, placeholder), key 삭제 QCheckBox, 단락 구분 QLabel "Prompt Compiler", default mode 콤보(tag/hybrid/natural), use resolver QCheckBox, preserve NL QCheckBox, relationship style 콤보(natural/tag).

**i18n 키** (4개 언어 JSON 모두 — 번역 문자열은 각 언어 담당자가 아니므로 ko를 기준으로 en/ja/zh는 기존 파일의 문체를 따라 작성):

```
options_nav.prompt_ai: "Prompt AI" (ko: "AI 프롬프트")
options_nav.prompt_ai_desc: "자연어 프롬프트 컴파일러의 LLM provider와 기본 동작을 설정합니다."
menu.prompt_compiler: "자연어 프롬프트 컴파일러..."
compiler.section_title: "AI 프롬프트"
compiler.open_dialog: "컴파일러 열기"
compiler.tab_create: "생성"
compiler.tab_modify: "수정"
compiler.input_placeholder: "원하는 장면을 자연어로 설명하세요... (예: 비 오는 밤의 골목에서 은발 소녀와 흑발 소녀가 마주보고 있다)"
compiler.modify_hint: "현재 프롬프트를 바탕으로 수정 지시를 주세요."
compiler.mode: "모드"
compiler.mode_tag: "Tag"
compiler.mode_hybrid: "Hybrid"
compiler.mode_natural: "Natural"
compiler.convert: "변환"
compiler.cancel: "중지"
compiler.regenerate: "다시 생성"
compiler.converting: "변환 중..."
compiler.result_scene: "Scene / Base"
compiler.result_character_n: "Character {0}"
compiler.result_relationships: "Relationships"
compiler.result_final_prompt: "최종 프롬프트"
compiler.result_negative: "Negative"
compiler.unresolved_title: "태그로 변환하지 못한 개념"
compiler.warnings_title: "경고"
compiler.apply: "적용 (Apply)"
compiler.insert: "추가 (Insert)"
compiler.replace: "교체 (Replace)"
compiler.applied: "컴파일 결과를 적용했습니다."
compiler.inserted: "컴파일 결과를 추가했습니다."
compiler.no_result: "먼저 변환을 실행하세요."
compiler.error_title: "컴파일 실패"
compiler.warn_keyring: "시스템 키링을 사용할 수 없어 LLM API 키를 저장하지 않았습니다."
```

기존 `menu` 섹션에 `prompt_compiler` 키 추가, 새 최상위 `compiler` 섹션, `options_nav`에 2키 추가. (각 JSON 파일 구조 유지: `{"language_name", "language_code", "translations": {...}}`)

**테스트** — `tests/test_settings_compiler.py`:

```python
from naiauto.core.settings.schema import AppSettings, CompilerSettings, PromptAISettings


def test_settings_defaults():
    s = AppSettings()
    assert s.prompt_ai.provider == "openai_compatible"
    assert s.prompt_ai.base_url == "http://127.0.0.1:7112/v1"
    assert s.compiler.default_mode == "hybrid"
    assert s.compiler.preserve_natural_language is True
    assert s.compiler.relationship_style == "natural"


def test_settings_roundtrip(tmp_path):
    from naiauto.core.settings.store import load_settings, save_settings

    s = AppSettings()
    s.prompt_ai.model = "qwen2.5-7b"
    s.compiler.relationship_style = "tag"
    path = tmp_path / "settings.json"
    save_settings(s, path)
    loaded = load_settings(path)
    assert loaded.prompt_ai.model == "qwen2.5-7b"
    assert loaded.compiler.relationship_style == "tag"
    assert loaded.compiler.default_mode == "hybrid"


def test_old_settings_migrate_with_defaults(tmp_path):
    import json

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"language": "en", "schema_version": 2}), encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.language == "en"
    assert loaded.prompt_ai.provider == "openai_compatible"
    assert loaded.compiler.default_mode == "hybrid"
```

추가로 `tests/test_options_registry.py` (옵션 페이지 등록 검증):

```python
from naiauto.ui.options_pages import page_class


def test_prompt_ai_page_registered():
    cls = page_class("prompt_ai")
    assert cls.KEY == "prompt_ai"
```

- [ ] **Step 1: 실패 테스트** — 위 테스트 2개 파일 작성 후 실행 → FAIL (AppSettings에 필드 없음)

- [ ] **Step 2: schema.py 수정** — 위 필드 추가. `build_compiler()`가 사용할 duck-typing 인터페이스 확정:

```python
def build_compiler(settings) -> PromptCompiler: ...  # Task 9에서 선언, 여기서 완성 (Task 9 파일 수정)
    # provider = create_provider(provider=settings.prompt_ai.provider,
    #                            base_url=settings.prompt_ai.base_url,
    #                            model=settings.prompt_ai.model,
    #                            api_key=credentials.load_credential(API_KEY_CREDENTIAL))
    # resolver = TagResolver(resolve_database_path(settings.tag_database_path))
    # formatter = PromptFormatter(preserve_natural_language=..., relationship_style=...)
    # PromptCompiler(provider=provider, resolver=resolver, formatter=formatter,
    #                temperature=..., max_tokens=..., timeout=...,
    #                use_resolver=settings.compiler.use_danbooru_resolver)
```

- [ ] **Step 3: 옵션 페이지 등록 + 페이지 구현** — 위 패턴대로. 참고: `tags_page.py`가 어떤 형태인지 읽고 같은 스타일 사용.

- [ ] **Step 4: i18n 4개 파일 수정** — 위 키 목록을 ko/en/ja/zh 모두에 추가 (기존 파일 형식 유지, 기존 키는 절대 변경하지 않는다).

- [ ] **Step 5: 테스트 통과 확인** — `pytest tests/test_settings_compiler.py tests/test_options_registry.py -q`

- [ ] **Step 6: selftest 호환 확인 (옵션 페이지 수 증가는 자동 반영)**

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m naiauto.ui.app --selftest  # app.py는 패키지 모듈이므로 -m 으로 실행
```

- [ ] **Step 7: Commit**

```bash
git add src/naiauto/core/settings/schema.py src/naiauto/ui/options_dialog.py src/naiauto/ui/options_pages/ src/naiauto/resources/languages/ src/naiauto/core/prompt/compiler.py tests/test_settings_compiler.py tests/test_options_registry.py
git commit -m "feat(settings): add prompt AI and compiler settings with options page"
```

---

## Task 11: Prompt Compiler 다이얼로그

**Files:**
- Create: `src/naiauto/ui/prompt_compiler_dialog.py`
- Test: `tests/test_compiler_dialog.py` (Qt offscreen — core 로직만, 위젯 상호작용은 smoke로)

**Interfaces:**
- Consumes: `core.prompt.compiler.build_compiler`/`PromptCompiler`/`CompiledPrompt`/`errors.*`, `core.settings.schema.AppSettings`, `core.i18n.manager.I18nManager`, `core.api.models.CharacterCaption`
- Produces:

```python
@dataclass(frozen=True)
class CompilerApplyPayload:
    """다이얼로그 → MainWindow 전달 (적용 의미는 MainWindow가 결정)."""

    mode: Literal["apply", "insert", "replace"]
    prompt: str
    negative_prompt: str
    characters: tuple[CharacterCaption, ...]


class PromptCompilerDialog(QDialog):
    """자연어 → 구조화 프롬프트 컴파일 다이얼로그 (WD14Dialog 스타일).

    흐름 (스펙 §24, §71): 입력 → 변환(worker) → 미리보기(구조 + 최종 문자열)
    → 사용자 검토 → Apply/Insert/Replace 신호 방출. 검토 전까지 기존 편집기를
    절대 건드리지 않는다.
    """

    applied = Signal(object)  # CompilerApplyPayload (메인 스레드에서 emit)

    def __init__(self, i18n: I18nManager, settings: AppSettings,
                 *, parent: QWidget | None = None) -> None: ...
    def retranslate(self) -> None: ...
```

**구조:**

```
컨트롤 행:  모드 콤보(Tag/Hybrid/Natural) | 변환 | 중지 | 다시 생성
입력 탭:    QTabWidget
  탭 "생성": QPlainTextEdit (placeholder compiler.input_placeholder)
  탭 "수정": 읽기전용 QPlainTextEdit(현재 main prompt 표시 — MainWindow가 setter로 반영)
             + QPlainTextEdit(수정 지시)
결과 영역:  QSplitter(Horizontal)
  왼쪽: QTextBrowser — 구조 요약 (Scene / Character N / Relationships / unresolved / warnings)
  오른쪽: QPlainTextEdit (읽기전용 아님 — 사용자가 Apply 전 최종 수정 가능)
네거티브:  QPlainTextEdit (compiled negative 표시, 편집 가능)
하단 버튼:  Apply | Insert | Replace | 닫기
상태바 라벨: converting 표시 / 오류 메시지
```

**동작:**
- `_on_convert()`: 입력 검증(빈값 → 인포 메시지). 버튼 비활성화, 상태 "변환 중...", `self._cancel_requested = False`, 워커 스레드 시작:

```python
def _run_convert(self) -> None:
    self._compiler_worker = threading.Thread(
        target=self._worker_convert, name="naiauto-compiler", daemon=True)
    self._compiler_worker.start()

def _worker_convert(self) -> None:
    try:
        if self._modify_mode():
            compiled = self._compiler.modify(
                self._existing_prompt(), self._instruction_text(),
                mode=self._mode())
        else:
            compiled = self._compiler.compile(self._input_text(), mode=self._mode())
    except CompilerError as e:
        self._emit_safely(self._converted_failed, None, e)
        return
    if self._cancel_requested:   # cancel flag — LLM 호출 후 폐기
        return
    self._emit_safely(self._converted_ok, compiled, None)
```

  시그널: `_converted_ok = Signal(object)`, `_converted_failed = Signal(object)` — 내부 시그널을 QDialog가 직접 emit (cross-thread emit은 Qt queued connection으로 안전 — 기존 `_emit_safely` 패턴: `shiboken6.isValid(self)` 검사).

- `_on_cancel()`: `self._cancel_requested = True`. (LLM HTTP 호출 자체 중단은 불가 — 호출 종료 후 결과 폐기. 타임아웃은 설정 필드로 제어. 스펙 §29 "가능하면 Cancel".)
- `_on_converted(compiled, err)`: err → QMessageBox.warning(제목 컴파일 실패, err 메시지 — 오류 타입별로 `errors.*` 키로 번역: CompilerConnectionError→"LLM 서버에 연결할 수 없습니다", CompilerTimeoutError→"시간 초과", CompilerAuthError→"인증 실패", CompilerParseError→"LLM 응답을 해석하지 못했습니다", CompilerEmptyResultError→"결과가 비어 있습니다". (키 추가 불필요 — 이 다이얼로그 전용 문구는 `compiler.err_connection` 등으로 i18n에 추가: `compiler.err_*` 5개 키)). 성공 → 결과 미리보기 갱신 + Apply/Insert/Replace 활성화.
- 미리보기 렌더링:

```python
def _render_preview(self, compiled: CompiledPrompt) -> None:
    # QTextBrowser에:
    #   "Scene / Base\n──────────\n" + 각 scene verified tag 한 줄
    #   "Character 1\n──────────\n" + char.tag 목록 + (position_hint/좌표) + neg
    #   "Relationships\n──────────\n" + "c1 ↔ c2 : looking_at" 행
    #   "태그로 변환하지 못한 개념\n──────────\n" + unresolved
    #   "경고\n──────────\n" + warnings
    # 우측 편집기에 compiled.base_prompt, 네거티브 편집기에 compiled.negative_prompt
```

- `_on_apply(mode)`: `to_generation_data(...)` (existing_negative는 MainWindow가 이미 보존 병합하므로 여기선 빈값) → `CompilerApplyPayload` → `self.applied.emit(payload)` → `self.accept()` (또는 유지 — MainWindow 적용 후 닫힘). final prompt 편집기에서 사용자가 수정한 문자열이 있으면 `payload.prompt`를 그 수정본으로 사용.
- `set_existing_prompt(text)`: 수정 탭에 현재 메인 프롬프트 반영 (MainWindow가 다이얼로그 열 때 호출).
- `retranslate()`: 모든 라벨/탭/플레이스홀더.
- 캐릭터 표시: Character 이름은 `compiler.result_character_n` 포맷(1-based), 관계는 `c1 ↔ c2 : looking_at` (i18n 키 `compiler.result_relationship_row`: `"{0} ↔ {1} : {2}"`).

**Task 11 테스트는 Qt 오프스크린으로 최소한만** (CI 우분투에서 PySide6 설치 필요 — `pip install -e .`가 설치하므로 문제없음, `QT_QPA_PLATFORM=offscreen`):

```python
# tests/test_compiler_dialog.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from naiauto.core.prompt.compiler import PromptCompiler
from naiauto.core.prompt.errors import CompilerConnectionError
from naiauto.core.prompt.formatter import PromptFormatter
from naiauto.core.prompt.llm import FakeLLMProvider
from naiauto.core.prompt.resolver import TagResolver
from naiauto.ui.prompt_compiler_dialog import CompilerApplyPayload, PromptCompilerDialog


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def _dummy_compiler(response):
    resolver = TagResolver()
    resolver.load()
    return PromptCompiler(
        provider=FakeLLMProvider(response=response),
        resolver=resolver,
        formatter=PromptFormatter(),
    )


def test_apply_payload_is_frozen_data(qapp):
    payload = CompilerApplyPayload(mode="apply", prompt="2girls, cafe", negative_prompt="",
                                   characters=())
    assert payload.mode == "apply"
    assert payload.prompt == "2girls, cafe"


def test_dialog_controls_exist(qapp):
    from naiauto.core.settings.schema import AppSettings
    from naiauto.core.i18n.manager import I18nManager

    dialog = PromptCompilerDialog(I18nManager(), AppSettings())
    assert dialog.convert_button is not None
    assert dialog.apply_button is not None
    assert not dialog.apply_button.isEnabled()  # 변환 전 비활성
    dialog.close()
```

(Qt 테스트가 부담되면 이 파일은 로컬에서만 실행하고 CI에서는 제외해도 무방 — Task 1의 CI는 `pytest tests/ -q`이므로 통과해야 한다: 위 테스트는 offscreen으로 실행되므로 우분투 CI에서 동작한다. 필요 시 `tests.yml`에 `QT_QPA_PLATFORM: offscreen` env 추가.)

- [ ] **Step 1: 다이얼로그 파일 작성** (Worker 포함 전체) — 위 구조대로. WD14Dialog를 참고.
- [ ] **Step 2: i18n 키 추가** — `compiler.err_connection/err_timeout/err_auth/err_parse/err_empty/result_relationship_row` 6개를 4개 언어 파일에 추가.
- [ ] **Step 3: 테스트 작성 + 통과** — `QT_QPA_PLATFORM=offscreen pytest tests/test_compiler_dialog.py -q`
- [ ] **Step 4: Commit**

```bash
git add src/naiauto/ui/prompt_compiler_dialog.py src/naiauto/resources/languages/ tests/test_compiler_dialog.py
git commit -m "feat(ui): add prompt compiler dialog with worker and preview"
```

---

## Task 12: MainWindow 통합 (메뉴/Apply/요약 섹션)

**Files:**
- Modify: `src/naiauto/ui/main_window.py`
- Test: `tests/test_mainwindow_compiler.py` (offscreen — apply 핸들러 로직)

**Interfaces:**
- Consumes: `ui.prompt_compiler_dialog.PromptCompilerDialog`/`CompilerApplyPayload`, `core.prompt.compiler.build_compiler`, `core.prompt.merge.merge_negatives`, `core.prompt.providers.API_KEY_CREDENTIAL`
- Produces (MainWindow에 추가되는 멤버):

```python
# tools_menu에 추가
self.compiler_action = self.tools_menu.addAction("")   # menu.prompt_compiler, Ctrl+Shift+P
self.compiler_action.triggered.connect(self._on_open_compiler)

def _on_open_compiler(self) -> None:
    """컴파일러 다이얼로그를 연다. 적용 결과는 _on_compiler_applied로."""
    from .prompt_compiler_dialog import PromptCompilerDialog

    dialog = PromptCompilerDialog(self._i18n, self._settings, parent=self)
    dialog.set_existing_prompt(self.prompt_edit.toPlainText())
    dialog.applied.connect(self._on_compiler_applied)
    dialog.exec()
    self._compiler_dialog = dialog  # 테스트에서 접근 가능하도록 유지

def _on_compiler_applied(self, payload: CompilerApplyPayload) -> None:
    """Apply/Insert/Replace 의미 (스펙 §24).

    적용 원칙: PLW — 즉시 overwrite 금지, 다이얼로그에서 사용자가 Apply를 눌렀을
    때만 이 경로가 온다 (사용자 승인 완료).

    apply   : prompt 교체, negative = merge_negatives(기존, payload.negative_prompt),
              캐릭터 = payload.characters로 교체 (load_captions)
    insert  : prompt = 기존 + ", " + payload.prompt (기존 wildcard/artist combo 유지),
              negative = 병합, 캐릭터 = 기존 + payload.characters 추가
    replace : prompt = payload.prompt, negative = payload.negative_prompt (기존 버림),
              캐릭터 = payload.characters로 교체
    """
```

구현 세부:
- `apply`/`replace`의 캐릭터 교체는 `self.character_prompts.load_captions(payload.characters)` (기존 public API — 위치 마커 포함, `clamp_coord` 처리).
- `insert`: `existing = self.prompt_edit.toPlainText().strip()`; 비어 있으면 그냥 payload.prompt. 아니면 `existing + ", " + payload.prompt` (wildcard 파괴 없음 — 순수 문자열 결합). 캐릭터: 기존 `captions()` + payload.characters 병합 후 `load_captions`.
- 적용 후 상태바: `compiler.applied` / `compiler.inserted`. 요약 섹션 갱신.
- **요약 섹션** (요청: "둘 다"): `_build_ui()`에서 `ai_section`과 `image_source` 사이에 `CollapsibleSection` 추가:

```python
# _build_ui() 후반부 (ai_section 다음, image_source 이전)
self.compiler_body = QWidget()
compiler_layout = QVBoxLayout(self.compiler_body)
self.compiler_summary = QPlainTextEdit()
self.compiler_summary.setReadOnly(True)
self.compiler_summary.setMaximumHeight(160)
self.compiler_open_button = QPushButton()
self.compiler_open_button.clicked.connect(self._on_open_compiler)
compiler_layout.addWidget(self.compiler_summary)
compiler_layout.addWidget(self.compiler_open_button)
self.compiler_section = CollapsibleSection(self._i18n, "compiler.section_title")
self.compiler_section.set_content(self.compiler_body)
left_layout.addWidget(self.compiler_section)

def _update_compiler_summary(self, compiled: CompiledPrompt) -> None:
    """마지막 컴파일 결과를 접이식 섹션에 요약 표시 (스펙 §42 스타일)."""
    lines = [f"Scene: {', '.join(t.tag for t in compiled.scene.tags)}"]
    for i, c in enumerate(compiled.characters, start=1):
        lines.append(f"Character {i}: {', '.join(t.tag for t in c.tags)}")
    if compiled.relationships:
        lines.append("Relationship: " + ", ".join(
            f"{r.source}→{r.target}:{r.action}" for r in compiled.relationships))
    self.compiler_summary.setPlainText("\n".join(lines))
```

- `retranslate()`에 `compiler_open_button.setText(tr("compiler.open_dialog"))` + `compiler_section.retranslate()` 추가.
- `_wire_sections`에 compiler 섹션 토글 설정 반영은 생략 (영속 상태 불필요 — 과도한 abstraction 방지). 단 `reset_layout`에서 접히게 할 필요 없음.
- `apply_reusable`/`collect_settings`/`build_job`은 수정하지 않는다 (컴파일러는 편집기 문자열에만 반영 — 기존 파이프라인 무변경).

**테스트** — `tests/test_mainwindow_compiler.py`: `_on_compiler_applied`가 편집기 문자열/슬롯을 올바르게 바꾸는지 검증한다 (offscreen). 의존성은 전부 stub으로 대체 — 실제 API/서비스 호출은 없다.

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from naiauto.core.api.models import CharacterCaption
from naiauto.core.settings.schema import AppSettings
from naiauto.core.i18n.manager import I18nManager
from naiauto.ui.main_window import MainWindow
from naiauto.ui.prompt_compiler_dialog import CompilerApplyPayload


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _StubSession:
    is_logged_in = False
    def reauthenticate(self):
        return False


class _StubClient:
    def __init__(self):
        self.session = _StubSession()
    def get_anlas(self):
        return {"total": 0, "fixed": 0, "purchased": 0, "usage": None}


class _StubService:
    is_running = False
    def stop(self):
        pass
    def set_live_resolution(self, *a):
        pass
    def reload_artist_combos(self, *a):
        pass


def _window(qapp):
    """MainWindow를 생성하되 네트워크/서비스 의존성은 전부 stub.

    check_updates_on_start=False 필수 — 시작 시 업데이트 확인 스레드가 실제 HTTP를
    쏘지 않도록 한다. 생성 후 창은 닫지 않는다 (테스트 훅).
    """
    from naiauto.ui.qt_bridge import QtEventBridge

    settings = AppSettings(check_updates_on_start=False)
    win = MainWindow(
        i18n=I18nManager(),
        settings=settings,
        client=_StubClient(),
        service=_StubService(),
        bridge=QtEventBridge(),
    )
    return win


def test_apply_replaces_prompt_and_characters(qapp):
    win = _window(qapp)
    win.prompt_edit.setPlainText("old prompt, old_tag")
    win.negative_edit.setPlainText("old_neg")
    payload = CompilerApplyPayload(
        mode="apply",
        prompt="2girls, cafe, rain",
        negative_prompt="bad_hands",
        characters=(CharacterCaption(prompt="silver_hair", center_x=0.3, center_y=0.5),),
    )
    win._on_compiler_applied(payload)
    assert win.prompt_edit.toPlainText() == "2girls, cafe, rain"
    # 네거티브는 기존 + 컴파일 병합 (스펙 §22)
    assert win.negative_edit.toPlainText() == "old_neg, bad_hands"
    captions = win.character_prompts.captions()
    assert len(captions) == 1
    assert captions[0].prompt == "silver_hair"
    assert captions[0].center_x == pytest.approx(0.3)


def test_insert_preserves_existing_and_appends(qapp):
    win = _window(qapp)
    win.prompt_edit.setPlainText("1girl, __hairstyle__, {artist:grp}")
    payload = CompilerApplyPayload(
        mode="insert",
        prompt="2girls, cafe",
        negative_prompt="",
        characters=(CharacterCaption(prompt="silver_hair"),),
    )
    win._on_compiler_applied(payload)
    text = win.prompt_edit.toPlainText()
    assert "__hairstyle__" in text and "{artist:grp}" in text  # §51, §52 보존
    assert text.endswith("2girls, cafe")
    assert len(win.character_prompts.captions()) == 1


def test_replace_wipes_existing(qapp):
    win = _window(qapp)
    win.prompt_edit.setPlainText("old")
    win.negative_edit.setPlainText("old_neg")
    payload = CompilerApplyPayload(
        mode="replace",
        prompt="1girl, rooftop, night",
        negative_prompt="text",
        characters=(),
    )
    win._on_compiler_applied(payload)
    assert win.prompt_edit.toPlainText() == "1girl, rooftop, night"
    assert win.negative_edit.toPlainText() == "text"
    assert win.character_prompts.captions() == ()


def test_insert_mode_appends_to_existing(qapp):
    # 순수 문자열 결합 규칙 (MainWindow 없이)
    from naiauto.core.prompt.merge import merge_negatives

    existing = "1girl, __hairstyle__, silver_hair"
    combined = existing + ", " + "2girls, cafe"
    assert "__hairstyle__" in combined
    assert combined.endswith("2girls, cafe")
    assert merge_negatives("bad_hands", "text") == "bad_hands, text"


def test_no_result_before_compile_hidden_buttons(qapp):
    win = _window(qapp)
    # 적용 버튼 활성 조건은 다이얼로그 소관 — MainWindow 상태바는 컴파일 결과 없이
    # 호출돼도 안전해야 한다 (결과 없음 → 아무것도 안 함 정도의 가드): Apply 전
    # `_compiler_dialog`가 None이어도 크래시 없음.
    assert getattr(win, "_compiler_dialog", None) is None
```

- [ ] **Step 1: main_window.py 수정** — 메뉴 액션 + `_on_open_compiler` + `_on_compiler_applied` + 요약 섹션 + retranslate. 단, `_on_compiler_applied`의 negative 병합은 `merge_negatives`를 사용하고, insert는 기존 captions + payload 캐릭터 병합 후 `load_captions`. `_on_compiler_applied`에 `_compiler_dialog = getattr(self, "_compiler_dialog", None)` 가드가 필요 없도록 `__init__`에서 `self._compiler_dialog = None`으로 초기화.

- [ ] **Step 2: 테스트 작성 + 통과**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_mainwindow_compiler.py -q
```

주의: `_window()` 생성 시 `_build_ui()`가 `_refresh_tag_completer()`(내장 DB 로드)와 `refresh_anlas()`(스레드 → stub client)를 호출하므로 내장 태그 DB 경로가 유효해야 한다 — `AppSettings(tag_database_path="")` 기본값이 내장 DB를 쓰므로 CI에서도 동작한다. (MainWindow가 실제 업데이트 확인을 하지 않도록 `check_updates_on_start=False`.)

- [ ] **Step 3: smoke 실행으로 창 생성 확인**

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m naiauto.ui.app --smoketest
```

(실제 smoke는 `python -m naiauto.ui.app --smoketest` — offscreen 환경 변수 필수)

- [ ] **Step 4: 전체 테스트 + ruff**

```bash
python -m pytest tests/ -q
ruff check src/naiauto/core/prompt src/naiauto/ui/main_window.py src/naiauto/ui/prompt_compiler_dialog.py
```

- [ ] **Step 5: Commit**

```bash
git add src/naiauto/ui/main_window.py tests/test_mainwindow_compiler.py
git commit -m "feat(ui): integrate prompt compiler into main window"
```

---

## Task 13: 문서 + 패키징 + README

**Files:**
- Modify: `README.md`
- Modify: `packaging/nai-auto-v5.spec`
- Modify: `pyproject.toml` (package-data)

**Interfaces:**
- Consumes: 없음 (기존 리소스 규칙)

- [ ] **Step 1: pyproject.toml package-data에 templates 추가**

```toml
[tool.setuptools.package-data]
naiauto = ["resources/languages/*.json", "resources/tags/*.csv", "core/prompt/templates/*.md"]
```

- [ ] **Step 2: packaging/nai-auto-v5.spec에 datas 추가**

`datas` 리스트 안, resources 항목 옆에:

```python
datas = [
    (str(PACKAGE_DIR / "resources"), "naiauto/resources"),
    (str(PACKAGE_DIR / "core" / "prompt" / "templates"), "naiauto/core/prompt/templates"),
    *keyring_datas,
]
```

- [ ] **Step 3: README에 자연어 컴파일러 섹션 추가** — 한국어 주요 기능 목록에 1줄 + 상세 섹션 + English 상응. 내용 요구 (스펙 §63):

```
## 🤖 자연어 프롬프트 컴파일러 (Natural Language Prompt Compiler)

- 도구 → 자연어 프롬프트 컴파일러(Ctrl+Shift+P)
- 원하는 장면을 자연어로 설명하면 Scene/Character/Relationship으로 분해
- Tag / Hybrid(기본) / Natural 3가지 모드
- 내장 Danbooru 태그 DB로 태그 검증 — 존재하지 않는 태그는 최종 프롬프트에서 제외
- 변환 결과를 미리 보고 Apply/Insert/Replace로 기존 편집기에 반영
- 캐릭터 위치(왼쪽/오른쪽)는 캐릭터 위치 캔버스에 자동 반영

### LLM Provider 설정 (옵션 → AI 프롬프트)
| 설정 | 값 |
|---|---|
| Provider | OpenAI-compatible (기본, llama.cpp/LM Studio/원격) 또는 Ollama |
| Base URL | http://127.0.0.1:7112/v1 (llama.cpp), http://localhost:11434 (Ollama) |
| Model | 서버에 등록된 모델명 |

### 로컬 LLM 예시
- llama.cpp server: `llama-server -m model.gguf --port 7112` → Base URL `http://127.0.0.1:7112/v1`
- LM Studio: Base URL `http://localhost:1234/v1`
- Ollama: `ollama run gemma3` → Provider=Ollama, Base URL `http://localhost:11434`

### API 키 구분 — 두 개는 별개 credential입니다
- NovelAI API 키 (pst-...) → 이미지 생성용. 로그인 창에서 입력, keyring 보관.
- LLM API 키 → 자연어 해석용(원격 provider일 때만 필요). 옵션 → AI 프롬프트에서 입력, keyring 보관.
- 로컬 LLM(llama.cpp/Ollama)은 키가 필요 없습니다.
```

English 섹션에도 같은 내용을 영어로 추가.

- [ ] **Step 4: ruff + 전체 테스트**

```bash
ruff check src/ tests/
python -m pytest tests/ -q
```

- [ ] **Step 5: Commit**

```bash
git add README.md packaging/nai-auto-v5.spec pyproject.toml
git commit -m "docs: add prompt compiler usage docs and packaging data"
```

---

## Task 14: 실서버 스모크 (llama.cpp 7112) + 최종 검증

**Files:**
- 없음 (수동 검증 — 테스트 코드에 실서버 호출을 넣지 않는다, 스펙 §60)

- [ ] **Step 1: 서버 확인**

```bash
curl -s http://127.0.0.1:7112/v1/models | head -c 500
```

Expected: 모델 목록 JSON. 실패 시 서버 기동 필요(사용자 환경) — 이 스텝은 서버가 떠 있을 때만.

- [ ] **Step 2: 실제 컴파일 1회 (스크립트)**

```bash
QT_QPA_PLATFORM=offscreen python - <<'PY'
from naiauto.core.settings.schema import AppSettings
from naiauto.core.prompt.compiler import build_compiler

s = AppSettings()
s.prompt_ai.base_url = "http://127.0.0.1:7112/v1"
s.prompt_ai.model = "<서버 모델명 — Step 1 출력에서 확인>"
compiler = build_compiler(s)
compiled = compiler.compile(
    "카페 창가에 은발 단발머리 소녀가 앉아 있다. 교복을 입고 있고 손에는 책을 들고 있다. "
    "맞은편에는 검은 장발 소녀가 앉아 있으며 캐주얼한 옷을 입고 있다. "
    "두 사람은 서로를 바라보며 대화하고 있다. 창밖에는 비가 내리고 있다.",
    mode="hybrid",
)
print("BASE:", compiled.base_prompt)
print("CHAR1:", [t.tag for t in compiled.characters[0].tags])
print("CHAR2:", [t.tag for t in compiled.characters[1].tags])
print("RELS:", compiled.relationships)
print("UNRESOLVED:", compiled.unresolved)
assert "silver_hair" in [t.tag for t in compiled.characters[0].tags]
assert compiled.characters[0].center_x == 0.5  # 위치 명시 없음 → None 대신 미지정(0.5 폴백은 merge)
PY
```

동작 확인 기준: base가 비어 있지 않고, 캐릭터 2명이 분리되며, scene 태그가 base에, 캐릭터 태그가 캐릭터 슬롯에. 서버가 내려가 있으면 `CompilerConnectionError`가 graceful하게 나오는 것까지 확인하고 스텝 3으로.

- [ ] **Step 3: 전체 회귀 (기존 기능 무손상 확인)**

```bash
python -m pytest tests/ -q
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m naiauto.ui.app --selftest
```

- [ ] **Step 4: 최종 커밋 (결과 기록은 PATCHNOTES.md 선택)** — Plan 문서는 Task 1 이전에 이미 커밋됨(설정 단계에서 `docs/` + 스펙 파일을 커밋했다면 생략 가능).

---

## Self-Review 결과 (스펙 커버리지)

| 스펙 섹션 | 태스크 |
|---|---|
| §1–2 (분석/비재작성) | Task 1 탐색 완료(계획 수립 전), Global Constraints |
| §3–5 (Scene/Character/Relationship 분리, 골든 예시) | Task 8–9 (formatter/compiler), test_compiler 골든 | 
| §6–8 (parser, schema, LLM output) | Task 2, 5 |
| §9 (LLM 금지사항) | system_prompt.md (Task 5) 지시문으로 강제 |
| §10–13 (resolver, alias, unresolved) | Task 6 (규칙 1–4, unresolved) |
| §14–15 (모드, Hybrid 기본) | Task 8, 설정 Task 10 (`default_mode="hybrid"`) |
| §16–18 (UI 분리, 위치, 캔버스 통합) | Task 11–12 (load_captions 재사용) |
| §19–21 (관계 해석, count 태그) | Task 7, 8 (count_tag 규칙) |
| §22 (negative) | Task 8–9 (merge_negatives) |
| §23–25 (modify, Apply UX, regen) | Task 9, 11 (`modify()`, Apply/Insert/Replace, 다시 생성 버튼) |
| §26–28 (provider, local-first, key 보안) | Task 4, 10 (keyring, `API_KEY_CREDENTIAL`) |
| §29–31 (async/worker, error, optional) | Task 11 (worker+시그널, 오류 타입별 번역), Task 4 (오류 계층) |
| §32–38 (아키텍처, formatter, GenerationRequest 통합) | Task 2–9 (merge → CharacterCaption, API 무변경) |
| §39–41 (의도 보존, explicit/inferred, confidence) | Task 2 (`TagRef.source`), Task 6 (status) |
| §42–43 (GUI 구조 표시, 위치 UI) | Task 11–12 (미리보기, position 캔버스) |
| §44–46 (presets 네임스페이스, i18n, settings) | 설정은 Task 10. **프리셋 연동은 범위 외로 판단 — 기존 generation preset과 충돌 없이 별도 동작(옵션 페이지가 기본값 관리)하며, compiler preset 저장은 추후 확장으로 남긴다** |
| §47–48 (system prompt 템플릿, prompt templates) | Task 5 (templates/system_prompt.md; tag/hybrid/natural 포맷은 formatter 코드) |
| §49–52 (modify 최소 변경, 관계 보존, wildcard, artist combo) | Task 9 (modify 토큰 보존), Task 12 (insert가 기존 문자열 유지) |
| §53–55 (순서, NL 배치, count) | Task 8 |
| §56 (비인간 캐릭터) | Task 8 `SUBJECT_PLURALS` (cat/dog 등), system prompt subjects 허용 목록 |
| §57–58 (i2i/inpaint 무충돌, WD14) | Global Constraints — 편집기 문자열만 변경하므로 무충돌, WD14 재사용 없음(중복 없음) |
| §59–61 (테스트) | Task 1–9 전부 TDD + 골든 통합 테스트 + Fake provider |
| §62–64 (패키징, 문서, 보안) | Task 13, 10(keyring) |
| §65–66 (미파괴, 과설계 금지) | Global Constraints, 완료 시 Task 14 회귀 |
| §67–68 (외부 참조, 설계 경계) | 참조만 하고 코드 복사 없음 — resolver는 자체 결정적 규칙 |
| §69–72 (아키텍처 다이어그램, 골든, 우선순위) | Task 2→9 순서가 Phase 2–8과 일치 |
| §73–75 (사전 분석, Do/Don't, Definition of Done) | Task 14 최종 체크리스트로 사용 |