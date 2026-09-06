# 로컬 SDXL/Anima 프롬프트 타깃 설계

날짜: 2026-09-06
상태: **설계 확정 — 구현 대기**
범위: 하위 프로젝트 A (프롬프트 출력단). 하위 프로젝트 B(로컬 생성 백엔드 연동)는 별도 스펙.

## 1. 배경과 목표

현재 자연어 프롬프트 컴파일러(`core/prompt/`)는 NovelAI V4/V5 전용이다.
출력물이 `base_prompt` + `negative_prompt` + **캐릭터별 `CharacterCaption[]`**
(prompt/uc/center_x·center_y)로 쪼개지고, hybrid/natural 모드에서 자연어 문단을
섞으며, 관계를 영어 문장으로 서술한다. 이 셋 다 NovelAI 고유 기능이다.

목표: 같은 파이프라인에서 **로컬 SDXL 계열(Illustrious·NoobAI·Animagine 등)이
바로 쓸 수 있는 단일 Positive/Negative 프롬프트**를 뽑는다. 사용자는 결과를
ComfyUI·A1111·Forge에 복사해 붙여넣어 쓴다.

### 범위 분해 (2026-09-06 결정)

사용자의 최종 목표는 로컬 생성 백엔드 연동까지지만, 한 스펙에 담기엔 크다.
두 하위 프로젝트로 나누고 A를 먼저 한다.

| | 내용 | 상태 |
|---|---|---|
| **A** | 프롬프트 타깃 — 프리셋 JSON, emitter, UI 타깃 셀렉터 | 이 스펙 |
| **B** | 생성 백엔드 — A1111/ComfyUI 클라이언트, `GenerationService` 분기, 샘플러·모델 매핑, 메타데이터 저장 | 후속 스펙 |

B는 A의 출력물을 소비하는 쪽이라 A가 선행한다. A만으로도 "복사해서 붙여넣기"라는
완결된 가치가 나온다.

### 비목표 (YAGNI)

- **가중치 자동 부여**(`(tag:1.2)`). LLM이 강조도를 판단할 근거가 없다.
  프리셋에 `weight_syntax` 필드만 두고 실제 사용은 후속으로 미룬다.
- **`AREA()` 출력.** `MASK()`와 합성 방식만 다르고 균등 분할 시나리오에선 이점이
  없다. 필요해지면 프리셋 필드 하나로 전환 가능한 구조로 둔다.
- **`BREAK` 구분자 출력.** A1111/Forge 문법이며 ComfyUI 기본 `CLIPTextEncode`는
  인식하지 못한다(특정 커스텀 노드팩 필요).
- **A1111 `sd-webui-regional-prompter`(ADDCOL/ADDROW) emitter.** 비율 분할만
  가능해 임의 박스 좌표를 못 쓴다. A1111/Forge 사용자는 `sequential`을 쓰면 되며,
  Regional Prompter와 함께 쓰는 방법은 **문서(MANUAL_KR.md)로만 안내**한다.
- **영역 박스 드래그 편집 UI.** 좌표는 `estimate_positions` 결과에서 자동 산출한다.
- **LoRA 자동 키워드 매칭.** 캐릭터 태그에서 LoRA를 추측하면 오탐이 많다.
  사용자가 다이얼로그에서 명시적으로 고른다.

## 2. 아키텍처

`mode`(문체 축: tag/hybrid/natural)와 **직교하는 `target`(출력 대상 축)** 을 도입한다.

```
파서(LLM) → resolver → positions/relationship        ← 타깃 무관, 그대로 재사용
                              ↓
                       CompiledPrompt                ← 단일 진실 원천
                              ↓
        ┌─────────────────────┴─────────────────────┐
   target=novelai                              target=<local>
        ↓                                            ↓
  PromptFormatter                          emitters.emit_sequential
  base + neg + CharacterCaption[]          positive + negative (characters=())
                                           emitters.emit_couple_mask   (추가 출력)
                                           emitters.emit_regional_json (추가 출력)
```

### 핵심 판단

1. **파이프라인 앞단(파서·resolver·관계 정규화)은 손대지 않는다.** 씬 이해 결과는
   타깃과 무관하다. `system_prompt.md`도 첫 줄의 "NovelAI V5 assistant"만
   중립화하고 나머지는 그대로 둔다.
2. **분기점은 `compiler._assemble`과 `merge` 두 곳뿐.**
3. **emitter는 `CompiledPrompt`를 받는 순수 함수**다. 클래스가 필요 없고,
   세 출력이 같은 자리에 놓인다. `PromptFormatter`를 상속하지 않는다 —
   그쪽은 캐릭터 분리를 전제로 짜여 있어 상속하면 두 책임이 엉킨다.
4. **어텐션 좌표 문법은 `asagi4/comfyui-prompt-control`로 고정한다** (§4.4 조사 근거).
   텍스트 프롬프트 안에 좌표와 LoRA를 동시에 넣을 수 있는 유일한 선택지이고,
   좌표계가 0..1 정규화라 우리 `regional_json`과 1:1로 대응한다.
5. **`CompiledPrompt`는 이미 "구조화 프롬프트" 그 자체**다(global scene +
   characters[id/tags/center_x/center_y] + relationships). ComfyUI 영역 분할에
   필요한 정보를 전부 갖고 있으므로 내부 표현은 바꿀 필요가 없다.
   추가되는 필드는 `target: str` 하나뿐이다.

## 3. 타깃 프리셋 (`core/prompt/targets.py`)

### 3.1 데이터 모델

```python
@dataclass(frozen=True)
class TargetPreset:
    id: str                          # "novelai" | "illustrious" | ...
    name: str                        # UI 표시명
    kind: str = "local"              # "novelai" | "local"
    quality_prefix: tuple[str, ...] = ()
    quality_suffix: tuple[str, ...] = ()
    default_negative: tuple[str, ...] = ()
    weight_syntax: str = "none"      # "none" | "a1111"  (A단계에선 미사용)
    flatten: str = "sequential"      # 기본 텍스트 emitter: "sequential" | "couple_mask"
    position_tags: bool = True
    natural_language: str = "drop"   # "drop" | "append"
    underscore_to_space: bool = True
    mask_size: tuple[int, int] | None = None   # couple_mask의 MASK_SIZE(w, h).
                                               # None이면 현재 생성 해상도를 쓴다.
```

`flatten` 유효값: `"sequential"` | `"couple_mask"`. 프리셋의 기본 텍스트 emitter를
정하지만, 다이얼로그에서 세 출력(§4)을 모두 볼 수 있으므로 **사용자를 가두지 않는다**.

### 3.2 JSON 형식

```json
{
  "id": "illustrious",
  "name": "Illustrious / NoobAI",
  "kind": "local",
  "quality_prefix": ["masterpiece", "best quality", "very awa"],
  "quality_suffix": [],
  "default_negative": ["lowres", "bad anatomy", "worst quality", "watermark"],
  "weight_syntax": "a1111",
  "flatten": "sequential",
  "position_tags": true,
  "natural_language": "drop",
  "underscore_to_space": true
}
```

### 3.3 로드 규칙

- 내장: `src/naiauto/resources/prompt_targets/*.json` —
  `illustrious.json`, `animagine.json`, `sdxl_base.json`
- 사용자: `settings.compiler.target_presets_dir` (빈 값 = 내장만)
- 같은 `id`면 **사용자 프리셋이 내장을 덮어쓴다**.
- `"novelai"`는 코드에 내장된 상수 프리셋(`kind="novelai"`)이며 JSON이 아니다.
  사용자 프리셋이 `id: "novelai"`를 선언해도 무시하고 경고 로그를 남긴다.

### 3.4 LoRA 레지스트리 (`loras.json`)

LLM은 사용자가 어떤 LoRA를 갖고 있는지 알 수 없다. **사용자 설정 레지스트리**를
두고, 캐릭터별 적용은 다이얼로그에서 명시적으로 고른다 (자동 키워드 매칭은 배제).

위치: `<target_presets_dir>/loras.json` (없으면 LoRA 기능 전체가 비활성).

