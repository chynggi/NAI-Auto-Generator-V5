# ComfyUI 생성 백엔드 연동 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 앱에서 바로 로컬 ComfyUI로 txt2img 생성을 돌린다. 기존 배치·와일드카드·아티스트 조합·시드 관리·갤러리는 그대로 쓴다.

**Architecture:** `GenerationService`가 이미 클라이언트를 주입받고 실질 인터페이스가 `generate(req) -> GenerationResult` 하나뿐이라, 그 자리를 백엔드 경계로 삼는다. `GenerationRequest`를 그대로 재사용하고 샘플러 이름은 매핑하지 않는다 — 백엔드를 바꾸면 UI의 목록 자체가 `/object_info` 결과로 갈아끼워진다. 워크플로 그래프는 우리가 저작한 JSON 템플릿을 리소스로 동봉하고, 매니페스트가 값 주입 지점을 선언한다.

**Tech Stack:** Python 3.11+, requests, websocket-client(신규), pydantic v2, PySide6, pytest, ruff, uv

**Spec:** `docs/superpowers/specs/2026-09-06-comfyui-backend-design.md`

---

## 사전 준비 — 반드시 먼저 읽을 것

**이 저장소의 규칙:**

- 테스트/린트는 **`uv run --extra dev`** 로 실행한다. `.venv/Scripts/python.exe`에는 pytest가 없다.
  - 테스트: `uv run --extra dev pytest -q`
  - 린트: `uv run --extra dev ruff check src tests`
- `src/naiauto/core/` 아래 모든 모듈은 **Qt 의존성이 없어야 한다.** `PySide6` import 금지.
- 신규 모듈은 **한국어 모듈 독스트링**으로 시작하고 `__all__`로 끝난다.
- 커밋 메시지는 Conventional Commits 접두사 + 한국어 본문, 끝에 다음 두 줄:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
  ```

**작업 전 기준선:**

```bash
cd "M:/Kubuntu/NAI-Auto-Generator-V5"
git status --short            # uv.lock 외 변경 없어야 한다
uv run --extra dev pytest -q  # 317 passed
```

**대상 환경** (조사로 확정, 스펙 §1 참고):

- ComfyUI v0.34.5, `http://127.0.0.1:8188`, `comfyui-prompt-control` 설치됨
- 체크포인트 `waiIllustriousSDXL_v170.safetensors`
- Anima: `Anima-2.9B-preview-v1.safetensors` + `qwen_3_06b_base.safetensors` + `qwen_image_vae.safetensors` + `anima-turbo-lora-v0.2.safetensors`

---

## 파일 구조

**신규**

| 파일 | 책임 |
|---|---|
| `src/naiauto/core/backends/__init__.py` | 패키지 공개 API |
| `src/naiauto/core/backends/base.py` | `ImageBackend` 프로토콜 + 능력 조회 헬퍼 |
| `src/naiauto/core/backends/errors.py` | ComfyUI 전용 오류 계층 |
| `src/naiauto/core/backends/comfy_workflow.py` | 템플릿 로딩·검증·값 주입·LoRA 결선. **순수 함수, I/O는 로딩뿐** |
| `src/naiauto/core/backends/comfy_objects.py` | `/object_info` 응답 파싱 |
| `src/naiauto/core/backends/comfy_progress.py` | WebSocket 수신 루프 |
| `src/naiauto/core/backends/comfyui.py` | 백엔드 본체 — 큐 삽입 → 진행 추적 → 이미지 회수 |
| `src/naiauto/resources/comfy_workflows/sdxl_basic.json` | 내장 템플릿 |
| `src/naiauto/resources/comfy_workflows/sdxl_regional.json` | 내장 템플릿 |
| `src/naiauto/resources/comfy_workflows/anima.json` | 내장 템플릿 |
| `src/naiauto/ui/options_pages/local_backend_page.py` | 옵션 "로컬 생성" 페이지 |
| `tests/test_comfy_workflow.py` | 주입 로직 (서버 불필요) |
| `tests/test_comfy_objects.py` | `/object_info` 파싱 |
| `tests/test_comfy_backend.py` | 백엔드 (HTTP/WS 스텁) |
| `tests/test_comfy_templates.py` | 내장 템플릿 3종 무결성 |

`comfy_workflow.py`(순수)와 `comfyui.py`(네트워크)를 나누는 이유는 A단계의 `targets`/`emitters` 분리와 같다 — 주입 로직이 가장 버그가 나기 쉬운데 서버 없이 테스트해야 한다.

**수정**

| 파일 | 변경 |
|---|---|
| `services/generation_service.py` | 타입 힌트를 `ImageBackend`로, 크레딧 로깅에 능력 가드 |
| `core/settings/schema.py` | `generation_backend`, `ComfyUISettings` |
| `ui/options_pages/__init__.py` | 새 페이지 정적 import 등록 |
| `ui/options_dialog.py` | `NAV_ORDER`에 `local_backend` 추가, `OWNED_FIELDS`에 새 필드 |
| `ui/main_window.py` | 백엔드 셀렉터, 샘플러/스케줄러 목록 교체, Anlas 숨김, 백엔드 생성 |
| `resources/languages/{ko,en,ja,zh}.json` | 새 UI 문자열 |
| `pyproject.toml` | `websocket-client` 필수 의존성 |
| `packaging/nai-auto-v5.spec` | `hiddenimports`에 `websocket` |
| `README.md`, `MANUAL_KR.md` | 기능 설명 + 설정 안내 |

**NAIClient는 손대지 않는다.** 능력 조회는 `getattr(backend, "supports_credit", True)`로 하므로 기존 클래스가 그대로 프로토콜을 만족한다.

---

## Task 1: 백엔드 프로토콜

**Files:**
- Create: `src/naiauto/core/backends/__init__.py`
- Create: `src/naiauto/core/backends/base.py`
- Create: `tests/test_backends_base.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_backends_base.py`:

```python
"""백엔드 프로토콜 테스트."""

from naiauto.core.api.models import GenerationRequest, GenerationResult
from naiauto.core.backends.base import ImageBackend, backend_supports_credit


class _Fake:
    supports_credit = False

    def generate(self, req: GenerationRequest) -> GenerationResult:
        return GenerationResult(raw_bytes=b"png")


class _Legacy:
    """supports_credit을 선언하지 않는 기존 클라이언트 (NAIClient 모양)."""

    def generate(self, req: GenerationRequest) -> GenerationResult:
        return GenerationResult(raw_bytes=b"png")


def test_fake_satisfies_protocol():
    assert isinstance(_Fake(), ImageBackend)
    assert isinstance(_Legacy(), ImageBackend)


def test_supports_credit_reads_declared_flag():
    assert backend_supports_credit(_Fake()) is False


def test_supports_credit_defaults_true_for_legacy_client():
    """NAIClient는 이 플래그를 선언하지 않는다 — 크레딧을 쓰는 쪽이 기본값이어야 한다."""
    assert backend_supports_credit(_Legacy()) is True


def test_real_nai_client_is_a_backend():
    from naiauto.core.api.client import NAIClient

    assert issubclass(NAIClient, ImageBackend) or isinstance.__self__ is not None
    assert backend_supports_credit(NAIClient.__new__(NAIClient)) is True
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --extra dev pytest tests/test_backends_base.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'naiauto.core.backends'`

- [ ] **Step 3: 구현**

`src/naiauto/core/backends/base.py`:

```python
"""이미지 생성 백엔드의 공통 계약.

``GenerationService``는 이미 클라이언트를 주입받고, 실질 인터페이스가
``generate(req) -> GenerationResult`` 하나뿐이다. 그 자리를 그대로 백엔드
경계로 쓴다 — NovelAI(``api.client.NAIClient``)와 로컬 ComfyUI가 같은 모양이다.

능력 플래그는 **선언하지 않아도 되도록** 설계했다. ``backend_supports_credit``이
``getattr`` 기본값 True를 쓰므로 기존 ``NAIClient``를 고치지 않아도 프로토콜을
만족한다 — 크레딧을 쓰지 않는 쪽(로컬)이 명시적으로 False를 선언한다.

Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from naiauto.core.api.models import GenerationRequest, GenerationResult

__all__ = ["ImageBackend", "backend_supports_credit"]


@runtime_checkable
class ImageBackend(Protocol):
    """이미지 1장을 만드는 백엔드."""

    def generate(self, req: GenerationRequest) -> GenerationResult:
        """요청 1건 → 이미지 바이트. 실패는 예외로 알린다."""
        ...


def backend_supports_credit(backend: object) -> bool:
    """백엔드가 크레딧/Anlas 조회를 지원하는가.

    선언하지 않은 백엔드는 지원하는 것으로 본다 — 기존 ``NAIClient``가
    그 경우이고, 새로 만드는 로컬 백엔드만 False를 명시한다.
    """
    return bool(getattr(backend, "supports_credit", True))
```

`src/naiauto/core/backends/__init__.py`:

```python
"""이미지 생성 백엔드 (NovelAI / 로컬 ComfyUI).

Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

from naiauto.core.backends.base import ImageBackend, backend_supports_credit

__all__ = ["ImageBackend", "backend_supports_credit"]
```

- [ ] **Step 4: 통과 확인**

Run: `uv run --extra dev pytest tests/test_backends_base.py -q`
Expected: PASS (4 passed)

`runtime_checkable` Protocol은 메서드 존재만 확인하므로 `_Legacy`도 통과한다. 그게 의도다.

- [ ] **Step 5: 커밋**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/core/backends tests/test_backends_base.py
git commit -m "$(cat <<'EOF'
feat(backends): 이미지 생성 백엔드 프로토콜

GenerationService가 클라이언트를 쓰는 곳은 generate()와 get_anlas() 두 곳뿐이다.
그 좁은 계약을 프로토콜로 굳힌다. 능력 플래그는 getattr 기본값을 쓰므로 기존
NAIClient를 고치지 않아도 프로토콜을 만족한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 2: GenerationService에 능력 가드

`_client`를 쓰는 곳은 **두 줄뿐**이다 — `get_anlas()`(크레딧 로깅)와 `generate()`. 후자는 프로토콜이 보장하므로, 전자에만 가드를 넣는다.

**Files:**
- Modify: `src/naiauto/services/generation_service.py`
- Modify: `tests/test_infra.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_infra.py` 맨 끝에 덧붙인다:

```python
def test_credit_logging_skipped_for_backend_without_credit():
    """로컬 백엔드는 Anlas 개념이 없다 — 조회를 시도하면 안 된다."""
    from naiauto.core.api.models import GenerationResult
    from naiauto.services.generation_service import GenerationService

    calls = []

    class _LocalBackend:
        supports_credit = False

        def generate(self, req):  # pragma: no cover - 이 테스트에서 안 부른다
            return GenerationResult(raw_bytes=b"")

        def get_anlas(self):
            calls.append("anlas")
            raise AssertionError("로컬 백엔드에서 get_anlas를 부르면 안 된다")

    service = GenerationService(_LocalBackend())
    service._log_credit(1)          # 예외 없이 조용히 지나가야 한다
    assert calls == []
    service.shutdown()


def test_credit_logging_attempted_for_novelai_backend():
    """NAIClient는 플래그를 선언하지 않는다 — 기본값(True)으로 조회를 시도해야 한다."""
    from naiauto.core.api.models import GenerationResult
    from naiauto.services.generation_service import GenerationService

    calls = []

    class _NaiLike:
        def generate(self, req):  # pragma: no cover
            return GenerationResult(raw_bytes=b"")

        def get_anlas(self):
            calls.append("anlas")
            return {}

    service = GenerationService(_NaiLike())
    service._log_credit(1)
    assert calls == ["anlas"]
    service.shutdown()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --extra dev pytest tests/test_infra.py -q`
Expected: FAIL — `test_credit_logging_skipped_for_backend_without_credit`에서 `AssertionError: 로컬 백엔드에서 get_anlas를 부르면 안 된다`

`_log_credit`의 정확한 시그니처를 먼저 확인하라. 인자가 `(self, index)`가 아니면 테스트를 실제 시그니처에 맞추고 보고하라.

- [ ] **Step 3: 가드를 넣는다**

`src/naiauto/services/generation_service.py`의 import 블록에 추가:

```python
from ..core.backends.base import ImageBackend, backend_supports_credit
```

`GenerationService.__init__`의 `client: NAIClient` 타입 힌트를 다음으로 바꾼다 (**인자 이름은 `client` 그대로 둔다** — 호출부를 건드리지 않기 위해서다):

```python
        client: ImageBackend,
```

`_log_credit` 메서드의 본문 **맨 앞**에 다음을 넣는다:

```python
        # 로컬 백엔드는 Anlas/크레딧 개념이 없다 — 조회 자체를 하지 않는다.
        if not backend_supports_credit(self._client):
            return
```

`NAIClient` import가 타입 힌트에서만 쓰였다면 ruff가 미사용을 알릴 수 있다. 그 경우 import를 지우지 말고 `TYPE_CHECKING` 블록으로 옮기거나, 다른 곳에서 쓰이면 그대로 둔다. 어느 쪽이었는지 보고하라.

- [ ] **Step 4: 통과 확인**

```
uv run --extra dev pytest tests/test_infra.py -q
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

전체 스위트는 317 + 2 = 319를 기대한다. **실제 숫자를 보고하라.**

- [ ] **Step 5: 커밋**

```bash
git add src/naiauto/services/generation_service.py tests/test_infra.py
git commit -m "$(cat <<'EOF'
feat(services): 크레딧 조회에 백엔드 능력 가드

로컬 백엔드는 Anlas 개념이 없어 get_anlas를 부르면 안 된다. 인자 이름은
client 그대로 두어 호출부를 건드리지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 3: ComfyUI 오류 계층

**Files:**
- Create: `src/naiauto/core/backends/errors.py`
- Create: `tests/test_comfy_errors.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_comfy_errors.py`:

```python
"""ComfyUI 백엔드 오류 계층 테스트."""

import pytest

from naiauto.core.backends.errors import (
    ComfyConnectionError,
    ComfyError,
    ComfyExecutionError,
    ComfyPromptRejectedError,
    ComfyTemplateError,
    ComfyTimeoutError,
)


@pytest.mark.parametrize(
    "cls",
    [
        ComfyConnectionError,
        ComfyPromptRejectedError,
        ComfyExecutionError,
        ComfyTimeoutError,
        ComfyTemplateError,
    ],
)
def test_all_errors_share_a_base(cls):
    """UI는 ComfyError 하나만 잡으면 되어야 한다."""
    assert issubclass(cls, ComfyError)


def test_prompt_rejected_keeps_node_errors():
    """서버가 준 node_errors가 가장 정확한 진단이다 — 뭉뚱그리면 안 된다."""
    node_errors = {"3": {"errors": [{"message": "value not in list"}]}}
    exc = ComfyPromptRejectedError("bad prompt", node_errors=node_errors)
    assert exc.node_errors == node_errors
    assert "bad prompt" in str(exc)


def test_prompt_rejected_without_node_errors():
    exc = ComfyPromptRejectedError("boom")
    assert exc.node_errors == {}


def test_execution_error_keeps_node_type():
    exc = ComfyExecutionError("KSampler failed", node_id="3", node_type="KSampler")
    assert exc.node_id == "3"
    assert exc.node_type == "KSampler"
    assert "KSampler" in str(exc)
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --extra dev pytest tests/test_comfy_errors.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'naiauto.core.backends.errors'`

- [ ] **Step 3: 구현**

`src/naiauto/core/backends/errors.py`:

