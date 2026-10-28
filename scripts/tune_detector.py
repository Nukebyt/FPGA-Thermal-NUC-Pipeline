import sys, itertools
sys.path.insert(0, ".")
import numpy as np
from model import scenes, metrics as M, motion_float as mf
T = 300
scene, gt, _ = scenes.make_scene(T, seed=11, n_blobs=4)
res = []
for thr, a, morph in itertools.product([100, 150, 250, 400, 600], [1/16, 1/32, 1/64, 1/128], [False, True]):
    d = mf.BackgroundDetector(scene.shape[1:], thresh=thr, alpha_fast=a, alpha_slow=a, morph=morph)
    m = np.stack([d.step(f) for f in scene])[120:]
    r = M.prf(m, gt[120:])
    res.append((r["f1"], r["far"], r["recall"], thr, a, morph))
res.sort(reverse=True)
for r in res[:10]: print("F1 %.3f FAR %.4f rec %.3f T=%d a=1/%d morph=%s" % (r[0], r[1], r[2], r[3], round(1/r[4]), r[5]))
