"""Microbolometer-style sensor non-uniformity model (roadmap task 1.3 / 1.5).

raw[t, i] = clip( g[i] * scene[t, i] + o[i] + col[x] + row[y] + drift[t, i] + n[t, i] ), dead/hot overrides.

All quantities are in sensor counts of a `bits`-bit ADC (default 14). `scene` is the clean image in the
same counts, so ground truth is exact: the clean scene itself. Parameter justification is in
docs/noise_model.md (each one is a stated assumption or a literature-backed range; read it before quoting).

Determinism: every random draw comes from numpy Generators seeded from `Preset.seed`, so a (preset, scene)
pair always gives the same noisy clip. Static maps use seed, temporal noise uses seed+1, drift seed+2.
"""
from dataclasses import dataclass, replace

import numpy as np


@dataclass(frozen=True)
class Preset:
    name: str
    sigma_g: float      # per-pixel gain spread, dimensionless (g ~ N(1, sigma_g))
    sigma_o: float      # per-pixel offset spread, counts
    sigma_col: float    # column fixed-pattern, counts
    sigma_row: float    # row fixed-pattern, counts
    sigma_t: float      # temporal (per-frame) Gaussian noise, counts
    drift: float        # offset random-walk step per frame, counts (sigma of the increment)
    dead_rate: float    # fraction of pixels stuck at 0
    hot_rate: float     # fraction of pixels stuck at full scale
    bits: int = 14
    seed: int = 1234


PRESETS = {
    "mild":    Preset("mild",    0.02,  30.0,  5.0, 0.0,  3.0, 0.005, 0.0001, 0.0001),
    "typical": Preset("typical", 0.05, 100.0, 20.0, 5.0,  8.0, 0.020, 0.0005, 0.0005),
    "severe":  Preset("severe",  0.10, 250.0, 50.0, 15.0, 15.0, 0.050, 0.0020, 0.0020),
}


def preset(name, **overrides):
    p = PRESETS[name]
    return replace(p, **overrides) if overrides else p


class SensorSim:
    """Stateful sensor: call frame(scene) once per frame, in order."""

    def __init__(self, p: Preset, shape):
        self.p = p
        self.shape = tuple(shape)
        h, w = self.shape
        rs = np.random.default_rng(p.seed)
        self.gain = 1.0 + p.sigma_g * rs.standard_normal(self.shape)
        self.offset0 = p.sigma_o * rs.standard_normal(self.shape)
        self.col = p.sigma_col * rs.standard_normal((1, w))
        self.row = p.sigma_row * rs.standard_normal((h, 1))
        u = rs.random(self.shape)
        self.dead = u < p.dead_rate
        self.hot = (u >= p.dead_rate) & (u < p.dead_rate + p.hot_rate)
        self.rt = np.random.default_rng(p.seed + 1)
        self.rd = np.random.default_rng(p.seed + 2)
        self.drift_acc = np.zeros(self.shape)
        self.t = 0

    @property
    def bad_mask(self):
        return self.dead | self.hot

    def true_offset(self):
        """Current per-pixel additive term (offset + col + row + drift), counts. For diagnostics only."""
        return self.offset0 + self.col + self.row + self.drift_acc

    def frame(self, scene):
        p = self.p
        full = (1 << p.bits) - 1
        if self.t > 0 and p.drift > 0:
            self.drift_acc += p.drift * self.rd.standard_normal(self.shape)
        n = p.sigma_t * self.rt.standard_normal(self.shape)
        raw = self.gain * scene + self.true_offset() + n
        raw = np.rint(raw)
        raw[self.dead] = 0
        raw[self.hot] = full
        self.t += 1
        return np.clip(raw, 0, full).astype(np.uint16)

    def clip(self, scene_seq):
        return np.stack([self.frame(f) for f in scene_seq])


def add_noise(scene_seq, preset_name_or_obj, **overrides):
    """Convenience: (T,H,W) clean counts -> (raw (T,H,W) uint16, SensorSim). The sim holds the truth."""
    p = preset(preset_name_or_obj, **overrides) if isinstance(preset_name_or_obj, str) else preset_name_or_obj
    sim = SensorSim(p, scene_seq.shape[1:])
    return sim.clip(scene_seq), sim
