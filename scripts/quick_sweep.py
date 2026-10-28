import sys, itertools
sys.path.insert(0, ".")
import numpy as np
from model import noise_model as nm, scenes, metrics as M, nuc_float as nf
T = 300
for pan in [(0.8, 0.5), (0.0, 0.0)]:
    scene, gt, _ = scenes.make_scene(T, pan=pan, seed=3)
    for pname in ["typical", "severe"]:
        p = nm.preset(pname, dead_rate=0, hot_rate=0)
        raw, sim = nm.add_noise(scene, p)
        print(f"== pan={pan} {pname} raw {M.sequence_curve(raw.astype(float), scene).mean():.0f}")
        for mu_o, clip, mug, edge in itertools.product([1/32, 1/16, 1/8], [256.0, 1024.0], [2.0**-28, 2.0**-25], [None, 1500.0]):
            a = nf.LmsNUC(raw.shape[1:], mu_o=mu_o, mu_g=mug, e_clip=clip, edge_stop=edge)
            outs = np.stack([a.step(raw[t]) for t in range(T)])
            cur = M.sequence_curve(outs[::5], scene[::5])
            print(f"  mu_o=1/{int(1/mu_o):3d} clip={clip:6.0f} mu_g=2^{int(np.log2(mug)):4d} edge={edge}  RMSE@100 {cur[20]:6.1f}  final {cur[-4:].mean():6.1f}  rough {M.roughness(outs[-1]):.4f}")
