"""로컬 ComfyUI 생성 옵션 페이지 (KEY="local_backend", 스펙 §6).

서버 주소·워크플로·모델 슬롯을 고른다. 템플릿마다 모델 슬롯 개수가 달라
(SDXL은 checkpoint 하나, Anima는 UNET+CLIP+VAE+터보 네 개) 위젯 수도 템플릿이
정한다. 템플릿을 오가도 각자의 선택이 남도록 ``_pending_slots``에 모아 둔다 —
평평한 dict로는 선택이 뒤섞인다 (§6.1).

서버가 꺼져 있으면(연결 확인 전) 슬롯 콤보 항목은 저장된 값 하나뿐이다.
목록을 못 받았다고 선택을 지우면 설정이 날아간다. 드래프트 의미론: ``load``는
드래프트 → 위젯, ``commit``은 위젯 → 드래프트다. 라이브 ``AppSettings``는 절대
만지지 않는다 (취소가 no-op이어야 한다). 범위 검증은 위젯의 클램프와
``core.settings.validation``의 몫이다.
"""

from __future__ import annotations

import copy

import requests
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.backends.comfy_objects import ObjectInfo, parse_object_info
from ...core.backends.comfy_workflow import ModelSlot, load_workflows
from ...core.i18n.manager import I18nManager
from ...core.settings.schema import AppSettings
from . import OptionsPage, register_page

__all__ = ["LocalBackendPage"]

#: 스프린박스 범위 — 위젯이 클램프하므로 손으로 고친 settings.json의 이상값도 안전하다.
DEFAULT_BASE_URL = "http://127.0.0.1:8188"
TIMEOUT_RANGE = (10.0, 3600.0)

#: 연결 확인 HTTP 타임아웃 (초). 옵션 창은 모달이고 로컬 서버라 짧으면 충분하다.
TEST_TIMEOUT = 5.0


