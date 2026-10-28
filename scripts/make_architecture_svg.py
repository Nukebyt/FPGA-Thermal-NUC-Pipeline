r"""Draws docs/img/architecture.svg, the system diagram for the README (laptop - Ethernet - HPS - bridge - FPGA pipeline).

  .venv\Scripts\python.exe scripts\make_architecture_svg.py

Plain SVG with system fonts, drawn on a white card so it reads in GitHub's light and dark themes."""
import os
from xml.sax.saxutils import escape

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "img", "architecture.svg")
W, H = 1420, 860
FONT = "Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif"
INK, MUTED = "#111827", "#4b5563"
LAP, HPS, FPGA, GREEN = ("#f3f4f6", "#9ca3af"), ("#eff6ff", "#2563eb"), ("#fff7ed", "#ea580c"), ("#16a34a")
out = []


def add(s):
    out.append(s)


def zone(x, y, w, h, fill, stroke, title, sub=None):
    add('<rect x="%d" y="%d" width="%d" height="%d" rx="16" fill="%s" stroke="%s" stroke-width="2"/>' % (x, y, w, h, fill, stroke))
    add('<text x="%d" y="%d" font-size="16" font-weight="700" fill="%s">%s</text>' % (x + 16, y + 27, stroke, escape(title)))
    if sub:
        add('<text x="%d" y="%d" font-size="12" fill="%s">%s</text>' % (x + 16, y + 45, MUTED, escape(sub)))


def box(x, y, w, h, title, lines=(), stroke="#9ca3af", accent=None, fill="#ffffff"):
    add('<rect x="%d" y="%d" width="%d" height="%d" rx="9" fill="%s" stroke="%s" stroke-width="1.6"/>' % (x, y, w, h, fill, stroke))
    if accent:
        add('<rect x="%d" y="%d" width="6" height="%d" rx="3" fill="%s"/>' % (x, y + 6, h - 12, accent))
    n = 1 + len(lines)
    y0 = y + h / 2 - (n - 1) * 8.5 + 4
    add('<text x="%.1f" y="%.1f" font-size="13" font-weight="700" fill="%s" text-anchor="middle">%s</text>' % (x + w / 2 + (3 if accent else 0), y0, INK, escape(title)))
    for i, l in enumerate(lines):
        add('<text x="%.1f" y="%.1f" font-size="11.5" fill="%s" text-anchor="middle">%s</text>' % (x + w / 2 + (3 if accent else 0), y0 + 17 * (i + 1), MUTED, escape(l)))


def arrow(pts, color="#374151", dash=False, both=False, label=None, lpos=None, lsize=11.5, anchor="middle"):
    d = "M " + " L ".join("%d,%d" % p for p in pts)
    add('<path d="%s" fill="none" stroke="%s" stroke-width="2" %s marker-end="url(#a%s)" %s/>' % (
        d, color, 'stroke-dasharray="6 5"' if dash else "", color.strip("#"), 'marker-start="url(#s%s)"' % color.strip("#") if both else ""))
    if label:
        lx, ly = lpos
        for k, t in enumerate(label.split("\n")):
            add('<text x="%d" y="%d" font-size="%s" fill="%s" text-anchor="%s" font-weight="600">%s</text>' % (lx, ly + 14 * k, lsize, color, anchor, escape(t)))


add('<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" font-family="%s">' % (W, H, W, H, FONT))
add("<defs>")
for c in ("374151", "2563eb", "ea580c", "16a34a", "7c3aed"):
    add('<marker id="a%s" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#%s"/></marker>' % (c, c))
    add('<marker id="s%s" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M10,0 L0,5 L10,10 z" fill="#%s"/></marker>' % (c, c))
add("</defs>")
add('<rect width="%d" height="%d" rx="18" fill="#ffffff"/>' % (W, H))

