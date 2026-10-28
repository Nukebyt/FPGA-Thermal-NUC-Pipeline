`timescale 1ns/1ps
// csr_regs.v -- control/status registers + hardware latency counters (roadmap 3.4, 4.7, 6.3).
// 32-bit word-addressed slave: one write per clock, read data valid one clock after `rd`. The bus is Avalon-MM
// compatible (waitrequest is always 0) so the lightweight HPS-to-FPGA bridge can drive it unchanged (Phase 3b).
// Until a master sets CTRL.csr_use the top level ignores these controls and uses the board switches.
//
// ---- map (word address) --------------------------------------------------------------------------------------
//  0x00 ID       RO  [31:16] 0x7A11, [15:0] BUILD (parameter; host software refuses to run on a mismatch)
//  0x01 CTRL     RW  [0] nuc_en [1] learn_en [2] bp_en [3] overlay [4] noise_en [6:5] preset [7] csr_use
//                    [9:8] view (0 corrected, 1 raw, 2 split) [10] iron palette        (reset: 1,1,1,1,1,01,0,2,0)
//  0x02 PULSE    WO  write-1 pulses: [0] coef_reset [1] frame_reset [2] clear sticky flags [3] clear latency stats
//  0x03 BP_T     RW  bad-pixel outlier threshold, counts (reset 800)
//  0x04 EMIN     RW  error limit floor, counts, <= 1023 (reset 16)
//  0x05 EMAX     RW  error limit ceiling, counts, <= 1023 (reset 512)
//  0x06 T_MASK   RW  motion threshold, counts (reset 400)
//  0x07 DET_WARM RW  frames before the mask is reported (reset 128)
//  0x08 ACT_THR  RW  gain-learning activity gate (reset 64)
//  0x09 MIN_AREA RW  smallest object, pixels (reset 8)
//  0x0A TONE_LO  RW  manual display window low (reset 0)      0x0B TONE_SH RW [3:0] manual shift   (reset 6)
//  0x0C TONE_AUTO RW [0] 1 = automatic window (reset 1)
//  0x0D LEARN_N  RW  NUC learning window: frames of learning after a coefficient reset, 0 = no limit (reset 256)
//  0x0E CAP      RW  frame capture: [0] source (0 corrected, 1 raw); writing [8]=1 arms a capture of the next frame.
//                    Read: [0] source [16] busy [17] done      0x0F CAP_FID RO frame index of the captured frame
//                    (frames since reset, 0-based). The pixels are at bus address 0x20000 (host_if.v).
//  0x10 STATUS   RO  [0] ready [1] retime_err (sticky) [2] box_ovf (sticky) [3] bad pixels seen (sticky) [4] det_valid
//                    [5] motion now (n_obj > 0 in the last frame) [6] gain learning active this frame
//                    [7] NUC learning runs this frame (learn_en, nuc_en and the LEARN_N window open)
//  0x11 FRAMES   RO  frames whose boxes were published since reset
//  0x12 BOXINFO  RO  [7:0] n_obj [12:8] listed [16] overflow of the last frame
//  0x13 ACT_SUM  RO  sum |y-B| of the last frame, counts
//  0x14 SUME_LO  RO  sum |e| of the last frame [31:0]   0x15 [7:0] = bits 39:32, [27:16] = error limit applied
//  0x16 DET_N    RO  detector frame count (saturates at 255)
//  0x17 BADCNT   RO  pixels flagged bad in the last frame
//  Latency counters (cycles of the 25 MHz clock; all deltas are of the LAST frame):
//  0x18 TS_FIRST RO  cycle counter at the first input tick of a frame
//  0x19 TS_EOF   RO  ... at the end-of-frame input tick (slot (H,0))
//  0x1A TS_Y00   RO  ... when pixel (0,0) leaves the NUC
//  0x1B TS_BOX   RO  ... when the box list was published
//  0x1C LAT_PIX  RO  TS_Y00 - TS_FIRST   (pixel-in -> pixel-out, includes the (W+2)-tick window delay)
//  0x1D LAT_FLAG RO  TS_BOX - TS_EOF     (end-of-frame -> motion flag: the fixed latency K)
//  0x1E LATP_MIN 0x1F LATP_MAX 0x20 LATF_MIN 0x21 LATF_MAX 0x22 LAT_N   RO  min/max over all frames since the last clear
//  0x23 CAPS    RO  [0] scene feed buffer present (FEED build)
//  0x24 FEED_CTRL RW [0] objects: draw the emulator's moving rectangles (reset 1; clear it for real clips)
//  0x25 FEED_ROW  RO source rows the scene scan has read since reset (rtl/scene_buf.v); the writer of the feed buffer
//                    stays behind this counter and ahead of it by less than a frame (sw/frame_feeder.c)
//  0x30 + 4*i + {0,1,2}  RO  box i: [0] {ymin[8:0],xmin[8:0]} [1] {ymax[8:0],xmax[8:0]} [2] area
module csr_regs #(
    parameter [15:0] BUILD = 16'h0001,
    parameter        FEED  = 0
) (
    input  wire         clk,
    input  wire         rst_n,
    // bus
    input  wire         wr,
    input  wire         rd,
    input  wire [7:0]   addr,
    input  wire [31:0]  wdata,
    output reg  [31:0]  rdata,
    // controls out
    output wire         nuc_en, learn_en, bp_en, overlay_en, noise_en, csr_use, iron,
    output wire [1:0]   preset, view,
    output wire [13:0]  bp_t,
    output wire [9:0]   emin, emax,
    output wire [13:0]  t_mask,
    output wire [7:0]   det_warm,
    output wire [15:0]  act_thr, min_area,
    output wire [13:0]  tone_lo,
    output wire [3:0]   tone_sh,
    output wire         tone_auto,
    output wire         obj_en,
    input  wire [31:0]  feed_rows,
    output wire [15:0]  learn_n,
    output reg          cap_arm,
    output wire         cap_src,
    input  wire         cap_busy, cap_done,
    input  wire [31:0]  cap_fid,
    output reg          coef_reset, frame_reset,
    // status in
    input  wire         ready, retime_err, box_ovf_now, bad_seen_now, det_valid, gain_active, learning,
    input  wire         box_done,
    input  wire [7:0]   box_n,
    input  wire [4:0]   box_cnt,
    input  wire [16*53-1:0] box_rec,
    input  wire         det_fdone,
    input  wire [31:0]  det_act_sum,
    input  wire [7:0]   det_n_after,
    input  wire         nuc_fdone,
    input  wire [39:0]  nuc_sum_abs_e,
    input  wire [11:0]  nuc_lim,
    input  wire [31:0]  bad_count,
    // latency events (single-clock pulses)
    input  wire         ev_first_in,
    input  wire         ev_eof_in,
    input  wire         ev_y00,
    // direct status outputs (HEX display, LEDs)
    output wire [31:0]  o_frames,
    output wire [31:0]  o_lat_pix, o_lat_flag, o_latf_min, o_latf_max, o_latp_min, o_latp_max
);

    // ---------------------------------------------------------------- registers
    reg [10:0] ctrl;
    reg [13:0] r_bpt, r_tmask, r_tlo;
    reg [9:0]  r_emin, r_emax;
    reg [7:0]  r_warm;
    reg [15:0] r_thr, r_area, r_learn;
    reg [3:0]  r_tsh;
    reg        r_tauto, r_csrc, r_obj;
    assign nuc_en = ctrl[0]; assign learn_en = ctrl[1]; assign bp_en = ctrl[2]; assign overlay_en = ctrl[3];
    assign noise_en = ctrl[4]; assign preset = ctrl[6:5]; assign csr_use = ctrl[7]; assign view = ctrl[9:8]; assign iron = ctrl[10];
    assign bp_t = r_bpt; assign emin = r_emin; assign emax = r_emax; assign t_mask = r_tmask; assign det_warm = r_warm;
    assign act_thr = r_thr; assign min_area = r_area; assign tone_lo = r_tlo; assign tone_sh = r_tsh; assign tone_auto = r_tauto;
    assign learn_n = r_learn; assign cap_src = r_csrc; assign obj_en = r_obj;

    reg clr_sticky, clr_lat;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            ctrl <= 11'b0_10_0_01_11111;       // nuc learn bp overlay noise on, preset 1 (typical), csr_use 0, split view, gray
            r_bpt <= 14'd800; r_emin <= 10'd16; r_emax <= 10'd512; r_tmask <= 14'd400; r_warm <= 8'd128;
            r_thr <= 16'd64; r_area <= 16'd8; r_tlo <= 14'd0; r_tsh <= 4'd6; r_tauto <= 1'b1; r_learn <= 16'd256; r_csrc <= 1'b0; cap_arm <= 1'b0; r_obj <= 1'b1;
            coef_reset <= 1'b0; frame_reset <= 1'b0; clr_sticky <= 1'b0; clr_lat <= 1'b0;
        end else begin
            coef_reset <= 1'b0; frame_reset <= 1'b0; clr_sticky <= 1'b0; clr_lat <= 1'b0; cap_arm <= 1'b0;
            if (wr) begin
                case (addr)
                    8'h01: ctrl <= wdata[10:0];
                    8'h02: begin coef_reset <= wdata[0]; frame_reset <= wdata[1]; clr_sticky <= wdata[2]; clr_lat <= wdata[3]; end
                    8'h03: r_bpt <= wdata[13:0];
                    8'h04: r_emin <= wdata[9:0];
                    8'h05: r_emax <= wdata[9:0];
                    8'h06: r_tmask <= wdata[13:0];
                    8'h07: r_warm <= wdata[7:0];
                    8'h08: r_thr <= wdata[15:0];
                    8'h09: r_area <= wdata[15:0];
                    8'h0A: r_tlo <= wdata[13:0];
                    8'h0B: r_tsh <= wdata[3:0];
                    8'h0C: r_tauto <= wdata[0];
                    8'h0D: r_learn <= wdata[15:0];
                    8'h0E: begin r_csrc <= wdata[0]; cap_arm <= wdata[8]; end
                    8'h24: r_obj <= wdata[0];
                    default: ;
                endcase
            end
        end
    end

    // ---------------------------------------------------------------- status capture
    reg s_retime, s_ovf, s_bad;
    reg [31:0] frames;
    reg [7:0]  b_n;
    reg [4:0]  b_cnt;
    reg        b_ovf;
    reg [31:0] act_sum, sume_lo;
    reg [7:0]  sume_hi, det_n;
    reg [11:0] lim;
    reg [31:0] badcnt;
    reg [16*53-1:0] rec;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s_retime <= 1'b0; s_ovf <= 1'b0; s_bad <= 1'b0; frames <= 32'd0; b_n <= 8'd0; b_cnt <= 5'd0; b_ovf <= 1'b0;
            act_sum <= 32'd0; sume_lo <= 32'd0; sume_hi <= 8'd0; det_n <= 8'd0; lim <= 12'd0; badcnt <= 32'd0; rec <= {16*53{1'b0}};
        end else begin
            if (clr_sticky) begin s_retime <= 1'b0; s_ovf <= 1'b0; s_bad <= 1'b0; end
            else begin
                if (retime_err) s_retime <= 1'b1;
                if (box_ovf_now && box_done) s_ovf <= 1'b1;
                if (bad_seen_now) s_bad <= 1'b1;
            end
            if (box_done) begin
                frames <= frames + 32'd1; b_n <= box_n; b_cnt <= box_cnt; b_ovf <= box_ovf_now; rec <= box_rec;
            end
            if (det_fdone) begin act_sum <= det_act_sum; det_n <= det_n_after; end
            if (nuc_fdone) begin sume_lo <= nuc_sum_abs_e[31:0]; sume_hi <= nuc_sum_abs_e[39:32]; lim <= nuc_lim; badcnt <= bad_count; end
        end
    end

    // ---------------------------------------------------------------- latency counters
    reg [31:0] cyc;
    reg [31:0] ts_first, ts_eof, ts_y00, ts_box, lat_pix, lat_flag;
    reg [31:0] lp_min, lp_max, lf_min, lf_max, lat_n;
    reg        have_first, have_y00, have_eof;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cyc <= 32'd0; ts_first <= 32'd0; ts_eof <= 32'd0; ts_y00 <= 32'd0; ts_box <= 32'd0; lat_pix <= 32'd0; lat_flag <= 32'd0;
            lp_min <= 32'hFFFFFFFF; lp_max <= 32'd0; lf_min <= 32'hFFFFFFFF; lf_max <= 32'd0; lat_n <= 32'd0;
            have_first <= 1'b0; have_y00 <= 1'b0; have_eof <= 1'b0;
        end else begin
            cyc <= cyc + 32'd1;
            if (clr_lat) begin
                lp_min <= 32'hFFFFFFFF; lp_max <= 32'd0; lf_min <= 32'hFFFFFFFF; lf_max <= 32'd0; lat_n <= 32'd0;
            end
            if (ev_first_in) begin ts_first <= cyc; have_first <= 1'b1; have_y00 <= 1'b0; have_eof <= 1'b0; end
            if (ev_y00 && have_first && !have_y00) begin
                ts_y00 <= cyc; have_y00 <= 1'b1;
                lat_pix <= cyc - ts_first;
                if (!clr_lat) begin
                    if (cyc - ts_first < lp_min) lp_min <= cyc - ts_first;
                    if (cyc - ts_first > lp_max) lp_max <= cyc - ts_first;
                end
            end
            if (ev_eof_in) begin ts_eof <= cyc; have_eof <= 1'b1; end
            if (box_done && have_eof) begin
                ts_box <= cyc;
                lat_flag <= cyc - ts_eof;
                have_eof <= 1'b0;
                if (!clr_lat) begin
                    lat_n <= lat_n + 32'd1;
                    if (cyc - ts_eof < lf_min) lf_min <= cyc - ts_eof;
                    if (cyc - ts_eof > lf_max) lf_max <= cyc - ts_eof;
                end
            end
        end
    end

    assign o_frames = frames;
    assign o_lat_pix = lat_pix; assign o_lat_flag = lat_flag; assign o_latf_min = lf_min; assign o_latf_max = lf_max;
    assign o_latp_min = lp_min; assign o_latp_max = lp_max;

    // ---------------------------------------------------------------- read mux (registered)
    wire [5:0] bsel = addr[7:2] - 6'd12;              // box index from address 0x30
    wire [3:0] bidx = bsel[3:0];
    reg [52:0] brec;
    always @(*) begin
        brec = rec[bidx*53 +: 53];
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) rdata <= 32'd0;
        else if (rd) begin
            case (addr)
                8'h00: rdata <= {16'h7A11, BUILD};
                8'h01: rdata <= {21'd0, ctrl};
                8'h03: rdata <= {18'd0, r_bpt};
                8'h04: rdata <= {22'd0, r_emin};
                8'h05: rdata <= {22'd0, r_emax};
                8'h06: rdata <= {18'd0, r_tmask};
                8'h07: rdata <= {24'd0, r_warm};
                8'h08: rdata <= {16'd0, r_thr};
                8'h09: rdata <= {16'd0, r_area};
                8'h0A: rdata <= {18'd0, r_tlo};
                8'h0B: rdata <= {28'd0, r_tsh};
                8'h0C: rdata <= {31'd0, r_tauto};
                8'h0D: rdata <= {16'd0, r_learn};
                8'h0E: rdata <= {14'd0, cap_done, cap_busy, 15'd0, r_csrc};
                8'h0F: rdata <= cap_fid;
                8'h10: rdata <= {24'd0, learning, gain_active, (b_n != 8'd0), det_valid, s_bad, s_ovf, s_retime, ready};
                8'h11: rdata <= frames;
                8'h12: rdata <= {15'd0, b_ovf, 3'd0, b_cnt, b_n};
                8'h13: rdata <= act_sum;
                8'h14: rdata <= sume_lo;
                8'h15: rdata <= {4'd0, lim, 8'd0, sume_hi};
                8'h16: rdata <= {24'd0, det_n};
                8'h17: rdata <= badcnt;
                8'h18: rdata <= ts_first;
                8'h19: rdata <= ts_eof;
                8'h1A: rdata <= ts_y00;
                8'h1B: rdata <= ts_box;
                8'h1C: rdata <= lat_pix;
                8'h1D: rdata <= lat_flag;
                8'h1E: rdata <= lp_min;
                8'h1F: rdata <= lp_max;
                8'h20: rdata <= lf_min;
                8'h21: rdata <= lf_max;
                8'h22: rdata <= lat_n;
                8'h23: rdata <= {31'd0, FEED != 0};
                8'h24: rdata <= {31'd0, r_obj};
                8'h25: rdata <= feed_rows;
                default: begin
                    if (addr >= 8'h30 && addr < 8'h70) begin
                        case (addr[1:0])
                            2'd0: rdata <= {14'd0, brec[17:9], brec[8:0]};
                            2'd1: rdata <= {14'd0, brec[35:27], brec[26:18]};
                            2'd2: rdata <= {15'd0, brec[52:36]};
                            default: rdata <= 32'd0;
                        endcase
                    end else rdata <= 32'hDEADBEEF;
                end
            endcase
        end
    end
endmodule
