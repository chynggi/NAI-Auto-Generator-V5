"""ComfyUI 백엔드 오류 계층 테스트."""

import pytest

from naiauto.core.backends.errors import (
    ComfyConnectionError,
    ComfyError,
    ComfyExecutionError,
    ComfyPromptRejectedError,
    ComfyTemplateError,
    ComfyTimeoutError,
)


@pytest.mark.parametrize(
    "cls",
    [
        ComfyConnectionError,
        ComfyPromptRejectedError,
        ComfyExecutionError,
        ComfyTimeoutError,
        ComfyTemplateError,
    ],
)
def test_all_errors_share_a_base(cls):
    """UI는 ComfyError 하나만 잡으면 되어야 한다."""
    assert issubclass(cls, ComfyError)


def test_prompt_rejected_keeps_node_errors():
    """서버가 준 node_errors가 가장 정확한 진단이다 — 뭉뚱그리면 안 된다."""
    node_errors = {"3": {"errors": [{"message": "value not in list"}]}}
    exc = ComfyPromptRejectedError("bad prompt", node_errors=node_errors)
    assert exc.node_errors == node_errors
    assert "bad prompt" in str(exc)


def test_prompt_rejected_without_node_errors():
    exc = ComfyPromptRejectedError("boom")
    assert exc.node_errors == {}


def test_execution_error_keeps_node_type():
    exc = ComfyExecutionError("KSampler failed", node_id="3", node_type="KSampler")
    assert exc.node_id == "3"
    assert exc.node_type == "KSampler"
    assert "KSampler" in str(exc)
