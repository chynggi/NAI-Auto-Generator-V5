# ComfyUI 생성 백엔드 연동 설계

날짜: 2026-09-06
상태: **설계 확정 — 구현 대기**
범위: 하위 프로젝트 B (생성단). 하위 프로젝트 A(프롬프트 출력단)는 완료 —
`docs/superpowers/specs/2026-09-06-local-sdxl-prompt-target-design.md`

## 1. 배경과 목표

A단계에서 프롬프트 컴파일러가 로컬 SDXL용 단일 Positive/Negative와 `COUPLE MASK`·
영역 JSON을 뽑게 됐다. 하지만 생성은 여전히 NovelAI API로만 나간다 — 사용자가
결과를 복사해 ComfyUI에 손으로 붙여넣어야 한다.

목표: **앱에서 바로 로컬 ComfyUI로 생성한다.** 기존 배치·와일드카드·아티스트
조합·시드 관리·갤러리는 그대로 쓴다.

### 이번 범위

- **ComfyUI만.** A1111 계열은 후속 (같은 백엔드 추상화 위에 얹는다).
- **txt2img만.** i2i·인페인팅·강화는 후속.

### 조사로 확정된 대상 환경 (2026-09-06)

이 설계는 추측이 아니라 설치된 실물을 읽고 썼다.

| 항목 | 값 |
|---|---|
| ComfyUI | v0.34.5 standalone (win-nvidia), Python 3.13.12, torch 2.12.1+cu130 |
| 설치 경로 | `%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI` |
| 모델 루트 | `%LOCALAPPDATA%\Comfy-Desktop\ComfyUI-Shared\models` |
| 포트 | 로그상 `127.0.0.1:8188` — 단 `installations.json`이 `portConflict: "auto"` |
| 확장 | `comfyui-prompt-control` 설치됨 (PC* 노드 16종) |
| 체크포인트 | `waiIllustriousSDXL_v170.safetensors` |
| diffusion_models | `Anima-2.9B-preview-v1.safetensors`, `anima-turbo-v1.1.safetensors` |
| text_encoders | `qwen_3_06b_base.safetensors` 외 |
| vae | `qwen_image_vae.safetensors` |
| loras | `anima-turbo-lora-v0.2`, `ba_anima`, `hans_anima-kei_(blue_archive)_lora` |

**포트를 고정으로 가정하지 않는다.** `portConflict: "auto"` 설정이 있어 다른 포트로
뜰 수 있다. 기본값 8188에 사용자 편집 가능.

### 비목표 (YAGNI)

- **A1111/Forge 백엔드.** 백엔드 추상화는 이번에 만들지만 구현은 후속.
- **i2i·인페인팅·강화.**
- **사용자 워크플로 템플릿 불러오기.** 내장 3종으로 시작한다. 주입 규약이 데이터로
  정의되므로 나중에 사용자 파일을 같은 경로로 읽을 수 있다.
- **ComfyUI 큐 관리 UI** (대기열 조회·재정렬). 앱은 자기 요청만 추적한다.
- **배치를 ComfyUI에 위임하기.** `batch_size`는 1로 고정하고 앱의 기존 배치 루프가
  장수를 돈다 — 위임하면 진행 표시·시드 관리·중지가 NAI 경로와 어긋난다.

## 2. 아키텍처

`GenerationService`가 이미 클라이언트를 주입받고, 실질 인터페이스가
`generate(req) -> GenerationResult` 하나다. **그 자리가 그대로 백엔드 경계다.**

```
GenerationService(backend: ImageBackend)
        │
        ├─ _prepare_request()  ← 와일드카드·아티스트 조합·{a|b}·해상도 지시어·시드
        │                        전부 백엔드 무관. 손대지 않는다.
        ↓
   backend.generate(req) → GenerationResult(raw_bytes)
        ├─ NAIClient        (기존, 무변경)
        └─ ComfyUIBackend   (신규)
```

### 핵심 판단

1. **`GenerationRequest`를 그대로 재사용한다.** NovelAI 전용 필드(`uc_preset_id`,
   `var_plus`, `vibes`, `character_refs`)가 있지만, ComfyUI 백엔드는 자기가 아는
   필드만 읽고 나머지를 무시한다. 중립 타입을 새로 만들면 `_prepare_request`의
   200줄을 전부 고쳐야 한다.

