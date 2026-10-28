"""Task 2.5: compare NUC variants on every severity preset, static and moving camera, plus the ghosting test.
Writes docs/results/nuc_study.md. Float models only; bit widths are chosen later (task 2.6)."""
import sys, time
sys.path.insert(0, ".")
import numpy as np
from model import noise_model as nm, scenes, metrics as M, nuc_float as nf
from scipy import ndimage as ndi

T = int(sys.argv[1]) if len(sys.argv) > 1 else 300
VARIANTS = {
    "none":            lambda sh: nf.IdentityNUC(),
    "const-stat":      lambda sh: nf.ConstStatNUC(sh, 1 / 64),
    "lms fixed-clip":  lambda sh: nf.LmsNUC(sh),
    "lms adapt-clip":  lambda sh: nf.LmsNUC(sh, adaptive=(3.0, 16.0, 512.0)),
    "lms adapt-skip":  lambda sh: nf.LmsNUC(sh, adaptive=(3.0, 16.0, 512.0), skip=True),
    "lms offs-only":   lambda sh: nf.LmsNUC(sh, learn_gain=False, adaptive=(3.0, 16.0, 512.0)),
    "lms +gate(cam)":  lambda sh: nf.LmsNUC(sh, adaptive=(3.0, 16.0, 512.0), global_gate=8.0),
}

def run(make, raw, use_bp=True):
    sh = raw.shape[1:]
    nuc = make(sh)
    bp = nf.BadPixelTracker(sh) if use_bp else None
    outs = []
    for t in range(len(raw)):
        x = raw[t]
        if isinstance(nuc, nf.LmsNUC):
            y = nuc.step(x, bad=None if bp is None else bp.flag)
        else:
            y = nuc.step(x)
        if bp is not None:
            bp.update(x, y)
            y = nf.replace_bad(y, bp.flag)
        outs.append(y)
    return np.stack(outs)

lines = ["# NUC variant study (float models)", "", f"T = {T} frames, 240x320, seed 3. Metric: global-affine-aligned RMSE vs clean (counts, mean of last 20 frames), "
         "roughness of the last frame (clean scene ~0.0085), frames to reach RMSE < raw/4.", ""]
for pan, camname in [((0.8, 0.5), "moving camera"), ((0.0, 0.0), "static camera")]:
    scene, gt, _ = scenes.make_scene(T, pan=pan, seed=3)
    for pname in ["mild", "typical", "severe"]:
        raw, sim = nm.add_noise(scene, nm.preset(pname))
        base = M.sequence_curve(raw.astype(float), scene).mean()
        lines += [f"## {camname}, {pname} (raw RMSE {base:.0f}, bad pixels {sim.bad_mask.mean()*100:.2f} %)", "",
                  "| variant | final RMSE | roughness | conv frame |", "|---|---|---|---|"]
        for name, mk in VARIANTS.items():
            t0 = time.time()
            outs = run(mk, raw, use_bp=(name != "none"))
            cur = M.sequence_curve(outs[::2], scene[::2])
            cf = M.convergence_frame(cur, base / 4, hold=5)
            lines.append(f"| {name} | {cur[-10:].mean():.1f} | {M.roughness(outs[-1]):.4f} | {None if cf is None else cf*2} |")
            print(camname, pname, name, f"{cur[-10:].mean():.1f}", f"{time.time()-t0:.1f}s", flush=True)
        lines.append("")

# ghosting: a hot stationary object (dt=1500) that starts moving at frame T0
lines += ["## Ghosting: stationary hot object starts moving at frame 120 (typical noise)", "",
          "Ghost = mean(output - clean) over the object's initial footprint (eroded), frames 200..end; burn-in shows as a negative value. Object contrast is +1500 counts.", "",
          "| variant | static camera | moving camera |", "|---|---|---|"]
res = {}
for pan, key in [((0.0, 0.0), "static"), ((0.8, 0.5), "moving")]:
    b = scenes.Blob(cx=160, cy=120, rx=14, ry=18, dt=1500, vx=2.0, vy=0.0, start=120)
    scene, gt, _ = scenes.make_scene(T, pan=pan, seed=5, blobs=[b])
    foot = ndi.binary_erosion(scenes._blob_alpha(scene.shape[1:], b, 0) > 0.5, iterations=3)
    if pan != (0.0, 0.0):
        foot = None
    raw, _ = nm.add_noise(scene, nm.preset("typical", dead_rate=0, hot_rate=0))
    for name, mk in VARIANTS.items():
        outs = run(mk, raw, use_bp=False)
        if foot is None:
            res[(name, key)] = float("nan")   # camera moves: footprint is not fixed in image coordinates
        else:
            res[(name, key)] = M.ghost_amplitude(outs, scene, foot, range(200, T, 10))
for name in VARIANTS:
    lines.append(f"| {name} | {res[(name,'static')]:.1f} | n/a |")
open("docs/results/nuc_study.md", "w").write("\n".join(lines) + "\n")
print("\n".join(lines))
