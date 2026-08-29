# 내장 llama.cpp 추론 (LlamaCppProvider) 설계

날짜: 2026-08-28
상태: **스파이크 완료 — 설계 확정** (빌드/실행 검증 통과)

## 1. 배경과 목표

현재 자연어 프롬프트 컴파일러는 외부 llama-server(OpenAI 호환 HTTP API)에
의존한다. 사용자는 다음 문제를 해결하려 한다:

- 포트/Base URL 설정, 서버 기동·종료 프로세스 관리 번거로움
- 다른 PC로의 배포 시 llama-server 설치 요구
- **LLM을 상주시키지 않아도 됨** — 앱 사용 시에만 모델 로드, 종료 시 VRAM 해제

접근: llama-cpp-python을 사용자의 커스텀 포크
`/home/chynggi/gigatoken-llama.cpp` 소스로 CUDA 빌드해 앱 프로세스 안에서 추론.
provider 계층에 `llama_cpp` 타입을 추가 — UI/컴파일러는 기존 `LLMProvider`
프로토콜을 그대로 사용한다.

## 2. 스파이크 결과 (2026-08-28 검증 완료)

### 빌드 스택
- `llama-cpp-python` 포크 클론: `/home/chynggi/llama-cpp-python` (v0.3.35)
- `vendor/llama.cpp` → `/home/chynggi/gigatoken-llama.cpp` 심볼릭 링크
- 빌드: `CMAKE_ARGS="-DGGML_CUDA=ON -DGGML_NATIVE=ON -DGGML_CUDA_FA_ALL_QUANTS=ON -DCMAKE_BUILD_TYPE=Release"`
- RTX 3060 12GB 검증 완료

### 바인딩 확장 (포크 수정 — 커밋 필요)
| 수정 | 내용 |
|---|---|
| `llama_model_params` | `tensor_read_lazy` 필드 추가 (구조체 정합성 버그 수정 — 없으면 `vocab_only=7` 오염) |
| `llama_context_params` | gigatoken 필드 5개 추가: `expert_heat_decay`, `expert_heat_log_period`, `expert_hot_s`, `expert_hyst`, `expert_dwell` |
| `llama_model_tensor_buft_override` | ctypes 구조체 신규 정의 |
| `ggml_backend_cpu_buffer_type()` | ctypes 바인딩 신규 |
| `tensor_buft_overrides` 필드 | `POINTER(llama_model_tensor_buft_override)`로 타입 변경 |
| `Llama.__init__` | `n_cpu_moe`, `n_cpu_ffn`, `expert_hot_s`, `expert_heat_decay`, `expert_heat_log_period`, `expert_hyst`, `expert_dwell` 파라미터 추가 |

### 실행 검증 (실제 모델)

| 모델 | 설정 | 결과 |
|---|---|---|
| stories15M | 기본 | ✅ 로드/추론 정상 |
| gemma-4-12B IQ4_XS (Dense) | `n_gpu_layers=99` (전체 GPU) | ✅ 로드 1.9s / 추론 1.7s |
| Serenity-26B-A4B Q6_K (MoE) | `n_cpu_moe=22`, `expert_hot_s=-1`, `n_gpu_layers=12`, `flash_attn=True` | ✅ 로드 2.5s / 추론 4.8s |

## 3. 사용자 실행 설정 분석 (llama-server → 내장 파라미터 매핑)

### MoE (Serenity-26B-A4B-HB16-Q6_K.gguf, 23.5GB)

| llama-server | 값 | 내장 파라미터 | 상태 |
|---|---|---|---|
| `-m` | Serenity-26B-A4B-HB16-Q6_K.gguf | `model_path` | ✅ |
| `-ncmoe 22` | 22 | `n_cpu_moe=22` (tensor_buft_overrides) | ✅ 노출 |
| `-c 32768` | 32768 | `n_ctx=32768` | ✅ |
| `--flash-attn 1` | on | `flash_attn=True` | ✅ |
| `--load-mode mlock` | mlock | `use_mlock=True` | ✅ |
| `--chat-template-file` | chat_template.jinja | `chat_template=<파일 내용>` | ✅ (Llama 파라미터) |
| `--kv-unified` | on | context_params.kv_unified | ✅ (embedding 시 자동, 직접 설정 필요 시 추가 노출) |
| `-md` | gemma-4-26B-A4B-it-assistant.Q4_K_M | `draft_model=LlamaDraftModel(...)` | ⏳ 기존 파라미터 있음 — 설정 UI에서 지원 여부 결정 |
| `--spec-type draft-mtp` | draft-mtp | `draft_model` + load_mtp | ⏳ 확인 필요 |
| `--backend-sampling` | on | context_params.backend_sampling | ⚠️ gigatoken llama.h 필드 아님 — 서버 common 계층 전용 |
| `--expert-hot-s -1` | -1 | `expert_hot_s=-1` | ✅ 노출 |
| `-fit off` | off | — | ⚠️ gigatoken common 계층 — 미지원 (기본 동작과 동일) |
| `-np 2` | 2 | `n_parallel` | ⏳ Llama에는 미노출 — 단일 시퀀스면 불필요 |
| `-ctk q8_0 -ctv q8_0` | q8_0 | `type_k=GGML_TYPE_Q8_0, type_v=...` | ✅ (Llama 파라미터) |

