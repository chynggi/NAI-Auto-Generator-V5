"""워크플로 템플릿 로딩·검증 테스트 — 서버 없이 돈다."""

import json

import pytest

from naiauto.core.backends.comfy_workflow import (
    builtin_workflows_dir,
    load_workflows,
    parse_template,
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
        "3": {"inputs": {"seed": 0}, "class_type": "KSampler"},
        "4": {"inputs": {"ckpt_name": ""}, "class_type": "CheckpointLoaderSimple"},
        "6": {"inputs": {"text": ""}, "class_type": "CLIPTextEncode"},
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
