"""Network client of sw/frame_feeder.c (runs on the DE10-Standard's ARM): register / buffer access and clip feeding over TCP.

    from thermal_net import NetBoard
    b = NetBoard("192.168.137.200")          # port 5002
    b.rd(0x00)                                # ID register (CSR word address, like host/viewer.py's Board)
    status, shown = b.feed(frame_bytes)       # 76,800 bytes, 320x240, 8 bit, raster order

Same rd / wr / block interface as host/viewer.py's JTAG Board, so the viewer runs on either (viewer.py --net HOST).
Standard library only (numpy is used for block() when available). Protocol: see the header of sw/frame_feeder.c."""
import socket
import struct

MAGIC = 0x4D524854
CMD_PING, CMD_RD, CMD_WR, CMD_WRB, CMD_FEED, CMD_STAT = range(6)
ST_OK, ST_TORN, ST_NOSCAN, ST_BADSIZE, ST_BADCMD, ST_BADADDR = range(6)
W, H = 320, 240
FRAME_BYTES = W * H
STAT_FIELDS = ("feeds", "torn", "errors", "last_us", "max_us", "min_us", "rows_read", "clients", "bus_reads", "bus_writes")
try:
    import numpy as np
except ImportError:                      # the mock test runs without numpy
    np = None


class NetError(RuntimeError):
    pass


class NetBoard:
    def __init__(self, host, port=5002, timeout=20.0):
        self.path = "%s:%d (frame_feeder)" % (host, port)
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def _recv(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise NetError("connection closed by the board")
            buf += chunk
        return bytes(buf)

    def _cmd(self, cmd, a=0, b=0, payload=b""):
        self.s.sendall(struct.pack("<IIII", MAGIC, cmd, a, b) + payload)
        magic, status, n, x = struct.unpack("<IiII", self._recv(16))
        if magic != MAGIC:
            raise NetError("bad reply magic %08x" % magic)
        return status, self._recv(n) if n else b"", x

    # ---- the Board interface used by host/viewer.py (CSR word addresses for rd/wr, byte addresses for block)
    def rd(self, word):
        st, data, _ = self._cmd(CMD_RD, 4 * word, 1)
        if st != ST_OK:
            raise NetError("read of word 0x%x failed (status %d)" % (word, st))
        return struct.unpack("<I", data)[0]

    def wr(self, word, value):
        st, _, _ = self._cmd(CMD_WR, 4 * word, value & 0xFFFFFFFF)
        if st != ST_OK:
            raise NetError("write of word 0x%x failed (status %d)" % (word, st))

    def block(self, byte_addr, n):
        st, data, _ = self._cmd(CMD_RD, byte_addr, n)
        if st != ST_OK:
            raise NetError("block read at 0x%x failed (status %d)" % (byte_addr, st))
        return np.frombuffer(data, "<u4").copy() if np is not None else list(struct.unpack("<%dI" % n, data))

    def write_block(self, byte_addr, words):
        data = struct.pack("<%dI" % len(words), *words)
        st, _, _ = self._cmd(CMD_WRB, byte_addr, len(words), data)
        if st != ST_OK:
            raise NetError("block write at 0x%x failed (status %d)" % (byte_addr, st))

    # ---- feeder specific
    def ping(self):
        return self._cmd(CMD_PING)[2]

    def feed(self, frame):
        """frame: FRAME_BYTES bytes (or a uint8 array). Returns (status, display frame index of the first appearance)."""
        data = frame.tobytes() if hasattr(frame, "tobytes") else bytes(frame)
        if len(data) != FRAME_BYTES:
            raise ValueError("a frame is %d bytes (320x240, 8 bit)" % FRAME_BYTES)
        st, _, x = self._cmd(CMD_FEED, 0, FRAME_BYTES, data)
        return st, x

    def stat(self):
        st, data, _ = self._cmd(CMD_STAT)
        return dict(zip(STAT_FIELDS, struct.unpack("<10I", data)))

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass
