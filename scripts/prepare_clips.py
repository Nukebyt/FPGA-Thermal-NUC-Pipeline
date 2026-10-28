"""Turn a CDnet thermal sequence into a raw clip for the frame feeder (roadmap 3b.1).

  python scripts/prepare_clips.py --seq park --start 0 --frames 600
  python scripts/prepare_clips.py --seq corridor --start 1000 --frames 900 --out data/clips

Writes <out>/<seq>_<start>_<frames>.u8   frames concatenated, 320x240, 8 bit, raster order (exactly what the frame store holds: the
                                          emulator makes counts = 3000 + 16 * pixel, the same convention as model/datasets.py)
       <out>/<seq>_<start>_<frames>.gt.u8 per frame 320x240: 0 background, 1 moving object, 2 not scored (CDnet labels 85 / 170 / outside
                                          the temporal ROI) - for scoring the board's boxes against the ground truth
The frames are scaled and cropped like model.datasets.load_cdnet (the model and the board see the same pixels).
Play them with host/feed_clip.py (laptop -> board over Ethernet) or `frame_feeder play clip.u8` on the board itself."""
import argparse
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from model import datasets as D  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq", required=True, choices=D.CDNET_THERMAL)
    ap.add_argument("--root", default=os.path.join(ROOT, "data", "cdnet", "thermal"))
    ap.add_argument("--start", type=int, default=0, help="first frame (0-based index into the sequence)")
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "clips"))
    a = ap.parse_args()
    d = os.path.join(a.root, a.seq)
    ins = sorted(glob.glob(os.path.join(d, "input", "in*.jpg")))[a.start:a.start + a.frames]
    if not ins:
        sys.exit("no frames under %s/input" % d)
    t0, t1 = 1, 10 ** 9
    troi = os.path.join(d, "temporalROI.txt")
    if os.path.exists(troi):
        t0, t1 = [int(v) for v in open(troi).read().split()[:2]]
    frames, gts = [], []
    for p in ins:
        idx = int(os.path.basename(p)[2:-4])
        frames.append(D._fit(cv2.imread(p, cv2.IMREAD_GRAYSCALE), cv2.INTER_AREA))
        g = cv2.imread(os.path.join(d, "groundtruth", "gt%06d.png" % idx), cv2.IMREAD_GRAYSCALE)
        if g is None or not (t0 <= idx <= t1):
            gts.append(np.full((D.H, D.W), 2, np.uint8))
        else:
            g = D._fit(g, cv2.INTER_NEAREST)
            m = np.zeros((D.H, D.W), np.uint8)
            m[g == 255] = 1
            m[(g == 85) | (g == 170)] = 2
            gts.append(m)
    os.makedirs(a.out, exist_ok=True)
    base = os.path.join(a.out, "%s_%d_%d" % (a.seq, a.start, len(ins)))
    np.stack(frames).astype(np.uint8).tofile(base + ".u8")
    np.stack(gts).astype(np.uint8).tofile(base + ".gt.u8")
    print("wrote %s.u8 (%d frames, %.1f MB) and .gt.u8; pixel range %d..%d; frames %d..%d of the sequence"
          % (base, len(ins), len(ins) * D.H * D.W / 1e6, min(f.min() for f in frames), max(f.max() for f in frames), a.start, a.start + len(ins) - 1))


if __name__ == "__main__":
    main()
