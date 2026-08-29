"""최근 입력 히스토리 — 사용자가 입력한 자연어 기록 (디스크 영속).

LLM "출력" 캐싱과 달리 **입력 스냅샷만** 저장한다. 다이얼로그에서 최근
입력 목록을 보여주고 재선택/재실행하기 위한 용도다. LLM 호출을 건너뛰지
않는다 — 같은 입력을 다시 실행하면 항상 새로 추론한다.

- 동일 입력(탭/본문/기존 프롬프트/지시문/모드 동일)은 중복 없이 맨 앞으로.
- ``max_entries`` 초과 시 가장 오래된 항목부터 제거.
- 손상/누락 파일 → 빈 상태, 쓰기는 원자적(tmp + replace).
Qt 의존성 없음 — core 레이어에서 UI 없이 import 가능해야 한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import platformdirs

from naiauto.core.settings.schema import APP_NAME

logger = logging.getLogger(__name__)

__all__ = ["InputHistoryEntry", "PromptInputHistory", "default_history_path"]

_VERSION = 1

#: 기본 히스토리 파일 이름 (user_data_dir 아래).
_HISTORY_FILENAME = "prompt_input_history.json"


def default_history_path() -> Path:
    """기본 히스토리 파일 경로 — {user_data_dir}/prompt_input_history.json."""
    return Path(platformdirs.user_data_dir(APP_NAME)) / _HISTORY_FILENAME


@dataclass(frozen=True)
class InputHistoryEntry:
    """변환 다이얼로그 입력 스냅샷.

    - ``tab=="create"``: ``text`` + ``mode``
    - ``tab=="modify"``: ``existing_prompt`` + ``instruction`` + ``mode``
    """

    tab: str  # "create" | "modify"
    text: str = ""              # create 탭 자연어 (modify면 빈 문자열)
    existing_prompt: str = ""   # modify 탭 기존 프롬프트 (create면 빈 문자열)
    instruction: str = ""       # modify 탭 지시문 (create면 빈 문자열)
    mode: str = "hybrid"        # tag | hybrid | natural
    ts: float = 0.0             # epoch 초 (표시/정렬 용도)


class PromptInputHistory:
    """최근 입력 히스토리 — 최신순 목록, 디스크 영속."""
    _FIELDS = ("tab", "text", "existing_prompt", "instruction", "mode")

    def __init__(self, path: Path, max_entries: int = 20) -> None:
        self._path = path
        self._max_entries = max(1, max_entries)
        self._entries: list[InputHistoryEntry] = []

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def add(self, entry: InputHistoryEntry) -> None:
        """입력 저장 — 동일 입력은 중복 없이 맨 앞, 초과분 제거 후 기록."""
        self._entries = [e for e in self._entries if tuple(getattr(e, f) for f in self._FIELDS) != tuple(getattr(entry, f) for f in self._FIELDS)]
        self._entries.insert(0, entry)
        del self._entries[self._max_entries :]
        self.save()

    def recent(self) -> list[InputHistoryEntry]:
        """최신순 입력 목록 (복사본)."""
        return list(self._entries)

    def load(self) -> None:
        """디스크에서 읽는다. 누락/손상 → 빈 목록 (예외 없음)."""
        self._entries = []
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            logger.warning("prompt input history broken, starting empty: %s", self._path)
            return
        raw_entries = data.get("entries") if isinstance(data, dict) else None
        if not isinstance(raw_entries, list):
            return
        for item in raw_entries:
            if not isinstance(item, dict):
                continue
            try:
                self._entries.append(
                    InputHistoryEntry(
                        tab=str(item["tab"]),
                        text=str(item.get("text", "")),
                        existing_prompt=str(item.get("existing_prompt", "")),
                        instruction=str(item.get("instruction", "")),
                        mode=str(item.get("mode", "hybrid")),
                        ts=float(item.get("ts", 0.0)),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

    def save(self) -> None:
        """원자적 쓰기(tmp + replace). 실패는 치명적이지 않다."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(
                    {"version": _VERSION, "entries": [asdict(e) for e in self._entries]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except OSError as e:
            logger.warning("cannot write prompt input history: %s", e)

    @property
    def path(self) -> Path:
        return self._path
