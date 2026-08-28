from naiauto.core.prompt.relationship import (
    RELATION_ACTIONS,
    normalize_action,
    normalize_relationships,
)
from naiauto.core.prompt.schema import LLMRelationshipModel


def test_synonyms_normalize():
    assert normalize_action("staring at") == "looking_at"
    assert normalize_action("chatting with") == "talking_to"
    assert normalize_action("conversing with") == "talking_to"
    assert normalize_action("face to face") == "facing"
    assert normalize_action("embracing") == "hugging"


def test_unknown_action_none():
    assert normalize_action("quantum entangling") is None


def test_whitespace_and_case_normalized():
    assert normalize_action("  Looking At  ") == "looking_at"


def test_mutual_expands_to_both_directions():
    rels, warns = normalize_relationships(
        [LLMRelationshipModel(source="c1", target="c2", action="facing", mutual=True)],
        {"c1", "c2"},
    )
    assert len(rels) == 2
    assert (rels[0].source, rels[0].target, rels[0].mutual) == ("c1", "c2", True)
    assert (rels[1].source, rels[1].target, rels[1].mutual) == ("c2", "c1", True)
    assert warns == []


def test_one_way_single_entry():
    rels, warns = normalize_relationships(
        [LLMRelationshipModel(source="c1", target="c2", action="looking_at")],
        {"c1", "c2"},
    )
    assert len(rels) == 1
    assert not rels[0].mutual


def test_unknown_character_id_warns_and_drops():
    rels, warns = normalize_relationships(
        [LLMRelationshipModel(source="c9", target="c2", action="looking_at")],
        {"c1", "c2"},
    )
    assert rels == []
    assert len(warns) == 1


def test_unknown_action_warns_and_drops():
    rels, warns = normalize_relationships(
        [LLMRelationshipModel(source="c1", target="c2", action="teleporting")],
        {"c1", "c2"},
    )
    assert rels == []
    assert len(warns) == 1


def test_all_actions_are_snake_case():
    assert all(" " not in a for a in RELATION_ACTIONS)
