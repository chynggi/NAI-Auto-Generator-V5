"""PromptInputHistory 단위 테스트 — 최근 입력 히스토리 (디스크 영속)."""
from naiauto.core.prompt.history import InputHistoryEntry, PromptInputHistory


def _entry(**kw):
    base = dict(tab="create", text="두 소녀가 카페에 있다", existing_prompt="", instruction="", mode="hybrid", ts=100.0)
    base.update(kw)
    return InputHistoryEntry(**base)


def test_recent_returns_most_recent_first(tmp_path):
    hist = PromptInputHistory(path=tmp_path / "h.json")
    hist.add(_entry(text="a", ts=1.0))
    hist.add(_entry(text="b", ts=2.0))
    assert [e.text for e in hist.recent()] == ["b", "a"]


def test_add_dedupes_exact_input_and_moves_to_front(tmp_path):
    hist = PromptInputHistory(path=tmp_path / "h.json")
    hist.add(_entry(text="a", ts=1.0))
    hist.add(_entry(text="b", ts=2.0))
    hist.add(_entry(text="a", ts=3.0))  # 동일 입력 — 중복 제거 + 맨 앞
    assert [e.text for e in hist.recent()] == ["a", "b"]


def test_different_mode_is_distinct_input(tmp_path):
    hist = PromptInputHistory(path=tmp_path / "h.json")
    hist.add(_entry(text="a", mode="tag", ts=1.0))
    hist.add(_entry(text="a", mode="hybrid", ts=2.0))
    assert len(hist.recent()) == 2


def test_modify_entry_distinct_from_create(tmp_path):
    hist = PromptInputHistory(path=tmp_path / "h.json")
    hist.add(_entry(tab="modify", existing_prompt="1girl, cafe", instruction="배경을 밤으로", ts=1.0))
    hist.add(_entry(text="1girl, cafe", ts=2.0))
    assert len(hist.recent()) == 2


def test_cap_evicts_oldest(tmp_path):
    hist = PromptInputHistory(path=tmp_path / "h.json", max_entries=2)
    hist.add(_entry(text="a", ts=1.0))
    hist.add(_entry(text="b", ts=2.0))
    hist.add(_entry(text="c", ts=3.0))
    assert [e.text for e in hist.recent()] == ["c", "b"]


def test_persists_to_disk(tmp_path):
    path = tmp_path / "h.json"
    hist = PromptInputHistory(path=path)
    hist.add(_entry(text="a", ts=1.0))
    hist.add(_entry(text="b", ts=2.0))

    reloaded = PromptInputHistory(path=path)
    reloaded.load()
    assert [e.text for e in reloaded.recent()] == ["b", "a"]


def test_add_after_reload_persists(tmp_path):
    path = tmp_path / "h.json"
    PromptInputHistory(path=path).add(_entry(text="a", ts=1.0))
    hist = PromptInputHistory(path=path)
    hist.load()
    hist.add(_entry(text="b", ts=2.0))

    reloaded = PromptInputHistory(path=path)
    reloaded.load()
    assert [e.text for e in reloaded.recent()] == ["b", "a"]


def test_malformed_file_loads_empty(tmp_path):
    path = tmp_path / "h.json"
    path.write_text("not json {{{", encoding="utf-8")
    hist = PromptInputHistory(path=path)
    hist.load()  # 예외 없이 빈 상태
    assert hist.recent() == []


def test_missing_file_loads_empty(tmp_path):
    hist = PromptInputHistory(path=tmp_path / "missing.json")
    hist.load()
    assert hist.recent() == []
