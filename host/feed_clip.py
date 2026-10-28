r"""Stream a clip into the board's thermal design from the laptop (roadmap 3b): sw/frame_feeder on the ARM writes each frame into
the design's scene frame store, behind the scan, so every 60 Hz display frame shows exactly one source frame (never a mix).

  .venv\Scripts\python.exe host\feed_clip.py --host 192.168.137.200 --clip data/clips/park_0_600.u8 --loop
  .venv\Scripts\python.exe host\feed_clip.py --host 192.168.137.200 --video person.mp4 --repeat 2
  .venv\Scripts\python.exe host\feed_clip.py --host 192.168.137.200 --images some\folder --loop

Sources: --clip (raw 320x240 8-bit frames, scripts/prepare_clips.py), --video (any file OpenCV reads), --images (a folder of images,
sorted by name). Colour frames are converted to grey, scaled to height 240 and cropped / padded to 320 wide.
--repeat N shows every source frame N times (the design runs at 60 Hz: use 2 for a 30 fps source, 1 for a 60 fps one).
At the start the script switches the emulator's own moving rectangles off (CSR FEED_CTRL) and, unless --keep-ctrl, selects the
viewer's default control word (NUC / learning / bad-pixel repair / noise on) so the clip is seen through a realistic sensor; use
--no-noise for the clean footage. Watch the result with host/viewer.py --net HOST."""
import argparse
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from thermal_net import NetBoard, FRAME_BYTES, ST_OK, ST_TORN, W, H  # noqa: E402

CTRL_DEFAULT = 0x2BF          # nuc learn bp overlay noise, preset typical, csr_use, split view, gray (host/viewer.py)
CSR_CTRL, CSR_FEED_CTRL = 0x01, 0x24


def fit(img):
    """Grey, scaled to height H, centre-cropped or edge-padded to width W (the same rule as model/datasets.py)."""
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = img.shape[:2]
    nw = max(1, int(round(w * H / h)))
    out = cv2.resize(img, (nw, H), interpolation=cv2.INTER_AREA)
    if nw > W:
        x0 = (nw - W) // 2
        out = out[:, x0:x0 + W]
    elif nw < W:
        pl = (W - nw) // 2
        out = np.pad(out, ((0, 0), (pl, W - nw - pl)), mode="edge")
    if out.dtype != np.uint8:
        out = np.clip(out, 0, 255).astype(np.uint8)
    return out


def frames_of(a):
    if a.clip:
        raw = np.fromfile(a.clip, np.uint8)
        n = raw.size // FRAME_BYTES
        if n < 1:
            sys.exit("%s holds less than one 320x240 frame" % a.clip)
        return [raw[i * FRAME_BYTES:(i + 1) * FRAME_BYTES] for i in range(n)]
    if a.video:
        cap = cv2.VideoCapture(a.video)
        out = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            out.append(fit(f).ravel())
        return out
    files = sorted(os.path.join(a.images, f) for f in os.listdir(a.images)
                   if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")))
    return [fit(cv2.imread(f, cv2.IMREAD_COLOR)).ravel() for f in files]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.137.200")
    ap.add_argument("--port", type=int, default=5002)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--clip")
    src.add_argument("--video")
    src.add_argument("--images")
    ap.add_argument("--repeat", type=int, default=1, help="show each source frame this many display frames")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--no-noise", action="store_true", help="clean footage: sensor non-uniformity off")
    ap.add_argument("--keep-ctrl", action="store_true", help="do not touch the CTRL register")
    ap.add_argument("--dry", action="store_true", help="load and convert the frames, do not connect")
    a = ap.parse_args()

    frames = frames_of(a)
    print("%d source frame(s), %d display frames per loop" % (len(frames), len(frames) * a.repeat))
    if a.dry:
        return 0
    b = NetBoard(a.host, a.port)
    print("connected to %s, ID %08x" % (b.path, b.ping()))
    if b.rd(0x23) & 1 == 0:
        sys.exit("this bitstream has no scene frame store (CAPS bit 0 = 0): load the SoC build (quartus/thermal_soc)")
    b.wr(CSR_FEED_CTRL, 0)                                  # the clip brings its own moving objects
    if not a.keep_ctrl:
        b.wr(CSR_CTRL, CTRL_DEFAULT & ~(0x10 if a.no_noise else 0))
    t0 = time.time()
    shown, torn, n, last = 0, 0, 0, time.time()
    try:
        while True:
            for f in frames:
                for _ in range(a.repeat):
                    st, _x = b.feed(f)
                    shown += 1
                    torn += st == ST_TORN
                    if st not in (ST_OK, ST_TORN):
                        sys.exit("feed failed, status %d (is the FPGA image running? see sw/frame_feeder.c)" % st)
                n += 1
                if time.time() - last > 2.0:
                    print("source frame %d  display frames %d  %.1f frames/s  torn %d" % (n, shown, shown / (time.time() - t0), torn))
                    last = time.time()
            if not a.loop:
                break
    except KeyboardInterrupt:
        pass
    print("done: %d display frames, %d torn (%.1f frames/s); board counters: %s" % (shown, torn, shown / max(time.time() - t0, 1e-3), b.stat()))
    b.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
