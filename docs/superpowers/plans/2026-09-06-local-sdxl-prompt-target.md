# 로컬 SDXL/Anima 프롬프트 타깃 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** NovelAI 전용이던 자연어 프롬프트 컴파일러에 출력 대상(target) 축을 추가해, 로컬 SDXL 계열(Illustrious·NoobAI·Animagine)이 바로 쓸 수 있는 단일 Positive/Negative 프롬프트와 ComfyUI 영역 분할 출력을 만든다.

**Architecture:** 파이프라인 앞단(LLM 파서 → resolver → positions/relationship)은 그대로 두고, `CompiledPrompt`를 단일 진실 원천으로 삼아 그 뒤에 **emitter 3종**(`sequential` / `couple_mask` / `regional_json`)을 갈아 끼운다. 분기점은 `compiler._assemble`과 `merge` 두 곳뿐이다. 타깃별 설정은 JSON 프리셋 데이터로 뺀다.

**Tech Stack:** Python 3.11+, pydantic v2(설정 스키마), PySide6(UI), pytest, ruff, uv

**Spec:** `docs/superpowers/specs/2026-09-06-local-sdxl-prompt-target-design.md`

---

## 사전 준비 — 반드시 먼저 읽을 것

**이 저장소의 규칙:**

- 테스트/린트는 **`uv run --extra dev`** 로 실행한다. `.venv/Scripts/python.exe`에는 pytest가 없다.
  - 테스트: `uv run --extra dev pytest -q`
  - 린트: `uv run --extra dev ruff check src tests`
- `src/naiauto/core/` 아래 모든 모듈은 **Qt 의존성이 없어야 한다.** `PySide6` import 금지.
- 모든 신규 모듈은 **한국어 모듈 독스트링**으로 시작한다 (기존 `core/prompt/*.py` 참고).
- 모든 파일 끝에 `__all__`을 둔다.
- 커밋 메시지는 한국어 본문 + Conventional Commits 접두사(`feat:`/`fix:`/`docs:`/`test:`).
- 커밋 메시지 끝에 다음 두 줄을 붙인다:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
  ```

**작업 전 확인:**

```bash
cd "M:/Kubuntu/NAI-Auto-Generator-V5"
git status --short          # uv.lock 외에 변경이 없어야 한다
uv run --extra dev pytest -q   # 전부 통과해야 시작한다 (기준선)
```

---

## 파일 구조

**신규**

| 파일 | 책임 |
|---|---|
| `src/naiauto/core/prompt/targets.py` | 타깃 프리셋 + LoRA 레지스트리의 **데이터 로딩만**. 문자열 조립 없음 |
| `src/naiauto/core/prompt/emitters.py` | `CompiledPrompt` → 출력 문자열/JSON. **순수 함수만**, I/O 없음 |
| `src/naiauto/resources/prompt_targets/illustrious.json` | 내장 프리셋 |
| `src/naiauto/resources/prompt_targets/animagine.json` | 내장 프리셋 |
| `src/naiauto/resources/prompt_targets/sdxl_base.json` | 내장 프리셋 |
| `tests/test_targets.py` | 프리셋·레지스트리 로딩 테스트 |
| `tests/test_emitters.py` | emitter 3종 테스트 |

`targets.py`(I/O)와 `emitters.py`(순수 계산)를 나눈 이유: emitter 테스트가 파일시스템 없이 돌아야 하고, 프리셋 로딩 규칙이 바뀌어도 조립 로직은 그대로여야 한다.

**수정**

| 파일 | 변경 |
|---|---|
| `core/prompt/formatter.py` | `count_tag`를 모듈 함수로 추출 (emitters가 재사용) |
| `core/prompt/schema.py` | `CompiledPrompt.target` 필드 |
| `core/prompt/errors.py` | `TargetPresetError` |
| `core/prompt/merge.py` | 로컬 타깃일 때 `characters=()` |
| `core/prompt/compiler.py` | `target`/`character_loras`/`resolution` 인자, `_assemble` 분기 |
| `core/prompt/__init__.py` | 신규 공개 심볼 export |
| `core/prompt/templates/system_prompt.md` | 첫 줄 중립화 |
| `core/settings/schema.py` | `default_target`, `target_presets_dir` |
| `ui/prompt_compiler_dialog.py` | 타깃 콤보, 결과 3탭, 캐릭터별 LoRA 선택 |
| `ui/options_pages/prompt_ai_page.py` | "출력 타깃" 그룹 |
| `resources/languages/{ko,en,ja,zh}.json` | `compiler.target*`, `compiler.lora*` 키 |
| `README.md`, `MANUAL_KR.md` | 기능 설명 + 확장 설치 안내 |

---

## Task 1: 타깃 프리셋 데이터 모델과 로더

**Files:**
- Create: `src/naiauto/core/prompt/targets.py`
- Create: `tests/test_targets.py`
- Modify: `src/naiauto/core/prompt/errors.py`

- [ ] **Step 1: `TargetPresetError`를 오류 계층에 추가한다**

`src/naiauto/core/prompt/errors.py`에서 `CompilerProviderUnavailableError` 클래스 **뒤에** 다음을 넣는다:

```python
class TargetPresetError(CompilerError):
    """타깃 프리셋 JSON 파싱/스키마 검증 실패."""
```

같은 파일의 `__all__` 리스트 마지막 항목 `"CompilerProviderUnavailableError",` 뒤에 다음을 넣는다:

```python
    "TargetPresetError",
```

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_targets.py`를 새로 만든다:

```python
"""타깃 프리셋 + LoRA 레지스트리 로딩 테스트."""

import json

import pytest

from naiauto.core.prompt.errors import TargetPresetError
from naiauto.core.prompt.targets import (
    NOVELAI_PRESET,
    NOVELAI_TARGET_ID,
    TargetPreset,
    builtin_targets_dir,
    find_target,
    load_target_presets,
    parse_preset,
)


def test_novelai_preset_is_first_and_marked_novelai():
    presets = load_target_presets(None)
    assert presets[0] is NOVELAI_PRESET
    assert NOVELAI_PRESET.id == NOVELAI_TARGET_ID
    assert NOVELAI_PRESET.kind == "novelai"


def test_builtin_presets_are_loaded():
    ids = {p.id for p in load_target_presets(None)}
    assert {"illustrious", "animagine", "sdxl_base"} <= ids


def test_builtin_dir_exists():
    assert builtin_targets_dir().is_dir()


def test_parse_preset_reads_all_fields():
    preset = parse_preset(
        {
            "id": "demo",
            "name": "Demo",
            "quality_prefix": ["masterpiece"],
            "quality_suffix": ["hires"],
            "default_negative": ["lowres"],
            "weight_syntax": "a1111",
            "flatten": "couple_mask",
            "position_tags": False,
            "natural_language": "append",
            "underscore_to_space": False,
            "mask_size": [832, 1216],
        }
    )
    assert preset == TargetPreset(
        id="demo",
        name="Demo",
        kind="local",
        quality_prefix=("masterpiece",),
        quality_suffix=("hires",),
        default_negative=("lowres",),
        weight_syntax="a1111",
        flatten="couple_mask",
        position_tags=False,
        natural_language="append",
        underscore_to_space=False,
        mask_size=(832, 1216),
    )


def test_parse_preset_applies_defaults():
    preset = parse_preset({"id": "bare", "name": "Bare"})
    assert preset.kind == "local"
    assert preset.quality_prefix == ()
    assert preset.flatten == "sequential"
    assert preset.position_tags is True
    assert preset.natural_language == "drop"
    assert preset.underscore_to_space is True
    assert preset.mask_size is None


@pytest.mark.parametrize(
    "data",
    [
        {"name": "no id"},
        {"id": "", "name": "empty id"},
        {"id": "bad_flatten", "name": "x", "flatten": "nope"},
        {"id": "bad_nl", "name": "x", "natural_language": "nope"},
        {"id": "bad_mask", "name": "x", "mask_size": [1, 2, 3]},
        {"id": "bad_list", "name": "x", "quality_prefix": "not a list"},
    ],
)
def test_parse_preset_rejects_invalid(data):
    with pytest.raises(TargetPresetError):
        parse_preset(data)


def test_user_preset_overrides_builtin_by_id(tmp_path):
    (tmp_path / "illustrious.json").write_text(
        json.dumps({"id": "illustrious", "name": "My Illustrious", "quality_prefix": ["mine"]}),
        encoding="utf-8",
    )
    presets = {p.id: p for p in load_target_presets(tmp_path)}
    assert presets["illustrious"].name == "My Illustrious"
    assert presets["illustrious"].quality_prefix == ("mine",)


def test_broken_user_preset_is_skipped_not_fatal(tmp_path):
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "good.json").write_text(
        json.dumps({"id": "good", "name": "Good"}), encoding="utf-8"
    )
    ids = {p.id for p in load_target_presets(tmp_path)}
    assert "good" in ids
    assert "broken" not in ids


def test_user_preset_claiming_novelai_id_is_ignored(tmp_path):
    (tmp_path / "novelai.json").write_text(
        json.dumps({"id": "novelai", "name": "Hijacked"}), encoding="utf-8"
    )
    presets = {p.id: p for p in load_target_presets(tmp_path)}
    assert presets["novelai"] is NOVELAI_PRESET


def test_missing_user_dir_falls_back_to_builtin(tmp_path):
    ids = {p.id for p in load_target_presets(tmp_path / "does-not-exist")}
    assert "illustrious" in ids


def test_find_target_falls_back_to_novelai():
    presets = load_target_presets(None)
    assert find_target(presets, "illustrious").id == "illustrious"
    assert find_target(presets, "no-such-target") is NOVELAI_PRESET
    assert find_target(presets, "") is NOVELAI_PRESET
```

