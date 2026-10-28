r"""Record GIFs of what the board shows, for the README.  Needs the board running sw/frame_feeder serve (docs/bringup_3b.md).

  .venv\Scripts\python.exe scripts\capture_gifs.py --clip data/clips/library_450_900.u8 --start 425 --end 785 --step 4 --tmask 640 --scale 1 --out docs/img/library.gif
  .venv\Scripts\python.exe scripts\capture_gifs.py --grab work/library.grab.npz --out docs/img/library.gif --lo-pct 70      # re-render, no board

The clip is played in lock step: warm-up with the empty-scene frames, then for every chosen source frame the script feeds it once
(the display holds it), captures the RAW and the NUC-CORRECTED frame of that same source frame from the capture buffer, and reads
the box list. Both panels therefore always show the same source frame (the sensor noise is the board's own and differs only in its
temporal part). The detector sees each frame for several display frames, so box sizes can differ a little from the free-running demo.
The captures are saved (work/<name>.grab.npz) and coloured afterwards: the board's capture buffer holds the 8-bit picture the design
tone-maps for its display (auto contrast over the whole range); here one fixed window per GIF is applied instead, so the cold
background stays purple-blue and warm things (people) reach orange / red, as on a thermal camera."""
import argparse
import os
import sys
import time

import cv2
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "host"))
sys.path.insert(0, os.path.join(HERE, ".."))

CTRL_DEFAULT = 0x2BF

from thermal_palette import LEVELS, colour, rainbow_rgb, window  # noqa: E402


