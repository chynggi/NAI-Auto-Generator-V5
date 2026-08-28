# NAI-Auto-Generator-V5
# Natural Language → NovelAI V5 Multi-Character Prompt Compiler
## 코딩 에이전트용 전체 구현 지시서

---

# 0. Mission

이 저장소에 **Natural Language → NovelAI V5 Prompt Compiler** 기능을 추가한다.

사용자가 일반적인 자연어로 원하는 이미지를 설명하면, 애플리케이션이 이를 분석하여:

```text
Natural Language
        ↓
Scene / Character / Relationship Parsing
        ↓
Structured Prompt Representation
        ↓
Danbooru / NovelAI Tag Resolution
        ↓
NovelAI V5 Multi-Character Prompt Formatting
        ↓
Human Review / Edit
        ↓
Existing GenerationRequest
        ↓
Existing NAIClient.generate()
        ↓
NovelAI V5 API
```

형태로 처리한다.

최종 목표는 단순한 "자연어 → 태그 변환기"가 아니다.

**NovelAI V5에 최적화된 자연어 기반 Multi-Character Prompt Compiler**를 구현한다.

기존 NovelAI API client와 이미지 생성 시스템은 가능한 한 그대로 유지한다.

새 기능은 기존 이미지 생성 시스템의 앞단에 추가되는 **독립적인 Prompt Intelligence subsystem**이어야 한다.

---

# 1. 기존 프로젝트를 우선 이해할 것

코드를 수정하기 전에 현재 repository를 충분히 조사한다.

특히 다음을 반드시 읽는다.

```text
src/naiauto/
src/naiauto/core/
src/naiauto/core/api/
src/naiauto/core/api/models.py
src/naiauto/core/api/client.py
src/naiauto/core/api/payload_v5.py
src/naiauto/core/api/model_specs.py
```

그리고 GUI 관련 코드를 찾아 다음 구조를 파악한다.

```text
Prompt Editor
Character Prompt Editor
Negative Prompt
Preset
Settings
Workers / Background Tasks
i18n
Tag Autocomplete
Gallery
Batch Generation
```

현재 repository에 이미 존재하는 기능과 자료구조를 먼저 재사용한다.

이 프로젝트는 이미 NovelAI V5 전용 API 계층과 `GenerationRequest`, `characterPrompts`, `v4_prompt`, `v4_negative_prompt`, Danbooru tag autocomplete 등을 가지고 있으므로 기존 기능을 중복 구현하지 않는다.  

---

# 2. Absolute Requirements

다음 원칙은 반드시 지킨다.

## 2.1 ComfyUI를 사용하지 않는다

이번 기능을 위해:

- ComfyUI
- ComfyUI custom node
- 별도 ComfyUI 서버

를 dependency로 추가하지 않는다.

NeuralBooru도 런타임 dependency로 사용하지 않는다.

NeuralBooru 및 유사 프로젝트의 아이디어는 참고할 수 있지만, 최종 구현은 이 앱 안에서 독립적으로 동작해야 한다.

---

## 2.2 NovelAI API client를 재작성하지 않는다

기존:

```text
GenerationRequest
    ↓
NAIClient.generate()
    ↓
existing V5 payload
    ↓
NovelAI API
```

구조를 유지한다.

Prompt Compiler는 API client 앞에 존재한다.

올바른 dependency 방향:

```text
GUI
 ↓
Prompt Compiler
 ↓
CompiledPrompt
 ↓
GenerationRequest
 ↓
NAIClient
 ↓
NovelAI API
```

잘못된 방향:

```text
NAIClient
 ↓
PromptCompiler
```

API 계층이 Prompt Intelligence 계층에 의존해서는 안 된다.

---

# 3. 가장 중요한 개념:
# Scene / Character / Relationship 분리

자연어를 분석할 때 가장 중요한 요구사항이다.

입력:

```text
비 오는 밤의 좁은 골목에서
은발 단발머리의 교복 소녀와
검은 장발의 캐주얼한 옷차림의 소녀가
서로 마주보고 이야기하고 있다.
네온사인이 젖은 바닥에 반사되고 있고
카메라는 아래에서 위를 바라본다.
```

을 단일 prompt로 평탄화하지 않는다.

반드시 다음으로 분해한다.

```text
SCENE
CHARACTER 1
CHARACTER 2
RELATIONSHIPS / ACTIONS
CAMERA / COMPOSITION
STYLE
NEGATIVE
```

---

# 4. Prompt Responsibility Rules

## 4.1 Base / Scene Prompt

다음과 같은 정보는 기본적으로 Scene/Base prompt에 넣는다.

```text
environment
location
background
time of day
weather
lighting
atmosphere
global composition
camera
lens / framing
perspective
overall art style
global visual effects
foreground/background relationship
```

예:

```text
rain
night
narrow alley
neon_lights
wet_ground
dramatic_lighting
low_angle
```

---

## 4.2 Character Prompt

다음과 같은 정보는 Character Prompt에 넣는다.

```text
hair
hair color
hair length
eyes
eye color
face
body
age category when safe/appropriate
clothing
accessories
character-specific pose
character-specific expression
character-specific action
character-specific appearance
character-specific visual traits
```

예:

```text
silver_hair
short_hair
school_uniform
transparent_umbrella
standing
looking_at_viewer
```

---

## 4.3 Relationship / Interaction

