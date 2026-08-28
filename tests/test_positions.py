from naiauto.core.prompt.positions import (
    X_HINTS,
    estimate_position,
    estimate_positions,
)
from naiauto.core.prompt.schema import CharacterPrompt


def test_left_right_center():
    assert estimate_position("left") == (X_HINTS["left"], 0.5)
    assert estimate_position("right") == (X_HINTS["right"], 0.5)
    assert estimate_position("center") == (X_HINTS["center"], 0.5)


def test_spec_example_coordinates():
    assert estimate_position("left") == (0.30, 0.50)
    assert estimate_position("right") == (0.70, 0.50)


def test_far_left_far_right():
    assert estimate_position("far_left") == (0.15, 0.50)
    assert estimate_position("far_right") == (0.85, 0.50)


def test_vertical_combined():
    assert estimate_position("left bottom") == (0.30, 0.70)
    assert estimate_position("center top") == (0.50, 0.30)


def test_unknown_hint_returns_none():
    assert estimate_position("") is None
    assert estimate_position("somewhere") is None
    assert estimate_position("left somewhere") is None


def test_estimate_positions_assigns_only_known():
    chars = (
        CharacterPrompt(id="c1", position_hint="left", center_x=None, center_y=None),
        CharacterPrompt(id="c2", position_hint="right", center_x=None, center_y=None),
        CharacterPrompt(id="c3", position_hint="", center_x=None, center_y=None),
    )
    out = estimate_positions(chars)
    assert out[0].center_x == 0.30 and out[0].center_y == 0.50
    assert out[1].center_x == 0.70 and out[1].center_y == 0.50
    assert out[2].center_x is None and out[2].center_y is None
