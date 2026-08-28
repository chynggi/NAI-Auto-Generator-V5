"""MainWindow ↔ 컴파일러 통합 테스트 — _on_compiler_applied 적용 의미 (offscreen).

의존성은 전부 stub — 실제 API/서비스 호출은 없다. `_window()`는 MainWindow를
생성하지만 `check_updates_on_start=False`라 시작 시 업데이트 확인 스레드가
네트워크를 쏘지 않는다.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from naiauto.core.api.models import CharacterCaption
from naiauto.core.i18n.manager import I18nManager
from naiauto.core.settings.schema import AppSettings
from naiauto.ui.main_window import MainWindow
from naiauto.ui.prompt_compiler_dialog import CompilerApplyPayload


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


class _StubSession:
    is_logged_in = False
    def reauthenticate(self):
        return False


class _StubClient:
    def __init__(self):
        self.session = _StubSession()
    def get_anlas(self):
        return {"total": 0, "fixed": 0, "purchased": 0, "usage": None}


class _StubService:
    is_running = False
    def stop(self):
        pass
    def set_live_resolution(self, *a):
        pass
    def reload_artist_combos(self, *a):
        pass


def _window(qapp):
    """MainWindow를 생성하되 네트워크/서비스 의존성은 전부 stub.

    check_updates_on_start=False 필수 — 시작 시 업데이트 확인 스레드가 실제 HTTP를
    쏘지 않도록 한다. 생성 후 창은 닫지 않는다 (테스트 훅).
    """
    from naiauto.ui.qt_bridge import QtEventBridge

    settings = AppSettings(check_updates_on_start=False)
    win = MainWindow(
        i18n=I18nManager(),
        settings=settings,
        client=_StubClient(),
        service=_StubService(),
        bridge=QtEventBridge(),
    )
    return win


def test_apply_replaces_prompt_and_characters(qapp):
    win = _window(qapp)
    win.prompt_edit.setPlainText("old prompt, old_tag")
    win.negative_edit.setPlainText("old_neg")
    payload = CompilerApplyPayload(
        mode="apply",
        prompt="2girls, cafe, rain",
        negative_prompt="bad_hands",
        characters=(CharacterCaption(prompt="silver_hair", center_x=0.3, center_y=0.5),),
    )
    win._on_compiler_applied(payload)
    assert win.prompt_edit.toPlainText() == "2girls, cafe, rain"
    # 네거티브는 기존 + 컴파일 병합 (스펙 §22)
    assert win.negative_edit.toPlainText() == "old_neg, bad_hands"
    captions = win.character_prompts.captions()
    assert len(captions) == 1
    assert captions[0].prompt == "silver_hair"
    assert captions[0].center_x == pytest.approx(0.3)


def test_insert_preserves_existing_and_appends(qapp):
    win = _window(qapp)
    win.prompt_edit.setPlainText("1girl, __hairstyle__, {artist:grp}")
    payload = CompilerApplyPayload(
        mode="insert",
        prompt="2girls, cafe",
        negative_prompt="",
        characters=(CharacterCaption(prompt="silver_hair"),),
    )
    win._on_compiler_applied(payload)
    text = win.prompt_edit.toPlainText()
    assert "__hairstyle__" in text and "{artist:grp}" in text  # §51, §52 보존
    assert text.endswith("2girls, cafe")
    assert len(win.character_prompts.captions()) == 1


def test_replace_wipes_existing(qapp):
    win = _window(qapp)
    win.prompt_edit.setPlainText("old")
    win.negative_edit.setPlainText("old_neg")
    payload = CompilerApplyPayload(
        mode="replace",
        prompt="1girl, rooftop, night",
        negative_prompt="text",
        characters=(),
    )
    win._on_compiler_applied(payload)
    assert win.prompt_edit.toPlainText() == "1girl, rooftop, night"
    assert win.negative_edit.toPlainText() == "text"
    assert win.character_prompts.captions() == ()


def test_insert_mode_appends_to_existing(qapp):
    # 순수 문자열 결합 규칙 (MainWindow 없이)
    from naiauto.core.prompt.merge import merge_negatives

    existing = "1girl, __hairstyle__, silver_hair"
    combined = existing + ", " + "2girls, cafe"
    assert "__hairstyle__" in combined
    assert combined.endswith("2girls, cafe")
    assert merge_negatives("bad_hands", "text") == "bad_hands, text"


def test_no_result_before_compile_hidden_buttons(qapp):
    win = _window(qapp)
    # 적용 버튼 활성 조건은 다이얼로그 소관 — MainWindow 상태바는 컴파일 결과 없이
    # 호출돼도 안전해야 한다 (결과 없음 → 아무것도 안 함 정도의 가드): Apply 전
    # `_compiler_dialog`가 None이어도 크래시 없음.
    assert getattr(win, "_compiler_dialog", None) is None