```python
"""ComfyUI 백엔드 오류 계층.

UI는 ``ComfyError`` 하나만 잡으면 되지만, 원인별로 다른 안내를 하려면 구분이
필요하다. 특히 ``ComfyPromptRejectedError``의 ``node_errors``는 서버가 주는
가장 정확한 진단(어느 노드의 어느 입력이 틀렸는지)이므로 뭉뚱그리지 않는다.

Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

__all__ = [
    "ComfyError",
    "ComfyConnectionError",
    "ComfyPromptRejectedError",
    "ComfyExecutionError",
    "ComfyTimeoutError",
    "ComfyTemplateError",
]


class ComfyError(Exception):
    """모든 ComfyUI 백엔드 오류의 베이스."""


class ComfyConnectionError(ComfyError):
    """서버에 붙지 못했다 (미실행이 가장 흔하다)."""


class ComfyPromptRejectedError(ComfyError):
    """``POST /prompt``가 400으로 거부했다.

    ``node_errors``는 서버가 알려준 노드별 문제다 — 모델 파일이 없거나 샘플러
    이름이 틀린 경우가 여기로 온다.
    """

    def __init__(self, message: str, node_errors: dict | None = None) -> None:
        super().__init__(message)
        self.node_errors = node_errors or {}


class ComfyExecutionError(ComfyError):
    """실행 중 노드가 예외를 냈다 (WS ``execution_error``)."""

    def __init__(
        self, message: str, node_id: str = "", node_type: str = ""
    ) -> None:
        super().__init__(f"{node_type or 'node'}: {message}" if node_type else message)
        self.node_id = node_id
        self.node_type = node_type


class ComfyTimeoutError(ComfyError):
    """정해진 시간 안에 결과가 오지 않았다."""


class ComfyTemplateError(ComfyError):
    """워크플로 템플릿이 잘못됐다 (슬롯 경로 없음, JSON 파손 등)."""
```

- [ ] **Step 4: 통과 확인**

Run: `uv run --extra dev pytest tests/test_comfy_errors.py -q`
Expected: PASS (8 passed — parametrize 5 + 개별 3)

- [ ] **Step 5: 커밋**

```bash
uv run --extra dev ruff check src tests
git add src/naiauto/core/backends/errors.py tests/test_comfy_errors.py
git commit -m "$(cat <<'EOF'
feat(backends): ComfyUI 오류 계층

node_errors를 예외에 실어 나른다. 서버가 주는 가장 정확한 진단이라
"생성 실패"로 뭉뚱그리면 사용자가 원인을 찾을 길이 없다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 4: 워크플로 템플릿 모델과 로딩

**Files:**
- Create: `src/naiauto/core/backends/comfy_workflow.py`
- Create: `tests/test_comfy_workflow.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_comfy_workflow.py`:

```python
"""워크플로 템플릿 로딩·검증 테스트 — 서버 없이 돈다."""

import json

import pytest

from naiauto.core.backends.comfy_workflow import (
    WorkflowTemplate,
    builtin_workflows_dir,
    load_workflows,
    parse_template,
)
from naiauto.core.backends.errors import ComfyTemplateError

MINIMAL = {
    "id": "demo",
    "name": "Demo",
    "output_node": "9",
    "lora_mode": "direct",
    "model_slots": {
        "checkpoint": {"path": "4.ckpt_name", "from": "CheckpointLoaderSimple.ckpt_name"}
    },
    "slots": {"positive": "6.text", "seed": "3.seed"},
    "graph": {
        "3": {"inputs": {"seed": 0}, "class_type": "KSampler"},
        "4": {"inputs": {"ckpt_name": ""}, "class_type": "CheckpointLoaderSimple"},
        "6": {"inputs": {"text": ""}, "class_type": "CLIPTextEncode"},
        "9": {"inputs": {"images": ["8", 0]}, "class_type": "PreviewImage"},
    },
}


def test_parse_reads_all_fields():
    t = parse_template(MINIMAL)
    assert t.id == "demo"
    assert t.name == "Demo"
    assert t.output_node == "9"
    assert t.lora_mode == "direct"
    assert t.slots["positive"] == "6.text"
    assert t.model_slots["checkpoint"].path == "4.ckpt_name"
    assert t.model_slots["checkpoint"].source == "CheckpointLoaderSimple.ckpt_name"
    assert t.requires_nodes == ()


def test_parse_defaults():
    data = {**MINIMAL}
    data.pop("lora_mode")
    t = parse_template(data)
    assert t.lora_mode == "direct"


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda d: d.pop("id"), "id 없음"),
        (lambda d: d.update(id=""), "id 빈 문자열"),
        (lambda d: d.pop("graph"), "graph 없음"),
        (lambda d: d.update(output_node="99"), "output_node가 그래프에 없음"),
        (lambda d: d.update(lora_mode="nope"), "lora_mode 유효값 아님"),
        (lambda d: d.update(slots={"positive": "99.text"}), "슬롯 노드가 없음"),
        (lambda d: d.update(slots={"positive": "6.nope"}), "슬롯 입력이 없음"),
        (lambda d: d.update(slots={"positive": "6text"}), "슬롯 경로에 점이 없음"),
        (
            lambda d: d.update(
                model_slots={"c": {"path": "99.x", "from": "A.b"}}
            ),
            "모델 슬롯 노드가 없음",
        ),
        (
            lambda d: d.update(model_slots={"c": {"path": "4.ckpt_name"}}),
            "모델 슬롯에 from 없음",
        ),
    ],
)
def test_parse_rejects_invalid(mutate, reason):
    data = json.loads(json.dumps(MINIMAL))
    mutate(data)
    with pytest.raises(ComfyTemplateError):
        parse_template(data)


def test_builtin_dir_exists():
    assert builtin_workflows_dir().is_dir()


def test_load_workflows_reads_builtins():
    ids = {t.id for t in load_workflows()}
    assert "sdxl_basic" in ids


def test_broken_file_is_skipped_not_fatal(tmp_path):
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "good.json").write_text(json.dumps(MINIMAL), encoding="utf-8")
    ids = {t.id for t in load_workflows(tmp_path)}
    assert "demo" in ids
    assert "broken" not in ids


def test_user_dir_overrides_builtin_by_id(tmp_path):
    data = json.loads(json.dumps(MINIMAL))
    data["id"] = "sdxl_basic"
    data["name"] = "My Basic"
    (tmp_path / "mine.json").write_text(json.dumps(data), encoding="utf-8")
    by_id = {t.id: t for t in load_workflows(tmp_path)}
    assert by_id["sdxl_basic"].name == "My Basic"


def test_unreadable_dir_is_skipped_not_fatal(tmp_path, monkeypatch):
    """읽을 수 없는 폴더가 앱 기동을 막지 않는다."""
    from pathlib import Path

    def _boom(self, pattern):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "glob", _boom)
    assert load_workflows(tmp_path) == ()


def test_available_filters_by_required_nodes():
    t = parse_template({**MINIMAL, "requires_nodes": ["PCLazyTextEncode"]})
    assert t.is_available({"KSampler", "CLIPTextEncode"}) is False
    assert t.is_available({"PCLazyTextEncode"}) is True


