"""Does NUC matter for a detector with no per-pixel temporal model? Hot-spot detector: y - box(y) > T. Moving camera."""
import sys
sys.path.insert(0, ".")
import numpy as np
from scipy.ndimage import uniform_filter
from model import noise_model as nm, scenes, metrics as M, nuc_float as nf
T = 300
def nuc_run(raw):
    sh = raw.shape[1:]
    nuc = nf.LmsNUC(sh, adaptive=(3.0, 16.0, 512.0), gain_gate=64.0)
    bp = nf.BadPixelTracker(sh); B = None; outs = []
    for t in range(len(raw)):
        y = nuc.step(raw[t], bad=bp.flag); bp.update(raw[t], y); y = nf.replace_bad(y, bp.flag)
        if B is None: B = y.copy()
        nuc.activity = float(np.abs(y - B).mean()); B += (y - B) / 16
        outs.append(y)
    return np.stack(outs)
def hot(frames, thr, box=21):
    return np.stack([(f - uniform_filter(f, box, mode="nearest")) > thr for f in frames])
scene, gt, _ = scenes.make_scene(T, seed=11, n_blobs=4, pan=(0.8, 0.5))
for pname in ["mild", "typical", "severe"]:
    raw, _ = nm.add_noise(scene, nm.preset(pname))
    nuc = nuc_run(raw)
    print(pname)
    for thr in [300, 450, 600, 800]:
        row = []
        for name, fr in [("clean", scene), ("noisy", raw.astype(float)), ("noisy+NUC", nuc)]:
            r = M.prf(hot(fr[150:], thr), gt[150:])
            row.append("%s F1 %.3f FAR %.4f" % (name, r["f1"], r["far"]))
        print("   T=%3d  " % thr + " | ".join(row))
