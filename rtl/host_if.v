`timescale 1ns/1ps
// host_if.v -- Avalon-MM slave (byte addresses, 32-bit, pipelined reads with readdatavalid, no waitrequest) in front of
// the CSR block, the frame-capture buffer and the scene feed buffer. Driven by the JTAG-to-Avalon master
// (quartus/ip/jtag_host) and by the HPS lightweight bridge (quartus/ip/hps_sys, sw/frame_feeder.c).
//
//   0x00000 + 4*a   csr_regs word a (a = 0..255)                       read / write
//   0x20000 + 4*k   capture buffer word k (pixels 4k..4k+3, LE)         read only (writes ignored)
//   0x40000 + 4*k   scene feed buffer word k (pixels 4k..4k+3, LE)      write only (reads return 0)
// The three regions are fully decoded on address bits [18:17] (00 / 01 / 1x) so none can alias into another.
//
// Read latency: readdatavalid 2 clocks after read (both targets have a registered read; one output register).
module host_if #(
    parameter FAW = 15                      // buffer word address bits
) (
    input  wire           clk,
    input  wire           rst_n,
    input  wire [18:0]    av_address,
    input  wire           av_read,
    input  wire           av_write,
    input  wire [31:0]    av_writedata,
    output reg  [31:0]    av_readdata,
    output reg            av_readdatavalid,
    // csr_regs bus
    output wire           csr_wr,
    output wire           csr_rd,
    output wire [7:0]     csr_addr,
    output wire [31:0]    csr_wdata,
    input  wire [31:0]    csr_rdata,
    // capture buffer read port
    output wire [FAW-1:0] fb_raddr,
    input  wire [31:0]    fb_rdata,
    // scene feed buffer write port
    output wire           fw_we,
    output wire [FAW-1:0] fw_addr,
    output wire [31:0]    fw_data
);
    wire is_feed = av_address[18];
    wire is_cap  = ~av_address[18] &  av_address[17];
    wire is_csr  = ~av_address[18] & ~av_address[17];
    assign csr_wr    = av_write & is_csr;
    assign csr_rd    = av_read & is_csr;
    assign csr_addr  = av_address[9:2];
    assign csr_wdata = av_writedata;
    assign fb_raddr  = av_address[FAW+1:2];
    assign fw_we     = av_write & is_feed;
    assign fw_addr   = av_address[FAW+1:2];
    assign fw_data   = av_writedata;

    reg rd1, cap1, csr1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            rd1 <= 1'b0; cap1 <= 1'b0; csr1 <= 1'b0; av_readdata <= 32'd0; av_readdatavalid <= 1'b0;
        end else begin
            rd1 <= av_read; cap1 <= is_cap; csr1 <= is_csr;
            av_readdatavalid <= rd1;
            if (rd1) av_readdata <= cap1 ? fb_rdata : csr1 ? csr_rdata : 32'd0;
        end
    end
endmodule
