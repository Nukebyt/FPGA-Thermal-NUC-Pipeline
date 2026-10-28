r"""One command for the live demo: the board plays a real thermal clip through the FPGA design and the laptop shows it.

  .venv\Scripts\python.exe host\run_demo.py                          # all clips one after the other, forever
  .venv\Scripts\python.exe host\run_demo.py --clip library           # one clip, looped
  .venv\Scripts\python.exe host\run_demo.py --clip library,corridor,park     # your own playlist
  .venv\Scripts\python.exe host\run_demo.py --clip corridor --scale 3
  .venv\Scripts\python.exe host\run_demo.py --list
  .venv\Scripts\python.exe host\run_demo.py --stop            # stop the playback on the board

What it does (the board must be booted from the SoC image and reachable by ssh, docs/bringup_3b.md):
  1. makes sure `frame_feeder serve` runs on the board (the register / picture server, port 5002);
  2. copies the clips to the board's RAM disk (/tmp) if they are not there yet (the SD card has no room);
  3. for each clip: sets T_MASK for the scene, resets the NUC and the detector (clean start), and starts `frame_feeder play CLIP FPS` on the
     board: the ARM itself writes the frames into the FPGA at the clip's frame rate, nothing is streamed from the laptop. A single clip
     is looped; several clips (the default is all of them) play one after the other, forever, each starting with its empty-scene warm-up;
  4. opens host/viewer.py --net --palette rainbow: raw (left) and NUC-corrected (right) in thermal colours, with the motion boxes.
Close the viewer window (or press q) and the playback is stopped.
Clips come from scripts/prepare_clips.py; the clip list below needs the files in data/clips/."""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
from thermal_net import NetBoard  # noqa: E402

# name: (file, T_MASK, fps, what to expect)
CLIPS = {
    "library":    ("library_720_400.u8",    640, 30, "a person walks into a dim room and leans over a desk"),
    "corridor":   ("corridor_430_400.u8",   400, 30, "a person walks towards the camera down a corridor"),
    "diningRoom": ("diningRoom_600_400.u8", 200, 30, "people walk past in a dining room"),
    "park":       ("park_100_450.u8",       256, 30, "people walk across a park (small, far away)"),
    "lakeSide":   ("lakeSide_1600_400.u8",   96, 30, "tiny distant people by a lake (hard: low contrast)"),
}
PLAY_LOG = "/tmp/play.log"


def ssh(host, cmd, check=True, timeout=60):
    r = subprocess.run(["ssh", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "root@" + host, cmd],
                       capture_output=True, text=True, timeout=timeout)
    if check and r.returncode != 0:
        sys.exit("ssh failed (%s): %s" % (cmd, (r.stderr or r.stdout).strip()))
    return r.stdout.strip()