2. **샘플러 이름을 매핑하지 않는다.** NAI는 `k_euler_ancestral`, ComfyUI는
   `euler_ancestral`을 쓴다. 매핑 표를 두면 새 샘플러가 나올 때마다 표를 고쳐야 하고
   매핑 실패가 조용한 버그가 된다. 대신 **백엔드를 바꾸면 UI의 샘플러 목록 자체가
   `/object_info` 결과로 갈아끼워지므로**, `sampler` 필드에는 그 백엔드의 어휘가
   그대로 담긴다.

3. **NAI 검증은 NAI 백엔드 안에만 둔다.** `validate_request`와 `ModelSpec` 샘플러
   검사는 이미 `api/client.py` 안에 있다 — 옮기지 않는다. ComfyUI 백엔드는 자기
   검증을 하고, 최종 검증은 서버의 `node_errors`가 해 준다.

4. **능력 플래그로 크레딧·Anlas를 끈다.** `GenerationService._log_credit`이
   `client.get_subscription()`을 부른다. 프로토콜에 `supports_credit`을 두고
   로컬 백엔드면 건너뛴다.

### 모듈 배치

```
core/backends/
├─ base.py            ImageBackend 프로토콜 + 백엔드 레지스트리
├─ comfyui.py         큐 삽입 → 진행 추적 → /view 이미지 회수
├─ comfy_workflow.py  템플릿 로딩 + 값 주입 (순수 함수, I/O 없음)
├─ comfy_objects.py   /object_info 파싱
└─ comfy_progress.py  WebSocket 진행 리스너

resources/comfy_workflows/
├─ sdxl_basic.json
├─ sdxl_regional.json
└─ anima.json
```

`comfy_workflow.py`를 클라이언트에서 분리하는 이유는 A단계의 `targets`/`emitters`
분리와 같다 — 주입 로직은 순수 계산이라 서버 없이 테스트해야 하고, 실제로 가장
버그가 나기 쉬운 부분이다.

## 3. 워크플로 템플릿과 주입 규약

### 3.1 노드 제목 규칙을 쓰지 않는 이유

`_meta.title == "POSITIVE"` 같은 규칙은 쓰지 않는다. 제목은 ComfyUI UI에서 자유롭게
바뀌고, 우리가 저작한 템플릿이라도 나중에 편집하면 조용히 깨진다. **매니페스트가
슬롯을 명시한다.**

### 3.2 형식

템플릿 1개 = JSON 1개 (매니페스트 + 그래프 한 파일).

```json
{
  "id": "anima",
  "name": "Anima (UNET + Qwen3 CLIP)",
  "requires_nodes": ["UNETLoader", "CLIPLoader", "VAELoader"],
  "output_node": "9",
  "lora_mode": "direct",
  "model_slots": {
    "unet": {"path": "4.unet_name", "from": "UNETLoader.unet_name"},
    "clip": {"path": "5.clip_name", "from": "CLIPLoader.clip_name"},
    "vae":  {"path": "6.vae_name",  "from": "VAELoader.vae_name"}
  },
  "slots": {
    "positive":  "7.text",
    "negative":  "8.text",
    "seed":      "3.seed",
    "steps":     "3.steps",
    "cfg":       "3.cfg",
    "sampler":   "3.sampler_name",
    "scheduler": "3.scheduler",
    "width":     "10.width",
    "height":    "10.height"
  },
  "graph": { "3": {"inputs": {...}, "class_type": "KSampler"}, ... }
}
```

- `slots` 값은 `"<node_id>.<input_name>"`.
- `model_slots`는 **템플릿마다 개수와 이름이 다르다.** Anima는 UNET+CLIP+VAE 세 개,
  SDXL은 `checkpoint` 하나. `from`은 `/object_info` 조회 경로이고, UI는 선언된
  슬롯마다 선택기를 하나씩 그린다. 코드는 슬롯 개수를 모르는 채 동작한다.
- `requires_nodes`에 적힌 클래스가 `/object_info`에 없으면 그 템플릿을 목록에서
  **숨긴다.** 확장 없이 골라 실패하는 경로를 없앤다.

### 3.3 로드 시점 검증

모든 `slots`/`model_slots` 경로가 `graph`에 실재하는지 로드할 때 확인한다. 없으면
그 템플릿만 거부하고 경고를 남긴다 — 앱은 뜬다 (A단계 프리셋 로더와 같은 방침).
우리가 템플릿을 저작하다 오타를 내면 런타임이 아니라 로드 때 드러난다.

### 3.4 내장 템플릿 3종

