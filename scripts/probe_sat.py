"""Debug helper: what do o and g do under the saturation stimulus? (Used to design the nuc_sat test.)"""
import sys
sys.path.insert(0, ".")
import numpy as np
from model import pipeline_int as pi

c = pi.Cfg(W=8, H=6, bp_en=False, KLIM=40000)
r, q = np.mgrid[0:c.H, 0:c.W]
x = np.where((r + q) % 2 == 0, int(sys.argv[1]) if len(sys.argv) > 1 else 3000, int(sys.argv[2]) if len(sys.argv) > 2 else 9000).astype(np.uint16)
s = pi.State.init(c)
for t in range(400):
    s.act = 1 << 30
    pi.nuc_frame(c, s, x)
    if t % 25 == 0 or t == 399:
        print(t, "o min/max", s.o.min(), s.o.max(), "g min/max", s.g.min(), s.g.max(), "lim", s.lim_q)
