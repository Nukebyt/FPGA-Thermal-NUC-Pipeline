"""Task 2.9 (real footage): CDnet 2014 thermal through the bit-accurate pipeline (model/pipeline_int.py, which the
RTL matches bit for bit). Per sequence and noise preset, three conditions on the same frames:

  clean      : the CDnet frames as they are (NUC and bad-pixel repair off)
  noisy      : + simulated sensor non-uniformity (noise_model preset), NUC off
  noisy+NUC  : + simulated non-uniformity, full pipeline (NUC + bad-pixel repair)

Scored like CDnet: post-morphology motion mask vs ground truth, pixel level, only inside the spatial ROI and the
temporal ROI, 'unknown' pixels excluded. Each clip starts WARM frames before the first scored frame so the
background (and the NUC) have warmed up; the first scored frame must also be past Cfg.DET_WARM.

  python scripts/eval_cdnet.py                    # all 5 sequences, typical + severe, 600 scored frames each
  python scripts/eval_cdnet.py --seq park --presets typical --scored 200
Writes docs/results/cdnet_eval.md and one montage PNG per sequence (docs/results/cdnet_<seq>.png)."""
import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from model import datasets as D, metrics as M, noise_model as nm, pipeline_int as P  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
CDNET = os.path.join(ROOT, "data", "cdnet", "thermal")
OUT = os.path.join(ROOT, "docs", "results")


def first_scored(seq):
    a = open(os.path.join(CDNET, seq, "temporalROI.txt")).read().split()
    return int(a[0])            # 1-based frame number


def run(c, frames):
    s = P.State.init(c)
    masks, ys = [], []
    for f in frames:
        o = P.frame_step(c, s, f)
        masks.append(o.mask)
        ys.append(o.y14)
    return np.stack(masks), ys


def to8(img, lo, hi):
    return np.clip((np.asarray(img, np.float64) - lo) * 255.0 / max(hi - lo, 1), 0, 255).astype(np.uint8)


def montage(path, scene, raw, ynuc, mask, gt, valid):
    """clean | noisy | noisy+NUC | mask vs GT (green = hit, red = false alarm, blue = miss)."""
    lo, hi = np.percentile(scene, [1, 99])
    pan = [to8(scene, lo, hi), to8(raw, lo, hi), to8(ynuc, lo, hi)]
    pan = [cv2.cvtColor(p, cv2.COLOR_GRAY2BGR) for p in pan]
    m = np.zeros(scene.shape + (3,), np.uint8)
    m[~valid] = (60, 60, 60)
    m[mask & gt & valid] = (0, 200, 0)
    m[mask & ~gt & valid] = (0, 0, 255)
    m[~mask & gt & valid] = (255, 80, 0)
    row = np.concatenate([np.pad(p, ((0, 0), (0, 4), (0, 0)), constant_values=255) for p in pan] + [m], axis=1)
    cv2.imwrite(path, row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq", nargs="*", default=list(D.CDNET_THERMAL))
    ap.add_argument("--presets", nargs="*", default=["typical", "severe"])
    ap.add_argument("--scored", type=int, default=600, help="scored frames per sequence")
    ap.add_argument("--warm", type=int, default=300, help="frames before the first scored frame")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    assert a.warm > P.Cfg().DET_WARM, "warm-up must cover DET_WARM"

    c_off = P.Cfg(nuc_en=False, bp_en=False)
    c_on = P.Cfg()
    rows = []
    for seq in a.seq:
        t0 = first_scored(seq)
        start = max(0, t0 - 1 - a.warm)
        scene, gt, valid, fe = D.load_cdnet(CDNET, seq, max_frames=(t0 - 1 - start) + a.scored, start=start)
        if fe <= c_on.DET_WARM:
            print(f"{seq}: only {fe} warm-up frames available (< DET_WARM {c_on.DET_WARM}); scoring from DET_WARM")
            fe = c_on.DET_WARM + 1
        sl = slice(fe, None)
        clean_in = np.round(scene).astype(np.uint16)
        tic = time.time()
        m_clean, _ = run(c_off, clean_in)
        r = M.prf(m_clean[sl], gt[sl], valid[sl])
        rows.append((seq, "-", "clean", r))
        for pn in a.presets:
            raw, _ = nm.add_noise(scene, pn, seed=a.seed)
            m_noisy, _ = run(c_off, raw)
            m_nuc, ys = run(c_on, raw)
            rows.append((seq, pn, "noisy", M.prf(m_noisy[sl], gt[sl], valid[sl])))
            rows.append((seq, pn, "noisy+NUC", M.prf(m_nuc[sl], gt[sl], valid[sl])))
            if pn == a.presets[-1]:
                # montage on the scored frame with the most ground-truth motion
                k = fe + int(np.argmax((gt[sl] & valid[sl]).sum(axis=(1, 2))))
                montage(os.path.join(OUT, f"cdnet_{seq}.png"), scene[k], raw[k], ys[k], m_nuc[k], gt[k], valid[k])
        n = len(scene) - fe
        print(f"{seq}: frames {start + 1}..{start + len(scene)}, scored {n}, {time.time() - tic:.0f} s", flush=True)
        for row in rows:
            if row[0] == seq:
                print("   %-8s %-10s F1 %.3f  P %.3f  R %.3f  FAR %.5f" % (row[1], row[2], row[3]["f1"],
                      row[3]["precision"], row[3]["recall"], row[3]["far"]), flush=True)

    os.makedirs(OUT, exist_ok=True)
    L = ["# CDnet 2014 thermal through the bit-accurate pipeline", "",
         "Generated by `scripts/eval_cdnet.py` (args: `%s`)." % " ".join(sys.argv[1:]), "",
         "Pixel-level scores of the final (post-morphology) motion mask, CDnet rules: spatial ROI, temporal ROI, "
         "'unknown' excluded. %d frames of warm-up before the first scored frame, up to %d scored frames per "
         "sequence. Detector: running-average background, T_MASK = %d counts (= %d grey levels of the 8-bit "
         "input), 3x3 open + close." % (a.warm, a.scored, c_on.T_MASK, c_on.T_MASK // 16), "",
         "| sequence | noise | condition | F1 | precision | recall | false-alarm rate |",
         "|---|---|---|---|---|---|---|"]
    for seq, pn, cond, r in rows:
        L.append("| %s | %s | %s | %.3f | %.3f | %.3f | %.5f |" % (seq, pn, cond, r["f1"], r["precision"],
                                                                   r["recall"], r["far"]))
    L += ["", "Montages (`cdnet_<seq>.png`): clean | noisy (%s) | noisy+NUC output | mask vs ground truth "
          "(green hit, red false alarm, blue miss, grey not scored)." % a.presets[-1], ""]
    with open(os.path.join(OUT, "cdnet_eval.md"), "w") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