다음 정보는 Scene 또는 Character Prompt에 무작정 섞지 않고 별도의 structured representation으로 보존한다.

```text
facing_each_other
looking_at_each_other
talking_to_each_other
holding_hands
hugging
standing_next_to
sitting_opposite
chasing
following
pointing_at
touching
```

가능한 경우 NovelAI V5의 관계/interaction 표현으로 formatter가 변환한다.

지원되는 관계 syntax는 formatter에서 관리한다.

특히 다중 캐릭터의 행동 관계를 표현할 필요가 있는 경우:

```text
source#
target#
mutual#
```

형식 등을 NovelAI V5 규칙에 따라 사용한다.

LLM이 이 syntax를 직접 최종 문자열로 결정하게 하지 않는다.

---

# 5. 입력 예시와 기대 결과

## Input

```text
카페 창가에 은발 단발머리 소녀가 앉아 있다.
교복을 입고 있고 손에는 책을 들고 있다.
맞은편에는 검은 장발 소녀가 앉아 있으며
캐주얼한 옷을 입고 있다.
두 사람은 서로를 바라보며 대화하고 있다.
창밖에는 비가 내리고 있고
따뜻한 오후 햇살과 실내 조명이 섞여 있다.
```

## Structured Representation

```json
{
  "scene": {
    "tags": [
      "cafe",
      "indoors",
      "window",
      "rain",
      "afternoon",
      "warm_lighting"
    ]
  },
  "characters": [
    {
      "id": "character_1",
      "tags": [
        "1girl",
        "silver_hair",
        "short_hair",
        "school_uniform",
        "holding_book",
        "sitting"
      ],
      "position_hint": "left"
    },
    {
      "id": "character_2",
      "tags": [
        "1girl",
        "black_hair",
        "long_hair",
        "casual_clothes",
        "sitting"
      ],
      "position_hint": "right"
    }
  ],
  "relationships": [
    {
      "source": "character_1",
      "target": "character_2",
      "action": "talking_to"
    },
    {
      "source": "character_2",
      "target": "character_1",
      "action": "talking_to"
    },
    {
      "source": "character_1",
      "target": "character_2",
      "action": "looking_at"
    },
    {
      "source": "character_2",
      "target": "character_1",
      "action": "looking_at"
    }
  ]
}
```

## Final Base Prompt

```text
2girls, cafe, indoors, window,
rain, afternoon, warm_lighting
```

## Character 1

```text
girl, silver_hair, short_hair,
school_uniform, holding_book, sitting
```

## Character 2

```text
girl, black_hair, long_hair,
casual_clothes, sitting
```

## Relationship

```text
source#talking target#talking
source#looking_at target#looking_at
```

실제 NovelAI formatter가 현재 V5 규격에 맞게 최종 표현을 결정한다.

---

# 6. Natural Language Parser

LLM은 처음부터 최종 prompt string을 만드는 것이 아니라 **Scene Understanding Layer**로 동작한다.

입력:

```text
사용자 자연어
```

출력:

```text
StructuredPrompt
```

최소 다음 항목을 지원해야 한다.

```text
scene
characters[]
relationships[]
camera
composition
style
negative
unresolved
```

---

# 7. Structured Schema

가능한 경우 dataclass 또는 현재 프로젝트와 가장 잘 맞는 typed structure를 사용한다.

최소 개념:

```python
ScenePrompt
CharacterPrompt
RelationshipPrompt
CameraPrompt
StylePrompt
NegativePrompt
CompiledPrompt
```

Character는 최소 다음 정보를 담을 수 있어야 한다.

```text
id
description
resolved_tags
raw_tags
pose
expression
position_hint
center_x
center_y
negative_tags
```

Scene은:

```text
resolved_tags
raw_tags
natural_language
camera
composition
lighting
environment
style
```

Relationship은:

```text
source_character_id
target_character_id
action
directionality
```

---

# 8. LLM Output

가능하면 JSON Schema / structured output을 이용한다.

LLM output 예:

```json
{
  "scene": {
    "tags": ["cafe", "window", "rain", "afternoon"],
    "description": "A warm cafe interior during a rainy afternoon."
  },
  "characters": [
    {
      "id": "c1",
      "description": "silver-haired short-haired schoolgirl",
      "tags": [
        "silver_hair",
        "short_hair",
        "school_uniform",
        "sitting"
      ],
      "position_hint": "left"
    },
    {
      "id": "c2",
      "description": "black-haired long-haired girl in casual clothing",
      "tags": [
        "black_hair",
        "long_hair",
        "casual_clothes",
        "sitting"
      ],
      "position_hint": "right"
    }
  ],
  "relationships": [
    {
      "source": "c1",
      "target": "c2",
      "action": "talking_to"
    }
  ]
}
```

LLM provider가 structured output을 안정적으로 제공하지 않는 경우 JSON extraction + schema validation fallback을 둔다.

Malformed JSON은 graceful error로 처리한다.

---

# 9. LLM이 하지 말아야 할 것

LLM에게 다음 권한을 주지 않는다.

```text
NovelAI API payload 직접 작성
GenerationRequest 직접 작성
NovelAI multipart payload 작성
API parameter 결정
image generation 설정 변경
```

LLM은 semantic extraction과 후보 태그 생성까지만 한다.

---

# 10. Tag Resolution

Prompt Compiler에는 deterministic tag resolver가 존재해야 한다.

LLM output:

