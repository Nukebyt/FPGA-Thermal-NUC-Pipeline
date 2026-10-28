`timescale 1ns/1ps
// row_retimer_tb.v -- self-checking test of row_retimer (bug log 26: its overrun flag was never exercised).
// Verdict: "RESULT: PASS" / "RESULT: FAIL".
//
// Phase A: rows arrive one pixel per clock with a gap long enough for the replay (2W + 4 clocks). Every output pixel must carry the
//   right bit and (row, col) label, in raster order, exactly RT(c) = 5 + 2c clocks after the clock edge that sampled the last pixel of its row (the RTL header counts from the
//   edge after it: 6 + 2c; the offset is the same for every pixel), and err
//   must stay 0.
// Phase B: two rows back to back (the second completes while the first is still replaying, in the other bank, so only the
//   "new row done while replaying" check can see it): err must latch high.
// Phase C: reset clears err and the retimer works again.
module row_retimer_tb;
    parameter W = 8;
    parameter H = 6;
    parameter GAP = 2 * W + 12;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    always #20 clk = ~clk;

    reg       ivalid = 1'b0, ibit = 1'b0;
    reg [8:0] icr = 0, icc = 0;
    wire      ovalid, obit, err;
    wire [8:0] ocr, occ;

    row_retimer #(.W(W), .H(H)) dut (.clk(clk), .rst_n(rst_n), .ivalid(ivalid), .ibit(ibit), .icr(icr), .icc(icc),
                                      .ovalid(ovalid), .obit(obit), .ocr(ocr), .occ(occ), .err(err));

    reg img [0:W*H-1];
    integer cyc = 0;
    integer tlast [0:H-1];
    integer errors = 0;
    integer outs = 0;
    integer next_r = 0, next_c = 0;
    reg     check_out = 1'b0;            // phase A: compare the output stream
    integer r, c, k, seed;

    // monitor: samples exactly what the DUT samples at each clock edge
    always @(posedge clk) begin
        cyc = cyc + 1;
        if (ivalid && icc == W - 1) tlast[icr] = cyc;
        if (check_out && ovalid) begin
            outs = outs + 1;
            if (ocr !== next_r || occ !== next_c) begin
                errors = errors + 1; $display("MISMATCH label got (%0d,%0d) expected (%0d,%0d)", ocr, occ, next_r, next_c);
            end
            if (obit !== img[next_r * W + next_c]) begin
                errors = errors + 1; $display("MISMATCH bit at (%0d,%0d) got %b", next_r, next_c, obit);
            end
            if (cyc - tlast[next_r] != 5 + 2 * next_c) begin
                errors = errors + 1; $display("MISMATCH latency at (%0d,%0d): %0d clocks after the last pixel, expected %0d",
                                              next_r, next_c, cyc - tlast[next_r], 5 + 2 * next_c);
            end
            if (next_c == W - 1) begin next_c = 0; next_r = next_r + 1; end else next_c = next_c + 1;
        end
    end

    task send_row;
        input integer row;
        input integer gap;
        integer cc2;
        begin
            for (cc2 = 0; cc2 < W; cc2 = cc2 + 1) begin
                ivalid <= 1'b1; ibit <= img[row * W + cc2]; icr <= row; icc <= cc2;
                @(posedge clk);
            end
            ivalid <= 1'b0;
            repeat (gap) @(posedge clk);
        end
    endtask

    initial begin
        seed = 7;
        for (k = 0; k < W * H; k = k + 1) img[k] = $random(seed);
        for (k = 0; k < H; k = k + 1) tlast[k] = 0;
        repeat (5) @(posedge clk);
        rst_n <= 1'b1;
        repeat (3) @(posedge clk);

        // ---- phase A
        check_out = 1'b1;
        for (r = 0; r < H; r = r + 1) send_row(r, GAP);
        repeat (4 * W) @(posedge clk);
        if (outs != W * H) begin errors = errors + 1; $display("MISMATCH %0d output pixels, expected %0d", outs, W * H); end
        if (err !== 1'b0) begin errors = errors + 1; $display("MISMATCH err high although every row had time to replay"); end
        check_out = 1'b0;

        // ---- phase B: row 0 then row 1 with no gap (different banks, never rewrites the bank being replayed)
        send_row(0, 0);
        send_row(1, 3 * GAP);
        if (err !== 1'b1) begin errors = errors + 1; $display("MISMATCH err not raised when a row completed during a replay"); end

        // ---- phase C: reset clears it, normal operation resumes
        rst_n <= 1'b0; repeat (3) @(posedge clk); rst_n <= 1'b1; repeat (3) @(posedge clk);
        if (err !== 1'b0) begin errors = errors + 1; $display("MISMATCH err not cleared by reset"); end
        send_row(2, GAP);
        send_row(3, GAP);
        if (err !== 1'b0) begin errors = errors + 1; $display("MISMATCH err raised after reset with well spaced rows"); end

        if (errors == 0) $display("RESULT: PASS (outputs=%0d W=%0d H=%0d)", outs, W, H);
        else $display("RESULT: FAIL (%0d errors)", errors);
        $finish;
    end

    initial begin
        #5000000;
        $display("RESULT: FAIL (timeout)");
        $finish;
    end
endmodule
