"""TagRetriever 단위 테스트 — 자연어 키워드 → 태그 DB 후보 검색 (RAG).

검색 규칙: 토큰별 정확/접두사/substring/4글자 근사 매칭, post_count 정렬.
"""

import pytest

from naiauto.core.prompt.retriever import TagRetriever


@pytest.fixture()
def retriever(bundled_db_path):
    r = TagRetriever(database_path=bundled_db_path)
    assert r.load()
    return r


def test_search_exact_match_first(retriever):
    tags = retriever.search("night", limit=5)
    assert tags[0] == "night"


def test_search_returns_substring_and_approx_matches(retriever):
    tags = retriever.search("a rainy alley at night", limit=30)
    assert "rain" in tags  # "rainy" → 4글자 근사 접두사("rain")
    assert "alley" in tags
    assert "night" in tags


def test_search_compound_word_prefix_approx(retriever):
    # "schoolgirl" → "scho" 접두사 근사로 school_uniform이 후보에 오른다
    tags = retriever.search("schoolgirl in a classroom", limit=30)
    assert "school_uniform" in tags
    assert "classroom" in tags


def test_search_respects_limit(retriever):
    tags = retriever.search("girl", limit=3)
    assert len(tags) == 3


def test_search_returns_empty_for_no_keywords(retriever):
    assert retriever.search("") == ()
    assert retriever.search("   ") == ()
    assert retriever.search("은발 소녀") == ()  # 영문 키워드만 대상


def test_search_ignores_stopwords(retriever):
    assert retriever.search("the a of at in on") == ()


def test_search_disabled_when_db_missing(tmp_path):
    r = TagRetriever(database_path=tmp_path / "nope.csv")
    assert r.load() is False
    assert r.search("rainy alley") == ()
