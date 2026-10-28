`timescale 1ns/1ps
// grid_ctr.v -- position of the current tick inside one stage's grid (combinational outputs).
//
// The tick stream (tick_gen.v) is a flat sequence; this stage's own grid of (W+1) columns x (H+1+...) rows starts
// when the number of ticks seen since `first` equals ORG. Outputs describe the tick that is present on `tick` NOW:
//   c_now, r_now : column / row in this stage's grid (0..W, 0..H+)
//   act          : the tick belongs to this stage's grid (past ORG and row <= H)
// Shared by win3x3 and the NUC front end so the two can never disagree about where a tick is.
module grid_ctr #(
    parameter W   = 320,
    parameter H   = 240,
    parameter ORG = 0
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        tick,
    input  wire        first,
    output wire [8:0]  c_now,
    output wire [8:0]  r_now,
    output wire        act
);
    reg  [19:0] tc;                          // ticks seen since first (index of the next tick)
    wire [19:0] cur_tc   = first ? 20'd0 : tc;
    wire        at_org   = (cur_tc == ORG);
    wire        past_org = (cur_tc >= ORG);
    reg  [8:0]  c_nx, r_nx;
    assign c_now = at_org ? 9'd0 : c_nx;
    assign r_now = at_org ? 9'd0 : r_nx;
    assign act   = past_org && (r_now <= H);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tc <= 20'd0; c_nx <= 9'd0; r_nx <= 9'd0;
        end else if (tick) begin
            tc <= cur_tc + 20'd1;
            if (past_org) begin
                c_nx <= (c_now == W) ? 9'd0 : c_now + 9'd1;
                r_nx <= (c_now == W) ? r_now + 9'd1 : r_now;
            end
        end
    end
endmodule
