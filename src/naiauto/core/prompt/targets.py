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
]

#: NovelAI 타깃 id — 코드 내장 상수 프리셋이며 JSON으로 덮어쓸 수 없다.
NOVELAI_TARGET_ID = "novelai"

#: 사용자 프리셋 폴더에서 읽는 LoRA 레지스트리 파일 이름.
LORA_REGISTRY_FILENAME = "loras.json"

#: ``flatten``/``natural_language``/``weight_syntax``의 유효값.
_FLATTEN_VALUES = ("sequential", "couple_mask")
_NL_VALUES = ("drop", "append")
_WEIGHT_SYNTAX_VALUES = ("none", "a1111")


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
        or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in value)
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
    weight_syntax = str(data.get("weight_syntax", "none"))
    if weight_syntax not in _WEIGHT_SYNTAX_VALUES:
        raise TargetPresetError(
            f"'weight_syntax' must be one of {_WEIGHT_SYNTAX_VALUES}, got {weight_syntax!r}"
        )
    return TargetPreset(
        id=preset_id,
        name=str(data.get("name", "")).strip() or preset_id,
        kind="local",
        quality_prefix=_str_tuple(data, "quality_prefix"),
        quality_suffix=_str_tuple(data, "quality_suffix"),
        default_negative=_str_tuple(data, "default_negative"),
        weight_syntax=weight_syntax,
        flatten=flatten,
        position_tags=bool(data.get("position_tags", True)),
        natural_language=natural_language,
        underscore_to_space=bool(data.get("underscore_to_space", True)),
        mask_size=_mask_size(data),
    )


def _load_dir(directory: Path) -> list[TargetPreset]:
    """폴더의 ``*.json``을 프리셋으로 읽는다. 깨진 파일은 건너뛴다."""
    presets: list[TargetPreset] = []
    try:
        if not directory.is_dir():
            return presets
        paths = sorted(directory.glob("*.json"))
    except OSError as exc:
        logger.warning("cannot read target preset directory %s: %s", directory, exc)
        return presets
    for path in paths:
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
