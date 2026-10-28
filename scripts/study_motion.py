"""Task 2.8 (synthetic): motion F1 for clean / noisy / noisy+NUC, per preset and threshold. Float models."""
import sys
sys.path.insert(0, ".")
import numpy as np
from model import noise_model as nm, scenes, metrics as M, nuc_float as nf, motion_float as mf
T = 400
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
def detect(frames, thr, warm=150):
    d = mf.BackgroundDetector(frames.shape[1:], thresh=thr, alpha_fast=1/128, alpha_slow=1/128)
    return np.stack([d.step(f) for f in frames])[warm:]
for scen, kw in [("static camera", {}), ("static + ambient warming (+3 counts/frame)", {"ramp": 3.0})]:
    scene, gt, _ = scenes.make_scene(T, seed=11, n_blobs=4)
    if "ramp" in kw:
        scene = scene + kw["ramp"] * np.arange(T)[:, None, None]
    print("==", scen)
    for pname in ["mild", "typical", "severe"]:
        raw, sim = nm.add_noise(scene, nm.preset(pname))
        nucout = nuc_run(raw)
        print(" ", pname)
        for thr in [200, 300, 400, 600, 800]:
            row = []
            for name, fr in [("clean", scene), ("noisy", raw.astype(float)), ("noisy+NUC", nucout)]:
                r = M.prf(detect(fr, thr), gt[150:])
                row.append("%s F1 %.3f FAR %.4f" % (name, r["f1"], r["far"]))
            print("    T=%3d  " % thr + " | ".join(row))
