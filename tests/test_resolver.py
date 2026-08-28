import pytest

from naiauto.core.prompt.resolver import TagResolver


@pytest.fixture()
def resolver(bundled_db_path):
    r = TagResolver(database_path=bundled_db_path)
    assert r.load()
    return r


def test_silver_hair_aliases_to_grey_hair(resolver):
    # [Ruling #5] Danbooru에서 silver_hair는 deprecated — grey_hair가 canonical
    refs = resolver.resolve_phrase("silver hair")
    assert len(refs) == 1
    assert refs[0].tag == "grey_hair"
    assert refs[0].status == "verified"
    assert refs[0].post_count > 0


def test_underscore_input_ok(resolver):
    refs = resolver.resolve_phrase("silver_hair")
    assert refs[0].tag == "grey_hair"


def test_capitalized_and_punctuated(resolver):
    refs = resolver.resolve_phrase("Silver Hair,")
    assert refs[0].tag == "grey_hair"


def test_blond_hair_aliases_to_blonde_hair(resolver):
    # [Ruling #5] canonical 철자는 blonde_hair
    refs = resolver.resolve_phrase("blond hair")
    assert refs[0].tag == "blonde_hair"
    assert refs[0].status == "verified"


def test_long_black_hair_splits_into_parts(resolver):
    refs = resolver.resolve_phrase("long black hair")
    tags = {r.tag for r in refs}
    assert {"long_hair", "black_hair"} <= tags
    assert all(r.status == "verified" for r in refs)


def test_haired_variant_rule(resolver):
    refs = resolver.resolve_phrase("silver-haired")
    assert refs[0].tag == "grey_hair"
    assert refs[0].status == "verified"


def test_eyed_variant_rule(resolver):
    refs = resolver.resolve_phrase("red-eyed")
    assert any(r.tag == "red_eyes" and r.status == "verified" for r in refs)


def test_underscore_compound_splits_into_tokens(resolver):
    # [Ruling #5] "wet_road" → wet + road (둘 다 DB에 존재)
    refs = resolver.resolve_phrase("wet_road")
    tags = {r.tag for r in refs}
    assert {"wet", "road"} <= tags
    assert all(r.status == "verified" for r in refs)


def test_nai_negative_vocabulary_verified(resolver):
    # [Ruling #5] 보조 파일(danbooru_tags_extra.csv)의 NAI UC 어휘
    refs = resolver.resolve_phrase("text")
    assert refs[0].tag == "text"
    assert refs[0].status == "verified"


def test_nonexistent_tag_is_unresolved(resolver):
    refs = resolver.resolve_phrase("cinematic melancholic atmosphere")
    assert len(refs) == 1
    assert refs[0].status == "unresolved"
    assert refs[0].tag == "cinematic_melancholic_atmosphere"
    assert refs[0].post_count == 0


def test_empty_phrase_unresolved(resolver):
    refs = resolver.resolve_phrase("")
    assert refs[0].status == "unresolved"


def test_unknown_single_token_not_splittable(resolver):
    # DB에 없는 조합인데 토큰 분해도 불가하면 unresolved
    refs = resolver.resolve_phrase("zzzqqq")
    assert refs[0].status == "unresolved"


def test_hyphenated_db_tag_resolves_directly(resolver):
    # 하이픈 보존 정규화: DB의 "two-tone_hair"가 그대로 매칭되어야 한다
    refs = resolver.resolve_phrase("two-tone hair")
    assert any(r.tag == "two-tone_hair" and r.status == "verified" for r in refs)


def test_haired_rule_still_works_with_hyphen_norm(resolver):
    # 규칙 2 경로 (하이픈→언더스코어 norm)가 여전히 동작
    refs = resolver.resolve_phrase("silver-haired")
    assert refs[0].tag == "grey_hair"
    assert refs[0].status == "verified"


def test_resolver_disabled_when_db_missing(tmp_path):
    # 메인 DB 로드 실패 시 보조 파일도 적용하지 않는다 (Ruling #5)
    r = TagResolver(database_path=tmp_path / "nope.csv")
    assert r.load() is False
    assert r.is_enabled is False
    assert r.resolve_phrase("silver hair")[0].status == "unresolved"  # 폴백 동작