```json
{
  "kafka": {
    "file": "kafka_illustrious.safetensors",
    "weight": 0.8,
    "triggers": ["kafka", "purple hair"]
  }
}
```

- `file` — 확장자 포함 파일명. `<lora:...>` 태그에는 **확장자를 뺀 stem**을 쓴다.
- `weight` — 기본 가중치. 다이얼로그에서 컴파일마다 덮어쓸 수 있다.
- `triggers` — 캐릭터 블록 맨 앞에 삽입할 트리거 단어. 빈 배열 허용.

```python
@dataclass(frozen=True)
class LoraEntry:
    id: str
    file: str
    weight: float = 1.0
    triggers: tuple[str, ...] = ()
```

**배치 규칙** (A1111·ComfyUI 모두 `<lora:...>` 태그의 위치를 따지지 않는다):

- `<lora:stem:weight>` 태그 → **글로벌 프롬프트 맨 앞**에 모은다
- `triggers` → **해당 캐릭터 블록 맨 앞**에 넣는다
- 같은 LoRA가 여러 캐릭터에 걸리면 **태그는 한 번만**, 트리거는 각 블록에

## 4. Emitter (`core/prompt/emitters.py`)

```python
def emit_sequential(compiled, preset, loras) -> tuple[str, str]   # (positive, negative)
def emit_couple_mask(compiled, preset, loras) -> tuple[str, str]
def emit_regional_json(compiled, preset, loras) -> dict
```

`loras: Mapping[str, LoraEntry]`는 **캐릭터 id → LoRA** 매핑이다 (미지정 캐릭터는 없음).
셋 다 `CompiledPrompt`만 읽는 순수 함수다.

### 4.1 `emit_sequential` — 조립 순서

```
[quality_prefix] + [count 태그] + [캐릭터 블록…] + [씬 태그]
                 + [관계 태그] + [camera/composition/style] + [NL?] + [quality_suffix]
```

1. **quality_prefix** — 맨 앞. SDXL은 앞쪽 토큰 가중이 크다.
2. **count 태그** — 기존 `PromptFormatter.count_tag()` 재사용(`2girls`).
   씬 태그 안의 중복 count 태그는 기존 `COUNT_TAG_RE`로 제거한다.
3. **캐릭터 블록** — 캐릭터 순서대로. 블록 = `[위치 태그] + 캐릭터 태그`.
   - 위치 태그: `position_hint` → `on the left` / `on the right` /
     `on the far left` / `on the far right`. `center`와 빈 값은 태그를 만들지 않는다.
   - **캐릭터가 1명이면 위치 태그를 생략한다.** 혼자인데 "on the left"는 구도만 망친다.
   - **캐릭터가 0명이면 블록 자체가 없다** (배경 프롬프트로 정상 동작).
   - `preset.position_tags == False`면 위치 태그를 전혀 넣지 않는다.
4. **씬 태그** — `rain, night, alley` 등.
5. **관계 태그** — **상호(mutual) 관계만** Danbooru 실존 태그로 매핑한다.
   단방향 관계는 SDXL 단일 프롬프트로 표현할 수단이 없다.

   | 정규화 액션 | 태그 |
   |---|---|
   | `holding_hands` | `holding hands` |
   | `hugging` | `hug` |
   | `looking_at` | `eye contact` |
   | `facing` | `facing another` |

   매핑에 없는 관계는 **드롭하되 `warnings`에 한 줄 남긴다** (조용히 버리지 않는다).
6. **camera / composition / style** — LLM이 `"low angle shot from below"`처럼
   문장으로 줄 때가 있으므로 **쉼표로 쪼개 태그화**한다.
7. **NL** — `preset.natural_language == "drop"`이면 생략, `"append"`면 맨 뒤에 붙인다.
8. **후처리** — `preset.underscore_to_space`가 참이면 결과 전체에서 `_` → 공백.
   이어서 중복 쉼표·공백을 정리한다 (`PromptFormatter._sanitize`와 같은 규칙이지만,
   그쪽은 비공개 메서드이므로 `emitters.py`에 같은 정규식을 둔다).

