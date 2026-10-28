"""Protocol and chase tests of sw/frame_feeder.c against its built-in FPGA model (make mock). Standard library only; run in
Linux / WSL:   make -C sw test

The mock scans the frame store at 60 frames/s of wall-clock time and tags every row of every displayed frame, so it counts torn
displayed frames independently of the feeder's own check. Frames sent here are flat: every pixel of frame n is n & 255, so a frame
that mixes two feeds shows up as rows with different tags."""
import os
import re
import socket
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "host"))
import thermal_net as tn  # noqa: E402

PORT = 5900 + os.getpid() % 90
FAILS = []


def check(name, ok, detail=""):
    print(("PASS  " if ok else "FAIL  ") + name + (("   " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


def start(env_extra=None):
    d = tempfile.mkdtemp()
    env = dict(os.environ, MOCK_RESULT=os.path.join(d, "result.txt"), MOCK_LOG=os.path.join(d, "frames.log"))
    env.update(env_extra or {})
    cmd = os.environ.get("FEEDER_CMD", os.path.join(HERE, "frame_feeder_mock")).split()      # e.g. "qemu-arm frame_feeder_mock_arm"
    p = subprocess.Popen(cmd + ["serve", str(PORT)], env=env, stderr=subprocess.PIPE)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", PORT), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.05)
    else:
        raise RuntimeError("server did not start")
    return p, d


def stop(p, d):
    p.terminate()
    err = p.communicate(timeout=10)[1].decode()
    res = open(os.path.join(d, "result.txt")).read()
    m = re.search(r"frames (\d+) torn (\d+) feeds (\d+) feed_torn (\d+)", res)
    return [int(v) for v in m.groups()], open(os.path.join(d, "frames.log")).read().splitlines(), err


def flat(n):
    return bytes([n & 255]) * tn.FRAME_BYTES


def main():
    # ---------------------------------------------------------------- registers, blocks, errors
    p, d = start()
    b = tn.NetBoard("127.0.0.1", PORT)
    check("PING returns the ID register", b.ping() == 0x7A110006, "%08x" % b.ping())
    check("CSR read: ID", b.rd(0x00) == 0x7A110006)
    check("CSR read: CAPS says feed present", b.rd(0x23) == 1)
    b.wr(0x24, 0)
    check("CSR write / read back", b.rd(0x24) == 0)
    r1 = b.rd(0x25)
    time.sleep(0.1)
    r2 = b.rd(0x25)
    check("FEED_ROW advances with the scan (about 1440 rows in 100 ms)", 1000 < r2 - r1 < 1900, "%d rows" % (r2 - r1))
    st, _, _ = b._cmd(tn.CMD_RD, 0x7FFFC, 4)
    check("read past the bus window is refused", st == tn.ST_BADADDR)
    st, _, _ = b._cmd(tn.CMD_RD, 2, 1)
    check("unaligned read is refused", st == tn.ST_BADADDR)
    st, _, _ = b._cmd(99)
    check("unknown command is answered", st == tn.ST_BADCMD)
    b.write_block(tn.W * 0 + 0x40000, [0x01020304] * 80)        # direct write of one row into the frame store
    # a bad request size on FEED drops the connection (payload cannot be resynchronised) but the server keeps going
    b2 = tn.NetBoard("127.0.0.1", PORT)
    b2.s.sendall(struct.pack("<IIII", tn.MAGIC, tn.CMD_FEED, 0, 123))
    try:
        got = b2.s.recv(16)
    except OSError:
        got = b""
    check("bad FEED size closes that connection", got == b"")
    check("server still alive after it", b.ping() == 0x7A110006)
    b2.close()

    # ---------------------------------------------------------------- full-speed feed: paced by the scan, never torn
    N = 90
    t0 = time.time()
    shown = []
    for n in range(N):
        s, x = b.feed(flat(n + 1))
        shown.append((s, x))
    dt = time.time() - t0
    check("%d frames fed back to back, none torn" % N, all(s == tn.ST_OK for s, _ in shown), "statuses %s" % sorted({s for s, _ in shown}))
    fps = N / dt
    check("feed rate is paced by the scan: about 60 frames/s (never above)", 45 < fps < 62, "%.1f frames/s" % fps)
    idx = [x for _, x in shown]
    check("display frame index of each new frame increases by one", all(b_ - a_ == 1 for a_, b_ in zip(idx, idx[1:])), "%s..." % idx[:6])
    stat = b.stat()
    check("STAT counts the feeds and no torn frames", stat["feeds"] == N and stat["torn"] == 0, str(stat))

    # ---------------------------------------------------------------- capture of the last fed frame (mock: scene snapshot)
    b.wr(0x0E, 0x100)
    for _ in range(100):
        if (b.rd(0x0E) >> 17) & 1:
            break
        time.sleep(0.01)
    cap = b.block(0x20000, tn.FRAME_BYTES // 4)
    words = [int(v) for v in cap]
    check("capture buffer read back through the block read holds the last frame (all %d)" % ((N) & 255),
          all(v == 0x01010101 * (N & 255) for v in words[:5000]) and len(words) == 19200, "first word %08x" % words[0])

    # ---------------------------------------------------------------- slow source: frames repeat, never torn
    for n in range(10):
        s, x = b.feed(flat(200 + n))
        time.sleep(0.05)
        if s != tn.ST_OK:
            check("slow feed (20 frames/s) stays untorn", False, "status %d" % s)
            break
    else:
        check("slow feed (20 frames/s) stays untorn", True)

    # ---------------------------------------------------------------- two clients at once
    viewer = tn.NetBoard("127.0.0.1", PORT)
    reads = 0
    t_end = time.time() + 0.6
    torn_two = 0
    n = 0
    while time.time() < t_end:
        s, _ = b.feed(flat(100 + n)); n += 1
        torn_two += s != tn.ST_OK
        for _ in range(20):
            viewer.rd(0x25); reads += 1
    check("two clients interleaved (feeder + register reads)", torn_two == 0 and reads > 100, "%d feeds, %d reads, %d torn" % (n, reads, torn_two))
    viewer.close()
    b.close()
    (frames, torn, feeds, feed_torn), log, err = stop(p, d)
    check("mock: no displayed frame mixed two feeds", torn == 0, "%d displayed frames, %d torn" % (frames, torn))
    check("mock: displayed frames were logged", frames > 50 and len(log) == frames, "%d" % frames)

    # ---------------------------------------------------------------- a slow ARM: the mock sees the tearing the feeder reports
    p, d = start({"MOCK_WRITE_DELAY_NS": "2500"})            # 19,200 writes x 2.5 us = 48 ms: far behind the scan
    b = tn.NetBoard("127.0.0.1", PORT)
    sts = [b.feed(flat(1 + n))[0] for n in range(6)]
    b.close()
    (frames, torn, feeds, feed_torn), log, err = stop(p, d)
    check("a too-slow writer is reported torn by the feeder", feed_torn >= 1 and tn.ST_TORN in sts, "statuses %s" % sts)
    check("the mock independently sees displayed frames that mix two feeds", torn >= 1, "%d of %d displayed frames" % (torn, frames))

    # ---------------------------------------------------------------- scan not running: the feeder gives up, does not hang
    p, d = start({"MOCK_FREEZE_SCAN": "1"})
    b = tn.NetBoard("127.0.0.1", PORT, timeout=10)
    t0 = time.time()
    s, _ = b.feed(flat(1))
    check("a frozen scan counter is reported (status NOSCAN) within about 0.3 s", s == tn.ST_NOSCAN and time.time() - t0 < 2.0, "status %d after %.2f s" % (s, time.time() - t0))
    b.close()
    stop(p, d)

    print("\nRESULT: " + ("PASS" if not FAILS else "FAIL (%s)" % ", ".join(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
