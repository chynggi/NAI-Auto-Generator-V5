# 인수인계 — ComfyUI 생성 백엔드 (하위 프로젝트 B)

**작성**: 2026-09-06
**브랜치**: `feat/comfyui-backend` (main에서 분기, 미병합)
**중단 지점**: Task 7 진행 중 (16개 중 6개 완료)
**전체 테스트**: 423 passed, ruff clean

---

## 1. 지금 당장 알아야 할 것

### 미커밋 작업이 있다

Task 7이 **커밋되지 않은 채** 작업 트리에 남아 있다. 중단 시점이 뮤테이션 테스트 도중이었다.

```
 M packaging/nai-auto-v5.spec          ← hiddenimports에 "websocket" 추가
 M pyproject.toml                      ← websocket-client>=1.7 필수 의존성 추가
?? src/naiauto/core/backends/comfy_progress.py
?? tests/test_comfy_progress.py
?? uv.lock                             ← 이전부터 미추적. 저장소 정책 미정
```

**주입됐던 뮤테이션은 원복했다.** `comfy_progress.py` 69행이 `if False and incoming is not None ...` 상태로 남아 있던 것을 정상으로 되돌렸고, 423 passed / ruff clean을 확인했다. **추가 정리 작업은 필요 없다.**

`uv.lock`은 upstream도 추적하지 않고 `.gitignore`에도 없다. 커밋 여부는 저장소 정책 판단이라 손대지 않았다.

### 재개 전에 반드시 고쳐야 할 결함 하나

`tests/test_comfy_progress.py`의 `test_other_prompt_ids_are_ignored`가 **엉뚱한 이유로 통과한다.**

```python
raw = json.dumps(
    {"type": "executed", "data": {"node": "9", "prompt_id": "other", "output": {}}}
)
assert parse_message(raw, PID) is None
```

`output`이 비어 있어서, `prompt_id` 필터를 완전히 제거해도 `executed` 분기가 "이미지 없음"으로 떨어져 똑같이 `None`을 반환한다. 뮤테이션(`if False and ...`)을 넣은 채로 23개 테스트가 전부 통과했다.

`prompt_id` 필터는 현재 **어떤 테스트도 검증하지 않는다.** 이 필터가 없으면 한 클라이언트가 여러 프롬프트를 큐에 넣었을 때 남의 작업 진행률이 우리 진행 바를 움직인다.

수정: 남의 메시지에 **유효한 이미지 출력**을 실어서, `None`이 오직 필터에서만 나오게 한다.

```python
def test_other_prompt_ids_are_ignored():
    """여러 클라이언트가 붙어 있을 수 있다 — 남의 작업 메시지를 먹으면 안 된다.

    output을 비우면 안 된다 — 필터를 꺼도 "이미지 없음"으로 None이 나와
    테스트가 엉뚱한 이유로 통과한다 (실제로 그랬다).
    """
    raw = json.dumps(
        {
            "type": "executed",
            "data": {
                "node": "9",
                "prompt_id": "other",
                "output": {"images": [{"filename": "x.png", "subfolder": "", "type": "temp"}]},
            },
        }
    )
    assert parse_message(raw, PID) is None
```

고친 뒤 `if False and`를 다시 넣어 **실제로 실패하는지** 확인할 것. 이건 계획(내가 쓴 것)의 결함이므로 `docs/superpowers/plans/2026-09-06-comfyui-backend.md`의 Task 7 테스트도 같이 고쳐야 한다.

---

## 2. 완료된 것

| # | 태스크 | 모델 | 커밋 | 누적 테스트 |
|---|---|---|---|---|
| 1 | 백엔드 프로토콜 | Haiku | `603c326` | 321 |
| 2 | 크레딧 능력 가드 | Sonnet | `5daa584` | 323 |
| 3 | ComfyUI 오류 계층 | Haiku | `ac6717c` | 331 |
| 4 | 템플릿 로딩·슬롯 검증 | Opus | `67b2195` + `727ed48` | 355 |
| 5 | 값 주입·LoRA 결선 | Opus | `c3f84b6` + `07ff051` + `263d290` | 380 |
| 6 | `/object_info` 파싱 | Sonnet | `ce0a05c` | 400 |
| 7 | WS 진행 리스너 | Sonnet | **미커밋** | 423 |

계획 자체를 고친 커밋: `7d3f82d`, `f3933b0`, `49d4287`

### 만들어진 것