**negative 조립**: `preset.default_negative` + 씬 negative + 전 캐릭터
`negative_tags`. 기존 `merge.merge_negatives()`가 정확히 이 일(쉼표 분할 →
strip → 빈값 제거 → 등장 순서 유지 중복 제거)을 하므로 그대로 쓴다.

**빈 결과**: positive가 빈 문자열이면 기존 `CompilerEmptyResultError`를 던진다.

### 4.2 `emit_couple_mask` — 어텐션 좌표 출력

대상 확장: **`asagi4/comfyui-prompt-control`** (선정 근거는 §4.4).

**문법** (2026-09-06 문서 기준):

```
MASK(x1 x2, y1 y2, weight, op)     # 기본값 MASK(0 1, 0 1, 1), op 기본 multiply
COUPLE MASK(...)  ≡  COUPLE(...)   # 축약형
MASK_SIZE(width, height)           # 기본 512x512 가정 오버라이드
<lora:name:weight>                 # 인라인 LoRA
```

좌표는 **0..1 정규화 float**이다 (절대 픽셀도 되지만 혼용 불가). `regional_json`의
`x`/`width`가 그대로 `x1`/`x2`가 되므로 변환 로직이 필요 없다 —
`x1 = x`, `x2 = x + width`, `y1 = y`, `y2 = y + height`.

**출력 형식** — 글로벌 라인 + 캐릭터별 `COUPLE` 라인. positive만 이 형식이고,
negative는 `emit_sequential`과 같은 단일 문자열이다 (확장이 negative 영역 분할을
지원하지 않는다).

```
MASK_SIZE(832, 1216) <lora:kafka_illustrious:0.8> masterpiece, best quality, 2girls, rain, night, alley
COUPLE MASK(0 0.5, 0 1) kafka, purple hair, long hair, black dress
COUPLE MASK(0.5 1, 0 1) silver hair, short hair, school uniform
```

규칙:

- 글로벌 라인 = `emit_sequential`에서 **캐릭터 블록만 뺀 것** + LoRA 태그 + `MASK_SIZE`.
- `MASK_SIZE`는 `preset.mask_size`가 있으면 그 값, 없으면 **현재 생성 해상도**를 쓴다
  (다이얼로그가 `settings.generation`의 width/height를 넘긴다). 확장의 기본 가정이
  512x512라 SDXL 해상도에서는 명시하지 않으면 마스크가 어긋난다.
- 캐릭터가 **0명이면 `COUPLE` 라인이 없다** — 글로벌 라인만 나오며 `MASK_SIZE`도 생략한다.
- 캐릭터가 **1명이면 `COUPLE` 라인을 만들지 않고** 캐릭터 태그를 글로벌 라인에 합친다.
  영역 분할의 의미가 없고 `MASK(0 1, 0 1)`은 노이즈다.
- 위치 태그(`on the left` 등)는 **넣지 않는다** — 좌표가 이미 그 일을 하며 중복은
  오히려 구도를 왜곡한다. `emit_sequential`과 다른 점이다.
- 좌표 산출은 `emit_regional_json`과 같은 함수를 공유한다 (§4.3).

### 4.3 `emit_regional_json` — 출력 형식

좌표는 **0..1 정규화**다. 해상도를 곱해 픽셀로 바꾸는 일은 B단계 몫이다.

```json
{
  "target": "illustrious",
  "global": {
    "positive": "masterpiece, best quality, 2girls, rain, night, alley",
    "negative": "lowres, bad anatomy, worst quality"
  },
  "regions": [
    {
      "id": "c1",
      "positive": "silver hair, short hair, school uniform",
      "negative": "",
      "x": 0.0, "y": 0.0, "width": 0.5, "height": 1.0,
      "center_x": 0.25, "center_y": 0.5,
      "lora": {"file": "kafka_illustrious.safetensors", "weight": 0.8,
               "triggers": ["kafka", "purple hair"]}
    }
  ]
}
```

- `global.positive` = `emit_sequential`의 결과에서 **캐릭터 블록만 뺀 것**
  (quality_prefix + count 태그 + 씬 태그 + 관계 + camera/style).
- **좌표 산출**: 캐릭터를 `center_x` 오름차순 정렬한 뒤 i번째에게
  `x = i/N`, `width = 1/N`, `y = 0`, `height = 1.0` (N = 캐릭터 수).
