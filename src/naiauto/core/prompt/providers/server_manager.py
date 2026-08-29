"""llama-server 프로세스 자동 관리.

외부 llama-server를 쓸 때(openai_compatible provider) 앱이 바이너리를 직접
기동/종료한다. MTP draft 모델(-md) 등 llama-cpp-python 바인딩에 없는
gigatoken 서버 전용 옵션을 실행 인자로 그대로 전달할 수 있다.

- ``ensure_running()``: 포트가 이미 응답하면 기존 서버 재사용, 없으면 기동.
- ``close()``: 앱이 띄운 서버만 종료 (남의 서버는 건드리지 않는다).
Qt 의존성 없음.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
import time
from pathlib import Path

import requests

from ..errors import CompilerProviderUnavailableError

logger = logging.getLogger(__name__)

__all__ = ["LlamaServerManager"]

#: 기동 후 포트 응답 대기 간격 (초).
_POLL_INTERVAL = 0.5


class LlamaServerManager:
    """llama-server 바이너리를 자동 기동/종료하는 프로세스 관리자."""

    def __init__(
        self,
        *,
        server_path: str,
        args: str,
        base_url: str,
        startup_timeout: float = 30.0,
    ) -> None:
        self._server_path = server_path
        self._args = args
        self._base_url = base_url.rstrip("/")
        self._startup_timeout = startup_timeout
        self._proc: subprocess.Popen | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_running(self) -> None:
        """서버가 떠 있는지 확인하고, 없으면 기동한다.

        - 포트가 이미 응답 → 아무것도 하지 않음 (기존 서버 재사용).
        - 응답 없음 → ``server_path`` + ``args``로 Popen 기동 후 포트 폴링.
        - 기동 실패/타임아웃 → ``CompilerProviderUnavailableError``.
        """
        if self._is_alive():
            logger.info("llama-server already running at %s (reusing)", self._base_url)
            return
        self._start()

    def close(self) -> None:
        """앱이 직접 띄운 서버만 종료한다."""
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            logger.info("llama-server stopped (pid %s)", self._proc.pid)
        self._proc = None

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _is_alive(self) -> bool:
        """OpenAI 호환 /models 엔드포인트로 서버 생존을 확인한다."""
        try:
            resp = requests.get(f"{self._base_url}/models", timeout=3)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def _start(self) -> None:
        if not Path(self._server_path).exists():
            raise CompilerProviderUnavailableError(
                f"llama-server binary not found: {self._server_path} "
                "(옵션 → AI 프롬프트 → 서버 경로를 확인하세요)"
            )
        cmd = [self._server_path, *shlex.split(self._args)]
        logger.info("starting llama-server: %s", " ".join(cmd))
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise CompilerProviderUnavailableError(
                f"failed to start llama-server: {exc}"
            ) from exc

        deadline = time.monotonic() + self._startup_timeout
        while time.monotonic() < deadline:
            if self._is_alive():
                logger.info("llama-server ready (pid %s)", self._proc.pid)
                return
            if self._proc.poll() is not None:
                raise CompilerProviderUnavailableError(
                    "llama-server exited immediately — 실행 인자(server_args)를 확인하세요"
                )
            time.sleep(_POLL_INTERVAL)
        raise CompilerProviderUnavailableError(
            f"llama-server did not respond within {self._startup_timeout:.0f}s"
        )
