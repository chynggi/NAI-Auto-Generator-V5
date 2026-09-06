"""워크플로 템플릿 로딩·검증 테스트 — 서버 없이 돈다."""

import json

import pytest

from naiauto.core.backends.comfy_workflow import (
    LoraAssignment,
    build_graph,
    builtin_workflows_dir,
    load_workflows,
    parse_template,
    strip_lora_tags,
)
from naiauto.core.backends.errors import ComfyTemplateError

MINIMAL = {
    "id": "demo",
    "name": "Demo",
    "output_node": "9",
    "lora_mode": "direct",
    "model_slots": {
        "checkpoint": {"path": "4.ckpt_name", "from": "CheckpointLoaderSimple.ckpt_name"}
    },
    "slots": {"positive": "6.text", "seed": "3.seed"},
    "graph": {
        "3": {"inputs": {"seed": 0, "model": ["4", 0]}, "class_type": "KSampler"},
        "4": {"inputs": {"ckpt_name": ""}, "class_type": "CheckpointLoaderSimple"},
        "6": {"inputs": {"text": "", "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
        "9": {"inputs": {"images": ["8", 0]}, "class_type": "PreviewImage"},
    },
}


def test_parse_reads_all_fields():
    t = parse_template(MINIMAL)
    assert t.id == "demo"
    assert t.name == "Demo"
    assert t.output_node == "9"
    assert t.lora_mode == "direct"
    assert t.slots["positive"] == "6.text"
    assert t.model_slots["checkpoint"].path == "4.ckpt_name"
    assert t.model_slots["checkpoint"].source == "CheckpointLoaderSimple.ckpt_name"
    assert t.requires_nodes == ()


def test_parse_defaults():
    data = {**MINIMAL}
    data.pop("lora_mode")
    t = parse_template(data)
    assert t.lora_mode == "direct"


@pytest.mark.parametrize(
    "mutate, reason",
    [
        (lambda d: d.pop("id"), "id 없음"),
        (lambda d: d.update(id=""), "id 빈 문자열"),
        (lambda d: d.pop("graph"), "graph 없음"),
        (lambda d: d.update(output_node="99"), "output_node가 그래프에 없음"),
        (lambda d: d.update(lora_mode="nope"), "lora_mode 유효값 아님"),
        (lambda d: d.update(slots={"positive": "99.text"}), "슬롯 노드가 없음"),
        (lambda d: d.update(slots={"positive": "6.nope"}), "슬롯 입력이 없음"),
        (lambda d: d.update(slots={"positive": "6text"}), "슬롯 경로에 점이 없음"),
        (lambda d: d.update(slots={"positive": "6.text.extra"}), "슬롯 경로에 점이 둘"),
        (
            lambda d: d.update(
                model_slots={"c": {"path": "99.x", "from": "A.b"}}
            ),
            "모델 슬롯 노드가 없음",
        ),
        (
            lambda d: d.update(model_slots={"c": {"path": "4.ckpt_name"}}),
            "모델 슬롯에 from 없음",
        ),
        (
            lambda d: d.update(model_slots={"c": {"path": "4.ckpt_name", "from": "A.b.c"}}),
            "model_slots.from에 점이 둘",
        ),
    ],
)
def test_parse_rejects_invalid(mutate, reason):
    data = json.loads(json.dumps(MINIMAL))
    mutate(data)
    with pytest.raises(ComfyTemplateError):
        parse_template(data)


def test_builtin_dir_exists():
    assert builtin_workflows_dir().is_dir()


def test_load_workflows_reads_builtins():
    ids = {t.id for t in load_workflows()}
    assert "sdxl_basic" in ids


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_user_dir_uses_builtins_only(blank):
    """빈 문자열이 Path('')=CWD가 되어 아무 json이나 읽는 일이 없어야 한다."""
    ids = {t.id for t in load_workflows(blank)}
    assert "sdxl_basic" in ids


def test_broken_file_is_skipped_not_fatal(tmp_path):
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "good.json").write_text(json.dumps(MINIMAL), encoding="utf-8")
    ids = {t.id for t in load_workflows(tmp_path)}
    assert "demo" in ids
    assert "broken" not in ids


def test_user_dir_overrides_builtin_by_id(tmp_path):
    data = json.loads(json.dumps(MINIMAL))
    data["id"] = "sdxl_basic"
    data["name"] = "My Basic"
    (tmp_path / "mine.json").write_text(json.dumps(data), encoding="utf-8")
    by_id = {t.id: t for t in load_workflows(tmp_path)}
    assert by_id["sdxl_basic"].name == "My Basic"


def test_unreadable_dir_is_skipped_not_fatal(tmp_path, monkeypatch):
    """읽을 수 없는 폴더가 앱 기동을 막지 않는다."""
    from pathlib import Path

    def _boom(self, pattern):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "glob", _boom)
    assert load_workflows(tmp_path) == ()


def test_available_filters_by_required_nodes():
    t = parse_template({**MINIMAL, "requires_nodes": ["PCLazyTextEncode"]})
    assert t.is_available({"KSampler", "CLIPTextEncode"}) is False
    assert t.is_available({"PCLazyTextEncode"}) is True


def test_available_with_no_requirements():
    assert parse_template(MINIMAL).is_available(set()) is True


