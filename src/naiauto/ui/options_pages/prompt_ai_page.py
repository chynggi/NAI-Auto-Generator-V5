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
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...core.i18n.manager import I18nManager
from ...core.prompt.providers import API_KEY_CREDENTIAL
from ...core.prompt.targets import NOVELAI_TARGET_ID, load_lora_registry, load_target_presets
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
    ("options.prompt_ai_provider_deepseek", "deepseek"),
    ("options.prompt_ai_provider_llamacpp", "llama_cpp"),
)
REASONING_EFFORT_ITEMS: tuple[tuple[str, str], ...] = (
    ("options.prompt_ai_effort_low", "low"),
    ("options.prompt_ai_effort_medium", "medium"),
    ("options.prompt_ai_effort_high", "high"),
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
        self.provider_combo.currentIndexChanged.connect(self._update_provider_ui)
        form.addRow(self.provider_label, self.provider_combo)

        self.base_url_label = QLabel(self)
        self.base_url_edit = QLineEdit(self)
        form.addRow(self.base_url_label, self.base_url_edit)

        self.model_label = QLabel(self)
        self.model_edit = QLineEdit(self)
        form.addRow(self.model_label, self.model_edit)

        # ── llama_cpp (내장 추론) 전용 행 ──
        self.model_path_label = QLabel(self)
        self.model_path_edit = QLineEdit(self)
        self.model_path_browse = QPushButton(self)
        self.model_path_browse.clicked.connect(self._browse_model)
        path_row = QHBoxLayout()
        path_row.addWidget(self.model_path_edit, 1)
        path_row.addWidget(self.model_path_browse)
        form.addRow(self.model_path_label, path_row)

        self.n_gpu_layers_label = QLabel(self)
        self.n_gpu_layers_spin = QSpinBox(self)
        self.n_gpu_layers_spin.setRange(-1, 200)
        self.n_gpu_layers_spin.setSpecialValueText("-1 (전부)")
        form.addRow(self.n_gpu_layers_label, self.n_gpu_layers_spin)

        self.n_cpu_moe_label = QLabel(self)
        self.n_cpu_moe_spin = QSpinBox(self)
        self.n_cpu_moe_spin.setRange(0, 512)
        form.addRow(self.n_cpu_moe_label, self.n_cpu_moe_spin)

        self.expert_hot_s_label = QLabel(self)
        self.expert_hot_s_spin = QSpinBox(self)
        self.expert_hot_s_spin.setRange(-1, 512)
        self.expert_hot_s_spin.setSpecialValueText("-1 (auto)")
        form.addRow(self.expert_hot_s_label, self.expert_hot_s_spin)

        self.n_ctx_label = QLabel(self)
        self.n_ctx_spin = QSpinBox(self)
        self.n_ctx_spin.setRange(512, 262144)
        self.n_ctx_spin.setSingleStep(1024)
        form.addRow(self.n_ctx_label, self.n_ctx_spin)

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

        # ── llama-server 자동 실행 (openai_compatible 전용) ──
        self.auto_start_check = QCheckBox(self)
        form.addRow(self.auto_start_check)

        self.server_path_label = QLabel(self)
        self.server_path_edit = QLineEdit(self)
        self.server_path_browse = QPushButton(self)
        self.server_path_browse.clicked.connect(self._browse_server)
        server_row = QHBoxLayout()
        server_row.addWidget(self.server_path_edit, 1)
        server_row.addWidget(self.server_path_browse)
        form.addRow(self.server_path_label, server_row)

        self.server_args_label = QLabel(self)
        self.server_args_edit = QLineEdit(self)
        form.addRow(self.server_args_label, self.server_args_edit)

        # ── DeepSeek 전용 (thinking 모드) ──
        self.thinking_check = QCheckBox(self)
        form.addRow(self.thinking_check)

        self.effort_label = QLabel(self)
        self.effort_combo = QComboBox(self)
        for _key, value in REASONING_EFFORT_ITEMS:
            self.effort_combo.addItem(value, value)
        form.addRow(self.effort_label, self.effort_combo)
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

        # ── 출력 타깃 (로컬 SDXL) ──
        # 프리셋 내용 편집 UI는 만들지 않는다 — 사용자가 폴더의 JSON을 직접 고치고
        # 앱은 로드된 것만 보여 준다 (loras.json과 같은 정책).
        self.target_label = QLabel(self)
        self.target_combo = QComboBox(self)
        for preset in load_target_presets(None):
            self.target_combo.addItem(preset.name, preset.id)
        compiler_form.addRow(self.target_label, self.target_combo)

        self.presets_dir_label = QLabel(self)
        self.presets_dir_edit = QLineEdit(self)
        self.presets_dir_edit.textChanged.connect(self._refresh_target_sources)
        self.presets_dir_browse = QPushButton(self)
        self.presets_dir_browse.clicked.connect(self._browse_presets_dir)
        presets_row = QHBoxLayout()
        presets_row.addWidget(self.presets_dir_edit, 1)
        presets_row.addWidget(self.presets_dir_browse)
        compiler_form.addRow(self.presets_dir_label, presets_row)

        self.lora_status_label = QLabel(self)
        compiler_form.addRow(self.lora_status_label)

        root.addLayout(compiler_form)

        root.addStretch(1)

        self.retranslate()

    # ── OptionsPage 계약 ────────────────────────────────────────────────

    def load(self, draft: AppSettings) -> None:
        ai = draft.prompt_ai
        self._select(self.provider_combo, ai.provider)
        self.base_url_edit.setText(ai.base_url)
        self.model_edit.setText(ai.model)
        self.model_path_edit.setText(ai.model_path)
        self.n_gpu_layers_spin.setValue(ai.n_gpu_layers)
        self.n_cpu_moe_spin.setValue(ai.n_cpu_moe)
        self.expert_hot_s_spin.setValue(ai.expert_hot_s)
        self.n_ctx_spin.setValue(ai.n_ctx)
        self.temperature_spin.setValue(ai.temperature)
        self.max_tokens_spin.setValue(ai.max_tokens)
        self.timeout_spin.setValue(ai.timeout_seconds)
        self._select(self.mode_combo, draft.compiler.default_mode)
        self.use_resolver_check.setChecked(draft.compiler.use_danbooru_resolver)
        self.preserve_nl_check.setChecked(draft.compiler.preserve_natural_language)
        self._select(self.relationship_combo, draft.compiler.relationship_style)
        # 폴더를 먼저 채우고 콤보를 다시 만든 다음에 타깃을 골라야 사용자 프리셋
        # id를 찾을 수 있다 (콤보가 내장 프리셋만 든 채로는 findData가 실패한다).
        self.presets_dir_edit.setText(draft.compiler.target_presets_dir)
        self._refresh_target_sources()
        index = self.target_combo.findData(draft.compiler.default_target)
        self.target_combo.setCurrentIndex(index if index >= 0 else 0)

        # API 키는 입력란에 실지 않는다 — 키링 존재 여부만 표시한다 (§28, §64).
        # load_credential은 keyring 미사용 시 빈 문자열을 주므로 존재 확인만으로 충분하다.
        self.api_key_edit.clear()
        self.delete_key_check.setChecked(False)
        self._notices = []
        draft.prompt_ai.api_key_available = bool(credentials.load_credential(API_KEY_CREDENTIAL))
        self._key_stored = draft.prompt_ai.api_key_available
        self.auto_start_check.setChecked(ai.auto_start_server)
        self.server_path_edit.setText(ai.server_path)
        self.server_args_edit.setText(ai.server_args)
        self.thinking_check.setChecked(ai.thinking_enabled)
        self._select(self.effort_combo, ai.reasoning_effort)
        self._update_provider_ui()
        self.retranslate()  # 상태 문구 갱신

    def commit(self, draft: AppSettings) -> None:
        ai = draft.prompt_ai
        ai.provider = self.provider_combo.currentData()
        ai.base_url = self.base_url_edit.text().strip()
        ai.model = self.model_edit.text().strip()
        ai.model_path = self.model_path_edit.text().strip()
        ai.n_gpu_layers = self.n_gpu_layers_spin.value()
        ai.n_cpu_moe = self.n_cpu_moe_spin.value()
        ai.expert_hot_s = self.expert_hot_s_spin.value()
        ai.n_ctx = self.n_ctx_spin.value()
        ai.temperature = self.temperature_spin.value()
        ai.max_tokens = self.max_tokens_spin.value()
        ai.timeout_seconds = self.timeout_spin.value()
        ai.auto_start_server = self.auto_start_check.isChecked()
        ai.server_path = self.server_path_edit.text().strip()
        ai.server_args = self.server_args_edit.text().strip()
        ai.thinking_enabled = self.thinking_check.isChecked()
        ai.reasoning_effort = self.effort_combo.currentData() or "medium"
        draft.compiler.default_mode = self.mode_combo.currentData()
        draft.compiler.use_danbooru_resolver = self.use_resolver_check.isChecked()
        draft.compiler.preserve_natural_language = self.preserve_nl_check.isChecked()
        draft.compiler.relationship_style = self.relationship_combo.currentData()
        draft.compiler.target_presets_dir = self.presets_dir_edit.text().strip()
        draft.compiler.default_target = self.target_combo.currentData() or NOVELAI_TARGET_ID

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
        self.model_path_label.setText(tr("options.prompt_ai_model_path"))
        self.model_path_browse.setText(tr("options.prompt_ai_browse"))
        self.n_gpu_layers_label.setText(tr("options.prompt_ai_n_gpu_layers"))
        self.n_cpu_moe_label.setText(tr("options.prompt_ai_n_cpu_moe"))
        self.expert_hot_s_label.setText(tr("options.prompt_ai_expert_hot_s"))
        self.n_ctx_label.setText(tr("options.prompt_ai_n_ctx"))
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
        self.auto_start_check.setText(tr("options.prompt_ai_auto_start_server"))
        self.server_path_label.setText(tr("options.prompt_ai_server_path"))
        self.server_path_browse.setText(tr("options.prompt_ai_browse"))
        self.server_args_label.setText(tr("options.prompt_ai_server_args"))
        self.thinking_check.setText(tr("options.prompt_ai_thinking"))
        self.effort_label.setText(tr("options.prompt_ai_effort"))
        for index, (key, _value) in enumerate(REASONING_EFFORT_ITEMS):
            self.effort_combo.setItemText(index, tr(key))
        self.compiler_section.setText(tr("options.prompt_ai_compiler_section"))
        self.mode_label.setText(tr("options.compiler_default_mode"))
        for index, (key, _value) in enumerate(MODE_ITEMS):
            self.mode_combo.setItemText(index, tr(key))
        self.use_resolver_check.setText(tr("options.compiler_use_resolver"))
        self.preserve_nl_check.setText(tr("options.compiler_preserve_nl"))
        self.relationship_label.setText(tr("options.compiler_relationship_style"))
        for index, (key, _value) in enumerate(RELATIONSHIP_ITEMS):
            self.relationship_combo.setItemText(index, tr(key))
        self.target_label.setText(tr("options.compiler_target"))
        self.presets_dir_label.setText(tr("options.compiler_target_presets_dir"))
        self.presets_dir_browse.setText(tr("options.browse"))
        self._refresh_target_sources()

    def notices(self) -> tuple[str, ...]:
        return tuple(self._notices)

    # ── 내부 ────────────────────────────────────────────────────────────

    def _update_provider_ui(self) -> None:
        """provider에 따라 표시할 입력 행을 전환한다.

        openai_compatible → Base URL + 모델명 + llama-server 자동 실행.
        ollama → Base URL + 모델명.
        deepseek → 모델명 + thinking 모드/강도.
        llama_cpp → GGUF 모델 경로 + 오프로드/전문가/컨텍스트 설정.
        """
        provider = self.provider_combo.currentData()
        is_openai = provider == "openai_compatible"
        is_llama = provider == "llama_cpp"
        is_deepseek = provider == "deepseek"
        self.base_url_label.setVisible(is_openai or provider == "ollama")
        self.base_url_edit.setVisible(is_openai or provider == "ollama")
        self.model_label.setVisible(is_openai or provider == "ollama" or is_deepseek)
        self.model_edit.setVisible(is_openai or provider == "ollama" or is_deepseek)
        for w in (
            self.auto_start_check,
            self.server_path_label, self.server_path_edit, self.server_path_browse,
            self.server_args_label, self.server_args_edit,
        ):
            w.setVisible(is_openai)
        self.thinking_check.setVisible(is_deepseek)
        self.effort_label.setVisible(is_deepseek)
        self.effort_combo.setVisible(is_deepseek)
        for w in (
            self.model_path_label, self.model_path_edit, self.model_path_browse,
            self.n_gpu_layers_label, self.n_gpu_layers_spin,
            self.n_cpu_moe_label, self.n_cpu_moe_spin,
            self.expert_hot_s_label, self.expert_hot_s_spin,
            self.n_ctx_label, self.n_ctx_spin,
        ):
            w.setVisible(is_llama)

    def _browse_server(self) -> None:
        """llama-server 바이너리 선택 다이얼로그."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._i18n.get_text("options.prompt_ai_server_path"),
            self.server_path_edit.text(),
            "llama-server;;모든 파일 (*)",
        )
        if path:
            self.server_path_edit.setText(path)

    def _browse_presets_dir(self) -> None:
        """타깃 프리셋 + loras.json이 든 폴더를 고른다."""
        tr = self._i18n.get_text
        path = QFileDialog.getExistingDirectory(
            self,
            tr("options.choose_folder", tr("options.compiler_target_presets_dir")),
            self.presets_dir_edit.text(),
        )
        if path:
            self.presets_dir_edit.setText(path)

    def _refresh_target_sources(self) -> None:
        """폴더가 바뀌면 타깃 콤보와 LoRA 상태 문구를 다시 만든다."""
        tr = self._i18n.get_text
        directory = self.presets_dir_edit.text().strip()
        current = self.target_combo.currentData()
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        for preset in load_target_presets(directory):
            self.target_combo.addItem(preset.name, preset.id)
        index = self.target_combo.findData(current)
        self.target_combo.setCurrentIndex(index if index >= 0 else 0)
        self.target_combo.blockSignals(False)
        count = len(load_lora_registry(directory))
        self.lora_status_label.setText(
            tr("options.compiler_lora_loaded", count)
            if count
            else tr("options.compiler_lora_missing")
        )

    def _browse_model(self) -> None:
        """GGUF 모델 파일 선택 다이얼로그."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._i18n.get_text("options.prompt_ai_model_path"),
            self.model_path_edit.text(),
            "GGUF 모델 (*.gguf);;모든 파일 (*)",
        )
        if path:
            self.model_path_edit.setText(path)

    @staticmethod
    def _select(combo: QComboBox, value: str) -> None:
        """data가 value인 항목을 고른다. 알 수 없는 값(손으로 고친 settings.json)은 0번으로."""
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)