def test_available_with_no_requirements():
    assert parse_template(MINIMAL).is_available(set()) is True
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --extra dev pytest tests/test_comfy_workflow.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'naiauto.core.backends.comfy_workflow'`

- [ ] **Step 3: 구현**

`src/naiauto/core/backends/comfy_workflow.py`:

```python
"""ComfyUI 워크플로 템플릿 — 로딩·검증·값 주입.

ComfyUI에는 "프롬프트를 보내는" API가 없다. 노드 그래프(API 형식) 전체를 큐에
넣는 구조라, 그래프를 어디서 가져오고 값을 어디에 넣을지가 정해져야 한다.

우리가 저작한 템플릿을 리소스로 동봉하고, 매니페스트가 주입 지점을 선언한다.
노드 제목(``_meta.title``) 규칙은 쓰지 않는다 — 제목은 ComfyUI UI에서 자유롭게
바뀌므로 조용히 깨진다.

``model_slots``는 템플릿마다 개수와 이름이 다르다. SDXL은 ``checkpoint`` 하나,
Anima는 UNET+CLIP+VAE 세 개다. 그래서 고정 집합이 아니라 템플릿이 선언한다.

주입은 순수 계산이고 로딩만 I/O다 — 그래야 서버 없이 테스트할 수 있다.
Qt 의존성 없음.
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from naiauto.core.backends.errors import ComfyTemplateError

logger = logging.getLogger(__name__)

__all__ = [
    "LORA_MODES",
    "ModelSlot",
    "WorkflowTemplate",
    "builtin_workflows_dir",
    "parse_template",
    "load_workflows",
    "find_workflow",
]

#: ``lora_mode`` 유효값.
#: direct   — 앱이 LoraLoader 체인을 그래프에 넣고 프롬프트에서 <lora:...>를 뺀다
#: delegate — 프롬프트를 그대로 넘긴다 (PCLazyLoraLoader가 알아서 한다)
LORA_MODES = ("direct", "delegate")


@dataclass(frozen=True)
class ModelSlot:
    """모델 파일을 넣을 자리 하나."""

    #: 그래프 안 위치 — "<node_id>.<input_name>"
    path: str
    #: /object_info 조회 경로 — "<NodeClass>.<input_name>"
    source: str


@dataclass(frozen=True)
class WorkflowTemplate:
    """워크플로 템플릿 1개 (매니페스트 + 그래프)."""

    id: str
    name: str
    output_node: str
    graph: dict
    slots: dict[str, str] = field(default_factory=dict)
    model_slots: dict[str, ModelSlot] = field(default_factory=dict)
    requires_nodes: tuple[str, ...] = ()
    lora_mode: str = "direct"

    def is_available(self, known_node_classes: Iterable[str]) -> bool:
        """``requires_nodes``가 전부 서버에 있으면 True."""
        known = set(known_node_classes)
        return all(node in known for node in self.requires_nodes)


def builtin_workflows_dir() -> Path:
    """패키지에 동봉된 템플릿 폴더 (다른 리소스와 같은 규칙)."""
    return Path(__file__).resolve().parent.parent.parent / "resources" / "comfy_workflows"


def _split_path(path: str, what: str) -> tuple[str, str]:
    """"3.seed" → ("3", "seed"). 형식이 아니면 ComfyTemplateError."""
    node_id, sep, input_name = str(path).partition(".")
    if not sep or not node_id or not input_name:
        raise ComfyTemplateError(f"{what}: {path!r} must be '<node_id>.<input_name>'")
    return node_id, input_name


def _check_path(graph: dict, path: str, what: str) -> None:
    """슬롯 경로가 그래프에 실재하는지 확인한다.

    로드 시점에 잡아야 한다 — 런타임에 드러나면 사용자가 생성 실패로만 본다.
    """
    node_id, input_name = _split_path(path, what)
    node = graph.get(node_id)
    if not isinstance(node, dict):
        raise ComfyTemplateError(f"{what}: node {node_id!r} not in graph")
    if input_name not in node.get("inputs", {}):
        raise ComfyTemplateError(f"{what}: node {node_id!r} has no input {input_name!r}")


def parse_template(data: dict) -> WorkflowTemplate:
    """템플릿 JSON 1개 → ``WorkflowTemplate``. 위반 시 ``ComfyTemplateError``."""
    if not isinstance(data, dict):
        raise ComfyTemplateError("template must be a JSON object")
    template_id = str(data.get("id", "")).strip()
    if not template_id:
        raise ComfyTemplateError("template needs a non-empty 'id'")
    graph = data.get("graph")
    if not isinstance(graph, dict) or not graph:
        raise ComfyTemplateError(f"{template_id}: 'graph' must be a non-empty object")

    output_node = str(data.get("output_node", "")).strip()
    if output_node not in graph:
        raise ComfyTemplateError(
            f"{template_id}: 'output_node' {output_node!r} not in graph"
        )

    lora_mode = str(data.get("lora_mode", "direct"))
    if lora_mode not in LORA_MODES:
        raise ComfyTemplateError(
            f"{template_id}: 'lora_mode' must be one of {LORA_MODES}, got {lora_mode!r}"
        )

    raw_slots = data.get("slots", {})
    if not isinstance(raw_slots, dict):
        raise ComfyTemplateError(f"{template_id}: 'slots' must be an object")
    slots: dict[str, str] = {}
    for name, path in raw_slots.items():
        _check_path(graph, str(path), f"{template_id}.slots.{name}")
        slots[str(name)] = str(path)

    raw_models = data.get("model_slots", {})
    if not isinstance(raw_models, dict):
        raise ComfyTemplateError(f"{template_id}: 'model_slots' must be an object")
    model_slots: dict[str, ModelSlot] = {}
    for name, spec in raw_models.items():
        if not isinstance(spec, dict) or "path" not in spec or "from" not in spec:
            raise ComfyTemplateError(
                f"{template_id}.model_slots.{name}: needs 'path' and 'from'"
            )
        _check_path(graph, str(spec["path"]), f"{template_id}.model_slots.{name}")
        _split_path(str(spec["from"]), f"{template_id}.model_slots.{name}.from")
        model_slots[str(name)] = ModelSlot(path=str(spec["path"]), source=str(spec["from"]))

    requires = data.get("requires_nodes", [])
    if not isinstance(requires, list) or any(not isinstance(n, str) for n in requires):
        raise ComfyTemplateError(f"{template_id}: 'requires_nodes' must be a list of strings")

    return WorkflowTemplate(
        id=template_id,
        name=str(data.get("name", "")).strip() or template_id,
        output_node=output_node,
        graph=graph,
        slots=slots,
        model_slots=model_slots,
        requires_nodes=tuple(requires),
        lora_mode=lora_mode,
    )


def _load_dir(directory: Path) -> list[WorkflowTemplate]:
    """폴더의 ``*.json``을 템플릿으로 읽는다. 깨진 파일은 건너뛴다."""
    templates: list[WorkflowTemplate] = []
    try:
        if not directory.is_dir():
            return templates
        paths = sorted(directory.glob("*.json"))
    except OSError as exc:
        logger.warning("cannot read workflow directory %s: %s", directory, exc)
        return templates
    for path in paths:
        try:
            templates.append(parse_template(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError, ValueError, ComfyTemplateError) as exc:
            logger.warning("skipping broken workflow template %s: %s", path, exc)
    return templates


def load_workflows(user_dir: str | Path | None = None) -> tuple[WorkflowTemplate, ...]:
    """내장 + 사용자 템플릿. 같은 id면 사용자 것이 이긴다."""
    ordered: dict[str, WorkflowTemplate] = {}
    for template in _load_dir(builtin_workflows_dir()):
        ordered[template.id] = template
    text = str(user_dir).strip() if user_dir is not None else ""
    if text:
        for template in _load_dir(Path(text)):
            ordered[template.id] = template
    return tuple(ordered.values())


def find_workflow(
    templates: tuple[WorkflowTemplate, ...], template_id: str
) -> WorkflowTemplate | None:
    """id로 템플릿을 찾는다. 없으면 None (호출자가 안내를 정한다)."""
    for template in templates:
        if template.id == template_id:
            return template
    return None
```

`copy`는 다음 태스크(주입)에서 쓴다. ruff가 미사용을 알리면 이 태스크에서는 import를 **빼고**, Task 5에서 다시 넣어라. 어느 쪽이었는지 보고하라.

- [ ] **Step 4: 최소 내장 템플릿을 만든다**

`test_load_workflows_reads_builtins`가 `sdxl_basic`을 요구한다. `src/naiauto/resources/comfy_workflows/sdxl_basic.json`:

```json
{
  "id": "sdxl_basic",
  "name": "SDXL 기본",
  "requires_nodes": [],
  "output_node": "9",
  "lora_mode": "direct",
  "model_slots": {
    "checkpoint": {"path": "4.ckpt_name", "from": "CheckpointLoaderSimple.ckpt_name"}
  },
  "slots": {
    "positive": "6.text",
    "negative": "7.text",
    "seed": "3.seed",
    "steps": "3.steps",
    "cfg": "3.cfg",
    "sampler": "3.sampler_name",
    "scheduler": "3.scheduler",
    "width": "5.width",
    "height": "5.height"
  },
  "graph": {
    "3": {
      "class_type": "KSampler",
      "inputs": {
        "seed": 0, "steps": 28, "cfg": 6.0,
        "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": 1.0,
        "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
        "latent_image": ["5", 0]
      }
    },
    "4": {
      "class_type": "CheckpointLoaderSimple",
      "inputs": {"ckpt_name": ""}
    },
    "5": {
      "class_type": "EmptyLatentImage",
      "inputs": {"width": 832, "height": 1216, "batch_size": 1}
    },
    "6": {
      "class_type": "CLIPTextEncode",
      "inputs": {"text": "", "clip": ["4", 1]}
    },
    "7": {
      "class_type": "CLIPTextEncode",
      "inputs": {"text": "", "clip": ["4", 1]}
    },
    "8": {
      "class_type": "VAEDecode",
      "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
    },
    "9": {
      "class_type": "PreviewImage",
      "inputs": {"images": ["8", 0]}
    }
  }
}
```

`batch_size`는 슬롯이 아니라 1로 고정한다 — 앱의 배치 루프가 장수를 돈다.
출력은 `PreviewImage`(임시 디렉터리)라 ComfyUI output 폴더에 사본이 남지 않는다.

- [ ] **Step 5: 통과 확인**

```
uv run --extra dev pytest tests/test_comfy_workflow.py -q
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

`test_comfy_workflow.py`는 20 passed(parametrize 10 + 개별 10)를 기대한다. **실제 숫자를 보고하라.**

- [ ] **Step 6: 커밋**

```bash
git add src/naiauto/core/backends/comfy_workflow.py src/naiauto/resources/comfy_workflows tests/test_comfy_workflow.py
git commit -m "$(cat <<'EOF'
feat(backends): 워크플로 템플릿 로딩과 슬롯 검증

노드 제목 규칙 대신 매니페스트가 주입 지점을 선언한다. 제목은 ComfyUI UI에서
바뀌므로 조용히 깨진다. 슬롯 경로는 로드 시점에 그래프와 대조하므로, 템플릿을
잘못 저작하면 런타임이 아니라 로드 때 드러난다.

model_slots는 템플릿이 개수와 이름을 선언한다 — SDXL은 체크포인트 하나지만
Anima는 UNET+CLIP+VAE 세 개라 고정 집합으로 둘 수 없다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 5: 값 주입과 LoRA 결선

**Files:**
- Modify: `src/naiauto/core/backends/comfy_workflow.py`
- Modify: `tests/test_comfy_workflow.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_comfy_workflow.py` 맨 끝에 덧붙인다. 상단 import에 `LoraAssignment`, `build_graph`, `strip_lora_tags`를 추가한다.

```python
# --- 값 주입 ---------------------------------------------------------------


def _template(**over):
    data = json.loads(json.dumps(MINIMAL))
    data.update(over)
    return parse_template(data)


def test_build_graph_injects_slots():
    t = _template(slots={"positive": "6.text", "seed": "3.seed"})
    g = build_graph(t, values={"positive": "1girl", "seed": 42}, models={})
    assert g["6"]["inputs"]["text"] == "1girl"
    assert g["3"]["inputs"]["seed"] == 42


def test_build_graph_injects_model_slots():
    t = _template()
    g = build_graph(t, values={}, models={"checkpoint": "wai.safetensors"})
    assert g["4"]["inputs"]["ckpt_name"] == "wai.safetensors"


def test_build_graph_does_not_mutate_template():
    """템플릿은 앱 수명 내내 재사용된다 — 원본을 건드리면 다음 생성이 오염된다."""
    t = _template()
    build_graph(t, values={"positive": "mutated"}, models={})
    assert t.graph["6"]["inputs"]["text"] == ""


def test_build_graph_ignores_unknown_values():
    """템플릿이 선언하지 않은 슬롯은 조용히 무시한다 (템플릿마다 슬롯이 다르다)."""
    t = _template(slots={"positive": "6.text"})
    g = build_graph(t, values={"positive": "a", "cfg": 7.0}, models={})
    assert g["6"]["inputs"]["text"] == "a"


def test_build_graph_skips_none_values():
    t = _template()
    g = build_graph(t, values={"seed": None}, models={})
    assert g["3"]["inputs"]["seed"] == 0


def test_build_graph_skips_empty_model_selection():
    """모델을 아직 안 고른 슬롯은 템플릿 기본값을 남긴다."""
    t = _template()
    g = build_graph(t, values={}, models={"checkpoint": ""})
    assert g["4"]["inputs"]["ckpt_name"] == ""


# --- LoRA ------------------------------------------------------------------


def test_strip_lora_tags_removes_and_tidies():
    text = "<lora:kafka:0.8>, masterpiece, 1girl"
    assert strip_lora_tags(text) == "masterpiece, 1girl"


def test_strip_lora_tags_handles_parenthesised_filenames():
    """실제 파일명에 괄호가 있다 — hans_anima-kei_(blue_archive)_lora."""
    text = "<lora:hans_anima-kei_(blue_archive)_lora:0.8>, 1girl"
    assert strip_lora_tags(text) == "1girl"


def test_strip_lora_tags_noop_without_tags():
    assert strip_lora_tags("masterpiece, 1girl") == "masterpiece, 1girl"


def test_direct_mode_inserts_lora_loader_chain():
    t = _template()
    loras = (LoraAssignment(file="kafka.safetensors", weight=0.8),)
    g = build_graph(t, values={"positive": "<lora:kafka:0.8>, 1girl"}, models={}, loras=loras)
    loaders = [n for n in g.values() if n["class_type"] == "LoraLoader"]
    assert len(loaders) == 1
    assert loaders[0]["inputs"]["lora_name"] == "kafka.safetensors"
    assert loaders[0]["inputs"]["strength_model"] == 0.8
    assert loaders[0]["inputs"]["strength_clip"] == 0.8
    # 프롬프트에서 태그가 빠졌다 — 안 빼면 문자열로 인코딩돼 결과를 오염시킨다
    assert "<lora:" not in g["6"]["inputs"]["text"]


def test_direct_mode_rewires_model_and_clip_consumers():
    """KSampler는 LoraLoader의 model을, CLIPTextEncode는 clip을 받아야 한다."""
    t = _template()
    loras = (LoraAssignment(file="kafka.safetensors", weight=0.8),)
    g = build_graph(t, values={}, models={}, loras=loras)
    loader_id = next(k for k, n in g.items() if n["class_type"] == "LoraLoader")
    assert g["3"]["inputs"]["model"] == [loader_id, 0]
    assert g["6"]["inputs"]["clip"] == [loader_id, 1]


def test_direct_mode_chains_multiple_loras():
    t = _template()
    loras = (
        LoraAssignment(file="a.safetensors", weight=0.8),
        LoraAssignment(file="b.safetensors", weight=0.5),
    )
    g = build_graph(t, values={}, models={}, loras=loras)
    loaders = [n for n in g.values() if n["class_type"] == "LoraLoader"]
    assert len(loaders) == 2


def test_delegate_mode_leaves_prompt_and_graph_alone():
    """PCLazyLoraLoader가 <lora:...>를 읽는다 — 우리가 또 결선하면 두 번 걸린다."""
    t = _template(lora_mode="delegate")
    loras = (LoraAssignment(file="kafka.safetensors", weight=0.8),)
    g = build_graph(t, values={"positive": "<lora:kafka:0.8>, 1girl"}, models={}, loras=loras)
    assert not [n for n in g.values() if n["class_type"] == "LoraLoader"]
    assert "<lora:kafka:0.8>" in g["6"]["inputs"]["text"]


def test_no_loras_leaves_graph_unchanged_shape():
    t = _template()
    g = build_graph(t, values={}, models={}, loras=())
    assert not [n for n in g.values() if n["class_type"] == "LoraLoader"]
    assert g["3"]["inputs"]["model"] == ["4", 0]
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --extra dev pytest tests/test_comfy_workflow.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_graph'`

- [ ] **Step 3: 구현**

`src/naiauto/core/backends/comfy_workflow.py`에 `import re`를 추가하고(`copy`도 여기서 필요하다), 파일 끝에 다음을 덧붙인다:

```python
#: 프롬프트에서 걷어낼 <lora:name:weight> 태그.
#: 파일명에 괄호가 들어갈 수 있어(hans_anima-kei_(blue_archive)_lora) ">"가 아닌
#: 모든 문자를 받는다.
_LORA_TAG_RE = re.compile(r"<lora:[^>]*>")

#: 태그를 뺀 자리에 남는 쉼표/공백 정리.
_TIDY_RE = re.compile(r"\s*,\s*")


@dataclass(frozen=True)
class LoraAssignment:
    """그래프에 결선할 LoRA 하나."""

    file: str
    weight: float = 1.0


def strip_lora_tags(text: str) -> str:
    """프롬프트에서 ``<lora:...>``를 빼고 남은 쉼표를 정리한다.

    기본 ComfyUI의 ``CLIPTextEncode``는 이 문법을 파싱하지 않고 그냥 문자열로
    인코딩한다 — 남겨 두면 결과를 오염시킨다.
    """
    cleaned = _LORA_TAG_RE.sub("", text)
    cleaned = _TIDY_RE.sub(", ", cleaned)
    return cleaned.strip().strip(",").strip()


def _next_node_id(graph: dict) -> str:
    """그래프에서 쓰이지 않은 숫자 노드 id."""
    used = {int(k) for k in graph if str(k).isdigit()}
    return str(max(used, default=0) + 1)


def _insert_lora_chain(
    graph: dict, template: WorkflowTemplate, loras: tuple[LoraAssignment, ...]
) -> None:
    """모델/CLIP 소비자들 앞에 ``LoraLoader`` 체인을 끼워 넣는다.

    체크포인트(또는 UNET) 출력을 받던 노드들이 대신 체인 끝을 받도록 재결선한다.
    ``delegate`` 모드에서는 부르지 않는다 — 확장이 같은 일을 하므로 두 번 걸린다.
    """
    if not loras:
        return
    # 체인의 시작점: 지금 model/clip을 내보내는 링크를 찾는다.
    model_src = None
    clip_src = None
    for node in graph.values():
        inputs = node.get("inputs", {})
        if model_src is None and isinstance(inputs.get("model"), list):
            model_src = list(inputs["model"])
        if clip_src is None and isinstance(inputs.get("clip"), list):
            clip_src = list(inputs["clip"])
    if model_src is None or clip_src is None:
        logger.warning(
            "%s: cannot find model/clip links to splice LoRA into, skipping", template.id
        )
        return

    for lora in loras:
        node_id = _next_node_id(graph)
        graph[node_id] = {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": lora.file,
                "strength_model": lora.weight,
                "strength_clip": lora.weight,
                "model": model_src,
                "clip": clip_src,
            },
        }
        model_src = [node_id, 0]
        clip_src = [node_id, 1]

    # 체인 뒤로 재결선 — 방금 만든 로더 자신은 건드리지 않는다.
    chain_ids = {model_src[0], clip_src[0]}
    for node_id, node in graph.items():
        if node.get("class_type") == "LoraLoader":
            continue
        inputs = node.get("inputs", {})
        if isinstance(inputs.get("model"), list):
            inputs["model"] = list(model_src)
        if isinstance(inputs.get("clip"), list):
            inputs["clip"] = list(clip_src)
    _ = chain_ids  # 가독성용 — 로더는 위 continue로 이미 제외된다


def build_graph(
    template: WorkflowTemplate,
    *,
    values: dict | None = None,
    models: dict[str, str] | None = None,
    loras: tuple[LoraAssignment, ...] = (),
) -> dict:
    """템플릿 + 값 → 큐에 넣을 그래프 (깊은 복사본).

    템플릿은 앱 수명 내내 재사용되므로 **원본을 절대 건드리지 않는다.**
    선언되지 않은 슬롯과 None/빈 값은 조용히 건너뛴다 — 템플릿마다 슬롯이 달라
    호출자가 전부를 알 수 없다.
    """
    values = values or {}
    models = models or {}
    graph = copy.deepcopy(template.graph)

    prompt_values = dict(values)
    if template.lora_mode == "direct":
        for key in ("positive", "negative"):
            if isinstance(prompt_values.get(key), str):
                prompt_values[key] = strip_lora_tags(prompt_values[key])
        _insert_lora_chain(graph, template, loras)

    for name, path in template.slots.items():
        if name not in prompt_values or prompt_values[name] is None:
            continue
        node_id, input_name = _split_path(path, f"{template.id}.slots.{name}")
        graph[node_id]["inputs"][input_name] = prompt_values[name]

    for name, slot in template.model_slots.items():
        chosen = models.get(name, "")
        if not chosen:
            continue
        node_id, input_name = _split_path(slot.path, f"{template.id}.model_slots.{name}")
        graph[node_id]["inputs"][input_name] = chosen

    return graph
```

`__all__`에 `"LoraAssignment"`, `"strip_lora_tags"`, `"build_graph"`를 추가한다.

**LoRA 체인 삽입은 이 계획에서 가장 까다로운 부분이다.** `_insert_lora_chain`이 첫 번째 `model`/`clip` 링크를 시작점으로 잡는데, 템플릿 그래프가 예상과 다르면 엉뚱한 곳에 끼울 수 있다. 테스트가 재결선까지 확인하니 실패하면 **테스트를 고치지 말고** 왜 다른지 보고하라.

- [ ] **Step 4: 통과 확인**

```
uv run --extra dev pytest tests/test_comfy_workflow.py -q
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

**실제 숫자를 보고하라.**

- [ ] **Step 5: 커밋**

```bash
git add src/naiauto/core/backends/comfy_workflow.py tests/test_comfy_workflow.py
git commit -m "$(cat <<'EOF'
feat(backends): 워크플로 값 주입과 LoRA 체인 결선

<lora:...>는 기본 ComfyUI의 CLIPTextEncode에서 아무 일도 하지 않고 문자열로
인코딩된다. direct 모드는 앱이 LoraLoader 체인을 끼우고 프롬프트에서 태그를
빼며, delegate 모드는 PCLazyLoraLoader에 맡기고 손대지 않는다 — 둘 다 하면
LoRA가 두 번 걸린다.

템플릿 그래프는 깊은 복사한다. 앱 수명 내내 재사용되므로 원본을 건드리면
다음 생성이 오염된다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 6: `/object_info` 파싱

**Files:**
- Create: `src/naiauto/core/backends/comfy_objects.py`
- Create: `tests/test_comfy_objects.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_comfy_objects.py`:

```python
"""/object_info 파싱 테스트 — 실제 응답 모양을 축약한 픽스처로 검증한다."""

from naiauto.core.backends.comfy_objects import ObjectInfo, parse_object_info

#: 실제 /object_info 응답의 모양 (필요한 부분만).
RAW = {
    "CheckpointLoaderSimple": {
        "input": {"required": {"ckpt_name": [["wai.safetensors", "other.safetensors"], {}]}}
    },
    "KSampler": {
        "input": {
            "required": {
                "seed": ["INT", {"default": 0}],
                "sampler_name": [["euler", "euler_ancestral", "dpmpp_2m"], {}],
                "scheduler": [["normal", "karras", "simple"], {}],
            }
        }
    },
    "UNETLoader": {
        "input": {"required": {"unet_name": [["Anima-2.9B-preview-v1.safetensors"], {}]}}
    },
    "PreviewImage": {"input": {"required": {"images": ["IMAGE", {}]}}},
}


def test_node_classes_lists_every_key():
    info = parse_object_info(RAW)
    assert "KSampler" in info.node_classes
    assert "UNETLoader" in info.node_classes


def test_options_reads_combo_lists():
    info = parse_object_info(RAW)
    assert info.options("CheckpointLoaderSimple.ckpt_name") == (
        "wai.safetensors",
        "other.safetensors",
    )
    assert info.options("KSampler.sampler_name") == ("euler", "euler_ancestral", "dpmpp_2m")
    assert info.options("KSampler.scheduler") == ("normal", "karras", "simple")


def test_options_empty_for_non_combo_input():
    """INT 같은 스칼라 입력은 선택지가 없다."""
    info = parse_object_info(RAW)
    assert info.options("KSampler.seed") == ()


def test_options_empty_for_unknown_paths():
    info = parse_object_info(RAW)
    assert info.options("NoSuchNode.foo") == ()
    assert info.options("KSampler.no_such_input") == ()
    assert info.options("malformed") == ()


def test_parse_tolerates_garbage():
    """서버 버전이 달라 모양이 어긋나도 크래시하면 안 된다."""
    assert parse_object_info({}).node_classes == frozenset()
    assert parse_object_info({"X": "not a dict"}).options("X.y") == ()
    assert parse_object_info({"X": {"input": None}}).options("X.y") == ()


def test_empty_info_is_falsy_and_usable():
    info = ObjectInfo.empty()
    assert not info.node_classes
    assert info.options("KSampler.sampler_name") == ()
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --extra dev pytest tests/test_comfy_objects.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'naiauto.core.backends.comfy_objects'`

- [ ] **Step 3: 구현**

`src/naiauto/core/backends/comfy_objects.py`:

```python
"""``/object_info`` 응답 파싱.

