"""Bit-accurate integer model of the whole pipeline (roadmap task 2.9). Golden reference #1 (vectorised).
Golden reference #2 is pipeline_ref.py (scalar loops, written independently); both must agree bit for bit
before either is used to judge RTL (checklist 3.2).

Frame-granular: every pixel of frame f is corrected with the coefficients as they were at the start of frame f;
write-backs land before frame f+1 reads them (one frame apart, see docs/design.md "hazards"). That is exactly
what the streaming RTL does, so a frame-vectorised model is exact for it.

Q formats (the RTL port comments copy this table):
  x        U14.0   raw sensor counts
  o        S12.OF  offset, counts, saturates at +-2047.x          (stored: S13, OF=1)
  g        U2.GF   gain, 1.0 = 1<<GF, clamped [GMIN, GMAX]        (stored: U13, GF=12)
  xo       S15.OF  (x<<OF) - o
  y        U14.YF  corrected pixel, YF=2 fractional bits, clamped to [0, (1<<(14+YF))-1]
  e        S?.YF   y - d, d = mean of valid 4-neighbours
  lim      U?.YF   frame-global error limit (from the previous frame's mean |e|)
  B        U14.BF  background model for the motion detector, BF=2
Rounding is round-half-up via (v + half) >> s on a two's-complement (floor) shift, matching Verilog >>>.
Border: window coordinates are clamped (edge replicate) on all four sides.
"""
from dataclasses import dataclass, field, replace
from typing import List, Optional, Tuple

import numpy as np

# ----------------------------------------------------------------------------------------------
# configuration (every field is mirrored by a CSR or a localparam in rtl/; docs/design.md lists where)
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Cfg:
    W: int = 320
    H: int = 240
    BITS: int = 14
    # NUC fixed-point
    OF: int = 1                 # 1 fractional bit: 30-bit coefficient word = 3 M10K at 1Kx10 (sweep: OF 0..6 equal)
    GF: int = 12
    YF: int = 2
    KO: int = 4                 # offset step = 2^-KO
    MUG_EXP: int = 28           # gain step = 2^-MUG_EXP per count^2
    OLIM: int = 2047            # |o| <= OLIM counts
    EMIN: int = 16              # error limit floor, counts
    EMAX: int = 512             # error limit ceiling, counts
    KLIM: int = 41              # lim = (sum|e| * KLIM) >> 20  ~ 3 * mean|e| for N = 76800
    ACT_WARM: int = 4           # activity is meaningless until the background has warmed up; gain learning stays on
    ACT_THR: int = 64           # learn gain only if (sum |y-B| >> 16) > ACT_THR   (moving camera)
    nuc_en: bool = True
    learn_en: bool = True       # freeze learning (CSR) when False
    LEARN_N: int = 256          # learning window: frames of active learning since the last coefficient reset, 0 = no
                                # limit. Static camera: quality peaks after ~25-400 frames, then the scene is absorbed
                                # (bug_log 19); a moving camera can run with 0.
    # bad pixels
    BP_T: int = 800             # outlier threshold, counts
    BP_ON: int = 8              # counter level that flags a pixel
    bp_en: bool = True
    # motion detector
    BF: int = 2
    KB: int = 7                 # steady-state background alpha = 2^-KB
    T_MASK: int = 400           # counts
    DET_WARM: int = 128         # frames before the mask/boxes are reported
    morph_en: bool = True
    NL: int = 16                # CCL label slots
    MAXOBJ: int = 16            # result slots
    MIN_AREA: int = 8

    @property
    def GMIN(self):
        return 1 << (self.GF - 1)               # gain 0.5

    @property
    def GMAX(self):
        return (2 << self.GF) - 1               # just under 2.0 (GF+1 bits)

    @property
    def YMAX(self):
        return (1 << (self.BITS + self.YF)) - 1

    @property
    def SHIFT_Y(self):
        return self.OF + self.GF - self.YF

    @property
    def SG(self):
        return self.MUG_EXP + self.YF + self.OF - self.GF

    @property
    def N(self):
        return self.W * self.H


