`timescale 1ns/1ps
// rom_sp.v -- single-port ROM, registered read, contents from a hex file ($readmemh).
// Standalone module (checklist 1.1). The hex file is a synthesis input: it is committed and its generator is named in
// its first line (checklist 7.1). Quartus resolves INIT_FILE relative to the project directory.
module rom_sp #(
    parameter DW        = 8,
    parameter AW        = 17,
    parameter DEPTH     = 76800,
    parameter INIT_FILE = "rom_bg.hex"
) (
    input  wire          clk,
    input  wire [AW-1:0] raddr,
    output reg  [DW-1:0] rdata
);
    (* ramstyle = "M10K", max_depth = 1024 *) reg [DW-1:0] mem [0:DEPTH-1];
    initial $readmemh(INIT_FILE, mem);
    always @(posedge clk) rdata <= mem[raddr];
endmodule
