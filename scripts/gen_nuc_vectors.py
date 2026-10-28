"""Vectors for tb/nuc_core_tb.v from the integer golden model (model/pipeline_int.py).

Writes (one hex word per line) into --out:
  x.hex     T*H*W   raw samples, 4 hex digits
  y.hex     T*H*W   expected corrected+replaced y14, 4 digits
  bad.hex   T*H*W   expected bad flag used this frame, 1 digit
  ctl.hex   T       per-frame control word (1 digit): bit0 gain_en, bit1 nuc_en, bit2 learn_en, bit3 bp_en
  coef.hex  T*H*W   expected coefficient word after the frame {bpc[3:0], g[12:0], o[13:0]}, 8 digits
  fr.hex    T       per frame: sum|e| (10 digits) and the limit used (3 digits), one line "sum lim"
Plain ASCII output (checklist 3.9). Modes:
  scene  : synthetic thermal scene + sensor noise (dead/hot pixels at ~1 %) -- realistic, bad flags appear
  random : uniform random 14-bit data every frame -- saturation, rails, huge errors, worst-case entropy
  sat    : checkerboard 1 / 16382 (a correction the coefficient ranges cannot provide), use with --bp_en 0 --gain_all 1
           and many frames: drives every coefficient into its clamps (offset +-2047, gain 0.5 / 2.0)
  flat   : constant 5000 +-1 noise -- tiny |e|, exercises the lower error-limit clamp
  cluster: scene + stuck-at-rail pixels arranged so some pixels have 0..4 bad neighbours (incl. corners/edges)
--toggle randomises nuc_en / learn_en / bp_en frame by frame (runtime CSR changes).
--learn_n N: learning window (frames that learn after a coefficient reset; 0 = no limit).
--coef_reset_at k: coefficient reset (KEY1) before frame k: o, g, bpc back to identity, window restarts.
  lrn.hex   T       per frame: 1 if learning ran
"""
import argparse
import os
import sys
from dataclasses import replace

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from model import noise_model as nm, scenes, pipeline_int as pi  # noqa: E402