- [ ] **Step 3: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_targets.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'naiauto.core.prompt.targets'`

- [ ] **Step 4: `targets.py`를 구현한다 (프리셋 부분)**

`src/naiauto/core/prompt/targets.py`를 새로 만든다:

```python
"""출력 타깃 프리셋 + LoRA 레지스트리 로딩.

프롬프트 컴파일러의 출력 대상(NovelAI / 로컬 SDXL 계열)마다 달라지는 값을
코드가 아니라 JSON 데이터로 둔다: 품질 태그, 기본 네거티브, 가중치 문법,
캐릭터 평탄화 방식 등. 조립 로직은 ``emitters``가 맡고 이 모듈은 **로딩만**
한다 — 그래야 emitter 테스트가 파일시스템 없이 돈다.

- ``load_target_presets``: 내장(resources/prompt_targets/*.json) + 사용자 폴더
- ``load_lora_registry``: 사용자 폴더의 ``loras.json``
- 깨진 항목은 건너뛰고 로그 경고만 남긴다 — 앱은 항상 뜬다.

Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from naiauto.core.prompt.errors import TargetPresetError

logger = logging.getLogger(__name__)

__all__ = [
    "NOVELAI_TARGET_ID",
    "NOVELAI_PRESET",
    "LORA_REGISTRY_FILENAME",
    "TargetPreset",
    "LoraEntry",
    "builtin_targets_dir",
    "parse_preset",
    "load_target_presets",
    "find_target",
    "load_lora_registry",
]

#: NovelAI 타깃 id — 코드 내장 상수 프리셋이며 JSON으로 덮어쓸 수 없다.
NOVELAI_TARGET_ID = "novelai"

#: 사용자 프리셋 폴더에서 읽는 LoRA 레지스트리 파일 이름.
LORA_REGISTRY_FILENAME = "loras.json"

#: ``flatten``/``natural_language``의 유효값.
_FLATTEN_VALUES = ("sequential", "couple_mask")
_NL_VALUES = ("drop", "append")


@dataclass(frozen=True)
class TargetPreset:
    """출력 타깃 1개의 조립 규칙."""

    id: str
    name: str
    kind: str = "local"  # "novelai" | "local"
    quality_prefix: tuple[str, ...] = ()
    quality_suffix: tuple[str, ...] = ()
    default_negative: tuple[str, ...] = ()
    weight_syntax: str = "none"  # "none" | "a1111" — A단계에서는 사용하지 않는다
    flatten: str = "sequential"  # 기본 텍스트 emitter
    position_tags: bool = True
    natural_language: str = "drop"  # "drop" | "append"
    underscore_to_space: bool = True
    #: couple_mask의 MASK_SIZE(w, h). None이면 호출자가 준 생성 해상도를 쓴다.
    mask_size: tuple[int, int] | None = None


@dataclass(frozen=True)
class LoraEntry:
    """LoRA 레지스트리 항목 1개."""

    id: str
    file: str  # 확장자 포함 파일명
    weight: float = 1.0
    triggers: tuple[str, ...] = ()

    @property
    def stem(self) -> str:
        """``<lora:...>`` 태그에 쓸 확장자 없는 이름."""
        return Path(self.file).stem


#: NovelAI 타깃 — 기존 ``PromptFormatter`` 경로를 쓴다는 표식일 뿐,
#: quality/negative 같은 필드는 쓰이지 않는다.
NOVELAI_PRESET = TargetPreset(id=NOVELAI_TARGET_ID, name="NovelAI V5", kind="novelai")


def builtin_targets_dir() -> Path:
    """패키지에 동봉된 프리셋 폴더 (i18n 리소스와 같은 규칙)."""
    return Path(__file__).resolve().parent.parent.parent / "resources" / "prompt_targets"


def _str_tuple(data: dict, key: str) -> tuple[str, ...]:
    """리스트 필드 → 문자열 튜플. 리스트가 아니면 TargetPresetError."""
    value = data.get(key, [])
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise TargetPresetError(f"{key!r} must be a list of strings")
    return tuple(v.strip() for v in value if v.strip())


def _mask_size(data: dict) -> tuple[int, int] | None:
    """``mask_size`` → (w, h) 또는 None."""
    value = data.get("mask_size")
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 2
        or any(not isinstance(v, int) or v <= 0 for v in value)
    ):
        raise TargetPresetError("'mask_size' must be [width, height] of positive ints")
    return (value[0], value[1])


def parse_preset(data: dict) -> TargetPreset:
    """프리셋 JSON 객체 1개 → ``TargetPreset``. 위반 시 ``TargetPresetError``."""
    if not isinstance(data, dict):
        raise TargetPresetError("preset must be a JSON object")
    preset_id = str(data.get("id", "")).strip()
    if not preset_id:
        raise TargetPresetError("preset needs a non-empty 'id'")
    flatten = str(data.get("flatten", "sequential"))
    if flatten not in _FLATTEN_VALUES:
        raise TargetPresetError(f"'flatten' must be one of {_FLATTEN_VALUES}, got {flatten!r}")
    natural_language = str(data.get("natural_language", "drop"))
    if natural_language not in _NL_VALUES:
        raise TargetPresetError(
            f"'natural_language' must be one of {_NL_VALUES}, got {natural_language!r}"
        )
    return TargetPreset(
        id=preset_id,
        name=str(data.get("name", "")).strip() or preset_id,
        kind="local",
        quality_prefix=_str_tuple(data, "quality_prefix"),
        quality_suffix=_str_tuple(data, "quality_suffix"),
        default_negative=_str_tuple(data, "default_negative"),
        weight_syntax=str(data.get("weight_syntax", "none")),
        flatten=flatten,
        position_tags=bool(data.get("position_tags", True)),
        natural_language=natural_language,
        underscore_to_space=bool(data.get("underscore_to_space", True)),
        mask_size=_mask_size(data),
    )


def _load_dir(directory: Path) -> list[TargetPreset]:
    """폴더의 ``*.json``을 프리셋으로 읽는다. 깨진 파일은 건너뛴다."""
    presets: list[TargetPreset] = []
    if not directory.is_dir():
        return presets
    for path in sorted(directory.glob("*.json")):
        if path.name == LORA_REGISTRY_FILENAME:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            preset = parse_preset(data)
        except (OSError, json.JSONDecodeError, ValueError, TargetPresetError) as exc:
            logger.warning("skipping broken target preset %s: %s", path, exc)
            continue
        if preset.id == NOVELAI_TARGET_ID:
            logger.warning("target preset %s claims reserved id 'novelai', ignoring", path)
            continue
        presets.append(preset)
    return presets


def load_target_presets(user_dir: str | Path | None) -> tuple[TargetPreset, ...]:
    """NovelAI + 내장 + 사용자 프리셋. 같은 id면 사용자 것이 이긴다.

    ``user_dir``이 비었거나 없는 폴더면 내장 프리셋만 쓴다 (조용히 폴백).
    """
    ordered: dict[str, TargetPreset] = {NOVELAI_TARGET_ID: NOVELAI_PRESET}
    for preset in _load_dir(builtin_targets_dir()):
        ordered[preset.id] = preset
    text = str(user_dir).strip() if user_dir is not None else ""
    if text:
        for preset in _load_dir(Path(text)):
            ordered[preset.id] = preset
    return tuple(ordered.values())


def find_target(presets: tuple[TargetPreset, ...], target_id: str) -> TargetPreset:
    """id로 프리셋을 찾는다. 없으면 ``NOVELAI_PRESET``으로 폴백."""
    for preset in presets:
        if preset.id == target_id:
            return preset
    if target_id and target_id != NOVELAI_TARGET_ID:
        logger.warning("unknown target %r, falling back to novelai", target_id)
    return NOVELAI_PRESET
```

- [ ] **Step 5: 내장 프리셋 3개를 만든다**

`src/naiauto/resources/prompt_targets/illustrious.json`:

```json
{
  "id": "illustrious",
  "name": "Illustrious / NoobAI",
  "quality_prefix": ["masterpiece", "best quality", "very awa", "absurdres"],
  "quality_suffix": [],
  "default_negative": [
    "lowres", "bad anatomy", "bad hands", "worst quality", "low quality",
    "jpeg artifacts", "signature", "watermark", "username", "blurry"
  ],
  "weight_syntax": "a1111",
  "flatten": "sequential",
  "position_tags": true,
  "natural_language": "drop",
  "underscore_to_space": true
}
```

`src/naiauto/resources/prompt_targets/animagine.json`:

```json
{
  "id": "animagine",
  "name": "Animagine XL",
  "quality_prefix": ["masterpiece", "high score", "great score", "absurdres"],
  "quality_suffix": [],
  "default_negative": [
    "lowres", "bad anatomy", "bad hands", "text", "error", "missing finger",
    "extra digits", "fewer digits", "cropped", "worst quality", "low quality",
    "signature", "watermark"
  ],
  "weight_syntax": "a1111",
  "flatten": "sequential",
  "position_tags": true,
  "natural_language": "drop",
  "underscore_to_space": true
}
```

`src/naiauto/resources/prompt_targets/sdxl_base.json`:

```json
{
  "id": "sdxl_base",
  "name": "SDXL (generic)",
  "quality_prefix": ["masterpiece", "best quality", "highly detailed"],
  "quality_suffix": [],
  "default_negative": ["lowres", "worst quality", "low quality", "watermark", "signature"],
  "weight_syntax": "a1111",
  "flatten": "sequential",
  "position_tags": true,
  "natural_language": "append",
  "underscore_to_space": true
}
```

`sdxl_base`만 `natural_language: "append"`인 것은 의도적이다 — 범용 SDXL은 자연어 캡션을 더 잘 먹는다.

- [ ] **Step 6: 테스트가 통과하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_targets.py -q`
Expected: PASS (14 passed)

- [ ] **Step 7: 커밋한다**

```bash
git add src/naiauto/core/prompt/targets.py src/naiauto/core/prompt/errors.py src/naiauto/resources/prompt_targets tests/test_targets.py
git commit -m "$(cat <<'EOF'
feat(prompt): 출력 타깃 프리셋 로더와 내장 프리셋 3종

타깃마다 달라지는 품질 태그·기본 네거티브·평탄화 방식을 JSON 데이터로 뺀다.
NovelAI는 코드 내장 상수 프리셋이며 사용자 JSON이 그 id를 덮어쓸 수 없다.
깨진 프리셋은 건너뛰고 경고만 남긴다 — 앱은 항상 뜬다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 2: LoRA 레지스트리 로더

**Files:**
- Modify: `src/naiauto/core/prompt/targets.py`
- Modify: `tests/test_targets.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_targets.py` 맨 끝에 다음을 덧붙인다. 파일 상단 import 블록의 `load_target_presets,` 줄 뒤에 `load_lora_registry,`, `LoraEntry,`, `LORA_REGISTRY_FILENAME,` 을 알파벳 순서에 맞게 추가한다 (최종 import 블록은 아래 코드의 주석 참고).

```python
# --- LoRA 레지스트리 -------------------------------------------------------
# import 블록에 다음이 포함되어야 한다:
#   LORA_REGISTRY_FILENAME, LoraEntry, load_lora_registry


def test_lora_registry_missing_dir_is_empty():
    assert load_lora_registry(None) == {}


def test_lora_registry_missing_file_is_empty(tmp_path):
    assert load_lora_registry(tmp_path) == {}


def test_lora_registry_reads_entries(tmp_path):
    (tmp_path / LORA_REGISTRY_FILENAME).write_text(
        json.dumps(
            {
                "kafka": {
                    "file": "kafka_illustrious.safetensors",
                    "weight": 0.8,
                    "triggers": ["kafka", "purple hair"],
                }
            }
        ),
        encoding="utf-8",
    )
    registry = load_lora_registry(tmp_path)
    assert registry["kafka"] == LoraEntry(
        id="kafka",
        file="kafka_illustrious.safetensors",
        weight=0.8,
        triggers=("kafka", "purple hair"),
    )
    assert registry["kafka"].stem == "kafka_illustrious"


def test_lora_registry_applies_defaults(tmp_path):
    (tmp_path / LORA_REGISTRY_FILENAME).write_text(
        json.dumps({"bare": {"file": "bare.safetensors"}}), encoding="utf-8"
    )
    entry = load_lora_registry(tmp_path)["bare"]
    assert entry.weight == 1.0
    assert entry.triggers == ()


def test_lora_registry_skips_broken_entries_keeps_good(tmp_path):
    (tmp_path / LORA_REGISTRY_FILENAME).write_text(
        json.dumps(
            {
                "no_file": {"weight": 1.0},
                "bad_weight": {"file": "x.safetensors", "weight": "heavy"},
                "bad_triggers": {"file": "y.safetensors", "triggers": "not a list"},
                "good": {"file": "good.safetensors"},
            }
        ),
        encoding="utf-8",
    )
    registry = load_lora_registry(tmp_path)
    assert set(registry) == {"good"}


def test_lora_registry_broken_json_is_empty(tmp_path):
    (tmp_path / LORA_REGISTRY_FILENAME).write_text("{ not json", encoding="utf-8")
    assert load_lora_registry(tmp_path) == {}
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_targets.py -q`
Expected: FAIL — `ImportError: cannot import name 'load_lora_registry'`

- [ ] **Step 3: `load_lora_registry`를 구현한다**

`src/naiauto/core/prompt/targets.py` 맨 끝(파일의 `find_target` 뒤)에 다음을 덧붙인다:

```python
def _parse_lora(entry_id: str, data: object) -> LoraEntry:
    """레지스트리 항목 1개 → ``LoraEntry``. 위반 시 ``TargetPresetError``."""
    if not isinstance(data, dict):
        raise TargetPresetError("lora entry must be a JSON object")
    file = str(data.get("file", "")).strip()
    if not file:
        raise TargetPresetError("lora entry needs a non-empty 'file'")
    weight = data.get("weight", 1.0)
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        raise TargetPresetError("'weight' must be a number")
    triggers = data.get("triggers", [])
    if not isinstance(triggers, list) or any(not isinstance(t, str) for t in triggers):
        raise TargetPresetError("'triggers' must be a list of strings")
    return LoraEntry(
        id=entry_id,
        file=file,
        weight=float(weight),
        triggers=tuple(t.strip() for t in triggers if t.strip()),
    )


def load_lora_registry(user_dir: str | Path | None) -> dict[str, LoraEntry]:
    """사용자 폴더의 ``loras.json`` → {id: LoraEntry}.

    폴더/파일 없음, JSON 파손 → 빈 dict (LoRA 기능 비활성). 개별 항목이
    깨진 경우 그 항목만 건너뛰고 나머지는 살린다.
    """
    text = str(user_dir).strip() if user_dir is not None else ""
    if not text:
        return {}
    path = Path(text) / LORA_REGISTRY_FILENAME
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("lora registry broken, ignoring %s: %s", path, exc)
        return {}
    if not isinstance(data, dict):
        logger.warning("lora registry must be a JSON object: %s", path)
        return {}
    registry: dict[str, LoraEntry] = {}
    for entry_id, raw in data.items():
        try:
            registry[str(entry_id)] = _parse_lora(str(entry_id), raw)
        except TargetPresetError as exc:
            logger.warning("skipping lora entry %r in %s: %s", entry_id, path, exc)
    return registry
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_targets.py -q`
Expected: PASS (20 passed)

- [ ] **Step 5: 린트 후 커밋한다**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/core/prompt/targets.py tests/test_targets.py
git commit -m "$(cat <<'EOF'
feat(prompt): LoRA 레지스트리(loras.json) 로더

LLM은 사용자가 어떤 LoRA를 갖고 있는지 알 수 없으므로 사용자 설정 파일로
둔다. 파일이 없으면 LoRA 기능 전체가 조용히 비활성되고, 개별 항목이 깨져도
나머지는 살린다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 3: `count_tag`를 재사용 가능한 모듈 함수로 추출

emitter가 `2girls` 같은 count 태그를 만들려면 기존 로직이 필요하다. `PromptFormatter.count_tag`는 인스턴스 상태를 전혀 쓰지 않으므로 모듈 함수로 빼고 메서드는 위임만 한다. **동작은 바뀌지 않는다** — 기존 테스트가 그대로 통과해야 한다.

**Files:**
- Modify: `src/naiauto/core/prompt/formatter.py`
- Test: `tests/test_formatter.py` (기존 테스트가 회귀 검증)

- [ ] **Step 1: 기준선을 잡는다**

Run: `uv run --extra dev pytest tests/test_formatter.py -q`
Expected: PASS — 이후 단계에서 이 결과가 바뀌면 안 된다.

- [ ] **Step 2: 모듈 함수를 추가한다**

`src/naiauto/core/prompt/formatter.py`에서 `_SANITIZE_RE = ...` 줄 **뒤**, `class PromptFormatter:` **앞**에 다음을 넣는다:

```python
def count_tag(subjects: tuple[str, ...]) -> str:
    """subjects가 모두 같고 ``SUBJECT_PLURALS``에 있으면 count 태그, 아니면 "".

    n>=2면 "{n}{복수형}"("2girls"), n==1이면 "1girl".
    ``emitters``와 ``PromptFormatter`` 양쪽이 쓴다.
    """
    if not subjects:
        return ""
    first = subjects[0]
    if first not in SUBJECT_PLURALS:
        return ""
    if any(s != first for s in subjects):
        return ""
    if len(subjects) >= 2:
        return f"{len(subjects)}{SUBJECT_PLURALS[first]}"
    return f"{len(subjects)}{first}"
```

- [ ] **Step 3: 메서드를 위임으로 바꾼다**

같은 파일의 `PromptFormatter.count_tag` 메서드 **전체**를 다음으로 교체한다:

```python
    def count_tag(self, subjects: tuple[str, ...]) -> str:
        """모듈 함수 ``count_tag``에 위임한다 (하위 호환용 메서드)."""
        return count_tag(subjects)
```

- [ ] **Step 4: `__all__`에 추가한다**

같은 파일 맨 끝 `__all__`을 다음으로 교체한다:

```python
__all__ = ["SUBJECT_PLURALS", "COUNT_TAG_RE", "ACTION_PHRASES", "count_tag", "PromptFormatter"]
```

- [ ] **Step 5: 회귀가 없는지 확인한다**

Run: `uv run --extra dev pytest tests/test_formatter.py tests/test_compiler.py -q`
Expected: PASS — Step 1과 같은 결과

- [ ] **Step 6: 커밋한다**

```bash
git add src/naiauto/core/prompt/formatter.py
git commit -m "$(cat <<'EOF'
refactor(prompt): count_tag를 모듈 함수로 추출

emitters가 같은 로직을 쓰려면 인스턴스 없이 호출할 수 있어야 한다.
메서드는 위임만 하므로 동작은 그대로다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 4: emitter 공용 헬퍼

세 emitter가 공유하는 조각을 먼저 만든다: 태그 정규화, 캐릭터 블록, 위치 태그, 관계 태그, 영역 좌표, LoRA 태그, 네거티브.

**Files:**
- Create: `src/naiauto/core/prompt/emitters.py`
- Create: `tests/test_emitters.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_emitters.py`를 새로 만든다:

```python
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_emitters.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'naiauto.core.prompt.emitters'`

이 시점에는 `CompiledPrompt`에 `target` 필드가 없어서 `TypeError`가 날 수도 있다. **Task 5에서 필드를 추가하기 전이므로**, 지금은 `tests/test_emitters.py`의 `compiled()` 헬퍼에서 `target=target` 인자를 임시로 빼지 말고 그대로 두고 넘어간다 — Step 3에서 `schema.py`를 먼저 고친다.

- [ ] **Step 3: `CompiledPrompt`에 `target` 필드를 추가한다**

`src/naiauto/core/prompt/schema.py`의 `CompiledPrompt` 정의에서 `unresolved: tuple[str, ...]` 줄 **뒤**에 다음을 넣는다:

```python
    #: 출력 대상 프리셋 id. "novelai"(기본)면 기존 NovelAI 경로.
    target: str = "novelai"
```

- [ ] **Step 4: `emitters.py`의 공용 헬퍼를 구현한다**

`src/naiauto/core/prompt/emitters.py`를 새로 만든다:

```python
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

#: 중복 쉼표/공백 정리 ("tag ,, tag" → "tag, tag").
#: formatter._sanitize와 같은 규칙이지만 그쪽은 비공개 메서드라 여기 따로 둔다.
_SANITIZE_RE = re.compile(r"\s*,\s*")

#: position_hint에서 수평 토큰만 골라내기 위한 세로 토큰 목록.
_VERTICAL_TOKENS = ("top", "bottom", "center")


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
    seen: set[str] = set()
    for rel in relationships:
        tag = MUTUAL_RELATION_TAGS.get(rel.action) if rel.mutual else None
        if tag is None:
            warnings.append(
                f"relationship {rel.source}->{rel.target} ({rel.action}) has no local "
                "tag equivalent and was dropped"
            )
            continue
        if tag not in seen:
            seen.add(tag)
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
    """캐릭터별 LoRA 배정 → ``<lora:stem:weight>`` 목록 (파일 기준 중복 제거)."""
    tags: list[str] = []
    seen: set[str] = set()
    for entry in loras.values():
        if entry.file in seen:
            continue
        seen.add(entry.file)
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
        if token in _VERTICAL_TOKENS:
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
    """태그 목록 → 최종 문자열 (언더스코어 치환 + 중복 쉼표 정리).

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
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_emitters.py tests/test_compiler.py tests/test_merge.py -q`
Expected: PASS — `test_emitters.py` 19 passed, 기존 테스트도 그대로 통과

- [ ] **Step 6: 커밋한다**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/core/prompt/emitters.py src/naiauto/core/prompt/schema.py tests/test_emitters.py
git commit -m "$(cat <<'EOF'
feat(prompt): emitter 공용 헬퍼와 CompiledPrompt.target

세 emitter가 공유하는 조각을 먼저 만든다 — 위치 태그, 상호 관계 태그 매핑,
가로 균등 분할 영역, LoRA 태그, 네거티브 병합. 단방향 관계는 단일 프롬프트로
표현할 수단이 없어 드롭하되 경고를 남긴다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 5: `emit_sequential`

**Files:**
- Modify: `src/naiauto/core/prompt/emitters.py`
- Modify: `tests/test_emitters.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_emitters.py` 맨 끝에 다음을 덧붙인다. 파일 상단 import 블록의 `character_regions,` 앞에 `emit_sequential,`을 추가한다.

```python
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
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_emitters.py -q`
Expected: FAIL — `ImportError: cannot import name 'emit_sequential'`

- [ ] **Step 3: `emit_sequential`을 구현한다**

`src/naiauto/core/prompt/emitters.py`의 `_finalize` 함수 **뒤**에 다음을 덧붙인다:

```python
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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_emitters.py -q`
Expected: PASS (30 passed)

- [ ] **Step 5: 커밋한다**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/core/prompt/emitters.py tests/test_emitters.py
git commit -m "$(cat <<'EOF'
feat(prompt): emit_sequential — 단일 Positive/Negative 조립

품질 프리픽스를 맨 앞에 두고(SDXL은 앞쪽 토큰 가중이 크다), 캐릭터 블록을
순서대로 이어붙인 뒤 씬·관계·구도를 붙인다. 1인일 때는 위치 태그를 넣지
않는다 — 혼자인데 "on the left"는 구도만 망친다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 6: `emit_couple_mask`

대상 확장: **`asagi4/comfyui-prompt-control`**. 문법은 `MASK(x1 x2, y1 y2, weight, op)` (0..1 정규화), `COUPLE MASK(...)`, `MASK_SIZE(width, height)`.

**Files:**
- Modify: `src/naiauto/core/prompt/emitters.py`
- Modify: `tests/test_emitters.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_emitters.py` 맨 끝에 다음을 덧붙인다. import 블록에 `emit_couple_mask,`를 추가한다.

```python
# --- emit_couple_mask ------------------------------------------------------


