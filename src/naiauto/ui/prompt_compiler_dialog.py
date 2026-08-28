"""자연어 → 구조화 프롬프트 컴파일 다이얼로그 (WD14Dialog 스타일).

흐름 (스펙 §24, §71): 입력 → 변환(worker 스레드) → 미리보기(구조 + 최종 문자열)
→ 사용자 검토 → Apply/Insert/Replace 신호 방출. 검토 전까지 기존 편집기를
절대 건드리지 않는다 — MainWindow(적용 담당)가 ``CompilerApplyPayload``를 받아
직접 적용한다.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import shiboken6
from PySide6.QtCore import Qt, Signal, SignalInstance
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
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
from naiauto.core.prompt.errors import (
    CompilerAuthError,
    CompilerEmptyResultError,
    CompilerError,
    CompilerParseError,
    CompilerServerError,
    CompilerTimeoutError,
)
from naiauto.core.prompt.merge import to_generation_data
from naiauto.core.prompt.schema import DEFAULT_MODE, MODE_TAGS, CompiledPrompt

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

        self.setMinimumSize(720, 560)
        self._build_ui()
        self.retranslate()
        self._apply_default_mode()
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
        self._final_edit = QPlainTextEdit()
        right_layout.addWidget(self._final_edit)
        self._result_splitter.addWidget(right_panel)
        self._result_splitter.setStretchFactor(0, 1)
        self._result_splitter.setStretchFactor(1, 1)
        layout.addWidget(self._result_splitter, stretch=2)

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

    def _on_language_changed(self, _code: str) -> None:
        self.retranslate()

    def _unsubscribe(self) -> None:
        """언어 콜백을 떼어 낸다. 다이얼로그가 죽은 뒤 콜백이 남으면 죽은 위젯을 만진다."""
        if self._subscribed:
            self._i18n.unsubscribe(self._on_language_changed)
            self._subscribed = False

    def done(self, result: int) -> None:
        self._unsubscribe()
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
                    inputs.existing, inputs.instruction, mode=inputs.mode
                )
            else:
                compiled = self._compiler.compile(inputs.text, mode=inputs.mode)
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

    def _on_converted_cancelled(self) -> None:
        self._set_conversion_idle()

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
