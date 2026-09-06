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
