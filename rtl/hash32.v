`timescale 1ns/1ps
// hash32.v -- lowbias32 integer hash, fully pipelined (one multiply per stage). Twin of model/sensor_emu.hash32().
//   x ^= x >> 16; x *= 0x7feb352d; x ^= x >> 15; x *= 0x846ca68b; x ^= x >> 16
// Latency: 5 clocks, one result per clock.
module hash32 (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [31:0] x,
    output reg  [31:0] y
);
    localparam LATENCY = 5;
    reg [31:0] s1, s2, s3, s4;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s1 <= 32'd0; s2 <= 32'd0; s3 <= 32'd0; s4 <= 32'd0; y <= 32'd0;
        end else begin
            s1 <= x ^ (x >> 16);
            s2 <= s1 * 32'h7FEB352D;
            s3 <= s2 ^ (s2 >> 15);
            s4 <= s3 * 32'h846CA68B;
            y  <= s4 ^ (s4 >> 16);
        end
    end
endmodule
