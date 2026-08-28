"""PromptCompilerDialog 테스트 — Qt offscreen (core 로직만, 위젯은 smoke)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from naiauto.core.i18n.manager import default_languages_path
from naiauto.ui.prompt_compiler_dialog import CompilerApplyPayload, PromptCompilerDialog

#: Task 11이 4개 언어 파일에 추가해야 하는 compiler 섹션 키.
NEW_COMPILER_KEYS = (
    "err_connection",
    "err_timeout",
    "err_auth",
    "err_parse",
    "err_empty",
    "result_relationship_row",
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def test_apply_payload_is_frozen_data(qapp):
    payload = CompilerApplyPayload(mode="apply", prompt="2girls, cafe", negative_prompt="", characters=())
    assert payload.mode == "apply"
    assert payload.prompt == "2girls, cafe"
    assert payload.characters == ()
    with pytest.raises(AttributeError):  # frozen dataclass — 불변
        payload.prompt = "mutated"


def test_dialog_controls_exist(qapp):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.settings.schema import AppSettings

    dialog = PromptCompilerDialog(I18nManager(), AppSettings())
    assert dialog.convert_button is not None
    assert dialog.apply_button is not None
    assert not dialog.apply_button.isEnabled()  # 변환 전 비활성
    dialog.close()


def test_compiler_error_keys_in_all_languages(qapp):
    """6개 신규 compiler 키가 4개 언어 파일 모두에 존재해야 한다."""
    for path in sorted(default_languages_path().glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        compiler_keys = set(data["translations"]["compiler"])
        missing = set(NEW_COMPILER_KEYS) - compiler_keys
        assert not missing, f"{path.name}: missing compiler keys {sorted(missing)}"
