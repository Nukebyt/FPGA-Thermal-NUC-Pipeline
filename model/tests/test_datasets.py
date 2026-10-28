"""Loader tests on a fabricated CDnet-shaped tree (no real data needed)."""
import os

import cv2
import numpy as np
import pytest

from model import datasets as D


@pytest.fixture
def fake_cdnet(tmp_path):
    root = tmp_path / "thermal"
    d = root / "park"
    (d / "input").mkdir(parents=True)
    (d / "groundtruth").mkdir()
    rng = np.random.default_rng(1)
    for i in range(1, 11):
        cv2.imwrite(str(d / "input" / ("in%06d.jpg" % i)), (rng.random((288, 352)) * 255).astype(np.uint8))
        g = np.zeros((288, 352), np.uint8)
        g[100:120, 50:80] = 255
        g[0:10, :] = 85
        g[10:20, 0:10] = 170
        cv2.imwrite(str(d / "groundtruth" / ("gt%06d.png" % i)), g)
    (d / "temporalROI.txt").write_text("4 9\n")
    return str(root)


def test_cdnet_shapes_and_labels(fake_cdnet):
    scene, gt, valid, first = D.load_cdnet(fake_cdnet, "park")
    assert scene.shape == (10, 240, 320) and gt.shape == valid.shape == scene.shape
    assert first == 3                      # temporalROI starts at frame 4 (index 3)
    assert not valid[:3].any() and not valid[9:].any()
    assert gt[4].any() and not (gt[4] & ~valid[4]).any()
    assert not valid[4][:8].any()          # label 85 rows (outside ROI) are excluded
    assert 3000 <= scene.min() and scene.max() <= 3000 + 16 * 255


def test_cdnet_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        D.load_cdnet(str(tmp_path), "corridor")


def test_flir_loader_and_scene(tmp_path):
    rng = np.random.default_rng(2)
    for i in range(3):
        cv2.imwrite(str(tmp_path / ("f%04d.tiff" % i)), (20000 + rng.random((512, 640)) * 3000).astype(np.uint16))
    fr = D.load_flir_thermal(str(tmp_path))
    assert fr.shape == (3, 240, 320)
    sc = D.scene_from_flir(fr)
    assert 4000 < np.median(sc) < 6000 and sc.min() >= 0 and sc.max() <= 16383


def test_pan_clip_bounds():
    still = np.random.default_rng(3).random((300, 400))
    clip = D.pan_clip(still, 20, vel=(1.0, 0.5))
    assert clip.shape == (20, 240, 320) and np.array_equal(clip[0], still[:240, :320])
    with pytest.raises(ValueError):
        D.pan_clip(still, 200)
