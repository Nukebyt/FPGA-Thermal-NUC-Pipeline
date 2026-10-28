`timescale 1ns/1ps
// tone_win.v -- automatic display window (thermal AGC) with a one-frame delay, and the 14 -> 8 bit mapping.
//
//   per frame: min / max of the pixels that are not excluded (rail pixels: v == 0 or 16383, i.e. dead/hot)
//   next frame window: lo = min,  sh = max(0, bitlen(max - min) - 8)       so (max-min) >> sh <= 255
//   out8 = clamp((v - lo) >> sh, 0, 255)          (v < lo -> 0)
//   frame 0 uses lo = 0, sh = 6. tone_auto = 0 uses the manual lo / sh instead.
// Twin: model/display_model.py ToneWindow. Combinational mapping `out8` is for the pixel on `v` this cycle;
// the window registers change only at `frame_start` (y_first), long before the first valid pixel of the frame.
module tone_win #(
    parameter W = 320,
    parameter H = 240
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        frame_start,     // pulse at the start of a frame (before any valid pixel)
    input  wire        valid,
    input  wire [8:0]  cr,
    input  wire [8:0]  cc,
    input  wire [13:0] v,
    input  wire        excl,            // exclude this pixel from min/max
    input  wire        auto,
    input  wire [13:0] man_lo,
    input  wire [3:0]  man_sh,
    output wire [7:0]  out8
);
    reg [13:0] mn, mx;
    reg [13:0] lo_a;
    reg [3:0]  sh_a;
    reg [13:0] lo_n;
    reg [3:0]  sh_n;
    reg        last_q;

    wire [13:0] range = (mx >= mn) ? (mx - mn) : 14'd0;
    reg  [3:0]  sh_f;
    integer     b;
    always @(*) begin
        // smallest s with (range >> s) <= 255
        sh_f = 4'd0;
        for (b = 1; b <= 6; b = b + 1) begin                 // ascending: the LARGEST b that still overflows wins
            if ((range >> (b - 1)) > 14'd255) sh_f = b[3:0];
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            mn <= 14'h3FFF; mx <= 14'd0; lo_a <= 14'd0; sh_a <= 4'd6; lo_n <= 14'd0; sh_n <= 4'd6; last_q <= 1'b0;
        end else begin
            last_q <= valid && (cr == H - 1) && (cc == W - 1);
            if (frame_start) begin
                mn <= 14'h3FFF; mx <= 14'd0;
                lo_a <= auto ? lo_n : man_lo;
                sh_a <= auto ? sh_n : man_sh;
            end else if (valid && !excl) begin
                if (v < mn) mn <= v;
                if (v > mx) mx <= v;
            end
            if (last_q) begin lo_n <= mn; sh_n <= sh_f; end
        end
    end

    wire signed [15:0] d = $signed({2'b00, v}) - $signed({2'b00, lo_a});
    wire [13:0] sft = d[15] ? 14'd0 : (d[13:0] >> sh_a);
    assign out8 = (sft > 14'd255) ? 8'd255 : sft[7:0];
endmodule