RECIP = {1: 65536, 2: 32768, 3: 21845, 4: 16384}      # round(65536 / n); n = number of valid neighbours


def coef_word(c: "Cfg", s: "State"):
    """Coefficient RAM word {bpc[3:0], g[GF:0], o[11+OF:0]} as the RTL stores it (o two's complement)."""
    ob = 12 + c.OF
    gb = c.GF + 1
    return (s.bpc << (gb + ob)) | (s.g << ob) | (s.o & ((1 << ob) - 1))


def rshift_round(v, s):
    """(v + 2^(s-1)) >> s, floor shift (arithmetic). s may be <= 0 (then exact left shift)."""
    if s <= 0:
        return v << (-s)
    return (v + (1 << (s - 1))) >> s


def nb_win(a):
    """(8,H,W) neighbours, edge replicated. Order NW N NE W E SW S SE."""
    p = np.pad(a, 1, mode="edge")
    h, w = a.shape
    return np.stack([p[dy:dy + h, dx:dx + w] for dy in (0, 1, 2) for dx in (0, 1, 2) if (dy, dx) != (1, 1)])


IDX4 = (1, 3, 4, 6)     # N W E S


@dataclass
class State:
    o: np.ndarray
    g: np.ndarray
    bpc: np.ndarray
    B: np.ndarray
    lim_q: int
    act: int                 # previous-frame (sum|y-B|) >> 16 ; initial value large => gain learning on
    n: int                   # frames seen by the detector (saturating at 255)
    frame: int = 0
    lcnt: int = 0            # frames in which learning ran since the last coefficient reset (saturating at 0xFFFF)

    @staticmethod
    def init(c: Cfg):
        sh = (c.H, c.W)
        return State(o=np.zeros(sh, np.int64), g=np.full(sh, 1 << c.GF, np.int64), bpc=np.zeros(sh, np.int64),
                     B=np.zeros(sh, np.int64), lim_q=c.EMAX << c.YF, act=1 << 30, n=0)

    def reset_control(self, c: Cfg):
        """FRAME_RESET (checklist 1.8): re-arm per-frame control state. RAM contents stay."""
        self.lim_q = c.EMAX << c.YF
        self.act = 1 << 30
        self.n = 0
        self.frame = 0


@dataclass
class FrameOut:
    y14: np.ndarray          # corrected + bad-pixel-replaced, U14
    mask: np.ndarray         # final (post-morphology) motion mask, bool
    raw_mask: np.ndarray     # threshold output before morphology
    boxes: List[Tuple[int, int, int, int, int]]   # (xmin, ymin, xmax, ymax, area), finished order
    n_objects: int           # objects found (saturating 255)
    overflow: bool           # label table or result list overflowed
    det_valid: bool          # n >= DET_WARM at this frame
    lim_q: int               # limit used for this frame
    gain_en: bool
    bad: np.ndarray          # flags used this frame
    sum_abs_e: int
    sum_act: int
    learning: bool           # NUC learning ran this frame (learn_en, nuc_en and the window open)


# ----------------------------------------------------------------------------------------------
# NUC + bad pixels
# ----------------------------------------------------------------------------------------------


