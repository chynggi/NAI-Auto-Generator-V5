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


def test_short_bob_hair_maps_bob_to_bob_cut(resolver):
    # 규칙 3: "short bob hair" → short_hair + bob_cut (bob 특수 매핑)
    refs = resolver.resolve_phrase("short bob hair")
    tags = {r.tag for r in refs}
    assert {"short_hair", "bob_cut"} <= tags
    assert all(r.status == "verified" for r in refs)


def test_partial_compound_keeps_unresolved_word(resolver):
    # [review #7] "long zzz hair" — long_hair는 verified, 실패한 단어는 조용히
    # 사라지지 않고 원문 전체의 unresolved ref로 끝에 붙는다
    refs = resolver.resolve_phrase("long zzz hair")
    assert any(r.tag == "long_hair" and r.status == "verified" for r in refs)
    assert refs[-1].tag == "long_zzz_hair"
    assert refs[-1].status == "unresolved"
    assert refs[-1].post_count == 0


def test_default_path_uses_bundled_database():
    # database_path=None → 내장 DB (동봉 22K + 보조 4)를 그대로 로드한다
    r = TagResolver()
    assert r.load() is True
    assert r.is_enabled is True
    assert r.tag_count > 20000
    assert r.resolve_phrase("silver hair")[0].tag == "grey_hair"


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


def test_parenthesized_character_tag_resolves(resolver):
    # [debug-fix] 정규화가 괄호를 제거해 "hiyori_(blue_archive)"가 깨지던 버그 —
    # 괄호는 캐릭터/시리즈 태그명의 일부이므로 보존해야 한다.
    refs = resolver.resolve_phrase("hiyori_(blue_archive)")
    assert any(r.tag == "hiyori_(blue_archive)" and r.status == "verified" for r in refs)


def test_parenthesized_character_tag_with_spaces_resolves(resolver):
    # 사람이 쓴 형태("hiyori (blue archive)")도 괄호 보존 정규화로 매칭
    refs = resolver.resolve_phrase("hiyori (blue archive)")
    assert any(r.tag == "hiyori_(blue_archive)" and r.status == "verified" for r in refs)


def test_indoor_aliases_to_indoors(resolver):
    # Danbooru canonical은 indoors — indoor는 존재하지 않는 형태
    refs = resolver.resolve_phrase("indoor")
    assert refs[0].tag == "indoors"
    assert refs[0].status == "verified"
    assert refs[0].post_count > 0


def test_farting_aliases_to_fart(resolver):
    # Danbooru에서 farting → fart로 병합됨
    refs = resolver.resolve_phrase("farting")
    assert refs[0].tag == "fart"
    assert refs[0].status == "verified"


def test_flatulence_aliases_to_fart(resolver):
    # Danbooru에 flatulence 태그는 없다 (전체 태그 스냅샷 확인) — LLM 습관 단어
    refs = resolver.resolve_phrase("flatulence")
    assert refs[0].tag == "fart"
    assert refs[0].status == "verified"
    assert refs[0].post_count > 0


def test_back_view_aliases_to_from_behind(resolver):
    # back_view는 deprecated — from_behind가 canonical (Danbooru 공식 alias 확인)
    refs = resolver.resolve_phrase("back_view")
    assert refs[0].tag == "from_behind"
    assert refs[0].status == "verified"


def test_hand_on_buttocks_aliases_to_hand_on_own_ass(resolver):
    # LLM이 흔히 쓰는 형태 — Danbooru canonical은 hand_on_own_ass (CSV 보강됨)
    refs = resolver.resolve_phrase("hand_on_buttocks")
    assert refs[0].tag == "hand_on_own_ass"
    assert refs[0].status == "verified"
    assert refs[0].post_count > 0


def test_bundled_alias_file_loaded(resolver):
    # 동봉 danbooru_aliases.csv (공식 alias 5만+)가 로드되어 상수 ALIASES에 병합된다
    refs = resolver.resolve_phrase("hand_on_waist")
    assert refs[0].tag == "hand_on_own_hip"
    assert refs[0].status == "verified"


def test_bundled_alias_covers_canonical_spelling(resolver):
    # blond_hair → blonde_hair는 공식 alias에도 존재 (상수와 중복 허용)
    refs = resolver.resolve_phrase("blond_hair")
    assert refs[0].tag == "blonde_hair"
    assert refs[0].status == "verified"


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