| id | 로더 | `lora_mode` | 필요 확장 |
|---|---|---|---|
| `sdxl_basic` | `CheckpointLoaderSimple` | `direct` | 없음 |
| `sdxl_regional` | `CheckpointLoaderSimple` | `delegate` | comfyui-prompt-control |
| `anima` | `UNETLoader`+`CLIPLoader`+`VAELoader` | `direct` | 없음 |

**Anima 구성은 공식 템플릿 `image_anima_base_v1.json`에서 확인했다:**
`CLIPLoader(qwen_3_06b_base.safetensors, type="stable_diffusion")` —
type이 `anima`가 아니라 `stable_diffusion`이고 나머지는 파일에서 자동 감지된다.
VAE는 `qwen_image_vae.safetensors`. 샘플러 `euler` + 스케줄러 `simple`.

**터보 LoRA는 네 번째 모델 슬롯으로 둔다** (`LoraLoaderModelOnly.lora_name`),
"없음"을 고를 수 있게 한다. 템플릿을 둘로 나누지 않는 이유는 그래프가 완전히
같고 값만 다르기 때문이다. steps/cfg는 일반 슬롯이므로 사용자가 메인 창에서
조절한다 — 공식 템플릿 기준으로 터보 사용 시 8/1, 미사용 시 30/4이며, 이 권장값은
문서에 적는다. 앱이 자동으로 바꾸지는 않는다 (사용자가 정한 값을 말없이 덮어쓰면
왜 바뀌었는지 알 수 없다).

**이 터보 LoRA는 §3.5의 동적 `<lora:...>` 체인과 별개다.** 템플릿이 선언한 고정
슬롯이므로 `lora_mode`의 영향을 받지 않는다. `direct` 모드에서 앱이 삽입하는
`LoraLoader` 체인은 이 노드 **뒤에** 이어 붙인다.

### 3.5 LoRA 처리 — 템플릿마다 다르다

**`<lora:...>` 태그는 기본 ComfyUI에서 아무 일도 하지 않는다.** `CLIPTextEncode`는
그 문법을 파싱하지 않고 문자열로 인코딩한다. A단계가 뽑는 `<lora:ba_anima:0.8>`이
기본 템플릿에서는 에러 없이 무시된다.

| `lora_mode` | 동작 |
|---|---|
| `direct` | 앱이 `LoraLoader` 체인을 그래프에 삽입하고, 프롬프트에서 `<lora:...>`를 **제거**한다 |
| `delegate` | 프롬프트를 그대로 넘긴다. `PCLazyLoraLoader`가 `<lora:...>`를 읽어 체인을 만든다 |

확장의 `create_lora_loader_nodes`가 이미 같은 일을 하므로, `delegate` 모드에서
우리가 또 결선하면 LoRA가 **두 번** 걸린다.

LoRA 정보의 출처는 A단계의 `emit_regional_json`이 분리해 둔 `regions[].lora` 키다.
그때 "소비자가 LoraLoader 결선과 텍스트 태그 중 고를 수 있어야 한다"고 남긴 것이
여기서 값을 한다.

### 3.6 안전망

프롬프트에 `COUPLE MASK(`가 있는데 선택된 템플릿의 `lora_mode`가 `direct`(=확장을
쓰지 않는 템플릿)면 생성 전에 경고한다. 그 조합은 좌표 문법이 그냥 문자열로
인코딩돼 결과만 망가지는데, 에러가 없어 알아채기 어렵다.

### 3.7 출력

워크플로 끝은 `PreviewImage`(임시 디렉터리)로 둔다. `SaveImage`를 쓰면 ComfyUI
output 폴더에도 사본이 남아 디스크를 두 배로 쓴다.

`PreviewImage`는 `SaveImage`를 상속해 `save_images`를 그대로 쓰므로, **API 그래프가
PNG의 `prompt` 텍스트 청크에 심긴다** (확인함: `nodes.py`의 `save_images`).
`GenerationResult.raw_bytes`에 그대로 담기므로 재현 정보가 보존된다. UI `workflow`는
우리가 `extra_data`로 보내지 않으므로 들어가지 않는다 — 재현에는 `prompt`로 충분하다.

## 4. 요청 흐름

```
1. uuid4로 prompt_id·client_id 생성                  ← 보내기 전에 만든다
2. WS 연결 /ws?clientId={client_id}                  ← POST보다 먼저
3. POST /prompt {prompt, client_id, prompt_id}
4. WS 수신 루프 (prompt_id로 필터)
     progress_state  → 진행률 이벤트
     executed(node == output_node) → images 확보
     execution_error → 즉시 실패
5. GET /view?filename&subfolder&type=temp → raw_bytes
```

