"""Vectors for tb/thermal_sys_feed_tb.v: two full-size 8-bit frames A and B for the frame store, as .npy (for the
checker) and as 32-bit little-endian words, one per line (for $readmemh). Both have texture on every row and column
and differ almost everywhere, so a frame that mixes them cannot pass for either."""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from model import sensor_emu as se  # noqa: E402


def frame(seed, H=240, W=320):
    rs = np.random.RandomState(seed)
    y, x = np.mgrid[0:H, 0:W]
    base = (96 + 70 * np.sin(x / (23.0 + seed)) + 50 * np.cos(y / (17.0 + 2 * seed))).astype(np.int64)
    return np.clip(base + rs.randint(-30, 31, (H, W)), 0, 255).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    nl = chr(10)
    for name, seed in (("A", 1), ("B", 2)):
        f = frame(seed)
        np.save(os.path.join(a.out, name + ".npy"), f)
        with open(os.path.join(a.out, name + ".hex"), "w", newline=nl) as fh:
            fh.write(nl.join("%08x" % int(v) for v in se.pack_words(f)) + nl)
    A, B = np.load(os.path.join(a.out, "A.npy")), np.load(os.path.join(a.out, "B.npy"))
    print("wrote A and B (%d levels / %d levels); %.1f %% of the pixels differ" % (len(np.unique(A)), len(np.unique(B)), 100.0 * (A != B).mean()))


if __name__ == "__main__":
    main()