```text
silver hair
short bob hair
warm cafe light
```

을 실제 tag database와 비교한다.

예:

```text
silver hair
    ↓
silver_hair

short bob hair
    ↓
short_hair
bob_cut

warm cafe light
    ↓
warm_lighting
```

실제 존재하지 않는 tag는 무작정 final prompt에 넣지 않는다.

---

# 11. Existing Danbooru Database 재사용

현재 앱에 내장되어 있는 Danbooru tag/autocomplete DB가 있다면 그것을 우선 사용한다.

가능한 경우 다음 데이터를 재사용한다.

```text
canonical tag
alias
category
deprecated status
frequency
```

새로운 대형 Danbooru DB를 추가로 다운로드하도록 만드는 것은 피한다.

---

# 12. Alias / Canonicalization

다음과 같은 입력을 허용한다.

```text
silver hair
silver-haired
silver-haired girl
silver_hair
```

resolver에서 canonical tag로 정규화한다.

또한 LLM이 일반 영어 표현을 사용하는 경우를 고려한다.

예:

```text
red eyes
→ red_eyes

long black hair
→ black_hair
long_hair
```

단, 의미가 불확실한 경우 과감하게 태그를 추가하지 않는다.

정확도보다 hallucinated tag 방지가 중요하다.

---

# 13. Unresolved Concepts

실제 Danbooru tag로 매핑할 수 없는 개념을 억지로 만들어내지 않는다.

예:

```text
cinematic melancholic atmosphere
```

가 존재하는 실제 tag 집합으로 정확하게 표현되지 않는다면:

```text
unresolved
```

또는 자연어 설명으로 보존한다.

최종 Hybrid formatter가 필요한 경우 natural-language segment에 남긴다.

---

# 14. Prompt Modes

최소 세 가지 모드를 제공한다.

## TAG

Danbooru / NovelAI tag 중심.

예:

```text
1girl, silver_hair, short_hair,
school_uniform, rain, night, alley
```

---

## HYBRID

**기본값.**

태그와 자연어를 조합한다.

예:

```text
1girl, silver_hair, short_hair,
school_uniform, rain, night, alley,
neon_lights, low_angle

She is standing alone in a narrow alley at night,
holding a transparent umbrella while rain falls around her.
```

NovelAI V5의 자연어 이해 능력을 적극 활용한다.

---

## NATURAL

자연어 설명 중심.

예:

```text
A silver-haired girl with short hair stands alone
in a narrow alley at night, holding a transparent umbrella.
Heavy rain falls around her and neon lights reflect
across the wet pavement.
```

---

# 15. Default Mode

기본값:

```text
Hybrid
```

이유:

```text
tag specificity
+
natural-language semantics
```

를 동시에 활용할 수 있기 때문이다.

---

# 16. Base Prompt와 Character Prompt를 UI에서도 분리한다

Prompt compiler 결과가 단순 문자열 하나로만 표시되어서는 안 된다.

예:

```text
Generated Prompt
──────────────────────────────

SCENE / BASE
rain, night, alley, neon_lights,
wet_ground, low_angle

CHARACTER 1
silver_hair, short_hair,
school_uniform,
transparent_umbrella

CHARACTER 2
black_hair, long_hair,
casual_clothes

RELATIONSHIP
character_1 ↔ character_2
talking_to
looking_at
```

그리고 최종 serialized NovelAI prompt도 별도로 보여준다.

---

# 17. Character Position

자연어에서 위치 정보를 추출한다.

예:

```text
왼쪽에 은발 소녀가 있고
오른쪽에 검은 머리 소녀가 있다.
```

Structured representation:

```text
character_1:
  position_hint = left

character_2:
  position_hint = right
```

가능하다면 실제 좌표로 변환한다.

예:

```text
character_1:
  center_x = 0.30
  center_y = 0.50

character_2:
  center_x = 0.70
  center_y = 0.50
```

단순 좌/우/중앙 등 명확한 정보가 있을 때만 자동 좌표를 계산한다.

애매한 위치는 "AI 자동 배치" 또는 기존 UI 배치에 맡긴다.

---

# 18. Character Canvas 통합

현재 앱에 존재하는 character canvas / marker editor를 재사용한다.

Compiler가 다음을 반환할 수 있어야 한다.

```text
character prompt
character negative
center_x
center_y
```

따라서 자연어 변환 후:

```text
Character 1
    ↓
existing character slot 1

Character 2
    ↓
existing character slot 2
```

로 자동 반영할 수 있다.

단, 사용자가 Apply하기 전에는 실제 설정을 변경하지 않는다.

---

# 19. Relationship Resolution

예:

```text
은발 소녀가 검은 머리 소녀를 바라본다.
```

구조:

```text
source = c1
target = c2
action = looking_at
```

예:

```text
두 사람이 서로 마주보고 있다.
```

구조:

```text
c1 → c2 : facing
c2 → c1 : facing
```

예:

```text
두 사람이 서로 손을 잡고 있다.
```

가능한 경우:

```text
mutual
```

형태로 formatter에서 처리한다.

LLM은 semantic relationship만 추출하고, NovelAI syntax는 formatter가 결정한다.

---

# 20. Character-specific vs Global Actions

매우 중요하다.

예:

```text
소녀가 우산을 들고 서 있다.
```

→ Character

```text
비가 내린다.
```

→ Scene

예:

```text
카메라는 아래에서 바라본다.
```

→ Camera / Scene

예:

```text
두 소녀가 서로 바라본다.
```

→ Relationship

예:

```text
소녀의 머리카락이 바람에 날린다.
```

→ Character 또는 character-specific motion

Parser가 이를 구분한다.

---

# 21. Count Tags

인물 수를 나타내는 태그는 Base/Scene 쪽에서 관리한다.

예:

```text
2girls
```

개별 Character Prompt에 불필요하게:

```text
2girls
```

를 반복하지 않는다.

Character prompt에는 보통:

```text
girl
...
```

처럼 해당 캐릭터 자체의 속성만 넣는다.

최종 formatter가 NovelAI V5 규칙에 맞춰 처리한다.

---

# 22. Negative Prompt

자연어에서 명시된 negative 요구사항을 분석한다.

예:

```text
손가락이 이상하게 나오지 않았으면 좋겠다.
텍스트가 들어가지 않았으면 좋겠다.
```

→

```text
bad_hands
text
```

기존 negative prompt는 보존한다.

LLM이 불필요한 대량의 generic negative tags를 자동으로 추가하지 않도록 한다.

사용자 negative와 compiler negative를 명확하게 병합한다.

---

# 23. Existing Prompt Edit

Compiler는 두 가지 입력 모드를 지원하도록 설계한다.

## CREATE

자연어 → 새로운 prompt

## MODIFY

기존 prompt + 자연어 변경사항

예:

Existing:

```text
1girl, silver_hair, school_uniform, classroom
```

Instruction:

```text
교실을 밤의 옥상으로 바꾸고 우산을 추가해줘.
```

결과:

```text
1girl, silver_hair, school_uniform,
umbrella, rooftop, night
```

단, 기존 캐릭터 특성은 보존한다.

---

# 24. Apply UX

AI 결과는 바로 덮어쓰지 않는다.

최소 다음 동작을 제공한다.

```text
Apply
Replace
Insert
```

또는 현재 UI 구조에 맞는 동등한 기능을 제공한다.

작동 원칙:

```text
Generate
  ↓
Preview
  ↓
User Review
  ↓
Apply
  ↓
Existing Prompt Editor
```

---

# 25. Regeneration

LLM 결과가 마음에 들지 않는 경우:

```text
Regenerate
```

할 수 있어야 한다.

같은 입력을 다시 요청할 경우 완전히 동일한 결과가 나올 필요는 없다.

temperature / seed 등이 provider에 따라 사용 가능하면 설정에서 관리한다.

---

# 26. LLM Provider Architecture

최소한 다음 provider들을 수용할 수 있도록 설계한다.

```text
Local OpenAI-compatible
Ollama
OpenAI-compatible Remote
```

예:

```text
Provider:
  OpenAI-compatible

Base URL:
  http://localhost:1234/v1

Model:
  gemma-4-12b
```

또는:

```text
Provider:
  Ollama

Model:
  gemma4:12b
```

Provider abstraction을 만들어 GUI가 특정 API 구현에 종속되지 않도록 한다.

---

# 27. Local-first

기본 철학은 local-first다.

가능하면 다음 환경을 쉽게 연결한다.

```text
LM Studio
llama.cpp server
Ollama
```

remote API는 선택 기능으로 둔다.

---

# 28. API Key Security

remote provider가 API key를 사용할 경우:

- 기존 프로젝트 credential handling 재사용
- 평문 설정 저장 금지
- debug log에서 key 제거

를 따른다.

---

# 29. Async / Worker

LLM inference는 GUI thread에서 직접 실행하지 않는다.

현재 프로젝트의 worker/task/thread abstraction이 있다면 그것을 재사용한다.

UI:

```text
Converting...
```

를 표시한다.

가능하면 Cancel을 지원한다.

---

# 30. Error Handling

다음 오류는 모두 graceful하게 처리한다.

```text
LLM server offline
HTTP error
authentication failure
timeout
invalid JSON
schema validation failure
tag resolver failure
unsupported model
empty result
```

오류가 발생했다고 앱 전체가 종료되면 안 된다.

기존 이미지 생성 기능은 계속 사용할 수 있어야 한다.

---

# 31. Optional Subsystem

Prompt Compiler가 없어도:

```text
기존 Prompt 입력
      ↓
Generate
```

는 완전히 정상 동작해야 한다.

즉 자연어 변환 기능은 optional feature다.

---

# 32. Compiler Architecture

권장 구조:

```text
src/naiauto/core/prompt/
    __init__.py
    compiler.py
    schema.py
    parser.py
    llm.py
    resolver.py
    formatter.py
    relationship.py
    positions.py
    merge.py
    providers/
        __init__.py
        openai_compatible.py
        ollama.py
    templates/
        nai_v5_hybrid.txt
        nai_v5_tag.txt
        nai_v5_natural.txt
```

실제 repository 구조가 더 적절하다면 조정한다.

과도한 abstraction은 피한다.

---

# 33. Module Responsibilities

## parser.py

Natural Language → Structured Prompt

## resolver.py

raw candidate → verified tag

## relationship.py

relationship normalization

## positions.py

semantic position → optional coordinates

## formatter.py

Structured Prompt → NovelAI V5 prompt structure

## merge.py

Compiler output → existing GenerationRequest compatible data

## llm.py

provider-independent interface

## providers/*

actual LLM API implementation

## compiler.py