서버가 어떤 노드와 어떤 선택지를 갖고 있는지 알려주는 유일한 창구다. 이 앱은
두 가지에 쓴다: 템플릿의 ``requires_nodes`` 충족 여부 판단, 그리고 모델·샘플러
목록 채우기.

응답 모양은 ``{"NodeClass": {"input": {"required": {"name": [<옵션>, {...}]}}}}``이고,
``<옵션>``이 리스트면 콤보(선택지), 문자열이면 스칼라 타입("INT" 등)이다.

서버 버전에 따라 모양이 어긋날 수 있으므로 모든 접근을 방어적으로 한다 —
목록을 못 읽는 것과 앱이 죽는 것은 전혀 다른 문제다. Qt 의존성 없음.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ObjectInfo", "parse_object_info"]


@dataclass(frozen=True)
class ObjectInfo:
    """서버가 아는 노드 클래스와 입력 선택지."""

    node_classes: frozenset[str]
    #: "NodeClass.input_name" → 선택지 튜플
    _options: dict[str, tuple[str, ...]]

    @classmethod
    def empty(cls) -> ObjectInfo:
        """서버에 못 붙었을 때 쓰는 빈 정보."""
        return cls(node_classes=frozenset(), _options={})

    def options(self, path: str) -> tuple[str, ...]:
        """"NodeClass.input_name" → 선택지. 없으면 빈 튜플."""
        return self._options.get(path, ())


def parse_object_info(raw: object) -> ObjectInfo:
    """``/object_info`` JSON → ``ObjectInfo``. 어떤 입력에도 예외를 내지 않는다."""
    if not isinstance(raw, dict):
        return ObjectInfo.empty()
    options: dict[str, tuple[str, ...]] = {}
    for node_class, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        inputs = spec.get("input")
        if not isinstance(inputs, dict):
            continue
        for section in ("required", "optional"):
            fields = inputs.get(section)
            if not isinstance(fields, dict):
                continue
            for input_name, definition in fields.items():
                if not isinstance(definition, list) or not definition:
                    continue
                choices = definition[0]
                # 리스트면 콤보, 문자열이면 스칼라 타입("INT" 등)이다.
                if isinstance(choices, list):
                    options[f"{node_class}.{input_name}"] = tuple(
                        str(c) for c in choices
                    )
    return ObjectInfo(node_classes=frozenset(map(str, raw)), _options=options)
```

- [ ] **Step 4: 통과 확인**

```
uv run --extra dev pytest tests/test_comfy_objects.py -q
uv run --extra dev ruff check src tests
```

- [ ] **Step 5: 커밋**

```bash
git add src/naiauto/core/backends/comfy_objects.py tests/test_comfy_objects.py
git commit -m "$(cat <<'EOF'
feat(backends): /object_info 파싱

서버가 어떤 노드와 선택지를 갖는지 아는 유일한 창구다. 서버 버전에 따라 응답
모양이 어긋날 수 있어 모든 접근을 방어적으로 한다 — 목록을 못 읽는 것과 앱이
죽는 것은 다른 문제다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 7: WebSocket 진행 리스너

**Files:**
- Create: `src/naiauto/core/backends/comfy_progress.py`
- Modify: `pyproject.toml`
- Modify: `packaging/nai-auto-v5.spec`
- Create: `tests/test_comfy_progress.py`

- [ ] **Step 1: 의존성을 추가한다**

`pyproject.toml`의 `dependencies` 리스트 끝(`"lmstudio>=1.5.0",` 뒤)에 추가:

```toml
    # ComfyUI 생성 진행률 — HTTP로는 스텝 진행을 알 수 없어 WebSocket이 유일한 길이다.
    # WD14·lmstudio와 같은 이유로 필수 의존성이다 (선택 의존성이면 exe 사용자가 쓸 수 없다).
    "websocket-client>=1.7",
```

`packaging/nai-auto-v5.spec`의 `hiddenimports` 리스트에 `"websocket",`을 추가한다 (`"typing_extensions",` 옆).

Run: `uv run --extra dev python -c "import websocket; print(websocket.__version__)"`
Expected: 버전이 찍힌다.

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`tests/test_comfy_progress.py`:

```python
"""WS 메시지 해석 테스트 — 실제 소켓 없이 메시지 파싱만 검증한다."""

import json

from naiauto.core.backends.comfy_progress import (
    Executed,
    ExecutionFailed,
    Progress,
    parse_message,
)

PID = "11111111-1111-1111-1111-111111111111"


def test_progress_state_v034():
    """v0.34는 노드별 progress_state를 보낸다."""
    raw = json.dumps(
        {
            "type": "progress_state",
            "data": {
                "prompt_id": PID,
                "nodes": {"3": {"value": 7, "max": 28, "state": "running"}},
            },
        }
    )
    msg = parse_message(raw, PID)
    assert isinstance(msg, Progress)
    assert msg.value == 7
    assert msg.max_value == 28


def test_legacy_progress_message():
    """구버전 서버는 progress {value, max}를 보낸다 — 둘 다 받는다."""
    raw = json.dumps({"type": "progress", "data": {"value": 3, "max": 20, "prompt_id": PID}})
    msg = parse_message(raw, PID)
    assert isinstance(msg, Progress)
    assert msg.value == 3
    assert msg.max_value == 20


def test_executed_carries_images():
    """executed가 출력을 직접 실어 온다 — /history 폴링이 필요 없는 이유다."""
    raw = json.dumps(
        {
            "type": "executed",
            "data": {
                "node": "9",
                "prompt_id": PID,
                "output": {
                    "images": [
                        {"filename": "x_temp_abcde_00001_.png", "subfolder": "", "type": "temp"}
                    ]
                },
            },
        }
    )
    msg = parse_message(raw, PID)
    assert isinstance(msg, Executed)
    assert msg.node == "9"
    assert msg.images == ({"filename": "x_temp_abcde_00001_.png", "subfolder": "", "type": "temp"},)


def test_execution_error():
    raw = json.dumps(
        {
            "type": "execution_error",
            "data": {
                "prompt_id": PID,
                "node_id": "3",
                "node_type": "KSampler",
                "exception_message": "out of memory",
            },
        }
    )
    msg = parse_message(raw, PID)
    assert isinstance(msg, ExecutionFailed)
    assert msg.node_type == "KSampler"
    assert "out of memory" in msg.message


def test_other_prompt_ids_are_ignored():
    """여러 클라이언트가 붙어 있을 수 있다 — 남의 작업 메시지를 먹으면 안 된다."""
    raw = json.dumps(
        {"type": "executed", "data": {"node": "9", "prompt_id": "other", "output": {}}}
    )
    assert parse_message(raw, PID) is None


def test_unknown_and_malformed_are_ignored():
    assert parse_message(json.dumps({"type": "status", "data": {}}), PID) is None
    assert parse_message("not json", PID) is None
    assert parse_message(json.dumps([1, 2, 3]), PID) is None
    assert parse_message(b"\x00\x01binary", PID) is None


def test_executed_without_images_is_ignored():
    """미리보기 노드가 아닌 노드도 executed를 낸다."""
    raw = json.dumps({"type": "executed", "data": {"node": "4", "prompt_id": PID, "output": {}}})
    assert parse_message(raw, PID) is None
```

- [ ] **Step 3: 실패 확인**

Run: `uv run --extra dev pytest tests/test_comfy_progress.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'naiauto.core.backends.comfy_progress'`

- [ ] **Step 4: 구현**

`src/naiauto/core/backends/comfy_progress.py`:

```python
"""ComfyUI WebSocket 메시지 해석.

메시지 파싱과 소켓 입출력을 나눈다 — 파싱은 순수 함수라 실제 서버 없이
테스트할 수 있고, 실제로 버전차가 드러나는 곳이 여기다.

v0.34는 노드별 ``progress_state``를 보내고, 구버전은 ``progress``를 보낸다.
둘 다 받는다. ``executed``는 출력(이미지 목록)을 직접 실어 오므로 ``/history``
폴링이 필요 없다.

Qt 의존성 없음.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = ["Progress", "Executed", "ExecutionFailed", "parse_message"]


@dataclass(frozen=True)
class Progress:
    """샘플링 진행률."""

    value: int
    max_value: int


@dataclass(frozen=True)
class Executed:
    """노드가 출력을 냈다."""

    node: str
    images: tuple[dict, ...]


@dataclass(frozen=True)
class ExecutionFailed:
    """실행 중 노드가 예외를 냈다."""

    message: str
    node_id: str = ""
    node_type: str = ""


def parse_message(raw: object, prompt_id: str) -> Progress | Executed | ExecutionFailed | None:
    """WS 프레임 하나 → 이벤트. 관심 없거나 남의 작업이면 None.

    바이너리 프레임(미리보기 이미지)과 모양이 어긋난 JSON은 조용히 무시한다 —
    서버 버전이 달라도 앱이 죽으면 안 된다.
    """
    if isinstance(raw, (bytes, bytearray)):
        return None  # 바이너리 프리뷰 프레임 — 이번 범위에서는 쓰지 않는다
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    # prompt_id가 있으면 우리 작업인지 확인한다. 없는 메시지는 통과시킨다
    # (일부 메시지는 id를 싣지 않는다).
    incoming = data.get("prompt_id")
    if incoming is not None and str(incoming) != prompt_id:
        return None

    kind = payload.get("type")
    if kind == "progress_state":
        nodes = data.get("nodes")
        if not isinstance(nodes, dict):
            return None
        for state in nodes.values():
            if not isinstance(state, dict):
                continue
            value, maximum = state.get("value"), state.get("max")
            if isinstance(value, (int, float)) and isinstance(maximum, (int, float)) and maximum:
                return Progress(value=int(value), max_value=int(maximum))
        return None
    if kind == "progress":
        value, maximum = data.get("value"), data.get("max")
        if isinstance(value, (int, float)) and isinstance(maximum, (int, float)) and maximum:
            return Progress(value=int(value), max_value=int(maximum))
        return None
    if kind == "executed":
        output = data.get("output")
        images = output.get("images") if isinstance(output, dict) else None
        if not isinstance(images, list) or not images:
            return None
        return Executed(
            node=str(data.get("node", "")),
            images=tuple(i for i in images if isinstance(i, dict)),
        )
    if kind == "execution_error":
        return ExecutionFailed(
            message=str(data.get("exception_message", "execution failed")),
            node_id=str(data.get("node_id", "")),
            node_type=str(data.get("node_type", "")),
        )
    return None
```

- [ ] **Step 5: 통과 확인**

```
uv run --extra dev pytest tests/test_comfy_progress.py -q
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

- [ ] **Step 6: 커밋**

```bash
git add pyproject.toml packaging/nai-auto-v5.spec src/naiauto/core/backends/comfy_progress.py tests/test_comfy_progress.py
git commit -m "$(cat <<'EOF'
feat(backends): ComfyUI WebSocket 메시지 해석

파싱과 소켓 입출력을 나눈다 — 버전차가 드러나는 곳이 파싱이라 서버 없이
테스트해야 한다. v0.34의 progress_state와 구버전 progress를 둘 다 받는다.
executed가 출력을 직접 실어 오므로 /history 폴링은 필요 없다.

websocket-client를 필수 의존성으로 추가한다. HTTP로는 스텝 진행을 알 수 없고,
선택 의존성이면 exe 사용자가 쓸 수 없다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

---

## Task 8: ComfyUI 백엔드 본체

**Files:**
- Create: `src/naiauto/core/backends/comfyui.py`
- Create: `tests/test_comfy_backend.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_comfy_backend.py`:

