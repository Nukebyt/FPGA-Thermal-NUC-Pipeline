`timescale 1ns/1ps
// thermal_top.v -- DE10-Standard top level without the HPS: thermal_board + a JTAG-to-Avalon master (Platform Designer system
// quartus/ip/jtag_host) on the host bus, so a laptop on the USB-Blaster can read/write the CSRs and read captured frames
// (host/viewer.py) without a VGA monitor. See thermal_board.v for switches, keys, LEDs and the GPIO markers.
module thermal_top #(
    parameter ROM_FILE = "rom_bg.hex",
    parameter [15:0] BUILD = 16'h0001,
    parameter FEED = 0
) (
    input  wire        CLOCK_50,
    input  wire [3:0]  KEY,
    input  wire [9:0]  SW,
    output wire [9:0]  LEDR,
    output wire [6:0]  HEX0, HEX1, HEX2, HEX3, HEX4, HEX5,
    output wire        VGA_CLK,
    output wire        VGA_HS,
    output wire        VGA_VS,
    output wire [7:0]  VGA_R,
    output wire [7:0]  VGA_G,
    output wire [7:0]  VGA_B,
    output wire        VGA_BLANK_N,
    output wire        VGA_SYNC_N,
    output wire [1:0]  GPIO
);
    wire        clk25, rst_n;
    wire [18:0] h_addr;
    wire        h_read, h_write, h_rvalid;
    wire [31:0] h_wdata, h_rdata;
    thermal_board #(.ROM_FILE(ROM_FILE), .BUILD(BUILD), .FEED(FEED)) u_board (
        .CLOCK_50(CLOCK_50), .KEY(KEY), .SW(SW), .LEDR(LEDR), .HEX0(HEX0), .HEX1(HEX1), .HEX2(HEX2), .HEX3(HEX3), .HEX4(HEX4), .HEX5(HEX5),
        .VGA_CLK(VGA_CLK), .VGA_HS(VGA_HS), .VGA_VS(VGA_VS), .VGA_R(VGA_R), .VGA_G(VGA_G), .VGA_B(VGA_B),
        .VGA_BLANK_N(VGA_BLANK_N), .VGA_SYNC_N(VGA_SYNC_N), .GPIO(GPIO),
        .clk25(clk25), .rst_n(rst_n), .h_addr(h_addr), .h_read(h_read), .h_write(h_write), .h_wdata(h_wdata),
        .h_rdata(h_rdata), .h_rvalid(h_rvalid));
    jtag_host u_jtag (
        .clk_clk(clk25), .reset_reset_n(rst_n),
        .host_waitrequest(1'b0), .host_readdata(h_rdata), .host_readdatavalid(h_rvalid),
        .host_burstcount(), .host_writedata(h_wdata), .host_address(h_addr), .host_write(h_write), .host_read(h_read),
        .host_byteenable(), .host_debugaccess());
endmodule