전체 pipeline orchestration

---

# 34. Suggested Interface

다음 형태의 인터페이스를 목표로 한다.

```python
result = prompt_compiler.compile(
    text=user_text,
    mode="hybrid",
    model="nai-diffusion-5-full",
)
```

결과:

```python
CompiledPrompt(
    base_prompt=...,
    negative_prompt=...,
    characters=[...],
    relationships=[...],
    warnings=[...],
    unresolved=[...],
)
```

또한:

```python
result = prompt_compiler.modify(
    existing_prompt=...,
    instruction=...,
    mode="hybrid",
)
```

같은 API를 제공할 수 있다.

---

# 35. Formatting Layer

Formatter는 반드시 다음 정보를 분리해 보유한다.

```text
base_prompt
base_negative
character_prompts[]
character_negatives[]
character_positions[]
relationships
```

문자열 하나로 합친 다음 다시 parsing하는 식의 구조를 사용하지 않는다.

---

# 36. GenerationRequest Integration

최종 단계에서 기존 `GenerationRequest`에 맞게 변환한다.

예:

```python
request = GenerationRequest(
    prompt=compiled.base_prompt,
    negative_prompt=compiled.negative_prompt,
    characters=...,
    ...
)
```

실제 field name은 repository의 현재 구조를 확인하여 사용한다.

기존 API layer의 interface는 가능한 한 변경하지 않는다.

---

# 37. Do Not Duplicate Existing Character Logic

현재 V5 API payload에는 이미:

```text
characterPrompts
v4_prompt.caption.char_captions
v4_negative_prompt.caption.char_captions
```

등이 존재한다. 

Compiler에서는 동일한 데이터를 또 다른 독자적인 API payload로 만들지 않는다.

`GenerationRequest`가 최종 single source of truth가 되도록 한다.

---

# 38. Hybrid Prompt Policy

Hybrid mode에서는 다음 우선순위를 따른다.

```text
1. explicit user information
2. verified Danbooru tags
3. structured relationships
4. camera/composition
5. natural-language details that cannot be represented reliably by tags
6. optional stylistic elaboration
```

LLM이 멋있어 보이게 하기 위해 의미 없는 장식 문장을 추가하지 않는다.

---

# 39. Preserve User Intent

Natural Language:

```text
작고 좁은 골목
```

을

```text
wide street
```

등으로 바꾸는 식의 의미 왜곡이 발생해서는 안 된다.

LLM이 불확실할 경우:

```text
uncertain
```

상태를 유지한다.

추정과 명시 정보를 구분한다.

---

# 40. Explicit vs Inferred Information

Structured schema는 가능하면:

```text
explicit
inferred
```

를 구분할 수 있도록 설계한다.

예:

```text
"은발"
→ explicit

"1girl"
→ inferred from singular female character
```

최종 formatter는 일반적으로 inferred information도 사용할 수 있지만, UI에서는 필요하면 표시할 수 있다.

---

# 41. Tag Confidence

가능하다면:

```text
verified
inferred
unresolved
```

상태를 갖는다.

예:

```text
silver_hair      verified
short_hair       verified
cinematic_neon   unresolved
```

unresolved는 final tag에 바로 넣지 않는다.

---

# 42. GUI Result

변환 결과는 적어도 다음처럼 구조적으로 확인할 수 있어야 한다.

```text
Scene
────────────────────────
rain
night
alley
neon_lights
wet_ground

Character 1
────────────────────────
silver_hair
short_hair
school_uniform
transparent_umbrella

Character 2
────────────────────────
black_hair
long_hair
casual_clothes

Relationships
────────────────────────
Character 1 → Character 2
talking_to
looking_at
```

최종 prompt string은 별도 영역에서 보여준다.

---

# 43. Position UI

기존 character canvas가 있다면 compiler 결과를 시각적으로 반영한다.

예:

```text
Natural Language
"왼쪽에 A, 오른쪽에 B"
```

→

```text
Character A marker → left
Character B marker → right
```

이후 사용자가 직접 드래그하여 수정할 수 있어야 한다.

---

# 44. Presets

Prompt Compiler 설정을 preset과 연계할 수 있도록 설계한다.

예:

```text
NovelAI V5 Hybrid
NovelAI V5 Tags
NovelAI V5 Natural
```

단, 기존 generation presets와 충돌하지 않도록 별도 namespace를 고려한다.

---

# 45. i18n

현재 프로젝트가 이미:

```text
한국어
English
日本語
中文
```

를 지원하므로 새 GUI 문자열도 같은 i18n 시스템을 사용한다. 

새로운 문자열을 하드코딩하지 않는다.

---

# 46. Settings

최소:

```text
Prompt AI
────────────────────
Provider
Base URL
Model
API Key
Timeout

Prompt Compiler
────────────────────
Default Mode
Use Danbooru Resolver
Preserve Natural Language
Temperature
Max Output Tokens
```

현재 settings architecture에 맞게 추가한다.

---

# 47. LLM System Prompt

LLM system prompt는 소스 코드의 Python 문자열로 길게 하드코딩하지 말고 template/data 파일로 관리한다.

최소 지시:

```text
You are a NovelAI V5 prompt analysis assistant.

Your job is to transform the user's image description
into structured scene, character and relationship information.

Do not generate NovelAI API requests.

Do not invent nonexistent Danbooru tags.

Separate:
- global scene
- individual characters
- character relationships
- camera
- composition
- style
- negatives

Character-specific visual traits belong to character prompts.
Global scene/environment/camera information belongs to the base scene.

Preserve user intent.
Do not add unsupported details without justification.
Return valid structured JSON.
```

실제 prompt는 repository의 multilingual/i18n 정책에 맞게 설계한다.

---

# 48. Prompt Templates

최소:

```text
nai_v5_tag
nai_v5_hybrid
nai_v5_natural
```

을 지원한다.

필요하면:

```text
nai_v5_multicharacter
nai_v5_edit
```

등을 추가한다.

---

# 49. Existing Prompt Editing Rules

Modify mode에서 기존 prompt를 전부 재생성하지 않는다.

가능한 경우:

```text
Existing structured prompt
       +
User modification
       ↓
minimal semantic change
```

을 목표로 한다.

사용자가:

```text
배경만 밤으로 바꿔줘
```

라고 했으면 캐릭터 속성을 재작성하지 않는다.

---

# 50. Relationship Preservation During Edit

예:

Existing:

```text
A looking_at B
```

사용자:

```text
A가 B에게 손을 흔들게 해줘.
```

→ 기존 관계를 유지하면서:

```text
A waving_to B
```

등으로 확장한다.

---

# 51. Existing Wildcards

Wildcards는 Compiler가 임의로 제거하지 않는다.

예:

```text
__hairstyle__
```

가 기존 prompt에 있으면 그대로 보존하는 방향을 사용한다.

---

# 52. Existing Artist Combos

현재 artist combo 시스템도 그대로 보존한다.

Compiler가 최종 결과를 생성할 때 기존 artist combo placeholder를 깨뜨리지 않는다.

---

# 53. Prompt Ordering

Formatter는 NovelAI에서 의미가 분명하도록 일관된 순서를 사용한다.

권장:

```text
count / subject
character identities / appearance
clothing
pose / action
interaction
scene / environment
lighting
camera / composition
style
natural-language details
```

단, 실제 NovelAI V5의 prompting behavior에 맞게 조정할 수 있다.

---

# 54. Natural Language Placement

모든 자연어를 Base Prompt 마지막에 무조건 붙이지 않는다.

다음 기준을 사용한다.

```text
character-specific natural description
    → character prompt / character text

global scene description
    → base prompt / scene text

relationship description
    → relationship representation

camera description
    → scene/base
```

---

# 55. Multi-Character Count

Character 수가 2명 이상이면:

```text
2girls
3girls
...
```

같은 global count 정보를 formatter가 적절한 위치에 넣는다.

캐릭터별 prompt에는 중복 count 정보를 넣지 않는다.

Character count가 불확실하면 자동 추정하지 말고 schema에 명확한 상태를 기록한다.

---

# 56. Non-Human Characters

사람 캐릭터만 가정하지 않는다.

다음도 표현 가능해야 한다.

```text
animal
creature
object-like subject
mascot
anthropomorphic character
```

그러나 NovelAI V5가 실제로 해당 entity를 어떻게 해석하는지는 formatter와 prompt model 설정에서 고려한다.

---

# 57. Images / i2i / Inpainting

이번 기능의 1차 목표는 text-to-image prompt compiler다.

i2i / inpainting에서는 기존 prompt generation pipeline과 충돌하지 않도록 한다.

향후 자연어 edit 기능을 기존 i2i/inpainting prompt에도 사용할 수 있는 구조로 설계하지만, 이번 구현에서 이미지 분석 AI를 새로 추가할 필요는 없다.

현재 V5 API 계층의 i2i/inpaint 구현은 유지한다. 

---

# 58. WD14

WD14 tagging 시스템과 Prompt Compiler는 중복 구현하지 않는다.

WD14는:

```text
image → tags
```

를 담당한다.

Prompt Compiler는:

```text
natural language → structured prompt
```

를 담당한다.

향후 둘을 결합할 수 있도록 interface만 깔끔하게 유지한다.

---

# 59. Testing

반드시 unit tests를 추가한다.

## Schema tests

```text
valid JSON
invalid JSON
missing fields
extra fields
```

## Tag resolver tests

```text
silver hair
→ silver_hair
```

존재하지 않는 tag 처리.

## Scene / Character separation tests

```text
rain
→ scene

silver_hair
→ character

talking_to
→ relationship

low_angle
→ camera
```

## Multi-character tests

2명 / 3명 / 여러 관계.

## Position tests

left / right / center.

## Formatter tests

Tag / Hybrid / Natural.

## Existing prompt modification tests

최소 변경 보존.

## Error tests

timeout / malformed JSON / provider unavailable / resolver failure.

## Regression tests

기존 `GenerationRequest` 및 `NAIClient.generate()` 기능이 그대로 동작하는지 확인한다.

---

# 60. No Real API Calls in Unit Tests

NovelAI API key를 테스트 코드에 넣지 않는다.

LLM도 실제 remote server에 테스트 호출하지 않는다.

provider를 mock한다.

Prompt Compiler 테스트는:

```text
Natural Language
   ↓
CompiledPrompt
   ↓
GenerationRequest
```

까지 검증한다.

---

# 61. Integration Test

가능하면 fake LLM provider를 만들어 deterministic test를 만든다.

예:

```text
input:
"silver-haired girl in a cafe"

fake response:
known JSON fixture

expected:
base_prompt contains cafe
character contains silver_hair
```

