"""ComfyUI 생성 백엔드.

흐름:
  1. prompt_id·client_id를 우리가 만든다 (서버가 canonical UUID를 받아 준다)
  2. WS를 **먼저** 연다 — POST가 먼저면 짧은 생성에서 executed를 놓친다
  3. POST /prompt
  4. WS에서 executed를 기다린다 (progress는 콜백으로 흘린다)
  5. GET /view로 이미지 바이트를 가져온다

/history 폴링은 하지 않는다 — executed가 출력을 직접 실어 온다. 소켓이 끊긴
경우에만 /history/{prompt_id}를 1회 확인한다.

Qt 의존성 없음.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from urllib.parse import urlencode, urlparse, urlunparse

import requests

from naiauto.core.api.models import GenerationRequest, GenerationResult
from naiauto.core.backends.comfy_progress import (
    Executed,
    ExecutionFailed,
    Progress,
    parse_message,
)
from naiauto.core.backends.comfy_workflow import (
    LoraAssignment,
    WorkflowTemplate,
    build_graph,
)
from naiauto.core.backends.errors import (
    ComfyConnectionError,
    ComfyExecutionError,
    ComfyPromptRejectedError,
    ComfyTemplateError,
    ComfyTimeoutError,
)

logger = logging.getLogger(__name__)

__all__ = ["ComfyUIBackend"]


class ComfyUIBackend:
    """로컬 ComfyUI로 txt2img를 돌리는 백엔드."""

    #: 로컬 서버에는 Anlas/크레딧 개념이 없다 (backends.base 참고).
    supports_credit = False

    def __init__(
        self,
        *,
        base_url: str,
        template: WorkflowTemplate | None,
        model_slots: dict[str, str],
        timeout: float = 300.0,
        loras: tuple[LoraAssignment, ...] = (),
        on_progress: Callable[[int, int], None] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.template = template
        self.model_slots = dict(model_slots)
        self.timeout = timeout
        self.loras = loras
        self._on_progress = on_progress
        self._stop = threading.Event()

    # -- 중지 ----------------------------------------------------------

    def request_stop(self) -> None:
        """다음 생성부터 중단한다 (GenerationService의 중지와 짝을 이룬다)."""
        self._stop.set()

    def clear_stop(self) -> None:
        self._stop.clear()

    # -- 네트워크 경계 (테스트가 이 다섯 개를 갈아 끼운다) ----------------

    def _new_prompt_id(self) -> str:
        return str(uuid.uuid4())

    def _make_socket(self):
        import websocket  # lazy — import 비용을 앱 시작에서 뺀다

        return websocket.WebSocket()

    def _post_json(self, url: str, payload: dict) -> dict:
        try:
            resp = requests.post(url, json=payload, timeout=30)
        except requests.RequestException as exc:
            raise ComfyConnectionError(f"cannot reach ComfyUI at {self.base_url}: {exc}") from exc
        if resp.status_code == 400:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            raise ComfyPromptRejectedError(
                str(body.get("error", {}).get("message", "prompt rejected")),
                node_errors=body.get("node_errors") or {},
            )
        resp.raise_for_status()
        return resp.json()

    def _get_json(self, url: str) -> dict:
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as exc:
            raise ComfyConnectionError(f"cannot reach ComfyUI at {self.base_url}: {exc}") from exc

    def _get_bytes(self, url: str) -> bytes:
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as exc:
            raise ComfyConnectionError(f"cannot fetch image: {exc}") from exc

    # -- 생성 ----------------------------------------------------------

    def generate(self, req: GenerationRequest) -> GenerationResult:
        if self.template is None:
            raise ComfyTemplateError("no workflow template selected")

        prompt_id = self._new_prompt_id()
        client_id = str(uuid.uuid4())
        graph = build_graph(
            self.template,
            values=self._values(req),
            models=self.model_slots,
            loras=self.loras,
        )

        socket = self._open_socket(client_id)
        try:
            self._post_json(
                f"{self.base_url}/prompt",
                {"prompt": graph, "client_id": client_id, "prompt_id": prompt_id},
            )
            images = self._await_images(socket, prompt_id)
        finally:
            try:
                socket.close()
            except Exception:  # noqa: BLE001 - 닫기 실패는 결과에 영향이 없다
                logger.debug("closing ComfyUI websocket failed", exc_info=True)

        return GenerationResult(raw_bytes=self._fetch_image(images[0]))

    def _values(self, req: GenerationRequest) -> dict:
        """``GenerationRequest`` → 슬롯 값. 템플릿이 모르는 키는 무시된다."""
        return {
            "positive": req.prompt,
            "negative": req.negative_prompt,
            "seed": req.seed,
            "steps": req.steps,
            "cfg": req.cfg_scale,
            "sampler": req.sampler,
            "scheduler": req.scheduler,
            "width": req.width,
            "height": req.height,
        }

    def _open_socket(self, client_id: str):
        """WS를 연다. **POST보다 먼저** 불러야 한다."""
        parsed = urlparse(self.base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        url = urlunparse((scheme, parsed.netloc, "/ws", "", f"clientId={client_id}", ""))
        try:
            socket = self._make_socket()
            socket.connect(url)
            return socket
        except Exception as exc:  # noqa: BLE001 - 소켓 라이브러리마다 예외가 다르다
            raise ComfyConnectionError(f"cannot open ComfyUI websocket at {self.base_url}: {exc}") from exc

    def _await_images(self, socket, prompt_id: str) -> tuple[dict, ...]:
        """executed를 기다린다. 소켓이 끊기면 /history를 1회 확인한다."""
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            if self._stop.is_set():
                self._interrupt()
                raise ComfyTimeoutError("generation stopped by user")
            try:
                frame = socket.recv()
            except Exception:  # noqa: BLE001 - 끊김은 정상 종료일 수도 있다
                break
            message = parse_message(frame, prompt_id)
            if isinstance(message, Progress):
                if self._on_progress is not None:
                    self._on_progress(message.value, message.max_value)
                continue
            if isinstance(message, ExecutionFailed):
                raise ComfyExecutionError(
                    message.message, node_id=message.node_id, node_type=message.node_type
                )
            if isinstance(message, Executed) and message.node == self.template.output_node:
                return message.images
        images = self._images_from_history(prompt_id)
        if images:
            return images
        raise ComfyTimeoutError(f"no image from ComfyUI within {self.timeout:.0f}s")

    def _images_from_history(self, prompt_id: str) -> tuple[dict, ...]:
        """소켓이 끊겼을 때의 폴백 — 1회만 확인한다."""
        try:
            history = self._get_json(f"{self.base_url}/history/{prompt_id}")
        except ComfyConnectionError:
            return ()
        entry = history.get(prompt_id) if isinstance(history, dict) else None
        outputs = entry.get("outputs") if isinstance(entry, dict) else None
        node = outputs.get(self.template.output_node) if isinstance(outputs, dict) else None
        images = node.get("images") if isinstance(node, dict) else None
        if isinstance(images, list) and images:
            return tuple(i for i in images if isinstance(i, dict))
        return ()

    def _interrupt(self) -> None:
        """서버가 큐에 든 작업을 계속 돌리지 않도록 끊는다."""
        try:
            self._post_json(f"{self.base_url}/interrupt", {})
        except (ComfyConnectionError, ComfyPromptRejectedError):
            logger.debug("interrupt failed", exc_info=True)

    def _fetch_image(self, image: dict) -> bytes:
        query = urlencode(
            {
                "filename": image.get("filename", ""),
                "subfolder": image.get("subfolder", ""),
                "type": image.get("type", "temp"),
            }
        )
        return self._get_bytes(f"{self.base_url}/view?{query}")
