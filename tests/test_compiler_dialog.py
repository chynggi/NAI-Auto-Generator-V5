"""PromptCompilerDialog 테스트 — Qt offscreen (core 로직만, 위젯은 smoke)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from naiauto.core.i18n.manager import default_languages_path
from naiauto.ui.prompt_compiler_dialog import CompilerApplyPayload, PromptCompilerDialog

#: 4개 언어 파일에 존재해야 하는 compiler 섹션 키.
NEW_COMPILER_KEYS = (
    "err_connection",
    "err_timeout",
    "err_auth",
    "err_parse",
    "err_empty",
    "result_relationship_row",
    "recent_inputs",
    "recent_placeholder",
    # 출력 타깃 (로컬 SDXL)
    "target",
    "target_novelai",
    "tab_prompt",
    "tab_couple_mask",
    "tab_regional_json",
    "copy",
    "copied",
    "local_hint",
    "couple_mask_hint",
    "lora",
    "lora_none",
    "lora_weight",
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


# --- 출력 타깃 -------------------------------------------------------------
# 위 히스토리 테스트가 쓰는 _dialog(qapp, tmp_path)와 시그니처가 달라 이름을
# 따로 둔다 — 같은 이름으로 덮으면 앞선 테스트들이 깨진다.


def _target_dialog(tmp_path):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.prompt.history import PromptInputHistory
    from naiauto.core.settings.schema import AppSettings

    return PromptCompilerDialog(
        I18nManager(),
        AppSettings(),
        history=PromptInputHistory(path=tmp_path / "history.json"),
    )


def _local_compiled(target="illustrious"):
    from naiauto.core.prompt.schema import (
        CharacterPrompt,
        CompiledPrompt,
        ScenePrompt,
        TagRef,
    )

    return CompiledPrompt(
        base_prompt="masterpiece, 2girls, rain",
        negative_prompt="lowres",
        scene=ScenePrompt(tags=(TagRef("rain"),), subjects=("girl", "girl")),
        characters=(
            CharacterPrompt(id="c1", tags=(TagRef("silver_hair"),), center_x=0.3, center_y=0.5),
            CharacterPrompt(id="c2", tags=(TagRef("black_hair"),), center_x=0.7, center_y=0.5),
        ),
        relationships=(),
        mode="hybrid",
        warnings=(),
        unresolved=(),
        target=target,
    )


def test_target_combo_lists_novelai_and_builtin_presets(qapp, tmp_path):
    dialog = _target_dialog(tmp_path)
    values = [dialog.target_combo.itemData(i) for i in range(dialog.target_combo.count())]
    assert values[0] == "novelai"
    assert "illustrious" in values
    dialog.close()


def test_target_combo_defaults_from_settings(qapp, tmp_path):
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.prompt.history import PromptInputHistory
    from naiauto.core.settings.schema import AppSettings

    settings = AppSettings()
    settings.compiler.default_target = "illustrious"
    dialog = PromptCompilerDialog(
        I18nManager(),
        settings,
        history=PromptInputHistory(path=tmp_path / "h.json"),
    )
    assert dialog.target_combo.currentData() == "illustrious"
    dialog.close()


def test_novelai_target_hides_local_tabs(qapp, tmp_path):
    dialog = _target_dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("novelai"))
    assert dialog._result_tabs.count() == 1
    dialog.close()


def test_local_target_shows_three_result_tabs(qapp, tmp_path):
    dialog = _target_dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("illustrious"))
    assert dialog._result_tabs.count() == 3
    dialog.close()


def test_local_target_renders_couple_mask_and_json(qapp, tmp_path):
    dialog = _target_dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("illustrious"))
    dialog._compiled = _local_compiled()
    dialog._render_preview(dialog._compiled)
    assert "COUPLE MASK(0 0.5, 0 1)" in dialog._couple_edit.toPlainText()
    data = json.loads(dialog._json_edit.toPlainText())
    assert [r["id"] for r in data["regions"]] == ["c1", "c2"]
    dialog.close()


def test_novelai_target_leaves_local_editors_empty(qapp, tmp_path):
    dialog = _target_dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("novelai"))
    dialog._compiled = _local_compiled(target="novelai")
    dialog._render_preview(dialog._compiled)
    assert dialog._couple_edit.toPlainText() == ""
    assert dialog._json_edit.toPlainText() == ""
    dialog.close()


def test_switching_back_to_novelai_clears_stale_local_output(qapp, tmp_path):
    """로컬 결과를 본 뒤 NovelAI로 돌아가면 낡은 COUPLE 문자열이 남으면 안 된다."""
    dialog = _target_dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("illustrious"))
    dialog._compiled = _local_compiled()
    dialog._render_preview(dialog._compiled)
    assert dialog._couple_edit.toPlainText() != ""
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("novelai"))
    assert dialog._couple_edit.toPlainText() == ""
    assert dialog._json_edit.toPlainText() == ""
    dialog.close()


def test_local_target_apply_sends_no_characters(qapp, tmp_path):
    received = []
    dialog = _target_dialog(tmp_path)
    dialog.applied.connect(received.append)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("illustrious"))
    dialog._compiled = _local_compiled()
    dialog._render_preview(dialog._compiled)
    dialog._on_apply("apply")
    assert received[0].characters == ()
    assert received[0].prompt == "masterpiece, 2girls, rain"


def test_novelai_target_apply_still_sends_characters(qapp, tmp_path):
    received = []
    dialog = _target_dialog(tmp_path)
    dialog.applied.connect(received.append)
    dialog._compiled = _local_compiled(target="novelai")
    dialog._render_preview(dialog._compiled)
    dialog._on_apply("apply")
    assert len(received[0].characters) == 2
    dialog.close()


# --- 캐릭터별 LoRA ---------------------------------------------------------


def _lora_dialog(tmp_path):
    """loras.json이 있는 프리셋 폴더를 가리키는 다이얼로그."""
    import json as _json

    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.prompt.history import PromptInputHistory
    from naiauto.core.settings.schema import AppSettings

    presets_dir = tmp_path / "presets"
    presets_dir.mkdir()
    (presets_dir / "loras.json").write_text(
        _json.dumps(
            {"kafka": {"file": "kafka.safetensors", "weight": 0.8, "triggers": ["kafka"]}}
        ),
        encoding="utf-8",
    )
    settings = AppSettings()
    settings.compiler.target_presets_dir = str(presets_dir)
    settings.compiler.default_target = "illustrious"
    return PromptCompilerDialog(
        I18nManager(), settings, history=PromptInputHistory(path=tmp_path / "h.json")
    )


def test_lora_group_hidden_without_registry(qapp, tmp_path):
    dialog = _target_dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("illustrious"))
    dialog._render_preview(_local_compiled())
    assert not dialog._lora_group.isVisibleTo(dialog)
    dialog.close()


def test_lora_rows_appear_per_character(qapp, tmp_path):
    dialog = _lora_dialog(tmp_path)
    dialog._render_preview(_local_compiled())
    assert set(dialog._lora_combos) == {"c1", "c2"}
    assert dialog._lora_combos["c1"].itemData(0) is None  # "없음"
    assert dialog._lora_combos["c1"].itemData(1) == "kafka"
    dialog.close()


def test_lora_group_hidden_on_novelai_target(qapp, tmp_path):
    dialog = _lora_dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("novelai"))
    dialog._render_preview(_local_compiled(target="novelai"))
    assert not dialog._lora_group.isVisibleTo(dialog)
    dialog.close()


def test_lora_selection_survives_recompile(qapp, tmp_path):
    dialog = _lora_dialog(tmp_path)
    dialog._render_preview(_local_compiled())
    dialog._lora_combos["c1"].setCurrentIndex(1)
    dialog._lora_weights["c1"].setValue(0.5)
    dialog._render_preview(_local_compiled())  # 다시 변환한 셈
    assert dialog._lora_combos["c1"].currentData() == "kafka"
    assert dialog._lora_weights["c1"].value() == 0.5
    dialog.close()


def test_character_loras_snapshot_reflects_selection(qapp, tmp_path):
    dialog = _lora_dialog(tmp_path)
    dialog._render_preview(_local_compiled())
    dialog._lora_combos["c2"].setCurrentIndex(1)
    dialog._lora_weights["c2"].setValue(0.6)
    loras = dialog._character_loras()
    assert set(loras) == {"c2"}
    assert loras["c2"].file == "kafka.safetensors"
    assert loras["c2"].weight == 0.6
    dialog.close()


def test_selecting_lora_fills_registry_default_weight(qapp, tmp_path):
    """LoRA를 고르면 가중치가 레지스트리 기본값(0.8)으로 맞춰진다."""
    dialog = _lora_dialog(tmp_path)
    dialog._render_preview(_local_compiled())
    dialog._lora_combos["c1"].setCurrentIndex(1)
    assert dialog._lora_weights["c1"].value() == 0.8
    dialog.close()


def test_lora_appears_in_couple_mask_output(qapp, tmp_path):
    dialog = _lora_dialog(tmp_path)
    dialog._render_preview(_local_compiled())
    dialog._lora_combos["c1"].setCurrentIndex(1)
    dialog._render_preview(_local_compiled())
    assert "<lora:kafka:0.8>" in dialog._couple_edit.toPlainText()
    dialog.close()


def test_lora_rows_cleared_when_result_has_no_characters(qapp, tmp_path):
    """캐릭터가 없는 배경 프롬프트에서는 행이 남지 않아야 한다."""
    from naiauto.core.prompt.schema import CompiledPrompt, ScenePrompt, TagRef

    dialog = _lora_dialog(tmp_path)
    dialog._render_preview(_local_compiled())
    assert dialog._lora_combos
    background = CompiledPrompt(
        base_prompt="alley, night",
        negative_prompt="",
        scene=ScenePrompt(tags=(TagRef("alley"),)),
        characters=(),
        relationships=(),
        mode="hybrid",
        warnings=(),
        unresolved=(),
        target="illustrious",
    )
    dialog._render_preview(background)
    assert dialog._lora_combos == {}
    dialog.close()


def test_history_restore_sets_target(qapp, tmp_path):
    from naiauto.core.prompt.history import InputHistoryEntry

    dialog = _target_dialog(tmp_path)
    dialog._history.add(
        InputHistoryEntry(tab="create", text="은발 소녀", mode="tag", target="illustrious")
    )
    dialog._refresh_history_combo()
    dialog._history_combo.setCurrentIndex(1)
    assert dialog.target_combo.currentData() == "illustrious"
    assert dialog.mode_combo.currentData() == "tag"
    dialog.close()


def test_history_restore_unknown_target_leaves_combo_alone(qapp, tmp_path):
    """레지스트리에서 사라진 타깃이면 현재 선택을 건드리지 않는다."""
    from naiauto.core.prompt.history import InputHistoryEntry

    dialog = _target_dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("novelai"))
    dialog._history.add(
        InputHistoryEntry(tab="create", text="x", mode="hybrid", target="deleted-preset")
    )
    dialog._refresh_history_combo()
    dialog._history_combo.setCurrentIndex(1)
    assert dialog.target_combo.currentData() == "novelai"
    dialog.close()


# --- LoRA 선택과 결과 탭의 동기화 -------------------------------------------


def test_selecting_lora_updates_prompt_tab_not_just_couple_tab(qapp, tmp_path):
    """적용 버튼은 프롬프트 탭을 읽는다 — LoRA가 거기에도 반영돼야 한다."""
    dialog = _lora_dialog(tmp_path)
    dialog._compiled = _local_compiled()
    dialog._render_preview(dialog._compiled)
    assert "<lora:" not in dialog._final_edit.toPlainText()

    dialog._lora_combos["c1"].setCurrentIndex(1)

    assert "<lora:kafka:0.8>" in dialog._final_edit.toPlainText()
    assert "<lora:kafka:0.8>" in dialog._couple_edit.toPlainText()
    dialog.close()


def test_changing_lora_weight_updates_prompt_tab(qapp, tmp_path):
    """가중치 스핀박스도 결과를 바꾼다 — 콤보만 연결하면 반쪽짜리다."""
    dialog = _lora_dialog(tmp_path)
    dialog._compiled = _local_compiled()
    dialog._render_preview(dialog._compiled)
    dialog._lora_combos["c1"].setCurrentIndex(1)
    assert "<lora:kafka:0.8>" in dialog._final_edit.toPlainText()

    dialog._lora_weights["c1"].setValue(0.5)

    assert "<lora:kafka:0.5>" in dialog._final_edit.toPlainText()
    assert "<lora:kafka:0.5>" in dialog._couple_edit.toPlainText()
    dialog.close()


def test_lora_change_keeps_apply_payload_in_sync(qapp, tmp_path):
    """적용 시 나가는 프롬프트에 LoRA가 실제로 담긴다."""
    received = []
    dialog = _lora_dialog(tmp_path)
    dialog.applied.connect(received.append)
    dialog._compiled = _local_compiled()
    dialog._render_preview(dialog._compiled)
    dialog._lora_combos["c1"].setCurrentIndex(1)
    dialog._on_apply("apply")
    assert "<lora:kafka:0.8>" in received[0].prompt
    assert received[0].characters == ()


def test_lora_reemit_is_noop_on_novelai_target(qapp, tmp_path):
    """NovelAI 결과는 emitter로 다시 뽑으면 안 된다 — 원본 그대로 남아야 한다."""
    dialog = _lora_dialog(tmp_path)
    dialog.target_combo.setCurrentIndex(dialog.target_combo.findData("novelai"))
    dialog._compiled = _local_compiled(target="novelai")
    dialog._render_preview(dialog._compiled)
    before = dialog._final_edit.toPlainText()
    dialog._reemit_local()
    assert dialog._final_edit.toPlainText() == before
    dialog.close()