---

# 62. Packaging

PyInstaller package에서 다음이 정상 포함되는지 확인한다.

```text
prompt templates
schema data
i18n
tag database dependencies
provider modules
```

사용자의 local LLM server는 패키지에 포함하지 않는다.

---

# 63. Documentation

README 또는 별도의 문서에 다음을 설명한다.

```text
Natural Language Prompt
LLM Provider 설정
Scene / Character 분리
Tag / Hybrid / Natural 모드
Local LLM 예시
NovelAI API key와 LLM API key의 차이
```

특히 다음을 명확히 한다.

```text
NovelAI API key
→ 이미지 생성용

LLM provider
→ 자연어 해석용
```

둘은 별개의 credential이다.

---

# 64. Security

NovelAI의 `pst-` token handling을 변경하지 않는다.

현재 프로젝트는 기억하기 옵션을 사용할 경우 OS keyring을 사용하도록 되어 있으므로 이 보안 모델을 유지한다. 

LLM API key도 가능한 한 동일한 credential storage 원칙을 따른다.

---

# 65. Do Not Break Existing Features

다음 기능은 자연어 compiler 구현 후에도 그대로 작동해야 한다.

```text
manual prompt input
negative prompt
character prompts
tag autocomplete
wildcards
artist combos
batch generation
presets
i2i
inpainting
gallery
PNG metadata restore
WD14 tagging
Anlas / credit display
```

---

# 66. Do Not Over-Engineer

처음부터:

```text
vector database
full RAG server
large ML model
embedding service
remote orchestration
agent framework
```

등을 도입하지 않는다.

Tag resolver는 현재 내장 데이터부터 활용한다.

필요성이 확인된 뒤에만 추가한다.

---

# 67. External Project References

구현하기 전에 다음 프로젝트의 아이디어와 구조를 조사한다.

```text
ChrisJohnson89/ComfyUI-NeuralBooru
kino-6/danbooru-prompt-compiler
joykst96/danbooru-tag-rag
Csanindzsa/danbooru-prompt-tool
2786886095/novelai-image-desktop
```

특히 확인할 것:

```text
natural-language parsing
tag candidate generation
tag whitelist validation
RAG-like tag resolution
NovelAI prompt formatting
multi-character prompting
character/scene separation
```

그러나 코드를 그대로 복사하지 않는다.

각 프로젝트의 license를 확인한다.

---

# 68. Recommended External Design Concepts

참고할 설계 원칙:

```text
LLM = semantic understanding

Tag Resolver = deterministic validation

Formatter = NovelAI-specific syntax

GenerationRequest = application-level generation contract

NAIClient = API transport
```

이 경계를 유지한다.

---

# 69. Final Architecture

최종 시스템은 다음과 같다.

```text
                 USER
                   │
                   ▼
       ┌──────────────────────┐
       │ Natural Language UI  │
       └──────────┬───────────┘
                  │
                  ▼
       ┌──────────────────────┐
       │   Prompt Compiler    │
       └──────────┬───────────┘
                  │
                  ▼
       ┌──────────────────────┐
       │   LLM Scene Parser   │
       └──────────┬───────────┘
                  │
                  ▼
       ┌──────────────────────────────┐
       │ Structured Prompt Schema     │
       │                              │
       │ Scene                        │
       │ Character[]                  │
       │ Relationship[]              │
       │ Camera                       │
       │ Composition                  │
       │ Style                        │
       │ Negative                     │
       └──────────────┬───────────────┘
                      │
          ┌───────────┼────────────┐
          ▼           ▼            ▼
       Resolver    Position     Relationship
          │           │            │
          └───────────┼────────────┘
                      ▼
       ┌──────────────────────────────┐
       │ NovelAI V5 Formatter         │
       │                              │
       │ Base Prompt                  │
       │ Character Prompts            │
       │ Character Positions          │
       │ Relationship syntax          │
       │ Natural-language segments    │
       └──────────────┬───────────────┘
                      │
                      ▼
              Human Review
                      │
                      ▼
             Existing Prompt UI
                      │
                      ▼
             GenerationRequest
                      │
                      ▼
              NAIClient.generate()
                      │
                      ▼
               NovelAI V5 API
```

---

# 70. Golden Example

입력:

```text
밤의 비 내리는 도시에서
왼쪽에는 긴 은발의 소녀가 검은 드레스를 입고 서 있고,
오른쪽에는 붉은 단발머리의 소녀가 우산을 들고 서 있다.
두 사람은 서로를 바라보고 있으며
젖은 도로에 네온사인이 반사되고 있다.
카메라는 두 사람을 낮은 앵글에서 바라본다.
```

Compiler는 먼저:

```text
SCENE
────────────────────────
city
night
rain
wet_road
neon_lights
low_angle

CHARACTER 1
────────────────────────
girl
long_hair
silver_hair
black_dress
standing
position=left

CHARACTER 2
────────────────────────
girl
short_hair
red_hair
umbrella
standing
position=right

RELATIONSHIP
────────────────────────
c1 → c2 : looking_at
c2 → c1 : looking_at
```

를 만든다.

그 후 resolver:

```text
silver_hair       ✓
long_hair         ✓
black_dress       ✓
short_hair        ✓
red_hair          ✓
umbrella          ✓
rain              ✓
wet_road          ✓
neon_lights       ✓
low_angle         ✓
```

