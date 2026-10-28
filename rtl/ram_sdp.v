`timescale 1ns/1ps
// ram_sdp.v -- simple dual-port RAM, one write port, one registered read port, one clock.
//
// Standalone module on purpose (checklist 1.1): RAM that is inferred inline inside a generate body or with a
// runtime byte-enable loop silently becomes flip-flops on Quartus 21.1. The read is REGISTERED (a combinational
// read is not recognised as RAM). Latency: rdata is the content as it was at the clock edge that captured raddr,
// i.e. one clock after raddr is presented. Read-during-write of the SAME address returns the OLD data in
// simulation; the synthesised M10K is told "no_rw_check", so callers must never depend on it (every user
// below writes an address a whole row/frame after it reads it).
module ram_sdp #(
    parameter DW    = 8,
    parameter AW    = 9,
    parameter DEPTH = 512,
    parameter ZERO_INIT = 0         // 1: contents start as zeros (power-up value of a frame store nobody has written yet)
) (
    input  wire          clk,
    input  wire          we,
    input  wire [AW-1:0] waddr,
    input  wire [DW-1:0] wdata,
    input  wire [AW-1:0] raddr,
    output reg  [DW-1:0] rdata
);
    // max_depth = 1024: 76,800-word memories map as 75 x 1K deep, width in 10-bit slices (no depth waste);
    // without it Quartus 21.1 packed this design into 546 of 553 M10K (bug log #13).
    (* ramstyle = "M10K, no_rw_check", max_depth = 1024 *) reg [DW-1:0] mem [0:DEPTH-1];

    // power-up contents: nested so that no loop exceeds Quartus' 5000-iteration limit for synthesis loops
    integer zi, zj;
    initial if (ZERO_INIT != 0)
        for (zi = 0; zi < (DEPTH + 127) / 128; zi = zi + 1)
            for (zj = 0; zj < 128; zj = zj + 1)
                if (zi * 128 + zj < DEPTH) mem[zi * 128 + zj] = {DW{1'b0}};

    always @(posedge clk) begin
        if (we) mem[waddr] <= wdata;
        rdata <= mem[raddr];
    end
endmodule
