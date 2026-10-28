`timescale 1ns/1ps
// frame_cap.v -- single-frame capture of the 8-bit display stream for the JTAG viewer (no VGA monitor needed).
//
// A host write arms the capture; the next whole frame of the selected stream (0 corrected, 1 raw; the same tone-mapped
// 8-bit values the VGA output would show) is stored, 4 pixels per 32-bit word, pixel (r,c) in byte (r*W+c)%4 of word
// (r*W+c)/4 (little endian). The buffer is then stable until the next arm, so the host can read it at JTAG speed.
// Pixels arrive in raster order (disp_path write side), one per pixel tick; W*H must be a multiple of 4.
// fid counts frames seen since reset (0-based index of the frame whose first pixel arrives); cap_fid is the fid of
// the last captured frame.
module frame_cap #(
    parameter W = 320,
    parameter H = 240,
    parameter AW = 15                   // word address bits (W*H/4 <= 2**AW)
) (
    input  wire          clk,
    input  wire          rst_n,
    // pixel stream (disp_path write side)
    input  wire          pv,            // a pixel this clock
    input  wire          pfirst,        // ... and it is pixel (0,0)
    input  wire [7:0]    pc8,           // corrected, tone-mapped
    input  wire [7:0]    pr8,           // raw, tone-mapped
    // control
    input  wire          arm,           // 1-clock pulse: capture the next whole frame
    input  wire          src,           // sampled at arm: 0 corrected, 1 raw
    output wire          busy,          // armed or capturing
    output reg           done,          // a complete frame is in the buffer (cleared by arm)
    output reg  [31:0]   cap_fid,
    // read port (registered, 1 clock)
    input  wire [AW-1:0] raddr,
    output wire [31:0]   rdata
);
    localparam N = W * H;
    localparam NW = N / 4;

    reg        armed, cap, src_a;
    reg [31:0] fid;
    reg [16:0] cnt;                     // pixel index within the captured frame
    reg [23:0] sh;                      // the three previous pixels of the current word
    reg        we;
    reg [AW-1:0] wa;
    reg [31:0] wd;

    wire start = pv && pfirst && armed;
    wire take  = pv && (cap || start);
    wire [7:0] px = src_a ? pr8 : pc8;
    wire [16:0] idx = start ? 17'd0 : cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            armed <= 1'b0; cap <= 1'b0; src_a <= 1'b0; done <= 1'b0; fid <= 32'd0; cap_fid <= 32'd0;
            cnt <= 17'd0; sh <= 24'd0; we <= 1'b0; wa <= {AW{1'b0}}; wd <= 32'd0;
        end else begin
            we <= 1'b0;
            if (pv && pfirst) fid <= fid + 32'd1;
            if (arm) begin                  // also restarts a capture in progress
                armed <= 1'b1; cap <= 1'b0; done <= 1'b0; src_a <= src;
            end else if (start) begin
                armed <= 1'b0; cap <= 1'b1; cap_fid <= fid;
            end
            if (take && !arm) begin
                sh <= {px, sh[23:8]};
                if (idx[1:0] == 2'd3) begin
                    we <= 1'b1; wa <= idx[AW+1:2]; wd <= {px, sh};
                end
                cnt <= idx + 17'd1;
                if (idx == N - 1) begin
                    cap <= 1'b0; done <= 1'b1;
                end
            end
        end
    end
    assign busy = armed | cap;

    ram_sdp #(.DW(32), .AW(AW), .DEPTH(NW)) buf_i (
        .clk(clk), .we(we), .waddr(wa), .wdata(wd), .raddr(raddr), .rdata(rdata));
endmodule
