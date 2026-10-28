`timescale 1ns/1ps
// thermal_sys_tb.v -- end-to-end simulation of the whole design (emulated sensor -> NUC -> detector -> boxes -> VGA)
// at production size 320x240 / 640x480. It dumps every active VGA pixel to a text file ("rrggbb" per line, a line "F"
// at each start of frame); scripts/check_vga.py compares the frames with the Python system model (model/display_model.py)
// pixel by pixel. At the end it reads the hardware latency counters through the CSR bus and prints them ("STAT ...").
//
// Settings are written over the host bus (Avalon, byte addresses, host_if.v) exactly as the JTAG viewer / HPS do it:
// csr_use=1 plus view / palette bits, DET_WARM=2.
// CAPTURE >= 0: at VGA frame CAPTURE the TB arms a frame capture (source CAPSRC), polls CAP until done, reads the frame
// index and all W*H/4 buffer words and writes them to CAPDUMP ("fid N" then one 8-digit word per line);
// scripts/check_capture.py compares them with the system model.
// Overrides: -P thermal_sys_tb.NFRAMES= .CTRL= .DUMP="file" .ROM="file" .CAPTURE= .CAPSRC= .CAPDUMP="file"
module thermal_sys_tb;
    parameter NFRAMES = 6;                       // VGA frames to simulate
    parameter [31:0] CTRL = 32'h0000_02BF;       // csr_use=1, view=2 (split), gray, preset 1, all enables on
    parameter DUMP = "work/vga_dump.txt";
    parameter ROM = "quartus/thermal/rom_bg.hex";
    parameter CAPTURE = -1;
    parameter CAPSRC = 0;
    parameter CAPDUMP = "work/cap_dump.txt";

    reg clk = 1'b0, rst_n = 1'b0;
    always #20 clk = ~clk;

    reg         av_write = 1'b0, av_read = 1'b0;
    reg  [18:0] av_address = 19'd0;
    reg  [31:0] av_writedata = 32'd0;
    wire [31:0] av_readdata;
    wire        av_readdatavalid;
    wire        hs_n, vs_n, de;
    wire [7:0]  r, g, b;
    wire        ready, motion, bad_seen, ovf, retime_err, gain;
    wire [31:0] frames, latf_min, latf_max;
    wire [7:0]  nobj;
    wire        pin_in, pin_flag;

    thermal_sys #(.W(320), .H(240), .AW(17), .ROM_FILE(ROM)) dut (
        .clk(clk), .rst_n(rst_n),
        .sw_nuc_en(1'b1), .sw_learn_en(1'b1), .sw_bp_en(1'b1), .sw_overlay(1'b1), .sw_noise_en(1'b1), .sw_iron(1'b0),
        .sw_preset(2'd1), .sw_view(2'd2), .key_coef_reset(1'b0), .key_frame_reset(1'b0),
        .av_address(av_address), .av_read(av_read), .av_write(av_write), .av_writedata(av_writedata),
        .av_readdata(av_readdata), .av_readdatavalid(av_readdatavalid),
        .vga_hs_n(hs_n), .vga_vs_n(vs_n), .vga_de(de), .vga_r(r), .vga_g(g), .vga_b(b),
        .st_ready(ready), .st_motion(motion), .st_bad_seen(bad_seen), .st_ovf(ovf), .st_retime_err(retime_err), .st_gain(gain),
        .st_frames(frames), .st_latf_min(latf_min), .st_latf_max(latf_max), .st_nobj(nobj),
        .pin_in_mark(pin_in), .pin_flag_mark(pin_flag));

    integer fd, frame_idx = -1, npix = 0, errors = 0;
    reg sof_q = 1'b0;

    // host bus: one transaction at a time (the JTAG master never has more than a few in flight)
    reg bus_lock = 1'b0;
    task av_wr;
        input [18:0] a; input [31:0] d;
        begin
            @(posedge clk); av_write <= 1'b1; av_address <= a; av_writedata <= d;
            @(posedge clk); av_write <= 1'b0;
        end
    endtask
    reg [31:0] got;
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
    task bus_write;                            // CSR word address
        input [7:0] a; input [31:0] d;
        begin av_wr({8'd0, a, 2'b00}, d); end
    endtask
    task bus_read;
        input [7:0] a;
        begin av_rd({8'd0, a, 2'b00}); end
    endtask

    // frame capture (runs while the VGA dump goes on)
    integer cfd, ci, polls;
    reg cap_finished = 1'b0;
    initial begin
        if (CAPTURE >= 0) begin
            wait (frame_idx == CAPTURE);
            wait (!bus_lock); bus_lock = 1'b1;
            bus_write(8'h0E, 32'h100 | CAPSRC);
            polls = 0;
            got = 32'd0;
            while (!got[17] && polls < 2000) begin
                repeat (500) @(posedge clk);
                bus_read(8'h0E); polls = polls + 1;
            end
            if (!got[17]) begin errors = errors + 1; $display("FAIL: capture never finished (CAP=%h)", got); end
            else if (got[0] !== CAPSRC[0]) begin errors = errors + 1; $display("FAIL: CAP source bit %b", got[0]); end
            bus_read(8'h0F);
            cfd = $fopen(CAPDUMP, "w");
            $fwrite(cfd, "fid %0d\n", got);
            for (ci = 0; ci < 320 * 240 / 4; ci = ci + 1) begin
                av_rd(19'h20000 + 4 * ci);
                $fwrite(cfd, "%08x\n", got);
            end
            $fclose(cfd);
            $display("CAP frame captured (source %0d) and read back over the host bus", CAPSRC);
            bus_lock = 1'b0;
        end
        cap_finished = 1'b1;
    end

    initial begin
        fd = $fopen(DUMP, "w");
        #200 rst_n = 1'b1;
        repeat (20) @(posedge clk);
        bus_lock = 1'b1;
        bus_write(8'h07, 32'd2);                  // DET_WARM = 2 frames
        bus_write(8'h01, CTRL);                   // csr_use=1 and the view / palette settings
        bus_lock = 1'b0;
        wait (frame_idx == NFRAMES);
        wait (cap_finished);
        repeat (50) @(posedge clk);
        $fclose(fd);
        // latency counters over all frames
        bus_read(8'h10); $display("STAT status=%h", got);
        bus_read(8'h11); $display("STAT frames=%0d", got);
        bus_read(8'h1E); $display("STAT latp_min=%0d", got);
        bus_read(8'h1F); $display("STAT latp_max=%0d", got);
        bus_read(8'h20); $display("STAT latf_min=%0d", got);
        bus_read(8'h21); $display("STAT latf_max=%0d", got);
        bus_read(8'h22); $display("STAT lat_n=%0d", got);
        bus_read(8'h12); $display("STAT boxinfo=%h", got);
        bus_read(8'h00); if (got !== 32'h7A110001) begin errors = errors + 1; $display("MISMATCH id %h", got); end
        if (retime_err) begin errors = errors + 1; $display("FAIL: retimer overrun flag set"); end
        if (npix != 307200 * NFRAMES) begin errors = errors + 1; $display("FAIL: dumped %0d active pixels, expected %0d", npix, 307200 * NFRAMES); end
        if (errors == 0) $display("RESULT: PASS (system ran %0d VGA frames; pixel compare is done by scripts/check_vga.py)", NFRAMES);
        else             $display("RESULT: FAIL (errors=%0d)", errors);
        $finish;
    end

    always @(posedge clk) begin
        if (rst_n) begin
            if (dut.u_vt.sof && !sof_q) begin
                frame_idx = frame_idx + 1;
                if (frame_idx <= NFRAMES) $fwrite(fd, "F\n");
            end
            sof_q <= dut.u_vt.sof;
            if (de && frame_idx >= 0 && frame_idx < NFRAMES) begin
                $fwrite(fd, "%02x%02x%02x\n", r, g, b);
                npix = npix + 1;
            end
        end
    end

    initial begin
        #(40 * 420000 * (NFRAMES + 3));
        $display("RESULT: FAIL (timeout)");
        $finish;
    end
endmodule
