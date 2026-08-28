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
