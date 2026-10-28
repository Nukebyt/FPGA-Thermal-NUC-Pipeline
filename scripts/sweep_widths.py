"""Task 2.6: integer-vs-float agreement and word-length sweep for the NUC (bit widths OF, GF, YF, step sizes).
Writes docs/results/width_sweep.md. Metric: global-affine-aligned RMSE of the corrected image vs clean, mean of
the last 10 evaluated frames. Memory per pixel = coefficient word (o + g) + 4-bit bad-pixel counter."""
import sys
sys.path.insert(0, ".")
from dataclasses import replace

import numpy as np

from model import noise_model as nm, scenes, metrics as M, pipeline_int as pi

T = int(sys.argv[1]) if len(sys.argv) > 1 else 250


def run_nuc(c, raw):
    s = pi.State.init(c)
    outs = []
    for f in raw:
        yq, bad, st = pi.nuc_frame(c, s, f)
        y14 = np.clip(pi.rshift_round(yq, c.YF), 0, (1 << c.BITS) - 1)
        # same activity signal as the full pipeline (needs the detector's B)
        _, sum_act = pi.detector_frame(c, s, y14)
        s.act = (sum_act >> 16) if s.n > c.ACT_WARM else (1 << 30)
        outs.append(y14)
    return np.stack(outs)


def score(c, raw, scene):
    outs = run_nuc(c, raw)
    cur = M.sequence_curve(outs[-20::2], scene[-20::2])
    return float(cur.mean()), M.roughness(outs[-1])


def bits_per_pixel(c):
    return (12 + c.OF) + (c.GF + 1) + 4


base = pi.Cfg()
lines = ["# Word-length sweep (integer NUC)", "", f"T={T}, typical noise, seed 3. 'RMSE' = aligned RMSE vs clean in counts. "
         "Float reference for the same clips is in docs/results/nuc_study.md.", ""]
cases = {}
for pan, cam in [((0.8, 0.5), "moving"), ((0.0, 0.0), "static")]:
    scene, gt, _ = scenes.make_scene(T, pan=pan, seed=3)
    for pname in ["typical", "severe"]:
        raw, _ = nm.add_noise(scene, nm.preset(pname))
        cases[(cam, pname)] = (raw, scene)

variants = [("baseline OF4 GF12 YF2 KO4", base)]
for of in (0, 2, 3, 6):
    variants.append((f"OF={of}", replace(base, OF=of)))
for gf in (8, 10, 14):
    variants.append((f"GF={gf}", replace(base, GF=gf)))
for yf in (0, 1, 3):
    variants.append((f"YF={yf}", replace(base, YF=yf)))
for ko in (3, 5):
    variants.append((f"KO={ko}", replace(base, KO=ko)))
for mg in (27, 29):
    variants.append((f"MUG_EXP={mg}", replace(base, MUG_EXP=mg)))
variants.append(("OF3 GF10 YF1 (small)", replace(base, OF=3, GF=10, YF=1)))
variants.append(("OF2 GF8 YF1 (tiny)", replace(base, OF=2, GF=8, YF=1)))

hdr = "| variant | bits/px (o+g+bpc) | M10K blocks @76800 px | " + " | ".join(f"{a}/{b}" for a, b in cases) + " |"
lines += [hdr, "|" + "---|" * (3 + len(cases))]
for name, c in variants:
    row = []
    for key, (raw, scene) in cases.items():
        r, _ = score(c, raw, scene)
        row.append(f"{r:.1f}")
    bpp = bits_per_pixel(c)
    lines.append(f"| {name} | {bpp} | {int(np.ceil(bpp * 76800 / 10240))} | " + " | ".join(row) + " |")
    print(lines[-1], flush=True)
open("docs/results/width_sweep.md", "w").write("\n".join(lines) + "\n")