@register_page
class LocalBackendPage(OptionsPage):
    """로컬 ComfyUI 생성 설정 (스펙 §6)."""

    KEY = "local_backend"

    def __init__(self, i18n: I18nManager, parent: QWidget | None = None, **_extra) -> None:
        # `**_extra`: 셸이 모든 페이지에 같은 키워드 인자 집합을 넘겨도 되도록 남는 것은 무시한다.
        super().__init__(parent)
        self._i18n = i18n
        #: ``load_workflows`` 결과 — 템플릿 콤보와 슬롯 위젯의 원천.
        self._templates: tuple = ()
        #: 연결 확인 성공 시 ``/object_info`` 파싱 결과. 기본 None = 서버 모름.
        self._object_info: ObjectInfo | None = None
        #: 템플릿 id → {슬롯명: 선택된 모델}. 뼈대가 아닌 위젯 값의 사본이다.
        self._slot_combos: dict[str, QComboBox] = {}
        #: 템플릿 id → {슬롯명: 선택된 모델}. `load`가 깊은 사본으로 들고,
        #: `commit`이 통째로 쓴다 — 지금 보이지 않는 템플릿의 선택도 살아남는다.
        self._pending_slots: dict[str, dict[str, str]] = {}
        #: 현재 ``_slot_combos``가 어느 템플릿의 것인지 — 값을 저장할 키.
        self._shown_template: str | None = None

        root = QVBoxLayout(self)

        self.section_label = QLabel(self)
        self.section_label.setStyleSheet("font-weight: bold;")
        root.addWidget(self.section_label)

        form = QFormLayout()

        self.url_label = QLabel(self)
        self._url_edit = QLineEdit(self)
        url_row = QHBoxLayout()
        url_row.addWidget(self._url_edit, 1)
        self.test_button = QPushButton(self)
        self.test_button.clicked.connect(self._test_connection)
        url_row.addWidget(self.test_button)
        form.addRow(self.url_label, url_row)

        self.status_label = QLabel(self)
        form.addRow(self.status_label)

        self.workflow_label = QLabel(self)
        self._template_combo = QComboBox(self)
        self._template_combo.currentIndexChanged.connect(self._on_template_changed)
        form.addRow(self.workflow_label, self._template_combo)

        self.workflow_dir_label = QLabel(self)
        self._workflows_dir_edit = QLineEdit(self)
        self._workflows_dir_edit.textChanged.connect(self._reload_templates)
        self.workflow_dir_browse = QPushButton(self)
        self.workflow_dir_browse.clicked.connect(self._browse_workflows_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self._workflows_dir_edit, 1)
        dir_row.addWidget(self.workflow_dir_browse)
        form.addRow(self.workflow_dir_label, dir_row)

        self.timeout_label = QLabel(self)
        self._timeout_spin = QDoubleSpinBox(self)
        self._timeout_spin.setRange(*TIMEOUT_RANGE)
        self._timeout_spin.setSingleStep(1)
        self._timeout_spin.setDecimals(1)
        form.addRow(self.timeout_label, self._timeout_spin)
        root.addLayout(form)

        self.models_label = QLabel(self)
        self.models_label.setStyleSheet("font-weight: bold;")
        root.addWidget(self.models_label)

        #: 슬롯 콤보들이 들어가는 폼 — `_select_template`이 통째로 갈아끼운다.
        self._slots_form = QFormLayout()
        root.addLayout(self._slots_form)

        root.addStretch(1)

        self.retranslate()

    # ── OptionsPage 계약 ────────────────────────────────────────────────

    def load(self, draft: AppSettings) -> None:
        self._pending_slots = copy.deepcopy(dict(draft.comfyui.model_slots))
        self._object_info = None
        self._url_edit.setText(draft.comfyui.base_url)
        self._timeout_spin.setValue(draft.comfyui.timeout_seconds)
        self._workflows_dir_edit.setText(draft.comfyui.workflows_dir)
        self._templates = load_workflows(draft.comfyui.workflows_dir)
        self._fill_template_combo()
        index = self._template_combo.findData(draft.comfyui.template_id)
        if index >= 0:
            selected = draft.comfyui.template_id
            self._template_combo.setCurrentIndex(index)
        else:
            selected = self._template_combo.currentData() or ""
        self._select_template(selected)
        self.status_label.setText(self._i18n.get_text("options.local_backend_no_options"))
        self.retranslate()

    def commit(self, draft: AppSettings) -> None:
        # 보이는 슬롯 콤보를 한 번 더 반영한 뒤 통째로 쓴다.
        self._remember_shown_slots()
        base = self._url_edit.text().strip()
        draft.comfyui.base_url = base or DEFAULT_BASE_URL
        draft.comfyui.template_id = self._template_combo.currentData() or ""
        draft.comfyui.model_slots = {k: dict(v) for k, v in self._pending_slots.items()}
        draft.comfyui.timeout_seconds = self._timeout_spin.value()
        draft.comfyui.workflows_dir = self._workflows_dir_edit.text().strip()

    def retranslate(self) -> None:
        tr = self._i18n.get_text
        self.section_label.setText(tr("options.local_backend_section"))
        self.url_label.setText(tr("options.local_backend_url"))
        self.test_button.setText(tr("options.local_backend_test"))
        self.workflow_label.setText(tr("options.local_backend_workflow"))
        self.workflow_dir_label.setText(tr("options.local_backend_workflow_dir"))
        self.workflow_dir_browse.setText(tr("options.browse"))
        self.timeout_label.setText(tr("options.local_backend_timeout"))
        self.models_label.setText(tr("options.local_backend_models_section"))
        # 슬롯 콤보의 "없음" 항목 문구만 다시 채운다 — 선택을 잃으면 안 된다.
        if self._shown_template is not None:
            for combo in self._slot_combos.values():
                stored = combo.currentData()
                combo.blockSignals(True)
                combo.setItemText(0, tr("options.local_backend_model_none"))
                combo.setCurrentIndex(combo.findData(stored) if stored else 0)
                combo.blockSignals(False)

    # ── 연결 확인 ───────────────────────────────────────────────────────

    def _test_connection(self) -> None:
        """``/object_info``로 연결을 확인한다 (동기 1회, 예외는 라벨로).

        응답을 파싱해 ``_apply_object_info``에 넘긴다. 실패하면 빈 정보를
        적용해 이전 연결 잔여물이 남지 않게 한다.
        """
        tr = self._i18n.get_text
        url = self._url_edit.text().strip() or DEFAULT_BASE_URL
        try:
            resp = requests.get(f"{url}/object_info", timeout=TEST_TIMEOUT)
            resp.raise_for_status()
            info = parse_object_info(resp.json())
        except requests.RequestException as exc:
            self.status_label.setText(tr("options.local_backend_failed", str(exc)))
            self._apply_object_info(ObjectInfo.empty())
            return
        self.status_label.setText(tr("options.local_backend_ok", len(info.node_classes)))
        self._apply_object_info(info)

    def _apply_object_info(self, info: ObjectInfo) -> None:
        """``/object_info`` 결과를 템플릿 목록과 슬롯 콤보에 반영한다.

        템플릿의 ``requires_nodes``를 충족하지 못하면 목록에서 뺀다 — 골라서
        실행 직전에 400을 받는 것보다 여기서 못 고르게 하는 게 낫다 (§3.2).
        """
        self._object_info = info
        self._fill_template_combo()

    # ── 템플릿 콤보 ─────────────────────────────────────────────────────

    def _fill_template_combo(self) -> None:
        """``_templates``/``_object_info`` 기준으로 콤보를 다시 채운다.

        선택은 (가용한 목록 안에서) 유지한다. object_info가 None이면(서버 모름)
        필터하지 않는다 — 저장된 템플릿을 고를 수 있어야 한다.
        """
        current = self._template_combo.currentData()
        self._template_combo.blockSignals(True)
        self._template_combo.clear()
        for template in self._templates:
            if self._object_info is not None and not template.is_available(self._object_info.node_classes):
                continue
            self._template_combo.addItem(template.name, template.id)
        if current is not None:
            index = self._template_combo.findData(current)
            self._template_combo.setCurrentIndex(index if index >= 0 else 0)
        self._template_combo.blockSignals(False)
        self._select_template(self._template_combo.currentData() or "")

    def _on_template_changed(self) -> None:
        if self._template_combo.count() == 0:
            return
        self._select_template(self._template_combo.currentData() or "")

    def _reload_templates(self) -> None:
        """사용자 워크플로 폴더가 바뀌면 템플릿 목록을 다시 읽는다."""
        self._templates = load_workflows(self._workflows_dir_edit.text().strip())
        self._fill_template_combo()

    def _browse_workflows_dir(self) -> None:
        tr = self._i18n.get_text
        path = QFileDialog.getExistingDirectory(
            self,
            tr("options.choose_folder", tr("options.local_backend_workflow_dir")),
            self._workflows_dir_edit.text(),
        )
        if path:
            self._workflows_dir_edit.setText(path)

    # ── 슬롯 콤보 ───────────────────────────────────────────────────────

    def _select_template(self, template_id: str) -> None:
        """템플릿의 모델 슬롯 위젯을 만든다 (개수는 템플릿이 정한다).

        위젯을 부수기 전에 현재 보이는 선택을 ``_pending_slots``에 저장한다 —
        콤보 객체를 버리기 전에 빼내지 않으면 그 값이 날아간다.
        """
        self._remember_shown_slots()
        self._slot_combos = {}
        while self._slots_form.rowCount():
            self._slots_form.removeRow(0)
        template = self._template_by_id(template_id)
        if template is None:
            self._shown_template = None
            return
        stored = self._pending_slots.get(template.id, {})
        for name, slot in template.model_slots.items():
            combo = QComboBox(self)
            self._fill_slot_combo(combo, slot, stored.get(name, ""))
            self._slot_combos[name] = combo
            self._slots_form.addRow(QLabel(name, self), combo)
        self._shown_template = template.id

    def _fill_slot_combo(self, combo: QComboBox, slot: ModelSlot, stored: str) -> None:
        """슬롯 콤보 항목을 채운다.

        ``_object_info``가 있으면 서버가 알려준 선택지, 없으면 저장된 값
        하나뿐이다. ``turbo_lora``처럼 비울 수 있는 슬롯을 위해 맨 앞에
        "(없음)"("" 값) 항목을 둔다.
        """
        combo.clear()
        combo.addItem(self._i18n.get_text("options.local_backend_model_none"), "")
        if self._object_info is not None:
            for choice in self._object_info.options(slot.source):
                combo.addItem(choice, choice)
            if stored and combo.findData(stored) < 0:
                combo.addItem(stored, stored)
        elif stored:
            combo.addItem(stored, stored)
        index = combo.findData(stored)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _remember_shown_slots(self) -> None:
        """현재 보이는 슬롯 콤보의 값을 ``_pending_slots``에 저장한다."""
        if self._shown_template is None:
            return
        saved = self._pending_slots.setdefault(self._shown_template, {})
        for name, combo in self._slot_combos.items():
            saved[name] = combo.currentData() or ""

    def _template_by_id(self, template_id: str):
        for template in self._templates:
            if template.id == template_id:
                return template
        return None
