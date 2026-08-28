"""옵션 페이지 등록 레지스트리 테스트."""

from naiauto.ui.options_pages import page_class


def test_prompt_ai_page_registered():
    cls = page_class("prompt_ai")
    assert cls.KEY == "prompt_ai"
