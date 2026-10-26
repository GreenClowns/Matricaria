import pytest

from matricaria.world.body import (
    AgeStage, Body, BodyChange, BodyChangeError, Build, SizeClass, apply_change, portrait_is_stale,
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


def test_growth_potion_makes_a_giant_step_by_step():
    body = Body(25, 170, 62)
    for _ in range(4):  # каждое действие — не больше чем вдвое
        body = apply_change(body, BodyChange(height_cm=body.height_cm))
    assert body.height_cm == 2720
    assert body.weight_kg > 100_000
    assert body.size_class is SizeClass.COLOSSAL
    assert body.build is Build.AVERAGE  # вес вырос вместе с ростом, сложение то же
    assert body.sprite_params()["scale_y"] == 6.0
    assert body.sprite_params()["framing"] == "legs_only"
    assert "colossal giant" in body.portrait_tags()


def test_shrinking_to_fairy_size():
    body = apply_change(Body(25, 160, 55), BodyChange(height_cm=-80))
    body = apply_change(body, BodyChange(height_cm=-40))
    assert body.size_class is SizeClass.TINY
    assert body.build is Build.AVERAGE
    assert body.sprite_params()["scale_y"] == 0.25


def test_growth_without_keep_build_makes_thin():
    body = apply_change(Body(25, 170, 62), BodyChange(height_cm=170, keep_build=False))
    assert body.weight_kg == 62
    assert body.build is Build.THIN


@pytest.mark.parametrize("change", [
    BodyChange(height_cm=171),   # больше чем вдвое
    BodyChange(height_cm=-86),   # меньше чем вдвое
    BodyChange(weight_kg=61),
    BodyChange(age_years=-1),
    BodyChange(age_years=5),
    BodyChange(chest=3),
])
def test_step_limits(change):
    with pytest.raises(BodyChangeError):
        apply_change(Body(25, 170, 60), change)


def test_absolute_limits():
    with pytest.raises(BodyChangeError):
        apply_change(Body(25, 2000, 50_000), BodyChange(height_cm=1500))


def test_chest_growth_for_adults():
    before = Body(22, 165, 55, chest=2)
    after = apply_change(before, BodyChange(chest=2))
    assert after.chest == 4
    assert "very large chest" in after.portrait_tags()
    assert portrait_is_stale(before, after)
    with pytest.raises(BodyChangeError):
        apply_change(after, BodyChange(chest=2))  # больше 5 нельзя


def test_minors_have_no_chest_size():
    with pytest.raises(BodyChangeError):
        Body(16, 160, 50, chest=1)
    with pytest.raises(BodyChangeError):
        apply_change(Body(16, 160, 50), BodyChange(chest=1))


def test_round_trip():
    body = Body(30, 150.5, 40, chest=3)
    assert Body.from_dict(body.to_dict()) == body
    assert Body.from_dict({"age_years": 12, "height_cm": 150, "weight_kg": 40}).chest == 0
