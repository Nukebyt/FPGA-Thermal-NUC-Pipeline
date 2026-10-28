import sys, time
sys.path.insert(0, ".")
import numpy as np
from model import noise_model as nm, scenes, metrics as M, nuc_float as nf

def run(alg, raw, clean, bp=False):
    outs = []
    for t in range(len(raw)):
        outs.append(alg.step(raw[t]))
    outs = np.stack(outs)
    cur = M.sequence_curve(outs, clean)
    return outs, cur

T = 300
for pan in [(0.0, 0.0), (0.8, 0.5)]:
    scene, gt, _ = scenes.make_scene(T, pan=pan, seed=3)
    for pname in ["mild", "typical"]:
        p = nm.preset(pname, dead_rate=0, hot_rate=0)
        raw, sim = nm.add_noise(scene, p)
        base = M.sequence_curve(raw.astype(float), scene)
        print(f"pan={pan} {pname}: raw aligned RMSE {base.mean():.1f}  rough {M.roughness(raw[-1]):.4f} clean rough {M.roughness(scene[-1]):.4f}")
        algs = {
         "cs": nf.ConstStatNUC(raw.shape[1:], 1/64),
         "lms": nf.LmsNUC(raw.shape[1:]),
         "lms+edge": nf.LmsNUC(raw.shape[1:], edge_stop=400.0),
         "lms+edge+mot": nf.LmsNUC(raw.shape[1:], edge_stop=400.0, motion_gate=40.0),
         "lms-offs-only+edge": nf.LmsNUC(raw.shape[1:], edge_stop=400.0, learn_gain=False),
        }
        for n, a in algs.items():
            t0=time.time()
            outs, cur = run(a, raw, scene)
            print(f"   {n:20s} final RMSE {cur[-20:].mean():7.1f}  min {cur.min():7.1f}  rough {M.roughness(outs[-1]):.4f}  conv(<{base.mean()/4:.0f}) {M.convergence_frame(cur, base.mean()/4)}  ({time.time()-t0:.1f}s)")
