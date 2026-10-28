`timescale 1ns/1ps
// scene_buf.v -- host-written 8-bit frame store that replaces the sensor emulator's background ROM (FEED builds).
//
// One frame of W*H bytes, raster order, 4 pixels per 32-bit word (little endian), written through the host bus
// (host_if feed region) and read by the emulator's scan at pixel rate. There is NO double buffer (the RAM budget
// does not allow one): the writer instead "chases" the reader. `rows_read` counts the source rows the scan has read
// since reset, so row r of the frame in flight is safe to overwrite as soon as rows_read has passed it, and must be
// rewritten before the scan reaches row r again, one frame time later. A writer that stays between the two limits
// never tears a frame (sw/frame_feeder.c does exactly that).
//
// Scan side: `saddr` is the pixel index (raster order); the byte is valid one clock later, like rom_sp. Pixels past
// the end of the frame (the emulator's dummy ticks) read word 0 so the output never turns X.
module scene_buf #(
    parameter NW = 19200                 // words = ceil(W*H / 4)
) (
    input  wire        clk,
    input  wire        rst_n,
    // scan side
    input  wire [16:0] saddr,
    output wire [7:0]  sq,
    input  wire        row_done,         // pulse: the last pixel of a source row is being read this clock
    output reg  [31:0] rows_read,
    // host write side
    input  wire        hw_we,
    input  wire [14:0] hw_addr,
    input  wire [31:0] hw_data
);
    wire [14:0] wa = saddr[16:2];
    wire [14:0] ra = (wa >= NW) ? 15'd0 : wa;
    wire [31:0] q;
    ram_sdp #(.DW(32), .AW(15), .DEPTH(NW), .ZERO_INIT(1)) buf_i (
        .clk(clk), .we(hw_we), .waddr(hw_addr), .wdata(hw_data), .raddr(ra), .rdata(q));

    reg [1:0] sel;
    always @(posedge clk) sel <= saddr[1:0];
    assign sq = (sel == 2'd0) ? q[7:0] : (sel == 2'd1) ? q[15:8] : (sel == 2'd2) ? q[23:16] : q[31:24];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) rows_read <= 32'd0;
        else if (row_done) rows_read <= rows_read + 32'd1;
    end
endmodule