- `center_x`/`center_y`는 `estimate_positions` 원값을 그대로 병기한다
  (중심점을 쓰는 확장 대비).
- 캐릭터가 0명이면 `regions: []`.
- `lora`는 해당 캐릭터에 LoRA가 지정된 경우에만 나온다 (없으면 키 자체가 없다).
  `regional_json`에서는 트리거를 `positive`에 합치지 않고 **분리해 둔다** —
  B단계가 노드를 어떻게 결선할지 선택할 수 있어야 한다.

`regional_json`은 `CompiledPrompt`에 저장하지 않는다 — 필요할 때 순수 함수로 만든다.

### 4.4 어텐션 좌표 확장 선정 근거 (2026-09-06 조사)

| 후보 | 방식 | 판정 |
|---|---|---|
| **`asagi4/comfyui-prompt-control`** | 프롬프트 텍스트에 `COUPLE MASK(x1 x2, y1 y2)` | **채택** |
| `Comfy Couple` / `ComfyEnhancedMultiRegion` / `AttentionCouplePPM` | 마스크를 **노드 입력**으로 받음 | 탈락 — 텍스트로 뱉을 것이 없어 A단계에 부적합. B단계 워크플로 결선 후보로는 유효 |
| `sd-webui-regional-prompter` (A1111) | `ADDCOL`/`ADDROW`/`ADDBASE` | 탈락 — 비율 분할만 가능해 임의 박스 좌표 불가. 문서로만 안내 |
| Latent Couple 계열 `[prompt: x,y,w,h]` | 확장마다 문법 상이 | 탈락 — 특정 확장 고착 |

채택 이유:

1. **텍스트만으로 완결된다.** A단계의 "복사해서 붙여넣기" 가치와 정확히 맞고,
   B단계에서 ComfyUI API로 갈 때도 텍스트 인코드 노드에 그대로 넣으면 된다.
2. **좌표계가 0..1 정규화**라 `regional_json`과 1:1 대응한다.
3. **`<lora:...>` 인라인 LoRA를 같은 문법으로 처리**한다 — 이번에 추가하는 두 기능
   (어텐션 좌표 + LoRA 트리거)을 한 출력이 커버한다.
4. SDXL 지원 확인됨 (다중 텍스트 인코더 per-encoder 프롬프트 지원).

**리스크**: 서드파티 확장의 문법 변경에 노출된다. 완화책 — `couple_mask`는
`sequential`을 대체하지 않고 **추가 출력**이며, 문법 조립은 `emitters.py`의 한
함수에 격리되어 있어 변경 시 수정 범위가 좁다.

