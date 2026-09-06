"""ComfyUI 백엔드 테스트 — HTTP/WS를 스텁으로 갈아 끼운다."""

import json

import pytest

from naiauto.core.api.models import GenerationRequest
from naiauto.core.backends.comfy_workflow import parse_template
from naiauto.core.backends.comfyui import ComfyUIBackend
from naiauto.core.backends.errors import (
    ComfyConnectionError,
    ComfyExecutionError,
    ComfyPromptRejectedError,
    ComfyTemplateError,
    ComfyTimeoutError,
)

PID = "11111111-1111-1111-1111-111111111111"

TEMPLATE = parse_template(
    {
        "id": "t",
        "name": "T",
        "output_node": "9",
        "model_slots": {"checkpoint": {"path": "4.ckpt_name", "from": "CheckpointLoaderSimple.ckpt_name"}},
        "slots": {"positive": "6.text", "seed": "3.seed"},
        "graph": {
            "3": {"inputs": {"seed": 0, "model": ["4", 0]}, "class_type": "KSampler"},
            "4": {"inputs": {"ckpt_name": ""}, "class_type": "CheckpointLoaderSimple"},
            "6": {"inputs": {"text": "", "clip": ["4", 1]}, "class_type": "CLIPTextEncode"},
            "9": {"inputs": {"images": ["8", 0]}, "class_type": "PreviewImage"},
        },
    }
)

EXECUTED = json.dumps(
    {
        "type": "executed",
        "data": {
            "node": "9",
            "prompt_id": PID,
            "output": {"images": [{"filename": "a.png", "subfolder": "", "type": "temp"}]},
        },
    }
)


class _StubWS:
    """websocket.WebSocket 대역 — 미리 정한 프레임을 차례로 돌려준다."""

    def __init__(self, frames, on_close=None):
        self._frames = list(frames)
        self.connected_url = None
        self.closed = False
        self._on_close = on_close

    def connect(self, url, **kwargs):
        self.connected_url = url

    def recv(self):
        if not self._frames:
            raise ConnectionError("socket closed")
        return self._frames.pop(0)

    def settimeout(self, value):
        pass

    def close(self):
        self.closed = True
        if self._on_close:
            self._on_close()


def _backend(monkeypatch, *, frames=(EXECUTED,), post=None, view=b"PNG", history=None):
    """스텁 HTTP/WS를 끼운 백엔드."""
    calls = {"post": [], "get": [], "ws": None}

    def _post_json(url, payload, **kwargs):
        calls["post"].append((url, payload))
        if post is not None:
            return post(url, payload)
        return {"prompt_id": PID, "number": 1, "node_errors": {}}

    def _get_bytes(url, **kwargs):
        calls["get"].append(url)
        return view

    def _get_json(url, **kwargs):
        calls["get"].append(url)
        return history if history is not None else {}

    ws = _StubWS(frames)
    calls["ws"] = ws

    backend = ComfyUIBackend(
        base_url="http://127.0.0.1:8188",
        template=TEMPLATE,
        model_slots={"checkpoint": "wai.safetensors"},
        timeout=1.0,
    )
    monkeypatch.setattr(backend, "_post_json", _post_json)
    monkeypatch.setattr(backend, "_get_bytes", _get_bytes)
    monkeypatch.setattr(backend, "_get_json", _get_json)
    monkeypatch.setattr(backend, "_make_socket", lambda: ws)
    monkeypatch.setattr(backend, "_new_prompt_id", lambda: PID)
    return backend, calls


REQ = GenerationRequest(prompt="1girl", negative_prompt="bad", seed=42, width=832, height=1216)


def test_generate_returns_image_bytes(monkeypatch):
    backend, calls = _backend(monkeypatch)
    result = backend.generate(REQ)
    assert result.raw_bytes == b"PNG"


def test_websocket_opens_before_post(monkeypatch):
    """POST가 먼저면 짧은 생성에서 executed를 놓쳐 영원히 기다린다."""
    order = []
    ws = _StubWS([EXECUTED])

    backend = ComfyUIBackend(base_url="http://127.0.0.1:8188", template=TEMPLATE, model_slots={}, timeout=1.0)

    def _connect(url, **kwargs):
        order.append("ws")

    ws.connect = _connect
    monkeypatch.setattr(backend, "_make_socket", lambda: ws)
    monkeypatch.setattr(backend, "_new_prompt_id", lambda: PID)
    monkeypatch.setattr(
        backend,
        "_post_json",
        lambda url, payload, **kw: (order.append("post"), {"prompt_id": PID})[1],
    )
    monkeypatch.setattr(backend, "_get_bytes", lambda url, **kw: b"PNG")
    backend.generate(REQ)
    assert order == ["ws", "post"]


def test_our_prompt_id_is_sent(monkeypatch):
    backend, calls = _backend(monkeypatch)
    backend.generate(REQ)
    _, payload = calls["post"][0]
    assert payload["prompt_id"] == PID
    assert payload["client_id"]


