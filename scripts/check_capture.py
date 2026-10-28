"""Compare a frame captured through the host bus (tb/thermal_sys_tb.v CAPDUMP, or host/viewer.py --save-raw on the
board) with the Python system model: frame `fid` of the selected source (corrected or raw, tone-mapped 8 bit).

  python scripts/check_capture.py --dump work/cap_dump.txt --src 0
Dump format: first line "fid N", then W*H/4 lines of 8 hex digits (pixel 4k+b in byte b)."""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from model import display_model as dm, pipeline_int as pi, sensor_emu as se  # noqa: E402
from check_vga import load_rom  # noqa: E402


def load_capture(path, W=320, H=240):
    with open(path) as f:
        lines = [l.strip() for l in f if l.strip()]
    if not lines or not lines[0].startswith("fid "):
        raise ValueError("%s: first line must be 'fid N'" % path)
    fid = int(lines[0].split()[1])
    words = np.array([int(l, 16) for l in lines[1:]], np.uint32)
    if words.size != W * H // 4:
        raise ValueError("%s: %d words, expected %d" % (path, words.size, W * H // 4))
    img = np.stack([(words >> (8 * b)) & 255 for b in range(4)], -1).reshape(H, W).astype(np.uint8)
    return fid, img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--src", type=int, default=0, help="0 corrected, 1 raw")
    ap.add_argument("--rom", default="quartus/thermal/rom_bg.hex")
    ap.add_argument("--preset", default="typical")
    ap.add_argument("--det_warm", type=int, default=2)
    a = ap.parse_args()
    fid, img = load_capture(a.dump)
    model = dm.SystemModel(se.SensorEmu(load_rom(a.rom), a.preset), pi.Cfg(DET_WARM=a.det_warm))
    model.run_source(fid + 1)
    exp = model.src[fid]["raw8" if a.src else "corr8"]
    bad = int((img != exp).sum())
    levels = len(np.unique(img))
    print("capture of source frame %d (%s): %d of %d pixels differ from the model; %d grey levels"
          % (fid, "raw" if a.src else "corrected", bad, img.size, levels))
    ok = bad == 0 and levels >= 20
    if levels < 20:
        print("FAIL: fewer than 20 grey levels - flat capture")
    print("RESULT: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
