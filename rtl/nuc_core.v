`timescale 1ns/1ps
// nuc_core.v -- scene-based NUC (LMS) + bad-pixel detect/replace. Bit-exact twin of model/pipeline_int.py nuc_frame().
//
// Algorithm per pixel (all integers, see the Q table in pipeline_int.py):
//   xo = (x<<OF) - o ; y = clamp(round((xo*g) >> (OF+GF-YF)))          correction
//   d  = mean of the valid 4-neighbours of y (own y if none)          desired value
//   e  = y - d ; ec = clamp(e, -lim, lim)
//   o += round(ec >> (YF+KO-OF)) ; g -= round(ec*xo >> SG) (only if gain_en)         LMS update, one frame later
//   bad-pixel counter: +1 if y is outside [min8-T, max8+T] of the valid 8-neighbours or x is at a rail, else -1
//   output = bad ? d : y, rounded to 14 bits
//
// Q formats:  x U14.0 | o S13 (S12.OF, OF=1) | g U13 (U2.GF, GF=12, 1.0=4096) | xo S18 (S16.OF) | y U16 (U14.YF, YF=2)
//             e S17.YF | lim U12.YF | coefficient word {bpc[3:0], g[12:0], o[12:0]} = 30 bits = 3 M10K at 1Kx10.
// Internally the offset is carried sign-extended to 14 bits; only the stored word is 13 bits.
//
// Latency ledger (clocks from the tick that carries pixel (r,c) to the tick-bus output that carries its result):
//   front end F0..F4 : 4 clocks  (coefficient RAM read, subtract, multiply, round/clamp)
//   win3x3           : 3 clocks  AND the window for pixel (r,c) is only complete when the tick of (r+1,c+1) has
//                                 arrived, i.e. (W+2) ticks later (a fixed number of ticks, hence of clocks only
//                                 when the tick spacing is fixed)
//   back end B1..B4  : 4 clocks to the output registers (ovalid/oy/ox/obad), write-back lands 2 clocks later
//   => per-tick LATENCY (otick = tick delayed) is LAT_TICK = 4 + 3 + 4 = 11 clocks.
//
// Hazard (checklist/roadmap 4.5): a pixel's coefficient word is read at its tick and written back about (W+2)
// ticks + 6 clocks later. The next read of the same address is one whole frame later. Required: the time between
// the last real pixel of a frame and the first tick of the next frame is >= (W+2)*tick_spacing + 16 clocks
// (vertical blanking guarantees this; documented in docs/design.md).
//
// Controls (nuc_en .. emax, gain_en_in, learn_n) are sampled at `first` and held for the frame. coef_reset clears the
// whole coefficient RAM (o=0, g=1.0, bpc=0) and stalls the datapath until done (`ready`=0); the datapath then
// resumes at the next `first`.
// Learning window: learning runs in a frame only if learn_en & nuc_en and fewer than learn_n frames have learned
// since the last coef_reset (learn_n = 0: no limit). lcnt counts the frames that learned (saturating).
module nuc_core #(
    parameter W  = 320,
    parameter H  = 240,
    parameter AW = 17,                 // address bits of the coefficient RAM (W*H <= 2**AW)
    parameter BP_ON = 8,               // bad-pixel counter threshold
    parameter KLIM  = 41               // limit = (sum|e| * KLIM) >> 20  (~3*mean|e| for 76800 pixels; scale for smaller frames)
) (
    input  wire        clk,
    input  wire        rst_n,
    // tick bus + raw sample (x_in is meaningful only on real-pixel ticks)
    input  wire        tick,
    input  wire        first,
    input  wire [13:0] x_in,
    // controls, sampled at `first`
    input  wire        nuc_en,
    input  wire        learn_en,
    input  wire        bp_en,
    input  wire [13:0] bp_t,           // counts
    input  wire [9:0]  emin,           // counts (<= 1023: limit register is U12.YF)
    input  wire [9:0]  emax,           // counts (<= 1023)
    input  wire        gain_en_in,     // gain learning allowed this frame (from the detector's activity gate)
    input  wire [15:0] learn_n,        // learning window, frames (0 = no limit)
    input  wire        coef_reset,     // 1-clock pulse
    output wire        ready,
    output wire        learning,       // learning runs in the current frame
    // result stream, aligned with otick (valid pixel: ovalid)
    output wire        otick,
    output wire        ofirst,
    output reg         ovalid,
    output reg  [8:0]  ocr,
    output reg  [8:0]  occ,
    output reg  [13:0] oy,             // corrected, bad-pixel-replaced, U14
    output reg  [13:0] ox,             // raw sample of the same pixel, U14
    output reg         obad,           // pixel was flagged bad (and replaced)
    // frame results
    output reg         fdone,          // 1-clock pulse after the last coefficient write of a frame
    output reg  [39:0] fsum_abs_e,     // sum |e| over non-bad pixels of the finished frame (Q.YF)
    output reg  [11:0] lim_used        // error limit that was applied during the finished frame (Q.YF)
);
    localparam OF = 1, GF = 12, YF = 2, KO = 4;
    localparam SHIFT_Y = OF + GF - YF;          // 11
    localparam SG      = 28 + YF + OF - GF;     // 19 (MUG_EXP = 28)
    localparam [13:0] OLIM_Q = 14'd4094;        // 2047 << OF (documentation; the clamp below uses the literal)
    localparam [12:0] GMIN = 13'd2048;          // 0.5
    localparam [12:0] GMAX = 13'd8191;          // just under 2.0
    localparam DEPTH = W * H;
    localparam [29:0] COEF_INIT = {4'd0, 13'd4096, 13'd0};
    localparam LAT_TICK = 11;

    // ------------------------------------------------------------------ coefficient clear / ready
    reg           busy;
    reg  [AW-1:0] cl_addr;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            busy <= 1'b1; cl_addr <= {AW{1'b0}};
        end else if (coef_reset) begin
            busy <= 1'b1; cl_addr <= {AW{1'b0}};
        end else if (busy) begin
            cl_addr <= cl_addr + 1'b1;
            if (cl_addr == DEPTH - 1) busy <= 1'b0;
        end
    end
    assign ready = ~busy;

    // run gating: the datapath only runs whole frames that start with `first` while not busy
    reg run_q;
    wire run_cur = first ? ~busy : run_q;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) run_q <= 1'b0;
        else if (tick) run_q <= run_cur;
    end
    wire tick_i  = tick & run_cur;
    wire first_i = first & ~busy;

    // ------------------------------------------------------------------ per-frame active controls
    reg        nuc_a, learn_a, bp_a, gain_a;
    reg [13:0] bpt_a;
    reg [9:0]  emin_a, emax_a;
    reg [11:0] lim_a;                   // active error limit (Q.YF)
    reg [11:0] lim_n;                   // limit computed from the previous frame
    reg [15:0] lcnt;                    // frames that learned since coef_reset
    wire       learn_now = learn_en & nuc_en & ((learn_n == 16'd0) | (lcnt < learn_n));
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            nuc_a <= 1'b1; learn_a <= 1'b1; bp_a <= 1'b1; gain_a <= 1'b1; bpt_a <= 14'd800;
            emin_a <= 10'd16; emax_a <= 10'd512; lim_a <= 12'd2048;
        end else if (tick_i & first_i) begin
            nuc_a <= nuc_en; learn_a <= learn_now; bp_a <= bp_en; gain_a <= gain_en_in; bpt_a <= bp_t;
            emin_a <= emin; emax_a <= emax; lim_a <= lim_n;
        end
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)                                             lcnt <= 16'd0;
        else if (coef_reset)                                    lcnt <= 16'd0;
        else if (tick_i & first_i & learn_now & (lcnt != 16'hFFFF)) lcnt <= lcnt + 16'd1;
    end
    assign learning = learn_a;          // learn_now already includes nuc_en

    // ------------------------------------------------------------------ F0: grid position, pixel index, RAM read
    wire [8:0] c_now, r_now;
    wire       gact;
    grid_ctr #(.W(W), .H(H), .ORG(0)) g0 (
        .clk(clk), .rst_n(rst_n), .tick(tick_i), .first(first_i), .c_now(c_now), .r_now(r_now), .act(gact));
    wire real_px = gact && (c_now < W) && (r_now < H);

    reg  [AW-1:0] pidx;
    wire [AW-1:0] cur_pidx = first_i ? {AW{1'b0}} : pidx;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) pidx <= {AW{1'b0}};
        else if (tick_i) pidx <= real_px ? cur_pidx + 1'b1 : cur_pidx;
    end

    wire [29:0]   cw;                         // coefficient word read (valid in F1)
    reg           wr_en_b;                    // back-end write request
    reg  [AW-1:0] wr_addr_b;
    reg  [29:0]   wr_data_b;
    ram_sdp #(.DW(30), .AW(AW), .DEPTH(DEPTH)) coef (
        .clk(clk),
        .we(busy | wr_en_b), .waddr(busy ? cl_addr : wr_addr_b), .wdata(busy ? COEF_INIT : wr_data_b),
        .raddr(cur_pidx), .rdata(cw));

    // ------------------------------------------------------------------ F1 .. F4
    reg        tk1, fs1;
    reg [13:0] x1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin tk1 <= 1'b0; fs1 <= 1'b0; x1 <= 14'd0; end
        else begin tk1 <= tick_i; fs1 <= first_i; x1 <= x_in; end
    end

    // F1 -> F2: subtract
    wire signed [17:0] xo1 = $signed({3'b000, x1, 1'b0}) - $signed({{5{cw[12]}}, cw[12:0]});
    reg        tk2, fs2;
    reg signed [17:0] xo2;
    reg [12:0] g2;
    reg [3:0]  bpc2;
    reg [13:0] o2, x2;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tk2 <= 1'b0; fs2 <= 1'b0; xo2 <= 18'sd0; g2 <= 13'd0; bpc2 <= 4'd0; o2 <= 14'd0; x2 <= 14'd0;
        end else begin
            tk2 <= tk1; fs2 <= fs1; xo2 <= xo1; g2 <= cw[25:13]; bpc2 <= cw[29:26]; o2 <= {cw[12], cw[12:0]}; x2 <= x1;
        end
    end

    // F2 -> F3: multiply (one DSP)
    reg        tk3, fs3;
    reg signed [31:0] prod3;
    reg signed [17:0] xo3;
    reg [12:0] g3;
    reg [3:0]  bpc3;
    reg [13:0] o3, x3;
    reg        rail3;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tk3 <= 1'b0; fs3 <= 1'b0; prod3 <= 32'sd0; xo3 <= 18'sd0; g3 <= 13'd0; bpc3 <= 4'd0; o3 <= 14'd0;
            x3 <= 14'd0; rail3 <= 1'b0;
        end else begin
            tk3 <= tk2; fs3 <= fs2;
            prod3 <= xo2 * $signed({1'b0, g2});
            xo3 <= xo2; g3 <= g2; bpc3 <= bpc2; o3 <= o2; x3 <= x2;
            rail3 <= (x2 == 14'd0) || (x2 == 14'h3FFF);
        end
    end

    // F3 -> F4: round, clamp, select bypass; pack for the window
    wire signed [31:0] pr_r = prod3 + 32'sd1024;                  // 1 << (SHIFT_Y-1)
    wire signed [31:0] pr_s = pr_r >>> SHIFT_Y;
    wire [15:0] y3 = pr_s[31] ? 16'd0 : (pr_s > 32'sd65535) ? 16'hFFFF : pr_s[15:0];
    wire [15:0] y3s = nuc_a ? y3 : {x3, 2'b00};
    wire        bad3 = bp_a && (bpc3 >= BP_ON);

    reg         tk4, fs4;
    reg [16:0]  din4;                                              // {y[15:0], bad}
    reg [49:0]  sin4;                                              // {xo[17:0], o[13:0], g[12:0], bpc[3:0], rail}
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin tk4 <= 1'b0; fs4 <= 1'b0; din4 <= 17'd0; sin4 <= 50'd0; end
        else begin
            tk4 <= tk3; fs4 <= fs3;
            din4 <= {y3s, bad3};
            sin4 <= {xo3, o3, g3, bpc3, rail3};
        end
    end

    // ------------------------------------------------------------------ window (3 clocks)
    wire         w_tick, w_first, w_valid;
    wire [8:0]   w_cr, w_cc;
    wire [9*17-1:0] w_win;
    wire [49:0]  w_side;
    win3x3 #(.DW(17), .SW(50), .W(W), .H(H), .ORG(0)) win (
        .clk(clk), .rst_n(rst_n), .tick(tk4), .first(fs4), .din(din4), .sin(sin4),
        .otick(w_tick), .ofirst(w_first), .wvalid(w_valid), .cr(w_cr), .cc(w_cc), .win(w_win), .sout(w_side));

    // element k of the window bus: NW=8 N=7 NE=6 W=5 C=4 E=3 SW=2 S=1 SE=0 ; each element = {y[15:0], bad}
    wire [16:0] eNW = w_win[8*17 +: 17], eN = w_win[7*17 +: 17], eNE = w_win[6*17 +: 17];
    wire [16:0] eW  = w_win[5*17 +: 17], eC = w_win[4*17 +: 17], eE  = w_win[3*17 +: 17];
    wire [16:0] eSW = w_win[2*17 +: 17], eS = w_win[1*17 +: 17], eSE = w_win[0*17 +: 17];

    // ------------------------------------------------------------------ B1: neighbour sums, min/max
    function [15:0] vy;          // y if valid else 0
        input [16:0] e;
        begin vy = e[0] ? 16'd0 : e[16:1]; end
    endfunction
    function [15:0] vy_hi;       // for min: invalid -> FFFF
        input [16:0] e;
        begin vy_hi = e[0] ? 16'hFFFF : e[16:1]; end
    endfunction
    function [15:0] max2; input [15:0] a; input [15:0] b; begin max2 = (a > b) ? a : b; end endfunction
    function [15:0] min2; input [15:0] a; input [15:0] b; begin min2 = (a < b) ? a : b; end endfunction

    wire [17:0] sum4_w = vy(eN) + vy(eW) + vy(eE) + vy(eS);
    wire [2:0]  cnt_w  = {2'b0, ~eN[0]} + {2'b0, ~eW[0]} + {2'b0, ~eE[0]} + {2'b0, ~eS[0]};
    wire [15:0] hi_w = max2(max2(max2(vy(eNW), vy(eN)), max2(vy(eNE), vy(eW))), max2(max2(vy(eE), vy(eSW)), max2(vy(eS), vy(eSE))));
    wire [15:0] lo_w = min2(min2(min2(vy_hi(eNW), vy_hi(eN)), min2(vy_hi(eNE), vy_hi(eW))), min2(min2(vy_hi(eE), vy_hi(eSW)), min2(vy_hi(eS), vy_hi(eSE))));
    wire        anyv_w = ~(eNW[0] & eN[0] & eNE[0] & eW[0] & eE[0] & eSW[0] & eS[0] & eSE[0]);

    reg         tkb1, fsb1, vb1;
    reg [8:0]   crb1, ccb1;
    reg [17:0]  sum4_1;
    reg [2:0]   cnt1;
    reg [15:0]  hi1, lo1, yc1;
    reg         anyv1, badc1;
    reg [49:0]  side1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tkb1 <= 1'b0; fsb1 <= 1'b0; vb1 <= 1'b0; crb1 <= 9'd0; ccb1 <= 9'd0; sum4_1 <= 18'd0; cnt1 <= 3'd0;
            hi1 <= 16'd0; lo1 <= 16'd0; yc1 <= 16'd0; anyv1 <= 1'b0; badc1 <= 1'b0; side1 <= 50'd0;
        end else begin
            tkb1 <= w_tick; fsb1 <= w_first; vb1 <= w_valid; crb1 <= w_cr; ccb1 <= w_cc;
            sum4_1 <= sum4_w; cnt1 <= cnt_w; hi1 <= hi_w; lo1 <= lo_w; anyv1 <= anyv_w;
            yc1 <= eC[16:1]; badc1 <= eC[0]; side1 <= w_side;
        end
    end

    // ------------------------------------------------------------------ B2: reciprocal multiply
    reg [16:0] recip;
    always @(*) begin
        case (cnt1)
            3'd1: recip = 17'd65536;
            3'd2: recip = 17'd32768;
            3'd3: recip = 17'd21845;
            3'd4: recip = 17'd16384;
            default: recip = 17'd0;
        endcase
    end
    reg         tkb2, fsb2, vb2;
    reg [8:0]   crb2, ccb2;
    reg [34:0]  mprod2;
    reg [2:0]   cnt2;
    reg [15:0]  hi2, lo2, yc2;
    reg         anyv2, badc2;
    reg [49:0]  side2;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tkb2 <= 1'b0; fsb2 <= 1'b0; vb2 <= 1'b0; crb2 <= 9'd0; ccb2 <= 9'd0; mprod2 <= 35'd0; cnt2 <= 3'd0;
            hi2 <= 16'd0; lo2 <= 16'd0; yc2 <= 16'd0; anyv2 <= 1'b0; badc2 <= 1'b0; side2 <= 50'd0;
        end else begin
            tkb2 <= tkb1; fsb2 <= fsb1; vb2 <= vb1; crb2 <= crb1; ccb2 <= ccb1;
            mprod2 <= sum4_1 * recip; cnt2 <= cnt1; hi2 <= hi1; lo2 <= lo1; yc2 <= yc1; anyv2 <= anyv1;
            badc2 <= badc1; side2 <= side1;
        end
    end

    // ------------------------------------------------------------------ B3: d, e, outlier
    wire [34:0] dsum = mprod2 + 35'd32768;
    wire [15:0] d3   = (cnt2 == 3'd0) ? yc2 : dsum[31:16];
    wire signed [17:0] e3w = $signed({2'b00, yc2}) - $signed({2'b00, d3});
    wire [15:0] tq   = {bpt_a, 2'b00};
    wire signed [18:0] hi_t = $signed({3'b000, hi2}) + $signed({3'b000, tq});
    wire signed [18:0] lo_t = $signed({3'b000, lo2}) - $signed({3'b000, tq});
    wire signed [18:0] ycs  = $signed({3'b000, yc2});
    wire        rail_b = side2[0];
    wire        outl_w = (anyv2 && ((ycs > hi_t) || (ycs < lo_t))) || rail_b;

    reg         tkb3, fsb3, vb3;
    reg [8:0]   crb3, ccb3;
    reg signed [17:0] e3;
    reg [15:0]  d3r, yc3;
    reg         badc3, outl3;
    reg [49:0]  side3;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tkb3 <= 1'b0; fsb3 <= 1'b0; vb3 <= 1'b0; crb3 <= 9'd0; ccb3 <= 9'd0; e3 <= 18'sd0; d3r <= 16'd0;
            yc3 <= 16'd0; badc3 <= 1'b0; outl3 <= 1'b0; side3 <= 50'd0;
        end else begin
            tkb3 <= tkb2; fsb3 <= fsb2; vb3 <= vb2; crb3 <= crb2; ccb3 <= ccb2;
            e3 <= e3w; d3r <= d3; yc3 <= yc2; badc3 <= badc2; outl3 <= outl_w; side3 <= side2;
        end
    end

    // ------------------------------------------------------------------ B4: output register, limit/clip, |e| accumulate
    wire [15:0] yo_q = badc3 ? d3r : yc3;
    wire [16:0] yo_r = {1'b0, yo_q} + 17'd2;                       // round (YF=2)
    wire [14:0] yo_s = yo_r[16:2];
    wire [13:0] yo14 = (yo_s > 15'd16383) ? 14'h3FFF : yo_s[13:0];

    wire signed [12:0] limp = {1'b0, lim_a};
    wire signed [12:0] limn = -limp;
    wire signed [12:0] ec_w = (e3 > $signed({5'b00000, lim_a})) ? limp :
                              (e3 < -$signed({5'b00000, lim_a})) ? limn : e3[12:0];
    wire [17:0] abs_e = e3[17] ? (~e3 + 18'd1) : e3;
    // raw x of the centre pixel = (xo + o) >> OF (OF = 1)
    wire signed [18:0] xr_s = $signed({side3[49], side3[49:32]}) + $signed({{5{side3[31]}}, side3[31:18]});
    wire [13:0] x_raw = xr_s[14:1];

    reg         tkb4, fsb4, vb4;
    reg [8:0]   crb4, ccb4;
    reg signed [12:0] ec4;
    reg         badc4, outl4;
    reg [49:0]  side4;
    reg         last4;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tkb4 <= 1'b0; fsb4 <= 1'b0; vb4 <= 1'b0; crb4 <= 9'd0; ccb4 <= 9'd0; ec4 <= 13'sd0; badc4 <= 1'b0;
            outl4 <= 1'b0; side4 <= 50'd0; last4 <= 1'b0;
            ovalid <= 1'b0; ocr <= 9'd0; occ <= 9'd0; oy <= 14'd0; ox <= 14'd0; obad <= 1'b0;
        end else begin
            tkb4 <= tkb3; fsb4 <= fsb3; vb4 <= vb3; crb4 <= crb3; ccb4 <= ccb3;
            ec4 <= ec_w; badc4 <= badc3; outl4 <= outl3; side4 <= side3;
            last4 <= vb3 && (crb3 == H - 1) && (ccb3 == W - 1);
            ovalid <= vb3; ocr <= crb3; occ <= ccb3; oy <= yo14; ox <= x_raw; obad <= badc3;
        end
    end
    // output tick bus (same clock as ovalid etc.)
    assign otick  = tkb4;
    assign ofirst = fsb4;

    // |e| accumulation (non-bad pixels), cleared at the next frame start
    reg [39:0] acc;
    wire       acc_clr = tick_i & first_i;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) acc <= 40'd0;
        else if (acc_clr) acc <= 40'd0;
        else if (vb3 && !badc3) acc <= acc + {22'd0, abs_e};
    end

    // ------------------------------------------------------------------ B5: update arithmetic
    wire signed [17:0] xo_b = $signed(side4[49:32]);
    wire signed [13:0] o_b  = $signed(side4[31:18]);
    wire [12:0]        g_b  = side4[17:5];
    wire [3:0]         bpc_b = side4[4:1];
    wire signed [13:0] do_w = (ec4 + 13'sd16) >>> 5;               // round(ec >> (YF+KO-OF)) , YF+KO-OF = 5
    wire signed [14:0] o_sum = $signed({o_b[13], o_b}) + $signed({do_w[13], do_w});
    wire signed [14:0] o_hi  = 15'sd4094;
    wire signed [14:0] o_lo  = -15'sd4094;
    wire signed [13:0] o_new = (o_sum > o_hi) ? 14'sd4094 : (o_sum < o_lo) ? -14'sd4094 : o_sum[13:0];

    reg         vb5, last5, badc5, outl5;
    reg [8:0]   crb5, ccb5;
    reg signed [30:0] mg5;
    reg signed [13:0] onew5, o5;
    reg [12:0]  g5;
    reg [3:0]   bpc5;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            vb5 <= 1'b0; last5 <= 1'b0; badc5 <= 1'b0; outl5 <= 1'b0; crb5 <= 9'd0; ccb5 <= 9'd0;
            mg5 <= 31'sd0; onew5 <= 14'sd0; o5 <= 14'sd0; g5 <= 13'd0; bpc5 <= 4'd0;
        end else begin
            vb5 <= vb4; last5 <= last4; badc5 <= badc4; outl5 <= outl4; crb5 <= crb4; ccb5 <= ccb4;
            mg5 <= ec4 * xo_b; onew5 <= o_new; o5 <= o_b; g5 <= g_b; bpc5 <= bpc_b;
        end
    end

    // ------------------------------------------------------------------ B6: gain update, counter, write-back
    wire signed [31:0] mg_r = {mg5[30], mg5} + 32'sd262144;       // 1 << (SG-1)
    wire signed [31:0] dg_w = mg_r >>> SG;
    wire signed [32:0] g_sub = $signed({20'd0, g5}) - $signed({dg_w[31], dg_w});
    wire [12:0] g_new = (g_sub < $signed({20'd0, GMIN})) ? GMIN : (g_sub > $signed({20'd0, GMAX})) ? GMAX : g_sub[12:0];
    wire        upd   = ~badc5 & learn_a & nuc_a;
    wire [12:0] o_wr  = upd ? onew5[12:0] : o5[12:0];
    wire [12:0] g_wr  = (upd & gain_a) ? g_new : g5;
    wire [3:0]  bpc_n = outl5 ? ((bpc5 == 4'd15) ? 4'd15 : bpc5 + 4'd1) : ((bpc5 == 4'd0) ? 4'd0 : bpc5 - 4'd1);
    wire [3:0]  bpc_wr = bp_a ? bpc_n : bpc5;

    reg [AW-1:0] wcnt;
    wire [AW-1:0] wcur = (crb5 == 9'd0 && ccb5 == 9'd0) ? {AW{1'b0}} : wcnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            wr_en_b <= 1'b0; wr_addr_b <= {AW{1'b0}}; wr_data_b <= 30'd0; wcnt <= {AW{1'b0}};
        end else begin
            wr_en_b   <= vb5 & ~busy;
            wr_addr_b <= wcur;
            wr_data_b <= {bpc_wr, g_wr, o_wr};
            if (vb5) wcnt <= wcur + 1'b1;
        end
    end

    // ------------------------------------------------------------------ end of frame: limit for the next frame
    reg [2:0]  fin_st;
    reg        last6;
    reg [51:0] m41;
    reg [51:0] sh20;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            fin_st <= 3'd0; last6 <= 1'b0; fdone <= 1'b0; fsum_abs_e <= 40'd0; lim_used <= 12'd0;
            lim_n <= 12'd2048; m41 <= 52'd0; sh20 <= 52'd0;
        end else begin
            fdone <= 1'b0;
            last6 <= last5 & vb5;
            // fin_st 0: wait for the last pixel's write to be issued (last6), 1: *41, 2: >>20, 3: clamp+publish
            case (fin_st)
                3'd0: if (last6) fin_st <= 3'd1;
                3'd1: begin m41 <= acc * KLIM; fin_st <= 3'd2; end
                3'd2: begin sh20 <= m41 >> 20; fin_st <= 3'd3; end
                3'd3: begin
                    fsum_abs_e <= acc;
                    lim_used   <= lim_a;
                    lim_n <= (sh20 < {emin_a, 2'b00}) ? {emin_a, 2'b00} :
                             (sh20 > {emax_a, 2'b00}) ? {emax_a, 2'b00} : sh20[11:0];
                    fdone <= 1'b1;
                    fin_st <= 3'd0;
                end
                default: fin_st <= 3'd0;
            endcase
        end
    end
endmodule