```
src/naiauto/core/backends/
  __init__.py         ImageBackend, backend_supports_credit 노출
  base.py             ImageBackend Protocol, backend_supports_credit
  errors.py           ComfyError 계층 6종
  comfy_workflow.py   템플릿 로딩·검증(전반) + 값 주입·LoRA 결선(후반)
  comfy_objects.py    ObjectInfo, parse_object_info
  comfy_progress.py   Progress/Executed/ExecutionFailed, parse_message  ← 미커밋
src/naiauto/resources/comfy_workflows/
  sdxl_basic.json     내장 템플릿 1종 (나머지 2종은 Task 10)
```

`services/generation_service.py`는 `client: ImageBackend`를 받고 `_log_credit`에 능력 가드가 들어갔다. **인자 이름은 `client` 그대로** — 호출부(`ui/app.py:73`)를 건드리지 않기 위해서다.

---

## 3. 이 작업에서 잡은 실제 결함 6건

전부 테스트만으로는 드러나지 않고 배포 후에야 나타났을 것들이다. 재개하는 사람이 같은 함정을 다시 밟지 않도록 기록한다.

**1. 패키징 누락 (기존 출시분 포함)** — `[tool.setuptools.package-data]`에 세 폴더가 빠져 있었다.

| 누락 | 출처 | 상태 |
|---|---|---|
| `resources/comfy_workflows/*.json` | 이번 작업 | `727ed48`에서 수정 |
| `resources/prompt_targets/*.json` | **A단계, 이미 출시됨** | `727ed48`에서 수정 |
| `resources/icons/*.ico` | 그 이전 | **미수정 — 아래 §5 참고** |

`pip install .`로 설치하면 로더가 `is_dir()` false로 조기 반환해 **로그조차 없이** 빈 목록을 돌려준다. 소스 트리 실행과 CI에서는 전부 통과하므로 테스트로 잡을 수 없다.

**2. LoRA 체인이 Anima에서 순환을 만들었다** — 재결선 대상을 "class_type이 `LoraLoader`가 아닌 노드 전부"로 골랐는데, Anima의 터보 LoRA는 `LoraLoaderModelOnly`라 필터를 빠져나가 체인 끝을 가리켰다. 결과가 `13 → 14 → 13` 순환이라 ComfyUI가 그래프를 거부한다.

`sdxl_basic`에는 그런 노드가 없어 38개 테스트가 전부 통과했다 — **Task 10에서 anima 템플릿을 만들 때까지 드러나지 않았을 버그**다.

수정: **원본 출처를 그대로 받던 노드만** 재결선한다. 계획(`f3933b0`)과 구현(`07ff051`) 양쪽 반영됨.

**3. `strip_lora_tags`가 약속한 쉼표 정리를 안 했다** — `_TIDY_RE`가 쉼표를 하나만 소비해서 `"a, <lora:x:1>, b"` → `"a, , b"`. 태그를 프롬프트 중간에 두거나 여러 개 겹치는 건 흔한 패턴이다. 기존 테스트 3개가 전부 "태그 1개 + 문자열 맨 앞"이라 이 경로를 안 밟았다. `49d4287`(계획) + `263d290`(구현).

**4. 무의미한 단언** — 계획 Task 1의 `assert issubclass(...) or isinstance.__self__ is not None`에서 `isinstance.__self__`는 builtins 모듈이라 **항상 참**이었다. `7d3f82d`.

**5. 검증력 없는 테스트** — `test_build_graph_skips_empty_model_selection`이 픽스처 기본값과 같은 `""`를 단언해서, `if not chosen: continue`를 지워도 통과했다. `263d290`.

**6. `prompt_id` 필터 미검증** — §1 참고. **아직 미수정.**

### 여기서 얻은 교훈

**뮤테이션 테스트가 6건 중 4건을 잡았다.** 테스트가 통과한다는 것과 테스트가 무언가를 검증한다는 것은 다르다. 각 태스크마다 "이 동작을 망가뜨리면 어떤 테스트가 실패하는가"를 실제로 확인시키는 것이 값을 했다.

---

## 4. 남은 태스크 (7–16)

계획 파일: `docs/superpowers/plans/2026-09-06-comfyui-backend.md`
설계 스펙: `docs/superpowers/specs/2026-09-06-comfyui-backend-design.md`

| # | 태스크 | 계획 행 범위 | 권장 모델 |
|---|---|---|---|
| 7 | WS 진행 리스너 | 1450–1725 | Sonnet — **거의 완료, §1 수정 후 커밋** |
| 8 | ComfyUI 백엔드 본체 | 1725–2315 | **Opus** |
| 9 | 설정 스키마 | 2315–2450 | Sonnet |
| 10 | 템플릿 2종 + 무결성 | 2450–2736 | Sonnet |
| 11 | i18n 4개 언어 | 2736–2873 | Sonnet |
| 12 | 옵션 페이지 | 2873–3100 | **Opus** |
| 13 | 메인 창 통합 | 3100–3304 | **Opus** |
| 14 | 라이브 스모크 | 3304–3413 | Haiku |
| 15 | 문서 | 3413–3462 | Sonnet |
| 16 | 최종 검증 | 3462–끝 | 직접 |

