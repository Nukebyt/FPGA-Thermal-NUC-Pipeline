"""Integer-exact twin of rtl/sensor_emu.v : the on-chip "thermal sensor" used for the board demo (roadmap Phase 3a).

It produces the same kind of data as model/noise_model.py (per-pixel gain / offset, column pattern, temporal noise,
dead / hot pixels on top of a clean scene) but with integer arithmetic that fits in FPGA fabric:
  * clean scene   S = BASE + 16 * rom8[r>>1, c>>1] + sum of moving rectangles (each adds dt); the ROM is half
    resolution (ceil(H/2) x ceil(W/2)), addressed {r>>1, c>>1} with power-of-two padding (no multiplier)
  * pseudo-random numbers are a stateless hash of (pixel index, frame, stream id): lowbias32, so every pixel's
    fixed pattern is identical in every frame and no per-pixel state is stored
  * Gaussian-ish values: Irwin-Hall sum of the 4 bytes of a hash word, z = sum - 510 (sigma ~ 147.8)
  * raw = clamp(((g * S) >> 12) + o + col + n, 0, 16383) ; dead -> 0 ; hot -> 16383
Because the clean scene is known exactly, NUC quality can be scored on the board's output against the ground truth
the emulator also exposes (clean()).

Presets mirror noise_model.PRESETS (mild / typical / severe); the conversion constants are derived in
docs/noise_model.md (sigma / 147.8 * 256, rounded).
"""
from dataclasses import dataclass
from typing import List

import numpy as np

M32 = 0xFFFFFFFF
BASE = 3000
SEEDS = dict(A=0x9E3779B9, B=0x85EBCA6B, C=0xC2B2AE35, D=0x27D4EB2F, E=0x165667B1)
FRAME_MUL = 0x9E3779B1


def hash32(x):
    """lowbias32 (Chris Wellons). x: python int or uint64 ndarray holding 32-bit values."""
    x = np.asarray(x, dtype=np.uint64)
    x = x ^ (x >> np.uint64(16))
    x = (x * np.uint64(0x7FEB352D)) & np.uint64(M32)
    x = x ^ (x >> np.uint64(15))
    x = (x * np.uint64(0x846CA68B)) & np.uint64(M32)
    x = x ^ (x >> np.uint64(16))
    return x


def irwin_hall(h):
    """4 bytes of a hash word -> z = b0+b1+b2+b3-510, int64 in [-510, 510]"""
    h = np.asarray(h, dtype=np.uint64)
    s = (h & np.uint64(0xFF)) + ((h >> np.uint64(8)) & np.uint64(0xFF)) + ((h >> np.uint64(16)) & np.uint64(0xFF)) + (h >> np.uint64(24))
    return s.astype(np.int64) - 510


@dataclass(frozen=True)
class EmuPreset:
    GS: int      # gain sigma scale:   dg(Q12) = (z * GS) >> 8
    OS: int      # offset sigma scale: do(counts) = (z * OS) >> 8
    CS: int      # column sigma scale
    TS: int      # temporal sigma scale
    DEAD: int    # dead if low 16 bits of hash C < DEAD   (rate = DEAD / 65536)
    HOT: int     # hot  if high 16 bits of hash C < HOT


EMU_PRESETS = {
    "mild":    EmuPreset(GS=142, OS=52, CS=9, TS=5, DEAD=7, HOT=7),
    "typical": EmuPreset(GS=355, OS=173, CS=35, TS=14, DEAD=33, HOT=33),
    "severe":  EmuPreset(GS=710, OS=433, CS=87, TS=26, DEAD=131, HOT=131),
}


@dataclass
class Rect:
    x0: int
    y0: int
    w: int
    h: int
    dt: int
    vx: int
    vy: int


DEFAULT_RECTS = [Rect(40, 60, 18, 36, 1300, 2, 1), Rect(200, 120, 40, 22, 900, -1, 2), Rect(120, 30, 12, 12, 1500, 3, -2)]
MOVE_DIV = 2          # rectangles move every MOVE_DIV-th frame


