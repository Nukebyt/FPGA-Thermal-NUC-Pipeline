`timescale 1ns/1ps
// row_retimer.v -- re-times a 1-bit raster stream into one burst per row, with a guaranteed idle gap between rows.
//
// Why it exists: the mask leaves the window chain offset by k*(W+2) flat ticks, so the big idle gap of the tick
// grid falls in the MIDDLE of a mask row while real row boundaries are only a couple of ticks apart. The box
// extractor needs >= 40 idle clocks after every row (its end-of-line scan), so it must not see that stream directly.
//
// Behaviour: pixels are written into a 2-bank row buffer as they arrive. When the last pixel of a row (cc = W-1)
// arrives, that row is replayed 4 clocks later at exactly one pixel every 2 clocks, in the same raster order and with
// the same (row, col) labels. The pixel (r, c) of the output is presented RT_LAT(c) = 6 + 2c clocks after the
// last pixel of row r arrived (measured by the testbench), so the whole thing has a fixed latency that does not depend on the input timing.
//
// Assumption (checked, never silent): a row must be fully replayed before the next row completes
// (2W + 4 clocks < one tick-row period), and the bank being replayed must not be overwritten. If either is
// violated `err` latches high (sticky until reset).
module row_retimer #(
    parameter W = 320,
    parameter H = 240
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       ivalid,
    input  wire       ibit,
    input  wire [8:0] icr,
    input  wire [8:0] icc,
    output reg        ovalid,
    output reg        obit,
    output reg  [8:0] ocr,
    output reg  [8:0] occ,
    output reg        err
);
    // ---- write side ----
    wire       rdbit;
    reg  [9:0] raddr;
    ram_sdp #(.DW(1), .AW(10), .DEPTH(1024)) rbuf (
        .clk(clk), .we(ivalid), .waddr({icr[0], icc}), .wdata(ibit), .raddr(raddr), .rdata(rdbit));

    reg        row_done;
    reg        row_bank;
    reg [8:0]  row_idx;
    reg        active;
    reg        rd_bank;
    reg [8:0]  rd_row;
    reg [9:0]  rd_c;               // next column to issue
    reg        ph;                 // 0: issue read, 1: wait
    reg        v1, v2;             // v1: raddr was registered last cycle; v2: RAM data is valid this cycle
    reg [8:0]  r1, c1, r2, c2;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            row_done <= 1'b0; row_bank <= 1'b0; row_idx <= 9'd0; active <= 1'b0; rd_bank <= 1'b0; rd_row <= 9'd0;
            rd_c <= 10'd0; ph <= 1'b0; v1 <= 1'b0; v2 <= 1'b0; r1 <= 9'd0; c1 <= 9'd0; r2 <= 9'd0; c2 <= 9'd0; raddr <= 10'd0;
            ovalid <= 1'b0; obit <= 1'b0; ocr <= 9'd0; occ <= 9'd0; err <= 1'b0;
        end else begin
            row_done <= ivalid && (icc == W - 1);
            if (ivalid && (icc == W - 1)) begin row_bank <= icr[0]; row_idx <= icr; end

            // overrun checks
            if (row_done && active) err <= 1'b1;                          // new row done while still replaying
            if (ivalid && active && (icr[0] == rd_bank)) err <= 1'b1;     // writing the bank being replayed

            // ---- replay engine: start 1 clock after row_done is seen (i.e. 2 clocks after the last pixel) ----
            v1 <= 1'b0;
            if (row_done) begin
                active <= 1'b1; rd_bank <= row_bank; rd_row <= row_idx; rd_c <= 10'd0; ph <= 1'b0;
            end else if (active) begin
                ph <= ~ph;
                if (!ph) begin
                    raddr <= {rd_bank, rd_c[8:0]};
                    v1 <= 1'b1; r1 <= rd_row; c1 <= rd_c[8:0];
                    rd_c <= rd_c + 10'd1;
                    if (rd_c == W - 1) active <= 1'b0;
                end
            end
            // raddr (registered) -> RAM captures it -> rdbit valid one cycle after v1
            v2 <= v1; r2 <= r1; c2 <= c1;
            ovalid <= v2; obit <= rdbit; ocr <= r2; occ <= c2;
        end
    end
endmodule
