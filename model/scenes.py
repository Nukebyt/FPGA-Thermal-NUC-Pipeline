"""Synthetic thermal scenes with exact motion ground truth.

Used before the real datasets are downloaded and as a controlled testbed afterwards (moving-camera
case, stationary-then-moving object for the ghosting test). Everything is deterministic from `seed`.

Units: sensor counts of a 14-bit ADC. Background sits around `base` and spans a few thousand counts,
which is how a real uncooled-sensor scene fills only part of the range.
"""
from dataclasses import dataclass
from typing import List

import numpy as np
from scipy.ndimage import gaussian_filter


@dataclass
class Blob:
    cx: float
    cy: float
    rx: float
    ry: float
    dt: float            # temperature contrast in counts
    vx: float = 0.0
    vy: float = 0.0
    start: int = 0       # frame at which it starts moving (before: stationary)


def _background(h, w, rng, base):
    k = min(h, w) / 240.0                       # everything below scales with frame size
    low = gaussian_filter(rng.standard_normal((h, w)), 30 * k)
    low = low / low.std() * 350.0
    tex = gaussian_filter(rng.standard_normal((h, w)), 1.4)
    tex = tex / tex.std() * 45.0
    bg = base + low + tex
    # horizon-like vertical gradient
    bg += np.linspace(300.0, -300.0, h)[:, None]
    # a few warm/cool rectangles with soft edges (buildings, windows)
    yy, xx = np.mgrid[0:h, 0:w]
    for _ in range(6):
        x0, y0 = rng.integers(0, max(2, w - int(40 * k))), rng.integers(0, max(2, h - int(40 * k)))
        ww, hh = rng.integers(max(3, int(20 * k)), max(4, int(90 * k))), rng.integers(max(3, int(15 * k)), max(4, int(70 * k)))
        amp = rng.choice([-1, 1]) * rng.uniform(150, 500)
        m = ((xx >= x0) & (xx < x0 + ww) & (yy >= y0) & (yy < y0 + hh)).astype(float)
        bg += amp * gaussian_filter(m, 1.2)
    return bg


def _blob_alpha(shape, b, t):
    """Soft ellipse of the blob at frame t; returns (alpha 0..1)."""
    h, w = shape
    dtm = max(0, t - b.start)
    cx = b.cx + b.vx * dtm
    cy = b.cy + b.vy * dtm
    # bounce inside the frame
    def bounce(v, lo, hi):
        span = hi - lo
        v = (v - lo) % (2 * span)
        return lo + (v if v <= span else 2 * span - v)
    cx = bounce(cx, b.rx + 2, w - b.rx - 2)
    cy = bounce(cy, b.ry + 2, h - b.ry - 2)
    yy, xx = np.mgrid[0:h, 0:w]
    d = ((xx - cx) / b.rx) ** 2 + ((yy - cy) / b.ry) ** 2
    return np.clip((1.0 - d) * 4.0, 0.0, 1.0)     # ~1 px soft edge


def default_blobs(h, w, rng, n=3):
    blobs = []
    k = min(h, w) / 240.0
    m = 40 * k
    for _ in range(n):
        blobs.append(Blob(cx=rng.uniform(m, w - m), cy=rng.uniform(m, h - m),
                          rx=max(rng.uniform(5, 14) * k, 4.0), ry=max(rng.uniform(8, 18) * k, 4.5),
                          dt=rng.uniform(700, 1500),
                          vx=rng.uniform(-1.6, 1.6) * max(k, 0.5), vy=rng.uniform(-0.8, 0.8) * max(k, 0.5)))
    return blobs


def make_scene(T, shape=(240, 320), seed=7, base=5000.0, blobs: List[Blob] = None,
               pan=(0.0, 0.0), n_blobs=3):
    """Returns (scene float (T,H,W) counts, gt bool (T,H,W) motion mask, blobs).

    pan=(vx, vy) camera motion in px/frame (integer-rounded crop of a larger canvas). pan=(0,0) is a static
    camera, where constant-statistics NUC cannot work (see docs/nuc_study.md).
    """
    h, w = shape
    rng = np.random.default_rng(seed)
    pad = int(np.ceil(max(abs(pan[0]), abs(pan[1])) * T)) + 4
    bg = _background(h + 2 * pad, w + 2 * pad, rng, base)
    blobs = default_blobs(h, w, rng, n_blobs) if blobs is None else blobs
    scene = np.empty((T, h, w))
    gt = np.zeros((T, h, w), dtype=bool)
    for t in range(T):
        ox = pad + int(round(pan[0] * t))
        oy = pad + int(round(pan[1] * t))
        f = bg[oy:oy + h, ox:ox + w].copy()
        for b in blobs:
            a = _blob_alpha(shape, b, t)
            f += b.dt * a
            moving = (t >= b.start) and (abs(b.vx) + abs(b.vy) > 0)
            if moving:
                gt[t] |= a > 0.5
        scene[t] = f
    return scene, gt, blobs