def stop_play(host):
    ssh(host, "pkill -f 'frame_feeder play' ; true", check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.137.200")
    ap.add_argument("--clip", default="all", help="a clip name (looped), several separated by commas, or all (a playlist, the default); see --list")
    ap.add_argument("--fps", type=float, default=None, help="frame rate of the footage (default: 30)")
    ap.add_argument("--tmask", type=int, default=None, help="detector threshold in counts (default: per clip)")
    ap.add_argument("--scale", type=int, default=2, help="viewer window scale (1..4)")
    ap.add_argument("--view", choices=["corrected", "raw", "both"], default="both",
                    help="both = raw | corrected side by side (about 6 fps); corrected = one picture (about 12 fps)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--stop", action="store_true", help="stop the playback on the board and exit")
    ap.add_argument("--no-viewer", action="store_true", help="start the playback only (watch with host/viewer.py yourself)")
    a = ap.parse_args()

    if a.list:
        for k, (f, t, fps, what) in sorted(CLIPS.items()):
            print("%-11s %-24s T_MASK %3d  %s%s" % (k, f, t, what, "" if os.path.exists(os.path.join(ROOT, "data", "clips", f)) else "   [clip file missing]"))
        return 0
    if a.stop:
        stop_play(a.host)
        print("playback stopped")
        return 0

    names = sorted(CLIPS) if a.clip == "all" else [c.strip() for c in a.clip.split(",") if c.strip()]
    for n in names:
        if n not in CLIPS:
            sys.exit("unknown clip %r (see --list)" % n)
        if not os.path.exists(os.path.join(ROOT, "data", "clips", CLIPS[n][0])):
            sys.exit("%s is missing: run scripts/prepare_clips.py (see --list)" % os.path.join(ROOT, "data", "clips", CLIPS[n][0]))
    if a.clip == "all":
        names = [n for n in ("library", "corridor", "diningRoom", "park", "lakeSide")]
    playlist = len(names) > 1

    print("board %s: %s" % (a.host, ssh(a.host, "uname -n; ls /home/root/frame_feeder")))
    if not ssh(a.host, "pgrep -f 'frame_feeder serve' ; true", check=False):
        print("starting frame_feeder serve ...")
        ssh(a.host, "cd /home/root && (setsid ./frame_feeder serve > feeder.log 2>&1 < /dev/null &) ; sleep 1")
    stop_play(a.host)

    for n in names:                                               # clips to the board's RAM disk, once
        fname = CLIPS[n][0]
        local = os.path.join(ROOT, "data", "clips", fname)
        size = os.path.getsize(local)
        have = ssh(a.host, "stat -c %%s /tmp/%s 2>/dev/null ; true" % fname, check=False)
        if have != str(size):
            print("copying %s (%.1f MB) to the board's /tmp ..." % (fname, size / 1e6))
            t0 = time.time()
            r = subprocess.run(["scp", "-q", "-o", "BatchMode=yes", local, "root@%s:/tmp/%s" % (a.host, fname)], capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit("scp failed: " + r.stderr.strip())
            print("  %.1f s" % (time.time() - t0))

    caption = os.path.join(ROOT, "work", "demo_caption.txt")
    os.makedirs(os.path.dirname(caption), exist_ok=True)

    def start_clip(n):
        """Set up the design for clip n (threshold, clean NUC and detector) and start the board's player. Returns the Popen of the player
        (playlist: plays once and ends) or None (single clip: looped in the background on the board)."""
        fname, tmask, fps, what = CLIPS[n]
        tmask = a.tmask if a.tmask is not None else tmask
        fps = a.fps or fps
        b = NetBoard(a.host)
        b.wr(0x01, 0x2BF)                  # CTRL: NUC, learning, bad-pixel repair, boxes, sensor noise (typical)
        b.wr(0x06, tmask)                  # T_MASK
        b.wr(0x02, 3)                      # PULSE: coefficient reset + detector reset, so every clip starts clean
        b.close()
        open(caption, "w", encoding="utf-8").write("%s: %s   (T_MASK %d)\n" % (n, what, tmask))
        print("playing %s: %s (T_MASK %d, %g fps, %.0f s)" % (n, what, tmask, fps, os.path.getsize(os.path.join(ROOT, "data", "clips", fname)) / 76800 / fps))
        if playlist:
            return subprocess.Popen(["ssh", "-q", "-o", "BatchMode=yes", "root@" + a.host, "cd /home/root && ./frame_feeder play /tmp/%s %g > %s 2>&1" % (fname, fps, PLAY_LOG)])
        ssh(a.host, "cd /home/root && (setsid ./frame_feeder play /tmp/%s %g loop > %s 2>&1 < /dev/null &) ; sleep 1" % (fname, fps, PLAY_LOG))
        return None

    viewer_cmd = [sys.executable, os.path.join(HERE, "viewer.py"), "--net", a.host, "--palette", "rainbow", "--scale", str(a.scale),
                  "--view", a.view, "--caption-file", caption]
    if a.no_viewer and playlist:
        sys.exit("--no-viewer needs a single --clip (a playlist is driven by this script while the viewer runs)")
    first = start_clip(names[0])
    if a.no_viewer:
        print(r"watch it with:  .venv\Scripts\python.exe host\viewer.py --net %s --palette rainbow --scale %d --view %s      stop with:  host\run_demo.py --stop" % (a.host, a.scale, a.view))
        return 0
    viewer = subprocess.Popen(viewer_cmd)
    player = first
    try:
        i = 0
        while viewer.poll() is None:
            if playlist and player.poll() is not None:           # this clip ended: next one
                i = (i + 1) % len(names)
                player = start_clip(names[i])
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        if viewer.poll() is None:
            viewer.terminate()
        if player is not None and player.poll() is None:
            player.terminate()
        stop_play(a.host)
        print("playback stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