```python
"""ComfyUI 백엔드 테스트 — HTTP/WS를 스텁으로 갈아 끼운다."""

import json

import pytest

from naiauto.core.api.models import GenerationRequest
from naiauto.core.backends.comfy_workflow import parse_template
from naiauto.core.backends.comfyui import ComfyUIBackend
from naiauto.core.backends.errors import (
    ComfyConnectionError,
    ComfyExecutionError,
    ComfyPromptRejectedError,
    ComfyTemplateError,
    ComfyTimeoutError,
)

PID = "11111111-1111-1111-1111-111111111111"

TEMPLATE = parse_template(
    {
        "id": "t",
        "name": "T",
        "output_node": "9",
        "model_slots": {
            "checkpoint": {"path": "4.ckpt_name", "from": "CheckpointLoaderSimple.ckpt_name"}
        },
        "slots": {"positive": "6.text", "seed": "3.seed"},
        "graph": {
            "3": {"inputs": {"seed": 0, "model": ["4", 0]}, "class_type": "KSampler"},
            "4": {"inputs": {"ckpt_name": ""}, "class_type": "CheckpointLoaderSimple"},
            "6": {"inputs": {"text": "", "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
            "9": {"inputs": {"images": ["8", 0]}, "class_type": "PreviewImage"},
        },
    }
)

EXECUTED = json.dumps(
    {
        "type": "executed",
        "data": {
            "node": "9",
            "prompt_id": PID,
            "output": {"images": [{"filename": "a.png", "subfolder": "", "type": "temp"}]},
        },
    }
)


class _StubWS:
    """websocket.WebSocket 대역 — 미리 정한 프레임을 차례로 돌려준다."""

    def __init__(self, frames, on_close=None):
        self._frames = list(frames)
        self.connected_url = None
        self.closed = False
        self._on_close = on_close

    def connect(self, url, **kwargs):
        self.connected_url = url

    def recv(self):
        if not self._frames:
            raise ConnectionError("socket closed")
        return self._frames.pop(0)

    def settimeout(self, value):
        pass

    def close(self):
        self.closed = True
        if self._on_close:
            self._on_close()


def _backend(monkeypatch, *, frames=(EXECUTED,), post=None, view=b"PNG", history=None):
    """스텁 HTTP/WS를 끼운 백엔드."""
    calls = {"post": [], "get": [], "ws": None}

    def _post_json(url, payload, **kwargs):
        calls["post"].append((url, payload))
        if post is not None:
            return post(url, payload)
        return {"prompt_id": PID, "number": 1, "node_errors": {}}

    def _get_bytes(url, **kwargs):
        calls["get"].append(url)
        return view

    def _get_json(url, **kwargs):
        calls["get"].append(url)
        return history if history is not None else {}

    ws = _StubWS(frames)
    calls["ws"] = ws

    backend = ComfyUIBackend(
        base_url="http://127.0.0.1:8188",
        template=TEMPLATE,
        model_slots={"checkpoint": "wai.safetensors"},
        timeout=1.0,
    )
    monkeypatch.setattr(backend, "_post_json", _post_json)
    monkeypatch.setattr(backend, "_get_bytes", _get_bytes)
    monkeypatch.setattr(backend, "_get_json", _get_json)
    monkeypatch.setattr(backend, "_make_socket", lambda: ws)
    monkeypatch.setattr(backend, "_new_prompt_id", lambda: PID)
    return backend, calls


REQ = GenerationRequest(prompt="1girl", negative_prompt="bad", seed=42, width=832, height=1216)


def test_generate_returns_image_bytes(monkeypatch):
    backend, calls = _backend(monkeypatch)
    result = backend.generate(REQ)
    assert result.raw_bytes == b"PNG"


def test_websocket_opens_before_post(monkeypatch):
    """POST가 먼저면 짧은 생성에서 executed를 놓쳐 영원히 기다린다."""
    order = []
    ws = _StubWS([EXECUTED])

    backend = ComfyUIBackend(
        base_url="http://127.0.0.1:8188", template=TEMPLATE, model_slots={}, timeout=1.0
    )

    def _connect(url, **kwargs):
        order.append("ws")

    ws.connect = _connect
    monkeypatch.setattr(backend, "_make_socket", lambda: ws)
    monkeypatch.setattr(backend, "_new_prompt_id", lambda: PID)
    monkeypatch.setattr(
        backend,
        "_post_json",
        lambda url, payload, **kw: (order.append("post"), {"prompt_id": PID})[1],
    )
    monkeypatch.setattr(backend, "_get_bytes", lambda url, **kw: b"PNG")
    backend.generate(REQ)
    assert order == ["ws", "post"]


def test_our_prompt_id_is_sent(monkeypatch):
    backend, calls = _backend(monkeypatch)
    backend.generate(REQ)
    _, payload = calls["post"][0]
    assert payload["prompt_id"] == PID
    assert payload["client_id"]


def test_slots_are_injected_into_posted_graph(monkeypatch):
    backend, calls = _backend(monkeypatch)
    backend.generate(REQ)
    _, payload = calls["post"][0]
    graph = payload["prompt"]
    assert graph["6"]["inputs"]["text"] == "1girl"
    assert graph["3"]["inputs"]["seed"] == 42
    assert graph["4"]["inputs"]["ckpt_name"] == "wai.safetensors"


def test_view_uses_temp_type(monkeypatch):
    backend, calls = _backend(monkeypatch)
    backend.generate(REQ)
    view_url = next(u for u in calls["get"] if "/view" in u)
    assert "type=temp" in view_url
    assert "filename=a.png" in view_url


def test_prompt_rejected_surfaces_node_errors(monkeypatch):
    node_errors = {"4": {"errors": [{"message": "value not in list"}]}}

    def _post(url, payload):
        raise ComfyPromptRejectedError("400", node_errors=node_errors)

    backend, _ = _backend(monkeypatch, post=_post)
    with pytest.raises(ComfyPromptRejectedError) as exc:
        backend.generate(REQ)
    assert exc.value.node_errors == node_errors


def test_execution_error_is_raised(monkeypatch):
    frame = json.dumps(
        {
            "type": "execution_error",
            "data": {
                "prompt_id": PID,
                "node_id": "3",
                "node_type": "KSampler",
                "exception_message": "boom",
            },
        }
    )
    backend, _ = _backend(monkeypatch, frames=[frame])
    with pytest.raises(ComfyExecutionError) as exc:
        backend.generate(REQ)
    assert exc.value.node_type == "KSampler"


def test_socket_drop_falls_back_to_history(monkeypatch):
    history = {
        PID: {"outputs": {"9": {"images": [{"filename": "h.png", "subfolder": "", "type": "temp"}]}}}
    }
    backend, calls = _backend(monkeypatch, frames=[], history=history)
    result = backend.generate(REQ)
    assert result.raw_bytes == b"PNG"
    assert any("/history/" in u for u in calls["get"])


def test_socket_drop_without_history_raises(monkeypatch):
    backend, _ = _backend(monkeypatch, frames=[], history={})
    with pytest.raises(ComfyTimeoutError):
        backend.generate(REQ)


def test_stop_sends_interrupt(monkeypatch):
    """중지 시 서버가 큐에 든 작업을 계속 돌리지 않도록 명시적으로 끊는다."""
    backend, calls = _backend(monkeypatch, frames=[])
    monkeypatch.setattr(backend, "_get_json", lambda url, **kw: {})
    backend.request_stop()
    with pytest.raises(ComfyTimeoutError):
        backend.generate(REQ)
    assert any("/interrupt" in url for url, _ in calls["post"])


def test_missing_template_raises(monkeypatch):
    backend = ComfyUIBackend(
        base_url="http://127.0.0.1:8188", template=None, model_slots={}, timeout=1.0
    )
    with pytest.raises(ComfyTemplateError):
        backend.generate(REQ)


def test_connection_failure_is_wrapped(monkeypatch):
    backend = ComfyUIBackend(
        base_url="http://127.0.0.1:8188", template=TEMPLATE, model_slots={}, timeout=1.0
    )

    def _boom():
        raise OSError("refused")

    monkeypatch.setattr(backend, "_make_socket", _boom)
    with pytest.raises(ComfyConnectionError):
        backend.generate(REQ)


def test_supports_credit_is_false():
    backend = ComfyUIBackend(
        base_url="http://127.0.0.1:8188", template=TEMPLATE, model_slots={}, timeout=1.0
    )
    assert backend.supports_credit is False
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --extra dev pytest tests/test_comfy_backend.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'naiauto.core.backends.comfyui'`

- [ ] **Step 3: 구현**

`src/naiauto/core/backends/comfyui.py`를 만든다. 구조는 다음과 같다 — 테스트가 monkeypatch하는 `_post_json` / `_get_bytes` / `_get_json` / `_make_socket` / `_new_prompt_id`를 **반드시 이 이름의 메서드로** 두어야 한다 (그래야 네트워크 없이 테스트할 수 있다).

```python
"""ComfyUI 생성 백엔드.

흐름:
  1. prompt_id·client_id를 우리가 만든다 (서버가 canonical UUID를 받아 준다)
  2. WS를 **먼저** 연다 — POST가 먼저면 짧은 생성에서 executed를 놓친다
  3. POST /prompt
  4. WS에서 executed를 기다린다 (progress는 콜백으로 흘린다)
  5. GET /view로 이미지 바이트를 가져온다

/history 폴링은 하지 않는다 — executed가 출력을 직접 실어 온다. 소켓이 끊긴
경우에만 /history/{prompt_id}를 1회 확인한다.

Qt 의존성 없음.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from urllib.parse import urlencode, urlparse, urlunparse

import requests

from naiauto.core.api.models import GenerationRequest, GenerationResult
from naiauto.core.backends.comfy_progress import (
    Executed,
    ExecutionFailed,
    Progress,
    parse_message,
)
from naiauto.core.backends.comfy_workflow import (
    LoraAssignment,
    WorkflowTemplate,
    build_graph,
)
from naiauto.core.backends.errors import (
    ComfyConnectionError,
    ComfyExecutionError,
    ComfyPromptRejectedError,
    ComfyTemplateError,
    ComfyTimeoutError,
)

logger = logging.getLogger(__name__)

__all__ = ["ComfyUIBackend"]


class ComfyUIBackend:
    """로컬 ComfyUI로 txt2img를 돌리는 백엔드."""

    #: 로컬 서버에는 Anlas/크레딧 개념이 없다 (backends.base 참고).
    supports_credit = False

    def __init__(
        self,
        *,
        base_url: str,
        template: WorkflowTemplate | None,
        model_slots: dict[str, str],
        timeout: float = 300.0,
        loras: tuple[LoraAssignment, ...] = (),
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.template = template
        self.model_slots = dict(model_slots)
        self.timeout = timeout
        self.loras = loras
        self._on_progress = on_progress
        self._stop = threading.Event()

    # -- 중지 ----------------------------------------------------------

    def request_stop(self) -> None:
        """다음 생성부터 중단한다 (GenerationService의 중지와 짝을 이룬다)."""
        self._stop.set()

    def clear_stop(self) -> None:
        self._stop.clear()

    # -- 네트워크 경계 (테스트가 이 다섯 개를 갈아 끼운다) ----------------

    def _new_prompt_id(self) -> str:
        return str(uuid.uuid4())

    def _make_socket(self):
        import websocket  # lazy — import 비용을 앱 시작에서 뺀다

        return websocket.WebSocket()

    def _post_json(self, url: str, payload: dict) -> dict:
        try:
            resp = requests.post(url, json=payload, timeout=30)
        except requests.RequestException as exc:
            raise ComfyConnectionError(f"cannot reach ComfyUI at {self.base_url}: {exc}") from exc
        if resp.status_code == 400:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            raise ComfyPromptRejectedError(
                str(body.get("error", {}).get("message", "prompt rejected")),
                node_errors=body.get("node_errors") or {},
            )
        resp.raise_for_status()
        return resp.json()

    def _get_json(self, url: str) -> dict:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise ComfyConnectionError(f"cannot reach ComfyUI at {self.base_url}: {exc}") from exc

    def _get_bytes(self, url: str) -> bytes:
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            raise ComfyConnectionError(f"cannot fetch image: {exc}") from exc

    # -- 생성 ----------------------------------------------------------

    def generate(self, req: GenerationRequest) -> GenerationResult:
        if self.template is None:
            raise ComfyTemplateError("no workflow template selected")

        prompt_id = self._new_prompt_id()
        client_id = str(uuid.uuid4())
        graph = build_graph(
            self.template,
            values=self._values(req),
            models=self.model_slots,
            loras=self.loras,
        )

        socket = self._open_socket(client_id)
        try:
            self._post_json(
                f"{self.base_url}/prompt",
                {"prompt": graph, "client_id": client_id, "prompt_id": prompt_id},
            )
            images = self._await_images(socket, prompt_id)
        finally:
            try:
                socket.close()
            except Exception:  # noqa: BLE001 - 닫기 실패는 결과에 영향이 없다
                logger.debug("closing ComfyUI websocket failed", exc_info=True)

        return GenerationResult(raw_bytes=self._fetch_image(images[0]))

    def _values(self, req: GenerationRequest) -> dict:
        """``GenerationRequest`` → 슬롯 값. 템플릿이 모르는 키는 무시된다."""
        return {
            "positive": req.prompt,
            "negative": req.negative_prompt,
            "seed": req.seed,
            "steps": req.steps,
            "cfg": req.cfg_scale,
            "sampler": req.sampler,
            "scheduler": req.scheduler,
            "width": req.width,
            "height": req.height,
        }

    def _open_socket(self, client_id: str):
        """WS를 연다. **POST보다 먼저** 불러야 한다."""
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        url = urlunparse((scheme, parsed.netloc, "/ws", "", f"clientId={client_id}", ""))
        try:
            socket = self._make_socket()
            socket.connect(url)
            return socket
        except Exception as exc:  # noqa: BLE001 - 소켓 라이브러리마다 예외가 다르다
            raise ComfyConnectionError(
                f"cannot open ComfyUI websocket at {self.base_url}: {exc}"
            ) from exc

    def _await_images(self, socket, prompt_id: str) -> tuple[dict, ...]:
        """executed를 기다린다. 소켓이 끊기면 /history를 1회 확인한다."""
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self._stop.is_set():
                self._interrupt()
                raise ComfyTimeoutError("generation stopped by user")
            try:
                frame = socket.recv()
            except Exception:  # noqa: BLE001 - 끊김은 정상 종료일 수도 있다
                break
            message = parse_message(frame, prompt_id)
            if isinstance(message, Progress):
                if self._on_progress is not None:
                    self._on_progress(message.value, message.max_value)
                continue
            if isinstance(message, ExecutionFailed):
                raise ComfyExecutionError(
                    message.message, node_id=message.node_id, node_type=message.node_type
                )
            if isinstance(message, Executed) and message.node == self.template.output_node:
                return message.images
        images = self._images_from_history(prompt_id)
        if images:
            return images
        raise ComfyTimeoutError(f"no image from ComfyUI within {self.timeout:.0f}s")

    def _images_from_history(self, prompt_id: str) -> tuple[dict, ...]:
        """소켓이 끊겼을 때의 폴백 — 1회만 확인한다."""
        try:
            history = self._get_json(f"{self.base_url}/history/{prompt_id}")
        except ComfyConnectionError:
            return ()
        entry = history.get(prompt_id) if isinstance(history, dict) else None
        outputs = entry.get("outputs") if isinstance(entry, dict) else None
        node = outputs.get(self.template.output_node) if isinstance(outputs, dict) else None
        images = node.get("images") if isinstance(node, dict) else None
        if isinstance(images, list) and images:
            return tuple(i for i in images if isinstance(i, dict))
        return ()

    def _interrupt(self) -> None:
        """서버가 큐에 든 작업을 계속 돌리지 않도록 끊는다."""
        try:
            self._post_json(f"{self.base_url}/interrupt", {})
        except (ComfyConnectionError, ComfyPromptRejectedError):
            logger.debug("interrupt failed", exc_info=True)

    def _fetch_image(self, image: dict) -> bytes:
        query = urlencode(
            {
                "filename": image.get("filename", ""),
                "subfolder": image.get("subfolder", ""),
                "type": image.get("type", "temp"),
            }
        )
        return self._get_bytes(f"{self.base_url}/view?{query}")
```

`json`이 미사용이면 import에서 빼라. ruff 결과를 보고 판단하고 보고하라.

- [ ] **Step 4: 통과 확인**

