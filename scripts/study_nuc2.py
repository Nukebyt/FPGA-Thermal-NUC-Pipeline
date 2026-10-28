"""Activity-gated gain learning: print the activity signal mean|y - B| for each camera mode, then compare."""
import sys
sys.path.insert(0, ".")
import numpy as np
from model import noise_model as nm, scenes, metrics as M, nuc_float as nf
from scipy import ndimage as ndi
T = 300
def run(raw, gate, a=1/16):
    sh = raw.shape[1:]
    nuc = nf.LmsNUC(sh, adaptive=(3.0, 16.0, 512.0), gain_gate=gate)
    bp = nf.BadPixelTracker(sh)
    B = None; outs = []; acts = []
    for t in range(len(raw)):
        y = nuc.step(raw[t], bad=bp.flag)
        bp.update(raw[t], y)
        y = nf.replace_bad(y, bp.flag)
        if B is None: B = y.copy()
        act = float(np.abs(y - B).mean()); acts.append(act)
        B = B + a * (y - B)
        nuc.activity = act
        outs.append(y)
    return np.stack(outs), np.array(acts)
for pname in ["typical", "severe"]:
    for pan, cam in [((0.8, 0.5), "moving"), ((0, 0), "static")]:
        scene, gt, _ = scenes.make_scene(T, pan=pan, seed=3)
        raw, _ = nm.add_noise(scene, nm.preset(pname))
        outs, acts = run(raw, None)
        print(pname, cam, "activity: first10 %.1f  frames100-300 median %.1f  p95 %.1f" % (acts[:10].mean(), np.median(acts[100:]), np.percentile(acts[100:], 95)))
        for gate in [30, 60, 120]:
            outs, _ = run(raw, gate)
            cur = M.sequence_curve(outs[::2], scene[::2])
            print("    gain_gate", gate, "final RMSE %.1f" % cur[-10:].mean(), " rough %.4f" % M.roughness(outs[-1]))
# ghost
for gate in [None, 30, 60, 120]:
    b = scenes.Blob(cx=160, cy=120, rx=14, ry=18, dt=1500, vx=2.0, vy=0.0, start=120)
    scene, gt, _ = scenes.make_scene(T, pan=(0, 0), seed=5, blobs=[b])
    foot = ndi.binary_erosion(scenes._blob_alpha(scene.shape[1:], b, 0) > 0.5, iterations=3)
    raw, _ = nm.add_noise(scene, nm.preset("typical", dead_rate=0, hot_rate=0))
    outs, acts = run(raw, gate)
    print("ghost static gate", gate, "%.1f" % M.ghost_amplitude(outs, scene, foot, range(200, T, 10)),
          " RMSE %.1f" % M.sequence_curve(outs[-20::5], scene[-20::5]).mean(), " act median %.1f" % np.median(acts[100:]))
