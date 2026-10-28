import sys
sys.path.insert(0, ".")
from dataclasses import replace
import numpy as np
from model import noise_model as nm, scenes, metrics as M, pipeline_int as pi
T = 330
scene, gt, _ = scenes.make_scene(T, seed=11, n_blobs=4)
raw, _ = nm.add_noise(scene, nm.preset("typical"))
base = pi.Cfg(MIN_AREA=8)
def f1(c, frames):
    s = pi.State.init(c)
    masks = []
    for f in frames:
        o = pi.frame_step(c, s, f); masks.append(o.mask)
    m = np.stack(masks)[200:]
    return M.prf(m, gt[200:])
print("clean, clip-int:")
for name, c, fr in [("clean (no NUC)", replace(base, nuc_en=False, bp_en=False), np.clip(scene, 0, 16383).astype(np.uint16)),
                    ("noisy+NUC", base, raw)]:
    r = f1(c, fr); print(f"  {name:16s} F1 {r['f1']:.3f} FAR {r['far']:.4f} recall {r['recall']:.3f}")
for bf, kb in [(0, 7), (1, 7), (2, 6), (2, 7), (2, 8), (3, 7), (4, 7)]:
    r = f1(replace(base, BF=bf, KB=kb), raw)
    print(f"  BF={bf} KB={kb}: F1 {r['f1']:.3f} FAR {r['far']:.4f}  B bits = {14+bf}")
for t in (250, 300, 400, 500):
    r = f1(replace(base, T_MASK=t), raw); print(f"  T_MASK={t}: F1 {r['f1']:.3f} FAR {r['far']:.4f}")
