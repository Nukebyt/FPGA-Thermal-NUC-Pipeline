"""Loaders for the real datasets (data/ is gitignored; see docs/datasets.md for what to download and where to put it).

Everything is converted to the pipeline's working format: 240x320 frames in 14-bit sensor counts.

  CDnet 2014 thermal : 8-bit JPEG frames + pixel-level ground truth. Static camera. Detector benchmark.
  FLIR ADAS thermal  : 14/16-bit TIFF frames. Mostly a moving (vehicle-mounted) camera. NUC benchmark.

Neither dataset is a clean scene: both already contain a real camera's own residual noise. We treat them as
'clean enough' ground truth and add the simulated non-uniformity on top (docs/noise_model.md says so).
"""
import glob
import os
from typing import Optional, Tuple

import cv2
import numpy as np

H, W = 240, 320
CDNET_THERMAL = ("corridor", "diningRoom", "lakeSide", "library", "park")


def _fit(img, interp):
    """Scale to height H keeping aspect, then centre-crop or edge-pad the width to W."""
    h, w = img.shape[:2]
    nw = max(1, int(round(w * H / h)))
    out = cv2.resize(img, (nw, H), interpolation=interp)
    if nw > W:
        x0 = (nw - W) // 2
        out = out[:, x0:x0 + W]
    elif nw < W:
        pl = (W - nw) // 2
        out = np.pad(out, ((0, 0), (pl, W - nw - pl)), mode="edge")
    return out


def to_counts_8bit(v8, base=3000.0, scale=16.0):
    """8-bit AGC'd thermal -> 14-bit counts: base + v*scale (3000..7080, i.e. ~25 % of the range, like a real scene)."""
    return base + scale * np.asarray(v8, np.float64)


def load_cdnet(root: str, seq: str, max_frames: Optional[int] = None, start: int = 0):
    """root = .../dataset2014/dataset/thermal  (contains corridor/, diningRoom/, ...).
    Returns scene (T,H,W) float counts, gt (T,H,W) bool motion (label 255), valid (T,H,W) bool (excludes label 85
    outside-ROI and 170 unknown, and frames outside temporalROI), first_eval_frame (index within the returned clip)."""
    d = os.path.join(root, seq)
    ins = sorted(glob.glob(os.path.join(d, "input", "in*.jpg")))
    if not ins:
        raise FileNotFoundError(f"no CDnet frames under {d}/input (see docs/datasets.md for the expected layout)")
    t0, t1 = 1, len(ins)
    troi = os.path.join(d, "temporalROI.txt")
    if os.path.exists(troi):
        a, b = open(troi).read().split()[:2]
        t0, t1 = int(a), int(b)
    ins = ins[start:]
    if max_frames:
        ins = ins[:max_frames]
    scene, gt, valid = [], [], []
    for p in ins:
        idx = int(os.path.basename(p)[2:-4])
        img = cv2.imread(p, cv2.IMREAD_GRAYSCALE)
        scene.append(_fit(img, cv2.INTER_AREA))
        g = cv2.imread(os.path.join(d, "groundtruth", "gt%06d.png" % idx), cv2.IMREAD_GRAYSCALE)
        if g is None or not (t0 <= idx <= t1):
            gt.append(np.zeros((H, W), bool))
            valid.append(np.zeros((H, W), bool))
        else:
            g = _fit(g, cv2.INTER_NEAREST)
            gt.append(g == 255)
            valid.append((g != 85) & (g != 170))
    first_eval = next((i for i, v in enumerate(valid) if v.any()), len(valid))
    return to_counts_8bit(np.stack(scene)), np.stack(gt), np.stack(valid), first_eval


def load_flir_thermal(root: str, max_frames: int = 400, start: int = 0):
    """All .tiff/.tif under root (recursive), sorted by name. Returns raw frames (T,H,W) float, native 16-bit units.
    640x512 frames are halved (area) to 320x256 and the central 240 rows kept."""
    files = sorted(glob.glob(os.path.join(root, "**", "*.tif*"), recursive=True))
    if not files:
        raise FileNotFoundError(f"no .tiff files under {root} (see docs/datasets.md)")
    out = []
    for p in files[start:start + max_frames]:
        im = cv2.imread(p, cv2.IMREAD_UNCHANGED)
        if im is None or im.ndim != 2:
            raise ValueError(f"{p}: expected a single-channel 16-bit thermal TIFF, got {None if im is None else im.shape}")
        im = im.astype(np.float32)
        if im.shape != (512, 640):
            im = cv2.resize(im, (640, 512), interpolation=cv2.INTER_AREA)
        im = cv2.resize(im, (320, 256), interpolation=cv2.INTER_AREA)
        out.append(im[8:248])
    return np.stack(out).astype(np.float64)


def scene_from_flir(frames: np.ndarray, base: float = 5000.0, max_span: float = 5000.0):
    """Native units -> 14-bit counts: recentre on the clip median to `base`, and compress (never expand) so the
    0.5..99.5 percent range spans at most `max_span` counts. Keeps the radiometric *shape*, drops the offset."""
    med = np.median(frames)
    lo, hi = np.percentile(frames, [0.5, 99.5])
    k = min(1.0, max_span / max(hi - lo, 1.0))
    return np.clip(base + (frames - med) * k, 0, 16383)


def pan_clip(still: np.ndarray, T: int, vel: Tuple[float, float] = (0.8, 0.5), shape=(H, W)):
    """A moving-camera clip from one large still (so a single FLIR frame can drive the scene-based-NUC test).
    `still` must be at least (shape + vel*T + 4) in each dimension."""
    h, w = shape
    out = np.empty((T, h, w))
    for t in range(T):
        ox, oy = int(round(vel[0] * t)), int(round(vel[1] * t))
        if oy + h > still.shape[0] or ox + w > still.shape[1]:
            raise ValueError("still image too small for this pan length")
        out[t] = still[oy:oy + h, ox:ox + w]
    return out
