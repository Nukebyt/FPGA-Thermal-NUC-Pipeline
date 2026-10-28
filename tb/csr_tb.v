`timescale 1ns/1ps
// csr_tb.v -- directed test of csr_regs: read/write, reset values, write-1 pulses, sticky flags, box read-back,
// the hardware latency counters (exact cycle arithmetic, min/max, clear), and unknown-address behaviour.
// Verdict: "RESULT: PASS" / "RESULT: FAIL". Every expectation is computed by the TB from the stimulus it applied.
module csr_tb;
    reg clk = 1'b0, rst_n = 1'b0;
    always #20 clk = ~clk;

    reg         wr = 1'b0, rd = 1'b0;
    reg  [7:0]  addr = 8'd0;
    reg  [31:0] wdata = 32'd0;
    wire [31:0] rdata;
    wire nuc_en, learn_en, bp_en, overlay_en, noise_en, csr_use, iron, tone_auto, coef_reset, frame_reset;
    wire [1:0] preset, view;
    wire [13:0] bp_t, t_mask, tone_lo;
    wire [9:0] emin, emax;
    wire [7:0] det_warm;
    wire [15:0] act_thr, min_area, learn_n;
    wire [3:0] tone_sh;
    wire obj_en;
    reg  [31:0] feed_rows = 32'd0;

    reg ready = 1'b1, retime_err = 1'b0, box_ovf_now = 1'b0, bad_seen_now = 1'b0, det_valid = 1'b1, gain_active = 1'b1, learning = 1'b0;
    reg box_done = 1'b0; reg [7:0] box_n = 8'd0; reg [4:0] box_cnt = 5'd0; reg [16*53-1:0] box_rec = {16*53{1'b0}};
    reg det_fdone = 1'b0; reg [31:0] det_act_sum = 32'd0; reg [7:0] det_n_after = 8'd0;
    reg nuc_fdone = 1'b0; reg [39:0] nuc_sum = 40'd0; reg [11:0] nuc_lim = 12'd0; reg [31:0] bad_count = 32'd0;
    reg ev_first = 1'b0, ev_eof = 1'b0, ev_y00 = 1'b0;

    csr_regs #(.BUILD(16'h1234), .FEED(1)) dut (
        .clk(clk), .rst_n(rst_n), .wr(wr), .rd(rd), .addr(addr), .wdata(wdata), .rdata(rdata),
        .nuc_en(nuc_en), .learn_en(learn_en), .bp_en(bp_en), .overlay_en(overlay_en), .noise_en(noise_en), .csr_use(csr_use), .iron(iron),
        .preset(preset), .view(view), .bp_t(bp_t), .emin(emin), .emax(emax), .t_mask(t_mask), .det_warm(det_warm),
        .act_thr(act_thr), .min_area(min_area), .tone_lo(tone_lo), .tone_sh(tone_sh), .tone_auto(tone_auto), .obj_en(obj_en), .feed_rows(feed_rows), .learn_n(learn_n),
        .cap_arm(), .cap_src(), .cap_busy(1'b0), .cap_done(1'b0), .cap_fid(32'd0),
        .coef_reset(coef_reset), .frame_reset(frame_reset),
        .ready(ready), .retime_err(retime_err), .box_ovf_now(box_ovf_now), .bad_seen_now(bad_seen_now), .det_valid(det_valid),
        .gain_active(gain_active), .learning(learning), .box_done(box_done), .box_n(box_n), .box_cnt(box_cnt), .box_rec(box_rec),
        .det_fdone(det_fdone), .det_act_sum(det_act_sum), .det_n_after(det_n_after),
        .nuc_fdone(nuc_fdone), .nuc_sum_abs_e(nuc_sum), .nuc_lim(nuc_lim), .bad_count(bad_count),
        .ev_first_in(ev_first), .ev_eof_in(ev_eof), .ev_y00(ev_y00),
        .o_frames(), .o_lat_pix(), .o_lat_flag(), .o_latf_min(), .o_latf_max(), .o_latp_min(), .o_latp_max());

    integer errors = 0;
    integer i;
    reg [31:0] got;

    task bus_write;
        input [7:0] a; input [31:0] d;
        begin
            @(posedge clk); wr <= 1'b1; addr <= a; wdata <= d;
            @(posedge clk); wr <= 1'b0;
        end
    endtask
    task bus_read;
        input [7:0] a;
        begin
            @(posedge clk); rd <= 1'b1; addr <= a;
            @(posedge clk); rd <= 1'b0;
            @(posedge clk); #1 got = rdata;          // registered read: valid one clock after rd
        end
    endtask
    task expect;
        input [255:0] name; input [31:0] g; input [31:0] e;
        begin
            if (g !== e) begin
                errors = errors + 1;
                $display("MISMATCH %0s got %h expected %h", name, g, e);
            end
        end
    endtask
    task pulse;
        input integer which;                          // 0 first, 1 eof, 2 y00, 3 box_done
        begin
            @(posedge clk);
            case (which)
                0: ev_first <= 1'b1;
                1: ev_eof <= 1'b1;
                2: ev_y00 <= 1'b1;
                3: box_done <= 1'b1;
            endcase
            @(posedge clk);
            ev_first <= 1'b0; ev_eof <= 1'b0; ev_y00 <= 1'b0; box_done <= 1'b0;
        end
    endtask
    task idle;
        input integer n;
        integer k;
        begin for (k = 0; k < n; k = k + 1) @(posedge clk); end
    endtask

    reg [31:0] lp, lf;
    initial begin
        #200 rst_n = 1'b1;
        idle(3);
        // ---- reset values ----
        bus_read(8'h00); expect("ID", got, 32'h7A111234);
        bus_read(8'h01); expect("CTRL reset", got, 32'b0_10_0_01_11111);
        bus_read(8'h03); expect("BP_T reset", got, 32'd800);
        bus_read(8'h04); expect("EMIN reset", got, 32'd16);
        bus_read(8'h05); expect("EMAX reset", got, 32'd512);
        bus_read(8'h06); expect("T_MASK reset", got, 32'd400);
        bus_read(8'h07); expect("DET_WARM reset", got, 32'd128);
        bus_read(8'h08); expect("ACT_THR reset", got, 32'd64);
        bus_read(8'h09); expect("MIN_AREA reset", got, 32'd8);
        bus_read(8'h0B); expect("TONE_SH reset", got, 32'd6);
        bus_read(8'h0C); expect("TONE_AUTO reset", got, 32'd1);
        bus_read(8'h0D); expect("LEARN_N reset", got, 32'd256);
        expect("learn_n output after reset", {16'd0, learn_n}, 32'd256);
        if (!(nuc_en && learn_en && bp_en && overlay_en && noise_en && !csr_use && preset == 2'd1 && view == 2'd2 && !iron)) begin
            errors = errors + 1; $display("MISMATCH control outputs after reset");
        end
        // ---- write / read back every RW register ----
        bus_write(8'h01, 32'h000005A3); bus_read(8'h01); expect("CTRL wr", got, 32'h5A3);
        if (nuc_en !== 1'b1 || learn_en !== 1'b1 || bp_en !== 1'b0 || csr_use !== 1'b1 || view !== 2'd1 || iron !== 1'b1) begin
            errors = errors + 1; $display("MISMATCH decoded control bits");
        end
        bus_write(8'h03, 32'h1234);  bus_read(8'h03); expect("BP_T wr", got, 32'h1234);
        bus_write(8'h04, 32'h3FF);   bus_read(8'h04); expect("EMIN wr", got, 32'h3FF);
        bus_write(8'h05, 32'hFFFFFC00 | 32'h155); bus_read(8'h05); expect("EMAX wr masked to 10 bits", got, 32'h155);
        bus_write(8'h06, 32'hFFFF);  bus_read(8'h06); expect("T_MASK wr masked to 14 bits", got, 32'h3FFF);
        bus_write(8'h07, 32'h1FF);   bus_read(8'h07); expect("DET_WARM masked to 8 bits", got, 32'hFF);
        bus_write(8'h08, 32'h1_2345); bus_read(8'h08); expect("ACT_THR masked to 16 bits", got, 32'h2345);
        bus_write(8'h09, 32'hABCD);  bus_read(8'h09); expect("MIN_AREA", got, 32'hABCD);
        bus_write(8'h0A, 32'h0F0F);  bus_read(8'h0A); expect("TONE_LO", got, 32'h0F0F);
        bus_write(8'h0B, 32'h1F);    bus_read(8'h0B); expect("TONE_SH masked", got, 32'hF);
        bus_write(8'h0C, 32'h0);     bus_read(8'h0C); expect("TONE_AUTO", got, 32'h0);
        bus_write(8'h0D, 32'h1_00C8); bus_read(8'h0D); expect("LEARN_N masked to 16 bits", got, 32'h00C8);
        expect("learn_n output", {16'd0, learn_n}, 32'h00C8);
        bus_write(8'h0D, 32'h0);     bus_read(8'h0D); expect("LEARN_N = 0 (no limit)", got, 32'h0);
        // ---- pulses are one clock wide, not stored ----
        @(posedge clk); wr <= 1'b1; addr <= 8'h02; wdata <= 32'h3;
        @(posedge clk); wr <= 1'b0;
        @(posedge clk);
        if (!(coef_reset && frame_reset)) begin errors = errors + 1; $display("MISMATCH pulses not seen"); end
        @(posedge clk);
        if (coef_reset || frame_reset) begin errors = errors + 1; $display("MISMATCH pulses longer than one clock"); end
        bus_read(8'h02); expect("PULSE reads as unknown address", got, 32'hDEADBEEF);
        // ---- status + sticky ----
        retime_err = 1'b1; idle(2); retime_err = 1'b0; bad_seen_now = 1'b1; idle(2); bad_seen_now = 1'b0;
        bus_read(8'h10); expect("STATUS sticky", got & 32'h0F, 32'b1011);        // ready, retime sticky, bad sticky
        bus_write(8'h02, 32'h4); idle(2);
        bus_read(8'h10); expect("STATUS after clear", got & 32'h0F, 32'b0001);
        learning = 1'b1; gain_active = 1'b0; idle(1);
        bus_read(8'h10); expect("STATUS learning bit 7, gain bit 6", got & 32'hC0, 32'h80);
        learning = 1'b0; gain_active = 1'b1; idle(1);
        bus_read(8'h10); expect("STATUS learning off", got & 32'hC0, 32'h40);
        // ---- boxes ----
        box_rec = {16*53{1'b0}};
        for (i = 0; i < 16; i = i + 1)
            box_rec[i*53 +: 53] = {i[16:0] + 17'd1000, 9'd100 + i[8:0], 9'd200 + i[8:0], 9'd10 + i[8:0], 9'd20 + i[8:0]};
        box_n = 8'd7; box_cnt = 5'd7;
        pulse(3);
        idle(2);
        for (i = 0; i < 16; i = i + 1) begin
            bus_read(8'h30 + 4*i + 0); expect("BOX w0", got, {14'd0, (9'd10 + i[8:0]), (9'd20 + i[8:0])} & 32'h3FFFF);
            bus_read(8'h30 + 4*i + 1); expect("BOX w1", got, {14'd0, (9'd100 + i[8:0]), (9'd200 + i[8:0])} & 32'h3FFFF);
            bus_read(8'h30 + 4*i + 2); expect("BOX area", got, 32'd1000 + i);
        end
        bus_read(8'h12); expect("BOXINFO", got, {15'd0, 1'b0, 3'd0, 5'd7, 8'd7});
        bus_read(8'h10); expect("STATUS motion", (got >> 5) & 1, 32'd1);
        // ---- latency counters: clear, then 4 frames with known cycle distances ----
        bus_write(8'h02, 32'h8); idle(3);
        for (i = 0; i < 4; i = i + 1) begin
            pulse(0);                         // first input tick
            idle(100 + 7 * i);
            pulse(2);                         // pixel (0,0) out   -> LAT_PIX = 100 + 7*i + 2 .. fixed by pulse() timing, measured below
            idle(50);
            pulse(1);                         // eof tick
            idle(36 + 5 * (i % 2));           // box_done after a varying delay (jitter on purpose)
            pulse(3);
            idle(20);
        end
        bus_read(8'h1C); lp = got;
        bus_read(8'h1D); lf = got;
        bus_read(8'h1E); expect("LATP_MIN", got, 32'd100 + 2);                 // i = 0: 100 idle + 2 pulse cycles
        bus_read(8'h1F); expect("LATP_MAX", got, 32'd100 + 21 + 2);            // i = 3
        bus_read(8'h20); expect("LATF_MIN", got, 32'd36 + 2);
        bus_read(8'h21); expect("LATF_MAX", got, 32'd36 + 5 + 2);
        bus_read(8'h22); expect("LAT_N", got, 32'd4);
        expect("LAT_PIX last", lp, 32'd100 + 21 + 2);
        expect("LAT_FLAG last", lf, 32'd36 + 5 + 2);
        // clear stats
        bus_write(8'h02, 32'h8); idle(3);
        bus_read(8'h22); expect("LAT_N cleared", got, 32'd0);
        bus_read(8'h1E); expect("LATP_MIN cleared", got, 32'hFFFFFFFF);
        // ---- scene feed registers ----
        bus_read(8'h23); expect("CAPS: feed present", got, 32'd1);
        bus_read(8'h24); expect("FEED_CTRL reset (objects on)", got, 32'd1);
        if (obj_en !== 1'b1) begin errors = errors + 1; $display("MISMATCH obj_en after reset"); end
        bus_write(8'h24, 32'hFFFFFFFE); bus_read(8'h24); expect("FEED_CTRL wr (masked to 1 bit)", got, 32'd0);
        if (obj_en !== 1'b0) begin errors = errors + 1; $display("MISMATCH obj_en after write"); end
        bus_write(8'h24, 32'd1); bus_read(8'h24); expect("FEED_CTRL wr 1", got, 32'd1);
        feed_rows = 32'h0001_2345; bus_read(8'h25); expect("FEED_ROW follows the scene scan", got, 32'h0001_2345);
        feed_rows = 32'hFFFF_FFFE; bus_read(8'h25); expect("FEED_ROW 32 bits", got, 32'hFFFF_FFFE);
        bus_write(8'h25, 32'd5); bus_read(8'h25); expect("FEED_ROW is read only", got, 32'hFFFF_FFFE);
        bus_write(8'h23, 32'd0); bus_read(8'h23); expect("CAPS is read only", got, 32'd1);
        // ---- unknown address ----
        bus_read(8'hF0); expect("unknown address", got, 32'hDEADBEEF);
        if (errors == 0) $display("RESULT: PASS");
        else             $display("RESULT: FAIL (errors=%0d)", errors);
        $finish;
    end
    initial begin
        #(40 * 200000);
        $display("RESULT: FAIL (timeout)");
        $finish;
    end
endmodule
