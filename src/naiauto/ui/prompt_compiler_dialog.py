"""자연어 → 구조화 프롬프트 컴파일 다이얼로그 (WD14Dialog 스타일).

흐름 (스펙 §24, §71): 입력 → 변환(worker 스레드) → 미리보기(구조 + 최종 문자열)
→ 사용자 검토 → Apply/Insert/Replace 신호 방출. 검토 전까지 기존 편집기를
절대 건드리지 않는다 — MainWindow(적용 담당)가 ``CompilerApplyPayload``를 받아
직접 적용한다.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal

import shiboken6
from PySide6.QtCore import Qt, Signal, SignalInstance
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from naiauto.core.prompt.compiler import PromptCompiler, build_compiler
from naiauto.core.prompt.emitters import emit_couple_mask, emit_regional_json
from naiauto.core.prompt.errors import (
    CompilerAuthError,
    CompilerEmptyResultError,
    CompilerError,
    CompilerParseError,
    CompilerServerError,
    CompilerTimeoutError,
)
from naiauto.core.prompt.history import (
    InputHistoryEntry,
    PromptInputHistory,
    default_history_path,
)
from naiauto.core.prompt.merge import to_generation_data
from naiauto.core.prompt.schema import DEFAULT_MODE, MODE_TAGS, CompiledPrompt
from naiauto.core.prompt.targets import NOVELAI_TARGET_ID, find_target

if TYPE_CHECKING:
    from naiauto.core.api.models import CharacterCaption
    from naiauto.core.i18n.manager import I18nManager
    from naiauto.core.settings.schema import AppSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CompilerApplyPayload:
    """다이얼로그 → MainWindow 전달 (적용 의미는 MainWindow가 결정)."""

    mode: Literal["apply", "insert", "replace"]
    prompt: str
    negative_prompt: str
    characters: tuple[CharacterCaption, ...]


@dataclass(frozen=True)
class _ConvertInputs:
    """워커 스레드로 넘기는 입력 스냅샷 — 위젯은 GUI 스레드에서만 읽는다."""

    modify: bool
    existing: str
    instruction: str
    text: str
    mode: str
    target: str = "novelai"
    character_loras: dict = field(default_factory=dict)
    resolution: tuple[int, int] | None = None


def _error_key_for(error: CompilerError) -> str:
    """컴파일러 오류 타입 → i18n 키. 연결/서버/provider 오류는 err_connection로 통합."""
    if isinstance(error, CompilerTimeoutError):
        return "compiler.err_timeout"
    if isinstance(error, CompilerAuthError):
        return "compiler.err_auth"
    if isinstance(error, CompilerParseError):
        return "compiler.err_parse"
    if isinstance(error, CompilerEmptyResultError):
        return "compiler.err_empty"
    return "compiler.err_connection"


class PromptCompilerDialog(QDialog):
    """자연어 → 구조화 프롬프트 컴파일 다이얼로그 (WD14Dialog 스타일).

    LLM 추론은 절대 GUI 스레드에서 하지 않는다 (§29) — ``threading.Thread``
    워커에서 실행하고 결과는 Qt 큐드 연결(queued connection)으로 GUI 스레드에
    돌려받는다. LLM HTTP 호출 자체는 중단할 수 없으므로, 취소는 결과를 폐기하는
    플래그로만 동작한다 ("가능하면 Cancel").
    """

    applied = Signal(object)  # CompilerApplyPayload (메인 스레드에서 emit)

    _converted_ok = Signal(object, object)  # (CompiledPrompt | None, None)
    _converted_failed = Signal(object, object)  # (None, CompilerError)
    _converted_cancelled = Signal()  # 취소됨 — 워커가 끝난 뒤 UI 복구 (스케치의 stuck 방지)

    def __init__(
        self,
        i18n: I18nManager,
        settings: AppSettings,
        *,
        parent: QWidget | None = None,
        history: PromptInputHistory | None = None,
    ) -> None:
        super().__init__(parent)
        self._i18n = i18n
        self._settings = settings
        #: 실행 당시 설정으로 조립 (LLM 호출은 워커에서만).
        self._compiler: PromptCompiler = build_compiler(settings)
        self._compiled: CompiledPrompt | None = None
        self._compiler_worker: threading.Thread | None = None
        self._last_run: _ConvertInputs | None = None
        self._cancel_requested = False
        self._subscribed = True
        #: 최근 입력 히스토리 (주입 없으면 기본 경로 사용). 입력만 저장 — 출력은 캐싱하지 않는다.
        self._history = history if history is not None else PromptInputHistory(path=default_history_path())
        self._history.load()
        self._history_restoring = False
        #: 캐릭터 id → LoRA 선택 콤보 / 가중치 스핀박스 (로컬 타깃에서만 만든다).
        self._lora_combos: dict[str, QComboBox] = {}
        self._lora_weights: dict[str, QDoubleSpinBox] = {}

        self.setMinimumSize(720, 560)
        self._build_ui()
        self.retranslate()
        self._apply_default_mode()
        self._apply_default_target()  # retranslate가 콤보를 채운 뒤여야 findData가 먹는다
        self._set_result_buttons(False)
        self.cancel_button.setEnabled(False)
        self.regenerate_button.setEnabled(False)

        self._converted_ok.connect(self._on_converted)
        self._converted_failed.connect(self._on_converted)
        self._converted_cancelled.connect(self._on_converted_cancelled)
        self._i18n.subscribe(self._on_language_changed)

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 컨트롤 행: 모드 콤보(Tag/Hybrid/Natural) | 변환 | 중지 | 다시 생성
        control_row = QHBoxLayout()
        self._mode_label = QLabel()
        control_row.addWidget(self._mode_label)
        self.mode_combo = QComboBox()
        control_row.addWidget(self.mode_combo)
        # 출력 타깃: NovelAI(기존 경로) 또는 로컬 SDXL 프리셋.
        self._target_label = QLabel()
        control_row.addWidget(self._target_label)
        self.target_combo = QComboBox()
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        control_row.addWidget(self.target_combo)
        control_row.addStretch(1)
        self.convert_button = QPushButton()
        self.convert_button.clicked.connect(self._on_convert)
        self.cancel_button = QPushButton()
        self.cancel_button.clicked.connect(self._on_cancel)
        self.regenerate_button = QPushButton()
        self.regenerate_button.clicked.connect(self._on_regenerate)
        control_row.addWidget(self.convert_button)
        control_row.addWidget(self.cancel_button)
        control_row.addWidget(self.regenerate_button)
        layout.addLayout(control_row)

        # 최근 입력 히스토리 행 — 선택 시 해당 탭/필드로 복원 (자동 변환은 하지 않음)
        history_row = QHBoxLayout()
        self._history_label = QLabel()
        history_row.addWidget(self._history_label)
        self._history_combo = QComboBox()
        self._history_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self._history_combo.currentIndexChanged.connect(self._on_history_selected)
        history_row.addWidget(self._history_combo, stretch=1)
        layout.addLayout(history_row)

        # 입력 탭
        self._tabs = QTabWidget()
        self._input_tab = QWidget()
        input_layout = QVBoxLayout(self._input_tab)
        self._input_edit = QPlainTextEdit()
        input_layout.addWidget(self._input_edit)
        self._tabs.addTab(self._input_tab, "")

        self._modify_tab = QWidget()
        modify_layout = QVBoxLayout(self._modify_tab)
        self._existing_edit = QPlainTextEdit()
        self._existing_edit.setReadOnly(True)
        modify_layout.addWidget(self._existing_edit, stretch=2)
        self._modify_hint_label = QLabel()
        modify_layout.addWidget(self._modify_hint_label)
        self._instruction_edit = QPlainTextEdit()
        modify_layout.addWidget(self._instruction_edit, stretch=3)
        self._tabs.addTab(self._modify_tab, "")
        layout.addWidget(self._tabs, stretch=1)

        # 결과: 구조 미리보기 | 최종 프롬프트 (사용자가 Apply 전 수정 가능)
        self._result_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._preview_browser = QTextBrowser()
        self._result_splitter.addWidget(self._preview_browser)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self._final_label = QLabel()
        right_layout.addWidget(self._final_label)
        # 결과 탭: 프롬프트(기존 편집기) | COUPLE MASK | 영역 JSON.
        # 첫 탭이 기존 _final_edit을 그대로 담으므로 Apply 경로는 바뀌지 않는다.
        self._result_tabs = QTabWidget()
        self._final_edit = QPlainTextEdit()
        self._result_tabs.addTab(self._final_edit, "")

        # 로컬 전용 페이지는 탭에서 빠져도 파괴되지 않게 다이얼로그를 부모로 둔다
        # (removeTab은 페이지를 소유권만 놓아 줄 뿐 삭제하지 않지만, 부모가 없으면
        # 파이썬 참조만 남은 top-level 위젯이 되어 잠깐 창으로 뜰 수 있다).
        self._couple_page = QWidget(self)
        couple_layout = QVBoxLayout(self._couple_page)
        self._couple_hint_label = QLabel()
        self._couple_hint_label.setWordWrap(True)
        couple_layout.addWidget(self._couple_hint_label)
        self._couple_edit = QPlainTextEdit()
        self._couple_edit.setReadOnly(True)
        couple_layout.addWidget(self._couple_edit)
        self._couple_copy_button = QPushButton()
        self._couple_copy_button.clicked.connect(
            lambda: self._copy_to_clipboard(self._couple_edit.toPlainText())
        )
        couple_layout.addWidget(self._couple_copy_button)

        self._json_page = QWidget(self)
        json_layout = QVBoxLayout(self._json_page)
        self._json_edit = QPlainTextEdit()
        self._json_edit.setReadOnly(True)
        json_layout.addWidget(self._json_edit)
        self._json_copy_button = QPushButton()
        self._json_copy_button.clicked.connect(
            lambda: self._copy_to_clipboard(self._json_edit.toPlainText())
        )
        json_layout.addWidget(self._json_copy_button)

        self._local_hint_label = QLabel()
        self._local_hint_label.setWordWrap(True)
        right_layout.addWidget(self._result_tabs)
        right_layout.addWidget(self._local_hint_label)
        self._result_splitter.addWidget(right_panel)
        self._result_splitter.setStretchFactor(0, 1)
        self._result_splitter.setStretchFactor(1, 1)
        layout.addWidget(self._result_splitter, stretch=2)

        # 캐릭터별 LoRA — 로컬 타깃 + loras.json이 있을 때만 보인다.
        self._lora_group = QGroupBox()
        self._lora_layout = QVBoxLayout(self._lora_group)
        self._lora_group.setVisible(False)
        layout.addWidget(self._lora_group)

        # 네거티브 (compiled negative 표시, 편집 가능)
        self._negative_label = QLabel()
        layout.addWidget(self._negative_label)
        self._negative_edit = QPlainTextEdit()
        self._negative_edit.setMaximumHeight(100)
        layout.addWidget(self._negative_edit)

        # 상태 + 하단 버튼
        self._status_label = QLabel()
        layout.addWidget(self._status_label)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.apply_button = QPushButton()
        self.apply_button.clicked.connect(lambda: self._on_apply("apply"))
        self.insert_button = QPushButton()
        self.insert_button.clicked.connect(lambda: self._on_apply("insert"))
        self.replace_button = QPushButton()
        self.replace_button.clicked.connect(lambda: self._on_apply("replace"))
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.reject)
        button_row.addWidget(self.apply_button)
        button_row.addWidget(self.insert_button)
        button_row.addWidget(self.replace_button)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

    # ------------------------------------------------------------------
    # i18n
    # ------------------------------------------------------------------

    def retranslate(self) -> None:
        """모든 라벨/탭/플레이스홀더를 현재 언어로 다시 채운다."""
        tr = self._i18n.get_text
        self.setWindowTitle(tr("compiler.section_title"))
        self._mode_label.setText(tr("compiler.mode"))
        current = self.mode_combo.currentData()
        self.mode_combo.clear()
        for mode in MODE_TAGS:
            self.mode_combo.addItem(tr(f"compiler.mode_{mode}"), mode)
        index = self.mode_combo.findData(current if current in MODE_TAGS else DEFAULT_MODE)
        self.mode_combo.setCurrentIndex(index if index >= 0 else 0)
        self._target_label.setText(tr("compiler.target"))
        current_target = self.target_combo.currentData()
        # 재구성 중 currentIndexChanged가 튀면 탭이 잠깐 붙었다 떨어진다 — 막는다.
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for preset in self._compiler.target_presets:
            label = tr("compiler.target_novelai") if preset.id == NOVELAI_TARGET_ID else preset.name
            self.target_combo.addItem(label, preset.id)
        target_index = self.target_combo.findData(current_target)
        self.target_combo.setCurrentIndex(target_index if target_index >= 0 else 0)
        self.target_combo.blockSignals(False)
        self._result_tabs.setTabText(0, tr("compiler.tab_prompt"))
        if self._result_tabs.count() == 3:
            self._result_tabs.setTabText(1, tr("compiler.tab_couple_mask"))
            self._result_tabs.setTabText(2, tr("compiler.tab_regional_json"))
        self._couple_hint_label.setText(tr("compiler.couple_mask_hint"))
        self._local_hint_label.setText(tr("compiler.local_hint"))
        self._couple_copy_button.setText(tr("compiler.copy"))
        self._json_copy_button.setText(tr("compiler.copy"))
        self.convert_button.setText(tr("compiler.convert"))
        self.cancel_button.setText(tr("compiler.cancel"))
        self.regenerate_button.setText(tr("compiler.regenerate"))
        self._tabs.setTabText(0, tr("compiler.tab_create"))
        self._tabs.setTabText(1, tr("compiler.tab_modify"))
        self._input_edit.setPlaceholderText(tr("compiler.input_placeholder"))
        self._modify_hint_label.setText(tr("compiler.modify_hint"))
        self._final_label.setText(tr("compiler.result_final_prompt"))
        self._negative_label.setText(tr("compiler.result_negative"))
        self.apply_button.setText(tr("compiler.apply"))
        self.insert_button.setText(tr("compiler.insert"))
        self.replace_button.setText(tr("compiler.replace"))
        self.close_button.setText(tr("dialogs.cancel"))
        self._history_label.setText(tr("compiler.recent_inputs"))
        self._refresh_history_combo()  # 플레이스홀더 문구도 현재 언어로 갱신

    def _on_language_changed(self, _code: str) -> None:
        self.retranslate()

    def _unsubscribe(self) -> None:
        """언어 콜백을 떼어 낸다. 다이얼로그가 죽은 뒤 콜백이 남으면 죽은 위젯을 만진다."""
        if self._subscribed:
            self._i18n.unsubscribe(self._on_language_changed)
            self._subscribed = False

    def done(self, result: int) -> None:
        self._unsubscribe()
        # 내장 추론 모델(예: LlamaCppProvider)이 있으면 VRAM 해제 — 비상주 요구.
        close = getattr(self._compiler, "close", None)
        if callable(close):
            close()
        super().done(result)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt 이름
        self._unsubscribe()
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Convert Flow
    # ------------------------------------------------------------------

    def _apply_default_mode(self) -> None:
        default = getattr(self._settings.compiler, "default_mode", DEFAULT_MODE)
        if default not in MODE_TAGS:
            default = DEFAULT_MODE
        self.mode_combo.setCurrentIndex(self.mode_combo.findData(default))

    def _apply_default_target(self) -> None:
        """설정의 default_target으로 콤보를 맞춘다 (없는 id면 novelai)."""
        default = getattr(self._settings.compiler, "default_target", NOVELAI_TARGET_ID)
        index = self.target_combo.findData(default)
        self.target_combo.setCurrentIndex(index if index >= 0 else 0)
        self._on_target_changed()

    def _target(self) -> str:
        data = self.target_combo.currentData()
        return str(data) if data else NOVELAI_TARGET_ID

    def _is_local_target(self) -> bool:
        return self._target() != NOVELAI_TARGET_ID

    def _on_target_changed(self, _index: int = 0) -> None:
        """로컬 타깃일 때만 COUPLE MASK/영역 JSON 탭과 안내를 보인다."""
        local = self._is_local_target()
        if local:
            if self._result_tabs.count() == 1:
                tr = self._i18n.get_text
                self._result_tabs.addTab(self._couple_page, tr("compiler.tab_couple_mask"))
                self._result_tabs.addTab(self._json_page, tr("compiler.tab_regional_json"))
        else:
            # 탭만 떼는 게 아니라 편집기도 비운다 — 안 그러면 NovelAI로 돌아온 뒤에도
            # 직전 로컬 결과 문자열이 남아 클립보드로 새어 나간다.
            while self._result_tabs.count() > 1:
                self._result_tabs.removeTab(1)
            self._couple_edit.clear()
            self._json_edit.clear()
        self._local_hint_label.setVisible(local)
        self._update_lora_visibility()

    def _copy_to_clipboard(self, text: str) -> None:
        """텍스트를 클립보드에 넣고 상태줄에 알린다."""
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._status_label.setText(self._i18n.get_text("compiler.copied"))

    def _resolution(self) -> tuple[int, int] | None:
        """couple_mask의 MASK_SIZE에 쓸 현재 생성 해상도."""
        generation = getattr(self._settings, "generation", None)
        width = int(getattr(generation, "width", 0) or 0)
        height = int(getattr(generation, "height", 0) or 0)
        return (width, height) if width > 0 and height > 0 else None

    def _character_loras(self) -> dict:
        """캐릭터 id → LoraEntry (다이얼로그 선택 스냅숏).

        레지스트리에 없는 id는 조용히 버린다 (레지스트리 파일이 바뀐 경우).
        """
        selected: dict = {}
        for char_id, combo in self._lora_combos.items():
            entry_id = combo.currentData()
            if not entry_id:
                continue
            entry = self._compiler.lora_registry.get(entry_id)
            if entry is None:
                continue
            selected[char_id] = replace(entry, weight=self._lora_weights[char_id].value())
        return selected

    def _mode(self) -> str:
        return str(self.mode_combo.currentData())

    def _on_convert(self) -> None:
        self._run_conversion(use_last=False)

    def _on_regenerate(self) -> None:
        """마지막 변환 입력을 그대로 다시 실행한다 (LLM 변동성으로 다른 결과 기대)."""
        self._run_conversion(use_last=True)

    def _run_conversion(self, *, use_last: bool) -> None:
        tr = self._i18n.get_text
        if use_last:
            if self._last_run is None:
                return
            inputs = self._last_run
        else:
            modify = self._tabs.currentWidget() is self._modify_tab
            text = self._input_edit.toPlainText()
            existing = self._existing_edit.toPlainText()
            instruction = self._instruction_edit.toPlainText()
            if modify and not instruction.strip():
                QMessageBox.information(self, tr("errors.info"), tr("compiler.modify_hint"))
                return
            if not modify and not text.strip():
                QMessageBox.information(self, tr("errors.info"), tr("compiler.input_placeholder"))
                return
            inputs = _ConvertInputs(
                modify=modify,
                existing=existing,
                instruction=instruction,
                text=text,
                mode=self._mode(),
                # 위젯/설정을 읽는 값은 여기 GUI 스레드에서만 스냅숏한다.
                target=self._target(),
                character_loras=self._character_loras(),
                resolution=self._resolution(),
            )
            self._last_run = inputs

        self._cancel_requested = False
        self.convert_button.setEnabled(False)
        self.regenerate_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self._status_label.setText(tr("compiler.converting"))
        self._compiler_worker = threading.Thread(
            target=self._worker_convert,
            args=(inputs,),
            name="naiauto-compiler",
            daemon=True,
        )
        self._compiler_worker.start()

    def _worker_convert(self, inputs: _ConvertInputs) -> None:
        """워커 스레드 — LLM 추론은 여기서만 한다 (§29). 위젯 접근 금지."""
        try:
            if inputs.modify:
                compiled = self._compiler.modify(
                    inputs.existing,
                    inputs.instruction,
                    mode=inputs.mode,
                    target=inputs.target,
                    character_loras=inputs.character_loras,
                    resolution=inputs.resolution,
                )
            else:
                compiled = self._compiler.compile(
                    inputs.text,
                    mode=inputs.mode,
                    target=inputs.target,
                    character_loras=inputs.character_loras,
                    resolution=inputs.resolution,
                )
        except CompilerError as exc:
            self._emit_safely(self._converted_failed, None, exc)
            return
        except Exception as exc:  # provider 계약 밖의 예외도 UI를 멈추지 않게 한다
            logger.exception("prompt compiler crashed unexpectedly")
            self._emit_safely(self._converted_failed, None, exc)
            return
        if self._cancel_requested:  # 취소 flag — LLM 호출은 이미 끝났으므로 결과만 폐기
            self._emit_safely(self._converted_cancelled)
            return
        self._emit_safely(self._converted_ok, compiled, None)

    def _emit_safely(self, signal: SignalInstance, *args: object) -> None:
        """다이얼로그가 아직 살아 있을 때만 시그널을 쏜다 (MainWindow 패턴).

        변환 중 다이얼로그를 닫으면 알릴 곳이 없다. 파괴된 위젯에 emit하면 파이썬
        예외가 아니라 세그폴트가 나므로, 파이썬 쪽에서 먼저 막는다.
        """
        if not shiboken6.isValid(self):
            return
        try:
            signal.emit(*args)
        except RuntimeError:
            pass  # isValid 확인과 emit 사이에 닫힌 경우

    def _on_cancel(self) -> None:
        """LLM HTTP 호출 자체는 중단할 수 없다 — 완료 후 결과를 폐기한다 (§29)."""
        self._cancel_requested = True
        self.cancel_button.setEnabled(False)

    def _on_converted(self, compiled: object, err: object) -> None:
        self._set_conversion_idle()
        if err is not None:
            message = self._error_message(err)
            self._status_label.setText(message)
            logger.warning("compiler conversion failed: %s", err)
            QMessageBox.warning(self, self._i18n.get_text("compiler.error_title"), message)
            return
        if not isinstance(compiled, CompiledPrompt):
            return
        self._compiled = compiled
        self._render_preview(compiled)
        self._set_result_buttons(True)
        self._record_history()

    def _on_converted_cancelled(self) -> None:
        self._set_conversion_idle()

    # ------------------------------------------------------------------
    # 최근 입력 히스토리
    # ------------------------------------------------------------------

    def _record_history(self) -> None:
        """성공한 변환의 입력 스냅샷을 히스토리에 기록하고 콤보를 갱신한다."""
        if self._last_run is None:
            return
        self._history.add(self._to_history_entry(self._last_run))
        self._refresh_history_combo()

    def _to_history_entry(self, inputs: _ConvertInputs) -> InputHistoryEntry:
        """워커 입력 스냅샷 → 히스토리 항목."""
        return InputHistoryEntry(
            tab="modify" if inputs.modify else "create",
            text=inputs.text,
            existing_prompt=inputs.existing,
            instruction=inputs.instruction,
            mode=inputs.mode,
            target=inputs.target,
            ts=time.time(),
        )

    def _refresh_history_combo(self) -> None:
        """플레이스홀더 + 최근 입력 목록으로 콤보를 다시 채운다 (시그널 차단)."""
        self._history_restoring = True
        try:
            self._history_combo.blockSignals(True)
            self._history_combo.clear()
            self._history_combo.addItem(self._i18n.get_text("compiler.recent_placeholder"), None)
            for entry in self._history.recent():
                label = entry.instruction if entry.tab == "modify" else entry.text
                if not label.strip():
                    label = entry.existing_prompt or "—"
                self._history_combo.addItem(label, entry)
            self._history_combo.setCurrentIndex(0)
        finally:
            self._history_combo.blockSignals(False)
            self._history_restoring = False

    def _on_history_selected(self, index: int) -> None:
        """최근 입력 선택 → 해당 탭/입력 필드/모드를 복원한다 (자동 실행 없음)."""
        if self._history_restoring:
            return
        entry = self._history_combo.itemData(index)
        if entry is None:
            return
        if entry.tab == "modify":
            self._tabs.setCurrentWidget(self._modify_tab)
            self._existing_edit.setPlainText(entry.existing_prompt)
            self._instruction_edit.setPlainText(entry.instruction)
        else:
            self._tabs.setCurrentWidget(self._input_tab)
            self._input_edit.setPlainText(entry.text)
        index = self.mode_combo.findData(entry.mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        target_index = self.target_combo.findData(entry.target)
        if target_index >= 0:
            self.target_combo.setCurrentIndex(target_index)

    def _set_conversion_idle(self) -> None:
        """변환 종료(성공/실패/취소) 후 컨트롤을 복구한다."""
        self.convert_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.regenerate_button.setEnabled(self._last_run is not None)
        self._status_label.setText("")
        self._compiler_worker = None

    def _error_message(self, err: object) -> str:
        tr = self._i18n.get_text
        if isinstance(err, CompilerServerError):
            return f"{tr('compiler.err_connection')}\n\n{err}"  # HTTP status/body 상세
        if isinstance(err, CompilerError):
            return tr(_error_key_for(err))
        return str(err) or tr("compiler.err_connection")

    # ------------------------------------------------------------------
    # Result Preview
    # ------------------------------------------------------------------

    def _set_result_buttons(self, enabled: bool) -> None:
        self.apply_button.setEnabled(enabled)
        self.insert_button.setEnabled(enabled)
        self.replace_button.setEnabled(enabled)

    def _render_preview(self, compiled: CompiledPrompt) -> None:
        """QTextBrowser 구조 요약 + 최종 프롬프트/네거티브 편집기 채움."""
        tr = self._i18n.get_text
        separator = "──────────"
        lines: list[str] = []

        if compiled.scene.tags:
            lines.append(tr("compiler.result_scene"))
            lines.append(separator)
            lines.extend(ref.tag for ref in compiled.scene.tags)
            lines.append("")

        for index, char in enumerate(compiled.characters, start=1):  # 1-based 표시
            lines.append(tr("compiler.result_character_n", index))
            lines.append(separator)
            lines.append(", ".join(ref.tag for ref in char.tags))
            if char.position_hint:
                lines.append(f"{tr('ui.position')}: {char.position_hint}")
            elif char.center_x is not None and char.center_y is not None:
                lines.append(f"{tr('ui.position')}: ({char.center_x:.2f}, {char.center_y:.2f})")
            if char.negative_tags:
                lines.append(
                    f"{tr('ui.char_negative_prompt_label')} {', '.join(char.negative_tags)}"
                )
            lines.append("")

        if compiled.relationships:
            lines.append(tr("compiler.result_relationships"))
            lines.append(separator)
            for rel in compiled.relationships:
                lines.append(tr("compiler.result_relationship_row", rel.source, rel.target, rel.action))
            lines.append("")

        if compiled.unresolved:
            lines.append(tr("compiler.unresolved_title"))
            lines.append(separator)
            lines.extend(f"- {concept}" for concept in compiled.unresolved)
            lines.append("")

        if compiled.warnings:
            lines.append(tr("compiler.warnings_title"))
            lines.append(separator)
            lines.extend(f"- {warning}" for warning in compiled.warnings)

        self._preview_browser.setPlainText("\n".join(lines).strip("\n"))
        self._final_edit.setPlainText(compiled.base_prompt)
        self._negative_edit.setPlainText(compiled.negative_prompt)
        # 행이 먼저 있어야 _render_local_outputs가 현재 선택을 읽을 수 있다.
        self._rebuild_lora_rows(compiled)
        self._render_local_outputs(compiled)

    def _render_local_outputs(self, compiled: CompiledPrompt) -> None:
        """로컬 타깃일 때만 COUPLE MASK/영역 JSON 탭을 채운다."""
        if compiled.target == NOVELAI_TARGET_ID:
            self._couple_edit.clear()
            self._json_edit.clear()
            return
        preset = find_target(self._compiler.target_presets, compiled.target)
        loras = self._character_loras()
        couple, _ = emit_couple_mask(compiled, preset, loras, resolution=self._resolution())
        self._couple_edit.setPlainText(couple)
        self._json_edit.setPlainText(
            json.dumps(emit_regional_json(compiled, preset, loras), ensure_ascii=False, indent=2)
        )

    def _update_lora_visibility(self) -> None:
        """로컬 타깃 + 레지스트리가 있을 때만 LoRA 그룹을 보인다."""
        has_registry = bool(self._compiler.lora_registry)
        self._lora_group.setVisible(self._is_local_target() and has_registry)

    def _rebuild_lora_rows(self, compiled: CompiledPrompt) -> None:
        """컴파일 결과의 캐릭터마다 LoRA 행을 만든다 (id 기준으로 선택 유지)."""
        tr = self._i18n.get_text
        self._lora_group.setTitle(tr("compiler.lora"))
        previous = {
            char_id: (combo.currentData(), self._lora_weights[char_id].value())
            for char_id, combo in self._lora_combos.items()
        }
        while self._lora_layout.count():
            item = self._lora_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._lora_combos.clear()
        self._lora_weights.clear()

        if compiled.target == NOVELAI_TARGET_ID or not self._compiler.lora_registry:
            self._update_lora_visibility()
            return

        for char in compiled.characters:
            row_widget = QWidget(self._lora_group)
            row = QHBoxLayout(row_widget)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(QLabel(char.id))
            combo = QComboBox()
            combo.addItem(tr("compiler.lora_none"), None)
            for entry_id in sorted(self._compiler.lora_registry):
                combo.addItem(entry_id, entry_id)
            row.addWidget(combo, stretch=1)
            row.addWidget(QLabel(tr("compiler.lora_weight")))
            weight = QDoubleSpinBox()
            weight.setRange(0.0, 2.0)
            weight.setSingleStep(0.05)
            weight.setDecimals(2)
            row.addWidget(weight)

            saved_id, saved_weight = previous.get(char.id, (None, None))
            index = combo.findData(saved_id) if saved_id else 0
            combo.setCurrentIndex(index if index >= 0 else 0)
            if saved_weight is not None:
                weight.setValue(saved_weight)
            elif saved_id:
                weight.setValue(self._compiler.lora_registry[saved_id].weight)
            else:
                weight.setValue(1.0)
            # 선택 복원이 끝난 뒤에 연결한다 — 먼저 연결하면 복원이 콜백을 깨워
            # 사용자가 조정한 가중치를 레지스트리 기본값으로 덮어쓴다.
            combo.currentIndexChanged.connect(
                lambda _i, cid=char.id: self._on_lora_selected(cid)
            )

            self._lora_layout.addWidget(row_widget)
            self._lora_combos[char.id] = combo
            self._lora_weights[char.id] = weight
        self._update_lora_visibility()

    def _on_lora_selected(self, char_id: str) -> None:
        """LoRA를 고르면 가중치를 레지스트리 기본값으로 맞춘다."""
        entry_id = self._lora_combos[char_id].currentData()
        entry = self._compiler.lora_registry.get(entry_id) if entry_id else None
        self._lora_weights[char_id].setValue(entry.weight if entry else 1.0)

    # ------------------------------------------------------------------
    # Apply (MainWindow가 의미를 결정 — 여기선 신호만 쏜다)
    # ------------------------------------------------------------------

    def _on_apply(self, mode: Literal["apply", "insert", "replace"]) -> None:
        tr = self._i18n.get_text
        if self._compiled is None:
            QMessageBox.information(self, tr("errors.info"), tr("compiler.no_result"))
            return
        # 사용자가 수정한 문자열이 있으면 그대로 적용 (빈 값만 컴파일 결과로 대체).
        prompt = self._final_edit.toPlainText().strip() or self._compiled.base_prompt
        negative = self._negative_edit.toPlainText().strip() or self._compiled.negative_prompt
        # existing_negative는 MainWindow가 보존 병합하므로 여기선 빈 값.
        merged = to_generation_data(self._compiled)
        payload = CompilerApplyPayload(
            mode=mode,
            prompt=prompt,
            negative_prompt=negative,
            characters=merged.characters,
        )
        logger.info("compiler result applied: mode=%s characters=%d", mode, len(payload.characters))
        self.applied.emit(payload)
        self.accept()

    def set_existing_prompt(self, text: str) -> None:
        """수정 탭에 현재 메인 프롬프트를 반영한다 (MainWindow가 다이얼로그 열 때 호출)."""
        self._existing_edit.setPlainText(text)
