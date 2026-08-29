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
    "recent_inputs",
    "recent_placeholder",
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


# ── 워커 스레드 로직 (검증: 성공/오류/취소 흐름) ───────────────────────
# _worker_convert를 GUI 스레드에서 직접 호출하면 시그널이 direct connection으로
# 동기 전달되므로 스레드 없이도 핸들러(_on_converted 등)가 즉시 실행된다.

_GOLDEN_JSON = """{
  "scene": {
    "tags": ["cafe", "night"],
    "subjects": ["girl", "girl"],
    "description": "",
    "natural_language": ""
  },
  "characters": [
    {"id": "c1", "description": "", "tags": ["long_hair", "black_dress"], "position_hint": "left"}
  ],
  "relationships": [],
  "camera": "", "composition": "", "style": "",
  "negative": [], "unresolved": []
}"""


def _compiler(response=_GOLDEN_JSON, error=None):
    from naiauto.core.prompt.compiler import PromptCompiler
    from naiauto.core.prompt.formatter import PromptFormatter
    from naiauto.core.prompt.llm import FakeLLMProvider
    from naiauto.core.prompt.resolver import TagResolver

    resolver = TagResolver()
    assert resolver.load()
    return PromptCompiler(
        provider=FakeLLMProvider(response=response, error=error),
        resolver=resolver,
        formatter=PromptFormatter(preserve_natural_language=True, relationship_style="natural"),
    )


def _dialog(qapp, tmp_path):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.prompt.history import PromptInputHistory
    from naiauto.core.settings.schema import AppSettings
    from naiauto.ui.prompt_compiler_dialog import PromptCompilerDialog

    dialog = PromptCompilerDialog(
        I18nManager(),
        AppSettings(),
        history=PromptInputHistory(path=tmp_path / "history.json"),
    )
    dialog._compiler = _compiler()  # LLM 네트워크 없이 결정적 응답으로 교체
    return dialog


def _convert_inputs(text="두 소녀가 카페에 있다", mode="hybrid"):
    from naiauto.ui.prompt_compiler_dialog import _ConvertInputs

    return _ConvertInputs(modify=False, existing="", instruction="", text=text, mode=mode)


def test_worker_convert_success_updates_preview_and_enables_apply(qapp, tmp_path):
    dialog = _dialog(qapp, tmp_path)
    dialog._worker_convert(_convert_inputs())
    assert dialog._compiled is not None
    preview = dialog._preview_browser.toPlainText()
    assert "cafe" in preview and "long_hair" in preview
    assert dialog._final_edit.toPlainText() != ""
    assert dialog.apply_button.isEnabled()
    assert dialog.insert_button.isEnabled()
    assert dialog.replace_button.isEnabled()
    assert dialog.convert_button.isEnabled()  # idle 복구
    assert not dialog.cancel_button.isEnabled()
    dialog.close()


def test_worker_convert_error_recovers_idle(qapp, monkeypatch, tmp_path):
    from naiauto.core.prompt.errors import CompilerConnectionError
    from naiauto.ui.prompt_compiler_dialog import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: shown.append(args))
    dialog = _dialog(qapp, tmp_path)
    dialog._compiler = _compiler(error=CompilerConnectionError("offline"))
    dialog._worker_convert(_convert_inputs())
    assert shown  # 오류 경고 호출 (모달 차단 없이)
    assert dialog._compiled is None
    assert not dialog.apply_button.isEnabled()
    assert dialog.convert_button.isEnabled()  # idle 복구
    assert not dialog.cancel_button.isEnabled()
    assert dialog._status_label.text() != ""  # 오류 메시지 표시
    assert dialog._compiler_worker is None
    dialog.close()


def test_worker_convert_cancel_discards_result(qapp, tmp_path):
    dialog = _dialog(qapp, tmp_path)
    dialog._cancel_requested = True
    dialog._worker_convert(_convert_inputs())
    assert dialog._compiled is None  # 결과 폐기
    assert not dialog.apply_button.isEnabled()
    assert dialog.convert_button.isEnabled()  # idle 복구
    assert not dialog.cancel_button.isEnabled()
    assert dialog._status_label.text() == ""
    assert dialog._compiler_worker is None
    dialog.close()


# ── 최근 입력 히스토리 ──────────────────────────────────────────────────

def test_worker_convert_success_records_input_history(qapp, tmp_path):
    from naiauto.core.prompt.history import PromptInputHistory

    dialog = _dialog(qapp, tmp_path)
    hist = PromptInputHistory(path=tmp_path / "history.json")
    hist.load()
    assert hist.recent() == []  # 시작은 빈 상태

    dialog._last_run = _convert_inputs(text="신비한 소녀가 나타난다")
    dialog._worker_convert(_convert_inputs(text="신비한 소녀가 나타난다"))
    hist.load()
    assert [e.text for e in hist.recent()] == ["신비한 소녀가 나타난다"]
    assert hist.recent()[0].tab == "create"
    assert hist.recent()[0].mode == "hybrid"
    dialog.close()


def test_worker_convert_failure_does_not_record_history(qapp, monkeypatch, tmp_path):
    from naiauto.core.prompt.errors import CompilerConnectionError
    from naiauto.core.prompt.history import PromptInputHistory
    from naiauto.ui.prompt_compiler_dialog import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    dialog = _dialog(qapp, tmp_path)
    dialog._compiler = _compiler(error=CompilerConnectionError("offline"))
    dialog._last_run = _convert_inputs(text="실패할 입력")
    dialog._worker_convert(_convert_inputs(text="실패할 입력"))
    hist = PromptInputHistory(path=tmp_path / "history.json")
    hist.load()
    assert hist.recent() == []  # 실패한 변환은 기록하지 않는다
    dialog.close()


def test_history_combo_select_restores_create_fields(qapp, tmp_path):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.prompt.history import InputHistoryEntry, PromptInputHistory
    from naiauto.core.settings.schema import AppSettings

    hist = PromptInputHistory(path=tmp_path / "history.json")
    hist.add(InputHistoryEntry(tab="create", text="은발의 소녀", mode="tag"))
    dialog = PromptCompilerDialog(
        I18nManager(),
        AppSettings(),
        history=hist,
    )
    dialog._refresh_history_combo()
    # 생성 탭 입력으로 복원
    dialog._on_history_selected(1)
    assert dialog._tabs.currentWidget() is dialog._input_tab
    assert dialog._input_edit.toPlainText() == "은발의 소녀"
    assert dialog._mode() == "tag"
    dialog.close()


def test_history_combo_select_restores_modify_fields(qapp, tmp_path):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.prompt.history import InputHistoryEntry, PromptInputHistory
    from naiauto.core.settings.schema import AppSettings

    hist = PromptInputHistory(path=tmp_path / "history.json")
    hist.add(InputHistoryEntry(tab="modify", existing_prompt="1girl, cafe", instruction="배경을 밤으로", mode="hybrid"))
    dialog = PromptCompilerDialog(I18nManager(), AppSettings(), history=hist)
    dialog._refresh_history_combo()
    dialog._on_history_selected(1)
    assert dialog._tabs.currentWidget() is dialog._modify_tab
    assert dialog._existing_edit.toPlainText() == "1girl, cafe"
    assert dialog._instruction_edit.toPlainText() == "배경을 밤으로"
    dialog.close()
