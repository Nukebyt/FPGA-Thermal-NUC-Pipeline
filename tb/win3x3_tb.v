`timescale 1ns/1ps
// win3x3_tb.v -- self-checking test of win3x3 with random data and random tick gaps (checklist 1.7, 3.1).
// Verdict: "RESULT: PASS" / "RESULT: FAIL".
//
// Latency ledger
//   win3x3 LATENCY = 3 clocks: otick(t+3) == tick(t). Checked every clock via a shift register.
//   A window is checked at the clock where wvalid=1; its centre (cr,cc) must be the next pixel in raster order.
//
// Expected windows are computed from the stored frame with clamped coordinates (independent of the RTL muxes).
// One process owns all testbench state; stimulus is driven with non-blocking assignments (checklist 3.6).
// Parameters override via -P on the iverilog command line: W H GAPMAX NFRAMES ORGK(=0: single stage)
module win3x3_tb;
    parameter W = 12;
    parameter H = 9;
    parameter GAPMAX = 5;           // extra random idle clocks between ticks: gap = 2 + rand(0..GAPMAX-2), min 2
    parameter NFRAMES = 3;
    localparam DW = 16;
    localparam SW = 4;
    localparam EXTRA = 2;           // dummy rows beyond H for one stage (needs >= 1)

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    always #20 clk = ~clk;

    reg              tick = 1'b0, first = 1'b0;
    reg  [DW-1:0]    din = 0;
    reg  [SW-1:0]    sin = 0;
    wire             otick, ofirst, wvalid;
    wire [8:0]       cr, cc;
    wire [9*DW-1:0]  win;
    wire [SW-1:0]    sout;

    win3x3 #(.DW(DW), .SW(SW), .W(W), .H(H), .ORG(0)) dut (
        .clk(clk), .rst_n(rst_n), .tick(tick), .first(first), .din(din), .sin(sin),
        .otick(otick), .ofirst(ofirst), .wvalid(wvalid), .cr(cr), .cc(cc), .win(win), .sout(sout));

    reg [DW-1:0] img [0:W*H-1];
    integer errors = 0;
    integer checked = 0;
    integer frame_checked = 0;
    integer next_idx = 0;           // expected raster index of the next window
    integer seed = 12345;

    function [DW-1:0] px;           // clamped fetch
        input integer r;
        input integer c;
        integer rr, cc2;
        begin
            rr = (r < 0) ? 0 : (r > H - 1) ? H - 1 : r;
            cc2 = (c < 0) ? 0 : (c > W - 1) ? W - 1 : c;
            px = img[rr * W + cc2];
        end
    endfunction

    function [SW-1:0] sidef;
        input [DW-1:0] v;
        begin
            sidef = v[3:0] ^ v[7:4] ^ 4'h5;
        end
    endfunction

    // ---- stimulus sequencer (state machine, one process) ----
    integer fr = 0, sr = 0, sc = 0, wait_cnt = 0, phase = 0;   // phase 0 idle-before, 1 ticking, 2 done
    reg [DW-1:0] junk;
    integer k;
    reg [3*DW-1:0] dummy;
    reg [2:0] tickpipe;
    integer exp_cnt;

    reg [DW-1:0] e_nw, e_n, e_ne, e_w, e_c, e_e, e_sw, e_s, e_se;
    integer r_, c_;

    always @(posedge clk) begin
        if (!rst_n) begin
            tick <= 1'b0; first <= 1'b0; tickpipe <= 3'b0;
        end else begin
            // latency ledger: otick must equal tick delayed by exactly 3 clocks
            tickpipe <= {tickpipe[1:0], tick};
            if (otick !== tickpipe[2]) begin
                errors = errors + 1;
                if (errors < 10) $display("MISMATCH latency @%0t otick=%b exp=%b", $time, otick, tickpipe[2]);
            end

            // ---- check output window ----
            if (wvalid) begin
                r_ = cr; c_ = cc;
                if (r_ * W + c_ != next_idx) begin
                    errors = errors + 1;
                    if (errors < 10) $display("MISMATCH order @%0t got (%0d,%0d) exp idx %0d", $time, r_, c_, next_idx);
                end
                e_nw = px(r_ - 1, c_ - 1); e_n = px(r_ - 1, c_); e_ne = px(r_ - 1, c_ + 1);
                e_w  = px(r_,     c_ - 1); e_c = px(r_,     c_); e_e  = px(r_,     c_ + 1);
                e_sw = px(r_ + 1, c_ - 1); e_s = px(r_ + 1, c_); e_se = px(r_ + 1, c_ + 1);
                if (win !== {e_nw, e_n, e_ne, e_w, e_c, e_e, e_sw, e_s, e_se}) begin
                    errors = errors + 1;
                    if (errors < 10) $display("MISMATCH window @%0t (%0d,%0d) got %h exp %h", $time, r_, c_, win,
                                              {e_nw, e_n, e_ne, e_w, e_c, e_e, e_sw, e_s, e_se});
                end
                if (sout !== sidef(e_c)) begin
                    errors = errors + 1;
                    if (errors < 10) $display("MISMATCH side @%0t (%0d,%0d) got %h exp %h", $time, r_, c_, sout, sidef(e_c));
                end
                checked = checked + 1;
                frame_checked = frame_checked + 1;
                next_idx = next_idx + 1;
            end

            // ---- drive ----
            tick <= 1'b0; first <= 1'b0;
            if (wait_cnt > 0) begin
                wait_cnt = wait_cnt - 1;
            end else if (phase == 0) begin
                // new frame: random image
                for (k = 0; k < W * H; k = k + 1) img[k] = $random(seed);
                frame_checked = 0; next_idx = 0;
                sr = 0; sc = 0; phase = 1;
            end
            if (wait_cnt == 0 && phase == 1) begin
                junk = $random(seed);
                tick <= 1'b1;
                first <= (sr == 0) && (sc == 0);
                din <= (sr < H && sc < W) ? img[sr * W + sc] : junk;
                sin <= (sr < H && sc < W) ? sidef(img[sr * W + sc]) : junk[3:0];
                wait_cnt = 1 + (($random(seed) & 32'h7fffffff) % (GAPMAX - 1));     // spacing 2..GAPMAX
                if (sc == W) begin
                    sc = 0; sr = sr + 1;
                end else sc = sc + 1;
                if (sr == H + EXTRA) begin
                    phase = 2; wait_cnt = 20;
                end
            end
            if (wait_cnt == 0 && phase == 2) begin
                if (frame_checked != W * H) begin
                    errors = errors + 1;
                    $display("MISMATCH frame %0d produced %0d windows, expected %0d", fr, frame_checked, W * H);
                end
                fr = fr + 1;
                phase = (fr == NFRAMES) ? 3 : 0;
                wait_cnt = (fr < NFRAMES) ? 30 : 0;
            end
        end
    end

    initial begin
        #200 rst_n = 1'b1;
        wait (phase == 3);
        #400;
        if (checked != NFRAMES * W * H) begin
            errors = errors + 1;
            $display("FAIL: checked %0d windows, expected %0d", checked, NFRAMES * W * H);
        end
        if (errors == 0) $display("RESULT: PASS (windows checked=%0d, GAPMAX=%0d)", checked, GAPMAX);
        else             $display("RESULT: FAIL (errors=%0d)", errors);
        $finish;
    end

    initial begin
        #(40 * 5000000);
        $display("RESULT: FAIL (timeout)");
        $finish;
    end
endmodule
