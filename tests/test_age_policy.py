from matricaria.validator.age_policy import check_action
from matricaria.world.body import Body, BodyChange

ADULT = Body(30, 175, 70)
CHILD = Body(10, 140, 32)
TEEN = Body(16, 168, 55)


def test_adults_have_no_age_limits():
    assert check_action("some_future_action", [ADULT, ADULT]).allowed
    assert check_action("body_change", [ADULT], BodyChange(weight_kg=10)).allowed


def test_talking_with_minors_is_allowed():
    for action in ("relation_change", "remember", "call", "give_item"):
        assert check_action(action, [ADULT, CHILD]).allowed


def test_unknown_actions_are_denied_with_minors():
    assert not check_action("some_future_action", [ADULT, CHILD]).allowed
    assert not check_action("some_future_action", [TEEN]).allowed


def test_minor_height_can_change():
    assert check_action("body_change", [CHILD], BodyChange(height_cm=5)).allowed
    assert check_action("body_change", [TEEN], BodyChange(age_years=1, height_cm=3)).allowed


def test_minor_weight_cannot_change():
    result = check_action("body_change", [CHILD], BodyChange(weight_kg=5))
    assert not result.allowed
    assert "weight_kg" in result.reason


def test_minor_chest_cannot_change():
    assert not check_action("body_change", [TEEN], BodyChange(chest=1)).allowed
    assert check_action("body_change", [ADULT], BodyChange(chest=1)).allowed


def test_minor_can_grow_tall():
    assert check_action("body_change", [CHILD], BodyChange(height_cm=100)).allowed