**WS를 POST보다 먼저 여는 것이 중요하다.** 반대로 하면 짧은 생성에서 `executed`를
놓쳐 영원히 기다린다.

**`prompt_id`를 우리가 정한다.** 서버는 클라이언트가 준 canonical UUID를 받아들인다
(`server.py`의 `post_prompt`). 서버 발급 id를 나중에 맞추는 경합이 없어진다.

**`/history` 폴링은 하지 않는다.** WS `executed` 메시지가 `output`을 직접 실어 온다
(`execution.py:578`). `/history/{prompt_id}`는 WS가 끊겼을 때 1회 폴백으로만 쓴다.

**진행 메시지는 `progress_state`다.** v0.34는 노드별
`{prompt_id, nodes: {id: {value, max, state}}}`를 보낸다(`comfy_execution/progress.py`).
구버전의 `progress`(`{value, max, node}`)도 함께 받아 하위 호환을 지킨다.

**중지**: 기존 `GenerationService._stop`이 내려가면 `POST /interrupt`를 보낸다.
NAI 경로는 다음 장을 안 만들면 그만이지만, ComfyUI는 큐에 들어간 작업을 계속
돌리므로 명시적 인터럽트가 필요하다.

## 5. 오류 처리

| 상황 | 처리 |
|---|---|
| 연결 거부 | `ComfyConnectionError` — "ComfyUI에 연결할 수 없습니다 ({base_url})". 서버 미실행이 가장 흔하다 |
| `POST /prompt` 400 | `node_errors`를 **그대로 노출**한다. 어느 노드의 어느 입력이 틀렸는지 서버가 알려준다 |
| 모델 파일 없음 | 위와 같은 경로로 잡힌다 (선택지에 없는 값 → `node_errors`) |
| WS `execution_error` | 노드 타입 + 예외 메시지를 표시 |
| WS 끊김 | `/history/{prompt_id}` 폴백 1회. 그래도 없으면 실패 |
| 타임아웃 | 설정값(기본 300초) |
| 템플릿 JSON 파손 / 슬롯 경로 없음 | 그 템플릿만 건너뛰고 경고 로그. 앱은 뜬다 |
| `requires_nodes` 미충족 | 템플릿을 목록에서 숨긴다 (오류 아님) |
| `/object_info` 조회 실패 | 빈 목록 + 안내. 사용자가 서버를 켜면 다시 조회 |

`node_errors`를 뭉뚱그리지 않는 것이 이 표의 핵심이다 — ComfyUI가 주는 가장 정확한
진단 정보이고, 우리가 주입을 잘못했을 때 유일하게 알려주는 창구다.

## 6. 설정과 UI

### 6.1 설정

`AppSettings`에 추가:

```python
generation_backend: str = "novelai"   # "novelai" | "comfyui"
comfyui: ComfyUISettings
```

```python
class ComfyUISettings(BaseModel):
    base_url: str = "http://127.0.0.1:8188"
    template_id: str = "sdxl_basic"
    #: 템플릿 id → {슬롯명: 선택한 모델 파일명}. 템플릿마다 슬롯이 다르므로 중첩 dict.
    model_slots: dict[str, dict[str, str]] = {}
    timeout_seconds: float = 300.0
```

기본값이 전부 있어 기존 설정 파일은 마이그레이션 없이 열린다.

### 6.2 옵션 다이얼로그 — 새 페이지 "로컬 생성"

- 연결 주소 + **연결 확인** 버튼 (`/object_info` 1회 호출로 성공/실패 표시)
- 템플릿 선택 (`requires_nodes` 미충족 항목은 숨김)
- **선언된 `model_slots`마다 모델 선택기 하나** — 목록은 `from`이 가리키는
  `/object_info` 옵션에서 채운다
- 타임아웃

자주 바뀌지 않는 값들이라 옵션에 둔다.

### 6.3 메인 창

- **백엔드 셀렉터** 추가 (`NovelAI` / `ComfyUI`).
- 기존 샘플러·스케줄러 콤보를 **백엔드에 따라 다시 채운다.** 지금은 `ModelSpec`에서
  오는데, 로컬 백엔드면 `/object_info`의 `KSampler.sampler_name`/`scheduler`
  옵션으로 바꾼다. §2의 "샘플러 이름을 매핑하지 않는다"가 여기서 값을 한다.
