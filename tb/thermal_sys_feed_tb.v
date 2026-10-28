`timescale 1ns/1ps
// thermal_sys_feed_tb.v -- the frame feeder protocol (roadmap 3b, sw/frame_feeder.c) against the whole design, FEED = 1.
//
// The TB plays the ARM through the host bus. It (1) writes frame A into the scene frame store while the design is still
// in reset, (2) captures a source frame (it must be A), (3) waits until the scan has just read row 0 of some frame k0,
// arms a second capture and rewrites the whole frame store with frame B row by row, each row only after the scan has
// read it (FEED_ROW > k0*H + r) and counting a "deadline miss" if the scan has already come round to it again
// (FEED_ROW >= (k0+1)*H + r). The second capture is therefore of frame k0+1, the frame in which the content changes:
// it must be B throughout, not a mix. scripts/check_feed.py compares both captures with the system model.
// Settings: noise off, objects off, NUC on: the raw capture (source 1) is the clean scene, tone mapped.
// Overrides: -P thermal_sys_feed_tb.DIR="work/feed"   (A.hex, B.hex in, cap1.txt cap2.txt info.txt out)
module thermal_sys_feed_tb;
    parameter DIR = "work/feed";
    parameter [31:0] CTRL = 32'h0000_028F;       // csr_use, view split, gray, NUC learn bp overlay on, noise OFF
    localparam W = 320, H = 240, NW = W * H / 4, WPR = W / 4;

    reg clk = 1'b0, rst_n = 1'b0;
    always #20 clk = ~clk;

    reg         av_write = 1'b0, av_read = 1'b0;
    reg  [18:0] av_address = 19'd0;
    reg  [31:0] av_writedata = 32'd0;
    wire [31:0] av_readdata;
    wire        av_readdatavalid;
    wire        hs_n, vs_n, de;
    wire [7:0]  r, g, b;
    wire        ready, motion, bad_seen, ovf, retime_err, gain, learn;
    wire [31:0] frames, latf_min, latf_max;
    wire [7:0]  nobj;
    wire        pin_in, pin_flag;

    thermal_sys #(.W(W), .H(H), .AW(17), .BUILD(16'h0006), .FEED(1)) dut (
        .clk(clk), .rst_n(rst_n),
        .sw_nuc_en(1'b1), .sw_learn_en(1'b1), .sw_bp_en(1'b1), .sw_overlay(1'b1), .sw_noise_en(1'b1), .sw_iron(1'b0),
        .sw_preset(2'd1), .sw_view(2'd2), .key_coef_reset(1'b0), .key_frame_reset(1'b0),
        .av_address(av_address), .av_read(av_read), .av_write(av_write), .av_writedata(av_writedata),
        .av_readdata(av_readdata), .av_readdatavalid(av_readdatavalid),
        .vga_hs_n(hs_n), .vga_vs_n(vs_n), .vga_de(de), .vga_r(r), .vga_g(g), .vga_b(b),
        .st_ready(ready), .st_motion(motion), .st_bad_seen(bad_seen), .st_ovf(ovf), .st_retime_err(retime_err), .st_gain(gain),
        .st_learn(learn), .st_frames(frames), .st_latf_min(latf_min), .st_latf_max(latf_max), .st_nobj(nobj),
        .pin_in_mark(pin_in), .pin_flag_mark(pin_flag));

    integer errors = 0;
    reg [31:0] got;
    task av_wr;
        input [18:0] a; input [31:0] d;
        begin
            @(posedge clk); av_write <= 1'b1; av_address <= a; av_writedata <= d;
            @(posedge clk); av_write <= 1'b0;
        end
    endtask
    task av_rd;
        input [18:0] a;
        integer k;
        begin
            @(posedge clk); av_read <= 1'b1; av_address <= a;
            @(posedge clk); av_read <= 1'b0;
            k = 0;
            while (!av_readdatavalid && k < 10) begin @(posedge clk); k = k + 1; end
            if (!av_readdatavalid) begin errors = errors + 1; $display("FAIL: no readdatavalid for address %h", a); end
            #1 got = av_readdata;
        end
    endtask
    task bus_write; input [7:0] a; input [31:0] d; begin av_wr({8'd0, a, 2'b00}, d); end endtask
    task bus_read;  input [7:0] a;                 begin av_rd({8'd0, a, 2'b00}); end endtask

    reg [31:0] wa [0:NW-1];
    reg [31:0] wb [0:NW-1];
    integer i, fd, polls, row, w, k0, torn, rows;
    reg [8*200-1:0] fname;

    // arm a raw capture (source 1), wait until done, read the frame index and all words into `file`
    task capture_to;
        input [8*200-1:0] file;
        input integer expect_fid;                 // -1: do not check
        integer ci;
        begin
            polls = 0; got = 32'd0;
            while (!got[17] && polls < 4000) begin
                repeat (500) @(posedge clk);
                bus_read(8'h0E); polls = polls + 1;
            end
            if (!got[17]) begin errors = errors + 1; $display("FAIL: capture never finished (CAP=%h)", got); end
            bus_read(8'h0F);
            if (expect_fid >= 0 && got !== expect_fid) begin
                errors = errors + 1; $display("MISMATCH capture frame index %0d expected %0d", got, expect_fid);
            end
            fd = $fopen(file, "w");
            $fwrite(fd, "fid %0d\n", got);
            for (ci = 0; ci < NW; ci = ci + 1) begin
                av_rd(19'h20000 + 4 * ci);
                $fwrite(fd, "%08x\n", got);
            end
            $fclose(fd);
        end
    endtask

    initial begin
        $sformat(fname, "%0s/A.hex", DIR); $readmemh(fname, wa);
        $sformat(fname, "%0s/B.hex", DIR); $readmemh(fname, wb);
        repeat (10) @(posedge clk);
        // (1) frame A into the frame store while the design is held in reset: frame 0 is A from its first pixel
        for (i = 0; i < NW; i = i + 1) av_wr(19'h40000 + 4 * i, wa[i]);
        #200 rst_n = 1'b1;
        repeat (20) @(posedge clk);
        bus_read(8'h00); if (got !== 32'h7A110006) begin errors = errors + 1; $display("MISMATCH id %h", got); end
        bus_read(8'h23); if (got !== 32'd1) begin errors = errors + 1; $display("MISMATCH CAPS %h", got); end
        bus_write(8'h07, 32'd2);                  // DET_WARM = 2 frames
        bus_write(8'h24, 32'd0);                  // objects off
        bus_write(8'h01, CTRL);
        // (2) capture of a frame while A is in the store
        bus_write(8'h0E, 32'h101);
        capture_to({DIR, "/cap1.txt"}, -1);
        // (3) wait for the scan to have just read row 0 of a frame
        bus_read(8'h25);
        while (got % H != 1) begin repeat (10) @(posedge clk); bus_read(8'h25); end
        k0 = got / H;
        torn = 0;
        for (row = 0; row < H; row = row + 1) begin
            // The capture follows the display path, which trails the scan by about a row: armed a few rows into frame k0 (once
            // the output of frame k0 has started) it takes the next whole frame, k0 + 1, the one in which the content changes.
            if (row == 6) bus_write(8'h0E, 32'h101);
            bus_read(8'h25);
            while (got <= k0 * H + row) bus_read(8'h25);
            if (got >= (k0 + 1) * H + row) begin torn = torn + 1; if (torn < 4) $display("deadline miss at row %0d (FEED_ROW %0d)", row, got); end
            for (w = 0; w < WPR; w = w + 1) av_wr(19'h40000 + 4 * (row * WPR + w), wb[row * WPR + w]);
        end
        capture_to({DIR, "/cap2.txt"}, k0 + 1);
        fd = $fopen({DIR, "/info.txt"}, "w");
        $fwrite(fd, "k0 %0d torn %0d\n", k0, torn);
        $fclose(fd);
        $display("FEED chase started after row 0 of frame %0d, %0d deadline misses", k0, torn);
        if (retime_err) begin errors = errors + 1; $display("FAIL: retimer overrun flag set"); end
        if (errors == 0) $display("RESULT: PASS (frame store switched A -> B in frame %0d; the comparison with the model is scripts/check_feed.py)", k0 + 1);
        else             $display("RESULT: FAIL (errors=%0d)", errors);
        $finish;
    end

    initial begin
        #(40 * 420000 * 30);
        $display("RESULT: FAIL (timeout)");
        $finish;
    end
endmodule
