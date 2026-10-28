"""Compare the VGA dump of tb/thermal_sys_tb.v with the Python system model, pixel by pixel.

  python scripts/check_vga.py --dump work/vga_dump.txt --frames 6 --view 2 --iron 0

Exit code 1 on any mismatch, on a missing/short dump, or if the comparison is vacuous (no box outline drawn when boxes
were expected, flat picture). Frame f of the dump is expected to show source frame f-1 (see model/display_model.py).
"""
import argparse
import sys

import numpy as np

sys.path.insert(0, ".")
from model import sensor_emu as se, pipeline_int as pi, display_model as dm  # noqa: E402


def load_rom(path):
    vals = [int(l, 16) for l in open(path) if l.strip() and not l.startswith("//")]
    rb, cb = se.rom_bits(320, 240)
    rr, cc = se.rom_shape(320, 240)
    return np.array(vals, np.uint8).reshape(1 << rb, 1 << cb)[:rr, :cc]


def parse_dump(path):
    frames, cur = [], None
    for line in open(path):
        line = line.strip()
        if line == "F":
            if cur is not None:
                frames.append(cur)
            cur = []
        elif line:
            cur.append(0x1000000 if "x" in line.lower() else int(line, 16))     # 0x1000000 marks an X pixel
    if cur is not None:
        frames.append(cur)
    out = []
    for f in frames:
        a = np.array(f, np.uint32)
        nx = int((a == 0x1000000).sum())
        out.append(None if a.size != 307200 else (nx, np.stack([(a >> 16) & 255, (a >> 8) & 255, a & 255], -1).reshape(480, 640, 3).astype(np.uint8)))
    return out


def n_colours(img):
    """Distinct RGB colours (not one channel: the iron palette keeps green at 0 for every dark pixel)."""
    v = img.astype(np.uint32)
    return len(np.unique((v[..., 0] << 16) | (v[..., 1] << 8) | v[..., 2]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True)
    ap.add_argument("--frames", type=int, default=6)
    ap.add_argument("--view", type=int, default=2)
    ap.add_argument("--iron", type=int, default=0)
    ap.add_argument("--rom", default="quartus/thermal/rom_bg.hex")
    ap.add_argument("--preset", default="typical")
    ap.add_argument("--save", default=None, help="write the first mismatching frame pair as PNGs with this prefix")
    a = ap.parse_args()

    got = parse_dump(a.dump)
    if len(got) < a.frames:
        print("FAIL: dump has %d frames, expected %d" % (len(got), a.frames))
        return 1
    emu = se.SensorEmu(load_rom(a.rom), a.preset)
    cfg = pi.Cfg(DET_WARM=2)
    model = dm.SystemModel(emu, cfg, view=a.view, iron=bool(a.iron), overlay=True)
    model.run_source(a.frames)
    ok = True
    boxes_seen = 0
    print("X pixels in frame 0 (expected, buffers never written yet): %s" % (got[0][0] if got[0] else "n/a"))
    for f in range(1, a.frames):
        if got[f] is None:
            print("FAIL: frame %d is incomplete" % f)
            ok = False
            continue
        nx, img = got[f]
        if nx:
            print("FAIL: frame %d contains %d X pixels" % (f, nx))
            ok = False
        got[f] = img
        exp = model.vga_frame(f)
        bad = int((got[f] != exp).any(-1).sum())
        green = int(((got[f][..., 0] == 0) & (got[f][..., 1] == 255) & (got[f][..., 2] == 0)).sum())
        boxes_seen += green
        nb = len(model.src[f - 2]["boxes"]) if f >= 2 else 0
        print("frame %d: %d mismatching pixels of %d (expected boxes %d, green overlay pixels %d, colours used %d)"
              % (f, bad, 480 * 640, nb, green, n_colours(got[f])))
        if bad:
            ok = False
            if a.save:
                import cv2
                cv2.imwrite("%s_got_%d.png" % (a.save, f), got[f][..., ::-1])
                cv2.imwrite("%s_exp_%d.png" % (a.save, f), exp[..., ::-1])
                ys, xs = np.nonzero((got[f] != exp).any(-1))
                print("   first mismatch at x=%d y=%d got %s exp %s" % (xs[0], ys[0], got[f][ys[0], xs[0]], exp[ys[0], xs[0]]))
    exp_boxes = sum(len(model.src[s]["boxes"]) for s in range(0, a.frames - 2))
    if exp_boxes and boxes_seen == 0:
        print("FAIL: boxes were expected but no overlay pixel appears (vacuous overlay test)")
        ok = False
    if isinstance(got[1], np.ndarray) and n_colours(got[1]) < 20:
        print("FAIL: frame 1 has fewer than 20 distinct colours - flat picture")
        ok = False
    print("RESULT: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