를 수행한다.

그 후 formatter:

```text
BASE
2girls, city, night, rain, wet_road, neon_lights, low_angle

CHARACTER 1
girl, long_hair, silver_hair, black_dress, standing

CHARACTER 2
girl, short_hair, red_hair, umbrella, standing
```

을 생성한다.

마지막으로 relationship / position data를 기존 Character Prompt / coordinate 시스템으로 전달한다.

---

# 71. Primary Success Criterion

성공의 기준은:

```text
"긴 자연어 설명을 넣었더니
NovelAI가 이해하기 좋은
Scene + Character + Relationship 구조로
자동 분리되고,
사용자가 결과를 수정한 뒤
바로 Generate를 누를 수 있다."
```

이다.

단순히 태그가 많이 나오는 것이 성공이 아니다.

다음 네 가지가 가장 중요하다.

```text
1. Scene / Character separation
2. Character relationship preservation
3. Valid Danbooru / NovelAI tag resolution
4. NovelAI V5 natural-language semantics preservation
```

---

# 72. Implementation Priority

다음 순서로 구현한다.

```text
Phase 1
Repository analysis
Existing prompt / character architecture 확인

Phase 2
Structured Prompt schema

Phase 3
LLM provider abstraction

Phase 4
Natural Language → structured scene/character parser

Phase 5
Danbooru resolver

Phase 6
NovelAI V5 formatter

Phase 7
GenerationRequest integration

Phase 8
Character canvas / prompt editor integration

Phase 9
GUI / Settings

Phase 10
Modify Existing Prompt

Phase 11
Position estimation

Phase 12
Tests

Phase 13
Packaging / regression
```

---

# 73. Before Coding

코드를 바로 작성하지 말고 먼저 현재 repository에서:

```text
prompt editor
character editor
GenerationRequest
NAIClient
tag database
settings
worker/task system
i18n
tests
packaging
```

의 실제 구현을 읽는다.

기존 architecture에 맞춰 파일 위치와 API를 결정한다.

이미 존재하는 기능을 중복 구현하지 않는다.

---

# 74. Final Non-Negotiable Rules

다음은 반드시 지킨다.

```text
DO:
✓ Scene과 Character를 분리한다.
✓ Relationship을 별도 구조로 보존한다.
✓ Character-specific information을 character prompt에 넣는다.
✓ Scene/background/camera를 base prompt에 넣는다.
✓ 실제 tag validation을 수행한다.
✓ NovelAI V5 natural language를 활용한다.
✓ Hybrid를 기본값으로 한다.
✓ 기존 GenerationRequest를 재사용한다.
✓ 기존 NAIClient를 재사용한다.
✓ 기존 Character UI를 재사용한다.
✓ 기존 API authentication을 재사용한다.
✓ LLM을 optional subsystem으로 만든다.
✓ LLM provider를 local-first로 만든다.
✓ 기존 기능을 깨뜨리지 않는다.

DO NOT:
✗ ComfyUI dependency 추가
✗ NeuralBooru runtime dependency 추가
✗ API client 재작성
✗ NovelAI payload를 LLM에게 직접 생성시키기
✗ 존재하지 않는 Danbooru tag를 임의 생성
✗ 캐릭터 속성과 Scene 속성을 무분별하게 섞기
✗ LLM inference를 GUI thread에서 실행
✗ 기존 prompt를 사용자 승인 없이 덮어쓰기
✗ 기존 batch/i2i/inpaint 시스템 재작성
✗ 무거운 ML model을 앱에 번들링
```

---

# 75. Definition of Done

다음이 모두 만족되어야 완료로 간주한다.

```text
[ ] Natural Language UI가 구현되었다.
[ ] Local OpenAI-compatible LLM을 연결할 수 있다.
[ ] Ollama를 연결할 수 있다.
[ ] Structured Prompt Schema가 존재한다.
[ ] Scene / Character / Relationship이 분리된다.
[ ] Character-specific properties가 Character Prompt로 간다.
[ ] Scene properties가 Base Prompt로 간다.
[ ] Relationship이 별도 구조로 유지된다.
[ ] Character 위치 정보가 보존된다.
[ ] Danbooru tag resolution이 동작한다.
[ ] Hallucinated / nonexistent tag가 검증된다.
[ ] Tag mode가 동작한다.
[ ] Hybrid mode가 동작한다.
[ ] Natural mode가 동작한다.
[ ] Hybrid가 기본값이다.
[ ] Multi-character prompting과 통합된다.
[ ] Existing character canvas와 통합된다.
[ ] Preview가 동작한다.
[ ] Apply / Replace / Insert가 동작한다.
[ ] Existing Prompt Modify가 동작한다.
[ ] LLM 오류가 graceful하게 처리된다.
[ ] LLM 없이 기존 generation이 정상 동작한다.
[ ] Unit tests가 추가되었다.
[ ] Regression tests가 통과한다.
[ ] Packaging이 정상이다.
[ ] API credentials가 안전하게 처리된다.
```

이 프로젝트의 최종 목적은:

**“사용자가 NovelAI prompt 문법을 몰라도, 원하는 장면을 자연어로 설명하면 NovelAI V5가 이해하기 좋은 Scene + Character + Relationship prompt로 자동 컴파일하고, 기존 NAI-Auto-Generator-V5의 모든 생성 기능으로 곧바로 이어지는 것”**

이다.