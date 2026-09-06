"""Prompt AI / Compiler 설정 (AppSettings.prompt_ai, AppSettings.compiler) 테스트."""

from naiauto.core.settings.schema import AppSettings


def test_settings_defaults():
    s = AppSettings()
    assert s.prompt_ai.provider == "openai_compatible"
    assert s.prompt_ai.base_url == "http://127.0.0.1:7112/v1"
    assert s.compiler.default_mode == "hybrid"
    assert s.compiler.preserve_natural_language is True
    assert s.compiler.relationship_style == "natural"


def test_settings_roundtrip(tmp_path):
    from naiauto.core.settings.store import load_settings, save_settings

    s = AppSettings()
    s.prompt_ai.model = "qwen2.5-7b"
    s.compiler.relationship_style = "tag"
    path = tmp_path / "settings.json"
    save_settings(s, path)
    loaded = load_settings(path)
    assert loaded.prompt_ai.model == "qwen2.5-7b"
    assert loaded.compiler.relationship_style == "tag"
    assert loaded.compiler.default_mode == "hybrid"


def test_old_settings_migrate_with_defaults(tmp_path):
    import json

    from naiauto.core.settings.store import load_settings

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"language": "en", "schema_version": 2}), encoding="utf-8")
    loaded = load_settings(path)
    assert loaded.language == "en"
    assert loaded.prompt_ai.provider == "openai_compatible"
    assert loaded.compiler.default_mode == "hybrid"


def test_compiler_target_defaults():
    from naiauto.core.settings.schema import AppSettings

    settings = AppSettings()
    assert settings.compiler.default_target == "novelai"
    assert settings.compiler.target_presets_dir == ""


def test_compiler_target_round_trips(tmp_path):
    import json

    from naiauto.core.settings.schema import AppSettings

    settings = AppSettings()
    settings.compiler.default_target = "illustrious"
    settings.compiler.target_presets_dir = str(tmp_path)
    restored = AppSettings.model_validate(json.loads(settings.model_dump_json()))
    assert restored.compiler.default_target == "illustrious"
    assert restored.compiler.target_presets_dir == str(tmp_path)


def test_old_settings_without_target_still_load():
    """기존 설정 파일(타깃 필드 없음)이 그대로 열려야 한다 — 마이그레이션 불필요."""
    from naiauto.core.settings.schema import AppSettings

    settings = AppSettings.model_validate({"compiler": {"default_mode": "tag"}})
    assert settings.compiler.default_mode == "tag"
    assert settings.compiler.default_target == "novelai"
