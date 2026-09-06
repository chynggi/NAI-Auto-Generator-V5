"""로컬 생성 옵션 페이지 — 드래프트 왕복과 슬롯 위젯 생성."""

import pytest
from PySide6.QtWidgets import QApplication

from naiauto.core.i18n.manager import I18nManager
from naiauto.core.settings.schema import AppSettings
from naiauto.ui.options_pages import page_class


@pytest.fixture()
def qapp():
    # `tests/test_compiler_dialog.py`와 같은 패턴 — conftest에는 없다.
    app = QApplication.instance() or QApplication([])
    yield app


def _page(qapp):
    # 페이지는 번역 함수가 아니라 I18nManager를 받는다 (prompt_ai_page 74행).
    return page_class("local_backend")(I18nManager())


def test_registered():
    assert page_class("local_backend").KEY == "local_backend"


def test_in_nav_order():
    from naiauto.ui.options_dialog import NAV_ORDER

    assert "local_backend" in NAV_ORDER


def test_round_trip(qapp):
    page = _page(qapp)
    draft = AppSettings()
    draft.comfyui.base_url = "http://192.168.0.9:8188"
    draft.comfyui.timeout_seconds = 120.0
    draft.comfyui.template_id = "anima"
    page.load(draft)

    out = AppSettings()
    page.commit(out)
    assert out.comfyui.base_url == "http://192.168.0.9:8188"
    assert out.comfyui.timeout_seconds == 120.0
    assert out.comfyui.template_id == "anima"


def test_blank_url_falls_back_to_default(qapp):
    """빈 주소로 저장하면 연결이 조용히 실패한다 — 기본값으로 되돌린다."""
    page = _page(qapp)
    page.load(AppSettings())
    page._url_edit.setText("   ")
    out = AppSettings()
    page.commit(out)
    assert out.comfyui.base_url == "http://127.0.0.1:8188"


def test_model_slot_widgets_follow_template(qapp):
    """슬롯 개수는 템플릿이 정한다 — SDXL은 1개, Anima는 4개."""
    page = _page(qapp)
    draft = AppSettings()
    draft.comfyui.template_id = "sdxl_basic"
    page.load(draft)
    assert set(page._slot_combos) == {"checkpoint"}

    page._select_template("anima")
    assert set(page._slot_combos) == {"unet", "clip", "vae", "turbo_lora"}


def test_slot_choice_is_kept_per_template(qapp):
    """템플릿을 오가도 각자의 선택이 남는다 (중첩 dict의 이유)."""
    page = _page(qapp)
    draft = AppSettings()
    draft.comfyui.model_slots = {
        "sdxl_basic": {"checkpoint": "a.safetensors"},
        "anima": {"unet": "b.safetensors"},
    }
    draft.comfyui.template_id = "sdxl_basic"
    page.load(draft)
    page._select_template("anima")
    page._select_template("sdxl_basic")

    out = AppSettings()
    page.commit(out)
    assert out.comfyui.model_slots["anima"]["unet"] == "b.safetensors"


def test_unavailable_template_is_hidden_when_nodes_missing(qapp):
    """requires_nodes 미충족 템플릿은 목록에서 뺀다 (스펙 §3.2)."""
    from naiauto.core.backends.comfy_objects import ObjectInfo

    page = _page(qapp)
    page.load(AppSettings())
    page._apply_object_info(
        ObjectInfo(node_classes=frozenset({"KSampler", "CheckpointLoaderSimple"}), _options={})
    )
    ids = [page._template_combo.itemData(i) for i in range(page._template_combo.count())]
    assert "sdxl_basic" in ids
    assert "sdxl_regional" not in ids


def test_saved_template_survives_when_server_unreachable(qapp):
    """서버가 꺼져 있어도 저장된 선택을 지운다면 사용자 설정이 날아간다."""
    page = _page(qapp)
    draft = AppSettings()
    draft.comfyui.template_id = "sdxl_regional"
    page.load(draft)
    out = AppSettings()
    page.commit(out)
    assert out.comfyui.template_id == "sdxl_regional"


def test_retranslate_does_not_lose_selection(qapp):
    page = _page(qapp)
    draft = AppSettings()
    draft.comfyui.template_id = "anima"
    page.load(draft)
    page.retranslate()
    out = AppSettings()
    page.commit(out)
    assert out.comfyui.template_id == "anima"


def test_edited_slot_value_is_saved_when_switching_template(qapp):
    """콤보를 다시 골라 템플릿을 오가도 그 선택이 남는다.

    위젯을 만들기 전에 현재 콤보 값을 뽑아 저장하지 않으면, 사용자가 고른
    값이 아니라 로드된 사본이 다시 심어진다.
    """
    page = _page(qapp)
    draft = AppSettings()
    draft.comfyui.model_slots = {"sdxl_basic": {"checkpoint": "a.safetensors"}}
    draft.comfyui.template_id = "sdxl_basic"
    page.load(draft)
    # 서버가 꺼져 있으므로 항목은 ("", "a.safetensors")뿐 — 0번("없음")을 고른다.
    page._slot_combos["checkpoint"].setCurrentIndex(0)
    page._select_template("anima")
    out = AppSettings()
    page.commit(out)
    assert out.comfyui.model_slots["sdxl_basic"]["checkpoint"] == ""


def test_load_does_not_mutate_draft_through_slot_saving(qapp):
    """드래프트 의미론 — 슬롯 저장이 드래프트를 오염시키면 취소가 no-op이 아니다.

    ``_pending_slots``는 드래프트를 통째로 끌어안지 않고 사본을 들고 있어야 한다.
    얕은 사본이면 템플릿 이동 시 저장하는 순간 드래프트 dict가 같이 오염된다.
    """
    page = _page(qapp)
    draft = AppSettings()
    draft.comfyui.model_slots = {"sdxl_basic": {"checkpoint": "a.safetensors"}}
    draft.comfyui.template_id = "sdxl_basic"
    page.load(draft)
    page._slot_combos["checkpoint"].setCurrentIndex(0)  # "(없음)"으로 변경
    page._select_template("anima")  # 현재 선택을 _pending_slots에 저장
    assert draft.comfyui.model_slots["sdxl_basic"]["checkpoint"] == "a.safetensors"
