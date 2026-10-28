`timescale 1ns/1ps
// sensor_emu.v -- on-chip emulated thermal sensor with a known ground truth (roadmap Phase 3a).
// Bit-exact twin of model/sensor_emu.py (SensorEmu): clean scene (ROM background + moving rectangles) passed through
// a per-pixel gain/offset, column pattern, temporal noise and dead/hot pixel model.
//
//   S   = 3000 + 16*rom[r>>1][c>>1] + sum(dt of the rectangles covering the pixel)   clean scene, counts (U15)
//   The ROM is half resolution, addressed {r>>1, c>>1} with each field padded to a power of two (no multiplier).
//   z_X = (b0+b1+b2+b3) - 510 of hash32(...)                                          Irwin-Hall, sigma ~ 147.8 (S11)
//   g   = 4096 + ((z_A*GS) >>> 8)  (Q12)   o = (z_B*OS) >>> 8   col = (z_E*CS) >>> 8   n = (z_D*TS) >>> 8
//   raw = clamp(((g*S) >>> 12) + o + col + n, 0, 16383) ; dead -> 0 ; hot -> 16383
// hash inputs: A: idx+SEED_A, B: idx+SEED_B, C: idx+SEED_C, D: 7*idx+frame*FRAME_MUL+SEED_D, E: col+SEED_E.
// The pattern repeats every frame (stateless hash) except the temporal term D, which changes per frame.
//
// Rectangles move every 2nd frame (bounce at the border); positions are updated at the first dummy-row tick, after
// the last real pixel of the frame. Rectangle table RECTP: 3 x 64 bits {x0[9:0], y0[9:0], w[9:0], h[9:0], dt[13:0],
// vx[4:0] signed, vy[4:0] signed}; the default must equal model.sensor_emu.DEFAULT_RECTS (checked by a pytest).
//
// FEED = 1 (roadmap 3b): the scene byte comes from a host-written full-resolution frame store (rtl/scene_buf.v) instead
//   of the half-resolution ROM:  S = 3000 + 16*scene[r][c] + rectangles.  `obj_en` = 0 hides the rectangles (real clips
//   bring their own moving objects). scene_addr is the raster pixel index of the tick in flight, scene_q its byte one
//   clock later; row_done pulses at the last real pixel of every row.
// Latency: otick/ofirst/x_out are the input tick bus delayed LAT_TICK = 9 clocks.
module sensor_emu #(
    parameter W  = 320,
    parameter H  = 240,
    parameter AW = 17,
    parameter INIT_FILE = "rom_bg.hex",
    parameter FEED = 0,
    // default = pack_rects(DEFAULT_RECTS) from model/sensor_emu.py (tests/test_sensor_emu.py checks they agree)
    parameter [191:0] RECTP = 192'h1e01e0300c17707e320780a0160e13e20a03c04824145041
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        tick,
    input  wire        first,
    input  wire [1:0]  preset,         // 0 mild, 1 typical, 2 severe
    input  wire        noise_en,       // 0: output the clean scene (no sensor non-uniformity)
    input  wire        obj_en,         // 0: hide the moving rectangles
    // FEED = 1: scene frame store (rtl/scene_buf.v)
    output wire [AW-1:0] scene_addr,
    input  wire [7:0]  scene_q,
    output wire        row_done,
    output wire        otick,
    output wire        ofirst,
    output reg  [13:0] x_out,          // raw sensor sample (U14)
    output reg  [14:0] clean_out,      // ground truth S (U15), aligned with x_out
    output reg         gt_motion       // pixel is inside a moving rectangle, aligned with x_out
);
    localparam LAT_TICK = 9;
    localparam [31:0] SEED_A = 32'h9E3779B9, SEED_B = 32'h85EBCA6B, SEED_C = 32'hC2B2AE35, SEED_D = 32'h27D4EB2F, SEED_E = 32'h165667B1;
    localparam [31:0] FRAME_MUL = 32'h9E3779B1;
    localparam RB = $clog2((H + 1) / 2);         // ROM row-address bits (7 for 240 lines)
    localparam CB = $clog2((W + 1) / 2);         // ROM column-address bits (8 for 320 columns)

    // ------------------------------------------------------------------ stage 0
    wire [8:0] c_now, r_now;
    wire       gact;
    grid_ctr #(.W(W), .H(H), .ORG(0)) g0 (.clk(clk), .rst_n(rst_n), .tick(tick), .first(first), .c_now(c_now), .r_now(r_now), .act(gact));
    wire real_px = gact && (c_now < W) && (r_now < H);

    reg  [AW-1:0] pidx;
    wire [AW-1:0] cur_pidx = first ? {AW{1'b0}} : pidx;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) pidx <= {AW{1'b0}};
        else if (tick) pidx <= real_px ? cur_pidx + 1'b1 : cur_pidx;
    end

    wire [7:0] rom_q;
    generate
        if (FEED == 0) begin : g_rom
            rom_sp #(.DW(8), .AW(RB + CB), .DEPTH(1 << (RB + CB)), .INIT_FILE(INIT_FILE)) bg (
                .clk(clk), .raddr({r_now[RB:1], c_now[CB:1]}), .rdata(rom_q));
        end else begin : g_feed
            assign rom_q = scene_q;
        end
    endgenerate
    assign scene_addr = cur_pidx;

    // rectangle state
    reg  [29:0] pxv, pyv;                // 3 x 10-bit positions
    reg  [2:0]  dxv, dyv;                // direction bits (1 = positive)
    reg        par;                      // frame count parity
    reg [31:0] fterm;                    // frame * FRAME_MUL (mod 2^32)

    // constant fields of the rectangle table
    wire [9:0]  rw  [0:2];
    wire [9:0]  rh  [0:2];
    wire [13:0] rdt [0:2];
    wire signed [4:0] rvx [0:2];
    wire signed [4:0] rvy [0:2];
    genvar gk;
    generate
        for (gk = 0; gk < 3; gk = gk + 1) begin : g_rect
            assign rw[gk]  = RECTP[gk*64 + 34 +: 10];
            assign rh[gk]  = RECTP[gk*64 + 24 +: 10];
            assign rdt[gk] = RECTP[gk*64 + 10 +: 14];
            assign rvx[gk] = RECTP[gk*64 + 5 +: 5];
            assign rvy[gk] = RECTP[gk*64 + 0 +: 5];
        end
    endgenerate

    wire [2:0] inr;
    wire [2:0] movr;
    generate
        for (gk = 0; gk < 3; gk = gk + 1) begin : g_in
            assign inr[gk]  = obj_en && ({1'b0, c_now} >= pxv[gk*10 +: 10]) && ({1'b0, c_now} < pxv[gk*10 +: 10] + rw[gk]) &&
                              ({1'b0, r_now} >= pyv[gk*10 +: 10]) && ({1'b0, r_now} < pyv[gk*10 +: 10] + rh[gk]);
            assign movr[gk] = inr[gk] && ((rvx[gk] != 5'sd0) || (rvy[gk] != 5'sd0));
        end
    endgenerate

    // end-of-frame update of rectangles / frame term (first dummy-row tick: all real pixels are done)
    // The tick grid also runs in the tail of the VGA frame in which the system came out of reset, before any `first`:
    // that phantom frame must not advance the frame counter or move the rectangles (twin starts at frame 0).
    reg armed;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) armed <= 1'b0;
        else if (tick && first) armed <= 1'b1;
    end
    wire eof_tick = tick && gact && armed && (r_now == H) && (c_now == 0);
    assign row_done = tick && real_px && armed && (c_now == W - 1);

    // movement (one axis helper)
    function [11:0] step_pos;           // returns {dir_new, pos_new[10:0]}  (pos in 0..lim)
        input [9:0]  pos;
        input        dir;
        input signed [4:0] v;
        input [9:0]  lim;
        reg signed [12:0] pn;
        reg signed [12:0] delta;
        reg signed [12:0] lim_s;
        reg d;
        begin
            delta = dir ? $signed({{8{v[4]}}, v}) : -$signed({{8{v[4]}}, v});
            pn = $signed({3'b000, pos}) + delta;
            lim_s = $signed({3'b000, lim});
            d = dir;
            if (pn < 0) begin pn = -pn; d = 1'b1; end
            else if (pn > lim_s) begin pn = (lim_s <<< 1) - pn; d = 1'b0; end
            step_pos = {d, pn[10:0]};
        end
    endfunction

    reg [11:0] sx0, sx1, sx2, sy0, sy1, sy2;
    always @(*) begin
        sx0 = step_pos(pxv[0 +: 10], dxv[0], rvx[0], W - rw[0]);
        sx1 = step_pos(pxv[10 +: 10], dxv[1], rvx[1], W - rw[1]);
        sx2 = step_pos(pxv[20 +: 10], dxv[2], rvx[2], W - rw[2]);
        sy0 = step_pos(pyv[0 +: 10], dyv[0], rvy[0], H - rh[0]);
        sy1 = step_pos(pyv[10 +: 10], dyv[1], rvy[1], H - rh[1]);
        sy2 = step_pos(pyv[20 +: 10], dyv[2], rvy[2], H - rh[2]);
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            pxv <= {RECTP[128 + 54 +: 10], RECTP[64 + 54 +: 10], RECTP[54 +: 10]};
            pyv <= {RECTP[128 + 44 +: 10], RECTP[64 + 44 +: 10], RECTP[44 +: 10]};
            dxv <= 3'b111; dyv <= 3'b111;
            par <= 1'b0; fterm <= 32'd0;
        end else if (eof_tick) begin
            par <= ~par;
            fterm <= fterm + FRAME_MUL;
            if (par) begin                       // frame count becomes even: move
                pxv <= {sx2[9:0], sx1[9:0], sx0[9:0]}; dxv <= {sx2[11], sx1[11], sx0[11]};
                pyv <= {sy2[9:0], sy1[9:0], sy0[9:0]}; dyv <= {sy2[11], sy1[11], sy0[11]};
            end
        end
    end

    // hash inputs
    wire [31:0] idx32 = {{(32-AW){1'b0}}, cur_pidx};
    wire [31:0] idx7  = (idx32 << 3) - idx32;
    wire [31:0] hin_a = idx32 + SEED_A;
    wire [31:0] hin_b = idx32 + SEED_B;
    wire [31:0] hin_c = idx32 + SEED_C;
    wire [31:0] hin_d = idx7 + fterm + SEED_D;
    wire [31:0] hin_e = {23'd0, c_now} + SEED_E;
    wire [31:0] ha, hb, hc, hd, he;
    hash32 hA (.clk(clk), .rst_n(rst_n), .x(hin_a), .y(ha));
    hash32 hB (.clk(clk), .rst_n(rst_n), .x(hin_b), .y(hb));
    hash32 hC (.clk(clk), .rst_n(rst_n), .x(hin_c), .y(hc));
    hash32 hD (.clk(clk), .rst_n(rst_n), .x(hin_d), .y(hd));
    hash32 hE (.clk(clk), .rst_n(rst_n), .x(hin_e), .y(he));

    // ------------------------------------------------------------------ pipeline of tick bus and scene value
    // tick bus: bit k of tpipe = tick delayed (k+1) clocks
    reg [LAT_TICK-1:0] tpipe, fpipe;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin tpipe <= {LAT_TICK{1'b0}}; fpipe <= {LAT_TICK{1'b0}}; end
        else begin tpipe <= {tpipe[LAT_TICK-2:0], tick}; fpipe <= {fpipe[LAT_TICK-2:0], first}; end
    end
    assign otick  = tpipe[LAT_TICK-1];
    assign ofirst = fpipe[LAT_TICK-1];

    // stage 1: scene value (ROM data arrives now)
    reg [2:0]  inr1, mov1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin inr1 <= 3'd0; mov1 <= 3'd0; end
        else begin inr1 <= inr; mov1 <= movr; end
    end
    wire [14:0] s1 = 15'd3000 + {3'b000, rom_q, 4'b0000}
                   + (inr1[0] ? {1'b0, rdt[0]} : 15'd0) + (inr1[1] ? {1'b0, rdt[1]} : 15'd0) + (inr1[2] ? {1'b0, rdt[2]} : 15'd0);
    reg [14:0] s2, s3, s4, s5, s6, s7, s8;
    reg        m2, m3, m4, m5, m6, m7, m8;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s2 <= 15'd0; s3 <= 15'd0; s4 <= 15'd0; s5 <= 15'd0; s6 <= 15'd0; s7 <= 15'd0; s8 <= 15'd0;
            m2 <= 1'b0; m3 <= 1'b0; m4 <= 1'b0; m5 <= 1'b0; m6 <= 1'b0; m7 <= 1'b0; m8 <= 1'b0;
        end else begin
            s2 <= s1; s3 <= s2; s4 <= s3; s5 <= s4; s6 <= s5; s7 <= s6; s8 <= s7;
            m2 <= |mov1; m3 <= m2; m4 <= m3; m5 <= m4; m6 <= m5; m7 <= m6; m8 <= m7;
        end
    end

    // ------------------------------------------------------------------ stage 5/6: z values, scaled
    reg [9:0] GS, OS, CS, TS;
    reg [15:0] DEADT, HOTT;
    always @(*) begin
        case (preset)
            2'd0: begin GS = 10'd142; OS = 10'd52;  CS = 10'd9;  TS = 10'd5;  DEADT = 16'd7;   HOTT = 16'd7;   end
            2'd1: begin GS = 10'd355; OS = 10'd173; CS = 10'd35; TS = 10'd14; DEADT = 16'd33;  HOTT = 16'd33;  end
            default: begin GS = 10'd710; OS = 10'd433; CS = 10'd87; TS = 10'd26; DEADT = 16'd131; HOTT = 16'd131; end
        endcase
    end
    function signed [10:0] zof;
        input [31:0] h;
        reg [10:0] sum;
        begin
            sum = {3'b0, h[7:0]} + {3'b0, h[15:8]} + {3'b0, h[23:16]} + {3'b0, h[31:24]};
            zof = $signed(sum) - 11'sd510;
        end
    endfunction
    reg signed [21:0] pA6, pB6, pE6, pD6;
    reg               dead6, hot6;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin pA6 <= 22'sd0; pB6 <= 22'sd0; pE6 <= 22'sd0; pD6 <= 22'sd0; dead6 <= 1'b0; hot6 <= 1'b0; end
        else begin
            pA6 <= zof(ha) * $signed({1'b0, GS});
            pB6 <= zof(hb) * $signed({1'b0, OS});
            pE6 <= zof(he) * $signed({1'b0, CS});
            pD6 <= zof(hd) * $signed({1'b0, TS});
            dead6 <= (hc[15:0] < DEADT);
            hot6  <= (hc[31:16] < HOTT) && !(hc[15:0] < DEADT);
        end
    end
    // stage 6 -> 7: g, o, col, n
    reg [12:0]        g7;
    reg signed [14:0] o7, col7, n7;
    reg               dead7, hot7;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin g7 <= 13'd0; o7 <= 15'sd0; col7 <= 15'sd0; n7 <= 15'sd0; dead7 <= 1'b0; hot7 <= 1'b0; end
        else begin
            g7   <= 13'd4096 + pA6[20:8];                  // pA6 >>> 8 (the sum stays positive, 13 bits suffice)
            o7   <= {pB6[21], pB6[21:8]};           // pB6 >>> 8, sign kept (|value| <= 863)
            col7 <= {pE6[21], pE6[21:8]};
            n7   <= {pD6[21], pD6[21:8]};
            dead7 <= dead6; hot7 <= hot6;
        end
    end
    // stage 7 -> 8: g*S
    reg signed [29:0] gs8;
    reg signed [14:0] o8, col8, n8;
    reg               dead8, hot8;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin gs8 <= 30'sd0; o8 <= 15'sd0; col8 <= 15'sd0; n8 <= 15'sd0; dead8 <= 1'b0; hot8 <= 1'b0; end
        else begin
            gs8 <= $signed({1'b0, g7}) * $signed({1'b0, s7});
            o8 <= o7; col8 <= col7; n8 <= n7; dead8 <= dead7; hot8 <= hot7;
        end
    end
    // stage 8 -> out
    wire signed [30:0] raw_s = (gs8 >>> 12) + o8 + col8 + n8;
    wire [13:0] raw_c = raw_s[30] ? 14'd0 : (raw_s > 31'sd16383) ? 14'h3FFF : raw_s[13:0];
    wire [13:0] clean_c = (s8 > 15'd16383) ? 14'h3FFF : s8[13:0];
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin x_out <= 14'd0; clean_out <= 15'd0; gt_motion <= 1'b0; end
        else begin
            x_out <= !noise_en ? clean_c : dead8 ? 14'd0 : hot8 ? 14'h3FFF : raw_c;
            clean_out <= s8;
            gt_motion <= m8;
        end
    end
endmodule