# --- 값 주입 ---------------------------------------------------------------


def _template(**over):
    data = json.loads(json.dumps(MINIMAL))
    data.update(over)
    return parse_template(data)


def test_build_graph_injects_slots():
    t = _template(slots={"positive": "6.text", "seed": "3.seed"})
    g = build_graph(t, values={"positive": "1girl", "seed": 42}, models={})
    assert g["6"]["inputs"]["text"] == "1girl"
    assert g["3"]["inputs"]["seed"] == 42


def test_build_graph_injects_model_slots():
    t = _template()
    g = build_graph(t, values={}, models={"checkpoint": "wai.safetensors"})
    assert g["4"]["inputs"]["ckpt_name"] == "wai.safetensors"


def test_build_graph_does_not_mutate_template():
    """템플릿은 앱 수명 내내 재사용된다 — 원본을 건드리면 다음 생성이 오염된다."""
    t = _template()
    build_graph(t, values={"positive": "mutated"}, models={})
    assert t.graph["6"]["inputs"]["text"] == ""


def test_build_graph_ignores_unknown_values():
    """템플릿이 선언하지 않은 슬롯은 조용히 무시한다 (템플릿마다 슬롯이 다르다)."""
    t = _template(slots={"positive": "6.text"})
    g = build_graph(t, values={"positive": "a", "cfg": 7.0}, models={})
    assert g["6"]["inputs"]["text"] == "a"


def test_build_graph_skips_none_values():
    t = _template()
    g = build_graph(t, values={"seed": None}, models={})
    assert g["3"]["inputs"]["seed"] == 0


def test_build_graph_skips_empty_model_selection():
    """모델을 아직 안 고른 슬롯은 템플릿 기본값을 남긴다."""
    t = _template()
    g = build_graph(t, values={}, models={"checkpoint": ""})
    assert g["4"]["inputs"]["ckpt_name"] == ""


# --- LoRA ------------------------------------------------------------------


def test_strip_lora_tags_removes_and_tidies():
    text = "<lora:kafka:0.8>, masterpiece, 1girl"
    assert strip_lora_tags(text) == "masterpiece, 1girl"


def test_strip_lora_tags_handles_parenthesised_filenames():
    """실제 파일명에 괄호가 있다 — hans_anima-kei_(blue_archive)_lora."""
    text = "<lora:hans_anima-kei_(blue_archive)_lora:0.8>, 1girl"
    assert strip_lora_tags(text) == "1girl"


def test_strip_lora_tags_noop_without_tags():
    assert strip_lora_tags("masterpiece, 1girl") == "masterpiece, 1girl"


def test_direct_mode_inserts_lora_loader_chain():
    t = _template()
    loras = (LoraAssignment(file="kafka.safetensors", weight=0.8),)
    g = build_graph(t, values={"positive": "<lora:kafka:0.8>, 1girl"}, models={}, loras=loras)
    loaders = [n for n in g.values() if n["class_type"] == "LoraLoader"]
    assert len(loaders) == 1
    assert loaders[0]["inputs"]["lora_name"] == "kafka.safetensors"
    assert loaders[0]["inputs"]["strength_model"] == 0.8
    assert loaders[0]["inputs"]["strength_clip"] == 0.8
    # 프롬프트에서 태그가 빠졌다 — 안 빼면 문자열로 인코딩돼 결과를 오염시킨다
    assert "<lora:" not in g["6"]["inputs"]["text"]


def test_direct_mode_rewires_model_and_clip_consumers():
    """KSampler는 LoraLoader의 model을, CLIPTextEncode는 clip을 받아야 한다."""
    t = _template()
    loras = (LoraAssignment(file="kafka.safetensors", weight=0.8),)
    g = build_graph(t, values={}, models={}, loras=loras)
    loader_id = next(k for k, n in g.items() if n["class_type"] == "LoraLoader")
    assert g["3"]["inputs"]["model"] == [loader_id, 0]
    assert g["6"]["inputs"]["clip"] == [loader_id, 1]


def test_direct_mode_chains_multiple_loras():
    t = _template()
    loras = (
        LoraAssignment(file="a.safetensors", weight=0.8),
        LoraAssignment(file="b.safetensors", weight=0.5),
    )
    g = build_graph(t, values={}, models={}, loras=loras)
    loaders = [n for n in g.values() if n["class_type"] == "LoraLoader"]
    assert len(loaders) == 2


def test_delegate_mode_leaves_prompt_and_graph_alone():
    """PCLazyLoraLoader가 <lora:...>를 읽는다 — 우리가 또 결선하면 두 번 걸린다."""
    t = _template(lora_mode="delegate")
    loras = (LoraAssignment(file="kafka.safetensors", weight=0.8),)
    g = build_graph(t, values={"positive": "<lora:kafka:0.8>, 1girl"}, models={}, loras=loras)
    assert not [n for n in g.values() if n["class_type"] == "LoraLoader"]
    assert "<lora:kafka:0.8>" in g["6"]["inputs"]["text"]


def test_no_loras_leaves_graph_unchanged_shape():
    t = _template()
    g = build_graph(t, values={}, models={}, loras=())
    assert not [n for n in g.values() if n["class_type"] == "LoraLoader"]
    assert g["3"]["inputs"]["model"] == ["4", 0]
