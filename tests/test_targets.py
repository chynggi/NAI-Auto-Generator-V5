"""타깃 프리셋 + LoRA 레지스트리 로딩 테스트."""

import json

import pytest

from naiauto.core.prompt.errors import TargetPresetError
from naiauto.core.prompt.targets import (
    LORA_REGISTRY_FILENAME,
    NOVELAI_PRESET,
    NOVELAI_TARGET_ID,
    LoraEntry,
    TargetPreset,
    builtin_targets_dir,
    find_target,
    load_lora_registry,
    load_target_presets,
    parse_preset,
)


def test_novelai_preset_is_first_and_marked_novelai():
    presets = load_target_presets(None)
    assert presets[0] is NOVELAI_PRESET
    assert NOVELAI_PRESET.id == NOVELAI_TARGET_ID
    assert NOVELAI_PRESET.kind == "novelai"


def test_builtin_presets_are_loaded():
    ids = {p.id for p in load_target_presets(None)}
    assert {"illustrious", "animagine", "sdxl_base"} <= ids


def test_builtin_dir_exists():
    assert builtin_targets_dir().is_dir()


def test_parse_preset_reads_all_fields():
    preset = parse_preset(
        {
            "id": "demo",
            "name": "Demo",
            "quality_prefix": ["masterpiece"],
            "quality_suffix": ["hires"],
            "default_negative": ["lowres"],
            "weight_syntax": "a1111",
            "flatten": "couple_mask",
            "position_tags": False,
            "natural_language": "append",
            "underscore_to_space": False,
            "mask_size": [832, 1216],
        }
    )
    assert preset == TargetPreset(
        id="demo",
        name="Demo",
        kind="local",
        quality_prefix=("masterpiece",),
        quality_suffix=("hires",),
        default_negative=("lowres",),
        weight_syntax="a1111",
        flatten="couple_mask",
        position_tags=False,
        natural_language="append",
        underscore_to_space=False,
        mask_size=(832, 1216),
    )


def test_parse_preset_applies_defaults():
    preset = parse_preset({"id": "bare", "name": "Bare"})
    assert preset.kind == "local"
    assert preset.quality_prefix == ()
    assert preset.flatten == "sequential"
    assert preset.position_tags is True
    assert preset.natural_language == "drop"
    assert preset.underscore_to_space is True
    assert preset.mask_size is None


@pytest.mark.parametrize(
    "data",
    [
        {"name": "no id"},
        {"id": "", "name": "empty id"},
        {"id": "bad_flatten", "name": "x", "flatten": "nope"},
        {"id": "bad_nl", "name": "x", "natural_language": "nope"},
        {"id": "bad_mask", "name": "x", "mask_size": [1, 2, 3]},
        {"id": "bad_list", "name": "x", "quality_prefix": "not a list"},
        {"id": "bad_weight", "name": "x", "weight_syntax": "nope"},
        {"id": "bad_bool_mask", "name": "x", "mask_size": [True, 1216]},
        {"id": "bad_item", "name": "x", "quality_prefix": ["ok", 5]},
    ],
)
def test_parse_preset_rejects_invalid(data):
    with pytest.raises(TargetPresetError):
        parse_preset(data)


def test_user_preset_overrides_builtin_by_id(tmp_path):
    (tmp_path / "illustrious.json").write_text(
        json.dumps({"id": "illustrious", "name": "My Illustrious", "quality_prefix": ["mine"]}),
        encoding="utf-8",
    )
    presets = {p.id: p for p in load_target_presets(tmp_path)}
    assert presets["illustrious"].name == "My Illustrious"
    assert presets["illustrious"].quality_prefix == ("mine",)


def test_broken_user_preset_is_skipped_not_fatal(tmp_path):
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    (tmp_path / "good.json").write_text(
        json.dumps({"id": "good", "name": "Good"}), encoding="utf-8"
    )
    ids = {p.id for p in load_target_presets(tmp_path)}
    assert "good" in ids
    assert "broken" not in ids


def test_user_preset_claiming_novelai_id_is_ignored(tmp_path):
    (tmp_path / "novelai.json").write_text(
        json.dumps({"id": "novelai", "name": "Hijacked"}), encoding="utf-8"
    )
    presets = {p.id: p for p in load_target_presets(tmp_path)}
    assert presets["novelai"] is NOVELAI_PRESET


def test_missing_user_dir_falls_back_to_builtin(tmp_path):
    ids = {p.id for p in load_target_presets(tmp_path / "does-not-exist")}
    assert "illustrious" in ids


def test_find_target_falls_back_to_novelai():
    presets = load_target_presets(None)
    assert find_target(presets, "illustrious").id == "illustrious"
    assert find_target(presets, "no-such-target") is NOVELAI_PRESET
    assert find_target(presets, "") is NOVELAI_PRESET