# ------------------------------------------------------------------------------------------------ laptop
zone(20, 30, 262, 790, LAP[0], LAP[1], "Laptop", "Windows, Python 3.13")
box(40, 90, 222, 100, "Thermal clips", ["CDnet 2014: library, corridor,", "diningRoom, park, lakeSide", "320x240, 8 bit (prepare_clips.py)"])
box(40, 225, 222, 100, "run_demo.py", ["copies the clips to the board,", "sets T_MASK per scene, resets", "the NUC, plays a playlist"], accent="#2563eb")
box(40, 370, 222, 100, "viewer.py (OpenCV)", ["raw | NUC-corrected, thermal", "colours, motion boxes,", "status and latency line"], accent="#7c3aed")
box(40, 560, 222, 100, "USB-Blaster (optional)", ["viewer.py over JTAG: 6 MHz", "JTAG clock, slow but needs", "no network"], accent="#9ca3af")
box(40, 700, 222, 90, "Reproducibility", ["Python bit-accurate model,", "Icarus testbenches, mutation", "self-test (scripts/)"])
arrow([(151, 190), (151, 225)])

# ------------------------------------------------------------------------------------------------ board
zone(350, 30, 1050, 790, "#ffffff", "#6b7280", "DE10-Standard board", "Cyclone V SoC 5CSXFC6D6F31C6: HPS (ARM) and FPGA fabric in one chip")
zone(370, 90, 270, 420, HPS[0], HPS[1], "HPS: ARM Cortex-A9, Linux", "Terasic image, started from the SD card")
box(388, 145, 234, 128, "frame_feeder (C, static ARM binary)", ["serve: TCP :5002, register and picture", "access for the laptop", "play: loops a clip from /tmp", "chase writer: never a torn frame"], accent="#2563eb")
box(388, 295, 234, 66, "/tmp RAM disk", ["the clips (the SD card has no room)"])
box(388, 383, 234, 66, "Ethernet + ssh / scp", ["192.168.137.200 (Windows ICS)"])
box(388, 463, 234, 34, "SD card boots the FPGA image", [], stroke="#9ca3af")

# bridge
add('<rect x="655" y="130" width="62" height="340" rx="10" fill="#dbeafe" stroke="#2563eb" stroke-width="1.8"/>')
add('<text transform="translate(692,300) rotate(-90)" font-size="13" font-weight="700" fill="#1e3a8a" text-anchor="middle">lightweight HPS-to-FPGA bridge, 0xFF200000</text>')

# fpga zone
zone(735, 90, 650, 700, FPGA[0], FPGA[1], "FPGA fabric", "25 MHz pixel clock, 8,575 ALMs (20 %), 551 of 553 RAM blocks")
# host bus column
box(752, 158, 124, 440, "Host bus", ["Avalon-MM slave", "(host_if)", "", "0x00000", "CSRs: controls,", "T_MASK, LEARN_N,", "status, latency", "", "0x20000", "capture buffer", "(read)", "", "0x40000", "scene store", "(write)"], stroke="#ea580c")
box(752, 618, 124, 70, "JTAG-to-Avalon", ["master (Qsys)"], stroke="#9ca3af")
arrow([(814, 618), (814, 598)], both=False)

