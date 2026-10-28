"""Regression runner: Icarus testbenches + Python unit tests. Plain ASCII on purpose (checklist 3.9).

Verdict rules
  * A testbench passes only if its output contains a line "RESULT: PASS" and no "RESULT: FAIL", no "MISMATCH"
    and no "FAIL" line. Compile error, timeout or NO verdict line == FAIL. The simulator exit code is never used.
  * --selftest re-runs the testbenches against deliberately broken copies of the RTL and requires FAIL on each.
    Run it every time this script, a testbench or the RTL under test changes.

Usage:  python scripts/run_regression.py [--selftest] [--skip-python] [--only NAME]
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IVERILOG = os.environ.get("IVERILOG", "iverilog")
VVP = os.environ.get("VVP", "vvp")

# name -> (rtl sources, testbench, [-P overrides "tb.PARAM=value"], optional vector-generation command)
TESTS = {}


def add(name, srcs, tb, params=(), pre=None):
    TESTS[name] = (list(srcs), tb, list(params), pre)


add("row_retimer", ["rtl/ram_sdp.v", "rtl/row_retimer.v"], "tb/row_retimer_tb.v")
add("win3x3_gap2", ["rtl/ram_sdp.v", "rtl/grid_ctr.v", "rtl/win3x3.v"], "tb/win3x3_tb.v", ["win3x3_tb.GAPMAX=2"])
add("win3x3_gap3", ["rtl/ram_sdp.v", "rtl/grid_ctr.v", "rtl/win3x3.v"], "tb/win3x3_tb.v", ["win3x3_tb.GAPMAX=3"])
add("win3x3_gap9", ["rtl/ram_sdp.v", "rtl/grid_ctr.v", "rtl/win3x3.v"], "tb/win3x3_tb.v", ["win3x3_tb.GAPMAX=9", "win3x3_tb.W=17", "win3x3_tb.H=11"])

NUC_SRC = ["rtl/ram_sdp.v", "rtl/grid_ctr.v", "rtl/win3x3.v", "rtl/nuc_core.v"]


def nuc_case(name, gen_args, params=()):
    d = "work/vec_" + name
    add(name, NUC_SRC, "tb/nuc_core_tb.v", ['nuc_core_tb.VEC="%s"' % d] + list(params),
        pre=[sys.executable, "scripts/gen_nuc_vectors.py", "--out", d] + gen_args.split())


nuc_case("nuc_scene", "--mode scene", ["nuc_core_tb.GAPMAX=4"])
nuc_case("nuc_scene_gap2", "--mode scene --seed 5", ["nuc_core_tb.GAPMAX=2"])
nuc_case("nuc_random", "--mode random --seed 3 --T 10 --klim 400", ["nuc_core_tb.T=10", "nuc_core_tb.GAPMAX=3", "nuc_core_tb.KLIM=400"])
nuc_case("nuc_odd_size", "--mode scene --W 41 --H 29 --T 14 --seed 8", ["nuc_core_tb.W=41", "nuc_core_tb.H=29", "nuc_core_tb.T=14", "nuc_core_tb.GAPMAX=7"])
nuc_case("nuc_bypass", "--mode scene --nuc_en 0 --seed 4")
nuc_case("nuc_nolearn", "--mode scene --learn_en 0 --seed 6")
nuc_case("nuc_nobp", "--mode scene --bp_en 0 --seed 7")
nuc_case("nuc_toggle", "--mode scene --toggle 1 --T 24 --seed 9", ["nuc_core_tb.T=24", "nuc_core_tb.GAPMAX=3"])
nuc_case("nuc_toggle_rand", "--mode random --toggle 1 --T 16 --seed 10", ["nuc_core_tb.T=16", "nuc_core_tb.GAPMAX=5"])
nuc_case("nuc_sat", "--mode sat --W 8 --H 6 --T 400 --gain_all 1 --bp_en 0 --klim 40000 --seed 11", ["nuc_core_tb.W=8", "nuc_core_tb.H=6", "nuc_core_tb.T=400", "nuc_core_tb.GAPMAX=2", "nuc_core_tb.KLIM=40000"])
nuc_case("nuc_flat", "--mode flat --W 24 --H 16 --T 12 --seed 13", ["nuc_core_tb.W=24", "nuc_core_tb.H=16", "nuc_core_tb.T=12", "nuc_core_tb.GAPMAX=3"])
nuc_case("nuc_window", "--mode scene --toggle 1 --T 24 --learn_n 6 --seed 14",
         ["nuc_core_tb.T=24", "nuc_core_tb.GAPMAX=3", "nuc_core_tb.LEARN_N=6"])
nuc_case("nuc_window_reset", "--mode scene --T 14 --learn_n 3 --coef_reset_at 6 --seed 15",
         ["nuc_core_tb.T=14", "nuc_core_tb.GAPMAX=3", "nuc_core_tb.LEARN_N=3", "nuc_core_tb.CRST=6"])
nuc_case("nuc_cluster", "--mode cluster --W 40 --H 30 --T 16 --seed 12", ["nuc_core_tb.W=40", "nuc_core_tb.H=30", "nuc_core_tb.T=16", "nuc_core_tb.GAPMAX=3"])

CCL_SRC = ["rtl/ram_sdp.v", "rtl/ccl_slot.v", "rtl/ccl_boxes.v"]


def ccl_case(name, gen_args, params=()):
    d = "work/vec_" + name
    add(name, CCL_SRC, "tb/ccl_tb.v", ['ccl_tb.VEC="%s"' % d] + list(params),
        pre=[sys.executable, "scripts/gen_ccl_vectors.py", "--out", d] + gen_args.split())


ccl_case("ccl_mixed", "--mode mixed --T 24 --seed 1", ["ccl_tb.GAPMAX=4"])
ccl_case("ccl_mixed_gap2", "--mode mixed --T 24 --seed 2", ["ccl_tb.GAPMAX=2"])
ccl_case("ccl_noise", "--mode noise --T 8 --seed 3", ["ccl_tb.T=8", "ccl_tb.GAPMAX=3"])
ccl_case("ccl_blobs_minarea", "--mode blobs --T 30 --seed 4 --min_area 6", ["ccl_tb.T=30", "ccl_tb.MINAREA=6", "ccl_tb.GAPMAX=5"])
ccl_case("ccl_dense", "--mode dense --T 12 --seed 5", ["ccl_tb.T=12", "ccl_tb.GAPMAX=3"])
ccl_case("ccl_directed", "--mode directed --T 32 --seed 7 --W 48 --H 30", ["ccl_tb.W=48", "ccl_tb.H=30", "ccl_tb.T=32", "ccl_tb.GAPMAX=3"])
ccl_case("ccl_checker_sat", "--mode dir:checker --T 3 --W 77 --H 41 --seed 8", ["ccl_tb.W=77", "ccl_tb.H=41", "ccl_tb.T=3", "ccl_tb.GAPMAX=2"])
ccl_case("ccl_big", "--mode mixed --W 77 --H 51 --T 16 --seed 6", ["ccl_tb.W=77", "ccl_tb.H=51", "ccl_tb.T=16", "ccl_tb.GAPMAX=3"])

CHAIN_SRC = ["rtl/ram_sdp.v", "rtl/grid_ctr.v", "rtl/win3x3.v", "rtl/nuc_core.v", "rtl/bg_detect.v", "rtl/morph3.v",
             "rtl/ccl_slot.v", "rtl/ccl_boxes.v", "rtl/row_retimer.v", "rtl/thermal_core.v"]


def chain_case(name, gen_args, params=()):
    d = "work/vec_" + name
    add(name, CHAIN_SRC, "tb/thermal_core_tb.v", ['thermal_core_tb.VEC="%s"' % d] + list(params),
        pre=[sys.executable, "scripts/gen_chain_vectors.py", "--out", d] + gen_args.split())


chain_case("chain_gate_toggle", "--klim 400 --act_thr 0 --T 24 --seed 3",
           ["thermal_core_tb.KLIM=400", "thermal_core_tb.ACT_THR=0", "thermal_core_tb.T=24", "thermal_core_tb.GAPMAX=3"])
chain_case("chain_gate_default", "--klim 400 --act_thr 64 --T 20 --seed 4",
           ["thermal_core_tb.KLIM=400", "thermal_core_tb.ACT_THR=64", "thermal_core_tb.T=20", "thermal_core_tb.GAPMAX=2"])
chain_case("chain_pan_severe", "--klim 400 --act_thr 0 --T 22 --seed 5 --preset severe --pan 0.7 --blobs 4",
           ["thermal_core_tb.KLIM=400", "thermal_core_tb.ACT_THR=0", "thermal_core_tb.T=22", "thermal_core_tb.GAPMAX=4"])
chain_case("chain_odd_size", "--W 37 --H 29 --klim 600 --act_thr 0 --T 20 --seed 6 --blobs 2 --t_mask 300",
           ["thermal_core_tb.W=37", "thermal_core_tb.H=29", "thermal_core_tb.KLIM=600", "thermal_core_tb.ACT_THR=0",
            "thermal_core_tb.TMASK=300", "thermal_core_tb.T=20", "thermal_core_tb.GAPMAX=6"])

chain_case("chain_thr_edge", "--W 37 --H 29 --klim 600 --act_thr 0 --T 20 --seed 6 --blobs 2 --t_mask_edge_frame 12",     # generator picks T_MASK = 20
           ["thermal_core_tb.W=37", "thermal_core_tb.H=29", "thermal_core_tb.KLIM=600", "thermal_core_tb.ACT_THR=0",
            "thermal_core_tb.TMASK=20", "thermal_core_tb.T=20", "thermal_core_tb.GAPMAX=6"])
chain_case("chain_gate_closed", "--klim 400 --act_thr 3 --T 20 --seed 8 --blobs 3",
           ["thermal_core_tb.KLIM=400", "thermal_core_tb.ACT_THR=3", "thermal_core_tb.T=20", "thermal_core_tb.GAPMAX=3"])
chain_case("chain_gate_equal", "--klim 400 --act_thr 0 --T 20 --seed 4 --act_thr_from_frame 10",      # generator sets ACT_THR=5 (the activity at frame 10)
           ["thermal_core_tb.KLIM=400", "thermal_core_tb.ACT_THR=5", "thermal_core_tb.T=20", "thermal_core_tb.GAPMAX=3"])
chain_case("chain_window", "--klim 400 --act_thr 0 --T 16 --seed 10 --learn_n 5",
           ["thermal_core_tb.KLIM=400", "thermal_core_tb.ACT_THR=0", "thermal_core_tb.T=16", "thermal_core_tb.GAPMAX=3",
            "thermal_core_tb.LEARN_N=5"])
chain_case("chain_long_warm", "--W 24 --H 18 --T 80 --klim 800 --act_thr 0 --seed 9 --blobs 2 --t_mask 350 --det_warm 70",
           ["thermal_core_tb.W=24", "thermal_core_tb.H=18", "thermal_core_tb.KLIM=800", "thermal_core_tb.ACT_THR=0",
            "thermal_core_tb.TMASK=350", "thermal_core_tb.DETWARM=70", "thermal_core_tb.T=80", "thermal_core_tb.GAPMAX=3"])

EMU_SRC = ["rtl/ram_sdp.v", "rtl/grid_ctr.v", "rtl/hash32.v", "rtl/rom_sp.v", "rtl/scene_buf.v", "rtl/sensor_emu.v"]


def emu_case(name, gen_args, params=()):
    d = "work/vec_" + name
    add(name, EMU_SRC, "tb/sensor_emu_tb.v",
        ["-I" + d, 'sensor_emu_tb.VEC="%s"' % d, 'sensor_emu_tb.ROM="%s/rom.hex"' % d] + list(params),
        pre=[sys.executable, "scripts/gen_emu_vectors.py", "--out", d] + gen_args.split())


emu_case("emu_typical", "--preset typical --T 8", ["sensor_emu_tb.PRESET=1", "sensor_emu_tb.GAPMAX=3"])
emu_case("emu_mild", "--preset mild --T 6 --seed 22", ["sensor_emu_tb.PRESET=0", "sensor_emu_tb.T=6", "sensor_emu_tb.GAPMAX=2"])
emu_case("emu_severe", "--preset severe --T 6 --seed 23", ["sensor_emu_tb.PRESET=2", "sensor_emu_tb.T=6", "sensor_emu_tb.GAPMAX=5"])
emu_case("emu_clean", "--preset typical --noise 0 --T 5 --seed 24", ["sensor_emu_tb.PRESET=1", "sensor_emu_tb.NOISE=0", "sensor_emu_tb.T=5"])
emu_case("emu_odd_size", "--W 37 --H 29 --preset severe --T 10 --seed 25",
         ["sensor_emu_tb.W=37", "sensor_emu_tb.H=29", "sensor_emu_tb.PRESET=2", "sensor_emu_tb.T=10", "sensor_emu_tb.GAPMAX=4"])
emu_case("emu_feed", "--preset typical --T 5 --seed 31 --feed 1",
         ["sensor_emu_tb.FEED=1", "sensor_emu_tb.PRESET=1", "sensor_emu_tb.T=5", "sensor_emu_tb.GAPMAX=3"])
emu_case("emu_feed_noobj", "--preset severe --T 4 --seed 32 --feed 1 --obj 0",
         ["sensor_emu_tb.FEED=1", "sensor_emu_tb.OBJ=0", "sensor_emu_tb.PRESET=2", "sensor_emu_tb.T=4", "sensor_emu_tb.GAPMAX=2"])
emu_case("emu_feed_odd", "--W 37 --H 29 --preset mild --T 4 --seed 33 --feed 1 --noise 0",
         ["sensor_emu_tb.FEED=1", "sensor_emu_tb.W=37", "sensor_emu_tb.H=29", "sensor_emu_tb.NOISE=0", "sensor_emu_tb.PRESET=0",
          "sensor_emu_tb.T=4", "sensor_emu_tb.GAPMAX=4"])
emu_case("emu_fullsize", "--W 320 --H 240 --preset typical --T 3 --seed 21",
         ["sensor_emu_tb.W=320", "sensor_emu_tb.H=240", "sensor_emu_tb.PRESET=1", "sensor_emu_tb.T=3", "sensor_emu_tb.GAPMAX=2"])

add("csr", ["rtl/csr_regs.v"], "tb/csr_tb.v")
add("host", ["rtl/ram_sdp.v", "rtl/csr_regs.v", "rtl/frame_cap.v", "rtl/host_if.v", "rtl/scene_buf.v"], "tb/host_tb.v")

# Slow end-to-end tests (full-size system, ~12 minutes each): run with --slow.  (name, tb parameters, check_vga args)
SYS_SRC = ["rtl/ram_sdp.v", "rtl/rom_sp.v", "rtl/hash32.v", "rtl/grid_ctr.v", "rtl/win3x3.v", "rtl/nuc_core.v", "rtl/bg_detect.v",
           "rtl/morph3.v", "rtl/ccl_slot.v", "rtl/ccl_boxes.v", "rtl/row_retimer.v", "rtl/thermal_core.v", "rtl/sensor_emu.v",
           "rtl/tone_win.v", "rtl/disp_path.v", "rtl/csr_regs.v", "rtl/vga_timing.v", "rtl/tick_gen.v", "rtl/frame_cap.v", "rtl/host_if.v",
           "rtl/scene_buf.v", "rtl/thermal_sys.v"]
# Each also captures one frame through the host bus (frame_cap + host_if) and checks it with scripts/check_capture.py.
SLOW = {
    "sys_split_gray": (["thermal_sys_tb.NFRAMES=5", "thermal_sys_tb.CTRL=32'h000002BF", "thermal_sys_tb.CAPTURE=2",
                        "thermal_sys_tb.CAPSRC=0"], "--frames 5 --view 2 --iron 0", "--src 0"),
    "sys_corrected_iron": (["thermal_sys_tb.NFRAMES=5", "thermal_sys_tb.CTRL=32'h000004BF", "thermal_sys_tb.CAPTURE=2",
                            "thermal_sys_tb.CAPSRC=1"], "--frames 5 --view 0 --iron 1", "--src 1"),
}

# (file, old text, new text, testbench name that must catch it)
MUTATIONS = [
    ("rtl/win3x3.v", "wire rig_rep = (c2 == W);", "wire rig_rep = (c2 == W - 1);", "win3x3_gap3"),
    ("rtl/win3x3.v", "wire bot_rep = (r2 == H);", "wire bot_rep = (r2 == H - 1);", "win3x3_gap3"),
    ("rtl/win3x3.v", "wire top_rep = (r2 == 9'd1);", "wire top_rep = (r2 == 9'd0);", "win3x3_gap3"),
    ("rtl/win3x3.v", "wire lef_rep = (c2 == 9'd1);", "wire lef_rep = (c2 == 9'd2);", "win3x3_gap2"),
    ("rtl/win3x3.v", "wdata(a1[DW+SW-1:SW])", "wdata(din1)", "win3x3_gap3"),
    ("rtl/win3x3.v", "sout   <= s1;", "sout   <= s0;", "win3x3_gap3"),
        ("rtl/nuc_core.v", "(o_sum > o_hi) ? 14'sd4094 : (o_sum < o_lo) ? -14'sd4094", "(o_sum > o_hi) ? 14'sd4093 : (o_sum < o_lo) ? -14'sd4094", "nuc_sat"),
    ("rtl/nuc_core.v", "(o_sum > o_hi) ? 14'sd4094 : (o_sum < o_lo) ? -14'sd4094", "(o_sum > o_hi) ? 14'sd4094 : (o_sum < o_lo) ? -14'sd4093", "nuc_sat"),
    ("rtl/nuc_core.v", "localparam SG      = 28 + YF + OF - GF;", "localparam SG      = 27 + YF + OF - GF;", "nuc_scene"),
    ("rtl/nuc_core.v", "32'sd262144;", "32'sd131072;", "nuc_scene"),
    ("rtl/nuc_core.v", "3'd3: recip = 17'd21845;", "3'd3: recip = 17'd21846;", "nuc_scene"),
    ("rtl/nuc_core.v", "parameter BP_ON = 8,", "parameter BP_ON = 7,", "nuc_scene"),
    ("rtl/nuc_core.v", "(ec4 + 13'sd16) >>> 5", "(ec4 + 13'sd15) >>> 5", "nuc_scene"),
    ("rtl/nuc_core.v", "localparam [12:0] GMIN = 13'd2048;", "localparam [12:0] GMIN = 13'd2047;", "nuc_sat"),
    ("rtl/nuc_core.v", "localparam [12:0] GMAX = 13'd8191;", "localparam [12:0] GMAX = 13'd8190;", "nuc_sat"),
    ("rtl/nuc_core.v", "(x2 == 14'd0) || (x2 == 14'h3FFF)", "(x2 == 14'd0)", "nuc_random"),
    ("rtl/nuc_core.v", "(upd & gain_a) ? g_new : g5", "upd ? g_new : g5", "nuc_scene"),
    ("rtl/nuc_core.v", "((bpc5 == 4'd0) ? 4'd0 : bpc5 - 4'd1)", "bpc5", "nuc_scene"),
    ("rtl/nuc_core.v", "wire        upd   = ~badc5 & learn_a & nuc_a;", "wire        upd   = ~badc5 & nuc_a;", "nuc_nolearn"),
    ("rtl/nuc_core.v", "(lcnt < learn_n)", "(lcnt <= learn_n)", "nuc_window"),
    ("rtl/nuc_core.v", "wire       learn_now = learn_en & nuc_en &", "wire       learn_now = learn_en &", "nuc_window"),
    ("rtl/nuc_core.v", "tick_i & first_i & learn_now & (lcnt", "tick_i & first_i & (lcnt", "nuc_window"),
    ("rtl/nuc_core.v", "else if (coef_reset)                                    lcnt <= 16'd0;", "else if (1'b0)                                          lcnt <= 16'd0;", "nuc_window_reset"),
    ("rtl/nuc_core.v", "((learn_n == 16'd0) |", "((learn_n == 16'd1) |", "nuc_scene"),
    ("rtl/nuc_core.v", "wire [15:0] d3   = (cnt2 == 3'd0) ? yc2 : dsum[31:16];", "wire [15:0] d3   = (cnt2 == 3'd0) ? 16'd0 : dsum[31:16];", "nuc_cluster"),
    ("rtl/nuc_core.v", "wire [15:0] y3s = nuc_a ? y3 : {x3, 2'b00};", "wire [15:0] y3s = y3;", "nuc_toggle"),
    ("rtl/nuc_core.v", "wire [16:0] yo_r = {1'b0, yo_q} + 17'd2;", "wire [16:0] yo_r = {1'b0, yo_q} + 17'd1;", "nuc_scene"),
    ("rtl/nuc_core.v", "(sh20 > {emax_a, 2'b00}) ? {emax_a, 2'b00}", "(sh20 > {emax_a, 2'b00}) ? {emin_a, 2'b00}", "nuc_random"),
    ("rtl/nuc_core.v", "(sh20 < {emin_a, 2'b00}) ? {emin_a, 2'b00} :", "(sh20 < {emin_a, 2'b00}) ? 12'd0 :", "nuc_flat"),
    ("rtl/nuc_core.v", "(ycs < lo_t))) || rail_b;", "(ycs < lo_t)));", "nuc_cluster"),
    ("rtl/nuc_core.v", "wire        anyv_w = ~(eNW[0] & eN[0] & eNE[0] & eW[0] & eE[0] & eSW[0] & eS[0] & eSE[0]);", "wire        anyv_w = 1'b1;", "nuc_cluster"),
]
MUTATIONS += [
    ("rtl/ccl_slot.v", "used <= 1'b0; blk <= 2'd2;", "used <= 1'b0; blk <= 2'd1;", "ccl_directed"),
    ("rtl/ccl_slot.v", "used <= 1'b0; blk <= 2'd2;", "used <= 1'b0; blk <= 2'd0;", "ccl_directed"),
    ("rtl/ccl_slot.v", "if (px > xmax) xmax <= px;", "if (px > xmax + 9'd1) xmax <= px;", "ccl_mixed"),
    ("rtl/ccl_slot.v", "area <= area + hi_area + 17'd1;", "area <= area + hi_area;", "ccl_mixed"),
    ("rtl/ccl_slot.v", "ymin <= (hi_ymin < ymin) ? hi_ymin : ymin;", "ymin <= ymin;", "ccl_mixed"),
    ("rtl/ccl_slot.v", "if (alias_set && link == alias_from) link <= alias_to;", "if (alias_set && link == alias_from && ID != alias_from) link <= alias_to;", "ccl_noise"),
    ("rtl/ccl_slot.v", "if (blk != 2'd0) blk <= blk - 2'd1;", "blk <= blk;", "ccl_noise"),
    ("rtl/ccl_slot.v", "                touched <= 1'b0;\n                if (blk", "                if (blk", "ccl_mixed"),
    ("rtl/ccl_boxes.v", "wire       n_valid = mask_q && (cr_q != 9'd0) && nraw[4];", "wire       n_valid = mask_q && nraw[4];", "ccl_directed"),
    ("rtl/ccl_boxes.v", "wire       w_valid = mask_q && (cc_q != 9'd0) && left_v;", "wire       w_valid = mask_q && left_v;", "ccl_directed"),
    ("rtl/ccl_boxes.v", "wire        scan_big = (area_v[ks[3:0]*17 +: 17] >= {1'b0, min_area});", "wire        scan_big = (area_v[ks[3:0]*17 +: 17] > {1'b0, min_area});", "ccl_blobs_minarea"),
    ("rtl/ccl_boxes.v", "if (ovf_alloc) ovf <= 1'b1;", "if (1'b0) ovf <= 1'b1;", "ccl_directed"),
    ("rtl/ccl_boxes.v", "end else ovf <= 1'b1;", "end else ovf <= ovf;", "ccl_dense"),
    ("rtl/ccl_boxes.v", "(used_v[ks[3:0]] & ~touched_v[ks[3:0]])", "(used_v[ks[3:0]])", "ccl_mixed"),
    ("rtl/ccl_boxes.v", "st <= eof_f ? S_FLUSH : S_IDLE;", "st <= S_IDLE;", "ccl_mixed"),
    ("rtl/ccl_boxes.v", "wire [3:0] lo_idx = (n_idx < w_idx) ? n_idx : w_idx;", "wire [3:0] lo_idx = (n_idx < w_idx) ? w_idx : n_idx;", "ccl_noise"),
    ("rtl/ccl_boxes.v", "if (!used_v[ki] && blk_v[ki*2 +: 2] == 2'd0) begin", "if (!used_v[ki]) begin", "ccl_directed"),
    ("rtl/ccl_boxes.v", "n_obj <= (n_obj == 8'd255) ? 8'd255 : n_obj + 8'd1;", "n_obj <= n_obj + 8'd1;", "ccl_checker_sat"),
    ("rtl/ccl_boxes.v", "res_cnt <= 5'd0; n_obj <= 8'd0; ovf <= 1'b0; eof_f <= 1'b0;", "res_cnt <= 5'd0; n_obj <= 8'd0; eof_f <= 1'b0;", "ccl_mixed"),
    ("rtl/ccl_boxes.v", "if (res_cnt[3:0] == rk) res_flat[rk*53 +: 53] <= scan_box;", "if (res_cnt[3:0] == rk) res_flat[((rk + 1) % 16)*53 +: 53] <= scan_box;", "ccl_mixed"),
]
MUTATIONS += [
    ("rtl/bg_detect.v", "else if (nn < 8'd4)   sh_of = 3'd2;", "else if (nn < 8'd5)   sh_of = 3'd2;", "chain_gate_toggle"),
    ("rtl/bg_detect.v", "else if (nn < 8'd64)  sh_of = 3'd6;", "else if (nn < 8'd60)  sh_of = 3'd6;", "chain_long_warm"),
    ("rtl/bg_detect.v", "wire signed [17:0] rnd = (sh_a == 3'd0) ? 18'sd0 : (18'sd1 <<< (sh_a - 3'd1));", "wire signed [17:0] rnd = 18'sd0;", "chain_gate_toggle"),
    ("rtl/bg_detect.v", "wire        mask_w = ~n0_a && (absd > {2'b00, t_a, 2'b00});", "wire        mask_w = ~n0_a && (absd >= {2'b00, t_a, 2'b00});", "chain_thr_edge"),
    ("rtl/bg_detect.v", "dv_a <= (n >= det_warm);", "dv_a <= (n > det_warm);", "chain_gate_toggle"),
    ("rtl/bg_detect.v", "wr_data <= n0_a ? yb2 : bnew16;", "wr_data <= bnew16;", "chain_gate_toggle"),
    ("rtl/bg_detect.v", "(acc[31:16] > thr_a)", "(acc[31:16] >= thr_a)", "chain_gate_equal"),
    ("rtl/bg_detect.v", "(n == 8'd255) ? 8'd255 : n + 8'd1) > ACT_WARM", "(n == 8'd255) ? 8'd255 : n + 8'd1) > ACT_WARM + 1", "chain_gate_closed"),
    ("rtl/bg_detect.v", "acc <= ((tk2 && fs2) ? 32'd0 : acc) + {16'd0, absd[17:2]};", "acc <= ((tk2 && fs2) ? 32'd0 : acc) + {16'd0, absd[17:2]} + 32'd1;", "chain_gate_toggle"),
    ("rtl/thermal_core.v", "morph3 #(.OP(0), .W(W), .H(H), .ORG(1 * (W + 2))) u_m1", "morph3 #(.OP(1), .W(W), .H(H), .ORG(1 * (W + 2))) u_m1", "chain_gate_toggle"),
    ("rtl/thermal_core.v", "morph3 #(.OP(1), .W(W), .H(H), .ORG(2 * (W + 2))) u_m2", "morph3 #(.OP(1), .W(W), .H(H), .ORG(2 * (W + 2) + 1)) u_m2", "chain_gate_toggle"),
    ("rtl/thermal_core.v", "morph3 #(.OP(0), .W(W), .H(H), .ORG(4 * (W + 2))) u_m4", "morph3 #(.OP(0), .W(W), .H(H), .ORG(4 * (W + 2) - 1)) u_m4", "chain_gate_toggle"),
    ("rtl/thermal_core.v", ".gain_en_in(gain_next)", ".gain_en_in(1'b1)", "chain_gate_closed"),
    ("rtl/thermal_core.v", ".gain_en_in(gain_next)", ".gain_en_in(1'b0)", "chain_gate_toggle"),
    ("rtl/morph3.v", "wire red = (OP == 0) ? (&w_win) : (|w_win);", "wire red = (OP == 0) ? (&w_win[8:1]) : (|w_win);", "chain_gate_toggle"),
    ("rtl/morph3.v", "wire red = (OP == 0) ? (&w_win) : (|w_win);", "wire red = (OP == 0) ? (&w_win) : (|w_win[7:0]);", "chain_gate_toggle"),
    ("rtl/row_retimer.v", "if (rd_c == W - 1) active <= 1'b0;", "if (rd_c == W - 2) active <= 1'b0;", "chain_gate_toggle"),
    ("rtl/row_retimer.v", "ovalid <= v2; obit <= rdbit; ocr <= r2; occ <= c2;", "ovalid <= v1; obit <= rdbit; ocr <= r1; occ <= c1;", "chain_gate_toggle"),
    ("rtl/row_retimer.v", "if (row_done && active) err <= 1'b1;", "if (1'b0) err <= 1'b1;", "row_retimer"),
]
MUTATIONS += [
    ("rtl/hash32.v", "s2 <= s1 * 32'h7FEB352D;", "s2 <= s1 * 32'h7FEB352C;", "emu_typical"),
    ("rtl/hash32.v", "s3 <= s2 ^ (s2 >> 15);", "s3 <= s2 ^ (s2 >> 14);", "emu_typical"),
    ("rtl/sensor_emu.v", "zof = $signed(sum) - 11'sd510;", "zof = $signed(sum) - 11'sd509;", "emu_typical"),
    ("rtl/sensor_emu.v", "2'd1: begin GS = 10'd355;", "2'd1: begin GS = 10'd356;", "emu_typical"),
    ("rtl/sensor_emu.v", "2'd0: begin GS = 10'd142; OS = 10'd52;", "2'd0: begin GS = 10'd142; OS = 10'd53;", "emu_mild"),
    ("rtl/sensor_emu.v", "DEADT = 16'd131; HOTT = 16'd131;", "DEADT = 16'd130; HOTT = 16'd131;", "emu_severe"),     # pixel 1161 has hash low16 == 130: sits exactly on the boundary
    ("rtl/sensor_emu.v", "wire [31:0] hin_d = idx7 + fterm + SEED_D;", "wire [31:0] hin_d = idx7 + SEED_D;", "emu_typical"),
    ("rtl/sensor_emu.v", "wire [31:0] idx7  = (idx32 << 3) - idx32;", "wire [31:0] idx7  = (idx32 << 3);", "emu_typical"),
    ("rtl/sensor_emu.v", "if (par) begin                       // frame count becomes even: move", "if (!par) begin                       // frame count becomes even: move", "emu_typical"),
    ("rtl/sensor_emu.v", "else if (pn > lim_s) begin pn = (lim_s <<< 1) - pn; d = 1'b0; end", "else if (pn > lim_s) begin pn = lim_s; d = 1'b0; end", "emu_odd_size"),
    ("rtl/sensor_emu.v", "if (pn < 0) begin pn = -pn; d = 1'b1; end", "if (pn < 0) begin pn = 0; d = 1'b1; end", "emu_odd_size"),
    ("rtl/sensor_emu.v", "x_out <= !noise_en ? clean_c : dead8 ? 14'd0 : hot8 ? 14'h3FFF : raw_c;", "x_out <= !noise_en ? clean_c : dead8 ? 14'd1 : hot8 ? 14'h3FFF : raw_c;", "emu_fullsize"),
    ("rtl/sensor_emu.v", "wire [14:0] s1 = 15'd3000 +", "wire [14:0] s1 = 15'd3001 +", "emu_typical"),
    ("rtl/sensor_emu.v", "(inr1[0] ? {1'b0, rdt[0]} : 15'd0)", "(inr1[0] ? {1'b0, rdt[1]} : 15'd0)", "emu_typical"),
    # not a mutant: hot6 without '&& !dead' is equivalent, x_out already gives dead8 priority over hot8 and hot7/hot8 feed nothing else
    ("rtl/sensor_emu.v", "o7   <= {pB6[21], pB6[21:8]};", "o7   <= {pB6[21], pB6[20:7]};", "emu_typical"),
]
MUTATIONS += [
    ("rtl/csr_regs.v", "2'd0: rdata <= {14'd0, brec[17:9], brec[8:0]};", "2'd0: rdata <= {14'd0, brec[26:18], brec[8:0]};", "csr"),
    ("rtl/csr_regs.v", "r_learn <= 16'd256;", "r_learn <= 16'd255;", "csr"),
    ("rtl/host_if.v", "av_readdatavalid <= rd1;", "av_readdatavalid <= av_read;", "host"),
    ("rtl/host_if.v", "assign csr_wr    = av_write & is_csr;", "assign csr_wr    = av_write;", "host"),
    ("rtl/host_if.v", "if (rd1) av_readdata <= cap1 ? fb_rdata : csr1 ? csr_rdata : 32'd0;", "if (rd1) av_readdata <= is_cap ? fb_rdata : csr1 ? csr_rdata : 32'd0;", "host"),
    ("rtl/host_if.v", "if (rd1) av_readdata <= cap1 ? fb_rdata : csr1 ? csr_rdata : 32'd0;", "if (rd1) av_readdata <= cap1 ? fb_rdata : csr_rdata;", "host"),
    ("rtl/host_if.v", "wire is_feed = av_address[18];", "wire is_feed = av_address[18] | av_address[17];", "host"),
    ("rtl/host_if.v", "wire is_feed = av_address[18];", "wire is_feed = av_address[18] & av_address[17];", "host"),
    ("rtl/host_if.v", "wire is_cap  = ~av_address[18] &  av_address[17];", "wire is_cap  = av_address[17];", "host"),
    ("rtl/host_if.v", "assign fw_addr   = av_address[FAW+1:2];", "assign fw_addr   = av_address[FAW:1];", "host"),
    ("rtl/host_if.v", "assign fw_data   = av_writedata;", "assign fw_data   = {av_writedata[15:0], av_writedata[31:16]};", "host"),
    ("rtl/scene_buf.v", "assign sq = (sel == 2'd0) ? q[7:0] : (sel == 2'd1) ? q[15:8] : (sel == 2'd2) ? q[23:16] : q[31:24];", "assign sq = (sel == 2'd0) ? q[7:0] : (sel == 2'd1) ? q[23:16] : (sel == 2'd2) ? q[15:8] : q[31:24];", "emu_feed"),
    ("rtl/scene_buf.v", "always @(posedge clk) sel <= saddr[1:0];", "always @(*) sel = saddr[1:0];", "emu_feed"),
    ("rtl/scene_buf.v", "wire [14:0] ra = (wa >= NW) ? 15'd0 : wa;", "wire [14:0] ra = wa;", "host"),
    ("rtl/scene_buf.v", "else if (row_done) rows_read <= rows_read + 32'd1;", "else if (row_done) rows_read <= rows_read + 32'd2;", "emu_feed"),
    ("rtl/scene_buf.v", ".ZERO_INIT(1)", ".ZERO_INIT(0)", "host"),
    ("rtl/sensor_emu.v", "assign row_done = tick && real_px && armed && (c_now == W - 1);", "assign row_done = tick && real_px && armed && (c_now == W);", "emu_feed"),
    ("rtl/sensor_emu.v", "assign row_done = tick && real_px && armed && (c_now == W - 1);", "assign row_done = tick && real_px && armed && (c_now == 0);", "emu_feed"),
    ("rtl/sensor_emu.v", "assign inr[gk]  = obj_en && (", "assign inr[gk]  = (", "emu_feed_noobj"),
    ("rtl/sensor_emu.v", "assign scene_addr = cur_pidx;", "assign scene_addr = pidx;", "emu_feed_odd"),
    ("rtl/sensor_emu.v", "wire [14:0] s1 = 15'd3000 + {3'b000, rom_q, 4'b0000}", "wire [14:0] s1 = 15'd3000 + {4'b0000, rom_q, 3'b000}", "emu_feed"),
    ("rtl/csr_regs.v", "8'h24: r_obj <= wdata[0];", "8'h24: r_obj <= wdata[1];", "csr"),
    ("rtl/csr_regs.v", "8'h25: rdata <= feed_rows;", "8'h25: rdata <= feed_rows + 32'd1;", "csr"),
    ("rtl/csr_regs.v", "cap_arm <= 1'b0; r_obj <= 1'b1;", "cap_arm <= 1'b0; r_obj <= 1'b0;", "csr"),
    ("rtl/csr_regs.v", "8'h23: rdata <= {31'd0, FEED != 0};", "8'h23: rdata <= 32'd0;", "csr"),
    ("rtl/frame_cap.v", "wire start = pv && pfirst && armed;", "wire start = pv && armed;", "host"),
    ("rtl/frame_cap.v", "armed <= 1'b1; cap <= 1'b0; done <= 1'b0;", "armed <= 1'b1; done <= 1'b0;", "host"),
    ("rtl/frame_cap.v", "cap_fid <= fid;", "cap_fid <= fid + 32'd1;", "host"),
    ("rtl/frame_cap.v", "wd <= {px, sh};", "wd <= {sh, px};", "host"),
    ("rtl/frame_cap.v", "wire [7:0] px = src_a ? pr8 : pc8;", "wire [7:0] px = src ? pr8 : pc8;", "host"),
    ("rtl/csr_regs.v", "cap_arm <= wdata[8]; end", "cap_arm <= wdata[0]; end", "host"),
    ("rtl/csr_regs.v", "{24'd0, learning, gain_active,", "{24'd0, gain_active, learning,", "csr"),
    ("rtl/csr_regs.v", "if (cyc - ts_eof < lf_min) lf_min <= cyc - ts_eof;", "if (cyc - ts_eof <= lf_min) lf_min <= cyc - ts_eof + 32'd1;", "csr"),
    ("rtl/csr_regs.v", "if (clr_sticky) begin s_retime <= 1'b0; s_ovf <= 1'b0; s_bad <= 1'b0; end", "if (clr_sticky) begin s_retime <= 1'b0; s_ovf <= 1'b0; end", "csr"),
    ("rtl/csr_regs.v", "8'h22: rdata <= lat_n;", "8'h22: rdata <= lat_n + 32'd1;", "csr"),
]
MUTATIONS = [m for m in MUTATIONS if m[1] != m[2]]


def verdict(text):
    lines = text.splitlines()
    has_pass = any(re.match(r"\s*RESULT:\s*PASS", l) for l in lines)
    bad = any(re.match(r"\s*RESULT:\s*FAIL", l) or "MISMATCH" in l or re.match(r"\s*FAIL", l) for l in lines)
    return has_pass and not bad


_BASES = {"real": ROOT}


def run_tb(name, base):
    srcs, tb, params, pre = TESTS[name]
    bd = _BASES[base]
    out = ROOT / "work" / (base + "_" + name + ".vvp")
    out.parent.mkdir(exist_ok=True)
    if pre:
        r = subprocess.run(pre, cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            return False, "VECTOR GENERATION FAILED\n" + r.stdout + r.stderr
    cmd = [IVERILOG, "-g2005", "-Wall", "-o", str(out)]
    for p in params:
        if p.startswith("-"):
            cmd.append(p)
        else:
            cmd += ["-P", p]
    cmd += [str(bd / s) for s in srcs] + [str(ROOT / tb)]
    c = subprocess.run(cmd, capture_output=True, text=True)
    if c.returncode != 0:
        return False, "COMPILE ERROR\n" + c.stdout + c.stderr
    try:
        r = subprocess.run([VVP, str(out)], capture_output=True, text=True, timeout=1800, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    return verdict(r.stdout + r.stderr), r.stdout + r.stderr


def run_all(skip_python, only):
    ok = True
    for name in TESTS:
        if only and only not in name:
            continue
        passed, text = run_tb(name, "real")
        last = [l for l in text.splitlines() if l.strip().startswith("RESULT")]
        print(("PASS  " if passed else "FAIL  ") + name + "   " + (last[-1].strip() if last else "(no verdict line)"))
        if not passed:
            ok = False
            print(text[-2500:])
    if not skip_python and not only:
        py = ROOT / ".venv" / "Scripts" / "python.exe"
        exe = str(py) if py.exists() else sys.executable
        r = subprocess.run([exe, "-m", "pytest", "-q"], cwd=ROOT, capture_output=True, text=True)
        tail = (r.stdout.strip().splitlines() or ["(no output)"])[-1]
        passed = r.returncode == 0 and " passed" in tail and "failed" not in tail and "error" not in tail
        print(("PASS  " if passed else "FAIL  ") + "pytest   " + tail)
        if not passed:
            ok = False
            print(r.stdout[-2500:])
    return ok


def run_feed_slow(only):
    """The frame feeder protocol against the whole design (FEED = 1): tb/thermal_sys_feed_tb.v + scripts/check_feed.py."""
    name = "sys_feed"
    if only and only not in name:
        return True
    d = ROOT / "work" / "feed"
    subprocess.run([sys.executable, "scripts/gen_feed_vectors.py", "--out", str(d)], cwd=ROOT, capture_output=True, text=True)
    out = ROOT / "work" / (name + ".vvp")
    c = subprocess.run([IVERILOG, "-g2005", "-o", str(out), "-P", 'thermal_sys_feed_tb.DIR="work/feed"']
                       + [str(ROOT / f) for f in SYS_SRC] + [str(ROOT / "tb/thermal_sys_feed_tb.v")], capture_output=True, text=True)
    if c.returncode != 0:
        print("FAIL  %s   COMPILE ERROR\n%s" % (name, c.stderr[-1500:]))
        return False
    r = subprocess.run([VVP, str(out)], capture_output=True, text=True, cwd=ROOT)
    sim_ok = verdict(r.stdout + r.stderr)
    k = subprocess.run([sys.executable, "scripts/check_feed.py", "--dir", "work/feed", "--cap1", "work/feed/cap1.txt",
                        "--cap2", "work/feed/cap2.txt", "--info", "work/feed/info.txt"], capture_output=True, text=True, cwd=ROOT)
    chk_ok = k.returncode == 0 and "RESULT: PASS" in k.stdout
    print(("PASS  " if sim_ok and chk_ok else "FAIL  ") + name + "   " + " | ".join(l.strip() for l in k.stdout.strip().splitlines()[:3]))
    if not (sim_ok and chk_ok):
        print(k.stdout[-1500:], k.stderr[-800:], r.stdout[-1200:])
    return sim_ok and chk_ok


def run_slow(only):
    ok = True
    for name, (params, chk, capchk) in SLOW.items():
        if only and only not in name:
            continue
        out = ROOT / "work" / (name + ".vvp")
        dump = "work/vga_dump_%s.txt" % name
        capdump = "work/cap_dump_%s.txt" % name
        cmd = [IVERILOG, "-g2005", "-o", str(out)]
        for p in params + ['thermal_sys_tb.DUMP="%s"' % dump, 'thermal_sys_tb.CAPDUMP="%s"' % capdump]:
            cmd += ["-P", p]
        cmd += [str(ROOT / sfile) for sfile in SYS_SRC] + [str(ROOT / "tb/thermal_sys_tb.v")]
        c = subprocess.run(cmd, capture_output=True, text=True)
        if c.returncode != 0:
            print("FAIL  %s   COMPILE ERROR\n%s" % (name, c.stderr[-1500:]))
            ok = False
            continue
        r = subprocess.run([VVP, str(out)], capture_output=True, text=True, cwd=ROOT)
        sim_ok = verdict(r.stdout + r.stderr)
        k = subprocess.run([sys.executable, "scripts/check_vga.py", "--dump", dump] + chk.split(), capture_output=True, text=True, cwd=ROOT)
        chk_ok = k.returncode == 0 and "RESULT: PASS" in k.stdout
        q = subprocess.run([sys.executable, "scripts/check_capture.py", "--dump", capdump] + capchk.split(),
                           capture_output=True, text=True, cwd=ROOT)
        cap_ok = q.returncode == 0 and "RESULT: PASS" in q.stdout
        print(("PASS  " if sim_ok and chk_ok and cap_ok else "FAIL  ") + name + "   VGA: "
              + (k.stdout.strip().splitlines() or ["(no output)"])[-1] + " | capture: "
              + (q.stdout.strip().splitlines() or ["(no output)"])[0])
        if not (sim_ok and chk_ok and cap_ok):
            ok = False
            print(k.stdout[-1500:], q.stdout[-600:], q.stderr[-600:], r.stdout[-800:])
    return ok


def selftest(only):
    print("selftest: regression must report FAIL for every broken RTL variant")
    all_caught = True
    for i, (rel, old, new, tbname) in enumerate(MUTATIONS):
        if only and only not in tbname:
            continue
        mdir = ROOT / "work" / ("mut%d" % i)
        if mdir.exists():
            shutil.rmtree(mdir)
        (mdir / "rtl").mkdir(parents=True)
        for f in (ROOT / "rtl").glob("*.v"):
            shutil.copy(f, mdir / "rtl" / f.name)
        p = mdir / rel
        src = p.read_text()
        if old not in src:
            print("  SELFTEST ERROR: mutation pattern not found: %s in %s" % (old, rel))
            all_caught = False
            continue
        p.write_text(src.replace(old, new, 1))
        _BASES["mut%d" % i] = mdir
        passed, text = run_tb(tbname, "mut%d" % i)
        # a mutant only counts as caught if the testbench itself reported a functional failure
        invalid = text.startswith(("COMPILE ERROR", "VECTOR GENERATION FAILED", "TIMEOUT"))
        caught = (not passed) and not invalid
        why = next((l.strip() for l in text.splitlines() if "MISMATCH" in l or l.strip().startswith("FAIL")), "")
        print("  %s  %s: %s -> %s  (%s)  %s" % ("CAUGHT" if caught else ("INVALID" if invalid else "MISSED"), rel,
                                                  old[:40], new[:40], tbname, why[:70]))
        all_caught = all_caught and caught
    assert verdict("") is False and verdict("hello") is False and verdict("RESULT: PASS\nMISMATCH x") is False
    print("  verdict(): empty / no-verdict / PASS+MISMATCH -> FAIL ok")
    return all_caught


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--skip-python", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--slow", action="store_true", help="also run the full-size end-to-end system simulations")
    a = ap.parse_args()
    ok = run_all(a.skip_python, a.only)
    if a.slow:
        ok = run_slow(a.only) and ok
        ok = run_feed_slow(a.only) and ok
    if a.selftest:
        ok = selftest(a.only) and ok
    print("OVERALL: " + ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