**행 번호는 계획을 고칠 때마다 밀린다.** 재개 시 `grep -n "^## Task" docs/superpowers/plans/2026-09-06-comfyui-backend.md`로 다시 확인할 것.

### Task 10에서 반드시 확인할 것

계획이 실행자에게 확인하고 **보고만** 하라고 지시한 항목들이다 (고치지 말 것):

1. **`build_graph`가 `delegate` 모드에서 `PCLazyLoraLoader.text`를 채우는가.** `sdxl_regional.json`의 노드 10 `text` 슬롯을 비워 두었는데, 스펙 §3.5의 의도("프롬프트를 그대로 넘긴다")대로면 `6.text`와 같은 값을 받아야 할 수도 있다. Task 5 구현을 읽고 판단할 것.
2. **`_insert_lora_chain`의 체인 시작점이 dict 삽입 순서에 의존한다.** 그래프에서 처음 만난 `model`/`clip` 링크를 잡는다. anima에서는 결과적으로 옳은 지점(터보 뒤)을 고르는 것을 확인했지만, 그건 KSampler가 그래프에서 먼저 나온다는 순서에 기댄 결과다. 실제 `anima.json`으로 재확인할 것.
3. **`strip_lora_tags`의 대상 키가 `"positive"`/`"negative"`로 하드코딩되어 있다.** 계획된 3개 템플릿에는 문제없지만, 리저널 슬롯(`positive_2` 등)이 `direct` 모드로 오면 조용히 태그가 남는다.

### Task 13에서 빼먹으면 안 되는 것

**스펙 §3.6 안전망**: 프롬프트에 `COUPLE MASK(`가 있는데 선택된 템플릿의 `lora_mode != "delegate"`면 생성 전에 막아야 한다. 이 조합은 좌표 문법이 그냥 문자열로 인코딩돼 **에러 없이 결과만 망가진다** — 사용자가 원인을 찾을 길이 없다. i18n 키 `errors.comfy_coupling_unsupported`가 Task 11에서 준비된다.

---

## 5. 사용자 결정이 필요한 것

**1. `resources/icons/*.ico` 패키징 누락.** §3-1의 세 번째 항목. 이 기능과 무관한 서브시스템이라 손대지 않았다. `pip install` 경로에서만 앱 아이콘이 빠진다 (PyInstaller 빌드는 `.spec`이 따로 처리하므로 영향 없음). 한 줄 수정이다.

**2. `uv.lock` 추적 여부.** upstream도 추적하지 않고 `.gitignore`에도 없다.

**3. `main`이 `origin/main`보다 1 뒤, 35 앞.** A단계 병합 후 푸시하지 않았다. 원격 커밋 1개를 어떻게 처리할지 정해야 푸시할 수 있다.

**4. `feat/local-sdxl-prompt-target` 브랜치 미삭제.** A단계 작업 브랜치.

---

## 6. 작업 방식 메모

**테스트/린트는 반드시 `uv run`으로.** `.venv/Scripts/python.exe`에는 pytest가 없다.

```
uv run --extra dev pytest -q
uv run --extra dev ruff check src tests
```

**서브에이전트 구동 방식을 썼다** (`superpowers:subagent-driven-development`). 태스크별로 모델 등급을 나누고, 어려운 태스크(4, 5, 7, 8, 12, 13)에만 리뷰어 서브에이전트를 붙이고 축자 스펙 태스크는 인라인으로 검토했다 — 비용 조절을 위한 조정이다.

**계획 본문이 긴 태스크는 전문을 옮기는 대신 정확한 행 범위를 지정해 읽게 했다.** 스킬 기본값은 "플랜 파일을 읽게 하지 말 것"이지만, 자기 태스크의 경계가 확정된 구간만 읽는 것은 취지를 해치지 않으면서 훨씬 저렴하다.

**각 태스크에 뮤테이션 테스트를 지시했다.** 이게 6건 중 4건을 잡았다. 재개해도 계속할 것을 권한다.

**서브에이전트가 Windows 경로로 리다이렉트하면** POSIX 셸이 경로 구분자를 파일명에 먹어서 저장소 루트에 `C:Userschyng...` 같은 파일이 생긴다. 커밋에 들어가지 않는지 확인할 것.