- 로컬 백엔드면 **Anlas 표시와 크레딧 측정을 숨긴다.**
- 모델 콤보는 NovelAI 전용으로 남는다 — ComfyUI의 모델 선택은 옵션의 슬롯 선택기가
  담당한다 (Anima처럼 모델이 3개 파일인 경우가 있어 콤보 하나로는 표현할 수 없다).

### 6.4 i18n

`resources/languages/{ko,en,ja,zh}.json`에 백엔드 셀렉터와 새 옵션 페이지 문자열 추가.

## 7. 테스트

서버 없이 도는 것과 아닌 것을 나눈다.

**신규**

- `tests/test_comfy_workflow.py` — 순수. 슬롯 주입, 경로 검증, 잘못된 슬롯 거부,
  `direct` 모드의 `LoraLoader` 체인 결선과 `<lora:...>` 제거, `delegate` 모드가
  프롬프트를 건드리지 않을 것, `batch_size` 고정
- `tests/test_comfy_backend.py` — HTTP/WS 스텁. WS를 POST보다 먼저 여는 순서,
  400 `node_errors` 표면화, `execution_error`, WS 끊김 시 `/history` 폴백,
  인터럽트, 타임아웃, `progress_state`와 구형 `progress` 양쪽 파싱
- `tests/test_comfy_objects.py` — `/object_info` 응답 파싱. 실제 응답 일부를
  픽스처로 저장해 쓴다
- **내장 템플릿 3종의 모든 슬롯 경로가 그래프에 실재하는지** 검증하는 테스트 —
  템플릿을 잘못 저작하면 CI에서 잡힌다

**보강**

- `tests/test_settings_*` — 새 설정 필드 왕복, 기존 설정 파일 로드
- 백엔드 프로토콜 준수 테스트 — `NAIClient`와 `ComfyUIBackend`가 같은 인터페이스를
  만족하는지

**라이브 스모크**: `pytest -m comfy_live`로만 도는 실제 생성 1장. 기본 실행에서
제외한다 (서버·GPU·모델이 필요하다).

## 8. 패키징

- `pyproject.toml` 필수 의존성에 `websocket-client` 추가. 이 프로젝트는 선택
  의존성을 쓰지 않는다 — exe로 받은 사용자가 설치할 수 없기 때문 (`pyproject`의
  기존 주석이 같은 이유로 `lmstudio`·`onnxruntime`을 필수로 둔 근거를 밝힌다).
- `packaging/nai-auto-v5.spec`의 `hiddenimports`에 `websocket` 추가.
- `resources/comfy_workflows/`는 `resources` 폴더가 통째로 번들되므로 자동 포함.

## 9. 하위 호환

`generation_backend` 기본값이 `"novelai"`라 기존 사용자는 아무것도 달라지지 않는다.
`NAIClient`와 `_prepare_request`는 손대지 않는다. 설정 스키마 마이그레이션 불필요.

## 10. 구현 중 확인할 것

- **`metadata/reuse.py`가 ComfyUI PNG를 만났을 때 크래시하는가.** NAI 메타데이터를
  기대하는 코드라 파싱에 실패할 텐데, 조용한 실패로 떨어지는지 확인하고 크래시라면
  가드를 추가한다.
- **LoRA 파일명의 괄호.** `hans_anima-kei_(blue_archive)_lora.safetensors`가
  `<lora:...>` 태그로 나갈 때 prompt-control 파서가 괄호를 어떻게 다루는지.
  `direct` 모드는 파일명을 `LoraLoader`에 직접 넣으므로 영향이 없다.
- **Anima 실제 생성 검증.** 설계는 공식 템플릿을 읽고 썼을 뿐 돌려 보지 않았다.
  `Anima-2.9B-preview-v1` + `qwen_3_06b_base` + `qwen_image_vae` 조합이 실제로
  이미지를 뽑는지 라이브 스모크로 확인한다.

## 11. 후속으로 미루는 것

- A1111/Forge 백엔드 (`ImageBackend` 구현 하나 추가)
- i2i·인페인팅·강화
- 사용자 워크플로 템플릿 불러오기
- `emit_regional_json`의 영역 좌표를 실제 영역 분할 노드에 결선하기 —
  이번엔 `COUPLE MASK` 문자열 경로만 지원한다
- A단계의 `weight_syntax` 활성화
