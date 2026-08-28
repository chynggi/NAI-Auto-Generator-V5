"""Prompt AI + Prompt Compiler 옵션 페이지 (KEY="prompt_ai", 스펙 §46).

두 설정 그룹을 한 페이지에 둔다: LLM provider(openai_compatible/ollama — llama.cpp
로컬 서버가 기본)와 컴파일러 기본 동작. API 키는 settings.json에 저장되지 않는다
(§28, §64): 입력하면 OS keyring(`core.settings.credentials`)에만 기록하고
`api_key_available`로 "저장되어 있음" 여부만 표시한다. keyring을 쓸 수 없는
환경에서는 저장하지 않고 입력란만 비운 뒤 경고 노트(`compiler.warn_keyring`)를 낸다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.i18n.manager import I18nManager
from ...core.prompt.providers import API_KEY_CREDENTIAL
from ...core.settings import credentials
from ...core.settings.schema import AppSettings
from . import OptionsPage, register_page

#: 스핀박스 범위 — 위젯이 클램프하므로 손으로 고친 settings.json의 이상값도 안전하다.
TEMPERATURE_RANGE = (0.0, 2.0)
MAX_TOKENS_RANGE = (64, 4096)
TIMEOUT_RANGE = (5.0, 600.0)

#: keyring에 저장하지 못했을 때의 안내 노트 키 (표시는 Main_Window의 몫).
KEYRING_WARN_KEY = "compiler.warn_keyring"

#: 콤보 항목 — (표시 i18n 키, data 값). retranslate가 인덱스로 다시 채운다.
PROVIDER_ITEMS: tuple[tuple[str, str], ...] = (
    ("options.prompt_ai_provider_openai", "openai_compatible"),
    ("options.prompt_ai_provider_ollama", "ollama"),
)
MODE_ITEMS: tuple[tuple[str, str], ...] = (
    ("compiler.mode_tag", "tag"),
    ("compiler.mode_hybrid", "hybrid"),
    ("compiler.mode_natural", "natural"),
)
RELATIONSHIP_ITEMS: tuple[tuple[str, str], ...] = (
    ("compiler.mode_natural", "natural"),
    ("compiler.mode_tag", "tag"),
)

__all__ = ["KEYRING_WARN_KEY", "PromptAiPage"]


@register_page
class PromptAiPage(OptionsPage):
    """Prompt AI + Prompt Compiler 설정 (스펙 §46의 두 그룹을 한 페이지에)."""

    KEY = "prompt_ai"

    def __init__(self, i18n: I18nManager, parent: QWidget | None = None, **_extra) -> None:
        # `**_extra`: 셸이 모든 페이지에 같은 키워드 인자 집합을 넘겨도 되도록 남는 것은 무시한다.
        super().__init__(parent)
        self._i18n = i18n
        #: keyring에 LLM API 키가 저장되어 있는지 (load에서 확정, retranslate가 표시).
        self._key_stored = False
        #: commit에서 낸 안내 노트 — 저장 후 Main_Window가 모아서 보여 준다.
        self._notices: list[str] = []

        root = QVBoxLayout(self)

        # ── 그룹 1: Prompt AI ──────────────────────────────────────────
        self.provider_section = QLabel(self)
        self.provider_section.setStyleSheet("font-weight: bold;")
        root.addWidget(self.provider_section)

        form = QFormLayout()
        self.provider_label = QLabel(self)
        self.provider_combo = QComboBox(self)
        for _key, value in PROVIDER_ITEMS:
            self.provider_combo.addItem(value, value)  # 문구는 retranslate에서 채운다
        form.addRow(self.provider_label, self.provider_combo)

        self.base_url_label = QLabel(self)
        self.base_url_edit = QLineEdit(self)
        form.addRow(self.base_url_label, self.base_url_edit)

        self.model_label = QLabel(self)
        self.model_edit = QLineEdit(self)
        form.addRow(self.model_label, self.model_edit)

        self.temperature_label = QLabel(self)
        self.temperature_spin = QDoubleSpinBox(self)
        self.temperature_spin.setRange(*TEMPERATURE_RANGE)
        self.temperature_spin.setSingleStep(0.05)
        self.temperature_spin.setDecimals(2)
        form.addRow(self.temperature_label, self.temperature_spin)

        self.max_tokens_label = QLabel(self)
        self.max_tokens_spin = QSpinBox(self)
        self.max_tokens_spin.setRange(*MAX_TOKENS_RANGE)
        self.max_tokens_spin.setSingleStep(64)
        form.addRow(self.max_tokens_label, self.max_tokens_spin)

        self.timeout_label = QLabel(self)
        self.timeout_spin = QDoubleSpinBox(self)
        self.timeout_spin.setRange(*TIMEOUT_RANGE)
        self.timeout_spin.setSingleStep(1)
        self.timeout_spin.setDecimals(1)
        form.addRow(self.timeout_label, self.timeout_spin)

        self.api_key_label = QLabel(self)
        self.api_key_edit = QLineEdit(self)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(self.api_key_label, self.api_key_edit)
        root.addLayout(form)

        self.delete_key_check = QCheckBox(self)
        root.addWidget(self.delete_key_check)
        self.api_key_status_label = QLabel(self)
        self.api_key_status_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        root.addWidget(self.api_key_status_label)

        # ── 그룹 2: Prompt Compiler ────────────────────────────────────
        self.compiler_section = QLabel(self)
        self.compiler_section.setStyleSheet("font-weight: bold;")
        root.addWidget(self.compiler_section)

        compiler_form = QFormLayout()
        self.mode_label = QLabel(self)
        self.mode_combo = QComboBox(self)
        for _key, value in MODE_ITEMS:
            self.mode_combo.addItem(value, value)
        compiler_form.addRow(self.mode_label, self.mode_combo)

        self.use_resolver_check = QCheckBox(self)
        compiler_form.addRow(self.use_resolver_check)
        self.preserve_nl_check = QCheckBox(self)
        compiler_form.addRow(self.preserve_nl_check)

        self.relationship_label = QLabel(self)
        self.relationship_combo = QComboBox(self)
        for _key, value in RELATIONSHIP_ITEMS:
            self.relationship_combo.addItem(value, value)
        compiler_form.addRow(self.relationship_label, self.relationship_combo)
        root.addLayout(compiler_form)

        root.addStretch(1)

        self.retranslate()

    # ── OptionsPage 계약 ────────────────────────────────────────────────

    def load(self, draft: AppSettings) -> None:
        ai = draft.prompt_ai
        self._select(self.provider_combo, ai.provider)
        self.base_url_edit.setText(ai.base_url)
        self.model_edit.setText(ai.model)
        self.temperature_spin.setValue(ai.temperature)
        self.max_tokens_spin.setValue(ai.max_tokens)
        self.timeout_spin.setValue(ai.timeout_seconds)
        self._select(self.mode_combo, draft.compiler.default_mode)
        self.use_resolver_check.setChecked(draft.compiler.use_danbooru_resolver)
        self.preserve_nl_check.setChecked(draft.compiler.preserve_natural_language)
        self._select(self.relationship_combo, draft.compiler.relationship_style)

        # API 키는 입력란에 실지 않는다 — 키링 존재 여부만 표시한다 (§28, §64).
        # load_credential은 keyring 미사용 시 빈 문자열을 주므로 존재 확인만으로 충분하다.
        self.api_key_edit.clear()
        self.delete_key_check.setChecked(False)
        self._notices = []
        draft.prompt_ai.api_key_available = bool(credentials.load_credential(API_KEY_CREDENTIAL))
        self._key_stored = draft.prompt_ai.api_key_available
        self.retranslate()  # 상태 문구 갱신

    def commit(self, draft: AppSettings) -> None:
        ai = draft.prompt_ai
        ai.provider = self.provider_combo.currentData()
        ai.base_url = self.base_url_edit.text().strip()
        ai.model = self.model_edit.text().strip()
        ai.temperature = self.temperature_spin.value()
        ai.max_tokens = self.max_tokens_spin.value()
        ai.timeout_seconds = self.timeout_spin.value()
        draft.compiler.default_mode = self.mode_combo.currentData()
        draft.compiler.use_danbooru_resolver = self.use_resolver_check.isChecked()
        draft.compiler.preserve_natural_language = self.preserve_nl_check.isChecked()
        draft.compiler.relationship_style = self.relationship_combo.currentData()

        self._notices = []
        if self.delete_key_check.isChecked():
            credentials.delete_credential(API_KEY_CREDENTIAL)
            ai.api_key_available = False
        key_text = self.api_key_edit.text().strip()
        if key_text:
            # [review #3] is_available()만 보지 않고 실제 저장 성공 여부를 확인한다 —
            # keyring 백엔드가 저장 단계에서 실패해도 저장된 것처럼 표시되지 않게.
            # save_credential은 keyring 미사용 환경에서도 False를 돌려준다.
            if credentials.save_credential(API_KEY_CREDENTIAL, key_text):
                ai.api_key_available = True
            else:
                # keyring을 쓸 수 없거나 저장에 실패하면 어디에도 저장하지 않는다 —
                # settings.json에 키가 들어가는 유일한 경로라 차단한다 (§28, §64).
                ai.api_key_available = False
                self._notices.append(KEYRING_WARN_KEY)
            self.api_key_edit.clear()

    def retranslate(self) -> None:
        tr = self._i18n.get_text
        self.provider_section.setText(tr("options.prompt_ai_section"))
        self.provider_label.setText(tr("options.prompt_ai_provider"))
        for index, (key, _value) in enumerate(PROVIDER_ITEMS):
            self.provider_combo.setItemText(index, tr(key))
        self.base_url_label.setText(tr("options.prompt_ai_base_url"))
        self.model_label.setText(tr("options.prompt_ai_model"))
        self.temperature_label.setText(tr("options.prompt_ai_temperature"))
        self.max_tokens_label.setText(tr("options.prompt_ai_max_tokens"))
        self.timeout_label.setText(tr("options.prompt_ai_timeout"))
        self.api_key_label.setText(tr("options.prompt_ai_api_key"))
        self.api_key_edit.setPlaceholderText(tr("options.prompt_ai_api_key_placeholder"))
        self.delete_key_check.setText(tr("options.prompt_ai_delete_api_key"))
        self.api_key_status_label.setText(
            tr("options.prompt_ai_api_key_saved")
            if self._key_stored
            else tr("options.prompt_ai_api_key_missing")
        )
        self.compiler_section.setText(tr("options.prompt_ai_compiler_section"))
        self.mode_label.setText(tr("options.compiler_default_mode"))
        for index, (key, _value) in enumerate(MODE_ITEMS):
            self.mode_combo.setItemText(index, tr(key))
        self.use_resolver_check.setText(tr("options.compiler_use_resolver"))
        self.preserve_nl_check.setText(tr("options.compiler_preserve_nl"))
        self.relationship_label.setText(tr("options.compiler_relationship_style"))
        for index, (key, _value) in enumerate(RELATIONSHIP_ITEMS):
            self.relationship_combo.setItemText(index, tr(key))

    def notices(self) -> tuple[str, ...]:
        return tuple(self._notices)

    # ── 내부 ────────────────────────────────────────────────────────────

    @staticmethod
    def _select(combo: QComboBox, value: str) -> None:
        """data가 value인 항목을 고른다. 알 수 없는 값(손으로 고친 settings.json)은 0번으로."""
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)
