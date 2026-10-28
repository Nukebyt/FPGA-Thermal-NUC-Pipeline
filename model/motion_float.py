"""Floating-point motion detector (roadmap task 2.7): running-average background, threshold, 3x3 open+close,
bounding boxes by connected components. Exploration model; the bit-accurate one lives in pipeline_int.py."""
import numpy as np
from scipy import ndimage as ndi


class BackgroundDetector:
    def __init__(self, shape, thresh=150.0, alpha_fast=1 / 64.0, alpha_slow=1 / 64.0, morph=True, warm_start=True):
        """alpha_fast applies where the pixel is background, alpha_slow where it is flagged foreground; equal values
        = blind update, which is what the study found best (a slow foreground rate keeps start-up ghosts alive).
        warm_start: alpha = max(alpha, 1/2^ceil(log2(n+1))) for the first frames, i.e. a running mean of the
        first frames, so objects present in frame 0 are diluted instead of baked into the background."""
        self.b = None
        self.n = 0
        self.t, self.af, self.as_, self.morph, self.warm = thresh, alpha_fast, alpha_slow, morph, warm_start

    def step(self, y):
        y = y.astype(np.float64)
        if self.b is None:
            self.b = y.copy()
            return np.zeros(y.shape, bool)
        mask = np.abs(y - self.b) > self.t
        a = np.where(mask, self.as_, self.af)
        if self.warm:
            a = np.maximum(a, 1.0 / (1 << int(np.ceil(np.log2(self.n + 1)))) if self.n < 64 else 0.0)
        self.n += 1
        self.b = self.b + a * (y - self.b)
        if self.morph:
            s = np.ones((3, 3), bool)
            mask = ndi.binary_opening(mask, s)
            mask = ndi.binary_closing(mask, s)
        return mask


def boxes(mask, max_obj=16, min_area=1):
    """Bounding boxes of 8-connected components, as (xmin, ymin, xmax, ymax, area), at most max_obj."""
    lab, n = ndi.label(mask, structure=np.ones((3, 3)))
    out = []
    for i, sl in enumerate(ndi.find_objects(lab), start=1):
        a = int((lab[sl] == i).sum())
        if a >= min_area:
            out.append((sl[1].start, sl[0].start, sl[1].stop - 1, sl[0].stop - 1, a))
    return out[:max_obj], len(out)
