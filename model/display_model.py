"""Python twin of the display path (rtl/tone_win.v + rtl/disp_path.v): tone mapping, palette, views, box overlay,
2x scaling, and the frame bookkeeping of the whole system (which source frame / box list is on screen).

Frame alignment (see docs/design.md):  VGA frame f shows SOURCE frame f-1 (the tick grid starts 4 lines before the
first active line, so source frame s is processed during the end of VGA frame s and shown in VGA frame s+1), tone-mapped
with the window computed from source frame f-2, and with the box list of source frame f-2 drawn on it (published during the
vertical blanking of VGA frame f-1; one-frame lag).
"""
import numpy as np

RAIL_HI = 16383


class ToneWindow:
    """Window for the NEXT frame from this frame's min/max, excluding pixels whose raw value is at a rail."""

    def __init__(self):
        self.lo, self.sh = 0, 6

    @staticmethod
    def _shift(rng):
        sh = 0
        while (rng >> sh) > 255:
            sh += 1
        return sh

    def update(self, values, raw):
        keep = (raw != 0) & (raw != RAIL_HI)
        if keep.any():
            mn, mx = int(values[keep].min()), int(values[keep].max())
        else:
            mn, mx = 0x3FFF, 0                    # RTL reset values: nothing seen
        rng = mx - mn if mx >= mn else 0
        self.lo, self.sh = mn, self._shift(rng)   # (RTL: sh limited to 6 by the priority loop; ranges here stay < 2**14)

    def map(self, v):
        d = v.astype(np.int64) - self.lo
        d = np.where(d < 0, 0, d) >> self.sh
        return np.minimum(d, 255).astype(np.uint8)


def iron_palette(v8):
    v = v8.astype(np.int64)
    r = np.where(v < 128, v * 2, 255)
    g = np.where(v < 128, 0, (v - 128) * 2)
    b = np.where(v < 64, v * 4, np.where(v < 128, 255 - (v - 64) * 4, np.where(v < 192, 0, (v - 192) * 4)))
    return np.stack([r, g, b], -1).astype(np.uint8)


def box_outline_mask(shape, boxes):
    """Source-resolution mask of box outlines. boxes: list of (xmin, ymin, xmax, ymax, area)."""
    h, w = shape
    m = np.zeros((h, w), bool)
    for (x0, y0, x1, y1, _a) in boxes:
        m[y0:y1 + 1, x0] = True
        m[y0:y1 + 1, x1] = True
        m[y0, x0:x1 + 1] = True
        m[y1, x0:x1 + 1] = True
    return m


def render(corr8, raw8, view=2, iron=False, overlay=True, boxes=()):
    """Returns the 480x640x3 uint8 VGA frame."""
    h, w = corr8.shape
    c = np.repeat(np.repeat(corr8, 2, 0), 2, 1)
    r = np.repeat(np.repeat(raw8, 2, 0), 2, 1)
    if view == 1:
        v8 = r
    elif view == 2:
        v8 = np.where(np.arange(2 * w)[None, :] < 320, r, c)
    else:
        v8 = c
    rgb = iron_palette(v8) if iron else np.repeat(v8[..., None], 3, -1)
    if overlay and len(boxes):
        m = np.repeat(np.repeat(box_outline_mask((h, w), boxes), 2, 0), 2, 1)
        rgb = rgb.copy()
        rgb[m] = (0, 255, 0)
    return rgb


class SystemModel:
    """The board design as a frame-level model: sensor emulator -> pipeline_int -> display."""

    def __init__(self, emu, cfg, view=2, iron=False, overlay=True):
        from . import pipeline_int as pi
        self.pi = pi
        self.emu, self.cfg = emu, cfg
        self.state = pi.State.init(cfg)
        self.tw_c, self.tw_r = ToneWindow(), ToneWindow()
        self.view, self.iron, self.overlay = view, iron, overlay
        self.src = []            # per source frame: dict(corr8, raw8, boxes, clean, ...)
        self.scene_fn = None     # FEED build: frame index -> the 8-bit scene held in the frame store during that frame

    def run_source(self, S):
        for _ in range(S):
            if self.scene_fn is not None:
                self.emu.set_scene(self.scene_fn(len(self.src)))
            raw = self.emu.frame_raw()
            clean = self.emu.clean()
            gt = self.emu.motion_mask()
            self.emu.advance()
            out = self.pi.frame_step(self.cfg, self.state, raw)
            corr8 = self.tw_c.map(out.y14)
            raw8 = self.tw_r.map(raw)
            self.src.append(dict(raw=raw, y14=out.y14, corr8=corr8, raw8=raw8, boxes=list(out.boxes), mask=out.mask,
                                 clean=clean, gt=gt, n_obj=out.n_objects))
            self.tw_c.update(out.y14.astype(np.int64), raw)      # window for the NEXT frame
            self.tw_r.update(raw.astype(np.int64), raw)

    def vga_frame(self, f):
        """Expected VGA frame f (f >= 1)."""
        s = f - 1
        d = self.src[s]
        boxes = self.src[s - 1]["boxes"] if s >= 1 else []
        return render(d["corr8"], d["raw8"], self.view, self.iron, self.overlay, boxes)
