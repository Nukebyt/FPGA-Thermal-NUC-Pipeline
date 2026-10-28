`timescale 1ns/1ps
// ccl_tb.v -- vector-driven, exact test of ccl_boxes against pipeline_int.ccl_boxes() (scripts/gen_ccl_vectors.py).
// Verdict: "RESULT: PASS" / "RESULT: FAIL".
//
// Latency ledger: fdone is high exactly LAT_EOF = 36 cycles after the cycle in which the last pixel
// (cr = H-1, cc = W-1) is on ivalid, for EVERY frame regardless of content (fixed latency K).
// This TB samples at clock edges: the edge that issues ivalid <= 1 is edge 0, so fdone is SEEN at edge LAT_EOF + 1.
// Compared per frame: n_obj, listed count, overflow flag, and every listed 53-bit record in finishing order.
// Stimulus: pixel events spaced 2..GAPMAX clocks apart (checklist 1.7), >= 50 idle clocks between rows.
// One process owns all TB state; drives with non-blocking assignments (checklist 3.6).
// Overrides: -P ccl_tb.W= .H= .T= .GAPMAX= .MINAREA= .VEC="dir"
module ccl_tb;
    parameter W = 40;
    parameter H = 30;
    parameter T = 24;
    parameter GAPMAX = 4;
    parameter MINAREA = 1;
    parameter VEC = "work/vec_ccl";
    localparam LAT_EOF = 36;
    localparam [15:0] MA = MINAREA;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    always #20 clk = ~clk;

    reg        mmem [0:T*H*W-1];
    reg [15:0] hmem [0:T-1];
    reg [55:0] rmem [0:T*16-1];

    reg        ivalid = 1'b0, imask = 1'b0;
    reg [8:0]  icr = 9'd0, icc = 9'd0;
    wire       fdone, pub_ovf;
    wire [7:0] pub_n;
    wire [4:0] pub_cnt;
    wire [16*53-1:0] pub_boxes;

    ccl_boxes #(.W(W), .H(H)) dut (
        .clk(clk), .rst_n(rst_n), .ivalid(ivalid), .imask(imask), .icr(icr), .icc(icc), .min_area(MA),
        .fdone(fdone), .pub_n(pub_n), .pub_cnt(pub_cnt), .pub_ovf(pub_ovf), .pub_boxes(pub_boxes));

    integer errors = 0, seed = 4242;
    integer fr = 0, r = 0, c = 0, wait_cnt = 0, phase = 0;
    integer since_last = -1;         // clocks since the last pixel of the frame was presented (-1 = not armed)
    integer frames_done = 0;
    integer i, k;
    reg [13:0] hdr_exp;
    reg [52:0] rec_got, rec_exp;
    integer exp_cnt;
    reg [4:0] hcnt;
    integer tmp;
    reg [7:0] hn;

    initial begin
        $readmemh({VEC, "/mask.hex"}, mmem);
        $readmemh({VEC, "/hdr.hex"}, hmem);
        $readmemh({VEC, "/rec.hex"}, rmem);
        #200 rst_n = 1'b1;
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            ivalid <= 1'b0;
        end else begin
            // ---- latency ledger ----
            if (since_last >= 0) since_last = since_last + 1;
            if (fdone) begin
                if (since_last != LAT_EOF + 1) begin
                    errors = errors + 1;
                    $display("MISMATCH latency frame %0d: fdone %0d clocks after last pixel, expected %0d", frames_done, since_last, LAT_EOF + 1);
                end
                since_last = -1;
                // ---- compare results ----
                hdr_exp = hmem[frames_done][13:0];
                hn = hdr_exp[13:6]; hcnt = hdr_exp[5:1];
                if (pub_n !== hn || pub_cnt !== hcnt || pub_ovf !== hdr_exp[0]) begin
                    errors = errors + 1;
                    $display("MISMATCH frame %0d header got n=%0d cnt=%0d ovf=%b exp n=%0d cnt=%0d ovf=%b", frames_done,
                             pub_n, pub_cnt, pub_ovf, hn, hcnt, hdr_exp[0]);
                end
                for (i = 0; i < hcnt; i = i + 1) begin
                    rec_got = pub_boxes[i*53 +: 53];
                    rec_exp = rmem[frames_done*16 + i][52:0];
                    if (rec_got !== rec_exp) begin
                        errors = errors + 1;
                        if (errors < 12) $display("MISMATCH frame %0d rec %0d got %h exp %h", frames_done, i, rec_got, rec_exp);
                    end
                end
                frames_done = frames_done + 1;
            end

            // ---- drive ----
            ivalid <= 1'b0;
            if (wait_cnt > 0) wait_cnt = wait_cnt - 1;
            if (wait_cnt == 0 && phase == 0) begin
                r = 0; c = 0; phase = 1;
            end
            if (wait_cnt == 0 && phase == 1) begin
                ivalid <= 1'b1;
                imask <= mmem[fr*H*W + r*W + c];
                icr <= r; icc <= c;
                if (r == H - 1 && c == W - 1) begin
                    since_last = 0;
                    phase = 2; wait_cnt = 200;
                end else if (c == W - 1) begin
                    c = 0; r = r + 1; wait_cnt = 50 + (($random(seed) & 32'h7fffffff) % 30);
                end else begin
                    c = c + 1; wait_cnt = 1 + (($random(seed) & 32'h7fffffff) % (GAPMAX - 1));
                end
            end
            if (wait_cnt == 0 && phase == 2) begin
                fr = fr + 1;
                phase = (fr == T) ? 3 : 0;
                wait_cnt = 5;
            end
        end
    end

    initial begin
        wait (phase == 3);
        #(40 * 300);
        if (frames_done != T) begin
            errors = errors + 1;
            $display("FAIL: %0d frames finished, expected %0d", frames_done, T);
        end
        if (errors == 0) $display("RESULT: PASS (frames=%0d GAPMAX=%0d MINAREA=%0d)", T, GAPMAX, MINAREA);
        else             $display("RESULT: FAIL (errors=%0d)", errors);
        $finish;
    end

    initial begin
        #(40 * 40000000);
        $display("RESULT: FAIL (timeout)");
        $finish;
    end
endmodule
