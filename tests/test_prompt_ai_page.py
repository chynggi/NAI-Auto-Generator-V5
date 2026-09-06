"""PromptAiPage commit의 keyring 저장 실패 처리 테스트 (offscreen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from naiauto.core.i18n.manager import I18nManager
from naiauto.core.settings.schema import AppSettings
from naiauto.ui.options_pages.prompt_ai_page import KEYRING_WARN_KEY, PromptAiPage


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def test_commit_marks_key_available_only_when_save_succeeds(qapp, monkeypatch):
    # [review #3] is_available()만 보지 않고 save_credential의 실제 성공 여부를
    # 반영한다 — 저장 실패 시 api_key_available=True로 오표시되지 않는다.
    from naiauto.ui.options_pages import prompt_ai_page

    draft = AppSettings()
    page = PromptAiPage(I18nManager())
    page.load(draft)
    page.api_key_edit.setText("secret")

    monkeypatch.setattr(prompt_ai_page.credentials, "save_credential", lambda *a: False)
    page.commit(draft)
    assert draft.prompt_ai.api_key_available is False
    assert KEYRING_WARN_KEY in page.notices()
    assert page.api_key_edit.text() == ""  # 입력란은 비운다 (재입력 유도)

    # 저장 성공 시에는 available=True + 경고 없음
    monkeypatch.setattr(prompt_ai_page.credentials, "save_credential", lambda *a: True)
    page.api_key_edit.setText("secret")
    page.commit(draft)
    assert draft.prompt_ai.api_key_available is True
    assert KEYRING_WARN_KEY not in page.notices()


def test_commit_no_key_leaves_state_unchanged(qapp, monkeypatch):
    from naiauto.ui.options_pages import prompt_ai_page

    # keyring 상태에 의존하지 않도록 load_credential을 mock (빈 키 = 저장 없음)
    monkeypatch.setattr(prompt_ai_page.credentials, "load_credential", lambda *a: "")

    draft = AppSettings()
    page = PromptAiPage(I18nManager())
    page.load(draft)
    assert draft.prompt_ai.api_key_available is False

    called = []
    monkeypatch.setattr(prompt_ai_page.credentials, "save_credential", lambda *a: called.append(a) or True)
    page.commit(draft)  # 입력 없음 → 저장 시도 자체가 없어야 한다
    assert called == []
    assert draft.prompt_ai.api_key_available is False
    assert page.notices() == ()


# --- 출력 타깃 -------------------------------------------------------------


def test_target_combo_lists_novelai_and_presets(qapp):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.ui.options_pages.prompt_ai_page import PromptAiPage

    page = PromptAiPage(I18nManager())
    values = [page.target_combo.itemData(i) for i in range(page.target_combo.count())]
    assert values[0] == "novelai"
    assert "illustrious" in values


def test_target_round_trips_through_load_and_commit(qapp, tmp_path):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.settings.schema import AppSettings
    from naiauto.ui.options_pages.prompt_ai_page import PromptAiPage

    page = PromptAiPage(I18nManager())
    draft = AppSettings()
    draft.compiler.default_target = "illustrious"
    draft.compiler.target_presets_dir = str(tmp_path)
    page.load(draft)
    assert page.target_combo.currentData() == "illustrious"
    assert page.presets_dir_edit.text() == str(tmp_path)

    out = AppSettings()
    page.commit(out)
    assert out.compiler.default_target == "illustrious"
    assert out.compiler.target_presets_dir == str(tmp_path)


def test_unknown_default_target_falls_back_in_ui(qapp):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.settings.schema import AppSettings
    from naiauto.ui.options_pages.prompt_ai_page import PromptAiPage

    page = PromptAiPage(I18nManager())
    draft = AppSettings()
    draft.compiler.default_target = "no-such-target"
    page.load(draft)
    assert page.target_combo.currentData() == "novelai"


def test_user_preset_dir_extends_target_combo(qapp, tmp_path):
    """폴더를 지정하면 사용자 프리셋이 콤보에 추가된다."""
    import json

    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.settings.schema import AppSettings
    from naiauto.ui.options_pages.prompt_ai_page import PromptAiPage

    (tmp_path / "mine.json").write_text(
        json.dumps({"id": "mine", "name": "My Model"}), encoding="utf-8"
    )
    page = PromptAiPage(I18nManager())
    draft = AppSettings()
    draft.compiler.target_presets_dir = str(tmp_path)
    page.load(draft)
    values = [page.target_combo.itemData(i) for i in range(page.target_combo.count())]
    assert "mine" in values


def test_lora_status_reports_registry_size(qapp, tmp_path):
    import json

    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.settings.schema import AppSettings
    from naiauto.ui.options_pages.prompt_ai_page import PromptAiPage

    (tmp_path / "loras.json").write_text(
        json.dumps({"kafka": {"file": "kafka.safetensors"}}), encoding="utf-8"
    )
    page = PromptAiPage(I18nManager())
    draft = AppSettings()
    draft.compiler.target_presets_dir = str(tmp_path)
    page.load(draft)
    assert "1" in page.lora_status_label.text()


def test_lora_status_when_registry_missing(qapp, tmp_path):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.settings.schema import AppSettings
    from naiauto.ui.options_pages.prompt_ai_page import PromptAiPage

    page = PromptAiPage(I18nManager())
    draft = AppSettings()
    draft.compiler.target_presets_dir = str(tmp_path)
    page.load(draft)
    assert page.lora_status_label.text() != ""
