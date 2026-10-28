"""Floating-point NUC algorithms (roadmap tasks 2.1-2.4). Exploration only; the frozen design is pipeline_int.py.

All classes: .step(x) takes one raw frame (H,W) of ADC counts and returns the corrected frame as float counts.
Coefficient updates use only that frame's inputs, and every pixel of the frame is corrected with the
coefficients as they were at frame start (this is what a streaming pipeline with a one-frame write-back
hazard distance does, so the vectorised model is exact for it).
"""
import numpy as np


def nb_stack(a, mode="edge"):
    """(8,H,W) neighbours of every pixel, edge-replicated at the border. Order: NW N NE W E SW S SE."""
    p = np.pad(a, 1, mode=mode)
    h, w = a.shape
    return np.stack([p[dy:dy + h, dx:dx + w] for dy in (0, 1, 2) for dx in (0, 1, 2) if (dy, dx) != (1, 1)])


IDX4 = [1, 3, 4, 6]       # N, W, E, S inside nb_stack order


class IdentityNUC:
    def step(self, x):
        return x.astype(np.float64)


class ConstStatNUC:
    """Harris-Chiang constant-statistics NUC: assume every pixel sees the same temporal mean and std.
    Running (exponential) mean/variance per pixel -> y = (x - m) * (sref / s) + mref.
    Needs scene motion (moving camera). On a static camera it learns the scene itself and fails."""

    def __init__(self, shape, rate=1 / 64.0):
        self.a = rate
        self.m = None
        self.v = None

    def step(self, x):
        x = x.astype(np.float64)
        if self.m is None:
            self.m = x.copy()
            self.v = np.full_like(x, 1.0)
            return x
        d = x - self.m
        self.m += self.a * d
        self.v += self.a * (d * d - self.v)
        s = np.sqrt(np.maximum(self.v, 1e-6))
        return (x - self.m) * (s.mean() / s) + self.m.mean()


class LmsNUC:
    """Scribner-style neural-network / LMS NUC with optional gates.

    y = g * (x - o)
    d = mean of the valid 4-neighbours of y            (desired value)
    e = y - d
    o += mu_o * clip(e)                  g -= mu_g * clip(e) * (x - o)
    edge_stop : no update if (max - min) of the valid 8-neighbours of y exceeds T_edge
    motion_gate: no update unless |x - x_prev| > T_motion (temporal difference cancels the offset FPN)
    bad pixels (mask given to step) are excluded from neighbour averages and not updated.
    """

    def __init__(self, shape, mu_o=1 / 16.0, mu_g=2.0 ** -28, e_clip=256.0,
                 edge_stop=None, motion_gate=None, learn_gain=True,
                 adaptive=None, skip=False, global_gate=None, gain_gate=None):
        """adaptive=(k, e_min, e_max): per-frame error limit E = clamp(k * mean|e|_previous_frame, e_min, e_max),
        replacing the fixed e_clip. skip=True zeroes errors beyond E instead of clipping them.
        global_gate=T: learn only if the frame-mean |x - x_prev| exceeds T (moving-camera mode)."""
        self.o = np.zeros(shape)
        self.g = np.ones(shape)
        self.mu_o, self.mu_g, self.e_clip = mu_o, mu_g, e_clip
        self.edge_stop, self.motion_gate, self.learn_gain = edge_stop, motion_gate, learn_gain
        self.adaptive, self.skip, self.global_gate = adaptive, skip, global_gate
        self.gain_gate = gain_gate
        self.activity = 0.0     # externally supplied: previous-frame mean|y - B| (see scripts/study_nuc2.py)
        self.abs_e_mean = None
        self.xprev = None
        self.frozen = False
        self.last_activity = 0.0

    def correct(self, x):
        return self.g * (x.astype(np.float64) - self.o)

    def step(self, x, bad=None):
        x = x.astype(np.float64)
        y = self.g * (x - self.o)
        bad = np.zeros(x.shape, bool) if bad is None else bad
        if not self.frozen:
            nb = nb_stack(y)
            vb = ~nb_stack(bad, mode="edge")
            v4 = vb[IDX4]
            cnt = v4.sum(0)
            d = np.where(cnt > 0, (nb[IDX4] * v4).sum(0) / np.maximum(cnt, 1), y)
            e = y - d
            if self.adaptive is not None:
                k, lo_, hi_ = self.adaptive
                lim = hi_ if self.abs_e_mean is None else float(np.clip(k * self.abs_e_mean, lo_, hi_))
            else:
                lim = self.e_clip
            big = np.abs(e) > lim
            self.abs_e_mean = float(np.abs(e[~bad]).mean())
            e = np.where(big, 0.0, e) if self.skip else np.clip(e, -lim, lim)
            upd = ~bad
            if self.global_gate is not None:
                self.last_activity = 0.0 if self.xprev is None else float(np.abs(x - self.xprev).mean())
                if self.last_activity <= self.global_gate:
                    upd &= False
            if self.edge_stop is not None:
                hi = np.where(vb, nb, -np.inf).max(0)
                lo = np.where(vb, nb, np.inf).min(0)
                upd &= (hi - lo) <= self.edge_stop
            if self.motion_gate is not None:
                if self.xprev is None:
                    upd &= False
                else:
                    upd &= np.abs(x - self.xprev) > self.motion_gate
            e = np.where(upd, e, 0.0)
            xo = x - self.o
            self.o = self.o + self.mu_o * e
            if self.learn_gain and (self.gain_gate is None or self.activity > self.gain_gate):
                self.g = self.g - self.mu_g * e * xo
        self.xprev = x
        return y


def bad_pixel_outliers(y, thresh):
    """True where y is outside [min8 - T, max8 + T] of its 8 neighbours (single-pixel outlier test).
    Robust to edges: a pixel on a real edge lies inside the neighbour range."""
    nb = nb_stack(y)
    return (y > nb.max(0) + thresh) | (y < nb.min(0) - thresh)


class BadPixelTracker:
    """4-bit saturating persistence counter per pixel; flag = counter >= on_level (hysteresis by decay)."""

    def __init__(self, shape, thresh=800.0, on_level=8, rails=(0, 16383)):
        self.c = np.zeros(shape, np.int32)
        self.thresh, self.on, self.rails = thresh, on_level, rails

    @property
    def flag(self):
        return self.c >= self.on

    def update(self, x, y):
        out = bad_pixel_outliers(y, self.thresh)
        out |= (x <= self.rails[0]) | (x >= self.rails[1])
        self.c = np.clip(self.c + np.where(out, 1, -1), 0, 15)


def replace_bad(y, bad):
    """Replace flagged pixels by the mean of their valid 4-neighbours (own value if none)."""
    nb = nb_stack(y)
    vb = ~nb_stack(bad)
    v4 = vb[IDX4]
    cnt = v4.sum(0)
    r = np.where(cnt > 0, (nb[IDX4] * v4).sum(0) / np.maximum(cnt, 1), y)
    return np.where(bad, r, y)
