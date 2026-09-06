"""LLM Options_Page (KEY=`"llm"`) — 자연어 프롬프트 생성용 LM Studio 연결 설정.

Host / 타임아웃 / 시스템 프롬프트 / 기본 반영 방식 / **프롬프트 세트 파일**을 다룬다.
"연결 테스트"는 지금 켜져 있는 LM Studio 서버에 실제로 붙어 본다 — 저장 전에도 사용자가
설정이 맞는지 바로 확인할 수 있게. 무거운 `lmstudio` import는 버튼을 눌렀을 때만 일어난다
(`core.llm.runtime_error` 참고).

프롬프트 세트는 LLM에 보내는 지시문을 **항목별로** 담은 JSON 파일이다 (형식은
`core/llm/prompt_config.py`). 여기서는 경로를 고르고, 기본값이 든 파일을 만들어 주고,
편집기로 열어 주고, 지금 그 파일이 읽히는지 즉시 확인해 준다 — 실제 적용은
프롬프트 어시스턴트 창이 열릴 때 일어난다.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ...core.i18n.manager import I18nManager
from ...core.llm.lmstudio_client import DEFAULT_HOST
from ...core.llm.prompt_config import (
    PromptConfigError,
    default_prompt_config_path,
    load_prompt_config,
    write_prompt_config,
)
from ...core.settings.schema import AppSettings
from . import OptionsPage, register_page

logger = logging.getLogger(__name__)

#: 타임아웃 스핀박스 범위 (core 검증의 LLM_TIMEOUT_RANGE와 맞춘다). 0 = 무제한.
TIMEOUT_RANGE = (0.0, 3600.0)

__all__ = ["LLMPage"]


@register_page
class LLMPage(OptionsPage):
    """LM Studio 연결 설정 페이지."""

    KEY = "llm"

    def __init__(self, i18n: I18nManager, parent: QWidget | None = None, **_extra: object) -> None:
        super().__init__(parent)
        self._i18n = i18n

        root = QVBoxLayout(self)

        form = QFormLayout()

        # Host + 연결 테스트
        self.host_label = QLabel(self)
        host_row = QHBoxLayout()
        self.host_edit = QLineEdit(self)
        self.host_edit.setPlaceholderText(DEFAULT_HOST)
        self.test_button = QPushButton(self)
        self.test_button.clicked.connect(self._test_connection)
        host_row.addWidget(self.host_edit, 1)
        host_row.addWidget(self.test_button)
        form.addRow(self.host_label, host_row)

        # 모델은 여기서 고르지 않는다 — 생성 다이얼로그가 서버에 로드된 목록에서 고른다.
        # (NAI가 모델을 저장하면 서버가 그 모델을 로드/유지하려다 복수 모델이 뜨는 문제가
        # 있었다.) 여기서는 안내 문구만 둔다.
        self.model_hint_label = QLabel(self)
        self.model_hint_label.setWordWrap(True)
        self.model_hint_label.setStyleSheet("color: palette(mid);")
        form.addRow("", self.model_hint_label)

        # 타임아웃
        self.timeout_label = QLabel(self)
        self.timeout_spin = QDoubleSpinBox(self)
        self.timeout_spin.setRange(*TIMEOUT_RANGE)
        self.timeout_spin.setDecimals(0)
        self.timeout_spin.setSingleStep(10)
        self.timeout_spin.setSuffix(" s")
        form.addRow(self.timeout_label, self.timeout_spin)

        root.addLayout(form)

        # 상태 문구 (연결 테스트/새로고침 결과)
        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        # 기본 출력 스타일 (자연어 문장 / 단부루 태그)
        self.style_label = QLabel(self)
        self.style_label.setStyleSheet("font-weight: bold;")
        root.addWidget(self.style_label)
        style_row = QHBoxLayout()
        self.natural_radio = QRadioButton(self)
        self.danbooru_radio = QRadioButton(self)
        # 스타일 라디오 2개를 하나의 그룹으로 묶는다 — 그러지 않으면 같은 부모 아래의
        # 반영 방식 라디오와 섞여 넷 중 하나만 선택되는 자동 배타에 걸린다.
        self._style_group = QButtonGroup(self)
        self._style_group.addButton(self.natural_radio)
        self._style_group.addButton(self.danbooru_radio)
        style_row.addWidget(self.natural_radio)
        style_row.addWidget(self.danbooru_radio)
        style_row.addStretch(1)
        root.addLayout(style_row)

        # 기본 반영 방식
        self.apply_mode_label = QLabel(self)
        self.apply_mode_label.setStyleSheet("font-weight: bold;")
        root.addWidget(self.apply_mode_label)
        mode_row = QHBoxLayout()
        self.append_radio = QRadioButton(self)
        self.replace_radio = QRadioButton(self)
        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.append_radio)
        self._mode_group.addButton(self.replace_radio)
        mode_row.addWidget(self.append_radio)
        mode_row.addWidget(self.replace_radio)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        # 시스템 프롬프트 (선택)
        self.system_label = QLabel(self)
        root.addWidget(self.system_label)
        self.system_edit = QPlainTextEdit(self)
        self.system_edit.setFixedHeight(110)
        root.addWidget(self.system_edit)

        # 프롬프트 세트 (항목별 지시문 JSON) — 외부 편집기로 고치는 파일
        self.prompt_section_label = QLabel(self)
        self.prompt_section_label.setStyleSheet("font-weight: bold;")
        root.addWidget(self.prompt_section_label)

        self.prompt_hint_label = QLabel(self)
        self.prompt_hint_label.setWordWrap(True)
        self.prompt_hint_label.setStyleSheet("color: palette(mid);")
        root.addWidget(self.prompt_hint_label)

        prompt_row = QHBoxLayout()
        self.prompt_path_edit = QLineEdit(self)
        self.prompt_path_edit.setPlaceholderText(str(default_prompt_config_path()))
        # 경로를 다 적고 포커스를 옮기면 그 자리에서 읽어 본다 (저장 전에 오타를 잡는다).
        self.prompt_path_edit.editingFinished.connect(self._refresh_prompt_status)
        self.prompt_browse_button = QPushButton(self)
        self.prompt_browse_button.clicked.connect(self._browse_prompt_config)
        prompt_row.addWidget(self.prompt_path_edit, 1)
        prompt_row.addWidget(self.prompt_browse_button)
        root.addLayout(prompt_row)

        prompt_btn_row = QHBoxLayout()
        self.prompt_create_button = QPushButton(self)
        self.prompt_create_button.clicked.connect(self._create_prompt_config)
        self.prompt_open_button = QPushButton(self)
        self.prompt_open_button.clicked.connect(self._open_prompt_config)
        prompt_btn_row.addWidget(self.prompt_create_button)
        prompt_btn_row.addWidget(self.prompt_open_button)
        prompt_btn_row.addStretch(1)
        root.addLayout(prompt_btn_row)

        self.prompt_status_label = QLabel(self)
        self.prompt_status_label.setWordWrap(True)
        root.addWidget(self.prompt_status_label)

        root.addStretch(1)
        self.retranslate()

    # ── OptionsPage 계약 ────────────────────────────────────────────────

    def load(self, draft: AppSettings) -> None:
        cfg = draft.lmstudio
        self.host_edit.setText(cfg.host)
        self.timeout_spin.setValue(cfg.timeout_seconds)
        self.system_edit.setPlainText(cfg.system_prompt)
        if cfg.default_style == "danbooru":
            self.danbooru_radio.setChecked(True)
        else:
            self.natural_radio.setChecked(True)
        if cfg.default_apply_mode == "replace":
            self.replace_radio.setChecked(True)
        else:
            self.append_radio.setChecked(True)
        self.prompt_path_edit.setText(cfg.prompt_config_path)
        self.status_label.setText("")
        self._refresh_prompt_status()

    def commit(self, draft: AppSettings) -> None:
        cfg = draft.lmstudio
        cfg.host = self.host_edit.text().strip() or DEFAULT_HOST
        # 모델은 저장하지 않는다 (다이얼로그가 서버 목록에서 고른다). 기존 값은 건드리지 않는다.
        cfg.timeout_seconds = self.timeout_spin.value()
        cfg.system_prompt = self.system_edit.toPlainText().strip()
        cfg.default_style = "danbooru" if self.danbooru_radio.isChecked() else "natural"
        cfg.default_apply_mode = "replace" if self.replace_radio.isChecked() else "append"
        # 빈 값은 "내장 기본 문안"이라는 뜻이라 그대로 둔다 (기본 경로로 채우지 않는다).
        cfg.prompt_config_path = self.prompt_path_edit.text().strip()

    def retranslate(self) -> None:
        tr = self._i18n.get_text
        self.host_label.setText(tr("options.llm_host"))
        self.test_button.setText(tr("options.llm_test"))
        self.model_hint_label.setText(tr("options.llm_model_hint"))
        self.timeout_label.setText(tr("options.llm_timeout"))
        self.style_label.setText(tr("options.llm_style"))
        self.natural_radio.setText(tr("options.llm_style_natural"))
        self.danbooru_radio.setText(tr("options.llm_style_danbooru"))
        self.apply_mode_label.setText(tr("options.llm_apply_mode"))
        self.append_radio.setText(tr("options.llm_apply_append"))
        self.replace_radio.setText(tr("options.llm_apply_replace"))
        self.system_label.setText(tr("options.llm_system_prompt"))
        self.system_edit.setPlaceholderText(tr("options.llm_system_prompt_hint"))
        self.prompt_section_label.setText(tr("options.llm_prompt_config_section"))
        self.prompt_hint_label.setText(tr("options.llm_prompt_config_hint"))
        self.prompt_browse_button.setText(tr("options.browse"))
        self.prompt_create_button.setText(tr("options.llm_prompt_config_create"))
        self.prompt_open_button.setText(tr("options.llm_prompt_config_open"))
        self._refresh_prompt_status()

    # ── 내부: 실서버 확인 ────────────────────────────────────────────────

    def _host(self) -> str:
        return self.host_edit.text().strip() or DEFAULT_HOST

    def _test_connection(self) -> None:
        """지금 켜진 LM Studio 서버에 붙어 본다 (`is_valid_api_host`)."""
        tr = self._i18n.get_text
        from ...core.llm.lmstudio_client import LMStudioPromptGenerator, runtime_error

        failure = runtime_error()
        if failure:
            self.status_label.setText(tr("options.llm_not_installed", failure))
            return
        try:
            ok = LMStudioPromptGenerator.check_connection(self._host())
        except Exception as e:  # noqa: BLE001
            logger.debug("LM Studio connection test failed: %s", e)
            self.status_label.setText(tr("options.llm_connect_failed", self._host()))
            return
        if ok:
            self.status_label.setText(tr("options.llm_connect_ok", self._host()))
        else:
            self.status_label.setText(tr("options.llm_connect_failed", self._host()))

    # ── 내부: 프롬프트 세트 파일 ─────────────────────────────────────────

    def _prompt_path(self) -> Path:
        """지금 칸에 적힌 경로. 비어 있으면 기본 위치(앱 데이터 폴더)."""
        text = self.prompt_path_edit.text().strip()
        return Path(text) if text else default_prompt_config_path()

    def _refresh_prompt_status(self) -> None:
        """지금 경로의 파일을 실제로 읽어 보고 결과를 문구로 알린다 (저장과 무관)."""
        tr = self._i18n.get_text
        target = self._prompt_path()
        if not target.exists():
            explicit = bool(self.prompt_path_edit.text().strip())
            key = "options.llm_prompt_config_missing" if explicit else "options.llm_prompt_config_none"
            self.prompt_status_label.setText(tr(key, str(target)))
            return
        try:
            config = load_prompt_config(target)
        except PromptConfigError as e:
            self.prompt_status_label.setText(tr("options.llm_prompt_config_error", str(e)))
            return
        self.prompt_status_label.setText(tr("options.llm_prompt_config_ok", config.name or target.name))

    def _browse_prompt_config(self) -> None:
        tr = self._i18n.get_text
        start = self._prompt_path()
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("options.choose_file", tr("options.llm_prompt_config_section")),
            str(start.parent if start.parent.exists() else Path.home()),
            tr("options.llm_prompt_config_filter"),
        )
        if path:
            self.prompt_path_edit.setText(path)
            self._refresh_prompt_status()

    def _create_prompt_config(self) -> None:
        """기본 문안이 든 편집용 파일을 만든다. 이미 있으면 덮어쓰지 않는다."""
        tr = self._i18n.get_text
        target = self._prompt_path()
        if target.exists():
            self.prompt_status_label.setText(tr("options.llm_prompt_config_exists", str(target)))
            self.prompt_path_edit.setText(str(target))
            return
        try:
            written = write_prompt_config(target)
        except PromptConfigError as e:
            self.prompt_status_label.setText(tr("options.llm_prompt_config_error", str(e)))
            return
        self.prompt_path_edit.setText(str(written))
        self.prompt_status_label.setText(tr("options.llm_prompt_config_created", str(written)))

    def _open_prompt_config(self) -> None:
        """OS 기본 편집기로 파일을 연다 (JSON은 보통 메모장/에디터가 받는다)."""
        tr = self._i18n.get_text
        target = self._prompt_path()
        if not target.is_file():
            self.prompt_status_label.setText(tr("options.llm_prompt_config_missing", str(target)))
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            self.prompt_status_label.setText(tr("options.llm_prompt_config_open_failed", str(target)))
