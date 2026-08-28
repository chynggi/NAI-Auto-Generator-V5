"""프롬프트 컴파일러 구조 스키마.

자연어 → NovelAI V5 프롬프트 컴파일 파이프라인의 중간 표현을 정의한다.
``TagRef``/``ScenePrompt``/``CharacterPrompt``/``RelationshipPrompt``/
``CompiledPrompt``는 파이프라인 내부에서 주고받는 불변 dataclass이고,
``LLM*Model``은 LLM 파서 출력(JSON) 검증용 pydantic v2 모델이다.
Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

#: 태그 검증 상태. "verified" = DB 존재, "inferred" = 규칙 기반 정규화,
#: "unresolved" = DB 미존재 (final prompt에서 제외, §13/§41).
TagStatus = Literal["verified", "inferred", "unresolved"]


@dataclass(frozen=True)
class TagRef:
    """검증된 태그 참조 1개 (resolver → formatter)."""

    tag: str  # 정규화된 태그명 (underscore)
    status: TagStatus = "verified"
    source: str = "explicit"  # "explicit" | "inferred"
    post_count: int = 0  # DB 미존재(unresolved)면 0


@dataclass(frozen=True)
class ScenePrompt:
    """씬 수준 프롬프트 구조."""

    tags: tuple[TagRef, ...] = ()  # verified/inferred만 (final에 포함)
    raw_tags: tuple[str, ...] = ()  # LLM 원문 후보
    subjects: tuple[str, ...] = ()  # ["girl", "girl"] — count 태그용
    description: str = ""
    natural_language: str = ""
    camera: str = ""
    composition: str = ""
    style: str = ""
    lighting: str = ""
    environment: str = ""


@dataclass(frozen=True)
class CharacterPrompt:
    """캐릭터 1명의 프롬프트 구조."""

    id: str  # "c1", "c2", ...
    description: str = ""
    tags: tuple[TagRef, ...] = ()
    raw_tags: tuple[str, ...] = ()
    negative_tags: tuple[str, ...] = ()
    pose: str = ""
    expression: str = ""
    position_hint: str = ""  # "left" | "right" | "center" | "far_left" | ...
    center_x: float | None = None
    center_y: float | None = None
    natural_language: str = ""
    prompt_text: str = ""  # formatter가 만든 최종 캐릭터 prompt 문자열 (merge가 사용)


@dataclass(frozen=True)
class RelationshipPrompt:
    """캐릭터 간 관계 1개."""

    source: str  # character id
    target: str
    action: str  # 정규화된 action (snake_case)
    mutual: bool = False  # True = 양방향 (서로)


@dataclass(frozen=True)
class CompiledPrompt:
    """컴파일 최종 결과물 (merge → UI/GenerationRequest)."""

    base_prompt: str
    negative_prompt: str
    scene: ScenePrompt
    characters: tuple[CharacterPrompt, ...]
    relationships: tuple[RelationshipPrompt, ...]
    mode: str  # "tag" | "hybrid" | "natural"
    warnings: tuple[str, ...]
    unresolved: tuple[str, ...]


MODE_TAGS = ("tag", "hybrid", "natural")
DEFAULT_MODE = "hybrid"


class LLMSceneModel(BaseModel):
    """LLM 파서 출력의 scene 섹션."""

    model_config = ConfigDict(extra="forbid")

    tags: list[str]
    subjects: list[str] = []
    description: str = ""
    natural_language: str = ""


class LLMCharacterModel(BaseModel):
    """LLM 파서 출력의 character 섹션."""

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
    """LLM 파서 출력의 relationship 섹션."""

    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    action: str
    mutual: bool = False


class LLMStructuredPrompt(BaseModel):
    """LLM 파서 최종 출력.

    model_validate()로 LLM 응답 JSON을 검증한다. 스키마에 없는 필드는 전부 거부.
    """

    model_config = ConfigDict(extra="forbid")

    scene: LLMSceneModel
    characters: list[LLMCharacterModel]
    relationships: list[LLMRelationshipModel] = []
    camera: str = ""
    composition: str = ""
    style: str = ""
    negative: list[str] = []
    unresolved: list[str] = []


__all__ = [
    "TagStatus",
    "TagRef",
    "ScenePrompt",
    "CharacterPrompt",
    "RelationshipPrompt",
    "CompiledPrompt",
    "MODE_TAGS",
    "DEFAULT_MODE",
    "LLMSceneModel",
    "LLMCharacterModel",
    "LLMRelationshipModel",
    "LLMStructuredPrompt",
]