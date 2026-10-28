`timescale 1ns/1ps
// nuc_core_tb.v -- vector-driven, bit-exact test of nuc_core against model/pipeline_int.py (scripts/gen_nuc_vectors.py).
// Verdict: "RESULT: PASS" / "RESULT: FAIL".
//
// What is compared, for every frame and every pixel:
//   * oy  (corrected, bad-replaced y14)     vs y.hex
//   * ox  (raw sample re-derived from the carried coefficient side info) vs x.hex
//   * obad                                  vs bad.hex
//   * the whole coefficient RAM after the frame (bpc, g, o)      vs coef.hex   (hierarchical read: TB only)
//   * fsum_abs_e / lim_used                 vs fr.hex
//   * `learning` (learning window open and enabled) per frame   vs lrn.hex
// Latency ledger: otick == tick delayed by LAT_TICK = 11 clocks (mirrors nuc_core's localparam).
// Pixel order: results arrive in raster order; index = cr*W + cc is compared with a running counter.
// Stimulus: ticks on the full (W+1) x (H+2) grid, random spacing 2..GAPMAX clocks (checklist 1.7); one process owns
// all TB state and drives with non-blocking assignments (checklist 3.6).
// Per-frame controls come from ctl.hex (bit0 gain_en, bit1 nuc_en, bit2 learn_en, bit3 bp_en), so runtime
// switching of the enables between frames is part of the test.
// CRST >= 0: pulse coef_reset before frame CRST (RAM clear + learning-window restart; generator --coef_reset_at).
// Overrides: -P nuc_core_tb.W= .H= .T= .GAPMAX= .KLIM= .LEARN_N= .CRST= .VEC="dir"
//            (KLIM, LEARN_N, CRST must match gen_nuc_vectors.py --klim / --learn_n / --coef_reset_at)
module nuc_core_tb;
    parameter W = 48;
    parameter H = 36;
    parameter T = 16;
    parameter GAPMAX = 4;
    parameter KLIM = 41;
    parameter LEARN_N = 0;
    parameter CRST = -1;
    parameter VEC = "work/vec_nuc";
    localparam N = W * H;
    localparam LAT_TICK = 11;
    localparam AW = 17;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    always #20 clk = ~clk;

    reg [15:0] xmem  [0:T*N-1];
    reg [15:0] ymem  [0:T*N-1];
    reg [3:0]  bmem  [0:T*N-1];
    reg [3:0]  cmem  [0:T-1];
    reg [3:0]  lmem  [0:T-1];
    reg [31:0] comem [0:T*N-1];
    reg [63:0] frmem [0:2*T-1];        // [2t] = sum, [2t+1] = lim  (read via $fscanf below instead)

    reg        tick = 1'b0, first = 1'b0;
    reg [13:0] x_in = 14'd0;
    reg        gain_en_in = 1'b1, nuc_en_r = 1'b1, learn_en_r = 1'b1, bp_en_r = 1'b1;
    reg        coef_reset = 1'b0;
    reg        crst_done = 1'b0;
    wire       ready, otick, ofirst, ovalid, obad, fdone, learning;
    wire [15:0] learn_n = LEARN_N;
    wire [8:0] ocr, occ;
    wire [13:0] oy, ox;
    wire [39:0] fsum;
    wire [11:0] lim_used;

    nuc_core #(.W(W), .H(H), .AW(AW), .KLIM(KLIM)) dut (
        .clk(clk), .rst_n(rst_n), .tick(tick), .first(first), .x_in(x_in),
        .nuc_en(nuc_en_r), .learn_en(learn_en_r), .bp_en(bp_en_r),
        .bp_t(14'd800), .emin(10'd16), .emax(10'd512), .gain_en_in(gain_en_in), .learn_n(learn_n), .coef_reset(coef_reset),
        .ready(ready), .learning(learning), .otick(otick), .ofirst(ofirst), .ovalid(ovalid), .ocr(ocr), .occ(occ),
        .oy(oy), .ox(ox), .obad(obad), .fdone(fdone), .fsum_abs_e(fsum), .lim_used(lim_used));

    integer errors = 0;
    integer seed = 777;
    integer fr = 0, sr = 0, sc = 0, wait_cnt = 0, phase = 0;
    integer idx_exp = 0;
    integer n_out = 0;
    integer frames_done = 0;
    integer i, fh, rc;
    reg [39:0] exp_sum;
    reg [11:0] exp_lim;
    reg [31:0] cw_got, cw_exp;
    reg [63:0] tpipe = 64'd0;
    integer total_checked = 0;

    initial begin
        $readmemh({VEC, "/x.hex"}, xmem);
        $readmemh({VEC, "/y.hex"}, ymem);
        $readmemh({VEC, "/bad.hex"}, bmem);
        $readmemh({VEC, "/ctl.hex"}, cmem);
        $readmemh({VEC, "/lrn.hex"}, lmem);
        $readmemh({VEC, "/coef.hex"}, comem);
        fh = $fopen({VEC, "/fr.hex"}, "r");
        for (i = 0; i < T; i = i + 1) begin
            rc = $fscanf(fh, "%h %h\n", exp_sum, exp_lim);
            frmem[2*i] = exp_sum; frmem[2*i+1] = exp_lim;
        end
        $fclose(fh);
        #200 rst_n = 1'b1;
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            tick <= 1'b0; first <= 1'b0; tpipe <= 64'd0;
        end else begin
            // ---- latency ledger ----
            tpipe <= {tpipe[62:0], tick};
            if (otick !== tpipe[LAT_TICK-1]) begin
                errors = errors + 1;
                if (errors < 10) $display("MISMATCH latency @%0t otick=%b exp=%b", $time, otick, tpipe[LAT_TICK-1]);
            end

            // ---- check pixel stream ----
            if (ovalid) begin
                if ((ocr * W + occ) !== idx_exp) begin
                    errors = errors + 1;
                    if (errors < 10) $display("MISMATCH order @%0t got (%0d,%0d) exp idx %0d", $time, ocr, occ, idx_exp);
                end
                if (oy !== ymem[frames_done*N + idx_exp][13:0]) begin
                    errors = errors + 1;
                    if (errors < 10) $display("MISMATCH y frame %0d idx %0d got %h exp %h", frames_done, idx_exp, oy, ymem[frames_done*N + idx_exp][13:0]);
                end
                if (ox !== xmem[frames_done*N + idx_exp][13:0]) begin
                    errors = errors + 1;
                    if (errors < 10) $display("MISMATCH x frame %0d idx %0d got %h exp %h", frames_done, idx_exp, ox, xmem[frames_done*N + idx_exp][13:0]);
                end
                if (obad !== bmem[frames_done*N + idx_exp][0]) begin
                    errors = errors + 1;
                    if (errors < 10) $display("MISMATCH bad frame %0d idx %0d got %b exp %b", frames_done, idx_exp, obad, bmem[frames_done*N + idx_exp][0]);
                end
                idx_exp = idx_exp + 1;
                n_out = n_out + 1;
                total_checked = total_checked + 1;
            end

            // ---- check end of frame ----
            if (fdone) begin
                if (n_out != N) begin
                    errors = errors + 1;
                    $display("MISMATCH frame %0d produced %0d pixels, expected %0d", frames_done, n_out, N);
                end
                if (fsum !== frmem[2*frames_done][39:0] || lim_used !== frmem[2*frames_done+1][11:0]) begin
                    errors = errors + 1;
                    $display("MISMATCH frame %0d stats sum got %h exp %h lim got %h exp %h", frames_done, fsum,
                             frmem[2*frames_done][39:0], lim_used, frmem[2*frames_done+1][11:0]);
                end
                if (learning !== lmem[frames_done][0]) begin
                    errors = errors + 1;
                    $display("MISMATCH frame %0d learning got %b exp %b", frames_done, learning, lmem[frames_done][0]);
                end
                for (i = 0; i < N; i = i + 1) begin
                    cw_got = {2'b00, dut.coef.mem[i]};
                    cw_exp = comem[frames_done*N + i];
                    if (cw_got !== cw_exp) begin
                        errors = errors + 1;
                        if (errors < 10) $display("MISMATCH coef frame %0d idx %0d got %h exp %h", frames_done, i, cw_got, cw_exp);
                    end
                end
                frames_done = frames_done + 1;
                n_out = 0; idx_exp = 0;
            end

            // ---- drive ----
            tick <= 1'b0; first <= 1'b0; coef_reset <= 1'b0;
            if (wait_cnt > 0) wait_cnt = wait_cnt - 1;
            else if (phase == 0) begin
                if (fr == CRST && !crst_done) begin
                    coef_reset <= 1'b1; crst_done <= 1'b1; wait_cnt = 4;      // ready drops; wait for the clear
                end else if (ready) begin
                    gain_en_in <= cmem[fr][0]; nuc_en_r <= cmem[fr][1]; learn_en_r <= cmem[fr][2]; bp_en_r <= cmem[fr][3];
                    sr = 0; sc = 0; phase = 1;
                end
            end
            if (wait_cnt == 0 && phase == 1) begin
                tick <= 1'b1;
                first <= (sr == 0) && (sc == 0);
                x_in <= (sr < H && sc < W) ? xmem[fr*N + sr*W + sc][13:0] : $random(seed);
                wait_cnt = 1 + (($random(seed) & 32'h7fffffff) % (GAPMAX - 1));
                if (sc == W) begin sc = 0; sr = sr + 1; end else sc = sc + 1;
                if (sr == H + 2) begin phase = 2; wait_cnt = (W + 4) * GAPMAX + 200; end
            end
            if (wait_cnt == 0 && phase == 2) begin
                fr = fr + 1;
                phase = (fr == T) ? 3 : 0;
                wait_cnt = 20;
            end
        end
    end

    initial begin
        wait (phase == 3);
        #(40 * 400);
        if (frames_done != T) begin
            errors = errors + 1;
            $display("FAIL: %0d frames completed, expected %0d", frames_done, T);
        end
        if (total_checked != T * N) begin
            errors = errors + 1;
            $display("FAIL: %0d pixels checked, expected %0d", total_checked, T * N);
        end
        if (errors == 0) $display("RESULT: PASS (frames=%0d pixels=%0d GAPMAX=%0d)", T, total_checked, GAPMAX);
        else             $display("RESULT: FAIL (errors=%0d)", errors);
        $finish;
    end

    initial begin
        #(40 * 60000000);
        $display("RESULT: FAIL (timeout)");
        $finish;
    end
endmodule
