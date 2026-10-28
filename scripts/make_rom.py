"""Generate the background ROM for rtl/sensor_emu.v (160x120 half resolution, 8 bit, shown 2x) -> quartus/thermal/rom_bg.hex and a preview PNG.

  python scripts/make_rom.py                       # default synthetic thermal scene (seed 21)
  python scripts/make_rom.py --image some.png      # any picture (grayscale, resized to 320x240), e.g. a CDnet / FLIR frame
  python scripts/make_rom.py --cdnet data/cdnet/thermal library 100      # one CDnet frame (sequence, frame number)

The ROM value v maps to counts 3000 + 16*v (model.sensor_emu.BASE). The output file is a synthesis input: it is
committed to the repository (checklist 7.1) and its first line names this script.
"""
import argparse
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from model import sensor_emu as se  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="quartus/thermal/rom_bg.hex")
    ap.add_argument("--seed", type=int, default=21)
    ap.add_argument("--image", default=None)
    ap.add_argument("--cdnet", nargs=3, metavar=("ROOT", "SEQ", "FRAME"), default=None)
    a = ap.parse_args()
    if a.image:
        im = cv2.imread(a.image, cv2.IMREAD_GRAYSCALE)
        rom = cv2.resize(im, (320, 240), interpolation=cv2.INTER_AREA)
    elif a.cdnet:
        root, seq, fr = a.cdnet
        im = cv2.imread(os.path.join(root, seq, "input", "in%06d.jpg" % int(fr)), cv2.IMREAD_GRAYSCALE)
        from model import datasets
        rom = datasets._fit(im, cv2.INTER_AREA)
    else:
        rom = se.rom_from_scene((240, 320), seed=a.seed)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    if rom.shape != se.rom_shape(320, 240):                      # pictures come in at full resolution
        rom = cv2.resize(rom, (160, 120), interpolation=cv2.INTER_AREA)
    se.write_hex(a.out, rom, W=320, H=240)
    cv2.imwrite(os.path.splitext(a.out)[0] + "_preview.png", rom)
    print("wrote", a.out, rom.shape, "min/max", rom.min(), rom.max())


if __name__ == "__main__":
    main()
