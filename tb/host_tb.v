`timescale 1ns/1ps
// host_tb.v -- host bus path: host_if (Avalon slave) + csr_regs + frame_cap + scene_buf, small frame (W x H).
// Verdict: "RESULT: PASS" / "RESULT: FAIL". Expectations are computed by the TB from the stimulus it drives.
//
//   * CSR read/write through byte addresses (word a at 4a), read latency = readdatavalid, writes to the buffer
//     region ignored, back-to-back (pipelined) reads of CSR then buffer return in order with the right data
//   * capture: arming in the middle of a frame captures the NEXT whole frame; the frame index (fid) is reported;
//     source select corrected / raw (latched at arm: changing it mid-capture has no effect); re-arming during a
//     capture restarts it (tried at 4 clock phases, so the arm lands on clocks with and without a pixel);
//     buffer stable after done
//   * pixel stream with random gaps (pv not every clock), as disp_path produces it
// Pixel values are a function of (frame, index): c8 = (f*37 + i*5) & 255, r8 = (f*11 + i*3 + 128) & 255.
module host_tb;
    parameter W = 12;
    parameter H = 6;
    localparam N = W * H;

    reg clk = 1'b0, rst_n = 1'b0;
    always #20 clk = ~clk;

    reg  [18:0] av_address = 19'd0;
    reg         av_read = 1'b0, av_write = 1'b0;
    reg  [31:0] av_writedata = 32'd0;
    wire [31:0] av_readdata;
    wire        av_readdatavalid;
    wire        csr_wr, csr_rd;
    wire [7:0]  csr_addr;
    wire [31:0] csr_wdata, csr_rdata, fb_rdata, cap_fid;
    wire [14:0] fb_raddr;
    wire        cap_arm, cap_src, cap_busy, cap_done;
    wire        fw_we;
    wire [14:0] fw_addr;
    wire [31:0] fw_data, feed_rows;
    wire        obj_en;
    reg  [16:0] saddr = 17'd0;
    reg         row_done = 1'b0;
    wire [7:0]  sq;

    host_if #(.FAW(15)) u_host (
        .clk(clk), .rst_n(rst_n), .av_address(av_address), .av_read(av_read), .av_write(av_write),
        .av_writedata(av_writedata), .av_readdata(av_readdata), .av_readdatavalid(av_readdatavalid),
        .csr_wr(csr_wr), .csr_rd(csr_rd), .csr_addr(csr_addr), .csr_wdata(csr_wdata), .csr_rdata(csr_rdata),
        .fb_raddr(fb_raddr), .fb_rdata(fb_rdata), .fw_we(fw_we), .fw_addr(fw_addr), .fw_data(fw_data));

    scene_buf #(.NW((W * H + 3) / 4)) u_scene (
        .clk(clk), .rst_n(rst_n), .saddr(saddr), .sq(sq), .row_done(row_done), .rows_read(feed_rows),
        .hw_we(fw_we), .hw_addr(fw_addr), .hw_data(fw_data));

    csr_regs #(.BUILD(16'h0042), .FEED(1)) u_csr (
        .clk(clk), .rst_n(rst_n), .wr(csr_wr), .rd(csr_rd), .addr(csr_addr), .wdata(csr_wdata), .rdata(csr_rdata),
        .nuc_en(), .learn_en(), .bp_en(), .overlay_en(), .noise_en(), .csr_use(), .iron(), .preset(), .view(),
        .bp_t(), .emin(), .emax(), .t_mask(), .det_warm(), .act_thr(), .min_area(), .tone_lo(), .tone_sh(), .tone_auto(), .obj_en(obj_en), .feed_rows(feed_rows),
        .learn_n(), .cap_arm(cap_arm), .cap_src(cap_src), .cap_busy(cap_busy), .cap_done(cap_done), .cap_fid(cap_fid),
        .coef_reset(), .frame_reset(),
        .ready(1'b1), .retime_err(1'b0), .box_ovf_now(1'b0), .bad_seen_now(1'b0), .det_valid(1'b0), .gain_active(1'b0),
        .learning(1'b0), .box_done(1'b0), .box_n(8'd0), .box_cnt(5'd0), .box_rec({16*53{1'b0}}),
        .det_fdone(1'b0), .det_act_sum(32'd0), .det_n_after(8'd0), .nuc_fdone(1'b0), .nuc_sum_abs_e(40'd0),
        .nuc_lim(12'd0), .bad_count(32'd0), .ev_first_in(1'b0), .ev_eof_in(1'b0), .ev_y00(1'b0),
        .o_frames(), .o_lat_pix(), .o_lat_flag(), .o_latf_min(), .o_latf_max(), .o_latp_min(), .o_latp_max());

    // pixel stream source
    reg        pv = 1'b0, pfirst = 1'b0;
    reg [7:0]  pc8 = 8'd0, pr8 = 8'd0;
    frame_cap #(.W(W), .H(H), .AW(15)) u_cap (
        .clk(clk), .rst_n(rst_n), .pv(pv), .pfirst(pfirst), .pc8(pc8), .pr8(pr8),
        .arm(cap_arm), .src(cap_src), .busy(cap_busy), .done(cap_done), .cap_fid(cap_fid),
        .raddr(fb_raddr), .rdata(fb_rdata));

    integer errors = 0;
    integer seed = 4242;
    integer sf = 0, si = 0;               // stream: frame, pixel index
    integer gap = 0;
    reg     stream_on = 1'b0;
    always @(posedge clk) begin
        pv <= 1'b0; pfirst <= 1'b0;
        if (stream_on) begin
            if (gap > 0) gap = gap - 1;
            else begin
                pv <= 1'b1; pfirst <= (si == 0);
                pc8 <= (sf * 37 + si * 5) & 255; pr8 <= (sf * 11 + si * 3 + 128) & 255;
                gap = 1 + (($random(seed) & 32'h7fffffff) % 3);
                if (si == N - 1) begin si = 0; sf = sf + 1; gap = 40; end else si = si + 1;
            end
        end
    end

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
            // read is sampled at the edge where the loop starts; readdatavalid must be seen exactly 2 edges later
            if (k != 2) begin errors = errors + 1; $display("MISMATCH read latency %0d edges (expected 2)", k); end
            #1 got = av_readdata;
        end
    endtask
    task expect;
        input [255:0] name; input [31:0] g; input [31:0] e;
        begin
            if (g !== e) begin errors = errors + 1; $display("MISMATCH %0s got %h expected %h", name, g, e); end
        end
    endtask
    task wait_done;
        integer k;
        begin
            got = 0; k = 0;
            while (!got[17] && k < 1000) begin av_rd(19'h00038); k = k + 1; end     // CAP = word 0x0E
            if (!got[17]) begin errors = errors + 1; $display("FAIL: capture not done"); end
        end
    endtask
    // read the whole buffer and compare with frame f of the given source
    task check_buffer;
        input integer f; input integer src;
        integer k, b, i;
        reg [7:0] e;
        begin
            for (k = 0; k < N / 4; k = k + 1) begin
                av_rd(19'h20000 + 4 * k);
                for (b = 0; b < 4; b = b + 1) begin
                    i = 4 * k + b;
                    e = src ? ((f * 11 + i * 3 + 128) & 255) : ((f * 37 + i * 5) & 255);
                    if (got[8*b +: 8] !== e) begin
                        errors = errors + 1;
                        if (errors < 12) $display("MISMATCH buffer frame %0d src %0d pixel %0d got %h exp %h", f, src, i, got[8*b +: 8], e);
                    end
                end
            end
        end
    endtask

    integer f_arm, g_arm, ph;
    reg [31:0] ew;
    // feed word pattern: every byte of every word is distinct
    function [31:0] fwv;
        input integer k;
        reg [7:0] a, b, c, d;
        begin a = k * 7 + 1; b = k * 5 + 2; c = k * 3 + 3; d = k + 4; fwv = {a, b, c, d}; end
    endfunction
    initial begin
        #200 rst_n = 1'b1;
        repeat (3) @(posedge clk);
        // ---- CSR through the bus ----
        av_rd(19'h00000); expect("ID", got, 32'h7A110042);
        av_rd(19'h00034); expect("LEARN_N reset", got, 32'd256);
        av_wr(19'h00034, 32'd77); av_rd(19'h00034); expect("LEARN_N write", got, 32'd77);
        av_rd(19'h00038); expect("CAP idle", got, 32'h0);
        av_wr(19'h20034, 32'hFFFF); av_rd(19'h00034); expect("buffer write ignored (would alias LEARN_N)", got, 32'd77);
        // ---- scene feed region: write only, fully decoded ----
        for (ph = 0; ph < N; ph = ph + 1) begin               // nobody has written the frame store yet: all zeros, no X
            saddr = ph; @(posedge clk); @(posedge clk); #1;
            if (sq !== 8'h00) begin errors = errors + 1; if (errors < 12) $display("MISMATCH power-up scene byte %0d got %h", ph, sq); end
        end
        for (ph = 0; ph < N / 4; ph = ph + 1) av_wr(19'h40000 + 4 * ph, fwv(ph));
        av_rd(19'h00034); expect("feed write did not alias LEARN_N (0x40034 = feed word 13)", got, 32'd77);
        av_rd(19'h00038); expect("feed write did not alias CAP", got, 32'h0);
        av_rd(19'h00034); expect("LEARN_N still 77", got, 32'd77);                          // leaves 77 in the CSR read register
        av_rd(19'h40034); expect("feed region reads as zero (not the stale CSR read data)", got, 32'd0);
        av_rd(19'h00034); expect("LEARN_N still 77", got, 32'd77);
        av_rd(19'h60034); expect("feed region (bit 17 set too) reads as zero", got, 32'd0);
        av_wr(19'h60040, 32'h5A5A5A5A);                    // 0x60000 region is still 'feed' (bits [18:17] = 11)
        for (ph = 0; ph < N; ph = ph + 1) begin
            saddr = ph; @(posedge clk); @(posedge clk); #1;
            ew = (ph / 4 == 16) ? 32'h5A5A5A5A : fwv(ph / 4);
            if (sq !== ew[8*(ph%4) +: 8]) begin
                errors = errors + 1;
                if (errors < 12) $display("MISMATCH scene byte %0d got %h exp %h", ph, sq, ew[8*(ph%4) +: 8]);
            end
        end
        // a write into the capture region (0x20034) must not reach the feed buffer (word 13 stays as written)
        av_wr(19'h20034, 32'hDEADBEEF);
        for (ph = 52; ph < 56; ph = ph + 1) begin
            saddr = ph; @(posedge clk); @(posedge clk); #1;
            ew = fwv(13);
            if (sq !== ew[8*(ph%4) +: 8]) begin errors = errors + 1; $display("MISMATCH feed word 13 changed by a capture-region write"); end
        end
        saddr = N + 40; @(posedge clk); @(posedge clk); #1;
        ew = fwv(0);
        expect("scan past the end of the frame reads word 0 (no X)", {24'd0, sq}, {24'd0, ew[8*((N + 40) % 4) +: 8]});
        // rows counter, visible as FEED_ROW (CSR word 0x25)
        av_rd(19'h00094); expect("FEED_ROW starts at 0", got, 32'd0);
        for (ph = 0; ph < 7; ph = ph + 1) begin @(posedge clk); row_done <= 1'b1; @(posedge clk); row_done <= 1'b0; end
        av_rd(19'h00094); expect("FEED_ROW counts row_done pulses", got, 32'd7);
        av_wr(19'h00090, 32'd0); av_rd(19'h00090); expect("objects off through the bus", got, 32'd0);
        if (obj_en !== 1'b0) begin errors = errors + 1; $display("MISMATCH obj_en"); end
        av_wr(19'h00090, 32'd1);
        // ---- capture corrected, armed mid-frame ----
        stream_on = 1'b1;
        wait (sf == 1 && si == N / 2);
        f_arm = sf;
        av_wr(19'h00038, 32'h100);                         // arm, source 0
        av_rd(19'h00038);
        if (!got[16]) begin errors = errors + 1; $display("MISMATCH busy not set after arm (CAP=%h)", got); end
        wait_done;
        av_rd(19'h0003C); expect("CAP_FID = next frame after the arm", got, f_arm + 1);
        check_buffer(f_arm + 1, 0);
        // buffer stays stable while frames continue
        wait (sf == f_arm + 4);
        check_buffer(f_arm + 1, 0);
        // two reads on consecutive clocks: CSR ID, then buffer word 1
        @(posedge clk); av_read <= 1'b1; av_address <= 19'h00000;
        @(posedge clk); av_address <= 19'h20004;
        @(posedge clk); av_read <= 1'b0;
        @(negedge clk);                                   // sample between edges: no race with the DUT registers
        while (!av_readdatavalid) @(negedge clk);
        expect("pipelined read 1 (ID)", av_readdata, 32'h7A110042);
        @(negedge clk);
        if (!av_readdatavalid) begin errors = errors + 1; $display("MISMATCH pipelined read 2 not on the next clock"); end
        for (ph = 0; ph < 4; ph = ph + 1) ew[8*ph +: 8] = ((f_arm + 1) * 37 + (4 + ph) * 5) & 255;
        expect("pipelined read 2 (buffer word 1)", av_readdata, ew);
        // source is latched at arm: switch to raw in the middle of a corrected capture without re-arming
        wait (si == 3);
        f_arm = sf;
        av_wr(19'h00038, 32'h100);
        wait (sf == f_arm + 1 && si == N / 2);
        av_wr(19'h00038, 32'h001);                         // source := raw, no arm
        wait_done;
        av_rd(19'h0003C); expect("CAP_FID (source change)", got, f_arm + 1);
        check_buffer(f_arm + 1, 0);
        // ---- capture raw ----
        wait (si == 3);
        f_arm = sf;
        av_wr(19'h00038, 32'h101);
        wait_done;
        av_rd(19'h00038); expect("CAP source bit", got & 32'h1, 32'h1);
        av_rd(19'h0003C); expect("CAP_FID raw", got, f_arm + 1);
        check_buffer(f_arm + 1, 1);
        // ---- re-arm during a capture: restarts, captures the frame after the second arm ----
        for (ph = 0; ph < 4; ph = ph + 1) begin
            wait (si == 2);
            g_arm = sf;
            av_wr(19'h00038, 32'h100);                     // captures frame g_arm + 1 ...
            wait (sf == g_arm + 1 && si == N / 2);         // ... which is half way now
            repeat (ph) @(posedge clk);
            f_arm = sf;
            av_wr(19'h00038, 32'h100);
            wait_done;
            av_rd(19'h0003C); expect("CAP_FID after re-arm", got, f_arm + 1);
            check_buffer(f_arm + 1, 0);
        end
        if (errors == 0) $display("RESULT: PASS (W=%0d H=%0d, 8 captures checked)", W, H);
        else             $display("RESULT: FAIL (errors=%0d)", errors);
        $finish;
    end

    initial begin
        #(40 * 2000000);
        $display("RESULT: FAIL (timeout)");
        $finish;
    end
endmodule
