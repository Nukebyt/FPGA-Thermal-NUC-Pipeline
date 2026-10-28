"""Sensor emulator twin: statistics match the noise-model presets, and the RTL constants match this model."""
import re
from pathlib import Path

import numpy as np

from model import sensor_emu as se, noise_model as nm

ROOT = Path(__file__).resolve().parents[2]


def test_rtl_default_rect_table_matches_python():
    txt = (ROOT / "rtl" / "sensor_emu.v").read_text()
    m = re.search(r"parameter \[191:0\] RECTP = 192'h([0-9a-fA-F_]+)", txt)
    assert m, "RECTP default not found in rtl/sensor_emu.v"
    assert int(m.group(1).replace("_", ""), 16) == se.pack_rects(se.DEFAULT_RECTS)


def test_rtl_preset_constants_match_python():
    txt = (ROOT / "rtl" / "sensor_emu.v").read_text()
    for idx, name in enumerate(("mild", "typical", "severe")):
        p = se.EMU_PRESETS[name]
        pat = (r"GS = 10'd%d;\s+OS = 10'd%d;\s+CS = 10'd%d;\s+TS = 10'd%d;\s+DEADT = 16'd%d;\s+HOTT = 16'd%d;"
               % (p.GS, p.OS, p.CS, p.TS, p.DEAD, p.HOT))
        assert re.search(pat, txt), f"preset {name} constants differ between rtl/sensor_emu.v and model/sensor_emu.py"


def test_noise_statistics_match_presets():
    rom = se.rom_from_scene()
    for name in ("mild", "typical", "severe"):
        emu = se.SensorEmu(rom, name)
        ref = nm.PRESETS[name]
        assert abs((emu.g / 4096.0).std() - ref.sigma_g) < 0.12 * ref.sigma_g + 0.002
        assert abs(emu.o.std() - ref.sigma_o) < 0.12 * ref.sigma_o + 1.0
        assert abs(emu.col.std() - ref.sigma_col) < 0.2 * ref.sigma_col + 1.0
        assert emu.dead.mean() < 4 * ref.dead_rate + 1e-4


def test_emulator_is_deterministic_and_frame_dependent():
    rom = se.rom_from_scene()
    a = se.SensorEmu(rom, "typical").run(3)[0]
    b = se.SensorEmu(rom, "typical").run(3)[0]
    assert np.array_equal(a, b)
    assert not np.array_equal(a[0], a[1])                      # temporal noise / motion
    fixed = (se.SensorEmu(rom, "typical").g)                    # the fixed pattern itself does not change
    assert np.array_equal(fixed, se.SensorEmu(rom, "typical").g)


def test_ground_truth_motion_only_for_moving_rects():
    rom = se.rom_from_scene()
    rects = [se.Rect(10, 10, 20, 20, 1000, 0, 0), se.Rect(100, 100, 20, 20, 1000, 1, 1)]
    emu = se.SensorEmu(rom, "mild", rects=rects + [se.Rect(200, 50, 5, 5, 0, 0, 0)])
    m = emu.motion_mask()
    assert not m[10:30, 10:30].any() and m[100:120, 100:120].all()
