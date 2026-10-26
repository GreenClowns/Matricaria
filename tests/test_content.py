from matricaria.art.style import portrait_prompt
from matricaria.content import ContentSettings, ModelInfo, decide
from matricaria.validator.age_policy import check_action
from matricaria.world.body import Body

ON = ContentSettings(adult_content=True, user_confirmed_adult=True)
OPEN_MODEL = ModelInfo("open", allows_explicit=True)
SAFE_MODEL = ModelInfo("safe", allows_explicit=False)
WOMAN = Body(24, 168, 60, {"chest": 3})
GIANT = Body(30, 60_000, 2e9, {"chest": 2})
TEEN = Body(17, 165, 52)
SHORT_ADULT = Body(25, 125, 30)


def test_off_by_default():
    assert not decide(None, OPEN_MODEL, [WOMAN]).explicit
    assert not decide(ContentSettings(), OPEN_MODEL, [WOMAN]).explicit


def test_needs_every_condition():
    assert decide(ON, OPEN_MODEL, [WOMAN, GIANT]).explicit
    assert not decide(ContentSettings(adult_content=True), OPEN_MODEL, [WOMAN]).explicit
    assert not decide(ON, SAFE_MODEL, [WOMAN]).explicit
    assert not decide(ON, None, [WOMAN]).explicit


def test_never_with_minors():
    assert not decide(ON, OPEN_MODEL, [WOMAN, TEEN]).explicit
    assert not decide(ON, OPEN_MODEL, [TEEN]).explicit


def test_short_adult_is_adult():
    assert decide(ON, OPEN_MODEL, [SHORT_ADULT]).explicit
    prompt = portrait_prompt({}, SHORT_ADULT, settings=ON, model=OPEN_MODEL)
    assert "adult face" in prompt["prompt"] and "child" in prompt["negative_prompt"]


def test_explicit_action_gate():
    assert check_action("intimate", [WOMAN, GIANT], settings=ON, model=OPEN_MODEL).allowed
    assert not check_action("intimate", [WOMAN, GIANT]).allowed
    assert not check_action("intimate", [WOMAN, TEEN], settings=ON, model=OPEN_MODEL).allowed


def test_portrait_shows_proportions_safe_mode():
    prompt = portrait_prompt({}, WOMAN)
    assert "huge breasts" in prompt["prompt"]
    assert "fully clothed" in prompt["prompt"] and "nsfw" in prompt["negative_prompt"]
    assert not prompt["explicit"]
    assert "titan" in portrait_prompt({}, GIANT)["prompt"]


def test_portrait_explicit_when_allowed():
    prompt = portrait_prompt({}, WOMAN, settings=ON, model=OPEN_MODEL, nude=True)
    assert prompt["explicit"]
    assert "nude" in prompt["prompt"] and "fully clothed" not in prompt["prompt"]
    assert "child" in prompt["negative_prompt"]


def test_nude_request_ignored_when_not_allowed():
    prompt = portrait_prompt({}, TEEN, settings=ON, model=OPEN_MODEL, nude=True)
    assert not prompt["explicit"]
    assert "nude" not in prompt["prompt"]
    assert "nude" in prompt["negative_prompt"] and "sexualized" in prompt["negative_prompt"]