def pack_rects(rects):
    """Pack 3 rectangles into the 192-bit RECTP parameter of rtl/sensor_emu.v ({x0,y0,w,h,dt,vx,vy} = 64 bits each)."""
    assert len(rects) == 3
    v = 0
    for k, r in enumerate(rects):
        word = (r.x0 << 54) | (r.y0 << 44) | (r.w << 34) | (r.h << 24) | (r.dt << 10) | ((r.vx & 31) << 5) | (r.vy & 31)
        v |= word << (64 * k)
    return v


class SensorEmu:
    def __init__(self, rom8: np.ndarray = None, preset="typical", rects: List[Rect] = None, W=320, H=240, preset_obj=None,
                 scene8: np.ndarray = None, obj_en=True):
        """rom8: half-resolution background ROM (the ROM build). scene8: full-resolution 8-bit frame (FEED build,
        rtl/scene_buf.v; replace it per frame with set_scene). obj_en = False hides the moving rectangles (CSR FEED_CTRL[0])."""
        self.W, self.H = W, H
        self.obj_en = obj_en
        self.noise_en = True             # False: the clean scene (RTL noise_en = 0)
        if scene8 is not None:
            assert rom8 is None and scene8.shape == (H, W), (scene8.shape, (H, W))
            self.rom = scene8.astype(np.int64)
        else:
            assert rom8.shape == rom_shape(W, H), (rom8.shape, rom_shape(W, H))
            self.rom = np.repeat(np.repeat(rom8.astype(np.int64), 2, 0), 2, 1)[:H, :W]
        self.p = preset_obj or EMU_PRESETS[preset]
        self.rects = [Rect(**r.__dict__) for r in (rects if rects is not None else DEFAULT_RECTS)]
        self.pos = [[r.x0, r.y0] for r in self.rects]
        self.dir = [[1, 1] for _ in self.rects]
        self.frame = 0
        idx = np.arange(W * H, dtype=np.uint64).reshape(H, W)
        self.idx = idx
        cols = np.arange(W, dtype=np.uint64)[None, :].repeat(H, 0)
        z = lambda seed, v: irwin_hall(hash32((v + np.uint64(seed)) & np.uint64(M32)))
        self.zA = z(SEEDS["A"], idx)
        self.zB = z(SEEDS["B"], idx)
        self.zE = z(SEEDS["E"], cols)
        hc = hash32((idx + np.uint64(SEEDS["C"])) & np.uint64(M32))
        self.dead = (hc & np.uint64(0xFFFF)) < np.uint64(self.p.DEAD)
        self.hot = ((hc >> np.uint64(16)) < np.uint64(self.p.HOT)) & ~self.dead
        self.g = 4096 + ((self.zA * self.p.GS) >> 8)
        self.o = (self.zB * self.p.OS) >> 8
        self.col = (self.zE * self.p.CS) >> 8

    def set_scene(self, scene8):
        """FEED build: the frame store now holds `scene8` (H x W, uint8)."""
        assert scene8.shape == (self.H, self.W)
        self.rom = scene8.astype(np.int64)

    # ---- clean scene (ground truth) ----
    def clean(self):
        S = BASE + (self.rom << 4)
        if self.obj_en:
            for r, (px, py) in zip(self.rects, self.pos):
                S[py:py + r.h, px:px + r.w] += r.dt
        return S

    def motion_mask(self):
        m = np.zeros((self.H, self.W), bool)
        if not self.obj_en:
            return m
        for r, (px, py) in zip(self.rects, self.pos):
            if r.vx or r.vy:
                m[py:py + r.h, px:px + r.w] = True
        return m

    def frame_raw(self):
        S = self.clean()
        if not self.noise_en:
            return np.clip(S, 0, 16383).astype(np.uint16)
        zD = irwin_hall(hash32((self.idx * np.uint64(7) + np.uint64((self.frame * FRAME_MUL) & M32) + np.uint64(SEEDS["D"])) & np.uint64(M32)))
        n = (zD * self.p.TS) >> 8
        raw = ((self.g * S) >> 12) + self.o + self.col + n
        raw = np.clip(raw, 0, 16383)
        raw = np.where(self.dead, 0, raw)
        raw = np.where(self.hot, 16383, raw)
        return raw.astype(np.uint16)

    def advance(self):
        """End-of-frame update: frame counter, and every MOVE_DIV-th frame move the rectangles (bounce at the borders)."""
        self.frame += 1
        if self.frame % MOVE_DIV == 0:
            for k, r in enumerate(self.rects):
                for ax, (v, lim) in enumerate(((r.vx, self.W - r.w), (r.vy, self.H - r.h))):
                    p = self.pos[k][ax] + self.dir[k][ax] * v
                    if p < 0:
                        p, self.dir[k][ax] = -p, 1
                    elif p > lim:
                        p, self.dir[k][ax] = 2 * lim - p, -1
                    self.pos[k][ax] = p

    def run(self, T, scenes=None):
        """T frames; scenes (T x H x W uint8) gives the frame-store content of each frame (FEED build)."""
        out, clean, mask = [], [], []
        for t in range(T):
            if scenes is not None:
                self.set_scene(scenes[t])
            out.append(self.frame_raw())
            clean.append(self.clean())
            mask.append(self.motion_mask())
            self.advance()
        return np.stack(out), np.stack(clean), np.stack(mask)


