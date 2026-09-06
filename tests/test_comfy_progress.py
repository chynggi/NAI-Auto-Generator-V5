"""WS 메시지 해석 테스트 — 실제 소켓 없이 메시지 파싱만 검증한다."""

import json

import pytest

from naiauto.core.backends.comfy_progress import (
    Executed,
    ExecutionFailed,
    Progress,
    parse_message,
)

PID = "11111111-1111-1111-1111-111111111111"


def test_progress_state_v034():
    """v0.34는 노드별 progress_state를 보낸다."""
    raw = json.dumps(
        {
            "type": "progress_state",
            "data": {
                "prompt_id": PID,
                "nodes": {"3": {"value": 7, "max": 28, "state": "running"}},
            },
        }
    )
    msg = parse_message(raw, PID)
    assert isinstance(msg, Progress)
    assert msg.value == 7
    assert msg.max_value == 28


def test_legacy_progress_message():
    """구버전 서버는 progress {value, max}를 보낸다 — 둘 다 받는다."""
    raw = json.dumps({"type": "progress", "data": {"value": 3, "max": 20, "prompt_id": PID}})
    msg = parse_message(raw, PID)
    assert isinstance(msg, Progress)
    assert msg.value == 3
    assert msg.max_value == 20


def test_executed_carries_images():
    """executed가 출력을 직접 실어 온다 — /history 폴링이 필요 없는 이유다."""
    raw = json.dumps(
        {
            "type": "executed",
            "data": {
                "node": "9",
                "prompt_id": PID,
                "output": {
                    "images": [
                        {"filename": "x_temp_abcde_00001_.png", "subfolder": "", "type": "temp"}
                    ]
                },
            },
        }
    )
    msg = parse_message(raw, PID)
    assert isinstance(msg, Executed)
    assert msg.node == "9"
    assert msg.images == ({"filename": "x_temp_abcde_00001_.png", "subfolder": "", "type": "temp"},)


def test_execution_error():
    raw = json.dumps(
        {
            "type": "execution_error",
            "data": {
                "prompt_id": PID,
                "node_id": "3",
                "node_type": "KSampler",
                "exception_message": "out of memory",
            },
        }
    )
    msg = parse_message(raw, PID)
    assert isinstance(msg, ExecutionFailed)
    assert msg.node_type == "KSampler"
    assert "out of memory" in msg.message


def test_other_prompt_ids_are_ignored():
    """여러 클라이언트가 붙어 있을 수 있다 — 남의 작업 메시지를 먹으면 안 된다.

    output을 비우면 안 된다 — 필터를 꺼도 "이미지 없음"으로 None이 나와
    테스트가 엉뚱한 이유로 통과한다 (실제로 그랬다).
    """
    raw = json.dumps(
        {
            "type": "executed",
            "data": {
                "node": "9",
                "prompt_id": "other",
                "output": {"images": [{"filename": "x.png", "subfolder": "", "type": "temp"}]},
            },
        }
    )
    assert parse_message(raw, PID) is None


def test_unknown_and_malformed_are_ignored():
    assert parse_message(json.dumps({"type": "status", "data": {}}), PID) is None
    assert parse_message("not json", PID) is None
    assert parse_message(json.dumps([1, 2, 3]), PID) is None
    assert parse_message(b"\x00\x01binary", PID) is None


def test_executed_without_images_is_ignored():
    """미리보기 노드가 아닌 노드도 executed를 낸다."""
    raw = json.dumps({"type": "executed", "data": {"node": "4", "prompt_id": PID, "output": {}}})
    assert parse_message(raw, PID) is None


@pytest.mark.parametrize(
    "raw",
    [
        "", "not json", "[]", "null", "123", b"", b"\x00\x01",
        '{"type": "progress_state"}',
        '{"type": "progress_state", "data": null}',
        '{"type": "progress_state", "data": {"prompt_id": "P", "nodes": null}}',
        '{"type": "progress_state", "data": {"prompt_id": "P", "nodes": {"1": null}}}',
        '{"type": "progress", "data": {}}',
        '{"type": "executed", "data": {"prompt_id": "P"}}',
        '{"type": "executed", "data": {"prompt_id": "P", "output": null}}',
        '{"type": "execution_error", "data": {"prompt_id": "P"}}',
        '{"type": "unknown_future_type", "data": {}}',
    ],
)
def test_parse_message_never_raises(raw):
    """외부 서버 프레임이다 — 예외를 내면 생성 스레드가 죽는다."""
    parse_message(raw, "P")