def test_slots_are_injected_into_posted_graph(monkeypatch):
    backend, calls = _backend(monkeypatch)
    backend.generate(REQ)
    _, payload = calls["post"][0]
    graph = payload["prompt"]
    assert graph["6"]["inputs"]["text"] == "1girl"
    assert graph["3"]["inputs"]["seed"] == 42
    assert graph["4"]["inputs"]["ckpt_name"] == "wai.safetensors"


def test_view_uses_temp_type(monkeypatch):
    backend, calls = _backend(monkeypatch)
    backend.generate(REQ)
    view_url = next(u for u in calls["get"] if "/view" in u)
    assert "type=temp" in view_url
    assert "filename=a.png" in view_url


def test_only_output_node_is_accepted(monkeypatch):
    """PreviewImage가 아닌 노드도 executed를 낸다 — output_node만 받는다.

    필터가 없으면 먼저 온 다른 노드의 이미지를 가져가 버린다.
    """
    other = json.dumps(
        {
            "type": "executed",
            "data": {
                "node": "8",
                "prompt_id": PID,
                "output": {"images": [{"filename": "other.png", "subfolder": "", "type": "temp"}]},
            },
        }
    )
    backend, calls = _backend(monkeypatch, frames=[other, EXECUTED])
    backend.generate(REQ)
    view_url = next(u for u in calls["get"] if "/view" in u)
    assert "filename=a.png" in view_url


def test_progress_is_forwarded(monkeypatch):
    """샘플링 진행률은 콜백으로 흘러나간다 — UI 진행 바의 원천이다."""
    progress = json.dumps({"type": "progress", "data": {"value": 3, "max": 20, "prompt_id": PID}})
    seen = []
    backend = ComfyUIBackend(
        base_url="http://127.0.0.1:8188",
        template=TEMPLATE,
        model_slots={},
        timeout=1.0,
        on_progress=lambda value, maximum: seen.append((value, maximum)),
    )
    ws = _StubWS([progress, EXECUTED])
    monkeypatch.setattr(backend, "_make_socket", lambda: ws)
    monkeypatch.setattr(backend, "_new_prompt_id", lambda: PID)
    monkeypatch.setattr(backend, "_post_json", lambda url, payload, **kw: {"prompt_id": PID})
    monkeypatch.setattr(backend, "_get_bytes", lambda url, **kw: b"PNG")
    backend.generate(REQ)
    assert seen == [(3, 20)]


def test_prompt_rejected_surfaces_node_errors(monkeypatch):
    node_errors = {"4": {"errors": [{"message": "value not in list"}]}}

    def _post(url, payload):
        raise ComfyPromptRejectedError("400", node_errors=node_errors)

    backend, _ = _backend(monkeypatch, post=_post)
    with pytest.raises(ComfyPromptRejectedError) as exc:
        backend.generate(REQ)
    assert exc.value.node_errors == node_errors


def test_execution_error_is_raised(monkeypatch):
    frame = json.dumps(
        {
            "type": "execution_error",
            "data": {
                "prompt_id": PID,
                "node_id": "3",
                "node_type": "KSampler",
                "exception_message": "boom",
            },
        }
    )
    backend, _ = _backend(monkeypatch, frames=[frame])
    with pytest.raises(ComfyExecutionError) as exc:
        backend.generate(REQ)
    assert exc.value.node_type == "KSampler"


def test_socket_drop_falls_back_to_history(monkeypatch):
    history = {PID: {"outputs": {"9": {"images": [{"filename": "h.png", "subfolder": "", "type": "temp"}]}}}}
    backend, calls = _backend(monkeypatch, frames=[], history=history)
    result = backend.generate(REQ)
    assert result.raw_bytes == b"PNG"
    assert any("/history/" in u for u in calls["get"])


def test_socket_drop_without_history_raises(monkeypatch):
    backend, _ = _backend(monkeypatch, frames=[], history={})
    with pytest.raises(ComfyTimeoutError):
        backend.generate(REQ)


def test_stop_sends_interrupt(monkeypatch):
    """중지 시 서버가 큐에 든 작업을 계속 돌리지 않도록 명시적으로 끊는다."""
    backend, calls = _backend(monkeypatch, frames=[])
    monkeypatch.setattr(backend, "_get_json", lambda url, **kw: {})
    backend.request_stop()
    with pytest.raises(ComfyTimeoutError):
        backend.generate(REQ)
    assert any("/interrupt" in url for url, _ in calls["post"])


def test_missing_template_raises(monkeypatch):
    backend = ComfyUIBackend(base_url="http://127.0.0.1:8188", template=None, model_slots={}, timeout=1.0)
    with pytest.raises(ComfyTemplateError):
        backend.generate(REQ)


def test_connection_failure_is_wrapped(monkeypatch):
    backend = ComfyUIBackend(base_url="http://127.0.0.1:8188", template=TEMPLATE, model_slots={}, timeout=1.0)

    def _boom():
        raise OSError("refused")

    monkeypatch.setattr(backend, "_make_socket", _boom)
    with pytest.raises(ComfyConnectionError):
        backend.generate(REQ)


def test_supports_credit_is_false():
    backend = ComfyUIBackend(base_url="http://127.0.0.1:8188", template=TEMPLATE, model_slots={}, timeout=1.0)
    assert backend.supports_credit is False