def frames_for(c, T, mode, seed, preset):
    if mode == "flat":
        rng = np.random.default_rng(seed)
        return (5000 + rng.integers(-1, 2, size=(T, c.H, c.W))).astype(np.uint16)
    if mode == "sat":
        r, q = np.mgrid[0:c.H, 0:c.W]
        f = np.where((r + q) % 2 == 0, 1, 16382).astype(np.int64)
        return np.broadcast_to(f, (T, c.H, c.W)).astype(np.uint16).copy()
    if mode == "cluster":
        scene, gt, _ = scenes.make_scene(T, shape=(c.H, c.W), seed=seed, n_blobs=2)
        raw, _ = nm.add_noise(scene, nm.preset(preset, dead_rate=0.0, hot_rate=0.0, seed=seed))
        raw = raw.copy()
        H, W = c.H, c.W
        for (r0, c0) in [(10, 10), (H - 2, W - 2), (0, 0), (5, W - 1), (H - 1, 20)]:   # plus shapes, corner, edges
            for (dr, dq) in [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)]:
                rr, qq = r0 + dr, c0 + dq
                if 0 <= rr < H and 0 <= qq < W:
                    raw[:, rr, qq] = 0
        raw[:, 0, 1] = 16383
        raw[:, 1, 0] = 16383
        raw[:, 20, 5:8] = 16383                      # a short run of bad pixels
        for dr in (-1, 0, 1):                        # healthy pixel (22, 30) ringed by 8 bad ones
            for dq in (-1, 0, 1):
                if dr or dq:
                    raw[:, 22 + dr, 30 + dq] = 0
        return raw
    if mode == "random":
        rng = np.random.default_rng(seed)
        f = rng.integers(0, 1 << c.BITS, size=(T, c.H, c.W))
        f[:, ::7, ::5] = 0                       # rails
        f[:, 3::11, 2::9] = (1 << c.BITS) - 1
        return f.astype(np.uint16)
    scene, gt, _ = scenes.make_scene(T, shape=(c.H, c.W), seed=seed, n_blobs=2)
    raw, _ = nm.add_noise(scene, nm.preset(preset, dead_rate=0.01, hot_rate=0.01, seed=seed))
    return raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--W", type=int, default=48)
    ap.add_argument("--H", type=int, default=36)
    ap.add_argument("--T", type=int, default=16)
    ap.add_argument("--mode", default="scene")
    ap.add_argument("--seed", type=int, default=2)
    ap.add_argument("--preset", default="severe")
    ap.add_argument("--nuc_en", type=int, default=1)
    ap.add_argument("--learn_en", type=int, default=1)
    ap.add_argument("--bp_en", type=int, default=1)
    ap.add_argument("--toggle", type=int, default=0)
    ap.add_argument("--gain_all", type=int, default=0)
    ap.add_argument("--klim", type=int, default=41)
    ap.add_argument("--learn_n", type=int, default=0, help="learning window (0 = no limit); TB parameter LEARN_N")
    ap.add_argument("--coef_reset_at", type=int, default=-1, help="coefficient reset before this frame; TB CRST")
    a = ap.parse_args()
    c0 = pi.Cfg(W=a.W, H=a.H, nuc_en=bool(a.nuc_en), learn_en=bool(a.learn_en), bp_en=bool(a.bp_en), KLIM=a.klim,
                  LEARN_N=a.learn_n)
    c = c0
    os.makedirs(a.out, exist_ok=True)
    frames = frames_for(c, a.T, a.mode, a.seed, a.preset)
    rng = np.random.default_rng(a.seed + 100)
    gain_bits = rng.integers(0, 2, size=a.T)
    gain_bits[:3] = 1
    if a.gain_all:
        gain_bits[:] = 1
    tog = np.random.default_rng(a.seed + 200).integers(0, 2, size=(a.T, 3))
    tog[:4] = 1                                    # let it learn first, then start switching
    s = pi.State.init(c)
    fx, fy, fb, fc, fco, ffr, flr = [], [], [], [], [], [], []
    for t in range(a.T):
        if t == a.coef_reset_at:
            # nuc_core coef_reset: RAM back to {bpc 0, g 1.0, o 0} and the learning window restarts; the error
            # limit (a register outside the RAM) keeps its value
            fresh = pi.State.init(c)
            s.o, s.g, s.bpc, s.lcnt = fresh.o, fresh.g, fresh.bpc, 0
        s.act = (1 << 30) if gain_bits[t] else 0
        c = c0 if not a.toggle else replace(c0, nuc_en=bool(tog[t, 0]), learn_en=bool(tog[t, 1]), bp_en=bool(tog[t, 2]))
        x = frames[t]
        yout, bad, st = pi.nuc_frame(c, s, x)
        y14 = np.clip(pi.rshift_round(yout, c.YF), 0, (1 << c.BITS) - 1)
        coef = pi.coef_word(c, s)
        fx += ["%04x" % v for v in x.ravel()]
        fy += ["%04x" % v for v in y14.ravel()]
        fb += ["%x" % int(v) for v in bad.ravel()]
        fc.append("%x" % (int(gain_bits[t]) | (int(c.nuc_en) << 1) | (int(c.learn_en) << 2) | (int(c.bp_en) << 3)))
        fco += ["%08x" % int(v) for v in coef.ravel()]
        ffr.append("%010x %03x" % (st["sum_abs_e"], st["lim"]))
        flr.append("%x" % int(st["learning"]))
    for name, data in (("x", fx), ("y", fy), ("bad", fb), ("ctl", fc), ("coef", fco), ("fr", ffr), ("lrn", flr)):
        with open(os.path.join(a.out, name + ".hex"), "w", newline="\n") as f:
            f.write("\n".join(data) + "\n")
    print("wrote %d frames of %dx%d (%s) to %s; bad pixels in last frame: %d; frames with gain_en: %d; "
          "frames that learned: %d" % (a.T, c.W, c.H, a.mode, a.out, int(bad.sum()), int(gain_bits.sum()),
                                       flr.count("1")))


if __name__ == "__main__":
    main()
