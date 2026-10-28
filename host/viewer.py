"""Viewer: the board's picture, boxes and status on the laptop, over the USB-Blaster or over Ethernet (no VGA monitor needed).

JTAG: needs a bitstream with the host bus (build 4 or later: quartus/ip/jtag_host + rtl/frame_cap.v + rtl/host_if.v) and
Quartus' System Console (C:\\intelFPGA_lite\\21.1\\quartus\\sopc_builder\\bin\\system-console.exe).
Ethernet (--net HOST): the SoC build (quartus/thermal_soc) with sw/frame_feeder running on the board's Linux; no USB-Blaster
and a much faster readout. Real clips are streamed into the design with host/feed_clip.py.

  .venv\\Scripts\\python.exe host\\viewer.py            # take over the controls (switches are ignored while it runs)
  .venv\\Scripts\\python.exe host\\viewer.py --passive  # only watch; the board switches stay in charge
  .venv\\Scripts\\python.exe host\\viewer.py --net 192.168.137.200   # over Ethernet instead of JTAG
  .venv\\Scripts\\python.exe host\\viewer.py --save-raw work\\cap_board.txt --once   # one capture for check_capture.py

Keys (window focused):
  n NUC on/off   l learning on/off   b bad-pixel repair   o boxes   e sensor noise   p noise preset (mild/typical/severe)
  v view (corrected / raw / side by side)   i iron palette (not with --palette rainbow)   k clear NUC coefficients (KEY1)   r reset detector (KEY2)
  w learning window (0 = forever / 64 / 256 / 1024 frames)   c clear latency statistics   s save PNG   q quit
Each refresh captures one whole frame in the FPGA (frame_cap), then reads it out (76,800 bytes) over JTAG or the network.
Boxes are the latest published box list; at a few frames per second they can lag the picture by a frame or two."""
import argparse
import os
import subprocess
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import thermal_palette  # noqa: E402
from model.display_model import iron_palette  # noqa: E402

SYSCON = r"C:\intelFPGA_lite\21.1\quartus\sopc_builder\bin\system-console.exe"
W, H = 320, 240
FB = 0x20000
# CSR word addresses (rtl/csr_regs.v)
ID, CTRL, PULSE, DET_WARM, LEARN_N, CAP, CAP_FID = 0x00, 0x01, 0x02, 0x07, 0x0D, 0x0E, 0x0F
STATUS, FRAMES, BOXINFO, LAT_FLAG, LATF_MIN, LATF_MAX, LAT_N, BADCNT = 0x10, 0x11, 0x12, 0x1D, 0x20, 0x21, 0x22, 0x17
CTRL_DEFAULT = 0x2BF          # nuc learn bp overlay noise, preset typical, csr_use, split view, gray
PRESETS = ("mild", "typical", "severe")


JTAGCONFIG = os.path.join(os.path.dirname(SYSCON), "..", "..", "bin64", "jtagconfig.exe")


def slow_jtag_clock(rate="6M"):
    """The cable's default 24 MHz TCK is too close to clk25 for the JTAG master's clock crossing: every read hangs
    (docs/bug_log.md entry 22). Run the cable at 6 MHz instead (cable 1 = the first USB-Blaster)."""
    try:
        subprocess.run([JTAGCONFIG, "--setparam", "1", "JtagClock", rate], capture_output=True, timeout=30)
    except Exception as e:
        print("warning: could not set the JTAG clock (%s); reads may hang" % e)


class Board:
    """Line protocol to host/jtag_server.tcl running in System Console."""

    def __init__(self, syscon=SYSCON):
        slow_jtag_clock()
        tcl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jtag_server.tcl")
        self.p = subprocess.Popen([syscon, "--cli", "--script=" + tcl], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, bufsize=1)
        t0 = time.time()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("System Console exited before it was ready")
            line = line.strip().lstrip("% ").strip()     # System Console may prefix its "% " prompt
            if line.startswith("READY"):
                self.path = line[6:]
                break
            if line.startswith("ERR"):
                raise RuntimeError(line)
            if time.time() - t0 > 120:
                raise RuntimeError("System Console did not become ready in 120 s")

    def _cmd(self, s):
        self.p.stdin.write(s + "\n")
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("System Console exited")
            line = line.strip().lstrip("% ").strip()     # System Console may prefix its "% " prompt
            if line.startswith("OK"):
                return line[2:].split()
            if line.startswith("ERR"):
                raise RuntimeError(line)
            # anything else is System Console chatter: skip

    def rd(self, word):
        return int(self._cmd("R 0x%x" % (4 * word))[0], 16)

    def wr(self, word, value):
        self._cmd("W 0x%x 0x%x" % (4 * word, value & 0xFFFFFFFF))

    def block(self, byte_addr, n):
        return np.array([int(v, 16) for v in self._cmd("B 0x%x %d" % (byte_addr, n))], np.uint32)

    def close(self):
        try:
            self._cmd("Q")
            self.p.stdin.close()
            self.p.wait(10)
        except Exception:
            self.p.kill()


