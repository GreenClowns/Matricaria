"""Тесты обработки картинок эталона (tools/art/process_art.py)."""

import importlib.util
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("process_art", ROOT / "tools" / "art" / "process_art.py")
process_art = importlib.util.module_from_spec(spec)
sys.modules["process_art"] = process_art
spec.loader.exec_module(process_art)


def blocky_image(block=8, bg=(216, 209, 196)):
    """Картинка 20×20 «пикселей» по block точек: фон и красный квадрат посередине."""
    small = Image.new("RGB", (20, 20), bg)
    for y in range(6, 14):
        for x in range(6, 14):
            small.putpixel((x, y), (200, 40, 40))
    return small.resize((20 * block, 20 * block), Image.NEAREST)


def test_estimate_block_finds_pixel_size():
    rng = np.random.default_rng(1)
    small = Image.fromarray(rng.integers(0, 255, (24, 24, 3), dtype=np.uint8), "RGB")
    assert process_art.estimate_block(small.resize((24 * 7, 24 * 7), Image.NEAREST)) == 7


def test_portrait_removes_background(tmp_path):
    src = tmp_path / "src.png"
    blocky_image(8).save(src)
    out = process_art.process_portrait(src, tmp_path / "out.png", 20, 8, None, 60)
    a = np.asarray(out)
    assert out.size == (20, 20)
    assert a[0, 0, 3] == 0          # угол — фон, прозрачный
    assert a[10, 10, 3] == 255      # центр — фигура, непрозрачный
    assert a[10, 10, 0] > 150 and a[10, 10, 1] < 100


def test_sheet_slices_frames_on_magenta(tmp_path):
    sheet = Image.new("RGB", (400, 200), (255, 0, 255))
    for i in range(3):
        for y in range(40, 160):
            for x in range(30 + i * 120, 90 + i * 120):
                sheet.putpixel((x, y), (60, 120, 60))
    src = tmp_path / "sheet.png"
    sheet.save(src)
    info = process_art.slice_sheet(src, tmp_path / "frames", 6, 8, (255, 0, 255), 90, min_area=500)
    assert len(info["frames"]) == 3
    assert (tmp_path / "frames" / "atlas.png").exists()


def test_magenta_like_skips_violet_robe():
    a = np.array([[[255, 0, 255], [110, 30, 110], [90, 50, 120], [150, 70, 40]]])
    assert process_art.magenta_like(a).tolist() == [[True, True, False, False]]


def test_sheet_gap_separates_close_frames(tmp_path):
    sheet = Image.new("RGB", (400, 140), (255, 0, 255))
    for i in range(2):
        for y in range(20, 120):
            for x in range(40 + i * 66, 100 + i * 66):
                sheet.putpixel((x, y), (60, 120, 60))
    src = tmp_path / "sheet.png"
    sheet.save(src)
    joined = process_art.slice_sheet(src, tmp_path / "a", 4, 8, (255, 0, 255), 90, min_area=500)
    split = process_art.slice_sheet(src, tmp_path / "b", 4, 8, (255, 0, 255), 90, min_area=500, gap=3)
    assert len(joined["frames"]) == 1
    assert len(split["frames"]) == 2


def test_recolor_changes_green_to_violet(tmp_path):
    img = Image.new("RGBA", (2, 1), (60, 140, 60, 255))
    img.putpixel((1, 0), (0, 0, 0, 0))
    src = tmp_path / "g.png"
    img.save(src)
    rules = [{"hue": [70, 170], "min_sat": 0.15, "to_hue": 275}]
    process_art.recolor(src, tmp_path / "v.png", rules)
    r, g, b, a = Image.open(tmp_path / "v.png").getpixel((0, 0))
    assert b > g and r > g
    assert Image.open(tmp_path / "v.png").getpixel((1, 0))[3] == 0