출처:
[문법 문서](https://github.com/asagi4/comfyui-prompt-control/blob/master/doc/regional_prompts.md) ·
[Attention Couple 문서](https://github.com/asagi4/comfyui-prompt-control/blob/master/doc/attention_couple.md) ·
[저장소](https://github.com/asagi4/comfyui-prompt-control) ·
[sd-webui-regional-prompter](https://github.com/hako-mikan/sd-webui-regional-prompter)

## 5. 파이프라인 연결

### 5.1 `schema.py`

`CompiledPrompt`에 `target: str = "novelai"` 필드 추가. 다른 변경 없음.

### 5.2 `compiler.py`

- `compile(text, *, mode="hybrid", target="novelai")`
- `modify(existing_prompt, instruction, *, mode="hybrid", target="novelai")`
- `_assemble(raw, mode, target)`:
  - `target` 프리셋의 `kind == "novelai"` → 기존 `PromptFormatter` 경로 그대로
  - 그 외 → 프리셋의 `flatten`에 따라 `emit_sequential` 또는 `emit_couple_mask`로
    `base_prompt`/`negative_prompt`를 만든다.
    캐릭터의 `prompt_text`는 로컬 타깃에서 쓰이지 않으므로 채우지 않는다.
- `compile`/`modify`에 `loras: Mapping[str, LoraEntry] | None = None` 인자를 더한다
  (다이얼로그의 캐릭터별 선택 결과). `None`이면 LoRA 없이 조립한다.
- `couple_mask`의 `MASK_SIZE`용 해상도도 인자로 받는다
  (`resolution: tuple[int, int] | None = None`).
- `build_compiler(settings)`가 프리셋 목록을 로드해 컴파일러에 넘긴다.
- **`modify`의 보존 토큰(`__dynamic__`/`{artist:grp}`) 스플라이스는 로컬 타깃에서도
  동일하게 동작해야 한다** — 태그 라인(첫 `\n\n` 앞)에 붙이는 기존 로직이
  로컬 타깃의 단일 라인 출력에서도 맞다.

### 5.3 `merge.py`

`to_generation_data(compiled, *, existing_negative="")`에서
`compiled.target`의 프리셋 `kind`가 `"novelai"`가 아니면 `characters=()`를 반환한다.
호출부 시그니처는 바뀌지 않는다.

### 5.4 `templates/system_prompt.md`

첫 줄만 중립화한다 (1줄 변경). 나머지 규칙은 타깃과 무관하므로 유지.

## 6. UI · 설정

### 6.1 `prompt_compiler_dialog.py`

- 기존 모드 콤보 옆에 **타깃 콤보** 추가. 항목은 프리셋 목록에서 동적으로 채운다
  (`NovelAI V5` + 내장 + 사용자 프리셋).
- 로컬 타깃 선택 시:
  - 미리보기가 **Positive / Negative 2칸**으로 전환, 캐릭터별 미리보기 영역은 숨김
  - 미리보기에 **탭 3개**: `프롬프트`(프리셋 `flatten` 결과) ·
    `COUPLE MASK` · `영역 JSON`. 각 탭에 복사 버튼.
    세 출력을 모두 보여 주므로 프리셋의 `flatten` 값이 사용자를 가두지 않는다.
  - 하단에 "캐릭터 프롬프트는 본문에 합쳐집니다" 안내
  - `COUPLE MASK` 탭에는 **"comfyui-prompt-control 확장이 필요합니다"** 안내를 붙인다.
- **캐릭터별 LoRA 선택 UI**: 로컬 타깃일 때 캐릭터 목록 옆에 LoRA 드롭다운
  (기본 "없음") + 가중치 스핀박스. 항목은 `loras.json`에서 채운다.
  `loras.json`이 없으면 이 UI 자체를 숨긴다.
  컴파일 결과의 캐릭터 수가 바뀌면 선택을 **캐릭터 id 기준으로 유지**한다.
- **"적용" 시 캐릭터 프롬프트 탭은 건드리지 않는다** (기존 사용자 입력 보존).
  `CompilerApplyPayload.characters`가 비어 있으므로 main_window가 캐릭터 탭을
  비우지 않도록 확인이 필요하다.
- 입력 히스토리(`InputHistoryEntry`)에 **`target`만** 저장하고 복원한다.
  LoRA 선택은 넣지 않는다 — 레지스트리가 바뀌면 복원이 어긋나고, 선택은 컴파일
  *결과*의 캐릭터에 붙는 것이라 *입력* 스냅숏의 성격이 아니다.

### 6.2 설정

`CompilerSettings`에 추가:

```python
default_target: str = "novelai"
target_presets_dir: str = ""     # 빈 값 = 내장 프리셋만
```

### 6.3 옵션 페이지

기존 `options_pages/prompt_ai_page.py`에 **"출력 타깃" 그룹**을 추가한다.
새 페이지는 만들지 않는다.

- 기본 타깃 선택 콤보
- 프리셋 폴더 경로 선택 (`loras.json`도 이 폴더에서 읽는다)
- LoRA 레지스트리 상태 표시 (`loras.json` 없음 / N개 로드됨)

**프리셋 내용 편집은 넣지 않는다** (2026-09-06 계획 수립 중 결정). 앱이 사용자
프리셋 파일을 써 넣는 경로를 만들면 내장/사용자 병합 규칙과 얽히고, 편집 UI
하나를 위해 저장 로직이 통째로 필요해진다. 프리셋도 `loras.json`과 같은 방침으로
간다 — **폴더를 열어 파일을 직접 고치게 하고, 앱은 로드 상태만 보여 준다.**

### 6.4 i18n

`resources/languages/{ko,en,ja,zh}.json`에 `compiler.target*` 키 추가.

### 6.5 upstream LM Studio 기능과의 관계

2026-09-06 upstream v0.7.5 병합으로 LM Studio 프롬프트 어시스턴트(`LMStudioSettings`,
WD14 태거 / LM Studio 태거 / 이미지 변형)가 들어왔다. **컴파일러와 통합하지 않고
병존시킨다** — 어시스턴트는 *이미지 → 태그* 및 *자유 변형*, 컴파일러는
*구조화 씬 이해 → 검증된 태그*로 목적이 다르다.

## 7. 오류 처리

기존 `errors.py` 계층을 재사용하고 새 예외는 하나만 만든다.

| 상황 | 처리 |
|---|---|
| 프리셋 JSON 파싱 실패 / 스키마 위반 | 새 `TargetPresetError`. 해당 프리셋만 건너뛰고 로그 경고 — 앱은 정상 기동 |
| 사용자 프리셋 폴더 없음 / 읽기 실패 | 내장 프리셋만으로 조용히 폴백 |
| `default_target`이 존재하지 않는 id | `"novelai"`로 폴백 + 경고 로그 |
| 사용자 프리셋이 `id: "novelai"` 선언 | 무시 + 경고 로그 |
| 로컬 타깃인데 캐릭터 0명 | 정상 — 배경 프롬프트 |
| 관계 태그 매핑 실패 | 드롭 + `warnings`에 1줄 |
| `emit_sequential` 결과가 빈 문자열 | 기존 `CompilerEmptyResultError` |
| `loras.json` 없음 | LoRA 기능 비활성 (조용히). 다이얼로그의 LoRA UI 숨김 |
| `loras.json` 파싱 실패 / 항목 스키마 위반 | 해당 항목만 건너뛰고 로그 경고. 파일 전체가 깨졌으면 빈 레지스트리로 폴백 |
| 선택된 LoRA id가 레지스트리에 없음 | 그 캐릭터의 LoRA를 조용히 건너뛴다. LoRA 선택은 히스토리에 저장하지 않으므로(§6.1) 세션 중 레지스트리 파일이 바뀐 경우에만 생긴다 |
| `couple_mask` 요청인데 캐릭터 0~1명 | 정상 — `COUPLE` 라인 없이 글로벌 라인만 |

## 8. 테스트

기존 `tests/` 규약(LLM은 스텁 provider로 대체)을 따른다.

**신규**

- `tests/test_targets.py` — 프리셋 로드, 사용자/내장 병합, 잘못된 JSON 무시,
  `default_target` 폴백, `id: "novelai"` 거부, `loras.json` 로드/누락/깨진 항목 폴백
- `tests/test_emitters.py`
  - `emit_sequential`: 조립 순서, 1인 위치 태그 생략, 0인 배경 프롬프트,
    count 태그 중복 제거, `underscore_to_space`, 관계 태그 매핑,
    매핑 실패 시 경고, negative 중복 제거, camera 문장의 쉼표 태그화,
    `natural_language` drop/append
  - `emit_couple_mask`: `MASK_SIZE` 삽입(프리셋 값 / 생성 해상도 / 0인 시 생략),
    좌표 변환(`x1=x`, `x2=x+width`), 1인 시 `COUPLE` 라인 없이 글로벌 병합,
    0인 시 글로벌 라인만, 위치 태그가 들어가지 **않을** 것,
    negative가 단일 문자열일 것
  - `emit_regional_json`: 좌표 균등 분할(1·2·3인), 0인 시 빈 regions,
    `global.positive`에 캐릭터 태그가 없을 것, `center_x` 정렬 순서,
    LoRA 미지정 시 `lora` 키 부재, 트리거가 `positive`에 합쳐지지 **않을** 것
  - LoRA 공통: `<lora:stem:weight>`가 글로벌 맨 앞에 1회만(중복 캐릭터),
    트리거가 해당 캐릭터 블록 맨 앞에, 확장자가 stem으로 잘릴 것

**보강**

- `tests/test_merge.py` — 로컬 타깃일 때 `characters=()`
- `tests/test_compiler.py` — `target`/`loras`/`resolution` 인자 전달,
  `flatten`에 따른 emitter 선택, `modify`의 보존 토큰이 로컬 타깃에서도 유지될 것
- `tests/test_compiler_dialog.py` — 타깃 전환 시 미리보기 전환, 탭 3개 렌더,
  적용 시 캐릭터 탭 미변경, 히스토리의 `target` 복원,
  `loras.json` 없을 때 LoRA UI 숨김, 재컴파일 시 id 기준 선택 유지
- `tests/test_settings_compiler.py` — `default_target`/`target_presets_dir` 왕복 저장

## 9. 변경 파일

**신규**

| 파일 | 규모 |
|---|---|
| `src/naiauto/core/prompt/targets.py` | ~160줄 (프리셋 + LoRA 레지스트리) |
| `src/naiauto/core/prompt/emitters.py` | ~260줄 (emitter 3종) |
| `src/naiauto/resources/prompt_targets/illustrious.json` | — |
| `src/naiauto/resources/prompt_targets/animagine.json` | — |
| `src/naiauto/resources/prompt_targets/sdxl_base.json` | — |
| `tests/test_targets.py` | — |
| `tests/test_emitters.py` | — |

**수정**

- `core/prompt/schema.py` — `CompiledPrompt.target`
- `core/prompt/compiler.py` — `target`/`loras`/`resolution` 인자, `_assemble` 분기,
  `build_compiler` 프리셋·레지스트리 로드
- `core/prompt/merge.py` — 로컬 타깃 `characters=()`
- `core/prompt/errors.py` — `TargetPresetError`
- `core/prompt/templates/system_prompt.md` — 첫 줄 중립화
- `core/settings/schema.py` — `default_target`, `target_presets_dir`
- `ui/prompt_compiler_dialog.py` — 타깃 콤보, 미리보기 3탭, 캐릭터별 LoRA 선택 UI
- `ui/options_pages/prompt_ai_page.py` — "출력 타깃" 그룹, LoRA 레지스트리 상태
- `resources/languages/{ko,en,ja,zh}.json` — `compiler.target*`, `compiler.lora*`
- `README.md` — 기능 설명
- `MANUAL_KR.md` — 기능 설명 + **comfyui-prompt-control 설치 안내** +
  **A1111/Forge에서 Regional Prompter와 함께 쓰는 법** (emitter를 만들지 않는 대신
  `sequential` 출력을 `ADDCOL`로 나눠 쓰는 절차를 문서로 안내)

**수정 불필요**: `packaging/nai-auto-v5.spec` — `resources` 폴더를 통째로 번들하므로
`prompt_targets/`가 자동 포함된다.

## 10. 하위 호환

`target` 기본값이 `"novelai"`이므로 기존 설정 파일·프리셋·호출부는 전부 그대로
동작한다. **설정 스키마 마이그레이션 불필요** (pydantic 기본값이 채운다).

## 11. B단계로 넘기는 것

- A1111 WebUI API / ComfyUI 클라이언트, `NAIClient` 옆의 백엔드 추상화
- `GenerationService._prepare_request` / `_generate_with_policy` 분기
- 샘플러·스케줄러·모델 이름 매핑, 해상도 프리셋
- 메타데이터 저장 (A1111 `parameters` PNG chunk vs NAI stealth PNG)
- Anlas/크레딧 로직 우회, UI 모델 선택기 개편
- `emit_regional_json`을 실제 ComfyUI 워크플로에 주입 (영역 분할 노드 결선).
  A단계에서 `regions[].lora`를 프롬프트에 합치지 않고 분리해 둔 이유가 이것이다 —
  `LoraLoader` 노드로 실제 결선할지, 텍스트 태그로 넘길지 B단계가 고른다
- 가중치 문법(`weight_syntax`) 활성화 — 프리셋 필드는 A에서 이미 만들어 둔다
- LoRA 파일 존재 검증 (백엔드의 LoRA 폴더를 조회할 수 있게 되는 시점)
