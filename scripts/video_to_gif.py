r"""Convert a video (the phone recording of the live demo) to a README-sized GIF with OpenCV and Pillow (no ffmpeg needed).

  .venv\Scripts\python.exe scripts\video_to_gif.py demo-gif.mp4 docs/img/demo.gif --width 640 --fps 12 --colors 64
"""
import argparse
import os

import cv2
import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--fps", type=float, default=12.0)
    ap.add_argument("--colors", type=int, default=64)
    a = ap.parse_args()
    cap = cv2.VideoCapture(a.src)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    keep_every = max(1, int(round(src_fps / a.fps)))
    frames, i = [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i % keep_every == 0:
            h, w = f.shape[:2]
            f = cv2.resize(f, (a.width, int(round(h * a.width / w))), interpolation=cv2.INTER_AREA)
            frames.append(Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)))
        i += 1
    imgs = [f.quantize(colors=a.colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
    dur = int(round(1000.0 * keep_every / src_fps / 10)) * 10
    os.makedirs(os.path.dirname(os.path.abspath(a.dst)), exist_ok=True)
    imgs[0].save(a.dst, save_all=True, append_images=imgs[1:], duration=dur, loop=0, optimize=True)
    print("wrote %s: %d frames, %d ms per frame, %.1f MB" % (a.dst, len(imgs), dur, os.path.getsize(a.dst) / 1e6))


if __name__ == "__main__":
    main()