def capture(b, src, timeout=2.0):
    """Arm frame_cap for the next whole frame of `src` (0 corrected, 1 raw), wait, read it. Returns (fid, image)."""
    b.wr(CAP, 0x100 | src)
    t0 = time.time()
    while not (b.rd(CAP) >> 17) & 1:
        if time.time() - t0 > timeout:
            raise RuntimeError("capture did not finish (is the design running? LEDR4 on?)")
    fid = b.rd(CAP_FID)
    words = b.block(FB, W * H // 4)
    img = np.stack([(words >> (8 * k)) & 255 for k in range(4)], -1).reshape(H, W).astype(np.uint8)
    return fid, img, words


def read_boxes(b):
    info = b.rd(BOXINFO)
    n_obj, listed = info & 0xFF, (info >> 8) & 0x1F
    boxes = []
    for i in range(listed):
        w0, w1 = b.rd(0x30 + 4 * i), b.rd(0x31 + 4 * i)
        boxes.append((w0 & 0x1FF, (w0 >> 9) & 0x1FF, w1 & 0x1FF, (w1 >> 9) & 0x1FF))
    return n_obj, boxes


def render(img8, iron, boxes, overlay, scale, win=None):
    """win: a thermal_palette.LiveWindow for the rainbow palette (--palette rainbow); None = the board's gray / iron."""
    if win is not None:
        rgb = thermal_palette.colour(img8, win.update(img8))
    else:
        rgb = iron_palette(img8) if iron else np.repeat(img8[..., None], 3, -1)
    bgr = np.ascontiguousarray(rgb[..., ::-1]).astype(np.uint8)
    bgr = cv2.resize(bgr, (img8.shape[1] * scale, img8.shape[0] * scale), interpolation=cv2.INTER_NEAREST)
    if overlay:
        for (x0, y0, x1, y1) in boxes:
            cv2.rectangle(bgr, (x0 * scale, y0 * scale), ((x1 + 1) * scale - 1, (y1 + 1) * scale - 1), (0, 255, 0), 1)
    return bgr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passive", action="store_true", help="do not take over the controls")
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--once", action="store_true", help="one capture, then exit (with --save-raw)")
    ap.add_argument("--save-raw", default=None, help="write the capture in scripts/check_capture.py format")
    ap.add_argument("--src", type=int, default=0, help="source for --once (0 corrected, 1 raw)")
    ap.add_argument("--syscon", default=SYSCON)
    ap.add_argument("--palette", choices=["board", "rainbow"], default="board",
                    help="board: gray / iron as the 'i' key selects; rainbow: thermal-camera colours (purple-blue cold, orange-red warm)")
    ap.add_argument("--view", choices=["corrected", "raw", "both"], default="both",
                    help="start view (key v cycles); a single picture refreshes about twice as fast as both side by side")
    ap.add_argument("--caption-file", default=None, help="text file whose first line is drawn on the picture (host/run_demo.py: the clip name)")
    ap.add_argument("--net", default=None, metavar="HOST[:PORT]", help="talk to sw/frame_feeder on the board instead of JTAG")
    a = ap.parse_args()

    if a.net:
        from thermal_net import NetBoard
        host, _, port = a.net.partition(":")
        b = NetBoard(host, int(port) if port else 5002)
    else:
        b = Board(a.syscon)
    ident = b.rd(ID)
    print("connected: %s  ID %08x (build %d)" % (b.path, ident, ident & 0xFFFF))
    if ident >> 16 != 0x7A11:
        print("unexpected ID - wrong bitstream?")
        b.close()
        return 1
    if a.once:
        fid, img, words = capture(b, a.src)
        if a.save_raw:
            with open(a.save_raw, "w") as f:
                f.write("fid %d\n" % fid + "".join("%08x\n" % w for w in words))
            print("saved frame %d to %s" % (fid, a.save_raw))
        b.close()
        return 0

    ctrl = b.rd(CTRL) if a.passive else CTRL_DEFAULT
    if not a.passive:
        b.wr(CTRL, ctrl)
    view = {"corrected": 0, "raw": 1, "both": 2}[a.view]           # 0 corrected, 1 raw, 2 side by side
    win_steps = (0, 64, 256, 1024)
    cv2.namedWindow("thermal", cv2.WINDOW_AUTOSIZE)
    t_last, fps = time.time(), 0.0
    wins = [thermal_palette.LiveWindow(), thermal_palette.LiveWindow()] if a.palette == "rainbow" else [None, None]
    try:
        while True:
            imgs = []
            if view in (1, 2):
                imgs.append(capture(b, 1)[1])
            if view in (0, 2):
                fid, img, _ = capture(b, 0)
                imgs.append(img)
            else:
                fid = b.rd(CAP_FID)
            n_obj, boxes = read_boxes(b)
            st, lmin, lmax, nlat, bad = b.rd(STATUS), b.rd(LATF_MIN), b.rd(LATF_MAX), b.rd(LAT_N), b.rd(BADCNT)
            ctrl_now = b.rd(CTRL)
            learn_n = b.rd(LEARN_N)
            iron = bool((ctrl_now >> 10) & 1)
            overlay = bool((ctrl_now >> 3) & 1)
            wsel = wins if len(imgs) == 2 else [wins[0] if view == 1 else wins[1]]       # raw and corrected keep separate windows
            tiles = [render(im, iron, boxes if (len(imgs) == 1 or k == 1) else [], overlay, a.scale, wsel[k]) for k, im in enumerate(imgs)]
            frame = np.concatenate(tiles, 1) if len(tiles) > 1 else tiles[0]
            if a.caption_file:
                try:
                    cap = open(a.caption_file, encoding="utf-8").readline().strip()
                except OSError:
                    cap = ""
                if cap:
                    frame = frame.copy()
                    cv2.putText(frame, cap, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4, cv2.LINE_AA)
                    cv2.putText(frame, cap, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
            now = time.time()
            fps = 0.8 * fps + 0.2 / max(now - t_last, 1e-3)
            t_last = now
            lines = [
                "frame %d   objects %d   viewer %.1f fps   %s" % (fid, n_obj, fps,
                                                                "PASSIVE (switches)" if a.passive else "host control"),
                "latency end-of-frame -> boxes: min %d  max %d cycles (%.1f us), jitter %d, frames %d"
                % (lmin, lmax, lmax / 25.0, lmax - lmin, nlat),
                "NUC %s  learning %s (window %s)  bad-pixel %s (%d px)  noise %s %s  gain %s  boxes %s (%d listed)"
                % ("on" if ctrl_now & 1 else "off", "RUNNING" if (st >> 7) & 1 else "frozen",
                   learn_n if learn_n else "forever", "on" if ctrl_now & 4 else "off", bad,
                   "on" if ctrl_now & 16 else "off", PRESETS[min((ctrl_now >> 5) & 3, 2)],
                   "on" if (st >> 6) & 1 else "off", "on" if overlay else "OFF (press o)", len(boxes)),
                "keys: n l b o e p v i k r w c s q" + ("" if view != 2 else "    (left raw, right corrected)"),
            ]
            pad = np.zeros((18 * len(lines) + 8, frame.shape[1], 3), np.uint8)
            for i, t in enumerate(lines):
                cv2.putText(pad, t, (6, 18 * i + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (220, 220, 220), 1, cv2.LINE_AA)
            cv2.imshow("thermal", np.concatenate([frame, pad], 0))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("s"):
                name = time.strftime("work/viewer_%Y%m%d_%H%M%S.png")
                os.makedirs("work", exist_ok=True)
                cv2.imwrite(name, frame)
                print("saved", name)
            if a.passive or key == 255:
                continue
            bits = {ord("n"): 0, ord("l"): 1, ord("b"): 2, ord("o"): 3, ord("e"): 4, ord("i"): 10}
            if key in bits:
                ctrl_now ^= 1 << bits[key]
            elif key == ord("p"):
                ctrl_now = (ctrl_now & ~0x60) | ((((ctrl_now >> 5) & 3) + 1) % 3 << 5)
            elif key == ord("v"):
                view = (view + 1) % 3
            elif key == ord("k"):
                b.wr(PULSE, 1)
            elif key == ord("r"):
                b.wr(PULSE, 2)
            elif key == ord("c"):
                b.wr(PULSE, 8)
            elif key == ord("w"):
                b.wr(LEARN_N, win_steps[(win_steps.index(learn_n) + 1) % 4 if learn_n in win_steps else 0])
            b.wr(CTRL, ctrl_now | 0x80)
    finally:
        if not a.passive:
            b.wr(CTRL, b.rd(CTRL) & ~0x80)        # hand control back to the switches
        b.close()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    sys.exit(main())