```
uv run --extra dev pytest tests/test_comfy_backend.py -q
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

**실제 숫자를 보고하라.** 테스트가 스텁 메서드 이름에 의존하므로, 구현에서 이름을 바꿨다면 테스트가 아니라 구현을 되돌려라.

- [ ] **Step 5: `__init__.py`에 노출한다**

`src/naiauto/core/backends/__init__.py`를 다음으로 교체:

```python
"""이미지 생성 백엔드 (NovelAI / 로컬 ComfyUI).

Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

from naiauto.core.backends.base import ImageBackend, backend_supports_credit
from naiauto.core.backends.comfy_objects import ObjectInfo, parse_object_info
from naiauto.core.backends.comfy_workflow import (
    LoraAssignment,
    WorkflowTemplate,
    build_graph,
    find_workflow,
    load_workflows,
)
from naiauto.core.backends.comfyui import ComfyUIBackend
from naiauto.core.backends.errors import ComfyError

__all__ = [
    "ImageBackend",
    "backend_supports_credit",
    "ComfyUIBackend",
    "ComfyError",
    "ObjectInfo",
    "parse_object_info",
    "WorkflowTemplate",
    "LoraAssignment",
    "load_workflows",
    "find_workflow",
    "build_graph",
]
```

- [ ] **Step 6: 커밋**

```bash
git add src/naiauto/core/backends tests/test_comfy_backend.py
git commit -m "$(cat <<'EOF'
feat(backends): ComfyUI 백엔드 본체

WS를 POST보다 먼저 연다 — 반대로 하면 짧은 생성에서 executed를 놓쳐 영원히
기다린다. prompt_id를 우리가 만들어 보내므로 서버 발급 id를 나중에 맞추는
경합이 없다. 400 응답의 node_errors는 뭉뚱그리지 않고 그대로 예외에 싣는다.

네트워크 경계를 다섯 메서드로 좁혀 두어 서버 없이 테스트한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01FyotVRmZsZSPLS5Dj8Wsou
EOF
)"
```

## Task 9: 설정 스키마

**Files:**
- Modify: `src/naiauto/core/settings/schema.py`
- Modify: `src/naiauto/ui/options_dialog.py`
- Modify: `tests/test_settings.py` (없으면 `tests/test_settings_schema.py`를 새로 만든다 — **먼저 `ls tests/ | grep settings`로 확인하고 보고하라**)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

설정 테스트 파일 끝에 덧붙인다:

```python
def test_comfyui_settings_defaults():
    from naiauto.core.settings.schema import AppSettings

    s = AppSettings()
    assert s.generation_backend == "novelai"
    assert s.comfyui.base_url == "http://127.0.0.1:8188"
    assert s.comfyui.template_id == "sdxl_basic"
    assert s.comfyui.model_slots == {}
    assert s.comfyui.timeout_seconds == 300.0
    assert s.comfyui.workflows_dir == ""


def test_old_settings_file_loads_without_migration(tmp_path):
    """새 필드가 전부 기본값을 가지므로 기존 settings.json이 그대로 열린다."""
    import json

    from naiauto.core.settings.schema import AppSettings

    old = {"schema_version": 1, "language": "ko"}
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    s = AppSettings.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert s.generation_backend == "novelai"


def test_model_slots_are_nested_per_template():
    """슬롯 이름은 템플릿마다 다르므로 템플릿 id로 한 겹 감싼다."""
    from naiauto.core.settings.schema import AppSettings

    s = AppSettings()
    s.comfyui.model_slots["anima"] = {"unet": "a.safetensors", "vae": "b.safetensors"}
    dumped = s.model_dump()
    restored = AppSettings.model_validate(dumped)
    assert restored.comfyui.model_slots["anima"]["unet"] == "a.safetensors"


def test_comfyui_fields_are_owned_by_options_dialog():
    """옵션 페이지가 편집하는 필드는 OWNED_FIELDS에 있어야 저장된다."""
    from naiauto.ui.options_dialog import OWNED_FIELDS

    assert "comfyui" in OWNED_FIELDS
    assert "generation_backend" in OWNED_FIELDS
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --extra dev pytest tests/test_settings*.py -q`
Expected: FAIL — `AttributeError: 'AppSettings' object has no attribute 'generation_backend'`

- [ ] **Step 3: 스키마를 넓힌다**

`src/naiauto/core/settings/schema.py`에서 `class AppSettings` **바로 앞**에 넣는다 (`LMStudioSettings` 다음):

```python
class ComfyUISettings(BaseModel):
    """로컬 ComfyUI 백엔드 설정 (스펙 §6.1).

    ``model_slots``가 중첩 dict인 이유는 슬롯 이름과 개수가 템플릿마다 다르기
    때문이다 — SDXL은 ``checkpoint`` 하나지만 Anima는 UNET+CLIP+VAE+터보 네 개다.
    템플릿을 바꿔 가며 써도 각자의 선택이 남는다.
    """

    base_url: str = "http://127.0.0.1:8188"
    template_id: str = "sdxl_basic"
    #: 템플릿 id → {슬롯명: 모델 파일명}
    model_slots: dict[str, dict[str, str]] = Field(default_factory=dict)
    timeout_seconds: float = 300.0
    #: 사용자 워크플로 템플릿 폴더 ("" = 내장만)
    workflows_dir: str = ""
```

`AppSettings`에 두 필드를 추가한다. `generation_backend`는 `measure_credit` 다음
줄에, `comfyui`는 중첩 모델들이 모인 끝(`lmstudio` 다음)에 둔다:

```python
    #: "novelai" | "comfyui" — 어느 백엔드로 생성할지 (스펙 §6.3)
    generation_backend: str = "novelai"
```

```python
    comfyui: ComfyUISettings = Field(default_factory=ComfyUISettings)
```

`schema_version`은 **올리지 않는다.** 새 필드가 전부 기본값을 가져 기존 파일이
마이그레이션 없이 열리므로, 버전을 올리면 실익 없이 마이그레이션 코드만 는다.

`src/naiauto/ui/options_dialog.py`의 `OWNED_FIELDS` 끝(`"compiler",` 다음)에 추가:

```python
    "generation_backend",
    "comfyui",
```

- [ ] **Step 4: 통과 확인**

```
uv run --extra dev pytest tests/test_settings*.py -q
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

**실제 숫자를 보고하라.**

- [ ] **Step 5: 커밋**

```bash
git add src/naiauto/core/settings/schema.py src/naiauto/ui/options_dialog.py tests/
git commit -m "$(cat <<'EOF'
feat(settings): ComfyUI 백엔드 설정

model_slots를 템플릿 id로 한 겹 감싼다 — 슬롯 이름과 개수가 템플릿마다 달라서
평평한 dict로는 템플릿을 바꿀 때 선택이 뒤섞인다.

새 필드가 전부 기본값을 가지므로 schema_version은 올리지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014dbUAFcV3ZCP26Yt2P6Fyo
EOF
)"
```

---

## Task 10: 나머지 내장 템플릿 2종과 무결성 테스트

**Files:**
- Create: `src/naiauto/resources/comfy_workflows/sdxl_regional.json`
- Create: `src/naiauto/resources/comfy_workflows/anima.json`
- Create: `tests/test_comfy_templates.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_comfy_templates.py`:

```python
"""내장 템플릿 무결성 — 저작 실수를 CI에서 잡는다.