def nuc_frame(c: Cfg, s: State, x: np.ndarray):
    """Returns (y_out_q, bad, stats). Updates s.o, s.g, s.bpc, s.lim_q in place."""
    x = x.astype(np.int64)
    rail = (x <= 0) | (x >= (1 << c.BITS) - 1)
    bad = (s.bpc >= c.BP_ON) if c.bp_en else np.zeros_like(x, bool)
    if not c.nuc_en:
        yq = np.clip(x << c.YF, 0, c.YMAX)
        xo = (x << c.OF)
    else:
        xo = (x << c.OF) - s.o
        yq = np.clip(rshift_round(xo * s.g, c.SHIFT_Y), 0, c.YMAX)
    nb = nb_win(yq)
    vb = ~nb_win(bad)
    v4 = vb[list(IDX4)]
    cnt = v4.sum(0)
    ssum = (nb[list(IDX4)] * v4).sum(0)
    recip = np.select([cnt == 1, cnt == 2, cnt == 3, cnt == 4], [RECIP[1], RECIP[2], RECIP[3], RECIP[4]], 0)
    d = np.where(cnt > 0, (ssum * recip + 32768) >> 16, yq)
    e = yq - d
    abs_e = np.abs(e)
    sum_abs_e = int(abs_e[~bad].sum())
    lim = s.lim_q
    ec = np.clip(e, -lim, lim)
    gain_en = s.act > c.ACT_THR
    learning = c.learn_en and c.nuc_en and (c.LEARN_N == 0 or s.lcnt < c.LEARN_N)
    if learning:
        s.lcnt = min(s.lcnt + 1, 0xFFFF)
    upd = (~bad) & learning
    o_new, g_new = s.o, s.g
    if c.nuc_en:
        do = rshift_round(ec, c.YF + c.KO - c.OF)
        o_new = np.where(upd, np.clip(s.o + do, -(c.OLIM << c.OF), c.OLIM << c.OF), s.o)
        dg = rshift_round(ec * xo, c.SG)
        g_new = np.where(upd & gain_en, np.clip(s.g - dg, c.GMIN, c.GMAX), s.g)
    # bad-pixel counter
    if c.bp_en:
        valid8 = ~nb_win(bad)
        hi = np.where(valid8, nb, -1).max(0)
        lo = np.where(valid8, nb, c.YMAX + 1).min(0)
        anyv = valid8.any(0)
        tq = c.BP_T << c.YF
        outlier = (anyv & ((yq > hi + tq) | (yq < lo - tq))) | rail
        s.bpc = np.clip(s.bpc + np.where(outlier, 1, -1), 0, 15)
    s.o, s.g = o_new, g_new
    yout = np.where(bad, d, yq)
    # next-frame limit from this frame's mean |e|
    s.lim_q = int(np.clip((sum_abs_e * c.KLIM) >> 20, c.EMIN << c.YF, c.EMAX << c.YF))
    return yout, bad, dict(sum_abs_e=sum_abs_e, lim=lim, gain_en=gain_en, learning=learning)


# ----------------------------------------------------------------------------------------------
# motion detector
# ----------------------------------------------------------------------------------------------


def erode3(m):
    return nb_win(m).all(0) & m


def dilate3(m):
    return nb_win(m).any(0) | m


def morph_open_close(m):
    return erode3(dilate3(dilate3(erode3(m))))     # open (erode,dilate) then close (dilate,erode)


def detector_frame(c: Cfg, s: State, y14: np.ndarray):
    """Returns (raw_mask, sum_act). Updates s.B, s.n."""
    yb = y14.astype(np.int64) << c.BF
    if s.n == 0:
        diff = np.zeros_like(yb)
        newB = yb
    else:
        diff = np.abs(yb - s.B)
        sh = min(c.KB, int(np.ceil(np.log2(s.n + 1))))
        newB = s.B + rshift_round(yb - s.B, sh)
    raw_mask = diff > (c.T_MASK << c.BF)
    sum_act = int((diff >> c.BF).sum())
    s.B = newB
    s.n = min(s.n + 1, 255)
    return raw_mask, sum_act


# ----------------------------------------------------------------------------------------------
# streaming single-pass connected-component bounding boxes (4-connectivity). This function IS the hardware spec.
# ----------------------------------------------------------------------------------------------