def panel(img8, boxes, scale, title, win, gamma):
    rgb = colour(img8, win, gamma)
    out = cv2.resize(rgb, (img8.shape[1] * scale, img8.shape[0] * scale), interpolation=cv2.INTER_NEAREST)
    for (x0, y0, x1, y1) in boxes:
        cv2.rectangle(out, (x0 * scale, y0 * scale), ((x1 + 1) * scale - 1, (y1 + 1) * scale - 1), (0, 255, 0), 1)
    bar = np.zeros((22, out.shape[1], 3), np.uint8)
    cv2.putText(bar, title, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return np.vstack([bar, out])


def grab(a):
    import thermal_net as tn
    import viewer as vw
    clip = np.fromfile(a.clip, np.uint8).reshape(-1, tn.H * tn.W)
    b = tn.NetBoard(a.host)
    print("board ID %08x" % b.ping())
    b.wr(0x24, 0)                                            # FEED_CTRL: the clip brings its own objects
    b.wr(vw.CTRL, CTRL_DEFAULT)
    b.wr(0x06, a.tmask)
    b.wr(vw.PULSE, 3)                                        # coefficient reset + frame reset: clean learning for this scene
    t0 = time.time()
    torn = 0
    for i in range(a.warm):                                  # empty scene: background and NUC settle
        for _ in range(2):
            torn += b.feed(clip[i])[0] != tn.ST_OK
    print("warm-up %d source frames in %.1f s (torn %d)" % (a.warm, time.time() - t0, torn))
    raws, cors, boxes_l = [], [], []
    t0 = time.time()
    for i in range(a.start, a.end, a.step):
        b.feed(clip[i])
        fr, rawimg, _ = vw.capture(b, 1)                     # raw and corrected of the same source frame
        fc, corimg, _ = vw.capture(b, 0)
        n_obj, boxes = vw.read_boxes(b)
        raws.append(rawimg); cors.append(corimg); boxes_l.append(boxes)
        if len(raws) % 20 == 0:
            print("  %d frames, %.0f ms per step, boxes %d, display frames raw %d corrected %d" %
                  (len(raws), 1000 * (time.time() - t0) / len(raws), len(boxes), fr, fc))
    print("captured %d frames in %.1f s; board counters %s" % (len(raws), time.time() - t0, b.stat()))
    b.close()
    boxarr = np.zeros((len(raws), 16, 4), np.int16) - 1
    for k, bl in enumerate(boxes_l):
        for j, bx in enumerate(bl[:16]):
            boxarr[k, j] = bx
    path = os.path.join(HERE, "..", "work", os.path.splitext(os.path.basename(a.out))[0] + ".grab.npz")
    np.savez_compressed(path, raw=np.stack(raws), cor=np.stack(cors), boxes=boxarr, step=a.step)
    print("saved", path)
    return np.stack(raws), np.stack(cors), boxarr, a.step


def render(raws, cors, boxarr, step, a):
    wr = window(list(raws[::max(1, len(raws) // 20)]), a.lo_pct, a.hi_pct)
    wc = window(list(cors[::max(1, len(cors) // 20)]), a.lo_pct, a.hi_pct)
    print("window raw %.0f..%.0f  corrected %.0f..%.0f  gamma %.2f" % (wr + wc + (a.gamma,)))
    frames = []
    for k in range(len(raws)):
        bl = [tuple(int(v) for v in bx) for bx in boxarr[k] if bx[0] >= 0]
        frames.append(np.hstack([panel(raws[k], [], a.scale, "raw sensor (simulated noise)", wr, a.gamma),
                                 panel(cors[k], bl, a.scale, "after NUC + motion boxes", wc, a.gamma)]))
    colors = [tuple(int(v) for v in rainbow_rgb(l)) for l in range(LEVELS)] + [(0, 255, 0), (255, 255, 255), (0, 0, 0)]
    pal_img = Image.new("P", (1, 1))
    flat = [c for rgb in colors for c in rgb]
    pal_img.putpalette(flat + [0] * (768 - len(flat)))
    imgs = [Image.fromarray(f).quantize(palette=pal_img, dither=Image.Dither.NONE) for f in frames]
    dur = int(round(100.0 * step / a.src_fps)) * 10
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    imgs[0].save(a.out, save_all=True, append_images=imgs[1:], duration=dur, loop=0, optimize=True, disposal=1)
    k = [0, len(frames) // 4, len(frames) // 2, 3 * len(frames) // 4]
    cv2.imwrite(os.path.join(HERE, "..", "work", "demo", os.path.splitext(os.path.basename(a.out))[0] + "_check.png"),
                np.vstack([np.hstack([frames[k[0]], frames[k[1]]]), np.hstack([frames[k[2]], frames[k[3]]])])[..., ::-1])
    print("wrote %s (%.1f MB, %d frames, %d ms per frame)" % (a.out, os.path.getsize(a.out) / 1e6, len(imgs), dur))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.137.200")
    ap.add_argument("--clip")
    ap.add_argument("--grab", help="re-render from a saved capture (work/<name>.grab.npz) instead of using the board")
    ap.add_argument("--start", type=int)
    ap.add_argument("--end", type=int)
    ap.add_argument("--step", type=int, default=4, help="source frames per GIF frame")
    ap.add_argument("--warm", type=int, default=150, help="empty-scene source frames (from clip frame 0) before the segment")
    ap.add_argument("--tmask", type=int, default=400)
    ap.add_argument("--src-fps", type=float, default=30.0, help="frame rate of the source footage (sets the GIF speed)")
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--lo-pct", type=float, default=20.0, help="percentile of the picture mapped to the coldest colour (purple)")
    ap.add_argument("--hi-pct", type=float, default=98.5, help="percentile mapped to the hottest colour")
    ap.add_argument("--gamma", type=float, default=0.9, help=">1 pushes the mid tones towards the cold end")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.grab:
        z = np.load(a.grab)
        raws, cors, boxarr, step = z["raw"], z["cor"], z["boxes"], int(z["step"])
    else:
        if not (a.clip and a.start is not None and a.end is not None):
            ap.error("--clip, --start and --end are needed to record")
        raws, cors, boxarr, step = grab(a)
    render(raws, cors, boxarr, step, a)


if __name__ == "__main__":
    main()