def rom_shape(W=320, H=240):
    """(rows, cols) of the half-resolution background ROM."""
    return ((H + 1) // 2, (W + 1) // 2)


def rom_bits(W=320, H=240):
    """(row bits, column bits) of the padded ROM address {r>>1, c>>1} (same rule as rtl/sensor_emu.v)."""
    rr, cc = rom_shape(W, H)
    return max(1, int(np.ceil(np.log2(rr)))), max(1, int(np.ceil(np.log2(cc))))


def rom_from_scene(shape=(240, 320), seed=21):
    """Default demo background: synthetic thermal scene without moving objects, quantised to 8 bit, half resolution."""
    from . import scenes
    import cv2
    scene, _, _ = scenes.make_scene(1, shape=shape, seed=seed, blobs=[])
    full = np.clip(np.rint((scene[0] - BASE) / 16.0), 0, 255).astype(np.uint8)
    rr, cc = rom_shape(shape[1], shape[0])
    return cv2.resize(full, (cc, rr), interpolation=cv2.INTER_AREA)


def pack_words(frame8):
    """FEED build: a frame as the 32-bit words the host writes (4 pixels per word, little endian, raster order, zero padded)."""
    flat = np.zeros(((frame8.size + 3) // 4) * 4, np.uint32)
    flat[:frame8.size] = frame8.ravel()
    q = flat.reshape(-1, 4)
    return q[:, 0] | (q[:, 1] << 8) | (q[:, 2] << 16) | (q[:, 3] << 24)


def write_hex(path, rom8, W=320, H=240):
    """Padded to 2**rb rows x 2**cb columns so the RTL address is a plain concatenation."""
    rb, cb = rom_bits(W, H)
    pad = np.zeros((1 << rb, 1 << cb), np.uint8)
    pad[:rom8.shape[0], :rom8.shape[1]] = rom8
    with open(path, "w", newline="\n") as f:
        f.write("// background ROM (%dx%d of %dx%d padded) for rtl/sensor_emu.v, generated by scripts/make_rom.py "
                "(model/sensor_emu.py)\n" % (rom8.shape[1], rom8.shape[0], 1 << cb, 1 << rb))
        f.write("\n".join("%02x" % v for v in pad.ravel()) + "\n")
