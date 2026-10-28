"""Тесты скелетных спрайтов (tools/art/skeleton.py)."""

import importlib.util
import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PIL.Image")

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("skeleton", ROOT / "tools" / "art" / "skeleton.py")
skeleton = importlib.util.module_from_spec(spec)
sys.modules["skeleton"] = skeleton
spec.loader.exec_module(skeleton)


def width(img):
    """Ширина фигуры по самой широкой строке."""
    alpha = np.asarray(img)[:, :, 3] > 0
    return int(alpha.sum(1).max())


def height(img):
    alpha = np.asarray(img)[:, :, 3] > 0
    rows = np.flatnonzero(alpha.any(1))
    return int(rows[-1] - rows[0] + 1)


def test_frame_is_transparent_around_figure():
    img = skeleton.render_frame(skeleton.Body(), skeleton.Pose())
    assert img.size == (skeleton.FRAME_W, skeleton.FRAME_H)
    a = np.asarray(img)
    assert a[0, 0, 3] == 0
    assert 40 <= height(img) <= 60      # рост как у эталона (около 52)


def test_fat_body_is_wider():
    thin = skeleton.render_frame(skeleton.Body(fat=0.0, muscle=0.0), skeleton.Pose())
    fat = skeleton.render_frame(skeleton.Body(fat=1.0, muscle=0.0), skeleton.Pose())
    assert width(fat) > width(thin)


def test_tall_body_is_taller():
    short = skeleton.render_frame(skeleton.Body(height=0.8), skeleton.Pose())
    tall = skeleton.render_frame(skeleton.Body(height=1.25), skeleton.Pose())
    assert height(tall) > height(short)


def test_same_input_same_picture():
    body, pose = skeleton.BODIES["plump"], skeleton.POSES["walk"][1]
    a = np.asarray(skeleton.render_frame(body, pose))
    b = np.asarray(skeleton.render_frame(body, pose))
    assert (a == b).all()


def test_demo_writes_sheets(tmp_path):
    skeleton.main(["demo", str(tmp_path)])
    assert (tmp_path / "average.png").exists()
    assert (tmp_path / "sheets.json").exists()