cols = [900, 1062, 1224]
cw, ch = 138, 84
rows = [158, 290, 422, 554]
# row 1
box(cols[0], rows[0], cw, ch, "Scene store", ["320x240x8 bit", "written by the ARM"], stroke="#ea580c", accent="#2563eb")
box(cols[1], rows[0], cw, ch, "Sensor emulator", ["gain, offset, stripes,", "noise, dead/hot px"], stroke="#ea580c")
box(cols[2], rows[0], cw, ch, "Scene-based NUC", ["per-pixel gain + offset", "LMS, no shutter"], stroke="#ea580c", accent=GREEN)
arrow([(cols[0] + cw, rows[0] + 42), (cols[1], rows[0] + 42)], "#ea580c")
arrow([(cols[1] + cw, rows[0] + 42), (cols[2], rows[0] + 42)], "#ea580c")
# row 2 (flows right to left)
box(cols[2], rows[1], cw, ch, "Bad-pixel repair", ["outlier for 8 frames", "-> neighbour mean"], stroke="#ea580c", accent=GREEN)
box(cols[1], rows[1], cw, ch, "Motion detector", ["running background", "threshold T_MASK"], stroke="#ea580c", accent=GREEN)
box(cols[0], rows[1], cw, ch, "Open + close", ["3x3 morphology", "removes speckle"], stroke="#ea580c", accent=GREEN)
arrow([(cols[2] + cw / 2, rows[0] + ch), (cols[2] + cw / 2, rows[1])], "#ea580c")
arrow([(cols[2], rows[1] + 42), (cols[1] + cw, rows[1] + 42)], "#ea580c")
arrow([(cols[1], rows[1] + 42), (cols[0] + cw, rows[1] + 42)], "#ea580c")
# row 3
box(cols[0], rows[2], cw, ch, "Box extraction", ["connected components,", "up to 16 boxes"], stroke="#ea580c", accent=GREEN)
box(cols[1], rows[2], cw, ch, "Box list + flag", ["published a fixed", "8,724 cycles later"], stroke="#16a34a", fill="#f0fdf4")
box(cols[2], rows[2], cw, ch, "Display path", ["auto contrast, palette,", "box overlay"], stroke="#ea580c")
arrow([(cols[0] + cw / 2, rows[1] + ch), (cols[0] + cw / 2, rows[2])], "#ea580c")
arrow([(cols[0] + cw, rows[2] + 42), (cols[1], rows[2] + 42)], "#ea580c")
arrow([(cols[1] + cw, rows[2] + 42), (cols[2], rows[2] + 42)], "#ea580c")
arrow([(cols[2] + cw / 2, rows[1] + ch), (cols[2] + cw / 2, rows[2])], "#ea580c")
# row 4
box(cols[0], rows[3], cw, ch, "Frame capture", ["raw or corrected", "one whole frame"], stroke="#ea580c")
box(cols[1], rows[3], cw, ch, "Latency counters", ["end of frame -> boxes:", "min = max = 349 us"], stroke="#16a34a", fill="#f0fdf4")
box(cols[2], rows[3], cw, ch, "VGA 640x480", ["60 Hz, optional", "monitor output"], stroke="#ea580c")
arrow([(cols[2] + cw / 2, rows[2] + ch), (cols[2] + cw / 2, rows[3])], "#ea580c")
arrow([(cols[1] + cw / 2, rows[2] + ch), (cols[1] + cw / 2, rows[3])], "#16a34a")
# host bus links
arrow([(876, rows[0] + 42), (cols[0], rows[0] + 42)], "#374151", dash=True)
arrow([(cols[0], rows[3] + 20), (876, rows[3] + 20)], "#374151", dash=True)

# ------------------------------------------------------------------------------------------------ links between the blocks
# laptop <-> HPS
arrow([(262, 275), (370, 275)], "#2563eb", both=True, label="Ethernet\nssh / scp", lpos=(316, 238))
arrow([(262, 420), (370, 420)], "#7c3aed", both=True, label="TCP :5002\nregisters,\npictures", lpos=(316, 369))
# HPS <-> bridge <-> host bus
arrow([(622, 215), (655, 215)], "#2563eb", both=True)
arrow([(717, 215), (752, 215)], "#2563eb", both=True)
# JTAG
arrow([(262, 610), (300, 610), (300, 850 - 38), (814, 850 - 38), (814, 688)], "#6b7280", dash=True, both=True)
add('<text x="364" y="804" font-size="11.5" font-weight="600" fill="#6b7280">USB-Blaster JTAG (6 MHz)</text>')

# ------------------------------------------------------------------------------------------------ legend
lx, ly = 750, 835
add('<rect x="%d" y="%d" width="12" height="12" rx="3" fill="none" stroke="#ea580c" stroke-width="2"/><text x="%d" y="%d" font-size="11.5" fill="%s">FPGA stage</text>' % (lx, ly - 10, lx + 18, ly, MUTED))
add('<rect x="%d" y="%d" width="6" height="14" rx="3" fill="#16a34a"/><text x="%d" y="%d" font-size="11.5" fill="%s">stage with a fixed latency (feed-forward)</text>' % (lx + 110, ly - 11, lx + 124, ly, MUTED))
add('<path d="M %d,%d L %d,%d" stroke="#374151" stroke-width="2" /><text x="%d" y="%d" font-size="11.5" fill="%s">pixel data</text>' % (lx + 380, ly - 4, lx + 410, ly - 4, lx + 418, ly, MUTED))
add('<path d="M %d,%d L %d,%d" stroke="#374151" stroke-width="2" stroke-dasharray="6 5"/><text x="%d" y="%d" font-size="11.5" fill="%s">control / read-back</text>' % (lx + 490, ly - 4, lx + 520, ly - 4, lx + 528, ly, MUTED))
add("</svg>")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
open(OUT, "w", encoding="utf-8").write("\n".join(out))
print("wrote", os.path.relpath(OUT))