parse_template이 이미 슬롯 경로를 검증하므로, 여기서는 "내장 3종이 모두
파싱된다"와 "우리가 약속한 슬롯이 실제로 있다"를 확인한다.
"""

import json

import pytest

from naiauto.core.backends.comfy_workflow import (
    LORA_MODES,
    builtin_workflows_dir,
    load_workflows,
    parse_template,
)

#: 백엔드의 `_values()`가 채우는 키 — 템플릿이 모르는 키는 무시되지만,
#: 내장 템플릿은 전부 선언해야 메인 창 값이 실제로 반영된다.
REQUIRED_SLOTS = (
    "positive",
    "negative",
    "seed",
    "steps",
    "cfg",
    "sampler",
    "scheduler",
    "width",
    "height",
)

BUILTIN_IDS = ("sdxl_basic", "sdxl_regional", "anima")


def _builtins():
    return {t.id: t for t in load_workflows()}


@pytest.mark.parametrize("template_id", BUILTIN_IDS)
def test_builtin_parses(template_id):
    assert template_id in _builtins()


@pytest.mark.parametrize("template_id", BUILTIN_IDS)
def test_builtin_declares_every_slot(template_id):
    template = _builtins()[template_id]
    missing = [s for s in REQUIRED_SLOTS if s not in template.slots]
    assert missing == [], f"{template_id}에 슬롯이 빠졌다: {missing}"


@pytest.mark.parametrize("template_id", BUILTIN_IDS)
def test_builtin_lora_mode_is_valid(template_id):
    assert _builtins()[template_id].lora_mode in LORA_MODES


@pytest.mark.parametrize("template_id", BUILTIN_IDS)
def test_builtin_has_model_slots(template_id):
    assert _builtins()[template_id].model_slots


def test_every_json_in_builtin_dir_parses():
    """폴더에 넣었는데 조용히 건너뛰어지는 파일이 없어야 한다.

    load_workflows는 파손된 파일을 로그만 남기고 넘어가므로, 내장 폴더는
    여기서 따로 엄격하게 본다.
    """
    for path in sorted(builtin_workflows_dir().glob("*.json")):
        parse_template(json.loads(path.read_text(encoding="utf-8")))


def test_output_is_preview_image_not_save_image():
    """SaveImage를 쓰면 ComfyUI output 폴더에 사본이 남는다 (스펙 §3.7)."""
    for template in _builtins().values():
        node = template.graph[template.output_node]
        assert node["class_type"] == "PreviewImage", template.id


def test_batch_size_is_pinned_to_one():
    """배치 장수는 앱의 루프가 돈다 — 그래프가 한 번에 여러 장을 만들면 안 된다."""
    for template in _builtins().values():
        for node in template.graph.values():
            if "batch_size" in node.get("inputs", {}):
                assert node["inputs"]["batch_size"] == 1, template.id


def test_regional_template_delegates_lora():
    """확장이 <lora:...>를 처리하므로 우리가 또 결선하면 두 번 걸린다 (§3.5)."""
    assert _builtins()["sdxl_regional"].lora_mode == "delegate"
    assert "PCLazyTextEncode" in _builtins()["sdxl_regional"].requires_nodes


def test_anima_declares_three_loaders_plus_turbo():
    slots = _builtins()["anima"].model_slots
    assert set(slots) == {"unet", "clip", "vae", "turbo_lora"}
```

- [ ] **Step 2: 실패 확인**

Run: `uv run --extra dev pytest tests/test_comfy_templates.py -q`
Expected: FAIL — `sdxl_regional`, `anima`가 없어서 `KeyError` / assert 실패. `sdxl_basic`도 `negative` 외 슬롯은 있으므로 `test_builtin_declares_every_slot`은 통과한다.

- [ ] **Step 3: `sdxl_regional.json`을 만든다**

`sdxl_basic`과 그래프 골격은 같고, `CLIPTextEncode` 두 개를 확장 노드로 바꾼다.
`PCLazyLoraLoader`가 model/clip을 받아 다시 내보내므로 KSampler와 인코더가 그
출력을 받는다 (확장 소스 `prompt_control/nodes_lazy.py`에서 입출력을 확인했다).

```json
{
  "id": "sdxl_regional",
  "name": "SDXL 리저널 (prompt-control)",
  "requires_nodes": ["PCLazyTextEncode", "PCLazyLoraLoader"],
  "output_node": "9",
  "lora_mode": "delegate",
  "model_slots": {
    "checkpoint": {"path": "4.ckpt_name", "from": "CheckpointLoaderSimple.ckpt_name"}
  },
  "slots": {
    "positive": "6.text",
    "negative": "7.text",
    "seed": "3.seed",
    "steps": "3.steps",
    "cfg": "3.cfg",
    "sampler": "3.sampler_name",
    "scheduler": "3.scheduler",
    "width": "5.width",
    "height": "5.height"
  },
  "graph": {
    "3": {
      "class_type": "KSampler",
      "inputs": {
        "seed": 0, "steps": 28, "cfg": 6.0,
        "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": 1.0,
        "model": ["10", 0], "positive": ["6", 0], "negative": ["7", 0],
        "latent_image": ["5", 0]
      }
    },
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ""}},
    "5": {
      "class_type": "EmptyLatentImage",
      "inputs": {"width": 832, "height": 1216, "batch_size": 1}
    },
    "6": {"class_type": "PCLazyTextEncode", "inputs": {"text": "", "clip": ["10", 1]}},
    "7": {"class_type": "PCLazyTextEncode", "inputs": {"text": "", "clip": ["10", 1]}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},
    "10": {
      "class_type": "PCLazyLoraLoader",
      "inputs": {"model": ["4", 0], "clip": ["4", 1], "text": ""}
    }
  }
}
```

`10.text`를 슬롯으로 두지 **않는다.** `PCLazyLoraLoader`는 텍스트에서 `<lora:...>`만
읽는데, 여기에 positive를 다시 넣으면 프롬프트가 두 곳에 중복된다. 대신 Task 12
이후의 백엔드 조립이 `lora_mode == "delegate"`일 때 이 값을 채운다 — **이번 태스크
범위가 아니다.** 지금은 빈 문자열이면 LoRA가 안 걸릴 뿐 그래프는 유효하다.

> **주의 — 실행자에게**: `build_graph`가 `delegate` 모드에서 `PCLazyLoraLoader.text`를
> 어떻게 채우는지 Task 5 구현을 다시 읽어라. Task 5가 이미 처리한다면 그대로 두고,
> 처리하지 않는다면 **고치지 말고 보고하라.** 스펙 §3.5의 의도는 "프롬프트를 그대로
> 넘긴다"이므로 `6.text`와 `10.text`가 같은 값을 받는 것이 맞을 수 있다. 확인 결과를
> 보고에 반드시 포함하라.

- [ ] **Step 4: `anima.json`을 만든다**

공식 템플릿 `image_anima_base_v1.json`에서 확인한 구성이다 (스펙 §3.4):
`CLIPLoader`의 `type`은 `"anima"`가 아니라 `"stable_diffusion"`이고, VAE는
`qwen_image_vae.safetensors`, 권장 샘플러는 `euler` + `simple`이다.

```json
{
  "id": "anima",
  "name": "Anima (UNET + Qwen3 CLIP)",
  "requires_nodes": ["UNETLoader", "CLIPLoader", "VAELoader"],
  "output_node": "9",
  "lora_mode": "direct",
  "model_slots": {
    "unet": {"path": "4.unet_name", "from": "UNETLoader.unet_name"},
    "clip": {"path": "11.clip_name", "from": "CLIPLoader.clip_name"},
    "vae": {"path": "12.vae_name", "from": "VAELoader.vae_name"},
    "turbo_lora": {"path": "13.lora_name", "from": "LoraLoaderModelOnly.lora_name"}
  },
  "slots": {
    "positive": "6.text",
    "negative": "7.text",
    "seed": "3.seed",
    "steps": "3.steps",
    "cfg": "3.cfg",
    "sampler": "3.sampler_name",
    "scheduler": "3.scheduler",
    "width": "5.width",
    "height": "5.height"
  },
  "graph": {
    "3": {
      "class_type": "KSampler",
      "inputs": {
        "seed": 0, "steps": 8, "cfg": 1.0,
        "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
        "model": ["13", 0], "positive": ["6", 0], "negative": ["7", 0],
        "latent_image": ["5", 0]
      }
    },
    "4": {
      "class_type": "UNETLoader",
      "inputs": {"unet_name": "", "weight_dtype": "default"}
    },
    "5": {
      "class_type": "EmptyLatentImage",
      "inputs": {"width": 832, "height": 1216, "batch_size": 1}
    },
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["11", 0]}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["11", 0]}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["12", 0]}},
    "9": {"class_type": "PreviewImage", "inputs": {"images": ["8", 0]}},
    "11": {
      "class_type": "CLIPLoader",
      "inputs": {"clip_name": "", "type": "stable_diffusion", "device": "default"}
    },
    "12": {"class_type": "VAELoader", "inputs": {"vae_name": ""}},
    "13": {
      "class_type": "LoraLoaderModelOnly",
      "inputs": {"model": ["4", 0], "lora_name": "", "strength_model": 1.0}
    }
  }
}
```

터보 LoRA는 **모델 슬롯**이지 `<lora:...>` 체인이 아니다 (§3.4). `direct` 모드에서
앱이 삽입하는 `LoraLoader` 체인은 노드 `13` **뒤에** 이어 붙는다 — Task 5의
`_insert_lora_chain`이 `KSampler.model`이 가리키는 곳을 기준으로 잇는지 확인하고,
그렇지 않다면 **보고하라** (고치지 말 것).

`steps`/`cfg` 기본값을 터보 기준(8/1)으로 둔 이유는 이 템플릿을 고르는 사람 대다수가
터보를 쓰기 때문이다. 미터보는 30/4다. 앱이 자동으로 바꾸지는 않는다 — 사용자가 정한
값을 말없이 덮어쓰면 왜 바뀌었는지 알 수 없다.

- [ ] **Step 5: 통과 확인**

```
uv run --extra dev pytest tests/test_comfy_templates.py -q
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

**실제 숫자를 보고하라.**

- [ ] **Step 6: 커밋**

```bash
git add src/naiauto/resources/comfy_workflows tests/test_comfy_templates.py
git commit -m "$(cat <<'EOF'
feat(backends): 리저널·Anima 내장 템플릿

sdxl_regional은 lora_mode=delegate다 — PCLazyLoraLoader가 <lora:...>를 이미
읽으므로 우리가 또 결선하면 LoRA가 두 번 걸린다.

anima의 CLIPLoader type은 stable_diffusion이다 (anima가 아니다). 공식 템플릿
image_anima_base_v1.json에서 확인했다. 터보 LoRA는 동적 체인이 아니라 네 번째
모델 슬롯으로 두어 "없음"을 고를 수 있게 한다.

내장 템플릿 무결성 테스트가 슬롯 누락·SaveImage 사용·batch_size 오설정을 잡는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014dbUAFcV3ZCP26Yt2P6Fyo
EOF
)"
```

---

## Task 11: i18n 문자열

**Files:**
- Modify: `src/naiauto/resources/languages/{ko,en,ja,zh}.json`

번역 파일은 `{"language_name", "language_code", "translations": {...}}` 구조이고,
`translations`는 **두 단계 중첩**이다 (`translations.options.<key>`). 네 파일 모두
같은 키 집합을 가져야 한다.

- [ ] **Step 1: 키 동기화 테스트가 이미 있는지 확인한다**

Run: `uv run --extra dev pytest -q -k i18n`

키 누락을 잡는 테스트가 이미 있으면 그것이 이 태스크의 검증이다. 없으면
`tests/test_i18n_keys.py`를 새로 만든다:

```python
"""번역 파일 4종의 키 집합이 같아야 한다."""

import json
from pathlib import Path

LANG_DIR = Path(__file__).resolve().parent.parent / "src" / "naiauto" / "resources" / "languages"


def _flat(node, prefix=""):
    out = set()
    for key, value in node.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            out |= _flat(value, f"{path}.")
        else:
            out.add(path)
    return out


def test_all_languages_share_the_same_keys():
    sets = {}
    for path in sorted(LANG_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        sets[path.stem] = _flat(data["translations"])
    reference = sets["ko"]
    for name, keys in sets.items():
        assert keys == reference, f"{name}: 누락 {reference - keys}, 잉여 {keys - reference}"


def test_local_backend_keys_exist():
    data = json.loads((LANG_DIR / "ko.json").read_text(encoding="utf-8"))
    options = data["translations"]["options"]
    assert "local_backend_url" in options
    assert "local_backend" in data["translations"]["options_nav"]
```

어느 쪽이었는지 **보고하라.**

- [ ] **Step 2: 실패 확인**

Run: `uv run --extra dev pytest tests/test_i18n_keys.py -q`
Expected: FAIL — `test_local_backend_keys_exist`에서 `KeyError` 또는 assert 실패

- [ ] **Step 3: 키를 넣는다**

`translations.options_nav`에 (한국어 기준):

| 키 | ko |
|---|---|
| `local_backend` | 로컬 생성 |
| `local_backend_desc` | 로컬 ComfyUI 서버 주소와 워크플로·모델을 설정합니다. |

`translations.options`에:

| 키 | ko |
|---|---|
| `local_backend_section` | ComfyUI 연결 |
| `local_backend_url` | 서버 주소 |
| `local_backend_test` | 연결 확인 |
| `local_backend_ok` | 연결됨 — 노드 {0}종 |
| `local_backend_failed` | 연결할 수 없습니다: {0} |
| `local_backend_workflow` | 워크플로 |
| `local_backend_workflow_dir` | 사용자 워크플로 폴더 |
| `local_backend_models_section` | 모델 |
| `local_backend_model_none` | (없음) |
| `local_backend_no_options` | 연결 확인을 먼저 눌러 주세요 |
| `local_backend_timeout` | 타임아웃 (초) |

`translations.ui`에 (메인 창):

| 키 | ko |
|---|---|
| `backend` | 백엔드 |
| `backend_novelai` | NovelAI |
| `backend_comfyui` | ComfyUI (로컬) |

`translations.errors`에:

| 키 | ko |
|---|---|
| `comfy_connection` | ComfyUI에 연결할 수 없습니다 ({0}). 서버가 실행 중인지 확인하세요. |
| `comfy_rejected` | ComfyUI가 요청을 거부했습니다: {0} |
| `comfy_execution` | ComfyUI 실행 오류 ({0}): {1} |
| `comfy_timeout` | ComfyUI 응답 시간이 초과되었습니다. |
| `comfy_no_template` | 워크플로를 먼저 선택하세요 (옵션 → 로컬 생성). |
| `comfy_coupling_unsupported` | 선택한 워크플로는 COUPLE MASK 좌표 문법을 지원하지 않습니다. sdxl_regional을 고르거나 좌표 없는 출력을 쓰세요. |

`comfy_coupling_unsupported`가 스펙 §3.6의 안전망이다. 나머지 3개 언어는 같은 키에
자연스러운 번역을 넣는다. **기계적으로 한국어를 복사하지 말 것** — en/ja/zh는 각
언어로 옮긴다. `{0}`/`{1}` 자리표시자는 모든 언어에서 유지한다.

`errors.comfy_execution`만 인자가 두 개(`{0}`=노드 타입, `{1}`=메시지)다.

- [ ] **Step 4: 통과 확인**

```
uv run --extra dev pytest tests/test_i18n_keys.py -q
uv run --extra dev pytest -q
```

JSON이 UTF-8로 저장됐는지 확인하라 (`python -c "import json;json.load(open('...','r',encoding='utf-8'))"`).

- [ ] **Step 5: 커밋**

```bash
git add src/naiauto/resources/languages tests/
git commit -m "$(cat <<'EOF'
feat(i18n): 로컬 백엔드 문자열 4개 언어

comfy_coupling_unsupported는 스펙 3.6의 안전망이다 — COUPLE MASK를 확장 없는
템플릿에 보내면 좌표가 그냥 문자열로 인코딩돼 에러 없이 결과만 망가진다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014dbUAFcV3ZCP26Yt2P6Fyo
EOF
)"
```

---

## Task 12: 옵션 페이지 "로컬 생성"

**Files:**
- Create: `src/naiauto/ui/options_pages/local_backend_page.py`
- Modify: `src/naiauto/ui/options_pages/__init__.py`
- Modify: `src/naiauto/ui/options_dialog.py`
- Create: `tests/test_local_backend_page.py`

**먼저 `src/naiauto/ui/options_pages/prompt_ai_page.py`를 전부 읽어라.** 페이지 계약
(`KEY` / `load` / `commit` / `retranslate`), 콤보를 i18n 키로 다시 채우는 패턴,
폴더 선택 버튼 패턴을 그대로 따른다. 드래프트 의미론(라이브 `AppSettings`를 절대
만지지 않는다)을 어기면 취소가 no-op이 아니게 된다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_local_backend_page.py`:

```python
"""로컬 생성 옵션 페이지 — 드래프트 왕복과 슬롯 위젯 생성."""

import pytest
from PySide6.QtWidgets import QApplication

from naiauto.core.i18n.manager import I18nManager
from naiauto.core.settings.schema import AppSettings
from naiauto.ui.options_pages import page_class


@pytest.fixture()
def qapp():
    # `tests/test_compiler_dialog.py`와 같은 패턴 — conftest에는 없다.
    app = QApplication.instance() or QApplication([])
    yield app


def _page(qapp):
    # 페이지는 번역 함수가 아니라 I18nManager를 받는다 (prompt_ai_page 74행).
    return page_class("local_backend")(I18nManager())


def test_registered():
    assert page_class("local_backend").KEY == "local_backend"


def test_in_nav_order():
    from naiauto.ui.options_dialog import NAV_ORDER

    assert "local_backend" in NAV_ORDER


def test_round_trip(qapp):
    page = _page(qapp)
    draft = AppSettings()
    draft.comfyui.base_url = "http://192.168.0.9:8188"
    draft.comfyui.timeout_seconds = 120.0
    draft.comfyui.template_id = "anima"
    page.load(draft)

    out = AppSettings()
    page.commit(out)
    assert out.comfyui.base_url == "http://192.168.0.9:8188"
    assert out.comfyui.timeout_seconds == 120.0
    assert out.comfyui.template_id == "anima"


def test_blank_url_falls_back_to_default(qapp):
    """빈 주소로 저장하면 연결이 조용히 실패한다 — 기본값으로 되돌린다."""
    page = _page(qapp)
    page.load(AppSettings())
    page._url_edit.setText("   ")
    out = AppSettings()
    page.commit(out)
    assert out.comfyui.base_url == "http://127.0.0.1:8188"


def test_model_slot_widgets_follow_template(qapp):
    """슬롯 개수는 템플릿이 정한다 — SDXL은 1개, Anima는 4개."""
    page = _page(qapp)
    draft = AppSettings()
    draft.comfyui.template_id = "sdxl_basic"
    page.load(draft)
    assert set(page._slot_combos) == {"checkpoint"}

    page._select_template("anima")
    assert set(page._slot_combos) == {"unet", "clip", "vae", "turbo_lora"}


def test_slot_choice_is_kept_per_template(qapp):
    """템플릿을 오가도 각자의 선택이 남는다 (중첩 dict의 이유)."""
    page = _page(qapp)
    draft = AppSettings()
    draft.comfyui.model_slots = {
        "sdxl_basic": {"checkpoint": "a.safetensors"},
        "anima": {"unet": "b.safetensors"},
    }
    draft.comfyui.template_id = "sdxl_basic"
    page.load(draft)
    page._select_template("anima")
    page._select_template("sdxl_basic")

    out = AppSettings()
    page.commit(out)
    assert out.comfyui.model_slots["anima"]["unet"] == "b.safetensors"


def test_unavailable_template_is_hidden_when_nodes_missing(qapp):
    """requires_nodes 미충족 템플릿은 목록에서 뺀다 (스펙 §3.2)."""
    from naiauto.core.backends.comfy_objects import ObjectInfo

    page = _page(qapp)
    page.load(AppSettings())
    page._apply_object_info(
        ObjectInfo(node_classes=frozenset({"KSampler", "CheckpointLoaderSimple"}), _options={})
    )
    ids = [page._template_combo.itemData(i) for i in range(page._template_combo.count())]
    assert "sdxl_basic" in ids
    assert "sdxl_regional" not in ids


def test_saved_template_survives_when_server_unreachable(qapp):
    """서버가 꺼져 있어도 저장된 선택을 지운다면 사용자 설정이 날아간다."""
    page = _page(qapp)
    draft = AppSettings()
    draft.comfyui.template_id = "sdxl_regional"
    page.load(draft)
    out = AppSettings()
    page.commit(out)
    assert out.comfyui.template_id == "sdxl_regional"


def test_retranslate_does_not_lose_selection(qapp):
    page = _page(qapp)
    draft = AppSettings()
    draft.comfyui.template_id = "anima"
    page.load(draft)
    page.retranslate()
    out = AppSettings()
    page.commit(out)
    assert out.comfyui.template_id == "anima"
```

`qapp` 픽스처가 있는지 `tests/conftest.py`에서 확인하라. 이름이 다르면 기존 UI 테스트
(`tests/test_compiler_dialog.py`)가 쓰는 이름을 그대로 따르고 **보고하라.**

- [ ] **Step 2: 실패 확인**

Run: `uv run --extra dev pytest tests/test_local_backend_page.py -q`
Expected: FAIL — `KeyError: "no options page registered for key 'local_backend'"`

- [ ] **Step 3: 페이지를 만든다**

`src/naiauto/ui/options_pages/local_backend_page.py`. 요구사항:

- `KEY = "local_backend"`, `@register_page`
- 위젯: `_url_edit`(QLineEdit), 연결 확인 버튼, 상태 라벨, `_template_combo`(QComboBox,
  `userData`에 템플릿 id), `_workflows_dir_edit` + 찾아보기 버튼, 슬롯 콤보들이 들어갈
  `QFormLayout`(`_slots_form`), `_timeout_spin`(QDoubleSpinBox, 범위 10.0–3600.0)
- `_templates`: `load_workflows(draft.comfyui.workflows_dir)` 결과를 `load`에서 보관
- `_object_info`: 연결 확인 성공 시 `parse_object_info(...)` 결과. 기본은 `None`
- `_slot_combos: dict[str, QComboBox]` — `_select_template(template_id)`이 다시 만든다
- `_pending_slots: dict[str, dict[str, str]]` — 템플릿별 선택. `load`가
  `draft.comfyui.model_slots`를 **깊은 사본**으로 여기에 담는다 (드래프트를 직접
  들고 있으면 취소가 no-op이 아니게 된다). `_select_template`은 위젯을 부수기
  **전에** 현재 콤보 값을 여기에 저장하고, 새 템플릿의 값을 여기서 꺼내 채운다.
  `commit`은 현재 콤보를 한 번 더 반영한 뒤 이 dict를 통째로 쓴다 — 그래야 지금
  보이지 않는 템플릿의 선택도 살아남는다.
- 모델 콤보 항목은 `_object_info`가 있으면 `ModelSlot.source`가 가리키는 옵션 목록,
  없으면 **저장된 값 하나만** 넣는다 (서버가 꺼져 있어도 설정이 날아가지 않는다).
  `turbo_lora`처럼 비울 수 있는 슬롯을 위해 맨 앞에 `local_backend_model_none`
  ("" 값)을 넣는다.
- `commit(draft)`은 `base_url`(빈 문자열 → 기본값), `template_id`, `model_slots`,
  `timeout_seconds`, `workflows_dir`을 채운다. **범위 검증은 하지 않는다** — 위젯이
  클램프하고, 나머지는 `core.settings.validation`의 몫이다 (페이지 docstring 참고).
- 연결 확인은 **동기 호출 1회**로 충분하다 (`requests.get(f"{url}/object_info",
  timeout=5)`). 옵션 창은 모달이고 로컬 서버라 응답이 빠르다. 실패는 예외를 삼키고
  `local_backend_failed`를 라벨에 띄운다 — 옵션 창이 죽으면 안 된다.
- `_apply_object_info(info: ObjectInfo)`를 별도 메서드로 두어 테스트가 네트워크 없이
  호출할 수 있게 한다. 연결 확인 버튼은 응답을 `parse_object_info`에 넣고 그 결과를
  이 메서드에 넘기기만 한다. 이 메서드가 템플릿 콤보를 `is_available`로 거르고
  슬롯 콤보 항목을 다시 채운다.
- `retranslate()`는 라벨과 콤보 표시 문구만 다시 채운다. **선택을 잃지 않도록**
  `currentData()`를 먼저 읽어 두고 다시 채운 뒤 복원한다 (`prompt_ai_page`의
  `_fill_*_combo`와 같은 패턴).

`src/naiauto/ui/options_pages/__init__.py`의 정적 import 블록에 알파벳 순으로 추가:

```python
    local_backend_page,  # noqa: F401
```

`src/naiauto/ui/options_dialog.py`의 `NAV_ORDER`에서 `"prompt_ai"` 다음에 넣는다:

```python
    "local_backend",
```

- [ ] **Step 4: 통과 확인**

```
uv run --extra dev pytest tests/test_local_backend_page.py -q
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

**실제 숫자를 보고하라.**

- [ ] **Step 5: 커밋**

```bash
git add src/naiauto/ui/options_pages tests/test_local_backend_page.py src/naiauto/ui/options_dialog.py
git commit -m "$(cat <<'EOF'
feat(ui): 로컬 생성 옵션 페이지

슬롯 선택기 개수를 코드가 모르고 템플릿이 정한다. 템플릿을 오가도 각자의 선택이
남도록 _pending_slots에 모아 두고, 서버가 꺼져 있으면 저장된 값 하나만 항목으로
넣는다 — 목록을 못 받았다고 선택을 지우면 설정이 날아간다.

연결 확인은 동기 1회다. 옵션 창은 모달이고 로컬 서버라 응답이 빠르다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014dbUAFcV3ZCP26Yt2P6Fyo
EOF
)"
```

---

## Task 13: 메인 창 통합

가장 위험한 태스크다. **`src/naiauto/ui/main_window.py`에서 먼저 읽어야 할 곳:**
`__init__`(155–220행), `_on_model_changed`(1216행), `refresh_anlas`(2207행),
`_on_anlas_fetched`(2217행), `_apply_settings`(1252행 부근), `_collect_settings`
(1342행 부근). `GenerationService`는 `ui/app.py:73`에서 한 번 만들어져 창에 주입된다.

**Files:**
- Modify: `src/naiauto/ui/main_window.py`
- Modify: `src/naiauto/services/generation_service.py` (백엔드 교체 메서드)
- Create: `tests/test_backend_switching.py`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`tests/test_backend_switching.py`:

```python
"""백엔드 전환 — 서비스 재결선, 콤보 목록 교체, Anlas 숨김."""

import pytest

from naiauto.core.api.models import GenerationResult


class _Local:
    supports_credit = False

    def generate(self, req):  # pragma: no cover
        return GenerationResult(raw_bytes=b"")


def test_service_backend_can_be_swapped():
    from naiauto.services.generation_service import GenerationService

    class _Nai:
        def generate(self, req):  # pragma: no cover
            return GenerationResult(raw_bytes=b"")

        def get_anlas(self):
            return {}

    nai = _Nai()
    service = GenerationService(nai)
    assert service.backend is nai
    local = _Local()
    service.set_backend(local)
    assert service.backend is local
    service.shutdown()


def test_backend_cannot_be_swapped_while_running():
    """생성 중에 백엔드를 갈아 끼우면 진행 중인 잡이 엉뚱한 서버를 본다."""
    from naiauto.services.generation_service import GenerationService

    service = GenerationService(_Local())
    service._running = True   # 실제 플래그 이름을 확인하고 맞출 것
    with pytest.raises(RuntimeError):
        service.set_backend(_Local())
    service._running = False
    service.shutdown()
```

`GenerationService`의 "실행 중" 플래그 실제 이름을 먼저 확인하라. 다르면 테스트를
실제 이름에 맞추고 **보고하라.**

메인 창 테스트는 `tests/`에 이미 있는 메인 창 테스트 파일에 덧붙인다
(`ls tests/ | grep -i main`으로 찾고 **보고하라**). 없으면 이 파일에 넣는다:

```python
def test_local_backend_hides_anlas(qapp, main_window):
    main_window._select_backend("comfyui")
    assert not main_window.anlas_label.isVisible()
    main_window._select_backend("novelai")
    assert main_window.anlas_label.isVisible()


def test_local_backend_replaces_sampler_list(qapp, main_window):
    main_window._apply_backend_object_info(
        {"KSampler": {"sampler_name": ["euler", "dpmpp_2m"], "scheduler": ["simple", "karras"]}}
    )
    main_window._select_backend("comfyui")
    items = [main_window.sampler_combo.itemText(i) for i in range(main_window.sampler_combo.count())]
    assert "dpmpp_2m" in items
    assert "k_euler_ancestral" not in items


def test_switching_back_restores_novelai_samplers(qapp, main_window):
    main_window._select_backend("comfyui")
    main_window._select_backend("novelai")
    items = [main_window.sampler_combo.itemText(i) for i in range(main_window.sampler_combo.count())]
    assert items == list(main_window.current_spec().samplers)
```

메인 창 픽스처가 없다면 **이 세 테스트는 건너뛰고 보고하라.** 메인 창 인스턴스를
새로 만드는 픽스처를 이 태스크에서 발명하지 말 것 — 창 생성은 파일 I/O·QSettings·
네트워크를 건드려 테스트가 불안정해진다.

- [ ] **Step 2: 실패 확인**

Run: `uv run --extra dev pytest tests/test_backend_switching.py -q`
Expected: FAIL — `AttributeError: 'GenerationService' object has no attribute 'backend'`

- [ ] **Step 3: 서비스에 교체 지점을 만든다**

`src/naiauto/services/generation_service.py`:

```python
    @property
    def backend(self) -> ImageBackend:
        """현재 생성 백엔드."""
        return self._client

    def set_backend(self, backend: ImageBackend) -> None:
        """백엔드를 갈아 끼운다. 생성 중에는 거부한다.

        진행 중인 잡이 요청을 보낸 서버와 결과를 회수할 서버가 달라지면
        이미지가 사라진다.
        """
        if self._running:      # 실제 플래그 이름에 맞출 것
            raise RuntimeError("cannot swap backend while a job is running")
        self._client = backend
```

`_client`를 그대로 두는 이유는 Task 2와 같다 — 이름을 바꾸면 무관한 줄이 diff에 는다.

- [ ] **Step 4: 메인 창을 고친다**

다음만 한다. **인접 코드를 손보지 말 것.**

1. `_build_ui`의 모델 콤보 근처에 `self.backend_combo = QComboBox()`를 추가하고
   두 항목(`ui.backend_novelai` → `"novelai"`, `ui.backend_comfyui` → `"comfyui"`)을
   `userData`로 넣는다. `self.backend_label`도 만들어 `form.addRow`에 넣는다.
2. `self.backend_combo.currentIndexChanged.connect(self._on_backend_changed)`.
3. `_on_backend_changed()` → `self._select_backend(self.backend_combo.currentData())`.
4. `_select_backend(backend_id)`:
   - `self._settings.generation_backend = backend_id`
   - `comfyui`면 `self._build_comfy_backend()`로 백엔드를 만들어 `service.set_backend`,
     아니면 `service.set_backend(self._client)`
   - `RuntimeError`(생성 중)면 콤보를 이전 값으로 되돌리고 상태바에 안내. **여기서
     조용히 넘어가면 사용자는 바꿨다고 믿는다.**
   - `self.anlas_label.setVisible(backend_id == "novelai")` — 크레딧 게이지 위젯도
     같이 숨긴다 (위젯 이름은 388–406행에서 확인)
   - `self._refresh_sampler_lists()`
5. `_build_comfy_backend()`: 설정에서 `base_url`/`template_id`/`model_slots`/
   `timeout_seconds`/`workflows_dir`을 읽어 `ComfyUIBackend`를 만든다. 템플릿을 못
   찾으면 `template=None`으로 두고 상태바에 `errors.comfy_no_template`을 띄운다 —
   백엔드가 생성 시점에 같은 오류를 낸다.
6. `_apply_backend_object_info(raw)`: `parse_object_info(raw)` 결과를
   `self._comfy_object_info`에 보관한다. 초기값은 `None`.
7. `_refresh_sampler_lists()`: `generation_backend`가 `novelai`면 지금처럼
   `spec.samplers`/`spec.schedulers`로, `comfyui`면 `_comfy_object_info`의
   `KSampler.sampler_name`/`KSampler.scheduler`로 채운다. 목록이 비어 있으면
   **콤보를 비우지 말고 그대로 둔다** (서버가 꺼져 있을 때 선택이 날아가지 않게).
8. `_on_model_changed`의 콤보 채우기 두 줄을 `self._refresh_sampler_lists()` 호출로
   바꾼다. 나머지(해상도 카탈로그, uc_preset, i2i 활성화)는 **그대로 둔다** — 그건
   NovelAI 모델 스펙에 딸린 것이고 백엔드와 무관하다.
9. `refresh_anlas()` 첫 줄에 가드: `if self._settings.generation_backend != "novelai":
   return`. 로컬 백엔드에는 `get_anlas`가 없다.
10. `_apply_settings()` 끝에서 `self._select_backend(self._settings.generation_backend)`.
    `_collect_settings()`는 `generation_backend`를 이미 `_select_backend`가 써 뒀으므로
    **건드리지 않는다.**
11. 옵션 창의 `applied` 시그널 처리부에서 백엔드를 다시 만든다 — 옵션에서 주소나
    템플릿을 바꿔도 반영되게. 기존 처리부를 찾아(`applied.connect`) 거기에
    `self._select_backend(self._settings.generation_backend)`를 덧붙인다.

**스펙 §3.6 안전망**: 생성 요청을 조립하는 곳(`build_job` 부근, 943행)에서
`"COUPLE MASK("`가 프롬프트에 있는데 선택된 템플릿의 `lora_mode != "delegate"`면
경고 상자를 띄우고 생성을 막는다. **이 안전망을 빼먹지 말 것** — 이 조합은 에러 없이
결과만 망가져 사용자가 원인을 못 찾는다.

- [ ] **Step 5: 통과 확인**

```
uv run --extra dev pytest tests/test_backend_switching.py -q
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

**실제 숫자를 보고하라.** 메인 창 테스트를 건너뛰었다면 그것도 보고하라.

- [ ] **Step 6: 커밋**

```bash
git add src/naiauto/ui/main_window.py src/naiauto/services/generation_service.py tests/test_backend_switching.py
git commit -m "$(cat <<'EOF'
feat(ui): 백엔드 셀렉터와 샘플러 목록 교체

샘플러 이름을 매핑하지 않고 서버가 주는 목록을 그대로 쓴다. 매핑표는 ComfyUI가
샘플러를 추가할 때마다 낡는다.

생성 중 백엔드 교체는 거부한다 — 요청을 보낸 서버와 결과를 회수할 서버가 달라지면
이미지가 사라진다. 실패를 조용히 넘기지 않고 콤보를 되돌린다.

COUPLE MASK를 확장 없는 템플릿에 보내면 좌표가 문자열로 인코딩돼 에러 없이 결과만
망가지므로 생성 전에 막는다 (스펙 3.6).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014dbUAFcV3ZCP26Yt2P6Fyo
EOF
)"
```

---

## Task 14: 라이브 스모크 테스트

기본 실행에서 빠지는, 실제 서버로 1장 뽑는 테스트다. 앞의 모든 스텁 테스트가
"우리가 상상한 프로토콜"만 검증하므로, 진짜 서버와 한 번은 맞춰 봐야 한다.

**Files:**
- Create: `tests/test_comfy_live.py`
- Modify: `pyproject.toml` (마커 등록)

- [ ] **Step 1: 마커를 등록한다**

`pyproject.toml`의 `[tool.pytest.ini_options]`에서 `markers`를 찾는다. 없으면 만든다:

```toml
markers = [
    "comfy_live: 실제 ComfyUI 서버가 필요한 테스트 (기본 실행에서 제외)",
]
```

기본 실행에서 빠지도록 `addopts`에 `-m "not comfy_live"`를 더한다. `addopts`가 이미
있으면 **덮어쓰지 말고 덧붙여라.** 기존 값을 보고하라.

- [ ] **Step 2: 테스트를 쓴다**

`tests/test_comfy_live.py`:

```python
"""실제 ComfyUI 서버로 1장 생성 — `pytest -m comfy_live`로만 돈다.

환경변수:
  NAIAUTO_COMFY_URL        기본 http://127.0.0.1:8188
  NAIAUTO_COMFY_CHECKPOINT 필수 — 서버에 실재하는 SDXL 체크포인트 파일명
"""

import os

import pytest

pytestmark = pytest.mark.comfy_live


def test_generates_one_image():
    from naiauto.core.api.models import GenerationRequest
    from naiauto.core.backends.comfy_workflow import find_workflow, load_workflows
    from naiauto.core.backends.comfyui import ComfyUIBackend

    checkpoint = os.environ.get("NAIAUTO_COMFY_CHECKPOINT")
    if not checkpoint:
        pytest.skip("NAIAUTO_COMFY_CHECKPOINT가 없다")

    template = find_workflow(load_workflows(), "sdxl_basic")
    assert template is not None

    seen = []
    backend = ComfyUIBackend(
        base_url=os.environ.get("NAIAUTO_COMFY_URL", "http://127.0.0.1:8188"),
        template=template,
        model_slots={"checkpoint": checkpoint},
        timeout=300.0,
        on_progress=lambda v, m: seen.append((v, m)),
    )
    result = backend.generate(
        GenerationRequest(
            prompt="1girl, solo, simple background",
            negative_prompt="worst quality",
            width=512,
            height=512,
            steps=4,
            cfg_scale=5.0,
            sampler="euler",
            scheduler="normal",
            seed=1234,
        )
    )
    assert result.raw_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert seen, "진행률 메시지를 하나도 못 받았다"
```

`GenerationRequest`의 실제 필드 이름을 `src/naiauto/core/api/models.py`에서 확인하고
맞춰라. 필수 인자가 더 있으면 채우고 **보고하라.**

- [ ] **Step 3: 기본 실행에서 빠지는지 확인**

```
uv run --extra dev pytest -q
uv run --extra dev pytest -m comfy_live --collect-only -q
```

첫 번째는 이 테스트를 **수집하지 않아야** 하고, 두 번째는 1개를 수집해야 한다.
실제 실행은 사용자가 서버를 켜고 한다 — **여기서 실행하지 말 것.**

- [ ] **Step 4: 커밋**

```bash
git add tests/test_comfy_live.py pyproject.toml
git commit -m "$(cat <<'EOF'
test(backends): 실제 서버 스모크 테스트 (comfy_live 마커)

스텁 테스트는 우리가 상상한 프로토콜만 검증한다. 진짜 서버와 한 번은 맞춰 봐야
한다. 기본 실행에서는 빠진다 — 서버·GPU·모델이 필요하다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014dbUAFcV3ZCP26Yt2P6Fyo
EOF
)"
```

---

## Task 15: 문서

**Files:**
- Modify: `README.md`
- Modify: `MANUAL_KR.md`

- [ ] **Step 1: 기존 문서를 읽는다**

A단계의 로컬 SDXL 출력 타깃 설명이 어디에 어떻게 들어갔는지 보고 **같은 자리, 같은
톤**으로 이어 쓴다 (`git show a18986b --stat`). 새 섹션을 발명하지 말 것.

- [ ] **Step 2: 내용을 쓴다**

넣을 것:

- ComfyUI를 로컬 백엔드로 쓸 수 있다는 한 문단. 프롬프트 컴파일러의 로컬 SDXL
  타깃과 짝을 이룬다는 점 (A단계가 뽑은 프롬프트를 그대로 로컬에서 생성한다).
- 설정 순서: ComfyUI를 켠다 → 옵션 → 로컬 생성 → 주소 입력 → 연결 확인 →
  워크플로 선택 → 모델 슬롯 선택 → 메인 창에서 백엔드를 ComfyUI로.
- 내장 워크플로 3종 표 (스펙 §3.4와 같은 내용). `sdxl_regional`은
  **comfyui-prompt-control 확장이 필요**하다는 점을 눈에 띄게.
- Anima 권장값: 터보 LoRA 사용 시 steps 8 / cfg 1, 미사용 시 30 / 4.
  **앱이 자동으로 바꾸지 않으므로 사용자가 메인 창에서 조절한다.**
- COUPLE MASK 좌표 문법은 `sdxl_regional`에서만 동작한다는 경고.
- 로컬 백엔드에서는 Anlas 표시와 크레딧 측정이 꺼진다는 점.
- 사용자 워크플로 폴더에 자기 템플릿을 넣을 수 있다는 점과 매니페스트 형식
  (스펙 §3.2를 요약. 전체 형식은 스펙 문서를 가리킨다).

`MANUAL_KR.md`는 더 자세히, `README.md`는 짧게. 다른 언어 README가 있으면
`ls README*`로 확인하고 **어떻게 했는지 보고하라.**

- [ ] **Step 3: 커밋**

```bash
git add README.md MANUAL_KR.md
git commit -m "$(cat <<'EOF'
docs: ComfyUI 로컬 백엔드 사용법

Anima 권장 steps/cfg를 문서에만 적는다 — 앱이 자동으로 바꾸면 사용자가 정한 값이
왜 바뀌었는지 알 수 없다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014dbUAFcV3ZCP26Yt2P6Fyo
EOF
)"
```

---

## Task 16: 최종 검증

- [ ] **Step 1: 전체 스위트와 린트**

```
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
uv run --extra dev ruff format --check src tests
```

**실제 숫자를 보고하라.** 실패가 하나라도 있으면 여기서 멈추고 보고한다.

- [ ] **Step 2: NovelAI 경로가 그대로인지 확인**

A단계까지의 테스트가 **하나도 깨지지 않아야** 한다. 이 프로젝트의 기본 사용법은
여전히 NovelAI다. 깨진 것이 있으면 백엔드 추상화가 새는 것이므로 반드시 보고한다.

- [ ] **Step 3: 프로즌 빌드 가정 점검**

- `pyproject.toml`에 `websocket-client`가 **필수** 의존성으로 있는가 (optional 아님)
- `packaging/nai-auto-v5.spec`의 `hiddenimports`에 `"websocket"`이 있는가
- `src/naiauto/resources/comfy_workflows/*.json` 3개가 실재하는가
- `ui/options_pages/__init__.py`에 `local_backend_page`가 **정적 import**로 있는가
  (`pkgutil` 발견은 프로즌 빌드에서 깨진다 — 모듈 docstring 참고)

```
uv run --extra dev python -c "
from naiauto.core.backends import load_workflows
from naiauto.ui.options_pages import page_class
print(sorted(t.id for t in load_workflows()))
print(page_class('local_backend').KEY)
"
```

세 템플릿 id와 `local_backend`가 나와야 한다.

- [ ] **Step 4: 수동 확인 항목을 사용자에게 넘긴다**

자동 테스트가 못 잡는 것들이다. **직접 하지 말고 목록으로 보고하라:**

1. ComfyUI를 켜고 옵션 → 로컬 생성 → 연결 확인 → 모델 목록이 채워지는가
2. `sdxl_basic`으로 1장 생성 — 진행률 바가 움직이는가
3. 생성 중 중지 — ComfyUI 콘솔에 인터럽트가 찍히는가
4. 결과 PNG를 앱에 끌어다 놓으면 그래프가 읽히는가 (`PreviewImage`가 `prompt`
   청크를 심는다)
5. `sdxl_regional` + COUPLE MASK 프롬프트로 다인 구도가 실제로 분리되는가
6. `anima` + 터보 LoRA로 steps 8 / cfg 1 생성
7. 백엔드를 NovelAI로 되돌리면 Anlas 표시가 돌아오는가
8. 서버를 끈 채 생성 → 연결 오류 메시지가 뜨고 앱이 살아 있는가

- [ ] **Step 5: 마무리**

`superpowers:finishing-a-development-branch` 스킬로 통합 방식을 정한다.



