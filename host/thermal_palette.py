"""Thermal-camera colours for the 8-bit pictures the board's capture buffer returns (used by host/viewer.py and scripts/capture_gifs.py).

Rainbow palette: purple-blue (cold) -> blue -> cyan -> green -> yellow -> orange -> red (hot). The board's picture is tone-mapped by
the design over its whole range for its own display; here a window is applied on top (percentiles of the picture, so the cold
background stays purple-blue and warm things reach orange / red). The window is a display choice made on the laptop."""
import numpy as np

STOPS = [(0, (45, 0, 105)), (40, (35, 20, 190)), (85, (0, 120, 255)), (120, (0, 215, 170)), (150, (140, 240, 40)),
         (185, (255, 215, 0)), (220, (255, 120, 0)), (255, (225, 20, 10))]
LEVELS = 32                       # a fixed colour table keeps GIFs small; fine for the live view too
LO_PCT, HI_PCT, GAMMA = 20.0, 98.5, 0.9


def rainbow_rgb(level, levels=LEVELS):
    """level 0..levels-1 -> rgb"""
    xs = [x for x, _ in STOPS]
    q = (np.asarray(level, np.float64) + 0.5) * 256.0 / levels
    return np.stack([np.interp(q, xs, [c[k] for _, c in STOPS]) for k in range(3)], -1).astype(np.uint8)


def window(imgs, lo_pct=LO_PCT, hi_pct=HI_PCT):
    """One (lo, hi) from the percentiles of all pixels of the given frames."""
    allp = np.concatenate([i.ravel() for i in imgs])
    lo, hi = np.percentile(allp, [lo_pct, hi_pct])
    return float(lo), float(max(hi, lo + 8))


def colour(img8, win, gamma=GAMMA, levels=LEVELS):
    lo, hi = win
    t = np.clip((img8.astype(np.float64) - lo) / (hi - lo), 0, 1) ** gamma
    return rainbow_rgb(np.minimum((t * levels).astype(np.int64), levels - 1), levels)


class LiveWindow:
    """Window for a live view: percentiles of each frame, smoothed over time so the colours do not pump."""

    def __init__(self, lo_pct=LO_PCT, hi_pct=HI_PCT, alpha=0.08):
        self.lo_pct, self.hi_pct, self.alpha, self.win = lo_pct, hi_pct, alpha, None

    def update(self, img8):
        w = window([img8[::2, ::2]], self.lo_pct, self.hi_pct)
        self.win = w if self.win is None else tuple((1 - self.alpha) * o + self.alpha * n for o, n in zip(self.win, w))
        return self.win
