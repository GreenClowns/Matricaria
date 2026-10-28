"""Тесты портретов кодом (tools/art/portrait.py)."""

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PIL.Image")

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("portrait", ROOT / "tools" / "art" / "portrait.py")
portrait = importlib.util.module_from_spec(spec)
sys.modules["portrait"] = portrait
spec.loader.exec_module(portrait)


def test_portrait_size():
    img = portrait.render(portrait.CAST["kira"])
    assert img.size == (portrait.SIZE, portrait.SIZE)


def test_same_look_same_picture():
    a = np.asarray(portrait.render(portrait.CAST["boris"]))
    b = np.asarray(portrait.render(portrait.CAST["boris"]))
    assert (a == b).all()


def test_emotion_changes_face_only():
    base = portrait.CAST["kira"]
    calm = np.asarray(portrait.render(base)).astype(int)
    angry = np.asarray(portrait.render(replace(base, emotion="angry"))).astype(int)
    diff = np.abs(calm - angry).sum(2) > 0
    ys, xs = np.nonzero(diff)
    assert diff.any()
    assert ys.min() > 40 and ys.max() < 95      # меняются только брови, глаза и рот


def test_eye_color_is_used():
    look = replace(portrait.CAST["lina"], eyes="#00ff00")
    a = np.asarray(portrait.render(look))
    assert ((a[:, :, 1] > 150) & (a[:, :, 0] < 120)).sum() > 10


def test_all_cast_and_emotions_render(tmp_path):
    portrait.main(["demo", str(tmp_path)])
    for key in portrait.CAST:
        assert (tmp_path / f"{key}.png").exists()
    assert (tmp_path / "kira_sad.png").exists()