### Dense (gemma-4-12B-it-blorbo IQ4_XS, 7.2GB)

동일 구조 + `n_cpu_moe=0`, `n_ctx=16384`(또는 4096), `type_k/v` 미지정.

## 4. 아키텍처

### 4.1 LlamaCppProvider (신규: `core/prompt/providers/llama_cpp.py`)

- `LLMProvider` 프로토콜 구현 (`name = "llama_cpp"`)
- 생성자: `model_path`, `n_ctx`, `n_gpu_layers`, `n_cpu_moe`, `n_cpu_ffn`,
  `expert_hot_s`, `expert_heat_decay`, `expert_heat_log_period`, `expert_hyst`,
  `expert_dwell`, `flash_attn`, `use_mlock`, `chat_template`, `type_k/type_v`,
  `load_mtp`, `draft_model_path` (선택)
- **lazy 로드**: 첫 `chat()` 호출 시 `Llama(...)` 생성 — 앱 기동 시점에
  VRAM을 쓰지 않는다 (비상주 요구 충족)
- `chat()`: `messages`를 `llm.create_chat_completion(messages, ...)`로 전달
  (temperature/max_tokens 매핑). 커스텀 `chat_template` 문자열은
  `Llama(chat_template=...)`로 전달
- `close()`: `Llama`의 컨텍스트/모델 해제 (VRAM 반환) — 앱 종료 시 호출
- 오류 변환: 모델 파일 없음/로드 실패 → `CompilerProviderUnavailableError`,
  추론 실패 → `CompilerError` 계열

### 4.2 설정 (`core/settings/schema.py`)

`PromptAISettings`에 추가:

```python
provider: str = "openai_compatible"  # + "llama_cpp" 허용
model_path: str = ""        # GGUF 경로 (llama_cpp 전용)
n_gpu_layers: int = 99      # Dense 전체 오프로드 기본
n_cpu_moe: int = 0          # MoE 전문가 CPU 오프로드 수 (Serenity=22)
expert_hot_s: int = 0       # gigatoken expert hot store (-1 = auto)
n_ctx: int = 16384          # Dense 기본
```

- `base_url`/`model`은 `openai_compatible`/`ollama` 전용으로 유지
- UI (prompt_ai_page): provider 콤보에 "내장 (llama.cpp)" 추가.
  선택 시 Base URL 입력 대신 **모델 파일 선택 버튼**(QFileDialog) +
  `n_gpu_layers`/`n_cpu_moe`/`expert_hot_s`/`n_ctx` 스핀박스 표시

### 4.3 provider 생성 (`core/prompt/providers/__init__.py`)

`create_provider()`에 `"llama_cpp"` 분기 — `LlamaCppProvider` 반환.

### 4.4 컴파일러 (`core/prompt/compiler.py::build_compiler`)

- provider_name이 `llama_cpp`이면 `model_path`/`n_ctx` 등으로 provider 생성
- 선번역(RAG)과 파싱 모두 같은 내장 모델 사용
- `prompt_ai.model_path`가 비면 `CompilerProviderUnavailableError` (모델 미설정 안내)

### 4.5 스레딩

in-process 추론은 블로킹 — `prompt_compiler_dialog.py`의 컴파일 실행을
QThread worker로 분리 (WD14Dialog의 `_InferenceWorker` 패턴 재사용).
구현 전 다이얼로그의 현재 실행 구조 확인 필요.

### 4.6 수명주기

- 모델은 컴파일러 생성 시(첫 사용)에 로드 — 앱 기동 시엔 로드하지 않음
- 앱 종료 시 `close()` — MainWindow 종료 훅에서 호출
- (후속 옵션) 다이얼로그 닫힘 시 언로드 — 초기 범위에선 앱 종료 시점으로 한정

## 5. 테스트

- 단위: `create_provider("llama_cpp", ...)` 분기, 설정 스키마 기본값,
  UI provider 전환 시 필드 표시/숨김
- `LlamaCppProvider` 자체는 실제 모델 로드가 필요하므로 스파이크에서 검증 완료
  (모의 객체로 오류 변환만 테스트)
- 스파이크: stories15M → Dense 전체 GPU → MoE(n_cpu_moe=22) 전부 통과

## 6. 배포 (분리된 후속 작업)

PyInstaller 빌드에 llama_cpp 동적 라이브러리(.so) 포함은 별도 이슈로
분리한다. 개발 환경(conda)에서는 `pip install /home/chynggi/llama-cpp-python`
정식 설치로 해결.

## 7. 오류 처리 요약

| 상황 | 동작 |
|---|---|
| llama_cpp 미설치 | `CompilerProviderUnavailableError` (설치 안내) |
| 모델 파일 없음/경로 미설정 | `CompilerProviderUnavailableError` |
| VRAM 부족/로드 실패 | `CompilerError` (사용자 메시지) |
| 추론 타임아웃 | 기존 timeout 계약 유지 |
| 앱 종료 | `close()` → VRAM 해제 |

