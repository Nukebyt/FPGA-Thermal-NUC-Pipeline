"""Vectors for tb/thermal_core_tb.v from the whole-pipeline golden model pipeline_int.frame_step().

Writes into --out (one hex word per line):
  x.hex    T*H*W   raw samples (4 digits)
  y.hex    T*H*W   expected corrected y14 (4 digits)
  mask.hex T*H*W   expected final (post open/close, gated by DET_WARM) mask bit
  hdr.hex  T       {n_obj[7:0], cnt[4:0], ovf} "%04x"
  rec.hex  T*16    53-bit box records "%014x"
  coef.hex T*H*W   NUC coefficient word after the frame (8 digits)
  bram.hex T*H*W   background model B after the frame (4 digits)
  fr.hex   T       "act_sum n_after det_valid lim sum_abs_e"
Cfg: small frame, DET_WARM=3, MIN_AREA=4, KLIM scaled by --klim. ACT_THR=--act_thr (0 makes the gate toggle often).
"""
import argparse
import os
import sys
from dataclasses import replace

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from model import noise_model as nm, scenes, pipeline_int as pi  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--W", type=int, default=48)
    ap.add_argument("--H", type=int, default=36)
    ap.add_argument("--T", type=int, default=20)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--preset", default="typical")
    ap.add_argument("--blobs", type=int, default=3)
    ap.add_argument("--klim", type=int, default=41)
    ap.add_argument("--act_thr", type=int, default=64)
    ap.add_argument("--t_mask", type=int, default=400)
    ap.add_argument("--det_warm", type=int, default=3)
    ap.add_argument("--min_area", type=int, default=4)
    ap.add_argument("--pan", type=float, default=0.0)
    ap.add_argument("--learn_n", type=int, default=256, help="NUC learning window; TB parameter LEARN_N")
    ap.add_argument("--act_thr_from_frame", type=int, default=-1,
                    help="set ACT_THR to the activity (sum>>16) observed after this frame, so the > vs >= edge is exercised")
    ap.add_argument("--t_mask_edge_frame", type=int, default=-1,
                    help="set T_MASK so that pixels sit exactly on the threshold (|y-B| == T_MASK) in this frame and the > vs >= "
                         "difference survives the morphology (bug log 26)")
    a = ap.parse_args()
    c = pi.Cfg(W=a.W, H=a.H, DET_WARM=a.det_warm, MIN_AREA=a.min_area, KLIM=a.klim, ACT_THR=a.act_thr, T_MASK=a.t_mask,
               LEARN_N=a.learn_n)
    scene, gt, _ = scenes.make_scene(a.T, shape=(c.H, c.W), seed=a.seed, n_blobs=a.blobs, pan=(a.pan, a.pan / 2))
    raw, _ = nm.add_noise(scene, nm.preset(a.preset, dead_rate=0.004, hot_rate=0.004, seed=a.seed))
    os.makedirs(a.out, exist_ok=True)
    if a.act_thr_from_frame >= 0:
        s0 = pi.State.init(c)
        acts = [pi.frame_step(c, s0, raw[t]).sum_act >> 16 for t in range(a.act_thr_from_frame + 1)]
        c = pi.Cfg(**{**c.__dict__, "ACT_THR": int(acts[-1])})
        print("ACT_THR set to", c.ACT_THR, "(activity history:", acts, ")")
    if a.t_mask_edge_frame >= 0:
        import copy
        s0 = pi.State.init(c)
        for t in range(a.t_mask_edge_frame):
            pi.frame_step(c, s0, raw[t])
        sb = copy.deepcopy(s0)
        y = pi.frame_step(c, s0, raw[a.t_mask_edge_frame]).y14.astype(np.int64) << c.BF
        diff = np.abs(y - sb.B)
        best = (0, c.T_MASK)
        for tt in np.unique(diff[(diff % (1 << c.BF) == 0) & (diff > 0)] >> c.BF)[:400]:
            thr = int(tt) << c.BF
            m1, m2 = pi.morph_open_close(diff > thr), pi.morph_open_close(diff >= thr)
            if int((m1 ^ m2).sum()) > best[0]:
                best = (int((m1 ^ m2).sum()), int(tt))
        assert best[0] > 0, "no threshold value makes > and >= differ after the morphology"
        c = pi.Cfg(**{**c.__dict__, "T_MASK": best[1]})
        print("T_MASK set to %d (%d pixels differ between > and >= after the morphology)" % (best[1], best[0]))
    s = pi.State.init(c)
    fx, fy, fm, fh, fr_, fco, fb, ffr = [], [], [], [], [], [], [], []
    n_masks = n_boxes = n_ovf = 0
    for t in range(a.T):
        o = pi.frame_step(c, s, raw[t])
        fx += ["%04x" % v for v in raw[t].ravel()]
        fy += ["%04x" % v for v in o.y14.ravel()]
        fm += ["%x" % int(v) for v in o.mask.ravel()]
        fh.append("%04x" % ((o.n_objects << 6) | (len(o.boxes) << 1) | int(o.overflow)))
        for i in range(16):
            if i < len(o.boxes):
                xmin, ymin, xmax, ymax, area = o.boxes[i]
                fr_.append("%014x" % ((area << 36) | (ymax << 27) | (xmax << 18) | (ymin << 9) | xmin))
            else:
                fr_.append("%014x" % 0)
        coef = pi.coef_word(c, s)
        fco += ["%08x" % int(v) for v in coef.ravel()]
        fb += ["%04x" % int(v) for v in s.B.ravel()]
        ffr.append("%08x %02x %x %03x %010x" % (o.sum_act, s.n, int(o.det_valid), o.lim_q, o.sum_abs_e))
        n_masks += int(o.mask.any())
        n_boxes += len(o.boxes)
        n_ovf += int(o.overflow)
    for name, data in (("x", fx), ("y", fy), ("mask", fm), ("hdr", fh), ("rec", fr_), ("coef", fco), ("bram", fb), ("fr", ffr)):
        with open(os.path.join(a.out, name + ".hex"), "w", newline="\n") as f:
            f.write("\n".join(data) + "\n")
    open(os.path.join(a.out, "act_thr.txt"), "w").write(str(c.ACT_THR))
    print("wrote %d frames %dx%d to %s; frames with a mask: %d; boxes: %d; overflow frames: %d"
          % (a.T, c.W, c.H, a.out, n_masks, n_boxes, n_ovf))


if __name__ == "__main__":
    main()
