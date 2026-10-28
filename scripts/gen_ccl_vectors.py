"""Vectors for tb/ccl_tb.v from the streaming specification pipeline_int.ccl_boxes().

Writes into --out (one hex word per line):
  mask.hex  T*H*W   mask bit
  hdr.hex   T       {n_obj[7:0], cnt[4:0], ovf} as 14-bit "%04x"
  rec.hex   T*16    53-bit box records {area[16:0], ymax[8:0], xmax[8:0], ymin[8:0], xmin[8:0]} "%014x" (unused = 0)
Modes:
  blobs  : a few random rectangles with ragged holes (merges), some touching borders
  dense  : many small objects (exhausts the 16 label slots and the 16 result slots)
  noise  : random speckle at 12 % density (hundreds of tiny objects, overflow, merges)
  mixed  : alternates the above per frame, plus empty and full frames
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from model import pipeline_int as pi  # noqa: E402


def directed(H, W, kind, dx=0):
    """Hand-built masks for hazards random data rarely hits."""
    m = np.zeros((H, W), bool)
    if kind == "stale":
        # C starts at (0,9+dx) -> slot 0. B starts at (1,4+dx) -> slot 1. Row 2 extends B right until it hits C's
        # column and MERGES slot 1 into slot 0, leaving stale label-1 cells (2,4..8) in the line buffer.
        # Row 3 starts an isolated pixel at (3,1+dx): a correct design must NOT hand it slot 1 yet (blk), or the
        # stale cells (2,4..8) would join it to the pixels of row 3.
        m[0, 9 + dx] = True
        m[1, 4 + dx:6 + dx] = True
        m[1, 9 + dx] = True
        m[2, 4 + dx:10 + dx] = True
        m[3, 1 + dx] = True
        m[3, 4 + dx:9 + dx] = True
    elif kind == "stale_same_row":
        m[0, 9 + dx] = True
        m[1, 4 + dx:6 + dx] = True
        m[1, 9 + dx] = True
        m[1, 14 + dx:17 + dx] = True
        m[2, 4 + dx:10 + dx] = True
        m[2, 14 + dx:17 + dx] = True
        m[2, 12 + dx] = True
    elif kind == "wrap":                      # last column of row r and first column of row r+1: NOT connected
        for r in range(0, H - 1, 4):
            m[r, W - 1] = True
            m[r + 1, 0] = True
    elif kind == "wide":                      # 20 simultaneous objects on one row: label slots run out, results do not
        m[0, 0:W:2] = True
        m[0, :] &= (np.arange(W) < 40)
    elif kind == "checker":                   # isolated pixels everywhere: > 255 objects per frame
        r, q = np.mgrid[0:H, 0:W]
        m = ((r + q) % 2 == 0)
    elif kind == "bottom_row":
        m[H - 1, :] = True
    elif kind == "top_row":
        m[0, 3:7] = True
        m[0, 10] = True
    return m


def make_mask(rng, H, W, mode):
    m = np.zeros((H, W), bool)
    if mode.startswith("dir:"):
        kind, _, dx = mode[4:].partition(":")
        return directed(H, W, kind, int(dx or 0))
    if mode == "blobs":
        for _ in range(rng.integers(1, 8)):
            y0, x0 = rng.integers(0, H - 2), rng.integers(0, W - 2)
            m[y0:y0 + rng.integers(1, max(2, H // 3)), x0:x0 + rng.integers(1, max(2, W // 3))] = True
        m &= rng.random(m.shape) < 0.9
    elif mode == "dense":
        for _ in range(rng.integers(20, 40)):
            y0, x0 = rng.integers(0, H - 1), rng.integers(0, W - 1)
            m[y0:y0 + rng.integers(1, 3), x0:x0 + rng.integers(1, 3)] = True
    elif mode == "noise":
        m = rng.random((H, W)) < 0.12
    elif mode == "empty":
        pass
    elif mode == "full":
        m[:] = True
    elif mode == "comb":                        # many vertical teeth joined by a bar at the bottom: late merges
        for x in range(1, W - 1, 3):
            m[2:H - 3, x] = True
        m[H - 3, 1:W - 1] = True
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--W", type=int, default=40)
    ap.add_argument("--H", type=int, default=30)
    ap.add_argument("--T", type=int, default=24)
    ap.add_argument("--mode", default="mixed")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--min_area", type=int, default=1)
    a = ap.parse_args()
    c = pi.Cfg(W=a.W, H=a.H, MIN_AREA=a.min_area)
    rng = np.random.default_rng(a.seed)
    os.makedirs(a.out, exist_ok=True)
    order = ["blobs", "dense", "noise", "empty", "comb", "full", "blobs", "dense"]
    if a.mode == "directed":
        order = ["dir:stale:0", "dir:stale:3", "dir:stale_same_row:0", "dir:stale_same_row:2", "dir:wrap", "dir:wide",
                 "dir:bottom_row", "dir:top_row", "full", "full", "dir:checker", "dir:stale:1", "dir:bottom_row", "dir:wrap",
                 "empty", "dir:top_row"]
    mk, hk, rk = [], [], []
    stats = dict(ovf=0, maxcnt=0, merges=0)
    for t in range(a.T):
        mode = order[t % len(order)] if a.mode in ("mixed", "directed") else a.mode
        m = make_mask(rng, a.H, a.W, mode)
        res, n_obj, ovf = pi.ccl_boxes(c, m)
        mk += ["%x" % int(v) for v in m.ravel()]
        hk.append("%04x" % ((n_obj << 6) | (len(res) << 1) | int(ovf)))
        for i in range(16):
            if i < len(res):
                xmin, ymin, xmax, ymax, area = res[i]
                rk.append("%014x" % ((area << 36) | (ymax << 27) | (xmax << 18) | (ymin << 9) | xmin))
            else:
                rk.append("%014x" % 0)
        stats["ovf"] += int(ovf)
        stats["maxcnt"] = max(stats["maxcnt"], len(res))
    for name, data in (("mask", mk), ("hdr", hk), ("rec", rk)):
        with open(os.path.join(a.out, name + ".hex"), "w", newline="\n") as f:
            f.write("\n".join(data) + "\n")
    print("wrote %d frames of %dx%d (%s) to %s; frames with overflow: %d; max listed: %d"
          % (a.T, a.W, a.H, a.mode, a.out, stats["ovf"], stats["maxcnt"]))


if __name__ == "__main__":
    main()
