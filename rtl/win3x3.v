`timescale 1ns/1ps
// win3x3.v -- streaming 3x3 window generator on the tick grid (see tick_gen.v), border = edge replicate.
//
// One instance = one 3x3 stage. Input: one data word per grid tick (row-major, W+1 columns, the last column and the
// rows >= H are dummies whose data is ignored). Output: one 3x3 window per REAL pixel, centred on pixel (cr, cc),
// 3 clocks after the tick that delivered the window's bottom-right element.
//
// Latency ledger (clocks, tick spacing >= 2):
//   cycle n   : tick, din, sin presented; line-buffer read address = column
//   cycle n+1 : line-buffer data valid, column vector formed, write-back of this row into the line buffers
//   cycle n+2 : window assembled (replication muxes), registered
//   cycle n+3 : otick/ofirst/wvalid/cr/cc/win/sout valid         => LATENCY = 3
//
// Grid origin: this stage's own grid starts when the number of ticks seen since `first` equals ORG, so cascaded
// stages use ORG = k*(W+2) (the flat-tick delay each earlier window stage adds). `tick` must keep arriving until
// this stage's grid has finished: the producer (tick_gen EXTRA) provides the rows.
//
// Side information: SW bits that ride along with each data word and come out, aligned with the CENTRE pixel, on
// sout (used to carry NUC coefficients to the write-back stage without a second delay line).
//
// win bus order, MSB first, each DW bits:  NW N NE | W C E | SW S SE.
// Replication: row -1 := row 0, row H := row H-1, col -1 := col 0, col W := col W-1 (clamp coordinates).
module win3x3 #(
    parameter DW  = 16,
    parameter SW  = 1,
    parameter W   = 320,
    parameter H   = 240,
    parameter ORG = 0
) (
    input  wire              clk,
    input  wire              rst_n,
    input  wire              tick,
    input  wire              first,
    input  wire [DW-1:0]     din,
    input  wire [SW-1:0]     sin,
    output reg               otick,
    output reg               ofirst,
    output reg               wvalid,
    output reg  [8:0]        cr,
    output reg  [8:0]        cc,
    output reg  [9*DW-1:0]   win,
    output reg  [SW-1:0]     sout
);
    localparam LATENCY = 3;

    // ---- position of the current tick inside this stage's grid ----
    wire [8:0] c_now, r_now;
    wire       act;
    grid_ctr #(.W(W), .H(H), .ORG(ORG)) gpos (
        .clk(clk), .rst_n(rst_n), .tick(tick), .first(first), .c_now(c_now), .r_now(r_now), .act(act));

    // ---- stage 1: line-buffer read, pipeline the inputs ----
    reg              tick1, first1, act1;
    reg  [DW-1:0]    din1;
    reg  [SW-1:0]    sin1;
    reg  [8:0]       c1, r1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tick1 <= 1'b0; first1 <= 1'b0; act1 <= 1'b0;
            din1 <= {DW{1'b0}}; sin1 <= {SW{1'b0}}; c1 <= 9'd0; r1 <= 9'd0;
        end else begin
            tick1 <= tick; first1 <= first; act1 <= tick & act;
            din1 <= din; sin1 <= sin; c1 <= c_now; r1 <= r_now;
        end
    end

    wire [DW+SW-1:0] a1;                     // row r-1: {data, side}
    wire [DW-1:0]    a2;                     // row r-2: data
    ram_sdp #(.DW(DW + SW), .AW(9), .DEPTH(512)) lb1 (
        .clk(clk), .we(act1), .waddr(c1), .wdata({din1, sin1}), .raddr(c_now), .rdata(a1));
    ram_sdp #(.DW(DW), .AW(9), .DEPTH(512)) lb2 (
        .clk(clk), .we(act1), .waddr(c1), .wdata(a1[DW+SW-1:SW]), .raddr(c_now), .rdata(a2));

    // ---- stage 2: column shift registers ----
    reg [DW-1:0] t0, m0, b0, t1, m1, b1, t2, m2, b2;
    reg [SW-1:0] s0, s1;
    reg          tick2, first2, act2;
    reg [8:0]    c2, r2;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            t0 <= 0; m0 <= 0; b0 <= 0; t1 <= 0; m1 <= 0; b1 <= 0; t2 <= 0; m2 <= 0; b2 <= 0;
            s0 <= 0; s1 <= 0;
            tick2 <= 1'b0; first2 <= 1'b0; act2 <= 1'b0; c2 <= 9'd0; r2 <= 9'd0;
        end else begin
            tick2 <= tick1; first2 <= first1; act2 <= act1; c2 <= c1; r2 <= r1;
            if (act1) begin
                t2 <= t1; m2 <= m1; b2 <= b1;
                t1 <= t0; m1 <= m0; b1 <= b0; s1 <= s0;
                t0 <= a2; m0 <= a1[DW+SW-1:SW]; b0 <= din1; s0 <= a1[SW-1:0];
            end
        end
    end

    // ---- stage 3: replication muxes, register outputs ----
    wire top_rep = (r2 == 9'd1);             // centre row 0
    wire bot_rep = (r2 == H);                // centre row H-1
    wire lef_rep = (c2 == 9'd1);             // centre col 0
    wire rig_rep = (c2 == W);                // centre col W-1

    wire [DW-1:0] tL = top_rep ? m2 : t2, bL = bot_rep ? m2 : b2;
    wire [DW-1:0] tC = top_rep ? m1 : t1, bC = bot_rep ? m1 : b1;
    wire [DW-1:0] tR = top_rep ? m0 : t0, bR = bot_rep ? m0 : b0;

    wire [DW-1:0] w_nw = lef_rep ? tC : tL, w_n = tC, w_ne = rig_rep ? tC : tR;
    wire [DW-1:0] w_w  = lef_rep ? m1 : m2, w_c = m1, w_e  = rig_rep ? m1 : m0;
    wire [DW-1:0] w_sw = lef_rep ? bC : bL, w_s = bC, w_se = rig_rep ? bC : bR;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            otick <= 1'b0; ofirst <= 1'b0; wvalid <= 1'b0; cr <= 9'd0; cc <= 9'd0;
            win <= {9*DW{1'b0}}; sout <= {SW{1'b0}};
        end else begin
            otick  <= tick2;
            ofirst <= first2;
            wvalid <= act2 && (r2 >= 9'd1) && (c2 >= 9'd1);
            cr     <= r2 - 9'd1;
            cc     <= c2 - 9'd1;
            win    <= {w_nw, w_n, w_ne, w_w, w_c, w_e, w_sw, w_s, w_se};
            sout   <= s1;
        end
    end
endmodule
