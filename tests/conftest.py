"""공용 테스트 픽스처."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def bundled_db_path() -> Path:
    """앱 내장 Danbooru 태그 DB 경로."""
    import naiauto.core.tag_completer as tc

    return tc.bundled_database_path()