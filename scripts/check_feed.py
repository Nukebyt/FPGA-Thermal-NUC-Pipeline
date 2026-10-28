"""Check the two captures of tb/thermal_sys_feed_tb.v against the system model.

cap1: taken while frame A was in the frame store.  cap2: taken of the frame in which the writer switched the frame store
from A to B by chasing the scan (row r rewritten after the scan read it and before it read it again). A torn frame would
show rows of A inside B. info: "k0 <frame in progress when the chase started> torn <deadline misses seen by the TB>".
Raw source frames, noise off, objects off (the TB sets CTRL accordingly)."""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from model import display_model as dm, pipeline_int as pi, sensor_emu as se  # noqa: E402
from check_capture import load_capture  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--cap1", required=True)
    ap.add_argument("--cap2", required=True)
    ap.add_argument("--info", required=True)
    a = ap.parse_args()
    A = np.load(os.path.join(a.dir, "A.npy"))
    B = np.load(os.path.join(a.dir, "B.npy"))
    info = open(a.info).read().split()
    k0, torn = int(info[info.index("k0") + 1]), int(info[info.index("torn") + 1])
    fid1, img1 = load_capture(a.cap1)
    fid2, img2 = load_capture(a.cap2)
    emu = se.SensorEmu(None, "typical", scene8=A, obj_en=False)
    emu.noise_en = False
    model = dm.SystemModel(emu, pi.Cfg(DET_WARM=2))
    model.scene_fn = lambda k: A if k <= k0 else B
    model.run_source(max(fid1, fid2) + 1)
    e1, e2 = model.src[fid1]["raw8"], model.src[fid2]["raw8"]
    d1, d2 = int((img1 != e1).sum()), int((img2 != e2).sum())
    # what a frame with the other scene (or a mix) would look like, to show the check can fail
    alt = dm.SystemModel(se.SensorEmu(None, "typical", scene8=A, obj_en=False), pi.Cfg(DET_WARM=2))
    alt.emu.noise_en = False
    alt.scene_fn = lambda k: A
    alt.run_source(fid2 + 1)
    d_alt = int((img2 != alt.src[fid2]["raw8"]).sum())
    print("cap1 (frame %d, store holds A): %d of %d pixels differ from the model" % (fid1, d1, img1.size))
    print("cap2 (frame %d = k0+1, the switch frame, k0 = %d): %d of %d pixels differ from the model (an A-only frame would differ in %d)"
          % (fid2, k0, d2, img2.size, d_alt))
    print("writer deadline misses seen by the testbench: %d" % torn)
    ok = d1 == 0 and d2 == 0 and fid2 == k0 + 1 and torn == 0 and d_alt > img2.size // 2 and len(np.unique(img2)) >= 20
    print("RESULT: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
