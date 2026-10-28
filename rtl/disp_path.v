`timescale 1ns/1ps
// disp_path.v -- NUC output stream -> VGA 640x480 (each source pixel shown 2x2), views, palette, box overlay.
//
// Write side: corrected and raw pixels are tone-mapped to 8 bit (tone_win, window from the previous frame) and stored in
// a 2-bank row buffer {bank = row[0], column}. The row buffer is read by the VGA scan: VGA line y shows source row y>>1
// from bank (y>>1)&1, VGA column x shows source column x>>1.
// Timing contract (tick_gen LEAD_LINES = 4): source row r is written during VGA line 2r-2 and shown on lines 2r, 2r+1;
// the same bank is rewritten for row r+2 starting at line 2r+2. Hence one bank pair is enough.
//
// Views: 0 corrected, 1 raw, 2 split (VGA x < 320: raw, else corrected), 3 corrected.
// Palette: gray, or "iron" (see model/display_model.py, the twin). Overlay: green outline of the 16 published boxes
// (boxes belong to the previous frame: one-frame lag, documented in docs/design.md).
//
// Latency VGA timing in -> out: LAT_DISP = 3 clocks (hs, vs, de are delayed by the same amount).
module disp_path #(
    parameter W = 320,
    parameter H = 240
) (
    input  wire        clk,
    input  wire        rst_n,
    // NUC output stream
    input  wire        y_first,
    input  wire        y_valid,
    input  wire [8:0]  y_cr,
    input  wire [8:0]  y_cc,
    input  wire [13:0] y_val,
    input  wire [13:0] x_val,
    // VGA timing (from vga_timing)
    input  wire [10:0] vx,
    input  wire [10:0] vy,
    input  wire        vde,
    input  wire        vhs_n,
    input  wire        vvs_n,
    // controls
    input  wire [1:0]  view,
    input  wire        iron,
    input  wire        overlay_en,
    input  wire        tone_auto,
    input  wire [13:0] tone_lo,
    input  wire [3:0]  tone_sh,
    // published boxes
    input  wire [4:0]  box_cnt,
    input  wire [16*53-1:0] box_rec,
    // VGA out
    output reg  [7:0]  vga_r,
    output reg  [7:0]  vga_g,
    output reg  [7:0]  vga_b,
    output reg         vga_hs_n,
    output reg         vga_vs_n,
    output reg         vga_de,
    // tone-mapped write-side stream for frame_cap (one pixel per wv, raster order)
    output wire        cap_v,
    output wire        cap_first,
    output wire [7:0]  cap_c8,
    output wire [7:0]  cap_r8
);
    // ---------------- tone mapping (two windows) and row-buffer write
    wire excl = (x_val == 14'd0) || (x_val == 14'h3FFF);
    wire [7:0] c8, r8;
    tone_win #(.W(W), .H(H)) twc (.clk(clk), .rst_n(rst_n), .frame_start(y_first), .valid(y_valid), .cr(y_cr), .cc(y_cc),
        .v(y_val), .excl(excl), .auto(tone_auto), .man_lo(tone_lo), .man_sh(tone_sh), .out8(c8));
    tone_win #(.W(W), .H(H)) twr (.clk(clk), .rst_n(rst_n), .frame_start(y_first), .valid(y_valid), .cr(y_cr), .cc(y_cc),
        .v(x_val), .excl(excl), .auto(tone_auto), .man_lo(tone_lo), .man_sh(tone_sh), .out8(r8));

    reg        wv, w00;
    reg [9:0]  wa;
    reg [15:0] wd;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin wv <= 1'b0; w00 <= 1'b0; wa <= 10'd0; wd <= 16'd0; end
        else begin
            wv <= y_valid; w00 <= y_valid && (y_cr == 9'd0) && (y_cc == 9'd0);
            wa <= {y_cr[0], y_cc}; wd <= {c8, r8};
        end
    end
    assign cap_v = wv; assign cap_first = w00; assign cap_c8 = wd[15:8]; assign cap_r8 = wd[7:0];

    // ---------------- read side
    wire [15:0] rq;
    ram_sdp #(.DW(16), .AW(10), .DEPTH(1024)) rows (
        .clk(clk), .we(wv), .waddr(wa), .wdata(wd), .raddr({vy[1], vx[9:1]}), .rdata(rq));

    // P0 -> P1 : delay the controls by one clock to match the RAM read
    reg [9:0] sx1;
    reg [8:0] row1;
    reg [10:0] vx1;
    reg de1, hs1, vs1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin sx1 <= 10'd0; row1 <= 9'd0; vx1 <= 11'd0; de1 <= 1'b0; hs1 <= 1'b1; vs1 <= 1'b1; end
        else begin sx1 <= {1'b0, vx[9:1]}; row1 <= vy[9:1]; vx1 <= vx; de1 <= vde; hs1 <= vhs_n; vs1 <= vvs_n; end
    end

    // pixel value after the view mux
    wire [7:0] cv = rq[15:8];
    wire [7:0] rv = rq[7:0];
    wire use_raw = (view == 2'd1) || ((view == 2'd2) && (vx1 < 11'd320));
    wire [7:0] v8 = use_raw ? rv : cv;

    // iron palette
    reg [7:0] ir, ig, ib;
    always @(*) begin
        ir = (v8 < 8'd128) ? {v8[6:0], 1'b0} : 8'd255;
        ig = (v8 < 8'd128) ? 8'd0 : {v8[6:0], 1'b0};
        if (v8 < 8'd64)        ib = {v8[5:0], 2'b00};
        else if (v8 < 8'd128)  ib = 8'd255 - {v8[5:0], 2'b00};
        else if (v8 < 8'd192)  ib = 8'd0;
        else                   ib = {v8[5:0], 2'b00};
    end

    // box outline hit (source coordinates)
    reg hit;
    integer k;
    reg [8:0] bxmin, bymin, bxmax, bymax;
    always @(*) begin
        hit = 1'b0;
        for (k = 0; k < 16; k = k + 1) begin
            bxmin = box_rec[k*53 +: 9];
            bymin = box_rec[k*53 + 9 +: 9];
            bxmax = box_rec[k*53 + 18 +: 9];
            bymax = box_rec[k*53 + 27 +: 9];
            if (k < box_cnt) begin
                if ((row1 >= bymin) && (row1 <= bymax) && ((sx1[8:0] == bxmin) || (sx1[8:0] == bxmax))) hit = 1'b1;
                if ((sx1[8:0] >= bxmin) && (sx1[8:0] <= bxmax) && ((row1 == bymin) || (row1 == bymax))) hit = 1'b1;
            end
        end
    end

    reg [7:0] r2, g2, b2;
    reg       hit2, de2, hs2, vs2;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin r2 <= 8'd0; g2 <= 8'd0; b2 <= 8'd0; hit2 <= 1'b0; de2 <= 1'b0; hs2 <= 1'b1; vs2 <= 1'b1; end
        else begin
            r2 <= iron ? ir : v8; g2 <= iron ? ig : v8; b2 <= iron ? ib : v8;
            hit2 <= hit && overlay_en; de2 <= de1; hs2 <= hs1; vs2 <= vs1;
        end
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin vga_r <= 8'd0; vga_g <= 8'd0; vga_b <= 8'd0; vga_hs_n <= 1'b1; vga_vs_n <= 1'b1; vga_de <= 1'b0; end
        else begin
            vga_r <= !de2 ? 8'd0 : hit2 ? 8'd0   : r2;
            vga_g <= !de2 ? 8'd0 : hit2 ? 8'd255 : g2;
            vga_b <= !de2 ? 8'd0 : hit2 ? 8'd0   : b2;
            vga_hs_n <= hs2; vga_vs_n <= vs2; vga_de <= de2;
        end
    end
endmodule
