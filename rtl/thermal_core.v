`timescale 1ns/1ps
// thermal_core.v -- NUC -> bad-pixel replace -> background detector -> open/close -> bounding boxes.
// Bit-exact twin of model/pipeline_int.py frame_step(). Everything runs on the tick grid (tick_gen.v) at the VGA
// pixel clock; one pixel every >= 2 clocks.
//
// Stream map (flat-tick delay of each window stage in front of the stage, ORG):
//   nuc_core window    ORG 0         result of pixel (r,c) appears at grid tick (r+1,c+1)
//   morph erode        ORG W+2
//   morph dilate       ORG 2(W+2)
//   morph dilate       ORG 3(W+2)
//   morph erode        ORG 4(W+2)    => mask of pixel (r,c) leaves the chain at flat tick idx(r,c) + 5(W+2)
// tick_gen EXTRA must be >= 7 rows for W >= 8 (5 window stages + flush + margin).
//
// Latency ledger (clocks, from the tick that carries raw pixel (r,c)): per-tick pipeline = nuc 11 + bg 3 + 4*morph(4)
// = 30 clocks. The box list is published a FIXED number of clocks after the last mask pixel leaves the morph chain:
// row_retimer replays the last row at one pixel per 2 clocks (4 + 2(W-1) clocks), then ccl_boxes needs 36 more.
// The activity gate (gain learning on/off) closes its loop here: bg_detect.gain_en_next -> nuc_core.gain_en_in.
module thermal_core #(
    parameter W  = 320,
    parameter H  = 240,
    parameter AW = 17,
    parameter KLIM = 41
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        tick,
    input  wire        first,
    input  wire [13:0] x_in,
    // controls (sampled at the first tick of a frame)
    input  wire        nuc_en,
    input  wire        learn_en,
    input  wire        bp_en,
    input  wire [13:0] bp_t,
    input  wire [9:0]  emin,
    input  wire [9:0]  emax,
    input  wire [13:0] t_mask,
    input  wire [7:0]  det_warm,
    input  wire [15:0] act_thr,
    input  wire [15:0] min_area,
    input  wire [15:0] learn_n,        // NUC learning window, frames (0 = no limit)
    input  wire        coef_reset,
    input  wire        frame_reset,
    output wire        ready,
    // corrected-image stream (aligned with the NUC output bus)
    output wire        y_tick,
    output wire        y_first,
    output wire        y_valid,
    output wire [8:0]  y_cr,
    output wire [8:0]  y_cc,
    output wire [13:0] y_val,
    output wire [13:0] x_val,
    output wire        y_bad,
    // final mask stream (aligned with the last morph stage)
    output wire        m_valid,
    output wire [8:0]  m_cr,
    output wire [8:0]  m_cc,
    output wire        m_bit,
    // boxes
    output wire        box_done,
    output wire [7:0]  box_n,
    output wire [4:0]  box_cnt,
    output wire        box_ovf,
    output wire [16*53-1:0] box_rec,
    // frame statistics
    output wire        nuc_fdone,
    output wire [39:0] nuc_sum_abs_e,
    output wire [11:0] nuc_lim,
    output wire        det_fdone,
    output wire [31:0] det_act_sum,
    output wire [7:0]  det_n_after,
    output wire        det_valid,
    output wire        retime_err,     // sticky: the mask row retimer was overrun (timing assumption violated)
    output wire        gain_active,    // gain learning is allowed in the current frame
    output wire        learning        // NUC learning runs in the current frame (learn_en, nuc_en, window open)
);
    // ---------------- NUC
    wire        n_tick, n_first, n_valid, n_bad;
    wire [8:0]  n_cr, n_cc;
    wire [13:0] n_y, n_x;
    wire        gain_next;
    wire        n_fdone;
    wire [39:0] n_sum;
    wire [11:0] n_lim;
    nuc_core #(.W(W), .H(H), .AW(AW), .KLIM(KLIM)) u_nuc (
        .clk(clk), .rst_n(rst_n), .tick(tick), .first(first), .x_in(x_in),
        .nuc_en(nuc_en), .learn_en(learn_en), .bp_en(bp_en), .bp_t(bp_t), .emin(emin), .emax(emax),
        .gain_en_in(gain_next), .learn_n(learn_n), .coef_reset(coef_reset), .ready(ready), .learning(learning),
        .otick(n_tick), .ofirst(n_first), .ovalid(n_valid), .ocr(n_cr), .occ(n_cc), .oy(n_y), .ox(n_x), .obad(n_bad),
        .fdone(n_fdone), .fsum_abs_e(n_sum), .lim_used(n_lim));
    assign y_tick = n_tick; assign y_first = n_first; assign y_valid = n_valid; assign y_cr = n_cr; assign y_cc = n_cc;
    assign y_val = n_y; assign x_val = n_x; assign y_bad = n_bad;
    assign nuc_fdone = n_fdone; assign nuc_sum_abs_e = n_sum; assign nuc_lim = n_lim;

    // ---------------- background detector
    wire        d_tick, d_first, d_valid, d_mask;
    wire [8:0]  d_cr, d_cc;
    wire        d_fdone, d_dv;
    wire [31:0] d_sum;
    wire [7:0]  d_n;
    bg_detect #(.W(W), .H(H), .AW(AW)) u_det (
        .clk(clk), .rst_n(rst_n),
        .itick(n_tick), .ifirst(n_first), .ivalid(n_valid), .icr(n_cr), .icc(n_cc), .iy(n_y),
        .t_mask(t_mask), .det_warm(det_warm), .act_thr(act_thr), .det_reset(frame_reset),
        .otick(d_tick), .ofirst(d_first), .ovalid(d_valid), .ocr(d_cr), .occ(d_cc), .omask(d_mask),
        .gain_en_next(gain_next), .fdone(d_fdone), .fact_sum(d_sum), .fn_after(d_n), .fdet_valid(d_dv));
    assign gain_active = gain_next;
    assign det_fdone = d_fdone; assign det_act_sum = d_sum; assign det_n_after = d_n; assign det_valid = d_dv;

    // ---------------- morphology: erode, dilate, dilate, erode
    wire        m1_t, m1_f, m1_v, m1_d;  wire [8:0] m1_r, m1_c;
    wire        m2_t, m2_f, m2_v, m2_d;  wire [8:0] m2_r, m2_c;
    wire        m3_t, m3_f, m3_v, m3_d;  wire [8:0] m3_r, m3_c;
    wire        m4_t, m4_f, m4_v, m4_d;  wire [8:0] m4_r, m4_c;
    morph3 #(.OP(0), .W(W), .H(H), .ORG(1 * (W + 2))) u_m1 (.clk(clk), .rst_n(rst_n), .tick(d_tick), .first(d_first), .din(d_mask),
        .otick(m1_t), .ofirst(m1_f), .ovalid(m1_v), .ocr(m1_r), .occ(m1_c), .odata(m1_d));
    morph3 #(.OP(1), .W(W), .H(H), .ORG(2 * (W + 2))) u_m2 (.clk(clk), .rst_n(rst_n), .tick(m1_t), .first(m1_f), .din(m1_d),
        .otick(m2_t), .ofirst(m2_f), .ovalid(m2_v), .ocr(m2_r), .occ(m2_c), .odata(m2_d));
    morph3 #(.OP(1), .W(W), .H(H), .ORG(3 * (W + 2))) u_m3 (.clk(clk), .rst_n(rst_n), .tick(m2_t), .first(m2_f), .din(m2_d),
        .otick(m3_t), .ofirst(m3_f), .ovalid(m3_v), .ocr(m3_r), .occ(m3_c), .odata(m3_d));
    morph3 #(.OP(0), .W(W), .H(H), .ORG(4 * (W + 2))) u_m4 (.clk(clk), .rst_n(rst_n), .tick(m3_t), .first(m3_f), .din(m3_d),
        .otick(m4_t), .ofirst(m4_f), .ovalid(m4_v), .ocr(m4_r), .occ(m4_c), .odata(m4_d));
    assign m_valid = m4_v; assign m_cr = m4_r; assign m_cc = m4_c; assign m_bit = m4_d;

    // ---------------- re-time the mask rows (the box extractor needs an idle gap after every row), then boxes
    wire        rt_v, rt_b;
    wire [8:0]  rt_r, rt_c;
    row_retimer #(.W(W), .H(H)) u_rt (
        .clk(clk), .rst_n(rst_n), .ivalid(m4_v), .ibit(m4_d), .icr(m4_r), .icc(m4_c),
        .ovalid(rt_v), .obit(rt_b), .ocr(rt_r), .occ(rt_c), .err(retime_err));
    ccl_boxes #(.W(W), .H(H)) u_ccl (
        .clk(clk), .rst_n(rst_n), .ivalid(rt_v), .imask(rt_b), .icr(rt_r), .icc(rt_c), .min_area(min_area),
        .fdone(box_done), .pub_n(box_n), .pub_cnt(box_cnt), .pub_ovf(box_ovf), .pub_boxes(box_rec));
endmodule
