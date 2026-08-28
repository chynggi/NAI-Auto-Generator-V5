"""자연어 → NovelAI V5 프롬프트 컴파일러 (core 레이어 공개 API).

사용 예::

    from naiauto.core.prompt import build_compiler, to_generation_data

    compiler = build_compiler(settings)
    compiled = compiler.compile("밤의 도시에서 은발의 소녀가 ...")
    data = to_generation_data(compiled, existing_negative="worst quality")

파이프라인: parser(LLM 구조화) → resolver(태그 검증) → positions/relationship
(정규화) → formatter(문자열) → merge(기존 GenerationRequest 연동).
Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

from naiauto.core.prompt.compiler import PromptCompiler, build_compiler
from naiauto.core.prompt.formatter import PromptFormatter
from naiauto.core.prompt.merge import MergeResult, to_generation_data
from naiauto.core.prompt.providers import API_KEY_CREDENTIAL
from naiauto.core.prompt.resolver import TagResolver
from naiauto.core.prompt.schema import CompiledPrompt

__all__ = [
    "PromptCompiler",
    "CompiledPrompt",
    "build_compiler",
    "to_generation_data",
    "MergeResult",
    "TagResolver",
    "PromptFormatter",
    "API_KEY_CREDENTIAL",
]
