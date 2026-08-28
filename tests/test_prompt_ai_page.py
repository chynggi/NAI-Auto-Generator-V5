"""PromptAiPage commit의 keyring 저장 실패 처리 테스트 (offscreen)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from naiauto.core.i18n.manager import I18nManager
from naiauto.core.settings.schema import AppSettings
from naiauto.ui.options_pages.prompt_ai_page import KEYRING_WARN_KEY, PromptAiPage


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


def test_commit_marks_key_available_only_when_save_succeeds(qapp, monkeypatch):
    # [review #3] is_available()만 보지 않고 save_credential의 실제 성공 여부를
    # 반영한다 — 저장 실패 시 api_key_available=True로 오표시되지 않는다.
    from naiauto.ui.options_pages import prompt_ai_page

    draft = AppSettings()
    page = PromptAiPage(I18nManager())
    page.load(draft)
    page.api_key_edit.setText("secret")

    monkeypatch.setattr(prompt_ai_page.credentials, "save_credential", lambda *a: False)
    page.commit(draft)
    assert draft.prompt_ai.api_key_available is False
    assert KEYRING_WARN_KEY in page.notices()
    assert page.api_key_edit.text() == ""  # 입력란은 비운다 (재입력 유도)

    # 저장 성공 시에는 available=True + 경고 없음
    monkeypatch.setattr(prompt_ai_page.credentials, "save_credential", lambda *a: True)
    page.api_key_edit.setText("secret")
    page.commit(draft)
    assert draft.prompt_ai.api_key_available is True
    assert KEYRING_WARN_KEY not in page.notices()


def test_commit_no_key_leaves_state_unchanged(qapp, monkeypatch):
    from naiauto.ui.options_pages import prompt_ai_page

    draft = AppSettings()
    page = PromptAiPage(I18nManager())
    page.load(draft)
    assert draft.prompt_ai.api_key_available is False

    called = []
    monkeypatch.setattr(prompt_ai_page.credentials, "save_credential", lambda *a: called.append(a) or True)
    page.commit(draft)  # 입력 없음 → 저장 시도 자체가 없어야 한다
    assert called == []
    assert draft.prompt_ai.api_key_available is False
    assert page.notices() == ()
