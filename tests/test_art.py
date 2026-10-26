import pytest

from matricaria.art.style import FACESET, HIBIT, portrait_prompt
from matricaria.world.body import Body

Image = pytest.importorskip("PIL.Image")

from matricaria.art.pixelize import pixelize  # noqa: E402


def _sample() -> "Image.Image":
    image = Image.new("RGB", (512, 512), (255, 255, 255))
    for y in range(128, 384):
        for x in range(160, 352):
            image.putpixel((x, y), (200 + (x % 40), 60, 120 + (y % 50)))
    return image


def test_pixelize_size_palette_and_outline():
    result = pixelize(_sample(), FACESET, upscale=False)
    assert result.size == (66, 66)  # сетка 64 + контур по 1 пикселю
    assert result.getpixel((0, 0))[3] == 0  # фон прозрачный
    assert result.getpixel((20, 33)) == (0, 0, 0, 255)  # контур слева от силуэта
    colors = {c for _, c in result.getcolors(maxcolors=4096) if c[3]}
    assert len(colors) <= FACESET.colors + 1


def test_pixelize_upscale_and_selout():
    result = pixelize(_sample(), HIBIT)
    assert result.size == (130 * 4, 130 * 4)
    edge = result.getpixel((40 * 4, 65 * 4))  # x 39 в сетке + 1 пиксель отступа
    assert edge[3] == 255 and edge[:3] != (0, 0, 0)  # контур окрашен соседним цветом


def test_prompt_is_safe_and_follows_body():
    child = portrait_prompt({"hair": {"color": "pink", "style": "short"}}, Body(9, 130, 40), "happy")
    assert "child" in child["prompt"] and "fully clothed" in child["prompt"]
    assert "chubby" in child["prompt"]
    assert "nsfw" in child["negative_prompt"] and "sexualized" in child["negative_prompt"]
    adult = portrait_prompt({"eyes": "blue"}, Body(25, 170, 62))
    assert "nsfw" in adult["negative_prompt"]
    assert "blue eyes" in adult["prompt"]
