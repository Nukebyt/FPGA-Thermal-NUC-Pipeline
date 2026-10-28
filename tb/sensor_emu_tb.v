`timescale 1ns/1ps
// sensor_emu_tb.v -- bit-exact test of sensor_emu against its Python twin (scripts/gen_emu_vectors.py).
// Verdict: "RESULT: PASS" / "RESULT: FAIL".
// Latency ledger: otick == tick delayed LAT_TICK = 9 clocks. The k-th output tick of a frame belongs to the k-th input
// tick (same order), which tells us whether it carries a real pixel and which one.
// Checked per real pixel: raw sample (x_out), ground-truth scene (clean_out), ground-truth motion flag (gt_motion).
// Rectangles move between frames, so this also tests the end-of-frame state update and the frame-dependent noise.
// FEED = 1: the scene comes from rtl/scene_buf.v, reloaded before every frame from VEC/scene<f>.hex (the frame store as
// the host would have written it); OBJ = 0 hides the rectangles.
// Overrides: -P sensor_emu_tb.W= .H= .T= .PRESET= .NOISE= .GAPMAX= .FEED= .OBJ= .VEC="dir" .ROM="file"; include dir with -I.
module sensor_emu_tb;
    parameter W = 48;
    parameter H = 36;
    parameter T = 8;
    parameter PRESET = 1;
    parameter NOISE = 1;
    parameter FEED = 0;
    parameter OBJ = 1;
    parameter GAPMAX = 3;
    parameter VEC = "work/vec_emu";
    parameter ROM = "work/vec_emu/rom.hex";
    localparam N = W * H;
    localparam ROWS = H + 2;
    localparam LAT_TICK = 9;
    localparam AW = 17;
    `include "rectp.vh"

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    always #20 clk = ~clk;

    reg [15:0] rawm [0:T*N-1];
    reg [15:0] clm  [0:T*N-1];
    reg        motm [0:T*N-1];
    reg        isreal [0:(W+1)*ROWS-1];
    integer    idx_of [0:(W+1)*ROWS-1];

    reg        tick = 1'b0, first = 1'b0;
    wire       otick, ofirst, gt_motion;
    wire [13:0] x_out;
    wire [14:0] clean_out;

    wire [AW-1:0] sc_addr;
    wire [7:0]    sc_q;
    wire          sc_row_done;
    wire [31:0]   rows_read;
    scene_buf #(.NW((W * H + 3) / 4)) sb (
        .clk(clk), .rst_n(rst_n), .saddr(sc_addr[16:0]), .sq(sc_q), .row_done(sc_row_done), .rows_read(rows_read),
        .hw_we(1'b0), .hw_addr(15'd0), .hw_data(32'd0));

    sensor_emu #(.W(W), .H(H), .AW(AW), .INIT_FILE(ROM), .RECTP(RECTP_TB), .FEED(FEED)) dut (
        .clk(clk), .rst_n(rst_n), .tick(tick), .first(first), .preset(PRESET[1:0]), .noise_en(NOISE != 0), .obj_en(OBJ != 0),
        .scene_addr(sc_addr), .scene_q(sc_q), .row_done(sc_row_done),
        .otick(otick), .ofirst(ofirst), .x_out(x_out), .clean_out(clean_out), .gt_motion(gt_motion));

    // FEED: the frame store holds frame f's scene while frame f is scanned (loaded as if the host had written it)
    reg [8*200-1:0] fname;
    task load_scene;
        input integer f;
        begin
            if (FEED != 0) begin
                $sformat(fname, "%0s/scene%0d.hex", VEC, f);
                $readmemh(fname, sb.buf_i.mem);
            end
        end
    endtask

    integer errors = 0, seed = 99;
    integer fr = 0, sr = 0, sc = 0, wait_cnt = 0, phase = 0;
    integer tin = 0, tout = 0, fo = 0, checked = 0;
    reg [15:0] tpipe = 16'd0;
    integer k, p;

    initial begin
        $readmemh({VEC, "/raw.hex"}, rawm);
        $readmemh({VEC, "/clean.hex"}, clm);
        $readmemh({VEC, "/mot.hex"}, motm);
        for (k = 0; k < (W+1)*ROWS; k = k + 1) begin
            isreal[k] = ((k % (W+1)) < W) && ((k / (W+1)) < H);
            idx_of[k] = (k / (W+1)) * W + (k % (W+1));
        end
        load_scene(0);
        #200 rst_n = 1'b1;
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            tick <= 1'b0; first <= 1'b0; tpipe <= 16'd0;
        end else begin
            tpipe <= {tpipe[14:0], tick};
            if (otick !== tpipe[LAT_TICK-1]) begin
                errors = errors + 1;
                if (errors < 10) $display("MISMATCH latency @%0t otick=%b exp=%b", $time, otick, tpipe[LAT_TICK-1]);
            end
            if (otick) begin
                if (ofirst) tout = 0;
                if (isreal[tout]) begin
                    p = idx_of[tout];
                    if (x_out !== rawm[fo*N + p][13:0]) begin
                        errors = errors + 1;
                        if (errors < 10) $display("MISMATCH raw frame %0d idx %0d got %h exp %h", fo, p, x_out, rawm[fo*N + p][13:0]);
                    end
                    if (clean_out !== clm[fo*N + p][14:0]) begin
                        errors = errors + 1;
                        if (errors < 10) $display("MISMATCH clean frame %0d idx %0d got %h exp %h", fo, p, clean_out, clm[fo*N + p][14:0]);
                    end
                    if (gt_motion !== motm[fo*N + p]) begin
                        errors = errors + 1;
                        if (errors < 10) $display("MISMATCH motion frame %0d idx %0d got %b exp %b", fo, p, gt_motion, motm[fo*N + p]);
                    end
                    checked = checked + 1;
                end
                tout = tout + 1;
                if (tout == (W+1)*ROWS) fo = fo + 1;
            end

            tick <= 1'b0; first <= 1'b0;
            if (wait_cnt > 0) wait_cnt = wait_cnt - 1;
            else if (phase == 0) begin sr = 0; sc = 0; phase = 1; end
            if (wait_cnt == 0 && phase == 1) begin
                tick <= 1'b1;
                first <= (sr == 0) && (sc == 0);
                if (sc == W) begin
                    sc = 0; sr = sr + 1;
                    wait_cnt = 30 + (($random(seed) & 32'h7fffffff) % 40);
                end else begin
                    sc = sc + 1;
                    wait_cnt = 1 + (($random(seed) & 32'h7fffffff) % (GAPMAX - 1));
                end
                if (sr == ROWS) begin phase = 2; wait_cnt = 100; end
            end
            if (wait_cnt == 0 && phase == 2) begin
                fr = fr + 1;
                if (FEED != 0 && rows_read !== fr * H) begin
                    errors = errors + 1;
                    $display("MISMATCH rows_read %0d after frame %0d expected %0d", rows_read, fr, fr * H);
                end
                if (fr < T) load_scene(fr);
                phase = (fr == T) ? 3 : 0;
                wait_cnt = 5;
            end
        end
    end

    initial begin
        wait (phase == 3);
        #(40 * 200);
        if (checked != T * N) begin
            errors = errors + 1;
            $display("FAIL: checked %0d pixels, expected %0d", checked, T * N);
        end
        if (errors == 0) $display("RESULT: PASS (frames=%0d pixels=%0d preset=%0d noise=%0d)", T, checked, PRESET, NOISE);
        else             $display("RESULT: FAIL (errors=%0d)", errors);
        $finish;
    end

    initial begin
        #(40 * 80000000);
        $display("RESULT: FAIL (timeout)");
        $finish;
    end
endmodule
