"""내장 llama.cpp 추론 provider (gigatoken 포크 기반 llama-cpp-python).

외부 llama-server 없이 앱 프로세스 안에서 GGUF 모델을 직접 로드해 추론한다.
llama-cpp-python은 선택적 의존성 — 미설치 환경에서는 첫 사용 시
``CompilerProviderUnavailableError``로 안내한다.

- **lazy 로드**: 모델은 첫 ``chat()`` 호출 시에만 로드 (앱 기동 시 VRAM 사용 안 함)
- **close()**: 모델/컨텍스트 해제 → VRAM 반환 (앱 종료 훅에서 호출)
- gigatoken 특화 파라미터: ``n_cpu_moe``(MoE 전문가 CPU 오프로드),
  ``expert_hot_s``/``expert_heat_decay``/``expert_hyst``/``expert_dwell`` 등

Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..errors import CompilerEmptyResultError, CompilerProviderUnavailableError

logger = logging.getLogger(__name__)

__all__ = ["LlamaCppProvider"]

#: lazy 로드된 llama_cpp 모듈 (스레드 안전을 위해 _ensure_loaded 안에서만 접근).
_llama_cpp = None


class LlamaCppProvider:
    """llama-cpp-python 기반 내장 추론 provider — ``LLMProvider`` 계약 구현.

    Parameters
    ----------
    model_path : str
        GGUF 모델 파일 경로 (필수).
    n_ctx : int
        컨텍스트 길이 (기본 16384 — Dense).
    n_gpu_layers : int
        GPU로 오프로드할 레이어 수 (99 = 전부, Dense 기본).
    n_cpu_moe : int
        CPU로 오프로드할 MoE 전문가 수 (Serenity 설정 22).
    n_cpu_ffn : int
        CPU로 오프로드할 Dense FFN 레이어 수 (0 = 꺼짐).
    expert_hot_s : int
        gigatoken expert hot-store 슬롯 수 (-1 = auto).
    expert_heat_decay : float
        gigatoken expert heatmap 감쇠율.
    expert_heat_log_period : int
        gigatoken expert heatmap 로그 주기 (0 = 끔).
    expert_hyst : float
        gigatoken expert 슬롯 교체 히스테리시스.
    expert_dwell : int
        gigatoken resident 슬롯 최소 유지 업데이트 수.
    flash_attn : bool
        FlashAttention 활성화.
    use_mlock : bool
        모델을 RAM에 고정 (mlock).
    type_k / type_v : int | None
        KV 캐시 데이터 타입 (예: q8_0) — None이면 모델 기본.
    """

    name = "llama_cpp"

    def __init__(
        self,
        *,
        model_path: str,
        n_ctx: int = 16384,
        n_gpu_layers: int = 99,
        n_cpu_moe: int = 0,
        n_cpu_ffn: int = 0,
        expert_hot_s: int = 0,
        expert_heat_decay: float = 0.999,
        expert_heat_log_period: int = 0,
        expert_hyst: float = 1.3,
        expert_dwell: int = 0,
        flash_attn: bool = False,
        use_mlock: bool = False,
        type_k: int | None = None,
        type_v: int | None = None,
        **_extra: Any,
    ) -> None:
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.n_gpu_layers = n_gpu_layers
        self.n_cpu_moe = n_cpu_moe
        self.n_cpu_ffn = n_cpu_ffn
        self.expert_hot_s = expert_hot_s
        self.expert_heat_decay = expert_heat_decay
        self.expert_heat_log_period = expert_heat_log_period
        self.expert_hyst = expert_hyst
        self.expert_dwell = expert_dwell
        self.flash_attn = flash_attn
        self.use_mlock = use_mlock
        self.type_k = type_k
        self.type_v = type_v
        #: lazy 로드된 Llama 인스턴스 — None이면 아직 로드 안 됨 (비상주).
        self._llm = None
        #: 로드 실패 후 재시도 방지용 (같은 오류 반복 방지).
        self._failed: str | None = None

    # ------------------------------------------------------------------
    # LLMProvider 계약
    # ------------------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float,
        max_tokens: int,
        timeout: float,
    ) -> str:
        """메시지 목록을 내장 모델로 추론해 응답 텍스트를 돌려준다.

        오류는 전부 ``CompilerError`` 계층으로 변환한다.
        """
        llm = self._ensure_loaded()
        try:
            out = llm.create_chat_completion(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            raise CompilerProviderUnavailableError(f"inference failed: {exc}") from exc
        try:
            content = out["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise CompilerEmptyResultError("unexpected LLM response shape") from exc
        if not content.strip():
            raise CompilerEmptyResultError("LLM returned an empty response")
        return content

    def close(self) -> None:
        """모델/컨텍스트를 해제해 VRAM을 반환한다 (앱 종료 훅용)."""
        if self._llm is not None:
            try:
                self._llm.close()
            except Exception:  # noqa: BLE001 — 정리 중 오류는 로그만
                logger.warning("llama_cpp close failed", exc_info=True)
            self._llm = None

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _ensure_loaded(self):
        """첫 호출 시 모델을 로드한다. 실패 원인은 ``_failed``에 기억해 반복 방지."""
        if self._llm is not None:
            return self._llm
        if self._failed is not None:
            raise CompilerProviderUnavailableError(self._failed)
        try:
            module = self._import_llama_cpp()
        except CompilerProviderUnavailableError as exc:
            self._failed = str(exc)
            raise
        if not Path(self.model_path).exists():
            self._failed = f"model file not found: {self.model_path}"
            raise CompilerProviderUnavailableError(self._failed)
        try:
            self._llm = module.Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                n_cpu_moe=self.n_cpu_moe,
                n_cpu_ffn=self.n_cpu_ffn,
                expert_hot_s=self.expert_hot_s,
                expert_heat_decay=self.expert_heat_decay,
                expert_heat_log_period=self.expert_heat_log_period,
                expert_hyst=self.expert_hyst,
                expert_dwell=self.expert_dwell,
                flash_attn=self.flash_attn,
                use_mlock=self.use_mlock,
                type_k=self.type_k,
                type_v=self.type_v,
                verbose=False,
            )
        except Exception as exc:  # ValueError(로드 실패) 등
            self._failed = f"failed to load model: {exc}"
            raise CompilerProviderUnavailableError(self._failed) from exc
        logger.info("llama_cpp model loaded: %s", self.model_path)
        return self._llm

    @staticmethod
    def _import_llama_cpp():
        """llama_cpp 모듈을 가져온다. 미설치 시 CompilerProviderUnavailableError."""
        global _llama_cpp
        if _llama_cpp is None:
            try:
                import llama_cpp  # noqa: PLC0415 — 선택적 의존성
            except ImportError as exc:
                raise CompilerProviderUnavailableError(
                    "llama-cpp-python is not installed. Install it with: "
                    "pip install /home/chynggi/llama-cpp-python"
                ) from exc
            _llama_cpp = llama_cpp
        return _llama_cpp
