"""Vectors for tb/sensor_emu_tb.v from the integer twin model/sensor_emu.py.

Writes into --out: rom.hex (background ROM, first line is a // comment), raw.hex (T*H*W, 4 digits), clean.hex
(ground-truth scene, 4 digits), mot.hex (ground-truth motion mask) and rectp.vh (`localparam [191:0] RECTP_TB = ...`).
The small-frame rectangles are scaled to fit; the full-size default (model.sensor_emu.DEFAULT_RECTS) is what the
board uses.
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from model import sensor_emu as se  # noqa: E402

NL = chr(10)
SMALL_RECTS = [se.Rect(5, 4, 10, 8, 1300, 2, 1), se.Rect(25, 15, 12, 8, 900, -1, 2), se.Rect(18, 3, 6, 6, 1500, 3, -2)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--W", type=int, default=48)
    ap.add_argument("--H", type=int, default=36)
    ap.add_argument("--T", type=int, default=8)
    ap.add_argument("--preset", default="typical")
    ap.add_argument("--noise", type=int, default=1)
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--feed", type=int, default=0, help="1: FEED build - a different random full-resolution frame in the "
                    "frame store each frame (scene<f>.hex, 32-bit words)")
    ap.add_argument("--obj", type=int, default=1, help="0: moving rectangles hidden (CSR FEED_CTRL[0])")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if (a.W, a.H) == (320, 240):
        rects = se.DEFAULT_RECTS
    else:
        rects = SMALL_RECTS
    if a.feed:
        rs = np.random.RandomState(a.seed)
        scenes = rs.randint(0, 256, (a.T, a.H, a.W)).astype(np.uint8)
        scenes[:, :, : max(1, a.W // 6)] //= 4                   # some structure: a dark band, a bright block
        scenes[:, a.H // 3: a.H // 2, a.W // 2: a.W // 2 + a.W // 5] = 255
        emu = se.SensorEmu(None, a.preset, rects=rects, W=a.W, H=a.H, scene8=scenes[0], obj_en=bool(a.obj))
        raw, clean, mot = emu.run(a.T, scenes=scenes)
        for f in range(a.T):
            with open(os.path.join(a.out, "scene%d.hex" % f), "w", newline=NL) as fh:
                fh.write(NL.join("%08x" % int(v) for v in se.pack_words(scenes[f])) + NL)
        rom = None
    else:
        rom = se.rom_from_scene((a.H, a.W), seed=a.seed)
        emu = se.SensorEmu(rom, a.preset, rects=rects, W=a.W, H=a.H)
        raw, clean, mot = emu.run(a.T)
    if not a.noise:
        raw = np.clip(clean, 0, 16383).astype(np.uint16)
    if rom is not None:
        se.write_hex(os.path.join(a.out, "rom.hex"), rom, W=a.W, H=a.H)
    for name, arr, fmt in (("raw", raw, "%04x"), ("clean", clean, "%04x"), ("mot", mot.astype(int), "%x")):
        with open(os.path.join(a.out, name + ".hex"), "w", newline="\n") as f:
            f.write("\n".join(fmt % int(v) for v in arr.ravel()) + "\n")
    with open(os.path.join(a.out, "rectp.vh"), "w", newline="\n") as f:
        f.write("localparam [191:0] RECTP_TB = 192'h%048x;\n" % se.pack_rects(rects))
    print("wrote %d frames %dx%d preset=%s noise=%d to %s; raw range %d..%d; moving pixels in frame 0: %d"
          % (a.T, a.W, a.H, a.preset, a.noise, a.out, raw.min(), raw.max(), int(mot[0].sum())))


if __name__ == "__main__":
    main()
