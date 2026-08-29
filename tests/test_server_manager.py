"""LlamaServerManager 테스트 — llama-server 자동 기동/종료."""

import subprocess

import pytest
import requests

from naiauto.core.prompt.errors import CompilerProviderUnavailableError
from naiauto.core.prompt.providers.server_manager import LlamaServerManager


class _FakeProc:
    def __init__(self):
        self.pid = 12345
        self.terminated = False
        self.waited = False

    def poll(self):
        return None if not self.terminated else 0

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True


def test_ensure_running_starts_server_when_port_down(monkeypatch, tmp_path):
    server = tmp_path / "llama-server"
    server.write_bytes(b"#!/bin/sh\nexit 0")
    server.chmod(0o755)

    procs = []

    class _OkResponse:
        status_code = 200

    def fake_get(*a, **kw):
        # 서버가 아직 안 떠 있으면 실패, Popen 후에는 성공
        if procs:
            return _OkResponse()
        raise requests.ConnectionError("refused")

    def fake_popen(cmd, **kw):
        procs.append(cmd)
        return _FakeProc()

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    m = LlamaServerManager(
        server_path=str(server),
        args="-m model.gguf -ncmoe 22",
        base_url="http://127.0.0.1:7999/v1",
        startup_timeout=5,
    )
    m.ensure_running()
    assert len(procs) == 1
    assert procs[0][0] == str(server)
    assert "-ncmoe" in procs[0]
    assert m._proc is not None


def test_ensure_running_reuses_existing_server(monkeypatch, tmp_path):
    server = tmp_path / "llama-server"
    server.write_bytes(b"x")
    server.chmod(0o755)

    calls = {"get": 0}

    class _OkResponse:
        status_code = 200

    def fake_get(*a, **kw):
        calls["get"] += 1
        return _OkResponse()

    def fake_popen(cmd, **kw):
        raise AssertionError("server should not be started")

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    m = LlamaServerManager(
        server_path=str(server),
        args="",
        base_url="http://127.0.0.1:7999/v1",
        startup_timeout=5,
    )
    m.ensure_running()
    assert m._proc is None  # 기존 서버 재사용 — 직접 띄우지 않음
    assert calls["get"] >= 1


def test_ensure_running_missing_binary_raises(monkeypatch, tmp_path):
    def fake_get(*a, **kw):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(requests, "get", fake_get)

    m = LlamaServerManager(
        server_path=str(tmp_path / "nope"),
        args="",
        base_url="http://127.0.0.1:7999/v1",
        startup_timeout=3,
    )
    with pytest.raises(CompilerProviderUnavailableError, match="llama-server"):
        m.ensure_running()


def test_close_terminates_started_server(monkeypatch, tmp_path):
    server = tmp_path / "llama-server"
    server.write_bytes(b"x")
    server.chmod(0o755)

    def fake_get(*a, **kw):
        raise requests.ConnectionError("refused")

    proc = _FakeProc()
    procs = []

    class _OkResponse:
        status_code = 200

    def fake_get_after_start(*a, **kw):
        # Popen 후에는 응답 — _start 폴링이 성공으로 끝나도록
        if proc.terminated is False and procs:
            return _OkResponse()
        raise requests.ConnectionError("refused")

    def fake_popen(cmd, **kw):
        procs.append(cmd)
        return proc

    monkeypatch.setattr(requests, "get", fake_get_after_start)
    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    m = LlamaServerManager(
        server_path=str(server),
        args="",
        base_url="http://127.0.0.1:7999/v1",
        startup_timeout=1,
    )
    m.ensure_running()
    m.close()
    assert proc.terminated is True
    assert proc.waited is True


def test_close_without_started_server_is_noop():
    m = LlamaServerManager(server_path="", args="", base_url="http://x/v1")
    m.close()  # 예외 없음