def test_couple_mask_two_characters_full_layout():
    positive, negative = emit_couple_mask(
        compiled(
            scene_tags=("rain", "night"),
            subjects=("girl", "girl"),
            characters=(
                char("c1", ["purple_hair"], hint="left", cx=0.30),
                char("c2", ["silver_hair"], hint="right", cx=0.70),
            ),
        ),
        PRESET,
        {},
        resolution=(832, 1216),
    )
    assert positive.splitlines() == [
        "MASK_SIZE(832, 1216) masterpiece, best quality, 2girls, rain, night",
        "COUPLE MASK(0 0.5, 0 1) purple hair",
        "COUPLE MASK(0.5 1, 0 1) silver hair",
    ]
    assert negative == "lowres, worst quality"


def test_couple_mask_omits_position_tags():
    positive, _ = emit_couple_mask(
        compiled(
            characters=(
                char("c1", ["a"], hint="left", cx=0.3),
                char("c2", ["b"], hint="right", cx=0.7),
            )
        ),
        PRESET,
        {},
        resolution=(832, 1216),
    )
    assert "on the left" not in positive
    assert "on the right" not in positive


def test_couple_mask_single_character_merges_into_global():
    positive, _ = emit_couple_mask(
        compiled(
            scene_tags=("alley",),
            subjects=("girl",),
            characters=(char("c1", ["silver_hair"], hint="left", cx=0.30),),
        ),
        PRESET,
        {},
        resolution=(832, 1216),
    )
    assert "COUPLE" not in positive
    assert "MASK_SIZE" not in positive
    assert "silver hair" in positive


def test_couple_mask_no_characters_is_single_line():
    positive, _ = emit_couple_mask(
        compiled(scene_tags=("alley", "night")), PRESET, {}, resolution=(832, 1216)
    )
    assert positive == "masterpiece, best quality, alley, night"


def test_couple_mask_preset_mask_size_wins_over_resolution():
    preset = TargetPreset(id="p", name="P", mask_size=(1024, 1024))
    positive, _ = emit_couple_mask(
        compiled(characters=(char("c1", ["a"], cx=0.3), char("c2", ["b"], cx=0.7))),
        preset,
        {},
        resolution=(832, 1216),
    )
    assert positive.startswith("MASK_SIZE(1024, 1024) ")


def test_couple_mask_without_resolution_omits_mask_size():
    positive, _ = emit_couple_mask(
        compiled(characters=(char("c1", ["a"], cx=0.3), char("c2", ["b"], cx=0.7))),
        PRESET,
        {},
        resolution=None,
    )
    assert "MASK_SIZE" not in positive
    assert positive.splitlines()[1].startswith("COUPLE MASK(0 0.5, 0 1) ")


def test_couple_mask_lora_tag_global_trigger_in_couple_line():
    entry = LoraEntry(id="kafka", file="kafka.safetensors", weight=0.8, triggers=("kafka",))
    positive, _ = emit_couple_mask(
        compiled(
            characters=(char("c1", ["purple_hair"], cx=0.3), char("c2", ["black_hair"], cx=0.7))
        ),
        PRESET,
        {"c1": entry},
        resolution=(832, 1216),
    )
    lines = positive.splitlines()
    assert lines[0].startswith("MASK_SIZE(832, 1216) <lora:kafka:0.8>, masterpiece")
    assert lines[1] == "COUPLE MASK(0 0.5, 0 1) kafka, purple hair"


def test_couple_mask_three_way_coordinates():
    positive, _ = emit_couple_mask(
        compiled(
            characters=(
                char("c1", ["a"], cx=0.15),
                char("c2", ["b"], cx=0.5),
                char("c3", ["c"], cx=0.85),
            )
        ),
        PRESET,
        {},
        resolution=(1024, 1024),
    )
    masks = [line.split(")")[0] + ")" for line in positive.splitlines()[1:]]
    assert masks == [
        "COUPLE MASK(0 0.333, 0 1)",
        "COUPLE MASK(0.333 0.667, 0 1)",
        "COUPLE MASK(0.667 1, 0 1)",
    ]
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_emitters.py -q`
Expected: FAIL — `ImportError: cannot import name 'emit_couple_mask'`

- [ ] **Step 3: `emit_couple_mask`를 구현한다**

`src/naiauto/core/prompt/emitters.py`의 `emit_sequential` 함수 **뒤**에 다음을 덧붙인다:

```python
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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_emitters.py -q`
Expected: PASS (38 passed)

- [ ] **Step 5: 커밋한다**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/core/prompt/emitters.py tests/test_emitters.py
git commit -m "$(cat <<'EOF'
feat(prompt): emit_couple_mask — 어텐션 좌표 출력

asagi4/comfyui-prompt-control의 COUPLE MASK 문법으로 방출한다. 확장의 기본
가정이 512x512라 SDXL 해상도에서는 MASK_SIZE를 반드시 명시한다. 캐릭터가
2명 미만이면 영역 분할의 의미가 없어 글로벌 라인 하나로 끝낸다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 7: `emit_regional_json`

**Files:**
- Modify: `src/naiauto/core/prompt/emitters.py`
- Modify: `tests/test_emitters.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_emitters.py` 맨 끝에 다음을 덧붙인다. import 블록에 `emit_regional_json,`을 추가한다.

```python
# --- emit_regional_json ----------------------------------------------------


def test_regional_json_shape():
    data = emit_regional_json(
        compiled(
            scene_tags=("rain", "night"),
            subjects=("girl", "girl"),
            characters=(
                char("c1", ["purple_hair"], cx=0.30, cy=0.5),
                char("c2", ["silver_hair"], cx=0.70, cy=0.5),
            ),
            target="demo",
        ),
        PRESET,
        {},
    )
    assert data["target"] == "demo"
    assert data["global"] == {
        "positive": "masterpiece, best quality, 2girls, rain, night",
        "negative": "lowres, worst quality",
    }
    assert data["regions"] == [
        {
            "id": "c1",
            "positive": "purple hair",
            "negative": "",
            "x": 0.0,
            "y": 0.0,
            "width": 0.5,
            "height": 1.0,
            "center_x": 0.30,
            "center_y": 0.5,
        },
        {
            "id": "c2",
            "positive": "silver hair",
            "negative": "",
            "x": 0.5,
            "y": 0.0,
            "width": 0.5,
            "height": 1.0,
            "center_x": 0.70,
            "center_y": 0.5,
        },
    ]


def test_regional_json_global_has_no_character_tags():
    data = emit_regional_json(
        compiled(scene_tags=("alley",), characters=(char("c1", ["silver_hair"], cx=0.3),)),
        PRESET,
        {},
    )
    assert "silver hair" not in data["global"]["positive"]


def test_regional_json_no_characters_has_empty_regions():
    data = emit_regional_json(compiled(scene_tags=("alley",)), PRESET, {})
    assert data["regions"] == []


def test_regional_json_sorts_regions_by_center_x():
    data = emit_regional_json(
        compiled(characters=(char("c1", ["a"], cx=0.85), char("c2", ["b"], cx=0.15))),
        PRESET,
        {},
    )
    assert [r["id"] for r in data["regions"]] == ["c2", "c1"]


def test_regional_json_missing_center_is_null():
    data = emit_regional_json(compiled(characters=(char("c1", ["a"]),)), PRESET, {})
    assert data["regions"][0]["center_x"] is None
    assert data["regions"][0]["center_y"] is None


def test_regional_json_character_negative_is_carried():
    data = emit_regional_json(
        compiled(characters=(char("c1", ["a"], cx=0.5, negative=("blurry",)),)), PRESET, {}
    )
    assert data["regions"][0]["negative"] == "blurry"


def test_regional_json_lora_is_separate_key_not_merged_into_positive():
    entry = LoraEntry(id="kafka", file="kafka.safetensors", weight=0.8, triggers=("kafka",))
    data = emit_regional_json(
        compiled(characters=(char("c1", ["purple_hair"], cx=0.5),)), PRESET, {"c1": entry}
    )
    region = data["regions"][0]
    assert region["lora"] == {
        "file": "kafka.safetensors",
        "weight": 0.8,
        "triggers": ["kafka"],
    }
    assert "kafka" not in region["positive"]
    assert "<lora:" not in data["global"]["positive"]