def test_unreadable_preset_dir_is_skipped_not_fatal(tmp_path, monkeypatch):
    """읽을 수 없는 폴더가 앱 기동을 막지 않는다."""
    from pathlib import Path

    def _boom(self, pattern):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "glob", _boom)
    presets = load_target_presets(tmp_path)
    assert presets[0] is NOVELAI_PRESET  # 내장 로드도 같은 이유로 비지만, 앱은 뜬다


def test_find_target_warns_on_unknown_id(caplog):
    presets = load_target_presets(None)
    with caplog.at_level("WARNING"):
        find_target(presets, "no-such-target")
    assert "no-such-target" in caplog.text


def test_find_target_quiet_on_normal_lookups(caplog):
    presets = load_target_presets(None)
    with caplog.at_level("WARNING"):
        find_target(presets, "")
        find_target(presets, "novelai")
    assert caplog.text == ""


def test_empty_user_dir_falls_back_to_builtin(tmp_path):
    ids = {p.id for p in load_target_presets(tmp_path)}
    assert "illustrious" in ids


def test_lora_registry_file_is_not_read_as_preset(tmp_path, caplog):
    (tmp_path / LORA_REGISTRY_FILENAME).write_text(
        json.dumps({"kafka": {"file": "k.safetensors"}}), encoding="utf-8"
    )
    with caplog.at_level("WARNING"):
        presets = load_target_presets(tmp_path)
    assert all(p.id != "loras" for p in presets)
    assert "loras.json" not in caplog.text  # 건너뛴 것이지 깨진 것이 아니다


def test_lora_entry_stem_drops_extension():
    assert LoraEntry(id="k", file="kafka_illustrious.safetensors").stem == "kafka_illustrious"


# --- LoRA 레지스트리 -------------------------------------------------------


def test_lora_registry_missing_dir_is_empty():
    assert load_lora_registry(None) == {}


def test_lora_registry_missing_file_is_empty(tmp_path):
    assert load_lora_registry(tmp_path) == {}


def test_lora_registry_reads_entries(tmp_path):
    (tmp_path / LORA_REGISTRY_FILENAME).write_text(
        json.dumps(
            {
                "kafka": {
                    "file": "kafka_illustrious.safetensors",
                    "weight": 0.8,
                    "triggers": ["kafka", "purple hair"],
                }
            }
        ),
        encoding="utf-8",
    )
    registry = load_lora_registry(tmp_path)
    assert registry["kafka"] == LoraEntry(
        id="kafka",
        file="kafka_illustrious.safetensors",
        weight=0.8,
        triggers=("kafka", "purple hair"),
    )
    assert registry["kafka"].stem == "kafka_illustrious"


def test_lora_registry_applies_defaults(tmp_path):
    (tmp_path / LORA_REGISTRY_FILENAME).write_text(
        json.dumps({"bare": {"file": "bare.safetensors"}}), encoding="utf-8"
    )
    entry = load_lora_registry(tmp_path)["bare"]
    assert entry.weight == 1.0
    assert entry.triggers == ()


def test_lora_registry_skips_broken_entries_keeps_good(tmp_path):
    (tmp_path / LORA_REGISTRY_FILENAME).write_text(
        json.dumps(
            {
                "no_file": {"weight": 1.0},
                "bad_weight": {"file": "x.safetensors", "weight": "heavy"},
                "bad_triggers": {"file": "y.safetensors", "triggers": "not a list"},
                "good": {"file": "good.safetensors"},
            }
        ),
        encoding="utf-8",
    )
    registry = load_lora_registry(tmp_path)
    assert set(registry) == {"good"}


def test_lora_registry_broken_json_is_empty(tmp_path):
    (tmp_path / LORA_REGISTRY_FILENAME).write_text("{ not json", encoding="utf-8")
    assert load_lora_registry(tmp_path) == {}


def test_lora_registry_top_level_list_is_empty(tmp_path):
    (tmp_path / LORA_REGISTRY_FILENAME).write_text('["not", "an object"]', encoding="utf-8")
    assert load_lora_registry(tmp_path) == {}


def test_lora_registry_rejects_bool_weight(tmp_path):
    """bool은 int의 하위 타입이라 명시적으로 걸러야 한다 (mask_size와 같은 이유)."""
    (tmp_path / LORA_REGISTRY_FILENAME).write_text(
        json.dumps({"b": {"file": "b.safetensors", "weight": True}}), encoding="utf-8"
    )
    assert load_lora_registry(tmp_path) == {}


def test_lora_registry_unreadable_dir_is_empty(tmp_path, monkeypatch):
    """읽을 수 없는 폴더가 앱 기동을 막지 않는다."""
    from pathlib import Path

    def _boom(self):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "is_file", _boom)
    assert load_lora_registry(tmp_path) == {}
