import pytest

from matricaria.world.body import (
    AgeStage, Body, BodyChange, BodyChangeError, Build, apply_change, portrait_is_stale,
)


def test_stages():
    assert Body(8, 128, 26).stage is AgeStage.CHILD
    assert Body(15, 165, 55).stage is AgeStage.TEEN
    assert Body(18, 170, 60).stage is AgeStage.ADULT
    assert Body(17, 170, 60).is_minor
    assert not Body(18, 170, 60).is_minor


def test_weight_gain_changes_build_and_portrait():
    before = Body(25, 170, 62)
    after = apply_change(before, BodyChange(weight_kg=30))
    assert before.build is Build.AVERAGE
    assert after.build is Build.HEAVY
    assert after.weight_kg == 92
    assert before.weight_kg == 62  # старое тело не меняется
    assert portrait_is_stale(before, after)
    assert after.sprite_params()["scale_x"] > before.sprite_params()["scale_x"]


def test_growth_scales_sprite_height():
    before = Body(25, 160, 60)
    after = apply_change(before, BodyChange(height_cm=20))
    assert after.height_cm == 180
    assert after.sprite_params()["scale_y"] > before.sprite_params()["scale_y"]


def test_sprite_scale_is_clamped():
    assert Body(30, 250, 150).sprite_params()["scale_y"] == 1.3
    assert Body(1, 60, 7).sprite_params()["scale_y"] == 0.5


@pytest.mark.parametrize("change", [
    BodyChange(height_cm=31),
    BodyChange(weight_kg=-41),
    BodyChange(age_years=-1),
])
def test_step_limits(change):
    with pytest.raises(BodyChangeError):
        apply_change(Body(25, 170, 60), change)


def test_absolute_limits():
    with pytest.raises(BodyChangeError):
        apply_change(Body(25, 240, 60), BodyChange(height_cm=20))


def test_round_trip():
    body = Body(12, 150.5, 40)
    assert Body.from_dict(body.to_dict()) == body
