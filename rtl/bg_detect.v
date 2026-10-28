`timescale 1ns/1ps
// bg_detect.v -- running-average background model + threshold. Bit-exact twin of pipeline_int.detector_frame().
//
//   n   = frames seen since reset (saturates at 255)
//   sh  = min(KB, ceil(log2(n+1)))            warm-start: the first frames average, then alpha = 2^-KB
//   B   : U14.BF (BF=2) stored 16 bits
//   diff = |{y,00} - B|     mask = diff > {t_mask,00}     B += round((y<<2 - B) >> sh)    (blind update)
//   frame 0 (n==0): B := y<<2, mask = 0, no activity.
//   act_sum = sum(diff >> 2) over the frame;  gain_en_next = ((act_sum>>16) > act_thr) once n > ACT_WARM, else 1.
//
// Q formats: y U14.0, B U14.2, diff U16.2 -> compared in Q.2, act_sum U32.0 (counts).
//
// Latency (clocks): 3. Input stream = nuc_core output bus (tick/first/valid/coords/y), output bus is the same
// stream delayed by 3 with the mask attached. Hazard: B[addr] is read at the pixel and written 2 clocks later;
// the next read of that address is one frame later.
module bg_detect #(
    parameter W  = 320,
    parameter H  = 240,
    parameter AW = 17,
    parameter KB = 7,
    parameter ACT_WARM = 4
) (
    input  wire        clk,
    input  wire        rst_n,
    // input stream
    input  wire        itick,
    input  wire        ifirst,
    input  wire        ivalid,
    input  wire [8:0]  icr,
    input  wire [8:0]  icc,
    input  wire [13:0] iy,
    // controls (sampled at the first pixel of a frame)
    input  wire [13:0] t_mask,         // counts
    input  wire [7:0]  det_warm,       // frames before the mask is reported
    input  wire [15:0] act_thr,        // gain-learning gate threshold on (act_sum >> 16)
    input  wire        det_reset,      // 1-clock pulse: n := 0, activity gate open (FRAME_RESET)
    // output stream
    output reg         otick,
    output reg         ofirst,
    output reg         ovalid,
    output reg  [8:0]  ocr,
    output reg  [8:0]  occ,
    output reg         omask,          // gated by det_valid
    // frame results
    output reg         gain_en_next,   // for nuc_core.gain_en_in of the NEXT frame
    output reg         fdone,          // pulse when the frame's last pixel has been written back
    output reg  [31:0] fact_sum,
    output reg  [7:0]  fn_after,       // n after this frame
    output reg         fdet_valid      // detection was reported (n_after > det_warm) for the finished frame
);
    localparam DEPTH = W * H;

    // ---- per-frame controls ----
    reg [7:0]  n;
    reg [13:0] t_a;
    reg [15:0] thr_a;
    reg [2:0]  sh_a;
    reg        n0_a, dv_a;
    wire       is_first = itick & ifirst;

    function [2:0] sh_of;
        input [7:0] nn;
        begin
            if (nn == 8'd0)       sh_of = 3'd0;
            else if (nn == 8'd1)  sh_of = 3'd1;
            else if (nn < 8'd4)   sh_of = 3'd2;
            else if (nn < 8'd8)   sh_of = 3'd3;
            else if (nn < 8'd16)  sh_of = 3'd4;
            else if (nn < 8'd32)  sh_of = 3'd5;
            else if (nn < 8'd64)  sh_of = 3'd6;
            else                  sh_of = 3'd7;
        end
    endfunction
    wire [2:0] sh_cap = (sh_of(n) > KB) ? KB[2:0] : sh_of(n);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            t_a <= 14'd400; thr_a <= 16'd64; sh_a <= 3'd0; n0_a <= 1'b1; dv_a <= 1'b0;
        end else if (is_first) begin
            t_a <= t_mask; thr_a <= act_thr; sh_a <= sh_cap; n0_a <= (n == 8'd0); dv_a <= (n >= det_warm);
        end
    end

    // ---- stage D0: RAM read ----
    reg [AW-1:0] ridx;
    wire         is_first_px = ivalid && (icr == 9'd0) && (icc == 9'd0);
    wire [AW-1:0] cur_idx = is_first_px ? {AW{1'b0}} : ridx;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) ridx <= {AW{1'b0}};
        else if (ivalid) ridx <= cur_idx + 1'b1;
    end

    wire [15:0]  bq;
    reg          wr_en;
    reg [AW-1:0] wr_addr;
    reg [15:0]   wr_data;
    ram_sdp #(.DW(16), .AW(AW), .DEPTH(DEPTH)) bram (
        .clk(clk), .we(wr_en), .waddr(wr_addr), .wdata(wr_data), .raddr(cur_idx), .rdata(bq));

    // ---- D1: delta ----
    reg          tk1, fs1, v1;
    reg [8:0]    cr1, cc1;
    reg [AW-1:0] idx1;
    reg [15:0]   yb1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tk1 <= 1'b0; fs1 <= 1'b0; v1 <= 1'b0; cr1 <= 9'd0; cc1 <= 9'd0; idx1 <= {AW{1'b0}}; yb1 <= 16'd0;
        end else begin
            tk1 <= itick; fs1 <= ifirst; v1 <= ivalid; cr1 <= icr; cc1 <= icc; idx1 <= cur_idx; yb1 <= {iy, 2'b00};
        end
    end
    wire signed [17:0] delta1 = $signed({2'b00, yb1}) - $signed({2'b00, bq});

    // ---- D2: diff, mask, new B ----
    reg          tk2, fs2, v2;
    reg [8:0]    cr2, cc2;
    reg [AW-1:0] idx2;
    reg signed [17:0] delta2;
    reg [15:0]   yb2, bq2;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tk2 <= 1'b0; fs2 <= 1'b0; v2 <= 1'b0; cr2 <= 9'd0; cc2 <= 9'd0; idx2 <= {AW{1'b0}};
            delta2 <= 18'sd0; yb2 <= 16'd0; bq2 <= 16'd0;
        end else begin
            tk2 <= tk1; fs2 <= fs1; v2 <= v1; cr2 <= cr1; cc2 <= cc1; idx2 <= idx1;
            delta2 <= delta1; yb2 <= yb1; bq2 <= bq;
        end
    end
    wire [17:0] absd = delta2[17] ? (~delta2 + 18'd1) : delta2;
    wire        mask_w = ~n0_a && (absd > {2'b00, t_a, 2'b00});
    // rounded shift of delta by sh_a (0..7)
    wire signed [17:0] rnd = (sh_a == 3'd0) ? 18'sd0 : (18'sd1 <<< (sh_a - 3'd1));
    wire signed [17:0] dsum = delta2 + rnd;
    wire signed [17:0] dsh  = dsum >>> sh_a;
    wire signed [18:0] bnew = $signed({3'b000, bq2}) + $signed({dsh[17], dsh});
    wire [15:0] bnew16 = bnew[15:0];

    reg [31:0] acc;
    reg        last2;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            otick <= 1'b0; ofirst <= 1'b0; ovalid <= 1'b0; ocr <= 9'd0; occ <= 9'd0; omask <= 1'b0;
            wr_en <= 1'b0; wr_addr <= {AW{1'b0}}; wr_data <= 16'd0; acc <= 32'd0; last2 <= 1'b0;
        end else begin
            otick <= tk2; ofirst <= fs2; ovalid <= v2; ocr <= cr2; occ <= cc2;
            omask <= mask_w & dv_a;                 // n counts frames BEFORE this one => n+1 > warm  <=> n >= warm
            wr_en <= v2; wr_addr <= idx2; wr_data <= n0_a ? yb2 : bnew16;     // frame 0 loads y explicitly (B is undefined)
            last2 <= v2 && (cr2 == H - 1) && (cc2 == W - 1);
            if (tk2 && fs2) acc <= 32'd0;
            if (v2 && !n0_a) acc <= ((tk2 && fs2) ? 32'd0 : acc) + {16'd0, absd[17:2]};
        end
    end

    // ---- frame end ----
    reg last3;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            n <= 8'd0; gain_en_next <= 1'b1; fdone <= 1'b0; fact_sum <= 32'd0; fn_after <= 8'd0;
            fdet_valid <= 1'b0; last3 <= 1'b0;
        end else begin
            fdone <= 1'b0;
            last3 <= last2;
            if (det_reset) begin
                n <= 8'd0; gain_en_next <= 1'b1;
            end else if (last3) begin
                n <= (n == 8'd255) ? 8'd255 : n + 8'd1;
                fn_after <= (n == 8'd255) ? 8'd255 : n + 8'd1;
                fdet_valid <= dv_a;
                fact_sum <= acc;
                gain_en_next <= (((n == 8'd255) ? 8'd255 : n + 8'd1) > ACT_WARM) ? ((acc[31:16] > thr_a) ? 1'b1 : 1'b0) : 1'b1;
                fdone <= 1'b1;
            end
        end
    end
endmodule
