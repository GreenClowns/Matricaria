import pytest

from matricaria.world.body import (
    UNLIMITED, AgeStage, Body, BodyChange, BodyChangeError, Build, SizeClass,
    apply_change, portrait_is_stale, rules_for,
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


def test_ai_growth_goes_step_by_step():
    body = Body(25, 170, 62)
    for _ in range(4):  # ИИ за одно действие меняет рост не больше чем вдвое
        body = apply_change(body, BodyChange(height_cm=body.height_cm), rules_for("ai"))
    assert body.height_cm == 2720
    assert body.size_class is SizeClass.COLOSSAL
    assert body.build is Build.AVERAGE  # вес вырос вместе с ростом, сложение то же
    with pytest.raises(BodyChangeError):
        apply_change(body, BodyChange(height_cm=body.height_cm * 2), rules_for("ai"))


def test_player_has_no_limits():
    assert rules_for("player") is UNLIMITED
    assert rules_for("ai", ai_limits=False) is UNLIMITED
    body = apply_change(Body(25, 170, 62), BodyChange(height_cm=1e9), rules_for("player"))
    assert body.size_class is SizeClass.WORLD
    assert body.build is Build.AVERAGE
    assert body.sprite_params()["scale_y"] == 6.0
    tiny = apply_change(Body(25, 170, 62), BodyChange(height_cm=-169.99), UNLIMITED)
    assert tiny.height_cm == pytest.approx(0.01)
    assert tiny.size_class is SizeClass.MICRO


def test_growth_without_keep_build_makes_thin():
    body = apply_change(Body(25, 170, 62), BodyChange(height_cm=170, keep_build=False))
    assert body.weight_kg == 62
    assert body.build is Build.THIN


def test_parts_grow_without_upper_limit():
    body = Body(24, 165, 55)
    for _ in range(10):
        body = apply_change(body, BodyChange(parts={"chest": 1000}), UNLIMITED)
    assert body.part("chest") == 10_000
    tags = body.portrait_tags()
    assert "gigantic breasts" in tags and "breasts larger than buildings" in tags
    assert "curvy" in tags


def test_part_levels_in_tags():
    assert "large breasts" in Body(24, 165, 55, {"chest": 1}).portrait_tags()
    assert "huge breasts" in Body(24, 165, 55, {"chest": 3}).portrait_tags()
    assert "small breasts" in Body(24, 165, 55, {"chest": -1}).portrait_tags()
    assert "very long hair" in Body(10, 140, 32, {"hair": 2}).portrait_tags()


@pytest.mark.parametrize("change", [
    BodyChange(height_cm=171),
    BodyChange(height_cm=-86),
    BodyChange(weight_kg=61),
    BodyChange(parts={"chest": 3}),
])
def test_ai_step_limits(change):
    with pytest.raises(BodyChangeError):
        apply_change(Body(25, 170, 60), change, rules_for("ai"))
    apply_change(Body(25, 170, 60), change, UNLIMITED)  # игроку можно


@pytest.mark.parametrize("change", [BodyChange(age_years=-1), BodyChange(age_years=5)])
def test_age_step_always_limited(change):
    with pytest.raises(BodyChangeError):
        apply_change(Body(25, 170, 60), change, UNLIMITED)


def test_only_physical_limits():
    with pytest.raises(BodyChangeError):
        apply_change(Body(25, 170, 60), BodyChange(height_cm=-170), UNLIMITED)
    with pytest.raises(BodyChangeError):
        Body(25, 170, 60, {"wings": 1})
    with pytest.raises(BodyChangeError):
        Body(25, 170, 60, {"chest": -4})


def test_minors_parts():
    with pytest.raises(BodyChangeError):
        Body(16, 160, 50, {"chest": 1})
    with pytest.raises(BodyChangeError):
        apply_change(Body(16, 160, 50), BodyChange(parts={"hips": 1}), UNLIMITED)
    assert apply_change(Body(9, 130, 28), BodyChange(parts={"hair": 2})).part("hair") == 2


def test_round_trip_and_old_format():
    body = Body(30, 150.5, 40, {"chest": 3.0})
    assert Body.from_dict(body.to_dict()) == body
    assert Body.from_dict({"age_years": 22, "height_cm": 165, "weight_kg": 55, "chest": 4}).part("chest") == 2