def ccl_boxes(c: Cfg, mask: np.ndarray):
    """Raster-order single pass. Label slots NL, results MAXOBJ. Returns (boxes, n_objects, overflow).

    Slot freeing rule (so that stale label-buffer references can never alias a reused slot):
      * a slot merged into another becomes reusable only at the start of the line after the NEXT line;
      * a slot whose object was not touched during a line is finished at the end of that line and reusable at once.
    Finished objects with area < MIN_AREA are dropped (not listed, not counted). n_objects counts the rest
    (saturating at 255); if the result list (MAXOBJ) is full the object is still counted and overflow is set.
    """
    H, W, NL = c.H, c.W, c.NL
    used = [False] * NL
    bb = [None] * NL            # [xmin, ymin, xmax, ymax, area]
    alias = list(range(NL))
    touched = [False] * NL
    free_at = [0] * NL          # slot reusable when line >= free_at[slot] (merged slots)
    prev = [-1] * W             # previous line's labels (-1 = background)
    cur = [-1] * W
    results = []
    n_obj = 0
    overflow = False

    def finish(k):
        nonlocal n_obj, overflow
        a = bb[k]
        if a[4] >= c.MIN_AREA:
            n_obj = min(n_obj + 1, 255)
            if len(results) < c.MAXOBJ:
                results.append(tuple(a))
            else:
                overflow = True
        used[k] = False
        alias[k] = k

    for r in range(H):
        for k in range(NL):
            touched[k] = False
        for col in range(W):
            if not mask[r, col]:
                cur[col] = -1
                continue
            n_l = alias[prev[col]] if prev[col] >= 0 else -1
            w_l = cur[col - 1] if col > 0 else -1
            w_l = alias[w_l] if w_l >= 0 else -1
            if n_l < 0 and w_l < 0:
                slot = next((k for k in range(NL) if not used[k] and free_at[k] <= r), -1)
                if slot < 0:
                    overflow = True
                    cur[col] = -1
                    continue
                used[slot] = True
                alias[slot] = slot
                bb[slot] = [col, r, col, r, 1]
                lab = slot
            elif n_l >= 0 and w_l >= 0 and n_l != w_l:
                lo, hi = min(n_l, w_l), max(n_l, w_l)
                a, b = bb[lo], bb[hi]
                bb[lo] = [min(a[0], b[0], col), min(a[1], b[1]), max(a[2], b[2], col), max(a[3], b[3], r), a[4] + b[4] + 1]
                for k in range(NL):
                    if alias[k] == hi:
                        alias[k] = lo
                used[hi] = False
                free_at[hi] = r + 2
                lab = lo
            else:
                lab = n_l if n_l >= 0 else w_l
                a = bb[lab]
                bb[lab] = [min(a[0], col), a[1], max(a[2], col), r, a[4] + 1]
                touched[lab] = True
            touched[lab] = True
            cur[col] = lab
        # end of line: finish untouched objects
        for k in range(NL):
            if used[k] and not touched[k]:
                finish(k)
        prev, cur = cur, [-1] * W
    for k in range(NL):
        if used[k]:
            finish(k)
    return results, n_obj, overflow


# ----------------------------------------------------------------------------------------------
# whole pipeline
# ----------------------------------------------------------------------------------------------


def frame_step(c: Cfg, s: State, x: np.ndarray) -> FrameOut:
    yq, bad, st = nuc_frame(c, s, x)
    y14 = np.clip(rshift_round(yq, c.YF), 0, (1 << c.BITS) - 1)
    raw_mask, sum_act = detector_frame(c, s, y14)
    s.act = (sum_act >> 16) if s.n > c.ACT_WARM else (1 << 30)
    valid = s.n > c.DET_WARM                 # s.n already counts this frame
    m = morph_open_close(raw_mask) if c.morph_en else raw_mask
    if valid:
        boxes, n_obj, ovf = ccl_boxes(c, m)
    else:
        m = np.zeros_like(m)
        boxes, n_obj, ovf = [], 0, False
    s.frame += 1
    return FrameOut(y14.astype(np.uint16), m, raw_mask, boxes, n_obj, ovf, valid, st["lim"], st["gain_en"], bad,
                    st["sum_abs_e"], sum_act, st["learning"])


def run(c: Cfg, frames: np.ndarray, state: Optional[State] = None):
    s = State.init(c) if state is None else state
    return [frame_step(c, s, f) for f in frames], s
