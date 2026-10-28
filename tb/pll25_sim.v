`timescale 1ns/1ps
// pll25_sim.v -- simulation stand-in for the Quartus altera_pll "pll25" (50 MHz -> 25 MHz, with `locked`).
// Same ports as quartus/*/ip/pll25/pll25.v. Locks 20 input clocks after refclk starts, like a real PLL taking time.
module pll25 (
    input  wire refclk,
    input  wire rst,
    output reg  outclk_0,
    output reg  locked
);
    integer n;
    initial begin outclk_0 = 1'b0; locked = 1'b0; n = 0; end
    always @(posedge refclk) begin
        outclk_0 <= ~outclk_0;
        if (rst) begin n <= 0; locked <= 1'b0; end
        else if (n < 20) n <= n + 1;
        else locked <= 1'b1;
    end
endmodule
