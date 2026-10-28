"""What the board is supposed to show: a real clip through the bit-accurate system model (FEED build), rendered like the VGA / viewer picture.

  python scripts/demo_sim.py --seq library --start 450 --frames 300 --tmask 640
  python scripts/demo_sim.py --clip data/clips/park_0_120.u8 --tmask 400

Per source frame the model gives the raw picture, the NUC-corrected picture and the box list, exactly as the RTL does (the
two are checked bit for bit in the regression). The clip plays at 60 / --repeat frames per second like feed_clip.py --repeat.
Writes <out>/demo_<name>.mp4 (raw left, NUC-corrected right, both full frames, green boxes), <out>/demo_<name>_sheet.png (a few frames) and
prints the box count against the ground truth when the clip has one (prepare_clips.py .gt.u8, or CDnet groundtruth for --seq)."""
import argparse
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from model import datasets as D  # noqa: E402
from model import display_model as dm  # noqa: E402
from model import pipeline_int as pi  # noqa: E402
from model import sensor_emu as se  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def load_seq(seq, start, n):
    d = os.path.join(ROOT, "data", "cdnet", "thermal", seq)
    ins = sorted(glob.glob(os.path.join(d, "input", "in*.jpg")))[start:start + n]
    fr, gt = [], []
    for p in ins:
        idx = int(os.path.basename(p)[2:-4])
        fr.append(D._fit(cv2.imread(p, cv2.IMREAD_GRAYSCALE), cv2.INTER_AREA))
        g = cv2.imread(os.path.join(d, "groundtruth", "gt%06d.png" % idx), cv2.IMREAD_GRAYSCALE)
        gt.append(np.zeros((D.H, D.W), np.uint8) if g is None else (D._fit(g, cv2.INTER_NEAREST) == 255).astype(np.uint8))
    return np.stack(fr), np.stack(gt)


def label(img, text):
    cv2.putText(img, text, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seq", choices=D.CDNET_THERMAL)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--frames", type=int, default=300, help="clip frames")
    ap.add_argument("--clip", help="raw .u8 clip from prepare_clips.py instead of --seq")
    ap.add_argument("--repeat", type=int, default=2, help="display frames per clip frame")
    ap.add_argument("--tmask", type=int, default=400)
    ap.add_argument("--iron", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(ROOT, "work", "demo"))
    a = ap.parse_args()
    if a.clip:
        clip = np.fromfile(a.clip, np.uint8).reshape(-1, D.H, D.W)[:a.frames]
        gtp = a.clip[:-3] + ".gt.u8"
        gt = (np.fromfile(gtp, np.uint8).reshape(-1, D.H, D.W)[:a.frames] == 1).astype(np.uint8) if os.path.exists(gtp) else None
        name = os.path.splitext(os.path.basename(a.clip))[0]
    elif a.seq:
        clip, gt = load_seq(a.seq, a.start, a.frames)
        name = "%s_%d_%d" % (a.seq, a.start, len(clip))
    else:
        sys.exit("give --seq or --clip")
    S = len(clip) * a.repeat
    emu = se.SensorEmu(None, "typical", scene8=clip[0], obj_en=False)
    model = dm.SystemModel(emu, pi.Cfg(T_MASK=a.tmask), view=2, iron=bool(a.iron), overlay=True)
    model.scene_fn = lambda k: clip[min(k // a.repeat, len(clip) - 1)]
    print("running %d display frames (%d clip frames x %d) ..." % (S, len(clip), a.repeat), flush=True)
    model.run_source(S)
    os.makedirs(a.out, exist_ok=True)

    vw = cv2.VideoWriter(os.path.join(a.out, "demo_%s.mp4" % name), cv2.VideoWriter_fourcc(*"mp4v"), 60 / a.repeat, (1280, 480))
    cand = [f for f in range(1, S, a.repeat) if f >= 2 and model.src[f - 2]["boxes"]]      # frames that show boxes
    sheet_at = set(cand[int(i)] for i in np.linspace(0, len(cand) - 1, 5)) if cand else set()
    sheet = []
    for f in range(1, S, a.repeat):
        d = model.src[f - 1]                                   # VGA frame f shows source frame f-1 with the box list of f-2
        boxes = model.src[f - 2]["boxes"] if f >= 2 else []
        left = dm.render(d["corr8"], d["raw8"], 1, bool(a.iron), True, boxes)[..., ::-1].copy()
        right = dm.render(d["corr8"], d["raw8"], 3, bool(a.iron), True, boxes)[..., ::-1].copy()
        label(left, "raw (real clip + simulated sensor noise)")
        label(right, "after NUC + motion boxes")
        rgb = np.hstack([left, right])
        vw.write(rgb)
        if f in sheet_at:
            sheet.append(rgb)
    vw.release()
    cv2.imwrite(os.path.join(a.out, "demo_%s_sheet.png" % name), np.vstack(sheet))
    print("wrote %s" % os.path.join(a.out, "demo_%s.mp4" % name))
    print("wrote %s" % os.path.join(a.out, "demo_%s_sheet.png" % name))
    if gt is not None:
        nbox = [len(d["boxes"]) for d in model.src[140 * a.repeat:]]
        gt_frames = [bool(gt[min(k // a.repeat, len(gt) - 1)].any()) for k in range(140 * a.repeat, S)]
        both = [(n > 0) for n, g in zip(nbox, gt_frames) if g]
        none = [(n > 0) for n, g in zip(nbox, gt_frames) if not g]
        print("frames with a person in the ground truth: %d of which boxes drawn: %d" % (len(both), sum(both)))
        print("frames without a person: %d of which boxes drawn (false alarms): %d" % (len(none), sum(none)))


if __name__ == "__main__":
    main()