def test_regional_json_omits_lora_key_when_unassigned():
    data = emit_regional_json(compiled(characters=(char("c1", ["a"], cx=0.5),)), PRESET, {})
    assert "lora" not in data["regions"][0]
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_emitters.py -q`
Expected: FAIL — `ImportError: cannot import name 'emit_regional_json'`

- [ ] **Step 3: `emit_regional_json`을 구현한다**

`src/naiauto/core/prompt/emitters.py`의 `emit_couple_mask` 함수 **뒤**에 덧붙인다:

```python
def emit_regional_json(
    compiled: CompiledPrompt,
    preset: TargetPreset,
    loras: Mapping[str, LoraEntry] | None = None,
) -> dict:
    """구조화 영역 출력 — 좌표는 0..1 정규화 (해상도 곱셈은 백엔드 몫).

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
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_emitters.py -q`
Expected: PASS (46 passed)

- [ ] **Step 5: 커밋한다**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/core/prompt/emitters.py tests/test_emitters.py
git commit -m "$(cat <<'EOF'
feat(prompt): emit_regional_json — 구조화 영역 출력

좌표를 0..1 정규화로 내보내고 해상도 곱셈은 소비하는 쪽에 맡긴다. LoRA는
positive에 합치지 않고 lora 키로 분리해 둔다 — 백엔드가 LoraLoader 결선과
텍스트 태그 중 고를 수 있어야 한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 8: `merge`가 로컬 타깃에서 캐릭터를 비운다

**Files:**
- Modify: `src/naiauto/core/prompt/merge.py`
- Modify: `tests/test_merge.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_merge.py` 맨 끝에 다음을 덧붙인다:

```python
def _compiled_with_target(target: str):
    from naiauto.core.prompt.schema import (
        CharacterPrompt,
        CompiledPrompt,
        ScenePrompt,
        TagRef,
    )

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
    from naiauto.core.prompt.merge import to_generation_data

    result = to_generation_data(_compiled_with_target("novelai"))
    assert len(result.characters) == 1
    assert result.characters[0].prompt == "silver_hair"


def test_local_target_drops_character_captions():
    from naiauto.core.prompt.merge import to_generation_data

    result = to_generation_data(_compiled_with_target("illustrious"))
    assert result.characters == ()
    assert result.prompt == "2girls, rain"
    assert result.negative_prompt == "lowres"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_merge.py -q`
Expected: FAIL — `test_local_target_drops_character_captions`에서 `assert (CharacterCaption(...),) == ()`

- [ ] **Step 3: `merge.py`를 고친다**

`src/naiauto/core/prompt/merge.py`의 import 블록 마지막(`from naiauto.core.prompt.schema import CompiledPrompt` 줄) **뒤**에 다음을 넣는다:

```python
from naiauto.core.prompt.targets import NOVELAI_TARGET_ID
```

같은 파일 `to_generation_data`의 `characters = tuple(` 로 시작하는 표현식 **앞**에 다음을 넣는다:

```python
    # 로컬 타깃은 캐릭터별 프롬프트 개념이 없다 — 캐릭터 태그는 이미 본문에
    # 합쳐져 있으므로 CharacterCaption을 만들지 않는다.
    if compiled.target != NOVELAI_TARGET_ID:
        return MergeResult(
            prompt=compiled.base_prompt,
            negative_prompt=merge_negatives(existing_negative, compiled.negative_prompt),
            characters=(),
        )
```

`to_generation_data`의 독스트링 끝에 다음 한 줄을 덧붙인다:

```
    ``compiled.target``이 "novelai"가 아니면 ``characters``는 항상 빈 튜플이다.
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_merge.py -q`
Expected: PASS

- [ ] **Step 5: 순환 import가 없는지 확인한다**

`merge` → `targets` → `errors` 방향이고 `targets`는 `merge`를 import하지 않으므로 순환이 없다. `emitters`가 `merge.merge_negatives`를 쓰는 것도 단방향이다. 확인:

Run: `uv run --extra dev python -c "import naiauto.core.prompt as p; print(p.__name__, 'ok')"`
Expected: `naiauto.core.prompt ok`

- [ ] **Step 6: 커밋한다**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/core/prompt/merge.py tests/test_merge.py
git commit -m "$(cat <<'EOF'
feat(prompt): 로컬 타깃에서는 CharacterCaption을 만들지 않는다

로컬 SDXL은 캐릭터별 프롬프트 개념이 없고 캐릭터 태그가 이미 본문에 합쳐져
있다. 호출부 시그니처는 그대로다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 9: 컴파일러에 타깃 축 연결

**Files:**
- Modify: `src/naiauto/core/prompt/compiler.py`
- Modify: `src/naiauto/core/prompt/__init__.py`
- Modify: `tests/test_compiler.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_compiler.py` 맨 끝에 다음을 덧붙인다. 이 테스트는 파일 안에 이미 있는 스텁 provider 패턴을 쓰지 않고, 파서를 직접 대체해 LLM 호출을 없앤다.

```python
# --- 출력 타깃 -------------------------------------------------------------


def _target_compiler(monkeypatch, raw_json: dict):
    """LLM을 타지 않는 컴파일러 — 파서만 스텁으로 갈아 끼운다."""
    from naiauto.core.prompt.compiler import PromptCompiler
    from naiauto.core.prompt.formatter import PromptFormatter
    from naiauto.core.prompt.schema import LLMStructuredPrompt

    class _StubProvider:
        def chat(self, messages, **kwargs):  # pragma: no cover - 호출되지 않는다
            raise AssertionError("provider should not be called")

    class _StubResolver:
        def resolve_phrase(self, phrase):  # 전부 verified로 통과
            from naiauto.core.prompt.schema import TagRef

            return [TagRef(tag=phrase, status="verified")]

    compiler = PromptCompiler(
        provider=_StubProvider(),
        resolver=_StubResolver(),
        formatter=PromptFormatter(),
    )
    parsed = LLMStructuredPrompt.model_validate(raw_json)
    monkeypatch.setattr(compiler._parser, "parse", lambda *a, **k: parsed)
    return compiler


_RAW = {
    "scene": {"tags": ["rain", "night"], "subjects": ["girl", "girl"]},
    "characters": [
        {"id": "c1", "tags": ["silver_hair"], "position_hint": "left"},
        {"id": "c2", "tags": ["black_hair"], "position_hint": "right"},
    ],
}


def test_compile_default_target_is_novelai(monkeypatch):
    compiled = _target_compiler(monkeypatch, _RAW).compile("x")
    assert compiled.target == "novelai"
    assert compiled.characters[0].prompt_text == "silver_hair"


def test_compile_local_target_flattens_into_base_prompt(monkeypatch):
    compiled = _target_compiler(monkeypatch, _RAW).compile("x", target="illustrious")
    assert compiled.target == "illustrious"
    assert "silver hair" in compiled.base_prompt
    assert "black hair" in compiled.base_prompt
    assert compiled.base_prompt.startswith("masterpiece")


def test_compile_unknown_target_falls_back_to_novelai(monkeypatch):
    compiled = _target_compiler(monkeypatch, _RAW).compile("x", target="no-such")
    assert compiled.target == "novelai"


def test_compile_couple_mask_flatten_uses_couple_emitter(monkeypatch):
    from naiauto.core.prompt.targets import TargetPreset

    compiler = _target_compiler(monkeypatch, _RAW)
    compiler.target_presets = compiler.target_presets + (
        TargetPreset(id="couple", name="Couple", flatten="couple_mask"),
    )
    compiled = compiler.compile("x", target="couple", resolution=(832, 1216))
    assert compiled.base_prompt.startswith("MASK_SIZE(832, 1216) ")
    assert "COUPLE MASK(0 0.5, 0 1)" in compiled.base_prompt


def test_compile_character_loras_reach_the_prompt(monkeypatch):
    from naiauto.core.prompt.targets import LoraEntry

    entry = LoraEntry(id="k", file="k.safetensors", weight=0.8, triggers=("kafka",))
    compiled = _target_compiler(monkeypatch, _RAW).compile(
        "x", target="illustrious", character_loras={"c1": entry}
    )
    assert compiled.base_prompt.startswith("<lora:k:0.8>, masterpiece")
    assert "kafka, silver hair" in compiled.base_prompt


def test_compile_local_target_records_relationship_warning(monkeypatch):
    raw = dict(_RAW)
    raw = {
        **_RAW,
        "relationships": [
            {"source": "c1", "target": "c2", "action": "chasing", "mutual": False}
        ],
    }
    compiled = _target_compiler(monkeypatch, raw).compile("x", target="illustrious")
    assert any("chasing" in w for w in compiled.warnings)


def test_modify_preserves_tokens_on_local_target(monkeypatch):
    raw = {
        "scene": {"tags": ["rain"], "subjects": ["girl"]},
        "characters": [{"id": "c1", "tags": ["silver_hair"]}],
    }
    compiled = _target_compiler(monkeypatch, raw).modify(
        "1girl, __dynamic__, {artist:grp}", "비를 추가해줘", target="illustrious"
    )
    assert "__dynamic__" in compiled.base_prompt
    assert "{artist:grp}" in compiled.base_prompt
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_compiler.py -q`
Expected: FAIL — `TypeError: compile() got an unexpected keyword argument 'target'`

- [ ] **Step 3: `PromptCompiler.__init__`에 타깃 상태를 추가한다**

`src/naiauto/core/prompt/compiler.py`의 import 블록에서 `from naiauto.core.prompt.schema import (` 블록 **뒤**에 다음 두 줄을 넣는다:

```python
from naiauto.core.prompt.emitters import emit_couple_mask, emit_sequential
from naiauto.core.prompt.targets import (
    NOVELAI_PRESET,
    LoraEntry,
    TargetPreset,
    find_target,
    load_lora_registry,
    load_target_presets,
)
```

같은 파일에서 `from collections.abc import Mapping`이 없으므로 `from types import SimpleNamespace` 줄 **앞**에 다음을 넣는다:

```python
from collections.abc import Mapping
```

`PromptCompiler.__init__`의 시그니처 마지막 인자 `server_manager=None,` **뒤**에 다음을 넣는다:

```python
        target_presets: tuple[TargetPreset, ...] = (NOVELAI_PRESET,),
        lora_registry: Mapping[str, LoraEntry] | None = None,
```

`__init__` 본문 마지막 줄(`self._server_manager = server_manager`) **뒤**에 다음을 넣는다:

```python
        #: 사용 가능한 출력 타깃 프리셋 (UI가 콤보를 채울 때도 읽는다).
        self.target_presets = target_presets
        #: 사용자 LoRA 레지스트리 (id → LoraEntry). UI가 드롭다운을 채울 때 읽는다.
        self.lora_registry = dict(lora_registry or {})
```

- [ ] **Step 4: `compile`/`modify`/`_assemble`에 타깃을 흘려보낸다**

`compile` 메서드 전체를 다음으로 교체한다:

```python
    def compile(
        self,
        text: str,
        *,
        mode: str = "hybrid",
        target: str = "novelai",
        character_loras: Mapping[str, LoraEntry] | None = None,
        resolution: tuple[int, int] | None = None,
    ) -> CompiledPrompt:
        """자연어 → CompiledPrompt. 빈 입력은 CompilerEmptyResultError.

        ``target``은 출력 대상 프리셋 id다. 모르는 id면 novelai로 폴백한다.
        ``character_loras``는 캐릭터 id → LoRA 배정(로컬 타깃에서만 쓰인다).
        ``resolution``은 couple_mask의 MASK_SIZE에 쓰인다.
        """
        if mode not in MODE_TAGS:
            raise ValueError(f"invalid mode: {mode!r} (expected one of {MODE_TAGS})")
        if not text.strip():
            raise CompilerEmptyResultError("empty input")
        tags, translations = self._retrieve((text,))
        raw = self._parser.parse(
            text,
            candidate_tags=tags,
            translated_text=translations.get(text, ""),
        )
        return self._assemble(raw, mode, target, character_loras or {}, resolution)
```

`modify` 메서드 시그니처와 본문의 `_assemble` 호출을 다음처럼 바꾼다. 시그니처를:

```python
    def modify(
        self,
        existing_prompt: str,
        instruction: str,
        *,
        mode: str = "hybrid",
        target: str = "novelai",
        character_loras: Mapping[str, LoraEntry] | None = None,
        resolution: tuple[int, int] | None = None,
    ) -> CompiledPrompt:
```

본문의 `result = self._assemble(raw, mode)` 줄을 다음으로 바꾼다:

```python
        result = self._assemble(raw, mode, target, character_loras or {}, resolution)
```

`_assemble` 시그니처를 다음으로 바꾼다:

```python
    def _assemble(
        self,
        raw: LLMStructuredPrompt,
        mode: str,
        target: str = "novelai",
        character_loras: Mapping[str, LoraEntry] | None = None,
        resolution: tuple[int, int] | None = None,
    ) -> CompiledPrompt:
```

- [ ] **Step 5: `_assemble`의 조립 단계를 타깃별로 분기시킨다**

`_assemble` 본문에서 `# 7/8. 문자열 조립 ...` 주석부터 `characters = [...]` 표현식까지의 블록 **전체**를 다음으로 교체한다:

```python
        # 7/8. 문자열 조립 — 타깃에 따라 NovelAI 포맷터 또는 로컬 emitter.
        preset = find_target(self.target_presets, target)
        emitter_warnings: list[str] = []
        if preset.kind == "novelai":
            base, negative = self._formatter.format(
                scene=scene,
                characters=tuple(characters),
                relationships=tuple(relationships),
                negative_tags=tuple(neg_refs),
                mode=mode,
            )
            characters = [
                replace(c, prompt_text=self._formatter.character_prompt_text(c, mode))
                for c in characters
            ]
        else:
            draft = CompiledPrompt(
                base_prompt="",
                negative_prompt=", ".join(ref.tag for ref in neg_refs),
                scene=scene,
                characters=tuple(characters),
                relationships=tuple(relationships),
                mode=mode,
                warnings=(),
                unresolved=(),
                target=preset.id,
            )
            loras = character_loras or {}
            if preset.flatten == "couple_mask":
                base, negative = emit_couple_mask(draft, preset, loras, resolution=resolution)
            else:
                base, negative = emit_sequential(draft, preset, loras)
            _, emitter_warnings = relationship_tags(tuple(relationships))
```

`_assemble`의 마지막 `return CompiledPrompt(...)` 표현식을 다음으로 교체한다:

```python
        return CompiledPrompt(
            base_prompt=base,
            negative_prompt=negative,
            scene=scene,
            characters=tuple(characters),
            relationships=tuple(relationships),
            mode=mode,
            warnings=tuple(warnings),
            unresolved=tuple(unresolved),
            target=preset.id,
        )
```

`warnings = list(rel_warnings)` 줄을 다음으로 교체한다:

```python
        warnings = list(rel_warnings) + emitter_warnings
```

`relationship_tags`를 쓰므로 Step 3의 emitters import 줄을 다음으로 바꾼다:

```python
from naiauto.core.prompt.emitters import emit_couple_mask, emit_sequential, relationship_tags
```

- [ ] **Step 6: `build_compiler`가 프리셋과 레지스트리를 로드하게 한다**

`build_compiler` 함수에서 `formatter = PromptFormatter(` 표현식 **앞**에 다음을 넣는다:

```python
    presets_dir = getattr(comp, "target_presets_dir", "") or ""
    target_presets = load_target_presets(presets_dir)
    lora_registry = load_lora_registry(presets_dir)
```

같은 함수 마지막 `return PromptCompiler(` 표현식의 `server_manager=server_manager,` 줄 **뒤**에 다음을 넣는다:

```python
        target_presets=target_presets,
        lora_registry=lora_registry,
```

- [ ] **Step 7: 공개 API에 새 심볼을 노출한다**

`src/naiauto/core/prompt/__init__.py`의 import 블록에 다음 두 줄을 `from naiauto.core.prompt.compiler import ...` 줄 **뒤**에 넣는다:

```python
from naiauto.core.prompt.emitters import emit_couple_mask, emit_regional_json, emit_sequential
from naiauto.core.prompt.targets import (
    NOVELAI_TARGET_ID,
    LoraEntry,
    TargetPreset,
    find_target,
    load_lora_registry,
    load_target_presets,
)
```

같은 파일의 `__all__`을 다음으로 교체한다:

```python
__all__ = [
    "PromptCompiler",
    "CompiledPrompt",
    "build_compiler",
    "to_generation_data",
    "MergeResult",
    "TagResolver",
    "PromptFormatter",
    "API_KEY_CREDENTIAL",
    "NOVELAI_TARGET_ID",
    "TargetPreset",
    "LoraEntry",
    "load_target_presets",
    "load_lora_registry",
    "find_target",
    "emit_sequential",
    "emit_couple_mask",
    "emit_regional_json",
]
```

- [ ] **Step 8: 테스트가 통과하는지 확인한다**

Run: `uv run --extra dev pytest tests/ -q`
Expected: PASS — 전체 스위트 통과 (기존 테스트 회귀 없음)

- [ ] **Step 9: 커밋한다**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/core/prompt/compiler.py src/naiauto/core/prompt/__init__.py tests/test_compiler.py
git commit -m "$(cat <<'EOF'
feat(prompt): 컴파일러에 출력 타깃 축 연결

compile/modify가 target·character_loras·resolution을 받고 _assemble이
NovelAI 포맷터와 로컬 emitter로 분기한다. 모르는 타깃 id는 novelai로
폴백하므로 기존 호출부는 전부 그대로 동작한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 10: 설정 스키마

**Files:**
- Modify: `src/naiauto/core/settings/schema.py`
- Modify: `tests/test_settings_compiler.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_settings_compiler.py` 맨 끝에 다음을 덧붙인다:

```python
def test_compiler_target_defaults():
    from naiauto.core.settings.schema import AppSettings

    settings = AppSettings()
    assert settings.compiler.default_target == "novelai"
    assert settings.compiler.target_presets_dir == ""


def test_compiler_target_round_trips(tmp_path):
    import json

    from naiauto.core.settings.schema import AppSettings

    settings = AppSettings()
    settings.compiler.default_target = "illustrious"
    settings.compiler.target_presets_dir = str(tmp_path)
    restored = AppSettings.model_validate(json.loads(settings.model_dump_json()))
    assert restored.compiler.default_target == "illustrious"
    assert restored.compiler.target_presets_dir == str(tmp_path)


def test_old_settings_without_target_still_load():
    """기존 설정 파일(타깃 필드 없음)이 그대로 열려야 한다 — 마이그레이션 불필요."""
    from naiauto.core.settings.schema import AppSettings

    settings = AppSettings.model_validate({"compiler": {"default_mode": "tag"}})
    assert settings.compiler.default_mode == "tag"
    assert settings.compiler.default_target == "novelai"
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_settings_compiler.py -q`
Expected: FAIL — `AttributeError: 'CompilerSettings' object has no attribute 'default_target'`

- [ ] **Step 3: `CompilerSettings`에 필드를 추가한다**

`src/naiauto/core/settings/schema.py`의 `CompilerSettings` 클래스에서 `relationship_style: str = "natural"` 줄 **뒤**에 다음을 넣는다:

```python
    #: 출력 대상 프리셋 id. "novelai"(기본) 또는 로컬 프리셋 id.
    default_target: str = "novelai"
    #: 사용자 타깃 프리셋 + loras.json이 든 폴더. 빈 값이면 내장 프리셋만 쓴다.
    target_presets_dir: str = ""
```

- [ ] **Step 4: 테스트가 통과하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_settings_compiler.py -q`
Expected: PASS

- [ ] **Step 5: 커밋한다**

```bash
git add src/naiauto/core/settings/schema.py tests/test_settings_compiler.py
git commit -m "$(cat <<'EOF'
feat(settings): 컴파일러 출력 타깃 설정 추가

default_target 기본값이 novelai라 기존 설정 파일은 마이그레이션 없이
그대로 열린다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 11: 시스템 프롬프트 중립화

**Files:**
- Modify: `src/naiauto/core/prompt/templates/system_prompt.md`

- [ ] **Step 1: 첫 줄을 바꾼다**

`src/naiauto/core/prompt/templates/system_prompt.md`의 첫 줄

```
You are a NovelAI V5 prompt analysis assistant.
```

을 다음으로 교체한다:

```
You are an image prompt analysis assistant.
```

같은 파일에서 다음 줄

```
- Do not generate NovelAI API requests, API payloads, or parameter values.
```

을 다음으로 교체한다:

```
- Do not generate API requests, payloads, or generation parameter values.
```

**나머지 규칙은 건드리지 않는다.** 씬 이해 규칙(Danbooru 태그, subjects, position_hint, relationships)은 출력 대상과 무관하다.

- [ ] **Step 2: 회귀가 없는지 확인한다**

Run: `uv run --extra dev pytest tests/test_parser.py tests/test_compiler.py -q`
Expected: PASS

- [ ] **Step 3: 커밋한다**

```bash
git add src/naiauto/core/prompt/templates/system_prompt.md
git commit -m "$(cat <<'EOF'
docs(prompt): 시스템 프롬프트에서 NovelAI 고유 표현을 걷어낸다

씬 이해 단계는 출력 대상과 무관하므로 나머지 규칙은 그대로 둔다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 12: i18n 키 추가 (4개 언어)

**Files:**
- Modify: `src/naiauto/resources/languages/ko.json`
- Modify: `src/naiauto/resources/languages/en.json`
- Modify: `src/naiauto/resources/languages/ja.json`
- Modify: `src/naiauto/resources/languages/zh.json`
- Modify: `tests/test_compiler_dialog.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_compiler_dialog.py` 상단의 `NEW_COMPILER_KEYS` 튜플을 다음으로 교체한다:

```python
#: Task 11이 4개 언어 파일에 추가해야 하는 compiler 섹션 키.
NEW_COMPILER_KEYS = (
    "err_connection",
    "err_timeout",
    "err_auth",
    "err_parse",
    "err_empty",
    "result_relationship_row",
    "recent_inputs",
    "recent_placeholder",
    # 출력 타깃 (로컬 SDXL)
    "target",
    "target_novelai",
    "tab_prompt",
    "tab_couple_mask",
    "tab_regional_json",
    "copy",
    "copied",
    "local_hint",
    "couple_mask_hint",
    "lora",
    "lora_none",
    "lora_weight",
)
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_compiler_dialog.py::test_compiler_error_keys_in_all_languages -q`
Expected: FAIL — `missing compiler keys ['copied', 'copy', 'couple_mask_hint', ...]`

- [ ] **Step 3: 한국어 키를 넣는다**

`src/naiauto/resources/languages/ko.json`의 `"compiler"` 객체 안, 마지막 키 뒤에 쉼표를 붙이고 다음을 넣는다:

```json
      "target": "출력 대상",
      "target_novelai": "NovelAI V5",
      "tab_prompt": "프롬프트",
      "tab_couple_mask": "COUPLE MASK",
      "tab_regional_json": "영역 JSON",
      "copy": "복사",
      "copied": "복사했습니다.",
      "local_hint": "캐릭터 프롬프트는 본문에 합쳐집니다.",
      "couple_mask_hint": "ComfyUI 확장 comfyui-prompt-control이 필요합니다.",
      "lora": "LoRA",
      "lora_none": "없음",
      "lora_weight": "가중치"
```

- [ ] **Step 4: 영어 키를 넣는다**

`src/naiauto/resources/languages/en.json`의 `"compiler"` 객체 안에 같은 방식으로 넣는다:

```json
      "target": "Output target",
      "target_novelai": "NovelAI V5",
      "tab_prompt": "Prompt",
      "tab_couple_mask": "COUPLE MASK",
      "tab_regional_json": "Region JSON",
      "copy": "Copy",
      "copied": "Copied.",
      "local_hint": "Character prompts are merged into the main prompt.",
      "couple_mask_hint": "Requires the ComfyUI extension comfyui-prompt-control.",
      "lora": "LoRA",
      "lora_none": "None",
      "lora_weight": "Weight"
```

- [ ] **Step 5: 일본어 키를 넣는다**

`src/naiauto/resources/languages/ja.json`의 `"compiler"` 객체 안에:

```json
      "target": "出力ターゲット",
      "target_novelai": "NovelAI V5",
      "tab_prompt": "プロンプト",
      "tab_couple_mask": "COUPLE MASK",
      "tab_regional_json": "領域 JSON",
      "copy": "コピー",
      "copied": "コピーしました。",
      "local_hint": "キャラクタープロンプトは本文に統合されます。",
      "couple_mask_hint": "ComfyUI 拡張 comfyui-prompt-control が必要です。",
      "lora": "LoRA",
      "lora_none": "なし",
      "lora_weight": "重み"
```

- [ ] **Step 6: 중국어 키를 넣는다**

`src/naiauto/resources/languages/zh.json`의 `"compiler"` 객체 안에:

```json
      "target": "输出目标",
      "target_novelai": "NovelAI V5",
      "tab_prompt": "提示词",
      "tab_couple_mask": "COUPLE MASK",
      "tab_regional_json": "区域 JSON",
      "copy": "复制",
      "copied": "已复制。",
      "local_hint": "角色提示词会合并到正文中。",
      "couple_mask_hint": "需要 ComfyUI 扩展 comfyui-prompt-control。",
      "lora": "LoRA",
      "lora_none": "无",
      "lora_weight": "权重"
```

- [ ] **Step 7: JSON이 유효하고 테스트가 통과하는지 확인한다**

```bash
uv run --extra dev python -c "
import json, pathlib
for p in sorted(pathlib.Path('src/naiauto/resources/languages').glob('*.json')):
    json.loads(p.read_text(encoding='utf-8'))
    print(p.name, 'ok')
"
uv run --extra dev pytest tests/test_compiler_dialog.py -q
```
Expected: 4개 파일 모두 `ok`, 테스트 PASS

- [ ] **Step 8: 커밋한다**

```bash
git add src/naiauto/resources/languages tests/test_compiler_dialog.py
git commit -m "$(cat <<'EOF'
feat(i18n): 출력 타깃·LoRA UI 문자열 4개 언어 추가

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 13: 다이얼로그 타깃 콤보와 결과 3탭

**Files:**
- Modify: `src/naiauto/ui/prompt_compiler_dialog.py`
- Modify: `tests/test_compiler_dialog.py`

지금 다이얼로그의 결과 영역은 `QSplitter[QTextBrowser | (라벨 + QPlainTextEdit)]` 구조다. 오른쪽 패널의 `_final_edit` 하나를 **`QTabWidget` 3탭**으로 바꾼다. 첫 탭이 기존 `_final_edit`을 그대로 담으므로 `_on_apply`는 손대지 않아도 된다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_compiler_dialog.py` 맨 끝에 다음을 덧붙인다:

```python
# --- 출력 타깃 -------------------------------------------------------------


def _dialog(tmp_path):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.prompt.history import PromptInputHistory
    from naiauto.core.settings.schema import AppSettings

    return PromptCompilerDialog(
        I18nManager(),
        AppSettings(),
        history=PromptInputHistory(path=tmp_path / "history.json"),
    )


def _local_compiled(target="illustrious"):
    from naiauto.core.prompt.schema import (
        CharacterPrompt,
        CompiledPrompt,
        ScenePrompt,
        TagRef,
    )

    return CompiledPrompt(
        base_prompt="masterpiece, 2girls, rain",
        negative_prompt="lowres",
        scene=ScenePrompt(tags=(TagRef("rain"),), subjects=("girl", "girl")),
        characters=(
            CharacterPrompt(id="c1", tags=(TagRef("silver_hair"),), center_x=0.3, center_y=0.5),
            CharacterPrompt(id="c2", tags=(TagRef("black_hair"),), center_x=0.7, center_y=0.5),
        ),
        relationships=(),
        mode="hybrid",
        warnings=(),
        unresolved=(),
        target=target,
    )


def test_target_combo_lists_novelai_and_builtin_presets(qapp, tmp_path):
    dialog = _dialog(tmp_path)
    values = [dialog.target_combo.itemData(i) for i in range(dialog.target_combo.count())]
    assert values[0] == "novelai"
    assert "illustrious" in values
    dialog.close()


def test_target_combo_defaults_from_settings(qapp, tmp_path):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.prompt.history import PromptInputHistory
    from naiauto.core.settings.schema import AppSettings

    settings = AppSettings()
    settings.compiler.default_target = "illustrious"
    dialog = PromptCompilerDialog(
        I18nManager(),
        settings,
        history=PromptInputHistory(path=tmp_path / "h.json"),
    )
    assert dialog.target_combo.currentData() == "illustrious"
    dialog.close()


def test_novelai_target_hides_local_tabs(qapp, tmp_path):
    dialog = _dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("novelai"))
    assert dialog._result_tabs.count() == 1
    dialog.close()


def test_local_target_shows_three_result_tabs(qapp, tmp_path):
    dialog = _dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("illustrious"))
    assert dialog._result_tabs.count() == 3
    dialog.close()


def test_local_target_renders_couple_mask_and_json(qapp, tmp_path):
    import json

    dialog = _dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("illustrious"))
    dialog._compiled = _local_compiled()
    dialog._render_preview(dialog._compiled)
    assert "COUPLE MASK(0 0.5, 0 1)" in dialog._couple_edit.toPlainText()
    data = json.loads(dialog._json_edit.toPlainText())
    assert [r["id"] for r in data["regions"]] == ["c1", "c2"]
    dialog.close()


def test_novelai_target_leaves_local_editors_empty(qapp, tmp_path):
    dialog = _dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("novelai"))
    dialog._compiled = _local_compiled(target="novelai")
    dialog._render_preview(dialog._compiled)
    assert dialog._couple_edit.toPlainText() == ""
    assert dialog._json_edit.toPlainText() == ""
    dialog.close()


def test_local_target_apply_sends_no_characters(qapp, tmp_path):
    received = []
    dialog = _dialog(tmp_path)
    dialog.applied.connect(received.append)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("illustrious"))
    dialog._compiled = _local_compiled()
    dialog._render_preview(dialog._compiled)
    dialog._on_apply("apply")
    assert received[0].characters == ()
    assert received[0].prompt == "masterpiece, 2girls, rain"


def test_novelai_target_apply_still_sends_characters(qapp, tmp_path):
    received = []
    dialog = _dialog(tmp_path)
    dialog.applied.connect(received.append)
    dialog._compiled = _local_compiled(target="novelai")
    dialog._render_preview(dialog._compiled)
    dialog._on_apply("apply")
    assert len(received[0].characters) == 2
    dialog.close()
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_compiler_dialog.py -q`
Expected: FAIL — `AttributeError: 'PromptCompilerDialog' object has no attribute 'target_combo'`

- [ ] **Step 3: import와 상태를 추가한다**

`src/naiauto/ui/prompt_compiler_dialog.py`의 `from naiauto.core.prompt.schema import DEFAULT_MODE, MODE_TAGS, CompiledPrompt` 줄 **뒤**에 다음을 넣는다:

```python
from naiauto.core.prompt.emitters import emit_couple_mask, emit_regional_json
from naiauto.core.prompt.targets import NOVELAI_TARGET_ID, find_target
```

파일 상단 import 블록에 `import json`이 없으면 `import logging` 줄 **앞**에 추가한다.

`_ConvertInputs` dataclass의 `mode: str` 줄 **뒤**에 다음을 넣는다:

```python
    target: str = "novelai"
```

- [ ] **Step 4: 타깃 콤보를 컨트롤 행에 넣는다**

`_build_ui`의 `control_row.addWidget(self.mode_combo)` 줄 **뒤**에 다음을 넣는다:

```python
        self._target_label = QLabel()
        control_row.addWidget(self._target_label)
        self.target_combo = QComboBox()
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        control_row.addWidget(self.target_combo)
```

- [ ] **Step 5: 결과 오른쪽 패널을 3탭으로 바꾼다**

`_build_ui`에서 다음 세 줄

```python
        self._final_edit = QPlainTextEdit()
        right_layout.addWidget(self._final_edit)
        self._result_splitter.addWidget(right_panel)
```

을 다음으로 교체한다:

```python
        # 결과 탭: 프롬프트(기존 편집기) | COUPLE MASK | 영역 JSON.
        # 첫 탭이 기존 _final_edit을 그대로 담으므로 Apply 경로는 바뀌지 않는다.
        self._result_tabs = QTabWidget()
        self._final_edit = QPlainTextEdit()
        self._result_tabs.addTab(self._final_edit, "")

        self._couple_page = QWidget()
        couple_layout = QVBoxLayout(self._couple_page)
        self._couple_hint_label = QLabel()
        self._couple_hint_label.setWordWrap(True)
        couple_layout.addWidget(self._couple_hint_label)
        self._couple_edit = QPlainTextEdit()
        self._couple_edit.setReadOnly(True)
        couple_layout.addWidget(self._couple_edit)
        self._couple_copy_button = QPushButton()
        self._couple_copy_button.clicked.connect(
            lambda: self._copy_to_clipboard(self._couple_edit.toPlainText())
        )
        couple_layout.addWidget(self._couple_copy_button)

        self._json_page = QWidget()
        json_layout = QVBoxLayout(self._json_page)
        self._json_edit = QPlainTextEdit()
        self._json_edit.setReadOnly(True)
        json_layout.addWidget(self._json_edit)
        self._json_copy_button = QPushButton()
        self._json_copy_button.clicked.connect(
            lambda: self._copy_to_clipboard(self._json_edit.toPlainText())
        )
        json_layout.addWidget(self._json_copy_button)

        self._local_hint_label = QLabel()
        self._local_hint_label.setWordWrap(True)
        right_layout.addWidget(self._result_tabs)
        right_layout.addWidget(self._local_hint_label)
        self._result_splitter.addWidget(right_panel)
```

`QTabWidget`은 이미 import되어 있다 (입력 탭에서 쓴다). `QPushButton`, `QLabel`, `QWidget`, `QVBoxLayout`도 마찬가지다.

- [ ] **Step 6: 타깃 전환 핸들러와 클립보드 헬퍼를 추가한다**

`_apply_default_mode` 메서드 **뒤**에 다음을 넣는다:

```python
    def _apply_default_target(self) -> None:
        """설정의 default_target으로 콤보를 맞춘다 (없는 id면 novelai)."""
        default = getattr(self._settings.compiler, "default_target", NOVELAI_TARGET_ID)
        index = self.target_combo.findData(default)
        self.target_combo.setCurrentIndex(index if index >= 0 else 0)
        self._on_target_changed()

    def _target(self) -> str:
        data = self.target_combo.currentData()
        return str(data) if data else NOVELAI_TARGET_ID

    def _is_local_target(self) -> bool:
        return self._target() != NOVELAI_TARGET_ID

    def _on_target_changed(self, _index: int = 0) -> None:
        """로컬 타깃일 때만 COUPLE MASK/영역 JSON 탭과 안내를 보인다."""
        local = self._is_local_target()
        if local:
            if self._result_tabs.count() == 1:
                tr = self._i18n.get_text
                self._result_tabs.addTab(self._couple_page, tr("compiler.tab_couple_mask"))
                self._result_tabs.addTab(self._json_page, tr("compiler.tab_regional_json"))
        else:
            while self._result_tabs.count() > 1:
                self._result_tabs.removeTab(1)
            self._couple_edit.clear()
            self._json_edit.clear()
        self._local_hint_label.setVisible(local)
        # 캐릭터별 LoRA 선택은 로컬 타깃 + 레지스트리가 있을 때만 (Task 14).
        self._update_lora_visibility()

    def _copy_to_clipboard(self, text: str) -> None:
        """텍스트를 클립보드에 넣고 상태줄에 알린다."""
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._status_label.setText(self._i18n.get_text("compiler.copied"))

    def _update_lora_visibility(self) -> None:
        """Task 14에서 실제 UI를 붙인다 — 지금은 자리만 잡는다."""
        return
```

`QApplication`을 import해야 한다. 파일 상단 `from PySide6.QtWidgets import (` 블록의 알파벳 순서에 맞게 `QApplication,`을 추가한다.

- [ ] **Step 7: `__init__`에서 기본 타깃을 적용한다**

`__init__`의 `self._apply_default_mode()` 줄 **뒤**에 다음을 넣는다:

```python
        self._apply_default_target()
```

- [ ] **Step 8: `retranslate`가 타깃 콤보를 채우게 한다**

`retranslate`의 `self.convert_button.setText(tr("compiler.convert"))` 줄 **앞**에 다음을 넣는다:

```python
        self._target_label.setText(tr("compiler.target"))
        current_target = self.target_combo.currentData()
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for preset in self._compiler.target_presets:
            label = tr("compiler.target_novelai") if preset.id == NOVELAI_TARGET_ID else preset.name
            self.target_combo.addItem(label, preset.id)
        target_index = self.target_combo.findData(current_target)
        self.target_combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        self.target_combo.blockSignals(False)
        self._result_tabs.setTabText(0, tr("compiler.tab_prompt"))
        if self._result_tabs.count() == 3:
            self._result_tabs.setTabText(1, tr("compiler.tab_couple_mask"))
            self._result_tabs.setTabText(2, tr("compiler.tab_regional_json"))
        self._couple_hint_label.setText(tr("compiler.couple_mask_hint"))
        self._local_hint_label.setText(tr("compiler.local_hint"))
        self._couple_copy_button.setText(tr("compiler.copy"))
        self._json_copy_button.setText(tr("compiler.copy"))
```

- [ ] **Step 9: 변환 입력과 워커에 타깃을 흘려보낸다**

`_run_conversion`에서 `mode=self._mode(),` 줄 **뒤**에 다음을 넣는다:

```python
                target=self._target(),
```

`_worker_convert`의 두 호출을 각각 다음으로 바꾼다:

```python
                compiled = self._compiler.modify(
                    inputs.existing,
                    inputs.instruction,
                    mode=inputs.mode,
                    target=inputs.target,
                    character_loras=self._character_loras(),
                    resolution=self._resolution(),
                )
            else:
                compiled = self._compiler.compile(
                    inputs.text,
                    mode=inputs.mode,
                    target=inputs.target,
                    character_loras=self._character_loras(),
                    resolution=self._resolution(),
                )
```

`_target` 메서드 **뒤**에 다음 두 헬퍼를 넣는다:

```python
    def _resolution(self) -> tuple[int, int] | None:
        """couple_mask의 MASK_SIZE에 쓸 현재 생성 해상도."""
        generation = getattr(self._settings, "generation", None)
        width = int(getattr(generation, "width", 0) or 0)
        height = int(getattr(generation, "height", 0) or 0)
        return (width, height) if width > 0 and height > 0 else None

    def _character_loras(self) -> dict:
        """캐릭터 id → LoraEntry. Task 14에서 UI 선택으로 채운다."""
        return {}
```

**주의:** `_character_loras`는 GUI 스레드가 아니라 워커에서 호출된다. Task 14에서 위젯을 직접 읽지 말고, 선택 결과를 `_ConvertInputs`에 스냅숏으로 담도록 고친다.

- [ ] **Step 10: 미리보기가 로컬 출력을 채우게 한다**

`_render_preview`의 마지막 세 줄

```python
        self._preview_browser.setPlainText("\n".join(lines).strip("\n"))
        self._final_edit.setPlainText(compiled.base_prompt)
        self._negative_edit.setPlainText(compiled.negative_prompt)
```

을 다음으로 교체한다:

```python
        self._preview_browser.setPlainText("\n".join(lines).strip("\n"))
        self._final_edit.setPlainText(compiled.base_prompt)
        self._negative_edit.setPlainText(compiled.negative_prompt)
        self._render_local_outputs(compiled)

    def _render_local_outputs(self, compiled: CompiledPrompt) -> None:
        """로컬 타깃일 때만 COUPLE MASK/영역 JSON 탭을 채운다."""
        if compiled.target == NOVELAI_TARGET_ID:
            self._couple_edit.clear()
            self._json_edit.clear()
            return
        preset = find_target(self._compiler.target_presets, compiled.target)
        loras = self._character_loras()
        couple, _ = emit_couple_mask(
            compiled, preset, loras, resolution=self._resolution()
        )
        self._couple_edit.setPlainText(couple)
        self._json_edit.setPlainText(
            json.dumps(
                emit_regional_json(compiled, preset, loras), ensure_ascii=False, indent=2
            )
        )
```

- [ ] **Step 11: 테스트가 통과하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_compiler_dialog.py tests/test_mainwindow_compiler.py -q`
Expected: PASS

- [ ] **Step 12: 커밋한다**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/ui/prompt_compiler_dialog.py tests/test_compiler_dialog.py
git commit -m "$(cat <<'EOF'
feat(ui): 컴파일러 다이얼로그에 출력 타깃 콤보와 결과 3탭

로컬 타깃을 고르면 COUPLE MASK·영역 JSON 탭이 붙고, NovelAI로 돌아가면
사라지며 편집기도 비운다. 첫 탭이 기존 최종 프롬프트 편집기를 그대로 담아
Apply 경로는 바뀌지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 14: 캐릭터별 LoRA 선택 UI

**Files:**
- Modify: `src/naiauto/ui/prompt_compiler_dialog.py`
- Modify: `tests/test_compiler_dialog.py`

LoRA 선택은 컴파일 **결과**의 캐릭터 목록에 붙는다. 즉 변환이 끝난 뒤에 행이 생기고, 다시 변환하면 캐릭터 id 기준으로 선택을 유지한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_compiler_dialog.py` 맨 끝에 다음을 덧붙인다:

```python
# --- 캐릭터별 LoRA ---------------------------------------------------------


def _dialog_with_loras(tmp_path):
    import json as _json

    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.prompt.history import PromptInputHistory
    from naiauto.core.settings.schema import AppSettings

    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    (presets_dir / "loras.json").write_text(
        _json.dumps(
            {
                "kafka": {
                    "file": "kafka.safetensors",
                    "weight": 0.8,
                    "triggers": ["kafka"],
                }
            }
        ),
        encoding="utf-8",
    )
    settings = AppSettings()
    settings.compiler.target_presets_dir = str(presets_dir)
    settings.compiler.default_target = "illustrious"
    return PromptCompilerDialog(
        I18nManager(), settings, history=PromptInputHistory(path=tmp_path / "h.json")
    )


def test_lora_rows_hidden_without_registry(qapp, tmp_path):
    dialog = _dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("illustrious"))
    dialog._render_preview(_local_compiled())
    assert not dialog._lora_group.isVisible()
    dialog.close()


def test_lora_rows_appear_per_character(qapp, tmp_path):
    dialog = _dialog_with_loras(tmp_path)
    dialog._render_preview(_local_compiled())
    assert set(dialog._lora_combos) == {"c1", "c2"}
    assert dialog._lora_combos["c1"].itemData(0) is None  # "없음"
    assert dialog._lora_combos["c1"].itemData(1) == "kafka"
    dialog.close()


def test_lora_rows_hidden_on_novelai_target(qapp, tmp_path):
    dialog = _dialog_with_loras(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("novelai"))
    dialog._render_preview(_local_compiled(target="novelai"))
    assert not dialog._lora_group.isVisible()
    dialog.close()


def test_lora_selection_survives_recompile(qapp, tmp_path):
    dialog = _dialog_with_loras(tmp_path)
    dialog._render_preview(_local_compiled())
    dialog._lora_combos["c1"].setCurrentIndex(1)
    dialog._lora_weights["c1"].setValue(0.5)
    dialog._render_preview(_local_compiled())  # 다시 변환한 셈
    assert dialog._lora_combos["c1"].currentData() == "kafka"
    assert dialog._lora_weights["c1"].value() == 0.5
    dialog.close()


def test_character_loras_snapshot_reflects_selection(qapp, tmp_path):
    dialog = _dialog_with_loras(tmp_path)
    dialog._render_preview(_local_compiled())
    dialog._lora_combos["c2"].setCurrentIndex(1)
    dialog._lora_weights["c2"].setValue(0.6)
    loras = dialog._character_loras()
    assert set(loras) == {"c2"}
    assert loras["c2"].file == "kafka.safetensors"
    assert loras["c2"].weight == 0.6
    dialog.close()


def test_lora_appears_in_couple_mask_output(qapp, tmp_path):
    dialog = _dialog_with_loras(tmp_path)
    dialog._render_preview(_local_compiled())
    dialog._lora_combos["c1"].setCurrentIndex(1)
    dialog._render_preview(_local_compiled())
    assert "<lora:kafka:0.8>" in dialog._couple_edit.toPlainText()
    dialog.close()
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_compiler_dialog.py -q`
Expected: FAIL — `AttributeError: 'PromptCompilerDialog' object has no attribute '_lora_group'`

- [ ] **Step 3: LoRA 그룹 위젯을 만든다**

`src/naiauto/ui/prompt_compiler_dialog.py`의 `_build_ui`에서 `self._negative_label = QLabel()` 줄 **앞**에 다음을 넣는다:

```python
        # 캐릭터별 LoRA — 로컬 타깃 + loras.json이 있을 때만 보인다.
        self._lora_group = QGroupBox()
        self._lora_layout = QVBoxLayout(self._lora_group)
        self._lora_group.setVisible(False)
        layout.addWidget(self._lora_group)
```

`QGroupBox`, `QDoubleSpinBox`를 `from PySide6.QtWidgets import (` 블록의 알파벳 순서에 맞게 추가한다.

`__init__`의 `self._history_restoring = False` 줄 **뒤**에 다음을 넣는다:

```python
        #: 캐릭터 id → LoRA 선택 콤보 / 가중치 스핀박스 (로컬 타깃에서만 만든다).
        self._lora_combos: dict[str, QComboBox] = {}
        self._lora_weights: dict[str, QDoubleSpinBox] = {}
```

- [ ] **Step 4: 행 생성·선택 유지 로직을 구현한다**

Task 13에서 자리만 잡아 둔 `_update_lora_visibility`를 다음으로 교체하고, 바로 뒤에 나머지 메서드를 넣는다:

```python
    def _update_lora_visibility(self) -> None:
        """로컬 타깃 + 레지스트리가 있을 때만 LoRA 그룹을 보인다."""
        has_registry = bool(self._compiler.lora_registry)
        self._lora_group.setVisible(self._is_local_target() and has_registry)

    def _rebuild_lora_rows(self, compiled: CompiledPrompt) -> None:
        """컴파일 결과의 캐릭터마다 LoRA 행을 만든다 (id 기준으로 선택 유지)."""
        tr = self._i18n.get_text
        self._lora_group.setTitle(tr("compiler.lora"))
        previous = {
            char_id: (combo.currentData(), self._lora_weights[char_id].value())
            for char_id, combo in self._lora_combos.items()
        }
        while self._lora_layout.count():
            item = self._lora_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._lora_combos.clear()
        self._lora_weights.clear()

        if compiled.target == NOVELAI_TARGET_ID or not self._compiler.lora_registry:
            self._update_lora_visibility()
            return

        for char in compiled.characters:
            row_widget = QWidget()
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(QLabel(char.id))
            combo = QComboBox()
            combo.addItem(tr("compiler.lora_none"), None)
            for entry_id in sorted(self._compiler.lora_registry):
                combo.addItem(entry_id, entry_id)
            row.addWidget(combo, stretch=1)
            row.addWidget(QLabel(tr("compiler.lora_weight")))
            weight = QDoubleSpinBox()
            weight.setRange(0.0, 2.0)
            weight.setSingleStep(0.05)
            weight.setDecimals(2)
            row.addWidget(weight)

            saved_id, saved_weight = previous.get(char.id, (None, None))
            index = combo.findData(saved_id) if saved_id else 0
            combo.setCurrentIndex(index if index >= 0 else 0)
            if saved_weight is not None:
                weight.setValue(saved_weight)
            elif saved_id:
                weight.setValue(self._compiler.lora_registry[saved_id].weight)
            else:
                weight.setValue(1.0)
            combo.currentIndexChanged.connect(
                lambda _i, cid=char.id: self._on_lora_selected(cid)
            )

            self._lora_layout.addWidget(row_widget)
            self._lora_combos[char.id] = combo
            self._lora_weights[char.id] = weight
        self._update_lora_visibility()

    def _on_lora_selected(self, char_id: str) -> None:
        """LoRA를 고르면 가중치를 레지스트리 기본값으로 맞춘다."""
        entry_id = self._lora_combos[char_id].currentData()
        entry = self._compiler.lora_registry.get(entry_id) if entry_id else None
        self._lora_weights[char_id].setValue(entry.weight if entry else 1.0)
```

`QHBoxLayout`은 이미 import되어 있다.

- [ ] **Step 5: `_character_loras`가 실제 선택을 읽게 한다**

Task 13에서 넣은 `_character_loras` 스텁을 다음으로 교체한다:

```python
    def _character_loras(self) -> dict:
        """캐릭터 id → LoraEntry (다이얼로그 선택 스냅숏).

        레지스트리에 없는 id는 조용히 버린다 (레지스트리 파일이 바뀐 경우).
        """
        from dataclasses import replace as _replace

        selected: dict = {}
        for char_id, combo in self._lora_combos.items():
            entry_id = combo.currentData()
            if not entry_id:
                continue
            entry = self._compiler.lora_registry.get(entry_id)
            if entry is None:
                continue
            selected[char_id] = _replace(entry, weight=self._lora_weights[char_id].value())
        return selected
```

- [ ] **Step 6: 미리보기에서 행을 다시 만든다**

`_render_preview`의 `self._render_local_outputs(compiled)` 줄 **앞**에 다음을 넣는다:

```python
        self._rebuild_lora_rows(compiled)
```

`_rebuild_lora_rows`가 `_render_local_outputs`보다 먼저 돌아야 `_character_loras()`가 최신 선택을 돌려준다.

- [ ] **Step 7: 워커 스레드 안전성을 확보한다**

`_character_loras()`는 위젯을 읽으므로 **워커 스레드에서 부르면 안 된다**. Task 13의 `_worker_convert`가 이를 호출하고 있으니 스냅숏 방식으로 고친다.

`_ConvertInputs`의 `target: str = "novelai"` 줄 **뒤**에 다음을 넣는다:

```python
    character_loras: dict = field(default_factory=dict)
    resolution: tuple[int, int] | None = None
```

파일 상단 `from dataclasses import dataclass` 줄을 다음으로 바꾼다:

```python
from dataclasses import dataclass, field
```

`_run_conversion`에서 `target=self._target(),` 줄 **뒤**에 다음을 넣는다:

```python
                character_loras=self._character_loras(),
                resolution=self._resolution(),
```

`_worker_convert`의 두 호출에서 `self._character_loras()` / `self._resolution()`을 각각 `inputs.character_loras` / `inputs.resolution`으로 바꾼다.

- [ ] **Step 8: 테스트가 통과하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_compiler_dialog.py -q`
Expected: PASS

- [ ] **Step 9: 커밋한다**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/ui/prompt_compiler_dialog.py tests/test_compiler_dialog.py
git commit -m "$(cat <<'EOF'
feat(ui): 캐릭터별 LoRA 선택

loras.json이 있을 때만 로컬 타깃에서 행이 생긴다. 다시 변환해도 캐릭터 id
기준으로 선택이 유지된다. 위젯 읽기는 GUI 스레드에서만 하고 워커에는
스냅숏으로 넘긴다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 15: 히스토리에 타깃 저장·복원

**Files:**
- Modify: `src/naiauto/core/prompt/history.py`
- Modify: `src/naiauto/ui/prompt_compiler_dialog.py`
- Modify: `tests/test_history.py`
- Modify: `tests/test_compiler_dialog.py`

LoRA 선택은 히스토리에 넣지 않는다 — 레지스트리가 바뀌면 복원이 어긋나고, 선택은 컴파일 결과에 붙는 것이라 입력 스냅숏의 성격이 아니다. **타깃만** 저장한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_history.py` 맨 끝에 다음을 덧붙인다:

```python
def test_entry_stores_target(tmp_path):
    from naiauto.core.prompt.history import InputHistoryEntry, PromptInputHistory

    history = PromptInputHistory(path=tmp_path / "h.json")
    history.add(InputHistoryEntry(tab="create", text="x", mode="hybrid", target="illustrious"))
    reloaded = PromptInputHistory(path=tmp_path / "h.json")
    reloaded.load()
    assert reloaded.recent()[0].target == "illustrious"


def test_entry_target_defaults_to_novelai(tmp_path):
    from naiauto.core.prompt.history import InputHistoryEntry

    assert InputHistoryEntry(tab="create", text="x").target == "novelai"


def test_old_history_file_without_target_loads(tmp_path):
    import json

    from naiauto.core.prompt.history import PromptInputHistory

    path = tmp_path / "h.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": [{"tab": "create", "text": "x", "mode": "hybrid", "ts": 1.0}],
            }
        ),
        encoding="utf-8",
    )
    history = PromptInputHistory(path=path)
    history.load()
    assert history.recent()[0].target == "novelai"


def test_same_text_different_target_are_separate_entries(tmp_path):
    from naiauto.core.prompt.history import InputHistoryEntry, PromptInputHistory

    history = PromptInputHistory(path=tmp_path / "h.json")
    history.add(InputHistoryEntry(tab="create", text="x", target="novelai"))
    history.add(InputHistoryEntry(tab="create", text="x", target="illustrious"))
    assert len(history.recent()) == 2
```

`tests/test_compiler_dialog.py` 맨 끝에도 다음을 덧붙인다:

```python
def test_history_restore_sets_target(qapp, tmp_path):
    from naiauto.core.prompt.history import InputHistoryEntry

    dialog = _dialog(tmp_path)
    dialog._history.add(
        InputHistoryEntry(tab="create", text="은발 소녀", mode="tag", target="illustrious")
    )
    dialog._refresh_history_combo()
    dialog._history_combo.setCurrentIndex(1)
    assert dialog.target_combo.currentData() == "illustrious"
    assert dialog.mode_combo.currentData() == "tag"
    dialog.close()
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_history.py tests/test_compiler_dialog.py -q`
Expected: FAIL — `TypeError: InputHistoryEntry.__init__() got an unexpected keyword argument 'target'`

- [ ] **Step 3: `InputHistoryEntry`에 필드를 추가한다**

`src/naiauto/core/prompt/history.py`의 `InputHistoryEntry`에서 `mode: str = "hybrid"` 줄 **뒤**에 다음을 넣는다:

```python
    target: str = "novelai"     # 출력 대상 프리셋 id
```

`PromptInputHistory._FIELDS`를 다음으로 교체한다:

```python
    _FIELDS = ("tab", "text", "existing_prompt", "instruction", "mode", "target")
```

`load`의 `InputHistoryEntry(` 생성자에서 `mode=str(item.get("mode", "hybrid")),` 줄 **뒤**에 다음을 넣는다:

```python
                        target=str(item.get("target", "novelai")),
```

- [ ] **Step 4: 다이얼로그가 타깃을 저장·복원하게 한다**

`src/naiauto/ui/prompt_compiler_dialog.py`의 `_to_history_entry`에서 `mode=inputs.mode,` 줄 **뒤**에 다음을 넣는다:

```python
            target=inputs.target,
```

`_on_history_selected` 마지막의 다음 세 줄

```python
        index = self.mode_combo.findData(entry.mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
```

을 다음으로 교체한다:

```python
        index = self.mode_combo.findData(entry.mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        target_index = self.target_combo.findData(entry.target)
        if target_index >= 0:
            self.target_combo.setCurrentIndex(target_index)
```

- [ ] **Step 5: 테스트가 통과하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_history.py tests/test_compiler_dialog.py -q`
Expected: PASS

- [ ] **Step 6: 커밋한다**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/core/prompt/history.py src/naiauto/ui/prompt_compiler_dialog.py tests/test_history.py tests/test_compiler_dialog.py
git commit -m "$(cat <<'EOF'
feat(prompt): 입력 히스토리에 출력 타깃 저장

같은 문장이라도 타깃이 다르면 별도 항목이다. 필드 기본값이 novelai라
기존 히스토리 파일은 그대로 열린다. LoRA 선택은 컴파일 결과에 붙는 것이라
입력 스냅숏에 넣지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 16: 옵션 페이지 "출력 타깃" 행

기존 `PromptAiPage`의 **Prompt Compiler 그룹**(`compiler_section` 아래 `compiler_form`)에 두 행을 더한다. 새 페이지는 만들지 않는다.

프리셋의 `quality_prefix`/`default_negative` 편집은 **이번 범위에서 뺀다** — 사용자 프리셋 파일을 앱이 써 넣는 경로를 만들면 내장/사용자 프리셋 병합 규칙과 얽히고, 편집 UI 하나를 위해 저장 로직이 통째로 필요해진다. 대신 **폴더 열기 + 로드 상태 표시**로 파일을 직접 고치게 한다. (스펙 §6.3의 "편집은 하지 않는다 — 폴더 열기 버튼만 둔다"와 같은 방침을 프리셋에도 적용한다.)

**Files:**
- Modify: `src/naiauto/ui/options_pages/prompt_ai_page.py`
- Modify: `src/naiauto/resources/languages/{ko,en,ja,zh}.json`
- Modify: `tests/test_prompt_ai_page.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_prompt_ai_page.py` 맨 끝에 다음을 덧붙인다. 파일 상단에 이미 `qapp` 픽스처와 `QT_QPA_PLATFORM=offscreen` 설정이 있으니 그대로 쓴다.

```python
# --- 출력 타깃 -------------------------------------------------------------


def test_target_combo_lists_novelai_and_presets(qapp):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.ui.options_pages.prompt_ai_page import PromptAiPage

    page = PromptAiPage(I18nManager())
    values = [page.target_combo.itemData(i) for i in range(page.target_combo.count())]
    assert values[0] == "novelai"
    assert "illustrious" in values


def test_target_round_trips_through_load_and_commit(qapp, tmp_path):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.settings.schema import AppSettings
    from naiauto.ui.options_pages.prompt_ai_page import PromptAiPage

    page = PromptAiPage(I18nManager())
    draft = AppSettings()
    draft.compiler.default_target = "illustrious"
    draft.compiler.target_presets_dir = str(tmp_path)
    page.load(draft)
    assert page.target_combo.currentData() == "illustrious"
    assert page.presets_dir_edit.text() == str(tmp_path)

    out = AppSettings()
    page.commit(out)
    assert out.compiler.default_target == "illustrious"
    assert out.compiler.target_presets_dir == str(tmp_path)


def test_unknown_default_target_falls_back_in_ui(qapp):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.settings.schema import AppSettings
    from naiauto.ui.options_pages.prompt_ai_page import PromptAiPage

    page = PromptAiPage(I18nManager())
    draft = AppSettings()
    draft.compiler.default_target = "no-such-target"
    page.load(draft)
    assert page.target_combo.currentData() == "novelai"


def test_lora_status_reports_registry_size(qapp, tmp_path):
    import json

    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.settings.schema import AppSettings
    from naiauto.ui.options_pages.prompt_ai_page import PromptAiPage

    (tmp_path / "loras.json").write_text(
        json.dumps({"kafka": {"file": "kafka.safetensors"}}), encoding="utf-8"
    )
    page = PromptAiPage(I18nManager())
    draft = AppSettings()
    draft.compiler.target_presets_dir = str(tmp_path)
    page.load(draft)
    assert "1" in page.lora_status_label.text()


def test_lora_status_when_registry_missing(qapp, tmp_path):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.settings.schema import AppSettings
    from naiauto.ui.options_pages.prompt_ai_page import PromptAiPage

    page = PromptAiPage(I18nManager())
    draft = AppSettings()
    draft.compiler.target_presets_dir = str(tmp_path)
    page.load(draft)
    assert page.lora_status_label.text() != ""
```

- [ ] **Step 2: 테스트가 실패하는지 확인한다**

Run: `uv run --extra dev pytest tests/test_prompt_ai_page.py -q`
Expected: FAIL — `AttributeError: 'PromptAiPage' object has no attribute 'target_combo'`

- [ ] **Step 3: 위젯을 추가한다**

`src/naiauto/ui/options_pages/prompt_ai_page.py`의 import 블록 끝에 다음을 넣는다:

```python
from naiauto.core.prompt.targets import (
    NOVELAI_TARGET_ID,
    load_lora_registry,
    load_target_presets,
)
```

`_build` 부분에서 `compiler_form.addRow(self.relationship_label, self.relationship_combo)` 줄 **뒤**, `root.addLayout(compiler_form)` 줄 **앞**에 다음을 넣는다:

```python
        # ── 출력 타깃 (로컬 SDXL) ──
        self.target_label = QLabel(self)
        self.target_combo = QComboBox(self)
        for preset in load_target_presets(None):
            self.target_combo.addItem(preset.name, preset.id)
        compiler_form.addRow(self.target_label, self.target_combo)

        self.presets_dir_label = QLabel(self)
        self.presets_dir_edit = QLineEdit(self)
        self.presets_dir_edit.textChanged.connect(self._refresh_target_sources)
        self.presets_dir_browse = QPushButton(self)
        self.presets_dir_browse.clicked.connect(self._browse_presets_dir)
        presets_row = QHBoxLayout()
        presets_row.addWidget(self.presets_dir_edit, 1)
        presets_row.addWidget(self.presets_dir_browse)
        compiler_form.addRow(self.presets_dir_label, presets_row)

        self.lora_status_label = QLabel(self)
        compiler_form.addRow(self.lora_status_label)
```

- [ ] **Step 4: 폴더 선택과 갱신 로직을 넣는다**

같은 파일의 `_browse_server` 메서드 **뒤**에 다음을 넣는다:

```python
    def _browse_presets_dir(self) -> None:
        """타깃 프리셋 + loras.json이 든 폴더를 고른다."""
        path = QFileDialog.getExistingDirectory(
            self, self._i18n.get_text("options.choose_folder"), self.presets_dir_edit.text()
        )
        if path:
            self.presets_dir_edit.setText(path)

    def _refresh_target_sources(self) -> None:
        """폴더가 바뀌면 타깃 콤보와 LoRA 상태 문구를 다시 만든다."""
        tr = self._i18n.get_text
        directory = self.presets_dir_edit.text().strip()
        current = self.target_combo.currentData()
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for preset in load_target_presets(directory):
            self.target_combo.addItem(preset.name, preset.id)
        index = self.target_combo.findData(current)
        self.target_combo.setCurrentIndex(index if index >= 0 else 0)
        self.target_combo.blockSignals(False)
        count = len(load_lora_registry(directory))
        self.lora_status_label.setText(
            tr("options.compiler_lora_loaded", count)
            if count
            else tr("options.compiler_lora_missing")
        )
```

- [ ] **Step 5: `load`/`commit`/`retranslate`를 잇는다**

`load`의 `self._select(self.relationship_combo, draft.compiler.relationship_style)` 줄 **뒤**에 다음을 넣는다:

```python
        self.presets_dir_edit.setText(draft.compiler.target_presets_dir)
        self._refresh_target_sources()
        index = self.target_combo.findData(draft.compiler.default_target)
        self.target_combo.setCurrentIndex(index if index >= 0 else 0)
```

`commit`의 `draft.compiler.relationship_style = self.relationship_combo.currentData()` 줄 **뒤**에 다음을 넣는다:

```python
        draft.compiler.target_presets_dir = self.presets_dir_edit.text().strip()
        draft.compiler.default_target = self.target_combo.currentData() or NOVELAI_TARGET_ID
```

`retranslate`의 마지막(`self.compiler_section.setText(...)` 계열이 끝나는 지점)에 다음을 넣는다:

```python
        self.target_label.setText(tr("options.compiler_target"))
        self.presets_dir_label.setText(tr("options.compiler_target_presets_dir"))
        self.presets_dir_browse.setText(tr("options.browse"))
        self._refresh_target_sources()
```

- [ ] **Step 6: 옵션 i18n 키를 4개 언어에 넣는다**

각 언어 파일의 `"options"` 객체 안, `"compiler_use_resolver"` 근처에 다음을 넣는다 (JSON 쉼표에 주의).

`ko.json`:
```json
      "compiler_target": "출력 대상",
      "compiler_target_presets_dir": "타깃 프리셋 폴더",
      "compiler_lora_loaded": "LoRA 레지스트리: {0}개",
      "compiler_lora_missing": "LoRA 레지스트리: loras.json 없음",
```

`en.json`:
```json
      "compiler_target": "Output target",
      "compiler_target_presets_dir": "Target preset folder",
      "compiler_lora_loaded": "LoRA registry: {0} entries",
      "compiler_lora_missing": "LoRA registry: loras.json not found",
```

`ja.json`:
```json
      "compiler_target": "出力ターゲット",
      "compiler_target_presets_dir": "ターゲットプリセットフォルダ",
      "compiler_lora_loaded": "LoRA レジストリ: {0} 件",
      "compiler_lora_missing": "LoRA レジストリ: loras.json がありません",
```

`zh.json`:
```json
      "compiler_target": "输出目标",
      "compiler_target_presets_dir": "目标预设文件夹",
      "compiler_lora_loaded": "LoRA 注册表：{0} 项",
      "compiler_lora_missing": "LoRA 注册表：未找到 loras.json",
```

`{0}` 자리 표시자 형식은 이 저장소의 `get_text(key, *args)` 규약과 같다 (`compiler.result_character_n` 참고). 실제 형식이 다르면 그 키의 값 형식을 그대로 따른다.

- [ ] **Step 7: 테스트가 통과하는지 확인한다**

```bash
uv run --extra dev python -c "
import json, pathlib
for p in sorted(pathlib.Path('src/naiauto/resources/languages').glob('*.json')):
    json.loads(p.read_text(encoding='utf-8')); print(p.name, 'ok')
"
uv run --extra dev pytest tests/test_prompt_ai_page.py tests/test_options_registry.py -q
```
Expected: PASS

- [ ] **Step 8: 커밋한다**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/ui/options_pages/prompt_ai_page.py src/naiauto/resources/languages tests/test_prompt_ai_page.py
git commit -m "$(cat <<'EOF'
feat(ui): 옵션에 기본 출력 타깃과 프리셋 폴더 설정

프리셋 내용 편집은 넣지 않는다 — 폴더를 열어 파일을 직접 고치게 하고,
앱은 로드 상태만 보여 준다. 저장 경로를 만들면 내장/사용자 병합 규칙과
얽힌다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 17: 문서

**Files:**
- Modify: `README.md`
- Modify: `MANUAL_KR.md`

- [ ] **Step 1: `README.md` 기능 목록에 한 줄을 더한다**

`README.md`의 기능 목록(불릿 리스트)에서 자연어 프롬프트 컴파일러를 설명하는 항목을 찾아 그 **바로 뒤**에 다음을 넣는다. 항목 형식(불릿 기호, 굵게 표기)은 주변 줄을 그대로 따라 쓴다.

```markdown
- **로컬 SDXL 출력** — 컴파일 결과를 NovelAI 형식 대신 Illustrious·NoobAI·Animagine 등 로컬 SDXL 모델용 단일 Positive/Negative로 뽑는다. ComfyUI 영역 분할용 `COUPLE MASK` 문자열과 좌표 JSON도 함께 준다.
```

- [ ] **Step 2: `MANUAL_KR.md`에 사용법 절을 넣는다**

`MANUAL_KR.md`에서 자연어 프롬프트 컴파일러를 설명하는 절을 찾아 그 **끝**에 다음을 덧붙인다. 제목 레벨(`##`/`###`)은 그 절과 같은 깊이로 맞춘다.

```markdown
### 로컬 SDXL/Anima로 뽑기

변환 창 위쪽 **출력 대상**을 `Illustrious / NoobAI`, `Animagine XL`,
`SDXL (generic)` 중에서 고르면 결과가 NovelAI 형식이 아니라 로컬 모델이 바로
먹는 형태로 나온다.

- 캐릭터별 프롬프트가 따로 나가지 않고 **본문 하나로 합쳐진다.** 로컬 SDXL에는
  캐릭터를 분리하는 기능이 없기 때문이다. 적용해도 캐릭터 프롬프트 탭은
  건드리지 않는다.
- 품질 태그(`masterpiece, best quality` 등)와 기본 네거티브가 자동으로 붙는다.
- 결과 오른쪽에 탭이 셋 생긴다.
  - **프롬프트** — 붙여넣어 바로 쓰는 단일 Positive. 아래 칸이 Negative다.
  - **COUPLE MASK** — 인물을 좌우로 나눠 그리는 ComfyUI용 문자열.
  - **영역 JSON** — 좌표를 0~1로 정규화한 구조화 데이터.

#### COUPLE MASK를 쓰려면

ComfyUI 확장 [`asagi4/comfyui-prompt-control`](https://github.com/asagi4/comfyui-prompt-control)이
필요하다. ComfyUI Manager에서 설치하거나 `custom_nodes` 폴더에 클론한 뒤,
`PC: Schedule Prompt`(`PCLazyTextEncode`) 노드에 이 탭의 문자열을 그대로 넣는다.

맨 앞의 `MASK_SIZE(가로, 세로)`는 지우지 말 것. 이 확장은 마스크 크기를
512×512로 가정하므로, SDXL 해상도에서 이 줄이 없으면 인물 영역이 어긋난다.

#### A1111 / Forge에서 쓰려면

**프롬프트** 탭 내용을 그대로 붙여넣으면 된다. 인물을 좌우로 나누고 싶다면
[Regional Prompter](https://github.com/hako-mikan/sd-webui-regional-prompter)를
설치하고, 이 앱이 뽑아 준 프롬프트를 다음처럼 손으로 나눈다.

```
masterpiece, best quality, 2girls, rain, night
ADDCOL 은발 캐릭터 태그
ADDCOL 흑발 캐릭터 태그
```

`ADDCOL`은 세로로 자른 열을 만든다. 이 앱은 `ADDCOL` 형식을 직접 뽑지 않는데,
Regional Prompter가 비율 분할만 지원해 임의 좌표를 표현할 수 없기 때문이다.

#### 캐릭터마다 다른 LoRA 쓰기

**옵션 → Prompt AI → 타깃 프리셋 폴더**를 지정하고, 그 폴더에 `loras.json`을
만든다.

```json
{
  "kafka": {
    "file": "kafka_illustrious.safetensors",
    "weight": 0.8,
    "triggers": ["kafka", "purple hair"]
  }
}
```

- `file` — LoRA 파일 이름. 프롬프트에는 확장자를 뗀 이름이 들어간다.
- `weight` — 기본 가중치. 변환 창에서 그때그때 바꿀 수 있다.
- `triggers` — 그 캐릭터 자리에 끼워 넣을 트리거 단어.

파일을 만들면 변환한 뒤 결과 아래에 캐릭터별 LoRA 드롭다운이 생긴다.
`<lora:...>` 태그는 프롬프트 맨 앞에 한 번만 들어가고, 트리거 단어는 해당
캐릭터 자리에 들어간다.

#### 나만의 타깃 프리셋 만들기

같은 폴더에 `<이름>.json`을 두면 목록에 추가된다. 내장 프리셋과 `id`가 같으면
내 것이 이긴다.

```json
{
  "id": "my_model",
  "name": "내 모델",
  "quality_prefix": ["masterpiece", "best quality"],
  "default_negative": ["lowres", "worst quality"],
  "flatten": "sequential",
  "natural_language": "drop",
  "underscore_to_space": true
}
```

- `flatten` — `sequential`(단일 프롬프트) 또는 `couple_mask`. 어느 쪽이든 탭
  셋은 다 나오고, 이 값은 **프롬프트** 탭에 무엇을 채울지만 정한다.
- `natural_language` — `drop`(태그만) 또는 `append`(자연어 문장도 붙임).
  애니 계열은 `drop`, 범용 SDXL은 `append`가 대체로 낫다.
- `underscore_to_space` — `silver_hair`를 `silver hair`로 바꾼다. Illustrious
  계열은 공백형을 학습해서 켜 두는 편이 맞다.
- `id`를 `novelai`로 쓰면 무시된다 (예약어).
```

- [ ] **Step 3: 전체 검증**

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```
Expected: 전부 통과

- [ ] **Step 4: 커밋한다**

```bash
git add README.md MANUAL_KR.md
git commit -m "$(cat <<'EOF'
docs: 로컬 SDXL 출력 사용법

COUPLE MASK를 쓰려면 comfyui-prompt-control이 필요하다는 것, MASK_SIZE를
지우면 안 되는 이유, A1111에서 Regional Prompter와 함께 쓰는 절차,
loras.json과 사용자 프리셋 작성법을 적는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## 완료 확인

모든 태스크가 끝나면 다음이 전부 참이어야 한다.

- [ ] `uv run --extra dev pytest -q` 전부 통과
- [ ] `uv run --extra dev ruff check src tests` — `All checks passed!`
- [ ] `git status --short`에 `uv.lock` 외 미커밋 변경 없음
- [ ] **수동 확인**: 앱을 띄우고(`uv run nai-auto-v5`) 프롬프트 컴파일러를 연 뒤
  - 출력 대상이 `NovelAI V5`일 때 결과 탭이 1개, 캐릭터 프롬프트가 채워진다
  - `Illustrious / NoobAI`로 바꾸면 탭이 3개가 되고 안내 문구가 보인다
  - 적용해도 캐릭터 프롬프트 탭이 그대로다
  - 언어를 영어로 바꿔도 새 라벨이 전부 번역된다
- [ ] `core/` 아래 새 코드에 `PySide6` import가 없다:
  `grep -rn "PySide6" src/naiauto/core/` → 결과 없음



