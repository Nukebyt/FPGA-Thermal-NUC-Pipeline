"""Golden reference #2: scalar, per-pixel loops, written independently of pipeline_int.py (checklist 3.2).
Slow on purpose (pure Python); use small Cfg(W, H) for cross-checks. Shares only the Cfg dataclass, State layout
and the RECIP table. Where pipeline_int is vectorised and edge-pads arrays, this model clamps indices explicitly,
computes every sum with explicit loops and rounds with python-int arithmetic (no numpy shifts).
CCL is checked against scipy.ndimage.label (4-connectivity) instead of a second streaming implementation:
a different algorithm gives a stronger cross-check of the boxes (see boxes_ref)."""
import math

import numpy as np
from scipy import ndimage as ndi

from .pipeline_int import Cfg, State, RECIP


def _rs(v, s):
    """round-half-up right shift for python ints; s<=0 means left shift"""
    if s <= 0:
        return v * (1 << (-s))
    return (v + (1 << (s - 1))) // (1 << s)       # floor division == arithmetic shift for ints


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def frame_ref(c: Cfg, s: State, x):
    """One frame. Returns dict(y14, raw_mask, mask, valid, ...). Mutates s like pipeline_int.frame_step."""
    H, W = c.H, c.W
    s_o = s.o.tolist()
    s_g = s.g.tolist()
    s_b = s.bpc.tolist()
    s_B = s.B.tolist()
    xs = [[int(x[r][cc]) for cc in range(W)] for r in range(H)]
    full = (1 << c.BITS) - 1
    bad = [[(s_b[r][cc] >= c.BP_ON) if c.bp_en else False for cc in range(W)] for r in range(H)]
    # 1. correct
    xo = [[0] * W for _ in range(H)]
    yq = [[0] * W for _ in range(H)]
    for r in range(H):
        for cc in range(W):
            if c.nuc_en:
                xo[r][cc] = (xs[r][cc] * (1 << c.OF)) - s_o[r][cc]
                yq[r][cc] = _clamp(_rs(xo[r][cc] * s_g[r][cc], c.SHIFT_Y), 0, c.YMAX)
            else:
                xo[r][cc] = xs[r][cc] * (1 << c.OF)
                yq[r][cc] = _clamp(xs[r][cc] * (1 << c.YF), 0, c.YMAX)

    def at(a, r, cc):
        return a[_clamp(r, 0, H - 1)][_clamp(cc, 0, W - 1)]

    # 2. per-pixel window math
    d = [[0] * W for _ in range(H)]
    e = [[0] * W for _ in range(H)]
    outl = [[False] * W for _ in range(H)]
    sum_abs_e = 0
    for r in range(H):
        for cc in range(W):
            tot, cnt = 0, 0
            for dr, dc in ((-1, 0), (0, -1), (0, 1), (1, 0)):
                if not at(bad, r + dr, cc + dc):
                    tot += at(yq, r + dr, cc + dc)
                    cnt += 1
            d[r][cc] = _rs(tot * RECIP[cnt], 16) if cnt else yq[r][cc]
            e[r][cc] = yq[r][cc] - d[r][cc]
            if not bad[r][cc]:
                sum_abs_e += abs(e[r][cc])
            hi, lo, anyv = -1, c.YMAX + 1, False
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if (dr or dc) and not at(bad, r + dr, cc + dc):
                        v = at(yq, r + dr, cc + dc)
                        hi, lo, anyv = max(hi, v), min(lo, v), True
            tq = c.BP_T * (1 << c.YF)
            rail = xs[r][cc] <= 0 or xs[r][cc] >= full
            outl[r][cc] = (anyv and (yq[r][cc] > hi + tq or yq[r][cc] < lo - tq)) or rail
    gain_en = s.act > c.ACT_THR
    lim = s.lim_q
    # learning window: count frames in which learning ran; stop after LEARN_N of them (0 = never stop)
    window_open = True if c.LEARN_N == 0 else s.lcnt < c.LEARN_N
    learning = bool(c.nuc_en and c.learn_en and window_open)
    if learning:
        s.lcnt = _clamp(s.lcnt + 1, 0, 65535)
    # 3. update
    for r in range(H):
        for cc in range(W):
            if learning and not bad[r][cc]:
                ec = _clamp(e[r][cc], -lim, lim)
                s_o[r][cc] = _clamp(s_o[r][cc] + _rs(ec, c.YF + c.KO - c.OF), -(c.OLIM << c.OF), c.OLIM << c.OF)
                if gain_en:
                    s_g[r][cc] = _clamp(s_g[r][cc] - _rs(ec * xo[r][cc], c.SG), c.GMIN, c.GMAX)
            if c.bp_en:
                s_b[r][cc] = _clamp(s_b[r][cc] + (1 if outl[r][cc] else -1), 0, 15)
    s.o = np.array(s_o, np.int64)
    s.g = np.array(s_g, np.int64)
    s.bpc = np.array(s_b, np.int64)
    s.lim_q = _clamp((sum_abs_e * c.KLIM) // (1 << 20), c.EMIN << c.YF, c.EMAX << c.YF)
    # 4. output + detector
    y14 = [[_clamp(_rs(d[r][cc] if bad[r][cc] else yq[r][cc], c.YF), 0, full) for cc in range(W)] for r in range(H)]
    sum_act = 0
    raw = [[False] * W for _ in range(H)]
    for r in range(H):
        for cc in range(W):
            yb = y14[r][cc] * (1 << c.BF)
            if s.n == 0:
                s_B[r][cc] = yb
            else:
                diff = abs(yb - s_B[r][cc])
                raw[r][cc] = diff > c.T_MASK * (1 << c.BF)
                sum_act += diff // (1 << c.BF)
                sh = min(c.KB, math.ceil(math.log2(s.n + 1)))
                s_B[r][cc] = s_B[r][cc] + _rs(yb - s_B[r][cc], sh)
    s.B = np.array(s_B, np.int64)
    s.n = min(s.n + 1, 255)
    s.act = (sum_act >> 16) if s.n > c.ACT_WARM else (1 << 30)
    valid = s.n > c.DET_WARM

    def erode(m):
        return [[all(at(m, r + dr, cc + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)) for cc in range(W)] for r in range(H)]

    def dilate(m):
        return [[any(at(m, r + dr, cc + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)) for cc in range(W)] for r in range(H)]

    m = erode(dilate(dilate(erode(raw)))) if c.morph_en else raw
    if not valid:
        m = [[False] * W for _ in range(H)]
    s.frame += 1
    return dict(y14=np.array(y14, np.uint16), raw_mask=np.array(raw), mask=np.array(m), valid=valid,
                sum_abs_e=sum_abs_e, sum_act=sum_act, bad=np.array(bad), learning=learning)


def boxes_ref(c: Cfg, mask):
    """Boxes via scipy 4-connected labelling, sorted. Comparable to pipeline_int.ccl_boxes only when nothing
    overflows (the streaming pass finishes objects in a different order, so compare sorted)."""
    lab, n = ndi.label(mask)           # default structure = 4-connectivity
    out = []
    for i, sl in enumerate(ndi.find_objects(lab), start=1):
        area = int((lab[sl] == i).sum())
        if area >= c.MIN_AREA:
            out.append((sl[1].start, sl[0].start, sl[1].stop - 1, sl[0].stop - 1, area))
    return sorted(out)
